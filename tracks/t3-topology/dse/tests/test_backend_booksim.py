"""Wave B3.7b tests — canonical standalone BookSim lowering + proof.

Focused on the two watchlist hazards: the route realization must be
mechanically proven (not inferred from a config name), and link
latency/route cost coupling must refuse rather than approximate.
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

from test_fabric_artifact import build_chain, compose, _with_hbm  # noqa: E402

from veritx_dse.backend.booksim import (  # noqa: E402
    BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION,
    BOOKSIM_STANDALONE_OWNERSHIP, BOOKSIM_STANDALONE_PROFILE, CONFIG_FILE,
    ROUTE_DUMP_FILE, TOPOLOGY_FILE, WORKLOAD_FILE, BackendMaterializationError,
    BookSimLoweringError, BookSimRouteError, bind_booksim_inputs,
    lower_booksim_standalone, materialize_backend, prepare_booksim_standalone,
    render_booksim_standalone, run_certified_booksim, verify_materialized,
)
from veritx_dse.backend.bundle import make_resolved_fabric_bundle  # noqa: E402
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendConfigArtifact, BackendTarget, CertificationEffect,
    ParameterOwner, RepresentationStatus, SemanticDimension, sha256_bytes,
)
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, RouteArtifact  # noqa: E402
from veritx_dse.model.address_decode import derive_address_decode  # noqa: E402
from veritx_dse.model.attachment import derive_attachment  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    derive_vc_assignment_artifact,
)
from veritx_dse.model.fabric_artifact import make_fabric_artifact  # noqa: E402
from veritx_dse.model.packet_format import derive_packet_format  # noqa: E402
from veritx_dse.model.resolved_fabric import make_resolved_fabric  # noqa: E402
from veritx_dse.model.resolved_route import derive_resolved_route  # noqa: E402
from veritx_dse.model.router_behavior import derive_router_behavior  # noqa: E402
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact  # noqa: E402

TRACE = b"0 0 0 3 2\n10 3 0 0 2\n"


@pytest.fixture(scope="module")
def chain():
    return build_chain()


def rebuild_bundle(chain, *, topo=None, vc=None, pf=None, rb=None,
                   routing_classes=(ANYNET_MIN_HOPS,)):
    """Re-derive a complete validated bundle from (possibly modified)
    semantic inputs using the public B3 APIs only."""
    topo = chain.topo if topo is None else topo
    att = derive_attachment(design=chain.cr, inventory=chain.inv,
                            topology=topo)
    rr = RouteArtifact.from_topology(topo, name="chain",
                                     routing_classes=routing_classes)
    rra = derive_resolved_route(topo, att, rr)
    vc = vc if vc is not None else derive_vc_assignment_artifact(chain.cr, rra)
    pf = pf if pf is not None else derive_packet_format(
        topology=topo, attachment=att, vc_assignment=vc)
    rb = rb if rb is not None else derive_router_behavior(vc_assignment=vc)
    ad = derive_address_decode(design=chain.cr, attachment=att)
    fabric = make_fabric_artifact(
        topology=topo, attachment=att, router_route=rr, resolved_route=rra,
        vc_assignment=vc, packet_format=pf, router_behavior=rb,
        address_decode=ad)
    rf = make_resolved_fabric(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=topo, attachment=att, router_route=rr, resolved_route=rra,
        vc_assignment=vc, packet_format=pf, router_behavior=rb,
        address_decode=ad, fabric=fabric)
    return make_resolved_fabric_bundle(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=topo, attachment=att, router_route=rr,
        resolved_route=rra, vc_assignment=vc, packet_format=pf,
        router_behavior=rb, address_decode=ad, fabric=fabric,
        resolved_fabric=rf)


def with_channels_replaced(topo, predicate, **fields):
    return replace(topo, channels=tuple(
        replace(c, **fields) if predicate(c) else c
        for c in topo.channels))


@pytest.fixture(scope="module")
def bundle(chain):
    from test_backend_bundle import make_bundle
    return make_bundle(chain)


@pytest.fixture(scope="module")
def lowered(bundle):
    return lower_booksim_standalone(bundle)


# ── lowering ────────────────────────────────────────────────────────────

class TestLowering:
    def test_target_profile_and_versions(self, lowered):
        assert lowered.backend_target is BackendTarget.BOOKSIM_STANDALONE
        assert lowered.backend_profile == BOOKSIM_STANDALONE_PROFILE
        assert lowered.backend_semantics_version \
            == BOOKSIM_BACKEND_SEMANTICS_VERSION
        assert lowered.lowerer_version == BOOKSIM_LOWERER_VERSION

    def test_every_dimension_bound_once(self, lowered):
        dims = [b.dimension for b in lowered.semantic_bindings]
        assert dims == list(SemanticDimension)

    def test_golden_chain_losses_are_explicit(self, lowered):
        assert lowered.binding(SemanticDimension.VC_CLASS_ASSIGNMENT) \
            .representation_status is RepresentationStatus.COARSENED
        assert lowered.binding(SemanticDimension.OUTPUT_STAGE_DEPTH) \
            .representation_status is RepresentationStatus.COARSENED
        assert lowered.binding(SemanticDimension.OUTPUT_DELAY_CYCLES) \
            .representation_status is RepresentationStatus.UNREPRESENTABLE
        # Not an exact-fabric run: downgraded VC class + output staging.
        assert not lowered.exact_fabric_eligible()

    def test_exact_irrelevant_dimensions(self, lowered):
        for dim in (SemanticDimension.CHANNEL_LATENCY,
                    SemanticDimension.ROUTE_REALIZATION,
                    SemanticDimension.VC_COUNT,
                    SemanticDimension.HOLD_SWITCH_FOR_PACKET,
                    SemanticDimension.CREDIT_RETURN_LATENCY,
                    SemanticDimension.PLANE_COMPOSITION):
            b = lowered.binding(dim)
            assert b.representation_status in (
                RepresentationStatus.EXACT,
                RepresentationStatus.DERIVED_EXACT), dim
        assert lowered.binding(SemanticDimension.ADDRESS_DECODE) \
            .representation_status is RepresentationStatus.BACKEND_IRRELEVANT

    def test_hold_switch_is_emitted(self, lowered, chain):
        rb = replace(chain.rb, artifact_hash="", hold_switch_for_packet=True)
        b = rebuild_bundle(chain, rb=rb)
        art = lower_booksim_standalone(b)
        assert dict(art.normalized_parameters)["hold_switch_for_packet"] == 1
        assert art.binding(SemanticDimension.HOLD_SWITCH_FOR_PACKET) \
            .representation_status is RepresentationStatus.EXACT

    def test_escape_vcs_block_exact_fabric(self, chain):
        rra = chain.rra
        vc = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [1], "B": [0]},
            derivation="escape-vc test", escape_vcs=(0,))
        b = rebuild_bundle(chain, vc=vc)
        art = lower_booksim_standalone(b)
        esc = art.binding(SemanticDimension.ESCAPE_VCS)
        assert esc.representation_status is RepresentationStatus.UNREPRESENTABLE
        assert esc.certification_effect is \
            CertificationEffect.BLOCKS_EXACT_FABRIC
        assert not art.exact_fabric_eligible()

    def test_cross_vc_transitions_unrepresentable(self, chain):
        vc = make_vc_assignment_artifact(
            resolved_route=chain.rra, vc_count=2,
            traffic_class_to_vcs={"A": [1], "B": [0]},
            derivation="transition test", allowed_transitions=((0, 1), (1, 0)))
        b = rebuild_bundle(chain, vc=vc)
        art = lower_booksim_standalone(b)
        assert art.binding(SemanticDimension.VC_TRANSITIONS) \
            .representation_status is RepresentationStatus.UNREPRESENTABLE

    def test_single_class_all_vcs_is_exact(self, chain):
        vc = make_vc_assignment_artifact(
            resolved_route=chain.rra, vc_count=2,
            traffic_class_to_vcs={"DEFAULT": [0, 1]},
            derivation="single class")
        b = rebuild_bundle(chain, vc=vc)
        art = lower_booksim_standalone(b)
        assert art.binding(SemanticDimension.VC_CLASS_ASSIGNMENT) \
            .representation_status is RepresentationStatus.EXACT

    def test_ownership_table_is_closed(self, lowered):
        emitted = {k for k, _ in lowered.normalized_parameters
                   if k not in ("routing_class", "channel_latency_cycles")}
        assert emitted <= set(BOOKSIM_STANDALONE_OWNERSHIP)
        for owner in BOOKSIM_STANDALONE_OWNERSHIP.values():
            assert isinstance(owner, ParameterOwner)

    def test_resolved_fabric_hash_binds(self, lowered, bundle):
        assert lowered.resolved_fabric_hash == \
            bundle.resolved_fabric.resolved_fabric_hash()
        assert lowered.fabric_hash == bundle.fabric.fabric_hash()


class TestLoweringRefusals:
    def test_heterogeneous_latency_refused(self, chain):
        topo = with_channels_replaced(
            chain.topo, lambda c: c.channel_id == 0, latency_cycles=2)
        with pytest.raises(BookSimLoweringError,
                           match="couples link latency and route cost"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_non_unit_route_weight_refused(self, chain):
        topo = with_channels_replaced(
            chain.topo, lambda c: c.channel_id == 0, route_weight=3)
        with pytest.raises(BookSimLoweringError,
                           match="route_weight"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_zero_latency_refused(self, chain):
        topo = replace(chain.topo, channels=tuple(
            replace(c, latency_cycles=0) for c in chain.topo.channels))
        with pytest.raises(BookSimLoweringError, match="latency >= 1"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_parallel_channels_refused(self, chain):
        extra = replace(chain.topo.channels[0],
                        channel_id=len(chain.topo.channels))
        topo = replace(chain.topo,
                       channels=chain.topo.channels + (extra,))
        with pytest.raises(BookSimLoweringError,
                           match="parallel channels"):
            lower_booksim_standalone(rebuild_bundle(chain, topo=topo))

    def test_unknown_profile_refused(self, bundle):
        with pytest.raises(BookSimLoweringError, match="unknown"):
            lower_booksim_standalone(bundle, profile="NOPE")

    def test_vc_routing_class_split_refused(self, chain):
        from veritx_dse.core.route_artifact import DOR_XY
        routing_classes = (ANYNET_MIN_HOPS, DOR_XY)
        att = derive_attachment(design=chain.cr, inventory=chain.inv,
                                topology=chain.topo)
        rr = RouteArtifact.from_topology(
            chain.topo, name="chain", routing_classes=routing_classes)
        rra = derive_resolved_route(chain.topo, att, rr)
        vc = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [1], "B": [0]},
            derivation="split routing class",
            vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: DOR_XY})
        b = rebuild_bundle(chain, vc=vc, routing_classes=routing_classes)
        with pytest.raises(BookSimLoweringError,
                           match="one global routing function"):
            lower_booksim_standalone(b)


# ── rendering + input binding ───────────────────────────────────────────

class TestRendering:
    def test_file_set_and_content(self, bundle, lowered):
        r = render_booksim_standalone(bundle, lowered,
                                      workload_trace=TRACE, seed=None)
        assert [n for n, _ in r.files] == [
            CONFIG_FILE, TOPOLOGY_FILE, WORKLOAD_FILE]
        cfg = r.file(CONFIG_FILE).decode()
        assert "topology = anynet;" in cfg
        assert "network_file = topology.anynet;" in cfg
        assert "traffic = trace(workload.trace);" in cfg
        assert "hold_switch_for_packet = 0;" in cfg
        # packet_size is deliberately NOT a config authority.
        assert "packet_size" not in cfg
        assert "routing_dump_file = routing.dump;" in cfg
        # No absolute paths anywhere in the rendered bytes.
        assert b"/" not in r.file(CONFIG_FILE)
        anynet = r.file(TOPOLOGY_FILE).decode()
        assert anynet.splitlines()[0] == "router 0 node 0 router 1 1 router 2 1"

    def test_sample_period_from_trace(self, bundle, lowered):
        r = render_booksim_standalone(bundle, lowered,
                                      workload_trace=b"0 0 0 1 1\n999 1 0 0 1\n")
        assert r.sample_period == 2000
        assert r.trace_summary.num_packets == 2
        assert r.trace_summary.max_timestamp == 999

    def test_anynet_roundtrip_ok(self, bundle, lowered, tmp_path):
        from veritx_dse.backend.booksim import verify_anynet_roundtrip
        r = render_booksim_standalone(bundle, lowered, workload_trace=TRACE)
        path = tmp_path / TOPOLOGY_FILE
        path.write_bytes(r.file(TOPOLOGY_FILE))
        report = verify_anynet_roundtrip(bundle, path)
        assert report["routers"] == 4
        assert report["nodes"] == 4

    def test_trace_over_cap_refused(self, bundle, lowered):
        with pytest.raises(BookSimLoweringError, match="exceeds"):
            render_booksim_standalone(
                bundle, lowered, workload_trace=b"0 0 0 1 9\n")

    def test_trace_node_outside_universe_refused(self, bundle, lowered):
        with pytest.raises(BookSimLoweringError, match="outside"):
            render_booksim_standalone(
                bundle, lowered, workload_trace=b"0 0 0 9 1\n")

    def test_trace_nonpositive_size_refused(self, bundle, lowered):
        with pytest.raises(BookSimLoweringError, match="non-positive"):
            render_booksim_standalone(
                bundle, lowered, workload_trace=b"0 0 0 1 0\n")

    def test_csv_dialect_accepted(self, bundle, lowered):
        r = render_booksim_standalone(
            bundle, lowered,
            workload_trace=b"timestamp,src,dst,type,packet_size\n"
                           b"0,0,3,READ,2\n")
        assert r.trace_summary.dialect == "csv"
        assert r.trace_summary.num_packets == 1

    def test_render_refuses_foreign_bundle(self, bundle, lowered, chain):
        other = _with_hbm()
        from test_backend_bundle import make_bundle
        foreign = make_bundle(other)
        with pytest.raises(BookSimLoweringError, match="does not match"):
            render_booksim_standalone(foreign, lowered,
                                      workload_trace=TRACE)

    def test_seed_rendered_and_manifested(self, bundle, lowered):
        r = render_booksim_standalone(bundle, lowered, workload_trace=TRACE,
                                      seed=7)
        assert "seed = 7;" in r.file(CONFIG_FILE).decode()
        m = bind_booksim_inputs(lowered, r,
                                workload_hash=sha256_bytes(TRACE), seed=7)
        assert m.seed == 7 and m.seed_policy == "explicit"
        assert m.invocation_args == (("config-file", CONFIG_FILE),)

    def test_input_manifest_roles_and_content(self, bundle, lowered):
        r = render_booksim_standalone(bundle, lowered, workload_trace=TRACE)
        m = bind_booksim_inputs(lowered, r,
                                workload_hash=sha256_bytes(TRACE))
        assert {i.role for i in m.rendered_inputs} == {
            "booksim_config", "topology", "workload"}
        assert m.input(CONFIG_FILE).sha256 \
            == sha256_bytes(r.file(CONFIG_FILE))
        assert m.workload_hash == sha256_bytes(TRACE)
        assert m.seed == 1 and m.seed_policy == "pinned_default"

    def test_manifest_rejects_wrong_workload_hash(self, bundle, lowered):
        from veritx_dse.backend.contracts import BackendInputError
        r = render_booksim_standalone(bundle, lowered, workload_trace=TRACE)
        with pytest.raises(BackendInputError, match="workload_hash"):
            bind_booksim_inputs(lowered, r, workload_hash="a" * 64)


# ── identity algebra under mutation ─────────────────────────────────────

class TestSemanticMutations:
    def _hash(self, chain, **kw):
        return lower_booksim_standalone(rebuild_bundle(chain, **kw)) \
            .backend_config_hash()

    def test_router_behavior_mutations_change_hash(self, chain):
        base = lower_booksim_standalone(rebuild_bundle(chain)) \
            .backend_config_hash()
        for field, value in (
                ("input_buffer_depth_flits_per_vc", 16),
                ("allocator_iterations", 3),
                ("hold_switch_for_packet", True),
                ("credit_return_latency_cycles", 4),
                ("route_compute_cycles", 2),
                ("input_speedup", 2),
        ):
            rb = replace(chain.rb, artifact_hash="", **{field: value})
            b = rebuild_bundle(chain, rb=rb)
            assert lower_booksim_standalone(b).backend_config_hash() != base, \
                field

    def test_max_packet_flits_mutation_changes_binding(self, chain):
        pf = derive_packet_format(topology=chain.topo,
                                  attachment=chain.att,
                                  vc_assignment=chain.vc,
                                  max_packet_flits=16)
        art = lower_booksim_standalone(rebuild_bundle(chain, pf=pf))
        assert art.binding(SemanticDimension.PACKET_MAX_FLITS) \
            .source_identity == pf.packet_format_hash()

    def test_topology_hash_change_alters_bindings(self, chain):
        from veritx_dse.model.topology_artifact import PhysicalLink
        topo = replace(chain.topo, physical_links=(
            PhysicalLink(physical_link_id=0, channel_ids=(0,)),))
        assert topo.topology_hash() != chain.topo.topology_hash()
        art = lower_booksim_standalone(rebuild_bundle(chain, topo=topo))
        assert art.binding(SemanticDimension.TOPOLOGY_GRAPH) \
            .source_identity == topo.topology_hash()

    def test_seed_does_not_change_config_hash(self, bundle, lowered):
        r1 = render_booksim_standalone(bundle, lowered, workload_trace=TRACE,
                                       seed=1)
        r2 = render_booksim_standalone(bundle, lowered, workload_trace=TRACE,
                                       seed=2)
        assert lowered.backend_config_hash() == lowered.backend_config_hash()
        m1 = bind_booksim_inputs(lowered, r1,
                                 workload_hash=sha256_bytes(TRACE), seed=1)
        m2 = bind_booksim_inputs(lowered, r2,
                                 workload_hash=sha256_bytes(TRACE), seed=2)
        assert m1.backend_input_hash() != m2.backend_input_hash()

    def test_target_change_changes_config_hash(self, bundle, lowered):
        other = BackendConfigArtifact(
            backend_target=BackendTarget.SERVING_BOOKSIM2,
            backend_profile=lowered.backend_profile,
            backend_semantics_version=lowered.backend_semantics_version,
            lowerer_version=lowered.lowerer_version,
            resolved_fabric_hash=lowered.resolved_fabric_hash,
            fabric_hash=lowered.fabric_hash,
            normalized_parameters=lowered.normalized_parameters,
            semantic_bindings=lowered.semantic_bindings)
        assert other.backend_config_hash() != lowered.backend_config_hash()

    def test_workload_change_changes_input_not_config(self, bundle, lowered):
        r = render_booksim_standalone(bundle, lowered, workload_trace=TRACE)
        m1 = bind_booksim_inputs(lowered, r, workload_hash=sha256_bytes(TRACE))
        other = TRACE + b"11 1 0 2 2\n"
        r2 = render_booksim_standalone(bundle, lowered, workload_trace=other)
        m2 = bind_booksim_inputs(lowered, r2,
                                 workload_hash=sha256_bytes(other))
        assert m1.backend_config_hash == m2.backend_config_hash
        assert m1.backend_input_hash() != m2.backend_input_hash()


# ── materialization/tamper ──────────────────────────────────────────────

class TestMaterialization:
    def test_materialize_and_verify(self, bundle, lowered, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        paths = materialize_backend(prepared.rendered, prepared.manifest,
                                    tmp_path / "backend")
        assert set(paths) == {CONFIG_FILE, TOPOLOGY_FILE, WORKLOAD_FILE}
        verify_materialized(prepared.manifest, tmp_path / "backend")

    def test_conflicting_content_refused(self, bundle, lowered, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        directory = tmp_path / "backend"
        (directory).mkdir()
        (directory / CONFIG_FILE).write_text("tampered")
        with pytest.raises(BackendMaterializationError,
                           match="refusing to overwrite"):
            materialize_backend(prepared.rendered, prepared.manifest,
                                directory)

    def test_modified_file_refused_before_spawn(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        directory = tmp_path / "backend"
        materialize_backend(prepared.rendered, prepared.manifest, directory)
        (directory / WORKLOAD_FILE).write_bytes(b"0 0 0 1 1\n")
        with pytest.raises(BackendMaterializationError, match="modified"):
            verify_materialized(prepared.manifest, directory)


# ── certified execution with injected runner ────────────────────────────

class _FakeResult:
    def __init__(self, stdout="", returncode=0, timed_out=False):
        self.stdout = stdout
        self.stderr = ""
        self.returncode = returncode
        self.timed_out = timed_out


_OK_STDOUT = (
    "Packet latency average = 12.0\n"
    "\tmaximum = 12.0\n"
    "Packet latency average = 12.0 (2 samples)\n"
    "Accepted packet rate average = 0.5\n"
    "Trace replay complete: delivered 2 packets, drain took 0 cycles\n"
)


def expected_dump_text(bundle, config, *, mutate=None):
    """Render the dump the C++ seam would write (test fixture only)."""
    selected = dict(config.normalized_parameters)["routing_class"]
    channels = {c.channel_id: c for c in bundle.topology.channels}
    e2r = dict(bundle.resolved_route.endpoint_to_router)
    lines = ["# fake"]
    rows = []
    for r in range(bundle.topology.router_count):
        for ep in bundle.attachment.endpoints:
            t = e2r[ep.endpoint_id]
            if r == t:
                nxt = r
            else:
                nxt = channels[bundle.router_route.entries[
                    (selected, r, t)]].dst_router
            if mutate is not None and (r, ep.endpoint_id) in mutate:
                nxt = mutate[(r, ep.endpoint_id)]
            rows.append((r, ep.endpoint_id, nxt))
    for r, e, n in sorted(rows):
        lines.append(f"src_router {r} dst_node {e} next_router {n} port 0")
    return "\n".join(lines) + "\n"


def make_capturing_runner(bundle, config, *, mutate=None, missing_dump=False,
                          capture=None):
    def runner(cmd, cwd, timeout):
        if capture is not None:
            capture["cmd"] = cmd
            capture["cwd"] = cwd
        if not missing_dump:
            Path(cwd, ROUTE_DUMP_FILE).write_text(
                expected_dump_text(bundle, config, mutate=mutate))
        return _FakeResult(stdout=_OK_STDOUT)
    return runner


class TestCertifiedExecution:
    def test_spawn_args_and_evidence(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        capture: dict = {}
        ev = run_certified_booksim(
            prepared, run_dir=tmp_path, repo_root=tmp_path,
            runner=make_capturing_runner(bundle, prepared.config,
                                         capture=capture),
            binary=Path("/bin/true"))
        assert capture["cmd"] == ["/bin/true", CONFIG_FILE]
        assert capture["cwd"].endswith("backend")
        assert ev.route_equivalence == "EXACT"
        assert ev.route_expected_sha256 == ev.route_executed_sha256
        assert ev.route_pairs_compared == 16
        assert ev.backend_config_hash == prepared.config.backend_config_hash()
        assert ev.backend_input_hash == prepared.manifest.backend_input_hash()
        assert ev.stats["latency"] == 12.0
        assert ev.semantic_loss

    def test_route_divergence_refused(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        with pytest.raises(BookSimRouteError, match="diverges"):
            run_certified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=make_capturing_runner(
                    bundle, prepared.config, mutate={(0, 3): 2}),
                binary=Path("/bin/true"))

    def test_missing_route_dump_refused(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        with pytest.raises(BookSimRouteError, match="no route dump"):
            run_certified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=make_capturing_runner(bundle, prepared.config,
                                             missing_dump=True),
                binary=Path("/bin/true"))

    def test_zero_delivery_refused(self, bundle, tmp_path):
        from veritx_dse.core.errors import BookSimError
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)

        def runner(cmd, cwd, timeout):
            Path(cwd, ROUTE_DUMP_FILE).write_text(
                expected_dump_text(bundle, prepared.config))
            return _FakeResult(stdout="delivered 0 packets\n")

        with pytest.raises(BookSimError, match="0 packets"):
            run_certified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=runner, binary=Path("/bin/true"))

    def test_timeout_refused(self, bundle, tmp_path):
        from veritx_dse.core.errors import TimeoutError
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)

        def runner(cmd, cwd, timeout):
            return _FakeResult(returncode=-9, timed_out=True)

        with pytest.raises(TimeoutError):
            run_certified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=runner, binary=Path("/bin/true"))

    def test_tamper_after_planning_blocks_spawn(self, bundle, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        directory = tmp_path / "backend"
        materialize_backend(prepared.rendered, prepared.manifest, directory)
        (directory / CONFIG_FILE).write_text("topology = mesh;\n")
        called = {"n": 0}

        def runner(cmd, cwd, timeout):
            called["n"] += 1
            return _FakeResult(stdout=_OK_STDOUT)

        with pytest.raises(BackendMaterializationError):
            run_certified_booksim(
                prepared, run_dir=tmp_path, repo_root=tmp_path,
                runner=runner, binary=Path("/bin/true"))
        assert called["n"] == 0

    def test_foreign_bundle_before_execution_refused(self, bundle, tmp_path,
                                                     chain):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        from test_backend_bundle import make_bundle
        foreign = make_bundle(_with_hbm())
        tampered = replace(prepared, bundle=foreign)
        with pytest.raises((BackendMaterializationError,
                            BookSimLoweringError)):
            run_certified_booksim(
                tampered, run_dir=tmp_path, repo_root=tmp_path,
                runner=lambda *a: _FakeResult(stdout=_OK_STDOUT),
                binary=Path("/bin/true"))


# ── real backend smoke (skipped without a runnable binary) ──────────────

def _find_repo_binary():
    import os
    from veritx_dse.core.paths import REPO
    from veritx_dse.simulation.booksim import find_booksim_bin
    try:
        path = find_booksim_bin(REPO)
    except FileNotFoundError:
        return None
    if os.environ.get("BOOKSIM_BIN"):
        return path
    return path


@pytest.fixture(scope="module")
def real_binary():
    path = _find_repo_binary()
    if path is None:
        pytest.skip("no runnable BookSim binary")
    if not Path(path).is_file():
        pytest.skip(f"BookSim binary missing at {path}")
    return path


class TestRealBookSim:
    def test_real_run_proves_executed_routes_and_activity(
            self, bundle, real_binary, tmp_path):
        prepared = prepare_booksim_standalone(bundle, workload_trace=TRACE)
        ev = run_certified_booksim(
            prepared, run_dir=tmp_path,
            repo_root=Path("/home/datavex/veritx-audit"),
            timeout=120, binary=Path(real_binary))
        assert ev.exit_status == 0
        assert ev.route_equivalence == "EXACT"
        assert ev.route_pairs_compared == 16
        assert ev.route_expected_sha256 == ev.route_executed_sha256
        assert ev.stats.get("delivered", 0) == 2
        assert "latency" in ev.stats
        assert ev.backend_dir.endswith("backend")
        # The executed bytes match the manifest (re-hashed pre-spawn).
        verify_materialized(prepared.manifest, Path(ev.backend_dir))
