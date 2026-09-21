"""Contract tests for `veritx trace …` — the seven live subcommands.

These tests target the LIVE implementations in cli.py (the dispatcher binds
cli.py's internal cmd_trace_* functions). The parallel commands_trace.py module
was dead code (wrong arity, phantom imports) and has been deleted; these tests
pin the live behavior so the split can't silently reappear.

Real traces, real converter, real artifacts — observable behavior only.
"""
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.cli.cli import (
    cmd_trace_validate,
    cmd_trace_info,
    cmd_trace_extract,
    cmd_trace_slice,
    cmd_trace_chakra,
    cmd_trace_model,
    cmd_trace_hpc,
)
from veritx_dse.core.logging import Ctx

LIB_TRACES = DSE / "tests" / "fixtures" / "traces"
TINY_TRACE = LIB_TRACES / "test_dynamic.trace"   # runs fast


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
    cap = capsys.readouterr()
    assert "✓ VALID" in cap.out      # detail lines print to stdout
    assert "Packets:" in cap.out
    assert "Trace is clean" in cap.err   # ok() goes to stderr


def test_validate_reports_errors_not_crash(tmp_path, capsys):
    bad = tmp_path / "bad.trace"
    bad.write_text("not a trace\n")   # 3 fields → short-line error
    cmd_trace_validate(Ctx(verbosity=1), _args(trace=str(bad)))
    cap = capsys.readouterr()
    assert "✗ INVALID" in cap.out
    assert "expected >=5 fields" in cap.out
    assert "errors" in cap.err       # fail() goes to stderr


def test_validate_missing_trace_not_crash(tmp_path, capsys):
    cmd_trace_validate(Ctx(verbosity=1), _args(trace=str(tmp_path / "nope.trace")))
    cap = capsys.readouterr()
    assert "✗ INVALID" in cap.out
    assert "Not found" in cap.out


@pytest.mark.skipif(not TINY_TRACE.exists(), reason="library trace missing")
def test_info_prints_fields(capsys):
    cmd_trace_info(Ctx(verbosity=1), _args(trace=str(TINY_TRACE)))
    out = capsys.readouterr().out
    for field in ("File:", "Packets:", "Time range:", "Avg IR:", "Profile:"):
        assert field in out


# ── extract: burst + uniform + errors (live: extract_burst/extract_uniform) ──

class TestExtract:
    def test_burst_takes_first_n_and_shifts_to_zero(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [
            (1000, 0, 0, 1, 4), (1100, 1, 0, 2, 4), (1200, 2, 0, 0, 4)])
        out = tmp_path / "burst.trace"
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(src), burst=2, uniform=False, out=str(out)))
        rows = [l.split() for l in out.read_text().splitlines()]
        assert len(rows) == 2
        assert rows[0][0] == "0"                    # shifted to t=0
        assert rows[1][0] == "100"                  # relative spacing kept
        assert "Extracted 2 packets" in capsys.readouterr().err

    def test_burst_larger_than_trace_takes_all(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(5, 0, 0, 1, 4)])
        out = tmp_path / "b.trace"
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(src), burst=99, uniform=False, out=str(out)))
        assert len(out.read_text().splitlines()) == 1
        assert "Extracted 1 packets" in capsys.readouterr().err

    def test_burst_zero_is_rejected(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(5, 0, 0, 1, 4)])
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(src), burst=0, uniform=False, out=str(tmp_path / "o")))
        err = capsys.readouterr().err
        assert "N >= 1" in err
        assert not (tmp_path / "o").exists()

    def test_uniform_redistributes_times(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(100, 0, 0, 1, 4), (900, 1, 0, 2, 4)])
        out = tmp_path / "u.trace"
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(src), uniform=True, out=str(out)))
        rows = [l.split()[0] for l in out.read_text().splitlines()]
        assert rows == ["0", "450"]                 # spacing = 900 // 2
        assert "Extracted 2 packets" in capsys.readouterr().err

    def test_neither_mode_fails(self, tmp_path, capsys):
        src = _write_trace(tmp_path, [(5, 0, 0, 1, 4)])
        cmd_trace_extract(Ctx(verbosity=1), _args(
            trace=str(src), burst=None, uniform=False, out=str(tmp_path / "o")))
        err = capsys.readouterr().err
        assert "--burst" in err and "--uniform" in err

    def test_missing_trace_raises_file_not_found(self, tmp_path):
        # Live contract: main() converts FileNotFoundError into "trace failed: …"
        with pytest.raises(FileNotFoundError):
            cmd_trace_extract(Ctx(verbosity=1), _args(
                trace=str(tmp_path / "nope.trace"), burst=2, uniform=False,
                out=str(tmp_path / "o")))


# ── slice (live: slice_trace — supports renumber) ─────────────────────────

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

    def test_slice_without_renumber_preserves_classes(self, tmp_path):
        src = _write_trace(tmp_path, [(0, 0, 3, 1, 4), (1, 1, 3, 2, 4)])
        out = tmp_path / "sliced.trace"
        cmd_trace_slice(Ctx(verbosity=1), _args(
            trace=str(src), classes="3", out=str(out), renumber=False))
        rows = [l.split() for l in out.read_text().splitlines() if not l.startswith("#")]
        assert all(r[2] == "3" for r in rows)
        assert out.read_text().startswith("# Sliced from in.trace")

    def test_slice_rejects_non_numeric_classes(self, tmp_path):
        src = _write_trace(tmp_path, [(0, 0, 0, 1, 4)])
        # Live contract: int() ValueError propagates to main()
        with pytest.raises(ValueError):
            cmd_trace_slice(Ctx(verbosity=1), _args(
                trace=str(src), classes="zero", out=str(tmp_path / "o")))

    def test_slice_missing_trace_fails(self, tmp_path, capsys):
        cmd_trace_slice(Ctx(verbosity=1), _args(
            trace=str(tmp_path / "nope"), classes="0", out=str(tmp_path / "o")))
        assert "Trace not found" in capsys.readouterr().err


# ── chakra (live: real converter via scripts/, guidance for .et dirs) ─────

class TestChakra:
    def test_txt_dir_converted_via_real_converter(self, tmp_path, capsys):
        d = tmp_path / "serving_traces"; d.mkdir()
        # Real LLMServingSim line: 11 fields — name comp in_loc in_size
        # w_loc w_size out_loc out_size comm comm_size misc
        (d / "instance0_batch0.txt").write_text(
            "ALLREDUCE:1,0 100 NPU0 512 NPU0 0 NPU0 512 ALLREDUCE:1,0 512 S\n")
        out = tmp_path / "converted.trace"
        cmd_trace_chakra(Ctx(verbosity=1), _args(
            et_dir=str(d), npu_map="0,1,2,3", out=str(out), speedup=1))
        assert out.exists()
        body = [l for l in out.read_text().splitlines() if not l.startswith("#")]
        assert len(body) >= 1
        # Ring allreduce over the mapped NPU group
        assert any(r.split()[3] != r.split()[1] for r in body)

    def test_missing_path_fails(self, tmp_path, capsys):
        cmd_trace_chakra(Ctx(verbosity=1), _args(et_dir=str(tmp_path / "nope")))
        assert "Not found" in capsys.readouterr().err   # live fail() branch

    def test_dir_with_et_files_gives_build_guidance(self, tmp_path, capsys):
        # CHAKRA_TO_ET is not built in this tree → the guidance branch is live
        d = tmp_path / "ets"; d.mkdir()
        (d / "llm.0.et").write_bytes(b"\x00\x01")
        cmd_trace_chakra(Ctx(verbosity=1), _args(et_dir=str(d)))
        err = capsys.readouterr().err
        assert "chakra_to_et" in err
        assert "cmake --build" in err

    def test_empty_dir_fails(self, tmp_path, capsys):
        d = tmp_path / "empty"; d.mkdir()
        cmd_trace_chakra(Ctx(verbosity=1), _args(et_dir=str(d)))
        assert "No .txt or .et files" in capsys.readouterr().err


# ── model (live: model_to_trace via main(), output dir auto-created) ──────

def _traffic_model(participants=(0, 1, 2), bytes_=512):
    return {"network": {"flow_classes": [{
        "name": "ar", "comm_type": "allreduce", "bytes_per_invocation": bytes_,
        "invocations_per_batch": 1,
        "instances": [{"participants": list(participants)}]}]}}


class TestModel:
    def test_generates_trace_from_traffic_model(self, tmp_path, capsys, monkeypatch):
        model = tmp_path / "tm.json"
        model.write_text(__import__("json").dumps(_traffic_model()))
        out = tmp_path / "gen" / "input.trace"       # parent dir doesn't exist yet
        monkeypatch.chdir(tmp_path)
        cmd_trace_model(Ctx(verbosity=1), _args(model=str(model), nodes=3, out=str(out)))
        assert out.exists()
        body = [l for l in out.read_text().splitlines() if not l.startswith("#")]
        assert len(body) == 12                       # ring allreduce, 3 nodes: 2(k−1)·k
        assert all(r.split()[2] == "0" for r in body)   # classes mapped to 0
        assert "Trace:" in capsys.readouterr().err

    def test_unknown_comm_type_fails_closed(self, tmp_path, capsys, monkeypatch):
        """PR C: unsupported semantics refuse to lower — CLI fails, no trace."""
        tm = _traffic_model()
        tm["network"]["flow_classes"][0]["comm_type"] = "teleport"
        model = tmp_path / "tm.json"
        model.write_text(__import__("json").dumps(tm))
        out = tmp_path / "o.trace"
        monkeypatch.chdir(tmp_path)
        cmd_trace_model(Ctx(verbosity=1), _args(model=str(model), nodes=3, out=str(out)))
        err = capsys.readouterr().err
        assert "Lowering refused" in err
        assert "teleport" in err
        assert not out.exists()
        assert not Path(str(out) + ".manifest.json").exists()

    def test_missing_model_fails(self, tmp_path, capsys):
        cmd_trace_model(Ctx(verbosity=1), _args(
            model=str(tmp_path / "nope.json"), nodes=4, out=str(tmp_path / "o")))
        assert "not found" in capsys.readouterr().err


# ── hpc (live: install into runs tree — explicit path or library lookup) ──

class TestHpc:
    def test_installs_library_trace(self, tmp_path, capsys):
        out = tmp_path / "runs" / "wrf.trace"
        cmd_trace_hpc(Ctx(verbosity=1), _args(
            trace_file="test_dynamic", nodes=64, out=str(out)))
        assert out.exists()
        assert "Trace:" in capsys.readouterr().err

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
        assert "Trace not found: hpc_wrf" in err
        assert "Trace library" in err                 # lists available entries

    def test_appends_dot_trace_extension(self, tmp_path, capsys):
        out = tmp_path / "runs" / "q.trace"
        cmd_trace_hpc(Ctx(verbosity=1), _args(
            trace_file="test_dynamic", nodes=64, out=str(out)))
        assert out.exists()                           # "test_dynamic" → test_dynamic.trace
