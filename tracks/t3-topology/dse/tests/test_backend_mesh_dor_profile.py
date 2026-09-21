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


# ── P1B-Q3 live/tamper matrix (item 2) ────────────────────────────────
# Live tests skip with "no runnable BookSim binary" when
# find_booksim_bin(REPO) fails. Tamper tests need no binary: they prove
# the verifier refuses forged bytes before any spawn. The pre-spawn
# fresh-dump slot rule and tampered-materialized-input rule are P0
# coverage and are not duplicated here.


def _mesh_traffic():
    """The P1A dense-64 workload bound to the compiled 9x9 DOR mesh."""
    req = CompileRequest.from_dict(json.loads(REPO_EXAMPLE.read_text()))
    comp = FabricCompiler().compile(req)
    assert comp.status == "COMPILED"
    graph = lower_compile_workload(req)
    logical = LogicalMessageArtifactV2(graph=graph,
                                       traffic_class="DEFAULT")
    return comp, PhysicalTrafficArtifactV2(logical=logical,
                                           bundle=comp.bundle)


class TestMeshLiveEvaluation:
    def test_valid_mesh_evaluates_with_exact_evidence(self, tmp_path):
        from veritx_dse.backend.projection import (
            prepare_physical_traffic_booksim, run_waved_booksim,
        )
        from veritx_dse.core.paths import REPO
        from veritx_dse.simulation.booksim import find_booksim_bin
        try:
            binary = find_booksim_bin(REPO)
        except FileNotFoundError:
            pytest.skip("no runnable BookSim binary")
        comp, pt = _mesh_traffic()
        assert comp.status == "COMPILED"
        assert lower_booksim_standalone(
            comp.bundle).backend_profile == BOOKSIM_MESH_DOR_PROFILE
        prepared, summary = prepare_physical_traffic_booksim(pt)
        assert prepared.config.backend_profile == \
            BOOKSIM_MESH_DOR_PROFILE
        result = run_waved_booksim(
            prepared, run_dir=tmp_path, repo_root=REPO, timeout=600,
            binary=Path(binary), summary=summary)
        evidence = result["evidence"]
        counters = result["backend_counters"]
        assert evidence.exit_status == 0
        assert evidence.route_equivalence == "EXACT"
        assert evidence.route_pairs_compared == 81 * 81
        assert counters["delivered_packets"] == summary["num_packets"]
        assert counters["flits_injected"] == summary["flits_total"]
        assert counters["flits_accepted"] == summary["flits_total"]
        assert evidence.backend_config_hash == \
            prepared.config.backend_config_hash()
        assert evidence.backend_input_hash == \
            prepared.manifest.backend_input_hash()


class TestForgedMeshProfileConfig:
    def test_forged_routing_function_refused(self):
        from dataclasses import replace
        from veritx_dse.backend.booksim import (
            assert_canonical_booksim_projection,
        )
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        values = dict(config.normalized_parameters)
        assert values["routing_function"] == "dim_order"
        values["routing_function"] = "planar_adapt"
        forged = replace(
            config,
            normalized_parameters=tuple(sorted(values.items())),
            artifact_hash="")
        with pytest.raises(BookSimLoweringError, match="noncanonical"):
            assert_canonical_booksim_projection(bundle, forged)


class TestTamperedRouteDump:
    def _synthetic_dump_text(self, bundle, config, *, flip=None):
        from veritx_dse.backend.booksim import expected_route_table
        table = expected_route_table(bundle, config)
        lines = ["# synthetic executed-route dump"]
        for r, d in sorted(table):
            nxt = table[(r, d)]
            if flip is not None and (r, d) == flip[0]:
                nxt = flip[1]
            lines.append(f"src_router {r} dst_node {d} "
                         f"next_router {nxt} port 0")
        return table, "\n".join(lines) + "\n"

    def test_pristine_synthetic_dump_compares_exact(self, tmp_path):
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        _table, text = self._synthetic_dump_text(bundle, config)
        dump = tmp_path / "routing.dump"
        dump.write_text(text)
        verdict = compare_route_realization(bundle, config, dump)
        assert verdict["status"] == "EXACT"
        assert verdict["pairs_compared"] == 81 * 81

    def test_single_flipped_hop_refuses(self, tmp_path):
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        table, _text = self._synthetic_dump_text(bundle, config)
        victim = next(k for k in sorted(table) if table[k] != k[0])
        flipped = (table[victim] + 1) % 81
        assert flipped != table[victim]
        _table, text = self._synthetic_dump_text(
            bundle, config, flip=(victim, flipped))
        dump = tmp_path / "routing.dump"
        dump.write_text(text)
        with pytest.raises(BookSimRouteError, match="diverges"):
            compare_route_realization(bundle, config, dump)


class TestTransplantedRouteArtifact:
    def test_foreign_anynet_route_artifact_refuses(self):
        """A valid route artifact from another fabric must not execute.

        The transplant is the 4-router ANYNET fixture artifact
        (make_bundle(build_chain()).router_route): compile_bundle on the
        same chain re-derives product routing, which P1.2 locks to
        DOR_XY on MESH — so only the fixture artifact carries the
        foreign ANYNET_MIN_HOPS keys this refusal message pins.
        """
        from dataclasses import replace
        from veritx_dse.backend.booksim import expected_route_table
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        foreign = make_bundle(build_chain()).router_route
        assert [d.id for d in foreign.routing_classes] == \
            ["ANYNET_MIN_HOPS"]
        transplant = replace(bundle, router_route=foreign)
        with pytest.raises(BookSimRouteError, match="no entry"):
            expected_route_table(transplant, config)


class TestForgedRenderedGrid:
    def _materialized(self, tmp_path):
        from veritx_dse.backend.booksim import materialize_backend
        bundle = _p1a_bundle()
        config = lower_booksim_standalone(bundle)
        prepared = prepare_booksim_standalone(
            bundle, workload_trace=b"0 0 0 1 1\n")
        backend_dir = tmp_path / "backend"
        materialize_backend(
            prepared.rendered, prepared.manifest, backend_dir)
        return bundle, config, backend_dir

    def _forge_cfg(self, backend_dir, key, value):
        cfg = backend_dir / "config.cfg"
        lines = [f"{key} = {value};" if raw.split(" = ")[0] == key
                 else raw
                 for raw in cfg.read_text().splitlines()]
        cfg.write_text("\n".join(lines) + "\n")

    def test_forged_k_refuses(self, tmp_path):
        from veritx_dse.backend.booksim import (
            BackendMaterializationError, verify_native_mesh_projection,
        )
        bundle, config, backend_dir = self._materialized(tmp_path)
        self._forge_cfg(backend_dir, "k", "8")
        with pytest.raises(BackendMaterializationError,
                            match="does not equal"):
            verify_native_mesh_projection(bundle, config, backend_dir)

    def test_forged_n_refuses(self, tmp_path):
        from veritx_dse.backend.booksim import (
            BackendMaterializationError, verify_native_mesh_projection,
        )
        bundle, config, backend_dir = self._materialized(tmp_path)
        self._forge_cfg(backend_dir, "n", "3")
        with pytest.raises(BackendMaterializationError,
                            match="does not equal"):
            verify_native_mesh_projection(bundle, config, backend_dir)

    def test_forged_routing_function_refuses(self, tmp_path):
        from veritx_dse.backend.booksim import (
            BackendMaterializationError, verify_native_mesh_projection,
        )
        bundle, config, backend_dir = self._materialized(tmp_path)
        self._forge_cfg(backend_dir, "routing_function", "min")
        with pytest.raises(BackendMaterializationError,
                            match="dim_order"):
            verify_native_mesh_projection(bundle, config, backend_dir)
