"""Tests for veritx_dse.cli — command dispatch and argument parsing.

Uses mock runner for BookSim calls to test without real binary.
"""
import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from veritx_dse.core.logging import Ctx
from veritx_dse.simulation.booksim import build_config, BookSimError
from veritx_dse.model.presets import SWEEP_TOPOS
from veritx_dse.model.compile_model import CompileRequest


# ── Mock BookSim runner ──────────────────────────────────────────────────────

class MockBookSimRunner:
    """Mock subprocess runner for BookSim tests."""

    def __init__(self, latency=100.0, hops=2.0):
        self.latency = latency
        self.hops = hops
        self.calls = []

    def __call__(self, cmd, cwd=None, timeout=None):
        self.calls.append({"cmd": cmd, "cwd": cwd, "timeout": timeout})
        result = MagicMock()
        result.returncode = 0
        result.stdout = f"Packet latency average = {self.latency}\nHops average = {self.hops}\n"
        result.stderr = ""
        return result


# ── build_config tests ───────────────────────────────────────────────────────

class TestBuildConfig:
    def test_seed_in_config(self):
        """Seed=42 must appear in generated config."""
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace", seed=42)
        assert "seed = 42" in config

    def test_seed_none_omitted(self):
        """No seed param → seed not in config."""
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace", seed=None)
        assert "seed" not in config

    def test_latency_thres_default(self):
        """Default latency_thres must be a large value: not 500 (aborts long
        runs) and not -1.0 (the BookSim lexer parses it as int → ParseError)."""
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace")
        assert "latency_thres = 1000000000000000.0" in config

    def test_latency_thres_throughput_keeps_guard(self):
        """Synthetic (throughput) mode keeps the 1e6 saturation guard."""
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace", sim_type="throughput")
        assert "latency_thres = 1000000.0" in config

    def test_latency_thres_explicit_override(self):
        """An explicit latency_thres wins in every mode."""
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace", latency_thres=5000.0)
        assert "latency_thres = 5000.0" in config

    def test_all_topos_produce_valid_config(self):
        """Every preset topology must generate a valid BookSim config."""
        for topo in SWEEP_TOPOS:
            config = build_config(topo, "test.trace", seed=42)
            assert "sim_type = latency" in config
            assert "traffic = trace" in config


# ── run_booksim mock tests ───────────────────────────────────────────────────

class TestRunBookSimMock:
    def test_mock_runner_returns_latency(self):
        """Mock runner should be accepted by run_booksim."""
        from veritx_dse.simulation.booksim import run_booksim

        runner = MockBookSimRunner(latency=42.0)
        ctx = Ctx(verbosity=0)
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace", seed=42)

        with patch("veritx_dse.booksim.find_booksim_bin", return_value=Path("/fake/booksim")):
            result = run_booksim(ctx, config, repo_root=Path("/tmp/test"), runner=runner)
        assert result["latency"] == 42.0
        assert len(runner.calls) == 1

    def test_mock_runner_timeout(self):
        """Mock runner raising TimeoutError should propagate."""
        from veritx_dse.simulation.booksim import run_booksim

        def timeout_runner(cmd, cwd, timeout):
            raise TimeoutBookSim()

        class TimeoutBookSim(Exception):
            pass

        runner = timeout_runner
        ctx = Ctx(verbosity=0)
        topo = SWEEP_TOPOS[0]
        config = build_config(topo, "test.trace", seed=42)

        with pytest.raises(Exception):
            run_booksim(ctx, config, repo_root=Path("/tmp/test"), runner=runner)


# ── CompileRequest validation tests ──────────────────────────────────────────

class TestCompileRequestValidation:
    def test_agent_count_zero_rejected(self):
        with pytest.raises(ValueError, match="count must be >= 1"):
            CompileRequest.from_dict({
                "workload": {"model_family": "dense_transformer", "tp": 4, "dp": 1, "serving_mode": "mixed"},
                "agents": [{"kind": "compute_tile", "count": 0}],
                "noc_config": {},
            })

    def test_agent_count_negative_rejected(self):
        with pytest.raises(ValueError, match="count must be >= 1"):
            CompileRequest.from_dict({
                "workload": {"model_family": "dense_transformer", "tp": 4, "dp": 1, "serving_mode": "mixed"},
                "agents": [{"kind": "compute_tile", "count": -1}],
                "noc_config": {},
            })

    def test_agent_data_width_small_rejected(self):
        with pytest.raises(ValueError, match="data_width"):
            CompileRequest.from_dict({
                "workload": {"model_family": "dense_transformer", "tp": 4, "dp": 1, "serving_mode": "mixed"},
                "agents": [{"kind": "compute_tile", "count": 1, "data_width": 4}],
                "noc_config": {},
            })


# ── Ctx seed tests ──────────────────────────────────────────────────────────

class TestCtxSeed:
    def test_default_seed(self):
        ctx = Ctx()
        assert ctx.seed == 0  # 0 = auto-generate

    def test_custom_seed(self):
        ctx = Ctx(seed=99)
        assert ctx.seed == 99


# ── Trace validation tests ──────────────────────────────────────────────────

class TestTraceValidation:
    def test_negative_node_id_rejected(self):
        from veritx_dse.simulation.traces import validate_trace
        import tempfile, os

        with tempfile.NamedTemporaryFile(mode="w", suffix=".trace", delete=False) as f:
            f.write("0 -1 0 2 4\n")
            f.flush()
            result = validate_trace(f.name)
            os.unlink(f.name)

        assert not result.valid
        assert any("negative" in e for e in result.errors)


# ── --set parsing: loud failures, no silent drops ──────────────────────────

class TestSetParsing:
    def test_malformed_set_fails(self):
        from veritx_dse.cli.cli import _parse_set
        ctx = Ctx()
        assert _parse_set(ctx, ["bareword"]) == {}
        assert ctx.failed

    def test_astra_keys_rejected_on_compare(self):
        from veritx_dse.cli.cli import _reject_astra_sets
        ctx = Ctx()
        assert _reject_astra_sets(ctx, ["system.scheduling-policy=FIFO"], "compare")
        assert ctx.failed

    def test_astra_keys_rejected_on_sweep(self):
        from veritx_dse.cli.cli import _reject_astra_sets
        ctx = Ctx()
        assert _reject_astra_sets(ctx, ["network.topology.Name=Ring"], "sweep")
        assert ctx.failed

    def test_plain_booksim_keys_pass_through(self):
        from veritx_dse.cli.cli import _parse_set, _reject_astra_sets
        ctx = Ctx()
        assert _parse_set(ctx, ["num_vcs=8", "arb_type=iSLIP"]) == {
            "num_vcs": 8, "arb_type": "iSLIP"}
        assert not ctx.failed
        assert not _reject_astra_sets(ctx, ["num_vcs=8"], "compare")
        assert not ctx.failed

    def test_cli_flag_spellings_map_to_booksim_keys(self):
        from veritx_dse.cli.cli import _parse_set
        ctx = Ctx()
        assert _parse_set(ctx, ["vcs=4", "vc-buf=8"]) == {
            "num_vcs": 4, "vc_buf_size": 8}
        assert not ctx.failed

    def test_malformed_astra_set_fails(self):
        from veritx_dse.cli.cli import _split_astra_sets
        ctx = Ctx()
        assert _split_astra_sets(ctx, ["system"]) == {}
        assert ctx.failed


# ── anynet connectivity guard ───────────────────────────────────────────────

class TestAnynetConnected:
    def _write(self, tmp_path, text):
        p = tmp_path / "t.anynet"
        p.write_text(text)
        return str(p)

    def test_connected(self, tmp_path):
        from veritx_dse.model.presets import check_anynet_connected
        p = self._write(tmp_path,
                        "router 0 node 0 router 1 router 2\n"
                        "router 1 node 1 router 0 router 2\n"
                        "router 2 node 2 router 0 router 1\n")
        assert check_anynet_connected(p) == (True, 3, 0)

    def test_disconnected_reports_counts(self, tmp_path):
        from veritx_dse.model.presets import check_anynet_connected
        p = self._write(tmp_path,
                        "router 0 node 0 router 1\n"
                        "router 1 node 1 router 0\n"
                        "router 2 node 2 router 3\n"
                        "router 3 node 3 router 2\n")
        assert check_anynet_connected(p) == (False, 4, 2)

    def test_missing_file_is_not_connected(self, tmp_path):
        from veritx_dse.model.presets import check_anynet_connected
        assert check_anynet_connected(str(tmp_path / "ghost.anynet")) == (False, 0, 0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
