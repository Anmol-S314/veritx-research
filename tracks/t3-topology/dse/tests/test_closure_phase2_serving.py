"""Phase-2 serving strictness (closure RC-07): corrupt serving evidence
must refuse loudly at the native layer, never normalize silently.

1. RequestMetric rejects bool / non-integer / negative cycle counts
   at construction.
2. The normalization envelope refuses a corrupt metric (naming the
   request) instead of dropping it silently.
3. A ledger line that carries the [LEDGER][COLL_SUBMIT] marker but
   does not parse refuses as truncation/corruption at parse time.
4. An unknown collective comm_type refuses naming the encoding and
   rank instead of degrading the kinds-mismatch diagnosis.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from veritx_dse.backend import canonical_serving as cs
from veritx_dse.backend import serving_normalization as snorm
from veritx_dse.backend import serving_round as sround
from veritx_dse.backend.canonical_serving import (
    CanonicalServingEvidence, RequestMetric,
)


def _ledger_line(*, rank=0, node=1, ctype=0, size=1024,
                 members="{0,1,2,3}", tick=0):
    return (f"[LEDGER][COLL_SUBMIT] rank={rank} astra_node={node} "
            f"comm_type={ctype} comm_size={size} priority=0 "
            f"involved_dims=[1,1,1,1] group_members={members} "
            f"tick={tick}")


def _plan(**overrides):
    base = dict(batch_id=0, instance_id=0,
                request_ids=("r0",), participant_ranks=tuple(range(16)),
                phase="prefill", tokens=16, collective_kind="ALLREDUCE",
                collective_bytes=1024, compute_ns=10_000)
    base.update(overrides)
    return sround.ServingBatchPlan(**base)


# ── 1. RequestMetric construction gate ───────────────────────────────

@pytest.mark.parametrize("bad", [True, False, -1, -100, "100", 1.5,
                                 (100,), None.__class__])
def test_request_metric_rejects_corrupt_cycle_counts(bad):
    with pytest.raises(cs.ServingBoundaryError):
        RequestMetric(request_id="r0", ttft_cycles=bad,
                      completion_cycles=100)
    with pytest.raises(cs.ServingBoundaryError):
        RequestMetric(request_id="r0", ttft_cycles=100,
                      completion_cycles=bad)


def test_request_metric_accepts_absent_and_zero():
    assert RequestMetric(request_id="r0", ttft_cycles=None,
                         completion_cycles=0).ttft_cycles is None


# ── 2. Normalization refuses instead of dropping ─────────────────────

def _evidence_with_metrics(metrics):
    return CanonicalServingEvidence(
        workload_id="serve-test", serving_config_id="cfg/test",
        service_profile_id="sha256:" + "01" * 32,
        machine_id="machine-test", namespace_id="namespace-test",
        participant_mapping_id="mapping-test",
        serving_binding_id="binding-test", backend_id="backend-test",
        astra_binary_sha256="a" * 64, astra_binary_size=123,
        astra_source_revision="deadbeef",
        embedded_fabric_abi_version="v1",
        standalone_config_sha256="sha256:" + "02" * 32,
        network_evidence_tier="ASTRA_OWNED_COLLECTIVE_EXECUTION",
        expansion_authority="astra_comm_coll",
        execution_mode="LIVE_CANONICAL_EXECUTION",
        instance_count=1, served_instances=(0,),
        instances_with_completions=(0,), request_count=len(metrics),
        request_metrics=tuple(metrics), rounds=1,
        endpoint_completions=((0, 1),), backend_evidence_ids=("e1",))


def test_normalize_refuses_corrupt_metric_naming_request():
    bad = SimpleNamespace(request_id="req-evil", ttft_cycles="junk",
                          completion_cycles=None)
    evidence = _evidence_with_metrics([bad])
    with pytest.raises(snorm.ServingBoundaryError, match="req-evil"):
        snorm.normalize_serving_evidence(evidence)


def test_normalize_refuses_negative_metric():
    bad = SimpleNamespace(request_id="req-neg", ttft_cycles=-5,
                          completion_cycles=None)
    evidence = _evidence_with_metrics([bad])
    with pytest.raises(snorm.ServingBoundaryError, match="req-neg"):
        snorm.normalize_serving_evidence(evidence)


# ── 3. Truncated ledger line fails fast ──────────────────────────────

def test_truncated_ledger_line_names_truncation():
    truncated = "[LEDGER][COLL_SUBMIT] rank=0 astra_node=1 comm_type=0"
    with pytest.raises(sround.ServingRoundError, match="runcated"):
        sround.parse_collective_ledger([truncated])


def test_pure_noise_lines_still_skip():
    assert sround.parse_collective_ledger(
        ["some astra stdout noise", ""]) == ()
    entries = sround.parse_collective_ledger(
        ["noise", _ledger_line()])
    assert len(entries) == 1


# ── 4. Unknown comm_type names encoding and rank ─────────────────────

def test_unknown_comm_type_names_encoding_and_rank():
    entries = sround.parse_collective_ledger(
        [_ledger_line(rank=3, ctype=99)])
    assert entries[0].kind is None
    plan = _plan()
    with pytest.raises(sround.ServingRoundError, match="99"):
        sround.validate_collective_ledger(
            entries, plan=plan, expected_members=(0, 1, 2, 3))


def test_unknown_comm_type_refuses_in_contract_validator():
    entries = sround.parse_collective_ledger(
        [_ledger_line(rank=1, node=7, ctype=99)])
    contract = (sround.CollectiveContract(
        operation_id="op0", astra_node_id=7,
        collective_kind="ALLREDUCE", payload_bytes=1024,
        endpoints=(0, 1, 2, 3)),)
    with pytest.raises(sround.ServingRoundError, match="99"):
        sround.validate_collective_ledger_contract(
            entries, contract=contract)
