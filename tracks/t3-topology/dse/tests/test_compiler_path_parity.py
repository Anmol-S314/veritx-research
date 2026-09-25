"""Adversarial parity: the two compile orchestration paths must agree.

`SrotaControlPlane` (the canonical service) compiles through
`compiler.canonical.compile_deterministic_candidate` with a baseline
candidate plan, while `FabricCompiler` compiles through
`compiler.orchestration.build_resolved_bundle` (the reclaimed Wave-C path).
They are separate orchestration implementations that both claim to perform
the same sealed derivation. This test runs the same intent through both
and asserts every semantic child identity is equal. A single divergence is
an architectural defect (semantic drift), not a test problem.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from test_application_service import _intent  # noqa: E402

from veritx_dse.application.compile_intent import (  # noqa: E402
    derive_compile_request,
)
from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.application.store import ResourceStore  # noqa: E402
from veritx_dse.compiler.canonical import (  # noqa: E402
    compile_deterministic_candidate,
)
from veritx_dse.compiler.candidate_policy import (  # noqa: E402
    generate_baseline_candidate,
)
from veritx_dse.compiler.orchestration import build_resolved_bundle  # noqa: E402
from veritx_dse.model.vc_resource import (  # noqa: E402
    vc_resources_from_assignment,
)


def _compiled_identities(c) -> dict[str, str]:
    return {
        "topology": c.topology.topology_hash(),
        "mapping": c.mapping.mapping_hash(),
        "attachment": c.attachment.attachment_hash(),
        "route": c.routing.route.artifact_hash,
        "resolved_route": c.routing.resolved_route.resolved_route_hash(),
        "vc_assignment": c.routing.vc_assignment.vc_assignment_hash(),
        "vc_resource": c.vc_resource.artifact_hash,
        "packet_format": c.packet_format.packet_format_hash,
        "router_behavior": c.router_behavior.router_behavior_hash,
        "address_decode": c.address_decode.address_decode_hash,
        "fabric": c.fabric.fabric_hash,
        "resolved_fabric": c.resolved_fabric.resolved_fabric_hash,
    }


def _bundle_identities(b) -> dict[str, str]:
    return {
        "topology": b.topology.topology_hash(),
        "mapping": b.mapping.mapping_hash(),
        "attachment": b.attachment.attachment_hash(),
        "route": b.router_route.artifact_hash,
        "resolved_route": b.resolved_route.resolved_route_hash(),
        "vc_assignment": b.vc_assignment.vc_assignment_hash(),
        "vc_resource":
            vc_resources_from_assignment(b.vc_assignment).artifact_hash,
        "packet_format": b.packet_format.packet_format_hash,
        "router_behavior": b.router_behavior.router_behavior_hash,
        "address_decode": b.address_decode.address_decode_hash,
        "fabric": b.fabric.fabric_hash,
        "resolved_fabric": b.resolved_fabric.resolved_fabric_hash,
    }


def _diff(a: dict, b: dict) -> dict:
    return {k: (a.get(k), b.get(k)) for k in set(a) | set(b)
            if a.get(k) != b.get(k)}


@pytest.mark.parametrize("preset", ["mesh4", "mesh4_hbm", "mesh4_wide128"])
def test_service_and_orchestration_agree_on_every_child(preset, tmp_path):
    intent = _intent(preset)
    design = derive_compile_request(intent)
    plan = generate_baseline_candidate(design=design)

    via_service = SrotaControlPlane(
        store=ResourceStore(tmp_path / "store")).compile(intent).compiled
    via_canonical = compile_deterministic_candidate(
        design=design, inventory=plan.inventory, mapping=plan.mapping,
        routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
        settings=plan.compile_settings)
    via_orchestration = build_resolved_bundle(design)

    service_ids = _compiled_identities(via_service)
    canonical_ids = _compiled_identities(via_canonical)
    orchestration_ids = _bundle_identities(via_orchestration)

    assert service_ids == canonical_ids, _diff(service_ids, canonical_ids)
    assert canonical_ids == orchestration_ids, \
        _diff(canonical_ids, orchestration_ids)


def test_v3_orchestration_uses_the_single_baseline_settings():
    """C2.1: the v3 path must not carry its own copy of the baseline
    hardware literals (8/8/1); it must consume the one definition."""
    from veritx_dse.compiler import candidate_policy, orchestration
    assert orchestration._baseline_settings() \
        is candidate_policy.BASELINE_FABRIC_SETTINGS
    assert not hasattr(orchestration, "_MAX_PACKET_FLITS")
    assert not hasattr(orchestration, "_INPUT_BUFFER_DEPTH_FLITS")
    assert not hasattr(orchestration, "_OUTPUT_STAGE_DEPTH_FLITS")
