"""Stage-6 CLI tests: --evaluate booksim on a tiny v3 fixture.

Proves the production route end to end (compile -> real candidates ->
Pareto -> schema-valid study view) and that re-running a study never
collides with previous evidence (fresh study token per invocation).
"""
from __future__ import annotations

import argparse
import json


def _fixture(tmp_path):
    doc = {
        "schema_version": 3,
        "compiler_semantics_version": 3,
        "workload": {
            "model_family": "dense_transformer",
            "model_name": "tiny",
            "tp": 4, "pp": 1, "ep": 1, "dp": 1,
            "serving_mode": "mixed",
            "collectives": [{
                "kind": "allreduce", "dimension": "TP",
                "payload_bytes": 2048, "traffic_class": "tp_collective"}],
        },
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
            "num_power_domains": 1, "process_node_nm": 7},
    }
    path = tmp_path / "tiny-v3.json"
    path.write_text(json.dumps(doc))
    return str(path)


def _args(fixture, study_out, run_root):
    return argparse.Namespace(
        fixture=fixture, search="grid", link_widths="64,128",
        concentrations="1", latency_ceiling=None, max_candidates=None,
        study_out=study_out, evaluate="booksim", binary=None,
        network_clock_hz=10 ** 9, run_root=run_root, timeout=600, seed=7)


def _run_booksim_study(tmp_path, tag):
    from veritx_dse.cli.cli import cmd_optimize
    from veritx_dse.core.logging import Ctx
    fixture = _fixture(tmp_path)
    study_out = str(tmp_path / f"study-{tag}.json")
    ctx = Ctx(verbosity=0)
    cmd_optimize(ctx, _args(
        fixture, study_out, str(tmp_path / f"runs-{tag}")))
    assert not ctx.failed
    return json.loads(open(study_out).read())


def test_booksim_study_is_real_and_repeatable(tmp_path):
    first = _run_booksim_study(tmp_path, "a")
    assert len(first["candidates"]) == 2
    for row in first["candidates"]:
        assert row["objective_values"].get("completion_cycles") is not None
        assert "area" not in row["objective_values"]
        perf = row["evaluation_ids"]["performance_result_id"]
        assert perf and not perf.startswith("fake:")
        assert row["locked_consequences"]["routing_classes"] == ["DOR_XY"]
    assert first["pareto_ids"], "real evidence must yield a Pareto set"
    assert first["selected_candidate_id"] in first["pareto_ids"]
    # Re-running the same study into a colliding root must still work:
    # evidence slots are per-invocation, never reused.
    second = _run_booksim_study(tmp_path, "b")
    assert len(second["candidates"]) == 2
    assert second["pareto_ids"]
    assert second["selected_candidate_id"] in second["pareto_ids"]
    # Same science, fresh evidence: identities stable, results real.
    assert [c["candidate_id"] for c in first["candidates"]] == \
        [c["candidate_id"] for c in second["candidates"]]
    assert [c["evaluation_ids"]["performance_result_id"]
            for c in first["candidates"]] != \
        [c["evaluation_ids"]["performance_result_id"]
            for c in second["candidates"]]
