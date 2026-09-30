"""veritx_dse.product.service — the product state machine over canonical views.

Rationale: docs/decisions/modules/product.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.compile_result_view import (
    build_compile_result,
    compile_result_is_current,
)
from veritx_dse.application.errors import ControlPlaneError, ErrorCode, intent_error
from veritx_dse.application.errors import map_lowering_error as _map_lowering_error
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.application.views import (
    artifact_chain_view, compilation_view, design_view, lowering_view,
    staged_topology_view, topology_view,
)
from veritx_dse.core.errors import (
    InvalidInput as _LoweringInvalid,
    MappingInvalid as _LoweringMappingInvalid,
    UnsupportedSchedule as _LoweringSchedule,
    UnsupportedSemantics as _LoweringSemantics,
)
from veritx_dse.core.paths import REPO
from veritx_dse.core.run_bundle import (
    RunBundleError, finalize_run_bundle, read_verified_file,
    verify_run_bundle,
)
from veritx_dse.core.runs import new_run_id
from veritx_dse.product.jobs import TERMINAL_STATES, JobManager
from veritx_dse.product.store import (
    ProductStore, ProductStoreError, _new_id, utcnow,
)
from veritx_dse.product.workload_registry import (
    BUILTIN_WORKLOADS,
    WorkloadRegistryError,
    load_registry,
    materialize,
    resolve as resolve_workload,
)

_WORKLOAD_TEMPLATES = BUILTIN_WORKLOADS

_RUN_STATUS = {
    "EVALUATED": "EVALUATED",
    "PARTIAL": "PARTIAL",
    "BACKEND_UNAVAILABLE": "BACKEND_UNAVAILABLE",
    "UNSUPPORTED": "UNSUPPORTED",
    "FAILED": "FAILED",
    "INVALID": "INVALID",
}

_TRUST_READ_FILE_CAP = 4 * 1024 * 1024
_TRUST_READ_TOTAL_CAP = 32 * 1024 * 1024

class ProductServiceError(ControlPlaneError):
    """A product resource or product operation failed."""

class BackendUnavailable(ControlPlaneError):
    def __init__(self, message: str) -> None:
        super().__init__(ErrorCode.EXECUTION_FAILED, message,
                         operation="backend")

@dataclass(frozen=True)
class ProductConfig:
    projects_root: Path
    booksim_bin: Path | None = None
    astra_bin: Path | None = None
    ramulator_vendor_dir: Path | None = None
    ramulator_python: str | None = None
    ramulator_geometry_profile: str = "CERTIFIED_RAMULATOR_HBM3_V1"
    network_clock_hz: int = 1_000_000_000
    timeout_s: int = 600
    repo_root: Path = REPO

_COMPUTED_IDENTITY_FIELDS = ("design_hash", "guardrail_hash")

def parse_request_doc(document: Any):
    """Parse a canonical product request document (v2 or v3)."""
    from veritx_dse.model.compile_model import CompileRequest, CompileRequestV3
    if not isinstance(document, dict):
        raise intent_error("request must be a JSON object")
    doc = {k: v for k, v in document.items()
           if k not in _COMPUTED_IDENTITY_FIELDS}
    schema_version = doc.get("schema_version")
    try:
        if schema_version == 4:
            from veritx_dse.model.compile_request_v4 import CompileRequestV4
            return CompileRequestV4.from_dict(doc)
        if schema_version == 3:
            return CompileRequestV3.from_dict(doc)
        if schema_version == 2:
            return CompileRequest.from_dict(doc)
    except ValueError as exc:
        raise intent_error(f"request document is invalid: {exc}") from exc
    raise intent_error(
        f"unsupported request schema_version {schema_version!r} "
        f"(expected 2, 3 or 4)")

def canonical_request_doc(request: Any) -> dict[str, Any]:
    doc = request.to_dict()
    for field in _COMPUTED_IDENTITY_FIELDS:
        doc.pop(field, None)
    return doc

def _view_hash(value: str) -> str:
    """Self-describing identity, matching DesignView/CompilationView."""
    return value if value.startswith("sha256:") else "sha256:" + value

class ProductService:
    def __init__(self, config: ProductConfig,
                 store: ProductStore | None = None,
                 registry: Any | None = None) -> None:
        self.config = config
        self.store = store or ProductStore(config.projects_root)
        self.jobs = JobManager(self.store)
        if registry is not None:
            self._registry = registry
        else:
            from veritx_dse.backend.registry import (
                default_backend_registry,
            )
            self._registry = default_backend_registry(
                booksim_bin=config.booksim_bin,
                astra_bin=config.astra_bin,
                repo_root=config.repo_root,
                ramulator_vendor_dir=config.ramulator_vendor_dir,
                ramulator_python=config.ramulator_python,
                ramulator_geometry_profile=config.ramulator_geometry_profile)
        self._assessment_cache: dict[str, dict[str, Any]] = {}
        for project in self.store.list_projects():
            self.jobs.recover_interrupted(project["project_id"])

    @staticmethod
    def _network_support_row(context: Any, registry: Any) -> Any:
        """The federation's adjudicated NETWORK_COMPLETION row.

        The single planner-truth accessor shared by capability
        assessment and preflight: Compilation → context → plan row.
        No caller re-derives BookSim representability beside it.
        """
        from veritx_dse.application.evaluation_plan import EvaluationPlanner
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        return EvaluationPlanner().plan(
            context, (EvaluationQuestion.NETWORK_COMPLETION,),
            registry).analyses[0]

    def _assess_compilation(self, request: Any,
                            compilation: Any) -> dict[str, Any]:
        """Assess whether a request can actually be SIMULATED.

Rationale: docs/decisions/modules/product.md
        """
        from veritx_dse.application.evaluation_context import (
            EvaluationContextError, build_evaluation_context,
        )
        from veritx_dse.backend.adapter import SupportLevel
        if compilation.status != "COMPILED":
            return {"support": SupportLevel.UNSUPPORTED.value,
                    "readiness": "BLOCKED",
                    "domain": "compile",
                    "reason": compilation.error
                    or "compilation was not successful"}
        try:
            context = build_evaluation_context(compilation)
        except EvaluationContextError as exc:
            return {"support": SupportLevel.UNSUPPORTED.value,
                    "readiness": "BLOCKED",
                    "domain": "compile",
                    "reason": str(exc)}
        except (_LoweringInvalid, _LoweringSemantics, _LoweringSchedule,
                _LoweringMappingInvalid) as exc:
            return {"support": SupportLevel.UNSUPPORTED.value,
                    "readiness": "BLOCKED",
                    "domain": "intent_lowering",
                    "reason": f"{type(exc).__name__}: {exc}"}
        row = self._network_support_row(context, self._registry)
        if row.support is SupportLevel.UNSUPPORTED:
            return {"support": SupportLevel.UNSUPPORTED.value,
                    "readiness": "BLOCKED",
                    "domain": "backend",
                    "reason": row.reason
                    or "no registered backend represents this workload"}
        return {"support": row.support.value,
                "readiness": row.readiness.value,
                "domain": None, "reason": row.reason}

    def _assess_request(self, request: Any) -> dict[str, Any]:
        key = request.design_hash()
        cached = self._assessment_cache.get(key)
        if cached is not None:
            return cached
        result = self._assess_compilation(
            request, FabricCompiler().compile(request))
        self._assessment_cache[key] = result
        return result

    def _assessment_for_revision(self, revision: dict[str, Any]
                                 ) -> dict[str, Any]:
        """Stored assessment when present, else recompute (cached).

        Stored assessments predate the support/readiness split only in
        databases written before it: a legacy `supported`-boolean record
        is recomputed rather than reinterpreted, so no caller ever
        reads readiness out of a representability verdict.
        """
        stored = revision.get("simulation")
        if isinstance(stored, dict) and "support" in stored:
            return stored
        return self._assess_request(parse_request_doc(revision["request"]))

    def workload_catalog(self) -> dict[str, Any]:
        workloads = []
        try:
            entries = load_registry(self.config.repo_root)
        except WorkloadRegistryError as exc:
            raise ProductServiceError(
                ErrorCode.INVALID_INTENT, f"workload registry: {exc}",
                operation="workload_catalog") from exc
        for record in entries:
            path = self.config.repo_root / record.path
            if not path.is_file():
                continue
            try:
                document = materialize(record, self.config.repo_root)
            except WorkloadRegistryError as exc:
                raise ProductServiceError(
                    ErrorCode.INVALID_INTENT, f"workload registry: {exc}",
                    operation="workload_catalog") from exc
            request = parse_request_doc(document)
            wl = request.workload
            entry: dict[str, Any] = {
                "workload_id": record.workload_id,
                "display_name": record.display_name,
                "description": record.description,
                "source": record.path,
                "content_digest": request.design_hash(),
                "model_family": getattr(wl.model_family, "value",
                                        wl.model_family),
                "model_name": getattr(wl, "model_name", None),
                "serving_mode": getattr(wl.serving_mode, "value",
                                        wl.serving_mode),
                "parallelism": {"tp": wl.tp, "pp": wl.pp,
                                "ep": wl.ep, "dp": wl.dp},
                "collectives": [self._collective_view(c)
                                for c in getattr(wl, "collectives", ())],
                "agents": [{"kind": getattr(a.kind, "value", a.kind),
                            "count": a.count} for a in request.agents],
                "noc": self._noc_view(request),
                "request": canonical_request_doc(request),
            }
            assessment = self._assess_request(request)
            entry["evaluation_support"] = assessment["support"]
            entry["evaluation_readiness"] = assessment["readiness"]
            entry["evaluation_supported"] = (
                assessment["support"] != "UNSUPPORTED")
            entry["evaluation_note"] = assessment["reason"]
            entry["evaluation_domain"] = assessment["domain"]
            workloads.append(entry)
        return {"contract_version": 1, "workloads": workloads}

    def workload_lowering(self, workload_id: str) -> dict[str, Any]:
        """The canonical lowering view for one catalog workload: workload
        -> operations -> collectives -> logical messages (§29's typed
        projection over LogicalMessageArtifactV2).

Rationale: docs/decisions/modules/product.md
        """
        template = resolve_workload(self.config.repo_root, workload_id)
        if template is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such workload: {workload_id}",
                operation="workload_lowering", resource_id=workload_id)
        path = self.config.repo_root / template.path
        if not path.is_file():
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                f"workload template document is missing: {template.path}",
                operation="workload_lowering", resource_id=workload_id)
        try:
            document = materialize(template, self.config.repo_root)
        except WorkloadRegistryError as exc:
            raise ProductServiceError(
                ErrorCode.INVALID_INTENT, f"workload registry: {exc}",
                operation="workload_lowering", resource_id=workload_id) from exc
        request = parse_request_doc(document)
        view = lowering_view(request)
        view["workload_id"] = workload_id
        return view

    def fabric_presets(self) -> dict[str, Any]:
        from veritx_dse.application.presets import preset_catalog
        return {"contract_version": 1, "presets": list(preset_catalog())}

    _SERVING_CONFIG_DIR = "third_party/llmservingsim/configs/cluster"
    _SERVING_TRACE_DIR = "third_party/llmservingsim/workloads"

    _SERVING_PROFILE_FIELDS = frozenset({
        "max_num_seqs", "max_num_batched_tokens", "npu_mem_gb",
        "cpu_mem_gb", "block_size", "fp_bits", "routing_policy",
        "collective_kind", "collective_bytes_per_rank",
        "compute_base_ns", "compute_per_token_ns", "ep_size",
        "ep_dispatch_kind", "ep_combine_kind",
        "ep_dispatch_bytes_per_rank", "ep_combine_bytes_per_rank",
        "expert_compute_base_ns", "expert_compute_per_token_ns",
    })
    _SERVING_PROFILE_NAMES = frozenset({
        "routing_policy", "collective_kind", "ep_dispatch_kind",
        "ep_combine_kind",
    })

    def _serving_profile_overrides(
            self, raw: Any) -> dict[str, Any] | None:
        """Validate declared service-profile overrides at submit time.

        The profile is a *declared* semantics input, so a bad value must be
        a typed refusal before the job starts, not a FAILED job. Keys are
        checked against the certified field set; the canonical constructor
        still validates the resulting profile.
        """
        if raw is None:
            return None
        if not isinstance(raw, dict):
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                "profile_overrides must be an object",
                operation="submit_serving")
        unknown = sorted(set(raw) - self._SERVING_PROFILE_FIELDS)
        if unknown:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                ("unsupported profile override field(s): "
                 + ", ".join(unknown)
                 + "; certified fields are "
                 + ", ".join(sorted(self._SERVING_PROFILE_FIELDS))),
                operation="submit_serving")
        for key, value in sorted(raw.items()):
            if key in self._SERVING_PROFILE_NAMES:
                if not isinstance(value, str) or not value:
                    raise ProductServiceError(
                        ErrorCode.UNSUPPORTED_SEMANTICS,
                        f"profile override {key} must be a non-empty name",
                        operation="submit_serving")
                continue
            if isinstance(value, bool) or not isinstance(value, int) \
                    or value <= 0:
                raise ProductServiceError(
                    ErrorCode.UNSUPPORTED_SEMANTICS,
                    f"profile override {key} must be a positive integer",
                    operation="submit_serving")
            if key == "ep_size" and value < 1:
                raise ProductServiceError(
                    ErrorCode.UNSUPPORTED_SEMANTICS,
                    "profile override ep_size must be >= 1",
                    operation="submit_serving")
        return dict(raw)

    def _serving_timeout(self, raw: Any) -> int:
        """Per-request wall-clock budget for the canonical run."""
        if raw is None:
            return self.config.timeout_s
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"timeout_s must be an integer; got {raw!r}",
                operation="submit_serving")
        if not 1 <= raw <= 3600:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"timeout_s must be in [1, 3600]; got {raw}",
                operation="submit_serving")
        return raw

    def _serving_config_entry(self, rel: str) -> dict[str, Any] | None:
        """One cluster service-semantics config, listed for selection.

        Geometry is read from the document so the UI can describe a choice
        without interpreting it. No serving semantics are derived here.
        """
        path = self.config.repo_root / rel
        if not path.is_file():
            return None
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        nodes = document.get("nodes") or []
        instances = [i for n in nodes for i in (n.get("instances") or [])]

        def _ints(key: str) -> list[int]:
            return sorted({int(i[key]) for i in instances
                           if isinstance(i.get(key), int)})

        def _strs(key: str) -> list[str]:
            return sorted({str(i[key]) for i in instances
                           if i.get(key) not in (None, "")})

        config_id = Path(rel).stem
        return {
            "contract_version": 1,
            "config_id": config_id,
            "display_name": config_id.replace("_", " "),
            "description": (f"{len(nodes)} node(s), "
                            f"{len(instances)} instance(s)"),
            "source": rel,
            "content_digest": ("sha256:" + hashlib.sha256(
                path.read_bytes()).hexdigest()),
            "geometry": {
                "num_nodes": int(document.get("num_nodes") or len(nodes)),
                "instances": len(instances),
                "tp_sizes": _ints("tp_size"),
                "ep_sizes": _ints("ep_size"),
                "pp_sizes": _ints("pp_size"),
                "pd_types": _strs("pd_type"),
                "models": _strs("model_name"),
                "hardware": _strs("hardware"),
                "link_bw": document.get("link_bw"),
                "link_latency": document.get("link_latency"),
            },
        }

    def _serving_trace_entry(self, rel: str) -> dict[str, Any] | None:
        """One JSONL request trace, listed for selection."""
        path = self.config.repo_root / rel
        if not path.is_file():
            return None
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            return None
        requests = 0
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                json.loads(line)
            except json.JSONDecodeError:
                continue
            requests += 1
        trace_id = Path(rel).stem
        return {
            "contract_version": 1,
            "trace_id": trace_id,
            "display_name": trace_id.replace("_", " "),
            "description": f"{requests} request(s) in the trace",
            "source": rel,
            "content_digest": ("sha256:" + hashlib.sha256(
                path.read_bytes()).hexdigest()),
            "requests": requests,
        }

    def serving_config_catalog(self) -> dict[str, Any]:
        """Cluster configs and request traces the canonical serve path can
        be pointed at, plus the tracked defaults. Mirrors workload_catalog /
        fabric_presets: the product layer lists, it does not interpret."""
        root = self.config.repo_root

        configs: list[dict[str, Any]] = []
        config_dir = root / self._SERVING_CONFIG_DIR
        if config_dir.is_dir():
            for path in sorted(config_dir.glob("*.json")):
                entry = self._serving_config_entry(
                    str(path.relative_to(root)))
                if entry is not None:
                    configs.append(entry)

        traces: list[dict[str, Any]] = []
        trace_dir = root / self._SERVING_TRACE_DIR
        if trace_dir.is_dir():
            for path in sorted(trace_dir.glob("*.jsonl")):
                entry = self._serving_trace_entry(
                    str(path.relative_to(root)))
                if entry is not None:
                    traces.append(entry)

        return {
            "contract_version": 1,
            "configs": configs,
            "traces": traces,
            "default_config": self._SERVING_CLUSTER_CONFIG,
            "default_trace": self._SERVING_DATASET,
        }

    _SERVING_FACET_MARKERS = (
        ("remote_kv", ("kv_remote", "remote_kv")),
        ("cxl", ("cxl",)),
        ("pim", ("pim",)),
        ("power", ("power",)),
        ("memory_tier", ("memory",)),
        ("heterogeneous", ("heterogeneous",)),
        ("dual_node", ("dual_node",)),
    )

    def serving_experiment_catalog(self) -> dict[str, Any]:
        """Runnable serving experiments: cluster config x trace.

Rationale: docs/decisions/modules/product.md
        """
        base = self.serving_config_catalog()
        configs = base["configs"]
        traces = base["traces"]
        experiments: list[dict[str, Any]] = []
        for config in configs:
            geometry = config.get("geometry") or {}
            facets = self._serving_experiment_facets(config)
            readiness = self._serving_experiment_readiness(config)
            for trace in traces:
                experiments.append({
                    "contract_version": 1,
                    "experiment_id": (config["config_id"] + "__"
                                       + trace["trace_id"]),
                    "config_id": config["config_id"],
                    "trace_id": trace["trace_id"],
                    "display_name": (config["display_name"] + " x "
                                     + trace["display_name"]),
                    "facets": facets,
                    "config_source": config["source"],
                    "config_digest": config["content_digest"],
                    "trace_source": trace["source"],
                    "trace_digest": trace["content_digest"],
                    "trace_requests": trace["requests"],
                    "readiness": readiness,
                })
        return {
            "contract_version": 1,
            "experiments": experiments,
            "gaps": self._serving_catalog_gaps(configs),
            "default_config": base["default_config"],
            "default_trace": base["default_trace"],
        }

    @classmethod
    def _serving_experiment_facets(
            cls, config: dict[str, Any]) -> dict[str, Any]:
        geometry = config.get("geometry") or {}
        models = [str(m) for m in (geometry.get("models") or [])]
        lowered = " ".join(models).lower() + " " + config["config_id"]
        ep_sizes = [int(e) for e in (geometry.get("ep_sizes") or [])]
        moe = any(e > 1 for e in ep_sizes) or any(
            marker in lowered for marker in ("moe", "a3b", "8x7b"))
        instances = int(geometry.get("instances") or 0)
        markers = {facet for facet, needles in
                   cls._SERVING_FACET_MARKERS
                   if any(n in lowered for n in needles)}
        pd_types = [str(p) for p in (geometry.get("pd_types") or [])]
        return {
            "models": models,
            "dense_or_moe": "moe" if moe else "dense",
            "instances": instances,
            "multi_instance": instances > 1,
            "tp_sizes": [int(t) for t in
                           (geometry.get("tp_sizes") or [])],
            "ep_sizes": ep_sizes,
            "dp_sizes": [int(d) for d in
                           (geometry.get("dp_sizes") or [])],
            "prefill_decode_split": len(pd_types) > 0,
            "pd_types": pd_types,
            "num_nodes": int(geometry.get("num_nodes") or 0),
            "hardware": [str(h) for h in
                           (geometry.get("hardware") or [])],
            "markers": sorted(markers),
        }

    def _serving_experiment_readiness(
            self, config: dict[str, Any]) -> dict[str, Any]:
        """Install facts per experiment, never a readiness verdict.

        A missing model config or absent backend binary is an
        environment fact the submit path refuses with its typed error;
        the catalog only reports what is present.
        """
        geometry = config.get("geometry") or {}
        models = [str(m) for m in (geometry.get("models") or [])]
        model_configs = {}
        for name in models:
            candidate = self.config.repo_root / (
                "third_party/llmservingsim/configs/model/" + name
                + ".json")
            model_configs[name] = candidate.is_file()
        try:
            from veritx_dse.backend.astra import resolve_runtime_binary
            astra_binary = resolve_runtime_binary()
            astra_present = astra_binary is not None and (
                Path(astra_binary).is_file())
        except Exception:                           # noqa: BLE001
            astra_present = False
        booksim = self.config.booksim_bin
        return {
            "model_configs": model_configs,
            "astra_binary_present": bool(astra_present),
            "booksim_configured": booksim is not None and (
                Path(booksim).is_file()),
        }

    def _serving_catalog_gaps(
            self, configs: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Model configs no cluster file references: explicit gaps."""
        referenced = set()
        for config in configs:
            geometry = config.get("geometry") or {}
            for model in (geometry.get("models") or []):
                referenced.add(str(model))
        model_root = (self.config.repo_root /
                      "third_party/llmservingsim/configs/model")
        gaps: list[dict[str, Any]] = []
        if not model_root.is_dir():
            return gaps
        for path in sorted(model_root.rglob("*.json")):
            if path.name == "README.md":
                continue
            name = (path.parent.name + "/" + path.stem
                    if path.parent != model_root else path.stem)
            if name not in referenced:
                gaps.append({
                    "model": name,
                    "source": str(path.relative_to(
                        self.config.repo_root)),
                    "reason": ("model config exists but no cluster "
                               "service-semantics file references it — "
                               "not runnable as an experiment"),
                })
        return gaps

    @staticmethod
    def _collective_view(collective: Any) -> dict[str, Any]:
        return {
            "kind": getattr(collective.kind, "value", collective.kind),
            "dimension": getattr(collective.dimension, "value",
                                 collective.dimension),
            "payload_bytes": collective.payload_bytes,
            "traffic_class": getattr(collective, "traffic_class", None),
        }

    @staticmethod
    def _noc_view(request: Any) -> dict[str, Any]:
        noc = request.noc_config
        return {
            "topology_family": getattr(noc.topology_family, "value",
                                       noc.topology_family),
            "radix": noc.radix,
            "concentration": noc.concentration,
            "link_width": noc.link_width,
            "rcu_enabled": noc.rcu_enabled,
            "arbitration": noc.arbitration,
        }

    def create_project(self, *, name: str,
                       workload_id: str | None = None) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise intent_error("project name must be a non-empty string")
        catalog = self.workload_catalog()["workloads"]
        if not catalog:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                "no workload templates are available on this tree")
        chosen = None
        if workload_id is not None:
            chosen = next((w for w in catalog
                           if w["workload_id"] == workload_id), None)
            if chosen is None:
                raise intent_error(
                    f"unknown workload {workload_id!r}; known: "
                    f"{[w['workload_id'] for w in catalog]}")
        chosen = chosen or catalog[0]
        project = self.store.create_project(
            name=name.strip(), draft_doc=chosen["request"],
            workload_id=chosen["workload_id"], source=chosen["source"])
        request = parse_request_doc(chosen["request"])
        self.store.save_draft(project["project_id"], chosen["request"],
                              design_hash=_view_hash(request.design_hash()))
        return self.project_view(project["project_id"])

    @staticmethod
    def _revision_promotable(revision: dict[str, Any]) -> bool:
        """Only a COMPILED revision with a PASS certificate may go active.

        A refused attempt (INVALID/UNSUPPORTED, or a FAIL certificate) is
        recorded as the latest attempt but must never displace the last
        usable revision.
        """
        compilation = revision.get("compilation") or {}
        certificate = revision.get("certificate") or {}
        return (compilation.get("status") == "COMPILED"
                and certificate.get("overall") == "PASS")

    def _ensure_revision_pointers(self, project_id: str) -> dict[str, Any]:
        """Backfill and repair the active/latest revision pointers.

Rationale: docs/decisions/modules/product.md
        """
        project = self.store.load_project(project_id)
        revision_ids = project.get("revision_ids", [])
        changed = False
        if (project.get("latest_attempt_revision_id") is None
                and revision_ids):
            project["latest_attempt_revision_id"] = revision_ids[-1]
            changed = True
        active_id = project.get("active_revision_id")
        if active_id is not None:
            try:
                active = self.store.load_revision(project_id, active_id)
            except ProductStoreError:
                active = None
            if active is None or not self._revision_promotable(active):
                fallback = None
                for rid in reversed(revision_ids):
                    if rid == active_id:
                        continue
                    try:
                        candidate = self.store.load_revision(
                            project_id, rid)
                    except ProductStoreError:
                        continue
                    if self._revision_promotable(candidate):
                        fallback = rid
                        break
                project["active_revision_id"] = fallback
                changed = True
        if changed:
            self.store.save_project(project)
        return project

    def project_view(self, project_id: str) -> dict[str, Any]:
        project = self._ensure_revision_pointers(project_id)
        draft = self.store.load_draft(project_id)
        revisions = self.store.list_revisions(project_id)
        active_id = project.get("active_revision_id")
        active = next((r for r in revisions
                       if r["revision_id"] == active_id), None)
        latest_id = project.get("latest_attempt_revision_id")
        latest = next((r for r in revisions
                       if r["revision_id"] == latest_id), None)
        runs = self.store.list_runs(project_id)
        jobs = self.store.list_jobs(project_id)
        optimizations = [self.store.load_optimization(project_id, oid)
                         for oid in project.get("optimization_ids", [])]
        dirty = active is None or (
            draft.get("design_hash") != active.get("design_hash"))
        flow = self._flow(active, dirty, runs, jobs, latest,
                          draft.get("design_hash"))
        latest_active_run = next(
            (r for r in reversed(runs)
             if r.get("revision_id") == active_id), None)
        latest_optimization = optimizations[-1] if optimizations else None
        serving = self.list_serving(project_id)
        latest_serving = serving[-1] if serving else None
        if active is None:
            active_evaluation = None
        else:
            assessment = self._assessment_for_revision(active)
            active_evaluation = {
                **assessment,
                "supported": assessment["support"] != "UNSUPPORTED",
            }
        return {
            "contract_version": 1,
            "project": {
                "project_id": project["project_id"],
                "name": project["name"],
                "created_at": project["created_at"],
                "updated_at": project["updated_at"],
            },
            "active_revision_id": active_id,
            "active_revision": (None if active is None
                                else self.revision_view(active)),
            "latest_attempt_revision_id": latest_id,
            "latest_attempt": (None if latest is None
                               else self._revision_summary(latest)),
            "latest_active_run": (None if latest_active_run is None
                                  else self._run_summary(latest_active_run)),
            "latest_static_evaluation": (
                None if latest_active_run is None
                else self._run_summary(latest_active_run)),
            "latest_serving_experiment": (
                None if latest_serving is None else {
                    "serving_id": latest_serving.get("serving_id"),
                    "state": latest_serving.get("state"),
                    "created_at": latest_serving.get("created_at"),
                }),
            "latest_optimization_study": (
                None if latest_optimization is None else {
                    "optimization_id":
                        latest_optimization["optimization_id"],
                    "base_revision_id":
                        latest_optimization["base_revision_id"],
                    "created_at": latest_optimization["created_at"],
                    "candidate_count": len(
                        latest_optimization["study"].get("candidates", [])),
                    "pareto_count": len(
                        latest_optimization["study"].get("pareto_ids", [])),
                    "selected_candidate_id": latest_optimization["study"]
                        .get("selected_candidate_id"),
                }),
            "active_evaluation": active_evaluation,
            "draft": {
                "dirty": dirty,
                "based_on_revision_id": active_id,
                "workload_id": draft.get("workload_id"),
                "source": draft.get("source"),
                "design_hash": draft.get("design_hash"),
                "updated_at": draft.get("updated_at"),
            },
            "revisions": [self._revision_summary(r) for r in revisions],
            "runs": [self._run_summary(r) for r in runs],
            "optimizations": [
                {"optimization_id": o["optimization_id"],
                 "base_revision_id": o["base_revision_id"],
                 "created_at": o["created_at"],
                 "candidate_count": len(o["study"].get("candidates", [])),
                 "pareto_count": len(o["study"].get("pareto_ids", [])),
                 "selected_candidate_id":
                     o["study"].get("selected_candidate_id")}
                for o in optimizations],
            "flow": flow,
        }

    def list_projects(self) -> dict[str, Any]:
        return {"contract_version": 1,
                "projects": [self.project_view(p["project_id"])
                             for p in self.store.list_projects()]}

    def rename_project(self, project_id: str, name: str) -> dict[str, Any]:
        if not isinstance(name, str) or not name.strip():
            raise intent_error("project name must be a non-empty string")
        self.store.load_project(project_id)
        project = self.store.rename_project(project_id, name.strip())
        return self.project_view(project["project_id"])

    def delete_project(self, project_id: str) -> dict[str, Any]:
        self.store.load_project(project_id)
        active = [j for j in self.store.list_jobs(project_id)
                  if j.get("state") not in TERMINAL_STATES]
        if active:
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"project {project_id} has {len(active)} job(s) in progress; "
                "wait for them to finish before deleting",
                operation="delete_project", resource_id=project_id)
        self.store.delete_project(project_id)
        return {"contract_version": 1, "deleted": True,
                "project_id": project_id}

    def draft_view(self, project_id: str) -> dict[str, Any]:
        project = self._ensure_revision_pointers(project_id)
        draft = self.store.load_draft(project_id)
        active_id = project.get("active_revision_id")
        active = None
        if active_id is not None:
            active = self.store.load_revision(project_id, active_id)
        dirty = active is None or (
            draft.get("design_hash") != active.get("design_hash"))
        return {
            "contract_version": 1,
            "project_id": project_id,
            "workload_id": draft.get("workload_id"),
            "source": draft.get("source"),
            "updated_at": draft.get("updated_at"),
            "design_hash": draft.get("design_hash"),
            "dirty": dirty,
            "active_revision_id": active_id,
            "latest_attempt_revision_id":
                project.get("latest_attempt_revision_id"),
            "derived_from_optimization_id":
                draft.get("derived_from_optimization_id"),
            "derived_from_candidate_id": draft.get("derived_from_candidate_id"),
            "request": draft.get("request"),
        }

    def design_view_v2(self, project_id: str, *,
                       presentation: str = "edit",
                       review_snapshot_hash: str | None = None,
                       ) -> dict[str, Any]:
        """DesignViewV2 for the current draft (Gate 7 §51.1).

        One projection, two presentations: authoring (``edit``) and the
        pre-compile boundary (``review``). The backend owns the canonical
        values, the grouping, readiness, findings, capability consequences
        and the scientific diff — the frontend renders them.
        """
        from veritx_dse.application.design_view_v2 import (
            build_design_view_v2,
        )

        project = self._ensure_revision_pointers(project_id)
        draft = self.store.load_draft(project_id)
        request = parse_request_doc(draft.get("request"))
        canonical_doc = canonical_request_doc(request)
        draft_hash = _view_hash(request.design_hash())

        parent_revision = None
        parent_doc = None
        active_id = project.get("active_revision_id")
        if active_id is not None:
            parent_revision = self.store.load_revision(project_id, active_id)
            parent_doc = parent_revision.get("request")

        return build_design_view_v2(
            canonical_doc,
            project_id=project_id,
            presentation=presentation,
            draft_design_hash=draft_hash,
            parent_revision=parent_revision,
            parent_doc=parent_doc,
            review_snapshot_hash=review_snapshot_hash,
        )

    def put_draft(self, project_id: str, request_doc: Any) -> dict[str, Any]:
        request = parse_request_doc(request_doc)
        self.store.save_draft(project_id, canonical_request_doc(request),
                              design_hash=_view_hash(request.design_hash()))
        return self.draft_view(project_id)

    def select_workload(self, project_id: str,
                        workload_id: str) -> dict[str, Any]:
        """Make a catalog workload the project's draft (a real user action).

        The draft request and its workload identity/source move together;
        the previous compiled revision is untouched, so the draft becomes
        dirty until recompiled.
        """
        self.store.load_project(project_id)
        catalog = self.workload_catalog()["workloads"]
        entry = next((w for w in catalog if w["workload_id"] == workload_id),
                     None)
        if entry is None:
            raise intent_error(
                f"unknown workload {workload_id!r}; known: "
                f"{[w['workload_id'] for w in catalog]}")
        request = parse_request_doc(entry["request"])
        draft = self.store.load_draft(project_id)
        draft["workload_id"] = entry["workload_id"]
        draft["source"] = entry["source"]
        draft["request"] = canonical_request_doc(request)
        draft["design_hash"] = _view_hash(request.design_hash())
        self.store.put_draft(project_id, draft)
        return self.draft_view(project_id)

    def use_candidate(self, optimization_id: str,
                      candidate_id: str) -> dict[str, Any]:
        """Adopt a studied candidate as the DRAFT. Never mutates a revision.

Rationale: docs/decisions/modules/product.md
        """
        from veritx_dse.optimization.candidate import (
            CandidateError, apply_patch,
        )

        optimization = self.get_optimization(optimization_id)
        project_id = optimization["project_id"]
        base_revision_id = optimization["base_revision_id"]
        study = optimization.get("study") or {}
        candidate = next(
            (c for c in study.get("candidates", [])
             if c.get("candidate_id") == candidate_id), None)
        if candidate is None:
            raise intent_error(
                f"unknown candidate {candidate_id!r} in optimization "
                f"{optimization_id!r}; the study records "
                f"{len(study.get('candidates', []))} candidate(s)")

        compilation_status = candidate.get("compilation_status")
        if compilation_status not in (None, "COMPILED", "SUCCEEDED"):
            raise intent_error(
                f"candidate {candidate_id!r} did not compile "
                f"(compilation_status={compilation_status!r}); "
                f"reason: {candidate.get('eligibility_reason') or 'unknown'}")

        patch = dict(candidate.get("guided_patch") or {})
        if not patch:
            raise intent_error(
                f"candidate {candidate_id!r} carries no GUIDED patch, so it "
                "is the base design; there is nothing to adopt")

        base_revision = self.store.load_revision(project_id, base_revision_id)
        base_request = parse_request_doc(base_revision.get("request"))
        try:
            patched = apply_patch(base_request, patch)
        except (CandidateError, ValueError, KeyError) as exc:
            raise intent_error(
                f"cannot apply candidate {candidate_id!r} patch {patch!r} to "
                f"base revision {base_revision_id!r}: {exc}") from exc

        expected = candidate.get("design_hash")
        actual = _view_hash(patched.design_hash())
        if expected and expected not in (actual, actual[len("sha256:"):]):
            raise intent_error(
                f"re-applying candidate {candidate_id!r} to base revision "
                f"{base_revision_id!r} produced design {actual}, but the "
                f"study recorded {expected!r}. The study and this draft would "
                "be different designs, so the adoption is refused rather than "
                "silently recording a mismatched provenance.")

        draft = self.store.load_draft(project_id)
        draft["request"] = canonical_request_doc(patched)
        draft["design_hash"] = _view_hash(patched.design_hash())
        draft["derived_from_optimization_id"] = optimization_id
        draft["derived_from_candidate_id"] = candidate_id
        draft["source"] = "optimization-candidate"
        self.store.put_draft(project_id, draft)
        view = self.draft_view(project_id)
        view["derived_from_optimization_id"] = optimization_id
        view["derived_from_candidate_id"] = candidate_id
        view["adopted_from_revision_id"] = base_revision_id
        return view

    def compile_draft(self, project_id: str,
                      expected_draft_design_hash: str | None = None,
                      ) -> dict[str, Any]:
        """Compile the current draft into an immutable revision.

Rationale: docs/decisions/modules/product.md
        """
        self._ensure_revision_pointers(project_id)
        draft = self.store.load_draft(project_id)
        request = parse_request_doc(draft.get("request"))
        canonical_doc = canonical_request_doc(request)
        current_hash = _view_hash(request.design_hash())
        if (expected_draft_design_hash is not None
                and expected_draft_design_hash != current_hash):
            raise ControlPlaneError(
                ErrorCode.STALE_REVIEW,
                "the draft changed after this review was generated; refresh "
                "Review before compiling (reviewed "
                f"{expected_draft_design_hash}, current {current_hash})",
                operation="compile",
                resource_id=project_id,
                details=(
                    ("expected_draft_design_hash", expected_draft_design_hash),
                    ("current_draft_design_hash", current_hash),
                ))
        compilation = FabricCompiler().compile(request)
        design = design_view(
            request, compilation if compilation.status == "COMPILED" else None)
        comp_view = compilation_view(compilation)
        certificate = None
        if compilation.certificate is not None:
            certificate = {
                "certificate_id": compilation.certificate.certificate_id(),
                "overall": compilation.certificate.overall,
                "obligations": [o.to_dict()
                                for o in compilation.certificate.obligations],
            }
        sequence = self.store.allocate_revision(project_id)
        revision_id = f"{project_id}-r{sequence:02d}"
        revision = {
            "schema_version": 1,
            "revision_id": revision_id,
            "display_name": f"r{sequence:02d}",
            "project_id": project_id,
            "created_at": utcnow(),
            "design_hash": _view_hash(request.design_hash()),
            "request": canonical_doc,
            "design": design,
            "compilation": comp_view,
            "certificate": certificate,
        }
        for key in ("derived_from_optimization_id", "derived_from_candidate_id"):
            if draft.get(key):
                revision[key] = draft[key]
        materialized = topology_view(compilation, revision_id=revision_id)
        if materialized is not None:
            revision["topology"] = materialized
        else:
            staged_topology = staged_topology_view(
                compilation, revision_id=revision_id)
            if staged_topology is not None:
                revision["staged_topology"] = staged_topology
        chain = artifact_chain_view(compilation)
        if chain is not None:
            revision["artifact_chain"] = chain
        if compilation.bundle is not None:
            revision["compile_result"] = build_compile_result(
                revision, compilation, revision.get("topology"), chain)
        revision["simulation"] = self._assess_compilation(
            request, compilation)
        candidate_id = draft.get("derived_from_candidate_id")
        if candidate_id and compilation.status == "COMPILED":
            from veritx_dse.product import vnext as _vnext
            try:
                _vnext.mark_candidate_compiled(
                    self.store, candidate_id, revision_id,
                    verified=(certificate is not None
                              and certificate.get("overall") == "PASS"))
            except Exception as exc:
                revision["candidate_flip_error"] = (
                    f"{type(exc).__name__}: {exc}")
        self.store.create_revision(
            project_id, revision,
            promote=self._revision_promotable(revision))
        return self.revision_view(revision)

    def get_revision_compile_result(self, revision_id: str) -> dict[str, Any]:
        """CompileResultView as served: the route TABLE is not shipped.

Rationale: docs/decisions/modules/product.md
        """
        payload = self._stored_compile_result(revision_id)
        if payload.get("available") and "groups" in payload:
            routing = payload["groups"].get("routing")
            if routing and routing.get("entries"):
                payload = {**payload, "groups": {
                    **payload["groups"],
                    "routing": {**routing, "entries": [],
                                "entries_withheld": True,
                                "entries_note": (
                                    "the route table is not shipped in this "
                                    "payload; query "
                                    "/revisions/{id}/route for a canonical "
                                    "route")}}}
        return payload

    def _stored_compile_result(self, revision_id: str) -> dict[str, Any]:
        """The full frozen payload, including the route table.

Rationale: docs/decisions/modules/product.md
        """
        _pid, revision = self.store.load_revision_global(revision_id)
        payload = revision.get("compile_result")
        if payload is not None and compile_result_is_current(payload):
            return payload

        compilation_view_doc = revision.get("compilation") or {}
        if compilation_view_doc.get("status") != "COMPILED":
            return self._staged_compile_result(revision_id, revision)

        compilation = FabricCompiler().compile(
            parse_request_doc(revision["request"]))
        if compilation.status != "COMPILED":
            return {
                "contract_version": 1,
                "available": False,
                "revision_id": revision_id,
                "reason": (compilation.error
                           or "the recorded revision no longer compiles"),
            }
        recorded = compilation_view_doc.get("artifact_hashes") or {}
        expected = {
            "design_hash": revision.get("design_hash"),
            "resolved_fabric_hash": compilation_view_doc.get(
                "resolved_fabric_hash"),
        }
        actual = compilation.bundle.root_hashes()

        def _bare(value: Any) -> str | None:
            return None if value is None else str(value).split(":", 1)[-1]

        for key, want in expected.items():
            have = actual.get(key)
            if want is None or have is None:
                continue
            if _bare(want) != _bare(have):
                raise ProductServiceError(
                    ErrorCode.EVIDENCE_INVALID,
                    f"re-derived compile result does not match the recorded "
                    f"{key} for this revision",
                    operation="get_revision_compile_result",
                    resource_id=revision_id)
        return build_compile_result(
            revision, compilation,
            self.get_revision_topology(revision_id),
            revision.get("artifact_chain") or artifact_chain_view(compilation))

    def _staged_compile_result(self, revision_id: str,
                               revision: dict[str, Any]) -> dict[str, Any]:
        """A staged refusal as a product state, not a catastrophic error.

Rationale: docs/decisions/modules/product.md
        """
        compilation_view_doc = revision.get("compilation") or {}
        status = compilation_view_doc.get("status")
        staged = compilation_view_doc.get("staged")
        staged_topology = revision.get("staged_topology")
        return {
            "contract_version": 1,
            "available": False,
            "staged": True,
            "revision_id": revision_id,
            "display_name": revision.get("display_name"),
            "design_hash": revision.get("design_hash"),
            "compilation_status": status,
            "stopped_at_stage": compilation_view_doc.get(
                "stopped_at_stage"),
            "produced_stages": (staged or {}).get("produced_stages", []),
            "reason": (compilation_view_doc.get("error")
                       or "derivation stopped before a bundle was produced"),
            "staged_topology": staged_topology,
            "unavailable_groups": [
                "routing", "resources", "address_decode", "provenance"],
            "certificate": {
                "available": False,
                "reason": ("no certificate was issued: compilation stopped "
                           f"at {compilation_view_doc.get('stopped_at_stage')}"
                           if compilation_view_doc.get("stopped_at_stage")
                           else "no certificate was issued"),
            },
            "capability_consequences": (
                self._staged_capability_consequences(revision)
                if staged_topology else []),
        }

    def _staged_capability_consequences(
            self, revision: dict[str, Any]) -> list[dict[str, Any]]:
        """The capability rows a staged stop actually exercises.

        Read from the registry, never hand-coded: the stopping stage maps
        to the capability whose later stage is unavailable, so the product
        says "routed execution is unavailable" in the registry's own
        words instead of inventing a reason string.
        """
        from veritx_dse.application import product_registry as registry

        staged = (revision.get("compilation") or {}).get("staged") or {}
        stage = staged.get("stopped_at_stage")
        family = (revision.get("staged_topology") or {}).get("family")
        capability_ids: list[str] = []
        if stage == "ROUTING" and family:
            for row in registry.capability_rows():
                if row.get("owner") != "FABRIC":
                    continue
                name = (row.get("name") or "").lower()
                if family.lower() in name and row.get("stages", {}).get(
                        "PROJECTABLE") == "NO":
                    capability_ids.append(row["id"])
        out: list[dict[str, Any]] = []
        for capability_id in capability_ids:
            consequence = registry.capability_consequence(capability_id)
            if consequence is None:
                continue
            out.append({
                "capability_id": capability_id,
                "choice": family,
                "name": consequence["name"],
                "wiring": consequence["wiring"],
                "reason": consequence["reason"],
                "limiting": consequence["limiting"],
                "claim_scope": consequence["claim_scope"],
                "stages": consequence["stages"],
                "registry_version": consequence["capability_semantics_version"],
            })
        return out

    def canonical_route(self, revision_id: str, *,
                        routing_class: str | None = None,
                        src: int | None = None,
                        dst: int | None = None) -> dict[str, Any]:
        """The DERIVED EXPECTED route for one (class, src, dst).

Rationale: docs/decisions/modules/product.md
        """
        from veritx_dse.application.compile_result_view import (  # noqa: PLC0415
            canonical_route as _walk,
        )

        payload = self._stored_compile_result(revision_id)
        if not payload.get("available"):
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                payload.get("reason")
                or "no compile result exists for this revision",
                operation="route", resource_id=revision_id)
        routing = payload["groups"]["routing"]
        resolved_class = routing_class or routing.get("default_class")
        if resolved_class is None:
            raise ProductServiceError(
                ErrorCode.INVALID_INTENT,
                "this revision declares no routing class",
                operation="route", resource_id=revision_id)
        if resolved_class not in (routing.get("routing_classes") or []):
            raise ProductServiceError(
                ErrorCode.INVALID_INTENT,
                f"unknown routing class {resolved_class!r}; declared: "
                f"{routing.get('routing_classes')}",
                operation="route", resource_id=revision_id)
        routers = sorted({
            row["src_router"] for row in routing.get("channel_hops", ())
            if row.get("src_router") is not None})
        if src is None:
            src = routers[0] if routers else 0
        if dst is None:
            dst = routers[-1] if routers else 0
        return _walk(routing, resolved_class, src, dst)

    def revision_view(self, revision: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "revision_id": revision["revision_id"],
            "display_name": revision["display_name"],
            "project_id": revision["project_id"],
            "created_at": revision["created_at"],
            "design_hash": revision["design_hash"],
            "derived_from_optimization_id":
                revision.get("derived_from_optimization_id"),
            "derived_from_candidate_id":
                revision.get("derived_from_candidate_id"),
            "design": revision["design"],
            "compilation": revision["compilation"],
            "certificate": revision["certificate"],
        }

    def get_revision(self, revision_id: str) -> dict[str, Any]:
        _pid, revision = self.store.load_revision_global(revision_id)
        return self.revision_view(revision)

    def revision_diff(self, revision_id: str,
                      against: str | None = None) -> dict[str, Any]:
        """RevisionDiffView — DESIGN / DERIVED / CAPABILITY changes
        between two frozen compile results.

Rationale: docs/decisions/modules/product.md
        """
        from veritx_dse.application.revision_diff import (
            build_revision_diff,
        )
        pid, revision = self.store.load_revision_global(revision_id)
        if against is not None:
            apid, against_revision = self.store.load_revision_global(
                against)
            if apid != pid:
                raise ProductServiceError(
                    ErrorCode.CONFLICT,
                    f"revision {against} belongs to another project and "
                    "cannot be the diff basis",
                    operation="revision_diff", resource_id=revision_id)
        else:
            ordered = [r["revision_id"]
                         for r in self.store.list_revisions(pid)]
            idx = (ordered.index(revision_id)
                   if revision_id in ordered else -1)
            against = ordered[idx - 1] if idx > 0 else None
            against_revision = (
                None if against is None
                else self.store.load_revision(pid, against))
        payload = self._stored_compile_result(revision_id)
        against_payload = (
            None if against_revision is None
            else self._stored_compile_result(
                against_revision["revision_id"]))
        return build_revision_diff(
            revision_id=revision_id, against_revision_id=against,
            revision_payload=payload, against_payload=against_payload,
            revision_meta={"display_name": revision.get("display_name")},
            against_meta=(
                None if against_revision is None
                else {"display_name":
                      against_revision.get("display_name")}))

    def get_revision_topology(self, revision_id: str) -> dict[str, Any]:
        """The materialized fabric graph a revision was certified against.

        Revisions persisted before this projection existed re-derive it
        from their own immutable request and are checked against the
        topology_hash the certificate already recorded — a mismatch is an
        EVIDENCE_INVALID, never a silently redrawn fabric.
        """
        _pid, revision = self.store.load_revision_global(revision_id)
        view = revision.get("topology")
        if view is None:
            compilation = revision.get("compilation") or {}
            if compilation.get("status") != "COMPILED":
                raise ProductServiceError(
                    ErrorCode.CONFLICT,
                    "this revision did not compile, so it has no "
                    "materialized topology",
                    operation="get_revision_topology",
                    resource_id=revision_id)
            rederived = topology_view(
                FabricCompiler().compile(
                    parse_request_doc(revision["request"])),
                revision_id=revision_id)
            expected = (compilation.get("artifact_hashes") or {}).get(
                "topology_hash")
            if rederived is None or (
                    expected is not None
                    and rederived["topology_hash"].split(":", 1)[-1]
                    != str(expected).split(":", 1)[-1]):
                raise ProductServiceError(
                    ErrorCode.EVIDENCE_INVALID,
                    "re-derived topology does not match the recorded "
                    "topology_hash for this revision",
                    operation="get_revision_topology",
                    resource_id=revision_id)
            view = rederived
        return view

    def get_revision_artifact_chain(self, revision_id: str) -> dict[str, Any]:
        """The canonical artifact DAG this revision was certified against.

        Revisions persisted before this projection existed re-derive it
        from their own immutable request and are checked against the
        artifact hashes the certificate already recorded — a mismatch is
        EVIDENCE_INVALID, never a silently redrawn chain.
        """
        _pid, revision = self.store.load_revision_global(revision_id)
        chain = revision.get("artifact_chain")
        if chain is not None:
            return chain
        compilation_doc = revision.get("compilation") or {}
        if compilation_doc.get("status") != "COMPILED":
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                "this revision did not compile, so it has no artifact chain",
                operation="get_revision_artifact_chain",
                resource_id=revision_id)
        rederived = artifact_chain_view(
            FabricCompiler().compile(
                parse_request_doc(revision["request"])))
        expected = compilation_doc.get("artifact_hashes") or {}
        if rederived is None:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                "re-derivation produced no artifact chain for a compiled "
                "revision",
                operation="get_revision_artifact_chain",
                resource_id=revision_id)
        for node in rederived["nodes"]:
            key = node["artifact"]
            if key == "design":
                continue
            recorded = expected.get(f"{key}_hash")
            if recorded is not None:
                actual = node["hash"].split(":", 1)[-1]
                if actual != str(recorded).split(":", 1)[-1]:
                    raise ProductServiceError(
                        ErrorCode.EVIDENCE_INVALID,
                        f"re-derived {key} does not match the recorded "
                        f"hash for this revision",
                        operation="get_revision_artifact_chain",
                        resource_id=revision_id)
        return rederived

    @staticmethod
    def _revision_summary(revision: dict[str, Any]) -> dict[str, Any]:
        compilation = revision.get("compilation") or {}
        certificate = revision.get("certificate") or {}
        return {
            "revision_id": revision["revision_id"],
            "display_name": revision["display_name"],
            "created_at": revision["created_at"],
            "design_hash": revision["design_hash"],
            "compilation_status": compilation.get("status"),
            "certificate_overall": certificate.get("overall"),
            "error": compilation.get("error"),
        }

    def job_view(self, job: dict[str, Any]) -> dict[str, Any]:
        return {
            "contract_version": 1,
            "job_id": job["job_id"],
            "project_id": job["project_id"],
            "kind": job["kind"],
            "revision_id": job["revision_id"],
            "state": job["state"],
            "submitted_at": job["submitted_at"],
            "updated_at": job["updated_at"],
            "error_code": job.get("error_code"),
            "error_message": job.get("error_message"),
            "result": job.get("result"),
        }

    def get_job(self, job_id: str) -> dict[str, Any]:
        pid = self.store.find_job_project(job_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such job: {job_id}",
                operation="get_job", resource_id=job_id)
        return self.job_view(self.store.load_job(pid, job_id))

    def _require_backend(self) -> Path:
        binary = self.config.booksim_bin
        if binary is None or not Path(binary).is_file():
            raise BackendUnavailable(
                "no qualified backend configured (set VERITX_BOOKSIM_BIN)")
        return Path(binary).resolve()

    @staticmethod
    def _parse_eval_questions(
            questions: Any, *, all_by_default: bool = False
    ) -> tuple[Any, ...]:
        """Normalize a question selection.

        Plan calls default to ALL currently defined questions; submit
        calls default to NETWORK_COMPLETION only, so old clients keep
        behavior.
        """
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        if questions is None:
            if all_by_default:
                return tuple(EvaluationQuestion)
            return (EvaluationQuestion.NETWORK_COMPLETION,)
        if isinstance(questions, (str, EvaluationQuestion)):
            questions = (questions,)
        parsed: list[EvaluationQuestion] = []
        for question in questions:
            if isinstance(question, EvaluationQuestion):
                parsed.append(question)
                continue
            if isinstance(question, str):
                try:
                    parsed.append(EvaluationQuestion[question])
                    continue
                except KeyError:
                    pass
            raise intent_error(
                f"unknown evaluation question {question!r} (known: "
                f"{sorted(q.name for q in EvaluationQuestion)})")
        if not parsed:
            raise intent_error("at least one evaluation question is required")
        if len(set(parsed)) != len(parsed):
            raise intent_error("duplicate evaluation question requested")
        return tuple(parsed)

    def _compilation_for_plan(self, revision: dict[str, Any]) -> Any:
        """The evaluable Compilation for a stored revision (typed refusal
        when the revision is not certified)."""
        compilation = revision.get("compilation") or {}
        certificate = revision.get("certificate") or {}
        if compilation.get("status") != "COMPILED" \
                or certificate.get("overall") != "PASS":
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"revision {revision.get('revision_id')} is not evaluable "
                f"(compilation={compilation.get('status')}, "
                f"certificate={certificate.get('overall')}); reason: "
                f"{compilation.get('error') or 'not certified'}",
                operation="evaluation_plan",
                resource_id=revision.get("revision_id"))
        request = parse_request_doc(revision["request"])
        return FabricCompiler().compile(request)

    @staticmethod
    def _require_evaluable_request(revision: dict[str, Any],
                                   operation: str) -> None:
        """Refuse evaluation work against frozen v2 requests.

Rationale: docs/decisions/modules/product.md
        """
        request_doc = revision.get("request") or {}
        if request_doc.get("schema_version") == 2:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"revision {revision.get('revision_id')} was compiled "
                "from a schema_version 2 request. Version 2 "
                "interpretation is frozen and cannot be evaluated; "
                "create a new draft from a v3 workload and compile it "
                "(explicit migration via migrate_v2_to_v3). Certified "
                "v2 history is preserved, but no new evaluation can "
                "run against it.",
                operation=operation,
                resource_id=revision.get("revision_id"))

    def evaluation_plan(
        self,
        revision_id: str,
        *,
        questions: Any = None,
        requested_backend: str | None = None,
    ) -> dict[str, Any]:
        """EvaluationPlanView — what this revision can run, per question.

        Pure adjudication: builds the canonical context once, asks the
        planner, projects the view. Never executes anything.
        """
        from veritx_dse.application.evaluation_context import (
            EvaluationContextError, build_evaluation_context,
        )
        from veritx_dse.application.evaluation_plan import (
            EvaluationPlanError, EvaluationPlanner,
        )
        from veritx_dse.application.evaluation_plan_view import (
            evaluation_plan_view,
        )
        _pid, revision = self.store.load_revision_global(revision_id)
        self._require_evaluable_request(revision, "evaluation_plan")
        parsed = self._parse_eval_questions(questions, all_by_default=True)
        if requested_backend is not None and not isinstance(
                requested_backend, str):
            raise intent_error("requested backend must be a string")
        compilation = self._compilation_for_plan(revision)
        try:
            context = build_evaluation_context(compilation)
        except (EvaluationContextError, _LoweringInvalid,
                _LoweringSemantics, _LoweringSchedule,
                _LoweringMappingInvalid) as exc:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"revision {revision_id} has no evaluable context: {exc}",
                operation="evaluation_plan",
                resource_id=revision_id) from exc
        except ControlPlaneError:
            raise
        except Exception as exc:
            raise ProductServiceError(
                ErrorCode.INTERNAL_ERROR,
                f"revision {revision_id} evaluation planning failed "
                f"internally: {type(exc).__name__}: {exc}",
                operation="evaluation_plan",
                resource_id=revision_id) from exc
        try:
            plan = EvaluationPlanner().plan(
                context, parsed, self.registry_for(_pid),
                requested_backend=requested_backend)
        except EvaluationPlanError as exc:
            raise ProductServiceError(
                ErrorCode.INVALID_INTENT, str(exc),
                operation="evaluation_plan",
                resource_id=revision_id) from exc
        resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        return evaluation_plan_view(
            plan, revision_id=revision_id,
            design_hash=context.design_hash,
            resolved_fabric_hash=(
                resolved() if callable(resolved) else resolved),
            workload_id=context.workload_id)

    def submit_evaluation(
        self,
        revision_id: str,
        *,
        questions: Any = None,
        requested_backend: str | None = None,
    ) -> dict[str, Any]:
        pid, revision = self.store.load_revision_global(revision_id)
        self._require_evaluable_request(revision, "submit_evaluation")
        if not self._revision_promotable(revision):
            compilation = revision.get("compilation") or {}
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"revision {revision_id} is not evaluable "
                f"(compilation={compilation.get('status')}, "
                "certificate="
                f"{(revision.get('certificate') or {}).get('overall')}); "
                f"reason: {compilation.get('error') or 'not certified'}",
                operation="submit_evaluation", resource_id=revision_id)
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        parsed = self._parse_eval_questions(questions)
        if requested_backend is not None and not isinstance(
                requested_backend, str):
            raise intent_error("requested backend must be a string")
        if EvaluationQuestion.NETWORK_COMPLETION in parsed:
            assessment = self._assessment_for_revision(revision)
            if assessment["support"] == "UNSUPPORTED":
                code = (ErrorCode.LOWERING_UNSUPPORTED
                        if assessment.get("domain") == "intent_lowering"
                        else ErrorCode.UNSUPPORTED_SEMANTICS)
                raise ProductServiceError(
                    code,
                    f"revision {revision_id} cannot be simulated: "
                    f"{assessment.get('reason')}",
                    operation="submit_evaluation",
                    resource_id=revision_id)
            self._require_backend()
        job = self.jobs.submit(
            pid, kind="EVALUATION", revision_id=revision_id,
            fn=lambda progress: self._run_federated_evaluation(
                pid, revision, parsed, requested_backend, progress))
        return self.job_view(job)

    def _check_compilation_parity(self, revision: dict[str, Any],
                                    request: Any) -> Any:
        """Refuse when a recompiled request drifts from the stored revision.

Rationale: docs/decisions/modules/product.md
        """
        recorded = ((revision.get("compilation") or {})
                    .get("artifact_hashes"))
        if not recorded:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"revision {revision.get('revision_id')} records no "
                "compile-artifact identities, so no run can prove it "
                "executes the stored compilation",
                operation="compilation_parity",
                resource_id=revision.get("revision_id"))
        compilation = FabricCompiler().compile(request)
        recompiled = compilation_view(compilation)
        if recompiled.get("status") != "COMPILED":
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"revision {revision.get('revision_id')} no longer "
                f"recompiles ({recompiled.get('status')}: "
                f"{recompiled.get('error')}) — refusing a run against "
                "drifted compiler semantics",
                operation="compilation_parity",
                resource_id=revision.get("revision_id"))
        fresh = recompiled.get("artifact_hashes") or {}
        if fresh != recorded:
            drifted = sorted(
                {*recorded, *fresh} - {
                    k for k in recorded
                    if k in fresh and fresh[k] == recorded[k]})
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"revision {revision.get('revision_id')} recompiles to "
                f"different artifacts (drifted: {drifted}) — refusing a "
                "run that would not execute the stored compilation",
                operation="compilation_parity",
                resource_id=revision.get("revision_id"))
        return compilation

    @staticmethod
    def _check_run_report_binding(run_id: str, revision: dict[str, Any],
                                    network: Any, report: Any) -> None:
        """Re-verify the requirement report binds THIS revision before
        the run is persisted.

Rationale: docs/decisions/modules/product.md
        """
        from types import SimpleNamespace
        from veritx_dse.optimization.result import (
            OptimizationResultError, _check_report_binding,
        )
        binding = SimpleNamespace(
            design_hash=revision.get("design_hash"),
            performance_result_id=getattr(
                network, "performance_result_id", None),
            requirement_report_id=None)
        try:
            _check_report_binding(binding, report, run_id)
        except OptimizationResultError as exc:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"refusing run {run_id}: the requirement report does "
                f"not bind this revision's network evaluation: {exc}",
                operation="run_report_binding",
                resource_id=run_id) from exc

    def _run_federated_evaluation(
            self, project_id: str, revision: dict[str, Any],
            questions: tuple[Any, ...], requested_backend: str | None,
            progress) -> tuple[str, dict[str, Any]]:
        """Execute the adjudicated plan: one analysis per READY row, each
        through its own backend seam, persisted as a multi-analysis run.

Rationale: docs/decisions/modules/product.md
        """
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        from veritx_dse.application.federated_evaluator import (
            ANALYSIS_INCONCLUSIVE, PARTIAL, AstraRunOptions,
            BookSimRunOptions, RamulatorRunOptions, ServingRunOptions,
            evaluate_federated,
        )
        request = parse_request_doc(revision["request"])
        compilation = self._check_compilation_parity(revision, request)
        run_id = new_run_id()
        bundle_dir = self.store.run_bundle_dir(project_id, run_id)
        progress("RUNNING")
        try:
            federated = evaluate_federated(
                compilation, questions, self.registry_for(project_id),
                requested_backend=requested_backend,
                booksim_options=BookSimRunOptions(
                    binary=self.config.booksim_bin,
                    repo_root=self.config.repo_root,
                    timeout_s=self.config.timeout_s,
                    network_clock_hz=self.config.network_clock_hz),
                astra_options=AstraRunOptions(
                    timeout_s=self.config.timeout_s,
                    repo_root=self.config.repo_root),
                ramulator_options=RamulatorRunOptions(
                    timeout_s=self.config.timeout_s),
                serving_options=self._serving_run_options(project_id),
                run_dir=bundle_dir,
                revision_id=revision["revision_id"])
        except (_LoweringInvalid, _LoweringSemantics, _LoweringSchedule,
                _LoweringMappingInvalid) as exc:
            raise _map_lowering_error(
                exc, operation="run_evaluation") from exc
        network = federated.network_evaluation
        network_analysis = next(
            (a for a in federated.analyses
             if a.question is EvaluationQuestion.NETWORK_COMPLETION
             and a.backend_id == "BOOKSIM_STANDALONE"),
            None)
        evaluation = (None if network is None
                      else network.to_view_dict())
        bundle_id = None
        if any(a.normalized_evidence is not None
               or a.status == ANALYSIS_INCONCLUSIVE
               for a in federated.analyses):
            progress("FINALIZING")
            manifest = finalize_run_bundle(bundle_dir)
            bundle_id = "sha256:" + manifest["bundle_id"]
        run = {
            "schema_version": 1,
            "run_id": run_id,
            "project_id": project_id,
            "revision_id": revision["revision_id"],
            "design_hash": revision["design_hash"],
            "compilation_parity": "MATCHED",
            "display_name": self._run_display_name(revision),
            "backend": None if network is None else network.backend,
            "status": _RUN_STATUS.get(
                federated.status, federated.status),
            "qualification": ("QUALIFIED" if network is not None
                              and network.status == "EVALUATED" else None),
            "qualification_basis": (
                "canonical FabricEvaluator EVALUATED (pinned producer, "
                "admitted + reload-verified evidence)"
                if network is not None
                and network.status == "EVALUATED" else None),
            "requirements_pass": (
                None if federated.requirement_report is None else
                self._report_passes(federated.requirement_report)),
            "started_at": utcnow(),
            "completed_at": utcnow(),
            "bundle_id": bundle_id,
            "evaluation": evaluation,
            "requirements": federated.requirement_report,
            "producer": (None if network is None or
                         network.producer_identity is None else {
                             "backend": network.backend,
                             "producer_identity":
                                 network.producer_identity,
                             "config_hash": network.backend_config_hash,
                             "input_hash": network.backend_input_hash}),
            "evidence": (None if network is None or
                         network.evidence_id is None else {
                             "evidence_id": network.evidence_id,
                             "raw_evidence_digest":
                                 network.raw_evidence_digest,
                             "stats_digest": network.stats_digest,
                             "run_bundle": bundle_id}),
            "reason": self._federated_reason(federated),
            "evaluation_plan": self._plan_record(
                revision["revision_id"], federated),
            "analyses": [a.to_dict() for a in federated.analyses],
            "reused_evidence_id": (
                None if network_analysis is None
                else network_analysis.reused_evidence_id),
            "reuse_matching": (
                None if network_analysis is None
                else network_analysis.reuse_matching),
            "reuse": {
                "reused": (
                    network_analysis is not None
                    and network_analysis.reused_evidence_id is not None),
                "reused_evidence_id": (
                    None if network_analysis is None
                    else network_analysis.reused_evidence_id),
                "matching": (
                    None if network_analysis is None
                    else network_analysis.reuse_matching),
            },
        }
        if federated.requirement_report is not None and network is not None \
                and network.status == "EVALUATED":
            self._check_run_report_binding(
                run_id, revision, network,
                federated.requirement_report)
        candidate_id = revision.get("derived_from_candidate_id")
        if candidate_id and network is not None \
                and network.status == "EVALUATED":
            from veritx_dse.product import vnext as _vnext2
            try:
                _vnext2.mark_candidate_evaluated(
                    self.store, candidate_id, run_id)
            except Exception as exc:
                run["candidate_flip_error"] = (
                    f"{type(exc).__name__}: {exc}")
        self.store.create_run(project_id, run)
        state = ("COMPLETED" if federated.status in ("EVALUATED", PARTIAL)
                 else "REFUSED")
        return state, {"run_id": run_id}

    @staticmethod
    def _federated_reason(federated: Any) -> str | None:
        """Top-level reason: FAILED analyses are named first with their
        question, backend and exact reason (a crashed run must never
        present a generic status); then the historical network-first
        rule; then every other non-evaluated analysis. A PARTIAL run
        with a null reason would hide which question refused."""
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        failed = [
            f"FAILED {a.question.value} on {a.backend_id}: "
            f"{a.reason or a.status}"
            for a in federated.analyses if a.status == "FAILED"]
        network = next(
            (a for a in federated.analyses
             if a.question is EvaluationQuestion.NETWORK_COMPLETION
             and a.backend_id == "BOOKSIM_STANDALONE"),
            None)
        base: str | None = None
        if network is not None and network.status != "EVALUATED" \
                and network.status != "FAILED":
            base = network.reason
        if base is None:
            pending = [f"{a.question.value}: {a.reason or a.status}"
                       for a in federated.analyses
                       if a.status != "EVALUATED"
                       and a.status != "FAILED"]
            if pending:
                base = ("partial evaluation; non-evaluated analyses: "
                        + "; ".join(pending))
        if failed and base:
            return "; ".join(failed) + "; " + base
        if failed:
            return "; ".join(failed)
        return base

    @staticmethod
    def _report_passes(report: dict[str, Any]) -> bool | None:
        from veritx_dse.application.requirements import report_passes
        try:
            return report_passes(report)
        except (AttributeError, TypeError):
            return None

    @staticmethod
    def _plan_record(revision_id: str,
                     federated: Any) -> dict[str, Any]:
        from veritx_dse.application.evaluation_plan_view import (
            evaluation_plan_view,
        )
        return evaluation_plan_view(
            federated.plan, revision_id=revision_id,
            design_hash=federated.design_hash,
            resolved_fabric_hash=federated.resolved_fabric_hash,
            workload_id=federated.workload_id)

    @staticmethod
    def _run_display_name(revision: dict[str, Any]) -> str:
        design = revision.get("design") or {}
        wl = design.get("workload") or {}
        noc = design.get("noc_guided") or {}
        model = wl.get("model_name") or wl.get("model_family") or "workload"
        topology = noc.get("topology_family") or "fabric"
        width = noc.get("link_width")
        width_text = f" · {width}b" if width is not None else ""
        return f"{model} · {topology}{width_text}"

    def list_runs(self, *, project_id: str | None = None,
                  revision_id: str | None = None) -> dict[str, Any]:
        runs = self.store.list_runs(project_id=project_id,
                                    revision_id=revision_id)
        return {"contract_version": 1,
                "runs": [self._run_summary(r) for r in runs]}

    @staticmethod
    def _run_summary(run: dict[str, Any]) -> dict[str, Any]:
        evaluation = run.get("evaluation") or {}
        metrics = evaluation.get("metrics") or {}
        return {
            "run_id": run["run_id"],
            "display_name": run.get("display_name"),
            "project_id": run["project_id"],
            "revision_id": run["revision_id"],
            "design_hash": run.get("design_hash"),
            "backend": run.get("backend"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "requirements_pass": run.get("requirements_pass"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "bundle_id": run.get("bundle_id"),
            "workload_id": evaluation.get("workload_id"),
            "completion_cycles": metrics.get("completion_cycles"),
            "analysis_backends": [
                {"backend_id": a.get("backend_id"),
                 "question": a.get("question"),
                 "status": a.get("status")}
                for a in (run.get("analyses") or [])
                if isinstance(a, dict)
            ],
        }

    def _read_trust_file(self, bundle_dir: Path,
                           relpath: str) -> bytes:
        """Read one bundle file pinned to its verified digest.

Rationale: docs/decisions/modules/product.md
        """
        try:
            data = read_verified_file(bundle_dir, relpath)
        except RunBundleError as exc:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"refusing trust read of {relpath}: {exc}",
                operation="read_trust_file") from exc
        if len(data) > _TRUST_READ_FILE_CAP:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"refusing trust read of {relpath}: "
                f"{len(data)} bytes exceeds the "
                f"{_TRUST_READ_FILE_CAP}-byte trust-read cap",
                operation="read_trust_file") from None
        return data

    def _verify_run_bundle(self, run: dict[str, Any]) -> dict[str, Any] | None:
        """Re-verify the durable RunBundle before any trust read.

Rationale: docs/decisions/modules/product.md
        """
        recorded = run.get("bundle_id")
        if recorded is None:
            return None
        bundle_dir = self.store.run_bundle_dir(run["project_id"], run["run_id"])
        try:
            summary = verify_run_bundle(bundle_dir)
        except RunBundleError as exc:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"run bundle failed verification: {exc}",
                operation="verify_run_bundle",
                resource_id=run["run_id"]) from exc
        computed = "sha256:" + summary["bundle_id"]
        if computed != recorded:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"run {run['run_id']} records bundle_id {recorded} but the "
                f"bundle content hashes to {computed} — refusing a tampered "
                "run bundle",
                operation="verify_run_bundle", resource_id=run["run_id"])
        return summary

    def get_run(self, run_id: str) -> dict[str, Any]:
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="get_run", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        self._verify_run_bundle(run)
        return self._run_view(run)

    def _run_view(self, run: dict[str, Any]) -> dict[str, Any]:
        return self._downgrade_unverified_trust({
            "contract_version": 1,
            "run_id": run["run_id"],
            "display_name": run.get("display_name"),
            "project_id": run["project_id"],
            "revision_id": run["revision_id"],
            "design_hash": run.get("design_hash"),
            "backend": run.get("backend"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "qualification_basis": run.get("qualification_basis"),
            "requirements_pass": run.get("requirements_pass"),
            "started_at": run.get("started_at"),
            "completed_at": run.get("completed_at"),
            "bundle_id": run.get("bundle_id"),
            "evaluation": run.get("evaluation"),
            "requirements": run.get("requirements"),
            "producer": run.get("producer"),
            "evidence": run.get("evidence"),
            "reason": run.get("reason"),
            "evaluation_plan": run.get("evaluation_plan"),
            "analyses": run.get("analyses"),
        }, run)

    @staticmethod
    def _downgrade_unverified_trust(payload: dict[str, Any],
                                      run: dict[str, Any]) -> dict[str, Any]:
        """Downgrade trust claims that have no sealed bundle behind them.

Rationale: docs/decisions/modules/product.md
        """
        if run.get("bundle_id") is not None:
            return payload
        if run.get("status") not in ("EVALUATED", "PARTIAL") \
                and not run.get("qualification"):
            return payload
        payload = dict(payload)
        payload["qualification"] = "UNVERIFIED"
        note = ("trust fields are UNVERIFIED: the run records no "
                "sealed run bundle")
        reason = payload.get("reason")
        payload["reason"] = note if not reason else f"{reason}; {note}"
        return payload

    def run_evidence(self, run_id: str) -> dict[str, Any]:
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="run_evidence", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        self._verify_run_bundle(run)
        bundle_dir = self.store.run_bundle_dir(pid, run_id)
        documents: dict[str, Any] = {}
        artifacts: list[dict[str, Any]] = []
        documents_truncated = False
        total_bytes = 0
        if run.get("bundle_id") is not None and bundle_dir.is_dir():
            for path in sorted(bundle_dir.rglob("*")):
                if not path.is_file():
                    continue
                rel = path.relative_to(bundle_dir).as_posix()
                if any(part.startswith(".") for part in rel.split("/")):
                    continue
                size_bytes = path.stat().st_size
                artifacts.append({"path": rel, "size_bytes": size_bytes})
                if path.suffix != ".json" \
                        or path.name == "checksums.json":
                    continue
                if size_bytes > _TRUST_READ_FILE_CAP or \
                        total_bytes + size_bytes > _TRUST_READ_TOTAL_CAP:
                    documents[rel] = {
                        "truncated": True,
                        "size_bytes": size_bytes,
                        "reason": "exceeds the trust-read byte budget",
                    }
                    documents_truncated = True
                    continue
                try:
                    raw = self._read_trust_file(bundle_dir, rel)
                    documents[rel] = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    continue
                total_bytes += size_bytes
        response = {
            "contract_version": 1,
            "run_id": run_id,
            "bundle_id": run.get("bundle_id"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "producer": run.get("producer"),
            "evidence": run.get("evidence"),
            "artifacts": artifacts,
            "documents": documents,
            "documents_truncated": documents_truncated,
        }
        return self._downgrade_unverified_trust(response, run)

    def run_artifacts(self,         run_id: str) -> dict[str, Any]:
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="run_artifacts", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        self._verify_run_bundle(run)
        bundle_dir = self.store.run_bundle_dir(pid, run_id)
        files: dict[str, Any] = {}
        checksums = bundle_dir / "checksums.json"
        if checksums.is_file():
            try:
                files = json.loads(checksums.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                files = {}
        return {"contract_version": 1, "run_id": run_id,
                "bundle": files}

    def revision_preflight(self, revision_id: str) -> dict[str, Any]:
        """PreflightView — the execution gate, evaluated before any run.

Rationale: docs/decisions/modules/product.md
        """
        try:
            _pid, revision = self.store.load_revision_global(revision_id)
        except ProductServiceError:
            raise
        compilation = revision.get("compilation") or {}
        certificate = revision.get("certificate") or {}
        status = compilation.get("status")
        cert_overall = certificate.get("overall")
        obligations = certificate.get("obligations") or []
        passed = sum(1 for o in obligations if o.get("status") == "PASS")
        cert_pass = status == "COMPILED" and cert_overall == "PASS"

        from veritx_dse.application.evaluation_context import (
            EvaluationContextError, build_evaluation_context,
        )
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        from veritx_dse.backend.adapter import SupportLevel
        from veritx_dse.backend.booksim_adapter import (
            BookSimProjectionRefusal,
        )
        binary = self.config.booksim_bin
        backend_configured = binary is not None and Path(binary).is_file()

        if not backend_configured:
            producer_status = "NOT_AVAILABLE"
            producer_reason = (
                "no qualified backend configured (set "
                "VERITX_BOOKSIM_BIN)")
        else:
            from veritx_dse.backend.booksim_execution import (
                BOOKSIM_BUILD_RECIPE_VERSION,
            )
            from veritx_dse.backend.producer import (
                ProducerError, assert_pinned_producer,
                resolve_producer_identity,
            )
            try:
                producer = resolve_producer_identity(
                    Path(binary), repo_root=self.config.repo_root,
                    require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
                assert_pinned_producer(producer)
            except ProducerError as exc:
                producer_status = "NOT_QUALIFIED"
                producer_reason = (
                    f"BookSim producer not qualified: {exc}")
            else:
                producer_status = "QUALIFIED"
                producer_reason = None

        profile_id: str | None = None
        profile_reason: str | None = None
        support = SupportLevel.UNSUPPORTED
        plan_reason: str | None = None
        if cert_pass:
            request_doc = revision.get("request")
            request = (parse_request_doc(request_doc)
                       if request_doc else None)
            if request is None:
                raise ProductServiceError(
                    ErrorCode.NOT_FOUND,
                    "the revision does not carry a parsable request")
            try:
                compiled = FabricCompiler().compile(request)
                if compiled.status != "COMPILED":
                    profile_reason = (
                        compiled.error
                        or "the stored request no longer compiles")
                else:
                    context = build_evaluation_context(compiled)
                    row = self._network_support_row(
                        context, self._registry)
                    support = row.support
                    plan_reason = row.reason
                    if support is SupportLevel.UNSUPPORTED:
                        profile_reason = (
                            plan_reason
                            or "no registered backend represents this "
                            "workload")
                    else:
                        adapter = self._registry.get("BOOKSIM_STANDALONE")
                        if adapter is None:
                            profile_reason = (
                                "no BookSim adapter is registered")
                        else:
                            prepared = adapter.prepare(
                                context, EvaluationQuestion.NETWORK_COMPLETION,
                                traffic_class=(
                                    context.unified_traffic_class))
                            profile_id = (
                                prepared.qualification_identity)
                            if profile_id is None:
                                profile_reason = (
                                    "the BookSim preparation named no "
                                    "execution profile")
            except (EvaluationContextError, _LoweringInvalid,
                    _LoweringSemantics, _LoweringSchedule,
                    _LoweringMappingInvalid,
                    BookSimProjectionRefusal) as exc:
                profile_reason = (
                    "the certified execution profile refused this "
                    f"design: {type(exc).__name__}: {str(exc)[:220]}")

        backend_state = (
            "MISSING" if not backend_configured
            else "READY" if (support is not SupportLevel.UNSUPPORTED
                               and profile_id is not None)
            else "REFUSED")
        backend_reason = (
            producer_reason if not backend_configured
            else None if profile_id is not None
            and support is not SupportLevel.UNSUPPORTED
            else (profile_reason or plan_reason))
        gates: list[dict[str, Any]] = [
            {
                "gate": "compilation",
                "state": ("READY" if status == "COMPILED"
                          else (status or "NOT_COMPILED")),
                "reason": (None if status == "COMPILED"
                           else compilation.get("error")
                           or f"compilation is {status or 'absent'}"),
            },
            {
                "gate": "certificate",
                "state": ("READY" if cert_pass
                          else (cert_overall or "NOT_CERTIFIED")),
                "reason": (None if cert_pass
                           else ("certificate is not PASS"
                                 if cert_overall is not None
                                 else "no certificate exists for this "
                                 "revision")),
                "obligations_passed": passed if obligations else None,
                "obligations_total": len(obligations) or None,
            },
            {
                "gate": "backend",
                "state": backend_state,
                "reason": backend_reason,
            },
            {
                "gate": "producer_qualification",
                "state": producer_status,
                "reason": producer_reason,
            },
        ]
        ready = (cert_pass and backend_state == "READY"
                 and producer_status == "QUALIFIED")
        return {
            "contract_version": 1,
            "revision_id": revision_id,
            "display_name": revision.get("display_name"),
            "backend": "booksim_standalone",
            "backend_profile": profile_id,
            "network_clock_hz": self.config.network_clock_hz,
            "expected_evidence_tier": ("authenticated backend evidence + "
                                       "run bundle" if ready else None),
            "route_observation_required": True,
            "conservation_required": True,
            "gates": gates,
            "ready": ready,
            "reason": (None if ready
                       else "; ".join(
                           g.get("reason") for g in gates
                           if g.get("reason")) or None),
        }

    def run_integrity(self, run_id: str) -> dict[str, Any]:
        """ExecutionIntegrityView — conservation + route realization.

Rationale: docs/decisions/modules/product.md
        """
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="run_integrity", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        if self._verify_run_bundle(run) is None:
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"run {run_id} has no finalized run bundle; no execution "
                "integrity evidence exists",
                operation="run_integrity", resource_id=run_id)
        bundle_dir = self.store.run_bundle_dir(pid, run_id)
        analyses = run.get("analyses")
        if analyses:
            return self._federated_integrity(run_id, run, bundle_dir,
                                             analyses)
        doc = None
        for rel in ("run/backend-evidence.json",
                    "backend-evidence.json"):
            if (bundle_dir / rel).is_file():
                raw = self._read_trust_file(bundle_dir, rel)
                try:
                    doc = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ProductServiceError(
                        ErrorCode.EVIDENCE_INVALID,
                        f"run {run_id} evidence document {rel} is "
                        f"unreadable: {exc}",
                        operation="run_integrity",
                        resource_id=run_id) from exc
                break
        if doc is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                f"run {run_id} carries no backend evidence document",
                operation="run_integrity", resource_id=run_id)
        try:
            evidence = doc["evidence"]
            stats = evidence["stats"]
        except (KeyError, TypeError) as exc:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"run {run_id} evidence document is unreadable: {exc}",
                operation="run_integrity", resource_id=run_id) from exc
        projection = self._booksim_integrity(evidence, stats)
        return {
            "contract_version": 1,
            "run_id": run_id,
            **projection,
            "evidence_id": run.get("evidence", {}).get("evidence_id")
            if isinstance(run.get("evidence"), dict) else None,
            "analyses": None,
        }

    @staticmethod
    def _booksim_integrity(evidence: dict[str, Any],
                           stats: dict[str, Any]) -> dict[str, Any]:
        """The BookSim packet/flit/route projection. BookSim evidence
        only — never rendered for another backend's counters."""

        def counter(key: str) -> dict[str, Any]:
            value = stats.get(key)
            if value is None:
                return {"value": None, "availability": "NOT_AVAILABLE"}
            return {"value": value, "availability": "MEASURED"}

        packets_injected = stats.get("injected_trace_packets")
        packets_delivered = stats.get("delivered_packets")
        flits_injected = stats.get("flits_injected")
        flits_accepted = stats.get("flits_accepted")

        def conserved(injected: Any, delivered: Any) -> str:
            if injected is None or delivered is None:
                return "NOT_MEASURED"
            return "CONSERVED" if injected == delivered else "VIOLATED"

        route_observation = evidence.get("route_observation")
        realized = route_observation == "EXECUTED_ROUTE_OBSERVED"
        return {
            "packet_conservation": {
                "declared": counter("declared_packets"),
                "loaded": counter("loaded_trace_packets"),
                "injected": counter("injected_trace_packets"),
                "delivered": counter("delivered_packets"),
                "verdict": conserved(packets_injected, packets_delivered),
            },
            "flit_conservation": {
                "declared": counter("declared_flits"),
                "injected": counter("flits_injected"),
                "accepted": counter("flits_accepted"),
                "verdict": conserved(flits_injected, flits_accepted),
            },
            "route_realization": {
                "status": ("OBSERVED" if realized
                           else "NOT_OBSERVED"),
                "scope": "destination-aware first-hop realization",
                "full_path_claimed": False,
                "realized_digest": evidence.get("route_dump_sha256"),
            },
        }

    def _federated_integrity(self, run_id: str, run: dict[str, Any],
                             bundle_dir: Path,
                             analyses: list[dict[str, Any]]
                             ) -> dict[str, Any]:
        """Per-analysis integrity for a federated run.

        The network tables render only for an EVALUATED BookSim
        NETWORK_COMPLETION analysis; every ASTRA analysis reports its
        own factual fields. A BookSim integrity table is never rendered
        for non-BookSim evidence.
        """
        per_analysis: dict[str, Any] = {}
        network_projection: dict[str, Any] | None = None
        for analysis in analyses:
            question = analysis.get("question")
            backend = analysis.get("backend_id")
            status = analysis.get("status")
            key = str(question).lower() if question else "unknown"
            if backend == "BOOKSIM_STANDALONE" and status == "EVALUATED":
                doc = self._analysis_evidence_doc(
                    run_id, bundle_dir, key)
                network_projection = self._booksim_integrity(
                    doc["evidence"], doc["evidence"]["stats"])
                per_analysis[key] = {
                    "backend": backend, "status": status,
                    "kind": "network_packet_integrity",
                    **network_projection,
                }
            elif backend == "ASTRA2_EMBEDDED_BOOKSIM":
                per_analysis[key] = self._astra_integrity(analysis)
            elif backend == "RAMULATOR2_HBM3_V1":
                per_analysis[key] = self._ramulator_integrity(analysis)
            else:
                per_analysis[key] = {
                    "backend": backend, "status": status,
                    "reason": analysis.get("reason"),
                }
        response: dict[str, Any] = {
            "contract_version": 1,
            "run_id": run_id,
            "packet_conservation": (
                None if network_projection is None
                else network_projection["packet_conservation"]),
            "flit_conservation": (
                None if network_projection is None
                else network_projection["flit_conservation"]),
            "route_realization": (
                None if network_projection is None
                else network_projection["route_realization"]),
            "evidence_id": run.get("evidence", {}).get("evidence_id")
            if isinstance(run.get("evidence"), dict) else None,
            "analyses": per_analysis,
        }
        return response

    def _analysis_evidence_doc(self, run_id: str, bundle_dir: Path,
                               analysis_key: str) -> dict[str, Any]:
        """The authenticated BookSim evidence wrapper for one analysis.

        Raises EVIDENCE_INVALID when the document is absent, unreadable
        or structurally wrong: an EVALUATED analysis without evidence
        is corruption, never a soft error field.
        """
        candidates = (
            f"analyses/{analysis_key}/evidence/backend-evidence.json",
            f"analyses/{analysis_key}/run/backend-evidence.json",
        )
        for rel in candidates:
            if not (bundle_dir / rel).is_file():
                continue
            raw = self._read_trust_file(bundle_dir, rel)
            try:
                doc = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ProductServiceError(
                    ErrorCode.EVIDENCE_INVALID,
                    f"run {run_id} analysis {analysis_key} evidence "
                    f"document is unreadable: {exc}",
                    operation="run_integrity",
                    resource_id=run_id) from exc
            evidence = doc.get("evidence")
            if isinstance(evidence, dict) \
                    and isinstance(evidence.get("stats"), dict):
                return doc
            if isinstance(doc.get("evidence_id"), str) \
                    and isinstance(doc.get("stats"), dict):
                return {"evidence": doc}
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"run {run_id} analysis {analysis_key} evidence "
                f"document carries no scientific evidence with stats",
                operation="run_integrity", resource_id=run_id)
        raise ProductServiceError(
            ErrorCode.EVIDENCE_INVALID,
            f"run {run_id} analysis {analysis_key} evidence document "
            f"is absent from the bundle",
            operation="run_integrity", resource_id=run_id)

    @staticmethod
    def _astra_integrity(analysis: dict[str, Any]) -> dict[str, Any]:
        """Factual ASTRA integrity — namespace, tier, injection, never a
        BookSim packet table."""
        summary = analysis.get("native_summary") or {}
        if analysis.get("status") != "EVALUATED":
            return {
                "backend": analysis.get("backend_id"),
                "status": analysis.get("status"),
                "reason": analysis.get("reason"),
            }
        return {
            "backend": analysis.get("backend_id"),
            "status": analysis.get("status"),
            "kind": "astra_system_integrity",
            "native_evidence_id": analysis.get("native_evidence_id"),
            "evidence_tier": summary.get("evidence_tier"),
            "expansion_authority": summary.get("expansion_authority"),
            "autonomous_injection_packets": summary.get(
                "autonomous_injection_packets"),
            "participant_statistics_present": summary.get(
                "participant_statistics_present"),
            "namespace_binding": summary.get("namespace_binding"),
            "namespace_id": summary.get("namespace_id"),
        }

    @staticmethod
    def _ramulator_integrity(analysis: dict[str, Any]) -> dict[str, Any]:
        """Factual Ramulator integrity — drain reconciliation and
        completed bytes from the native summary, never a BookSim packet
        table and never re-derived science."""
        summary = analysis.get("native_summary") or {}
        if analysis.get("status") != "EVALUATED":
            return {
                "backend": analysis.get("backend_id"),
                "status": analysis.get("status"),
                "reason": analysis.get("reason"),
            }
        return {
            "backend": analysis.get("backend_id"),
            "status": analysis.get("status"),
            "kind": "memory_drain_integrity",
            "native_evidence_id": analysis.get("native_evidence_id"),
            "drain": {
                "generated_requests": summary.get("generated_requests"),
                "accepted_requests": summary.get("accepted_requests"),
                "completed_requests": summary.get("completed_requests"),
                "outstanding_requests":
                    summary.get("outstanding_requests"),
            },
            "completed_read_bytes": summary.get("completed_read_bytes"),
            "completed_write_bytes": summary.get("completed_write_bytes"),
            "completion_cycles": summary.get("completion_cycles"),
        }

    def verify_run(self, run_id: str) -> dict[str, Any]:
        """Re-verify a run's RunBundle on demand (thin adapter).

        All verification semantics live in ``core.run_bundle``; this
        method only locates the run, delegates, and projects the summary.
        Every read path already verifies; this is the explicit product
        action for the UI's Verify Bundle button.
        """
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="verify_run", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        summary = self._verify_run_bundle(run)
        if summary is None:
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"run {run_id} has no finalized run bundle to verify "
                "(a refused evaluation produces no evidence)",
                operation="verify_run", resource_id=run_id)
        return {
            "contract_version": 1,
            "run_id": run_id,
            "status": "VERIFIED",
            "bundle_id": "sha256:" + summary["bundle_id"],
            "file_count": summary["file_count"],
            "files_checked": summary["file_count"],
        }

    def submit_reproduction(self, run_id: str) -> dict[str, Any]:
        """Submit a reproduction Job over the canonical reproduce authority.

Rationale: docs/decisions/modules/product.md
        """
        pid = self.store.find_run_project(run_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND, f"no such run: {run_id}",
                operation="submit_reproduction", resource_id=run_id)
        run = self.store.load_run(pid, run_id)
        if self._verify_run_bundle(run) is None:
            raise ProductServiceError(
                ErrorCode.CONFLICT,
                f"run {run_id} has no finalized run bundle to reproduce",
                operation="submit_reproduction", resource_id=run_id)
        bundle_dir = self.store.run_bundle_dir(pid, run_id)
        if run.get("analyses"):
            job = self.jobs.submit(
                pid, kind="REPRODUCTION",
                revision_id=run.get("revision_id"),
                fn=lambda progress: self._run_federated_reproduction(
                    run_id, bundle_dir, run.get("analyses"), progress))
            return self.job_view(job)
        binary = self._require_backend()
        job = self.jobs.submit(
            pid, kind="REPRODUCTION", revision_id=run.get("revision_id"),
            fn=lambda progress: self._run_reproduction(
                run_id, bundle_dir, binary, progress))
        return self.job_view(job)

    def _run_federated_reproduction(
            self, run_id: str, bundle_dir: Path,
            analyses: list[dict[str, Any]],
            progress) -> tuple[str, dict[str, Any]]:
        """Reproduce each executed analysis through its own backend."""
        progress("RUNNING")
        reproductions: dict[str, Any] = {}
        for analysis in analyses:
            question = str(analysis.get("question", "unknown"))
            key = question.lower()
            reproductions[key] = self._reproduce_analysis(
                bundle_dir, key, analysis)
        progress("FINALIZING")
        return "COMPLETED", {"run_id": run_id,
                             "reproductions": reproductions}

    def _reproduce_analysis(self, bundle_dir: Path, key: str,
                            analysis: dict[str, Any]) -> dict[str, Any]:
        """One analysis, its own backend, honest unavailability."""
        from veritx_dse.core.run_bundle import RunBundleError
        backend = analysis.get("backend_id")
        if analysis.get("status") != "EVALUATED":
            return {"backend": backend, "status": "NOT_EXECUTED",
                    "outcome": "NOT_EXECUTED",
                    "reason": analysis.get("reason")
                    or "the analysis never executed; nothing to reproduce"}
        analysis_dir = bundle_dir / "analyses" / key
        if backend == "BOOKSIM_STANDALONE":
            return self._reproduce_booksim_analysis(
                bundle_dir, analysis_dir, backend)
        if backend == "ASTRA2_EMBEDDED_BOOKSIM":
            return self._reproduce_astra_analysis(
                bundle_dir, analysis_dir, backend)
        if backend == "RAMULATOR2_HBM3_V1":
            return self._reproduce_ramulator_analysis(
                bundle_dir, analysis_dir, backend)
        return {"backend": backend, "status": "EVALUATED",
                "outcome": "REPRODUCTION_NOT_AVAILABLE",
                "reason": f"no reproduction authority for backend "
                f"{backend!r}"}

    def _reproduce_booksim_analysis(self, bundle_dir: Path,
                                    analysis_dir: Path,
                                    backend: str) -> dict[str, Any]:
        from veritx_dse.backend.reproduce import (
            reproduce_booksim_run_bundle,
        )
        from veritx_dse.core.run_bundle import RunBundleError
        binary = self.config.booksim_bin
        if binary is None or not Path(binary).is_file():
            return {"backend": backend, "status": "EVALUATED",
                    "outcome": "REPRODUCTION_NOT_AVAILABLE",
                    "reason": "no BookSim binary configured here"}
        run_subdir = analysis_dir / "run"
        if not (run_subdir / "backend-evidence.json").is_file():
            return {"backend": backend, "status": "EVALUATED",
                    "outcome": "REPRODUCTION_NOT_AVAILABLE",
                    "reason": "the analysis bundle carries no BookSim "
                    "execution record to rerun"}
        try:
            result = reproduce_booksim_run_bundle(
                run_subdir, binary=str(binary),
                timeout=self.config.timeout_s)
        except RunBundleError as exc:
            return {"backend": backend, "status": "EVALUATED",
                    "outcome": "DIVERGED",
                    "reason": f"reproduction refused: {exc}"}
        return {"backend": backend, "status": "EVALUATED",
                "outcome": ("SCIENTIFICALLY_REPRODUCED"
                            if result.get("matched") else "DIVERGED"),
                "reproduced_stats": result.get("stats"),
                "route_dump_sha256": result.get("route_dump_sha256")}

    def _reproduce_astra_analysis(self, bundle_dir: Path,
                                  analysis_dir: Path,
                                  backend: str) -> dict[str, Any]:
        from veritx_dse.backend.reproduce_astra import (
            reproduce_astra_run_bundle,
        )
        from veritx_dse.core.run_bundle import RunBundleError
        binary = self.config.astra_bin
        if binary is not None and not Path(binary).is_file():
            binary = None
        if binary is None:
            from veritx_dse.backend.astra import resolve_runtime_binary
            binary = resolve_runtime_binary()
        if binary is None:
            return {"backend": backend, "status": "EVALUATED",
                    "outcome": "REPRODUCTION_NOT_AVAILABLE",
                    "reason": "no ASTRA runtime binary available here"}
        try:
            result = reproduce_astra_run_bundle(
                analysis_dir, binary=str(binary),
                timeout=self.config.timeout_s)
        except RunBundleError as exc:
            message = str(exc)
            if "NOT_AVAILABLE" in message:
                return {"backend": backend, "status": "EVALUATED",
                        "outcome": "REPRODUCTION_NOT_AVAILABLE",
                        "reason": message}
            return {"backend": backend, "status": "EVALUATED",
                    "outcome": "DIVERGED", "reason": message}
        return {"backend": backend, "status": "EVALUATED",
                "outcome": ("SCIENTIFICALLY_REPRODUCED"
                            if result.get("matched") else "DIVERGED"),
                "evidence_id": result.get("evidence_id"),
                "aggregate_cycles": result.get("aggregate_cycles")}

    def _reproduce_ramulator_analysis(self, bundle_dir: Path,
                                      analysis_dir: Path,
                                      backend: str) -> dict[str, Any]:
        from veritx_dse.backend.reproduce_ramulator import (
            reproduce_ramulator_run_bundle,
        )
        from veritx_dse.core.run_bundle import RunBundleError
        try:
            result = reproduce_ramulator_run_bundle(
                analysis_dir,
                vendor_dir=self.config.ramulator_vendor_dir,
                python_exe=self.config.ramulator_python,
                timeout=self.config.timeout_s)
        except RunBundleError as exc:
            message = str(exc)
            if "NOT_AVAILABLE" in message:
                return {"backend": backend, "status": "EVALUATED",
                        "outcome": "REPRODUCTION_NOT_AVAILABLE",
                        "reason": message}
            return {"backend": backend, "status": "EVALUATED",
                    "outcome": "DIVERGED", "reason": message}
        return {"backend": backend, "status": "EVALUATED",
                "outcome": ("SCIENTIFICALLY_REPRODUCED"
                            if result.get("matched") else "DIVERGED"),
                "evidence_id": result.get("evidence_id"),
                "rerun_status": result.get("status")}

    def _run_reproduction(self, run_id: str, bundle_dir: Path,
                          binary: Path, progress) -> tuple[str, dict[str, Any]]:
        progress("RUNNING")
        from veritx_dse.backend.reproduce import reproduce_booksim_run_bundle

        try:
            result = reproduce_booksim_run_bundle(
                bundle_dir, binary=str(binary),
                timeout=self.config.timeout_s)
        except RunBundleError as exc:
            raise ProductServiceError(
                ErrorCode.EVIDENCE_INVALID,
                f"reproduction refused: {exc}",
                operation="reproduce_run", resource_id=run_id) from exc
        matched = bool(result.get("matched"))
        progress("FINALIZING")
        return "COMPLETED", {
            "run_id": run_id,
            "outcome": ("SCIENTIFICALLY_REPRODUCED" if matched
                        else "DIVERGED"),
            "bundle_id": result.get("bundle_id"),
            "reproduced_stats": result.get("stats"),
            "route_dump_sha256": result.get("route_dump_sha256"),
        }

    _SERVING_CLUSTER_CONFIG = ("third_party/llmservingsim/configs/cluster/"
                               "single_node_4_instance_2TP.json")
    _SERVING_DATASET = ("third_party/llmservingsim/workloads/"
                        "example_trace.jsonl")

    @staticmethod
    def _resolve_serving_input(value: str | None,
                               default: str) -> Path:
        """A serving input path: the tracked default, or a caller-supplied
        absolute/repo-relative path. The canonical loader still validates
        the contents — the product layer never parses service semantics."""
        if value:
            candidate = Path(value)
            if candidate.is_absolute():
                return candidate
            return REPO / candidate
        return REPO / default

    def list_serving(self, project_id: str) -> list[dict[str, Any]]:
        self.store.load_project(project_id)
        return self.store.list_serving(project_id)

    def get_serving(self, serving_id: str) -> dict[str, Any]:
        pid = self.store.find_serving_project(serving_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                f"no such serving experiment: {serving_id}",
                operation="get_serving", resource_id=serving_id)
        return self.store.load_serving(pid, serving_id)

    def serving_binding(self, project_id: str) -> dict[str, Any]:
        self.store.load_project(project_id)
        binding = self.store.load_serving_binding(project_id)
        return {"contract_version": 1, "project_id": project_id,
                "binding": binding}

    def clear_serving_binding(self, project_id: str) -> dict[str, Any]:
        self.store.load_project(project_id)
        self.store.clear_serving_binding(project_id)
        return {"contract_version": 1, "project_id": project_id,
                "binding": None}

    def bind_serving(self, project_id: str,
                     body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Bind one cluster×trace serving experiment to this project.

        Binding is explicit and validated: the files must exist and the
        cluster semantics must parse. The binding records the design/revision
        identity it was made against (provenance only — the design still comes
        from the evaluated revision), plus model and hardware identity.
        """
        project = self.store.load_project(project_id)
        body = body or {}
        cluster = self._resolve_serving_input(
            body.get("cluster_config"), self._SERVING_CLUSTER_CONFIG)
        dataset = self._resolve_serving_input(
            body.get("dataset"), self._SERVING_DATASET)
        if not cluster.is_file():
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"cluster service-semantics config not found: {cluster}",
                operation="bind_serving", resource_id=project_id)
        if not dataset.is_file():
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"request dataset not found: {dataset}",
                operation="bind_serving", resource_id=project_id)
        num_reqs = int(body.get("num_reqs") or 8)
        overrides = self._serving_profile_overrides(
            body.get("profile_overrides"))
        timeout_s = self._serving_timeout(body.get("timeout_s"))
        from veritx_dse.backend.serving_adapter import (
            ServingAdapter, ServingExperiment, ServingSemanticRefusal,
            _model_matches,
        )
        experiment = ServingExperiment(
            cluster_config=cluster, dataset=dataset, num_reqs=num_reqs,
            profile_overrides=overrides or None, timeout_s=timeout_s)
        try:
            ServingAdapter._validate_experiment(experiment)
        except ServingSemanticRefusal as exc:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"serving experiment refused: {exc}",
                operation="bind_serving", resource_id=project_id) from exc
        revision_id = project.get("active_revision_id")
        revision = (self.store.load_revision(project_id, revision_id)
                    if revision_id else None)
        facts = ServingAdapter.serving_cluster_facts(experiment)
        if not facts["internally_consistent"]:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                "serving cluster is internally inconsistent: an instance's "
                "EP size exceeds its TP span (the serving loop binds TP/EP "
                "groups inside one instance and never multiplies ranks)",
                operation="bind_serving", resource_id=project_id)
        serving_ranks = facts["ranks"]
        design_ranks = None
        design_model = None
        if revision is not None:
            try:
                wl = parse_request_doc(revision["request"]).workload
                design_ranks = (int(wl.tp) * int(wl.pp)
                                * int(wl.ep) * int(wl.dp))
                design_model = wl.model_name
            except Exception:  # noqa: BLE001 - no design → no compat claim
                design_ranks = None
        if design_ranks is not None and serving_ranks != design_ranks:
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"serving cluster serves {serving_ranks} rank(s) but the "
                f"design places {design_ranks}; no compatible binding",
                operation="bind_serving", resource_id=project_id)
        if design_model and not _model_matches(facts["models"], design_model):
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"serving cluster profiles {facts['models']} but the design "
                f"is {design_model!r}; no compatible binding",
                operation="bind_serving", resource_id=project_id)
        harness = getattr(experiment, "experiment_id", None)
        model_name = None
        hardware = None
        try:
            import json as _json
            doc = _json.loads(Path(cluster).read_text(encoding="utf-8"))
            for node in doc.get("nodes", ()):
                for inst in node.get("instances", ()):
                    model_name = model_name or inst.get("model_name")
                    hardware = hardware or inst.get("hardware")
        except (OSError, ValueError):
            pass
        binding = {
            "binding_id": harness() if callable(harness) else None,
            "cluster_config": str(cluster),
            "dataset": str(dataset),
            "num_reqs": num_reqs,
            "profile_overrides": overrides,
            "timeout_s": timeout_s,
            "model_name": model_name,
            "hardware": hardware,
            "serving_ranks": serving_ranks,
            "design_ranks": design_ranks,
            "compatible": design_ranks is None or serving_ranks == design_ranks,
            "bound_revision_id": revision_id,
            "bound_design_hash": (revision or {}).get("design_hash"),
            "bound_at": utcnow(),
        }
        self.store.save_serving_binding(project_id, binding)
        return {"contract_version": 1, "project_id": project_id,
                "binding": binding}

    def _serving_run_options(self, project_id: str) -> Any | None:
        """The serving leg's execution options from the project binding.

        Without a binding there is nothing to execute — the leg stays a
        typed refusal, never a fabricated result.
        """
        binding = self.store.load_serving_binding(project_id)
        if binding is None:
            return None
        from veritx_dse.application.federated_evaluator import (
            ServingRunOptions,
        )
        return ServingRunOptions(
            cluster_config=binding["cluster_config"],
            dataset=binding["dataset"],
            num_reqs=int(binding.get("num_reqs") or 8),
            profile_overrides=binding.get("profile_overrides") or None,
            timeout_s=int(binding.get("timeout_s") or 900))

    def _serving_experiment_for(self, project_id: str) -> Any | None:
        binding = self.store.load_serving_binding(project_id)
        if binding is None:
            return None
        from veritx_dse.backend.serving_adapter import ServingExperiment
        return ServingExperiment(
            cluster_config=binding["cluster_config"],
            dataset=binding["dataset"],
            num_reqs=int(binding.get("num_reqs") or 8),
            profile_overrides=binding.get("profile_overrides") or None,
            timeout_s=int(binding.get("timeout_s") or 900))

    def registry_for(self, project_id: str) -> Any:
        """The backend registry for a project, with the serving adapter
        bound when an experiment is bound — otherwise the default registry
        (serving stays honestly BLOCKED)."""
        experiment = self._serving_experiment_for(project_id)
        if experiment is None:
            return self._registry
        from veritx_dse.backend.registry import BackendRegistry
        from veritx_dse.backend.serving_adapter import ServingAdapter
        adapters = tuple(
            ServingAdapter(experiment=experiment,
                           repo_root=self.config.repo_root)
            if getattr(a, "backend_id", None) == "CANONICAL_SERVING" else a
            for a in self._registry.adapters())
        return BackendRegistry(adapters)

    def submit_serving(self, project_id: str,
                       body: dict[str, Any] | None = None) -> dict[str, Any]:
        """Submit a canonical serving experiment as a Job.

Rationale: docs/decisions/modules/product.md
        """
        self.store.load_project(project_id)
        body = body or {}
        cluster = self._resolve_serving_input(
            body.get("cluster_config"), self._SERVING_CLUSTER_CONFIG)
        dataset = self._resolve_serving_input(
            body.get("dataset"), self._SERVING_DATASET)
        if not cluster.is_file():
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"cluster service-semantics config not found: {cluster}",
                operation="submit_serving", resource_id=project_id)
        if not dataset.is_file():
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"request dataset not found: {dataset}",
                operation="submit_serving", resource_id=project_id)
        self._require_backend()
        num_reqs = int(body.get("num_reqs") or 8)
        overrides = self._serving_profile_overrides(
            body.get("profile_overrides"))
        timeout_s = self._serving_timeout(body.get("timeout_s"))
        serving_id = _new_id("sv")
        self.store.create_serving(project_id, {
            "schema_version": 1,
            "serving_id": serving_id,
            "project_id": project_id,
            "state": "QUEUED",
            "workload_id": body.get("workload_id"),
            "num_reqs": num_reqs,
            "profile_overrides": overrides,
            "timeout_s": timeout_s,
            "evidence": None,
            "created_at": utcnow(),
        })
        job = self.jobs.submit(
            project_id, kind="SERVING", revision_id=None,
            fn=lambda progress: self._run_serving(
                serving_id, cluster, dataset, num_reqs, progress,
                overrides, timeout_s))
        return self.job_view(job)

    def _run_serving(self, serving_id: str, cluster: Path, dataset: Path,
                     num_reqs: int, progress,
                     profile_overrides: dict[str, Any] | None = None,
                     timeout_s: int | None = None,
                     ) -> tuple[str, dict[str, Any]]:
        from veritx_dse.simulation.serve_canonical import (
            run_canonical_serve,
        )
        pid = self.store.find_serving_project(serving_id)
        progress("PREPARING")
        self.store.update_serving(pid, serving_id, state="RUNNING")
        run_dir = self.store.serving_dir(pid) / "_runs" / serving_id
        try:
            result = run_canonical_serve(
                cluster_config=str(cluster), dataset=str(dataset),
                num_reqs=num_reqs, run_dir=run_dir,
                profile_overrides=profile_overrides,
                timeout_s=(timeout_s if timeout_s is not None
                           else self.config.timeout_s))
        except Exception as exc:
            self.store.update_serving(
                pid, serving_id, state="REFUSED",
                error=f"{type(exc).__name__}: {exc}")
            raise
        progress("FINALIZING")
        evidence = None
        for name in ("serving-evidence.json", "evidence.json"):
            candidate = run_dir / name
            if candidate.is_file():
                evidence = json.loads(candidate.read_text(encoding="utf-8"))
                break
        normalized_doc = None
        normalized_candidate = run_dir / "normalized-serving-evidence.json"
        if normalized_candidate.is_file():
            try:
                normalized_doc = json.loads(
                    normalized_candidate.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                normalized_doc = None
        self.store.update_serving(
            pid, serving_id, state="COMPLETED",
            evidence={
                "request_count": result.requests_completed,
                "requests_expected": result.requests_expected,
                "rounds": result.rounds,
                "machine_id": result.machine_id,
                "namespace_id": result.namespace_id,
                "evidence_ids": list(result.evidence_ids),
                "document": evidence,
                "normalized_analyses": (
                    None if normalized_doc is None
                    else normalized_doc.get("analyses")),
                "normalization_reason": (
                    "serving run predates normalized serving archival"
                    if normalized_doc is None
                    else normalized_doc.get("reason")),
            })
        return "COMPLETED", {"serving_id": serving_id}

    def submit_optimization(self, revision_id: str,
                            body: dict[str, Any]) -> dict[str, Any]:
        pid, revision = self.store.load_revision_global(revision_id)
        self._require_evaluable_request(revision, "submit_optimization")
        definition_doc = self._parse_definition(body)
        needs_network = any(
            o.get("question") == "NETWORK_COMPLETION"
            for o in definition_doc["objectives"])
        binary = self._require_backend() if needs_network else None
        job = self.jobs.submit(
            pid, kind="OPTIMIZATION", revision_id=revision_id,
            fn=lambda progress: self._run_optimization(
                pid, revision, binary, definition_doc, progress))
        return self.job_view(job)

    _OPTIMIZATION_KEYS = frozenset({
        "domain", "objectives", "constraints", "method", "budget",
        "seed", "selection",
    })

    _OBJECTIVE_KEYS = frozenset({
        "metric", "direction", "question", "backend_id",
    })

    @staticmethod
    def _parse_objective(o: dict[str, Any]) -> dict[str, Any]:
        """Normalize one product objective into the canonical shape."""
        if not isinstance(o, dict):
            raise intent_error(
                f"malformed optimization objective {o!r}: must be an "
                f"object with metric/direction (+ optional "
                f"question/backend_id)")
        unknown = sorted(set(o) - ProductService._OBJECTIVE_KEYS)
        if unknown:
            raise intent_error(
                f"unknown optimization objective option(s) {unknown}; "
                f"supported: {sorted(ProductService._OBJECTIVE_KEYS)}")
        try:
            metric = o["metric"]
            direction = o["direction"]
        except KeyError as exc:
            raise intent_error(
                f"malformed optimization objective: {exc}") from exc
        question = o.get("question", "NETWORK_COMPLETION")
        backend_id = o.get("backend_id")
        if question is None:
            question = "NETWORK_COMPLETION"
        if not isinstance(question, str) or not question:
            raise intent_error(
                f"optimization objective question must name an "
                f"EvaluationQuestion, got {question!r}")
        from veritx_dse.application.evaluation_question import (
            EvaluationQuestion,
        )
        names = {q.value for q in EvaluationQuestion}
        if question not in names:
            raise intent_error(
                f"unknown optimization objective question {question!r}; "
                f"supported: {sorted(names)}")
        if backend_id is not None and (
                not isinstance(backend_id, str) or not backend_id):
            raise intent_error(
                f"optimization objective backend_id must be a backend id "
                f"string or null, got {backend_id!r}")
        return {"metric": metric, "direction": direction,
                "question": question, "backend_id": backend_id}

    @staticmethod
    def _parse_definition(body: dict[str, Any]) -> dict[str, Any]:
        """Normalize a product optimization body into the canonical shape.

Rationale: docs/decisions/modules/product.md
        """
        unknown = sorted(set(body) - ProductService._OPTIMIZATION_KEYS)
        if unknown:
            from veritx_dse.optimization.definition import (
                SELECTION_POLICIES, SEARCH_METHODS,
            )
            raise intent_error(
                f"unknown optimization option(s) {unknown}; supported: "
                f"domain, objectives, constraints, method "
                f"{list(SEARCH_METHODS)}, budget "
                "{max_candidates, max_evaluations}, seed, selection "
                f"{list(SELECTION_POLICIES)}")
        try:
            domain = [{"name": d["name"], "values": list(d["values"])}
                      for d in body.get("domain", [])]
            objectives = [ProductService._parse_objective(o)
                          for o in body.get(
                              "objectives",
                              [{"metric": "completion_cycles",
                                "direction": "MIN"}])]
            constraints = [{"metric": c["metric"], "op": c["op"],
                            "threshold": c["threshold"]}
                           for c in body.get("constraints", [])]
            method = body.get("method", "grid")
            selection = body.get("selection")
            seed = body.get("seed")
            raw_budget = body.get("budget")
            if raw_budget is None:
                budget: dict[str, Any] = {}
            elif isinstance(raw_budget, dict):
                budget = dict(raw_budget)
            else:
                raise intent_error(
                    "optimization budget must be an object with "
                    "max_candidates / max_evaluations")
        except (KeyError, TypeError) as exc:
            raise intent_error(f"malformed optimization definition: {exc}") from exc
        if not domain:
            raise intent_error("optimization requires a non-empty domain")
        return {"domain": domain, "objectives": objectives,
                "constraints": constraints, "method": method,
                "budget": budget,
                "selection": selection if selection is not None
                else "min_first_objective",
                "seed": seed}

    def _run_optimization(self, project_id: str, revision: dict[str, Any],
                          binary: Path | None, definition_doc: dict[str, Any],
                          progress) -> tuple[str, dict[str, Any]]:
        from veritx_dse.model.compile_model import CompileRequestV3
        from veritx_dse.optimization.definition import (
            Constraint, DomainParam, Objective, OptimizationDefinition,
        )
        from veritx_dse.optimization.result import (
            CertifiedBackendConfig, Optimizer,
        )
        request = parse_request_doc(revision["request"])
        if not isinstance(request, CompileRequestV3):
            raise ProductServiceError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                "certified optimization requires a v3 design request",
                operation="optimize")
        try:
            definition = OptimizationDefinition(
                domain=tuple(DomainParam(d["name"], tuple(d["values"]))
                             for d in definition_doc["domain"]),
                objectives=tuple(Objective(
                    o["metric"], o["direction"],
                    question=o.get("question") or "NETWORK_COMPLETION",
                    backend_id=o.get("backend_id"))
                    for o in definition_doc["objectives"]),
                constraints=tuple(Constraint(c["metric"], c["op"],
                                             c["threshold"])
                                  for c in definition_doc["constraints"]),
                method=definition_doc["method"],
                budget=definition_doc["budget"],
                seed=definition_doc["seed"],
                selection=definition_doc["selection"])
        except (KeyError, TypeError, ValueError) as exc:
            raise intent_error(
                f"optimization definition is invalid: {exc}") from exc
        run_root = (self.store.project_dir(project_id) / "optimizations"
                    / "_runs" / _new_id("run"))
        progress("RUNNING")
        study = Optimizer().optimize_certified(
            request, definition,
            backend_config=CertifiedBackendConfig(
                binary=(str(binary) if binary is not None else None),
                network_clock_hz=self.config.network_clock_hz,
                timeout_s=self.config.timeout_s,
                run_root=str(run_root), repo_root=str(self.config.repo_root),
                astra_binary=(None if self.config.astra_bin is None
                              else str(self.config.astra_bin)),
                ramulator_vendor_dir=(
                    None if self.config.ramulator_vendor_dir is None
                    else str(self.config.ramulator_vendor_dir)),
                ramulator_python=self.config.ramulator_python))
        view = study.to_study_view()
        optimization_id = _new_id("opt")
        runs = self.store.list_runs(project_id=project_id)
        by_result: dict[str, str] = {}
        for run in runs:
            evaluation = run.get("evaluation") or {}
            result_id = evaluation.get("performance_result_id")
            if result_id:
                by_result[result_id] = run["run_id"]
        candidate_runs = []
        for candidate in view.get("candidates", []):
            evaluation_ids = candidate.get("evaluation_ids") or {}
            result_id = evaluation_ids.get("performance_result_id")
            run_id = by_result.get(result_id)
            candidate_runs.append({
                "candidate_id": candidate["candidate_id"],
                "performance_result_id": result_id,
                "requirement_report_id":
                    evaluation_ids.get("requirement_report_id"),
                "run_id": run_id,
                "evidence_kind": ("product-run" if run_id
                                  else "optimization-candidate"),
                "evaluation_status": candidate.get("evaluation_status"),
                "evaluation_authority": candidate.get("evaluation_authority"),
            })
        optimization = {
            "schema_version": 1,
            "optimization_id": optimization_id,
            "project_id": project_id,
            "base_revision_id": revision["revision_id"],
            "created_at": utcnow(),
            "definition": definition_doc,
            "study": view,
            "candidate_runs": candidate_runs,
            "candidate_evidence_note": (
                "Candidate evidence lives in the certified optimization "
                "study (performance_result_id / requirement_report_id). A "
                "candidate is linked to a Product Run only when an existing "
                "verified run registered the same performance_result_id; "
                "otherwise its evidence_kind is 'optimization-candidate' and "
                "run_id is null."),
            "selected_candidate_id": view.get("selected_candidate_id"),
        }
        self.store.create_optimization(project_id, optimization)
        return "COMPLETED", {"optimization_id": optimization_id}

    def get_optimization(self, optimization_id: str) -> dict[str, Any]:
        pid = self.store.find_optimization_project(optimization_id)
        if pid is None:
            raise ProductServiceError(
                ErrorCode.NOT_FOUND,
                f"no such optimization: {optimization_id}",
                operation="get_optimization", resource_id=optimization_id)
        opt = self.store.load_optimization(pid, optimization_id)
        return {
            "contract_version": 1,
            "optimization_id": opt["optimization_id"],
            "project_id": opt["project_id"],
            "base_revision_id": opt["base_revision_id"],
            "created_at": opt["created_at"],
            "study": opt["study"],
            "candidate_runs": opt["candidate_runs"],
            "candidate_evidence_note": opt.get("candidate_evidence_note"),
            "selected_candidate_id": opt["selected_candidate_id"],
        }

    def compare(self, a_run_id: str, b_run_id: str) -> dict[str, Any]:
        a = self.get_run(a_run_id)
        b = self.get_run(b_run_id)
        if a.get("analyses") and b.get("analyses"):
            return self._compare_federated(a, b)
        compatibility = self._compare_compatibility(a, b)
        a_metrics = (a.get("evaluation") or {}).get("metrics") or {}
        b_metrics = (b.get("evaluation") or {}).get("metrics") or {}
        keys = sorted(set(a_metrics) | set(b_metrics))

        def numeric(value: Any) -> bool:
            return (value is not None and isinstance(value, (int, float))
                    and not isinstance(value, bool))

        rows = []
        for key in keys:
            av = a_metrics.get(key)
            bv = b_metrics.get(key)
            row_comparable = (compatibility["compatible"]
                              and numeric(av) and numeric(bv))
            if row_comparable:
                row_verdict: str = "COMPARABLE"
                row_differs: str | None = None
            elif (compatibility["same_workload"]
                    and compatibility["same_backend"]
                    and not compatibility["both_qualified"]):
                row_verdict = "QUALIFICATION_DIFFERENCE"
                row_differs = "qualification"
            elif not compatibility["compatible"]:
                row_verdict = "NOT_COMPARABLE"
                row_differs = "scenario"
            else:
                row_verdict = "MISSING_MEASUREMENT"
                row_differs = "value"
            rows.append({
                "key": key,
                "a": av,
                "b": bv,
                "comparable": row_comparable,
                "verdict": row_verdict,
                "differs": row_differs,
            })
        return {
            "contract_version": 1,
            "a": self._compare_side(a),
            "b": self._compare_side(b),
            "compatibility": compatibility,
            "rows": rows,
            "note": ("No automatic winner. Rows are marked comparable only "
                     "when both runs share a workload identity, a backend "
                     "and a QUALIFIED evidence chain, and both measured the "
                     "quantity; tradeoffs are shown as-is."),
        }

    @staticmethod
    def _federated_metric_index(
            run: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, Any]]:
        """(question, metric key, dimension coordinates) -> measurement."""
        index: dict[tuple[str, str, str], dict[str, Any]] = {}
        for analysis in run.get("analyses") or []:
            question = analysis.get("question")
            for metric in analysis.get("normalized_metrics") or []:
                dims = tuple(
                    (d[0], d[1]) for d in (metric.get("dimensions") or []))
                coords = ",".join(f"{name}={value}"
                                  for name, value in sorted(dims))
                index[(question, metric.get("key"), coords)] = {
                    "value": metric.get("value"),
                    "unit": metric.get("unit"),
                    "backend": analysis.get("backend_id"),
                    "fidelity": analysis.get("model_fidelity"),
                    "qualification": analysis.get("qualification"),
                    "native_evidence_id": analysis.get(
                        "native_evidence_id"),
                }
        return index

    def _compare_federated(self, a: dict[str, Any],
                           b: dict[str, Any]) -> dict[str, Any]:
        """Compare normalized federated evidence, one metric at a time.

        A comparison is eligible only for the same question, metric key,
        unit, dimensional coordinates, compatible model fidelity and
        acceptable qualification. Anything else is comparable=false with
        the exact difference — never a delta across models.
        """
        def numeric(value: Any) -> bool:
            return (value is not None and isinstance(value, (int, float))
                    and not isinstance(value, bool))

        a_index = self._federated_metric_index(a)
        b_index = self._federated_metric_index(b)
        a_workload = ((a.get("evaluation_plan") or {}).get("workload_id")
                      or (a.get("evaluation") or {}).get("workload_id"))
        b_workload = ((b.get("evaluation_plan") or {}).get("workload_id")
                      or (b.get("evaluation") or {}).get("workload_id"))
        same_workload = (a_workload is not None
                         and a_workload == b_workload)
        rows = []
        for key in sorted(set(a_index) | set(b_index)):
            question, metric, coords = key
            am = a_index.get(key)
            bm = b_index.get(key)
            reason: str | None = None
            comparable = True
            verdict = "COMPARABLE"
            differs: str | None = None
            if am is None or bm is None:
                comparable = False
                missing = "b" if am is not None else "a"
                reason = f"measured on one side only (absent in run {missing})"
                other_index = b_index if am is not None else a_index
                alt_questions = sorted({
                    q for (q, k, c) in other_index
                    if k == metric and c == coords})
                if alt_questions:
                    verdict = "MODEL_DIFFERENCE"
                    differs = "question"
                    reason += (
                        f"; the same metric key is measured under "
                        f"different question(s) {alt_questions} on the "
                        f"other side: different models (MODEL "
                        f"DIFFERENCE), not a performance difference")
                else:
                    verdict = "MISSING_MEASUREMENT"
                    differs = "presence"
            elif not same_workload:
                comparable = False
                verdict = "NOT_COMPARABLE"
                differs = "workload"
                reason = (f"different workload identity ({a_workload!r} "
                          f"vs {b_workload!r})")
            elif am["unit"] != bm["unit"]:
                comparable = False
                verdict = "NOT_COMPARABLE"
                differs = "unit"
                reason = (f"unit mismatch ({am['unit']!r} vs "
                          f"{bm['unit']!r})")
            elif am["backend"] != bm["backend"]:
                comparable = False
                verdict = "MODEL_DIFFERENCE"
                differs = "backend"
                reason = (f"backend difference ({am['backend']!r} vs "
                          f"{bm['backend']!r}): a cross-backend number is "
                          f"a MODEL DIFFERENCE, not a performance winner")
            elif am["fidelity"] != bm["fidelity"]:
                comparable = False
                verdict = "MODEL_DIFFERENCE"
                differs = "model_fidelity"
                reason = (f"model difference ({am['fidelity']!r} vs "
                          f"{bm['fidelity']!r}): different models, not a "
                          f"performance winner")
            elif am["qualification"] != bm["qualification"] \
                    or am["qualification"] is None:
                comparable = False
                verdict = "QUALIFICATION_DIFFERENCE"
                differs = "qualification"
                reason = (f"qualification mismatch "
                          f"({am['qualification']!r} vs "
                          f"{bm['qualification']!r})")
            elif not (numeric(am["value"]) and numeric(bm["value"])):
                comparable = False
                verdict = "MISSING_MEASUREMENT"
                differs = "value"
                reason = "at least one side did not measure a number"
            delta: float | None = None
            if comparable:
                delta = float(bm["value"]) - float(am["value"])
            rows.append({
                "question": question,
                "key": metric,
                "dimensions": coords or None,
                "a": None if am is None else am["value"],
                "b": None if bm is None else bm["value"],
                "unit": None if am is None else am["unit"],
                "comparable": comparable,
                "verdict": verdict,
                "differs": differs,
                "delta_b_minus_a": delta,
                "a_evidence": (None if am is None
                                 else am["native_evidence_id"]),
                "b_evidence": (None if bm is None
                                 else bm["native_evidence_id"]),
                "reason": reason,
            })
        return {
            "contract_version": 1,
            "a": self._compare_side(a),
            "b": self._compare_side(b),
            "compatibility": {
                "compatible": same_workload,
                "same_workload": same_workload,
                "reasons": ([] if same_workload else [
                    "different or missing workload identity "
                    f"({a_workload!r} vs {b_workload!r})"]),
            },
            "rows": rows,
            "note": ("No automatic winner. Rows are comparable only for "
                     "the same question, metric, unit, dimensional "
                     "coordinates, model fidelity and qualification; "
                     "cross-model numbers are labeled MODEL DIFFERENCE, "
                     "never ranked."),
        }

    @staticmethod
    def _compare_compatibility(a: dict[str, Any],
                               b: dict[str, Any]) -> dict[str, Any]:
        """The explicit compatibility gate. Same metric key is not enough."""
        a_eval = a.get("evaluation") or {}
        b_eval = b.get("evaluation") or {}
        a_workload = a_eval.get("workload_id")
        b_workload = b_eval.get("workload_id")
        same_workload = (a_workload is not None
                         and a_workload == b_workload)
        a_backend = a.get("backend")
        b_backend = b.get("backend")
        same_backend = (a_backend is not None and a_backend == b_backend)
        both_qualified = (a.get("qualification") == "QUALIFIED"
                          and b.get("qualification") == "QUALIFIED")
        reasons: list[str] = []
        if not same_workload:
            reasons.append(
                "different or missing workload identity "
                f"({a_workload!r} vs {b_workload!r})")
        if not same_backend:
            reasons.append(
                f"different or missing backend ({a_backend!r} vs "
                f"{b_backend!r})")
        if not both_qualified:
            reasons.append("at least one run has no QUALIFIED evidence chain")
        return {
            "compatible": same_workload and same_backend and both_qualified,
            "same_workload": same_workload,
            "same_backend": same_backend,
            "both_qualified": both_qualified,
            "metric_units": ("not carried by EvaluationView v1; metrics are "
                             "raw backend quantities"),
            "reasons": reasons,
        }

    def _compare_side(self, run: dict[str, Any]) -> dict[str, Any]:
        project_id = run["project_id"]
        revision = self.store.load_revision(project_id, run["revision_id"])
        design = revision.get("design") or {}
        return {
            "run_id": run["run_id"],
            "display_name": run.get("display_name"),
            "revision_id": run["revision_id"],
            "design_hash": run.get("design_hash"),
            "backend": run.get("backend"),
            "status": run.get("status"),
            "qualification": run.get("qualification"),
            "workload_id": (run.get("evaluation") or {}).get("workload_id"),
            "noc": design.get("noc_guided"),
            "locked_derived": design.get("locked_derived"),
            "requirements_pass": run.get("requirements_pass"),
        }

    @staticmethod
    def _latest_refusal(latest: dict[str, Any] | None) -> str | None:
        """The refusal reason when the latest attempt is not usable."""
        if latest is None:
            return None
        compilation = latest.get("compilation") or {}
        certificate = latest.get("certificate") or {}
        if (compilation.get("status") == "COMPILED"
                and certificate.get("overall") == "PASS"):
            return None
        return (compilation.get("error")
                or "compilation was not successful")

    @classmethod
    def _flow(cls, active: dict[str, Any] | None, dirty: bool,
              runs: list[dict[str, Any]],
              jobs: list[dict[str, Any]],
              latest: dict[str, Any] | None = None,
              draft_hash: str | None = None) -> dict[str, Any]:
        if active is None:
            refusal = cls._latest_refusal(latest)
            if refusal is not None:
                return {"state": "REFUSED", "next_action": "EDIT_DRAFT",
                        "reason": refusal}
            return {"state": "DRAFT" if not dirty else "DIRTY",
                    "next_action": "COMPILE",
                    "reason": "no compiled revision yet"}
        active_runs = [r for r in runs
                       if r.get("revision_id") == active["revision_id"]]
        active_jobs = [j for j in jobs
                       if j.get("revision_id") == active["revision_id"]]
        evaluating = [j for j in active_jobs
                      if j["kind"] == "EVALUATION"
                      and j["state"] not in ("COMPLETED", "REFUSED",
                                             "FAILED", "CANCELLED")]
        optimizing = [j for j in active_jobs
                      if j["kind"] == "OPTIMIZATION"
                      and j["state"] not in ("COMPLETED", "REFUSED",
                                             "FAILED", "CANCELLED")]
        compilation = active.get("compilation") or {}
        certificate = active.get("certificate") or {}
        if compilation.get("status") != "COMPILED":
            return {"state": "REFUSED", "next_action": "EDIT_DRAFT",
                    "reason": compilation.get("error")
                    or "compilation was not successful"}
        if dirty:
            if (latest is not None and draft_hash is not None
                    and draft_hash == latest.get("design_hash")):
                refusal = cls._latest_refusal(latest)
                if refusal is not None:
                    return {"state": "REFUSED",
                            "next_action": "EDIT_DRAFT",
                            "reason": refusal}
            return {"state": "DIRTY", "next_action": "COMPILE",
                    "reason": "draft has uncompiled changes"}
        if certificate.get("overall") != "PASS":
            return {"state": "COMPILED", "next_action": "INSPECT_VERIFY",
                    "reason": "certificate is not PASS"}
        if optimizing:
            return {"state": "OPTIMIZING", "next_action": "WAIT",
                    "reason": f"optimization {optimizing[-1]['job_id']}"}
        if evaluating:
            return {"state": "EVALUATING", "next_action": "WAIT",
                    "reason": f"evaluation {evaluating[-1]['job_id']}"}
        evaluated = [r for r in active_runs
                     if r.get("status") == "EVALUATED"]
        if evaluated:
            return {"state": "EVALUATED",
                    "next_action": "COMPARE_OR_OPTIMIZE",
                    "reason": f"latest run {evaluated[-1]['run_id']}"}
        failed = [r for r in active_runs
                  if r.get("status") in ("FAILED", "INVALID",
                                         "UNSUPPORTED")]
        if failed:
            return {"state": "EVALUATION_FAILED",
                    "next_action": "RUN_EVALUATION",
                    "reason": failed[-1].get("reason")}
        return {"state": "VERIFIED", "next_action": "RUN_EVALUATION",
                "reason": "certificate PASS"}

    def federation_backends(self) -> dict[str, Any]:
        """Per-backend federation truth, one owner per fact.

Rationale: docs/decisions/modules/product.md
        """
        entries = []
        for adapter in self._registry.adapters():
            capabilities = []
            try:
                declared = adapter.capabilities()
            except Exception:                           # noqa: BLE001
                declared = ()
            for capability in declared:
                capabilities.append({
                    "question": capability.question.value,
                    "support": capability.support.value,
                    "fidelity": capability.fidelity.value,
                    "limitations": list(capability.limitations),
                })
            available, detail = self._backend_install_fact(
                adapter.backend_id)
            entries.append({
                "backend_id": adapter.backend_id,
                "registered": True,
                "runtime_available": available,
                "availability_detail": detail,
                "capabilities": capabilities,
            })
        return {"contract_version": 1, "backends": entries}

    def _backend_install_fact(self, backend_id: str) -> tuple[bool, str]:
        """Install fact for one backend: present or absent on this tree.

        A missing backend is reported as absent (UNAVAILABLE at plan
        time), never as unsupported — absence is an environment fact,
        support is a semantic declaration the adapter already carries.
        """
        if backend_id == "BOOKSIM_STANDALONE":
            binary = self.config.booksim_bin
            if binary is not None and Path(binary).is_file():
                return True, "BookSim binary present"
            return False, "no BookSim binary configured on this tree"
        if backend_id == "ASTRA2_EMBEDDED_BOOKSIM":
            try:
                from veritx_dse.backend.astra import resolve_runtime_binary
                resolved = resolve_runtime_binary()
            except Exception as exc:                    # noqa: BLE001
                return False, f"ASTRA resolver failed: {exc}"
            if resolved is not None:
                return True, "ASTRA runtime binary present"
            binary = self.config.astra_bin
            if binary is not None and Path(binary).is_file():
                return True, "ASTRA runtime binary present"
            return False, "no ASTRA runtime binary on this tree"
        if backend_id == "RAMULATOR2_HBM3_V1":
            try:
                from veritx_dse.simulation.ramulator import discover
                backend = discover(
                    python_exe=self.config.ramulator_python,
                    vendor_dir=self.config.ramulator_vendor_dir)
            except Exception as exc:                    # noqa: BLE001
                return False, f"Ramulator discovery failed: {exc}"
            if backend.ready:
                return True, "Ramulator extension built for this interpreter"
            return False, (
                "Ramulator extension absent "
                f"(expected at {backend.ext_path})")
        return False, f"no install probe for backend {backend_id!r}"

__all__ = [
    "BackendUnavailable", "ProductConfig", "ProductService",
    "ProductServiceError", "parse_request_doc",
]
