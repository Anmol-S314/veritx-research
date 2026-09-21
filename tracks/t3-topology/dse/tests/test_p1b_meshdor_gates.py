"""Stage-8 USEFUL_TEST replay: handoff Q3 adversarial intents, ported.

Source: handoff lane `test_backend_mesh_dor_profile.py` (27 tests) on
`p1/fabric-compiler-productization`. Ported here against the integrated
lane authorities (`backend/meshdor.py` gates, `assert_canonical_*`,
`_select_backend_path`) — same adversarial intent, lane mechanics.
Deliberately NOT ported (documented divergences, see bottom):
- trace round-trip / node-projection IDs: no lane equivalent surface.
- serving-target refusal: qualification-target layer is P0-sealed.
- pristine-synthetic-dump positive: covered by the live exit gate.

The lane's flagged KNOWN LIMITATION (express/missing grid edges passing
the link gates) is CLOSED here: `_mesh_link_semantics` now requires the
directed channel set to equal the native k x k adjacency exactly, so the
DERIVED_EXACT topology claim is earned rather than assumed.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from test_fabric_artifact import build_chain  # noqa: E402
from veritx_dse.application.compile import compile_bundle  # noqa: E402
from veritx_dse.backend.booksim import BookSimLoweringError  # noqa: E402
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendConfigArtifact,
    RepresentationStatus,
    SemanticDimension,
)
from veritx_dse.backend.meshdor import (  # noqa: E402
    _mesh_attachment,
    _mesh_link_semantics,
    _mesh_routing_class,
    _mesh_shape,
    assert_canonical_meshdor_projection,
    lower_meshdor_standalone,
)
from veritx_dse.core.route_artifact import (  # noqa: E402
    ANYNET_MIN_HOPS,
    DOR_XY,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.topology_artifact import (  # noqa: E402
    DirectedChannel,
    MaterializedFamily,
)


def _bundle_2x2():
    chain = build_chain(tp=4, pp=1, ep=1, dp=1, n_agents=4,
                        family=TopologyFamily.MESH)
    return compile_bundle(chain.cr)


def _topo_double(**kw):
    real = _bundle_2x2().topology
    kw.setdefault("family", MaterializedFamily.MESH)
    kw.setdefault("router_count", 4)
    kw.setdefault("routers", [
        SimpleNamespace(router_id=i, seat_capacity=1) for i in range(4)])
    kw.setdefault("channels", real.channels)
    return SimpleNamespace(topology=SimpleNamespace(**kw))


class TestSeatGate:
    def test_seat_capacity_2_refuses(self):
        bundle = _topo_double(routers=[
            SimpleNamespace(router_id=i, seat_capacity=2)
            for i in range(4)])
        with pytest.raises(BookSimLoweringError, match="seat_capacity 1"):
            _mesh_shape(bundle)


class TestExactGridPositive:
    def test_real_2x2_passes_all_gates(self):
        bundle = _bundle_2x2()
        assert _mesh_shape(bundle) == 2
        _mesh_attachment(bundle)
        assert _mesh_routing_class(bundle) == DOR_XY
        _mesh_link_semantics(bundle)


def _link_channels(a: int, b: int, template: DirectedChannel,
                   first_id: int) -> tuple[DirectedChannel, ...]:
    """Two directed channels a<->b shaped like a native link."""
    return tuple(
        DirectedChannel(
            channel_id=first_id + i, src_router=src, src_port=0,
            dst_router=dst, dst_port=0,
            width_bits=template.width_bits,
            latency_cycles=template.latency_cycles,
            route_weight=template.route_weight)
        for i, (src, dst) in enumerate(((a, b), (b, a))))


class TestExactAdjacencyGate:
    """RT-1: the channel set must BE the native k x k mesh adjacency.

    The executed DOR grid is derived from k alone, so any express or
    missing edge would otherwise be certified DERIVED_EXACT without
    ever being executed. These are direct `_mesh_link_semantics`
    adversarial calls plus the earned-claim check through the real
    lowering.
    """

    def test_express_diagonal_edges_refused_naming_extra_pair(self):
        bundle = _bundle_2x2()
        template = bundle.topology.channels[0]
        # Routers 0 and 3 are diagonal neighbours in a 2x2 mesh: not
        # adjacent, but latency/weight/parallelism all look native.
        express = _link_channels(0, 3, template, first_id=10_000)
        double = _topo_double(
            channels=bundle.topology.channels + express)
        with pytest.raises(BookSimLoweringError) as excinfo:
            _mesh_link_semantics(double)
        message = str(excinfo.value)
        assert "(0, 3)" in message and "(3, 0)" in message
        assert "extra" in message

    def test_missing_internal_edge_refused_naming_pair(self):
        bundle = _bundle_2x2()
        pruned = tuple(
            c for c in bundle.topology.channels
            if (c.src_router, c.dst_router) != (0, 1))
        double = _topo_double(channels=pruned)
        with pytest.raises(BookSimLoweringError) as excinfo:
            _mesh_link_semantics(double)
        message = str(excinfo.value)
        assert "(0, 1)" in message
        assert "missing" in message

    def test_real_2x2_lowering_earns_derived_exact(self):
        cfg = lower_meshdor_standalone(_bundle_2x2())
        binding = next(
            b for b in cfg.semantic_bindings
            if b.dimension is SemanticDimension.TOPOLOGY_GRAPH)
        assert binding.representation_status is \
            RepresentationStatus.DERIVED_EXACT


class TestNativeRenderKeys:
    def test_lowered_config_is_native_mesh_dim_order(self):
        cfg = lower_meshdor_standalone(_bundle_2x2())
        params = dict(cfg.normalized_parameters)
        assert params["topology"] == "mesh"
        assert params["routing_function"] == "dim_order"
        assert params["k"] == 2 and params["n"] == 2


class TestForgedRenderedConfig:
    @pytest.mark.parametrize("key,forged", [
        ("routing_function", "min"),
        ("n", 3),
        ("k", 3),
    ])
    def test_forged_field_refuses(self, key, forged):
        bundle = _bundle_2x2()
        cfg = lower_meshdor_standalone(bundle)
        params = dict(cfg.normalized_parameters)
        params[key] = forged
        bad = BackendConfigArtifact(
            backend_target=cfg.backend_target,
            backend_profile=cfg.backend_profile,
            backend_semantics_version=cfg.backend_semantics_version,
            lowerer_version=cfg.lowerer_version,
            resolved_fabric_hash=cfg.resolved_fabric_hash,
            fabric_hash=cfg.fabric_hash,
            normalized_parameters=tuple(sorted(params.items())),
            semantic_bindings=cfg.semantic_bindings)
        with pytest.raises(BookSimLoweringError, match="differs in"):
            assert_canonical_meshdor_projection(bundle, bad)


class TestForeignBundleTransplant:
    def test_config_from_other_bundle_refuses(self):
        from veritx_dse.application.compile import compile_bundle
        from test_fabric_artifact import build_chain as _chain
        bundle_a = _bundle_2x2()
        # A genuinely different fabric (link width moves fabric
        # identity); identical rebuilds would be byte-identical configs
        # and must NOT refuse — determinism is the point.
        other = _chain(tp=4, pp=1, ep=1, dp=1, n_agents=4,
                       family=TopologyFamily.MESH, link_width=128)
        bundle_b = compile_bundle(other.cr)
        assert (bundle_b.fabric.fabric_hash() !=
                bundle_a.fabric.fabric_hash())
        cfg_b = lower_meshdor_standalone(bundle_b)
        with pytest.raises(BookSimLoweringError,
                           match="fabric_hash.*does not match"):
            assert_canonical_meshdor_projection(bundle_a, cfg_b)


class TestBackendPathSelection:
    def _sel_bundle(self, family, vc_classes, router_classes):
        return SimpleNamespace(
            topology=SimpleNamespace(family=family),
            vc_assignment=SimpleNamespace(
                vc_to_routing_class=tuple(
                    (i, cls) for i, cls in enumerate(vc_classes))),
            router_route=SimpleNamespace(
                routing_classes=tuple(
                    SimpleNamespace(id=cls) for cls in router_classes)))

    def test_mesh_dor_selects_meshdor(self):
        from veritx_dse.application.fabric_evaluator import (
            _select_backend_path,
        )
        bundle = self._sel_bundle(
            MaterializedFamily.MESH, [DOR_XY], [DOR_XY])
        assert _select_backend_path(bundle) == "meshdor"

    def test_anynet_bundle_selects_anynet(self):
        from veritx_dse.application.fabric_evaluator import (
            _select_backend_path,
        )
        bundle = self._sel_bundle(
            MaterializedFamily.MESH,
            [ANYNET_MIN_HOPS], [ANYNET_MIN_HOPS])
        assert _select_backend_path(bundle) == "anynet"

    def test_split_classes_select_nothing(self):
        from veritx_dse.application.fabric_evaluator import (
            _select_backend_path,
        )
        bundle = self._sel_bundle(
            MaterializedFamily.MESH,
            [DOR_XY, ANYNET_MIN_HOPS], [DOR_XY, ANYNET_MIN_HOPS])
        assert _select_backend_path(bundle) is None


class TestMultiEndpointAttachment:
    def test_two_endpoints_one_router_refuses(self):
        bundle = _topo_double()
        bundle = SimpleNamespace(
            topology=bundle.topology,
            attachment=SimpleNamespace(endpoints=[
                SimpleNamespace(endpoint_id=0, router_id=0),
                SimpleNamespace(endpoint_id=1, router_id=0),
            ]))
        with pytest.raises(BookSimLoweringError,
                           match="identity-prefix"):
            _mesh_attachment(bundle)
