"""veritx_dse.gateway — the live Studio gateway.

Rationale: docs/decisions/modules/gateway.md
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from veritx_dse.application.errors import ControlPlaneError, ErrorCode
from veritx_dse.core.errors import InvalidInput, Refusal
from veritx_dse.core.paths import REPO
from veritx_dse.core.run_bundle import (
    CHECKSUMS_NAME, RunBundleError, verify_run_bundle,
)
from veritx_dse.gateway.staleness import staleness, warn_if_stale
from veritx_dse.gateway.errors import (
    BackendUnavailable, Conflict, NotFound, error_code_for, http_status_for,
)
from veritx_dse.gateway.revisions import (
    Revision, RevisionStore, revision_id_for,
)
from veritx_dse.application.capabilities import capability_registry
from veritx_dse.application.loom_capability import loom_capabilities
from veritx_dse.application.value_provenance import provenance_registry
from veritx_dse.product.qualification import qualification_view
from veritx_dse.product.service import ProductConfig, ProductService
from veritx_dse.product.validation import validation_campaigns

logger = logging.getLogger("veritx.gateway")


def run_freshness(product: ProductService, run_id: str,
                  run: dict[str, Any]) -> dict[str, Any] | None:
    """Server-computed freshness for one run against the design in view.

    Returns None only when the owning project cannot be resolved, which is a
    data-integrity problem the run view already refuses — not a reason to
    invent a verdict.
    """
    from veritx_dse.application.value_provenance import (
        STALENESS_MEANING, staleness_for,
    )
    try:
        project = product.project_view(run["project_id"])
    except Exception:  # noqa: BLE001 — the run view already refused it
        return None
    active = project.get("active_revision_id")
    dirty = bool((project.get("draft") or {}).get("dirty"))
    state = staleness_for(run.get("revision_id"), active, draft_dirty=dirty)
    return {
        "state": state,
        "meaning": STALENESS_MEANING[state],
        "run_revision_id": run.get("revision_id"),
        "active_revision_id": active,
        "draft_dirty": dirty,
        "draft_design_hash": (project.get("draft") or {}).get("design_hash"),
        "run_design_hash": run.get("design_hash"),
    }

@dataclass(frozen=True)
class GatewayConfig:
    store_root: Path
    runs_root: Path
    booksim_bin: Path | None = None
    astra_bin: Path | None = None
    network_clock_hz: int = 1_000_000_000
    timeout_s: int = 600
    experiments_dir: Path | None = None
    revisions_root: Path | None = None
    projects_root: Path | None = None

    @property
    def revisions_dir(self) -> Path:
        return self.revisions_root or (
            self.store_root.parent / "studio-revisions")

def config_from_env() -> GatewayConfig:
    # One authority for "where is the repo": core.paths.REPO. This used to be
    # Path(__file__).resolve().parents[3], which resolves to the t3-topology
    # track dir, not the repo root — so store/runs landed under
    # tracks/t3-topology/runs/ and experiments_dir pointed at
    # tracks/t3-topology/validation/experiments, which does not exist.
    repo = REPO
    store = os.environ.get("VERITX_STORE_ROOT")
    runs = os.environ.get("VERITX_RUNS_ROOT")
    revisions = os.environ.get("VERITX_REVISIONS_ROOT")
    projects = os.environ.get("VERITX_PROJECTS_ROOT")
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    store_root = Path(store) if store else repo / "runs" / "studio-store"
    return GatewayConfig(
        store_root=store_root,
        runs_root=Path(runs) if runs else repo / "runs" / "veritx-runs",
        booksim_bin=resolve_booksim_bin(binary),
        astra_bin=resolve_astra_bin(os.environ.get("VERITX_ASTRA_BIN")),
        experiments_dir=repo / "validation" / "experiments",
        revisions_root=(Path(revisions) if revisions
                        else store_root.parent / "studio-revisions"),
        projects_root=Path(projects) if projects else store_root / "projects",
    )

def resolve_astra_bin(env_value: str | None = None) -> Path | None:
    """The gateway's ASTRA binary: env override, then the canonical
    resolver. Returns None only when the binary genuinely does not
    exist, so MISSING means missing rather than unset."""
    if env_value:
        return Path(env_value)
    try:
        from veritx_dse.backend.astra import resolve_runtime_binary
        return resolve_runtime_binary()
    except Exception:
        return None

def _backend_presence(config: GatewayConfig) -> dict[str, Any]:
    """Cheap, non-secret backend presence. No simulation ever runs here.

    States are install facts (PRESENT/ABSENT), never readiness: READY
    requires adjudicating a real canonical context, which health must
    not do. A manifest flag names whether build-time provenance exists
    for the binary (no digests, no paths leak).
    """
    from veritx_dse.core.build_manifest import manifest_path_for

    def probe(binary: Path | None) -> dict[str, Any]:
        if binary is None or not Path(binary).is_file():
            return {"state": "ABSENT", "binary_present": False,
                    "manifest_present": False}
        try:
            manifest = manifest_path_for(Path(binary)).is_file()
        except Exception:
            manifest = False
        return {"state": "PRESENT", "binary_present": True,
                "manifest_present": bool(manifest)}

    return {
        "BOOKSIM_STANDALONE": probe(config.booksim_bin),
        "ASTRA2_EMBEDDED_BOOKSIM": probe(config.astra_bin),
        "RAMULATOR2_HBM3_V1": _ramulator_presence(),
    }

def _ramulator_presence() -> dict[str, Any]:
    """Ramulator install fact: is the compiled extension importable by
    this interpreter? No build, no simulation, no readiness claim."""
    try:
        from veritx_dse.core.build_manifest import manifest_path_for
        from veritx_dse.simulation.ramulator import discover
        backend = discover()
    except Exception:
        return {"state": "ABSENT", "binary_present": False,
                "manifest_present": False}
    if not backend.ready:
        return {"state": "ABSENT", "binary_present": False,
                "manifest_present": False}
    try:
        manifest = manifest_path_for(backend.ext_path).is_file()
    except Exception:
        manifest = False
    return {"state": "PRESENT", "binary_present": True,
            "manifest_present": bool(manifest)}

def resolve_booksim_bin(env_value: str | None = None) -> Path | None:
    """The gateway's BookSim binary: env override, then the standard search.

Rationale: docs/decisions/modules/gateway.md
    """
    if env_value:
        return Path(env_value)
    try:
        from veritx_dse.core.paths import REPO
        from veritx_dse.simulation.booksim import find_booksim_bin
        return find_booksim_bin(REPO)
    except Exception:
        return None

class CreateProjectBody(BaseModel):
    name: str
    workload_id: str | None = None

class DraftBody(BaseModel):
    request: dict[str, Any]

class SelectWorkloadBody(BaseModel):
    workload_id: str

class RenameProjectBody(BaseModel):
    name: str

class EvaluateBodyV1(BaseModel):
    backend: str | None = None
    questions: list[str] | None = None

class ServingBody(BaseModel):
    workload_id: str | None = None
    num_reqs: int | None = None
    cluster_config: str | None = None
    dataset: str | None = None
    timeout_s: int | None = None
    profile_overrides: dict[str, Any] | None = None

class ServingBindingBody(BaseModel):
    """Bind one cluster×trace serving experiment to a project."""
    cluster_config: str | None = None
    dataset: str | None = None
    num_reqs: int | None = None
    timeout_s: int | None = None
    profile_overrides: dict[str, Any] | None = None

class OptimizeBodyV1(BaseModel):
    domain: list[dict[str, Any]]
    objectives: list[dict[str, Any]] = [
        {"metric": "completion_cycles", "direction": "MIN"}]
    constraints: list[dict[str, Any]] = []
    method: str = "grid"
    selection: str | None = None
    seed: int | None = None
    budget: dict[str, Any] | None = None

class CompileBody(BaseModel):
    preset: str | None = None
    policy: str = "baseline_deterministic_v2"
    overrides: list[str] = []
    name: str | None = None
    request: dict[str, Any] | None = None

class CompileDraftBody(BaseModel):
    """Compile request body (Gate 7 §4).

Rationale: docs/decisions/modules/gateway.md
    """

    expected_draft_design_hash: str | None = None

class EvaluateBody(BaseModel):
    revision_id: str | None = None
    request: dict[str, Any] = {}
    patch: dict[str, Any] = {}

def _compile_design(config: GatewayConfig, body: CompileBody):
    """Compile one design to (canonical request, Compilation, design_hash,
    resolved_fabric_hash). Two engine-authored paths, one product boundary.

Rationale: docs/decisions/modules/gateway.md
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler

    if body.request is not None:
        from veritx_dse.model.compile_model import CompileRequestV3
        try:
            request = CompileRequestV3.from_dict(body.request)
        except (ValueError, KeyError, InvalidInput) as exc:
            raise InvalidInput(str(exc)) from exc
        compilation = FabricCompiler().compile(request)
        resolved = ""
        if compilation.status == "COMPILED":
            resolved = compilation.bundle.root_hashes()["resolved_fabric_hash"]
        return request, compilation, request.design_hash(), resolved

    if body.preset is None:
        raise InvalidInput(
            "a compile needs either a preset or a v3 design request")

    from veritx_dse.application.compile_intent import CompileIntent
    from veritx_dse.application.service import SrotaControlPlane
    from veritx_dse.application.store import ResourceStore
    from veritx_dse.cli.commands_compile import _parse_override
    from veritx_dse.compiler.candidate_policy import CandidatePolicy

    try:
        overrides = tuple(_parse_override(t) for t in body.overrides)
        policy = CandidatePolicy(body.policy)
        intent = CompileIntent(
            name=body.name or f"studio:{body.preset}",
            fabric_preset=body.preset, fabric_overrides=overrides,
            candidate_policy=policy)
    except (ValueError, KeyError, InvalidInput) as exc:
        raise InvalidInput(str(exc)) from exc
    outcome = SrotaControlPlane(store=ResourceStore(config.store_root))\
        .compile(intent)
    request = outcome.compiled.design
    compilation = FabricCompiler().compile(request)
    if compilation.status == "COMPILED":
        resolved = compilation.bundle.root_hashes()["resolved_fabric_hash"]
        if resolved != outcome.resolved_fabric_hash:
            raise ControlPlaneError(
                ErrorCode.INTERNAL_ERROR,
                "guided and v3 compile paths disagree on resolved_fabric_hash",
                operation="compile")
    else:
        resolved = ""
    return request, compilation, outcome.design_hash, resolved

def _views(request: Any,
           compilation: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    from veritx_dse.application.views import compilation_view, design_view

    return design_view(request, compilation), compilation_view(compilation)

def _revision_of(config: GatewayConfig, body: CompileBody, *,
                 design_hash: str,
                 resolved_fabric_hash: str) -> Revision | None:
    """Record an immutable revision for a COMPILED design."""
    if not resolved_fabric_hash:
        return None
    intent = body.model_dump()
    revision = Revision(
        revision_id=revision_id_for(
            intent=intent, design_hash=design_hash,
            resolved_fabric_hash=resolved_fabric_hash),
        intent=intent, design_hash=design_hash,
        resolved_fabric_hash=resolved_fabric_hash)
    RevisionStore(config.revisions_dir).put(revision)
    return revision

def _load_revision(config: GatewayConfig, revision_id: str):
    """Re-derive a revision's canonical request; refuse on compiler drift."""
    revision = RevisionStore(config.revisions_dir).get(revision_id)
    request, compilation, design_hash, resolved = _compile_design(
        config, CompileBody(**revision.intent))
    if (design_hash != revision.design_hash
            or resolved != revision.resolved_fabric_hash):
        raise Conflict(
            f"revision {revision_id} no longer compiles to its stored "
            "identity; refusing to reinterpret it")
    if compilation.status != "COMPILED":
        raise Conflict(
            f"revision {revision_id} is {compilation.status}, not a "
            "compiled fabric")
    return revision, request, compilation

def _canonical_request(config: GatewayConfig, body: Any):
    """The canonical request from a revision id, or a raw compatibility body."""
    if getattr(body, "revision_id", None):
        _revision, request, _compilation = _load_revision(
            config, body.revision_id)
        return request
    from veritx_dse.model.compile_model import CompileRequestV3

    try:
        return CompileRequestV3.from_dict(body.request)
    except (ValueError, KeyError, InvalidInput) as exc:
        raise InvalidInput(str(exc)) from exc

def _compile(config: GatewayConfig, body: CompileBody) -> dict[str, Any]:
    request, compilation, design_hash, resolved = _compile_design(config, body)
    design, compilation_projection = _views(request, compilation)
    revision = _revision_of(config, body, design_hash=design_hash,
                            resolved_fabric_hash=resolved)
    out: dict[str, Any] = {
        "revision_id": revision.revision_id if revision else None,
        "design_hash": design_hash,
        "resolved_fabric_hash": resolved or None,
        "design_view": design,
        "compilation_view": compilation_projection,
    }
    if compilation.status == "COMPILED":
        hashes = {str(k): str(v)
                  for k, v in compilation.bundle.root_hashes().items()}
        out.update({
            "topology_hash": hashes["topology_hash"],
            "attachment_hash": hashes["attachment_hash"],
            "mapping_hash": hashes["mapping_hash"],
            "route_hash": hashes["router_route_hash"],
            "resolved_route_hash": hashes["resolved_route_hash"],
            "vc_assignment_hash": hashes["vc_assignment_hash"],
            "fabric_hash": hashes["fabric_hash"],
            "vc_count": compilation.bundle.vc_assignment.vc_count,
        })
    return out

def _list_runs(config: GatewayConfig) -> list[dict[str, Any]]:
    root = config.runs_root
    if not root.is_dir():
        return []
    runs = []
    for child in sorted(root.iterdir()):
        if not (child / CHECKSUMS_NAME).is_file():
            continue
        entry: dict[str, Any] = {"run_id": child.name, "status": "UNVERIFIED"}
        try:
            summary = verify_run_bundle(child)
            entry["status"] = "VERIFIED"
            entry["bundle_id"] = summary["bundle_id"]
            entry["file_count"] = summary["file_count"]
        except RunBundleError as exc:
            entry["status"] = "INVALID"
            entry["reason"] = str(exc)
        runs.append(entry)
    return runs

def _run_dir(config: GatewayConfig, run_id: str) -> Path:
    if "/" in run_id or "\\" in run_id or run_id in (".", ".."):
        raise InvalidInput("invalid run id")
    path = config.runs_root / run_id
    if not path.is_dir():
        raise NotFound(f"no such run: {run_id}")
    return path

def _workloads(config: GatewayConfig) -> dict[str, Any]:
    from veritx_dse.application.compile_intent import preset_names
    workloads: list[dict[str, Any]] = [
        {"id": f"preset:{name}", "kind": "preset", "name": name}
        for name in preset_names()
    ]
    exp_dir = config.experiments_dir
    if exp_dir is not None and exp_dir.is_dir():
        for path in sorted(exp_dir.glob("*.json")):
            try:
                doc = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            workloads.append({
                "id": f"experiment:{doc.get('id', path.stem)}",
                "kind": "validation_experiment",
                "title": doc.get("title", ""),
            })
    return {"workloads": workloads}

def create_app(config: GatewayConfig | None = None) -> FastAPI:
    cfg = config or config_from_env()
    projects_root = cfg.projects_root or (cfg.store_root / "projects")
    product = ProductService(ProductConfig(
        projects_root=projects_root, booksim_bin=cfg.booksim_bin,
        astra_bin=cfg.astra_bin,
        network_clock_hz=cfg.network_clock_hz, timeout_s=cfg.timeout_s))
    app = FastAPI(title="VERITX Studio Gateway", version="1.0.0")
    app.state.product = product

    @app.get("/api/v1/health", tags=["product"])
    def v1_health() -> dict[str, Any]:
        """Liveness PLUS code staleness.

Rationale: docs/decisions/modules/gateway.md
        """
        info = staleness()
        status = "stale" if info.get("stale") else "ok"
        return {"status": status, "api": "v1", "code": info,
                "backends": _backend_presence(cfg)}

    @app.get("/api/v1/qualification", tags=["product"])
    def v1_qualification() -> dict[str, Any]:
        return qualification_view()

    @app.get("/api/v1/capabilities", tags=["product"])
    def v1_capabilities() -> dict[str, Any]:
        return capability_registry()

    @app.get("/api/v1/loom/capabilities", tags=["product"])
    def v1_loom_capabilities(
            include_topology_probe: bool = True) -> dict[str, Any]:
        """The ONE capability table a Loom client may read.

        Every status here is decided server-side. The topology rows are
        PROBED — the compiler, the profile selector and the execution handlers
        are actually run for each registered family — so the table cannot claim
        a capability the compiler does not have. ``check_capability_truth.py``
        enforces the same invariant at build time.

        The probe is expensive, so ``include_topology_probe=false`` returns the
        static rows alone for callers that will not render a topology
        selector. A client that offers a topology choice MUST read the probed
        table and must not fall back to a name list.
        """
        return loom_capabilities(include_topology_probe=include_topology_probe)

    @app.get("/api/v1/loom/provenance", tags=["product"])
    def v1_loom_provenance() -> dict[str, Any]:
        """The value-provenance vocabulary, served so a client renders
        origin and freshness labels from one source rather than its own."""
        return provenance_registry()

    @app.get("/api/v1/federation/backends", tags=["product"])
    def v1_federation_backends() -> dict[str, Any]:
        """Per-backend federation truth: registration (declared
        capabilities) plus runtime install facts. Readiness is never
        adjudicated here — that belongs to the evaluation plan for a
        real canonical context."""
        return product.federation_backends()

    @app.get("/api/v1/validation", tags=["product"])
    def v1_validation() -> dict[str, Any]:
        return validation_campaigns()

    @app.get("/api/v1/catalog/workloads", tags=["product"])
    def v1_workloads() -> dict[str, Any]:
        return product.workload_catalog()

    @app.get("/api/v1/workloads/{workload_id}/lowering", tags=["product"])
    def v1_workload_lowering(workload_id: str) -> dict[str, Any]:
        return product.workload_lowering(workload_id)

    @app.get("/api/v1/catalog/fabric-presets", tags=["product"])
    def v1_presets() -> dict[str, Any]:
        return product.fabric_presets()

    @app.get("/api/v1/catalog/serving-configs", tags=["product"])
    def v1_serving_configs() -> dict[str, Any]:
        """Cluster service-semantics configs and request traces the
        canonical serve path can be pointed at, with the tracked defaults."""
        return product.serving_config_catalog()

    @app.get("/api/v1/catalog/hardware-profiles", tags=["product"])
    def v1_hardware_profiles() -> dict[str, Any]:
        """Hardware profiles derived from tracked measured sources (serving
        cluster configs + profiler meta). Every field states whether an
        authority consumes it; the profile is descriptive at design time."""
        from veritx_dse.application.hardware_profiles import (
            hardware_profile_catalog,
        )
        return hardware_profile_catalog()

    @app.get("/api/v1/catalog/serving-experiments", tags=["product"])
    def v1_serving_experiments() -> dict[str, Any]:
        """Runnable serving experiments: on-disk cluster configs
        crossed with on-disk request traces, facet labels derived from
        geometry and asset names, install-fact readiness per entry, and
        explicit gaps for model configs no cluster file references."""
        return product.serving_experiment_catalog()

    @app.post("/api/v1/projects", tags=["product"])
    def v1_create_project(body: CreateProjectBody) -> dict[str, Any]:
        return product.create_project(name=body.name,
                                      workload_id=body.workload_id)

    @app.get("/api/v1/projects", tags=["product"])
    def v1_list_projects() -> dict[str, Any]:
        return product.list_projects()

    @app.get("/api/v1/projects/{project_id}", tags=["product"])
    def v1_project(project_id: str) -> dict[str, Any]:
        return product.project_view(project_id)

    @app.patch("/api/v1/projects/{project_id}", tags=["product"])
    def v1_rename_project(project_id: str,
                          body: RenameProjectBody) -> dict[str, Any]:
        return product.rename_project(project_id, body.name)

    @app.delete("/api/v1/projects/{project_id}", tags=["product"])
    def v1_delete_project(project_id: str) -> dict[str, Any]:
        return product.delete_project(project_id)

    @app.get("/api/v1/projects/{project_id}/draft", tags=["product"])
    def v1_draft(project_id: str) -> dict[str, Any]:
        return product.draft_view(project_id)

    @app.get("/api/v1/projects/{project_id}/design", tags=["product"])
    def v1_design(project_id: str,
                  presentation: str = "edit",
                  review_snapshot_hash: str | None = None) -> dict[str, Any]:
        """DesignViewV2 — authoring (edit) or the pre-compile boundary
        (review). One projection, not two models (Gate 7 §2/§51.1)."""
        return product.design_view_v2(
            project_id, presentation=presentation,
            review_snapshot_hash=review_snapshot_hash)

    @app.put("/api/v1/projects/{project_id}/draft", tags=["product"])
    def v1_put_draft(project_id: str, body: DraftBody) -> dict[str, Any]:
        return product.put_draft(project_id, body.request)

    @app.post("/api/v1/projects/{project_id}/workload", tags=["product"])
    def v1_select_workload(project_id: str,
                           body: SelectWorkloadBody) -> dict[str, Any]:
        return product.select_workload(project_id, body.workload_id)

    @app.post("/api/v1/projects/{project_id}/compile", tags=["product"])
    def v1_compile(project_id: str,
                   body: CompileDraftBody | None = None) -> dict[str, Any]:
        """Compile the draft into an immutable revision.

        ``expected_draft_design_hash`` binds the compile to the reviewed
        snapshot (Gate 7 §4, REV-D2). Omitting it compiles the current draft
        — the compatibility path — but the product flow always sends it.
        """
        return product.compile_draft(
            project_id,
            expected_draft_design_hash=(
                body.expected_draft_design_hash if body else None))

    @app.get("/api/v1/revisions/{revision_id}", tags=["product"])
    def v1_revision(revision_id: str) -> dict[str, Any]:
        return product.get_revision(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/compilation", tags=["product"])
    def v1_revision_compilation(revision_id: str) -> dict[str, Any]:
        """Compatibility alias: returns the revision envelope (the same
        shape as GET .../revisions/{id}), NOT the CompileResult inspector
        shape — that lives at GET .../revisions/{id}/compile-result.
        The alias stays so existing readers keep working; new clients
        must use /compile-result.
        """
        return product.get_revision(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/topology", tags=["product"])
    def v1_revision_topology(revision_id: str) -> dict[str, Any]:
        return product.get_revision_topology(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/artifacts", tags=["product"])
    def v1_revision_artifacts(revision_id: str) -> dict[str, Any]:
        return product.get_revision_artifact_chain(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/compile-result", tags=["product"])
    def v1_revision_compile_result(revision_id: str) -> dict[str, Any]:
        """CompileResultView — the seven inspector groups under one Compile
        Result (Gate 8 §50), frozen at certification time."""
        return product.get_revision_compile_result(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/route", tags=["product"])
    def v1_revision_route(revision_id: str, routing_class: str | None = None,
                          src: int | None = None,
                          dst: int | None = None) -> dict[str, Any]:
        """The canonical DERIVED EXPECTED route for one (class, src, dst).

        A query over the route table frozen at certification time, never a
        re-derivation. Gate 8 §58: this is the expected state; a runtime
        observation is a different fact with its own scope.
        """
        return product.canonical_route(revision_id,
                                       routing_class=routing_class,
                                       src=src, dst=dst)

    @app.get("/api/v1/revisions/{revision_id}/preflight", tags=["product"])
    def v1_revision_preflight(revision_id: str) -> dict[str, Any]:
        return product.revision_preflight(revision_id)

    @app.get("/api/v1/revisions/{revision_id}/diff", tags=["product"])
    def v1_revision_diff(revision_id: str,
                         against: str | None = None) -> dict[str, Any]:
        """RevisionDiffView — DESIGN / DERIVED / CAPABILITY changes between
        two frozen compile results. The default basis is the predecessor
        in the project's revision order."""
        return product.revision_diff(revision_id, against)

    @app.get("/api/v1/projects/{project_id}/serving", tags=["product"])
    def v1_serving_list(project_id: str) -> dict[str, Any]:
        return {"contract_version": 1,
                "experiments": product.list_serving(project_id)}

    @app.post("/api/v1/projects/{project_id}/serving", tags=["product"])
    def v1_serving_submit(project_id: str,
                          body: ServingBody | None = None) -> dict[str, Any]:
        return product.submit_serving(project_id,
                                      body.model_dump() if body else None)

    @app.get("/api/v1/serving/{serving_id}", tags=["product"])
    def v1_serving_get(serving_id: str) -> dict[str, Any]:
        return product.get_serving(serving_id)

    @app.get("/api/v1/projects/{project_id}/serving-binding", tags=["product"])
    def v1_serving_binding_get(project_id: str) -> dict[str, Any]:
        return product.serving_binding(project_id)

    @app.post("/api/v1/projects/{project_id}/serving-binding",
              tags=["product"])
    def v1_serving_binding_set(
            project_id: str,
            body: ServingBindingBody | None = None) -> dict[str, Any]:
        return product.bind_serving(
            project_id, body.model_dump() if body else None)

    @app.delete("/api/v1/projects/{project_id}/serving-binding",
                tags=["product"])
    def v1_serving_binding_clear(project_id: str) -> dict[str, Any]:
        return product.clear_serving_binding(project_id)

    @app.get("/api/v1/revisions/{revision_id}/evaluation-plan",
            tags=["product"])
    def v1_evaluation_plan(revision_id: str,
                           questions: str | None = None,
                           backend: str | None = None) -> dict[str, Any]:
        """EvaluationPlanView — what this revision can run, per question.

        ``questions`` is a comma-separated question selection
        (default: all known questions); ``backend`` pins one explicit
        backend. Pure adjudication: never executes.
        """
        parsed = ([q.strip() for q in questions.split(",") if q.strip()]
                  if questions else None)
        return product.evaluation_plan(
            revision_id, questions=parsed, requested_backend=backend)

    @app.post("/api/v1/revisions/{revision_id}/evaluate", tags=["product"])
    def v1_evaluate(revision_id: str,
                    body: EvaluateBodyV1 | None = None) -> dict[str, Any]:
        payload = body or EvaluateBodyV1()
        return product.submit_evaluation(
            revision_id, questions=payload.questions,
            requested_backend=payload.backend)

    @app.post("/api/v1/revisions/{revision_id}/optimize", tags=["product"])
    def v1_optimize(revision_id: str,
                    body: OptimizeBodyV1) -> dict[str, Any]:
        return product.submit_optimization(revision_id, body.model_dump())

    @app.get("/api/v1/jobs/{job_id}", tags=["product"])
    def v1_job(job_id: str) -> dict[str, Any]:
        return product.get_job(job_id)

    @app.get("/api/v1/runs", tags=["product"])
    def v1_runs(project_id: str | None = None,
                revision_id: str | None = None) -> dict[str, Any]:
        return product.list_runs(project_id=project_id,
                                 revision_id=revision_id)

    @app.get("/api/v1/runs/{run_id}", tags=["product"])
    def v1_run(run_id: str) -> dict[str, Any]:
        """The run view, plus a server-computed freshness verdict.

        The verdict is computed HERE rather than in a client because it is a
        relation between three server-owned facts: the revision the run
        executed, the revision currently active on the project, and whether the
        draft has uncompiled changes. A client that derives it locally can
        disagree with the server about whether a result is stale, which is the
        one thing a stale-result warning must never do.
        """
        run = product.get_run(run_id)
        freshness = run_freshness(product, run_id, run)
        if freshness is not None:
            run["freshness"] = freshness
        return run

    @app.get("/api/v1/runs/{run_id}/evidence", tags=["product"])
    def v1_run_evidence(run_id: str) -> dict[str, Any]:
        return product.run_evidence(run_id)

    @app.get("/api/v1/runs/{run_id}/artifacts", tags=["product"])
    def v1_run_artifacts(run_id: str) -> dict[str, Any]:
        return product.run_artifacts(run_id)

    @app.get("/api/v1/runs/{run_id}/traffic-matrix", tags=["product"])
    def v1_run_traffic_matrix(run_id: str) -> dict[str, Any]:
        return product.run_traffic_matrix(run_id)

    @app.get("/api/v1/runs/{run_id}/integrity", tags=["product"])
    def v1_run_integrity(run_id: str) -> dict[str, Any]:
        return product.run_integrity(run_id)

    @app.post("/api/v1/runs/{run_id}/verify", tags=["product"])
    def v1_run_verify(run_id: str) -> dict[str, Any]:
        return product.verify_run(run_id)

    @app.post("/api/v1/runs/{run_id}/reproduce", tags=["product"])
    def v1_run_reproduce(run_id: str) -> dict[str, Any]:
        return product.submit_reproduction(run_id)
    @app.get("/api/v1/optimization/capabilities", tags=["product"])
    def v1_optimization_capabilities() -> dict[str, Any]:
        """What VERITX can actually optimize, derived from backend authority.

Rationale: docs/decisions/modules/gateway.md
        """
        from veritx_dse.optimization.capabilities import (
            optimization_capabilities,
        )
        return optimization_capabilities()

    @app.post(
        "/api/v1/optimizations/{optimization_id}/candidates/{candidate_id}/use",
        tags=["product"])
    def v1_use_candidate(optimization_id: str,
                         candidate_id: str) -> dict[str, Any]:
        """Adopt a studied candidate as the DRAFT.

        The base revision is NOT mutated: it stays immutable, and the user
        must explicitly compile before a new revision exists.
        """
        return product.use_candidate(optimization_id, candidate_id)

    @app.get("/api/v1/optimizations/{optimization_id}", tags=["product"])
    def v1_optimization(optimization_id: str) -> dict[str, Any]:
        return product.get_optimization(optimization_id)

    @app.get("/api/v1/compare", tags=["product"])
    def v1_compare(a: str, b: str) -> dict[str, Any]:
        return product.compare(a, b)

    from veritx_dse.gateway.vnext import register_vnext_routes
    register_vnext_routes(app)

    @app.get("/health", deprecated=True)
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/qualification", deprecated=True)
    def qualification() -> dict[str, Any]:
        return qualification_view()

    @app.get("/workloads", deprecated=True)
    def workloads() -> dict[str, Any]:
        return _workloads(cfg)

    @app.post("/compile", deprecated=True)
    def compile_(body: CompileBody) -> dict[str, Any]:
        return _compile(cfg, body)

    @app.get("/revisions", deprecated=True)
    def revisions() -> dict[str, Any]:
        store = RevisionStore(cfg.revisions_dir)
        return {"revisions": [
            {"revision_id": rid}
            for rid in store.list_ids()]}

    @app.get("/revisions/{revision_id}", deprecated=True)
    def revision(revision_id: str) -> dict[str, Any]:
        rev, request, compilation = _load_revision(cfg, revision_id)
        design, compilation_projection = _views(request, compilation)
        return {
            "revision_id": rev.revision_id,
            "design_hash": rev.design_hash,
            "resolved_fabric_hash": rev.resolved_fabric_hash,
            "intent": rev.intent,
            "design_view": design,
            "compilation_view": compilation_projection,
        }

    @app.get("/runs", deprecated=True)
    def runs() -> dict[str, Any]:
        return {"runs": _list_runs(cfg)}

    @app.get("/runs/{run_id}", deprecated=True)
    def run(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            summary = verify_run_bundle(path)
        except RunBundleError as exc:
            raise Conflict(str(exc)) from exc
        manifest = path / "manifest.json"
        doc = json.loads(manifest.read_text()) if manifest.is_file() else None
        return {"run_id": run_id, **summary, "manifest": doc}

    @app.get("/runs/{run_id}/evidence", deprecated=True)
    def evidence(run_id: str) -> dict[str, Any]:
        path = _run_dir(cfg, run_id)
        try:
            verify_run_bundle(path)
        except RunBundleError as exc:
            raise Conflict(str(exc)) from exc
        ev = path / "backend-evidence.json"
        if not ev.is_file():
            raise NotFound("no evidence in run")
        return json.loads(ev.read_text())

    def _require_binary() -> Path:
        if cfg.booksim_bin is None or not Path(cfg.booksim_bin).is_file():
            raise BackendUnavailable(
                "no qualified backend configured (set VERITX_BOOKSIM_BIN)")
        return Path(cfg.booksim_bin)

    @app.post("/evaluate", deprecated=True)
    def evaluate(body: EvaluateBody) -> dict[str, Any]:
        binary = _require_binary()
        from veritx_dse.optimization.candidate import make_candidate
        from veritx_dse.optimization.real_evaluator import (
            RealCandidateEvaluator,
        )
        request = _canonical_request(cfg, body)
        from veritx_dse.core.errors import UnsupportedSemantics
        from veritx_dse.model.compile_model import CompileRequestV3
        if not isinstance(request, CompileRequestV3):
            raise UnsupportedSemantics(
                "evaluation requires a v3 design; this revision was "
                "compiled from a guided preset")
        port = RealCandidateEvaluator(
            binary=str(binary), run_root=str(cfg.runs_root / "_evaluate"),
            network_clock_hz=cfg.network_clock_hz, timeout_s=cfg.timeout_s)
        out = port.evaluate(make_candidate(request, body.patch))
        return {"status": out.status,
                "performance_result_id": out.performance_result_id,
                "objective_values": getattr(out, "objective_values", None),
                "error": out.error}

    async def _typed_error_response(exc: Exception) -> JSONResponse:
        status = http_status_for(exc)
        code = error_code_for(exc)
        if status is None:
            logger.exception("unhandled gateway error", exc_info=exc)
            return JSONResponse(
                status_code=500,
                content={"detail": "internal server error",
                         "code": "INTERNAL_ERROR"})
        if status >= 500:
            logger.error("gateway typed failure %s: %s", code, exc)
        return JSONResponse(status_code=status,
                            content={"detail": str(exc), "code": code})

    for _typed in (Refusal, ControlPlaneError, BackendUnavailable,
                   Conflict, NotFound):
        async def _handler(request: Request, exc: Exception,
                           _t=_typed) -> JSONResponse:
            return await _typed_error_response(exc)

        app.add_exception_handler(_typed, _handler)

    @app.exception_handler(Exception)
    async def _internal_error_handler(request: Request,
                                      exc: Exception) -> JSONResponse:
        return await _typed_error_response(exc)

    return app

app = create_app()

warn_if_stale()
