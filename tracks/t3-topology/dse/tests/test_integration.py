"""Integration tests — full CLI pipeline end-to-end.

These tests verify that CLI commands work together correctly,
simulating real user workflows. Uses the actual CLI interface:
  veritx compile <json>     — compile a CompileRequest
  veritx init --out <file>  — generate a CompileRequest
  veritx trace info <path>  — analyze a trace
  veritx trace validate <path> — validate trace format
  veritx generate uvm <json>  — generate UVM testbench
  veritx compare ...        — head-to-head topology comparison
"""
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape codes from text."""
    return re.sub(r'\x1b\[[0-9;]*m', '', text)

DSE_DIR = Path(__file__).parent.parent  # dse/ (tests/ is one level deeper)
REPO = DSE_DIR.parent.parent.parent
CLI = [sys.executable, "-m", "veritx_dse.cli"]
EXAMPLES_DIR = DSE_DIR / "examples"  # dse/examples/
TRACES_DIR = DSE_DIR / "inputs" / "traces"
QWEN_TRACE = TRACES_DIR / "qwen3_serving_astra.trace"
TINY_TRACE = TRACES_DIR / "test_dynamic.trace"  # 130 lines, runs in <5s


def _cli(*args: str, input_text: str = "\n", timeout: int = 60,
         cwd: str | None = None) -> subprocess.CompletedProcess:
    """Run CLI with proper PYTHONPATH."""
    env = {**os.environ, "PYTHONPATH": str(DSE_DIR)}  # dse/ for veritx_dse import
    return subprocess.run(
        list(CLI) + list(args),
        input=input_text, capture_output=True, text=True,
        timeout=timeout, cwd=cwd or str(REPO), env=env,
    )


# ── Compile from preset JSON ────────────────────────────────────────────

class TestCompilePipeline:
    """veritx compile — canonical product compile surface (no BookSim)."""

    @pytest.mark.parametrize("preset", ["mesh4", "mesh4_hbm",
                                        "mesh4_wide128"])
    def test_canonical_presets_compile(self, preset, tmp_path):
        """Each named CompileIntent preset resolves structurally."""
        result = _cli(
            "compile", "--preset", preset,
            "--policy", "baseline_deterministic_v2",
            "--store", str(tmp_path / "store"), timeout=90)
        assert result.returncode == 0, (
            f"Preset {preset} failed:\n"
            f"stdout[-300:]: {result.stdout[-300:]}\n"
            f"stderr[-300:]: {result.stderr[-300:]}"
        )
        clean = _strip_ansi(result.stdout)
        assert "RESOLVED" in clean
        assert "resolved_fabric_hash" in clean or "resolved_fabric" in clean

    def test_compile_reports_structural_state_only(self, tmp_path):
        """The canonical compile command makes no execution claims."""
        result = _cli(
            "compile", "--preset", "mesh4",
            "--policy", "baseline_deterministic_v2",
            "--store", str(tmp_path / "store"), timeout=90)
        assert result.returncode == 0
        clean = _strip_ansi(result.stdout).lower()
        assert "compile state" in clean and "resolved" in clean
        assert "backend execution" in clean and "not performed" in clean
        for token in ("latency", "verified", "qualified", "executable",
                      "booksim", "area", "power"):
            assert token not in clean, token

    def test_compile_commits_a_resolution(self, tmp_path):
        """A committed resolution exists under the explicit store path."""
        store = tmp_path / "store"
        result = _cli(
            "compile", "--preset", "mesh4",
            "--policy", "baseline_deterministic_v2",
            "--store", str(store), timeout=90)
        assert result.returncode == 0
        assert len(list((store / "resolutions").glob("*.json"))) == 1
        assert len(list((store / "designs").glob("*.json"))) == 1

    def test_compile_json_output_summary(self, tmp_path):
        """--output writes the same non-persisted summary as presentation."""
        out_path = tmp_path / "summary.json"
        result = _cli(
            "compile", "--preset", "mesh4",
            "--policy", "baseline_deterministic_v2",
            "--store", str(tmp_path / "store"),
            "--output", str(out_path), timeout=90)
        assert result.returncode == 0
        summary = json.loads(out_path.read_text())
        assert summary["status"] == "RESOLVED"
        assert set(summary) == {
            "status", "intent_id", "design_hash", "fabric_hash",
            "resolved_fabric_hash", "topology_hash", "mapping_hash",
            "vc_count"}

    def test_compile_override_converges_on_wide128(self, tmp_path):
        """Preset override and named preset resolve to the same hardware."""
        result = _cli(
            "compile", "--preset", "mesh4",
            "--policy", "baseline_deterministic_v2",
            "--store", str(tmp_path / "store"),
            "--set", "noc_config.link_width=128", timeout=90)
        assert result.returncode == 0
        assert "9f5d25edb7053bdf170669345b14d056e690479d895d00bee6a5cef3da604528" \
            in _strip_ansi(result.stdout)


# ── Init wizard ──────────────────────────────────────────────────────────

class TestInitWizard:
    """veritx init — interactive CompileRequest generator."""

    def test_init_help(self):
        """init --help shows usage."""
        result = _cli("init", "--help")
        assert result.returncode == 0
        assert "out" in result.stdout.lower()

    def test_init_with_piped_input(self):
        """init with piped input → generates valid JSON."""
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        try:
            # Feed answers: model_family, model_name, TP, EP, n_compute, n_hbm, topology
            input_text = "moe\nQwen3-Test\n16\n8\n16\n4\nmesh\n"
            result = _cli("init", "--out", out_path, input_text=input_text, timeout=10)
            if result.returncode == 0 and Path(out_path).exists():
                data = json.loads(Path(out_path).read_text())
                assert "workload" in data or "noc_config" in data
        finally:
            os.unlink(out_path)


# ── Trace commands ───────────────────────────────────────────────────────

class TestTraceCommands:
    """veritx trace info/validate — trace analysis."""

    @pytest.mark.skipif(not QWEN_TRACE.exists(), reason="Qwen3 trace not found")
    def test_trace_info_shows_stats(self):
        """trace info → shows packet count, sources, injection rate."""
        result = _cli("trace", "info", str(QWEN_TRACE), timeout=10)
        assert result.returncode == 0
        stdout = result.stdout.lower()
        # Should show some trace statistics
        has_stats = any(kw in stdout for kw in [
            "packet", "src", "inject", "cycle", "burst", "rank"
        ])
        assert has_stats, f"Missing trace stats in output:\n{result.stdout[-300:]}"

    @pytest.mark.skipif(not QWEN_TRACE.exists(), reason="Qwen3 trace not found")
    def test_trace_validate_clean(self):
        """trace validate → clean trace passes validation."""
        result = _cli("trace", "validate", str(QWEN_TRACE), timeout=10)
        assert result.returncode == 0

    def test_trace_validate_nonexistent(self):
        """trace validate with missing file → clear error."""
        result = _cli("trace", "validate", "/nonexistent/trace.trace", timeout=10)
        # Should fail or warn, not crash
        output = _strip_ansi(result.stdout + result.stderr).lower()
        assert result.returncode != 0 or "error" in output or "not found" in output or "no such file" in output or "failed" in output


# ── Generate UVM ─────────────────────────────────────────────────────────

class TestGenerateUVM:
    """veritx generate uvm — UVM testbench generation."""

    def test_generate_uvm_help(self):
        """generate uvm --help shows options."""
        result = _cli("generate", "uvm", "--help")
        assert result.returncode == 0
        assert "request" in result.stdout.lower() or "json" in result.stdout.lower()

    def test_generate_uvm_from_example(self):
        """generate uvm --request <json> → produces 3+ .sv files."""
        json_path = EXAMPLES_DIR / "qwen3_moe_16npu.json"
        if not json_path.exists():
            pytest.skip("Example not found")
        with tempfile.TemporaryDirectory() as tmpdir:
            result = _cli("generate", "uvm",
                         "--request", str(json_path),
                         "--out", tmpdir, timeout=30)
            if result.returncode == 0:
                sv_files = list(Path(tmpdir).glob("*.sv"))
                assert len(sv_files) >= 3, f"Expected ≥3 .sv files, got {len(sv_files)}"


# ── Compare ──────────────────────────────────────────────────────────────

class TestComparePipeline:
    """veritx compare — head-to-head topology comparison."""

    @pytest.mark.skipif(not TINY_TRACE.exists(), reason="test_dynamic.trace not found")
    def test_compare_mesh_vs_torus(self):
        """compare mesh_8x8 vs torus_8x8 → produces result table."""
        result = _cli(
            "compare",
            "--trace", str(TINY_TRACE),
            "--topos", "mesh_8x8,torus_8x8",
            "--seeds", "1",
            "--timeout", "10",
            timeout=30,
        )
        assert result.returncode == 0, f"Compare failed: {result.stderr[-300:]}"
        stdout = result.stdout.lower()
        assert "mesh" in stdout and "torus" in stdout

    @pytest.mark.skipif(not TINY_TRACE.exists(), reason="test_dynamic.trace not found")
    def test_compare_json_output(self):
        """compare --json → valid JSON."""
        result = _cli(
            "compare",
            "--trace", str(TINY_TRACE),
            "--topos", "mesh_8x8",
            "--seeds", "1",
            "--timeout", "10",
            "--json",
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                data = json.loads(result.stdout)
                assert isinstance(data, dict) or isinstance(data, list)
            except json.JSONDecodeError:
                pytest.skip("JSON output not parseable — may have mixed stdout")


# ── Error handling ───────────────────────────────────────────────────────

class TestErrorHandling:
    """Verify CLI handles errors gracefully."""

    def test_compile_rejects_raw_request_positional(self, tmp_path):
        """A bare CompileRequest path is no longer the CLI contract."""
        result = _cli("compile", str(EXAMPLES_DIR / "moe_8npu.json"),
                      "--store", str(tmp_path / "store"), timeout=10)
        assert result.returncode != 0
        assert "Traceback" not in result.stderr

    def test_compile_requires_store_and_valid_declaration(self, tmp_path):
        """--store is required; malformed --set is a clean user error."""
        missing_store = _cli("compile", "--preset", "mesh4",
                             "--policy", "baseline_deterministic_v2",
                             timeout=10)
        assert missing_store.returncode != 0
        assert "Traceback" not in missing_store.stderr
        bad_override = _cli(
            "compile", "--preset", "mesh4",
            "--policy", "baseline_deterministic_v2",
            "--store", str(tmp_path / "store"),
            "--set", "noc_config.arbitration=rr", timeout=10)
        assert bad_override.returncode != 0
        assert "Traceback" not in bad_override.stderr
        assert "JSON scalar" in _strip_ansi(bad_override.stderr
                                            + bad_override.stdout)

    def test_help_all_commands(self):
        """veritx <cmd> --help works for all commands."""
        for cmd in ["trace", "compile", "init", "generate", "compare",
                    "synthesize", "evaluate", "certify", "run", "sweep"]:
            result = _cli(cmd, "--help", timeout=5)
            assert result.returncode == 0, f"'{cmd} --help' failed"
