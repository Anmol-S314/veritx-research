"""The standalone-BookSim backend adapter.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace as _NS
from typing import Any

from veritx_dse.application.evaluation_context import (
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import (
    BackendAdapter, BackendAssessment, BackendCapability, BackendReadiness,
    ModelFidelity, PreparedExecution, SupportLevel,
)
from veritx_dse.performance.traffic_class import (
    TrafficClassMetricsError, build_traffic_class_metrics,
)

class BookSimProjectionRefusal(Exception):
    """The canonical traffic/fabric pair is not projectable to BookSim.

Rationale: docs/decisions/modules/backend.md
    """

    def __init__(self, reason: str, *,
                 message_artifact_id: str | None = None,
                 physical_traffic_id: str | None = None) -> None:
        super().__init__(reason)
        self.message_artifact_id = message_artifact_id
        self.physical_traffic_id = physical_traffic_id

BOOKSIM_MODEL_FIDELITY = ModelFidelity.NETWORK_PACKET_SIMULATION

@dataclass(frozen=True)
class BookSimExecutionResult:
    """The backend-native result: the execution record plus the pinned
    producer identity the evidence chain must bind."""

    record: Any
    producer: Any

class BookSimExecutionFailure(Exception):
    """The prepared execution failed AFTER the producer was identified.
    Carries the producer identity so a FAILED outcome can still bind
    which binary ran — the pre-adapter evaluator always did."""

    def __init__(self, message: str, *, producer: Any) -> None:
        super().__init__(message)
        self.producer = producer

@dataclass(frozen=True)
class BookSimPreparation:
    """What prepare() hands to execute() — the native prepared input plus
    the identity fields the evaluator's outcome binds."""

    prepared: Any
    physical_traffic: Any
    message_artifact_id: str
    physical_traffic_id: str
    profile_id: str
    config_hash: str
    input_hash: str
    realization_digest: str

def _check_booksim_evidence_binding(
    evidence: Any, *,
    message_artifact_id: str | None,
    physical_traffic_id: str | None,
    config_hash: str | None,
    input_hash: str | None,
    realization_digest: str | None,
    resolved_fabric_hash: str,
) -> None:
    """Anti-transplant: persisted evidence must claim exactly the
    preparation (and fabric) it is normalized against.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.backend.evidence import BackendEvidenceError

    def _require(name: str, claimed: Any, bound: Any) -> None:
        if bound is None:
            raise BackendEvidenceError(
                f"cannot normalize BookSim evidence: the {name} this "
                f"run binds is absent — refusing an unbound "
                f"normalization")
        if claimed != bound:
            raise BackendEvidenceError(
                f"native evidence {name} {claimed!r} does not match "
                f"the prepared {name} {bound!r} — refusing a "
                f"transplanted normalization")

    _require("prepared_id", evidence.prepared_id, realization_digest)
    _require("config_sha256", evidence.config_sha256, config_hash)
    _require("trace_sha256", evidence.trace_sha256, input_hash)
    _require("message_artifact_id", evidence.message_artifact_id,
             message_artifact_id)
    _require("physical_traffic_id", evidence.physical_traffic_id,
             physical_traffic_id)
    _require("resolved_fabric_hash", evidence.resolved_fabric_hash,
             resolved_fabric_hash)

_CLASS_MAP_UNAVAILABLE = (
    "per-class readings are present in the native stats but the "
    "canonical trace class map is unavailable, so no per-class reading "
    "was projected")

def _class_index(value: Any) -> int | None:
    """A trace-class index from an int or its canonical JSON string key."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str) and value.isdigit() \
            and str(int(value)) == value:
        return int(value)
    return None

def _per_class_metric_values(
        stats: Mapping[str, Any],
        trace_classes: Any) -> tuple[list[Any], str | None]:
    """The per-class counter/latency readings this evidence carries.

    BookSim reports ``stats.flits_by_class`` by trace class INDEX; the
    canonical NAME comes from ``PreparedBookSimInput.trace_class_map``
    (or the equivalent map derived from the same canonical traffic).
    ``stats.latency_by_class`` uses the same index order and is exposed
    only for fields the fork actually printed. Returns ``(values,
    limitation)`` and never fabricates:

    - an index the map does not name refuses the WHOLE per-class
      projection (the map and the evidence disagree — a guessed name
      would relabel a measurement);
    - an index the stats omit is simply absent (the class has no reading,
      which is not a zero);
    - a non-integer counter refuses rather than coercing.
    """
    from veritx_dse.backend.normalized_evidence import MetricValue
    from veritx_dse.optimization.metric_registry import (
        BOOKSIM_PER_CLASS_LATENCY_METRICS, BOOKSIM_PER_CLASS_METRICS,
        traffic_class_dimensions,
    )
    has_counters = isinstance(stats, Mapping) and bool(
        stats.get("flits_by_class"))
    latency_stats = (stats.get("latency_by_class")
                     if isinstance(stats, Mapping) else None)
    has_latency = isinstance(latency_stats, Mapping) and bool(latency_stats)
    if not has_counters and not has_latency:
        return [], None
    classes = tuple(trace_classes or ())
    if not classes:
        # A single class block is fully represented by the aggregate scalar
        # latency keys; without a canonical map there is no honest NAME for
        # a dimensioned row, so nothing is projected and nothing is claimed.
        if not has_counters and isinstance(latency_stats, Mapping) \
                and len(latency_stats) == 1:
            return [], None
        return [], _CLASS_MAP_UNAVAILABLE
    values: list[MetricValue] = []

    def _class_name(raw_index: Any,
                    seen: set[int]) -> tuple[str | None, str | None]:
        index = _class_index(raw_index)
        if index is None or index >= len(classes):
            return None, (
                f"native per-class index {raw_index!r} is outside the "
                f"canonical class map {list(classes)}; refusing to guess "
                f"a class name")
        if index in seen:
            return None, (
                f"native per-class stats repeat class index {index}; "
                f"refusing a spliced per-class reading")
        seen.add(index)
        return classes[index], None

    counters = (stats.get("flits_by_class")
                if isinstance(stats, Mapping) else None)
    if isinstance(counters, Mapping) and counters:
        seen: set[int] = set()
        for raw_index, row in counters.items():
            class_name, reason = _class_name(raw_index, seen)
            if reason is not None:
                return [], reason.replace(
                    "native per-class", "native flits_by_class")
            if not isinstance(row, Mapping):
                return [], (
                    f"native flits_by_class[{raw_index}] is not a counter "
                    f"mapping; refusing to invent per-class values")
            for metric, counter in BOOKSIM_PER_CLASS_METRICS:
                raw = row.get(counter)
                if raw is None:
                    continue
                if isinstance(raw, bool) or not isinstance(raw, int) \
                        or raw < 0:
                    return [], (
                        f"native flits_by_class[{raw_index}][{counter!r}] "
                        f"is not a non-negative integer, got {raw!r}")
                values.append(MetricValue(
                    key=metric, value=float(raw), unit=None,
                    source_metric_key=None,
                    dimensions=traffic_class_dimensions(class_name)))

    latency = (stats.get("latency_by_class")
               if isinstance(stats, Mapping) else None)
    if isinstance(latency, Mapping) and latency:
        seen = set()
        for raw_index, row in latency.items():
            class_name, reason = _class_name(raw_index, seen)
            if reason is not None:
                return [], reason.replace(
                    "native per-class", "native latency_by_class")
            if not isinstance(row, Mapping):
                return [], (
                    f"native latency_by_class[{raw_index}] is not a "
                    f"latency mapping; refusing to invent per-class values")
            for metric, field in BOOKSIM_PER_CLASS_LATENCY_METRICS:
                raw = row.get(field)
                if raw is None:
                    continue
                if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                    return [], (
                        f"native latency_by_class[{raw_index}][{field!r}] "
                        f"is not a real number, got {raw!r}")
                number = float(raw)
                if number != number or abs(number) == float("inf"):
                    return [], (
                        f"native latency_by_class[{raw_index}][{field!r}] "
                        f"is not finite, got {raw!r}")
                if metric == "pkt_count" and (
                        not isinstance(raw, int) or raw < 0):
                    return [], (
                        f"native latency_by_class[{raw_index}][{field!r}] "
                        f"is not a non-negative integer, got {raw!r}")
                values.append(MetricValue(
                    key=metric, value=number, unit=None,
                    source_metric_key=None,
                    dimensions=traffic_class_dimensions(class_name)))
    values.sort(key=lambda metric: (metric.key, metric.dimensions))
    return values, None

def _trace_classes_of(physical_traffic: Any) -> tuple[str, ...]:
    """The canonical trace class map of a physical traffic artifact.

    The SAME function the projection renders trace indices with, so the
    index->name correspondence is the renderer's own, not a second copy.
    Single-class artifacts are named too (the prepared input binds no map
    there, but the one class is still canonical). Any refusal is () —
    callers then decline to project per-class readings.
    """
    if physical_traffic is None:
        return ()
    try:
        from veritx_dse.backend.booksim_projection import trace_class_map
        return tuple(trace_class_map(physical_traffic))
    except Exception:  # optional enrichment: never fail a normalization
        return ()

def _physical_traffic_from_context(context: Any) -> Any | None:
    """The canonical physical traffic this context projects, or None."""
    try:
        _logical, physical = BookSimAdapter()._canonical_traffic(
            context,
            traffic_class=getattr(context, "unified_traffic_class", None))
    except Exception:  # optional enrichment: never fail a normalization
        return None
    return physical


def _trace_classes_from_context(context: Any) -> tuple[str, ...] | None:
    """The canonical trace class map this context projects, or None.

    Rebuilds the SAME canonical traffic the evaluator built (the workload
    layer memoizes it by content) and reads the ONE class-map authority.
    Any refusal or absent context means "no map" — normalization never
    guesses a class name, it only declines to project per-class readings.
    """
    physical = _physical_traffic_from_context(context)
    return _trace_classes_of(physical) or None


def _traffic_class_metrics_from_evidence(
        *,
        stats: Mapping[str, Any],
        classes: tuple[str, ...],
        flit_width_bits: int | None,
        evidence_sha256: str,
        stats_sha256: str,
) -> dict[str, Any] | None:
    """Build the verified-result per-class block from parsed evidence stats."""
    return build_traffic_class_metrics(
        stats=stats, class_names=classes,
        flit_width_bits=flit_width_bits,
        evidence_sha256=evidence_sha256, stats_sha256=stats_sha256)


def _attach_traffic_class_metrics(outcome: Any, block: Any) -> None:
    """Attach per-class readings to the outcome's verified result.

    The block is not part of the result's content identity (aggregate
    results keep their exact identity) but it is digest-bound to the
    result's network binding; ``reverify_result`` refuses a mismatch.
    """
    if block is None:
        return
    performance = getattr(outcome, "performance_result", None)
    if not isinstance(performance, dict):
        return
    binding = performance.get("network_binding")
    if not isinstance(binding, dict):
        return
    if performance.get("traffic_class_metrics") is not None:
        return
    def _bare(value: Any) -> Any:
        return value[7:] if isinstance(value, str) \
            and value.startswith("sha256:") else value
    if _bare(block.get("evidence_sha256")) != \
            _bare(binding.get("evidence_sha256")) \
            or _bare(block.get("stats_sha256")) != \
            _bare(binding.get("stats_sha256")):
        return
    performance["traffic_class_metrics"] = block

class BookSimAdapter:
    """Orchestrates the certified standalone-BookSim execution chain.

Rationale: docs/decisions/modules/backend.md
    """

    def __init__(
        self,
        *,
        binary: str | Path | None = None,
        repo_root: str | Path | None = None,
    ) -> None:
        self._binary = Path(binary) if binary is not None else None
        self._repo_root = Path(repo_root) if repo_root is not None else None
        # One evaluation asks for the same context's traffic more than once
        # (assess() for planning, then _prepare_native() for preparation),
        # and materialising millions of packets twice is pure waste. Keyed
        # by the context's identity, so a hit is provably the same inputs;
        # the context is held in the entry to keep its id from being reused.
        self._traffic_cache: dict[
            tuple[int, str | None], tuple[Any, Any, Any]] = {}
        self._capabilities: tuple[BackendCapability, ...] = (
            BackendCapability(
                question=EvaluationQuestion.NETWORK_COMPLETION,
                support=SupportLevel.SUPPORTED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                limitations=(
                    "network packet simulation only: cycles are the "
                    "canonical projection's completion window, never "
                    "end-to-end workload runtime",)),
        )

    @property
    def backend_id(self) -> str:
        return "BOOKSIM_STANDALONE"

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return self._capabilities

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason="standalone BookSim answers NETWORK_COMPLETION only",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        try:
            _logical, physical = self._canonical_traffic(
                context, traffic_class=context.unified_traffic_class)
            self._select_profile(context, physical)
        except BookSimProjectionRefusal as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=str(exc),
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        try:
            bin_path = self._resolve_binary()
        except FileNotFoundError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.UNAVAILABLE,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"BookSim producer absent: {exc}",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        from veritx_dse.backend.booksim_execution import (
            BOOKSIM_BUILD_RECIPE_VERSION,
        )
        from veritx_dse.backend.producer import (
            ProducerError, assert_pinned_producer,
            resolve_producer_identity,
        )
        try:
            producer = resolve_producer_identity(
                bin_path, repo_root=self._repo_root_or_default(),
                require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        except ProducerError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"BookSim producer not qualified: {exc}",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        try:
            assert_pinned_producer(producer)
        except ProducerError as exc:
            return BackendAssessment(
                backend_id=self.backend_id, question=question,
                support=SupportLevel.SUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                fidelity=BOOKSIM_MODEL_FIDELITY,
                qualification_profile=None,
                reason=f"BookSim producer not pinned: {exc}",
                required_parents=self._required_parents(),
                limitations=self._capabilities[0].limitations)
        return BackendAssessment(
            backend_id=self.backend_id, question=question,
            support=SupportLevel.SUPPORTED,
            readiness=BackendReadiness.READY,
            fidelity=BOOKSIM_MODEL_FIDELITY,
            qualification_profile="CERTIFIED_BOOKSIM",
            reason=None,
            required_parents=self._required_parents(),
            limitations=self._capabilities[0].limitations)

    def _repo_root_or_default(self) -> Path:
        if self._repo_root is not None:
            return self._repo_root
        from veritx_dse.core.paths import REPO as _REPO
        return Path(_REPO)

    def _resolve_binary(self) -> Path:
        """The BookSim executable: explicit configuration first, else the
        canonical discovery. Absence is FileNotFoundError (UNAVAILABLE),
        never a semantic verdict."""
        if self._binary is not None:
            if not self._binary.is_file():
                raise FileNotFoundError(
                    f"explicit BookSim binary absent: {self._binary}")
            return self._binary
        from veritx_dse.simulation.booksim import find_booksim_bin
        return find_booksim_bin(self._repo_root_or_default())

    def _required_parents(self) -> tuple[str, ...]:
        return ("design", "resolved_fabric", "workload",
                "message_artifact", "physical_traffic")

    def _canonical_traffic(
            self, context: CanonicalEvaluationContext,
            *, traffic_class: str | None = None) -> tuple[Any, Any]:
        """Build the canonical message/traffic artifacts EXACTLY as the
        pre-adapter evaluator did: V3 per-message classes when the
        lowering is multi-class, V2 with the ASSERTED class when it is
        single-class — then admit every class against the compiled VC
        assignment (before spawn; never silent VC0).

Rationale: docs/decisions/modules/backend.md
        """
        cache_key = (id(context), traffic_class)
        cached = self._traffic_cache.get(cache_key)
        if cached is not None and cached[0] is context:
            return cached[1], cached[2]

        from veritx_dse.application.fabric_evaluator import (
            VCAdmissionError, _admit_traffic_classes,
        )
        from veritx_dse.core.errors import (
            ConservationFailed, EvidenceInvalid, InvalidInput,
            MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
        )
        from veritx_dse.workload.messages import (
            LogicalMessageArtifactV2, LogicalMessageArtifactV3,
        )
        from veritx_dse.workload.traffic import (
            PhysicalTrafficArtifactV2, PhysicalTrafficArtifactV3,
        )
        workload = context.workload
        expected_class = context.unified_traffic_class
        try:
            from veritx_dse.workload.intent_lowering import assert_traffic_classes_bound
            assert_traffic_classes_bound(
                context.lowered_workload, context.bundle.vc_assignment,
                multi_plane=getattr(
                    context.compilation, "multi_plane_vc", None))
            if expected_class is None:
                logical = LogicalMessageArtifactV3(
                    graph=workload,
                    traffic_class_by_operation=(
                        context.lowered_workload.traffic_class_by_operation))
                physical = PhysicalTrafficArtifactV3(
                    logical=logical,
                    resolved_fabric=context.bundle.resolved_fabric,
                    mapping=context.bundle.mapping,
                    attachment=context.bundle.attachment,
                    inventory=context.bundle.inventory,
                    packet_format=context.bundle.packet_format)
            else:
                if traffic_class is None:
                    raise BookSimProjectionRefusal(
                        "single-class evaluation must assert the lowered "
                        "traffic class (the intent owns class names; "
                        "evaluation only asserts them)")
                logical = LogicalMessageArtifactV2(
                    workload, traffic_class=traffic_class)
                physical = PhysicalTrafficArtifactV2(
                    logical=logical,
                    resolved_fabric=context.bundle.resolved_fabric,
                    mapping=context.bundle.mapping,
                    attachment=context.bundle.attachment,
                    inventory=context.bundle.inventory,
                    packet_format=context.bundle.packet_format)
        except (UnsupportedSemantics, UnsupportedSchedule) as exc:
            raise BookSimProjectionRefusal(
                f"workload semantics unprojectable: {exc}") from exc
        except MappingInvalid as exc:
            raise BookSimProjectionRefusal(
                f"traffic binding refused: {type(exc).__name__}: {exc}") from exc
        except (InvalidInput, EvidenceInvalid, ConservationFailed) as exc:
            raise BookSimProjectionRefusal(
                f"workload lowering failed: {type(exc).__name__}: {exc}") \
                from exc
        try:
            _admit_traffic_classes(
                logical, context.bundle,
                multi_plane=getattr(
                    context.compilation, "multi_plane_vc", None))
        except VCAdmissionError as exc:
            raise BookSimProjectionRefusal(
                f"traffic-class admission refused: {exc}",
                message_artifact_id=logical.message_artifact_id(),
                physical_traffic_id=physical.physical_traffic_id()) from exc
        if len(self._traffic_cache) >= 2:
            self._traffic_cache.clear()
        self._traffic_cache[(id(context), traffic_class)] = (
            context, logical, physical)
        return logical, physical

    def _assert_intent_class(
            self, context: CanonicalEvaluationContext,
            traffic_class: str | None, *, logical: Any,
            physical: Any) -> None:
        """The intent-class assertion (semantics outside workload_id):
        relabeling at eval time is refused. Multi-class lowerings assert
        nothing globally — their classes are per-message, admitted above."""
        expected_class = context.unified_traffic_class
        if expected_class is not None and traffic_class != expected_class:
            raise BookSimProjectionRefusal(
                f"evaluation traffic class {traffic_class!r} does "
                f"not match the lowered intent class {expected_class!r}: "
                f"eval-time relabeling is refused (the intent owns class "
                f"names; evaluation only asserts them)",
                message_artifact_id=logical.message_artifact_id(),
                physical_traffic_id=physical.physical_traffic_id())

    def _projection_parents(
            self, context: CanonicalEvaluationContext,
            physical: Any) -> Any:
        """The certified projection parents for this context — the same
        object preparation consumes. Profile selection over these is a
        semantic gate shared by assess() and prepare()."""
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionParents,
        )
        from veritx_dse.model.multi_plane_vc import (
            materialize_multi_plane_vc,
        )
        from veritx_dse.model.vc_resource import (
            vc_resources_from_assignment,
        )
        bundle = context.bundle
        return BookSimProjectionParents(
            resolved_fabric=bundle.resolved_fabric,
            topology=bundle.topology,
            attachment=bundle.attachment, mapping=bundle.mapping,
            vc_resource=vc_resources_from_assignment(
                bundle.vc_assignment),
            vc_assignment=bundle.vc_assignment,
            packet_format=bundle.packet_format,
            route=bundle.router_route,
            physical_traffic=physical, source_bundle=bundle,
            multi_plane_vc=materialize_multi_plane_vc(
                primary=bundle.vc_assignment, topology=bundle.topology))

    def _select_profile(
            self, context: CanonicalEvaluationContext,
            physical: Any) -> str:
        """The certified profile for this fabric, or a typed refusal."""
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionError, select_booksim_profile,
        )
        try:
            profile = select_booksim_profile(self._projection_parents(context, physical))
            from veritx_dse.backend.router_controls import CONTROLLED_BASE
            # CMesh and the per-class-VC mesh profile are qualified, but
            # still pass through the same live qualifier so the assessment
            # never trusts profile selection alone. Running these through
            # evaluate_qualification means a stale semantics, lowerer or
            # evidence path turns the assessment into a typed refusal rather
            # than an unearned READY.
            if (profile.profile_id in ("CERTIFIED_BOOKSIM_MESH_DOR_CLASS_VC_V1",
                                      "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1")
                    or profile.profile_id in CONTROLLED_BASE):
                from veritx_dse.application.booksim_qualification_registry import evaluate_qualification
                qualified, reason = evaluate_qualification(profile, self._projection_parents(context, physical))
                if not qualified:
                    raise BookSimProjectionRefusal(reason)
            return profile.profile_id
        except BookSimProjectionError as exc:
            raise BookSimProjectionRefusal(
                f"{type(exc).__name__}: {exc}") from exc

    def _prepare_native(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        *,
        traffic_class: str | None = None,
    ) -> BookSimPreparation:
        """The backend-native preparation: canonical artifacts + admission
        + projection. Only KNOWN semantic/projection failures become a
        refusal — programming bugs escape and fail tests, never a
        semantic verdict."""
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            raise BookSimProjectionRefusal(
                "standalone BookSim answers NETWORK_COMPLETION only")
        logical, physical = self._canonical_traffic(
            context, traffic_class=traffic_class)
        self._assert_intent_class(context, traffic_class,
                                  logical=logical, physical=physical)
        from veritx_dse.backend.booksim_projection import (
            BookSimProjectionError, prepare_booksim_input,
        )
        from veritx_dse.core.errors import (
            ConservationFailed, EvidenceInvalid, InvalidInput,
            MappingInvalid, UnsupportedSchedule, UnsupportedSemantics,
        )
        parents = self._projection_parents(context, physical)
        try:
            prepared = prepare_booksim_input(parents)
        except (BookSimProjectionError, InvalidInput, EvidenceInvalid,
                MappingInvalid, ConservationFailed, UnsupportedSemantics,
                UnsupportedSchedule) as exc:
            raise BookSimProjectionRefusal(
                f"{type(exc).__name__}: {exc}") from exc
        from veritx_dse.backend.booksim_execution import (
            CONFIG_FILE, TRACE_FILE, prepared_file_digests,
        )
        digests = prepared_file_digests(prepared)
        return BookSimPreparation(
            prepared=prepared, physical_traffic=physical,
            message_artifact_id=logical.message_artifact_id(),
            physical_traffic_id=physical.physical_traffic_id(),
            profile_id=prepared.profile_id,
            config_hash=digests[CONFIG_FILE],
            input_hash=digests[TRACE_FILE],
            realization_digest=prepared.prepared_id())

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """The federation seam: native preparation wrapped in the generic
        ``PreparedExecution``. No duplicate BackendConfigArtifact /
        BackendInputManifest is manufactured to fill fields the BookSim
        projection does not naturally expose — those stay None while the
        native preparation carries the real identities."""
        traffic_class = kwargs.get("traffic_class")
        if traffic_class is not None and not isinstance(traffic_class, str):
            raise BookSimProjectionRefusal(
                f"traffic_class must be a string, got "
                f"{type(traffic_class).__name__}")
        native = self._prepare_native(
            context, question,
            traffic_class=traffic_class)  # type: ignore[arg-type]
        return PreparedExecution(
            backend_id=self.backend_id,
            projection_identity=native.realization_digest,
            qualification_identity=native.profile_id,
            backend_config=None, backend_input=None, producer=None,
            native_prepared=native)

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> Any:
        """Run the prepared input under a pinned producer.

        ``options`` is the evaluator's own namespace (binary, run_dir,
        timeout, seed, repo_root) — the backend-native execution options;
        migrating them into a generic dataclass is deliberately NOT this
        commit. Returns the ``ExecutionRecord`` unchanged.
        """
        from veritx_dse.backend.booksim_execution import (
            BOOKSIM_BUILD_RECIPE_VERSION,
        )
        from veritx_dse.backend.booksim_execution import (
            BookSimExecutionError, execute_prepared_booksim,
        )
        from veritx_dse.backend.producer import (
            ProducerError, assert_pinned_producer,
            resolve_producer_identity,
        )
        native = prepared.native_prepared
        if not isinstance(native, BookSimPreparation):
            raise TypeError(
                f"BookSimAdapter.execute takes a PreparedExecution whose "
                f"native_prepared is a BookSimPreparation, got "
                f"{type(native).__name__}")
        bin_path = Path(options.binary) \
            if getattr(options, "binary", None) is not None \
            else self._resolve_binary()
        repo_root = Path(options.repo_root) \
            if getattr(options, "repo_root", None) is not None \
            else self._repo_root_or_default()
        producer = resolve_producer_identity(
            bin_path, repo_root=repo_root,
            require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION)
        assert_pinned_producer(producer)
        try:
            record = execute_prepared_booksim(
                prepared=native.prepared, binary=bin_path,
                run_dir=Path(options.run_dir) / "run",
                timeout=options.timeout, seed=options.seed,
                repo_root=repo_root, write=True,
                require_pinned_producer=True,
                require_manifest_recipe=BOOKSIM_BUILD_RECIPE_VERSION,
                sample_period_cycles=getattr(
                    options, "sample_period_cycles", None),
                series_link_width_bits=getattr(
                    options, "series_link_width_bits", None),
                series_flit_width_bits=getattr(
                    options, "series_flit_width_bits", None),
                series_store_dir=getattr(
                    options, "series_store_dir", None))
        except BookSimExecutionError as exc:
            raise BookSimExecutionFailure(
                f"{type(exc).__name__}: {exc}",
                producer=producer) from exc
        return BookSimExecutionResult(record=record, producer=producer)

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> NormalizedBackendEvidence:
        """Project the authenticated native evidence into the normalized
        envelope. Re-reads the persisted bytes through the canonical
        reader and admits them for certified product use — normalization
        never invents metrics, and never invents wall time."""
        from veritx_dse.backend.normalized_evidence import (
            MetricValue, NormalizedBackendEvidence,
        )
        if question is not EvaluationQuestion.NETWORK_COMPLETION:
            raise BookSimProjectionRefusal(
                "standalone BookSim answers NETWORK_COMPLETION only")
        native = prepared.native_prepared
        if not isinstance(native, BookSimPreparation):
            raise TypeError(
                f"BookSimAdapter.normalize takes a PreparedExecution "
                f"whose native_prepared is a BookSimPreparation, got "
                f"{type(native).__name__}")
        if not isinstance(native_result, BookSimExecutionResult):
            raise TypeError(
                f"BookSimAdapter.normalize takes a "
                f"BookSimExecutionResult, got "
                f"{type(native_result).__name__}")
        from veritx_dse.backend.evidence import (
            ScientificBackendEvidence, admit_for_certified_product,
            read_verified_evidence, validate_evidence_document,
        )
        persisted = read_verified_evidence(native_result.record.ref)
        if not isinstance(persisted.get("evidence"), dict):
            from veritx_dse.backend.evidence import BackendEvidenceError
            raise BackendEvidenceError(
                "persisted evidence wrapper carries no scientific "
                "evidence document")
        verified_doc = validate_evidence_document(persisted["evidence"])
        evidence = ScientificBackendEvidence.from_dict(verified_doc)
        admit_for_certified_product(evidence)
        _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
        resolved_hash = _resolved() if callable(_resolved) else _resolved
        _check_booksim_evidence_binding(
            evidence,
            message_artifact_id=native.message_artifact_id,
            physical_traffic_id=native.physical_traffic_id,
            config_hash=native.config_hash,
            input_hash=native.input_hash,
            realization_digest=native.realization_digest,
            resolved_fabric_hash=resolved_hash)
        metrics: list[MetricValue] = []
        from veritx_dse.optimization.metric_registry import (
            BOOKSIM_PER_CLASS_LATENCY_METRICS,
        )
        latency_keys = {metric for metric, _field
                        in BOOKSIM_PER_CLASS_LATENCY_METRICS}
        latency_by_class = evidence.stats.get("latency_by_class")
        classes = (getattr(native.prepared, "trace_class_map", ())
                   or _trace_classes_of(native.physical_traffic))
        multi_class_latency = (
            (isinstance(latency_by_class, Mapping)
             and len(latency_by_class) > 1)
            or len(tuple(classes or ())) > 1)
        for key, value in evidence.stats.items():
            if multi_class_latency and key in latency_keys:
                # The historical scalar latency keys match the FIRST
                # ``Class N:`` block, which is class 0 — not an aggregate
                # for a multi-class run. The measured per-class rows below
                # carry the real readings; never relabel class 0 as all.
                continue
            if isinstance(value, bool):
                continue
            if isinstance(value, int):
                metrics.append(MetricValue(
                    key=key, value=float(value), unit=None,
                    source_metric_key=key))
            elif isinstance(value, float):
                if value == value and abs(value) != float("inf"):
                    metrics.append(MetricValue(
                        key=key, value=value, unit=None,
                        source_metric_key=key))
        per_class, class_limitation = _per_class_metric_values(
            evidence.stats, classes)
        metrics.extend(per_class)
        limitations = self._capabilities[0].limitations
        if multi_class_latency:
            limitations = limitations + (
                "multi-class BookSim latency is printed per traffic "
                "class; the scalar packet/flit latency keys are not an "
                "aggregate and are not normalized",)
        if class_limitation is not None:
            limitations = limitations + (class_limitation,)
        return NormalizedBackendEvidence(
            backend_id=self.backend_id, question=question,
            model_fidelity=BOOKSIM_MODEL_FIDELITY,
            canonical_parent_ids=(
                context.design_hash, resolved_hash,
                context.workload_id,
                native.message_artifact_id,
                native.physical_traffic_id),
            native_evidence_id=evidence.evidence_id(),
            qualification=evidence.execution_fidelity,
            producer_identity=evidence.binary_sha256,
            backend_config_hash=native.config_hash,
            backend_input_hash=native.input_hash,
            metrics=tuple(metrics),
            limitations=limitations)

def normalize_booksim_outcome(
    context: CanonicalEvaluationContext,
    outcome: Any,
    *,
    trace_class_map: tuple[str, ...] | None = None,
) -> NormalizedBackendEvidence:
    """Normalize the authenticated resulting outcome of the certified
    FabricEvaluator — the federated path that must NOT construct a
    second BookSim evidence chain.

    ``trace_class_map`` is the canonical class map this run rendered. The
    federated path may pass the map it prepared; when it does not, the map
    is derived from the same canonical traffic the evaluator built. Without
    one, per-class counters stay unprojected (a named limitation), never
    guessed.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.backend.normalized_evidence import (
        MetricValue, NormalizedBackendEvidence,
    )
    if getattr(outcome, "status", None) != "EVALUATED":
        raise BookSimProjectionRefusal(
            f"only an EVALUATED BookSim outcome normalizes, got "
            f"{getattr(outcome, 'status', None)!r}")
    from veritx_dse.backend.evidence import (
        BackendEvidenceError, admit_normalize_bare_evidence,
    )
    evidence_path = getattr(outcome, "evidence_path", None)
    if not evidence_path:
        raise BackendEvidenceError(
            "the BookSim outcome carries no evidence path; refusing to "
            "normalize an outcome without persisted evidence")
    producer_sha = getattr(outcome, "producer_identity", None)
    if not producer_sha:
        raise BackendEvidenceError(
            "the BookSim outcome names no producer identity; refusing "
            "to normalize evidence without a bound producer")
    sealed = getattr(outcome, "raw_evidence_digest", None)
    if not sealed:
        raise BackendEvidenceError(
            "the BookSim outcome names no sealed evidence digest; "
            "refusing to normalize evidence without a digest binding")
    evidence = admit_normalize_bare_evidence(
        Path(evidence_path),
        expected_sha256=sealed,
        prepared_id=getattr(outcome, "realization_digest", None),
        config_sha256=getattr(outcome, "backend_config_hash", None),
        trace_sha256=getattr(outcome, "backend_input_hash", None),
        binary_sha256=producer_sha)
    if outcome.design_hash != context.design_hash:
        raise BackendEvidenceError(
            f"BookSim outcome design_hash {outcome.design_hash!r} does "
            f"not match this context {context.design_hash!r} — "
            f"refusing a transplanted normalization")
    if outcome.workload_id != context.workload_id:
        raise BackendEvidenceError(
            f"BookSim outcome workload_id {outcome.workload_id!r} does "
            f"not match this context {context.workload_id!r} — "
            f"refusing a transplanted normalization")
    _outcome_resolved = context.bundle.resolved_fabric.resolved_fabric_hash
    _outcome_resolved_hash = _outcome_resolved() \
        if callable(_outcome_resolved) else _outcome_resolved
    if outcome.resolved_fabric_hash != _outcome_resolved_hash:
        raise BackendEvidenceError(
            "BookSim outcome resolved_fabric_hash does not match this "
            "context — refusing a transplanted normalization")
    _check_booksim_evidence_binding(
        evidence,
        message_artifact_id=outcome.message_artifact_id,
        physical_traffic_id=outcome.physical_traffic_id,
        config_hash=outcome.backend_config_hash,
        input_hash=outcome.backend_input_hash,
        realization_digest=outcome.realization_digest,
        resolved_fabric_hash=_outcome_resolved_hash)
    metrics: list[MetricValue] = []
    physical = _physical_traffic_from_context(context)
    classes = tuple(trace_class_map or ()) \
        or _trace_classes_of(physical) or ()
    from veritx_dse.optimization.metric_registry import (
        BOOKSIM_PER_CLASS_LATENCY_METRICS,
    )
    latency_keys = {metric for metric, _field
                    in BOOKSIM_PER_CLASS_LATENCY_METRICS}
    latency_by_class = evidence.stats.get("latency_by_class")
    multi_class_latency = (
        (isinstance(latency_by_class, Mapping)
         and len(latency_by_class) > 1)
        or len(classes) > 1)
    stats = outcome.metrics or {}
    for key, value in stats.items():
        if multi_class_latency and key in latency_keys:
            # Class blocks are per class; the scalar key is class 0's
            # first block, never a multi-class aggregate.
            continue
        if isinstance(value, bool):
            continue
        if isinstance(value, int):
            metrics.append(MetricValue(
                key=key, value=float(value), unit=None,
                source_metric_key=key))
        elif isinstance(value, float):
            if value == value and abs(value) != float("inf"):
                metrics.append(MetricValue(
                    key=key, value=value, unit=None,
                    source_metric_key=key))
    per_class, class_limitation = _per_class_metric_values(
        evidence.stats, classes)
    metrics.extend(per_class)
    limitations = (
        "network packet simulation only: cycles are the "
        "canonical projection's completion window, never "
        "end-to-end workload runtime",)
    if multi_class_latency:
        limitations = limitations + (
            "multi-class BookSim latency is printed per traffic "
            "class; the scalar packet/flit latency keys are not an "
            "aggregate and are not normalized",)
    if class_limitation is not None:
        limitations = limitations + (class_limitation,)
    flit_width_bits = getattr(
        getattr(physical, "packet_format", None), "flit_width_bits", None)
    # The direct evaluator already attaches the authenticated class block
    # through the ONE application helper; reuse it instead of deriving a
    # second block here. Only an outcome without one is enriched locally.
    performance = getattr(outcome, "performance_result", None)
    class_block = (performance.get("traffic_class_metrics")
                   if isinstance(performance, dict) else None)
    if class_block is None:
        try:
            if len(classes) > 1:
                class_block = _traffic_class_metrics_from_evidence(
                    stats=evidence.stats, classes=classes,
                    flit_width_bits=flit_width_bits,
                    evidence_sha256=outcome.raw_evidence_digest,
                    stats_sha256=outcome.stats_digest)
        except TrafficClassMetricsError as exc:
            limitation = f"per-class requirement evidence refused: {exc}"
            if limitation not in limitations:
                limitations = limitations + (limitation,)
    _attach_traffic_class_metrics(outcome, class_block)
    _resolved = context.bundle.resolved_fabric.resolved_fabric_hash
    resolved_hash = _resolved() if callable(_resolved) else _resolved
    return NormalizedBackendEvidence(
        backend_id="BOOKSIM_STANDALONE",
        question=EvaluationQuestion.NETWORK_COMPLETION,
        model_fidelity=BOOKSIM_MODEL_FIDELITY,
        canonical_parent_ids=(
            context.design_hash, resolved_hash,
            context.workload_id,
            outcome.message_artifact_id,
            outcome.physical_traffic_id),
        native_evidence_id=evidence.evidence_id(),
        qualification=evidence.execution_fidelity,
        producer_identity=evidence.binary_sha256,
        backend_config_hash=outcome.backend_config_hash,
        backend_input_hash=outcome.backend_input_hash,
        metrics=tuple(metrics),
        limitations=limitations)

__all__ = [
    "BOOKSIM_MODEL_FIDELITY", "BookSimAdapter", "BookSimExecutionResult",
    "BookSimPreparation", "BookSimProjectionRefusal",
    "normalize_booksim_outcome",
]
