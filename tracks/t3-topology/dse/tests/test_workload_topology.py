"""Workload -> canonical explicit topology bridge (synthesis/workload_topology).

The load-bearing properties:

  * the matrix is projected from the canonical logical-message artifact, so
    its total demand is exactly the message bytes;
  * a multi-class lowering uses V3, never a guessed single class;
  * padding grows the matrix with zero-demand nodes and changes identity;
  * a succeeded candidate becomes the SAME explicit topology a hand-authored
    graph uses, and the product compiler is the attachment authority;
  * every refusal is surfaced, never swallowed or repaired by fabricating
    agents/nodes.
"""
from __future__ import annotations

import dataclasses
import json

import pytest

from veritx_dse.core.errors import UnsupportedSemantics
from veritx_dse.synthesis.candidate import TopologyCandidate
from veritx_dse.synthesis.definition import SynthesisDefinition
from veritx_dse.synthesis.traffic import SynthesisTrafficMatrix
from veritx_dse.synthesis.workload_topology import (
    WorkloadTopologyError,
    candidate_to_intent,
    pad_traffic_matrix,
    synthesize_request,
    traffic_matrix_from_request,
)
from veritx_dse.model.topology_intent import ExplicitTopologyIntent
from veritx_dse.workload.intent_lowering import (
    build_multi_class_messages,
    build_single_class_messages,
    lower_compile_workload,
)
from veritx_dse.workload.messages import (
    LogicalMessageArtifactV2,
    LogicalMessageArtifactV3,
)
from veritx_dse.model.compile_model import (
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
)
from test_trace_evaluation import _request as _base_request

#: The 2x2 mesh fixture from test_trace_evaluation: 4 agents, one allreduce,
#: physical clock and noc_controls. It compiles as an explicit custom graph.
RING4 = ((0, 1), (1, 2), (2, 3), (0, 3))

def _request():
    return _base_request()

def _definition(nodes: int) -> SynthesisDefinition:
    common = dict(
        nodes=nodes,
        radix=2,
        max_len=1.0,
        bandwidth_GBs=50.0,
        latency_ns=500.0,
    )
    if nodes == 4:
        return SynthesisDefinition(layout="grid", k=2, **common)
    if nodes == 9:
        return SynthesisDefinition(layout="grid", k=3, **common)
    if nodes == 2:
        return SynthesisDefinition(layout="interposer", rows=1, cols=2,
                                   **common)
    raise AssertionError(f"no test definition for {nodes} nodes")

def _candidate(
        definition: SynthesisDefinition,
        matrix: SynthesisTrafficMatrix,
        links,
        *,
        nodes: int | None = None,
        status: str = "SUCCEEDED",
        solver_status: str = "FEASIBLE",
        producer_id: str = "test/fake",
) -> TopologyCandidate:
    return TopologyCandidate(
        definition_id=definition.definition_id(),
        traffic_id=matrix.traffic_id(),
        links=tuple(links),
        nodes=definition.nodes if nodes is None else nodes,
        algorithm="milp_tmcf",
        solver_status=solver_status,
        objective_value=1.0 if status == "SUCCEEDED" else None,
        objective_name="traffic_weighted_hops",
        status=status,
        producer_id=producer_id,
    )

def _ring4(definition: SynthesisDefinition,
           matrix: SynthesisTrafficMatrix) -> TopologyCandidate:
    return _candidate(definition, matrix, RING4)

def _mesh_links(side: int) -> tuple[tuple[int, int], ...]:
    links: list[tuple[int, int]] = []
    for row in range(side):
        for col in range(side):
            node = row * side + col
            if col + 1 < side:
                links.append((node, node + 1))
            if row + 1 < side:
                links.append((node, node + side))
    return tuple(links)

def _synthesized_ring():
    return synthesize_request(
        _request(), _definition(4), synthesizer=_ring4)

def test_traffic_matrix_matches_logical_message_bytes():
    request = _request()
    matrix = traffic_matrix_from_request(request)

    lowered = lower_compile_workload(request)
    artifact = build_single_class_messages(lowered)
    assert isinstance(artifact, LogicalMessageArtifactV2)
    assert matrix.dimension == 4
    assert matrix.unit == "bytes"
    assert matrix.source_artifact_id == artifact.message_artifact_id()
    assert matrix.total_demand() == sum(
        message.payload_bytes for message in artifact.messages)

def test_traffic_matrix_unit_messages_counts_messages_not_bytes():
    request = _request()
    matrix = traffic_matrix_from_request(request, unit="messages")
    artifact = build_single_class_messages(lower_compile_workload(request))
    assert matrix.unit == "messages"
    assert matrix.total_demand() == len(artifact.messages)

def test_multi_class_lowering_uses_v3_and_never_guesses_a_class():
    base = _request()
    multi = dataclasses.replace(
        base,
        workload=dataclasses.replace(
            base.workload,
            collectives=(
                CollectiveIntent(
                    kind=CollectiveKind.ALLREDUCE,
                    dimension=CollectiveDimension.TP,
                    payload_bytes=8192,
                    traffic_class="tp_a",
                ),
                CollectiveIntent(
                    kind=CollectiveKind.ALLREDUCE,
                    dimension=CollectiveDimension.TP,
                    payload_bytes=8192,
                    traffic_class="tp_b",
                ),
            ),
        ),
    )
    lowered = lower_compile_workload(multi)
    assert len(lowered.classes) == 2
    # A V2 artifact cannot represent the per-operation classes; the bridge
    # must not "pick one" and must not relabel the workload.
    with pytest.raises(UnsupportedSemantics):
        build_single_class_messages(lowered)

    artifact = build_multi_class_messages(lowered)
    assert isinstance(artifact, LogicalMessageArtifactV3)
    matrix = traffic_matrix_from_request(multi)
    assert matrix.dimension == 4
    assert matrix.source_artifact_id == artifact.message_artifact_id()
    assert matrix.total_demand() == sum(
        message.payload_bytes for message in artifact.messages)

def test_padding_extends_with_zero_demand_and_changes_identity():
    matrix = traffic_matrix_from_request(_request())
    padded = pad_traffic_matrix(matrix, 9)

    assert padded.dimension == 9
    assert padded.source_artifact_id == (
        f"{matrix.source_artifact_id}#padded-to-9")
    assert padded.namespace == matrix.namespace
    assert padded.unit == matrix.unit
    assert padded.aggregation == matrix.aggregation
    assert padded.total_demand() == matrix.total_demand()
    assert padded.traffic_id() != matrix.traffic_id()
    for i in range(9):
        for j in range(9):
            expected = matrix.values[i][j] if i < 4 and j < 4 else 0.0
            assert padded.values[i][j] == expected

def test_padding_to_the_same_dimension_still_records_padded_identity():
    matrix = traffic_matrix_from_request(_request())
    padded = pad_traffic_matrix(matrix, matrix.dimension)
    assert padded.dimension == matrix.dimension
    assert padded.values == matrix.values
    assert padded.total_demand() == matrix.total_demand()
    assert padded.source_artifact_id == (
        f"{matrix.source_artifact_id}#padded-to-{matrix.dimension}")
    assert padded.traffic_id() != matrix.traffic_id()

def test_padding_refuses_a_shrink():
    matrix = traffic_matrix_from_request(_request())
    with pytest.raises(WorkloadTopologyError, match="never shrinks"):
        pad_traffic_matrix(matrix, 3)
    with pytest.raises(WorkloadTopologyError, match=">= 2"):
        pad_traffic_matrix(matrix, 1)

def test_candidate_to_intent_is_ordinary_explicit_topology():
    request = _request()
    matrix = traffic_matrix_from_request(request)
    definition = _definition(4)
    candidate = _candidate(definition, matrix, RING4)

    intent = candidate_to_intent(candidate, definition)
    assert isinstance(intent, ExplicitTopologyIntent)
    assert intent.graph.kind == "custom"
    assert intent.graph.nodes == 4
    assert intent.graph.name == "synthesized_milp_tmcf_4"
    assert intent.graph.links == [list(edge) for edge in RING4]
    assert intent.graph.link_attrs == {
        "bandwidth_GBs": 50.0, "latency_ns": 500.0}
    assert intent.graph.routing == "min"

def test_synthesize_request_compiles_a_ring_candidate():
    base = _request()
    before = base.to_dict()
    seen: dict[str, object] = {}

    def fake(definition, matrix):
        seen["definition"] = definition
        seen["matrix"] = matrix
        return _ring4(definition, matrix)

    result = synthesize_request(base, _definition(4), synthesizer=fake)

    assert seen["definition"] == _definition(4)
    assert isinstance(seen["matrix"], SynthesisTrafficMatrix)
    assert seen["matrix"].dimension == 4
    assert result.compilation.status == "COMPILED"
    assert result.candidate.status == "SUCCEEDED"
    assert result.topology.graph.nodes == 4
    assert len(result.topology.graph.links) == 4
    assert result.request.topology == result.topology
    assert result.request.design_hash() != base.design_hash()
    assert base.to_dict() == before

def test_synthesize_refuses_definition_smaller_than_traffic():
    called = False

    def fake(definition, matrix):
        nonlocal called
        called = True
        raise AssertionError("synthesis must not run on an undersized graph")

    with pytest.raises(WorkloadTopologyError, match="smaller graph"):
        synthesize_request(_request(), _definition(2), synthesizer=fake)
    assert not called

@pytest.mark.parametrize("status,solver_status", [
    ("FAILED", "UNKNOWN"),
    ("INFEASIBLE", "INFEASIBLE"),
])
def test_synthesize_refuses_a_candidate_without_a_graph(status, solver_status):
    definition = _definition(4)

    def fake(defn, matrix):
        return _candidate(
            defn, matrix, (), status=status, solver_status=solver_status,
            producer_id="test/failing-producer")

    with pytest.raises(WorkloadTopologyError) as info:
        synthesize_request(_request(), definition, synthesizer=fake)
    message = str(info.value)
    assert status in message
    assert "test/failing-producer" in message

def test_disconnected_candidate_compile_refusal_is_surfaced():
    definition = _definition(4)

    def fake(defn, matrix):
        return _candidate(defn, matrix, ((0, 1), (2, 3)))

    with pytest.raises(WorkloadTopologyError) as info:
        synthesize_request(_request(), definition, synthesizer=fake)
    message = str(info.value)
    assert "compiler refused" in message
    assert "UNSUPPORTED" in message
    assert "disconnected" in message

def test_synthesize_refuses_mismatched_candidate_nodes():
    definition = _definition(4)

    def fake(defn, matrix):
        return _candidate(defn, matrix, ((0, 1), (1, 2)), nodes=3)

    with pytest.raises(WorkloadTopologyError, match="candidate nodes 3"):
        synthesize_request(_request(), definition, synthesizer=fake)

def test_to_dict_is_json_native_and_deterministic():
    result = _synthesized_ring()
    first = result.to_dict()
    second = result.to_dict()

    assert first == second
    json.dumps(first)
    assert first["design_hash"] == result.request.design_hash()
    assert first["topology"] == {
        "kind": "custom",
        "nodes": 4,
        "links": [list(edge) for edge in RING4],
    }
    assert first["candidate"] == {
        "algorithm": "milp_tmcf",
        "status": "SUCCEEDED",
        "producer": "test/fake",
    }
    assert first["matrix"] == {
        "traffic_id": result.matrix.traffic_id(),
        "dimension": 4,
        "total_demand": result.matrix.total_demand(),
    }
    assert first["compilation"] == {"status": "COMPILED"}

def test_nine_node_padding_seats_four_agents_on_a_connected_graph():
    """Padding adds zero-demand nodes; the compiler seats the 4 agents.

    This request attaches to a 9-node explicit graph (verified in this
    repo), so the successful branch is asserted. If the compiler ever
    refuses the attachment, ``synthesize_request`` raises with that refusal
    instead of inventing agents — which is what the refusal tests cover.
    """
    base = _request()
    definition = _definition(9)
    original = traffic_matrix_from_request(base)

    def fake(defn, matrix):
        assert matrix.dimension == 9
        return _candidate(defn, matrix, _mesh_links(3))

    result = synthesize_request(base, definition, synthesizer=fake)

    assert result.matrix.dimension == 9
    assert result.matrix.total_demand() == original.total_demand()
    assert result.request.total_nodes == 4
    assert result.topology.graph.nodes == 9
    assert len(result.topology.graph.links) == 12
    assert result.compilation.status == "COMPILED"
