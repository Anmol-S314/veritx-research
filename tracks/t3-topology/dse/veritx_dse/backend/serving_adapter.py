"""The canonical serving federation adapter.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAdapter, BackendAssessment, BackendCapability, BackendReadiness,
    ModelFidelity, PreparedExecution, SupportLevel,
)
from veritx_dse.backend.canonical_serving import (
    CanonicalServingEvidence, RequestMetric, ServingBoundaryError,
)
from veritx_dse.backend.serving_normalization import (
    SERVING_BACKEND_ID, SERVING_LIMITATIONS, SERVING_MODEL_FIDELITY,
    SERVING_QUESTIONS, normalize_serving_evidence,
)

BACKEND_ID = SERVING_BACKEND_ID

#: model fidelity of a live serving run (shared with the normalization
#: authority; stated here so capabilities bind it, never redeclare it).
SERVING_ADAPTER_FIDELITY = SERVING_MODEL_FIDELITY

SERVING_ADAPTER_LIMITATIONS = SERVING_LIMITATIONS + (
    "serving experiment inputs (cluster service semantics, request "
    "trace, request count, service-profile overrides) are caller-bound "
    "at adapter construction; the planner never invents them",
    "the serving run executes on the evaluated design: prepare binds "
    "the context's own compile-request document and execute passes it "
    "as the fabric authority",
)

QUALIFICATION_PROFILE = "CANONICAL_SERVING_LIVE"


class ServingSemanticRefusal(ValueError):
    """The serving question has no representation for this context.

Rationale: docs/decisions/modules/backend.md
    """


class ServingRuntimeAbsent(Exception):
    """The serving runtime is absent: spec valid, nothing to execute on.

    Maps to UNAVAILABLE, never to a semantic verdict and never to a
    fabrication."""


@dataclass(frozen=True)
class ServingExperiment:
    """Caller-bound serving inputs. Paths resolve repo-relative or
    absolute at validation time; validation (not construction) refuses
    so a misconfigured experiment is a typed refusal with a reason."""

    cluster_config: str | Path
    dataset: str | Path
    num_reqs: int = 8
    profile_overrides: dict[str, Any] | None = None
    astra_binary: str | Path | None = None
    timeout_s: int = 900

    def identity_dict(self) -> dict[str, Any]:
        return {
            "cluster_config": str(self.cluster_config),
            "dataset": str(self.dataset),
            "num_reqs": self.num_reqs,
            "profile_overrides": dict(self.profile_overrides or {}),
            "astra_binary": (None if self.astra_binary is None
                             else str(self.astra_binary)),
            "timeout_s": self.timeout_s,
        }

    def experiment_id(self) -> str:
        return "sha256:" + hashlib.sha256(json.dumps(
            self.identity_dict(), sort_keys=True,
            separators=(",", ":")).encode()).hexdigest()


@dataclass(frozen=True)
class ServingPreparation:
    """What prepare() hands to execute() — the bound experiment plus the
    evaluated design's own compile-request document (in-memory; execute
    writes it beside the run). No execution, no runtime required."""

    experiment_id: str
    cluster_config: str
    dataset: str
    num_reqs: int
    profile_overrides: tuple[tuple[str, Any], ...]
    astra_binary: str | None
    timeout_s: int
    design_doc: dict[str, Any]
    design_hash: str
    workload_id: str


@dataclass(frozen=True)
class ServingNativeExecution:
    """The backend-native serving result: live evidence plus the run
    facts integrity views need. The evidence object (not a dict) rides
    here so normalize() never re-parses persisted bytes."""

    evidence: CanonicalServingEvidence
    design_hash: str
    run_dir: str
    requests_completed: int
    requests_expected: int
    rounds: int
    machine_id: str
    namespace_id: str


def _norm_model(name: str) -> str:
    return (name or "").lower().rsplit("/", 1)[-1].replace("_", "-").strip()


def _model_matches(cluster_models: Any, design_model: str) -> bool:
    """The cluster's model must be the design's model (vendor-prefix and
    case insensitive). Not a family heuristic — an identity match."""
    wanted = _norm_model(design_model)
    if not wanted:
        return False
    return any(_norm_model(m) == wanted for m in (cluster_models or ()))


def _repo_root() -> Path:
    from veritx_dse.core.paths import REPO
    return REPO


def _resolve_input(value: str | Path) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = _repo_root() / path
    return path


def _runtime_probe(astra_binary: str | Path | None) -> tuple[bool, str]:
    """Presence probe for the serving runtime. No spawn, no digest."""
    from veritx_dse.core.paths import REPO
    llm_root = REPO / "third_party" / "llmservingsim"
    if not llm_root.is_dir():
        return False, (
            f"LLMServingSim tree absent at {llm_root}: serving "
            f"semantics have no runtime")
    if astra_binary is not None:
        binary = Path(astra_binary)
        if not binary.is_absolute():
            binary = REPO / binary
        if not binary.is_file():
            return False, (
                f"configured ASTRA binary absent at {binary}")
        return True, ""
    default = (REPO / "third_party" / "astra-sim" / "astra-sim"
               / "network_frontend" / "booksim2" / "bin"
               / "AstraSim_BookSim2")
    if not default.is_file():
        return False, (
            f"ASTRA serving binary absent at {default}: build the "
            f"BookSim2 frontend before serving execution")
    return True, ""


class ServingAdapter:
    """Orchestrates bound-experiment serving through the canonical path.

Rationale: docs/decisions/modules/backend.md
    """

    def __init__(
        self,
        *,
        experiment: ServingExperiment | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        self._experiment = experiment
        self._repo_root = Path(repo_root) \
            if repo_root is not None else None
        self._capabilities: tuple[BackendCapability, ...] = tuple(
            BackendCapability(
                question=question, support=SupportLevel.SUPPORTED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                limitations=SERVING_ADAPTER_LIMITATIONS)
            for question in SERVING_QUESTIONS)

    @property
    def backend_id(self) -> str:
        return BACKEND_ID

    @property
    def experiment(self) -> ServingExperiment | None:
        return self._experiment

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload",
                "serving_experiment")

    # ── assess ────────────────────────────────────────────────────────

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        if question not in SERVING_QUESTIONS:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason="canonical serving answers SERVING_TTFT and "
                "SERVING_COMPLETION only",
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        experiment = self._experiment
        if experiment is None:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason="no serving experiment bound to this adapter: "
                "cluster service semantics, request trace, request "
                "count and service-profile overrides are caller-bound "
                "inputs the planner never invents",
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        try:
            self._validate_experiment(experiment)
        except ServingSemanticRefusal as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason=f"{type(exc).__name__}: {exc}",
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        # COMPATIBILITY: the cluster must serve exactly the evaluated
        # design's participant count. A catalog entry that cannot describe
        # this design is not "ready" — it is incompatible.
        try:
            facts = self.serving_cluster_facts(experiment)
        except Exception as exc:  # noqa: BLE001 - unreadable cluster
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason=f"bound serving cluster is unreadable: {exc}",
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        if not facts["internally_consistent"]:
            bad = facts["ep_exceeds_instance"]
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason=(
                    "bound serving cluster is internally inconsistent: "
                    f"EP size exceeds the instance TP span for instances "
                    f"{[(i, f'tp{tp}', f'ep{ep}') for i, tp, ep in bad]}; "
                    "the serving loop binds TP/EP groups inside one instance "
                    "and never multiplies ranks"),
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        served = facts["ranks"]
        design_ranks = getattr(context.workload, "participant_count", None)
        if design_ranks is not None and served != design_ranks:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason=(
                    "bound serving cluster is INCOMPATIBLE with this design: "
                    f"it serves {served} rank(s) but the design places "
                    f"{design_ranks}. A catalog entry that cannot describe "
                    "this design is not readiness."),
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        # MODEL: the cluster's model must be the design's model. Serving a
        # different model's measured profile would be a silent substitution.
        design_model = None
        request = getattr(context, "request", None)
        if request is not None:
            design_model = getattr(getattr(request, "workload", None),
                                   "model_name", None)
        if design_model and not _model_matches(facts["models"], design_model):
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason=(
                    "bound serving cluster is INCOMPATIBLE with this design: "
                    f"it profiles {facts['models']} but the design is "
                    f"{design_model!r}. Serving another model's measured "
                    "profile would be a silent substitution."),
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        present, reason = _runtime_probe(experiment.astra_binary)
        if not present:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=SERVING_ADAPTER_FIDELITY,
                qualification_profile=None,
                reason=reason,
                required_parents=self._required_parents(),
                limitations=SERVING_ADAPTER_LIMITATIONS)
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=SERVING_ADAPTER_FIDELITY,
            qualification_profile=QUALIFICATION_PROFILE,
            reason=None,
            required_parents=self._required_parents(),
            limitations=SERVING_ADAPTER_LIMITATIONS)

    @staticmethod
    def serving_cluster_facts(experiment: ServingExperiment) -> dict[str, Any]:
        """The cluster's serving geometry as the serve path reads it.

        Returns the serving rank count (sum of per-instance TP spans) and
        whether the cluster is internally consistent for the serving loop:
        every instance's EP size must fit inside that instance's TP span
        (TP/EP groups overlap; the rank count is never multiplied).
        """
        from veritx_dse.simulation.serve_canonical import (
            load_cluster_service_semantics,
        )
        service = load_cluster_service_semantics(experiment.cluster_config)
        instances = service["instances"]
        ranks = sum(max(int(i["tp_size"]), 1) for i in instances)
        inconsistent = [
            (index, int(i["tp_size"]), int(i["ep_size"]))
            for index, i in enumerate(instances)
            if int(i["ep_size"]) > max(int(i["tp_size"]), 1)
        ]
        return {
            "ranks": ranks,
            "models": sorted({i["model_name"] for i in instances}),
            "ep_exceeds_instance": inconsistent,
            "internally_consistent": not inconsistent,
        }

    @staticmethod
    def serving_rank_count(experiment: ServingExperiment) -> int:
        """The cluster's serving rank count (sum of per-instance TP spans)."""
        return ServingAdapter.serving_cluster_facts(experiment)["ranks"]

    @staticmethod
    def _validate_experiment(experiment: ServingExperiment) -> None:
        """Spec gates: files exist, counts sane, cluster semantics parse.

        Typed refusals only; programming errors escape (never BLOCKED).
        """
        cluster = _resolve_input(experiment.cluster_config)
        if not cluster.is_file():
            raise ServingSemanticRefusal(
                f"cluster service-semantics config not found: {cluster}")
        dataset = _resolve_input(experiment.dataset)
        if not dataset.is_file():
            raise ServingSemanticRefusal(
                f"request dataset not found: {dataset}")
        if isinstance(experiment.num_reqs, bool) or \
                not isinstance(experiment.num_reqs, int) \
                or experiment.num_reqs < 1:
            raise ServingSemanticRefusal(
                f"num_reqs must be a positive int, got "
                f"{experiment.num_reqs!r}")
        if experiment.profile_overrides is not None and \
                not isinstance(experiment.profile_overrides, dict):
            raise ServingSemanticRefusal(
                "profile_overrides must be a mapping or None, got "
                f"{type(experiment.profile_overrides).__name__}")
        if isinstance(experiment.timeout_s, bool) or \
                not isinstance(experiment.timeout_s, int) \
                or experiment.timeout_s < 1:
            raise ServingSemanticRefusal(
                f"timeout_s must be a positive int, got "
                f"{experiment.timeout_s!r}")
        from veritx_dse.simulation.serve_canonical import (
            load_cluster_service_semantics,
        )
        try:
            load_cluster_service_semantics(cluster)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ServingSemanticRefusal(
                f"cluster service semantics do not parse: "
                f"{type(exc).__name__}: {exc}") from exc

    # ── prepare ───────────────────────────────────────────────────────

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """Bind the experiment to THIS design. No execution, no runtime.

        The context's own compile-request document rides in the
        preparation so execute() serves this evaluated fabric — never a
        derived one.
        """
        if question not in SERVING_QUESTIONS:
            raise ServingSemanticRefusal(
                "canonical serving answers SERVING_TTFT and "
                "SERVING_COMPLETION only")
        experiment = self._experiment
        if experiment is None:
            raise ServingSemanticRefusal(
                "no serving experiment bound to this adapter")
        self._validate_experiment(experiment)
        try:
            design_doc = context.request.to_dict()
        except Exception as exc:
            raise ServingSemanticRefusal(
                f"evaluated design has no serializable compile request: "
                f"{type(exc).__name__}: {exc}") from exc
        if not isinstance(design_doc, dict) or not design_doc:
            raise ServingSemanticRefusal(
                "evaluated design serializes to an empty document")
        return PreparedExecution(
            backend_id=self.backend_id,
            projection_identity=experiment.experiment_id(),
            qualification_identity=None,
            backend_config=None, backend_input=None, producer=None,
            native_prepared=ServingPreparation(
                experiment_id=experiment.experiment_id(),
                cluster_config=str(_resolve_input(
                    experiment.cluster_config)),
                dataset=str(_resolve_input(experiment.dataset)),
                num_reqs=experiment.num_reqs,
                profile_overrides=tuple(sorted(
                    dict(experiment.profile_overrides or {}).items())),
                astra_binary=(None if experiment.astra_binary is None
                              else str(experiment.astra_binary)),
                timeout_s=experiment.timeout_s,
                design_doc=design_doc,
                design_hash=context.design_hash,
                workload_id=context.workload_id))

    # ── execute ───────────────────────────────────────────────────────

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> ServingNativeExecution:
        """Run the bound experiment on the prepared design, live.

        The single canonical entry (``run_canonical_serve``) executes;
        no alternative runner exists. The persisted evidence document is
        read back and strictly rebuilt (evidence-id recompute), so a
        substituted file refuses instead of normalizing.
        """
        from veritx_dse.simulation.serve_canonical import (
            run_canonical_serve,
        )
        native = prepared.native_prepared
        if not isinstance(native, ServingPreparation):
            raise TypeError(
                f"ServingAdapter.execute takes a PreparedExecution "
                f"whose native_prepared is a ServingPreparation, got "
                f"{type(native).__name__}")
        run_dir = Path(getattr(options, "run_dir"))
        timeout_s = getattr(options, "timeout_s", native.timeout_s)
        present, reason = _runtime_probe(native.astra_binary)
        if not present:
            raise ServingRuntimeAbsent(reason)
        run_dir.mkdir(parents=True, exist_ok=True)
        request_path = run_dir / "compile-request.json"
        request_path.write_text(
            json.dumps(native.design_doc, sort_keys=True, indent=2)
            + "\n", encoding="utf-8")
        (run_dir / "serving-experiment.json").write_text(
            json.dumps({
                "experiment_id": native.experiment_id,
                "cluster_config": native.cluster_config,
                "dataset": native.dataset,
                "num_reqs": native.num_reqs,
                "profile_overrides": dict(native.profile_overrides),
                "design_hash": native.design_hash,
                "workload_id": native.workload_id,
            }, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        result = run_canonical_serve(
            cluster_config=native.cluster_config,
            dataset=native.dataset, num_reqs=native.num_reqs,
            run_dir=run_dir, compile_request=request_path,
            astra_binary=native.astra_binary,
            profile_overrides=dict(native.profile_overrides) or None,
            timeout_s=timeout_s)
        evidence_path = run_dir / "serving-evidence.json"
        if not evidence_path.is_file():
            raise ServingBoundaryError(
                "canonical serve path produced no serving-evidence.json: "
                "refusing to normalize an unpersisted run")
        try:
            doc = json.loads(evidence_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ServingBoundaryError(
                f"persisted serving evidence does not parse: "
                f"{type(exc).__name__}: {exc}") from exc
        evidence = _evidence_from_doc(doc)
        return ServingNativeExecution(
            evidence=evidence, design_hash=native.design_hash,
            run_dir=str(run_dir),
            requests_completed=result.requests_completed,
            requests_expected=result.requests_expected,
            rounds=result.rounds, machine_id=result.machine_id,
            namespace_id=result.namespace_id)

    # ── normalize ─────────────────────────────────────────────────────

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> Any:
        """Project the live evidence into the asked question's envelope.

        The shared normalization authority decides metric truth; this
        method only selects the asked envelope and binds it against the
        preparation (design-hash match refuses transplanted runs).
        """
        from veritx_dse.backend.normalized_evidence import (
            NormalizedBackendEvidence,
        )
        if question not in SERVING_QUESTIONS:
            raise ServingSemanticRefusal(
                "canonical serving answers SERVING_TTFT and "
                "SERVING_COMPLETION only")
        native = prepared.native_prepared
        if not isinstance(native, ServingPreparation):
            raise TypeError(
                f"ServingAdapter.normalize takes a PreparedExecution "
                f"whose native_prepared is a ServingPreparation, got "
                f"{type(native).__name__}")
        if not isinstance(native_result, ServingNativeExecution):
            raise TypeError(
                f"ServingAdapter.normalize takes a "
                f"ServingNativeExecution, got "
                f"{type(native_result).__name__}")
        if native_result.design_hash != native.design_hash:
            raise ServingBoundaryError(
                "native serving execution does not bind this "
                "preparation's design: refusing a transplanted "
                "normalization")
        envelopes = normalize_serving_evidence(native_result.evidence)
        for envelope in envelopes:
            if envelope.question is question:
                assert isinstance(envelope, NormalizedBackendEvidence)
                return envelope
        raise ServingBoundaryError(  # pragma: no cover - closed pair
            f"no {question.value} envelope projected")


_EVIDENCE_FIELDS: tuple[str, ...] = (
    "workload_id", "serving_config_id", "service_profile_id",
    "machine_id", "namespace_id", "participant_mapping_id",
    "serving_binding_id", "backend_id", "astra_binary_sha256",
    "astra_binary_size", "astra_source_revision",
    "embedded_fabric_abi_version", "standalone_config_sha256",
    "network_evidence_tier", "expansion_authority", "execution_mode",
    "instance_count", "served_instances", "instances_with_completions",
    "request_count", "request_metrics", "rounds",
    "endpoint_completions", "backend_evidence_ids",
    "autonomous_injection_packets",
)

#: persisted-envelope keys that are NOT constructor inputs (derived
#: views over the identity, never inputs to it).
_EVIDENCE_DERIVED_KEYS: tuple[str, ...] = (
    "type", "schema_version", "evidence_id", "reusable",
    "every_instance_served",
)


def _evidence_from_doc(doc: Any) -> CanonicalServingEvidence:
    """Strictly rebuild live evidence from its persisted document.

    Verbatim field carry, then the evidence-id recompute: a substituted
    file refuses here instead of normalizing foreign science.
    """
    if not isinstance(doc, dict):
        raise ServingBoundaryError(
            f"serving evidence document must be an object, got "
            f"{type(doc).__name__}")
    unknown = sorted(set(doc) - set(_EVIDENCE_FIELDS)
                     - set(_EVIDENCE_DERIVED_KEYS))
    if unknown:
        raise ServingBoundaryError(
            f"serving evidence carries unknown fields {unknown}: "
            f"refusing to normalize evidence whose schema changed "
            f"without review")
    missing = [name for name in _EVIDENCE_FIELDS if name not in doc]
    if missing:
        raise ServingBoundaryError(
            f"serving evidence is missing fields {missing}")
    try:
        metrics = tuple(
            RequestMetric(request_id=row[0], ttft_cycles=row[1],
                          completion_cycles=row[2])
            for row in doc["request_metrics"])
        evidence = CanonicalServingEvidence(
            **{name: (tuple(doc[name])
                      if name in ("served_instances",
                                  "instances_with_completions",
                                  "backend_evidence_ids")
                      else tuple(tuple(pair)
                                 for pair in doc[name])
                      if name == "endpoint_completions"
                      else tuple(doc[name])
                      if name == "autonomous_injection_packets"
                      else doc[name])
               for name in _EVIDENCE_FIELDS
               if name != "request_metrics"},
            request_metrics=metrics)
    except (TypeError, ValueError, IndexError, KeyError) as exc:
        raise ServingBoundaryError(
            f"persisted serving evidence is malformed: "
            f"{type(exc).__name__}: {exc}") from exc
    if evidence.evidence_id() != doc.get("evidence_id"):
        raise ServingBoundaryError(
            "persisted serving evidence id does not recompute: "
            "refusing a substituted evidence document")
    return evidence


__all__ = [
    "BACKEND_ID", "QUALIFICATION_PROFILE",
    "SERVING_ADAPTER_FIDELITY", "SERVING_ADAPTER_LIMITATIONS",
    "ServingAdapter", "ServingExperiment", "ServingNativeExecution",
    "ServingPreparation", "ServingRuntimeAbsent",
    "ServingSemanticRefusal",
]
