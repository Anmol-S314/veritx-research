"""tests/test_fixture_manifest.py — shipped fixtures are tracked, hashed, owned.

The defect this pins: the suite's required scientific inputs (trace library,
ASTRA size configs, the Slice-A regression trace) lived in `dse/archive/`,
which the repository's blanket `archive/` ignore rule swallowed. The same
commit then reported 61 failures in a fresh checkout against 23 in a working
worktree, purely because untracked local state supplied the inputs.

A fixture is a scientific input, so it gets the same treatment as evidence:
content hash, provenance, an owning test, and proof that Git will deliver it.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
MANIFEST = Path(__file__).resolve().parent / "fixtures" / "MANIFEST.json"


def _fixtures() -> list[dict]:
    doc = json.loads(MANIFEST.read_text())
    assert doc["schema_version"] == 1
    assert doc["fixtures"], "fixture manifest must not be empty"
    return doc["fixtures"]


def _git(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(["git", *args], cwd=REPO, check=True,
                              capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as exc:
        pytest.skip(f"git unavailable: {exc}")


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f["name"])
def test_fixture_exists_and_hash_matches(fixture):
    path = REPO / fixture["path"]
    assert path.is_file(), f"{fixture['path']} is declared but missing"
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    assert digest == fixture["sha256"], f"{fixture['path']} content changed"


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f["name"])
def test_fixture_is_tracked(fixture):
    tracked = set(_git("ls-files").stdout.splitlines())
    assert fixture["path"] in tracked, (
        f"{fixture['path']} is a required input but is not tracked; a fresh "
        "checkout will not have it")


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f["name"])
def test_fixture_is_not_gitignored(fixture):
    """The specific class: `archive/` must never swallow a live input again."""
    r = subprocess.run(["git", "check-ignore", "-q", fixture["path"]],
                       cwd=REPO, capture_output=True)
    if r.returncode not in (0, 1):
        pytest.skip("git check-ignore unavailable")
    assert r.returncode == 1, (
        f"{fixture['path']} is gitignored; tracked inputs must be deliverable")


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f["name"])
def test_fixture_declares_provenance_and_owner(fixture):
    assert fixture["provenance"].strip(), f"{fixture['name']}: no provenance"
    assert fixture["required_by"], f"{fixture['name']}: no owning test"
    for rel in fixture["required_by"]:
        assert (DSE / rel).is_file(), (
            f"{fixture['name']} claims owner {rel}, which does not exist")


@pytest.mark.parametrize("fixture", _fixtures(), ids=lambda f: f["name"])
def test_generated_fixtures_declare_a_generator(fixture):
    if fixture["generation"] != "GENERATED":
        return
    generator = REPO / fixture["generator"]
    assert generator.is_file(), (
        f"{fixture['name']} is GENERATED but {fixture['generator']} is missing; "
        "a generated fixture must be reproducible offline")
