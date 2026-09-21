"""tests/test_v2_cutover_gaps.py — the NetworkWindowBinding generation.

These pins were written BEFORE the gap was closed, to make it impossible to
forget; they flipped when the fix landed and now assert the closed
contract. See docs/2C4-V1-PARENTAGE-LEDGER.md §3.

The contract:

  v1 binding   no schema_version, operation_graph_id parent, byte-identical
               to what it always serialized (historical results must keep
               verifying)
  v2 binding   schema_version=2, workload_graph_id parent
  dispatch     explicit: absence means v1, unknown refuses, and a binding
               never names a parent from the other generation
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.waved_resources import (  # noqa: E402
    CHAIN_SCHEMA_VERSION_V2, PLAN_CHAIN_KEYS_V2,
)
from veritx_dse.wavee.network import (  # noqa: E402
    NETWORK_BINDING_SCHEMA_VERSION_V1, NETWORK_BINDING_SCHEMA_VERSION_V2,
    NetworkWindowBinding, bind_network_window,
)
from veritx_dse.wavee.time import TimeError  # noqa: E402


def _v1_binding() -> dict:
    return {
        "operation_graph_id": "sha256:" + "a" * 64,
        "physical_traffic_id": "sha256:" + "b" * 64,
        "backend_config_hash": "c" * 64,
        "backend_input_hash": "d" * 64,
        "evidence_sha256": "e" * 64,
        "stats_sha256": "f" * 64,
        "network_clock_hz": None,
        "window_kind": "BARRIER",
        "duration": None,
    }


def _v2_binding() -> dict:
    d = _v1_binding()
    d.pop("operation_graph_id")
    d["schema_version"] = NETWORK_BINDING_SCHEMA_VERSION_V2
    d["workload_graph_id"] = "sha256:" + "1" * 64
    return d


def _v1_chain() -> dict:
    return {
        "operation_graph_id": "sha256:" + "a" * 64,
        "physical_traffic_id": "sha256:" + "b" * 64,
        "backend_config_hash": "c" * 64,
        "backend_input_hash": "d" * 64,
    }


def _v2_chain() -> dict:
    block = {key: f"v2-{key}" for key in PLAN_CHAIN_KEYS_V2}
    block["chain_schema_version"] = CHAIN_SCHEMA_VERSION_V2
    block["backend_config_hash"] = "c" * 64
    block["backend_input_hash"] = "d" * 64
    assert "operation_graph_id" not in block
    return block


class TestBindingGenerations:
    """Ledger 3.3 — the persisted schema, not a read."""

    def test_v1_binding_round_trips_byte_identically(self):
        """Historical results must keep verifying: a v1 binding still
        serializes with no version field and the historical parent key."""
        d = _v1_binding()
        assert NetworkWindowBinding.from_dict(d).to_dict() == d

    def test_v1_binding_carries_no_generation_field(self):
        binding = NetworkWindowBinding.from_dict(_v1_binding())
        assert binding.schema_version == NETWORK_BINDING_SCHEMA_VERSION_V1
        assert "schema_version" not in binding.to_dict()

    def test_v2_binding_round_trips(self):
        d = _v2_binding()
        binding = NetworkWindowBinding.from_dict(d)
        assert binding.schema_version == NETWORK_BINDING_SCHEMA_VERSION_V2
        assert binding.to_dict() == d

    def test_v2_binding_names_the_canonical_parent(self):
        binding = NetworkWindowBinding.from_dict(_v2_binding())
        assert binding.workload_parent_id == _v2_binding()[
            "workload_graph_id"]
        assert "operation_graph_id" not in binding.to_dict()

    def test_mixed_generations_refuse_in_both_directions(self):
        """The transplant: v2 fields under a v1 document, and the
        reverse. Neither may be read as the other generation."""
        both = _v2_binding()
        both["operation_graph_id"] = "sha256:" + "9" * 64
        with pytest.raises(TimeError, match="network binding fields"):
            NetworkWindowBinding.from_dict(both)
        v1_with_version = dict(_v1_binding())
        v1_with_version["schema_version"] = 1
        with pytest.raises(TimeError, match="network binding fields"):
            NetworkWindowBinding.from_dict(v1_with_version)

    def test_unknown_generation_refuses(self):
        d = _v2_binding()
        d["schema_version"] = 7
        with pytest.raises(TimeError, match="unknown network binding"):
            NetworkWindowBinding.from_dict(d)


class TestBinderDispatchesOnChainGeneration:
    """Ledger 3.2 — the construction site."""

    @staticmethod
    def _evidence() -> dict:
        return {"stats": {"completion_time": 128, "delivered": 4}}

    def test_v1_chain_binds_a_v1_binding(self):
        binding, duration = bind_network_window(
            evidence=self._evidence(), chain=_v1_chain(),
            network_clock_hz=None, evidence_sha256="e" * 64)
        assert binding.schema_version == NETWORK_BINDING_SCHEMA_VERSION_V1
        assert binding.workload_parent_id == _v1_chain()["operation_graph_id"]
        assert duration == 128

    def test_v2_chain_binds_a_v2_binding(self):
        binding, _ = bind_network_window(
            evidence=self._evidence(), chain=_v2_chain(),
            network_clock_hz=None, evidence_sha256="e" * 64)
        assert binding.schema_version == NETWORK_BINDING_SCHEMA_VERSION_V2
        assert binding.workload_parent_id == _v2_chain()["workload_graph_id"]
        assert "workload_graph_id" in binding.to_dict()
        assert "operation_graph_id" not in binding.to_dict()

    def test_unknown_chain_generation_refuses(self):
        chain = _v2_chain()
        chain["chain_schema_version"] = 9
        with pytest.raises(TimeError, match="cannot bind a network window"):
            bind_network_window(
                evidence=self._evidence(), chain=chain,
                network_clock_hz=None, evidence_sha256="e" * 64)

    def test_chain_missing_its_declared_parent_refuses(self):
        """A v2 chain that declares its generation but names no canonical
        parent must not silently fall back to the v1 key."""
        chain = _v2_chain()
        del chain["workload_graph_id"]
        with pytest.raises(TimeError, match="must name its workload"):
            bind_network_window(
                evidence=self._evidence(), chain=chain,
                network_clock_hz=None, evidence_sha256="e" * 64)


class TestDerivationBuildsAGenerationCorrectChain:
    """Ledger 3.4 — the caller in `_derive_wave_e_block`."""

    @staticmethod
    def _evidence():
        class _E:
            backend_config_hash = "c" * 64
            backend_input_hash = "d" * 64
        return _E()

    def test_v1_plan_chain_yields_a_v1_binder_chain(self):
        from veritx_dse.application.service import _binder_chain
        out = _binder_chain(_v1_chain(), self._evidence())
        assert "operation_graph_id" in out
        assert "workload_graph_id" not in out
        assert "chain_schema_version" not in out
        assert out["backend_config_hash"] == "c" * 64

    def test_v2_plan_chain_yields_a_v2_binder_chain(self):
        from veritx_dse.application.service import _binder_chain
        out = _binder_chain(_v2_chain(), self._evidence())
        assert out["workload_graph_id"] == _v2_chain()["workload_graph_id"]
        assert out["chain_schema_version"] == 2
        assert "operation_graph_id" not in out

    def test_the_derivation_and_the_binder_agree_end_to_end(self):
        """The property that matters: what _derive_wave_e_block builds is
        exactly what the binder accepts, for both generations."""
        from veritx_dse.application.service import _binder_chain
        evidence = self._evidence()
        for chain in (_v1_chain(), _v2_chain()):
            built = _binder_chain(chain, evidence)
            binding, _ = bind_network_window(
                evidence={"stats": {"completion_time": 10, "delivered": 1}},
                chain=built, network_clock_hz=None,
                evidence_sha256="e" * 64)
            assert binding.workload_parent_id == built.get(
                "workload_graph_id") or binding.workload_parent_id == \
                built.get("operation_graph_id")
