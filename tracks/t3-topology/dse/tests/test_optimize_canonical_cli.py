"""Canonical ``veritx optimize`` CLI battery (replaces the retired P2
TestOptimizeCli block).

Covers the canonical surface only:

* the ``optimize`` subcommand is registered with the flags the
  canonical implementation owns;
* a missing input document fails closed (no study, no run slots, no
  simulator execution, no exception escape);
* a non-integral network clock refuses at the transport boundary;
* a live run produces a schema-valid study whose view hashes are
  ``sha256:``-prefixed while engine identities stay bare.

Live-BookSim determinism across invocations (identical science →
identical bytes) is proven by
tests/test_p1_optimize_booksim.py and is not repeated here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.cli import commands_optimize as co  # noqa: E402
from veritx_dse.core.logging import Ctx  # noqa: E402


def _args(fixture, study_out, run_root, **over):
    kw = dict(fixture=fixture, search="grid", link_widths="64,128",
              concentrations="1", latency_ceiling=None,
              max_candidates=None, study_out=study_out, evaluate="booksim",
              binary=None, network_clock_hz=10 ** 9, run_root=run_root,
              timeout=600, seed=7)
    kw.update(over)
    return argparse.Namespace(**kw)


def test_optimize_registered_with_canonical_flags():
    from veritx_dse.cli.cli import DISPATCH, build_parser
    assert DISPATCH["optimize"] is co.cmd_optimize
    args = build_parser().parse_args(
        ["optimize", "--fixture", "f.json", "--study-out", "s.json",
         "--run-root", "r", "--search", "grid",
         "--link-widths", "64,128", "--network-clock-hz", "1e9"])
    assert args.fixture == "f.json"
    assert args.study_out == "s.json"
    assert args.run_root == "r"
    assert args.search == "grid"
    assert args.link_widths == "64,128"
    assert args.network_clock_hz == "1e9"


def test_missing_fixture_fails_closed(tmp_path):
    """Missing input: no study, no run slots, no simulator execution."""
    study_out = tmp_path / "study.json"
    run_root = tmp_path / "runs"
    co.cmd_optimize(
        Ctx(verbosity=0),
        _args(str(tmp_path / "nope.json"), str(study_out),
              str(run_root)))
    assert not study_out.exists()
    assert not run_root.exists()


def test_nonintegral_clock_refuses_at_the_boundary(tmp_path):
    study_out = tmp_path / "study.json"
    run_root = tmp_path / "runs"
    co.cmd_optimize(
        Ctx(verbosity=0),
        _args("whatever.json", str(study_out), str(run_root),
              network_clock_hz="1.5"))
    assert not study_out.exists()
    assert not run_root.exists()


def test_clock_parsing_accepts_exact_forms():
    assert co._parse_clock_hz(None) is None
    assert co._parse_clock_hz(10 ** 9) == 10 ** 9
    assert co._parse_clock_hz("1000000000") == 10 ** 9
    assert co._parse_clock_hz("1e9") == 10 ** 9
    with pytest.raises(ValueError):
        co._parse_clock_hz("1.5")
    with pytest.raises(ValueError):
        co._parse_clock_hz("fast")
    with pytest.raises(ValueError):
        co._parse_clock_hz(-3)


def _tiny_fixture(path: Path) -> str:
    doc = {
        "schema_version": 3, "compiler_semantics_version": 3,
        "workload": {
            "model_family": "dense_transformer", "model_name": "tiny",
            "tp": 4, "pp": 1, "ep": 1, "dp": 1, "serving_mode": "mixed",
            "collectives": [{
                "kind": "allreduce", "dimension": "TP",
                "payload_bytes": 2048, "traffic_class": "tp_collective"}]},
        "requirements": [{
            "traffic_class": "tp_collective",
            "qos_class": "latency_critical",
            "latency_ceiling_cycles": 10 ** 9,
            "bandwidth_floor_gbps": None, "binding": True}],
        "agents": [{
            "kind": "compute_tile", "count": 4, "data_width": 256,
            "addr_width": 64, "protocol": "AXI",
            "clock_domain": None, "power_domain": None}],
        "dependencies": [],
        "noc_config": {
            "topology_family": "mesh", "radix": None,
            "concentration": 1, "arbitration": None,
            "rcu_enabled": None, "link_width": 64,
            "mcast_groups": None, "mcast_setup_cycles": None,
            "output_formats": ["json"], "obfuscation_level": 0},
        "address_map": {"ranges": []},
        "physical": {
            "clock_freq_mhz": 1000.0, "data_width": 256,
            "num_power_domains": 1, "process_node_nm": 7}}
    fixture = path / "tiny-v3.json"
    fixture.write_text(json.dumps(doc))
    return str(fixture)


def test_live_study_view_conventions(tmp_path):
    """Canonical CLI smoke: live run emits a prefixed-hash study view.

    View hashes crossing into the study are ``sha256:``-prefixed;
    engine identities stay bare. Pareto and selection follow the
    declared policy (no winner under selection=none is covered by the
    definition-identity battery).
    """
    from veritx_dse.core.paths import BOOKSIM_BIN
    if not Path(str(BOOKSIM_BIN)).is_file():
        pytest.skip("vendored BookSim binary not built")
    study_out = tmp_path / "study.json"
    co.cmd_optimize(
        Ctx(verbosity=0),
        _args(_tiny_fixture(tmp_path), str(study_out),
              str(tmp_path / "runs")))
    assert study_out.is_file()
    view = json.loads(study_out.read_text())
    assert view["contract_version"] == 2
    assert view["base_design_hash"].startswith("sha256:")
    assert len(view["candidates"]) == 2
    for row in view["candidates"]:
        assert row["evaluation_ids"]["design_hash"].startswith("sha256:")
        assert row["evaluation_status"] == "EVALUATED"
        assert row["objective_values"].get("completion_cycles") is not None
    assert view["pareto_ids"], "real evidence must yield a Pareto set"
    assert view["selected_candidate_id"] in view["pareto_ids"]
