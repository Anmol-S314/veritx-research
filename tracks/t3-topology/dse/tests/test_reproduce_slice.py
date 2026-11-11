from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO / "scripts"))
from reproduce_slice import slice_request

PINNED_DESIGN_HASH = (
    "b078985e46d85faa97db91ff0c8c27931702a745a6065bfd6162224917767ecc")


def test_slice_request_is_pinned():
    assert slice_request().design_hash() == PINNED_DESIGN_HASH


def test_reproduce_command_exists_and_is_executable():
    for name in ("reproduce_slice.sh", "verify_slice.sh",
                 "reproduce_slice.py", "verify_slice.py"):
        path = REPO / "scripts" / name
        assert path.is_file(), name
        assert path.stat().st_mode & 0o111 or name.endswith(".py"), name


@pytest.mark.skipif(shutil.which("verilator") is None,
                    reason="verilator not installed; cannot run the composed TB")
def test_reproduce_then_verify(tmp_path):
    out = tmp_path / "slice"
    repro = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "reproduce_slice.py"),
         "--out", str(out)],
        capture_output=True, text=True, timeout=600, cwd=str(REPO))
    manifest = json.loads((out / "project-top-manifest.json").read_text())
    assert manifest["scope"] == "COMPOSED_SLICE"
    assert manifest["design_hash"] == PINNED_DESIGN_HASH
    assert manifest["lint"]["status"] == "PASS"
    assert manifest["final_implementation"] is False
    assert preview_doc_is_sidecar(out)
    for row in manifest["files"]:
        digest = hashlib.sha256((out / "rtl" / row["path"]).read_bytes()).hexdigest()
        assert digest == row["sha256"], row["path"]

    expected_code = 0 if manifest["sim"]["status"] == "PASS" else 1
    assert repro.returncode == expected_code, repro.stdout[-2000:] + repro.stderr[-500:]

    verify = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "verify_slice.py"),
         "--out", str(out), "--hashes-only"],
        capture_output=True, text=True, timeout=120, cwd=str(REPO))
    assert verify.returncode == 0, (verify.stdout, verify.stderr)

    target = out / "rtl" / "project_top.sv"
    with target.open("a") as handle:
        handle.write("\n// tamper\n")
    tampered = subprocess.run(
        [sys.executable, str(REPO / "scripts" / "verify_slice.py"),
         "--out", str(out)],
        capture_output=True, text=True, timeout=300, cwd=str(REPO))
    assert tampered.returncode != 0
    assert "hash mismatch" in tampered.stdout


def preview_doc_is_sidecar(out: Path) -> bool:
    return json.loads((out / "rtl-preview.json").read_text())["scope"] == "TOPOLOGY_ONLY_PREVIEW"
