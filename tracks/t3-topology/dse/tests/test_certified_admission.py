"""Certified-path producer admission (adversarial review of 978a38ed).

An unpinned / wrongly-built / dirty producer must be structurally
incapable of producing certified evidence: the certified evaluator refuses
before execution, so no candidate can reach CERTIFIED_PRODUCT.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_p2_optimization_truth import _defn, _real_base  # noqa: E402

from veritx_dse.core.build_manifest import write_build_manifest  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.optimization.candidate import make_candidate  # noqa: E402
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    RealCandidateEvaluator,
)
from veritx_dse.simulation.booksim import find_booksim_bin  # noqa: E402


def _copied_binary(tmp_path: Path) -> Path:
    src = Path(find_booksim_bin(REPO))
    dst = tmp_path / "booksim"
    shutil.copy2(src, dst)
    return dst


def _evaluate(binary: Path, tmp_path: Path):
    port = RealCandidateEvaluator(
        binary=str(binary), run_root=str(tmp_path / "runs"),
        network_clock_hz=10 ** 9, timeout_s=60)
    return port.evaluate(make_candidate(_real_base(), {"link_width": 64}))


def test_no_manifest_producer_is_not_certifiable(tmp_path):
    binary = _copied_binary(tmp_path)
    out = _evaluate(binary, tmp_path)
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.performance_result_id is None
    assert out.authenticated_proof is None


def test_manifest_with_wrong_recipe_is_not_certifiable(tmp_path):
    binary = _copied_binary(tmp_path)
    write_build_manifest(binary, repo_root=REPO, recipe_version="evil/v1")
    out = _evaluate(binary, tmp_path)
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.authenticated_proof is None


def test_dirty_manifest_is_not_certifiable(tmp_path):
    # a manifest that records a dirty build cannot certify
    repo = tmp_path / "dirty-repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.invalid"],
                   cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=repo, check=True)
    (repo / "f").write_text("a", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "A"], cwd=repo, check=True)
    (repo / "f").write_text("dirty", encoding="utf-8")  # uncommitted
    binary = _copied_binary(tmp_path)
    write_build_manifest(binary, repo_root=repo,
                         recipe_version="booksim2-fork/v1")
    out = _evaluate(binary, tmp_path)
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.authenticated_proof is None


def test_wrong_binary_after_manifest_is_not_certifiable(tmp_path):
    binary = _copied_binary(tmp_path)
    write_build_manifest(binary, repo_root=REPO,
                         recipe_version="booksim2-fork/v1")
    binary.write_bytes(binary.read_bytes() + b"\x00")  # replaced after build
    out = _evaluate(binary, tmp_path)
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.authenticated_proof is None
