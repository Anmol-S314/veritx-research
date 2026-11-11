from __future__ import annotations

from pathlib import Path

import pytest

from veritx_dse.model.compile_model import Agent, AgentKind
from veritx_dse.model.system_intent import (
    SystemIntentError, SystemIntentV4, legacy_group_id,
    migrate_v3_address_targets, migrate_v3_agents_to_v4,
)

EVIDENCE = Path(__file__).resolve().parents[4] / "docs" / "product" / "evidence" / "mixtral-74-81-8-162" / "revision-p-fd7e5e31be77-r02.json"


def _example_agents():
    return (
        Agent(kind=AgentKind.COMPUTE_TILE, count=4),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
        Agent(kind=AgentKind.COMPUTE_TILE, count=2),
    )


def test_legacy_group_id_is_deterministic():
    assert [legacy_group_id(i) for i in (0, 1, 2, 10)] == [
        "legacy-agent-group-000", "legacy-agent-group-001",
        "legacy-agent-group-002", "legacy-agent-group-010",
    ]


def test_address_targets_are_a_bijection_onto_positions():
    mapping = migrate_v3_address_targets(_example_agents())
    assert mapping == {0: "legacy-agent-group-000", 1: "legacy-agent-group-001",
                       2: "legacy-agent-group-002"}
    assert len(set(mapping.values())) == len(mapping)


def test_migration_stamps_exact_shape_of_the_declared_agents():
    intent = migrate_v3_agents_to_v4(_example_agents())
    assert [g.kind for g in intent.agent_groups] == [
        AgentKind.COMPUTE_TILE, AgentKind.HBM_CONTROLLER, AgentKind.COMPUTE_TILE]
    assert [g.count for g in intent.agent_groups] == [4, 1, 2]
    for group in intent.agent_groups:
        assert group.instance_ids == tuple(
            f"{group.group_id}/{i}" for i in range(group.count))


def test_migration_stamps_identity_onto_position_not_agent():
    first = migrate_v3_agents_to_v4(_example_agents())
    reordered = migrate_v3_agents_to_v4((
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
        Agent(kind=AgentKind.COMPUTE_TILE, count=4),
        Agent(kind=AgentKind.COMPUTE_TILE, count=2),
    ))
    assert first.agent_groups[0].kind is reordered.agent_groups[1].kind
    assert first.agent_groups[0].group_id == "legacy-agent-group-000"
    assert reordered.agent_groups[1].group_id == "legacy-agent-group-001"


def test_positional_ids_do_not_survive_reordering_which_is_the_known_gap():
    first = migrate_v3_agents_to_v4(_example_agents())
    reordered = migrate_v3_agents_to_v4((
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1),
        Agent(kind=AgentKind.COMPUTE_TILE, count=4),
        Agent(kind=AgentKind.COMPUTE_TILE, count=2),
    ))
    assert first.agent_groups[0].group_id == "legacy-agent-group-000"
    assert first.agent_groups[0].kind is AgentKind.COMPUTE_TILE
    assert reordered.agent_groups[0].group_id == "legacy-agent-group-000"
    assert reordered.agent_groups[0].kind is AgentKind.HBM_CONTROLLER


@pytest.mark.skipif(not EVIDENCE.is_file(), reason="pinned Mixtral artifact not present")
def test_stamped_mixtral_revision_agent_counts_are_preserved_by_migration():
    import json
    doc = json.loads(EVIDENCE.read_text())
    agents = tuple(
        Agent(kind=AgentKind[a["kind"].upper()], count=a["count"])
        for a in doc["design"]["agents"])
    intent = migrate_v3_agents_to_v4(agents)
    assert [g.count for g in intent.agent_groups] == [64, 8, 2]
    assert sum(g.count for g in intent.agent_groups) == 74
    assert len({g.group_id for g in intent.agent_groups}) == len(intent.agent_groups)
