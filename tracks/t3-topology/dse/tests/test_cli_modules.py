"""Unit tests for veritx_dse refactored modules.

Tests are isolated — no BookSim binary, no network, no side effects.
Run: pytest test_cli_modules.py -v
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from textwrap import dedent

import pytest

# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_trace(tmp_path):
    """Create a minimal valid trace file."""
    trace = tmp_path / "test.trace"
    trace.write_text(dedent("""\
        # Test trace
        100 0 0 1 8
        101 0 0 2 8
        102 1 0 0 8
        200 2 0 3 8
        201 3 0 0 8
        1000 0 1 4 8
        1001 1 1 5 8
    """))
    return str(trace)


@pytest.fixture
def tmp_multiclass_trace(tmp_path):
    """Trace with multiple classes."""
    trace = tmp_path / "mc.trace"
    trace.write_text(dedent("""\
        # Multi-class trace
        100 0 0 1 8
        101 0 1 2 8
        102 1 0 0 8
        200 2 1 3 8
    """))
    return str(trace)


@pytest.fixture
def ctx(tmp_path):
    """Minimal Ctx for testing."""
    from veritx_dse.core.logging import Ctx
    return Ctx(verbosity=0, log_file=str(tmp_path / "test.log"))


# ── Logging tests ───────────────────────────────────────────────────────────

class TestCtx:
    def test_default_verbosity(self):
        from veritx_dse.core.logging import Ctx
        c = Ctx()
        assert c.verbosity == 1
        assert c.json_mode is False

    def test_log_file_created(self, tmp_path):
        from veritx_dse.core.logging import Ctx
        log_path = tmp_path / "test.log"
        c = Ctx(log_file=str(log_path))
        assert log_path.exists()
        c.close()

    def test_log_functions_dont_crash(self, ctx):
        from veritx_dse.core.logging import log, ok, fail, verbose, debug, banner, output
        log(ctx, "test")
        ok(ctx, "test")
        fail(ctx, "test")
        verbose(ctx, "test")
        debug(ctx, "test")
        banner(ctx, "Test")
        output(ctx, {"key": "value"})

    def test_json_mode(self, tmp_path, capsys):
        from veritx_dse.core.logging import Ctx, output
        c = Ctx(json_mode=True)
        output(c, {"result": 42})
        captured = capsys.readouterr()
        assert '"result": 42' in captured.out

    def test_log_file_append(self, tmp_path):
        from veritx_dse.core.logging import Ctx, log
        log_path = tmp_path / "test.log"
        c = Ctx(log_file=str(log_path))
        log(c, "first")
        log(c, "second")
        c.close()
        lines = log_path.read_text().strip().splitlines()
        assert len(lines) >= 3  # START + first + second


# ── Presets tests ───────────────────────────────────────────────────────────

class TestTopology:
    def test_mesh_edge_count(self):
        from veritx_dse.model.presets import Topology
        t = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
        assert t.edges() == 128  # 2 * 8^2 = 128

    def test_torus_same_as_mesh(self):
        from veritx_dse.model.presets import Topology
        t = Topology("torus_8x8", "torus", "dim_order", {"k": 8, "n": 2})
        assert t.edges() == 128

    def test_flatfly_edge_count(self):
        from veritx_dse.model.presets import Topology
        t = Topology("ff", "flatfly", "ran_min", {"k": 4, "n": 2, "c": 4})
        edges = t.edges()
        assert edges > 0

    def test_gec_edge_count(self):
        from veritx_dse.model.presets import Topology
        t = Topology("gec", "gec", "dor", {"k": 8, "c": 1, "o": 7, "d": 1})
        edges = t.edges()
        # mesh_edges = 2*8*7 = 112, express = 7*64 = 448, total = 560
        assert edges == 560

    def test_lookup_by_name(self):
        from veritx_dse.model.presets import lookup_topo
        t = lookup_topo("mesh_8x8")
        assert t is not None
        assert t.backend == "mesh"

    def test_lookup_by_backend(self):
        from veritx_dse.model.presets import lookup_topo
        t = lookup_topo("mesh")
        assert t is not None
        assert t.backend == "mesh"

    def test_lookup_unknown(self):
        from veritx_dse.model.presets import lookup_topo
        assert lookup_topo("nonexistent") is None

    def test_make_anynet_topo(self, tmp_path):
        from veritx_dse.model.presets import make_anynet_topo
        anynet = tmp_path / "test.anynet"
        anynet.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
        t = make_anynet_topo(str(anynet))
        assert t.backend == "anynet"
        assert t.routing == "min"

    def test_count_anynet_edges(self, tmp_path):
        from veritx_dse.model.presets import count_anynet_edges
        anynet = tmp_path / "test.anynet"
        anynet.write_text(dedent("""\
            router 0 node 0 router 1 router 2
            router 1 node 1 router 0 router 2
            router 2 node 2 router 0 router 1
        """))
        nodes, edges = count_anynet_edges(str(anynet))
        assert nodes == 3
        assert edges == 3  # triangle

    def test_sweep_topos_count(self):
        from veritx_dse.model.presets import SWEEP_TOPOS
        assert len(SWEEP_TOPOS) >= 7  # mesh, torus, flatfly, 3 GEC variants

    def test_dense_presets_exist(self):
        from veritx_dse.model.presets import DENSE_PRESETS
        assert "llama70b_ring" in DENSE_PRESETS
        assert "qwen3_moe" in DENSE_PRESETS


# ── Booksim config tests ───────────────────────────────────────────────────

class TestBookSimConfig:
    def test_mesh_config_has_required_params(self, tmp_trace):
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
        cfg = build_config(topo, tmp_trace)
        assert "topology = mesh;" in cfg
        assert "k = 8;" in cfg
        assert "n = 2;" in cfg
        assert "wait_for_tail_credit = 1;" in cfg
        assert "sim_type = latency;" in cfg
        assert "latency_thres = 1000000.0;" in cfg

    def test_config_no_classes_param(self, tmp_trace):
        """CRITICAL: 'classes' must never appear as a standalone param — it inflates latency 75x."""
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
        cfg = build_config(topo, tmp_trace)
        # Check no line starts with 'classes' (avoids matching 'vc_allocator')
        for line in cfg.splitlines():
            stripped = line.strip()
            assert not stripped.startswith('classes'), f"Found 'classes' param: {stripped}"

    def test_gec_config_has_noc_latency_zero(self, tmp_trace):
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("gec", "gec", "dor", {"k": 8, "c": 1, "o": 7, "d": 1},
                        needs_noc_latency_zero=True)
        cfg = build_config(topo, tmp_trace)
        assert "use_noc_latency = 0;" in cfg
        assert "routing_delay = 1;" in cfg

    def test_gec_mece_increases_vcs(self, tmp_trace):
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("gec", "gec", "dor", {"k": 8, "c": 1, "o": 1, "d": 7},
                        needs_noc_latency_zero=True)
        cfg = build_config(topo, tmp_trace)
        assert "num_vcs = 8;" in cfg  # d=7, so num_vcs=8

    def test_anynet_config_has_network_file(self, tmp_path, tmp_trace):
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        anynet = tmp_path / "test.anynet"
        anynet.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
        topo = Topology("test", "anynet", "min", {"network_file": str(anynet)})
        cfg = build_config(topo, tmp_trace)
        assert "topology = anynet;" in cfg
        assert f"network_file = {anynet};" in cfg

    def test_throughput_mode_config(self, tmp_trace):
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
        cfg = build_config(topo, tmp_trace, sim_type="throughput", ir=0.1)
        assert "uniform(0.1);" in cfg
        assert "sim_type = throughput;" in cfg

    def test_k_n_before_topology(self, tmp_trace):
        """CRITICAL: k and n MUST come before topology= in config."""
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
        cfg = build_config(topo, tmp_trace)
        k_pos = cfg.index("k = 8;")
        topo_pos = cfg.index("topology = mesh;")
        assert k_pos < topo_pos, "k must come before topology"

    def test_seed_in_config(self, tmp_trace):
        from veritx_dse.simulation.booksim import build_config
        from veritx_dse.model.presets import Topology
        topo = Topology("mesh_8x8", "mesh", "min_adapt", {"k": 8, "n": 2})
        cfg = build_config(topo, tmp_trace, seed=42)
        assert "seed = 42;" in cfg


# ── Trace stats tests ──────────────────────────────────────────────────────

class TestTraceStats:
    def test_detect_basic(self, tmp_trace):
        from veritx_dse.simulation.booksim import detect_trace_stats
        stats = detect_trace_stats(tmp_trace)
        assert stats.num_packets == 7
        assert stats.num_srcs == 4
        assert stats.max_cycle == 1001
        assert stats.ir > 0

    def test_detect_multiclass(self, tmp_multiclass_trace):
        from veritx_dse.simulation.booksim import detect_trace_stats
        stats = detect_trace_stats(tmp_multiclass_trace)
        assert stats.num_classes == 2
        assert stats.num_packets == 4

    def test_detect_empty_trace(self, tmp_path):
        from veritx_dse.simulation.booksim import detect_trace_stats
        trace = tmp_path / "empty.trace"
        trace.write_text("# empty\n")
        stats = detect_trace_stats(str(trace))
        assert stats.num_packets == 0

    def test_detect_nonexistent(self):
        from veritx_dse.simulation.booksim import detect_trace_stats
        stats = detect_trace_stats("/nonexistent/file.trace")
        assert stats.num_packets == 0


# ── Trace validate tests ───────────────────────────────────────────────────

class TestValidateTrace:
    def test_valid_trace(self, tmp_trace):
        from veritx_dse.simulation.traces import validate_trace
        result = validate_trace(tmp_trace)
        assert result.valid
        assert result.packets == 7
        assert len(result.errors) == 0

    def test_nonexistent_trace(self):
        from veritx_dse.simulation.traces import validate_trace
        result = validate_trace("/nonexistent/file.trace")
        assert not result.valid
        assert "Not found" in result.errors[0]

    def test_self_loop_detection(self, tmp_path):
        from veritx_dse.simulation.traces import validate_trace
        trace = tmp_path / "selfloop.trace"
        trace.write_text(dedent("""\
            100 0 0 0 8
            101 0 0 0 8
            102 0 0 0 8
            103 0 0 0 8
            104 0 0 0 8
            105 0 0 0 8
            106 0 0 0 8
            107 0 0 0 8
            108 0 0 0 8
            109 0 0 0 8
            110 0 0 0 8
        """))
        result = validate_trace(str(trace))
        assert result.self_loops == 11
        assert any("self-loop" in w for w in result.warnings)

    def test_short_lines(self, tmp_path):
        from veritx_dse.simulation.traces import validate_trace
        trace = tmp_path / "bad.trace"
        trace.write_text("100 0 0\n101 0 0 1 8\n")
        result = validate_trace(str(trace))
        assert not result.valid
        assert any(">=5 fields" in e for e in result.errors)


# ── Trace extract tests ────────────────────────────────────────────────────

class TestTraceExtract:
    def test_extract_burst(self, tmp_trace, tmp_path):
        from veritx_dse.simulation.traces import extract_burst
        out = str(tmp_path / "burst.trace")
        result = extract_burst(tmp_trace, 3, out)
        assert result.packets == 3
        assert result.mode == "burst"
        # Check times shifted to 0
        lines = Path(out).read_text().strip().splitlines()
        assert lines[0].startswith("0 ")

    def test_extract_uniform(self, tmp_trace, tmp_path):
        from veritx_dse.simulation.traces import extract_uniform
        out = str(tmp_path / "uniform.trace")
        result = extract_uniform(tmp_trace, out)
        assert result.packets == 7
        assert result.mode == "uniform"
        assert result.spacing > 0

    def test_extract_burst_count(self, tmp_trace, tmp_path):
        from veritx_dse.simulation.traces import extract_burst
        out = str(tmp_path / "burst.trace")
        result = extract_burst(tmp_trace, 2, out)
        lines = Path(out).read_text().strip().splitlines()
        assert len(lines) == 2


# ── Trace slice tests ──────────────────────────────────────────────────────

class TestTraceSlice:
    def test_slice_single_class(self, tmp_multiclass_trace, tmp_path):
        from veritx_dse.simulation.traces import slice_trace
        out = str(tmp_path / "sliced.trace")
        result = slice_trace(tmp_multiclass_trace, {0}, out)
        assert result.kept == 2
        assert result.dropped == 2

    def test_slice_with_renumber(self, tmp_multiclass_trace, tmp_path):
        from veritx_dse.simulation.traces import slice_trace
        out = str(tmp_path / "sliced.trace")
        result = slice_trace(tmp_multiclass_trace, {0, 1}, out, renumber=True)
        assert result.kept == 4
        # All classes should be 0 after renumber
        content = Path(out).read_text()
        for line in content.strip().splitlines():
            if line.startswith("#"):
                continue
            parts = line.split()
            assert parts[2] == "0"


# ── Parse output tests ─────────────────────────────────────────────────────

class TestParseOutput:
    def test_parse_latency(self):
        from veritx_dse.simulation.booksim import parse_output
        stdout = "Packet latency average = 23.45\nHops average = 3.2\nAccepted packet rate average = 0.05"
        result = parse_output(stdout)
        assert result["latency"] == 23.45
        assert result["hops"] == 3.2
        assert result["throughput"] == 0.05

    def test_parse_empty(self):
        from veritx_dse.simulation.booksim import parse_output
        result = parse_output("")
        assert "latency" not in result

    def test_parse_partial(self):
        from veritx_dse.simulation.booksim import parse_output
        result = parse_output("Packet latency average = 100.0")
        assert result["latency"] == 100.0
        assert "hops" not in result


# ── CLI fail-fast fixes: --anynet handling, dead --nodes, --burst guard ──────

class TestExpandAnynetFiles:
    def test_comma_split(self):
        from veritx_dse.cli.cli import _expand_anynet_files
        assert _expand_anynet_files(["a.anynet,b.anynet"]) == [
            "a.anynet", "b.anynet"]

    def test_repeatable(self):
        from veritx_dse.cli.cli import _expand_anynet_files
        assert _expand_anynet_files(["a.anynet", "b.anynet"]) == [
            "a.anynet", "b.anynet"]

    def test_mixed_and_blanks(self):
        from veritx_dse.cli.cli import _expand_anynet_files
        assert _expand_anynet_files(["a.anynet, b.anynet", "", "c.anynet"]
                                    ) == ["a.anynet", "b.anynet", "c.anynet"]

    def test_none_and_empty(self):
        from veritx_dse.cli.cli import _expand_anynet_files
        assert _expand_anynet_files(None) == []
        assert _expand_anynet_files([]) == []


class TestCompareAnynetFailFast:
    def _ns(self, trace, anynet):
        from argparse import Namespace
        return Namespace(trace=trace, dense=None, topos="mesh_4x4",
                         anynet=anynet, seeds=1, seed_base=0, timeout=60,
                         mode="latency", ir=0.05, memory=False,
                         sensitivity=None)

    def test_missing_anynet_aborts_without_sim(self, ctx, tmp_trace):
        from unittest.mock import patch
        from veritx_dse.cli.cli import cmd_compare
        with patch("veritx_dse.cli.cli.run_compare") as rc:
            cmd_compare(ctx, self._ns(tmp_trace, ["/nonexistent/a.anynet"]))
            rc.assert_not_called()
        log = open(ctx.log_file).read()
        assert "Aborting compare" in log

    def test_comma_anynet_missing_aborts(self, ctx, tmp_trace):
        from unittest.mock import patch
        from veritx_dse.cli.cli import cmd_compare
        with patch("veritx_dse.cli.cli.run_compare") as rc:
            cmd_compare(ctx, self._ns(tmp_trace, ["a.anynet,b.anynet"]))
            rc.assert_not_called()

    def test_existing_anynet_reaches_sim(self, ctx, tmp_path, tmp_trace):
        from unittest.mock import patch, MagicMock
        from veritx_dse.cli.cli import cmd_compare
        af = tmp_path / "t.anynet"
        af.write_text("router 0 node 0 router 1\nrouter 1 node 1 router 0\n")
        fake = MagicMock()
        fake.to_dict.return_value = {}
        with patch("veritx_dse.cli.cli.run_compare", return_value=fake) as rc:
            cmd_compare(ctx, self._ns(tmp_trace, [str(af)]))
            rc.assert_called_once()
        specs = rc.call_args[0][2]
        assert [s[0] for s in specs] == ["mesh_4x4", "t"]


class TestIterativeNodesRemoved:
    def test_nodes_flag_rejected(self):
        from veritx_dse.cli.cli import build_parser
        import pytest
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["synthesize", "iterative", "--trace", "x",
                               "--nodes", "8"])

    def test_timeout_flag_accepted(self):
        from veritx_dse.cli.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["synthesize", "iterative", "--trace", "x",
                                  "--timeout", "120"])
        assert args.timeout == 120
        args = parser.parse_args(["synthesize", "bo", "--traffic", "x"])
        assert args.timeout is None  # unset → VERITX_TIMEOUT env or builtin
        args = parser.parse_args(["certify", "flow", "--model", "m",
                                  "--topo", "t"])
        assert args.timeout is None
        args = parser.parse_args(["certify", "full", "--model", "m",
                                  "--topo", "t"])
        assert args.timeout is None
        args = parser.parse_args(["run", "--model", "m"])
        assert args.timeout is None
        args = parser.parse_args(["compare", "--trace", "t"])
        assert args.timeout is None


class TestExtractBurstGuard:
    def test_burst_zero_fails_without_file(self, ctx, tmp_trace, tmp_path):
        from argparse import Namespace
        from veritx_dse.cli.cli import cmd_trace_extract
        out = str(tmp_path / "empty.trace")
        cmd_trace_extract(ctx, Namespace(trace=tmp_trace, uniform=False,
                                         burst=0, out=out))
        import os
        assert not os.path.exists(out)
        assert "--burst needs N >= 1" in open(ctx.log_file).read()


class TestEffTimeout:
    """Precedence: --timeout flag > VERITX_TIMEOUT env > built-in default."""

    def _ns(self, timeout):
        from argparse import Namespace
        return Namespace(timeout=timeout)

    def test_flag_wins(self, monkeypatch):
        from veritx_dse.cli.cli import _eff_timeout
        monkeypatch.setenv("VERITX_TIMEOUT", "9999")
        assert _eff_timeout(self._ns(120), 60) == 120

    def test_env_fallback(self, monkeypatch):
        from veritx_dse.cli.cli import _eff_timeout
        monkeypatch.setenv("VERITX_TIMEOUT", "3600")
        assert _eff_timeout(self._ns(None), 60) == 3600

    def test_builtin_default(self, monkeypatch):
        from veritx_dse.cli.cli import _eff_timeout
        monkeypatch.delenv("VERITX_TIMEOUT", raising=False)
        assert _eff_timeout(self._ns(None), 60) == 60

    def test_missing_attr_uses_env(self, monkeypatch):
        from argparse import Namespace
        from veritx_dse.cli.cli import _eff_timeout
        monkeypatch.setenv("VERITX_TIMEOUT", "86400")
        assert _eff_timeout(Namespace(), 60) == 86400

    def test_invalid_env_fails_fast(self, monkeypatch):
        import pytest
        from veritx_dse.cli.cli import _eff_timeout
        monkeypatch.setenv("VERITX_TIMEOUT", "soon")
        with pytest.raises(ValueError, match="VERITX_TIMEOUT"):
            _eff_timeout(self._ns(None), 60)

    def test_zero_and_negative_rejected(self):
        import pytest
        from veritx_dse.cli.cli import _eff_timeout
        with pytest.raises(ValueError, match=">= 1"):
            _eff_timeout(self._ns(0), 60)
        with pytest.raises(ValueError, match=">= 1"):
            _eff_timeout(self._ns(-5), 60)


class TestBaselineAnynetFailFast:
    def _ns(self, trace, anynet):
        from argparse import Namespace
        return Namespace(trace=trace, topos="mesh_4x4", anynet=anynet,
                         seeds=1, timeout=60)

    def test_missing_anynet_aborts(self, ctx, tmp_trace):
        from unittest.mock import patch
        from veritx_dse.cli.cli import cmd_baseline
        with patch("veritx_dse.cli.cli.run_compare") as rc:
            cmd_baseline(ctx, self._ns(tmp_trace, ["/nonexistent_b.anynet"]))
            rc.assert_not_called()
        assert "Aborting baseline" in open(ctx.log_file).read()


class TestSimOverrides:
    """evaluate --vcs/--vc-buf/--sample-period/--max-samples forwarding."""

    def test_all_unset_empty(self):
        from argparse import Namespace
        from veritx_dse.cli.cli import _sim_overrides
        ns = Namespace(vcs=None, vc_buf=None, sample_period=None,
                       max_samples=None)
        assert _sim_overrides(ns) == {}

    def test_partial_forward(self):
        from argparse import Namespace
        from veritx_dse.cli.cli import _sim_overrides
        ns = Namespace(vcs=16, vc_buf=None, sample_period=None,
                       max_samples=None)
        assert _sim_overrides(ns) == {"num_vcs": 16}

    def test_vcs_reaches_config(self, ctx, tmp_trace):
        from argparse import Namespace
        from unittest.mock import patch, MagicMock
        from veritx_dse.cli.cli import cmd_evaluate_booksim
        ns = Namespace(topo="mesh", k=4, trace=tmp_trace, routing=None,
                       vcs=16, vc_buf=None, sample_period=None,
                       max_samples=None, timeout=60)
        fake_result = {"latency": 10.0, "hops": 2.0}
        with patch("veritx_dse.cli.cli.run_booksim",
                   return_value=dict(fake_result)) as rb:
            cmd_evaluate_booksim(ctx, ns)
            cfg = rb.call_args[0][1]
            assert "num_vcs = 16;" in cfg

    def test_explicit_vcs_overrides_gec_guard(self, tmp_trace):
        from veritx_dse.model.presets import lookup_topo
        from veritx_dse.simulation.booksim import build_config
        topo = lookup_topo("gec_mecs_k8")
        default_cfg = build_config(topo, tmp_trace)
        assert "num_vcs = 8;" in default_cfg  # guard intact by default
        override_cfg = build_config(topo, tmp_trace,
                                    overrides={"num_vcs": 4})
        assert "num_vcs = 4;" in override_cfg  # explicit user wins


class TestEnvConstants:
    def test_env_int(self, monkeypatch):
        from veritx_dse.core.constants import env_int
        monkeypatch.delenv("VERITX_TEST_INT", raising=False)
        assert env_int("VERITX_TEST_INT", 7) == 7
        monkeypatch.setenv("VERITX_TEST_INT", "42")
        assert env_int("VERITX_TEST_INT", 7) == 42
        monkeypatch.setenv("VERITX_TEST_INT", "many")
        import pytest
        with pytest.raises(ValueError, match="VERITX_TEST_INT"):
            env_int("VERITX_TEST_INT", 7)

    def test_plane_max_vc_single_source(self):
        from veritx_dse.core import constants as C
        from veritx_dse.model import compile_model as M
        assert M.PLANE_C_MAX_VC == C.PLANE_C_MAX_VC == 8


class TestIterativeBreadthFlags:
    def test_horizon_branch_group(self):
        from veritx_dse.cli.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["synthesize", "iterative", "--trace", "x",
                                  "--horizon", "3", "--branch", "2",
                                  "--group", "6"])
        assert (args.horizon, args.branch, args.group) == (3, 2, 6)
        args = parser.parse_args(["synthesize", "iterative", "--trace", "x"])
        assert (args.horizon, args.branch, args.group) == (None, None, None)

    def test_run_max_edges(self):
        from veritx_dse.cli.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["run", "--model", "m"])
        assert args.max_edges == 120
        args = parser.parse_args(["run", "--model", "m",
                                  "--max-edges", "64"])
        assert args.max_edges == 64
