"""Wave B-FINAL.1 tests — producer and evidence-reuse integrity.

B-FINAL bound the producer; audit found four holes in the reuse half:

    unpinned producers could reuse matching evidence
    unknown dirt state passed as clean
    the \"dirty content digest\" hashed status lines, not content
    persisted result fields could be edited while reuse still passed
    plus a hash-to-exec TOCTOU window on the binary

These tests pin each fix, then certify the full chain end to end.
"""
from __future__ import annotations

import copy
import json
import platform
import shutil
import stat
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

from veritx_dse.backend.booksim import (  # noqa: E402
    _run_qualified_booksim_with_runner_for_test, run_qualified_booksim,
)
from veritx_dse.backend.contracts import sha256_bytes  # noqa: E402
from veritx_dse.backend.evidence import (  # noqa: E402
    BackendEvidenceError, EvidenceRef, evidence_sha256_of,
    read_verified_evidence, write_evidence,
)
from veritx_dse.backend.producer import (  # noqa: E402
    ProducerError, ProducerIdentity, assert_pinned_producer,
    resolve_producer_identity, verify_reusable_evidence,
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


def _git(cwd, *args):
    proc = subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, timeout=30)
    if proc.returncode != 0:
        pytest.skip(f"git unavailable: {proc.stderr.strip()}")
    return proc.stdout


def make_pinned_repo(base, name="repo"):
    """A scratch git checkout with one committed tracked file."""
    git = Path(base) / name
    git.mkdir(parents=True, exist_ok=True)
    _git(git, "init", "-q")
    _git(git, "config", "user.email", "t@t")
    _git(git, "config", "user.name", "t")
    (git / "src.txt").write_text("v1")
    _git(git, "add", "src.txt")
    _git(git, "commit", "-qm", "v1")
    return git


def write_binary(repo, name="fake", content=b"fake-booksim-binary-v1"):
    path = Path(repo) / name
    path.write_bytes(content)
    return path


def copy_real_binary(git, name="booksim"):
    """Stage the real BookSim binary inside a scratch repo (untracked)."""
    from veritx_dse.simulation.booksim import (  # noqa: PLC0415
        find_booksim_bin,
    )
    try:
        src = Path(find_booksim_bin(REPO))
    except FileNotFoundError:
        pytest.skip("no runnable BookSim binary")
    dst = Path(git) / name
    shutil.copy(src, dst)
    dst.chmod(dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP
              | stat.S_IXOTH)
    return dst


def make_repo_with_real_binary(base, name="realrepo"):
    git = make_pinned_repo(base, name)
    return git, copy_real_binary(git)


def _run_real(bundle, run_dir, binary, repo_root, *, workload=TRACE,
              seed=None, timeout=120):
    """Production-API execution (no injected transport)."""
    prepared = prepare_booksim_standalone(
        bundle, workload_trace=workload, seed=seed)
    return prepared, run_qualified_booksim(
        prepared, run_dir=run_dir, repo_root=repo_root, timeout=timeout,
        binary=binary)


def _run_ok(bundle, run_dir, binary, repo_root, *, workload=TRACE,
            seed=None):
    prepared = prepare_booksim_standalone(
        bundle, workload_trace=workload, seed=seed)
    return prepared, _run_qualified_booksim_with_runner_for_test(
        prepared, run_dir=run_dir, repo_root=repo_root,
        runner=make_capturing_runner(bundle, prepared.config),
        binary=binary)


class TestProducerResolution:
    def test_digest_matches_exact_bytes(self, tmp_path):
        binary = tmp_path / "fake"
        binary.write_bytes(b"producer-bytes-xyz")
        producer = resolve_producer_identity(binary, repo_root=tmp_path)
        assert producer.binary_sha256 == sha256_bytes(b"producer-bytes-xyz")
        assert producer.binary_size == len(b"producer-bytes-xyz")
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
        binary = tmp_path / "fake"
        binary.write_bytes(b"")
        with pytest.raises(ProducerError, match="empty"):
            resolve_producer_identity(binary, repo_root=tmp_path)

    def test_clean_tree_is_pinned(self, tmp_path):
        git = make_pinned_repo(tmp_path)
        binary = write_binary(git)
        producer = resolve_producer_identity(binary, repo_root=git)
        head = _git(git, "rev-parse", "HEAD").strip()
        assert producer.source_revision == head
        assert producer.source_dirty is False
        assert producer.source_dirty_digest == sha256_bytes(b"")
        assert producer.source_pinned
        assert_pinned_producer(producer)

    def test_dirty_tree_is_recorded_not_laundered(self, tmp_path):
        git = make_pinned_repo(tmp_path)
        binary = write_binary(git)
        clean = resolve_producer_identity(binary, repo_root=git)
        (git / "src.txt").write_text("v1-dirty")
        dirty = resolve_producer_identity(binary, repo_root=git)
        assert dirty.source_revision == clean.source_revision
        assert dirty.source_dirty is True
        assert not dirty.source_pinned
        assert dirty.source_dirty_digest != clean.source_dirty_digest
        with pytest.raises(ProducerError, match="dirty"):
            assert_pinned_producer(dirty)

    def test_different_edits_to_same_file_differ(self, tmp_path):
        git = make_pinned_repo(tmp_path)
        binary = write_binary(git)
        (git / "src.txt").write_text("change A with some substance")
        digest_b = resolve_producer_identity(
            binary, repo_root=git).source_dirty_digest
        (git / "src.txt").write_text("completely different change B")
        resolved_c = resolve_producer_identity(binary, repo_root=git)
        assert resolved_c.source_dirty is True
        assert resolved_c.source_dirty_digest != digest_b

    def test_staged_content_is_represented(self, tmp_path):
        git = make_pinned_repo(tmp_path)
        binary = write_binary(git)
        (git / "src.txt").write_text("staged version one")
        _git(git, "add", "src.txt")
        digest_one = resolve_producer_identity(
            binary, repo_root=git).source_dirty_digest
        (git / "src.txt").write_text("staged version two")
        _git(git, "add", "src.txt")
        digest_two = resolve_producer_identity(
            binary, repo_root=git).source_dirty_digest
        assert digest_one != digest_two

    def test_unpinned_reuse_refused_for_evidence_grade(self, tmp_path):
        producer = resolve_producer_identity(
            write_binary(tmp_path), repo_root=tmp_path)
        with pytest.raises(ProducerError, match="revision unavailable"):
            assert_pinned_producer(producer)

    def test_unknown_dirt_state_refused(self):
        producer = ProducerIdentity(
            binary_sha256=sha256_bytes(b"x"), binary_size=1,
            source_revision="deadbeef", source_dirty=None,
            source_dirty_digest=None, tool_identity=platform.platform())
        assert not producer.source_pinned
        with pytest.raises(ProducerError, match="unknown"):
            assert_pinned_producer(producer)


class TestRunBindsProducer:
    def test_evidence_carries_pre_spawn_digest(self, bundle, tmp_path):
        git = make_pinned_repo(tmp_path)
        binary = write_binary(git)
        _, ev = _run_ok(bundle, tmp_path / "run", binary, git)
        assert ev.booksim_binary_sha256 == sha256_bytes(
            b"fake-booksim-binary-v1")
        assert ev.producer_tool_identity == platform.platform()
        assert ev.command == (str(binary.resolve()), "config.cfg")
        assert ev.execution_transport == "TEST_INJECTED"
        assert ev.invocation_args == (("config-file", "config.cfg"),)
        assert ev.exit_status == 0
        assert ev.route_equivalence == "EXACT"

    def test_unreadable_binary_refuses_before_spawn(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        calls = {"n": 0}

        def never(cmd, cwd, timeout):
            calls["n"] += 1
            raise AssertionError("spawned with an unidentified producer")

        with pytest.raises(ProducerError, match="cannot resolve"):
            _run_qualified_booksim_with_runner_for_test(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=never, binary=tmp_path / "absent")
        assert calls["n"] == 0
        assert not (tmp_path / "backend").exists()

    def test_binary_mutation_before_spawn_refused(
            self, bundle, tmp_path, monkeypatch):
        import veritx_dse.backend.booksim as booksim_mod  # noqa: PLC0415
        binary = write_binary(tmp_path, content=b"binary-A-bytes")
        producer_a = resolve_producer_identity(binary, repo_root=tmp_path)
        # The binary is replaced after initial resolution but before the
        # runner is invoked; the pre-spawn recheck must catch it.
        binary.write_bytes(b"binary-B-replacement")
        monkeypatch.setattr(
            booksim_mod, "resolve_producer_identity",
            lambda *a, **k: producer_a)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        calls = {"n": 0}

        def never(cmd, cwd, timeout):
            calls["n"] += 1
            raise AssertionError("spawned a substituted producer")

        with pytest.raises(ProducerError,
                           match="changed between resolution and spawn"):
            _run_qualified_booksim_with_runner_for_test(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=never, binary=binary)
        assert calls["n"] == 0

    def test_real_binary_evidence_matches_pinned_producer(
            self, bundle, tmp_path):
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
        git, binary = make_repo_with_real_binary(tmp_path)
        prepared, ev = _run_real(bundle, tmp_path / "run", binary, git)
        assert ev.execution_transport == "SUPERVISED_PROCESS"
        producer = resolve_producer_identity(binary, repo_root=git)
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        assert isinstance(ref, EvidenceRef)
        assert ref.sha256 == evidence_sha256_of(ev.to_dict())
        return prepared, ev, producer, ref, git

    def test_matching_triple_reuses(self, bundle, tmp_path):
        prepared, ev, producer, ref, _ = self._bound(bundle, tmp_path)
        got = verify_reusable_evidence(
            ref,
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer)
        assert got == ev.to_dict()

    def test_unpinned_producer_reuse_refused(self, bundle, tmp_path):
        prepared, ev, _, ref, _ = self._bound(bundle, tmp_path)
        loose = resolve_producer_identity(
            write_binary(tmp_path, name="loose", content=b"other-bytes"),
            repo_root=tmp_path)
        assert not loose.source_pinned
        with pytest.raises(ProducerError, match="revision unavailable"):
            verify_reusable_evidence(
                ref,
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=loose)

    def test_dirty_producer_reuse_refused(self, bundle, tmp_path):
        prepared, ev, _, ref, git = self._bound(bundle, tmp_path)
        (git / "src.txt").write_text("post-run dirt")
        dirty = resolve_producer_identity(git / "booksim", repo_root=git)
        assert dirty.source_dirty is True
        with pytest.raises(ProducerError, match="dirty"):
            verify_reusable_evidence(
                ref,
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=dirty)

    def test_unknown_dirt_reuse_refused(self, bundle, tmp_path):
        prepared, ev, producer, ref, _ = self._bound(bundle, tmp_path)
        unknown = replace(producer, source_dirty=None,
                          source_dirty_digest=None)
        with pytest.raises(ProducerError, match="unknown"):
            verify_reusable_evidence(
                ref,
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=unknown)

    def test_config_substitution_refused(self, bundle, tmp_path):
        _, ev, producer, ref, _ = self._bound(bundle, tmp_path)
        with pytest.raises(ProducerError, match="different backend config"):
            verify_reusable_evidence(
                ref, backend_config_hash="0" * 64,
                backend_input_hash=ev.backend_input_hash, producer=producer)

    def test_input_substitution_refused(self, bundle, tmp_path):
        _, ev, producer, ref, _ = self._bound(bundle, tmp_path)
        other = prepare_booksim_standalone(
            bundle, workload_trace=TRACE, seed=9)
        with pytest.raises(ProducerError, match="different backend inputs"):
            verify_reusable_evidence(
                ref, backend_config_hash=ev.backend_config_hash,
                backend_input_hash=other.manifest.backend_input_hash(),
                producer=producer)

    def test_producer_substitution_refused(self, bundle, tmp_path):
        _, ev, _, ref, git = self._bound(bundle, tmp_path)
        other_binary = write_binary(git, name="other",
                                    content=b"different-producer")
        other_producer = resolve_producer_identity(
            other_binary, repo_root=git)
        with pytest.raises(ProducerError, match="different binary"):
            verify_reusable_evidence(
                ref, backend_config_hash=ev.backend_config_hash,
                backend_input_hash=ev.backend_input_hash,
                producer=other_producer)

    def test_legacy_evidence_without_producer_refused(self, bundle,
                                                      tmp_path):
        _, ev, producer, _, _ = self._bound(bundle, tmp_path)
        legacy = ev.to_dict()
        for key in ("booksim_binary_sha256", "execution_transport",
                    "producer_source_revision", "producer_source_dirty",
                    "producer_source_dirty_digest"):
            del legacy[key]
        legacy_ref = write_evidence(tmp_path / "legacy", legacy)
        with pytest.raises(ProducerError, match="non-production"):
            verify_reusable_evidence(
                legacy_ref, backend_config_hash=ev.backend_config_hash,
                backend_input_hash=ev.backend_input_hash, producer=producer)

    def test_tool_identity_is_attempt_metadata_not_science(self, bundle,
                                                           tmp_path):
        """evidence-v2: platform text never enters scientific reuse."""
        _, ev, producer, ref, _ = self._bound(bundle, tmp_path)
        moved = replace(producer, tool_identity="other-platform")
        got = verify_reusable_evidence(
            ref, backend_config_hash=ev.backend_config_hash,
            backend_input_hash=ev.backend_input_hash, producer=moved)
        assert got == ev.to_dict()
        assert "producer_tool_identity" not in got
        # The run STILL records the environment text — just elsewhere.
        assert ev.producer_tool_identity
        assert ev.to_attempt_dict()["producer_tool_identity"] == \
            ev.producer_tool_identity

    def test_naked_path_cannot_reuse(self, bundle, tmp_path):
        _, ev, producer, ref, _ = self._bound(bundle, tmp_path)
        with pytest.raises(BackendEvidenceError, match="EvidenceRef"):
            read_verified_evidence(ref.path)
        with pytest.raises(BackendEvidenceError, match="EvidenceRef"):
            verify_reusable_evidence(
                ref.path, backend_config_hash=ev.backend_config_hash,
                backend_input_hash=ev.backend_input_hash, producer=producer)


class TestResultTamper:
    def _persisted(self, bundle, tmp_path):
        git, binary = make_repo_with_real_binary(tmp_path)
        prepared, ev = _run_real(bundle, tmp_path / "run", binary, git)
        producer = resolve_producer_identity(binary, repo_root=git)
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        raw = Path(ref.path).read_bytes()
        return prepared, ev, producer, ref, raw

    def _mutators(self, evidence):
        assert isinstance(evidence["stats"]["latency"], (int, float))
        assert evidence["route_pairs_compared"] > 0
        assert isinstance(evidence["semantic_loss"], list)
        return [
            ("stats.latency",
             lambda d: d["stats"].__setitem__("latency", 0.1)),
            ("qualification",
             lambda d: d.__setitem__("qualification", "EXECUTED_EXACT")),
            ("route_equivalence",
             lambda d: d.__setitem__("route_equivalence", "DIVERGENT")),
            ("route_executed_sha256",
             lambda d: d.__setitem__(
                 "route_executed_sha256",
                 "f" + d["route_executed_sha256"][1:])),
            ("route_expected_sha256",
             lambda d: d.__setitem__(
                 "route_expected_sha256",
                 "e" + d["route_expected_sha256"][1:])),
            ("route_pairs_compared",
             lambda d: d.__setitem__(
                 "route_pairs_compared", d["route_pairs_compared"] + 1)),
            ("semantic_loss",
             lambda d: d.__setitem__(
                 "semantic_loss", d["semantic_loss"] + [{"forged": True}])),
            ("parser_version",
             lambda d: d.__setitem__(
                 "parser_version", "forged/parser")),
            ("exit_status",
             lambda d: d.__setitem__("exit_status", 1)),
            ("seed",
             lambda d: d.__setitem__("seed", 424242)),
        ]

    def test_each_result_field_tamper_refuses(self, bundle, tmp_path):
        prepared, ev, producer, ref, raw = self._persisted(bundle, tmp_path)
        path = Path(ref.path)
        for label, mutate in self._mutators(ev.to_dict()):
            forged = copy.deepcopy(ev.to_dict())
            mutate(forged)
            path.write_bytes(json.dumps(forged).encode())
            with pytest.raises(BackendEvidenceError,
                               match="digest|modified"):
                verify_reusable_evidence(
                    ref,
                    backend_config_hash=prepared.config
                    .backend_config_hash(),
                    backend_input_hash=prepared.manifest
                    .backend_input_hash(),
                    producer=producer)
            path.write_bytes(raw)
        # Untouched bytes still verify after every tamper round.
        got = verify_reusable_evidence(
            ref,
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer)
        assert got == ev.to_dict()


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
    """Bundle -> reusable result via the production transport."""

    def test_chain_and_all_mutations(self, bundle, tmp_path):
        from veritx_dse.backend.booksim import (  # noqa: PLC0415
            assert_canonical_booksim_projection,
            assert_canonical_prepared_booksim,
        )
        git, binary = make_repo_with_real_binary(tmp_path)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        assert_canonical_booksim_projection(bundle, prepared.config)
        assert_canonical_prepared_booksim(prepared)
        producer = resolve_producer_identity(binary, repo_root=git)
        assert_pinned_producer(producer)
        # No injected callback may satisfy this test: production API only.
        ev = run_qualified_booksim(
            prepared, run_dir=tmp_path / "run", repo_root=git,
            timeout=120, binary=binary)
        assert ev.execution_transport == "SUPERVISED_PROCESS"
        assert ev.booksim_binary_sha256 == producer.binary_sha256
        assert ev.route_equivalence == "EXACT"
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        config_hash = prepared.config.backend_config_hash()
        input_hash = prepared.manifest.backend_input_hash()

        def reuse(**over):
            kwargs = {"backend_config_hash": config_hash,
                      "backend_input_hash": input_hash,
                      "producer": producer}
            kwargs.update(over)
            return verify_reusable_evidence(ref, **kwargs)

        assert reuse() == ev.to_dict()

        # Fabric/config identity moves -> reuse refuses.
        with pytest.raises(ProducerError, match="different backend config"):
            reuse(backend_config_hash="0" * 64)
        # Workload/input identity moves -> reuse refuses.
        other_input = prepare_booksim_standalone(
            bundle, workload_trace=TRACE + b"20 1 3 0 1\n")
        with pytest.raises(ProducerError, match="different backend inputs"):
            reuse(backend_input_hash=other_input.manifest
                  .backend_input_hash())
        # Producer bytes move -> reuse refuses.
        real_bytes = binary.read_bytes()
        binary.write_bytes(b"replacement-producer-bytes")
        moved = resolve_producer_identity(binary, repo_root=git)
        with pytest.raises(ProducerError, match="different binary"):
            reuse(producer=moved)
        # Tracked source state moves -> reuse refuses.
        binary.write_bytes(real_bytes)
        (git / "src.txt").write_text("post-run source change")
        dirtied = resolve_producer_identity(binary, repo_root=git)
        assert dirtied.source_dirty is True
        with pytest.raises(ProducerError, match="differs in|dirty"):
            reuse(producer=dirtied)
        # Evidence bytes move -> digest verification refuses.
        path = Path(ref.path)
        raw = path.read_bytes()
        tampered = copy.deepcopy(ev.to_dict())
        tampered["stats"]["latency"] = 0.001
        path.write_bytes(json.dumps(tampered).encode())
        with pytest.raises(BackendEvidenceError, match="digest|modified"):
            reuse()
        path.write_bytes(raw)
        assert reuse() == ev.to_dict()
