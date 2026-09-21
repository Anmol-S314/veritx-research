"""P1C phase-2 fix 3 tests: single-class bridge, honest multi-class refusal.

Run: cd tracks/t3-topology/dse && python3 -m pytest tests/test_p1c_eval_bridge.py -q
"""
from __future__ import annotations

import pytest

from veritx_dse.core.errors import InvalidInput, UnsupportedSemantics
from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    RequirementV3,
    QoSClass,
    ServingMode,
    TopologyFamily,
    WorkloadV3,
)
from veritx_dse.workload.intent_lowering import (
    bridge_to_evaluation_messages,
    lower_compile_workload,
)


def _request(collectives, tp=4, dp=1):
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=tp, dp=dp,
            serving_mode=ServingMode.MIXED,
            collectives=tuple(collectives)),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=tp * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _ci(tc="tp_collective", kind="allreduce", dim="TP", payload=2048):
    return CollectiveIntent(kind=CollectiveKind(kind),
                            dimension=CollectiveDimension(dim),
                            payload_bytes=payload, traffic_class=tc)


class TestEvalBridge:
    def test_single_class_routes_into_canonical_chain(self):
        lowered = lower_compile_workload(_request([_ci()]))
        msgs = bridge_to_evaluation_messages(lowered)
        assert msgs.traffic_class == "tp_collective"
        assert len(msgs.messages) > 0
        msgs.validate_conservation()

    def test_matching_requested_class_asserts_through(self):
        lowered = lower_compile_workload(_request([_ci()]))
        msgs = bridge_to_evaluation_messages(
            lowered, requested_traffic_class="tp_collective")
        assert msgs.traffic_class == "tp_collective"

    def test_relabeling_refused(self):
        # Eval-time relabeling (e.g. best_effort as latency_critical)
        # would forge QoS evidence: the lowered class is authoritative.
        lowered = lower_compile_workload(_request([_ci()]))
        with pytest.raises(InvalidInput):
            bridge_to_evaluation_messages(
                lowered, requested_traffic_class="latency_critical")

    def test_multi_class_is_typed_unsupported(self):
        lowered = lower_compile_workload(_request([
            _ci(tc="tp_collective"),
            CollectiveIntent(kind=CollectiveKind.ALLGATHER,
                             dimension=CollectiveDimension.DP,
                             payload_bytes=1024,
                             traffic_class="dp_collective")], tp=2, dp=2))
        assert lowered.unified_traffic_class is None
        with pytest.raises(UnsupportedSemantics) as ei:
            bridge_to_evaluation_messages(lowered)
        assert ei.value.code == "UNSUPPORTED_SEMANTICS"
        # ...even when the caller names one member: no cherry-picking.
        with pytest.raises(UnsupportedSemantics):
            bridge_to_evaluation_messages(
                lowered, requested_traffic_class="tp_collective")

    def test_non_lowered_input_refused(self):
        with pytest.raises(InvalidInput):
            bridge_to_evaluation_messages(object())
