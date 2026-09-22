"""tests/test_p1b_meshdor_profile.py — P1B DOR program qualification.

CERTIFIED_BOOKSIM_MESH_DOR_XY_V1: audit closure, narrow-domain lowering,
native-mesh route equivalence (2x2, 3x3, 9x9 all-pairs first-hop tables
compared mechanically against the DOR_XY RouteArtifact — never a
Python-DOR-vs-Python comparison), adversarial refusals, the
llama_dense_64tiles exit gate (-> EVALUATED), and evaluator wiring.

Real-binary tests run wherever BookSim builds; audit/lowering/adversarial
tests are hermetic (rendering needs no binary).
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.application.fabric_compiler import (  # noqa: E402
    Compilation, FabricCompiler,
)
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    BACKEND_UNAVAILABLE, EVALUATED, FAILED, UNSUPPORTED, EvaluationOptions,
    FabricEvaluator,
)
from veritx_dse.backend.booksim import BookSimLoweringError  # noqa: E402
from veritx_dse.backend.meshdor import (  # noqa: E402
    MESHDOR_CONFIG_FILE, compare_meshdor_route_realization,
    lower_meshdor_standalone, prepare_meshdor, render_meshdor_standalone,
    run_waved_meshdor, verify_meshdor_profile_gates,
)
from veritx_dse.backend.meshdor_profile import (  # noqa: E402
    MESH_DOR_PROFILE, MESH_DOR_PROFILE_ID, MESH_DOR_SITES,
)
from veritx_dse.core.route_artifact import DOR_XY  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    Agent, AgentKind, CollectiveDimension, CollectiveIntent,
    CollectiveKind, CompileRequestV3, DependencyGraph, ModelFamily,
    NocConfig, TopologyFamily, WorkloadV3,
)
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.model.topology_artifact import (  # noqa: E402
    MaterializedFamily,
)
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)

EVAL = FabricEvaluator()
SRC = (DSE.parent.parent.parent / "third_party" / "booksim2" / "src")


def _chain(n_agents, tp, pp=1, ep=1, dp=1,
           family=TopologyFamily.MESH):
    return build_chain(tp=tp, pp=pp, ep=ep, dp=dp, n_agents=n_agents,
                       family=family)


def _compiled(n_agents, tp, pp=1, ep=1, dp=1,
              family=TopologyFamily.MESH):
    chain = _chain(n_agents, tp, pp, ep, dp, family)
    comp = FabricCompiler().compile(chain.cr)
    assert comp.status == "COMPILED", comp.error
    assert comp.certificate.overall == "PASS"
    return chain, comp


def _v3_request(*, tp, pp=1, ep=1, dp=1, payload=256, tc="A"):
    """The v3 intent whose lowering is the evaluator workload."""
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            tp=tp, pp=pp, ep=ep, dp=dp,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.GLOBAL,
                payload_bytes=payload, traffic_class=tc),)),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE,
                      count=tp * pp * ep * dp),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


def _with_request(comp, request):
    """Pair a certified v2 bundle with the v3 intent under test."""
    return Compilation(status=comp.status, request=request,
                       bundle=comp.bundle, certificate=comp.certificate,
                       error=comp.error)


def _lowered(comp):
    return lower_compile_workload(comp.request).graph


def _workload(participant_count, parallelism, *, payload=256,
              kind="ALLREDUCE", design_hash=None):
    op = OperationNode(
        "c0", KIND_COLLECTIVE, (),
        collective_detail(collective_kind=kind,
                          participants=tuple(range(participant_count)),
                          payload_bytes=payload,
                          participant_count=participant_count))
    provenance = {"design_hash": design_hash} \
        if design_hash is not None else None
    return WorkloadGraph(parallelism=parallelism,
                         participant_count=participant_count,
                         operations=(op,), semantics=WorkloadSemantics(),
                         provenance=provenance)


def _first_vc_class(bundle):
    return bundle.vc_assignment.traffic_class_to_vcs[0][0]


def _compilation_for(chain, bundle):
    from veritx_dse.verification.certificate import verify_compiled_fabric
    cert = verify_compiled_fabric(bundle)
    assert cert.overall == "PASS"
    return Compilation(status="COMPILED", request=chain.cr, bundle=bundle,
                       certificate=cert, error=None)


def _traffic_for(bundle, workload, traffic_class):
    from veritx_dse.workload.messages import LogicalMessageArtifactV2
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2
    logical = LogicalMessageArtifactV2(workload,
                                       traffic_class=traffic_class)
    return PhysicalTrafficArtifactV2(logical=logical, bundle=bundle)


def _real_binary():
    from veritx_dse.core.paths import REPO
    from veritx_dse.simulation.booksim import find_booksim_bin
    try:
        return find_booksim_bin(REPO)
    except FileNotFoundError:
        pytest.skip("no BookSim binary in this env")


def _fake_binary(tmp_path):
    import hashlib
    data = b"p1b-fake-meshdor-producer-v1"
    path = Path(tmp_path) / "fake-booksim"
    path.write_bytes(data)
    return str(path), hashlib.sha256(data).hexdigest()


# ── audit closure ───────────────────────────────────────────────────────

class TestMeshAudit:
    def test_mesh_drift_clean(self):
        from veritx_dse.backend.source_audit import audit_source_drift
        report = audit_source_drift(
            SRC, profile=MESH_DOR_PROFILE, sites=MESH_DOR_SITES)
        report.raise_if_dirty()

    def test_standalone_drift_still_clean(self):
        # The C++ dump hook adds kncube reads of ACTIVE fields only
        # (routing_dump_file, routing_function, topology): the sealed
        # AnyNet closure must not move.
        from veritx_dse.backend.booksim_profile import (
            BOOKSIM_STANDALONE_PROFILE,
        )
        from veritx_dse.backend.source_audit import (
            GATED_READ_SITES, audit_source_drift,
        )
        report = audit_source_drift(
            SRC, profile=BOOKSIM_STANDALONE_PROFILE,
            sites=GATED_READ_SITES)
        report.raise_if_dirty()

    def test_rendered_mesh_gates_hold_and_anynet_gates_refuse(self):
        from veritx_dse.backend.booksim import parse_booksim_config_values
        from veritx_dse.backend.source_audit import (
            GATED_READ_SITES, SourceAuditError, verify_site_gates,
        )
        chain, comp = _compiled(4, 4)
        pt = _traffic_for(comp.bundle, _workload(
            4, ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)),
            _first_vc_class(comp.bundle))
        prepared, _ = prepare_meshdor(pt)
        values = parse_booksim_config_values(
            prepared.rendered.file(MESHDOR_CONFIG_FILE).decode())
        verify_site_gates(MESH_DOR_SITES, values)
        with pytest.raises(SourceAuditError):
            verify_site_gates(GATED_READ_SITES, values)

    def test_ownership_is_closed_and_rendered(self):
        from veritx_dse.backend.booksim import parse_booksim_config_values
        from veritx_dse.backend.meshdor import MESHDOR_CONFIG_KEY_ORDER
        assert set(MESHDOR_CONFIG_KEY_ORDER) == \
            MESH_DOR_PROFILE.active_names()
        chain, comp = _compiled(4, 4)
        pt = _traffic_for(comp.bundle, _workload(
            4, ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)),
            _first_vc_class(comp.bundle))
        prepared, _ = prepare_meshdor(pt)
        values = parse_booksim_config_values(
            prepared.rendered.file(MESHDOR_CONFIG_FILE).decode())
        for name, value in MESH_DOR_PROFILE.pinned_values().items():
            assert name in values, name
        assert values["topology"] == "mesh"
        assert values["routing_function"] == "dim_order"
        assert "network_file" not in values
        assert sorted(n for n, _ in prepared.rendered.files) == \
            ["config.cfg", "workload.trace"]

    def test_sealed_anynet_profile_untouched(self):
        from veritx_dse.backend.booksim_profile import (
            BOOKSIM_STANDALONE_PROFILE as _SEALED,
        )
        assert _SEALED.profile_id == \
            "CERTIFIED_BOOKSIM_ANYNET_V1"
        pins = _SEALED.pinned_values()
        assert pins["topology"] == "anynet"
        assert "network_file" in _SEALED.active_names()
        assert "k" not in _SEALED.active_names()


# ── narrow-domain lowering ──────────────────────────────────────────────

class TestMeshLowering:
    def test_full_mesh_lowers_with_derived_shape(self):
        chain, comp = _compiled(4, 4)
        cfg = lower_meshdor_standalone(comp.bundle)
        assert cfg.backend_profile == MESH_DOR_PROFILE_ID
        params = dict(cfg.normalized_parameters)
        assert (params["k"], params["n"]) == (2, 2)
        assert params["routing_function"] == "dim_order"
        assert params["routing_class"] == DOR_XY

    def test_prefix_mesh_lowers(self):
        # 5 endpoints on 9 routers: identity prefix, idle native nodes.
        chain, comp = _compiled(5, 5)
        assert comp.bundle.topology.router_count == 9
        cfg = lower_meshdor_standalone(comp.bundle)
        assert dict(cfg.normalized_parameters)["k"] == 3

    def test_concentrated_mesh_refuses(self):
        chain = _chain(4, 2, dp=2,
                       family=TopologyFamily.CONCENTRATED_MESH)
        comp = FabricCompiler().compile(chain.cr)
        assert comp.status == "COMPILED"
        with pytest.raises(BookSimLoweringError, match="MESH only"):
            lower_meshdor_standalone(comp.bundle)

    def test_non_dor_bundle_refuses(self):
        from test_p1b_fabric_evaluator import _anynet_bundle_2node
        chain, bundle = _anynet_bundle_2node()
        with pytest.raises(BookSimLoweringError, match="DOR_XY"):
            lower_meshdor_standalone(bundle)

    def test_permuted_attachment_refuses(self):
        from veritx_dse.model.address_decode import (
            derive_address_decode,
        )
        from veritx_dse.model.attachment import (
            AgentAttachmentArtifact, Endpoint,
        )
        from veritx_dse.model.fabric_artifact import make_fabric_artifact
        from veritx_dse.model.packet_format import derive_packet_format
        from veritx_dse.model.resolved_bundle import (
            make_resolved_fabric_bundle,
        )
        from veritx_dse.model.resolved_fabric import make_resolved_fabric
        from veritx_dse.model.resolved_route import derive_resolved_route
        from veritx_dse.model.router_behavior import derive_router_behavior
        from veritx_dse.model.compile_model import (
            derive_vc_assignment_artifact,
        )
        chain, comp = _compiled(4, 4)
        b = comp.bundle
        endpoints = tuple(
            Endpoint(endpoint_id=e.endpoint_id, agent=e.agent,
                     router_id=(1 if e.endpoint_id == 0 else
                                0 if e.endpoint_id == 1 else
                                e.router_id),
                     port_id=e.port_id, interface=e.interface)
            for e in b.attachment.endpoints)
        att = AgentAttachmentArtifact(
            topology_hash=b.topology.topology_hash(),
            endpoints=endpoints)
        att.validate_against(chain.cr, b.inventory, b.topology)
        rra = derive_resolved_route(b.topology, att, b.router_route)
        vc = derive_vc_assignment_artifact(chain.cr, rra)
        ad = derive_address_decode(design=chain.cr, attachment=att)
        pf = derive_packet_format(topology=b.topology, attachment=att,
                                  vc_assignment=vc)
        rb = derive_router_behavior(vc_assignment=vc)
        fabric = make_fabric_artifact(
            topology=b.topology, attachment=att,
            router_route=b.router_route, resolved_route=rra,
            vc_assignment=vc, packet_format=pf, router_behavior=rb,
            address_decode=ad)
        rf = make_resolved_fabric(
            design=chain.cr, inventory=b.inventory, mapping=b.mapping,
            topology=b.topology, attachment=att,
            router_route=b.router_route, resolved_route=rra,
            vc_assignment=vc, packet_format=pf, router_behavior=rb,
            address_decode=ad, fabric=fabric)
        permuted = make_resolved_fabric_bundle(
            design=chain.cr, inventory=b.inventory, mapping=b.mapping,
            topology=b.topology, attachment=att,
            router_route=b.router_route, resolved_route=rra,
            vc_assignment=vc, packet_format=pf, router_behavior=rb,
            address_decode=ad, fabric=fabric,
            resolved_fabric=rf)
        with pytest.raises(BookSimLoweringError,
                           match="identity-prefix"):
            lower_meshdor_standalone(permuted)

    def test_link_guard_units(self):
        from veritx_dse.backend.meshdor import (
            _mesh_link_semantics, _mesh_shape,
        )

        def topo(**kw):
            kw.setdefault("family", MaterializedFamily.MESH)
            kw.setdefault("router_count", 4)
            kw.setdefault("routers", [SimpleNamespace(seat_capacity=1)
                                      for _ in range(4)])
            kw.setdefault("channels", [
                SimpleNamespace(src_router=0, dst_router=1,
                                latency_cycles=1, route_weight=1),
                SimpleNamespace(src_router=1, dst_router=0,
                                latency_cycles=1, route_weight=1)])
            return SimpleNamespace(topology=SimpleNamespace(**kw))

        assert _mesh_shape(topo()) == 2
        bad_lat = topo(channels=[
            SimpleNamespace(src_router=0, dst_router=1, latency_cycles=2,
                            route_weight=1)])
        with pytest.raises(BookSimLoweringError, match="latency 1"):
            _mesh_link_semantics(bad_lat)
        bad_w = topo(channels=[
            SimpleNamespace(src_router=0, dst_router=1, latency_cycles=1,
                            route_weight=2)])
        with pytest.raises(BookSimLoweringError, match="route_weight"):
            _mesh_link_semantics(bad_w)
        dup = topo(channels=[
            SimpleNamespace(src_router=0, dst_router=1, latency_cycles=1,
                            route_weight=1),
            SimpleNamespace(src_router=0, dst_router=1, latency_cycles=1,
                            route_weight=1)])
        with pytest.raises(BookSimLoweringError, match="parallel"):
            _mesh_link_semantics(dup)
        with pytest.raises(BookSimLoweringError, match="square"):
            _mesh_shape(topo(router_count=5,
                             routers=[SimpleNamespace(seat_capacity=1)
                                      for _ in range(5)]))
        with pytest.raises(BookSimLoweringError, match="CONCENTRATED"):
            _mesh_shape(topo(family=MaterializedFamily.CONCENTRATED_MESH))

    def test_canonical_refuses_transplant(self):
        from veritx_dse.backend.contracts import BackendConfigArtifact
        from veritx_dse.backend.meshdor import (
            assert_canonical_meshdor_projection,
        )
        chain_a = build_chain(tp=4, pp=1, ep=1, dp=1, n_agents=4,
                              family=TopologyFamily.MESH)
        from veritx_dse.application.compile import compile_bundle
        bundle_a = compile_bundle(chain_a.cr)
        cfg_a = lower_meshdor_standalone(bundle_a)
        # A consistently re-hashed forgery (same bundle, mutated k):
        # fabric hashes match, so only the re-lowering check can catch
        # it — this is the "differs in" path.
        params = dict(cfg_a.normalized_parameters)
        params["k"] = params["k"] + 1
        forged = BackendConfigArtifact(
            backend_target=cfg_a.backend_target,
            backend_profile=cfg_a.backend_profile,
            backend_semantics_version=
            cfg_a.backend_semantics_version,
            lowerer_version=cfg_a.lowerer_version,
            resolved_fabric_hash=cfg_a.resolved_fabric_hash,
            fabric_hash=cfg_a.fabric_hash,
            normalized_parameters=tuple(sorted(params.items())),
            semantic_bindings=cfg_a.semantic_bindings)
        with pytest.raises(BookSimLoweringError, match="differs in"):
            assert_canonical_meshdor_projection(bundle_a, forged)

    def test_wrong_dump_refuses(self, tmp_path):
        import re
        chain, comp = _compiled(4, 4)
        pt = _traffic_for(comp.bundle, _workload(
            4, ParallelismArtifact(tp=4, pp=1, ep=1, dp=1)),
            _first_vc_class(comp.bundle))
        prepared, _ = prepare_meshdor(pt)
        from veritx_dse.backend.projection import render_waved_trace
        _ = render_waved_trace(pt)
        from veritx_dse.core.paths import REPO
        from veritx_dse.simulation.booksim import find_booksim_bin
        binary = find_booksim_bin(REPO)
        run_dir = Path(tmp_path) / "run" / "backend"
        run_dir.mkdir(parents=True)
        from veritx_dse.backend.meshdor import materialize_mesh_backend
        paths = materialize_mesh_backend(
            prepared.rendered, prepared.manifest, run_dir)
        import subprocess
        subprocess.run([str(binary), "config.cfg"], cwd=str(run_dir),
                       capture_output=True, timeout=120)
        dump = run_dir / "routing.dump"
        assert dump.exists()
        rows = dump.read_text().splitlines()
        data = [ln for ln in rows if not ln.startswith("#")]
        first = data[0].split()
        # Flip the first next-hop to a different router.
        bad_next = (int(first[5]) + 1) % 4
        data[0] = (
            f"src_router {first[1]} dst_node {first[3]} "
            f"next_router {bad_next} port {first[7]}")
        dump.write_text("\n".join([rows[0]] + data) + "\n")
        with pytest.raises(Exception, match="diverges"):
            compare_meshdor_route_realization(
                comp.bundle, prepared.config, dump)


# ── native route equivalence (real binary) ──────────────────────────────────

class TestRouteEquivalence:
    def _run_mesh(self, n_agents, tp, pp=1, ep=1, dp=1, tmp_path=None,
                  payload=256, participants=4):
        from veritx_dse.core.paths import REPO
        binary = _real_binary()
        chain, comp = _compiled(n_agents, tp, pp, ep, dp)
        n_routers = comp.bundle.topology.router_count
        pa = ParallelismArtifact(tp=tp, pp=pp, ep=ep, dp=dp)
        pt = _traffic_for(comp.bundle,
                          _workload(participants, pa, payload=payload),
                          _first_vc_class(comp.bundle))
        prepared, summary = prepare_meshdor(pt)
        result = run_waved_meshdor(
            prepared, run_dir=Path(tmp_path) / "run", repo_root=REPO,
            timeout=300, binary=Path(str(binary)), summary=summary)
        ev = result["evidence"]
        assert ev.exit_status == 0
        assert ev.route_equivalence == "EXACT"
        assert ev.route_pairs_compared == n_routers * n_routers
        assert ev.stats["delivered"] == summary["num_packets"]
        return comp, ev, summary

    def test_2x2_dump_equivalent(self, tmp_path):
        self._run_mesh(4, 4, tmp_path=tmp_path)

    def test_3x3_dump_equivalent(self, tmp_path):
        self._run_mesh(9, 3, 1, 3, tmp_path=tmp_path)

    def test_9x9_dump_equivalent(self, tmp_path):
        comp, ev, summary = self._run_mesh(81, 9, 1, 9, tmp_path=tmp_path,
                                           payload=256, participants=4)
        assert summary["num_packets"] > 0
        assert ev.stats["completion_time"] > 0


# ── exit gate: llama_dense_64tiles -> EVALUATED ─────────────────────────────

class TestExitGate:
    def test_llama_dense_64tiles_evaluated(self, tmp_path):
        import json
        from veritx_dse.core.paths import REPO
        from veritx_dse.model.compile_model import CompileRequest
        example = (DSE.parent / "examples" / "llama_dense_64tiles.json")
        assert example.is_file(), "llama_dense_64tiles example missing"
        request = CompileRequest.from_dict(json.loads(example.read_text()))
        comp = FabricCompiler().compile(request)
        assert comp.status == "COMPILED", comp.error
        assert comp.certificate.overall == "PASS"
        bundle = comp.bundle
        assert bundle.topology.router_count == 81
        tc = _first_vc_class(bundle)
        comp = _with_request(comp, _v3_request(tp=8, payload=2048, tc=tc))
        workload = _lowered(comp)
        binary = _real_binary()
        out = EVAL.evaluate(
            comp, workload,
            EvaluationOptions(traffic_class=tc,
                              network_clock_hz=10 ** 9,
                              run_dir=str(tmp_path),
                              binary=str(binary), timeout_s=600))
        assert out.status == EVALUATED, out.reason
        assert out.backend_profile == MESH_DOR_PROFILE_ID
        assert out.performance_result_id
        assert out.network_traffic_window["cycles_only"] is False
        assert out.network_traffic_window["wall_time_ns"] is not None
        view = out.to_view_dict()
        import jsonschema
        import json as _json
        schema = _json.loads((DSE.parent.parent.parent / "contracts" /
                              "srota" / "v1" /
                              "evaluation.view.schema.json").read_text())
        jsonschema.validate(view, schema)


# ── evaluator wiring over the mesh path (hermetic stub) ─────────────────────

def _stub_meshdor_run(monkeypatch, *, completion=59,
                      delivered_override=None, producer_sha="cd" * 32):
    import hashlib
    import veritx_dse.backend.meshdor as meshdor
    from veritx_dse.backend.booksim import (
        CertifiedBookSimEvidence, expected_route_table,
    )
    from veritx_dse.core.spec import canonical_json

    def _fake(prepared, *, run_dir, repo_root, timeout, binary):
        trace = dict(prepared.rendered.files)["workload.trace"]
        lines = [ln.split() for ln in trace.decode().splitlines()
                 if ln.strip()]
        num_packets = len(lines)
        flits_total = sum(int(ln[4]) for ln in lines)
        delivered = num_packets if delivered_override is None \
            else delivered_override
        expected = expected_route_table(prepared.bundle, prepared.config)
        exp_sha = hashlib.sha256(canonical_json(
            [[r, e, expected[(r, e)]] for r, e in sorted(expected)]
        ).encode()).hexdigest()
        stats = {"completion_time": completion, "delivered": delivered,
                 "pkt_count": delivered, "flits_injected": flits_total,
                 "flits_accepted": flits_total,
                 "drain_verdict": "stub", "latency": 9.5}
        return CertifiedBookSimEvidence(
            backend_config_hash=prepared.config.backend_config_hash(),
            backend_input_hash=prepared.manifest.backend_input_hash(),
            resolved_fabric_hash=prepared.config.resolved_fabric_hash,
            fabric_hash=prepared.config.fabric_hash,
            route_equivalence="EXACT",
            route_expected_sha256=exp_sha,
            route_executed_sha256=exp_sha,
            route_pairs_compared=len(expected),
            exact_fabric_eligible=prepared.config.exact_fabric_eligible(),
            qualification="EXECUTED_WITH_DECLARED_LOSS",
            semantic_loss=prepared.config.semantic_loss_summary(),
            stats=stats, exit_status=0, wall_time_s=0.1,
            command=("stub-booksim",), backend_dir=str(run_dir),
            workload_hash=prepared.manifest.workload_hash,
            seed=prepared.manifest.seed,
            seed_policy=prepared.manifest.seed_policy,
            rendered_inputs=tuple(r.identity_dict()
                                  for r in prepared.manifest.rendered_inputs),
            invocation_args=prepared.manifest.invocation_args,
            booksim_binary_sha256=producer_sha,
            producer_source_revision=None,
            producer_source_dirty=None,
            producer_source_dirty_digest=None,
            producer_tool_identity="stub",
            execution_transport="SUPERVISED_PROCESS")

    monkeypatch.setattr(meshdor, "run_meshdor_booksim", _fake)


class TestMeshEvaluatorStub:
    def test_stubbed_mesh_evaluated(self, monkeypatch, tmp_path):
        fake_bin, fake_sha = _fake_binary(tmp_path)
        _stub_meshdor_run(monkeypatch, completion=59,
                          producer_sha=fake_sha)
        chain, comp = _compiled(4, 4)
        tc = _first_vc_class(comp.bundle)
        comp = _with_request(comp, _v3_request(tp=4, tc=tc))
        out = EVAL.evaluate(
            comp, _lowered(comp),
            EvaluationOptions(traffic_class=tc,
                              network_clock_hz=10 ** 9, binary=fake_bin,
                              run_dir=str(tmp_path)))
        assert out.status == EVALUATED, out.reason
        assert out.backend_profile == MESH_DOR_PROFILE_ID
        assert out.producer_identity == fake_sha
        assert out.network_traffic_window == {
            "window_cycles": 59, "wall_time_ns": 59.0,
            "cycles_only": False}
        from veritx_dse.core.time import QTime
        from veritx_dse.performance.model import (
            ClockDef, PerformanceModel, ResourceDef,
        )
        from veritx_dse.performance.result import reverify_result
        from veritx_dse.performance.workload import (
            EVENT_NETWORK_TRAFFIC_WINDOW, TemporalEvent, TemporalWorkload,
        )
        model = PerformanceModel(
            clocks=(ClockDef("network", 10 ** 9),),
            resources=(ResourceDef("fabric.network_window", "EXCLUSIVE",
                                   capacity=1),),
            network_clock="network")
        temporal = TemporalWorkload(
            performance_model=model,
            events=(TemporalEvent("network_traffic_window",
                                  EVENT_NETWORK_TRAFFIC_WINDOW,
                                  QTime.zero()),))
        reverify_result(dict(out.performance_result), workload=temporal)

    def test_stubbed_mesh_quiescence_failed(self, monkeypatch, tmp_path):
        fake_bin, fake_sha = _fake_binary(tmp_path)
        _stub_meshdor_run(monkeypatch, delivered_override=1,
                          producer_sha=fake_sha)
        chain, comp = _compiled(4, 4)
        tc = _first_vc_class(comp.bundle)
        comp = _with_request(comp, _v3_request(tp=4, tc=tc))
        out = EVAL.evaluate(
            comp, _lowered(comp),
            EvaluationOptions(traffic_class=tc,
                              network_clock_hz=10 ** 9, binary=fake_bin,
                              run_dir=str(tmp_path)))
        assert out.status == FAILED
        assert "delivered" in (out.reason or "")


# ── cross-backend qualification dispatch ────────────────────────────────────

class TestCrossQualificationDispatch:
    def test_mesh_profile_routes_to_mesh_canonical_assert(self):
        from types import SimpleNamespace as _NS
        from veritx_dse.backend.contracts import BackendTarget
        from veritx_dse.backend.meshdor_profile import MESH_DOR_PROFILE_ID
        from veritx_dse.backend.qualification import (
            QualificationError, qualify_cross_backend,
        )
        chain, comp = _compiled(4, 4)
        mesh_stub = _NS(backend_target=BackendTarget.BOOKSIM_STANDALONE,
                        backend_profile=MESH_DOR_PROFILE_ID,
                        backend_semantics_version="FORGED",
                        fabric_hash="0" * 64, resolved_fabric_hash="1" * 64)
        serving_stub = _NS(
            backend_target=BackendTarget.SERVING_BOOKSIM2,
            backend_profile="CERTIFIED_SERVING_BOOKSIM2_V1",
            fabric_hash="0" * 64, resolved_fabric_hash="1" * 64)
        with pytest.raises(QualificationError, match="mesh-DOR lowering"):
            qualify_cross_backend(
                comp.bundle,
                {"BOOKSIM_STANDALONE": mesh_stub,
                 "SERVING_BOOKSIM2": serving_stub})
