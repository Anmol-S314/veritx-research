"""Build-time provenance manifest (P0.6).

The A->B counterexample: a binary built at commit A must never be
attributed to commit B just because the tree was later checked out at B.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.producer import (  # noqa: E402
    ProducerError, assert_pinned_producer, resolve_producer_identity,
)
from veritx_dse.core.build_manifest import (  # noqa: E402
    BuildManifest, BuildManifestError, load_and_verify_manifest,
    manifest_path_for, verify_build_manifest, write_build_manifest,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True,
                          capture_output=True, text=True).stdout.strip()


def _temp_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    (repo / "f").write_text("a", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "A")
    return repo


def _binary(tmp_path: Path) -> Path:
    path = tmp_path / "booksim"
    path.write_bytes(b"\x7fELF" + b"x" * 128)
    return path


def test_manifest_attributes_binary_to_build_revision_not_later_checkout(
        tmp_path):
    repo = _temp_repo(tmp_path)
    binary = _binary(tmp_path)
    write_build_manifest(binary, repo_root=repo, recipe_version="v1")
    rev_a = _git(repo, "rev-parse", "HEAD")
    # tree moves to B; binary untouched
    (repo / "f").write_text("b", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-qm", "B")
    rev_b = _git(repo, "rev-parse", "HEAD")
    assert rev_a != rev_b

    identity = resolve_producer_identity(binary, repo_root=repo)
    assert identity.source_revision == rev_a        # NOT the live HEAD B
    assert identity.manifest_verified is True
    assert identity.pinned is True
    assert_pinned_producer(identity)


def test_without_a_manifest_ambient_head_is_not_reusable(tmp_path):
    repo = _temp_repo(tmp_path)
    binary = _binary(tmp_path)
    identity = resolve_producer_identity(binary, repo_root=repo)
    assert identity.manifest_verified is False
    assert identity.pinned is False
    with pytest.raises(ProducerError, match="build-time manifest"):
        assert_pinned_producer(identity)


def test_binary_changed_after_manifest_refuses(tmp_path):
    repo = _temp_repo(tmp_path)
    binary = _binary(tmp_path)
    write_build_manifest(binary, repo_root=repo, recipe_version="v1")
    binary.write_bytes(b"\x7fELF" + b"y" * 128)      # binary replaced
    with pytest.raises(ProducerError):
        resolve_producer_identity(binary, repo_root=repo)


def test_manifest_roundtrip_and_strict_reader(tmp_path):
    repo = _temp_repo(tmp_path)
    binary = _binary(tmp_path)
    path = write_build_manifest(
        binary, repo_root=repo, recipe_version="v1", compiler="g++",
        compiler_version="15.2.0", build_config="Release",
        compile_flags=("-O3",))
    manifest = load_and_verify_manifest(binary, path=path)
    assert manifest is not None and manifest.recipe_version == "v1"
    assert manifest.compiler == "g++"
    # strict: unknown field refuses
    import json
    doc = json.loads(Path(path).read_text())
    doc["extra"] = 1
    with pytest.raises(BuildManifestError, match="unknown fields"):
        BuildManifest.from_dict(doc)


def test_missing_manifest_returns_none(tmp_path):
    binary = _binary(tmp_path)
    assert load_and_verify_manifest(binary) is None
    assert not manifest_path_for(binary).exists()


def test_recipe_version_mismatch_refuses(tmp_path):
    repo = _temp_repo(tmp_path)
    binary = _binary(tmp_path)
    path = write_build_manifest(binary, repo_root=repo, recipe_version="v1")
    manifest = load_and_verify_manifest(binary, path=path)
    with pytest.raises(BuildManifestError, match="recipe_version"):
        verify_build_manifest(binary, manifest, recipe_version="v2")


def test_release_build_records_the_toolchain_it_actually_uses():
    """C1.5: `CXX=clang++ make release-build` must not write a manifest that
    claims g++. One variable must drive both the build and the manifest."""
    repo = DSE.parents[2]
    makefile = (repo / "Makefile").read_text(encoding="utf-8")
    assert "RELEASE_CXX ?=" in makefile
    # the same variable is threaded into every backend build
    assert "third_party/booksim2/src CXX=$(RELEASE_CXX)" in makefile
    assert "CXX=$(RELEASE_CXX) JOBS=" in makefile
    # the manifest compiler is the build compiler, never a hardcoded g++
    assert "--compiler g++" not in makefile
    assert makefile.count("--compiler $(RELEASE_CXX)") == 2


def test_release_manifest_binds_the_release_to_its_facts(tmp_path):
    """C8: release-manifest.json records SHA, container pin state, backend
    manifests, schema versions and report digests."""
    import json
    import subprocess
    repo = DSE.parents[2]
    out = tmp_path / "release-manifest.json"
    subprocess.run(
        [sys.executable, "scripts/write_release_manifest.py", "--out",
         str(out), "--backend-manifest",
         "third_party/booksim2/src/booksim.build-manifest.json"],
        cwd=repo, check=True)
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema_version"] == 1
    assert doc["release_sha"]
    assert doc["schema_versions"]["prepared_booksim"] == 5
    assert doc["schema_versions"]["backend_evidence"] == 3
    assert doc["container"]["pinned_by_digest"] is False
    assert doc["backends"][0]["path"].endswith("booksim.build-manifest.json")
