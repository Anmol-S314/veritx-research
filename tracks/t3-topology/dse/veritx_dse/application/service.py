"""veritx_dse.application.service — one authoritative control plane.

``SrotaControlPlane`` sequences the SEALED Wave-B authorities:

    validate request -> resolve workload -> compile design -> plan ->
    lower backend -> prepare canonical inputs -> qualified execution ->
    persist evidence -> typed result resource

It owns orchestration ONLY: no routes, VC assignment, packet formats,
profile values or config semantics are derived here (frozen layers do
that). All product surfaces (Python/CLI/API/T3) call these operations;
adapters translate transport, never semantics.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from veritx_dse.core.runs import new_run_id

from .compile import compile_bundle
from .comparison import (
    check_compatibility, compare_metrics, parse_contract,
)
from .errors import (
    ControlPlaneError, ErrorCode, intent_error, internal_error,
    map_execution_error, map_lowering_error, map_semantic_error,
)
from .presets import (
    METRIC_SCHEMA_VERSION, STATS_TO_METRIC, derive_request,
    get_metric_definition,
)
from .requests import (
    EXECUTABLE_BACKEND_TARGETS, Intent, parse_intent,
    resolve_workload_bytes,
)
from .resources import (
    AttemptRecord, CompiledDesign, ComparisonResult, EvaluationPlan,
    EvaluationResult, ExperimentRecord, WorkloadRecord, _content_id,
    check_envelope,
)
from .store import ResourceStore

EXECUTION_MODE_REAL = "REAL_SIMULATION"
ATTEMPT_STATUSES = ("PLANNED", "RUNNING", "SUCCEEDED", "FAILED",
                    "TIMED_OUT", "UNSUPPORTED", "BLOCKED")


def _default_store_root() -> Path:
    from veritx_dse.core.paths import REPO
    return REPO / "runs" / "veritx-control-plane"


class SrotaControlPlane:
    """The single product-facing control plane (boring on purpose)."""

    def __init__(self, store_root: str | Path | None = None,
                 repo_root: str | Path | None = None,
                 binary: str | Path | None = None):
        from veritx_dse.core.paths import REPO
        self.store = ResourceStore(
            store_root if store_root is not None
            else _default_store_root())
        self.repo_root = Path(
            repo_root) if repo_root is not None else REPO
        self.binary = Path(binary) if binary is not None else None

    # ── compile ───────────────────────────────────────────────────

    def compile(self, intent_doc: Any) -> dict[str, Any]:
        """Intent -> validated CompiledDesign + WorkloadRecord (no spawn)."""
        from veritx_dse.model.compile_model import CompileRequest
        intent = parse_intent(intent_doc)
        trace_bytes, trace_source = resolve_workload_bytes(intent)
        request_dict = self._derive_request(intent)
        try:
            compile_request = CompileRequest.from_dict(request_dict)
        except Exception as exc:
            raise intent_error(
                f"preset request is not a valid CompileRequest: {exc}",
                operation="compile",
                cause_type=type(exc).__name__) from exc
        try:
            bundle = compile_bundle(compile_request)
        except ControlPlaneError:
            raise
        except Exception as exc:  # pragma: no cover - mapped above
            raise map_semantic_error(exc, operation="compile") from exc
        self._check_trace_universe(trace_bytes, bundle, intent)
        design = CompiledDesign(
            intent_id=intent.intent_id(),
            design_hash=compile_request.design_hash(),
            mapping_hash=bundle.resolved_fabric.mapping_hash,
            fabric_hash=bundle.fabric.fabric_hash(),
            topology_hash=bundle.topology.topology_hash(),
            attachment_hash=bundle.attachment.attachment_hash(),
            compile_request=compile_request.to_dict())
        workload = self._workload_record(trace_bytes, trace_source,
                                         bundle)
        design_id = design.resource_id()
        self.store.put("intent", intent.intent_id(), intent.to_dict())
        self.store.put("design", design_id, design.to_dict())
        self.store.put("workload", workload.workload_id(),
                       workload.to_dict())
        return {
            "design": design.to_dict(),
            "workload": workload.to_dict(),
            "bundle_hashes": bundle.root_hashes(),
        }

    def _derive_request(self, intent: Intent) -> dict[str, Any]:
        try:
            return derive_request(intent.fabric_preset,
                                  dict(intent.fabric_overrides))
        except (KeyError, TypeError) as exc:
            raise intent_error(str(exc), operation="compile",
                               cause_type=type(exc).__name__) from exc

    @staticmethod
    def _check_trace_universe(trace_bytes: bytes, bundle: Any,
                              intent: Intent) -> None:
        """Max node id must fit the attachment universe (else INVALID)."""
        endpoints = bundle.attachment.endpoint_count
        maximum = -1
        for raw in trace_bytes.decode("utf-8", errors="strict").splitlines():
            line = raw.strip()
            if not line or line[0] in ("#", "%"):
                continue
            fields = [f.strip() for f in
                      line.replace(",", " ").split()]
            try:
                numbers = [int(f) for f in fields[:5]]
            except ValueError:
                continue
            if len(numbers) < 5:
                continue
            dialect_csv = "," in line
            src, dst = (numbers[1], numbers[2]) if dialect_csv else (
                numbers[1], numbers[3])
            maximum = max(maximum, src, dst)
        if maximum >= endpoints:
            raise intent_error(
                f"trace node {maximum} is outside the attachment "
                f"universe ({endpoints} endpoints)",
                operation="compile")

    @staticmethod
    def _workload_record(trace_bytes: bytes, source: dict[str, Any],
                         bundle: Any) -> WorkloadRecord:
        from veritx_dse.backend.contracts import sha256_bytes
        packets = sum(
            1 for raw in trace_bytes.decode("utf-8",
                                            errors="strict").splitlines()
            if raw.strip() and raw.strip()[0] not in ("#", "%"))
        return WorkloadRecord(
            trace_sha256=sha256_bytes(trace_bytes),
            trace_bytes=len(trace_bytes),
            endpoint_count=bundle.attachment.endpoint_count,
            packets=packets, source=source)

    # ── plan ──────────────────────────────────────────────────────

    def plan(self, intent_doc: Any) -> dict[str, Any]:
        """Intent -> deterministic EvaluationPlan (no spawn, no lowering)."""
        from veritx_dse.backend.booksim import (
            BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION,
            BOOKSIM_STANDALONE_PROFILE,
        )
        compiled = self.compile(intent_doc)
        intent = parse_intent(intent_doc)
        design = compiled["design"]
        workload = compiled["workload"]
        self._require_executable(intent)
        profile = BOOKSIM_STANDALONE_PROFILE
        semantics = BOOKSIM_BACKEND_SEMANTICS_VERSION
        lowerer = BOOKSIM_LOWERER_VERSION
        plan_id = _content_id("srota-plan/v1", {
            "design_hash": design["design_hash"],
            "mapping_hash": design["mapping_hash"],
            "fabric_hash": design["fabric_hash"],
            "workload_hash": workload["trace_sha256"],
            "backend_target": intent.backend_target,
            "backend_profile": profile,
            "backend_semantics_version": semantics,
            "lowerer_version": lowerer,
            "execution_mode": EXECUTION_MODE_REAL,
            "seed": intent.seed,
            "seed_policy": intent.seed_policy(),
            "metric_ids": list(intent.metrics),
            "metric_schema_version": METRIC_SCHEMA_VERSION,
        })
        plan = EvaluationPlan(
            plan_id=plan_id, intent_id=intent.intent_id(),
            design_id=design["resource_id"],
            workload_id=workload["resource_id"],
            design_hash=design["design_hash"],
            mapping_hash=design["mapping_hash"],
            fabric_hash=design["fabric_hash"],
            workload_hash=workload["trace_sha256"],
            backend_target=intent.backend_target,
            backend_profile=profile,
            backend_semantics_version=semantics,
            lowerer_version=lowerer,
            execution_mode=EXECUTION_MODE_REAL,
            seed=intent.seed, seed_policy=intent.seed_policy(),
            metric_ids=intent.metrics,
            metric_schema_version=METRIC_SCHEMA_VERSION)
        self.store.put("plan", plan_id, plan.to_dict())
        return {"plan": plan.to_dict(), "design": design,
                "workload": workload}

    @staticmethod
    def _require_executable(intent: Intent) -> None:
        if intent.backend_target not in EXECUTABLE_BACKEND_TARGETS:
            raise ControlPlaneError(
                ErrorCode.UNSUPPORTED_SEMANTICS,
                f"backend_target {intent.backend_target} is not "
                f"qualified for execution (executable: "
                f"{list(EXECUTABLE_BACKEND_TARGETS)}); serving stays "
                f"BLOCKED and analytical stays NOT_RUN",
                operation="plan")

    # ── evaluate ──────────────────────────────────────────────────

    def evaluate(self, intent_doc: Any) -> dict[str, Any]:
        """Intent -> EvaluationResult (reuse or fresh qualified run)."""
        from veritx_dse.backend.booksim import (
            PreparedBackend, bind_booksim_inputs,
            lower_booksim_standalone, render_booksim_standalone,
            run_qualified_booksim,
        )
        from veritx_dse.backend.contracts import sha256_bytes
        from veritx_dse.backend.evidence import write_evidence
        from veritx_dse.backend.producer import (
            resolve_producer_identity, verify_reusable_evidence,
        )
        planned = self.plan(intent_doc)
        intent = parse_intent(intent_doc)
        plan = planned["plan"]
        bundle = self._rebuild_bundle(plan)
        trace_bytes, _ = resolve_workload_bytes(intent)
        try:
            config = lower_booksim_standalone(bundle)
            rendered = render_booksim_standalone(
                bundle, config, workload_trace=trace_bytes,
                seed=intent.seed)
            manifest = bind_booksim_inputs(
                config, rendered,
                workload_hash=sha256_bytes(trace_bytes), seed=intent.seed)
        except Exception as exc:
            raise map_lowering_error(exc, operation="evaluate") from exc
        prepared = PreparedBackend(bundle=bundle, config=config,
                                   rendered=rendered, manifest=manifest)
        experiment_id = _content_id("srota-experiment/v1", {
            "plan_id": plan["resource_id"],
            "backend_config_hash": config.backend_config_hash(),
            "backend_input_hash": manifest.backend_input_hash(),
            "execution_mode": plan["execution_mode"],
        })
        experiment = ExperimentRecord(
            experiment_id=experiment_id, plan_id=plan["resource_id"],
            backend_config_hash=config.backend_config_hash(),
            backend_input_hash=manifest.backend_input_hash(),
            execution_mode=plan["execution_mode"])
        self.store.put("experiment", experiment_id, experiment.to_dict())
        # Reuse first: an identical experiment with verifiable evidence.
        reused = self._try_reuse(experiment, plan, intent)
        if reused is not None:
            return reused
        attempt_id = new_run_id()
        attempt_dir = self.store.root / "attempts" / attempt_id
        binary = self._resolve_binary()
        producer = resolve_producer_identity(
            binary, repo_root=self.repo_root)
        try:
            evidence = run_qualified_booksim(
                prepared, run_dir=attempt_dir, repo_root=self.repo_root,
                timeout=intent.timeout_s, binary=binary)
        except Exception as exc:
            self._persist_failed_attempt(
                attempt_id, experiment_id, attempt_dir, producer, exc)
            raise map_execution_error(
                exc, operation="evaluate",
                attempt_id=attempt_id) from exc
        ref = write_evidence(attempt_dir, evidence.to_dict())
        result = self._build_result(
            plan, planned, experiment, attempt_id, attempt_dir, evidence,
            producer, ref, reused=False)
        self._persist_success(experiment, attempt_id, attempt_dir,
                              producer, ref, result)
        return result.to_dict()

    def _rebuild_bundle(self, plan: dict[str, Any]):
        """Re-derive the bundle deterministically from stored design."""
        from veritx_dse.model.compile_model import CompileRequest
        design = self.store.get("design", plan["design_id"])
        try:
            compile_request = CompileRequest.from_dict(
                design["compile_request"])
        except Exception as exc:
            raise internal_error(
                f"stored design {plan['design_id']} does not parse: {exc}",
                operation="evaluate") from exc
        try:
            return compile_bundle(compile_request)
        except ControlPlaneError:
            raise
        except Exception as exc:  # pragma: no cover - mapped above
            raise map_semantic_error(exc, operation="evaluate") from exc

    def _resolve_binary(self) -> Path:
        if self.binary is not None:
            return self.binary
        try:
            from veritx_dse.simulation.booksim import find_booksim_bin
            return Path(find_booksim_bin(self.repo_root))
        except Exception as exc:
            raise ControlPlaneError(
                ErrorCode.EXECUTION_FAILED,
                f"no runnable BookSim binary: {exc}",
                operation="evaluate",
                cause_type=type(exc).__name__) from exc

    def _try_reuse(self, experiment: ExperimentRecord, plan: dict[str, Any],
                   intent: Intent) -> dict[str, Any] | None:
        """Verified reuse of an identical experiment (or None to run)."""
        from veritx_dse.backend.evidence import EvidenceRef
        from veritx_dse.backend.producer import (
            ProducerError, resolve_producer_identity,
            verify_reusable_evidence,
        )
        from veritx_dse.core.errors import VeritXError
        link_id = f"experiment-result-{experiment.experiment_id}"
        if not self.store.exists("links", link_id):
            return None
        try:
            link = self.store.get("links", link_id)
            result = self.store.get("result", link["result_id"])
            ref_doc = result["evidence_ref"]
            ref = EvidenceRef(path=ref_doc["path"],
                              sha256=ref_doc["sha256"])
            producer = resolve_producer_identity(
                self._resolve_binary(), repo_root=self.repo_root)
            verify_reusable_evidence(
                ref,
                backend_config_hash=result["backend_config_hash"],
                backend_input_hash=result["backend_input_hash"],
                producer=producer)
            out = dict(result)
            out["reused"] = True
            return out
        except (ControlPlaneError, ProducerError, VeritXError, KeyError,
                ValueError):
            return None

    def _persist_failed_attempt(self, attempt_id: str, experiment_id: str,
                                attempt_dir: Path, producer: Any,
                                exc: Exception) -> None:
        from veritx_dse.core.errors import TimeoutError as CoreTimeout
        if isinstance(exc, CoreTimeout):
            status = "TIMED_OUT"
        else:
            status = "FAILED"
        error = ControlPlaneError(
            ErrorCode.EXECUTION_TIMEOUT
            if status == "TIMED_OUT" else ErrorCode.EXECUTION_FAILED,
            str(exc), operation="evaluate", resource_id=attempt_id,
            cause_type=type(exc).__name__)
        attempt = AttemptRecord(
            attempt_id=attempt_id, experiment_id=experiment_id,
            status=status, backend_dir=str(attempt_dir),
            producer=producer.identity_dict(), error=error.to_dict())
        self.store.put("attempt", attempt_id, attempt.to_dict())

    def _build_result(self, plan: dict[str, Any], planned: dict[str, Any],
                      experiment: ExperimentRecord, attempt_id: str,
                      attempt_dir: Path, evidence: Any, producer: Any,
                      ref: Any, *, reused: bool) -> EvaluationResult:
        from veritx_dse.core.spec import canonical_json
        import hashlib as _hashlib
        metrics = []
        for metric_id in plan["metric_ids"]:
            definition = get_metric_definition(metric_id)
            stats_key = next(
                k for k, v in STATS_TO_METRIC.items() if v == metric_id)
            stats = evidence.stats
            if stats_key not in stats:
                raise internal_error(
                    f"metric {metric_id} absent from backend stats",
                    operation="evaluate")
            value = stats[stats_key]
            if not isinstance(value, (int, float)):
                raise internal_error(
                    f"metric {metric_id} has non-numeric value {value!r}",
                    operation="evaluate")
            metrics.append({
                "metric_id": metric_id,
                "value": float(value),
                "unit": definition.unit,
                "definition_version": METRIC_SCHEMA_VERSION,
            })
        loss = sorted((dict(r) for r in evidence.semantic_loss),
                      key=lambda r: r.get("dimension", ""))
        loss_digest = _hashlib.sha256(
            canonical_json(loss).encode()).hexdigest()
        result_id = _content_id("srota-result/v1", {
            "experiment_id": experiment.experiment_id,
            "attempt_id": attempt_id,
            "evidence_sha256": ref.sha256,
        })
        return EvaluationResult(
            result_id=result_id,
            experiment_id=experiment.experiment_id,
            attempt_id=attempt_id, plan_id=plan["resource_id"],
            design_id=planned["design"]["resource_id"],
            workload_id=planned["workload"]["resource_id"],
            design_hash=plan["design_hash"],
            mapping_hash=plan["mapping_hash"],
            fabric_hash=plan["fabric_hash"],
            workload_hash=plan["workload_hash"],
            backend_target=plan["backend_target"],
            backend_profile=plan["backend_profile"],
            backend_semantics_version=plan["backend_semantics_version"],
            backend_config_hash=evidence.backend_config_hash,
            backend_input_hash=evidence.backend_input_hash,
            execution_mode=plan["execution_mode"],
            status="SUCCEEDED",
            qualification=evidence.qualification,
            execution_transport=evidence.execution_transport,
            semantic_loss=tuple(loss),
            loss_digest=loss_digest,
            metrics=tuple(metrics),
            metric_schema_version=METRIC_SCHEMA_VERSION,
            evidence_ref={"path": ref.path, "sha256": ref.sha256},
            producer=producer.identity_dict(),
            seed=evidence.seed, seed_policy=evidence.seed_policy,
            reused=reused)

    def _persist_success(self, experiment: ExperimentRecord,
                         attempt_id: str, attempt_dir: Path, producer: Any,
                         ref: Any, result: EvaluationResult) -> None:
        attempt = AttemptRecord(
            attempt_id=attempt_id,
            experiment_id=experiment.experiment_id, status="SUCCEEDED",
            backend_dir=str(attempt_dir),
            producer=producer.identity_dict(),
            evidence_ref={"path": ref.path, "sha256": ref.sha256})
        self.store.put("attempt", attempt_id, attempt.to_dict())
        self.store.put("result", result.result_id, result.to_dict())
        link_id = f"experiment-result-{experiment.experiment_id}"
        try:
            self.store.put("links", link_id,
                           {"result_id": result.result_id,
                            "experiment_id": experiment.experiment_id})
        except ControlPlaneError as exc:
            if exc.code != ErrorCode.CONFLICT:
                raise

    # ── compare ───────────────────────────────────────────────────

    def compare(self, request_doc: Any) -> dict[str, Any]:
        """Two persisted results -> gated ComparisonResult."""
        if not isinstance(request_doc, dict):
            raise intent_error("compare request must be an object",
                               operation="compare")
        unknown = sorted(set(request_doc) - {"candidate_ids", "contract"})
        if unknown:
            raise intent_error(
                f"compare request has unknown fields {unknown}",
                operation="compare")
        candidates = request_doc.get("candidate_ids")
        if not isinstance(candidates, list) or len(candidates) != 2 or \
                any(not isinstance(c, str) for c in candidates):
            raise intent_error(
                "candidate_ids must be a list of exactly two result ids",
                operation="compare")
        contract = parse_contract(request_doc.get("contract", {}))
        results = [self._load_result(c) for c in candidates]
        for result in results:
            self._verify_comparison_evidence(result)
        compatibility = check_compatibility(results[0], results[1],
                                            contract)
        metrics = compare_metrics(results[0], results[1],
                                  contract.metric_ids)
        comparison_id = _content_id("srota-comparison/v1", {
            "candidate_ids": sorted(candidates),
            "contract": contract.identity_dict(),
            "metric_ids": list(contract.metric_ids),
        })
        comparison = ComparisonResult(
            comparison_id=comparison_id,
            candidate_ids=(candidates[0], candidates[1]),
            contract=contract.identity_dict(),
            compatibility=compatibility, metrics=tuple(metrics),
            fidelity_context={
                "a_qualification": results[0]["qualification"],
                "b_qualification": results[1]["qualification"],
                "a_loss_digest": results[0]["loss_digest"],
                "b_loss_digest": results[1]["loss_digest"],
                "acknowledged_differences": list(
                    contract.acknowledged_differences),
            })
        self.store.put("comparison", comparison_id, comparison.to_dict())
        return comparison.to_dict()

    def _load_result(self, result_id: str) -> dict[str, Any]:
        result = self.store.get("result", result_id)
        return check_envelope(result, "result")

    def _verify_comparison_evidence(self, result: dict[str, Any]) -> None:
        """Digest + recorded-field consistency for comparison inputs.

        Live producer pinning was enforced at execution; comparison
        re-authenticates the persisted bytes and requires the recorded
        snapshot to be clean, supervised-process evidence. Scientific
        comparison consumes valid successful results only.
        """
        from veritx_dse.backend.evidence import read_verified_evidence
        ref_doc = result.get("evidence_ref") or {}
        try:
            from veritx_dse.backend.evidence import EvidenceRef
            ref = EvidenceRef(path=ref_doc["path"],
                              sha256=ref_doc["sha256"])
            evidence = read_verified_evidence(ref)
        except Exception as exc:
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {result.get('resource_id')} evidence fails "
                f"verification: {exc}",
                operation="compare",
                cause_type=type(exc).__name__) from exc
        for key in ("backend_config_hash", "backend_input_hash"):
            if evidence.get(key) != result.get(key):
                raise ControlPlaneError(
                    ErrorCode.COMPARISON_INCOMPATIBLE,
                    f"candidate {result.get('resource_id')} evidence "
                    f"does not match its recorded {key}",
                    operation="compare")
        if evidence.get("execution_transport") != "SUPERVISED_PROCESS":
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {result.get('resource_id')} is not "
                f"supervised-process evidence",
                operation="compare")
        producer = result.get("producer") or {}
        if producer.get("source_dirty") is not False:
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {result.get('resource_id')} was produced "
                f"from an unpinned or dirty tree",
                operation="compare")

    # ── inspect ───────────────────────────────────────────────────

    def inspect(self, resource_id: str) -> dict[str, Any]:
        """Read-only forensic navigation (never mutates, never executes)."""
        kinds = ("result", "attempt", "experiment", "plan", "design",
                 "workload", "comparison", "intent", "links")
        for kind in kinds:
            if self.store.exists(kind, resource_id):
                record = self.store.get(kind, resource_id)
                return self._describe(kind, record)
        raise ControlPlaneError(
            ErrorCode.NOT_FOUND,
            f"unknown resource {resource_id!r}", operation="inspect",
            resource_id=resource_id)

    def _describe(self, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        related: dict[str, Any] = {}
        evidence_status: dict[str, Any] = {"checked": False}
        if kind == "result":
            for link_kind, key in (
                    ("experiment", "experiment_id"),
                    ("attempt", "attempt_id"),
                    ("plan", "plan_id"),
                    ("design", "design_id"),
                    ("workload", "workload_id")):
                target = record.get(key)
                if isinstance(target, str) and self.store.exists(
                        link_kind, target):
                    related[key] = self.store.get(link_kind, target)
                else:
                    related[key] = {"resource_id": target,
                                    "missing": True}
            evidence_status = self._evidence_status(record)
        elif kind == "attempt":
            for link_kind, key in (("experiment", "experiment_id"),):
                target = record.get(key)
                if isinstance(target, str) and self.store.exists(
                        link_kind, target):
                    related[key] = self.store.get(link_kind, target)
        elif kind in ("experiment", "plan"):
            for link_kind, key in (("plan", "plan_id"),):
                target = record.get(key)
                if kind == "experiment" and isinstance(target, str) \
                        and self.store.exists(link_kind, target):
                    related[key] = self.store.get(link_kind, target)
        return {"kind": kind, "record": record, "related": related,
                "evidence_status": evidence_status}

    @staticmethod
    def _evidence_status(result: dict[str, Any]) -> dict[str, Any]:
        from veritx_dse.backend.evidence import EvidenceRef
        ref_doc = result.get("evidence_ref") or {}
        try:
            from veritx_dse.backend.evidence import read_verified_evidence
            ref = EvidenceRef(path=ref_doc["path"],
                              sha256=ref_doc["sha256"])
            evidence = read_verified_evidence(ref)
        except Exception as exc:
            return {"checked": True, "verified": False,
                    "reason": f"{type(exc).__name__}: {exc}"}
        matches = all(
            evidence.get(key) == result.get(key)
            for key in ("backend_config_hash", "backend_input_hash"))
        return {"checked": True, "verified": bool(matches),
                "reason": "" if matches else "record mismatch"}


__all__ = [
    "ATTEMPT_STATUSES",
    "EXECUTION_MODE_REAL",
    "SrotaControlPlane",
]
