"""Wave B3.4b tests — RouterBehaviorArtifact: router behavior authority.

Seam-level: build real VCAssignmentArtifact parents, derive the canonical
v1 behavior, pin every default, and verify that behavior mutations change
identity while GUIDED arbitration aliases do not.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from veritx_dse.model.router_behavior import (
    AllocatorPolicy, BufferOrganization, FlowControlProtocol,
    InputVCPacketPolicy, RouterBehaviorArtifact, RouterBehaviorError,
    VCAllocationScope, VCReusePolicy, canonical_allocator,
    derive_router_behavior,
)
from veritx_dse.model.vc_assignment import VCAssignmentArtifact


def _vc(vc_count=1, resolved_route_hash="r" * 64, transitions=None,
        routing_classes=None):
    if transitions is None:
        transitions = tuple((i, i) for i in range(vc_count))
    if routing_classes is None:
        routing_classes = tuple(
            (i, "ANYNET_MIN_HOPS") for i in range(vc_count))
    return VCAssignmentArtifact(
        resolved_route_hash=resolved_route_hash,
        vc_count=vc_count,
        vc_ids=tuple(range(vc_count)),
        traffic_class_to_vcs=(("A", (0,)),),
        vc_to_routing_class=routing_classes,
        allowed_transitions=transitions,
        escape_vcs=(),
        derivation="router_behavior_test",
    )


def _derive(**kw):
    vc = kw.pop("vc_assignment", None)
    vc_count = kw.pop("vc_count", 1)
    if vc is None:
        vc = _vc(vc_count)
    return vc, derive_router_behavior(vc_assignment=vc, **kw)


# ── golden baseline (§73) ─────────────────────────────────────────────────

class TestGoldenDefault:
    def test_canonical_v1_defaults(self):
        _vc_art, art = _derive(vc_count=1)
        assert art.buffer_organization is \
            BufferOrganization.PER_INPUT_PORT_PER_VC
        assert art.input_buffer_depth_flits_per_vc == 8
        assert art.output_stage_depth_flits_per_vc == 1

        assert art.flow_control is FlowControlProtocol.CREDIT
        assert art.credit_return_latency_cycles == 1
        assert art.vc_reuse_policy is VCReusePolicy.WAIT_FOR_TAIL_CREDIT

        assert art.vc_allocator is AllocatorPolicy.ISLIP
        assert art.switch_allocator is AllocatorPolicy.ISLIP
        assert art.allocator_iterations == 1

        assert art.hold_switch_for_packet is False
        assert art.input_vc_packet_policy is \
            InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
        assert art.vc_allocation_scope is VCAllocationScope.PACKET

        assert (art.input_speedup, art.output_speedup,
                art.internal_speedup) == (1, 1, 1)

        assert art.route_compute_cycles == 0
        assert art.vc_alloc_cycles == 1
        assert art.switch_alloc_cycles == 1
        assert art.switch_traversal_cycles == 1
        assert art.output_delay_cycles == 0

    def test_roundtrip_preserves_hash(self):
        _vc_art, art = _derive()
        loaded = RouterBehaviorArtifact.from_dict(art.to_dict())
        assert loaded.router_behavior_hash() == art.router_behavior_hash()

    def test_no_route_or_packet_authority_fields(self):
        _vc_art, art = _derive()
        blob = repr(art.identity_dict()).lower()
        assert "routing_class" not in blob
        assert "route_table" not in blob
        assert "flit_width" not in blob
        assert "topology" not in blob


# ── identity mutations (§74) ──────────────────────────────────────────────

class TestIdentityMutations:
    @pytest.mark.parametrize("mutation", [
        {"input_buffer_depth_flits_per_vc": 16},
        {"output_stage_depth_flits_per_vc": 2},
        {"credit_return_latency_cycles": 2},
        {"vc_allocator": AllocatorPolicy.ROUND_ROBIN},
        {"switch_allocator": AllocatorPolicy.ROUND_ROBIN},
        {"allocator_iterations": 2},
        {"hold_switch_for_packet": True},
        {"route_compute_cycles": 1},
        {"vc_alloc_cycles": 2},
        {"switch_alloc_cycles": 2},
        {"switch_traversal_cycles": 2},
        {"output_delay_cycles": 1},
        {"input_speedup": 2},
        {"output_speedup": 2},
        {"internal_speedup": 2},
    ])
    def test_behavior_change_changes_hash(self, mutation):
        _vc_art, art = _derive()
        twin = replace(art, artifact_hash="", **mutation)
        assert twin.router_behavior_hash() != art.router_behavior_hash()

    def test_vc_parent_change_changes_hash(self):
        _vc_art, art = _derive()
        other_vc = _vc(1, "s" * 64)
        other = derive_router_behavior(vc_assignment=other_vc)
        assert other.vc_assignment_hash != art.vc_assignment_hash
        assert other.router_behavior_hash() != art.router_behavior_hash()

    def test_vc_transition_semantics_change_hash_through_parent(self):
        vc_a = _vc(2, transitions=((0, 0), (1, 1)))
        vc_b = _vc(2, transitions=((0, 0), (0, 1), (1, 1)))
        a = derive_router_behavior(vc_assignment=vc_a)
        b = derive_router_behavior(vc_assignment=vc_b)
        a.validate_against(vc_a)
        b.validate_against(vc_b)
        assert a.vc_assignment_hash != b.vc_assignment_hash
        assert a.router_behavior_hash() != b.router_behavior_hash()

    def test_wrong_vc_parent_refused(self):
        _vc_art, art = _derive()
        with pytest.raises(RouterBehaviorError, match="vc_assignment_hash"):
            art.validate_against(_vc(1, "s" * 64))


# ── arbitration aliases (§76) ─────────────────────────────────────────────

class TestArbitrationAliases:
    def test_none_and_islip_are_the_same_semantics(self):
        assert canonical_allocator(None) is AllocatorPolicy.ISLIP
        assert canonical_allocator("islip") is AllocatorPolicy.ISLIP
        assert canonical_allocator(" iSLIP ") is AllocatorPolicy.ISLIP
        _vc_a, a = _derive()
        _vc_b, b = _derive(arbitration="islip")
        assert a.router_behavior_hash() == b.router_behavior_hash()

    @pytest.mark.parametrize("alias", ["round_robin", "round-robin", "rr",
                                       "RR"])
    def test_round_robin_aliases_canonicalize(self, alias):
        assert canonical_allocator(alias) is AllocatorPolicy.ROUND_ROBIN

    def test_round_robin_aliases_share_one_semantic_hash(self):
        hashes = set()
        for alias in ("round_robin", "round-robin", "rr"):
            _vc_art, art = _derive(arbitration=alias)
            assert art.vc_allocator is AllocatorPolicy.ROUND_ROBIN
            hashes.add(art.router_behavior_hash())
        assert len(hashes) == 1

    @pytest.mark.parametrize("bad", ["priority", "escape_first", "random",
                                     "free_form_thing"])
    def test_unknown_arbitration_refused(self, bad):
        with pytest.raises(RouterBehaviorError, match="arbitration"):
            canonical_allocator(bad)

    def test_unknown_arbitration_in_builder_refused(self):
        with pytest.raises(RouterBehaviorError, match="arbitration"):
            _derive(arbitration="priority")


# ── strictness (§75) ──────────────────────────────────────────────────────

class TestStrictness:
    @pytest.mark.parametrize("mutation,match", [
        ({"input_buffer_depth_flits_per_vc": 0}, "input_buffer_depth"),        ({"input_buffer_depth_flits_per_vc": True}, "input_buffer_depth"),
        ({"input_buffer_depth_flits_per_vc": 8.0}, "input_buffer_depth"),
        ({"input_buffer_depth_flits_per_vc": "8"}, "input_buffer_depth"),
        ({"credit_return_latency_cycles": -1}, "credit_return"),
        ({"input_speedup": 0}, "input_speedup"),
        ({"internal_speedup": 0}, "internal_speedup"),
        ({"allocator_iterations": 0}, "allocator_iterations"),
        ({"hold_switch_for_packet": 1}, "hold_switch_for_packet"),
        ({"route_compute_cycles": -1}, "route_compute_cycles"),
        ({"output_delay_cycles": -1}, "output_delay_cycles"),
    ])
    def test_constructor_rejects_bad_values(self, mutation, match):
        _vc_art, art = _derive()
        with pytest.raises(RouterBehaviorError, match=match):
            replace(art, artifact_hash="", **mutation)

    def test_builder_rejects_zero_depth(self):
        with pytest.raises(RouterBehaviorError, match="buffer_depth"):
            _derive(buffer_depth_flits=0)

    @pytest.mark.parametrize("mutate,match", [
        (lambda d: d.update(extra=1), "unknown fields"),
        (lambda d: d.update(schema_version=3), "schema_version"),
        (lambda d: d.update(vc_allocator="priority"), "unknown VC allocator"),
        (lambda d: d.update(switch_allocator="magic"),
         "unknown switch allocator"),
        (lambda d: d.update(flow_control="credit_based"),
         "unknown flow control"),
        (lambda d: d.update(buffer_organization="shared"),
         "unknown buffer organization"),
        (lambda d: d.update(vc_reuse_policy="immediate"),
         "unknown VC reuse policy"),
        (lambda d: d.update(input_buffer_depth_flits_per_vc=True),
         "input_buffer_depth"),
        (lambda d: d.update(input_buffer_depth_flits_per_vc=8.0),
         "input_buffer_depth"),
        (lambda d: d.update(input_buffer_depth_flits_per_vc="8"),
         "input_buffer_depth"),
        (lambda d: d.update(hold_switch_for_packet=1),
         "hold_switch_for_packet"),
        (lambda d: d.update(input_vc_packet_policy="interleaved"),
         "unknown input VC packet policy"),
        (lambda d: d.update(vc_allocation_scope="flit"),
         "unknown VC allocation scope"),
        (lambda d: d.update(artifact_hash="0" * 64), "artifact_hash"),
    ])
    def test_persisted_mutations_refused(self, mutate, match):
        _vc_art, art = _derive()
        d = art.to_dict()
        mutate(d)
        with pytest.raises(RouterBehaviorError, match=match):
            RouterBehaviorArtifact.from_dict(d)

    def test_missing_artifact_hash_refused(self):
        _vc_art, art = _derive()
        d = art.to_dict()
        del d["artifact_hash"]
        with pytest.raises(RouterBehaviorError, match="artifact_hash"):
            RouterBehaviorArtifact.from_dict(d)

    def test_unknown_field_in_future_schema_refused(self):
        _vc_art, art = _derive()
        d = art.to_dict()
        d["future_field"] = 3
        with pytest.raises(RouterBehaviorError, match="unknown fields"):
            RouterBehaviorArtifact.from_dict(d)


# ── B3.4c packet-context / VC-scope seal ──────────────────────────────────

class TestPacketContextSemantics:
    def test_one_packet_context_per_input_vc(self):
        _vc_art, art = _derive()
        assert art.input_vc_packet_policy is \
            InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
        assert art.vc_allocation_scope is VCAllocationScope.PACKET
        # ...and this is independent of switch arbitration granularity
        assert art.hold_switch_for_packet is False

    def test_switch_hold_does_not_change_vc_scope(self):
        _vc_art, art = _derive()
        held = replace(art, artifact_hash="", hold_switch_for_packet=True)
        assert held.vc_allocation_scope is VCAllocationScope.PACKET
        assert held.input_vc_packet_policy is \
            InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
        assert held.router_behavior_hash() != art.router_behavior_hash()

    def test_schema_v1_is_refused_with_explicit_message(self):
        _vc_art, art = _derive()
        d = art.to_dict()
        d["schema_version"] = 1
        with pytest.raises(RouterBehaviorError,
                           match="schema v1|silent migration"):
            RouterBehaviorArtifact.from_dict(d)

    def test_v1_packet_hold_policy_field_is_not_accepted(self):
        _vc_art, art = _derive()
        d = art.to_dict()
        d.pop("input_vc_packet_policy")
        d["packet_hold_policy"] = "flit_interleaved"
        with pytest.raises(RouterBehaviorError, match="unknown fields"):
            RouterBehaviorArtifact.from_dict(d)
