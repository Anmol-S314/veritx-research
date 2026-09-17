"""Regression tests for bugs found during the Sep-2026 output audit.

Each test fails on the pre-fix code:
- trace replay flagged healthy runs unstable / lost packets / negative rates
- ranking used qtime-based plat means instead of honest latency
- pareto rejected canonical topology names (stale duplicate registry)
- `veritx run` printed "finished with errors" on success
"""
import importlib.util
import json
from argparse import Namespace
from pathlib import Path

import pytest

from veritx_dse.cli.cli import cmd_run, main
from veritx_dse.core.logging import Ctx
from veritx_dse.core.paths import REPO
from veritx_dse.model.presets import SWEEP_TOPOS, lookup_topo
from veritx_dse.simulation.booksim import build_config, run_booksim

TINY = "0 0 0 1 4\n100 1 0 2 4\n200 2 0 3 4\n300 3 0 0 4\n"  # cycle src cl dst size


@pytest.fixture()
def tiny_trace(tmp_path):
    p = tmp_path / "tiny.trace"
    p.write_text(TINY)
    return str(p)


def _eval(topo_name, trace):
    topo = lookup_topo(topo_name)
    cfg = build_config(topo, trace, sim_type="latency", seed=0)
    return run_booksim(Ctx(verbosity=0), cfg, repo_root=REPO, timeout=120,
                       label=f"regression-{topo_name}")


class TestTraceReplayInvariants:
    """End-to-end through the real binary: delivery, verdict, honest stats."""

    def test_delivers_every_packet_no_unstable(self, tiny_trace):
        res = _eval("mesh_4x4", tiny_trace)
        assert res.get("unstable", False) is False
        assert res.get("delivered") == 4
        assert "Trace replay complete" in res.get("drain_verdict", "")

    def test_torus_healthy_too(self, tiny_trace):
        res = _eval("torus_8x8", tiny_trace)
        assert res.get("unstable", False) is False
        assert res.get("delivered") == 4

    def test_honest_latency_present_and_sane(self, tiny_trace):
        res = _eval("mesh_4x4", tiny_trace)
        assert "honest_latency" in res
        # Honest (arrival - trace timestamp) must not exceed the qtime-based
        # plat mean, which inflates across idle gaps. Guards the parse.
        assert res["honest_latency"] <= res["latency"]
        assert res["honest_latency"] > 0


def _load_pareto_module():
    spec = importlib.util.spec_from_file_location(
        "mwp", str(Path(REPO) / "tracks/t3-topology/dse/veritx_dse/tools/multi_workload_pareto.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestParetoCanonicalCoverage:
    def test_resolves_every_sweep_topo(self):
        mod = _load_pareto_module()
        missing = [t.name for t in SWEEP_TOPOS if mod._lookup(t.name) is None]
        assert missing == []

    def test_gec_carries_vc_and_noc_flags(self):
        mod = _load_pareto_module()
        name, backend, params, routing = mod._lookup("gec_mecs_k8")
        assert backend == "gec" and routing == "dor"
        assert params["num_vcs"] >= params["d"] + 1
        assert params["use_noc_latency"] == 0

    def test_parse_lat_prefers_honest(self):
        mod = _load_pareto_module()
        out = ("Packet latency average = 31616.1\n"
               "\tp50 = 74.0\n\thonest_avg = 75.999\n")
        assert mod._parse_lat(out) == 75.999
        # pre-honest_avg binaries: plat fallback still works
        assert mod._parse_lat("Packet latency average = 42.3\n") == 42.3
        assert mod._parse_lat("no stats here") is None


class TestRunBanner:
    def test_success_says_complete(self, tmp_path, monkeypatch, capsys):
        monkeypatch.chdir(tmp_path)
        model = tmp_path / "m.json"
        model.write_text(json.dumps({"network": {"flow_classes": [{
            "name": "ar", "comm_type": "allreduce", "bytes_per_invocation": 512,
            "invocations_per_batch": 1,
            "instances": [{"participants": [0, 1, 2, 3]}]}]}}))
        args = Namespace(
            model=str(model), nodes=4, search="bo", iters=1, cert=None,
            scorer="analytical", timeout=120, timeout_s=None, quiet=False,
            verbose=False, json=False, output=None, log=None, seed=1,
            iterative_method="rho", max_edges=20)
        cmd_run(Ctx(verbosity=1), args)
        out = capsys.readouterr()
        combined = out.out + out.err
        assert "Pipeline complete" in combined
        assert "finished with errors" not in combined

    def test_spine_pass_legs_fail_is_partial_banner(
        self, tmp_path, monkeypatch, capsys
    ):
        """Spine (eval+cert) passing but an optional astra leg failing should
        print 'Pipeline complete (partial)' and never 'finished with errors'.

        Regression for the case where astra-sim timed out / timeloop was missing
        a shared library, yet the pipeline had a real BookSim latency and a
        passing cert — the banner should say partial, not failure.
        """
        monkeypatch.chdir(tmp_path)
        model = tmp_path / "m.json"
        model.write_text(json.dumps({"network": {"flow_classes": [{
            "name": "ar", "comm_type": "allreduce",
            "bytes_per_invocation": 512,
            "invocations_per_batch": 1,
            "instances": [{"participants": [0, 1, 2, 3]}]}]}}))
        args = Namespace(
            model=str(model), nodes=4, search="bo", iters=1, cert=None,
            scorer="analytical", timeout=120, timeout_s=None, quiet=False,
            verbose=False, json=False, output=None, log=None, seed=1,
            iterative_method="rho", max_edges=20)

        # Make the optional astra leg fail by returning an error dict (mirrors
        # the real _run_astra_leg contract: failures return {"error": ...}, they
        # do not raise).
        import veritx_dse.cli.cli as _cli_mod
        monkeypatch.setattr(
            _cli_mod, "_run_astra_leg",
            lambda ctx, run_dir, anynet_path, n_nodes, budget, **kw: {"error": "astra-sim timed out after 600s"},
        )

        # Make the spine's BookSim eval return a clean result for the tiny
        # 4-pkt trace, so only the optional leg fails.
        from veritx_dse.simulation.booksim import run_booksim as _real_run_booksim
        _clean = {"latency": 70.0, "hops": 3.2, "pkt_count": 4,
                  "delivered": 4, "drain_verdict": "Trace replay complete"}
        monkeypatch.setattr(
            "veritx_dse.simulation.booksim.run_booksim",
            lambda ctx, config, *, repo_root, timeout=60, label="BookSim", runner=None: dict(_clean),
        )

        cmd_run(Ctx(verbosity=1), args)
        out = capsys.readouterr()
        combined = out.out + out.err

        assert "Pipeline complete (partial)" in combined, combined
        assert "spine passed; one or both optional legs unavailable" in combined, combined
        assert "finished with errors" not in combined, combined

    def test_spine_pass_legs_fail_exits_zero_via_main(
        self, tmp_path, monkeypatch, capsys
    ):
        """End-to-end: main() should exit 0 when the spine passes even if an
        optional leg failed, because cmd_run returns 0 and main honors it over
        ctx.failed.

        Regression for the case where astra-sim timed out / timeloop was missing
        a shared library yet the pipeline had a real BookSim latency and a
        passing cert — the process exit should be 0, not 1.
        """
        monkeypatch.chdir(tmp_path)
        model = tmp_path / "m.json"
        model.write_text(json.dumps({"network": {"flow_classes": [{
            "name": "ar", "comm_type": "allreduce",
            "bytes_per_invocation": 512,
            "invocations_per_batch": 1,
            "instances": [{"participants": [0, 1, 2, 3]}]}]}}))

        # Force the spine's BookSim eval to a clean result.
        from veritx_dse.simulation.booksim import run_booksim as _real_run_booksim
        _clean = {"latency": 70.0, "hops": 3.2, "pkt_count": 4,
                  "delivered": 4, "drain_verdict": "Trace replay complete"}
        monkeypatch.setattr(
            "veritx_dse.simulation.booksim.run_booksim",
            lambda ctx, config, *, repo_root, timeout=60, label="BookSim", runner=None: dict(_clean),
        )
        # Force the optional astra leg to fail (return error dict, no raise).
        import veritx_dse.cli.cli as _cli_mod
        monkeypatch.setattr(
            _cli_mod, "_run_astra_leg",
            lambda ctx, run_dir, anynet_path, n_nodes, budget, **kw: {"error": "astra-sim timed out after 600s"},
        )

        import sys as _sys
        _exit_seen = []
        _orig_exit = _sys.exit
        def _capt_exit(code=0):
            _exit_seen.append(code)
            raise SystemExit(code)
        monkeypatch.setattr(_sys, "exit", _capt_exit)

        _argv = [
            "veritx", "run",
            "--model", str(model),
            "--nodes", "4",
            "--search", "bo",
            "--iters", "1",
            "--cert", "none",
            "--scorer", "analytical",
            "--timeout", "120",
        ]
        _saved_argv = _sys.argv
        _sys.argv = _argv
        try:
            main()
        except SystemExit as _se:
            _exit_seen.append(_se.code)
        finally:
            _sys.argv = _saved_argv

        assert _exit_seen and _exit_seen[-1] == 0, f"expected exit 0, got {_exit_seen}"
        out = capsys.readouterr()
        combined = out.out + out.err
        assert "Pipeline complete (partial)" in combined, combined
        assert "finished with errors" not in combined, combined
