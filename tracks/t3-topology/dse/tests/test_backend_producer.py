"""Wave B-FINAL tests — execution-producer binding and safe evidence reuse.

B3.8i proves the input chain (bundle -> config -> bytes -> manifest).
B-FINAL binds the execution itself:

    canonical prepared inputs
        -> exact producer (binary digest pre-spawn, source revision, dirt)
        -> actual execution attempt (exact argv, recorded outcome)
        -> result evidence (content-addressed)
        -> safe reuse (refuse cross-producer / cross-input reuse)

Plus the B3.8i residual: serving_backend_evidence() validates the
canonical prepared/materialized chain before emitting anything.
"""
from __future__ import annotations

import platform
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, make_capturing_runner, prepare_booksim_standalone,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import run_qualified_booksim  # noqa: E402
from veritx_dse.backend.contracts import sha256_bytes  # noqa: E402
from veritx_dse.backend.evidence import (  # noqa: E402
    evidence_sha256_of, read_evidence, write_evidence,
)
from veritx_dse.backend.producer import (  # noqa: E402
    ProducerError, assert_pinned_producer, resolve_producer_identity,
    verify_evidence_binding,
)
from veritx_dse.backend.serving import (  # noqa: E402
    ServingBackendError, prepare_serving_booksim, serving_backend_evidence,
)
from veritx_dse.core.paths import REPO  # noqa: E402


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def _fake_binary(tmp_path, name="fake", content=b"fake-booksim-binary-v1"):
    path = tmp_path / name
    path.write_bytes(content)
    return path


def _run_ok(bundle, tmp_path, binary, *, workload=TRACE, seed=None):
    prepared = prepare_booksim_standalone(
        bundle, workload_trace=workload, seed=seed)
    return prepared, run_qualified_booksim(
        prepared, run_dir=tmp_path, repo_root=tmp_path,
        runner=make_capturing_runner(bundle, prepared.config),
        binary=binary)


class TestProducerResolution:
    def test_digest_matches_exact_bytes(self, tmp_path):
        binary = _fake_binary(tmp_path, content=b"producer-bytes-xyz")
        producer = resolve_producer_identity(binary, repo_root=tmp_path)
        assert producer.binary_sha256 == sha256_bytes(b"producer-bytes-xyz")
        assert producer.binary_size == len(b"producer-bytes-xyz")
        # tmp_path is not a git checkout: unpinned, stated honestly.
        assert producer.source_revision is None
        assert producer.source_dirty is None
        assert producer.source_dirty_digest is None
        assert not producer.source_pinned
        assert producer.tool_identity == platform.platform()

    def test_missing_binary_refuses(self, tmp_path):
        with pytest.raises(ProducerError, match="cannot hash"):
            resolve_producer_identity(tmp_path / "absent",
                                      repo_root=tmp_path)

    def test_empty_binary_refuses(self, tmp_path):
        binary = _fake_binary(tmp_path, content=b"")
        with pytest.raises(ProducerError, match="empty"):
            resolve_producer_identity(binary, repo_root=tmp_path)

    def test_unpinned_producer_refused_for_evidence_grade_reuse(
            self, tmp_path):
        producer = resolve_producer_identity(
            _fake_binary(tmp_path), repo_root=tmp_path)
        with pytest.raises(ProducerError, match="unpinned"):
            assert_pinned_producer(producer)

    def test_git_revision_and_clean_tree_are_pinned(self, tmp_path):
        git = tmp_path / "repo"
        git.mkdir()
        binary = git / "booksim"
        binary.write_bytes(b"v1-bytes")
        self._git(git, "init", "-q")
        self._git(git, "config", "user.email", "t@t")
        self._git(git, "config", "user.name", "t")
        (git / "src.txt").write_text("v1")
        self._git(git, "add", ".")
        self._git(git, "commit", "-qm", "v1")
        producer = resolve_producer_identity(binary, repo_root=git)
        head = subprocess.run(
            ["git", "-C", str(git), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=30)
        assert producer.source_revision == head.stdout.strip()
        assert producer.source_dirty is False
        assert producer.source_pinned
        assert_pinned_producer(producer)

    def test_dirty_tree_is_recorded_not_laundered(self, tmp_path):
        git = tmp_path / "repo"
        git.mkdir()
        binary = git / "booksim"
        binary.write_bytes(b"v1-bytes")
        self._git(git, "init", "-q")
        self._git(git, "config", "user.email", "t@t")
        self._git(git, "config", "user.name", "t")
        (git / "src.txt").write_text("v1")
        self._git(git, "add", ".")
        self._git(git, "commit", "-qm", "v1")
        clean = resolve_producer_identity(binary, repo_root=git)
        (git / "src.txt").write_text("v1-dirty")
        dirty = resolve_producer_identity(binary, repo_root=git)
        assert dirty.source_revision == clean.source_revision
        assert dirty.source_dirty is True
        assert not dirty.source_pinned
        assert dirty.source_dirty_digest != clean.source_dirty_digest
        with pytest.raises(ProducerError, match="dirty"):
            assert_pinned_producer(dirty)

    @staticmethod
    def _git(cwd, *args):
        proc = subprocess.run(["git", "-C", str(cwd), *args],
                              capture_output=True, text=True, timeout=30)
        if proc.returncode != 0:
            pytest.skip(f"git unavailable: {proc.stderr.strip()}")


class TestRunBindsProducer:
    def test_evidence_carries_pre_spawn_digest(self, bundle, tmp_path):
        binary = _fake_binary(tmp_path)
        _, ev = _run_ok(bundle, tmp_path, binary)
        assert ev.booksim_binary_sha256 == sha256_bytes(
            b"fake-booksim-binary-v1")
        assert ev.producer_tool_identity == platform.platform()
        # Exact invocation: the argv that actually spawned.
        assert ev.command == (str(binary), "config.cfg")
        assert ev.invocation_args == (("config-file", "config.cfg"),)
        assert ev.exit_status == 0
        assert ev.route_equivalence == "EXACT"

    def test_unreadable_binary_refuses_before_spawn(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        calls = {"n": 0}

        def never(cmd, cwd, timeout):
            calls["n"] += 1
            raise AssertionError("spawned with an unidentified producer")

        with pytest.raises(ProducerError, match="cannot hash"):
            run_qualified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=never, binary=tmp_path / "absent")
        assert calls["n"] == 0
        assert not (tmp_path / "backend").exists()

    def test_real_binary_evidence_is_source_pinned(self, bundle, tmp_path):
        from veritx_dse.simulation.booksim import (  # noqa: PLC0415
            find_booksim_bin,
        )
        try:
            binary = Path(find_booksim_bin(REPO))
        except FileNotFoundError:
            pytest.skip("no runnable BookSim binary")
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_qualified_booksim(
            prepared, run_dir=tmp_path, repo_root=REPO, timeout=120,
            binary=binary)
        assert ev.booksim_binary_sha256 == sha256_bytes(
            binary.read_bytes())
        producer = resolve_producer_identity(binary, repo_root=REPO)
        assert ev.producer_source_revision == producer.source_revision
        assert ev.producer_source_dirty == producer.source_dirty
        assert ev.producer_source_dirty_digest == \
            producer.source_dirty_digest
        assert producer.source_revision is not None


class TestSafeReuse:
    def _bound(self, bundle, tmp_path):
        binary = _fake_binary(tmp_path)
        prepared, ev = _run_ok(bundle, tmp_path, binary)
        producer = resolve_producer_identity(binary, repo_root=tmp_path)
        return prepared, ev, producer

    def test_matching_triple_reuses(self, bundle, tmp_path):
        prepared, ev, producer = self._bound(bundle, tmp_path)
        verify_evidence_binding(
            ev.to_dict(),
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer)
        # Persisted evidence re-verifies identically (result identity).
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        assert ref["sha256"] == evidence_sha256_of(ev.to_dict())
        verify_evidence_binding(
            read_evidence(ref["path"]),
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer)

    def test_config_substitution_refused(self, bundle, tmp_path):
        _, ev, producer = self._bound(bundle, tmp_path)
        with pytest.raises(ProducerError, match="different backend config"):
            verify_evidence_binding(
                ev.to_dict(), backend_config_hash="0" * 64,
                backend_input_hash=ev.backend_input_hash, producer=producer)

    def test_input_substitution_refused(self, bundle, tmp_path):
        prepared, ev, producer = self._bound(bundle, tmp_path)
        other = prepare_booksim_standalone(
            bundle, workload_trace=TRACE, seed=9)
        with pytest.raises(ProducerError, match="different backend inputs"):
            verify_evidence_binding(
                ev.to_dict(),
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=other.manifest.backend_input_hash(),
                producer=producer)

    def test_producer_substitution_refused(self, bundle, tmp_path):
        prepared, ev, _ = self._bound(bundle, tmp_path)
        other_binary = _fake_binary(tmp_path, name="other",
                                    content=b"different-producer")
        other_producer = resolve_producer_identity(
            other_binary, repo_root=tmp_path)
        with pytest.raises(ProducerError, match="different binary"):
            verify_evidence_binding(
                ev.to_dict(),
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=other_producer)

    def test_legacy_evidence_without_producer_refused(self, bundle,
                                                      tmp_path):
        _, ev, producer = self._bound(bundle, tmp_path)
        legacy = ev.to_dict()
        for key in ("booksim_binary_sha256", "producer_source_revision",
                    "producer_source_dirty", "producer_source_dirty_digest",
                    "producer_tool_identity"):
            del legacy[key]
        with pytest.raises(ProducerError, match="predates producer"):
            verify_evidence_binding(
                legacy, backend_config_hash=ev.backend_config_hash,
                backend_input_hash=ev.backend_input_hash, producer=producer)

    def test_tool_change_refused(self, bundle, tmp_path):
        prepared, ev, producer = self._bound(bundle, tmp_path)
        moved = replace(producer, tool_identity="other-platform")
        with pytest.raises(ProducerError, match="differs in"):
            verify_evidence_binding(
                ev.to_dict(),
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=moved)


class TestServingEvidenceResidual:
    def test_canonical_serving_evidence_emits(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        ev = serving_backend_evidence(prepared)
        assert ev["flit_bytes"] == 8
        assert ev["physical_dims"] == [2, 2]

    def test_forged_flit_bytes_cannot_emit(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        with pytest.raises(ServingBackendError, match="flit_bytes"):
            serving_backend_evidence(replace(prepared, flit_bytes=64))

    def test_forged_dims_cannot_emit(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        with pytest.raises(ServingBackendError, match="byte mismatch"):
            serving_backend_evidence(replace(prepared, physical_dims=(4,)))

    def test_forged_manifest_cannot_emit(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        forged = replace(prepared.manifest, seed=7, artifact_hash="")
        with pytest.raises(ServingBackendError, match="differs in"):
            serving_backend_evidence(replace(prepared, manifest=forged))


class TestFullChainCertification:
    """One run across the entire Wave-B chain, every link re-verified."""

    def test_bundle_to_reusable_evidence(self, bundle, tmp_path):
        from veritx_dse.backend.booksim import (  # noqa: PLC0415
            assert_canonical_booksim_projection,
            assert_canonical_prepared_booksim,
        )
        binary = _fake_binary(tmp_path)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        assert_canonical_booksim_projection(bundle, prepared.config)
        assert_canonical_prepared_booksim(prepared)
        producer = resolve_producer_identity(binary, repo_root=tmp_path)
        ev = run_qualified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=binary)
        assert ev.qualification == "EXECUTED_WITH_DECLARED_LOSS"
        assert ev.booksim_binary_sha256 == producer.binary_sha256
        verify_evidence_binding(
            ev.to_dict(),
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer)
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        verify_evidence_binding(
            read_evidence(ref["path"]),
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer)
