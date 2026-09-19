"""Wave B3.8c tests — cross-path transposition/tamper qualification.

Artifacts, manifests, rendered inputs, route dumps, consumed configs and
evidence must not be transplantable between targets or fabrics. Every
transposition refuses before anything executes.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_booksim import (  # noqa: E402
    TRACE, expected_dump_text, lower_booksim_standalone,
    make_capturing_runner, prepare_booksim_standalone,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import _with_hbm, build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    BackendMaterializationError, BookSimLoweringError, ROUTE_DUMP_FILE,
    compare_route_realization, materialize_backend,
    run_certified_booksim,
)
from veritx_dse.backend.evidence import (  # noqa: E402
    BackendEvidenceError, write_evidence,
)
from veritx_dse.backend.serving import (  # noqa: E402
    ServingBackendError, lower_serving_booksim, prepare_serving_booksim,
    validate_serving_consumption,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def _never_called(*args, **kwargs):
    raise AssertionError("backend executed despite a transposition refusal")


class TestArtifactTransposition:
    def test_serving_artifact_cannot_run_standalone(
            self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        serving = lower_serving_booksim(bundle)
        transposed = replace(prepared, config=serving)
        with pytest.raises(BackendMaterializationError,
                           match="manifest does not bind"):
            run_certified_booksim(
                transposed, run_dir=tmp_path, repo_root=tmp_path,
                runner=_never_called, binary=Path("/bin/true"))

    def test_stale_manifest_cannot_bind_other_config(
            self, bundle, tmp_path):
        a = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        b = prepare_booksim_standalone(bundle, workload_trace=TRACE + b"5 1 0 0 1\n")
        transposed = replace(a, manifest=b.manifest)
        with pytest.raises((BackendMaterializationError, BookSimLoweringError),
                           match="manifest|canonical binding"):
            run_certified_booksim(
                transposed, run_dir=tmp_path, repo_root=tmp_path,
                runner=_never_called, binary=Path("/bin/true"))

    def test_foreign_rendered_files_collide_not_overwrite(
            self, bundle, tmp_path):
        a = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        foreign = prepare_booksim_standalone(
            make_bundle(_with_hbm()), workload_trace=TRACE + b"9 3 0 4 1\n")
        directory = tmp_path / "backend"
        materialize_backend(a.rendered, a.manifest, directory)
        with pytest.raises(BackendMaterializationError,
                           match="refusing to overwrite"):
            materialize_backend(foreign.rendered, foreign.manifest,
                                directory)

    def art_cannot_render_for_other_bundle(
            self, chain, bundle):
        from veritx_dse.backend.booksim import render_booksim_standalone
        art = lower_booksim_standalone(bundle)
        foreign = make_bundle(_with_hbm())
        with pytest.raises(BookSimLoweringError, match="does not match"):
            render_booksim_standalone(foreign, art, workload_trace=TRACE)


class TestRouteDumpTransposition:
    def test_foreign_fabric_dump_refused(self, bundle, tmp_path):
        foreign_bundle = make_bundle(_with_hbm())
        foreign_art = lower_booksim_standalone(foreign_bundle)
        dump = tmp_path / ROUTE_DUMP_FILE
        dump.write_text(expected_dump_text(foreign_bundle, foreign_art))
        with pytest.raises(Exception, match="coverage|diverges"):
            compare_route_realization(
                bundle, lower_booksim_standalone(bundle), dump)

    def test_dump_tamper_refused(self, bundle, tmp_path):
        art = lower_booksim_standalone(bundle)
        dump = tmp_path / ROUTE_DUMP_FILE
        lines = expected_dump_text(bundle, art).splitlines()
        # Point one non-local first hop back at its own router (never a
        # legal expected next hop) without hardcoding topology tie-breaks.
        for i, line in enumerate(lines):
            if line.startswith("src_router") and \
                    "next_router 0 " not in line:
                head = line.split("next_router")[0]
                tail = line.split("next_router")[1].split(" ", 2)[2]
                lines[i] = head + "next_router 0 " + tail
                break
        dump.write_text("\n".join(lines) + "\n")
        with pytest.raises(Exception, match="diverges"):
            compare_route_realization(bundle, art, dump)

    def test_duplicate_dump_entry_refused(self, bundle, tmp_path):
        art = lower_booksim_standalone(bundle)
        text = expected_dump_text(bundle, art)
        first = text.splitlines()[1]
        dump = tmp_path / ROUTE_DUMP_FILE
        dump.write_text(text + first + "\n")
        with pytest.raises(Exception, match="repeats"):
            compare_route_realization(bundle, art, dump)

    def test_malformed_dump_line_refused(self, bundle, tmp_path):
        art = lower_booksim_standalone(bundle)
        dump = tmp_path / ROUTE_DUMP_FILE
        dump.write_text("src_router zero dst_node 1 next_router 1 port 0\n")
        with pytest.raises(Exception, match="malformed"):
            compare_route_realization(bundle, art, dump)


class TestServingConsumptionTransposition:
    def test_standalone_config_refused_by_serving(
            self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        standalone = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        with pytest.raises(ServingBackendError):
            validate_serving_consumption(
                prepared,
                cfg_text=standalone.rendered.file("config.cfg").decode(),
                flit_bytes=8, physical_dims=(2, 2), replay_only=False)

    def test_flit_bytes_from_other_width_refused(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        wide = prepare_serving_booksim(
            make_bundle(build_chain(link_width=128)),
            out_dir=tmp_path / "wide", physical_dims=(2, 2))
        assert wide.flit_bytes == 16
        with pytest.raises(ServingBackendError,
                           match="64 bits must never become 64 bytes"):
            validate_serving_consumption(
                prepared,
                cfg_text=prepared.rendered.file("config.cfg").decode(),
                flit_bytes=wide.flit_bytes, physical_dims=(2, 2),
                replay_only=False)

    def test_foreign_dims_refused(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        with pytest.raises(ServingBackendError):
            validate_serving_consumption(
                prepared,
                cfg_text=prepared.rendered.file("config.cfg").decode(),
                flit_bytes=8, physical_dims=(4,), replay_only=False)


class TestEvidenceTransposition:
    def test_cross_target_evidence_cannot_share_a_path(
            self, bundle, tmp_path):
        standalone = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        serving = prepare_serving_booksim(
            bundle, out_dir=tmp_path / "serve", physical_dims=(2, 2))
        from veritx_dse.backend.serving import serving_backend_evidence
        run_dir = tmp_path / "run"
        write_evidence(run_dir, {
            "backend_config_hash": standalone.config.backend_config_hash(),
            "backend_input_hash": standalone.manifest.backend_input_hash(),
        })
        with pytest.raises(BackendEvidenceError, match="refusing"):
            write_evidence(run_dir, serving_backend_evidence(serving))

    def test_tampered_evidence_detected(self, bundle, tmp_path):
        from veritx_dse.backend.evidence import (
            evidence_sha256, evidence_sha256_of, read_evidence,
        )
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        payload = {"backend_config_hash":
                   prepared.config.backend_config_hash()}
        ref = write_evidence(tmp_path, payload)
        path = Path(ref["path"])
        assert evidence_sha256(path) == evidence_sha256_of(payload)
        prefix = prepared.config.backend_config_hash()[:6]
        path.write_text(path.read_text().replace(prefix, "f" * 6))
        assert evidence_sha256(path) != ref["sha256"]
        assert read_evidence(path)["backend_config_hash"] \
            != prepared.config.backend_config_hash()
