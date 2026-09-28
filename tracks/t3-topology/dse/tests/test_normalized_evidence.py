"""Federation Commit 08 — the normalized evidence envelope.

The one shape the federation's consumers read; the native evidence
stays authoritative. Pins the fidelity-vs-qualification orthogonality
and the provenance-carrying metric law.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import ModelFidelity  # noqa: E402
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence, NormalizedEvidenceError,
)

H64 = "a" * 64


def _envelope(**kw) -> NormalizedBackendEvidence:
    defaults = dict(
        backend_id="BOOKSIM_STANDALONE",
        question=EvaluationQuestion.NETWORK_COMPLETION,
        model_fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
        canonical_parent_ids=(H64, "b" * 64),
        native_evidence_id="native-evidence-1",
        qualification="QUALIFIED",
        producer_identity=H64,
        metrics=(MetricValue(key="completion_cycles", value=6164.0,
                             unit="cycles", source_metric_key=None),),
    )
    defaults.update(kw)
    return NormalizedBackendEvidence(**defaults)


def test_valid_envelope_constructs():
    env = _envelope()
    assert env.metric("completion_cycles").value == 6164.0
    assert env.metric("missing") is None


def test_question_and_fidelity_are_typed():
    with pytest.raises(NormalizedEvidenceError, match="EvaluationQuestion"):
        _envelope(question="NETWORK_COMPLETION")
    with pytest.raises(NormalizedEvidenceError, match="ModelFidelity"):
        _envelope(model_fidelity="NETWORK_PACKET_SIMULATION")


def test_native_evidence_id_and_producer_are_required():
    with pytest.raises(NormalizedEvidenceError):
        _envelope(native_evidence_id="")
    with pytest.raises(NormalizedEvidenceError):
        _envelope(producer_identity=None)


def test_canonical_parents_nonempty_no_duplicates():
    with pytest.raises(NormalizedEvidenceError, match="non-empty"):
        _envelope(canonical_parent_ids=())
    with pytest.raises(NormalizedEvidenceError, match="duplicate"):
        _envelope(canonical_parent_ids=(H64, H64))
    with pytest.raises(NormalizedEvidenceError, match="tuple"):
        _envelope(canonical_parent_ids=[H64])


def test_qualification_and_fidelity_are_orthogonal():
    """THE law: a diagnostic (unpinned-producer) run of a packet-level
    simulator is honest evidence — model kind is unchanged by provenance
    quality. And a qualified run of an analytical model is still an
    analytical estimate. Neither dimension reinterprets the other."""
    diagnostic_packet_run = _envelope(
        qualification="DIAGNOSTIC_UNPINNED_PRODUCER")
    assert diagnostic_packet_run.model_fidelity is \
        ModelFidelity.NETWORK_PACKET_SIMULATION
    assert diagnostic_packet_run.qualification == \
        "DIAGNOSTIC_UNPINNED_PRODUCER"

    qualified_analytical_run = _envelope(
        model_fidelity=ModelFidelity.ANALYTICAL_ESTIMATE,
        qualification="QUALIFIED")
    assert qualified_analytical_run.qualification == "QUALIFIED"


def test_metrics_are_finite_typed_no_duplicate_keys():
    with pytest.raises(NormalizedEvidenceError, match="finite"):
        _envelope(metrics=(MetricValue(
            key="x", value=float("nan"), unit=None,
            source_metric_key=None),))
    with pytest.raises(NormalizedEvidenceError, match="duplicate"):
        _envelope(metrics=(
            MetricValue(key="x", value=1.0, unit=None,
                        source_metric_key=None),
            MetricValue(key="x", value=2.0, unit=None,
                        source_metric_key=None),))
    with pytest.raises(NormalizedEvidenceError, match="MetricValue"):
        _envelope(metrics=(("x", 1.0),))
    with pytest.raises(NormalizedEvidenceError, match="tuple"):
        _envelope(metrics=[MetricValue(key="x", value=1.0, unit=None,
                                       source_metric_key=None)])


def test_metric_value_carries_source_provenance():
    """A normalized metric may name the native stat key it was derived
    from — no bare numbers without provenance."""
    m = MetricValue(key="completion_cycles", value=11720.0, unit="cycles",
                    source_metric_key="completion_time")
    assert m.source_metric_key == "completion_time"
    with pytest.raises(NormalizedEvidenceError):
        MetricValue(key="x", value=1.0, unit=None, source_metric_key="")


def test_limitations_follow_the_strict_tuple_law():
    with pytest.raises(NormalizedEvidenceError, match="tuple"):
        _envelope(limitations=["one VC envelope"])
    with pytest.raises(NormalizedEvidenceError, match="duplicate"):
        _envelope(limitations=("a", "a"))


def test_envelope_is_frozen():
    env = _envelope()
    with pytest.raises(dataclasses.FrozenInstanceError):
        env.qualification = "QUALIFIED"


def _rank_metric(rank: int, value: float = 1234.0) -> MetricValue:
    return MetricValue(
        key="completion_cycles", value=value, unit="cycles",
        source_metric_key="per_rank_cycles",
        dimensions=(("rank", str(rank)),))


def test_per_rank_metrics_share_a_key_with_different_dimensions():
    """No rank_0_cycles inventions: the same key with different
    dimensions is legal; identity is (key, dimensions)."""
    env = _envelope(metrics=(_rank_metric(0), _rank_metric(1, 1250.0)))
    assert env.metric("completion_cycles").dimensions == (("rank", "0"),)


def test_duplicate_key_and_dimensions_refused():
    with pytest.raises(NormalizedEvidenceError, match="duplicate"):
        _envelope(metrics=(_rank_metric(3), _rank_metric(3, 999.0)))


def test_dimensions_are_strict():
    with pytest.raises(NormalizedEvidenceError, match="tuple"):
        MetricValue(key="x", value=1.0, unit=None, source_metric_key=None,
                    dimensions=[("rank", "0")])
    with pytest.raises(NormalizedEvidenceError):
        MetricValue(key="x", value=1.0, unit=None, source_metric_key=None,
                    dimensions=(("rank", ""),))
    with pytest.raises(NormalizedEvidenceError, match="duplicate"):
        MetricValue(key="x", value=1.0, unit=None, source_metric_key=None,
                    dimensions=(("rank", "0"), ("rank", "1")))
    with pytest.raises(NormalizedEvidenceError):
        MetricValue(key="x", value=1.0, unit=None, source_metric_key=None,
                    dimensions=(("rank", "0", "extra"),))
