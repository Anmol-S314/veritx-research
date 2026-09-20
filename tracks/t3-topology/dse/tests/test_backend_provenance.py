"""Wave B3.7e tests — exact backend-input provenance.

Evidence is a derived view of already-verified facts: it must let an
auditor reconstruct the exact scientific inputs, and it must never
silently overwrite a different claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, make_capturing_runner,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    prepare_booksim_standalone, run_certified_booksim,
)
from veritx_dse.backend.contracts import sha256_bytes  # noqa: E402
from veritx_dse.backend.evidence import (  # noqa: E402
    EVIDENCE_FILE, BackendEvidenceError, evidence_sha256,
    evidence_sha256_of, read_evidence, write_evidence,
)
from veritx_dse.backend.producer import ProducerError  # noqa: E402
from veritx_dse.backend.serving import (  # noqa: E402
    prepare_serving_booksim, serving_backend_evidence,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def _run(tmp_path, bundle):
    prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
    return prepared, run_certified_booksim(
        prepared, run_dir=tmp_path, repo_root=tmp_path,
        runner=make_capturing_runner(bundle, prepared.config),
        binary=Path("/bin/true"))


class TestStandaloneProvenance:
    def test_evidence_binds_exact_inputs(self, bundle, tmp_path):
        prepared, ev = _run(tmp_path, bundle)
        assert ev.workload_hash == sha256_bytes(TRACE)
        assert ev.seed == 1 and ev.seed_policy == "pinned_default"
        assert ev.invocation_args == (("config-file", "config.cfg"),)
        assert ev.command[1] == "config.cfg"
        # role -> content hash must match the manifest exactly
        by_name = {row["logical_name"]: row for row in ev.rendered_inputs}
        for record in prepared.manifest.rendered_inputs:
            assert by_name[record.logical_name]["sha256"] == record.sha256
            assert by_name[record.logical_name]["role"] == record.role

    def test_evidence_carries_all_identity_hashes(self, bundle, tmp_path):
        prepared, ev = _run(tmp_path, bundle)
        assert ev.backend_config_hash == prepared.config.backend_config_hash()
        assert ev.backend_input_hash == prepared.manifest.backend_input_hash()
        assert ev.resolved_fabric_hash == prepared.config.resolved_fabric_hash
        assert ev.fabric_hash == prepared.config.fabric_hash
        assert ev.route_equivalence == "EXACT"

    def test_seed_change_moves_input_evidence(self, bundle, tmp_path):
        _, delta_seed_ev = _run(tmp_path / "s1", bundle)
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE,
                                              seed=9)
        shifted = run_certified_booksim(
            prepared, run_dir=tmp_path / "s2", repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=Path("/bin/true"))
        assert delta_seed_ev.backend_config_hash \
            == shifted.backend_config_hash
        assert delta_seed_ev.backend_input_hash != shifted.backend_input_hash
        assert shifted.seed == 9 and shifted.seed_policy == "explicit"

    def test_binary_digest_is_pre_spawn_identity(self, bundle, tmp_path):
        from test_backend_producer import (  # noqa: PLC0415
            make_pinned_repo, write_binary,
        )
        from veritx_dse.backend.producer import (  # noqa: PLC0415
            resolve_producer_identity, verify_evidence_binding,
        )
        _, ev = _run(tmp_path, bundle)
        assert ev.booksim_binary_sha256 == sha256_bytes(
            Path("/bin/true").read_bytes())
        # Replacing the binary does not alter the scientific input hash...
        assert ev.backend_input_hash \
            == prepare_booksim_standalone(
                bundle, workload_trace=TRACE).manifest.backend_input_hash()
        # ...but evidence only reuses for the identical pinned producer.
        git = make_pinned_repo(tmp_path, name="reuse-repo")
        binary = write_binary(
            git, content=Path("/bin/true").read_bytes())
        prepared = prepare_booksim_standalone(bundle,
                                              workload_trace=TRACE)
        pinned_ev = run_certified_booksim(
            prepared, run_dir=tmp_path / "pinned", repo_root=git,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=binary)
        pinned = resolve_producer_identity(binary, repo_root=git)
        assert pinned.source_pinned
        verify_evidence_binding(
            pinned_ev.to_dict(),
            backend_config_hash=pinned_ev.backend_config_hash,
            backend_input_hash=pinned_ev.backend_input_hash,
            producer=pinned)
        other_producer = resolve_producer_identity(
            write_binary(git, name="other",
                         content=b"different-producer-bytes"),
            repo_root=git)
        with pytest.raises(ProducerError, match="different binary"):
            verify_evidence_binding(
                pinned_ev.to_dict(),
                backend_config_hash=pinned_ev.backend_config_hash,
                backend_input_hash=pinned_ev.backend_input_hash,
                producer=other_producer)


class TestEvidencePersistence:
    def test_write_read_roundtrip(self, bundle, tmp_path):
        _, ev = _run(tmp_path / "run", bundle)
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        assert Path(ref.path).name == EVIDENCE_FILE
        assert ref.sha256 == evidence_sha256(Path(ref.path))
        assert read_evidence(ref.path) == ev.to_dict()
        assert evidence_sha256_of(ev.to_dict()) == ref.sha256

    def test_identical_evidence_is_idempotent(self, bundle, tmp_path):
        _, ev = _run(tmp_path / "run", bundle)
        first = write_evidence(tmp_path / "run", ev.to_dict())
        second = write_evidence(tmp_path / "run", ev.to_dict())
        assert first == second

    def test_different_evidence_refused(self, bundle, tmp_path):
        _, ev = _run(tmp_path / "run", bundle)
        write_evidence(tmp_path / "run", ev.to_dict())
        tampered = ev.to_dict()
        tampered["seed"] = 12345
        with pytest.raises(BackendEvidenceError, match="refusing"):
            write_evidence(tmp_path / "run", tampered)

    def test_tamper_changes_the_digest(self, bundle, tmp_path):
        _, ev = _run(tmp_path / "run", bundle)
        ref = write_evidence(tmp_path / "run", ev.to_dict())
        path = Path(ref.path)
        path.write_text(path.read_text().replace('"seed":1', '"seed":2'))
        assert evidence_sha256(path) != ref.sha256


class TestServingProvenance:
    def test_serving_evidence_mirrors_manifest(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path / "serve", physical_dims=(2, 2))
        ev = serving_backend_evidence(prepared)
        assert ev["backend_config_hash"] \
            == prepared.config.backend_config_hash()
        assert ev["backend_input_hash"] == prepared.manifest.backend_input_hash()
        assert ev["flit_bytes"] == 8
        assert ev["physical_dims"] == [2, 2]
        assert ev["invocation_args"] == {
            "config-file": "config.cfg", "flit-bytes": "8",
            "physical-dims": "2,2", "replay-only": "false"}
        by_name = {row["logical_name"]: row for row in ev["rendered_inputs"]}
        assert by_name["flit_bytes.txt"]["sha256"] == sha256_bytes(b"8\n")
        assert by_name["config.cfg"]["role"] == "booksim_config"

    def test_serving_evidence_persists(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path / "serve", physical_dims=(2, 2))
        ref = write_evidence(tmp_path / "serve",
                             serving_backend_evidence(prepared))
        assert read_evidence(ref.path)["flit_bytes"] == 8
