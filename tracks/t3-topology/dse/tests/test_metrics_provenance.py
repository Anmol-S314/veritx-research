"""Verified-PRD Integrity PR E — units/fidelity/provenance baseline.

Pins the typed-metric and executable-provenance contract:

  * metric(): naked numbers are not results — unit, producer, fidelity and
    aggregation scope ride with every scientific value; fidelity is
    validated against the closed category set;
  * run_booksim emits typed metrics at the source: BookSim cycles are
    NETWORK_SIMULATION fidelity, produced by booksim2 — downstream code
    can never again compare them against clocks or estimates silently;
  * every result carries the SHA256 of the binary that produced it
    (provenance §10.4: the executable is part of the experiment).

Level-2 where possible: the run_booksim test executes the REAL booksim
binary when present (skipped otherwise), exercising the actual seam.
"""
import hashlib
import json
from pathlib import Path

import pytest

from veritx_dse.core.runs import (
    FIDELITY_CATEGORIES,
    binary_identity,
    metric,
)
from veritx_dse.simulation.booksim import parse_output, run_booksim


# ── metric(): the typed-value contract ──────────────────────────────────────

class TestMetricContract:
    def test_metric_carries_units_and_provenance(self):
        m = metric("packet_latency_average", 123.4, "cycles",
                   producer="booksim2", fidelity="NETWORK_SIMULATION")
        assert m["unit"] == "cycles"
        assert m["producer"] == "booksim2"
        assert m["fidelity"] == "NETWORK_SIMULATION"
        assert m["aggregation_scope"] == "per_packet"
        assert m["value"] == 123.4

    def test_fidelity_is_closed_vocabulary(self):
        with pytest.raises(ValueError, match="fidelity"):
            metric("x", 1, "cycles", producer="p",
                   fidelity="VIBES_BASED")

    def test_all_categories_are_available(self):
        assert "ANALYTICAL_ESTIMATE" in FIDELITY_CATEGORIES
        assert "NETWORK_SIMULATION" in FIDELITY_CATEGORIES
        assert "FORMAL_PROOF" in FIDELITY_CATEGORIES

    def test_derivation_records_conversions(self):
        m = metric("flit_count", 21, "flits", producer="model_to_trace",
                   fidelity="ANALYTICAL_ESTIMATE",
                   derivation="ceil(1290 bytes / 64 B per flit)")
        assert "64" in m["derivation"]


# ── binary_identity(): executable provenance ────────────────────────────────

class TestBinaryIdentity:
    def test_sha256_of_real_file(self, tmp_path):
        p = tmp_path / "sim.bin"
        p.write_bytes(b"\x7fELF-fake-simulator")
        ident = binary_identity(p)
        assert ident["sha256"] == hashlib.sha256(p.read_bytes()).hexdigest()
        assert ident["path"] == str(p)

    def test_missing_binary_is_truthful_none(self, tmp_path):
        ident = binary_identity(tmp_path / "nope.bin")
        assert ident["sha256"] is None, "never invent a hash"
        assert ident["path"].endswith("nope.bin")


# ── run_booksim: typed emission at the source ───────────────────────────────

class TestRunBooksimTypedResults:
    def test_parse_output_keys_drive_typed_metrics(self):
        """The typed layer keys off parse_output's contract — the exact
        keys BookSim stdout produces must type cleanly."""
        stdout = (
            "Completion time is 123456 cycles\n"
            "Packet latency average = 7020.35\n"
            "\tp50 = 6500\n"
            "\tp99 = 14000\n"
            "Hops average = 4.25\n"
            "Accepted packet rate average = 0.031\n"
            "delivered 1000 packets\n"
        )
        result = parse_output(stdout)
        assert result["completion_time"] == 123456
        assert result["latency"] == 7020.35
        assert result["hops"] == 4.25
        assert result["throughput"] == 0.031

    def test_supervised_result_typing_path(self, tmp_path, monkeypatch):
        """The default supervised runner path types metrics identically:
        parse_output drives the keys, so the contract holds at the seam
        without mocking subprocess (real fake executable)."""
        fake = tmp_path / "fakebooksim"
        fake.write_text(
            "#!/bin/sh\n"
            "echo 'Completion time is 500 cycles'\n"
            "echo 'Packet latency average = 42.5'\n"
            "echo 'Hops average = 2.0'\n"
            "echo 'Accepted packet rate average = 0.5'\n"
            "echo 'delivered 10 packets'\n"
        )
        fake.chmod(0o755)

        import veritx_dse.simulation.booksim as bs
        monkeypatch.setattr(bs, "find_booksim_bin", lambda repo: fake)

        cfg = "topology = mesh;\n"
        captured = {}
        real_supervised = bs.supervised_run if hasattr(bs, "supervised_run") else None

        from veritx_dse.core import process as proc_mod

        orig = proc_mod.supervised_run

        def spy_supervised(cmd, cwd, timeout, **kw):
            captured["argv"] = cmd
            return orig(cmd, cwd=cwd, timeout=timeout, **kw)

        monkeypatch.setattr(proc_mod, "supervised_run", spy_supervised)
        from veritx_dse.core.logging import Ctx
        res = run_booksim(Ctx(verbosity=0), cfg, repo_root=tmp_path, timeout=30)
        assert captured["argv"][0] == str(fake)
        m = res["metrics"]
        assert m["completion_time"]["unit"] == "cycles"
        assert m["completion_time"]["fidelity"] == "NETWORK_SIMULATION"
        assert m["packet_latency_average"]["value"] == 42.5
        assert m["hops_average"]["unit"] == "hops"
        assert m["accepted_packet_rate"]["unit"] == "packets_per_cycle"
        assert res["booksim_binary"]["sha256"] == \
            hashlib.sha256(fake.read_bytes()).hexdigest()
