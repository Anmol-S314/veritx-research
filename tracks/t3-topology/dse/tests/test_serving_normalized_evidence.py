"""PROMPT 3 — normalized canonical serving evidence.

Serving authority stays where it is (submit_serving /
run_canonical_serve / CanonicalServingNetworkBackend /
CanonicalServingEvidence); this suite proves the normalized view over
it: live + complete evidence projects per-request TTFT/completion
envelopes with request_id dimensions, absent metrics stay absent (never
zero-filled), replay-only and partial runs refuse, and no TPOT is ever
invented.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import ModelFidelity  # noqa: E402
from veritx_dse.backend.canonical_serving import (  # noqa: E402
    CanonicalServingEvidence, RequestMetric, ServingBoundaryError,
)
from veritx_dse.backend.serving_normalization import (  # noqa: E402
    SERVING_BACKEND_ID, SERVING_QUESTIONS, normalize_serving_evidence,
    serving_envelopes_to_dicts,
)

DIGEST = "ab" * 32

def _evidence(*, mode="LIVE_CANONICAL_EXECUTION",
              tier="ASTRA_OWNED_COLLECTIVE_EXECUTION",
              instance_count=2,
              served=(0, 1),
              metrics=None) -> CanonicalServingEvidence:
    if metrics is None:
        metrics = (
            RequestMetric(request_id="req-a", ttft_cycles=100,
                          completion_cycles=500),
            RequestMetric(request_id="req-b", ttft_cycles=200,
                          completion_cycles=700),
        )
    return CanonicalServingEvidence(
        workload_id="serve-test",
        serving_config_id="cfg/test",
        service_profile_id="sha256:" + "01" * 32,
        machine_id="machine-test",
        namespace_id="namespace-test",
        participant_mapping_id="mapping-test",
        serving_binding_id="binding-test",
        backend_id="backend-test",
        astra_binary_sha256=DIGEST,
        astra_binary_size=123,
        astra_source_revision="deadbeef",
        embedded_fabric_abi_version="v1",
        standalone_config_sha256="sha256:" + "02" * 32,
        network_evidence_tier=tier,
        expansion_authority="astra_comm_coll",
        execution_mode=mode,
        instance_count=instance_count,
        served_instances=tuple(served),
        instances_with_completions=tuple(served),
        request_count=len(metrics),
        request_metrics=tuple(metrics),
        rounds=3,
        endpoint_completions=((0, 2),),
        backend_evidence_ids=("e1",))

def test_normalize_returns_exactly_ttft_and_completion():
    envelopes = normalize_serving_evidence(_evidence())
    assert [e.question for e in envelopes] == list(SERVING_QUESTIONS)
    assert [e.question for e in envelopes] == [
        EvaluationQuestion.SERVING_TTFT,
        EvaluationQuestion.SERVING_COMPLETION]

def test_ttft_envelope_carries_per_request_dimensions():
    (ttft, _) = normalize_serving_evidence(_evidence())
    assert ttft.backend_id == SERVING_BACKEND_ID
    assert ttft.model_fidelity is ModelFidelity.FULL_SYSTEM_SIMULATION
    by_request = {m.dimensions[0][1]: m for m in ttft.metrics}
    assert by_request["req-a"].key == "ttft_cycles"
    assert by_request["req-a"].value == 100.0
    assert by_request["req-a"].unit == "cycles"
    assert by_request["req-a"].source_metric_key == "ttft_cycles"
    assert by_request["req-b"].value == 200.0
    for metric in ttft.metrics:
        assert metric.dimensions[0][0] == "request_id"

def test_completion_envelope_carries_per_request_dimensions():
    (_, completion) = normalize_serving_evidence(_evidence())
    by_request = {m.dimensions[0][1]: m for m in completion.metrics}
    assert by_request["req-a"].key == "completion_cycles"
    assert by_request["req-a"].value == 500.0
    assert by_request["req-b"].value == 700.0

def test_native_identity_stays_bound():
    evidence = _evidence()
    (ttft, completion) = normalize_serving_evidence(evidence)
    for envelope in (ttft, completion):
        assert envelope.native_evidence_id == evidence.evidence_id()
        assert envelope.producer_identity == DIGEST
        assert envelope.qualification == "LIVE_CANONICAL_EXECUTION"
        assert "binding-test" in envelope.canonical_parent_ids
        assert "machine-test" in envelope.canonical_parent_ids
        assert evidence.service_profile_id in \
            envelope.canonical_parent_ids

def test_absent_metric_stays_absent_never_zero_filled():
    evidence = _evidence(metrics=(
        RequestMetric(request_id="req-a", ttft_cycles=None,
                      completion_cycles=500),
        RequestMetric(request_id="req-b", ttft_cycles=200,
                      completion_cycles=None),
    ))
    (ttft, completion) = normalize_serving_evidence(evidence)
    assert [m.dimensions[0][1] for m in ttft.metrics] == ["req-b"]
    assert [m.dimensions[0][1] for m in completion.metrics] == ["req-a"]
    assert all(m.value != 0.0 for m in (*ttft.metrics, *completion.metrics))

def test_no_tpot_is_ever_invented():
    (ttft, completion) = normalize_serving_evidence(_evidence())
    keys = {m.key for m in (*ttft.metrics, *completion.metrics)}
    assert keys == {"ttft_cycles", "completion_cycles"}

def test_replay_only_evidence_refuses():
    with pytest.raises(ServingBoundaryError, match="replay-only"):
        normalize_serving_evidence(
            _evidence(mode="REPLAY_ONLY_PROTOCOL"))

def test_wrong_tier_refuses():
    with pytest.raises(ServingBoundaryError):
        normalize_serving_evidence(_evidence(tier="OTHER_TIER"))

def test_partial_serving_refuses():
    with pytest.raises(ServingBoundaryError, match="not every serving"):
        normalize_serving_evidence(
            _evidence(instance_count=2, served=(0,)))

def test_foreign_evidence_type_refuses():
    with pytest.raises(TypeError):
        normalize_serving_evidence(object())

def test_envelopes_project_to_stable_dicts():
    envelopes = normalize_serving_evidence(_evidence())
    rows = serving_envelopes_to_dicts(envelopes)
    assert [r["question"] for r in rows] == [
        "SERVING_TTFT", "SERVING_COMPLETION"]
    assert rows[0]["metrics"][0]["dimensions"] == [["request_id", "req-a"]]
    assert rows[0]["backend_id"] == SERVING_BACKEND_ID
    assert rows[0]["model_fidelity"] == "FULL_SYSTEM_SIMULATION"

def test_persist_writes_envelopes_beside_native_evidence(tmp_path):
    import json
    from veritx_dse.simulation.serve_canonical import (
        _persist_serving_normalized_view,
    )
    evidence = _evidence()
    _persist_serving_normalized_view(tmp_path, evidence)
    document = json.loads(
        (tmp_path / "normalized-serving-evidence.json").read_text(
            encoding="utf-8"))
    assert document["normalized"] is True
    assert document["evidence_id"] == evidence.evidence_id()
    assert [a["question"] for a in document["analyses"]] == [
        "SERVING_TTFT", "SERVING_COMPLETION"]
    assert document["reason"] is None

def test_persist_partial_writes_absence_record_never_silent(tmp_path):
    import json
    from veritx_dse.simulation.serve_canonical import (
        _persist_serving_normalized_view,
    )
    evidence = _evidence(instance_count=2, served=(0,))
    _persist_serving_normalized_view(tmp_path, evidence)
    document = json.loads(
        (tmp_path / "normalized-serving-evidence.json").read_text(
            encoding="utf-8"))
    assert document["normalized"] is False
    assert document["analyses"] is None
    assert document["reason"]
