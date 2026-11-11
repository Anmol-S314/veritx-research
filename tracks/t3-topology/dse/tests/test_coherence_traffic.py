"""Synthetic coherency traffic: shape, determinism, and refusals.

These tests pin the generator's own contract.  The protocol seam it feeds is
already covered by ``test_workload_coherence`` (request -> lowering) and
``test_workload_traffic`` (fanout); this file checks that the synthetic front
end produces the same shapes and never widens that seam.
"""
from __future__ import annotations

import dataclasses

import pytest

from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CoherenceIntent,
    CoherencePattern,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    DependencyGraph,
    ModelFamily,
    QoSClass,
    RequirementV3,
    WorkloadV3,
    derive_v3_traffic_classes,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.compute_intent import ComputeIntent
from veritx_dse.model.multi_plane_vc import COHERENCE_CLASS, is_coherence_class
from veritx_dse.model.noc_controls import NocControls
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.workload.coherence_traffic import (
    CoherenceTrafficError,
    CoherenceTrafficSpec,
    apply_coherence_traffic,
    generate_coherence_intents,
)
from veritx_dse.workload.intent_lowering import (
    build_multi_class_messages,
    lower_compile_workload,
)

READ = CoherencePattern.READ_SHARED.value
WRITE = CoherencePattern.WRITE_INVALIDATE.value


def _spec(**overrides) -> CoherenceTrafficSpec:
    """A valid spec; overrides replace individual fields.

    Declaring ``sharing_degree`` without explicitly declaring ``sharers``
    switches to the derived-sharer path.
    """
    base = dict(
        world_size=4,
        homes=(0,),
        patterns=(READ,),
        sharers=(1, 2),
        lines=2,
        line_bytes=64,
        intents_per_pattern=1,
        max_intents=64,
        seed=7,
    )
    if "sharing_degree" in overrides and "sharers" not in overrides:
        base.pop("sharers")
    base.update(overrides)
    return CoherenceTrafficSpec(**base)


def _base_request(*, tp: int = 4, collectives=(), coherence=(), agents=(),
                  requirements=()) -> CompileRequestV4:
    return CompileRequestV4(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            model_name="coherence-traffic-probe",
            tp=tp, ep=1, pp=1, dp=1,
            collectives=tuple(collectives),
            coherence=tuple(coherence)),
        requirements=tuple(requirements),
        agents=tuple(agents),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        noc_controls=NocControls(),
        compute=ComputeIntent(stages=()))


def _tp_collective() -> CollectiveIntent:
    return CollectiveIntent(
        kind=CollectiveKind.ALLREDUCE,
        dimension=CollectiveDimension.TP,
        payload_bytes=64,
        traffic_class="tp_collective")


def test_read_shared_generation_is_exact_and_home_disjoint():
    spec = _spec(world_size=4, homes=(0, 1), patterns=(READ,),
                 sharers=(2, 3), intents_per_pattern=2, max_intents=8)
    intents = generate_coherence_intents(spec)

    assert len(intents) == 2 * 1 * 2
    assert [(i.home_rank, i.pattern.value) for i in intents] == [
        (0, READ), (0, READ), (1, READ), (1, READ)]
    for intent in intents:
        assert intent.pattern is CoherencePattern.READ_SHARED
        assert intent.writer_rank is None
        assert intent.sharers == (2, 3)
        assert intent.home_rank not in intent.sharers
        assert intent.lines == 2
        assert intent.line_bytes == 64
        assert intent.traffic_class == "coherence"


def test_write_invalidate_generation_pins_the_declared_writer():
    spec = _spec(homes=(0,), patterns=(WRITE,), sharers=(1, 2),
                 writer=1, intents_per_pattern=3, max_intents=3)
    intents = generate_coherence_intents(spec)

    assert len(intents) == 3
    for intent in intents:
        assert intent.pattern is CoherencePattern.WRITE_INVALIDATE
        assert intent.writer_rank == 1
        assert intent.writer_rank in intent.sharers
        assert intent.sharers == (1, 2)


def test_mixed_patterns_emit_one_intent_per_home_pattern_repetition():
    spec = _spec(world_size=4, homes=(0, 1), patterns=(READ, WRITE),
                 sharers=(2, 3), writer=2, intents_per_pattern=2,
                 max_intents=8)
    intents = generate_coherence_intents(spec)

    assert len(intents) == 2 * 2 * 2
    assert [(i.home_rank, i.pattern.value, i.writer_rank)
            for i in intents] == [
        (0, READ, None), (0, READ, None),
        (0, WRITE, 2), (0, WRITE, 2),
        (1, READ, None), (1, READ, None),
        (1, WRITE, 2), (1, WRITE, 2),
    ]


def test_sharing_degree_derivation_is_deterministic_and_wraps():
    read = CoherenceTrafficSpec(
        world_size=8, homes=(7,), patterns=(READ,), sharing_degree=3,
        lines=1, line_bytes=64, intents_per_pattern=1, max_intents=4)
    assert read.resolved_sharers(7) == (0, 1, 2)
    assert generate_coherence_intents(read) == generate_coherence_intents(read)

    wrapped = dataclasses.replace(read, homes=(3,))
    assert wrapped.resolved_sharers(3) == (4, 5, 6)

    write = CoherenceTrafficSpec(
        world_size=8, homes=(3,), patterns=(WRITE,), sharing_degree=3,
        writer=0, lines=1, line_bytes=64, intents_per_pattern=1,
        max_intents=4)
    # Writer is added first, then the wrapping fill, then sorted.
    assert write.resolved_sharers(3) == (0, 4, 5)
    assert 3 not in write.resolved_sharers(3)
    assert write.resolved_sharers(3)[0] == 0


def test_seed_is_validated_but_reserved_and_does_not_change_intents():
    spec = _spec(world_size=8, homes=(1,), patterns=(READ,),
                 sharing_degree=2, seed=0)
    same_shape = dataclasses.replace(spec, seed=999)
    assert generate_coherence_intents(spec) \
        == generate_coherence_intents(same_shape)


def test_apply_preserves_the_request_and_changes_only_coherence_identity():
    base = _base_request(
        collectives=(_tp_collective(),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=1000.0),))
    spec = _spec(world_size=4, homes=(0, 1), patterns=(READ,),
                 sharers=(2, 3), intents_per_pattern=1, max_intents=2)
    before_hash = base.design_hash()

    updated = apply_coherence_traffic(base, spec)

    assert updated is not base
    assert updated.workload is not base.workload
    assert updated.workload.coherence == generate_coherence_intents(spec)
    assert updated.workload.collectives == base.workload.collectives
    assert updated.requirements == base.requirements
    assert updated.agents == base.agents
    assert updated.topology == base.topology
    assert updated.dependencies == base.dependencies
    assert updated.noc_controls == base.noc_controls
    assert updated.compute == base.compute
    assert updated.address_map == base.address_map
    assert updated.physical == base.physical
    assert updated.design_hash() != before_hash
    assert base.workload.coherence == ()


def test_apply_replaces_existing_coherence_intents():
    old = CoherenceIntent(
        pattern=CoherencePattern.READ_SHARED, home_rank=0, writer_rank=None,
        sharers=(1,), line_bytes=64, lines=1, traffic_class="coherence")
    base = _base_request(coherence=(old,))
    spec = _spec(world_size=4, homes=(0,), patterns=(READ,),
                 sharers=(1, 2), intents_per_pattern=1, max_intents=1)

    updated = apply_coherence_traffic(base, spec)

    assert updated.workload.coherence == generate_coherence_intents(spec)
    assert old not in updated.workload.coherence
    assert base.workload.coherence == (old,)


def test_lowering_emits_kind_coherence_and_names_the_class_sidecar():
    base = _base_request()
    spec = _spec(world_size=4, homes=(0, 1), patterns=(READ, WRITE),
                 sharers=(2, 3), writer=2, intents_per_pattern=1,
                 max_intents=4)

    lowered = lower_compile_workload(apply_coherence_traffic(base, spec))
    ops = lowered.graph.of_kind("COHERENCE")

    assert len(ops) == 4
    assert [op.operation_id for op in ops] == [
        "h000_read_shared", "h001_write_invalidate",
        "h002_read_shared", "h003_write_invalidate"]
    sidecar = dict(lowered.traffic_class_by_operation)
    assert set(sidecar) == {op.operation_id for op in ops}
    assert set(sidecar.values()) == {"coherence"}
    assert lowered.classes == ("coherence",)


def test_message_fanout_is_two_messages_per_line_per_sharer():
    base = _base_request(collectives=(_tp_collective(),))
    spec = _spec(world_size=4, homes=(0,), patterns=(READ, WRITE),
                 sharers=(1, 2), writer=1, lines=3, line_bytes=64,
                 intents_per_pattern=1, max_intents=2)

    lowered = lower_compile_workload(apply_coherence_traffic(base, spec))
    messages = build_multi_class_messages(lowered)

    read = messages.messages_for_operation("h000_read_shared")
    write = messages.messages_for_operation("h001_write_invalidate")
    assert len(read) == 2 * 3 * 2
    assert len(write) == 2 * 3 * 2
    assert {m.payload_bytes for m in read + write} == {64}
    assert {m.traffic_class for m in read + write} == {"coherence"}
    # The existing lowering places every coherence message at step 0.
    assert {m.step for m in read + write} == {0}


def test_coherence_class_joins_the_registry_without_a_third_class():
    base = _base_request(collectives=(_tp_collective(),))
    spec = _spec(world_size=4, homes=(0,), patterns=(READ,),
                 sharers=(1, 2))
    updated = apply_coherence_traffic(base, spec)

    classes = derive_v3_traffic_classes(updated)
    assert classes == ("coherence", "tp_collective")
    assert COHERENCE_CLASS in classes
    assert is_coherence_class(COHERENCE_CLASS)
    assert is_coherence_class("coherence:msi")
    assert not is_coherence_class("tp_collective")

    lowered = lower_compile_workload(updated)
    assert lowered.classes == ("coherence", "tp_collective")
    assert len(lowered.graph.of_kind("COHERENCE")) == 1


def test_caller_declared_coherence_namespace_is_preserved():
    spec = _spec(world_size=4, homes=(0,), patterns=(READ,),
                 sharers=(1, 2), traffic_class="coherence:msi")
    intents = generate_coherence_intents(spec)
    assert {i.traffic_class for i in intents} == {"coherence:msi"}
    assert is_coherence_class(intents[0].traffic_class)


def test_generation_refuses_more_than_max_intents():
    spec = _spec(world_size=4, homes=(0, 1), patterns=(READ, WRITE),
                 sharers=(2, 3), writer=2, intents_per_pattern=2,
                 max_intents=7)
    with pytest.raises(CoherenceTrafficError, match="max_intents"):
        generate_coherence_intents(spec)


@pytest.mark.parametrize("overrides, match", [
    ({"homes": ()}, "homes must not be empty"),
    ({"homes": (0, 0)}, "duplicates"),
    ({"homes": (4,)}, "outside"),
    ({"homes": (0, 1), "sharers": (1, 2)}, "must not appear among"),
    ({"sharers": (0, 1)}, "must not appear among"),
    ({"sharers": (1, 4)}, "outside"),
    ({"sharers": (1, 1)}, "duplicates"),
    ({"patterns": ()}, "patterns must not be empty"),
    ({"patterns": ("MESI_EXCLUSIVE",)}, "outside"),
    ({"patterns": (WRITE,), "writer": None}, "WRITE_INVALIDATE requires"),
    ({"patterns": (WRITE,), "sharers": (1, 2), "writer": 3},
     "is not among the declared sharers"),
    ({"patterns": (WRITE,), "sharers": (1, 2), "writer": 4}, "outside"),
    ({"patterns": (WRITE,), "writer": 0}, "must not be one of the homes"),
    ({"writer": 1}, "READ_SHARED must not declare"),
    ({"sharers": (1, 2), "sharing_degree": 2}, "exactly one"),
    ({"sharers": None, "sharing_degree": None}, "exactly one"),
    ({"sharing_degree": 4}, "sharing_degree"),
    ({"sharing_degree": 0}, "sharing_degree must be >= 1"),
    ({"lines": 0}, "lines must be >= 1"),
    ({"line_bytes": 0}, "line_bytes must be >= 1"),
    ({"world_size": 1}, "world_size must be >= 2"),
    ({"intents_per_pattern": 0}, "intents_per_pattern must be >= 1"),
    ({"seed": -1}, "seed must be >= 0"),
    ({"max_intents": 0}, "max_intents must be >= 1"),
    ({"traffic_class": ""}, "traffic_class must be a non-empty"),
    ({"traffic_class": "   "}, "traffic_class must be a non-empty"),
])
def test_spec_refusals(overrides, match):
    with pytest.raises(CoherenceTrafficError, match=match):
        _spec(**overrides)


def test_generate_refuses_a_non_spec():
    with pytest.raises(CoherenceTrafficError, match="CoherenceTrafficSpec"):
        generate_coherence_intents(object())


def test_apply_refuses_a_non_v4_request():
    with pytest.raises(CoherenceTrafficError, match="CompileRequestV4"):
        apply_coherence_traffic(object(), _spec())


def test_apply_refuses_a_spec_wider_than_the_request_world():
    base = _base_request(tp=2)
    spec = _spec(world_size=4, homes=(0,), sharers=(1, 2))
    with pytest.raises(CoherenceTrafficError, match="world_size"):
        apply_coherence_traffic(base, spec)
