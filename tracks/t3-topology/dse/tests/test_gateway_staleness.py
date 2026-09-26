"""Gateway staleness detection.

The gateway runs WITHOUT --reload, so a backend commit does not reach a
running process and the failure is SILENT: the process keeps answering 200
with payloads built by the OLD code. That caused two real incidents, the
second one AFTER the fix had landed.

These tests pin the control that makes staleness observable.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.gateway import staleness as st


def test_a_fresh_process_is_not_stale():
    """LOADED_AT is recorded at import, after the sources it loaded."""
    info = st.staleness()
    assert info["stale"] is False
    assert info["pid"] > 0
    assert info["source_age_s"] == 0.0


def test_staleness_flips_when_source_is_newer(tmp_path):
    """A source file newer than the process MUST report stale."""
    src = tmp_path / "pkg"
    src.mkdir()
    (src / "mod.py").write_text("x = 1\n")
    # Pretend the process loaded before that file was written.
    old = st.newest_source_mtime(src)
    assert old is not None
    newer = old + 10
    import os
    os.utime(src / "mod.py", (newer, newer))
    assert st.newest_source_mtime(src) > old


def test_health_reports_stale_as_a_status(monkeypatch):
    """The health endpoint is the ONE place a stale process announces
    itself — a bare {"status": "ok"} would be a lie."""
    from veritx_dse.gateway.app import create_app
    monkeypatch.setattr(
        "veritx_dse.gateway.app.staleness",
        lambda: {"stale": True, "reason": "source newer than process",
                 "pid": 1, "loaded_at": 0.0})
    app = create_app()
    route = next(r for r in app.routes
                 if getattr(r, "path", None) == "/api/v1/health")
    body = route.endpoint()
    assert body["status"] == "stale"
    assert body["code"]["stale"] is True


def test_health_is_ok_when_current(monkeypatch):
    from veritx_dse.gateway.app import create_app
    monkeypatch.setattr(
        "veritx_dse.gateway.app.staleness",
        lambda: {"stale": False, "pid": 1, "loaded_at": 0.0,
                 "newest_source_mtime": 0.0, "source_age_s": 0.0})
    app = create_app()
    route = next(r for r in app.routes
                 if getattr(r, "path", None) == "/api/v1/health")
    body = route.endpoint()
    assert body["status"] == "ok"
    assert body["code"]["stale"] is False


def test_stale_info_carries_a_restart_hint():
    """Staleness must be actionable, not merely reported."""
    info = st.staleness()
    assert set(info) >= {"stale", "pid", "loaded_at"}


def test_unreadable_tree_does_not_crash():
    info = st.staleness()
    assert "stale" in info
    assert st.newest_source_mtime(Path("/nonexistent/xyz")) is None


# ══ gateway backend resolution ═════════════════════════════════════════
#
# BUG THIS PINS. The gateway read VERITX_BOOKSIM_BIN and passed None when
# unset, WITHOUT falling back to find_booksim_bin(). Every other consumer
# falls back. So on a machine with a built, working BookSim the gateway
# alone reported `backend: MISSING - "no qualified backend configured (set
# VERITX_BOOKSIM_BIN)"` and refused every evaluation.

def test_gateway_falls_back_to_the_standard_booksim_search():
    from veritx_dse.gateway.app import resolve_booksim_bin
    resolved = resolve_booksim_bin(None)
    assert resolved is not None, (
        "the gateway must fall back to find_booksim_bin, not report MISSING "
        "just because VERITX_BOOKSIM_BIN is unset")
    assert resolved.is_file()
    assert resolved.name == "booksim"


def test_gateway_env_override_still_wins():
    from veritx_dse.gateway.app import resolve_booksim_bin
    assert resolve_booksim_bin("/tmp/custom/booksim") == Path("/tmp/custom/booksim")


def test_gateway_reports_none_only_when_genuinely_absent(monkeypatch):
    """MISSING must mean missing, not unset."""
    from veritx_dse.gateway import app as gw
    import veritx_dse.simulation.booksim as bs

    def boom(_root):
        raise FileNotFoundError("no binary")
    monkeypatch.setattr(bs, "find_booksim_bin", boom)
    assert gw.resolve_booksim_bin(None) is None


def test_config_from_env_store_path_is_the_real_store():
    """`repo` in config_from_env is tracks/t3-topology (the store really
    lives there) and must NOT be swapped for the repository root."""
    from veritx_dse.gateway.app import config_from_env
    cfg = config_from_env()
    assert cfg.store_root.parts[-2:] == ("runs", "studio-store")
    assert cfg.store_root.is_dir(), \
        "store_root must point at the existing studio store"


def test_config_from_env_backend_is_ready_when_booksim_is_built():
    from veritx_dse.gateway.app import config_from_env
    cfg = config_from_env()
    assert cfg.booksim_bin is not None
    assert cfg.booksim_bin.is_file()
    # The two roots are DIFFERENT and both must be right.
    assert cfg.store_root != cfg.booksim_bin.parent
