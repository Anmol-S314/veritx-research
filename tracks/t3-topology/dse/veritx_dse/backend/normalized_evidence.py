"""The normalized evidence envelope — one shape, native authority.

The federation's common result carrier: every adapter normalizes its
backend-native evidence (ScientificBackendEvidence, AstraRuntimeEvidence,
serving/Ramulator evidence) into THIS envelope so planners, optimizers
and Studio read one shape. The native evidence stays authoritative and
is pointed at by ``native_evidence_id`` — the envelope is never a
conversion of, or replacement for, a foreign backend's evidence schema
(different backends express genuinely different things; flattening them
would be a semantic lie).

Like the other orchestration contracts this is in-memory: no
schema_version, no serialization. Content identity lives in the native
evidence and the canonical parents it names.
"""
from __future__ import annotations

from dataclasses import dataclass

from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.adapter import ModelFidelity


class NormalizedEvidenceError(ValueError):
    """A normalized evidence envelope was malformed."""


def _non_empty_str(name: str, value: object) -> None:
    if type(value) is not str or not value:
        raise NormalizedEvidenceError(
            f"{name} must be a non-empty string, got {value!r}")


@dataclass(frozen=True)
class MetricValue:
    """One measured quantity with its provenance attached.

    Every objective value that ever reaches an optimizer or the Studio
    rides in one of these: a number alone is not evidence.

    ``dimensions`` carries coordinates such as ``(("rank", "3"),)`` for
    per-rank ASTRA metrics or ``(("request_id", ...),)`` for serving —
    never invented key suffixes like ``rank_0_cycles``. Metric identity
    is ``(key, dimensions)``: the same key with different dimensions is
    a different measurement of the same quantity, not a duplicate.
    """

    key: str
    value: float
    unit: str | None
    source_metric_key: str | None
    dimensions: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        _non_empty_str("key", self.key)
        if type(self.value) is not float or self.value != self.value \
                or self.value in (float("inf"), float("-inf")):
            raise NormalizedEvidenceError(
                f"metric {self.key!r} value must be a finite float, got "
                f"{self.value!r}")
        if self.unit is not None:
            _non_empty_str("unit", self.unit)
        if self.source_metric_key is not None:
            _non_empty_str("source_metric_key", self.source_metric_key)
        if type(self.dimensions) is not tuple:
            raise NormalizedEvidenceError(
                "dimensions must be a tuple, got "
                f"{type(self.dimensions).__name__}")
        seen: set[str] = set()
        for dimension in self.dimensions:
            if type(dimension) is not tuple or len(dimension) != 2:
                raise NormalizedEvidenceError(
                    "each dimension must be exactly (name, value), got "
                    f"{dimension!r}")
            name, dimension_value = dimension
            _non_empty_str("dimension name", name)
            _non_empty_str("dimension value", dimension_value)
            if name in seen:
                raise NormalizedEvidenceError(
                    f"metric {self.key!r} has duplicate dimension "
                    f"{name!r}")
            seen.add(name)

    def identity(self) -> tuple[str, tuple[tuple[str, str], ...]]:
        """Metric identity: (key, dimensions), never the key alone."""
        return (self.key, self.dimensions)


@dataclass(frozen=True)
class NormalizedBackendEvidence:
    """The normalized view of one backend's authenticated evidence.

    ``qualification`` is the native execution/provenance verdict (e.g.
    ScientificBackendEvidence.execution_fidelity: QUALIFIED /
    DIAGNOSTIC_UNPINNED_PRODUCER / TEST_INJECTED, or an
    ExecutionQualification value) — deliberately orthogonal to
    ``model_fidelity``, which says what KIND of model produced the
    number. Never collapse the two dimensions.
    """

    backend_id: str
    question: EvaluationQuestion
    model_fidelity: ModelFidelity

    canonical_parent_ids: tuple[str, ...]
    native_evidence_id: str
    qualification: str
    producer_identity: str

    backend_config_hash: str | None = None
    backend_input_hash: str | None = None
    metrics: tuple[MetricValue, ...] = ()
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty_str("backend_id", self.backend_id)
        if not isinstance(self.question, EvaluationQuestion):
            raise NormalizedEvidenceError(
                f"question must be an EvaluationQuestion, got "
                f"{self.question!r}")
        if not isinstance(self.model_fidelity, ModelFidelity):
            raise NormalizedEvidenceError(
                f"model_fidelity must be a ModelFidelity, got "
                f"{self.model_fidelity!r}")
        if type(self.canonical_parent_ids) is not tuple or \
                not self.canonical_parent_ids:
            raise NormalizedEvidenceError(
                "canonical_parent_ids must be a non-empty tuple of "
                "canonical artifact identities")
        seen: set[str] = set()
        for parent in self.canonical_parent_ids:
            _non_empty_str("canonical_parent_ids entry", parent)
            if parent in seen:
                raise NormalizedEvidenceError(
                    f"canonical_parent_ids has duplicate {parent!r}")
            seen.add(parent)
        _non_empty_str("native_evidence_id", self.native_evidence_id)
        _non_empty_str("qualification", self.qualification)
        _non_empty_str("producer_identity", self.producer_identity)
        if self.backend_config_hash is not None:
            _non_empty_str("backend_config_hash", self.backend_config_hash)
        if self.backend_input_hash is not None:
            _non_empty_str("backend_input_hash", self.backend_input_hash)
        if type(self.metrics) is not tuple:
            raise NormalizedEvidenceError(
                "metrics must be a tuple, got "
                f"{type(self.metrics).__name__}")
        identities: set[
            tuple[str, tuple[tuple[str, str], ...]]] = set()
        for metric in self.metrics:
            if not isinstance(metric, MetricValue):
                raise NormalizedEvidenceError(
                    "metrics entries must be MetricValue, got "
                    f"{type(metric).__name__}")
            identity = metric.identity()
            if identity in identities:
                raise NormalizedEvidenceError(
                    f"metrics has duplicate (key, dimensions) "
                    f"{identity!r}")
            identities.add(identity)
        if type(self.limitations) is not tuple:
            raise NormalizedEvidenceError(
                "limitations must be a tuple, got "
                f"{type(self.limitations).__name__}")
        limitation_seen: set[str] = set()
        for limitation in self.limitations:
            _non_empty_str("limitations entry", limitation)
            if limitation in limitation_seen:
                raise NormalizedEvidenceError(
                    f"limitations has duplicate {limitation!r}")
            limitation_seen.add(limitation)

    def metric(self, key: str) -> MetricValue | None:
        for metric in self.metrics:
            if metric.key == key:
                return metric
        return None


def assert_envelope_matches_native(
        envelope: "NormalizedBackendEvidence",
        native: "ScientificBackendEvidence") -> None:
    """Prove a normalized envelope is a view over its native document.

    The envelope must name the native evidence id it was projected
    from; every metric carrying a ``source_metric_key`` must equal the
    native stat it claims to project (no swapped run-B numbers under a
    run-A id); the canonical parents must include the native binding
    identities; qualification and producer identity must be the native
    verdicts, not re-stated claims. Metrics without a source key are
    derived quantities and are not value-checked here.
    """
    from veritx_dse.backend.evidence import (
        BackendEvidenceError, canonical_hex64,
    )
    if envelope.native_evidence_id != native.evidence_id():
        raise NormalizedEvidenceError(
            "envelope native_evidence_id does not match the native "
            "document identity — refusing an envelope pointing at "
            "another run's evidence")
    for metric in envelope.metrics:
        source = metric.source_metric_key
        if source is None:
            continue
        if source not in native.stats:
            raise NormalizedEvidenceError(
                f"envelope metric {metric.key!r} claims native source "
                f"{source!r} the native document never measured")
        raw = native.stats[source]
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise NormalizedEvidenceError(
                f"envelope metric {metric.key!r} projects a "
                f"non-numeric native value {raw!r}")
        if float(raw) != metric.value:
            raise NormalizedEvidenceError(
                f"envelope metric {metric.key!r} value {metric.value!r} "
                f"does not equal the native {source!r} value "
                f"{float(raw)!r} — refusing swapped statistics")
    # Binding identities are digests; named parents (design names,
    # workload ids) are not comparable here and are skipped — the
    # adapter's outcome-vs-context checks own those.
    digests: set[str] = set()
    for parent in envelope.canonical_parent_ids:
        try:
            digests.add(canonical_hex64(parent, "parent"))
        except BackendEvidenceError:
            continue
    for name in ("message_artifact_id", "physical_traffic_id",
                 "resolved_fabric_hash"):
        bound = canonical_hex64(getattr(native, name), name)
        if bound not in digests:
            raise NormalizedEvidenceError(
                f"envelope parents omit the native {name} — refusing "
                f"an envelope detached from its binding identities")
    if envelope.qualification != native.execution_fidelity:
        raise NormalizedEvidenceError(
            "envelope qualification does not match the native "
            "execution fidelity")
    if canonical_hex64(envelope.producer_identity, "producer_identity") \
            != canonical_hex64(native.binary_sha256, "binary_sha256"):
        raise NormalizedEvidenceError(
            "envelope producer identity does not match the native "
            "producer binary")
        return None


__all__ = [
    "MetricValue", "NormalizedBackendEvidence", "NormalizedEvidenceError",
    "assert_envelope_matches_native",
]
