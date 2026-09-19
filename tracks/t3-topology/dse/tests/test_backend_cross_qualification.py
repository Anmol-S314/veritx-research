"""Wave B3.8b tests — cross-backend semantic intersection + unsupported domains.

No latency parity here: the contracts are "same exact claim => same
authoritative source" and "cannot represent => explicit, visible loss".
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
    TRACE, rebuild_bundle, with_channels_replaced,
)
from test_backend_bundle import make_bundle  # noqa: E402
from test_backend_execution_qualification import (  # noqa: E402
    _rebuild_with_route, _vc,
)
from test_fabric_artifact import _with_hbm, build_chain  # noqa: E402

from veritx_dse.backend.analytical import (  # noqa: E402
    AnalyticalLoweringError, lower_analytical_aware,
    lower_analytical_unaware,
)
from veritx_dse.backend.booksim import (  # noqa: E402
    BookSimLoweringError, exact_flit_bytes, lower_booksim_standalone,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    CertificationEffect, RepresentationStatus, SemanticDimension,
)
from veritx_dse.backend.qualification import (  # noqa: E402
    QualificationError, qualify_cross_backend,
)
from veritx_dse.backend.serving import lower_serving_booksim  # noqa: E402
from veritx_dse.core.route_artifact import (  # noqa: E402
    ANYNET_MIN_HOPS, DOR_XY,
)


@pytest.fixture(scope="module")
def chain():
    return build_chain()


@pytest.fixture(scope="module")
def bundle(chain):
    return make_bundle(chain)


def four_targets(bundle):
    n = bundle.attachment.endpoint_count
    return {
        "BOOKSIM_STANDALONE": lower_booksim_standalone(bundle),
        "SERVING_BOOKSIM2": lower_serving_booksim(bundle),
        "SERVING_ANALYTICAL_AWARE": lower_analytical_aware(
            bundle, network_dims=(n,)).config,
        "SERVING_ANALYTICAL_UNAWARE": lower_analytical_unaware(
            bundle, network_dims=(n,)).config,
    }


class TestSemanticIntersection:
    def test_shared_exact_claims_use_one_source(self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        assert report.targets == tuple(sorted(artifacts))
        assert "TOPOLOGY_GRAPH" in report.shared_exact_dimensions
        for claim in report.shared_exact:
            sources = {artifacts[t].binding(claim.dimension).source_identity
                       for t in claim.targets}
            assert len(sources) == 1, claim.dimension
            assert claim.source_identity == next(iter(sources))

    def test_no_false_equalities_over_all_dimensions(self, bundle):
        artifacts = four_targets(bundle)
        for dim in SemanticDimension:
            exact_sources = {
                name: art.binding(dim).source_identity
                for name, art in artifacts.items()
                if art.binding(dim).representation_status in
                (RepresentationStatus.EXACT,
                 RepresentationStatus.DERIVED_EXACT)}
            assert len(set(exact_sources.values())) <= 1, (dim,
                                                           exact_sources)

    def test_disagreements_are_explicit(self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        assert report.disagreements
        for row in report.disagreements:
            art = artifacts[row.target]
            binding = art.binding(row.dimension)
            assert binding.reason, (row.target, row.dimension)
            if binding.representation_status is not \
                    RepresentationStatus.BACKEND_IRRELEVANT:
                assert binding.certification_effect is not \
                    CertificationEffect.NONE, (row.target, row.dimension)

    def test_targets_share_fabric_identity_but_not_config_hashes(
            self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        assert report.fabric_hash == bundle.fabric.fabric_hash()
        assert report.resolved_fabric_hash == \
            bundle.resolved_fabric.resolved_fabric_hash()
        assert len({h for _n, h in report.config_hashes}) == 4

    def test_route_realization_disagreement_is_visible(self, bundle):
        artifacts = four_targets(bundle)
        report = qualify_cross_backend(artifacts)
        rows = {r.target: r for r in report.disagreements
                if r.dimension is SemanticDimension.ROUTE_REALIZATION}
        assert rows["SERVING_BOOKSIM2"].effect == "BLOCKS_EXACT_FABRIC"
        assert "ANALYTICAL" in rows["SERVING_ANALYTICAL_AWARE"].target

    def test_foreign_fabric_targets_refused(self, bundle):
        artifacts = four_targets(bundle)
        foreign = four_targets(make_bundle(_with_hbm()))
        mixed = dict(artifacts)
        mixed["SERVING_BOOKSIM2"] = foreign["SERVING_BOOKSIM2"]
        with pytest.raises(QualificationError, match="fabric_hash"):
            qualify_cross_backend(mixed)


# ── unsupported-domain qualification ────────────────────────────────────

class TestUnsupportedDomains:
    def test_heterogeneous_latency_refused(self, chain):
        topo = with_channels_replaced(
            chain.topo, lambda c: c.channel_id == 0, latency_cycles=2)
        with pytest.raises(BookSimLoweringError, match="couples"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_non_unit_route_weight_refused(self, chain):
        topo = with_channels_replaced(
            chain.topo, lambda c: c.channel_id == 0, route_weight=3)
        with pytest.raises(BookSimLoweringError, match="route_weight"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_parallel_channels_refused(self, chain):
        from dataclasses import replace
        extra = replace(chain.topo.channels[0],
                        channel_id=len(chain.topo.channels))
        topo = replace(chain.topo,
                       channels=chain.topo.channels + (extra,))
        with pytest.raises(BookSimLoweringError, match="parallel"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_non_anynet_route_class_refused(self, chain):
        with pytest.raises(BookSimLoweringError, match="ANYNET_MIN_HOPS"):
            lower_booksim_standalone(
                rebuild_bundle(chain, routing_classes=(DOR_XY,)))

    def test_non_byte_exact_flit_width_refused(self):
        from types import SimpleNamespace
        with pytest.raises(BookSimLoweringError, match="byte-exact"):
            exact_flit_bytes(SimpleNamespace(flit_width_bits=65))

    def test_trace_over_packet_cap_refused(self, bundle):
        from veritx_dse.backend.booksim import render_booksim_standalone
        with pytest.raises(BookSimLoweringError, match="exceeds"):
            render_booksim_standalone(
                bundle, lower_booksim_standalone(bundle),
                workload_trace=b"0 0 0 1 99\n")

    def test_aware_refuses_n_dim(self, bundle):
        with pytest.raises(AnalyticalLoweringError, match="1-dim"):
            lower_analytical_aware(bundle, network_dims=(2, 2))

    def test_escape_and_transition_blocks_are_domain_scoped(self, chain):
        escape = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        transitions = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, transitions=((0, 1), (1, 0)))))
        for art, dim in ((escape, SemanticDimension.ESCAPE_VCS),
                         (transitions, SemanticDimension.VC_TRANSITIONS)):
            row = art.binding(dim)
            assert row.representation_status is \
                RepresentationStatus.UNREPRESENTABLE
            assert row.certification_effect is \
                CertificationEffect.BLOCKS_EXACT_FABRIC
            assert row.supported_domain == ""
            assert not art.exact_fabric_eligible()

    def test_route_dump_transposition_refused(self, chain, bundle):
        from veritx_dse.backend.booksim import (
            BookSimRouteError, compare_route_realization,
        )
        import tempfile
        from pathlib import Path
        config = lower_booksim_standalone(bundle)
        other = lower_booksim_standalone(
            rebuild_bundle(chain, vc=_vc(chain, escape=(0,))))
        with tempfile.TemporaryDirectory() as td:
            dump = Path(td) / "routing.dump"
            # an empty dump has zero coverage -> refuse
            dump.write_text("# nothing\n")
            with pytest.raises(BookSimRouteError, match="coverage"):
                compare_route_realization(bundle, config, dump)
        assert other.backend_config_hash() != config.backend_config_hash()
