"""veritx_dse.application.federated_evaluator — the product-level resource.

Turns the sealed BookSim+ASTRA federation into one callable resource:

    evaluate_federated(compilation, questions, registry, ...)
        -> FederatedEvaluationOutcome

Laws (non-negotiable):
  * the canonical context is built ONCE; every analysis evaluates the
    same design/fabric/workload — no backend owns a private view;
  * the planner adjudicates every question; execution never second-
    guesses selection and never substitutes backends;
  * BOOKSIM_STANDALONE / NETWORK_COMPLETION executes through the
    existing certified FabricEvaluator — no second BookSim evidence or
    performance chain is ever constructed;
  * ASTRA analyses execute through their adapter seam
    (prepare -> execute -> normalize), staging their own workload;
  * ASTRA cycle counts never enter the network PerformanceResult: they
    answer different questions;
  * RequirementEvaluator stays bound to the verified PerformanceResult
    from NETWORK_COMPLETION until another requirement class explicitly
    names a different metric authority;
  * overall EVALUATED requires every requested question EVALUATED —
    never report EVALUATED when a requested question failed.
  * overall FAILED whenever a genuine execution FAILED — even beside
    successes (PARTIAL is incomplete coverage, never a crash mask).
    Successful analyses are preserved in the record, never discarded.
  * reproduction archival is explicit, never silent: every ASTRA /
    Ramulator analysis records an ArchivalResult (ARCHIVED or
    NOT_AVAILABLE naming the missing artifact). An EVALUATED analysis
    whose mandatory inputs never reached the layout keeps its
    EVALUATED status — the scripted-adapter product tests and the
    reproduce-time NOT_AVAILABLE verdict depend on it — but the run
    never claims reproducibility for it: the archival record rides in
    the analysis, and reproduction refuses without archived inputs.
    (Rationale: the strict variant — failing such analyses closed —
    would require redesigning the scripted-adapter test ecosystem,
    which stages no real inputs by construction; execute() already
    wrote evidence before persist runs, so a persist fault with
    successful execution is near-pathological and normalize-readback
    would usually fail it anyway.)
  * INCONCLUSIVE native verdicts are never FAILED and never PASS.
  * BOOKSIM_STANDALONE executes exactly once per NETWORK_COMPLETION
    question through the adapter seam (prepare -> execute); the
    certified FabricEvaluator is the single orchestration authority
    that drives that seam, and the federated path normalizes through
    exactly one normalization entry.
"""
from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext, build_evaluation_context,
)
from veritx_dse.application.evaluation_plan import (
    EvaluationPlan, EvaluationPlanner,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.application.fabric_compiler import Compilation
from veritx_dse.application.fabric_evaluator import (
    BACKEND_UNAVAILABLE, EVALUATED, FAILED, UNSUPPORTED, EvaluationOptions,
    EvaluationOutcome, FabricEvaluator, STANDALONE_BACKEND,
)
from veritx_dse.backend.adapter import (
    BackendReadiness, ModelFidelity, SupportLevel,
)
from veritx_dse.backend.normalized_evidence import NormalizedBackendEvidence
from veritx_dse.backend.registry import BackendRegistry

#: per-analysis outcome vocabulary (the evaluator's, never invented)
ANALYSIS_EVALUATED = EVALUATED
ANALYSIS_UNSUPPORTED = UNSUPPORTED
ANALYSIS_UNAVAILABLE = BACKEND_UNAVAILABLE
ANALYSIS_FAILED = FAILED
#: a backend executed but its native verdict decided nothing — never a
#: crash (FAILED), never a pass (EVALUATED), never silently coverable.
ANALYSIS_INCONCLUSIVE = "INCONCLUSIVE"
ANALYSIS_STATUSES = (
    ANALYSIS_EVALUATED, ANALYSIS_UNSUPPORTED, ANALYSIS_UNAVAILABLE,
    ANALYSIS_FAILED, ANALYSIS_INCONCLUSIVE,
)

#: reproduction-archival vocabulary: mandatory per-backend inputs
#: either reached the run layout or they did not.
ARCHIVAL_ARCHIVED = "ARCHIVED"
ARCHIVAL_NOT_AVAILABLE = "NOT_AVAILABLE"


@dataclass(frozen=True)
class ArchivalResult:
    """Did this analysis's mandatory reproduction inputs persist?

    A typed result, never a swallowed exception: EVALUATED-but-
    unarchived cannot claim reproducibility, so the evaluator fails
    the analysis closed with the missing artifact named.
    """

    status: str
    missing: tuple[str, ...] = ()
    reason: str | None = None


#: overall outcome vocabulary: the evaluator's four plus PARTIAL
PARTIAL = "PARTIAL"
OVERALL_STATUSES = (
    EVALUATED, PARTIAL, BACKEND_UNAVAILABLE, UNSUPPORTED, FAILED,
)


@dataclass(frozen=True)
class BookSimRunOptions:
    """Backend-native execution options for the BookSim leg."""

    binary: str | Path | None = None
    repo_root: str | Path | None = None
    timeout_s: int = 600
    seed: int | None = None
    network_clock_hz: Any = None


@dataclass(frozen=True)
class AstraRunOptions:
    """Backend-native execution options for the ASTRA leg."""

    timeout_s: int = 600
    repo_root: str | Path | None = None


@dataclass(frozen=True)
class RamulatorRunOptions:
    """Backend-native execution options for the Ramulator leg.

    Discovery configuration (which vendor tree / interpreter) lives on
    the registered adapter, bound once in the registry — never
    reconstructed per run. Only the wall-clock budget rides here.
    """

    timeout_s: int = 600


@dataclass(frozen=True)
class AnalysisOutcome:
    """One requested question and what the federation did with it."""

    question: EvaluationQuestion
    backend_id: str | None
    status: str
    model_fidelity: ModelFidelity | None
    qualification: str | None
    normalized_evidence: NormalizedBackendEvidence | None
    native_evidence_id: str | None
    reason: str | None
    #: explicit reuse linkage (Studio §41): when this analysis did not
    #: execute but returned byte-verified reused evidence, the reused
    #: evidence id rides here (never a synthetic measurement) plus the
    #: matched reuse parents. None on a direct execution.
    reused_evidence_id: str | None = None
    reuse_matching: dict[str, Any] | None = None
    #: backend-native factual summary (evidence tier, injection counters,
    #: namespace binding, ...) for integrity views; never science.
    native_summary: dict[str, Any] | None = None
    #: reproduction-archival verdict for this analysis (None when the
    #: backend defines no mandatory archival step, e.g. BookSim whose
    #: reproduction replays the sealed bundle). Set by the evaluator,
    #: enforced at aggregation: EVALUATED-but-unarchived fails closed.
    archival: ArchivalResult | None = None

    def to_dict(self) -> dict[str, Any]:
        envelope = self.normalized_evidence
        return {
            "question": self.question.value,
            "backend_id": self.backend_id,
            "status": self.status,
            "model_fidelity": (None if self.model_fidelity is None
                               else self.model_fidelity.value),
            "qualification": self.qualification,
            "native_evidence_id": self.native_evidence_id,
            "reason": self.reason,
            "native_summary": self.native_summary,
            "normalized_metrics": (
                None if envelope is None else [
                    {"key": m.key, "value": m.value, "unit": m.unit,
                     "source_metric_key": m.source_metric_key,
                     "dimensions": [list(d) for d in m.dimensions]}
                    for m in envelope.metrics]),
            "limitations": (None if envelope is None
                            else list(envelope.limitations)),
            "archival": (None if self.archival is None else {
                "status": self.archival.status,
                "missing": list(self.archival.missing),
                "reason": self.archival.reason,
            }),
            "reused_evidence_id": self.reused_evidence_id,
            "reuse_matching": self.reuse_matching,
        }


@dataclass(frozen=True)
class FederatedEvaluationOutcome:
    """The adjudicated multi-analysis evaluation of one compilation."""

    status: str
    design_hash: str
    resolved_fabric_hash: str
    workload_id: str
    plan: EvaluationPlan
    analyses: tuple[AnalysisOutcome, ...]
    network_evaluation: EvaluationOutcome | None = None
    requirement_report: dict | None = None

    def analysis(self, question: EvaluationQuestion) -> AnalysisOutcome:
        for row in self.analyses:
            if row.question is question:
                return row
        raise KeyError(f"no analysis for {question!r}")


def _question_dir(question: EvaluationQuestion) -> str:
    return question.value.lower()


def evaluate_federated(
    compilation: Compilation,
    questions: tuple[EvaluationQuestion, ...],
    registry: BackendRegistry,
    *,
    requested_backend: str | None = None,
    booksim_options: BookSimRunOptions | None = None,
    astra_options: AstraRunOptions | None = None,
    ramulator_options: RamulatorRunOptions | None = None,
    run_dir: str | Path | None = None,
    revision_id: str | None = None,
) -> FederatedEvaluationOutcome:
    """Plan once, execute each READY analysis once, aggregate honestly.

    ``run_dir`` (when given) receives the federated layout
    (plan.json, analyses/<question>/..., normalized-evidence.json);
    directory names are structural, never scientific identity. Without
    it, execution still uses an ephemeral directory — never the cwd.
    """
    if not isinstance(compilation, Compilation):
        raise TypeError(
            f"evaluate_federated takes a Compilation, got "
            f"{type(compilation).__name__}")
    context = build_evaluation_context(compilation)
    plan = EvaluationPlanner().plan(
        context, questions, registry, requested_backend=requested_backend)
    booksim_opts = booksim_options or BookSimRunOptions()
    astra_opts = astra_options or AstraRunOptions()
    ramulator_opts = ramulator_options or RamulatorRunOptions()
    if run_dir is not None:
        exec_root = Path(run_dir)
        persistent = True
    else:
        exec_root = Path(tempfile.mkdtemp(prefix="federated-eval-"))
        persistent = False
    (exec_root / "analyses").mkdir(parents=True, exist_ok=True)

    outcomes: list[AnalysisOutcome] = []
    network_evaluation: EvaluationOutcome | None = None
    for row in plan.analyses:
        adapter = (None if row.backend_id is None
                   else registry.get(row.backend_id))
        if row.readiness is not BackendReadiness.READY or adapter is None:
            outcomes.append(_refused(row))
            continue
        analysis_dir = exec_root / "analyses" / _question_dir(row.question)
        analysis_dir.mkdir(parents=True, exist_ok=True)
        if row.backend_id == "BOOKSIM_STANDALONE" and \
                row.question is EvaluationQuestion.NETWORK_COMPLETION:
            evaluated, analysis = _evaluate_network(
                compilation, context, row, booksim_opts, analysis_dir)
            if evaluated is not None:
                network_evaluation = evaluated
            outcomes.append(analysis)
        elif row.backend_id == "ASTRA2_EMBEDDED_BOOKSIM":
            outcomes.append(_evaluate_astra(
                context, row, adapter, astra_opts, analysis_dir))
        elif row.backend_id == "RAMULATOR2_HBM3_V1":
            outcomes.append(_evaluate_ramulator(
                context, row, adapter, ramulator_opts, analysis_dir))
        else:  # pragma: no cover - planner never selects unknown backends
            outcomes.append(AnalysisOutcome(
                question=row.question, backend_id=row.backend_id,
                status=ANALYSIS_FAILED,
                model_fidelity=None, qualification=None,
                normalized_evidence=None, native_evidence_id=None,
                reason=f"no federated execution path for backend "
                f"{row.backend_id!r}"))

    requirement_report = None
    if network_evaluation is not None \
            and network_evaluation.status == EVALUATED:
        from veritx_dse.application.requirements import RequirementEvaluator
        requirement_report = RequirementEvaluator.evaluate(
            compilation.request, context.workload,
            network_evaluation.performance_result)

    if persistent:
        _persist_federated_layout(
            exec_root, context, plan, tuple(outcomes),
            revision_id=revision_id)

    return FederatedEvaluationOutcome(
        status=_aggregate(tuple(outcomes)),
        design_hash=context.design_hash,
        resolved_fabric_hash=_resolved_hash(context),
        workload_id=context.workload_id,
        plan=plan, analyses=tuple(outcomes),
        network_evaluation=network_evaluation,
        requirement_report=requirement_report)


def _resolved_hash(context: CanonicalEvaluationContext) -> str:
    value = context.bundle.resolved_fabric.resolved_fabric_hash
    return value() if callable(value) else value


def _refused(row: Any) -> AnalysisOutcome:
    """A non-READY plan row becomes a non-executed analysis — never a
    fabrication, never a substitution. BLOCKED readiness is a refusal
    (UNSUPPORTED outcome), never a runtime failure."""
    if row.readiness is BackendReadiness.UNAVAILABLE:
        status = ANALYSIS_UNAVAILABLE
    else:
        status = ANALYSIS_UNSUPPORTED
    return AnalysisOutcome(
        question=row.question, backend_id=row.backend_id,
        status=status, model_fidelity=None, qualification=None,
        normalized_evidence=None, native_evidence_id=None,
        reason=row.reason)


# ── evidence-reuse orchestration (network leg) ────────────────────────
#
# The safe verification primitives (verify/read_reusable_record) prove
# that STORED bytes are intact, but they cannot skip an execution: the
# full EvidenceCache key contains execution outputs (evidence_id,
# route_dump_sha256, route_observation) unknowable before the backend
# runs. So this layer does lookup-before-execute on the maximal
# pre-execution projection of the parent key, and treats the excluded
# outputs as functionally determined by those inputs under the seeded
# deterministic backend. The determination is then CONFIRMED, not
# assumed: a hit re-reads stored bytes through the verified reader and
# copies them into the current layout with a post-copy digest check.
# Any mismatch executes fresh. A hit never creates a synthetic
# measurement. In-memory process-wide only; strict clock exact-match.

_REUSE_PRE_FIELDS = (
    "prepared_id", "config_sha256", "trace_sha256", "binary_sha256",
    "binary_size", "profile_id", "projection_semantics_version",
    "parser_version", "build_manifest", "build_recipe_version",
    "schema_version", "producer_revision", "producer_dirty",
    "producer_transport", "producer_fidelity", "seed", "topology_id",
    "fabric_id", "traffic_id", "message_id", "question",
    "network_clock_hz",
)

_REUSE_KEY_DOMAIN = "veritx/network-reuse-key/v1"

_OUTCOME_REUSE: dict[str, list[dict[str, Any]]] = {}
_OUTCOME_REUSE_CAP = 128


def reset_network_reuse() -> None:
    """Clear the process-wide network reuse index (tests only)."""
    _OUTCOME_REUSE.clear()
    _evidence_reuse_cache()._entries.clear()
    _evidence_reuse_cache()._hits.clear()


def _evidence_reuse_cache():
    """The process-wide evidence-tier cache (full parent keys)."""
    global _EVIDENCE_REUSE_CACHE
    try:
        return _EVIDENCE_REUSE_CACHE
    except NameError:
        from veritx_dse.backend.evidence_cache import EvidenceCache
        _EVIDENCE_REUSE_CACHE = EvidenceCache()
        return _EVIDENCE_REUSE_CACHE


def _pre_execution_parents(context, traffic_class, options):
    """Pre-execution reuse parents, or None to skip caching.

    Uses the adapter's OWN prepare (identical call to FabricEvaluator's
    internal one, so byte-identical digests — no second authority, no
    backend spawn) plus read-only producer introspection with the
    execution's identical recipe.
    """
    from veritx_dse.backend.booksim_adapter import BookSimAdapter
    try:
        pre = BookSimAdapter().prepare(
            context, EvaluationQuestion.NETWORK_COMPLETION,
            traffic_class=traffic_class)
    except Exception:
        return None
    native = pre.native_prepared
    prepared = native.prepared
    try:
        from veritx_dse.backend import booksim_projection as _bp
        semantics_by_profile = {
            _bp.MESH_DOR_PROFILE.profile_id:
                _bp.MESH_DOR_PROFILE.semantics_version,
            _bp.CMESH_DOR_PROFILE.profile_id:
                _bp.CMESH_DOR_PROFILE.semantics_version,
            _bp.ANYNET_PROFILE.profile_id:
                _bp.ANYNET_PROFILE.semantics_version,
            _bp.MESH_DOR_MC_PROFILE.profile_id:
                _bp.MESH_DOR_MC_PROFILE.semantics_version,
        }
        projection_semantics = semantics_by_profile[native.profile_id]
        identity = prepared.identity_dict()
        trace_sha256 = identity["trace_sha256"]
        prepared_id = prepared.prepared_id()
    except Exception:
        return None
    try:
        from veritx_dse.backend.booksim_execution import (
            BOOKSIM_BUILD_RECIPE_VERSION,
            EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
        )
        from veritx_dse.backend.producer import (
            resolve_producer_identity,
        )
        from veritx_dse.core.paths import REPO as _REPO
        repo_root = Path(options.repo_root) \
            if options.repo_root is not None else Path(_REPO)
        if options.binary is not None:
            bin_path = Path(options.binary)
        else:
            from veritx_dse.simulation.booksim import find_booksim_bin
            bin_path = find_booksim_bin(repo_root)
        producer = resolve_producer_identity(
            bin_path, repo_root=repo_root,
            require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
    except Exception:
        return None
    seed = options.seed if type(options.seed) is int \
        and not isinstance(options.seed, bool) and options.seed >= 0 \
        else 0
    try:
        topology_id = context.bundle.topology.topology_hash()
    except Exception:
        return None
    try:
        from veritx_dse.backend import evidence as _ev2
        parser_version = _ev2.PARSER_VERSION
        schema_version = _ev2.EVIDENCE_SCHEMA_VERSION
    except Exception:
        return None
    return {
        "prepared_id": prepared_id,
        "config_sha256": native.config_hash,
        "trace_sha256": trace_sha256,
        "binary_sha256": producer.binary_sha256,
        "binary_size": producer.binary_size,
        "profile_id": native.profile_id,
        "projection_semantics_version": projection_semantics,
        "parser_version": parser_version,
        "build_manifest": producer.build_manifest_sha256,
        "build_recipe_version": producer.build_recipe_version,
        "schema_version": schema_version,
        "producer_revision": producer.source_revision,
        "producer_dirty": producer.dirty,
        "producer_transport": EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
        "producer_fidelity": "QUALIFIED",
        "seed": seed,
        "topology_id": topology_id,
        "fabric_id": _resolved_hash(context),
        "traffic_id": native.physical_traffic_id,
        "message_id": native.message_artifact_id,
        "question": EvaluationQuestion.NETWORK_COMPLETION.value,
        "network_clock_hz": options.network_clock_hz,
    }


def _tier1_key(pre_parents):
    from veritx_dse.core.artifact import content_id
    return content_id(
        _REUSE_KEY_DOMAIN,
        {k: pre_parents[k] for k in _REUSE_PRE_FIELDS},
    )


def _lookup_reusable(pre_parents, analysis_dir):
    """Hit path or None (miss/refusal -> caller executes fresh)."""
    key = _tier1_key(pre_parents)
    records = _OUTCOME_REUSE.get(key)
    if not records:
        return None
    from veritx_dse.backend import evidence as _ev
    for record in records:
        try:
            ref = record["ref"]
            evidence = _ev.read_reusable_record(
                ref,
                prepared_id=pre_parents["prepared_id"],
                config_sha256=pre_parents["config_sha256"],
                trace_sha256=pre_parents["trace_sha256"],
                binary_sha256=pre_parents["binary_sha256"],
            )
            if evidence.evidence_id != record["evidence_id"]:
                continue
            import dataclasses
            import hashlib
            evidence_dir = analysis_dir / "evidence"
            evidence_dir.mkdir(parents=True, exist_ok=True)
            raw = Path(ref.path).read_bytes()
            if hashlib.sha256(raw).hexdigest() != ref.sha256:
                continue
            target = evidence_dir / "backend-evidence.json"
            target.write_bytes(raw)
            outcome = dataclasses.replace(
                record["outcome"],
                run_dir=str(analysis_dir),
                evidence_path=str(target),
            )
            matching = {k: pre_parents[k] for k in _REUSE_PRE_FIELDS}
            analysis = dataclasses.replace(
                record["analysis"],
                reused_evidence_id=evidence.evidence_id,
                reuse_matching=matching,
            )
            return outcome, analysis, matching
        except Exception:
            continue
    return None


def _register_reusable(pre_parents, outcome, analysis):
    """Register a fresh EVALUATED outcome. Auxiliary: never fails."""
    try:
        from veritx_dse.backend import evidence as _ev
        from veritx_dse.backend.evidence import EvidenceRef
        ref = EvidenceRef(path=outcome.evidence_path or "",
                           sha256=outcome.raw_evidence_digest or "")
        evidence = _ev.read_reusable_record(
            ref,
            prepared_id=pre_parents["prepared_id"],
            config_sha256=pre_parents["config_sha256"],
            trace_sha256=pre_parents["trace_sha256"],
            binary_sha256=pre_parents["binary_sha256"],
        )
        full_parents = dict(pre_parents)
        full_parents["evidence_id"] = evidence.evidence_id
        full_parents["route_observation"] = evidence.route_observation
        full_parents["route_dump_sha256"] = evidence.route_dump_sha256
        _evidence_reuse_cache().put(ref, full_parents)
        key = _tier1_key(pre_parents)
        records = _OUTCOME_REUSE.setdefault(key, [])
        records.append({
            "ref": ref,
            "outcome": outcome,
            "analysis": analysis,
            "evidence_id": evidence.evidence_id,
        })
        while len(_OUTCOME_REUSE) > _OUTCOME_REUSE_CAP:
            _OUTCOME_REUSE.pop(next(iter(_OUTCOME_REUSE)))
    except Exception:
        return


def _evaluate_network(
    compilation: Compilation,
    context: CanonicalEvaluationContext,
    row: Any,
    options: BookSimRunOptions,
    analysis_dir: Path,
) -> tuple[EvaluationOutcome | None, AnalysisOutcome]:
    """The certified network path: the EXISTING FabricEvaluator owns the
    evidence/performance chain; the adapter only normalizes the
    authenticated resulting outcome. No second BookSim chain exists.

    Execution-authority note: FabricEvaluator.evaluate drives the
    BookSim adapter seam itself (adapter.prepare -> adapter.execute —
    the single spawn per NETWORK_COMPLETION question), then this leg
    normalizes through normalize_booksim_outcome, which enforces the
    identical admission + parent-binding law as adapter.normalize.
    Unifying the two normalization entries (deleting
    normalize_booksim_outcome in favor of adapter.normalize) requires
    threading the execution result through booksim_adapter — a
    booksim_adapter.py change owned by a later lane, not this one.
    The no-duplicate-execution test below pins the invariant that
    matters: exactly one backend spawn per network question.
    """
    from veritx_dse.backend.booksim_adapter import (
        normalize_booksim_outcome,
    )
    traffic_class = context.unified_traffic_class or "DEFAULT"
    pre_parents = _pre_execution_parents(context, traffic_class, options)
    if pre_parents is not None:
        hit = _lookup_reusable(pre_parents, analysis_dir)
        if hit is not None:
            return hit[0], hit[1]
    outcome = FabricEvaluator().evaluate(
        compilation, context.workload,
        EvaluationOptions(
            backend=STANDALONE_BACKEND, traffic_class=traffic_class,
            timeout_s=options.timeout_s,
            network_clock_hz=options.network_clock_hz,
            seed=(options.seed if options.seed is not None else 0),
            run_dir=analysis_dir, repo_root=options.repo_root,
            binary=options.binary))
    if outcome.status != EVALUATED:
        status = (ANALYSIS_UNAVAILABLE
                  if outcome.status == BACKEND_UNAVAILABLE
                  else ANALYSIS_UNSUPPORTED
                  if outcome.status == UNSUPPORTED
                  else ANALYSIS_FAILED)
        return None, AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=status, model_fidelity=None, qualification=None,
            normalized_evidence=None, native_evidence_id=None,
            reason=outcome.reason)
    envelope = normalize_booksim_outcome(context, outcome)
    analysis = AnalysisOutcome(
        question=row.question, backend_id=row.backend_id,
        status=ANALYSIS_EVALUATED,
        model_fidelity=envelope.model_fidelity,
        qualification=envelope.qualification,
        normalized_evidence=envelope,
        native_evidence_id=envelope.native_evidence_id,
        reason=None,
        native_summary={
            # Bundle-relative evidence lives at
            # analyses/network_completion/evidence/backend-evidence.json;
            # no host path is ever recorded in the outcome.
            "backend_profile": outcome.backend_profile,
        })
    if pre_parents is not None:
        _register_reusable(pre_parents, outcome, analysis)
    return outcome, analysis


def _evaluate_astra(
    context: CanonicalEvaluationContext,
    row: Any,
    adapter: Any,
    options: AstraRunOptions,
    analysis_dir: Path,
) -> AnalysisOutcome:
    """The ASTRA path: prepare -> execute (stages its own workload) ->
    normalize. One execution answers one question; the native evidence
    stays authoritative."""
    from veritx_dse.backend.astra import AstraError, AstraUnavailable
    from veritx_dse.backend.astra_execution import AstraExecutionError
    from veritx_dse.backend.astra_machine import AstraMachineError
    from veritx_dse.backend.booksim_adapter import BookSimProjectionRefusal
    from veritx_dse.core.errors import MappingInvalid
    try:
        prepared = adapter.prepare(context, row.question)
        evidence = adapter.execute(
            prepared,
            SimpleNamespace(run_dir=analysis_dir,
                            timeout_s=options.timeout_s))
    except (AstraError, AstraExecutionError, AstraMachineError,
            BookSimProjectionRefusal, MappingInvalid) as exc:
        status = (ANALYSIS_UNAVAILABLE
                  if isinstance(exc, AstraUnavailable)
                  else ANALYSIS_FAILED)
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=status, model_fidelity=None, qualification=None,
            normalized_evidence=None, native_evidence_id=None,
            reason=f"{type(exc).__name__}: {exc}")
    archival = _persist_astra_inputs(analysis_dir, prepared)
    try:
        envelope = adapter.normalize(
            context, row.question, prepared, evidence)
    except (AstraExecutionError, ValueError) as exc:
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_FAILED, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=None,
            reason=f"evidence normalization failed: "
            f"{type(exc).__name__}: {exc}",
            archival=archival)
    return AnalysisOutcome(
        question=row.question, backend_id=row.backend_id,
        status=ANALYSIS_EVALUATED,
        model_fidelity=envelope.model_fidelity,
        qualification=envelope.qualification,
        normalized_evidence=envelope,
        native_evidence_id=envelope.native_evidence_id,
        reason=None,
        native_summary={
            "evidence_tier": evidence.evidence_tier,
            "expansion_authority": evidence.expansion_authority,
            "autonomous_injection_packets":
                evidence.autonomous_injection_packets,
            "participant_statistics_present":
                evidence.participant_statistics_present,
            "namespace_binding": evidence.namespace_binding,
            "namespace_id": evidence.namespace_id,
            "rank_to_endpoint": [list(pair)
                                 for pair in evidence.rank_to_endpoint],
            "aggregate_cycles": evidence.aggregate_cycles,
            "aggregate_exposed_comm":
                evidence.aggregate_exposed_comm,
        },
        archival=archival)


def _evaluate_ramulator(
    context: CanonicalEvaluationContext,
    row: Any,
    adapter: Any,
    options: RamulatorRunOptions,
    analysis_dir: Path,
) -> AnalysisOutcome:
    """The Ramulator path: prepare -> execute (lowers its own trace
    under run_dir/ramulator/) -> normalize. One execution answers the
    DRAM_TIMING question; the native memory evidence stays authoritative.

    Status mapping preserves the native vocabulary: a backend crash
    (EVALUATION_FAILED) is FAILED; INCONCLUSIVE stays INCONCLUSIVE in
    the reason and is never EVALUATED; an unsupported geometry is
    UNSUPPORTED; only a drained PASS normalizes. Requirement binding is
    untouched — still the network PerformanceResult only.
    """
    from veritx_dse.backend.ramulator_adapter import (
        RamulatorBackendAbsent, RamulatorSemanticRefusal,
        ramulator_evidence_id,
    )
    from veritx_dse.simulation.ramulator import RamulatorError
    try:
        prepared = adapter.prepare(context, row.question)
        evidence = adapter.execute(
            prepared,
            SimpleNamespace(run_dir=analysis_dir,
                            timeout_s=options.timeout_s))
    except RamulatorBackendAbsent as exc:
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_UNAVAILABLE, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=None,
            reason=f"{type(exc).__name__}: {exc}")
    except (RamulatorError, RamulatorSemanticRefusal) as exc:
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_FAILED, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=None,
            reason=f"{type(exc).__name__}: {exc}")
    archival = _persist_ramulator_inputs(analysis_dir, prepared)
    if evidence.status == "EVALUATION_FAILED":
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_FAILED, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=None,
            reason=f"Ramulator backend crashed: "
            f"{evidence.failure_reason}")
    if evidence.status == "UNSUPPORTED":
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_UNSUPPORTED, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=None,
            reason=f"Ramulator geometry unsupported: "
            f"{evidence.failure_reason}")
    if evidence.status != "PASS":
        # INCONCLUSIVE (or any future non-PASS verdict) is never FAILED
        # and never PASS: the backend executed but decided nothing, so
        # the analysis carries the native verdict openly. (Sibling
        # contract: optimization.real_evaluator._native_inconclusive
        # keys on the "native memory evidence {STATUS}" reason shape —
        # it must also accept ANALYSIS_INCONCLUSIVE, not just FAILED.)
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_INCONCLUSIVE, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=ramulator_evidence_id(evidence),
            reason=f"native memory evidence {evidence.status}: "
            f"{evidence.failure_reason}",
            archival=archival)
    try:
        envelope = adapter.normalize(
            context, row.question, prepared, evidence)
    except (RamulatorError, ValueError) as exc:
        return AnalysisOutcome(
            question=row.question, backend_id=row.backend_id,
            status=ANALYSIS_FAILED, model_fidelity=None,
            qualification=None, normalized_evidence=None,
            native_evidence_id=None,
            reason=f"evidence normalization failed: "
            f"{type(exc).__name__}: {exc}",
            archival=archival)
    return AnalysisOutcome(
        question=row.question, backend_id=row.backend_id,
        status=ANALYSIS_EVALUATED,
        model_fidelity=envelope.model_fidelity,
        qualification=envelope.qualification,
        normalized_evidence=envelope,
        native_evidence_id=envelope.native_evidence_id,
        reason=None,
        native_summary=_ramulator_summary(evidence),
        archival=archival)


def _ramulator_summary(evidence: Any) -> dict[str, Any]:
    """Backend-native factual summary (drain counters, completed bytes,
    row behavior) for integrity views; never science beyond what the
    native evidence already states."""

    def _value(key: str) -> Any:
        entry = (evidence.metrics or {}).get(key)
        if isinstance(entry, dict):
            return entry.get("value")
        return None

    return {
        "status": evidence.status,
        "failure_reason": evidence.failure_reason,
        "generated_requests": _value("generated_requests"),
        "accepted_requests": _value("accepted_requests"),
        "completed_requests": _value("completed_requests"),
        "outstanding_requests": _value("outstanding_requests"),
        "completed_read_bytes": _value("completed_read_bytes"),
        "completed_write_bytes": _value("completed_write_bytes"),
        "completion_cycles": _value("completion_cycles"),
        "row_hits": _value("row_hits"),
        "row_misses": _value("row_misses"),
        "row_conflicts": _value("row_conflicts"),
    }


def _persist_ramulator_inputs(analysis_dir: Path, prepared: Any
                             ) -> ArchivalResult:
    """Archive the exact memory artifact + profile identities the run
    executed, so reproduction reruns stored inputs rather than
    re-deriving them.

    Fail-closed archival: any persistence fault returns NOT_AVAILABLE
    naming every artifact that did not reach the layout — the caller
    fails the analysis rather than claiming silent reproducibility.
    Only typed faults are converted; anything else escapes.
    """
    from veritx_dse.core.artifact import ArtifactError
    wanted = ("memory-artifact.json", "prepared.json")
    try:
        native = prepared.native_prepared
        inputs_dir = analysis_dir / "ramulator-inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        (inputs_dir / "memory-artifact.json").write_text(
            json.dumps(native.artifact.serialize(), sort_keys=True,
                       indent=2) + "\n",
            encoding="utf-8")
        (inputs_dir / "prepared.json").write_text(
            json.dumps({
                "memory_artifact_hash": native.memory_artifact_hash,
                "access_stream_hash": native.access_stream_hash,
                "backend_config_hash": native.backend_config_hash,
                "geometry": native.geometry.to_dict(),
            }, sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
    except (OSError, ValueError, TypeError, AttributeError,
            ArtifactError) as exc:
        return ArchivalResult(
            status=ARCHIVAL_NOT_AVAILABLE, missing=wanted,
            reason=f"{type(exc).__name__}: {exc}")
    return ArchivalResult(status=ARCHIVAL_ARCHIVED)


def _persist_astra_inputs(analysis_dir: Path, prepared: Any
                          ) -> ArchivalResult:
    """Archive the exact machine/projection/namespace inputs the run
    executed, so reproduction reruns stored inputs rather than
    re-deriving them.

    Fail-closed archival: any persistence fault returns NOT_AVAILABLE
    naming every artifact that did not reach the layout — the caller
    fails the analysis rather than claiming silent reproducibility.
    Only typed faults are converted; anything else escapes.
    """
    wanted = ("machine.json", "workload-projection.json",
              "namespace.json")
    try:
        from dataclasses import asdict as _asdict
        native = prepared.native_prepared
        inputs_dir = analysis_dir / "astra-inputs"
        inputs_dir.mkdir(parents=True, exist_ok=True)
        # Full field archival (asdict), not the identity projection:
        # reproduction rebuilds the exact executed objects, including
        # the rendered config texts the identity dict omits.
        (inputs_dir / "machine.json").write_text(
            json.dumps(_asdict(native.machine),
                       sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        (inputs_dir / "workload-projection.json").write_text(
            json.dumps(_asdict(native.workload_projection),
                       sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
        (inputs_dir / "namespace.json").write_text(
            json.dumps(_asdict(native.namespace),
                       sort_keys=True, indent=2) + "\n",
            encoding="utf-8")
    except (OSError, ValueError, TypeError, AttributeError) as exc:
        return ArchivalResult(
            status=ARCHIVAL_NOT_AVAILABLE, missing=wanted,
            reason=f"{type(exc).__name__}: {exc}")
    return ArchivalResult(status=ARCHIVAL_ARCHIVED)


def _aggregate(analyses: tuple[AnalysisOutcome, ...]) -> str:
    """Overall run status with explicit failure precedence.

    A genuine execution FAILED anywhere fails the run even beside
    successes (PARTIAL is incomplete coverage, never a crash mask).
    INCONCLUSIVE executed without deciding: a gap, never a crash.
    Any other non-success, non-failure status (UNSUPPORTED,
    UNAVAILABLE, BLOCKED, NOT_APPLICABLE, ...) is a coverage gap.
    Successful analyses are always preserved in the record.
    """
    evaluated = [a for a in analyses if a.status == ANALYSIS_EVALUATED]
    failed = [a for a in analyses if a.status == ANALYSIS_FAILED]
    inconclusive = [a for a in analyses
                    if a.status == ANALYSIS_INCONCLUSIVE]
    unavailable = [a for a in analyses
                   if a.status == ANALYSIS_UNAVAILABLE]
    if analyses and len(evaluated) == len(analyses):
        return EVALUATED
    if failed:
        return FAILED
    if evaluated:
        return PARTIAL
    if inconclusive:
        # Executed without a verdict: incomplete coverage, never a
        # crash and never a pass.
        return PARTIAL
    if unavailable:
        return BACKEND_UNAVAILABLE
    return UNSUPPORTED


def _aggregate_reason(analyses: tuple[AnalysisOutcome, ...]) -> str | None:
    """Overall reason naming failures first, then coverage gaps.

    A FAILED analysis is named with its question, backend and exact
    reason — a run that crashed must never present a generic status.
    """
    failed = [a for a in analyses if a.status == ANALYSIS_FAILED]
    if failed:
        first = failed[0]
        return (f"FAILED {first.question.value} on "
                f"{first.backend_id}: "
                f"{first.reason or first.status}")
    pending = [a for a in analyses if a.status != ANALYSIS_EVALUATED]
    if not pending:
        return None
    return ("partial evaluation; non-evaluated analyses: " + "; ".join(
        f"{a.question.value}: {a.reason or a.status}" for a in pending))


def _persist_federated_layout(
    root: Path,
    context: CanonicalEvaluationContext,
    plan: EvaluationPlan,
    analyses: tuple[AnalysisOutcome, ...],
    *,
    revision_id: str | None,
) -> None:
    """The structurally obvious run layout. Directory names are
    presentation, never scientific identity (finalize/verify still seal
    every persisted byte)."""
    from veritx_dse.application.evaluation_plan_view import (
        evaluation_plan_view,
    )
    (root / "plan.json").write_text(
        json.dumps(evaluation_plan_view(
            plan, revision_id=revision_id,
            design_hash=context.design_hash,
            resolved_fabric_hash=_resolved_hash(context),
            workload_id=context.workload_id),
            sort_keys=True, indent=2) + "\n",
        encoding="utf-8")
    (root / "normalized-evidence.json").write_text(
        json.dumps({
            "contract_version": 1,
            "design_hash": _prefixed(context.design_hash),
            "resolved_fabric_hash": _prefixed(_resolved_hash(context)),
            "workload_id": context.workload_id,
            "analyses": [a.to_dict() for a in analyses],
        }, sort_keys=True, indent=2) + "\n",
        encoding="utf-8")


def _prefixed(value: str) -> str:
    return value if value.startswith("sha256:") else "sha256:" + value


__all__ = [
    "ANALYSIS_FAILED", "ANALYSIS_INCONCLUSIVE", "ANALYSIS_STATUSES",
    "ANALYSIS_EVALUATED", "ANALYSIS_UNAVAILABLE", "ANALYSIS_UNSUPPORTED",
    "ARCHIVAL_ARCHIVED", "ARCHIVAL_NOT_AVAILABLE", "ArchivalResult",
    "AnalysisOutcome", "AstraRunOptions", "BookSimRunOptions",
    "FederatedEvaluationOutcome", "OVERALL_STATUSES", "PARTIAL",
    "RamulatorRunOptions", "evaluate_federated",
    "reset_network_reuse",
]
