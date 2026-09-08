"""Contract tests for `veritx trace …` — all seven subcommands.

These commands previously had three dead-on-arrival members (extract called
extract_uniform with the wrong arity, slice imported a function that never
existed, hpc/model referenced unimported globals). These tests pin the
repaired behavior: real trace files, real conversions, observable artifacts.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.cli.commands_trace import (
    cmd_trace_extract,
    cmd_trace_hpc,
    cmd_trace_info,
    cmd_trace_model,
    cmd_trace_slice,
    cmd_trace_validate,
)
from veritx_dse.core.logging import Ctx

LIB_TRACES = DSE / "inputs" / "traces"
TINY_TRACE = LIB_TRACES / "test_dynamic.trace"   # 130 packets, runs fast


def _write_trace(tmp_path, rows):
    p = tmp_path / "in.trace"
    p.write_text("\n".join(f"{c} {s} {cl} {d} {sz}" for c, s, cl, d, sz in rows) + "\n")
    return p


def _args(**kw):
    return SimpleNamespace(**kw)


# ── validate / info ──────────────────────────────────────────────────────

@pytest.mark.skipif(not TINY_TRACE.exists(), reason="library trace missing")
def test_validate_happy_path(capsys):
    cmd_trace_validate(Ctx(verbosity=1), _args(trace=str(TINY_TRACE)))
    err = capsys.readouterr().err
    assert "Packets" in err and "IR" in err
    assert "errors" not in err.lower() or "usable" in err


def test_validate_reports_errors_not_crash(tmp_path, capsys):
    bad = tmp_path / "bad.trace"
    bad.write_text("not a trace\n")
    cmd_trace_validate(Ctx(verbosity=1), _args(trace=str(bad)))
    assert "errors" in capsys.readouterr().err


@pytest.mark.skipif(not TINY_TRACE.exists(), reason="library trace missing")
def test_info_prints_fields(capsys):
    cmd_trace_info(Ctx(verbosity=1), _args(trace=str(TINY_TRACE)))
    out = capsys.readouterr().out
    for field in ("File:", "Valid:", "Packets:", "Span:", "IR:"):
        assert field in out


# ── extract: burst + uniform + errors ────────────────────────────────────

class TestExtract:
    def test_burst_takes_first_n_and_shifts_to_zero(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [
            (1000, 0, 0, 1, 4), (1100, 1, 0, 2, 4), (1200, 2, 0, 0, 4)])
        out = tmp_path / "burst.trace"
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(src), burst=2, out=str(out)))
        rows = [l.split() for l in out.read_text().splitlines()]
        assert len(rows) == 2
        assert rows[0][0] == "0"                    # shifted to t=0
        assert rows[1][0] == "100"                  # relative spacing kept
        assert "first 2 packets" in capsys.readouterr().err

    def test_burst_larger_than_trace_clamps(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(5, 0, 0, 1, 4)])
        out = tmp_path / "b.trace"
        cmd_trace_extract(Ctx(verbosity=1), _args(trace=str(src), burst=99, out=str(out)))
        assert len(out.read_text().splitlines()) == 1
        assert "first 1 packets" in capsys.readouterr().err

    def test_uniform_redistributes_times(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(100, 0, 0, 1, 4), (900, 1, 0, 2, 4)])
        out = tmp_path / "u.trace"
        cmd_trace_extract(Ctx(verbosity=1), _args(trace=str(src), burst=None, out=str(out)))
        rows = [l.split()[0] for l in out.read_text().splitlines()]
        assert rows == ["0", "450"]                 # spacing = 900//2
        assert "spacing 450" in capsys.readouterr().err

    def test_missing_trace_fails(self, tmp_path, capsys):
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(tmp_path / "nope.trace"), burst=2, out=str(tmp_path / "o")))
        assert "not found" in capsys.readouterr().err


# ── slice ────────────────────────────────────────────────────────────────

class TestSlice:
    def test_slice_keeps_selected_class_and_renumbers(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [
            (0, 0, 0, 1, 4), (1, 1, 1, 2, 4), (2, 2, 0, 0, 4)])
        out = tmp_path / "sliced.trace"
        cmd_trace_slice(Ctx(verbosity=1), _args(
            trace=str(src), classes="0", out=str(out), renumber=True))
        rows = [l.split() for l in out.read_text().splitlines() if not l.startswith("#")]
        assert len(rows) == 2
        assert all(r[2] == "0" for r in rows)       # renumbered to 0
        assert "2 packets kept, 1 dropped" in capsys.readouterr().err

    def test_slice_rejects_non_numeric_classes(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(0, 0, 0, 1, 4)])
        cmd_trace_slice(Ctx(verbosity=1), _args(
            trace=str(src), classes="zero", out=str(tmp_path / "o")))
        assert "comma-separated" in capsys.readouterr().err

    def test_slice_missing_trace_fails(self, tmp_path, capsys):
        cmd_trace_slice(Ctx(verbosity=1), _args(
            trace=str(tmp_path / "nope"), classes="0", out=str(tmp_path / "o")))
        assert "not found" in capsys.readouterr().err


# ── chakra (guidance command — must not crash, must explain) ─────────────

class TestChakra:
    def test_missing_path(self, tmp_path, capsys):
        from veritx_dse.cli.commands_trace import cmd_trace_chakra
        cmd_trace_chakra(Ctx(verbosity=1), _args(et_dir=str(tmp_path / "nope")))
        assert "Path not found" in capsys.readouterr().err

    def test_dir_without_et_files(self, tmp_path, capsys):
        from veritx_dse.cli.commands_trace import cmd_trace_chakra
        d = tmp_path / "empty"; d.mkdir()
        cmd_trace_chakra(Ctx(verbosity=1), _args(et_dir=str(d)))
        err = capsys.readouterr().err
        assert "No .et files" in err

    def test_dir_with_et_files_gives_guidance(self, tmp_path, capsys):
        from veritx_dse.cli.commands_trace import cmd_trace_chakra
        d = tmp_path / "ets"; d.mkdir()
        (d / "llm.0.et").write_bytes(b"\x00\x01")
        cmd_trace_chakra(Ctx(verbosity=1), _args(et_dir=str(d)))
        err = capsys.readouterr().err
        assert "chakra_to_dse" in err and "trace model" in err


# ── model ────────────────────────────────────────────────────────────────

class TestModel:
    def test_generates_trace_from_traffic_model(self, tmp_path, capsys, monkeypatch):
        tm = {"network": {"flow_classes": [{
            "name": "ar", "comm_type": "allreduce", "bytes_per_invocation": 512,
            "invocations_per_batch": 1, "instances": [{"participants": [0, 1, 2]}]}]}}
        model = tmp_path / "tm.json"
        model.write_text(json.dumps(tm))
        out = tmp_path / "gen" / "input.trace"
        monkeypatch.chdir(tmp_path)
        cmd_trace_model(Ctx(verbosity=1), _args(model=str(model), nodes=3, out=str(out)))
        assert out.exists()
        body = [l for l in out.read_text().splitlines() if not l.startswith("#")]
        assert len(body) == 12                       # ring allreduce 3 nodes: 2(k-1)·k
        assert "Trace written" in capsys.readouterr().err

    def test_missing_model_fails(self, tmp_path, capsys):
        cmd_trace_model(Ctx(verbosity=1), _args(
            model=str(tmp_path / "nope.json"), nodes=4, out=str(tmp_path / "o")))
        assert "not found" in capsys.readouterr().err


# ── hpc (trace library install) ──────────────────────────────────────────

class TestHpc:
    def test_installs_library_trace(self, tmp_path, capsys):
        out = tmp_path / "runs" / "wrf.trace"
        cmd_trace_hpc(Ctx(verbosity=1), _args(
            trace_file="test_dynamic", nodes=64, out=str(out)))
        assert out.exists()
        assert "Installed" in capsys.readouterr().err

    def test_accepts_explicit_path(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(0, 0, 0, 1, 4)])
        out = tmp_path / "copy.trace"
        cmd_trace_hpc(Ctx(verbosity=1), _args(
            trace_file=str(src), nodes=64, out=str(out)))
        assert out.exists() and out.read_text() == src.read_text()

    def test_unknown_library_entry_lists_available(self, tmp_path, capsys):
        cmd_trace_hpc(Ctx(verbosity=1), _args(
            trace_file="hpc_wrf", nodes=64, out=str(tmp_path / "o")))
        err = capsys.readouterr().err
        assert "not in library" in err
        assert "Available:" in err
