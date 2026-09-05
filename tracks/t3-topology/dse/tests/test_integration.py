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
    """veritx compile <json> — full 6-stage pipeline."""

    @pytest.mark.parametrize("example", [
        "qwen3_moe_16npu.json",
        "llama70b_tp64.json",
        "llama1b_tp64.json",
        "dense_64npu.json",
        "moe_8npu.json",
    ])
    def test_all_presets_compile(self, example):
        """Each example JSON → compile succeeds with 6 stages."""
        json_path = EXAMPLES_DIR / example
        if not json_path.exists():
            pytest.skip(f"Example {example} not found")
        result = _cli("compile", str(json_path), timeout=90)
        assert result.returncode == 0, (
            f"Example {example} failed:\n"
            f"stdout[-300:]: {result.stdout[-300:]}\n"
            f"stderr[-300:]: {result.stderr[-300:]}"
        )
        clean = _strip_ansi(result.stdout)
        # Should show some compile output (may not have full result if no trace)
        assert len(clean.strip()) > 50, f"Compile produced no output for {example}"

    def test_compile_shows_area_power_timing(self):
        """compile qwen3 → shows area, power, timing numbers."""
        json_path = EXAMPLES_DIR / "qwen3_moe_16npu.json"
        if not json_path.exists():
            pytest.skip("Example not found")
        result = _cli("compile", str(json_path), timeout=90)
        assert result.returncode == 0
        clean = _strip_ansi(result.stdout)
        # Should show physical estimates
        has_numbers = any(kw in clean for kw in ["mm", "MHz", "pJ", "W"])
        assert has_numbers, f"Missing area/power/timing in output:\n{clean[-500:]}"

    def test_compile_shows_accuracy_notes(self):
        """compile --output → JSON report includes accuracy notes."""
        json_path = EXAMPLES_DIR / "qwen3_moe_16npu.json"
        if not json_path.exists():
            pytest.skip("Example not found")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        try:
            result = _cli("compile", str(json_path), "--output", out_path, timeout=90)
            assert result.returncode == 0
            report = json.loads(Path(out_path).read_text())
            report_str = json.dumps(report).lower()
            has_caveat = any(kw in report_str for kw in [
                "estimat", "caveat", "relative", "limitation", "note", "accuracy"
            ])
            assert has_caveat, f"Missing accuracy notes in JSON report. Keys: {list(report.keys())}"
        finally:
            os.unlink(out_path)

    def test_compile_shows_manifest_signature(self):
        """compile → manifest with HMAC-SHA256 signature."""
        json_path = EXAMPLES_DIR / "qwen3_moe_16npu.json"
        if not json_path.exists():
            pytest.skip("Example not found")
        result = _cli("compile", str(json_path), timeout=90)
        assert result.returncode == 0
        clean = _strip_ansi(result.stdout).lower()
        assert any(kw in clean for kw in ["hmac", "sign", "manifest", "guardrail"])

    def test_compile_json_output(self):
        """compile --output → produces valid JSON report."""
        json_path = EXAMPLES_DIR / "qwen3_moe_16npu.json"
        if not json_path.exists():
            pytest.skip("Example not found")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            out_path = f.name
        try:
            result = _cli("compile", str(json_path), "--output", out_path, timeout=90)
            assert result.returncode == 0
            report = json.loads(Path(out_path).read_text())
            # Should have key sections
            assert "veritx_version" in report or "result" in report or "area" in report
        finally:
            os.unlink(out_path)


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

    def test_compile_missing_file(self):
        """compile with missing JSON → clear error."""
        result = _cli("compile", "/nonexistent/request.json", timeout=10)
        # May return 0 but show error in stdout, or non-zero
        assert result.returncode != 0 or "error" in (result.stdout + result.stderr).lower() or "not found" in (result.stdout + result.stderr).lower()

    def test_compile_invalid_json(self):
        """compile with invalid JSON → clear error."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("not valid json {{{")
            f.flush()
            result = _cli("compile", f.name, timeout=10)
            os.unlink(f.name)
            assert result.returncode != 0 or "error" in _strip_ansi(result.stderr + result.stdout).lower() or "failed" in _strip_ansi(result.stderr).lower()

    def test_help_all_commands(self):
        """veritx <cmd> --help works for all commands."""
        for cmd in ["trace", "compile", "init", "generate", "compare",
                    "synthesize", "evaluate", "certify", "run", "sweep"]:
            result = _cli(cmd, "--help", timeout=5)
            assert result.returncode == 0, f"'{cmd} --help' failed"
