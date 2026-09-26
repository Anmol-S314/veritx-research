"""SYSTEM intent v4 (Domain A closure) — contract and adversarial tests.

Cases A18–A34 from ``docs/product/INTENT-SYSTEM.md`` §20, plus the
migration and inventory contracts.
"""
from __future__ import annotations

import pytest

from veritx_dse.model.compile_model import Agent, AgentKind
from veritx_dse.model.system_intent import (
    AgentGroup,
    AgentInterface,
    ClockDomain,
    ContainerKind,
    PhysicalInventoryArtifact,
    PowerDomain,
    SystemContainer,
    SystemIntentError,
    SystemIntentV4,
    derive_physical_inventory,
    legacy_group_id,
    migrate_v3_address_targets,
    migrate_v3_agents_to_v4,
)


# ── fixtures ──────────────────────────────────────────────────────────────

def _machine(container_id: str = "machine") -> SystemContainer:
    return SystemContainer(container_id=container_id,
                           kind=ContainerKind.MACHINE)


def _two_accelerators() -> tuple[SystemContainer, ...]:
    return (
        _machine(),
        SystemContainer(container_id="node0", kind=ContainerKind.NODE,
                        parent_id="machine"),
        SystemContainer(container_id="acc0", kind=ContainerKind.ACCELERATOR,
                        parent_id="node0"),
        SystemContainer(container_id="acc1", kind=ContainerKind.ACCELERATOR,
                        parent_id="node0"),
    )


def _group(group_id: str, *, container_id: str = "acc0",
           count: int = 8, kind: AgentKind = AgentKind.COMPUTE_TILE,
           **kw) -> AgentGroup:
    return AgentGroup(group_id=group_id, kind=kind, count=count,
                      container_id=container_id, **kw)


def _intent(groups, containers=None, **kw) -> SystemIntentV4:
    return SystemIntentV4(
        containers=containers or _two_accelerators(),
        agent_groups=tuple(groups), **kw)


# ── A18 reorder is a no-op ───────────────────────────────────────────────

def test_a18_reorder_is_no_op():
    a = _group("compute_a")
    b = _group("compute_b", container_id="acc1")
    forward = _intent([a, b])
    reversed_ = _intent([b, a])
    assert forward.system_intent_hash() == reversed_.system_intent_hash()
    assert [g.group_id for g in reversed_.agent_groups] == \
        ["compute_a", "compute_b"]


# ── A19 rename never moves identity ──────────────────────────────────────

def test_a19_rename_does_not_move_identity():
    plain = _intent([_group("compute_a")])
    named = _intent([_group("compute_a", name="Front-end tiles")])
    named_root = SystemIntentV4(
        containers=(SystemContainer("machine", ContainerKind.MACHINE,
                                    name="Rack 1"),),
        agent_groups=(_group("compute_a", container_id="machine"),))
    flat = SystemIntentV4(
        containers=(_machine(),),
        agent_groups=(_group("compute_a", container_id="machine"),))
    assert plain.system_intent_hash() == named.system_intent_hash()
    assert named_root.system_intent_hash() == flat.system_intent_hash()


# ── A20/A21/A22 structural integrity ─────────────────────────────────────

def test_a20_duplicate_group_id_is_invalid():
    with pytest.raises(SystemIntentError, match="duplicate group_id"):
        _intent([_group("compute_a"), _group("compute_a",
                                             container_id="acc1")])


def test_a21_missing_container_is_invalid():
    with pytest.raises(SystemIntentError, match="missing container"):
        _intent([_group("compute_a", container_id="nope")])


def test_a22_parent_cycle_is_invalid():
    containers = (
        _machine(),
        SystemContainer("a", ContainerKind.PACKAGE, parent_id="b"),
        SystemContainer("b", ContainerKind.PACKAGE, parent_id="a"),
    )
    with pytest.raises(SystemIntentError, match="cycle|one root"):
        _intent([_group("compute_a", container_id="a")], containers=containers)


def test_exactly_one_root_required():
    containers = (
        _machine("m1"),
        _machine("m2"),
    )
    with pytest.raises(SystemIntentError, match="exactly one root"):
        _intent([_group("compute_a", container_id="m1")], containers=containers)


# ── A23/A24 hierarchy is semantic but creates no topology ────────────────

def test_a23_two_packages_are_distinct_hierarchy():
    containers = (
        _machine(),
        SystemContainer("pkg0", ContainerKind.PACKAGE, parent_id="machine"),
        SystemContainer("pkg1", ContainerKind.PACKAGE, parent_id="machine"),
    )
    one = _intent([_group("compute_a", container_id="pkg0")],
                  containers=containers)
    other = _intent([_group("compute_a", container_id="pkg1")],
                    containers=containers)
    assert one.system_intent_hash() != other.system_intent_hash()


def test_a24_moving_a_group_changes_identity():
    left = _intent([_group("compute_a", container_id="acc0")])
    right = _intent([_group("compute_a", container_id="acc1")])
    assert left.system_intent_hash() != right.system_intent_hash()


def test_hierarchy_creates_no_topology_concepts():
    intent = _intent([_group("compute_a")])
    inventory = derive_physical_inventory(intent)
    payload = inventory.to_dict()
    for forbidden in ("ranks", "placement", "seats", "attachments",
                      "routers", "links", "planes", "routes"):
        assert forbidden not in payload


# ── A25 multiple domains: schema valid, fabric unsupported ───────────────

def test_a25_multiple_clock_domains_are_declarable():
    intent = _intent(
        [_group("compute_a", clock_domain_id="clk0"),
         _group("compute_b", container_id="acc1", clock_domain_id="clk1")],
        clock_domains=(ClockDomain("clk0"), ClockDomain("clk1")),
    )
    assert len(intent.clock_domains) == 2
    # the declaration is VALID; refusal belongs to fabric lowering


def test_undeclared_domain_reference_is_invalid():
    with pytest.raises(SystemIntentError, match="undeclared clock domain"):
        _intent([_group("compute_a", clock_domain_id="clk0")])
    with pytest.raises(SystemIntentError, match="undeclared power domain"):
        _intent([_group("compute_a", power_domain_id="pd0")])


# ── A28 elastic range is not representable ───────────────────────────────

def test_a28_elastic_count_is_refused():
    with pytest.raises(SystemIntentError, match="exact int"):
        _group("compute_a", count=(32, 64, 128))
    with pytest.raises(SystemIntentError, match="exact int"):
        _group("compute_a", count=True)


# ── A31/A32 unknown vocabulary fails closed ──────────────────────────────

def test_a31_unknown_container_kind_refused():
    with pytest.raises(SystemIntentError, match="unknown container kind"):
        SystemContainer.from_dict({"container_id": "x", "kind": "board",
                                   "parent_id": None})


def test_a32_unknown_agent_kind_refused():
    with pytest.raises(SystemIntentError, match="unknown agent kind"):
        AgentGroup.from_dict({
            "group_id": "g", "kind": "tpu", "count": 1,
            "container_id": "machine",
            "interface": {"data_width": 256, "addr_width": 64,
                          "protocol": "AXI"}})


def test_unknown_field_fails_closed():
    with pytest.raises(SystemIntentError, match="unknown fields"):
        SystemContainer.from_dict({"container_id": "x", "kind": "machine",
                                   "parent_id": None, "capabilities": []})
    with pytest.raises(SystemIntentError, match="unknown fields"):
        AgentInterface.from_dict({"data_width": 256, "addr_width": 64,
                                  "protocol": "AXI", "qos": "high"})


# ── interface semantics ──────────────────────────────────────────────────

def test_interface_bounds_are_enforced():
    with pytest.raises(SystemIntentError, match="data_width"):
        AgentInterface(data_width=4)
    with pytest.raises(SystemIntentError, match="addr_width"):
        AgentInterface(addr_width=4)
    with pytest.raises(SystemIntentError, match="protocol"):
        AgentInterface(protocol="")


def test_interface_change_moves_identity():
    a = _intent([_group("compute_a")])
    b = _intent([_group("compute_a",
                        interface=AgentInterface(protocol="CHI"))])
    assert a.system_intent_hash() != b.system_intent_hash()


# ── structural queries: SYSTEM owns facts, PLACEMENT owns policy ─────────

def test_ancestors_and_same_container():
    intent = _intent([_group("compute_a", container_id="acc0"),
                      _group("compute_b", container_id="acc1")])
    chain = intent.ancestors("acc0")
    assert [c.container_id for c in chain] == ["acc0", "node0", "machine"]
    assert intent.ancestor_of_kind("acc0", ContainerKind.NODE).container_id \
        == "node0"
    # same node, different accelerators
    assert intent.same_container("compute_a", "compute_b",
                                 ContainerKind.NODE)
    assert not intent.same_container("compute_a", "compute_b",
                                     ContainerKind.ACCELERATOR)


# ── serialization round-trip ─────────────────────────────────────────────

def test_intent_round_trip_preserves_identity():
    intent = _intent(
        [_group("compute_a", clock_domain_id="clk0"),
         _group("hbm_a", container_id="acc1", count=2,
                kind=AgentKind.HBM_CONTROLLER)],
        clock_domains=(ClockDomain("clk0"),),
    )
    again = SystemIntentV4.from_dict(intent.to_dict())
    assert again.system_intent_hash() == intent.system_intent_hash()
    assert again.to_dict() == intent.to_dict()


def test_wrong_type_tag_refused():
    doc = _intent([_group("compute_a")]).to_dict()
    doc["type"] = "srota/SomethingElse"
    with pytest.raises(SystemIntentError, match="type tag"):
        SystemIntentV4.from_dict(doc)


# ── derived physical inventory ───────────────────────────────────────────

def test_inventory_expands_supply_and_derives_demand():
    intent = _intent([
        _group("compute_a", count=8),
        _group("hbm_a", container_id="acc1", count=2,
               kind=AgentKind.HBM_CONTROLLER),
    ])
    inv = derive_physical_inventory(intent)
    assert inv.agent_count == 10
    assert inv.compute_instance_count == 8
    assert inv.endpoint_demand == 10          # derived, never declared
    assert inv.instances[0] == ("compute_a/0", "compute_tile")
    assert ("compute_a/7", "compute_tile") in inv.instances
    assert inv.system_intent_hash == intent.system_intent_hash()


def test_inventory_instance_ids_are_position_independent():
    a = derive_physical_inventory(_intent([_group("compute_a", count=2)]))
    b = derive_physical_inventory(_intent([_group("compute_a", count=2)]))
    assert a.inventory_hash == b.inventory_hash
    assert a.instances == b.instances


def test_inventory_hash_is_tamper_evident():
    inv = derive_physical_inventory(_intent([_group("compute_a", count=2)]))
    doc = inv.to_dict()
    doc["agent_count"] = 99
    with pytest.raises(SystemIntentError, match="does not match content"):
        PhysicalInventoryArtifact.from_dict(doc)


def test_inventory_round_trip():
    inv = derive_physical_inventory(_intent([_group("compute_a", count=3)]))
    again = PhysicalInventoryArtifact.from_dict(inv.to_dict())
    assert again.inventory_hash == inv.inventory_hash


def test_inventory_requires_system_intent():
    with pytest.raises(SystemIntentError, match="SystemIntentV4"):
        derive_physical_inventory({"agent_groups": []})


# ── v3 -> v4 migration ───────────────────────────────────────────────────

def _v3_agents() -> tuple[Agent, ...]:
    return (
        Agent(kind=AgentKind.COMPUTE_TILE, count=8),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=2, addr_width=48),
        Agent(kind=AgentKind.NIC, count=1, protocol="CHI"),
    )


def test_migration_ids_are_deterministic():
    assert legacy_group_id(0) == "legacy-agent-group-000"
    assert legacy_group_id(12) == "legacy-agent-group-012"
    one = migrate_v3_agents_to_v4(_v3_agents())
    two = migrate_v3_agents_to_v4(_v3_agents())
    assert one.system_intent_hash() == two.system_intent_hash()


def test_migration_is_lossless_for_v3_fields():
    intent = migrate_v3_agents_to_v4(_v3_agents())
    assert [g.group_id for g in intent.agent_groups] == [
        "legacy-agent-group-000",
        "legacy-agent-group-001",
        "legacy-agent-group-002",
    ]
    assert [g.count for g in intent.agent_groups] == [8, 2, 1]
    assert intent.agent_groups[1].interface.addr_width == 48
    assert intent.agent_groups[2].interface.protocol == "CHI"
    # flat v3 has no hierarchy: one MACHINE root, nothing invented
    assert [c.kind for c in intent.containers] == [ContainerKind.MACHINE]


def test_migration_address_targets_are_a_bijection():
    agents = _v3_agents()
    table = migrate_v3_address_targets(agents)
    assert table == {0: "legacy-agent-group-000",
                     1: "legacy-agent-group-001",
                     2: "legacy-agent-group-002"}
    assert len(set(table.values())) == len(agents)


def test_migration_refuses_empty_inventory():
    with pytest.raises(SystemIntentError, match="cannot be empty"):
        migrate_v3_agents_to_v4(())


def test_migrated_intent_derives_inventory():
    intent = migrate_v3_agents_to_v4(_v3_agents())
    inv = derive_physical_inventory(intent)
    assert inv.agent_count == 11
    assert inv.compute_instance_count == 8
