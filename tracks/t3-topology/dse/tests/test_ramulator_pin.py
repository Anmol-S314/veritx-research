"""Pin and provenance tests for the vendored Ramulator backend.

These are deliberately separate from the contract tests: they prove the
built extension is the one the tracked vendor source produced, so a run can
never claim a revision the tree does not contain.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.core.build_manifest import (  # noqa: E402
    load_and_verify_manifest, manifest_path_for,
)
from veritx_dse.simulation.ramulator import (  # noqa: E402
    RAMULATOR_RECIPE_VERSION, VENDOR_PIN, RamulatorBackend, RamulatorError,
    discover,
)

VENDOR = REPO / "third_party" / "ramulator2"
EXT = (VENDOR / "python" / "ramulator" /
       f"_ramulator{sysconfig.get_config_var('EXT_SUFFIX')}")
needs_backend = pytest.mark.skipif(
    not EXT.is_file(),
    reason="ramulator extension for this interpreter is not built")


def _manifest():
    manifest = load_and_verify_manifest(
        EXT, recipe_version=RAMULATOR_RECIPE_VERSION)
    assert manifest is not None
    return manifest


def test_vendor_pin_names_a_repo_commit():
    proc = subprocess.run(
        ["git", "cat-file", "-t", VENDOR_PIN], cwd=str(REPO),
        capture_output=True, text=True, timeout=30)
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "commit"


@needs_backend
def test_manifest_verifies_and_matches_pin_and_binary():
    manifest = _manifest()
    digest = hashlib.sha256(EXT.read_bytes()).hexdigest()
    assert manifest.source_revision == VENDOR_PIN
    assert manifest.source_dirty is False
    assert manifest.source_paths == ("third_party/ramulator2",)
    assert manifest.recipe_version == RAMULATOR_RECIPE_VERSION
    assert manifest.binary_sha256 == digest
    assert manifest.binary_size == EXT.stat().st_size

    backend = discover(python_exe=sys.executable, vendor_dir=VENDOR)
    assert backend.commit == VENDOR_PIN
    assert backend.manifest is not None
    producer = backend.producer()
    assert producer["commit_sha"] == VENDOR_PIN
    assert producer["binary_sha256"] == f"sha256:{digest}"


@needs_backend
def test_tampered_binary_is_refused(tmp_path):
    ext = tmp_path / EXT.name
    shutil.copyfile(EXT, ext)
    shutil.copyfile(manifest_path_for(EXT), manifest_path_for(ext))
    with open(ext, "ab") as handle:
        handle.write(b"\0")
    backend = RamulatorBackend(python_exe=sys.executable,
                               package_dir=tmp_path, ext_path=ext)
    with pytest.raises(RamulatorError, match="manifest"):
        backend.verified_manifest()


@needs_backend
def test_wrong_revision_is_refused(tmp_path):
    ext = tmp_path / EXT.name
    shutil.copyfile(EXT, ext)
    raw = json.loads(manifest_path_for(EXT).read_text(encoding="utf-8"))
    raw["source_revision"] = "0" * 40
    manifest_path_for(ext).write_text(json.dumps(raw), encoding="utf-8")
    backend = RamulatorBackend(python_exe=sys.executable,
                               package_dir=tmp_path, ext_path=ext)
    with pytest.raises(RamulatorError, match="VENDOR_PIN"):
        backend.verified_manifest()


@needs_backend
def test_discover_refuses_tampered_canonical_manifest(monkeypatch, tmp_path):
    import veritx_dse.simulation.ramulator as sim

    vendor = tmp_path / "vendor"
    ext = vendor / "python" / "ramulator" / EXT.name
    ext.parent.mkdir(parents=True)
    shutil.copyfile(EXT, ext)
    shutil.copyfile(manifest_path_for(EXT), manifest_path_for(ext))
    with open(ext, "ab") as handle:
        handle.write(b"\0")
    monkeypatch.setattr(sim, "VENDOR_DIR", vendor)
    with pytest.raises(RamulatorError, match="manifest"):
        sim.discover(python_exe=sys.executable, vendor_dir=vendor)

