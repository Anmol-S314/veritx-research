"""tests/test_routing_derivation.py — P1.2: routing is compiler-derived.

The routing-function problem: legacy code derived strings
(dim_order/dor/min_adapt) while the bundle independently built
ANYNET_MIN_HOPS routes. Now derive_route() is the single chooser,
LOCKED (no user field), deterministic, and fail-closed outside
MESH/CONCENTRATED_MESH.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.core.route_artifact import (  # noqa: E402
    DOR_XY, RouteArtifactError,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.routing import derive_route  # noqa: E402
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily, materialize_family,
)


def _mesh(k=4):
    return materialize_family(MaterializedFamily.MESH, endpoint_count=k * k)


def _request(family=TopologyFamily.MESH):
    from test_fabric_artifact import build_chain  # noqa: E402
    return build_chain(tp=1, pp=1, ep=1, dp=4, n_agents=4,
                       family=family).cr


class TestDeriveRoute:
    def test_mesh_derives_dor_xy(self):
        topo = _mesh()
        route = derive_route(request=_request(), topology=topo)
        assert [d.id for d in route.routing_classes] == [DOR_XY]
        assert route.topology_hash == topo.topology_hash()

    def test_concentrated_mesh_derives_dor_xy(self):
        topo = materialize_family(
            MaterializedFamily.CONCENTRATED_MESH, endpoint_count=32,
            concentration=2)
        route = derive_route(request=_request(), topology=topo)
        assert [d.id for d in route.routing_classes] == [DOR_XY]

    def test_torus_refuses(self):
        topo = materialize_family(MaterializedFamily.TORUS,
                                  endpoint_count=16)
        with pytest.raises(RouteArtifactError, match="UNSUPPORTED"):
            derive_route(request=_request(), topology=topo)

    def test_ring_refuses(self):
        topo = materialize_family(MaterializedFamily.RING,
                                  endpoint_count=8)
        with pytest.raises(RouteArtifactError, match="UNSUPPORTED"):
            derive_route(request=_request(), topology=topo)

    def test_non_request_refuses(self):
        with pytest.raises(RouteArtifactError, match="CompileRequest"):
            derive_route(request={"not": "a request"}, topology=_mesh())

    def test_deterministic(self):
        topo = _mesh()
        req = _request()
        a = derive_route(request=req, topology=topo)
        b = derive_route(request=req, topology=topo)
        assert a.artifact_hash == b.artifact_hash

    def test_routing_is_not_user_expressible(self):
        """LOCKED structurally: NocConfig has no routing field."""
        from veritx_dse.model.compile_model import NocConfig
        assert not hasattr(NocConfig(topology_family=None), "routing")
        assert "routing" not in NocConfig.__dataclass_fields__

    def test_compile_bundle_uses_derived_route(self):
        from veritx_dse.application.compile import compile_bundle
        bundle = compile_bundle(_request())
        assert [d.id for d in
                bundle.router_route.routing_classes] == [DOR_XY]
        assert bundle.resolved_route is not None


class TestVCRouteBinding:
    """P1.3: the VC structure binds the actual derived route."""

    def test_vcs_name_the_derived_class(self):
        from types import SimpleNamespace

        from veritx_dse.application.compile import compile_bundle
        from veritx_dse.model.compile_model import (
            derive_vc_assignment_artifact,
        )
        bundle = compile_bundle(_request())
        art = derive_vc_assignment_artifact(
            bundle.design, bundle.resolved_route)
        assert art.vc_count >= 1
        assert [rc for _, rc in art.vc_to_routing_class] == \
            [DOR_XY] * art.vc_count
        assert "DOR_XY" in art.derivation
        assert "cycle_separated=" in art.derivation
        art.validate_against(bundle.resolved_route)

    def test_unserved_routing_class_refuses(self):
        """A route class with no VC is unroutable hardware — refuse,
        never silently leave it uncovered."""
        from types import SimpleNamespace

        from veritx_dse.model.compile_model import (
            Agent, AgentKind, CompileRequest, DependencyGraph,
            NocConfig, Workload, ModelFamily,
            derive_vc_assignment_artifact,
        )
        from veritx_dse.model.vc_assignment import VCAssignmentError
        cr = CompileRequest(
            workload=Workload(model_family=ModelFamily.DENSE_TRANSFORMER,
                              tp=2, pp=1, ep=1, dp=2),
            requirements=[],
            agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
            dependencies=DependencyGraph([]),
            noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        )
        stub_route = SimpleNamespace(
            routing_classes=["DOR_XY", "ESCAPE"],
            resolved_route_hash=lambda: "sha256:" + "0" * 64,
        )
        with pytest.raises(VCAssignmentError, match="no VC"):
            derive_vc_assignment_artifact(cr, stub_route)

    def test_empty_routing_classes_refuse(self):
        from types import SimpleNamespace

        from veritx_dse.model.compile_model import (
            derive_vc_assignment_artifact,
        )
        from veritx_dse.model.vc_assignment import VCAssignmentError
        stub_route = SimpleNamespace(
            routing_classes=[],
            resolved_route_hash=lambda: "sha256:" + "0" * 64,
        )
        with pytest.raises(VCAssignmentError, match="no routing classes"):
            derive_vc_assignment_artifact(_request(), stub_route)
