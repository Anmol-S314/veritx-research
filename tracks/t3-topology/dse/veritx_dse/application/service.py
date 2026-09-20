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
    EXECUTABLE_BACKEND_TARGETS, Intent, parse_intent, resolve_intent,
)
from .resources import (
    AttemptRecord, CompiledDesign, ComparisonResult, EvaluationPlan,
    EvaluationResult, ExperimentRecord, WorkloadRecord, _content_id,
    check_envelope,
)
from .store import ResourceStore

EXECUTION_MODE_REAL = "REAL_SIMULATION"
ATTEMPT_STATUSES = ("PLANNED", "RUNNING", "SUCCEEDED", "FAILED",
                    "TIMED_OUT", "CANCELLED", "INTERRUPTED",
                    "UNSUPPORTED", "BLOCKED")
# Lifecycle decision (reconciled with core/runs.py): PLANNED covers the
# old CREATED+VALIDATED history (validation evidence IS the persisted
# plan/design records); terminal states are single-write records; resume
# is a NEW attempt, never a mutation (no backend checkpoint exists).


def _default_store_root() -> Path:
    from veritx_dse.core.paths import REPO
    return REPO / "runs" / "veritx-control-plane"


class SrotaControlPlane:
    """The single product-facing control plane (boring on purpose)."""

    def __init__(self, store_root: str | Path | None = None,
                 repo_root: str | Path | None = None,
                 binary: str | Path | None = None):
        from veritx_dse.core.paths import REPO
        from veritx_dse.core.runs import RunError, assert_runtime_compatible
        try:
            assert_runtime_compatible()
        except RunError as exc:
            raise internal_error(
                str(exc), operation="init",
                cause_type="RunError") from exc
        self.store = ResourceStore(
            store_root if store_root is not None
            else _default_store_root())
        self.repo_root = Path(
            repo_root) if repo_root is not None else REPO
        self.binary = Path(binary) if binary is not None else None

    @staticmethod
    def _runtime_provenance(repo_root: Path) -> dict[str, Any]:
        """Observational runtime provenance (never experiment identity).

        Reuses core/runs.py capture: interpreter, lockfile, platform,
        allowlisted env. Changing Python versions changes this block,
        never the scientific experiment ID.
        """
        from veritx_dse.core.runs import capture_provenance
        return capture_provenance(repo_root, argv=[])

    # ── compile ───────────────────────────────────────────────────

    def compile(self, intent_doc: Any) -> dict[str, Any]:
        """Intent -> validated CompiledDesign + WorkloadRecord (no spawn)."""
        intent, trace_bytes, trace_source = resolve_intent(intent_doc)
        return self._compile_resolved(intent, trace_bytes, trace_source)

    def _compile_resolved(self, intent: Intent, trace_bytes: bytes,
                            trace_source: dict[str, Any]) -> dict[str, Any]:
        """Compile core over resolved intent + bytes (no rereads)."""
        from veritx_dse.model.compile_model import CompileRequest
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
        self._store_intent(intent)
        self.store.put("design", design_id, design.to_dict())
        self._store_workload(workload)
        return {
            "design": design.to_dict(),
            "workload": workload.to_dict(),
            "bundle_hashes": bundle.root_hashes(),
        }

    def _store_intent(self, intent: Intent) -> None:
        """Persist the intent document (first label wins).

        Display labels are excluded from intent identity, so two intents
        with identical semantics but different names share one id. The
        first persisted label wins; a genuine id collision (same id,
        different semantics) refuses instead of proceeding.
        """
        try:
            self.store.put("intent", intent.intent_id(), intent.to_dict())
        except ControlPlaneError as exc:
            if exc.code != ErrorCode.CONFLICT:
                raise
            existing = self.store.get("intent", intent.intent_id())
            if parse_intent(existing).intent_id() != intent.intent_id():
                raise

    def _store_workload(self, workload: WorkloadRecord) -> None:
        """Persist the workload record (first source label wins).

        The workload id covers content + universe, not the source label
        (registry name vs file path): identical bytes from different
        transports share one id and the first label wins. A genuine
        same-id/different-content collision refuses.
        """
        try:
            self.store.put("workload", workload.workload_id(),
                           workload.to_dict())
        except ControlPlaneError as exc:
            if exc.code != ErrorCode.CONFLICT:
                raise
            existing = self.store.get("workload", workload.workload_id())
            if existing.get("trace_sha256") != workload.trace_sha256:
                raise

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

    # ── validate / capabilities / diagnose / list ──────────────────

    def validate(self, intent_doc: Any) -> dict[str, Any]:
        """Pure request validation (no compile, no backend, no spawn)."""
        intent, trace_bytes, trace_source = resolve_intent(intent_doc)
        from veritx_dse.backend.contracts import sha256_bytes
        return {
            "valid": True,
            "intent_id": intent.intent_id(),
            "fabric_preset": intent.fabric_preset,
            "backend_target": intent.backend_target,
            "seed_policy": intent.seed_policy(),
            "trace_sha256": sha256_bytes(trace_bytes),
            "trace_source": trace_source,
            "metrics": list(intent.metrics),
        }

    def capabilities(self) -> dict[str, Any]:
        """Authoritative capability registry (derived, not listed)."""
        from .capabilities import POLICY, capability_registry
        registry = capability_registry()
        registry["policy"] = dict(POLICY)
        return registry

    def diagnose(self) -> dict[str, Any]:
        """Operational health (no experiment, no identity effects)."""
        import platform
        import sys
        binary: dict[str, Any] = {"configured": self.binary is not None}
        try:
            path = self._resolve_binary()
            binary.update({"found": True, "path": str(path)})
        except ControlPlaneError as exc:
            binary.update({"found": False, "reason": exc.message})
        probe = self.store.root / ".diagnose-probe"
        try:
            probe.parent.mkdir(parents=True, exist_ok=True)
            probe.write_text("ok")
            writable = probe.read_text() == "ok"
        except OSError:
            writable = False
        finally:
            try:
                probe.unlink()
            except OSError:
                pass
        return {
            "binary": binary,
            "store_writable": writable,
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "capabilities": self.capabilities(),
        }

    def list_results(self, limit: int | None = None) -> dict[str, Any]:
        """Verified result listing (capped index).

        Every row passes the verified loader; corrupt/tampered records
        are reported as integrity INVALID with no trusted scientific
        fields (never surfaced as science).
        """
        from .capabilities import cap_query_rows
        from .results import load_verified_result
        count = cap_query_rows(limit)
        directory = self.store.root / "result"
        ids = sorted(p.stem for p in directory.glob("*.json"))[:count]
        rows = []
        invalid = 0
        for resource_id in ids:
            try:
                record = load_verified_result(self.store, resource_id)
                rows.append({
                    "resource_id": resource_id,
                    "experiment_id": record.get("experiment_id"),
                    "status": record.get("status"),
                    "qualification": record.get("qualification"),
                    "fabric_hash": record.get("fabric_hash"),
                    "integrity": "VERIFIED",
                })
            except ControlPlaneError:
                invalid += 1
                rows.append({"resource_id": resource_id,
                             "integrity": "INVALID"})
        return {"results": rows, "count": len(rows),
                "invalid_count": invalid, "cap": count}

    # ── plan ──────────────────────────────────────────────────────

    def plan(self, intent_doc: Any) -> dict[str, Any]:
        """Intent -> deterministic EvaluationPlan (no spawn, no lowering)."""
        intent, trace_bytes, trace_source = resolve_intent(intent_doc)
        return self._plan_resolved(intent, trace_bytes, trace_source)

    def _plan_resolved(self, intent: Intent, trace_bytes: bytes,
                       trace_source: dict[str, Any]) -> dict[str, Any]:
        """Plan core over resolved intent + bytes (no rereads)."""
        from veritx_dse.backend.booksim import (
            BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION,
            BOOKSIM_STANDALONE_PROFILE,
        )
        compiled = self._compile_resolved(intent, trace_bytes,
                                          trace_source)
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
        intent, trace_bytes, trace_source = resolve_intent(intent_doc)
        from .capabilities import check_execution_budget
        check_execution_budget(intent.timeout_s)
        planned = self._plan_resolved(intent, trace_bytes, trace_source)
        plan = planned["plan"]
        bundle = self._rebuild_bundle(plan)
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
        runtime = self._runtime_provenance(self.repo_root)
        try:
            evidence = run_qualified_booksim(
                prepared, run_dir=attempt_dir, repo_root=self.repo_root,
                timeout=intent.timeout_s, binary=binary)
        except KeyboardInterrupt:
            # Synchronous cancellation: the attempt is terminally
            # INTERRUPTED (never resumed in place — a retry is a new
            # attempt; no backend checkpoint exists).
            attempt = AttemptRecord(
                attempt_id=attempt_id, experiment_id=experiment_id,
                status="INTERRUPTED", backend_dir=str(attempt_dir),
                producer=producer.identity_dict(),
                error={"code": "INTERRUPTED",
                       "message": "KeyboardInterrupt during execution"},
                runtime=runtime)
            self.store.put("attempt", attempt_id, attempt.to_dict())
            raise
        except Exception as exc:
            self._persist_failed_attempt(
                attempt_id, experiment_id, attempt_dir, producer,
                runtime, exc)
            raise map_execution_error(
                exc, operation="evaluate",
                attempt_id=attempt_id) from exc
        ref = write_evidence(attempt_dir, evidence.to_dict())
        result = self._build_result(
            plan, planned, experiment, attempt_id, attempt_dir, evidence,
            producer, ref, reused=False)
        self._persist_success(experiment, attempt_id, attempt_dir,
                              producer, runtime, ref, result)
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
        """Verified reuse of an identical experiment (or None to run).

        Bound to the CURRENT experiment throughout: the link must name
        this experiment, the result must belong to it with matching
        config/input hashes, and Wave-B verification runs against the
        current experiment's hashes — never the stored result's own
        claims. A transplanted link or result refuses; the caller then
        executes fresh.
        """
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
            if link.get("experiment_id") != experiment.experiment_id:
                return None
            result = self.store.get("result", link["result_id"])
            if result.get("experiment_id") != experiment.experiment_id \
                    or result.get("plan_id") != experiment.plan_id \
                    or result.get("backend_config_hash") != \
                    experiment.backend_config_hash \
                    or result.get("backend_input_hash") != \
                    experiment.backend_input_hash:
                return None
            ref_doc = result["evidence_ref"]
            ref = EvidenceRef(path=ref_doc["path"],
                              sha256=ref_doc["sha256"])
            producer = resolve_producer_identity(
                self._resolve_binary(), repo_root=self.repo_root)
            verify_reusable_evidence(
                ref,
                backend_config_hash=experiment.backend_config_hash,
                backend_input_hash=experiment.backend_input_hash,
                producer=producer)
            from .results import load_verified_result
            load_verified_result(
                self.store, result["resource_id"],
                expected_experiment_id=experiment.experiment_id)
            out = dict(result)
            out["reused"] = True
            return out
        except (ControlPlaneError, ProducerError, VeritXError, KeyError,
                ValueError):
            return None

    def _persist_failed_attempt(self, attempt_id: str, experiment_id: str,
                                attempt_dir: Path, producer: Any,
                                runtime: dict[str, Any],
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
            producer=producer.identity_dict(), error=error.to_dict(),
            runtime=runtime)
        self.store.put("attempt", attempt_id, attempt.to_dict())

    def _build_result(self, plan: dict[str, Any], planned: dict[str, Any],
                      experiment: ExperimentRecord, attempt_id: str,
                      attempt_dir: Path, evidence: Any, producer: Any,
                      ref: Any, *, reused: bool) -> EvaluationResult:
        from .results import loss_digest_of
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
        loss_digest = loss_digest_of(loss)
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
                         runtime: dict[str, Any], ref: Any,
                         result: EvaluationResult) -> None:
        attempt = AttemptRecord(
            attempt_id=attempt_id,
            experiment_id=experiment.experiment_id, status="SUCCEEDED",
            backend_dir=str(attempt_dir),
            producer=producer.identity_dict(),
            evidence_ref={"path": ref.path, "sha256": ref.sha256},
            runtime=runtime)
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

    # ── study ─────────────────────────────────────────────────────

    def run_study(self, study_doc: Any) -> dict[str, Any]:
        """Sequentially evaluate study candidates (grouping, no DAG).

        Each candidate is a full intent evaluated through the normal
        path (reuse included). Failures are collected per candidate;
        the study completes unless the request itself is invalid. An
        optional comparison block runs pairwise comparisons over stored
        result IDs by candidate index.
        """
        from .capabilities import check_study_budget
        from .studies import StudyRequest
        from .resources import StudyDefinition, StudyResult
        request = StudyRequest.parse(study_doc)
        check_study_budget(len(request.candidates))
        identities = request.candidate_identities()
        definition = StudyDefinition(
            study_id=request.study_id(), name=request.name,
            candidate_intents=tuple(identities),
            comparison_request=request.comparison)
        self.store.put("studydef", definition.study_id,
                       definition.to_dict())
        experiments: list[dict[str, Any]] = []
        for index, candidate in enumerate(request.candidates):
            candidate_identity = identities[index]
            try:
                from .requests import resolve_intent
                intent, _, _ = resolve_intent(candidate)
                assert intent.intent_id() == candidate_identity
            except ControlPlaneError as exc:
                experiments.append({
                    "index": index, "status": "INVALID",
                    "candidate_identity": candidate_identity,
                    "intent_id": None, "experiment_id": None,
                    "result_id": None, "error": exc.to_dict()})
                continue
            try:
                result = self.evaluate(candidate)
                experiments.append({
                    "index": index, "status": "SUCCEEDED",
                    "candidate_identity": candidate_identity,
                    "intent_id": intent.intent_id(),
                    "experiment_id": result["experiment_id"],
                    "result_id": result["resource_id"],
                    "reused": result["reused"]})
            except ControlPlaneError as exc:
                experiments.append({
                    "index": index, "status": "FAILED",
                    "candidate_identity": candidate_identity,
                    "intent_id": intent.intent_id(),
                    "experiment_id": None,
                    "result_id": None, "error": exc.to_dict()})
        comparisons: list[dict[str, Any]] = []
        if request.comparison is not None:
            comparisons = self._study_comparisons(
                request, experiments)
        study = StudyResult(
            study_id=definition.study_id,
            study_run_id=new_run_id(),
            name=request.name,
            candidate_intents=tuple(identities),
            experiments=tuple(experiments),
            comparisons=tuple(comparisons),
            comparison_request=request.comparison)
        self.store.put("studyrun", study.study_run_id, study.to_dict())
        return study.to_dict()

    def _study_comparisons(
            self, request: Any,
            experiments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        from .comparison import parse_contract
        block = request.comparison or {}
        if not isinstance(block, dict):
            raise intent_error("study comparison must be an object",
                               operation="run_study")
        contract = parse_contract(block.get("contract", {}))
        pairs = block.get("pairs", [])
        if not isinstance(pairs, list) or not pairs:
            raise intent_error(
                "study comparison needs a non-empty pairs list",
                operation="run_study")
        by_index = {e["index"]: e for e in experiments}
        out = []
        for pair in pairs:
            if not isinstance(pair, list) or len(pair) != 2:
                raise intent_error(
                    f"comparison pair must be two indices, got {pair!r}",
                    operation="run_study")
            sides = []
            for index in pair:
                entry = by_index.get(index)
                if entry is None or entry.get("result_id") is None:
                    sides.append(None)
                else:
                    sides.append(entry["result_id"])
            if any(s is None for s in sides):
                out.append({"pair": list(pair), "status": "SKIPPED",
                            "reason": "a side has no successful result"})
                continue
            try:
                compared = self.compare({
                    "candidate_ids": sides,
                    "contract": contract.identity_dict()})
                out.append({"pair": list(pair), "status": "COMPARED",
                            "comparison_id": compared["resource_id"]})
            except ControlPlaneError as exc:
                out.append({"pair": list(pair), "status": "REFUSED",
                            "error": exc.to_dict()})
        return out

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
        results = [self._load_comparison_result(c) for c in candidates]
        for result in results:
            self._verify_comparison_evidence(result)
        compatibility = check_compatibility(results[0], results[1],
                                            contract)
        metrics = compare_metrics(results[0], results[1],
                                  contract.metric_ids)
        comparison_id = _content_id("srota-comparison/v1", {
            # Directional: candidate order shapes deltas, so it shapes
            # identity (compare(A,B) != compare(B,A)).
            "candidate_ids": list(candidates),
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

    def _load_comparison_result(self, result_id: str) -> dict[str, Any]:
        """Verified result + comparison-grade evidence policy."""
        from .results import load_verified_result
        try:
            result = load_verified_result(self.store, result_id)
        except ControlPlaneError as exc:
            raise ControlPlaneError(
                ErrorCode.COMPARISON_INCOMPATIBLE,
                f"candidate {result_id} fails verification: "
                f"{exc.message}",
                operation="compare", resource_id=result_id,
                cause_type=exc.code.value) from exc
        self._verify_comparison_evidence(result)
        return result

    def _load_result(self, result_id: str) -> dict[str, Any]:
        result = self.store.get("result", result_id)
        return check_envelope(result, "result")

    def _verify_comparison_evidence(self, result: dict[str, Any]) -> None:
        """Recorded-snapshot policy for comparison inputs.

        Digest authentication and full field consistency already hold
        (verified loader); comparison additionally requires recorded
        supervised transport and a recorded clean tree. Live producer
        pinning was enforced at execution.
        """
        if result.get("execution_transport") != "SUPERVISED_PROCESS":
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
                 "workload", "comparison", "intent", "links",
                 "studydef", "studyrun")
        for kind in kinds:
            if self.store.exists(kind, resource_id):
                record = self.store.get(kind, resource_id)
                return self._describe(kind, record)
        raise ControlPlaneError(
            ErrorCode.NOT_FOUND,
            f"unknown resource {resource_id!r}", operation="inspect",
            resource_id=resource_id)

    def _describe(self, kind: str, record: dict[str, Any]) -> dict[str, Any]:
        from .results import (
            load_verified_attempt, load_verified_comparison,
            load_verified_design, load_verified_experiment,
            load_verified_intent, load_verified_plan,
            load_verified_study, load_verified_studyrun,
            load_verified_workload,
        )
        related: dict[str, Any] = {}
        evidence_status: dict[str, Any] = {"checked": False}
        integrity: dict[str, Any] = {"checked": False}
        loaders = {
            "result": None,  # handled below (needs evidence stages)
            "attempt": load_verified_attempt,
            "experiment": load_verified_experiment,
            "plan": load_verified_plan,
            "design": load_verified_design,
            "workload": load_verified_workload,
            "intent": load_verified_intent,
            "comparison": load_verified_comparison,
            "studydef": load_verified_study,
            "studyrun": load_verified_studyrun,
        }
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
            try:
                from .results import load_verified_result
                load_verified_result(
                    self.store, record.get("resource_id", ""))
                integrity = {"checked": True, "state": "VERIFIED"}
            except ControlPlaneError as exc:
                integrity = {"checked": True, "state": "INVALID",
                             "reason": exc.message}
        elif kind in loaders and loaders[kind] is not None:
            try:
                checked = loaders[kind](
                    self.store, record.get("resource_id", ""))
                if kind == "attempt" and isinstance(checked, dict) \
                        and checked.get("status") != "SUCCEEDED":
                    # Failed/timed-out/interrupted attempts verify
                    # structurally only: never label failure metadata
                    # cryptographically authenticated.
                    integrity = {"checked": True,
                                 "state": "STRUCTURALLY_VALID",
                                 "evidence": "NOT_AVAILABLE"}
                else:
                    integrity = {"checked": True, "state": "VERIFIED"}
                if kind == "workload":
                    # packets/source are observational transport and
                    # derived metadata: NOT covered by the workload
                    # content ID and never a scientific claim.
                    integrity["observational"] = ["packets", "source"]
            except ControlPlaneError as exc:
                integrity = {"checked": True, "state": "INVALID",
                             "reason": exc.message}
            if kind in ("experiment", "plan"):
                for link_kind, key in (("plan", "plan_id"),):
                    target = record.get(key)
                    if kind == "experiment" and isinstance(target, str) \
                            and self.store.exists(link_kind, target):
                        related[key] = self.store.get(link_kind, target)
            if kind == "attempt":
                target = record.get("experiment_id")
                if isinstance(target, str) and self.store.exists(
                        "experiment", target):
                    related["experiment_id"] = self.store.get(
                        "experiment", target)
            if kind == "studydef":
                directory = self.store.root / "studyrun"
                runs = []
                if directory.is_dir():
                    for path in sorted(directory.glob("*.json")):
                        try:
                            run = self.store.get("studyrun", path.stem)
                        except ControlPlaneError:
                            continue
                        if isinstance(run, dict) and \
                                run.get("study_id") == \
                                record.get("resource_id"):
                            runs.append(path.stem)
                related["runs"] = runs
            if kind == "studyrun":
                target = record.get("study_id")
                if isinstance(target, str) and self.store.exists(
                        "studydef", target):
                    related["studydef"] = self.store.get(
                        "studydef", target)
        return {"kind": kind, "record": record, "related": related,
                "evidence_status": evidence_status,
                "integrity": integrity}

    def _evidence_status(self, result: dict[str, Any]) -> dict[str, Any]:
        """Three-stage integrity: record, evidence bytes, full chain."""
        from veritx_dse.backend.evidence import EvidenceRef
        record_integrity = isinstance(result, dict) and \
            result.get("resource_type") == "result"
        ref_doc = result.get("evidence_ref") or {}
        try:
            from veritx_dse.backend.evidence import \
                read_verified_evidence
            ref = EvidenceRef(path=ref_doc["path"],
                              sha256=ref_doc["sha256"])
            read_verified_evidence(ref)
            evidence_integrity: bool = True
            evidence_reason = ""
        except Exception as exc:
            evidence_integrity = False
            evidence_reason = f"{type(exc).__name__}: {exc}"
        try:
            from .results import load_verified_result
            load_verified_result(self.store,
                                 result.get("resource_id", ""))
            chain_integrity: bool = True
            chain_reason = ""
        except Exception as exc:
            chain_integrity = False
            chain_reason = f"{type(exc).__name__}: {exc}"
        verified = record_integrity and evidence_integrity and \
            chain_integrity
        reason = "" if verified else next(
            r for r in ("" if record_integrity else "record mismatch",
                        evidence_reason, chain_reason) if r)
        return {"checked": True, "verified": verified,
                "reason": reason,
                "record_integrity": record_integrity,
                "evidence_integrity": evidence_integrity,
                "chain_integrity": chain_integrity}


__all__ = [
    "ATTEMPT_STATUSES",
    "EXECUTION_MODE_REAL",
    "SrotaControlPlane",
]
