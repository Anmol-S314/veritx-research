"""tests/test_v2_cutover_gaps.py — executable pins for the v1-parentage gaps.

These are not "the v2 path works" tests; v2 has no writer yet. They are
pins that FAIL the moment the gap is closed, so 2c.4b cannot land the
writer switch while these sites still assume a v1 chain. Each one is
behavioural: the store, schema and constructor are exercised, not read.

See docs/2C4-V1-PARENTAGE-LEDGER.md.
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


def _v2_chain() -> dict:
    """A v2 chain as a real CALLER supplies it.

    service.py:_derive_wave_e_block hand-builds the binder's chain from
    the plan chain plus the run's backend hashes, so the backend hashes
    are generation-neutral and present in both generations. An earlier
    version of this fixture omitted them, which made the pin below pass
    for the wrong reason: the call raised KeyError on backend_config_hash
    whether or not the code could read a v2 parent. Verified by mutation.
    """
    block = {key: f"v2-{key}" for key in PLAN_CHAIN_KEYS_V2}
    block["chain_schema_version"] = CHAIN_SCHEMA_VERSION_V2
    block["backend_config_hash"] = "c" * 64
    block["backend_input_hash"] = "d" * 64
    assert "operation_graph_id" not in block
    return block


class TestNetworkBindingCannotExpressV2Ancestry:
    """Ledger 3.3 — the persisted binding schema, not a read."""

    @staticmethod
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

    def test_v1_binding_round_trips(self):
        from veritx_dse.wavee.network import NetworkWindowBinding
        d = self._v1_binding()
        assert NetworkWindowBinding.from_dict(d).to_dict() == d

    def test_binding_schema_refuses_a_v2_parent(self):
        """PIN: closes when NetworkWindowBinding becomes generation-aware.

        A binding that names a canonical WorkloadGraph parent is refused
        by the field set today, so a v2 plan cannot express its network
        ancestry at all.
        """
        from veritx_dse.wavee.time import TimeError
        from veritx_dse.wavee.network import NetworkWindowBinding
        d = self._v1_binding()
        d["workload_graph_id"] = d.pop("operation_graph_id")
        with pytest.raises(TimeError, match="network binding fields"):
            NetworkWindowBinding.from_dict(d)

    def test_binding_schema_has_no_generation_discriminator(self):
        """PIN: the binding cannot say WHICH generation it belongs to.

        Every other artifact in this cutover carries an explicit
        generation; this one carries a v1 field name and nothing else,
        which is why renaming rather than versioning would be wrong.

        The assertion is the TimeError and its message, so the pin bites
        when `allowed` gains `schema_version` — at which point the call
        succeeds and the closed gap is reported.
        """
        from veritx_dse.wavee.time import TimeError
        from veritx_dse.wavee.network import NetworkWindowBinding
        d = {**self._v1_binding(), "schema_version": 2}
        with pytest.raises(TimeError, match="network binding fields"):
            NetworkWindowBinding.from_dict(d)


class TestBindNetworkWindowRequiresV1Chain:
    """Ledger 3.2 — the construction site."""

    def test_v2_chain_cannot_bind_a_network_window(self):
        """PIN: closes when bind_network_window dispatches on generation."""
        from veritx_dse.wavee.network import bind_network_window
        evidence = {"stats": {"completion_time": 128, "delivered": 4}}
        with pytest.raises(KeyError):
            bind_network_window(
                evidence=evidence, chain=_v2_chain(),
                network_clock_hz=None, evidence_sha256="a" * 64)

    def test_v1_chain_binds_successfully(self):
        """The contrast case: the same call with a v1 chain works, so the
        failure above is the missing key and not a broken fixture."""
        from veritx_dse.wavee.network import bind_network_window
        evidence = {"stats": {"completion_time": 128, "delivered": 4}}
        chain = {
            "operation_graph_id": "sha256:" + "a" * 64,
            "physical_traffic_id": "sha256:" + "b" * 64,
            "backend_config_hash": "c" * 64,
            "backend_input_hash": "d" * 64,
        }
        binding, duration = bind_network_window(
            evidence=evidence, chain=chain, network_clock_hz=None,
            evidence_sha256="e" * 64)
        assert binding.operation_graph_id == chain["operation_graph_id"]
        assert duration == 128


class TestWaveEResultDerivationReadsV1Chain:
    """Ledger 3.4 — the caller in `_derive_wave_e_block`."""

    @staticmethod
    def _code() -> str:
        import inspect
        from veritx_dse.application.service import SrotaControlPlane
        return inspect.getsource(SrotaControlPlane._derive_wave_e_block)

    def test_derivation_still_reads_the_v1_parent_key(self):
        """PIN: closes when _derive_wave_e_block becomes generation-aware.

        Structural, because driving it needs a persisted v2 plan. It
        reads `chain["operation_graph_id"]` and merges backend hashes
        from the run, so on a v2 chain this raises KeyError during
        Wave-E result derivation — upstream of the binder itself.
        """
        code = self._code()
        assert 'chain["operation_graph_id"]' in code, (
            "the v1 parent read was removed; update ledger 3.4 and "
            "replace this pin with a behavioural test")


class TestWaveEResultVerifierComparesV1Parent:
    """Ledger 3.1 — the result-side comparison."""

    @staticmethod
    def _source_code() -> str:
        import inspect
        from veritx_dse.application import wave_e_resources as mod
        names = [n for n in dir(mod) if n.startswith("_verify")
                 or "wave_e" in n]
        chunks = []
        for name in names:
            obj = getattr(mod, name)
            if callable(obj) and getattr(obj, "__module__", "") == \
                    mod.__name__:
                try:
                    chunks.append(inspect.getsource(obj))
                except (OSError, TypeError):
                    pass
        return "\n".join(chunks)

    def test_v1_parent_comparison_site_still_exists(self):
        """PIN: closes when the comparison becomes generation-aware.

        This one is asserted structurally because driving it end to end
        requires a persisted v2 plan, which no writer emits yet. The
        ledger records the exact line; this test makes the removal
        mandatory rather than optional.
        """
        code = self._source_code()
        assert 'plan_wave_d["operation_graph_id"]' in code, (
            "the v1 parent comparison was removed; update ledger 3.1 and "
            "replace this pin with a generation-aware behavioural test")
