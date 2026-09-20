"""Wave B-FINAL.2 tests — certified execution authenticity.

The reuse chain is sealed; what remains is the word \"executed\":

    an injected runner must not fabricate reusable EXECUTED_* evidence
    the route dump must be fresh output of the current attempt
    the binary path must be canonical before hashing and execution
    digest-verified reuse must be the only public reuse API
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, _FakeResult, _OK_STDOUT, expected_dump_text,
    prepare_booksim_standalone,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_backend_producer import (  # noqa: E402
    make_pinned_repo, make_repo_with_real_binary, write_binary,
)
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    ROUTE_DUMP_FILE, BookSimRouteError,
    _run_qualified_booksim_with_runner_for_test, run_qualified_booksim,
)
from veritx_dse.backend.contracts import sha256_bytes  # noqa: E402
from veritx_dse.backend.evidence import (  # noqa: E402
    BackendEvidenceError, write_evidence,
)
from veritx_dse.backend.producer import (  # noqa: E402
    ProducerError, resolve_producer_identity, verify_reusable_evidence,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def _never(calls):
    def runner(cmd, cwd, timeout):
        calls["n"] += 1
        raise AssertionError("spawned despite a pre-spawn refusal")
    return runner


class TestRunnerForgery:
    def test_production_api_has_no_runner_seam(self):
        assert "runner" not in inspect.signature(
            run_qualified_booksim).parameters

    def test_fake_runner_cannot_fabricate_reusable_evidence(
            self, bundle, tmp_path):
        from test_backend_booksim import (  # noqa: PLC0415
            make_capturing_runner,
        )
        git = make_pinned_repo(tmp_path)
        binary = write_binary(git)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)

        def forging_runner(cmd, cwd, timeout):
            # Never executes cmd: writes a perfect dump, returns
            # plausible stdout. Indistinguishable from success downstream
            # unless the transport is bound.
            Path(cwd, ROUTE_DUMP_FILE).write_text(
                expected_dump_text(bundle, prepared.config))
            return _FakeResult(stdout=_OK_STDOUT)

        ev = _run_qualified_booksim_with_runner_for_test(
            prepared, run_dir=tmp_path, repo_root=git,
            runner=forging_runner, binary=binary)
        assert ev.route_equivalence == "EXACT"
        assert ev.qualification == "EXECUTED_WITH_DECLARED_LOSS"
        assert ev.execution_transport == "TEST_INJECTED"
        producer = resolve_producer_identity(binary, repo_root=git)
        ref = write_evidence(tmp_path, ev.to_dict())
        with pytest.raises(ProducerError, match="non-production"):
            verify_reusable_evidence(
                ref,
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=producer)

    def test_capturing_seam_products_are_marked(self, bundle, tmp_path):
        from test_backend_booksim import (  # noqa: PLC0415
            make_capturing_runner,
        )
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = _run_qualified_booksim_with_runner_for_test(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=Path("/bin/true"))
        assert ev.execution_transport == "TEST_INJECTED"


class TestRouteFreshness:
    def test_preexisting_exact_dump_refused_before_spawn(
            self, bundle, tmp_path):
        from test_backend_booksim import (  # noqa: PLC0415
            make_capturing_runner,
        )
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        backend_dir = tmp_path / "backend"
        backend_dir.mkdir(parents=True)
        # An exact valid dump from an "earlier attempt".
        (backend_dir / ROUTE_DUMP_FILE).write_text(
            expected_dump_text(bundle, prepared.config))
        calls = {"n": 0}
        with pytest.raises(BookSimRouteError, match="already exists"):
            _run_qualified_booksim_with_runner_for_test(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=_never(calls), binary=Path("/bin/true"))
        assert calls["n"] == 0

    def test_missing_dump_still_refused(self, bundle, tmp_path):
        from test_backend_booksim import (  # noqa: PLC0415
            make_capturing_runner,
        )
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        with pytest.raises(BookSimRouteError, match="no route dump"):
            _run_qualified_booksim_with_runner_for_test(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=make_capturing_runner(
                    bundle, prepared.config, missing_dump=True),
                binary=Path("/bin/true"))


class TestBinaryPathCanonicalization:
    def test_relative_path_resolves_before_cwd_change(
            self, bundle, tmp_path, monkeypatch):
        import os  # noqa: PLC0415
        real_a = tmp_path / "caller"
        (real_a / "build").mkdir(parents=True)
        binary_a = real_a / "build" / "booksim"
        binary_a.write_bytes(b"binary-A-bytes")
        # A conflicting relative path under the future backend dir.
        backend_dir = tmp_path / "run" / "backend"
        (backend_dir / "build").mkdir(parents=True)
        (backend_dir / "build" / "booksim").write_bytes(b"binary-B-bytes")
        monkeypatch.chdir(real_a)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        capture: dict = {}

        def runner(cmd, cwd, timeout):
            capture["cmd"] = cmd
            Path(cwd, ROUTE_DUMP_FILE).write_text(
                expected_dump_text(bundle, prepared.config))
            return _FakeResult(stdout=_OK_STDOUT)

        ev = _run_qualified_booksim_with_runner_for_test(
            prepared, run_dir=tmp_path / "run", repo_root=tmp_path,
            runner=runner, binary=Path("build/booksim"))
        # The caller-cwd binary A was hashed AND executed: one path.
        assert ev.booksim_binary_sha256 == sha256_bytes(b"binary-A-bytes")
        assert capture["cmd"][0] == str(binary_a.resolve())
        assert Path(capture["cmd"][0]).is_absolute()
        assert ev.command[0] == str(binary_a.resolve())
        assert os.getcwd() == str(real_a)


class TestSinglePublicReuseApi:
    def test_raw_mapping_rejected(self, bundle, tmp_path):
        git, binary = make_repo_with_real_binary(tmp_path)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_qualified_booksim(
            prepared, run_dir=tmp_path / "run", repo_root=git,
            timeout=120, binary=binary)
        producer = resolve_producer_identity(binary, repo_root=git)
        with pytest.raises(BackendEvidenceError, match="EvidenceRef"):
            verify_reusable_evidence(
                ev.to_dict(),
                backend_config_hash=prepared.config.backend_config_hash(),
                backend_input_hash=prepared.manifest.backend_input_hash(),
                producer=producer)

    def test_private_binding_not_public(self):
        import veritx_dse.backend.producer as producer_mod  # noqa: PLC0415
        assert "verify_evidence_binding" not in producer_mod.__all__
        assert not hasattr(producer_mod, "verify_evidence_binding")

    def test_production_evidence_reuses(self, bundle, tmp_path):
        git, binary = make_repo_with_real_binary(tmp_path)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_qualified_booksim(
            prepared, run_dir=tmp_path / "run", repo_root=git,
            timeout=120, binary=binary)
        assert ev.execution_transport == "SUPERVISED_PROCESS"
        producer = resolve_producer_identity(binary, repo_root=git)
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        assert verify_reusable_evidence(
            ref,
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            producer=producer) == ev.to_dict()
