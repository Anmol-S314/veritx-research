"""BookSim binary discovery must respect the platform executable suffix.

A frozen Windows build ships `booksim.exe`; resolving the POSIX name would
report the backend as missing and refuse every evaluation.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402


def _make(tmp_path: Path, name: str) -> Path:
    path = tmp_path / "third_party" / "booksim2" / "src" / name
    path.parent.mkdir(parents=True)
    path.write_bytes(b"\x7fELF-placeholder")
    return path


def test_windows_suffix_is_found(tmp_path, monkeypatch):
    expected = _make(tmp_path, "booksim.exe")
    monkeypatch.setattr(sys, "platform", "win32")
    assert find_booksim_bin(tmp_path) == expected


def test_posix_name_is_found(tmp_path, monkeypatch):
    expected = _make(tmp_path, "booksim")
    monkeypatch.setattr(sys, "platform", "linux")
    assert find_booksim_bin(tmp_path) == expected


def test_missing_binary_still_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(FileNotFoundError):
        find_booksim_bin(tmp_path)
