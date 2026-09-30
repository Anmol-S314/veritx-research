"""MIN_ADAPT_MESH projection: selection-gated, escape-proven, honestly blocked.

Covers the adaptive projection bridge: the canonical
AdaptiveBackendSelection is the ONLY authority that reaches the fork's
min_adapt_mesh function (routing_function stays LOCKED — no user knob),
escape VC0 + adaptive 1..N with >= 2 VCs, fidelity
ADAPTIVE_RUNTIME_SELECTION, and first_hop_table_comparable=False honored
(no dump rendered, no deterministic-table claim).

HONEST BOUNDARY (pinned, not worked around): the vendored fork executes
every traffic class over ONE VC envelope (route-set vc_start..vc_end,
injection from VC 0 — vc_exactness), while the escape subfunction needs
a per-VC escape/adaptive partition. No compiler derivation yields a
multi-VC full-envelope design (per-class VCs are singletons), so no
compiled design reaches live adaptive execution today. The missing
bridge is routing-level class/role binding in the fork + its canonical
representation — named by the blocked-execution test, never faked.

The fork DOES register min_adapt_mesh (routefunc.cpp); UGAL/Valiant/
Chaos/planar/ROMM/GEC-adaptive and the broken limited_adapt_mesh never
reach this projection (refused upstream).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.preset_certification import (  # noqa: E402
    _load_preset_doc,
)

def _example(name: str) -> dict:
    """A shape EXAMPLE fixture, read directly; real presets fall back to the
    catalog. The product catalog now carries real models only, so synthetic
    shapes are loaded from their example documents."""
    import json as _json
    from veritx_dse.core.paths import REPO
    path = (REPO / "tracks/t3-topology/examples"
            / f"{name.replace('-', '_')}-v3.json")
    if path.is_file():
        return _json.loads(path.read_text(encoding="utf-8"))
    from veritx_dse.application.preset_certification import _load_preset_doc
    return _load_preset_doc(name)
from veritx_dse.backend import booksim_projection as bp  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.model.vc_resource import (  # noqa: E402
    VCResourceArtifact, vc_resources_from_assignment,
)

def test_min_adapt_profile_is_registered_with_its_own_audit():
    assert bp.MIN_ADAPT_MESH_PROFILE.profile_id == \
        "CERTIFIED_BOOKSIM_MIN_ADAPT_MESH_V1"
    names = bp.MIN_ADAPT_MESH_PROFILE.known_names()
    assert "routing_dump_file" not in names
    assert "routing_function" in names and "num_vcs" in names

def test_select_booksim_profile_stays_deterministic_only():
    import inspect
    src = inspect.getsource(bp.select_booksim_profile)
    assert "MIN_ADAPT" not in src and "min_adapt" not in src

def test_backend_only_algorithms_stay_refused():
    from veritx_dse.model.routing_relation_materialize import (
        REFUSED_BACKEND_ONLY_ALGORITHMS, refuse_backend_only_algorithm,
    )
    assert "limited_adapt_mesh" in REFUSED_BACKEND_ONLY_ALGORITHMS
    with pytest.raises(Exception):
        refuse_backend_only_algorithm("limited_adapt_mesh")
    with pytest.raises(Exception):
        refuse_backend_only_algorithm("ugal_flatfly")

def test_fork_registers_min_adapt_mesh():
    """The vendored fork implements the function; only the binding layer
    is missing (evidence the block is the bridge, not the backend)."""
    src = (REPO / "third_party" / "booksim2" / "src" / "routefunc.cpp"
           ).read_text(encoding="utf-8")
    assert 'gRoutingFunctionMap["min_adapt_mesh"]' in src

def _esc():
    from veritx_dse.model.routing_realization import AdaptiveBackendSelection
    import hashlib
    digest = hashlib.sha256(b"min-adapt-test").hexdigest()
    return AdaptiveBackendSelection(
        routing_function="min_adapt_mesh", policy_hash=digest,
        realization_hash=digest, escape_vcs=(0,), adaptive_vcs=(1,),
        num_vcs=2)

def test_escape_check_accepts_exact_extension():
    sel = _esc()
    bp._check_escape_transitions(((0, 0), (1, 1)), ((0, 0), (1, 0), (1, 1)),
                                 sel)
    with pytest.raises(bp.SemanticLoss):
        bp._check_escape_transitions(
            ((0, 0), (1, 1), (1, 0)), ((0, 0), (1, 1)), sel)

def test_escape_check_refuses_narrowing_and_widening():
    sel = _esc()
    with pytest.raises(bp.SemanticLoss, match="lacks required"):
        bp._check_escape_transitions(
            ((0, 0), (1, 1)), ((0, 0), (0, 1), (1, 1)), sel)
    with pytest.raises(bp.SemanticLoss, match="non-escape"):
        bp._check_escape_transitions(
            ((0, 0), (1, 1)), ((0, 0), (1, 0), (1, 1), (0, 1)), sel)

def test_escape_check_requires_selection_type():
    req = CompileRequestV3.from_dict(_example("dense-1b-16tiles"))
    compilation = FabricCompiler().compile(req)
    assert compilation.status == "COMPILED"
    from veritx_dse.workload.intent_lowering import lower_compile_workload
    _ = lower_compile_workload(req)
    bundle = compilation.bundle
    parents = bp.BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric, topology=bundle.topology,
        attachment=bundle.attachment, mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format, route=bundle.router_route,
        physical_traffic=_v2_physical(req, compilation))
    with pytest.raises(bp.SemanticLoss):
        bp.qualify_min_adapt_mesh(parents, object(), object(), object())

def _v2_physical(req, compilation):
    from veritx_dse.workload.intent_lowering import (
        build_single_class_messages, lower_compile_workload,
    )
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2
    bundle = compilation.bundle
    lowered = lower_compile_workload(req)
    logical = build_single_class_messages(lowered)
    physical = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    physical.validate_conservation()
    return physical

def test_single_vc_design_cannot_host_the_escape_partition():
    from veritx_dse.model.routing_relation_materialize import (
        materialize_routing_relation, min_adapt_mesh_policy,
    )
    from veritx_dse.model.routing_resource_binding import (
        RoutingResourceBindingArtifact,
    )
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    doc = _example("dense-1b-16tiles")
    req = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(req)
    assert compilation.status == "COMPILED"
    bundle = compilation.bundle
    vcr = vc_resources_from_assignment(bundle.vc_assignment)
    assert vcr.vc_count == 1
    policy = min_adapt_mesh_policy()
    relation = materialize_routing_relation(bundle.topology, policy)
    binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash,
        vc_resource_hash=vcr.artifact_hash,
        role_to_vcs=(("escape", (0,)), ("adaptive", (1,))))
    with pytest.raises(Exception, match="not in the VC.*universe"):
        binding.validate_against(policy, vcr)

def test_observation_scope_guard_fires_for_adaptive():
    from veritx_dse.backend.route_observation import (
        refuse_deterministic_claim_for_adaptive,
    )
    with pytest.raises(Exception):
        refuse_deterministic_claim_for_adaptive("per_hop_min_adaptive")

def test_live_adaptive_execution_blocked_on_routing_level_binding():
    """BLOCKED, pinned: no compiler derivation yields a multi-VC
    full-envelope design (per-class VCs are singletons; vc_exactness
    refuses subsets), so the escape partition has no executable host.

    Missing bridge (exact): routing-level class/role binding in the fork
    (iq_router route-set allocation consulting packet class/role) + its
    canonical representation + EXECUTION_HANDLERS / class-domain /
    qualification-record registration for
    CERTIFIED_BOOKSIM_MIN_ADAPT_MESH_V1. This test MUST fail loudly if
    that bridge lands without updating it (the assertion below encodes
    the current backend law)."""
    from veritx_dse.model.compile_model import CompileRequest
    tried = []
    for preset in ("dense-1b-16tiles", "mesh4"):
        doc = _example(preset)
        req = (CompileRequestV3.from_dict(doc)
               if doc.get("schema_version") == 3
               else CompileRequest.from_dict(doc))
        compilation = FabricCompiler().compile(req)
        if compilation.status != "COMPILED":
            continue
        vcr = vc_resources_from_assignment(compilation.bundle.vc_assignment)
        exact, _reason = bp.vc_exactness(vcr)
        tried.append((preset, vcr.vc_count, exact))
    assert tried, "no preset compiled — the premise is gone"
    assert not any(count >= 2 and exact for _, count, exact in tried), (
        f"a multi-VC full-envelope design now exists {tried}: the "
        "routing-level binding bridge may have landed — wire the live "
        "adaptive execution and rewrite this test")
