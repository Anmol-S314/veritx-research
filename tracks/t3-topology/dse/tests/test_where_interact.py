"""Contract tests for the usability commands: `veritx where` and `veritx interact`.

Seam: the real CLI subprocess (`python3 -m veritx_dse.cli ...`) — exit codes,
stdout/stderr, and files on disk. Resolution helpers get unit tests at their
own seam. These commands exist to kill the "what's the absolute path to a
trace/config/example" friction; the tests pin that a short name plus no other
context is enough to get a usable, copy-pasteable answer.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))


def _cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "veritx_dse.cli", *args],
        cwd=str(DSE), capture_output=True, text=True, timeout=60,
        stdin=subprocess.DEVNULL,
    )


# ── resolution helpers (unit seam) ────────────────────────────────────────

from veritx_dse.cli.cli import _resolve_asset  # noqa: E402


class TestResolveAsset:
    def test_finds_library_trace_by_bare_name(self):
        """'test_dynamic' → the library trace, no extension needed."""
        hit = _resolve_asset("test_dynamic", kind="trace")
        assert hit is not None and hit.exists()
        assert hit.suffix == ".trace"

    def test_finds_trace_with_extension(self):
        hit = _resolve_asset("test_dynamic.trace", kind="trace")
        assert hit is not None and hit.exists()

    def test_partial_name_matches(self):
        """'qwen3' should resolve to the qwen3 trace if it exists."""
        hit = _resolve_asset("qwen3", kind="trace")
        if hit is None:
            pytest.skip("no qwen3 trace in library")
        assert "qwen3" in hit.name

    def test_existing_relative_path_wins(self, tmp_path):
        f = tmp_path / "mine.trace"
        f.write_text("0 0 0 1 4\n")
        hit = _resolve_asset(str(f), kind="trace")
        assert hit == f.resolve()

    def test_unknown_name_returns_none_not_crash(self):
        assert _resolve_asset("definitely-not-here-xyz", kind="trace") is None

    def test_examples_kind(self):
        hit = _resolve_asset("moe_8npu", kind="example")
        assert hit is not None and hit.exists() and hit.suffix == ".json"


# ── `veritx where` (subprocess seam) ──────────────────────────────────────

class TestWhere:
    def test_where_trace_prints_copy_pasteable_path(self):
        r = _cli("where", "test_dynamic")
        assert r.returncode == 0, r.stderr
        combined = r.stdout + r.stderr
        assert "test_dynamic.trace" in combined
        assert str(DSE) in combined            # absolute, copy-pasteable
        assert ".trace" in combined

    def test_where_lists_candidates_on_ambiguity_or_miss(self):
        r = _cli("where", "zzz-no-such-asset")
        assert r.returncode == 1
        combined = r.stdout + r.stderr
        # Miss must teach, not just fail: show what IS available.
        assert "traces" in combined.lower()
        assert "test_dynamic" in combined

    def test_where_examples_kind(self):
        r = _cli("where", "moe_8npu")
        assert r.returncode == 0, r.stderr
        assert "moe_8npu.json" in r.stdout + r.stderr

    def test_where_json_mode(self):
        r = _cli("--json", "where", "test_dynamic")
        assert r.returncode == 0, r.stderr
        data = json.loads(r.stdout)
        assert data["resolved"].endswith(".trace")
        assert Path(data["resolved"]).exists()


# ── `veritx interact` (subprocess seam) ───────────────────────────────────

class TestInteract:
    def test_interact_eof_prints_menu_and_suggested_commands(self):
        """EOF on stdin → friendly overview with copy-pasteable next steps,
        exit 0. This is the 'I don't know where to start' entry point."""
        r = _cli("interact")
        assert r.returncode == 0, r.stderr
        combined = r.stdout + r.stderr
        assert "veritx where" in combined          # teaches the resolver
        assert "veritx trace validate" in combined # a real next step
        assert "veritx evaluate" in combined
