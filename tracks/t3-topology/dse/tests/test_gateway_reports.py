"""Gateway report inventory and read-only serving.

The endpoints enumerate two server-chosen roots; the client never supplies a
filesystem path. These tests pin the media filter, the digest lookup, and the
symlink escape refusal.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
if str(DSE) not in sys.path:
    sys.path.insert(0, str(DSE))

from veritx_dse.gateway import app as gateway_app  # noqa: E402
from veritx_dse.gateway.errors import NotFound  # noqa: E402


@pytest.fixture()
def report_root(tmp_path, monkeypatch):
    root = tmp_path / "report"
    (root / "t3").mkdir(parents=True)
    (root / "t3" / "index.html").write_text(
        "<html>dashboard</html>", encoding="utf-8")
    (root / "plot.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (root / "notes.txt").write_text("not a report", encoding="utf-8")
    monkeypatch.setattr(gateway_app, "REPO", tmp_path)
    monkeypatch.setattr(gateway_app, "_REPORT_ROOTS", (root,))
    return root


def test_inventory_lists_only_report_media(report_root):
    entries = gateway_app._report_index()
    assert [entry["title"] for entry in entries] == ["T3 dashboard", "Plot"]
    assert entries[0]["kind"] == "dashboard"
    assert entries[0]["source_path"] == "report/t3/index.html"
    assert entries[1]["media_type"] == "image/png"


def test_report_file_resolves_digest_and_rejects_unknown(report_root):
    entry = gateway_app._report_index()[0]
    path, served = gateway_app._report_file(entry["report_id"])
    assert path == (report_root / "t3" / "index.html").resolve()
    assert served["title"] == "T3 dashboard"
    with pytest.raises(NotFound):
        gateway_app._report_file("not-a-report")


def test_symlink_outside_the_root_is_rejected(report_root, tmp_path):
    outside = tmp_path / "outside.html"
    outside.write_text("<html>outside</html>", encoding="utf-8")
    (report_root / "escape.html").symlink_to(outside)
    entries = {
        entry["source_path"]: entry for entry in gateway_app._report_index()
    }
    assert "report/escape.html" in entries
    with pytest.raises(NotFound):
        gateway_app._report_file(entries["report/escape.html"]["report_id"])
