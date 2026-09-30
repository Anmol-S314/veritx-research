"""Phase-3 BookSim truth hardening (closure Wave-3, booksim-truth lane).

Locks the invariant: no profile reports QUALIFIED without passing its
qualifier, and no unregistered profile executes. Covers MC registry
agreement, the execution handler gate, trace/profile domain agreement,
VC-domain soundness (disjointness predicate, routing consistency,
subset-overlap refusal), AnyNet VC exactness, and CDG shared-VC honesty.
"""
from __future__ import annotations

import dataclasses
import json
from types import SimpleNamespace

import pytest

from test_backend_booksim_projection import (  # noqa: E402
    _parents,
)
from test_channel_vc_cdg import (  # noqa: E402
    _real_fabric, _vc,
)

from veritx_dse.application import (  # noqa: E402
    booksim_qualification_registry as registry,
)
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)
from veritx_dse.backend import booksim_execution as bx  # noqa: E402
from veritx_dse.backend.booksim_execution import (  # noqa: E402
    BookSimExecutionError,
)
from veritx_dse.backend.booksim_projection import (  # noqa: E402
    MESH_DOR_MC_PROFILE, prepare_booksim_input,
    qualify_anynet_min_hops, select_booksim_profile,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.core.route_artifact import DOR_XY  # noqa: E402
from veritx_dse.model.vc_resource import (  # noqa: E402
    VCResourceArtifact, VCResourceError, require_disjoint_traffic_classes,
)
from veritx_dse.core.errors import MappingInvalid  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.verification.channel_vc_cdg import (  # noqa: E402
    certify_channel_vc_deadlock,
)
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    assert_traffic_classes_bound, lower_compile_workload,
)

MOE = REPO / "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json"

def _moe_compiled():
    request = parse_request_doc(json.loads(MOE.read_text(encoding="utf-8")))
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.status
    return request, compilation

@pytest.fixture(scope="module")
def moe():
    return _moe_compiled()

def _moe_parents(moe):
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionParents,
    )
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    from veritx_dse.workload.intent_lowering import build_multi_class_messages
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV3
    request, compilation = moe
    bundle = compilation.bundle
    logical = build_multi_class_messages(lower_compile_workload(request))
    physical = PhysicalTrafficArtifactV3(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    return BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=physical)

def _binary(tmp_path):
    path = tmp_path / "booksim"
    path.write_bytes(b"#!/bin/sh\nexit 0\n" + b"x" * 64)
    path.chmod(0o755)
    return path

def _runner(stdout, stderr=""):
    def run(command, cwd, timeout):
        return bx.ProcessOutcome(returncode=0, stdout=stdout,
                                 stderr=stderr, timed_out=False)
    return run

def test_mc_stages_agree(moe):
    """PROJECTABLE / EXECUTABLE / QUALIFIED agree for multi-class mesh.

    The MC profile selects, prepares, resolves an execution handler,
    and passes its qualifier over the real canonical parents — closing
    the hole where truth said NO while execution proceeded anyway.
    """
    parents = _moe_parents(moe)
    profile = select_booksim_profile(parents)
    assert profile.profile_id == MESH_DOR_MC_PROFILE.profile_id
    prepared = prepare_booksim_input(parents)
    assert prepared.profile_id == MESH_DOR_MC_PROFILE.profile_id
    handler, err = registry.resolve_execution_handler(profile.profile_id)
    assert handler is not None, err
    qualified, authority = registry.evaluate_qualification(profile, parents)
    assert qualified, authority

def test_unlisted_profile_is_not_qualified_by_construction(moe, monkeypatch):
    """Dropping the MC record makes the same parents NOT_QUALIFIED.

    Proves validate/evaluate detects an unlisted profile: qualification
    by omission is impossible, even though the qualifier would pass.
    """
    parents = _moe_parents(moe)
    profile = select_booksim_profile(parents)
    trimmed = {k: v for k, v in registry.QUALIFICATION.items()
               if k != profile.profile_id}
    monkeypatch.setattr(registry, "QUALIFICATION", trimmed)
    qualified, authority = registry.evaluate_qualification(profile, parents)
    assert not qualified
    assert "no qualification record" in authority

def test_execute_refuses_unregistered_profile(tmp_path):
    """execute_prepared_booksim is gated on the execution handler."""
    _, parents = _parents()
    prepared = prepare_booksim_input(parents)
    forged = dataclasses.replace(prepared, profile_id="BOGUS-PROFILE-V9")
    with pytest.raises(BookSimExecutionError, match="unregistered"):
        bx.execute_prepared_booksim(
            prepared=forged, binary=_binary(tmp_path),
            run_dir=tmp_path / "run", timeout=10,
            runner=_runner("irrelevant"))

def test_mc_trace_on_single_profile_refuses(tmp_path):
    """An injected multi-class trace on a single-class profile fails."""
    _, parents = _parents()
    prepared = prepare_booksim_input(parents)
    forged_trace = "0 0 0 1 4\n1 1 1 0 4\n"
    forged = dataclasses.replace(prepared, trace_text=forged_trace)
    with pytest.raises(BookSimExecutionError,
                       match="single-class profile.*refusing a multi-class"):
        bx.execute_prepared_booksim(
            prepared=forged, binary=_binary(tmp_path),
            run_dir=tmp_path / "run", timeout=10,
            runner=_runner("irrelevant"))

def test_out_of_range_class_on_mc_profile_refuses(tmp_path, moe):
    """A trace index outside the bound MC class map fails."""
    parents = _moe_parents(moe)
    prepared = prepare_booksim_input(parents)
    forged = dataclasses.replace(prepared, trace_text="0 0 99 1 4\n")
    with pytest.raises(BookSimExecutionError, match="exceed the bound"):
        bx.execute_prepared_booksim(
            prepared=forged, binary=_binary(tmp_path),
            run_dir=tmp_path / "run", timeout=10,
            runner=_runner("irrelevant"))

def test_valid_single_class_passes_domain(tmp_path):
    """A genuine single-class prepared input still executes (injected)."""
    _, parents = _parents()
    prepared = prepare_booksim_input(parents)
    count = prepared.expected_packets
    stdout = (
        f"Loaded text trace: {count} packets from workload.trace\n"
        "Packet latency average = 12.5\n"
        "Flit latency average = 4.5\n"
        "Time taken is 900 cycles\n"
        "Completion time is 777 cycles\n")
    stderr = f"[trace] All 800 cycles, injected={count} — draining\n"
    record = bx.execute_prepared_booksim(
        prepared=prepared, binary=_binary(tmp_path),
        run_dir=tmp_path / "run", timeout=10,
        runner=_runner(stdout, stderr))
    assert record.evidence.prepared_id == prepared.prepared_id()

def test_disjoint_sets_pass():
    require_disjoint_traffic_classes((("A", (0,)), ("B", (1,))))

def test_shared_vc_refuses_with_names():
    with pytest.raises(VCResourceError, match="VC 1 shared by"):
        require_disjoint_traffic_classes((("A", (0, 1)), ("B", (1, 2))))

def test_assert_admits_full_envelope_overlap(moe):
    """The shipped MoE design shares one VC across classes: sound, admitted.

    Full-envelope overlap executes exactly what the fork runs (one VC
    envelope); per-class replay keeps the classes distinct.
    """
    request, compilation = moe
    lowered = lower_compile_workload(request)
    assert_traffic_classes_bound(
        lowered, compilation.bundle.vc_assignment)

def _stub_assignment(**over):
    base = dict(
        traffic_class_to_vcs=(
            ("ep_dispatch", (0,)), ("tp_collective", (0,))),
        vc_to_routing_class=((0, "DOR_XY"),),
        allowed_transitions=((0, 0),),
        vc_ids=(0,))
    base.update(over)
    return SimpleNamespace(**base)

def test_assert_refuses_vc_without_routing_class(moe):
    """A VC no routing table covers is unprovable — refused, not KeyError."""
    request, _compilation = moe
    lowered = lower_compile_workload(request)
    assignment = _stub_assignment(vc_to_routing_class=())
    with pytest.raises(MappingInvalid, match="no routing class"):
        assert_traffic_classes_bound(lowered, assignment)

def test_assert_refuses_subset_overlap(moe):
    """Overlap on a subset the backend never executes is refused."""
    request, _compilation = moe
    lowered = lower_compile_workload(request)
    assignment = _stub_assignment(
        vc_to_routing_class=((0, "DOR_XY"), (1, "DOR_XY")),
        allowed_transitions=((0, 0), (1, 1)),
        vc_ids=(0, 1))
    with pytest.raises(MappingInvalid, match="full VC envelope"):
        assert_traffic_classes_bound(lowered, assignment)

def test_assert_refuses_transition_without_routing_class(moe):
    request, _compilation = moe
    lowered = lower_compile_workload(request)
    assignment = _stub_assignment(allowed_transitions=((0, 1),))
    with pytest.raises(MappingInvalid, match="allowed VC transitions"):
        assert_traffic_classes_bound(lowered, assignment)

def _anynet_parents(vc_spec):
    """AnyNet parents mirroring test_backend_booksim_projection._parents."""
    from test_canonical_compiler import (  # noqa: E402
        _anynet_policy, _det, _design,
    )
    from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402
    from veritx_dse.workload.graph import (  # noqa: E402
        KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
        collective_detail, compute_detail,
    )
    from veritx_dse.workload.messages import (  # noqa: E402
        LogicalMessageArtifactV2,
    )
    from veritx_dse.workload.traffic import (  # noqa: E402
        PhysicalTrafficArtifactV2,
    )
    import veritx_dse.backend.booksim_projection as _bp  # noqa: E402
    compute, tp = 16, 16
    design = _design(compute=compute, tp=tp,
                     family=TopologyFamily.MESH)
    compiled = _det(design, policy=_anynet_policy(), vc_spec=vc_spec)
    operations = [
        OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                      detail=compute_detail(
                          duration_ns=10000,
                          participant_count=compute)),
        OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                      deps=("pre",),
                      detail=collective_detail(
                          collective_kind="ALLREDUCE",
                          participants=tuple(range(compute)),
                          payload_bytes=1024,
                          participant_count=compute)),
    ]
    graph = WorkloadGraph(parallelism=compiled.inventory.parallelism,
                          participant_count=compute,
                          operations=tuple(operations))
    logical = LogicalMessageArtifactV2(graph=graph)
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        inventory=compiled.inventory, packet_format=compiled.packet_format)
    return _bp.BookSimProjectionParents(
        resolved_fabric=compiled.resolved_fabric,
        topology=compiled.topology, attachment=compiled.attachment,
        mapping=compiled.mapping, vc_resource=compiled.vc_resource,
        vc_assignment=compiled.routing.vc_assignment,
        packet_format=compiled.packet_format,
        route=compiled.routing.route, physical_traffic=traffic)

def test_anynet_subset_vc_refuses():
    """AnyNet cannot execute class-to-VC subsets: named refusal."""
    from test_canonical_compiler import _vs  # noqa: E402
    from veritx_dse.core.route_artifact import (  # noqa: E402
        ANYNET_MIN_HOPS,
    )
    spec = _vs(vc_count=2, traffic_class_to_vcs=(("default", (0,)),),
               vc_to_routing_class=((0, ANYNET_MIN_HOPS),
                                    (1, ANYNET_MIN_HOPS)),
               allowed_transitions=((0, 0), (1, 1)))
    parents = _anynet_parents(spec)
    from veritx_dse.backend.booksim_projection import SemanticLoss
    with pytest.raises(SemanticLoss, match="VC envelope"):
        qualify_anynet_min_hops(parents)

def test_anynet_non_identity_transitions_refuse():
    """AnyNet renders no cross-VC routing: non-identity transitions refuse."""
    from test_canonical_compiler import _vs  # noqa: E402
    from veritx_dse.core.route_artifact import (  # noqa: E402
        ANYNET_MIN_HOPS,
    )
    spec = _vs(vc_count=2,
               traffic_class_to_vcs=(("default", (0, 1)),),
               vc_to_routing_class=((0, ANYNET_MIN_HOPS),
                                    (1, ANYNET_MIN_HOPS)),
               allowed_transitions=((0, 1), (1, 1)))
    parents = _anynet_parents(spec)
    from veritx_dse.backend.booksim_projection import SemanticLoss
    with pytest.raises(SemanticLoss, match="identity VC"):
        qualify_anynet_min_hops(parents)

def test_cdg_shared_vc_same_routing_passes():
    """Two classes sharing one VC under one routing class: PASS, correctly.

    The shared VC is one wait resource; the acyclicity verdict covers it.
    Sharing is not waved through — it is analyzed exactly.
    """
    topo, rr, rra = _real_fabric(4, (DOR_XY,))
    vc = _vc(rra, vc_count=1,
             traffic_class_to_vcs={"A": [0], "B": [0]})
    cert = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert cert.verdict == "PASS"

def test_cdg_transition_without_routing_class_is_typed():
    """The KeyError path is unreachable for real inputs — and typed anyway."""
    topo, rr, rra = _real_fabric(4, (DOR_XY,))
    vc = _vc(rra, vc_count=1, allowed_transitions=[(0, 0)])
    ordinarily = certify_channel_vc_deadlock(
        topology=topo, resolved_route=rra, router_route=rr, vc_assignment=vc)
    assert ordinarily.verdict == "PASS"
    from veritx_dse.model.vc_assignment import VCAssignmentError
    with pytest.raises(VCAssignmentError, match="routing"):
        _vc(rra, vc_count=2,
            vc_to_routing_class={0: DOR_XY},
            allowed_transitions=[(0, 1)])
