"""tests/test_p1b_fabric_evaluator.py — P1B A2–A7: FabricEvaluator.

Covers the precondition refusals (typed, no backend work), the
traffic-class admission gate (never silent VC0), the DOR_XY/ANYNET
projection seam (unprojectable -> UNSUPPORTED), BACKEND_UNAVAILABLE
with no binary, cycles-only UNSUPPORTED with no clock, the full
EVALUATED path (stubbed execution over a genuinely certified bundle),
failure mappings, and EvaluationView schema conformance.

The EVALUATED vehicle is a 2-node ANYNET_MIN_HOPS bundle: it is the
shape that is BOTH genuinely certificate-PASS (verify_compiled_fabric)
AND genuinely lowerable (lower_booksim_standalone) under the sealed
authorities. Compiled DOR_XY meshes honestly stop at UNSUPPORTED —
documented in test_mesh_projection_unsupported and the P1B report.
Execution is stubbed at the run_qualified_booksim seam (no BookSim
binary in most envs); the stub returns a CertifiedBookSimEvidence the
evaluator authenticates through the real evidence round-trip. A real
binary-gated end-to-end (test_real_booksim_end_to_end) runs wherever
the binary builds.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_fabric_artifact import build_chain  # noqa: E402

from veritx_dse.application.errors import ControlPlaneError  # noqa: E402
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    Compilation, FabricCompiler,
)
from veritx_dse.application.fabric_evaluator import (  # noqa: E402
    BACKEND_UNAVAILABLE, EVALUATED, FAILED, UNSUPPORTED,
    EvaluationOptions, EvaluationOutcome, FabricEvaluator,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.workload.canonical_graph import (  # noqa: E402
    KIND_COLLECTIVE, OperationNode, WorkloadGraph, WorkloadSemantics,
    collective_detail,
)

EVAL = FabricEvaluator()


# ── builders ────────────────────────────────────────────────────────────

def _mesh_request_chain(small=True):
    if small:
        return build_chain(tp=2, pp=1, ep=1, dp=2, n_agents=4,
                           family=TopologyFamily.MESH)
    return build_chain(tp=8, pp=1, ep=1, dp=1, n_agents=64,
                       family=TopologyFamily.MESH)


def _compiled_mesh(small=True):
    chain = _mesh_request_chain(small)
    return chain, FabricCompiler().compile(chain.cr)


def _anynet_bundle_2node():
    """Genuinely certifiable AND lowerable (see module docstring)."""
    from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS
    from veritx_dse.model.fabric_artifact import make_fabric_artifact
    from veritx_dse.model.packet_format import derive_packet_format
    from veritx_dse.model.resolved_bundle import make_resolved_fabric_bundle
    from veritx_dse.model.resolved_fabric import make_resolved_fabric
    from veritx_dse.model.router_behavior import derive_router_behavior
    from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
    chain = build_chain(tp=2, pp=1, ep=1, dp=1, n_agents=2,
                        family=TopologyFamily.MESH)
    vc = make_vc_assignment_artifact(
        resolved_route=chain.rra, vc_count=2,
        traffic_class_to_vcs={"A": [0, 1]},
        vc_to_routing_class={0: ANYNET_MIN_HOPS, 1: ANYNET_MIN_HOPS},
        derivation="p1b-test")
    pf = derive_packet_format(topology=chain.topo, attachment=chain.att,
                              vc_assignment=vc)
    rb = derive_router_behavior(vc_assignment=vc)
    fabric = make_fabric_artifact(
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=vc, packet_format=pf,
        router_behavior=rb, address_decode=chain.ad)
    rf = make_resolved_fabric(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=vc, packet_format=pf,
        router_behavior=rb, address_decode=chain.ad, fabric=fabric)
    bundle = make_resolved_fabric_bundle(
        design=chain.cr, inventory=chain.inv, mapping=chain.mapping,
        topology=chain.topo, attachment=chain.att, router_route=chain.rr,
        resolved_route=chain.rra, vc_assignment=vc, packet_format=pf,
        router_behavior=rb, address_decode=chain.ad, fabric=fabric,
        resolved_fabric=rf)
    return chain, bundle


def _compilation_for(chain, bundle):
    from veritx_dse.verification.certificate import verify_compiled_fabric
    cert = verify_compiled_fabric(bundle)
    assert cert.overall == "PASS"
    return Compilation(status="COMPILED", request=chain.cr, bundle=bundle,
                       certificate=cert, error=None)


def _workload(participant_count, design_hash, *, payload=1024,
              kind="ALLREDUCE"):
    pa = None
    if participant_count == 4:
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
    elif participant_count == 2:
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=1)
    elif participant_count == 8:
        pa = ParallelismArtifact(tp=8, pp=1, ep=1, dp=1)
    else:
        raise AssertionError("test helper covers 2/4/8 participants")
    op = OperationNode(
        "c0", KIND_COLLECTIVE, (),
        collective_detail(collective_kind=kind,
                          participants=tuple(range(participant_count)),
                          payload_bytes=payload,
                          participant_count=participant_count))
    return WorkloadGraph(parallelism=pa,
                         participant_count=participant_count,
                         operations=(op,), semantics=WorkloadSemantics(),
                         provenance={"design_hash": design_hash})


def _fake_binary(tmp_path):
    """A hermetic availability fixture: availability resolves (hashes)
    this file, while execution stays stubbed (the file never spawns)."""
    import hashlib
    data = b"p1b-fake-booksim-producer-v1"
    path = Path(tmp_path) / "fake-booksim"
    path.write_bytes(data)
    return str(path), hashlib.sha256(data).hexdigest()


def _stub_qualified_booksim(monkeypatch, *, completion=41,
                            delivered_override=None, raise_exc=None,
                            producer_sha="ab" * 32):
    """Stub execution at the run_qualified_booksim seam.

    Returns evidence consistent with the prepared inputs (config/input
    hashes, expected route table, quiescence counters) so the
    evaluator's authentication, quiescence and binding checks run for
    real; only the BookSim spawn itself is stubbed.
    """
    import hashlib

    from veritx_dse.backend.booksim import (
        CertifiedBookSimEvidence, expected_route_table,
    )
    from veritx_dse.core.spec import canonical_json
    import veritx_dse.backend.projection as projection

    def _fake(prepared, *, run_dir, repo_root, timeout, binary):
        if raise_exc is not None:
            raise raise_exc
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
                 "drain_verdict": "stub",
                 "latency": 12.5}
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

    monkeypatch.setattr(projection, "run_qualified_booksim", _fake)


def _view_schema():
    import json
    # DSE = <repo>/tracks/t3-topology/dse -> repo root is 3 levels up.
    path = (DSE.parent.parent.parent / "contracts" / "srota" / "v1" /
            "evaluation.view.schema.json")
    return json.loads(path.read_text())


def _assert_view_valid(outcome: EvaluationOutcome):
    import jsonschema
    jsonschema.validate(outcome.to_view_dict(), _view_schema())


# ── preconditions: typed refusal, no backend work ───────────────────────

class TestPreconditions:
    def test_invalid_compilation_raises(self):
        chain = _mesh_request_chain()
        bad = Compilation(status="INVALID", request=chain.cr, bundle=None,
                          certificate=None, error="boom")
        with pytest.raises(ControlPlaneError) as ei:
            EVAL.evaluate(bad, _workload(4, chain.cr.design_hash()))
        assert ei.value.code.value == "INVALID_INTENT"

    def test_unsupported_compilation_raises(self):
        chain = _mesh_request_chain()
        bad = Compilation(status="UNSUPPORTED", request=chain.cr,
                          bundle=None, certificate=None, error="torus")
        with pytest.raises(ControlPlaneError) as ei:
            EVAL.evaluate(bad, _workload(4, chain.cr.design_hash()))
        assert ei.value.code.value == "UNSUPPORTED_SEMANTICS"

    def test_failed_certificate_raises(self):
        import dataclasses
        chain, comp = _compiled_mesh()
        assert comp.status == "COMPILED"
        tampered = dataclasses.replace(
            comp.bundle,
            router_behavior=__import__(
                "veritx_dse.model.router_behavior",
                fromlist=["derive_router_behavior"]
            ).derive_router_behavior(
                vc_assignment=comp.bundle.vc_assignment,
                buffer_depth_flits=16))
        from veritx_dse.verification.certificate import (
            verify_compiled_fabric,
        )
        cert = verify_compiled_fabric(tampered)
        assert cert.overall == "FAIL"
        bad = Compilation(status="COMPILED", request=chain.cr,
                          bundle=comp.bundle, certificate=cert, error=None)
        with pytest.raises(ControlPlaneError) as ei:
            EVAL.evaluate(bad, _workload(4, chain.cr.design_hash()))
        assert ei.value.code.value == "EVIDENCE_INVALID"

    @pytest.mark.parametrize("bad", ["nope", 42])
    def test_wrong_types_raise(self, bad):
        chain, comp = _compiled_mesh()
        with pytest.raises(ControlPlaneError):
            EVAL.evaluate(bad, _workload(4, chain.cr.design_hash()))
        with pytest.raises(ControlPlaneError):
            EVAL.evaluate(comp, bad)
        with pytest.raises(ControlPlaneError):
            EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()), options=bad)

    def test_options_none_means_defaults(self):
        # options=None is the documented default (not a type error).
        # Defaults use traffic_class="DEFAULT", which the compiled VC
        # authority does not declare — the admission gate fires first.
        chain, comp = _compiled_mesh()
        out = EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()), options=None)
        assert out.status == UNSUPPORTED
        assert "VC0" in (out.reason or "")

    def test_bad_timeout_raises(self):
        chain, comp = _compiled_mesh()
        with pytest.raises(ControlPlaneError):
            EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()),
                          EvaluationOptions(timeout_s=0))


# ── admission gate ──────────────────────────────────────────────────────

class TestAdmissionGate:
    def test_unknown_traffic_class_is_typed_refusal(self):
        chain, comp = _compiled_mesh()
        assert comp.status == "COMPILED"
        out = EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="NOPE"))
        assert out.status == UNSUPPORTED
        assert "NOPE" in (out.reason or "")
        assert "VC0" in (out.reason or "")
        # Lowering still succeeded and is bound (traffic conserved).
        assert out.message_artifact_id
        assert out.physical_traffic_id
        assert out.performance_result_id is None
        assert out.metrics is None
        _assert_view_valid(out)

    def test_known_class_selects_meshdor_path(self, monkeypatch):
        # Class "A" is declared by the compiled VC authority, so the
        # admission gate passes and the evaluator selects the native
        # mesh-DOR path (no binary here -> BACKEND_UNAVAILABLE with the
        # mesh profile bound, never a projection refusal).
        import veritx_dse.simulation.booksim as sim_booksim
        monkeypatch.setattr(
            sim_booksim, "find_booksim_bin",
            lambda repo_root: (_ for _ in ()).throw(
                FileNotFoundError("no booksim here")))
        from veritx_dse.backend.meshdor_profile import (
            MESH_DOR_PROFILE_ID,
        )
        chain, comp = _compiled_mesh()
        out = EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="A"))
        assert out.status == BACKEND_UNAVAILABLE
        assert out.backend_profile == MESH_DOR_PROFILE_ID
        assert out.backend_config_hash
        assert out.realization_digest
        _assert_view_valid(out)


# ── profile selection ───────────────────────────────────────────────

class TestProfileSelection:
    def test_concentrated_mesh_matches_no_path(self):
        from veritx_dse.model.compile_model import TopologyFamily
        from test_fabric_artifact import build_chain as _bc
        chain = _bc(tp=2, pp=1, ep=1, dp=2, n_agents=4,
                    family=TopologyFamily.CONCENTRATED_MESH)
        comp = FabricCompiler().compile(chain.cr)
        assert comp.status == "COMPILED"
        out = EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="A"))
        assert out.status == UNSUPPORTED
        assert "no certified BookSim path" in (out.reason or "")
        assert out.backend_profile is None
        _assert_view_valid(out)

    def test_anynet_bundle_selects_anynet_path(self, monkeypatch):
        import veritx_dse.simulation.booksim as sim_booksim
        monkeypatch.setattr(
            sim_booksim, "find_booksim_bin",
            lambda repo_root: (_ for _ in ()).throw(
                FileNotFoundError("no booksim here")))
        from veritx_dse.backend.booksim import (
            BOOKSIM_STANDALONE_PROFILE,
        )
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(comp, _workload(2, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="A"))
        assert out.status == BACKEND_UNAVAILABLE
        assert out.backend_profile == BOOKSIM_STANDALONE_PROFILE
        _assert_view_valid(out)

    def test_mesh_dense_64_selects_meshdor_path(self, monkeypatch):
        # Canonical scenario: 64-router compiled mesh, certificate PASS,
        # traffic conserved, VC admission PASS, mesh-DOR path selected
        # (no binary here -> BACKEND_UNAVAILABLE with mesh bindings).
        import veritx_dse.simulation.booksim as sim_booksim
        monkeypatch.setattr(
            sim_booksim, "find_booksim_bin",
            lambda repo_root: (_ for _ in ()).throw(
                FileNotFoundError("no booksim here")))
        from veritx_dse.backend.meshdor_profile import (
            MESH_DOR_PROFILE_ID,
        )
        chain, comp = _compiled_mesh(small=False)
        assert comp.status == "COMPILED"
        assert comp.certificate.overall == "PASS"
        out = EVAL.evaluate(comp, _workload(8, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="A"))
        assert out.status == BACKEND_UNAVAILABLE
        assert out.backend_profile == MESH_DOR_PROFILE_ID
        assert out.message_artifact_id
        assert out.physical_traffic_id
        assert out.backend_config_hash
        _assert_view_valid(out)

    def test_unknown_backend_unsupported(self):
        chain, comp = _compiled_mesh()
        out = EVAL.evaluate(comp, _workload(4, chain.cr.design_hash()),
                            EvaluationOptions(backend="NOPE"))
        assert out.status == UNSUPPORTED
        assert "NOPE" in (out.reason or "")


# ── availability ────────────────────────────────────────────────────────

class TestAvailability:
    def test_no_producer_is_backend_unavailable(self, monkeypatch):
        import veritx_dse.simulation.booksim as sim_booksim
        monkeypatch.setattr(
            sim_booksim, "find_booksim_bin",
            lambda repo_root: (_ for _ in ()).throw(
                FileNotFoundError("no booksim here")))
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(comp, _workload(2, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="A"))
        assert out.status == BACKEND_UNAVAILABLE
        assert "producer" in (out.reason or "").lower()
        assert out.backend_config_hash
        assert out.backend_input_hash
        assert out.performance_result_id is None
        assert out.metrics is None
        _assert_view_valid(out)

    def test_unreadable_binary_is_backend_unavailable(self, tmp_path):
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(
            comp, _workload(2, chain.cr.design_hash()),
            EvaluationOptions(traffic_class="A",
                              binary=str(tmp_path / "missing-booksim")))
        assert out.status == BACKEND_UNAVAILABLE
        _assert_view_valid(out)


# ── cycles-only honesty ─────────────────────────────────────────────────

class TestCyclesOnly:
    def test_no_clock_is_unsupported_with_cycles(self, monkeypatch,
                                                 tmp_path):
        fake_bin, fake_sha = _fake_binary(tmp_path)
        _stub_qualified_booksim(monkeypatch, producer_sha=fake_sha)
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(comp, _workload(2, chain.cr.design_hash()),
                            EvaluationOptions(traffic_class="A",
                                              binary=fake_bin,
                                              run_dir=str(tmp_path)))
        assert out.status == UNSUPPORTED
        assert "network clock" in (out.reason or "")
        window = out.network_traffic_window
        assert window["window_cycles"] == 41
        assert window["wall_time_ns"] is None
        assert window["cycles_only"] is True
        # The evidence is still authenticated and bound.
        assert out.raw_evidence_digest
        assert out.stats_digest
        assert out.evidence_id
        assert out.performance_result_id is None
        assert out.metrics and out.metrics["completion_time"] == 41
        _assert_view_valid(out)


# ── evaluated path (stubbed execution, certified bundle) ────────────────

class TestEvaluated:
    def test_evaluated_binds_verified_performance(self, monkeypatch,
                                                  tmp_path):
        fake_bin, fake_sha = _fake_binary(tmp_path)
        _stub_qualified_booksim(monkeypatch, completion=41,
                                producer_sha=fake_sha)
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(
            comp, _workload(2, chain.cr.design_hash()),
            EvaluationOptions(traffic_class="A", network_clock_hz=10 ** 9,
                              binary=fake_bin, run_dir=str(tmp_path)))
        assert out.status == EVALUATED, out.reason
        assert out.message_artifact_id
        assert out.physical_traffic_id
        assert out.producer_identity == fake_sha
        assert out.raw_evidence_digest and out.stats_digest
        assert out.evidence_id
        assert out.performance_result_id
        window = out.network_traffic_window
        assert window == {"window_cycles": 41, "wall_time_ns": 41.0,
                          "cycles_only": False}
        assert out.metrics["completion_time"] == 41
        assert out.metrics["delivered"] == out.metrics["pkt_count"]
        assert "latency" in out.metrics
        assert "unstable" not in (out.metrics or {})
        assert out.fidelity_warning and "UNCALIBRATED" in out.fidelity_warning
        assert out.reason is None
        # The result reverifies against its parents (independent check).
        from veritx_dse.performance.model import (
            ClockDef, PerformanceModel, ResourceDef,
        )
        from veritx_dse.performance.result import reverify_result
        from veritx_dse.performance.workload import (
            EVENT_NETWORK_TRAFFIC_WINDOW, TemporalEvent, TemporalWorkload,
        )
        from veritx_dse.core.time import QTime
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
        assert out.performance_result["makespan"] == \
            QTime(41, 10 ** 9).to_dict()
        _assert_view_valid(out)

    def test_evaluated_view_requires_its_bindings(self, monkeypatch,
                                                  tmp_path):
        fake_bin, fake_sha = _fake_binary(tmp_path)
        _stub_qualified_booksim(monkeypatch, producer_sha=fake_sha)
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(
            comp, _workload(2, chain.cr.design_hash()),
            EvaluationOptions(traffic_class="A", network_clock_hz=10 ** 9,
                              binary=fake_bin, run_dir=str(tmp_path)))
        view = out.to_view_dict()
        for key in ("message_artifact_id", "physical_traffic_id",
                    "backend_producer", "evidence", "performance_result_id",
                    "network_traffic_window"):
            assert view[key], key
        assert view["backend_producer"]["producer_identity"] == fake_sha
        assert view["evidence"]["raw_evidence_digest"] == \
            out.raw_evidence_digest


# ── failure mappings ────────────────────────────────────────────────────

class TestFailures:
    def test_quiescence_breach_is_failed(self, monkeypatch, tmp_path):
        fake_bin, fake_sha = _fake_binary(tmp_path)
        _stub_qualified_booksim(monkeypatch, delivered_override=1,
                                producer_sha=fake_sha)
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(
            comp, _workload(2, chain.cr.design_hash()),
            EvaluationOptions(traffic_class="A", network_clock_hz=10 ** 9,
                              binary=fake_bin, run_dir=str(tmp_path)))
        assert out.status == FAILED
        assert "delivered" in (out.reason or "")
        assert out.performance_result_id is None
        _assert_view_valid(out)

    def test_execution_exception_is_failed(self, monkeypatch, tmp_path):
        from veritx_dse.core.errors import BookSimError
        fake_bin, _ = _fake_binary(tmp_path)
        _stub_qualified_booksim(
            monkeypatch, raise_exc=BookSimError("simulator crashed"))
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(
            comp, _workload(2, chain.cr.design_hash()),
            EvaluationOptions(traffic_class="A", network_clock_hz=10 ** 9,
                              binary=fake_bin, run_dir=str(tmp_path)))
        assert out.status == FAILED
        assert "crashed" in (out.reason or "")
        _assert_view_valid(out)

    def test_unprojectable_workload_is_unsupported(self):
        from veritx_dse.workload.canonical_graph import (
            KIND_P2P, p2p_detail,
        )
        chain, comp = _compiled_mesh()
        pa = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
        op = OperationNode("s", KIND_P2P, (),
                           p2p_detail(role="SEND", src_rank=0, dst_rank=1,
                                      payload_bytes=64, participant_count=4))
        graph = WorkloadGraph(parallelism=pa, participant_count=4,
                              operations=(op,),
                              semantics=WorkloadSemantics(),
                              provenance={
                                  "design_hash": comp.request.design_hash()})
        out = EVAL.evaluate(comp, graph,
                            EvaluationOptions(traffic_class="A"))
        assert out.status == UNSUPPORTED
        assert "complete transfer" in (out.reason or "")


# ── real binary (provisioned env only) ──────────────────────────────────

def _find_binary():
    from veritx_dse.core.paths import REPO
    from veritx_dse.simulation.booksim import find_booksim_bin
    return find_booksim_bin(REPO)


class TestRealBookSim:
    def test_real_booksim_end_to_end(self, tmp_path):
        try:
            binary = _find_binary()
        except FileNotFoundError:
            pytest.skip("no BookSim binary in this env")
        chain, bundle = _anynet_bundle_2node()
        comp = _compilation_for(chain, bundle)
        out = EVAL.evaluate(
            comp, _workload(2, chain.cr.design_hash()),
            EvaluationOptions(traffic_class="A", network_clock_hz=10 ** 9,
                              run_dir=str(tmp_path), binary=str(binary),
                              timeout_s=120))
        assert out.status == EVALUATED, out.reason
        assert out.performance_result_id
        _assert_view_valid(out)
