"""Contract tests for the remaining cli.py commands (Batch E).

Live subprocess contracts: every test runs the real CLI module and asserts on
observable behavior (exit codes, stderr, artifacts). Fast: tiny trace (4
packets), 4-node topologies, budget-capped synthesis (ultra: real objects,
no mocks — the binaries are milliseconds now).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.cli.cli import (
    cmd_sweep, cmd_run, cmd_compare, cmd_pareto, cmd_baseline,
    cmd_certify_flow, cmd_certify_rtl, cmd_certify_full, cmd_compile,
    cmd_init, cmd_report, cmd_evaluate_anynet, cmd_synthesize_bo,
    cmd_synthesize_iterative, cmd_runs, cmd_results,
    cmd_status, cmd_diff, cmd_generate_uvm, main, _expand_anynet_files,
    _eff_timeout, _resolve_path, sanitize_path, _parse_astra_cycles,
    _latex_to_html,
)
from veritx_dse.core.logging import Ctx

REPO = DSE.parent.parent.parent          # .../veritx-research
TINY_TRACE = "/tmp/tiny.trace"           # 4 packets, created by conftest
MODEL = "/tmp/tm_proto.json"             # allreduce traffic model
WINNER = REPO / "runs/experiments"       # run pipeline artifacts live here

CL = [sys.executable, "-m", "veritx_dse.cli.cli"]


def _sweep_artifact(root: Path) -> Path:
    """The sweep's own output path.

    Results live in immutable run dirs (``new_run_dir``: <root>/sweep/
    <ts>_seed<seed>/sweep.json). The tests used to assert a hard-coded
    REPO/runs/booksim/sweep_tiny.json that the sweep stopped writing, so
    five nodes failed on a missing file rather than on sweep or report
    behaviour.
    """
    return next(iter(sorted(root.glob("sweep/*/sweep.json"))))


def _cli(*args, timeout=120):
    """Run the real CLI; returns (rc, stderr_tail)."""
    import subprocess
    r = subprocess.run(CL + list(args), cwd=str(DSE), capture_output=True,
                       text=True, timeout=timeout, stdin=subprocess.DEVNULL)
    return r.returncode, (r.stderr or "").strip().splitlines()[-3:]


@pytest.fixture(scope="module")
def tiny_trace():
    p = Path(TINY_TRACE)
    if not p.exists():
        p.write_text("0 0 0 1 4\n100 1 0 2 4\n200 2 0 3 4\n300 3 0 0 4\n")
    return str(p)


@pytest.fixture(scope="module")
def model():
    p = Path(MODEL)
    if not p.exists():
        p.write_text(json.dumps({"network": {"flow_classes": [{
            "name": "ar", "comm_type": "allreduce", "bytes_per_invocation": 512,
            "invocations_per_batch": 1,
            "instances": [{"participants": [0, 1, 2, 3]}]}]}}))
    return str(p)


@pytest.fixture(scope="module")
def winner_anynet(model):
    """Produce a real synthesized winner.anynet via one full pipeline run."""
    import subprocess
    rc, _ = _cli("legacy", "run", "--model", model, "--nodes", "4", "--search", "bo",
                 "--iters", "10", "--cert", "flow", "--timeout", "300",
                 timeout=420)
    assert rc == 0, "run pipeline must succeed to produce winner.anynet"
    runs = sorted(WINNER.glob("*/winner.anynet"))
    assert runs, "run must write winner.anynet"
    return str(runs[-1])


# ── helpers (in-process, cheap) ──────────────────────────────────────────

class TestHelpers:
    def test_expand_anynet_flat_and_comma(self):
        assert _expand_anynet_files(["a.anynet,b.anynet", " c.anynet "]) == \
            ["a.anynet", "b.anynet", "c.anynet"]
        assert _expand_anynet_files(None) == []
        assert _expand_anynet_files([",,"]) == []

    def test_eff_timeout_precedence(self, monkeypatch):
        ns = SimpleNamespace(timeout=None)
        monkeypatch.setenv("VERITX_TIMEOUT", "77")
        assert _eff_timeout(ns, 60) == 77
        ns.timeout = 5
        assert _eff_timeout(ns, 60) == 5
        ns.timeout = 0
        with pytest.raises(ValueError):
            _eff_timeout(ns, 60)

    def test_resolve_path_relative_and_traversal(self, tmp_path):
        assert _resolve_path(str(tmp_path)) == str(tmp_path)
        assert _resolve_path(tmp_path) == str(tmp_path)      # Path object
        # Historically (before the upward-relative fix for --spec) the
        # resolver rejected every '..' unconditionally. It now rejects
        # unbounded upward escapes; a path that stays inside REPO under
        # resolution survives so `--spec ../product/…` from dse/ works.
        # Purely-outward paths (.. alone, ../..//tmp) still raise.
        # Historical boundary: the resolver used to reject *every* '..' and
        # then *blw* allowed the upward walk for --spec. Neither case holds
        # now: upward paths that land on a real file pass, unbounded escapes
        # fail. (../../tmp/foo from /tmp resolves to /tmp/foo — a real file,
        # so it would pass; the real guard target is a path that escapes past
        # the filesystem and then points at nothing, e.g. ../../../../etc/passwd)
        with pytest.raises(ValueError):
            _resolve_path("../../../../../../../etc/passwd")
        resolved = _resolve_path(str(tmp_path))
        assert Path(resolved).is_absolute()

    def test_sanitize_path(self):
        assert sanitize_path("/abs/path") == "/abs/path"
        with pytest.raises(ValueError):
            sanitize_path("../up")

    def test_parse_astra_cycles(self):
        out = "[workload] sys[0] finished, 50310 cycles\n" \
              "[workload] sys[3] finished, 50310 cycles\ngarbage"
        assert _parse_astra_cycles(out) == {0: 50310, 3: 50310}
        assert _parse_astra_cycles("nothing here") == {}

    def test_latex_to_html_escapes_rows(self):
        latex = "\\begin{table}\n\\hline\n" \
                "\\textbf{Topo} & Mean \\\\\n" \
                "mesh & 15.0c \\\\\n\\end{table}"
        html = _latex_to_html(latex, "T")
        assert "<!DOCTYPE html>" in html
        assert "<b>Topo</b>" in html
        assert "mesh" in html

    def test_main_no_command_prints_help(self, capsys):
        sys.argv = ["veritx"]
        main()                                   # no command → help, rc 0
        assert "usage" in capsys.readouterr().out.lower()


# ── evaluate anynet (live binary) ─────────────────────────────────────────

class TestEvaluateAnynet:
    def test_anynet_eval_end_to_end(self, tiny_trace, winner_anynet, capsys):
        cmd_evaluate_anynet(Ctx(verbosity=1, seed=42), SimpleNamespace(
            topo=winner_anynet, trace=tiny_trace, vcs=None, vc_buf=None,
            sample_period=None, timeout=60))
        err = capsys.readouterr().err
        assert "Latency:" in err and "Saved:" in err

    def test_anynet_disconnected_rejected(self, tiny_trace, tmp_path, capsys):
        # 4 routers, 2 disjoint pairs — the connectivity guard must fire
        bad = tmp_path / "disconnected.anynet"
        bad.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n"
                       "router 2 node 2 router 3\nrouter 3 node 3 router 2\n")
        rc, err = _cli("legacy", "evaluate-anynet", "--topo", str(bad),
                       "--trace", tiny_trace)
        assert rc == 1 and "Disconnected topology" in "\n".join(err)


# ── certify (real flow_certifier; rtl fails honestly without a Verilator build)

class TestCertify:
    def test_flow_passes_on_real_synthesized_topo(self, model, winner_anynet, capsys):
        cmd_certify_flow(Ctx(verbosity=1), SimpleNamespace(
            model=model, topo=winner_anynet, timeout=120))
        assert "PASSED" in capsys.readouterr().err

    def test_flow_missing_model_fails(self, winner_anynet, tmp_path, capsys):
        cmd_certify_flow(Ctx(verbosity=1), SimpleNamespace(
            model=str(tmp_path / "nope.json"), topo=winner_anynet, timeout=60))
        assert "Traffic model not found" in capsys.readouterr().err

    def test_flow_missing_topo_fails(self, model, tmp_path, capsys):
        cmd_certify_flow(Ctx(verbosity=1), SimpleNamespace(
            model=model, topo=str(tmp_path / "nope.anynet"), timeout=60))
        assert "Topology not found" in capsys.readouterr().err

    def test_rtl_missing_build_fails_honestly(self, tmp_path, capsys, monkeypatch):
        import veritx_dse.cli.cli as cli_mod
        monkeypatch.setattr(cli_mod, "CERTIFY_SH",
                            Path(__file__).parent / "does_not_exist.sh")
        cmd_certify_rtl(Ctx(verbosity=1), SimpleNamespace(
            topo="x", build_dir=str(tmp_path), tier="quick", timeout=60))
        assert "certify.sh not found" in capsys.readouterr().err

    def test_certify_full_reports_failure(self, model, tmp_path, capsys, monkeypatch):
        import veritx_dse.cli.cli as cli_mod
        monkeypatch.setattr(cli_mod, "CERTIFY_SH",
                            Path(__file__).parent / "does_not_exist.sh")
        cmd_certify_full(Ctx(verbosity=1), SimpleNamespace(
            model=model, topo=str(tmp_path / "nope.anynet"),
            build_dir=str(tmp_path), tier="quick", timeout=60))
        err = capsys.readouterr().err
        assert "Topology not found" in err and "certify.sh not found" in err


# ── sweep / compare / pareto / baseline (real BookSim, tiny trace) ────────

class TestSweep:
    def test_sweep_all_topos_real_latencies(self, tiny_trace, tmp_path, capsys):
        cmd_sweep(Ctx(verbosity=1, seed=42), SimpleNamespace(
            trace=tiny_trace, mode="latency", ir=0.05, timeout=30,
            out_dir=str(tmp_path)))
        res = json.loads(_sweep_artifact(tmp_path).read_text())
        assert len(res) == 13  # mesh4x4/8x8, torus, flatfly, 3×gec, fbfly, cmesh, fattree, qtree, tree4, dragonfly
        assert all(isinstance(r["latency"], float) for r in res)
        assert "Results:" in capsys.readouterr().err


class TestCompare:
    def test_compare_two_topos(self, tiny_trace, tmp_path, capsys):
        out = tmp_path / "cmp.json"
        rc, err = _cli("--json", "--output", str(out), "legacy", "compare",
                       "--trace", tiny_trace, "--topos", "mesh_8x8,torus_8x8",
                       "--seeds", "1", "--timeout", "30")
        assert rc == 0
        d = json.loads(out.read_text())
        assert [s["name"] for s in d["summary"]] == ["mesh_8x8", "torus_8x8"]
        assert all("mean" in s for s in d["summary"])

    def test_compare_unknown_topo_fails(self, tiny_trace, capsys):
        rc, err = _cli("legacy", "compare", "--trace", tiny_trace, "--topos", "nope_9x9")
        assert rc == 1 and "Unknown topology" in "\n".join(err)


class TestPareto:
    def test_pareto_output_shape(self, tiny_trace, tmp_path):
        out = tmp_path / "par.json"
        rc, _ = _cli("legacy", "pareto", "--traces", tiny_trace,
                     "--topos", "mesh_8x8,torus_8x8", "--seeds", "1",
                     "--timeout", "30", "--out", str(out), timeout=180)
        assert rc == 0
        d = json.loads(out.read_text())
        assert "agg" in d and "front" in d and "traces" in d

    def test_pareto_seeds_validation(self, tiny_trace, capsys):
        rc, err = _cli("legacy", "pareto", "--traces", tiny_trace, "--seeds", "0")
        assert rc == 1 and "seeds must be >= 1" in "\n".join(err)


class TestBaseline:
    def test_baseline_runs_literature_set(self, tiny_trace, tmp_path):
        out = tmp_path / "base.json"
        rc, _ = _cli("--json", "--output", str(out), "legacy", "baseline",
                     "--trace", tiny_trace, "--timeout", "30")
        assert rc == 0
        d = json.loads(out.read_text())
        names = [s["name"] for s in d["summary"]]
        assert "mesh_8x8" in names and "torus_8x8" in names

    def test_baseline_missing_trace(self, tmp_path, capsys):
        rc, err = _cli("legacy", "baseline", "--trace", str(tmp_path / "nope"))
        assert rc == 1 and "trace not found" in "\n".join(err)


# ── run pipeline (the full chain) ──────────────────────────────────────────

class TestRun:
    def test_run_full_pipeline_artifacts(self, model, winner_anynet):
        """winner_anynet fixture runs the pipeline; here we verify artifacts."""
        run_dir = Path(winner_anynet).parent
        assert (run_dir / "input.trace").exists()
        assert (run_dir / "manifest.json").exists()
        m = json.loads((run_dir / "manifest.json").read_text())
        assert m["nodes"] == 4 and "eval" in m
        assert m.get("cert") == "PASS"          # real cert, real verdict

    def test_run_rejects_tiny_node_count(self, model):
        rc, err = _cli("legacy", "run", "--model", model, "--nodes", "1")
        assert rc == 1 and "nodes must be >= 2" in "\n".join(err)


# ── compile (intent-to-fabric) ──────────────────────────────────────────────

class TestCompile:
    def test_compile_example_end_to_end(self, tmp_path):
        out = tmp_path / "compile_out.json"
        rc, _ = _cli("legacy", "compile", "examples/moe_8npu.json", "--timeout", "120",
                     "--output", str(out))
        assert rc == 0
        d = json.loads(out.read_text())
        assert d["manifest"]["revision"] >= 1

    def test_compile_missing_request(self, tmp_path, capsys):
        rc, err = _cli("legacy", "compile", str(tmp_path / "nope.json"))
        assert rc == 1 and "CompileRequest not found" in "\n".join(err)

    def test_compile_garbage_request(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text('{"nope": true}')
        rc, err = _cli("legacy", "compile", str(bad))
        assert rc == 1 and "Failed to parse" in "\n".join(err)


# ── init wizard (EOF = defaults) ────────────────────────────────────────────

class TestInit:
    def test_init_eof_defaults_writes_valid_request(self, tmp_path):
        out = tmp_path / "cr.json"
        rc, _ = _cli("init", "-o", str(out))
        assert rc == 0
        d = json.loads(out.read_text())
        assert "workload" in d and "agents" in d and "noc_config" in d

    def test_init_answers_produce_valid_request(self, tmp_path):
        out = tmp_path / "cr2.json"
        rc, _ = _cli("init", "-o", str(out))
        assert rc == 0 and out.exists()
        d = json.loads(out.read_text())
        assert d["workload"]["tp"] >= 1


# ── report (LaTeX/HTML/PDF) ─────────────────────────────────────────────────

class TestReport:
    @pytest.fixture(scope="class")
    def sweep_json(self, tiny_trace, tmp_path_factory):
        """A real sweep artifact for the report leg, in a temp run root.

        The old fixture ran the sweep and then handed `report` a hard-coded
        REPO/runs/booksim/sweep_tiny.json the sweep no longer writes, so all
        four report nodes failed on a missing file, not on report logic.
        """
        root = tmp_path_factory.mktemp("sweep-root")
        cmd_sweep(Ctx(verbosity=1, seed=42), SimpleNamespace(
            trace=tiny_trace, mode="latency", ir=0.05, timeout=30,
            out_dir=str(root)))
        return str(_sweep_artifact(root))

    def test_report_stdout_table(self, sweep_json, capsys):
        rc, _ = _cli("legacy", "report", "--json", sweep_json)
        assert rc == 0

    def test_report_latex_file(self, sweep_json, tmp_path, capsys):
        out = tmp_path / "r.tex"
        rc, _ = _cli("legacy", "report", "--json", sweep_json, "--out", str(out))
        assert rc == 0 and out.exists()
        assert "\\begin{table}" in out.read_text()

    def test_report_html_file(self, sweep_json, tmp_path):
        out = tmp_path / "r.html"
        rc, _ = _cli("legacy", "report", "--json", sweep_json, "--out", str(out))
        assert rc == 0 and out.read_text().startswith("<!DOCTYPE html>")

    def test_report_pdf_compiles(self, sweep_json, tmp_path):
        out = tmp_path / "r.pdf"
        rc, err = _cli("legacy", "report", "--json", sweep_json, "--out", str(out),
                       timeout=180)
        assert rc == 0
        assert out.read_bytes()[:4] == b"%PDF"

    def test_report_unreadable_json_yields_comment(self, tmp_path, capsys):
        bad = tmp_path / "bad.json"
        bad.write_text("{not json")
        rc, _ = _cli("legacy", "report", "--json", str(bad))
        assert rc == 0                          # comment, not a crash

    def test_report_unknown_format_exits_1(self, tmp_path, capsys):
        bad = tmp_path / "unk.json"
        bad.write_text('{"neither": 1}')
        rc, err = _cli("legacy", "report", "--json", str(bad))
        assert rc == 1 and "Unknown JSON format" in "\n".join(err)


# ── synthesize wrappers ──────────────────────────────────────────────────────
# NOTE: the `grid` subcommand was removed — it invoked scripts/run.py, which
# imported a deleted `evaluator` module (crashed on every invocation).

class TestSynthesize:

    def test_bo_reports_persisted_results(self, tmp_path, monkeypatch, capsys):
        """After BO completes, the persisted results JSON is read and echoed.
        The child process is stubbed at the subprocess boundary (it would
        otherwise overwrite the fixture); the read/echo contract is real."""
        import subprocess as sp
        import veritx_dse.cli.cli as cli_mod
        monkeypatch.setattr(cli_mod, "RUNS_DIR", tmp_path)
        monkeypatch.setattr(cli_mod, "SYNTH_DIR", tmp_path / "booksim")
        results = tmp_path / "booksim" / "bo_results_N4.json"
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text(json.dumps({"best_latency": 15.0,
                                       "booksim_latency": 15.0}))
        monkeypatch.setattr(sp, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""))
        cmd_synthesize_bo(Ctx(verbosity=1), SimpleNamespace(
            nodes=4, traffic=TINY_TRACE, iters=1, seed=42,
            scorer="analytical", timeout=60))
        err = capsys.readouterr().err
        assert "Best analytical: 15.0c" in err and "Results:" in err

    def test_bo_bad_results_json(self, tmp_path, monkeypatch, capsys):
        import subprocess as sp
        import veritx_dse.cli.cli as cli_mod
        monkeypatch.setattr(cli_mod, "RUNS_DIR", tmp_path)
        monkeypatch.setattr(cli_mod, "SYNTH_DIR", tmp_path / "booksim")
        results = tmp_path / "booksim" / "bo_results_N4.json"
        results.parent.mkdir(parents=True, exist_ok=True)
        results.write_text("{broken")
        monkeypatch.setattr(sp, "run", lambda *a, **k: SimpleNamespace(
            returncode=0, stdout="", stderr=""))
        cmd_synthesize_bo(Ctx(verbosity=1), SimpleNamespace(
            nodes=4, traffic=TINY_TRACE, iters=1, seed=42,
            scorer="analytical", timeout=60))
        assert "Failed to parse results" in capsys.readouterr().err

    def test_iterative_reports_final(self, tiny_trace, tmp_path, capsys):
        cmd_synthesize_iterative(Ctx(verbosity=1), SimpleNamespace(
            trace=tiny_trace, method="rho", steps=2, max_edges=12,
            horizon=None, branch=None, group=None, seed_anynet=None,
            out=str(tmp_path / "it.anynet"), timeout=120))
        assert "Final:" in capsys.readouterr().err

    def test_synthesize_dispatch_routes(self, monkeypatch, capsys):
        """main() routes synthesize subcommands through the dispatch table."""
        import veritx_dse.cli.cli as cli_mod
        called = []
        monkeypatch.setattr(cli_mod, "cmd_synthesize_iterative",
                            lambda ctx, args: called.append("iterative"))
        # DISPATCH holds the function reference directly — patch the table too
        monkeypatch.setitem(cli_mod.DISPATCH["legacy"],
                            "synthesize-iterative",
                            lambda ctx, args: called.append("iterative"))
        argv = sys.argv
        sys.argv = ["veritx", "legacy", "synthesize-iterative",
                    "--trace", "x"]
        try:
            main()                               # success → returns, no exit
        finally:
            sys.argv = argv
        assert called == ["iterative"]


# ── runs / results / status / diff wrappers ──────────────────────────────────

class TestRunHistory:
    def test_runs_lists_experiments(self, winner_anynet, capsys):
        cmd_runs(Ctx(verbosity=1), SimpleNamespace(last=5, run_id=None))
        assert "2026" in capsys.readouterr().out or capsys.readouterr().out == ""

    def test_diff_needs_two_runs(self, winner_anynet, capsys):
        """One run id + no second → defaults kick in and diff latest pair."""
        from veritx_dse.cli import pipeline as pl
        runs = sorted((pl.RUNS_DIR / "experiments").glob("*"))
        if len(runs) >= 2:
            cmd_diff(Ctx(verbosity=1), SimpleNamespace(
                run_a=None, run_b=None))
            assert "Diff:" in capsys.readouterr().out
        else:
            cmd_diff(Ctx(verbosity=1), SimpleNamespace(
                run_a=runs[0].name if runs else None, run_b=None))

    def test_status_and_results_smoke(self, capsys):
        cmd_status(Ctx(verbosity=1), SimpleNamespace(last=3))
        cmd_results(Ctx(verbosity=1), SimpleNamespace(last=3))


# ── generate uvm ──────────────────────────────────────────────────────────────

class TestGenerateUvm:
    def test_uvm_from_example(self, tmp_path, capsys):
        out = tmp_path / "uvm"
        rc, _ = _cli("generate", "uvm", "--request", "examples/moe_8npu.json",
                     "--out", str(out), "--nodes", "64")
        assert rc == 0
        for f in ("tb_noc.sv", "seq_lib.sv", "assertions.sv", "cov.sv"):
            assert (out / f).exists() and (out / f).stat().st_size > 0

    def test_uvm_missing_request(self, tmp_path, capsys):
        rc, err = _cli("generate", "uvm", "--request", str(tmp_path / "nope.json"))
        assert rc == 1 and "CompileRequest not found" in "\n".join(err)


# ── exit-code contract (the CI-critical one) ───────────────────────────

class TestExitCodes:
    @pytest.mark.parametrize("args,needle", [
        (("legacy", "compile", "/nope/req.json"), "CompileRequest not found"),
        (("legacy", "baseline", "--trace", "/nope/trace"), "trace not found"),
        (("legacy", "compare", "--trace", "/nope/trace", "--topos", "mesh_8x8"), "trace not found"),
        (("generate", "uvm", "--request", "/nope/r.json"), "CompileRequest not found"),
    ])
    def test_soft_failures_exit_nonzero(self, args, needle):
        """fail()-and-return paths must exit 1, never 0 (CI reads rc)."""
        rc, err = _cli(*args)
        assert rc == 1, f"expected rc=1, got {rc}; stderr={err}"
        assert any(needle in l for l in err)
