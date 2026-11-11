"""Placement contract (P1.10): fixed placement, allowed movement, locality."""
from __future__ import annotations

import time

import pytest

from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.mapping import MappingArtifact, RankPlacement, derive_mapping
from veritx_dse.model.placement import AgentInstance, build_inventory
from veritx_dse.model.placement_contract import (
    PLACEMENT_CONTRACT_SCHEMA_VERSION,
    Affinity,
    AllowedMovement,
    AntiAffinity,
    CoLocate,
    FixedPlacement,
    LocalityDomain,
    MovementPolicy,
    PlacementContract,
    PlacementContractError,
    Prefer,
    Reason,
    ReasonCode,
    SeatCoordinate,
    Spread,
    Verdict,
    check_placement_contract,
)


def _cr(tp=2, pp=1, ep=1, dp=1, agents=None):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=pp,
                          ep=ep, dp=dp),
        requirements=[],
        agents=agents or [Agent(kind=AgentKind.COMPUTE_TILE,
                                count=tp * pp * ep * dp)],
        dependencies=[],
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _inventory(**kw):
    return build_inventory(_cr(**kw))


def _derived(**kw):
    return derive_mapping(_cr(**kw))


def _seat(g, i):
    return SeatCoordinate(group_index=g, instance_index=i)


def _mapping(pairs):
    return MappingArtifact(placements=tuple(
        RankPlacement(rank=r, agent=AgentInstance(g, i, AgentKind.COMPUTE_TILE))
        for r, g, i in pairs))


def _codes(verdict):
    return set(verdict.reason_codes)


def test_valid_pin_passes():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok
    assert verdict.reasons == ()
    assert verdict.ranks_mapped == 4
    assert verdict.world_size == 4
    assert bool(verdict) is True


def test_duplicate_seat_pin_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(placements=(
        FixedPlacement(rank=0, seat=_seat(0, 1)),
        FixedPlacement(rank=1, seat=_seat(0, 1)),
    ))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.DUPLICATE_SEAT_PIN in _codes(verdict)
    pin_reason = next(r for r in verdict.reasons
                      if r.code is ReasonCode.DUPLICATE_SEAT_PIN)
    assert "(0,1)" in pin_reason.witnesses
    assert "0" in pin_reason.witnesses and "1" in pin_reason.witnesses


def test_pin_mismatch_reports_witness():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.PIN_MISMATCH in _codes(verdict)
    mismatch = next(r for r in verdict.reasons
                    if r.code is ReasonCode.PIN_MISMATCH)
    assert mismatch.witnesses[:3] == ("0", "(0,1)", "(0,0)")


def test_pin_rank_beyond_world_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=9, seat=_seat(0, 0)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.UNKNOWN_RANK in _codes(verdict)


def test_pin_seat_not_compute_refuses():
    inventory = _inventory(
        tp=4,
        agents=[Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
                Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    mapping = _derived(
        tp=4,
        agents=[Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
                Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.PIN_SEAT_NOT_COMPUTE in _codes(verdict)


def test_pin_unknown_seat_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(7, 7)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.UNKNOWN_SEAT in _codes(verdict)


def test_spread_over_too_few_seats_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a", seats=(_seat(0, 0),)),
                 LocalityDomain(name="island_b", seats=(_seat(0, 1),))),
        anti_affinities=(AntiAffinity(ranks=(0, 1, 2)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.SPREAD_TOO_FEW_SEATS in _codes(verdict)
    spread = next(r for r in verdict.reasons
                  if r.code is ReasonCode.SPREAD_TOO_FEW_SEATS)
    assert spread.witnesses == ("2", "3")


def test_spread_with_enough_domains_passes():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 2))),
                 LocalityDomain(name="island_b",
                                seats=(_seat(0, 1), _seat(0, 3)))),
        anti_affinities=(AntiAffinity(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok


def test_affinity_mandated_domain_capacity_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a", seats=(_seat(0, 0),)),),
        co_locates=(CoLocate(ranks=(0, 1), domain="island_a"),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.AFFINITY_CAPACITY_BLOCKED in _codes(verdict)
    blocked = next(r for r in verdict.reasons
                   if r.code is ReasonCode.AFFINITY_CAPACITY_BLOCKED)
    assert blocked.witnesses == ("island_a", "1", "2")
    assert "island_a" in blocked.detail


def test_affinity_unmandated_capacity_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a", seats=(_seat(0, 0),)),
                 LocalityDomain(name="island_b", seats=(_seat(0, 1),))),
        co_locates=(CoLocate(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.AFFINITY_CAPACITY_BLOCKED in _codes(verdict)
    blocked = next(r for r in verdict.reasons
                   if r.code is ReasonCode.AFFINITY_CAPACITY_BLOCKED)
    assert blocked.witnesses == ("island_a", "1", "2")


def test_affinity_mandated_domain_success():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 1),
                                       _seat(0, 2), _seat(0, 3))),),
        co_locates=(CoLocate(ranks=(0, 1), domain="island_a"),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok


def test_affinity_unmandated_success():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 1))),
                 LocalityDomain(name="island_b",
                                seats=(_seat(0, 2), _seat(0, 3)))),
        co_locates=(CoLocate(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok


def test_affinity_failure_spans_domains():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 2))),
                 LocalityDomain(name="island_b",
                                seats=(_seat(0, 1), _seat(0, 3)))),
        co_locates=(CoLocate(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.AFFINITY_DOMAIN_CONFLICT in _codes(verdict)
    conflict = next(r for r in verdict.reasons
                    if r.code is ReasonCode.AFFINITY_DOMAIN_CONFLICT)
    assert set(conflict.witnesses) == {"island_a", "island_b"}


def test_affinity_failure_mandated_domain_mismatch():
    inventory = _inventory(tp=4)
    mapping = _mapping([(0, 0, 0), (1, 0, 3), (2, 0, 1), (3, 0, 2)])
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 1))),
                 LocalityDomain(name="island_b",
                                seats=(_seat(0, 2), _seat(0, 3)))),
        co_locates=(CoLocate(ranks=(0, 1), domain="island_a"),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.AFFINITY_DOMAIN_CONFLICT in _codes(verdict)
    conflict = next(r for r in verdict.reasons
                    if r.code is ReasonCode.AFFINITY_DOMAIN_CONFLICT)
    assert conflict.witnesses[:2] == ("1", "(0,3)")
    assert "island_a" in conflict.witnesses


def test_anti_affinity_conflict():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 1))),
                 LocalityDomain(name="island_b",
                                seats=(_seat(0, 2), _seat(0, 3)))),
        anti_affinities=(AntiAffinity(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.ANTI_AFFINITY_CONFLICT in _codes(verdict)
    conflict = next(r for r in verdict.reasons
                    if r.code is ReasonCode.ANTI_AFFINITY_CONFLICT)
    assert conflict.witnesses == ("0", "1", "island_a")


def test_anti_affinity_success_distinct_domains():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 2))),
                 LocalityDomain(name="island_b",
                                seats=(_seat(0, 1), _seat(0, 3)))),
        anti_affinities=(AntiAffinity(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok


def test_prefer_records_but_never_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(prefers=(
        Prefer(rank=0, seat=_seat(0, 1)),
        Prefer(rank=1, domain="undeclared-island"),
        Prefer(rank=2, seat=_seat(0, 2)),
    ))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok
    assert verdict.reasons == ()
    by_rank = {report.rank: report for report in verdict.preferences}
    assert by_rank[0].satisfied is False
    assert by_rank[1].satisfied is False
    assert "not declared" in by_rank[1].detail
    assert by_rank[2].satisfied is True
    assert all("prefer" not in r.code.value.lower()
               for r in verdict.reasons)


def test_mapping_agent_not_in_inventory_witness():
    inventory = _inventory(tp=4)
    mapping = _mapping([(0, 0, 0), (1, 0, 1), (2, 0, 2), (3, 0, 9)])
    contract = PlacementContract()
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.MAPPING_AGENT_NOT_IN_INVENTORY in _codes(verdict)
    witness = next(r for r in verdict.reasons
                   if r.code is ReasonCode.MAPPING_AGENT_NOT_IN_INVENTORY)
    assert "agent_group[0]/compute_tile[9]" in witness.witnesses


def test_mapping_kind_mismatch_witness():
    inventory = _inventory(
        tp=4,
        agents=[Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
                Agent(kind=AgentKind.COMPUTE_TILE, count=4)])
    mapping = MappingArtifact(placements=(
        RankPlacement(0, AgentInstance(0, 0, AgentKind.COMPUTE_TILE)),
        RankPlacement(1, AgentInstance(1, 0, AgentKind.COMPUTE_TILE)),
        RankPlacement(2, AgentInstance(1, 1, AgentKind.COMPUTE_TILE)),
        RankPlacement(3, AgentInstance(1, 2, AgentKind.COMPUTE_TILE)),
    ))
    contract = PlacementContract()
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.MAPPING_AGENT_NOT_IN_INVENTORY in _codes(verdict)
    witness = next(r for r in verdict.reasons
                   if r.code is ReasonCode.MAPPING_AGENT_NOT_IN_INVENTORY)
    assert witness.witnesses[0] == "0"
    assert "compute_tile" in witness.witnesses[1]


def test_mapping_rank_out_of_inventory_witness():
    inventory = _inventory(tp=4,
                           agents=[Agent(kind=AgentKind.COMPUTE_TILE,
                                         count=6)])
    mapping = _mapping([(0, 0, 0), (1, 0, 1), (2, 0, 2), (3, 0, 3),
                        (4, 0, 4), (5, 0, 5)])
    contract = PlacementContract()
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.MAPPING_RANK_OUT_OF_INVENTORY in _codes(verdict)
    witness = next(r for r in verdict.reasons
                   if r.code is ReasonCode.MAPPING_RANK_OUT_OF_INVENTORY)
    assert witness.witnesses == ("4", "5")
    assert verdict.ranks_mapped == 4


def test_mapping_incomplete_witness():
    inventory = _inventory(tp=4)
    mapping = _mapping([(0, 0, 0), (1, 0, 1)])
    contract = PlacementContract()
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.MAPPING_INCOMPLETE in _codes(verdict)
    witness = next(r for r in verdict.reasons
                   if r.code is ReasonCode.MAPPING_INCOMPLETE)
    assert "2" in witness.witnesses and "3" in witness.witnesses


def test_empty_contract_still_gates_mapping():
    inventory = _inventory(tp=4)
    assert check_placement_contract(
        PlacementContract(), inventory, _derived(tp=4)).ok
    broken = _mapping([(0, 0, 0), (1, 0, 1), (2, 0, 2), (3, 0, 8)])
    assert not check_placement_contract(
        PlacementContract(), inventory, broken).ok


def test_movement_radius_enforced():
    inventory = _inventory(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),),
        movements=(AllowedMovement(rank=0, policy=MovementPolicy.RADIUS,
                                   radius=1),))
    ok_mapping = _derived(tp=4)
    assert check_placement_contract(contract, inventory, ok_mapping).ok
    far_mapping = _mapping([(0, 0, 3), (1, 0, 1), (2, 0, 2), (3, 0, 0)])
    verdict = check_placement_contract(contract, inventory, far_mapping)
    assert not verdict.ok
    assert ReasonCode.MOVEMENT_RADIUS_EXCEEDED in _codes(verdict)
    assert ReasonCode.PIN_MISMATCH not in _codes(verdict)
    exceeded = next(r for r in verdict.reasons
                    if r.code is ReasonCode.MOVEMENT_RADIUS_EXCEEDED)
    assert exceeded.witnesses == ("0", "1", "3")


def test_pinned_movement_means_exact_pin():
    inventory = _inventory(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),),
        movements=(AllowedMovement(rank=0, policy=MovementPolicy.PINNED),))
    displaced = _mapping([(0, 0, 1), (1, 0, 0), (2, 0, 2), (3, 0, 3)])
    verdict = check_placement_contract(contract, inventory, displaced)
    assert not verdict.ok
    assert ReasonCode.PIN_MISMATCH in _codes(verdict)


def test_radius_zero_movement_refuses_displacement():
    inventory = _inventory(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),),
        movements=(AllowedMovement(rank=0, policy=MovementPolicy.RADIUS,
                                   radius=0),))
    displaced = _mapping([(0, 0, 1), (1, 0, 0), (2, 0, 2), (3, 0, 3)])
    verdict = check_placement_contract(contract, inventory, displaced)
    assert not verdict.ok
    assert ReasonCode.MOVEMENT_RADIUS_EXCEEDED in _codes(verdict)


def test_movement_within_radius_passes():
    inventory = _inventory(tp=4)
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),),
        movements=(AllowedMovement(rank=0, policy=MovementPolicy.RADIUS,
                                   radius=2),))
    mapping = _mapping([(0, 0, 2), (1, 0, 1), (2, 0, 0), (3, 0, 3)])
    verdict = check_placement_contract(contract, inventory, mapping)
    assert verdict.ok
    assert verdict.reasons == ()


def test_movement_without_pin_refuses():
    inventory = _inventory(tp=4)
    contract = PlacementContract(
        movements=(AllowedMovement(rank=0, policy=MovementPolicy.RADIUS,
                                   radius=2),))
    verdict = check_placement_contract(contract, inventory,
                                       _derived(tp=4))
    assert not verdict.ok
    assert ReasonCode.MOVEMENT_WITHOUT_PIN in _codes(verdict)


def test_affinity_member_outside_domains_unverifiable():
    inventory = _inventory(tp=4,
                           agents=[Agent(kind=AgentKind.COMPUTE_TILE,
                                         count=6)])
    mapping = _mapping([(0, 0, 0), (1, 0, 5), (2, 0, 1), (3, 0, 2)])
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 1))),),
        co_locates=(CoLocate(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.AFFINITY_UNVERIFIED in _codes(verdict)


def test_anti_affinity_member_outside_domains_unverifiable():
    inventory = _inventory(tp=4,
                           agents=[Agent(kind=AgentKind.COMPUTE_TILE,
                                         count=6)])
    mapping = _mapping([(0, 0, 0), (1, 0, 5), (2, 0, 1), (3, 0, 2)])
    contract = PlacementContract(
        domains=(LocalityDomain(name="island_a",
                                seats=(_seat(0, 0), _seat(0, 1))),
                 LocalityDomain(name="island_b", seats=(_seat(0, 3),)),),
        anti_affinities=(AntiAffinity(ranks=(0, 1)),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.SPREAD_UNVERIFIED in _codes(verdict)


def test_mandated_domain_undeclared_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(
        co_locates=(CoLocate(ranks=(0, 1), domain="nope"),))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.UNKNOWN_DOMAIN in _codes(verdict)


def test_overlapping_domains_refuse():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(domains=(
        LocalityDomain(name="island_a", seats=(_seat(0, 0), _seat(0, 1))),
        LocalityDomain(name="island_b", seats=(_seat(0, 1), _seat(0, 3))),
    ))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.OVERLAPPING_DOMAINS in _codes(verdict)


def test_duplicate_domain_name_refuses():
    inventory = _inventory(tp=4)
    mapping = _derived(tp=4)
    contract = PlacementContract(domains=(
        LocalityDomain(name="island_a", seats=(_seat(0, 0),)),
        LocalityDomain(name="island_a", seats=(_seat(0, 1),)),
    ))
    verdict = check_placement_contract(contract, inventory, mapping)
    assert not verdict.ok
    assert ReasonCode.DUPLICATE_DOMAIN in _codes(verdict)


def test_affinity_aliases_export():
    assert Affinity is CoLocate
    assert Spread is AntiAffinity


def test_schema_version_guard():
    with pytest.raises(PlacementContractError):
        PlacementContract(schema_version=PLACEMENT_CONTRACT_SCHEMA_VERSION + 1)
    with pytest.raises(PlacementContractError):
        PlacementContract(schema_version=True)


def test_movement_policy_radius_coherence():
    with pytest.raises(PlacementContractError):
        AllowedMovement(rank=0, policy=MovementPolicy.PINNED, radius=1)
    with pytest.raises(PlacementContractError):
        AllowedMovement(rank=0, policy=MovementPolicy.UNPINNED, radius=2)
    AllowedMovement(rank=0, policy=MovementPolicy.RADIUS, radius=0)
    AllowedMovement(rank=0, policy=MovementPolicy.RADIUS, radius=3)


def test_floats_and_bools_rejected():
    with pytest.raises(PlacementContractError):
        SeatCoordinate(group_index=0.0, instance_index=1)
    with pytest.raises(PlacementContractError):
        SeatCoordinate(group_index=True, instance_index=1)
    with pytest.raises(PlacementContractError):
        AllowedMovement(rank=0, policy=MovementPolicy.RADIUS, radius=1.5)
    with pytest.raises(PlacementContractError):
        AllowedMovement(rank=0, policy=MovementPolicy.RADIUS, radius=True)
    with pytest.raises(PlacementContractError):
        FixedPlacement(rank=False, seat=_seat(0, 0))


def test_prefer_requires_exactly_one_target():
    with pytest.raises(PlacementContractError):
        Prefer(rank=0)
    with pytest.raises(PlacementContractError):
        Prefer(rank=0, domain="x", seat=_seat(0, 0))


def test_verdict_refuses_inconsistent_ok_and_reasons():
    witness = Reason(code=ReasonCode.UNKNOWN_RANK, detail="rank 99 missing")
    with pytest.raises(PlacementContractError):
        Verdict(ok=True, reasons=(witness,))
    with pytest.raises(PlacementContractError):
        Verdict(ok=False, reasons=())
    Verdict(ok=True)
    Verdict(ok=False, reasons=(witness,))


def test_check_rejects_wrong_argument_types():
    with pytest.raises(TypeError):
        check_placement_contract(object(), _inventory(tp=4),
                                 _derived(tp=4))
    with pytest.raises(TypeError):
        check_placement_contract(PlacementContract(), object(),
                                 _derived(tp=4))
    with pytest.raises(TypeError):
        check_placement_contract(PlacementContract(), _inventory(tp=4),
                                 object())


def test_contract_roundtrip_dict_has_scope_marker():
    contract = PlacementContract(
        placements=(FixedPlacement(rank=0, seat=_seat(0, 0)),),
        domains=(LocalityDomain(name="island_a", seats=(_seat(0, 0),)),))
    doc = contract.to_dict()
    assert doc["schema_version"] == PLACEMENT_CONTRACT_SCHEMA_VERSION
    assert doc["scope"] == "LOGICAL_RANK_TO_AGENT_SEAT_COORDINATES_NO_GEOMETRY"


def _eighty_one_rank_fixture():
    inventory = _inventory(tp=81)
    mapping = _derived(tp=81)
    domains = tuple(
        LocalityDomain(name=f"island_{k}",
                       seats=tuple(_seat(0, s) for s in range(k * 9, k * 9 + 9)))
        for k in range(9))
    placements = tuple(FixedPlacement(rank=r, seat=_seat(0, r))
                       for r in range(81))
    movements = tuple(
        AllowedMovement(rank=r, policy=MovementPolicy.RADIUS, radius=2)
        for r in range(81))
    co_locates = tuple(
        CoLocate(ranks=tuple(range(k * 9, k * 9 + 9)), domain=f"island_{k}")
        for k in range(9))
    anti_affinities = (AntiAffinity(ranks=tuple(range(0, 81, 9))),)
    prefers = tuple(Prefer(rank=r, domain=f"island_{r // 9}")
                    for r in range(81))
    contract = PlacementContract(
        placements=placements, movements=movements, domains=domains,
        co_locates=co_locates, anti_affinities=anti_affinities,
        prefers=prefers)
    return inventory, mapping, domains, contract


def test_check_placement_contract_is_idempotent_across_calls():
    inventory, mapping, domains, contract = _eighty_one_rank_fixture()
    first = check_placement_contract(contract, inventory, mapping)
    assert first.ok
    for _ in range(4):
        again = check_placement_contract(contract, inventory, mapping)
        assert again == first
        assert again.to_dict() == first.to_dict()
    broken = PlacementContract(
        placements=tuple(FixedPlacement(rank=r, seat=_seat(0, (r + 1) % 81))
                         for r in range(81)),
        domains=domains,
        co_locates=(CoLocate(ranks=(0, 40, 80)),))
    broken_first = check_placement_contract(broken, inventory, mapping)
    assert not broken_first.ok
    for _ in range(4):
        again = check_placement_contract(broken, inventory, mapping)
        assert again == broken_first
        assert again.to_dict() == broken_first.to_dict()


def test_eighty_one_rank_check_informational_timing():
    inventory, mapping, _domains, contract = _eighty_one_rank_fixture()
    start = time.perf_counter()
    verdict = check_placement_contract(contract, inventory, mapping)
    elapsed = time.perf_counter() - start
    print(f"check_placement_contract on the 81-rank synthetic inventory "
          f"took {elapsed:.4f} s (informational only)")
    assert verdict.ok
