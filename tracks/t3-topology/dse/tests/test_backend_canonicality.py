"""Wave B3.8h tests — canonical backend lowering authenticity.

A BackendConfigArtifact can be internally hash-consistent, bind the right
fabric/resolved identities, and still not be the authorized lowering of
that fabric (recomputed hash + forged parameters/bindings). These tests
forge such artifacts, recompute their hashes, and prove the renderer,
runner and cross-backend qualifier all refuse them with zero spawns.
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
    TRACE, make_capturing_runner, prepare_booksim_standalone,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_backend_cross_qualification import four_targets  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION,
    BOOKSIM_STANDALONE_PROFILE, BookSimLoweringError,
    assert_canonical_booksim_projection, execution_qualification,
    lower_booksim_standalone, parse_booksim_config_values,
    render_booksim_standalone, run_certified_booksim,
    verify_rendered_profile_gates,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendConfigArtifact, BackendConfigError, CertificationEffect,
    RepresentationStatus, SemanticDimension, sha256_bytes,
)
from veritx_dse.backend.qualification import (  # noqa: E402
    QualificationError, compare_booksim_realizations,
    qualify_cross_backend,
)
from veritx_dse.backend.serving import (  # noqa: E402
    ServingBackendError, lower_serving_booksim, prepare_serving_booksim,
    render_serving_config,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def _never(*args, **kwargs):
    raise AssertionError("backend executed despite a canonicality refusal")


def _forge(art: BackendConfigArtifact, **params) -> BackendConfigArtifact:
    values = dict(art.normalized_parameters)
    values.update(params)
    return replace(art, normalized_parameters=tuple(sorted(values.items())),
                   artifact_hash="")


def _assert_runner_refuses(bundle, forged, tmp_path):
    """Runner-level refusal: forged config + canonical rendered inputs.

    The runner's canonical check must fire before manifest binding and
    before any spawn, so pairing the forged config with the canonical
    rendered files is the sharpest test of execution-path validation.
    """
    canonical = prepare_booksim_standalone(bundle, workload_trace=TRACE)
    prepared = replace(canonical, config=forged)
    with pytest.raises(BookSimLoweringError, match="noncanonical"):
        run_certified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=_never, binary=tmp_path / "fake")


class TestCanonicalBaseline:
    def test_canonical_artifact_validates(self, bundle):
        art = lower_booksim_standalone(bundle)
        expected = assert_canonical_booksim_projection(bundle, art)
        assert expected.backend_config_hash() == art.backend_config_hash()

    def test_roundtrip_artifact_is_canonical(self, bundle):
        art = lower_booksim_standalone(bundle)
        loaded = BackendConfigArtifact.from_dict(art.to_dict())
        assert loaded.backend_config_hash() == art.backend_config_hash()
        assert assert_canonical_booksim_projection(
            bundle, loaded).backend_config_hash() \
            == art.backend_config_hash()

    def test_stale_hash_mutation_still_refuses(self, bundle):
        d = lower_booksim_standalone(bundle).to_dict()
        d["normalized_parameters"]["sim_power"] = 1
        with pytest.raises(BackendConfigError, match="does not match"):
            BackendConfigArtifact.from_dict(d)


class TestProfileForgery:
    @pytest.mark.parametrize("field,value", [
        ("sim_power", 1),
        ("speculative", 1),
        ("router", "event"),
        ("noq", 1),
        ("vc_busy_when_full", 1),
        ("arb_type", "pim"),
    ])
    def test_recomputed_hash_profile_pin_refused(self, bundle, tmp_path,
                                                 field, value):
        art = lower_booksim_standalone(bundle)
        forged = _forge(art, **{field: value})
        # internally valid, parent identities unchanged
        assert forged.backend_config_hash() != art.backend_config_hash()
        assert forged.fabric_hash == art.fabric_hash
        assert forged.resolved_fabric_hash == art.resolved_fabric_hash
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            assert_canonical_booksim_projection(bundle, forged)
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            render_booksim_standalone(bundle, forged, workload_trace=TRACE)
        _assert_runner_refuses(bundle, forged, tmp_path)

    @pytest.mark.parametrize("field,value", [
        ("backend_profile", "CERTIFIED_BOOKSIM_ANYNET_V2"),
        ("backend_semantics_version", "forged-semantics"),
        ("lowerer_version", "forged/9"),
    ])
    def test_recomputed_hash_identity_forgery_refused(self, bundle,
                                                      field, value):
        art = lower_booksim_standalone(bundle)
        forged = replace(art, artifact_hash="", **{field: value})
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            assert_canonical_booksim_projection(bundle, forged)


class TestFabricProjectionForgery:
    @pytest.mark.parametrize("field,value", [
        ("num_vcs", 99),
        ("vc_buf_size", 64),
        ("routing_delay", 7),
        ("credit_delay", 9),
        ("input_speedup", 4),
        ("routing_function", "dor"),
        ("read_request_end_vc", 12),
    ])
    def test_recomputed_hash_fabric_projection_refused(self, bundle,
                                                       tmp_path, field,
                                                       value):
        art = lower_booksim_standalone(bundle)
        forged = _forge(art, **{field: value})
        assert forged.fabric_hash == art.fabric_hash
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            assert_canonical_booksim_projection(bundle, forged)
        _assert_runner_refuses(bundle, forged, tmp_path)


class TestBindingForgery:
    def _with_binding(self, art, index_fn, **changes):
        binds = list(art.semantic_bindings)
        idx = next(i for i, b in enumerate(binds) if index_fn(b))
        binds[idx] = replace(binds[idx], **changes)
        return replace(art, semantic_bindings=tuple(binds),
                       artifact_hash="")

    @pytest.mark.parametrize("changes", [
        {"source_identity": "a" * 64},
        {"supported_domain": "forged domain"},
        {"backend_fields": (("num_vcs", 4),)},
    ])
    def test_recomputed_hash_binding_value_refused(self, bundle, changes):
        art = lower_booksim_standalone(bundle)
        forged = self._with_binding(
            art, lambda b: b.dimension is SemanticDimension.VC_COUNT,
            **changes)
        with pytest.raises((BookSimLoweringError, BackendConfigError)):
            assert_canonical_booksim_projection(bundle, forged)

    def test_recomputed_hash_status_upgrade_refused(self, bundle):
        art = lower_booksim_standalone(bundle)
        forged = self._with_binding(
            art,
            lambda b: b.dimension is SemanticDimension.VC_CLASS_ASSIGNMENT,
            representation_status=RepresentationStatus.EXACT,
            certification_effect=CertificationEffect.NONE,
            supported_domain="forged exactness")
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            assert_canonical_booksim_projection(bundle, forged)

    def test_recomputed_hash_effect_downgrade_refused(self, bundle):
        art = lower_booksim_standalone(bundle)
        forged = self._with_binding(
            art,
            lambda b: b.dimension is SemanticDimension.OUTPUT_DELAY_CYCLES,
            certification_effect=CertificationEffect.NONE,
            representation_status=RepresentationStatus.EXACT,
            supported_domain="forged exactness",
            reason="")
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            assert_canonical_booksim_projection(bundle, forged)

    def test_runner_never_derives_qualification_from_forged_bindings(
            self, bundle, tmp_path):
        art = lower_booksim_standalone(bundle)
        assert execution_qualification(art).value == \
            "EXECUTED_WITH_DECLARED_LOSS"
        forged = self._with_binding(
            art,
            lambda b: b.dimension is SemanticDimension.VC_CLASS_ASSIGNMENT,
            representation_status=RepresentationStatus.EXACT,
            certification_effect=CertificationEffect.NONE,
            supported_domain="forged exactness")
        _assert_runner_refuses(bundle, forged, tmp_path)


class TestEqualButForgedCrossBackend:
    def test_two_identically_forged_artifacts_cannot_qualify(self, bundle):
        arts = four_targets(bundle)
        forged_standalone = _forge(arts["BOOKSIM_STANDALONE"],
                                   speculative=1)
        forged_serving = _forge(arts["SERVING_BOOKSIM2"], speculative=1)
        # They agree with each other...
        assert compare_booksim_realizations(
            forged_standalone, forged_serving).equivalent
        # ...but canonical context refuses both.
        arts["BOOKSIM_STANDALONE"] = forged_standalone
        arts["SERVING_BOOKSIM2"] = forged_serving
        with pytest.raises(QualificationError, match="canonical lowering"):
            qualify_cross_backend(bundle, arts)

    def test_two_identically_forged_fabric_params_refuse(self, bundle):
        arts = four_targets(bundle)
        arts["BOOKSIM_STANDALONE"] = _forge(arts["BOOKSIM_STANDALONE"],
                                            num_vcs=123)
        arts["SERVING_BOOKSIM2"] = _forge(arts["SERVING_BOOKSIM2"],
                                          num_vcs=123)
        with pytest.raises(QualificationError, match="canonical lowering"):
            qualify_cross_backend(bundle, arts)


class TestRenderedGateVerification:
    def test_valid_rendered_config_passes(self, bundle):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        values = parse_booksim_config_values(
            prepared.rendered.file("config.cfg").decode())
        verify_rendered_profile_gates(values)

    @pytest.mark.parametrize("field,value", [
        ("sim_power", "1"),
        ("router", "event"),
        ("topology", "mesh"),
        ("buffer_policy", "shared"),
        ("use_read_write", "1"),
    ])
    def test_gate_violation_refused(self, bundle, field, value):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        values = parse_booksim_config_values(
            prepared.rendered.file("config.cfg").decode())
        values[field] = value
        with pytest.raises(BookSimLoweringError,
                           match="violates certified profile gates"):
            verify_rendered_profile_gates(values)

    def test_serving_render_refuses_forged_artifact(self, bundle):
        canonical = lower_serving_booksim(bundle)
        forged = _forge(canonical, speculative=1)
        with pytest.raises(ServingBackendError, match="canonical lowering"):
            render_serving_config(bundle, forged)


class TestServingCanonicality:
    def test_serving_artifact_is_canonical(self, bundle, tmp_path):
        prepared = prepare_serving_booksim(
            bundle, out_dir=tmp_path, physical_dims=(2, 2))
        assert assert_canonical_booksim_projection(
            bundle, prepared.config).backend_config_hash() \
            == prepared.config.backend_config_hash()

    def test_forged_serving_artifact_refused_by_renderer(self, bundle):
        canonical = lower_serving_booksim(bundle)
        forged = _forge(canonical, noq=1)
        with pytest.raises(ServingBackendError, match="canonical lowering"):
            render_serving_config(bundle, forged)


class TestGoldenRegression:
    def test_normal_execution_still_works(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_certified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config),
            binary=tmp_path / "fake")
        assert ev.route_equivalence == "EXACT"
        assert ev.qualification == "EXECUTED_WITH_DECLARED_LOSS"
