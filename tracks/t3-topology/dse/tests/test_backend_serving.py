"""Wave B3.7c tests — serving BookSim consumer seam.

The watchlist regression lives here: a 64-BIT flit must never reach the
embedded frontend as the legacy 64-BYTE value.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
REPO = DSE.parent.parent.parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(REPO / "third_party" / "llmservingsim"))

from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    BookSimLoweringError, exact_flit_bytes, lower_booksim_standalone,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendTarget, CertificationEffect, RepresentationStatus,
    SemanticDimension,
)
from veritx_dse.backend.serving import (  # noqa: E402
    SERVING_BOOKSIM2_PROFILE, SERVING_CONFIG_FILE, SERVING_FLIT_BYTES_FILE,
    SERVING_PHYSICAL_DIMS_FILE, ServingBackendError, lower_serving_booksim,
    prepare_serving_booksim, render_serving_config, validate_physical_dims,
    validate_serving_consumption, verify_serving_prepared,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


# ── flit width conversion (the watchlist bug) ────────────────────────────

class TestFlitWidth:
    def test_64_bits_is_8_bytes_not_64(self, bundle):
        assert bundle.packet_format.flit_width_bits == 64
        assert exact_flit_bytes(bundle.packet_format) == 8
        assert exact_flit_bytes(bundle.packet_format) != 64

    def test_non_byte_exact_width_refused(self):
        with pytest.raises(BookSimLoweringError, match="not byte-exact"):
            exact_flit_bytes(SimpleNamespace(flit_width_bits=65))

    def test_flit_bytes_file_is_8(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        assert prepared.flit_bytes == 8
        assert prepared.rendered.file(SERVING_FLIT_BYTES_FILE) == b"8\n"
        assert prepared.manifest.invocation_args == (
            ("config-file", SERVING_CONFIG_FILE),
            ("flit-bytes", "8"),
            ("physical-dims", "2,2"),
            ("replay-only", "false"),
        )

    def test_wider_flit_changes_conversion_and_identity(self, chain, bundle):
        wide_chain = build_chain(link_width=128)
        wide_bundle = make_bundle(wide_chain)
        assert exact_flit_bytes(wide_bundle.packet_format) == 16
        a = lower_serving_booksim(bundle)
        b = lower_serving_booksim(wide_bundle)
        assert a.backend_config_hash() != b.backend_config_hash()
        assert a.binding(SemanticDimension.FLIT_WIDTH).backend_fields \
            != b.binding(SemanticDimension.FLIT_WIDTH).backend_fields


# ── lowering ────────────────────────────────────────────────────────────

class TestServingLowering:
    def test_target_and_profile(self, bundle):
        art = lower_serving_booksim(bundle)
        assert art.backend_target is BackendTarget.SERVING_BOOKSIM2
        assert art.backend_profile == SERVING_BOOKSIM2_PROFILE
        assert art.fabric_hash == bundle.fabric.fabric_hash()

    def test_route_realization_is_not_claimed_exact(self, bundle):
        art = lower_serving_booksim(bundle)
        b = art.binding(SemanticDimension.ROUTE_REALIZATION)
        assert b.representation_status is \
            RepresentationStatus.UNREPRESENTABLE
        assert b.certification_effect is \
            CertificationEffect.BLOCKS_EXACT_FABRIC
        assert not art.exact_fabric_eligible()

    def test_packetization_losses_are_explicit(self, bundle):
        art = lower_serving_booksim(bundle)
        max_flits = art.binding(SemanticDimension.PACKET_MAX_FLITS)
        assert max_flits.representation_status is \
            RepresentationStatus.UNREPRESENTABLE
        assert "embedded" in max_flits.reason.lower()
        delim = art.binding(SemanticDimension.PACKET_DELIMITATION)
        assert delim.representation_status is \
            RepresentationStatus.UNREPRESENTABLE

    def test_flit_width_is_derived_exact(self, bundle):
        art = lower_serving_booksim(bundle)
        b = art.binding(SemanticDimension.FLIT_WIDTH)
        assert b.representation_status is RepresentationStatus.DERIVED_EXACT
        assert b.backend_fields == (("flit_bytes", 8),)

    def test_target_change_changes_config_hash(self, bundle):
        standalone = lower_booksim_standalone(bundle)
        serving = lower_serving_booksim(bundle)
        assert standalone.backend_config_hash() != serving.backend_config_hash()

    def test_config_has_no_packet_size_and_no_background_traffic(
            self, bundle):
        cfg = render_serving_config(
            bundle, lower_serving_booksim(bundle)).decode()
        assert "packet_size" not in cfg
        assert "traffic = uniform;" in cfg
        assert "injection_rate = 0.0;" in cfg
        assert "routing_dump_file = routing.dump;" in cfg


class TestPhysicalDims:
    def test_product_must_match_endpoints(self, bundle):
        assert validate_physical_dims((2, 2), endpoint_count=4) == (2, 2)
        assert validate_physical_dims((4,), endpoint_count=4) == (4,)
        with pytest.raises(ServingBackendError, match="multiply to"):
            validate_physical_dims((3, 2), endpoint_count=4)

    def test_invalid_dims_refused(self):
        for bad in ((), None, (0, 4), (-1, 4), (True, 4), ("2", 2)):
            with pytest.raises(ServingBackendError):
                validate_physical_dims(bad, endpoint_count=4)


# ── preparation + consumption validation ────────────────────────────────

class TestPreparation:
    def test_prepare_writes_contract_files(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        for name in (SERVING_CONFIG_FILE, "topology.anynet",
                     SERVING_FLIT_BYTES_FILE, SERVING_PHYSICAL_DIMS_FILE):
            assert (tmp_path / name).is_file(), name
        verify_serving_prepared(prepared)
        assert prepared.manifest.execution_mode == "REAL_SIMULATION_EMBEDDED"
        assert prepared.manifest.workload_hash is None

    def test_same_inputs_other_directory_same_hashes(self, bundle, tmp_path):
        a = prepare_serving_booksim(
            bundle, out_dir=tmp_path / "a", physical_dims=(2, 2))
        b = prepare_serving_booksim(
            bundle, out_dir=tmp_path / "b", physical_dims=(2, 2))
        assert a.config.backend_config_hash() \
            == b.config.backend_config_hash()
        assert a.manifest.backend_input_hash() \
            == b.manifest.backend_input_hash()

    def test_consumption_validation_accepts_exact(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        validate_serving_consumption(
            prepared, cfg_text=prepared.rendered.file(SERVING_CONFIG_FILE)
            .decode(), flit_bytes=8, physical_dims=(2, 2), replay_only=False)

    def test_consumption_refuses_64_bytes(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        with pytest.raises(ServingBackendError,
                           match="64 bits must never become 64 bytes"):
            validate_serving_consumption(
                prepared,
                cfg_text=prepared.rendered.file(
                    SERVING_CONFIG_FILE).decode(),
                flit_bytes=64, physical_dims=(2, 2), replay_only=False)

    def test_consumption_refuses_replay(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        with pytest.raises(ServingBackendError, match="replay"):
            validate_serving_consumption(
                prepared,
                cfg_text=prepared.rendered.file(
                    SERVING_CONFIG_FILE).decode(),
                flit_bytes=8, physical_dims=(2, 2), replay_only=True)

    def test_consumption_refuses_param_divergence(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        cfg = prepared.rendered.file(SERVING_CONFIG_FILE).decode()
        tampered = cfg.replace("num_vcs = 2;", "num_vcs = 16;")
        with pytest.raises(ServingBackendError, match="num_vcs"):
            validate_serving_consumption(
                prepared, cfg_text=tampered, flit_bytes=8,
                physical_dims=(2, 2), replay_only=False)

    def test_consumption_refuses_missing_param(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        cfg = prepared.rendered.file(SERVING_CONFIG_FILE).decode()
        tampered = cfg.replace("hold_switch_for_packet = 0;\n", "")
        with pytest.raises(ServingBackendError, match="hold_switch"):
            validate_serving_consumption(
                prepared, cfg_text=tampered, flit_bytes=8,
                physical_dims=(2, 2), replay_only=False)

    def test_consumption_refuses_false_packet_authority(self, bundle,
                                                        tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        cfg = prepared.rendered.file(SERVING_CONFIG_FILE).decode()
        with pytest.raises(ServingBackendError, match="packet_size"):
            validate_serving_consumption(
                prepared, cfg_text=cfg + "packet_size = 64;\n",
                flit_bytes=8, physical_dims=(2, 2), replay_only=False)


# ── vendored consumer helper ────────────────────────────────────────────

class TestConsumerHelper:
    def _helper(self):
        from serving.veritx_certified import (  # noqa: PLC0415
            CERTIFIED_BACKEND_ENV, CertifiedBackendError,
            load_certified_backend, resolve_certified_backend,
        )
        return (CERTIFIED_BACKEND_ENV, CertifiedBackendError,
                load_certified_backend, resolve_certified_backend)

    def test_absent_env_is_none(self):
        (_env, _err, _load, resolve) = self._helper()
        assert resolve({}) is None

    def test_valid_directory_loads(self, bundle, tmp_path):
        (env, _err, load, resolve) = self._helper()
        prepare_serving_booksim(bundle, out_dir=tmp_path,
                                physical_dims=(2, 2))
        got = resolve({env: str(tmp_path)})
        assert got["flit_bytes"] == 8
        assert got["physical_dims"] == (2, 2)
        assert got["config_path"].endswith(SERVING_CONFIG_FILE)
        assert load(tmp_path)["dir"] == str(tmp_path)

    def test_missing_files_fail_closed(self, bundle, tmp_path):
        (_env, err, load, _resolve) = self._helper()
        prepare_serving_booksim(bundle, out_dir=tmp_path,
                                physical_dims=(2, 2))
        (tmp_path / SERVING_FLIT_BYTES_FILE).unlink()
        with pytest.raises(err, match=SERVING_FLIT_BYTES_FILE):
            load(tmp_path)

    def test_malformed_flit_bytes_fail_closed(self, bundle, tmp_path):
        (_env, err, load, _resolve) = self._helper()
        prepare_serving_booksim(bundle, out_dir=tmp_path,
                                physical_dims=(2, 2))
        (tmp_path / SERVING_FLIT_BYTES_FILE).write_text("64.0\n")
        with pytest.raises(err, match="integer"):
            load(tmp_path)

    def test_malformed_dims_fail_closed(self, bundle, tmp_path):
        (_env, err, load, _resolve) = self._helper()
        prepare_serving_booksim(bundle, out_dir=tmp_path,
                                physical_dims=(2, 2))
        (tmp_path / SERVING_PHYSICAL_DIMS_FILE).write_text('{"dims": [0, 4]}')
        with pytest.raises(err, match="positive"):
            load(tmp_path)

    def test_serving_module_consumes_the_seam(self):
        """Pin the seam in the vendored module so it cannot silently
        revert to the hardcoded 64-BYTE path."""
        text = (REPO / "third_party" / "llmservingsim" / "serving"
                / "__main__.py").read_text()
        assert "resolve_certified_backend" in text
        assert 'CERTIFIED_BACKEND_ENV + " refuses "' in text
        assert '--booksim2-flit-bytes=%d" % _certified["flit_bytes"]' in text
