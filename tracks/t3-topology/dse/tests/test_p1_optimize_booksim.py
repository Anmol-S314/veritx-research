"""Stage-6 CLI tests: --evaluate booksim on a tiny v3 fixture.

Proves the production route end to end (compile -> real candidates ->
Pareto -> schema-valid study view) and that two invocations against the
SAME evidence root in the SAME second both succeed with distinct evidence
(run roots are per-invocation, never reused).
"""
from __future__ import annotations

import argparse
import hashlib
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


def _run_booksim_study(tmp_path, tag, run_root):
    from veritx_dse.cli.cli import cmd_optimize
    from veritx_dse.core.logging import Ctx
    fixture = _fixture(tmp_path)
    study_out = str(tmp_path / f"study-{tag}.json")
    ctx = Ctx(verbosity=0)
    cmd_optimize(ctx, _args(fixture, study_out, str(run_root)))
    assert not ctx.failed
    return json.loads(open(study_out).read())


def _evidence_digests(token_dir):
    """raw evidence digests (sha256 of each persisted evidence artifact)."""
    return sorted(
        hashlib.sha256(p.read_bytes()).hexdigest()
        for p in token_dir.rglob("evidence/*.json"))


def test_booksim_study_is_real_and_repeatable(tmp_path, monkeypatch):
    # Pin wall time so both invocations land in the SAME second: the test
    # must prove collision-freedom, not merely hope the clock ticked over.
    import datetime as _datetime

    class _FrozenDatetime(_datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2031, 1, 1, 0, 0, 0, tzinfo=tz)

    monkeypatch.setattr(_datetime, "datetime", _FrozenDatetime)
    shared_root = tmp_path / "runs"

    first = _run_booksim_study(tmp_path, "a", shared_root)
    assert len(first["candidates"]) == 2
    for row in first["candidates"]:
        assert row["objective_values"].get("completion_cycles") is not None
        assert "area" not in row["objective_values"]
        perf = row["evaluation_ids"]["performance_result_id"]
        assert perf and not perf.startswith("fake:")
        assert row["locked_consequences"]["routing_classes"] == ["DOR_XY"]
    assert first["pareto_ids"], "real evidence must yield a Pareto set"
    assert first["selected_candidate_id"] in first["pareto_ids"]

    # Re-run against the SAME base root in the SAME second: evidence slots
    # are per-invocation, never reused, so both runs must succeed.
    second = _run_booksim_study(tmp_path, "b", shared_root)
    assert len(second["candidates"]) == 2
    assert second["pareto_ids"]
    assert second["selected_candidate_id"] in second["pareto_ids"]

    # The shared root holds exactly two per-invocation roots: same
    # second+pid prefix, distinct monotonic counter suffix.
    tokens = sorted(p for p in shared_root.iterdir() if p.is_dir())
    assert len(tokens) == 2, [t.name for t in tokens]
    assert len({t.name.rsplit("-", 1)[0] for t in tokens}) == 1, \
        [t.name for t in tokens]
    assert tokens[0].name != tokens[1].name

    # Same science, fresh evidence: identities stable, results real, and
    # each run's persisted evidence digests are distinct.
    assert [c["candidate_id"] for c in first["candidates"]] == \
        [c["candidate_id"] for c in second["candidates"]]
    assert [c["evaluation_ids"]["performance_result_id"]
            for c in first["candidates"]] != \
        [c["evaluation_ids"]["performance_result_id"]
            for c in second["candidates"]]
    digests = [_evidence_digests(t) for t in tokens]
    assert digests[0] and digests[1], digests
    assert digests[0] != digests[1], digests
