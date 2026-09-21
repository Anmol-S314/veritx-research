"""tests/test_backend_mesh_dor_profile.py — P1B-Q1/Q3: native DOR mesh.

The P1A compiler emits DOR_XY meshes; the certified BookSim profile must
realize exactly that hardware (KNCube native mesh + dim_order_mesh),
never a fallback projection. Selection is fabric-derived; the supported
domain is narrow and every departure refuses with a reason.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)
from veritx_dse.backend.booksim import (  # noqa: E402
    BOOKSIM_MESH_DOR_PROFILE, BOOKSIM_STANDALONE_PROFILE,
    BookSimLoweringError, BookSimRouteError, _native_mesh_projection,
    compare_route_realization, endpoint_node_projection,
    lower_booksim_standalone, prepare_booksim_standalone,
    profile_key_order, select_booksim_profile,
)
from veritx_dse.backend.booksim_profile import (  # noqa: E402
    BOOKSIM_MESH_DOR_PROFILE as MESH_SPEC,
)
from veritx_dse.backend.projection import (  # noqa: E402
    render_physical_traffic_trace, verify_trace_projection,
)
from veritx_dse.backend.contracts import BackendTarget  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequest,
)
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)
from veritx_dse.workload.messages import (  # noqa: E402
    LogicalMessageArtifactV2,
)
from veritx_dse.workload.traffic import (  # noqa: E402
    PhysicalTrafficArtifactV2,
)

from test_backend_bundle import make_bundle  # noqa: E402
from test_fabric_artifact import build_chain  # noqa: E402

REPO_EXAMPLE = (DSE.parent / "examples" / "llama_dense_64tiles.json")

_MESH = MaterializedFamily.MESH
_CONCENTRATED = MaterializedFamily.CONCENTRATED_MESH


def _p1a_bundle():
    req = CompileRequest.from_dict(json.loads(REPO_EXAMPLE.read_text()))
    comp = FabricCompiler().compile(req)
    assert comp.status == "COMPILED"
    return comp.bundle


def _topo_stub(router_count, edges, *, family=_MESH, latency=1):
    channels = [SimpleNamespace(src_router=s, dst_router=d,
                                latency_cycles=latency)
                for s, d in edges]
    return SimpleNamespace(router_count=router_count, channels=channels,
                           family=family)


def _att_stub(pairs):
    return SimpleNamespace(
        endpoints=[SimpleNamespace(endpoint_id=e, router_id=r)
                   for e, r in pairs])


def _bundle_stub(topo, att, classes):
    return SimpleNamespace(
        router_route=SimpleNamespace(
            routing_classes=tuple(SimpleNamespace(id=c) for c in classes)),
        topology=topo, attachment=att)


def _grid_edges(k, *, drop=(), latency=1):
    edges = []
    for r in range(k * k):
        x, y = r % k, r // k
        if x + 1 < k:
            edges += [(r, r + 1), (r + 1, r)]
        if y + 1 < k:
            edges += [(r, r + k), (r + k, r)]
    return [e for e in edges if e not in drop]


class TestProfileSelection:
    def test_p1a_mesh_selects_native_dor_profile(self):
        spec = select_booksim_profile(_p1a_bundle())
        assert spec.profile_id == BOOKSIM_MESH_DOR_PROFILE
        assert spec is MESH_SPEC

    def test_anynet_design_keeps_anynet_profile(self):
        spec = select_booksim_profile(make_bundle(build_chain()))
        assert spec.profile_id == BOOKSIM_STANDALONE_PROFILE

    def test_unrealizable_route_class_refuses(self):
        stub = _bundle_stub(_topo_stub(4, []), _att_stub([]), ["RING"])
        with pytest.raises(BookSimLoweringError,
                           match="no certified BookSim profile"):
            select_booksim_profile(stub)


class TestNativeMeshGateRefusals:
    def test_non_square_grid_refuses(self):
        stub = _bundle_stub(_topo_stub(12, [(0, 1)]), _att_stub([]),
                            ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="k x k"):
            _native_mesh_projection(stub)

    def test_missing_internal_link_refuses(self):
        stub = _bundle_stub(_topo_stub(4, _grid_edges(2, drop={(0, 1)})),
                            _att_stub([(0, 0)]), ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="exact 2x2 grid"):
            _native_mesh_projection(stub)

    def test_express_link_refuses(self):
        edges = _grid_edges(2) + [(0, 3)]
        stub = _bundle_stub(_topo_stub(4, edges), _att_stub([(0, 0)]),
                            ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="exact 2x2 grid"):
            _native_mesh_projection(stub)

    def test_parallel_channels_refuse(self):
        edges = _grid_edges(2) + [(0, 1)]
        stub = _bundle_stub(_topo_stub(4, edges), _att_stub([(0, 0)]),
                            ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="parallel"):
            _native_mesh_projection(stub)

    def test_multi_cycle_link_refuses(self):
        stub = _bundle_stub(_topo_stub(4, _grid_edges(2), latency=2),
                            _att_stub([(0, 0)]), ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="one cycle"):
            _native_mesh_projection(stub)

    def test_concentrated_mesh_refuses(self):
        stub = _bundle_stub(
            _topo_stub(4, _grid_edges(2), family=_CONCENTRATED),
            _att_stub([(0, 0)]), ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="MESH"):
            _native_mesh_projection(stub)

    def test_multiple_endpoints_per_router_refuse(self):
        stub = _bundle_stub(_topo_stub(4, _grid_edges(2)),
                            _att_stub([(0, 0), (1, 0), (2, 2)]),
                            ["DOR_XY"])
        with pytest.raises(BookSimLoweringError, match="one terminal"):
            _native_mesh_projection(stub)

    def test_real_mesh_projection_is_exact_grid(self):
        projection = _native_mesh_projection(_p1a_bundle())
        assert (projection.k, projection.n) == (9, 2)
        assert projection.node_count == 81
        assert len(projection.endpoint_to_node) == 72
        nodes = [n for _e, n in projection.endpoint_to_node]
        assert len(set(nodes)) == len(nodes)  # injective
        assert projection.node_of(0) == 0


class TestNativeMeshLowering:
    def test_lowered_config_is_native_mesh_dim_order(self):
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        params = dict(config.normalized_parameters)
        assert config.backend_profile == BOOKSIM_MESH_DOR_PROFILE
        assert params["topology"] == "mesh"
        assert (params["k"], params["n"]) == (9, 2)
        assert params["routing_function"] == "dim_order"
        assert params["routing_class"] == "DOR_XY"
        assert params["num_vcs"] == 1
        assert "network_file" not in params
        assert config.lowerer_version == "B37/2"

    def test_rendered_inputs_have_no_topology_file(self):
        bundle = _p1a_bundle()
        prepared = prepare_booksim_standalone(bundle, workload_trace=b"0 0 0 1 1\n")
        names = [n for n, _ in prepared.rendered.files]
        assert names == ["config.cfg", "workload.trace"]
        values = dict(line.split(" = ")[0:1] + [""]
                      for line in [])
        cfg = prepared.rendered.file("config.cfg").decode()
        assert "topology = mesh;" in cfg
        assert "k = 9;" in cfg and "n = 2;" in cfg
        assert "routing_function = dim_order;" in cfg
        assert "network_file" not in cfg
        assert [r.role for r in prepared.manifest.rendered_inputs] == \
            ["booksim_config", "workload"]

    def test_emitted_keys_equal_profile_key_order(self):
        bundle = _p1a_bundle()
        prepared = prepare_booksim_standalone(bundle, workload_trace=b"0 0 0 1 1\n")
        keys = tuple(line.split(" = ")[0]
                     for line in prepared.rendered.file("config.cfg")
                     .decode().splitlines())
        assert keys == profile_key_order(MESH_SPEC)

    def test_serving_target_refuses_mesh_profile(self):
        from veritx_dse.backend.booksim import lower_booksim_projection
        from veritx_dse.backend.booksim import (
            BOOKSIM_MESH_DOR_BACKEND_SEMANTICS_VERSION,
            BOOKSIM_MESH_DOR_LOWERER_VERSION,
        )
        with pytest.raises(BookSimLoweringError, match="standalone-only"):
            lower_booksim_projection(
                _p1a_bundle(), target=BackendTarget.SERVING_BOOKSIM2,
                profile=BOOKSIM_MESH_DOR_PROFILE,
                semantics_version=BOOKSIM_MESH_DOR_BACKEND_SEMANTICS_VERSION,
                lowerer_version=BOOKSIM_MESH_DOR_LOWERER_VERSION,
                profile_spec=MESH_SPEC)


class TestNodeProjection:
    def _traffic(self):
        bundle = _p1a_bundle()
        req = CompileRequest.from_dict(json.loads(REPO_EXAMPLE.read_text()))
        graph = lower_compile_workload(req)
        logical = LogicalMessageArtifactV2(graph=graph,
                                           traffic_class="DEFAULT")
        return PhysicalTrafficArtifactV2(logical=logical, bundle=bundle)

    def test_mesh_projection_is_router_ids(self):
        pt = self._traffic()
        node_of = endpoint_node_projection(pt.bundle)
        assert node_of is not None
        assert set(node_of.values()) == set(range(72))

    def test_projected_trace_round_trips(self):
        pt = self._traffic()
        node_of = endpoint_node_projection(pt.bundle)
        summary = verify_trace_projection(pt, node_of_endpoint=node_of)
        assert summary["num_packets"] > 0
        rendered = render_physical_traffic_trace(
            pt, node_of_endpoint=node_of).decode()
        assert rendered.splitlines()[0].split()[3] == "1"

    def test_mismatched_projection_refuses(self):
        """The verifier binds the exact rendered bytes to the projection
        it declares: verifying with a DIFFERENT projection must refuse.
        (A non-injective projection is unreachable on the product path:
        ``endpoint_node_projection`` derives it from the mesh gate,
        which refuses crowded routers.)"""
        pt = self._traffic()
        real = endpoint_node_projection(pt.bundle)
        shifted = {e: n + 1 for e, n in real.items()}
        with pytest.raises(Exception, match="not the projection"):
            verify_trace_projection(pt, node_of_endpoint=shifted)


class TestRouteEvidenceStillRequired:
    def test_missing_route_dump_refuses(self, tmp_path):
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        with pytest.raises(BookSimRouteError, match="no route dump"):
            compare_route_realization(
                bundle, config, tmp_path / "routing.dump")
