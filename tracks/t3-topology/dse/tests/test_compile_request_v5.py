"""CompileRequestV5 identity and explicit migration contract."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.model.compile_request_v5 import (  # noqa: E402
    AgentIntentV5,
    CompileRequestV5,
    CompileRequestV5MigrationError,
    CompileRequestV5SchemaError,
    migrate_v4_to_v5,
)
from veritx_dse.model.ip_catalog import InterfaceRole  # noqa: E402
from veritx_dse.model.transaction_intent import (  # noqa: E402
    OrderingMode,
    OrderingPolicy,
    TransactionPolicy,
)


def _v4() -> CompileRequestV4:
    path = DSE.parent / "examples" / "qwen3_moe_tp2_ep4_16tiles-v4.json"
    return CompileRequestV4.from_dict(json.loads(path.read_text()))


def test_v4_migration_is_explicit_neutral_and_preserves_v4_hash():
    original = _v4()
    old_hash = original.design_hash()
    migrated = migrate_v4_to_v5(original)
    assert migrated.base_v4 is original
    assert migrated.to_compile_request_v4() is original
    assert original.design_hash() == old_hash
    assert migrated.migration_provenance["source_design_hash"] == old_hash
    assert "no interface role" in migrated.migration_provenance[
        "neutral_extension_semantics"]


def test_v5_roundtrip_and_hash_are_deterministic():
    migrated = migrate_v4_to_v5(_v4())
    wire = migrated.to_dict()
    restored = CompileRequestV5.from_dict(wire)
    assert restored == migrated
    assert restored.design_hash() == migrated.design_hash()
    assert CompileRequestV5.from_dict(restored.to_dict()) == restored


def test_v5_extension_changes_identity_and_v4_projection_refuses():
    base = _v4()
    policy = TransactionPolicy(
        ordering=OrderingPolicy(
            mode=OrderingMode.STRONG,
            enforce_raw=True, enforce_war=True, enforce_waw=True))
    extended = CompileRequestV5(
        base_v4=base,
        agent_intents=(AgentIntentV5(
            agent_group_index=0,
            interface_role=InterfaceRole.INITIATOR,
            transaction_policy=policy),))
    neutral = migrate_v4_to_v5(base)
    assert extended.design_hash() != neutral.design_hash()
    with pytest.raises(CompileRequestV5SchemaError, match="refusing to drop"):
        extended.to_compile_request_v4()


def test_v5_reader_refuses_unknown_fields_and_implicit_v4():
    v5 = migrate_v4_to_v5(_v4()).to_dict()
    v5["mystery"] = True
    with pytest.raises(CompileRequestV5SchemaError, match="unknown fields"):
        CompileRequestV5.from_dict(v5)
    with pytest.raises(CompileRequestV5SchemaError, match="requires schema_version=5"):
        CompileRequestV5.from_dict(_v4().to_dict())


def test_agent_intent_refuses_unknown_role_and_negative_group():
    with pytest.raises(CompileRequestV5SchemaError, match="unknown interface_role"):
        AgentIntentV5.from_dict({"agent_group_index": 0,
                                 "interface_role": "MASTER"})
    with pytest.raises(CompileRequestV5SchemaError, match="non-negative"):
        AgentIntentV5(agent_group_index=-1)


def test_v5_hash_is_domain_separated_from_v4():
    v4 = _v4()
    v5 = migrate_v4_to_v5(v4)
    assert v5.design_hash() != v4.design_hash()


def test_agent_extension_declaration_order_does_not_change_identity():
    base = _v4()
    left = CompileRequestV5(base_v4=base, agent_intents=(
        AgentIntentV5(0, InterfaceRole.INITIATOR),
        AgentIntentV5(1, InterfaceRole.TARGET),
    ))
    right = CompileRequestV5(base_v4=base, agent_intents=(
        AgentIntentV5(1, InterfaceRole.TARGET),
        AgentIntentV5(0, InterfaceRole.INITIATOR),
    ))
    assert left.agent_intents == right.agent_intents
    assert left.design_hash() == right.design_hash()
