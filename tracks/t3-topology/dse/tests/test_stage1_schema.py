"""STAGE 1 schema: CompileRequestV4 agent_intents + traffic_policy (D3).

Golden hashes: the srota32 preset hash and the small mesh hash were recorded
BEFORE the stage-1 fields existed; any change here is a compatibility break
(P4: absent ≡ empty, byte-identical serialization).
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
    TrafficClassVC, TrafficPolicyV4,
)
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CollectiveDimension, CollectiveIntent, CollectiveKind,
    DependencyGraph, ModelFamily, WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import (
    CompileRequestV4, CompileRequestV4SchemaError,
)
from veritx_dse.model.topology_intent import MeshIntent

# Recorded on HEAD before stage-1 fields landed (docs §8.4 golden hashes).
SMALL_MESH_HASH = "d503d90bf422348dddd65ed2e4b7c37c7290fd63375817e0dca153e7d41368a8"
PRESET_HASH = "542e845608452b9cda153f7b339cf53e07cb06d7dde6ed1a1b082daf70f3c249"


def _workload() -> WorkloadV3:
    return WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))


def _small_request(**kwargs) -> CompileRequestV4:
    args = dict(
        workload=_workload(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1))
    args.update(kwargs)
    return CompileRequestV4(**args)


def test_golden_hashes_are_unchanged():
    assert _small_request().design_hash() == SMALL_MESH_HASH
    from test_topology_search import _base
    assert _base().design_hash() == PRESET_HASH


def test_absent_is_empty():
    request = _small_request()
    assert request.agent_intents == ()
    assert request.traffic_policy.is_empty()
    # No new keys serialize, and the hash equals the no-intent hash.
    document = request.to_dict()
    assert "agent_intents" not in document
    assert "traffic_policy" not in document
    reloaded = CompileRequestV4.from_dict(document)
    assert reloaded.design_hash() == SMALL_MESH_HASH
    assert reloaded.agent_intents == ()
    assert reloaded.traffic_policy.is_empty()


def test_explicit_empty_hashes_identically_to_absent():
    base = _small_request().to_dict()
    for key in ("design_hash", "guardrail_hash"):
        base.pop(key)
    base["agent_intents"] = []
    base["traffic_policy"] = {"traffic_class_vcs": []}
    reloaded = CompileRequestV4.from_dict(base)
    assert reloaded.design_hash() == SMALL_MESH_HASH
    # .. and still serialize without the keys (absent ≡ empty).
    assert "agent_intents" not in reloaded.to_dict()
    assert "traffic_policy" not in reloaded.to_dict()


def test_mesh_example_roundtrip():
    """STAGE 1 §3.2 JSON → from_dict → to_dict byte-identity + hash."""
    base = _small_request().to_dict()
    for key in ("design_hash", "guardrail_hash"):
        base.pop(key)
    base["agent_intents"] = [{
        "agent_idx": 0, "protocol": "axi5", "ordering": "strong",
        "max_outstanding": 16, "split_at": 64,
        "clock_domain": None, "power_domain": None,
    }]
    base["traffic_policy"] = {"traffic_class_vcs": [
        {"traffic_class": "tp_collective", "vc": 0}]}
    request = CompileRequestV4.from_dict(base)
    assert request.agent_intents == (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG,
                      max_outstanding=16, split_at=64),)
    assert request.traffic_policy == TrafficPolicyV4(
        traffic_class_vcs=(TrafficClassVC("tp_collective", 0),))
    document = request.to_dict()
    # None fields omit (sparse serialization); the parsed doc is recovered.
    assert document["agent_intents"] == [{
        "agent_idx": 0, "protocol": "axi5", "ordering": "strong",
        "max_outstanding": 16, "split_at": 64}]
    assert document["traffic_policy"] == base["traffic_policy"]
    # Hash names the new science (P4) and round-trips stably.
    assert request.design_hash() != SMALL_MESH_HASH
    reloaded = CompileRequestV4.from_dict(document)
    assert reloaded.to_dict() == document
    assert reloaded.design_hash() == request.design_hash()


def test_permission_windows_roundtrip():
    base = _small_request().to_dict()
    for key in ("design_hash", "guardrail_hash"):
        base.pop(key)
    base["agent_intents"] = [{
        "agent_idx": 0,
        "permission_windows": [
            {"address_range": "HBM0", "readable": True, "writable": False}],
    }]
    request = CompileRequestV4.from_dict(base)
    assert request.agent_intents[0].permission_windows == (
        PermissionWindow("HBM0", readable=True, writable=False),)
    assert CompileRequestV4.from_dict(
        request.to_dict()).agent_intents == request.agent_intents


@pytest.mark.parametrize("patch", [
    {"agent_intenets": []},
    {"traffic_policy": {"traffic_class_vcs": [{"traffic_class": "x", "Vc": 0}]}},
    {"traffic_policy": {"unknown_key": []}},
    {"agent_intents": [{"agent_idx": 0, "bogus": 1}]},
    {"agent_intents": [{"agent_idx": 0, "protocol": "axi99"}]},
    {"agent_intents": [{"agent_idx": 5, "protocol": "axi5"}]},
    {"agent_intents": [{"agent_idx": 0, "max_outstanding": 0}]},
    {"agent_intents": [{"agent_idx": 0, "split_at": 0}]},
    {"traffic_policy": {"traffic_class_vcs": [{"traffic_class": "x", "vc": 16}]}},
    {"traffic_policy": {"traffic_class_vcs": [{"traffic_class": "x", "vc": -1}]}},
], ids=["topo-typo", "vc-capital", "policy-unknown", "row-unknown",
        "bad-protocol", "idx-out-of-range", "max-outstanding-zero",
        "split-at-zero", "vc-at-max", "vc-negative"])
def test_strict_keys_refuse(patch):
    base = _small_request().to_dict()
    for key in ("design_hash", "guardrail_hash"):
        base.pop(key)
    base.update(patch)
    with pytest.raises(CompileRequestV4SchemaError):
        CompileRequestV4.from_dict(base)


def test_duplicate_indices_and_classes_refuse():
    with pytest.raises(ValueError, match="duplicate agent_idx"):
        _small_request(agent_intents=(
            AgentIntentV4(0, protocol=ProtocolFamily.AXI5),
            AgentIntentV4(0, protocol=ProtocolFamily.CHI)))
    with pytest.raises(ValueError, match="duplicate traffic_class"):
        TrafficPolicyV4(traffic_class_vcs=(
            TrafficClassVC("a", 0), TrafficClassVC("a", 1)))


def test_migrate_v3_to_v4_carries_empty_stage1():
    """§8.4: a migrated v3 draft (no intents) stays empty and compiles."""
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.compile_request_v4 import migrate_v3_to_v4
    from test_compile_request_v4 import _v3
    v4 = migrate_v3_to_v4(_v3(topology_family=None, radix=None,
                              concentration=None))
    assert v4.agent_intents == ()
    assert v4.traffic_policy.is_empty()
    assert FabricCompiler().compile(v4).status == "COMPILED"


def test_compiled_fixtures_are_byte_identical():
    """Golden compiled fixtures (mesh4/mesh8x8) still compile identically."""
    tool = REPO / "tracks/t3-topology/dse/tools/generate_compiled_fixtures.py"
    assert tool.is_file(), "generator tool missing (DSE checkout drift?)"
    proc = subprocess.run(
        [sys.executable, str(tool), "--check"],
        cwd=str(REPO / "tracks/t3-topology/dse"),
        capture_output=True, text=True, timeout=600)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_json_document_with_new_fields_is_stable():
    base = _small_request().to_dict()
    for key in ("design_hash", "guardrail_hash"):
        base.pop(key)
    base["agent_intents"] = [{"agent_idx": 0, "protocol": "tilelink",
                              "ordering": "relaxed"}]
    first = json.dumps(CompileRequestV4.from_dict(base).to_dict(), sort_keys=True)
    second = json.dumps(CompileRequestV4.from_dict(
        json.loads(first)).to_dict(), sort_keys=True)
    assert first == second
