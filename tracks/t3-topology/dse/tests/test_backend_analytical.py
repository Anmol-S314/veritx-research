"""Wave B3.7d tests — analytical aware/unaware capability matrices.

The engines are distinct backend identities; unresolved bandwidth/latency
units refuse execution instead of fabricating science.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.backend.analytical import (  # noqa: E402
    ANALYTICAL_AWARE_PROFILE, ANALYTICAL_UNAWARE_PROFILE,
    AnalyticalLoweringError, assert_analytical_executable,
    lower_analytical_aware, lower_analytical_unaware,
)
from veritx_dse.backend.booksim import (  # noqa: E402
    lower_booksim_standalone,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendTarget, CertificationEffect, RepresentationStatus,
    SemanticDimension,
)
from veritx_dse.backend.serving import lower_serving_booksim  # noqa: E402


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


EXACTISH = (RepresentationStatus.EXACT,
            RepresentationStatus.DERIVED_EXACT)


class TestAnalyticalLowering:
    def test_targets_are_distinct(self, bundle):
        aware = lower_analytical_aware(bundle, network_dims=(4,))
        unaware = lower_analytical_unaware(bundle, network_dims=(2, 2))
        assert aware.config.backend_target is \
            BackendTarget.SERVING_ANALYTICAL_AWARE
        assert unaware.config.backend_target is \
            BackendTarget.SERVING_ANALYTICAL_UNAWARE
        assert aware.config.backend_profile == ANALYTICAL_AWARE_PROFILE
        assert unaware.config.backend_profile == ANALYTICAL_UNAWARE_PROFILE
        assert aware.config.backend_config_hash() \
            != unaware.config.backend_config_hash()

    def test_engine_param_is_explicit(self, bundle):
        aware = lower_analytical_aware(bundle, network_dims=(4,))
        unaware = lower_analytical_unaware(bundle, network_dims=(2, 2))
        assert dict(aware.config.normalized_parameters)["network_engine"] \
            == "congestion_aware"
        assert dict(unaware.config.normalized_parameters)["network_engine"] \
            == "congestion_unaware"

    def test_aware_refuses_multidimensional(self, bundle):
        with pytest.raises(AnalyticalLoweringError, match="1-dim"):
            lower_analytical_aware(bundle, network_dims=(2, 2))

    def test_unaware_accepts_multidimensional(self, bundle):
        prepared = lower_analytical_unaware(bundle, network_dims=(2, 2))
        assert prepared.config.binding(
            SemanticDimension.TOPOLOGY_GRAPH).backend_fields == (
                ("npus_count", 4), ("topology_shape", (2, 2)))

    def test_dims_must_cover_endpoints(self, bundle):
        with pytest.raises(AnalyticalLoweringError, match="multiply to"):
            lower_analytical_unaware(bundle, network_dims=(3, 2))

    def test_every_dimension_is_bound(self, bundle):
        prepared = lower_analytical_aware(bundle, network_dims=(4,))
        dims = [b.dimension for b in prepared.config.semantic_bindings]
        assert dims == list(SemanticDimension)

    def test_units_block_execution(self, bundle):
        prepared = lower_analytical_aware(bundle, network_dims=(4,))
        width = prepared.config.binding(SemanticDimension.CHANNEL_WIDTH)
        latency = prepared.config.binding(SemanticDimension.CHANNEL_LATENCY)
        for row in (width, latency):
            assert row.representation_status is \
                RepresentationStatus.UNREPRESENTABLE
            assert row.certification_effect is \
                CertificationEffect.UNSUPPORTED_EXECUTION
        assert not prepared.executable()
        with pytest.raises(AnalyticalLoweringError, match="UNSUPPORTED"):
            assert_analytical_executable(prepared)

    def test_no_numeric_bandwidth_or_latency_is_invented(self, bundle):
        prepared = lower_analytical_unaware(bundle, network_dims=(2, 2))
        keys = {k for k, _ in prepared.config.normalized_parameters}
        assert keys == {"network_engine", "npus_count", "topology_shape"}
        assert not prepared.config.exact_fabric_eligible()

    def test_same_inputs_same_hash(self, bundle):
        a = lower_analytical_unaware(bundle, network_dims=(2, 2))
        b = lower_analytical_unaware(bundle, network_dims=(2, 2))
        assert a.config.backend_config_hash() \
            == b.config.backend_config_hash()

    def test_dims_change_hash(self, bundle):
        a = lower_analytical_unaware(bundle, network_dims=(2, 2))
        flat = lower_analytical_unaware(bundle, network_dims=(4,))
        assert a.config.backend_config_hash() \
            != flat.config.backend_config_hash()


# ── cross-backend consistency (§15) ─────────────────────────────────────

class TestCrossBackendConsistency:
    def test_exact_claims_share_the_same_semantic_source(self, bundle):
        standalone = lower_booksim_standalone(bundle)
        serving = lower_serving_booksim(bundle)
        analytical = lower_analytical_unaware(
            bundle, network_dims=(2, 2)).config
        artifacts = (standalone, serving, analytical)

        claims: dict[str, dict[str, str]] = {}
        for art in artifacts:
            for row in art.semantic_bindings:
                if row.representation_status in EXACTISH:
                    claims.setdefault(row.dimension.value, {})[
                        art.backend_target.value] = row.source_identity
        shared = {dim: sources for dim, sources in claims.items()
                  if len(sources) > 1}
        assert shared, "expected at least one shared exact dimension"
        for dim, sources in shared.items():
            assert len(set(sources.values())) == 1, (
                f"{dim} claimed exact by {sorted(sources)} but with "
                f"different semantic sources")

    def test_lossy_backends_do_not_join_false_equalities(self, bundle):
        analytical = lower_analytical_unaware(
            bundle, network_dims=(2, 2)).config
        for dim in (SemanticDimension.VC_COUNT,
                    SemanticDimension.ROUTE_REALIZATION,
                    SemanticDimension.CHANNEL_WIDTH):
            row = analytical.binding(dim)
            assert row.representation_status not in EXACTISH

    def test_targets_do_not_change_fabric_hash(self, bundle):
        hashes = {
            lower_booksim_standalone(bundle).fabric_hash,
            lower_serving_booksim(bundle).fabric_hash,
            lower_analytical_aware(
                bundle, network_dims=(4,)).config.fabric_hash,
            lower_analytical_unaware(
                bundle, network_dims=(2, 2)).config.fabric_hash,
        }
        assert len(hashes) == 1
        assert next(iter(hashes)) == bundle.fabric.fabric_hash()
