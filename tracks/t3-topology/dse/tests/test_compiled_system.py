"""Canonical system identity/admission without broadening legacy execution."""
from dataclasses import replace
import json

import pytest

from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.presets import _typed_request, build_typed_preset_request
from veritx_dse.core.errors import EvidenceInvalid, InvalidInput
from veritx_dse.model.compiled_system import CompiledSystemArtifact
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.model.domain_intent import ClockSource, ClockSourceKind, ClockDomain
from veritx_dse.model.sideband import SidebandInterface, SidebandKind, Direction
from veritx_dse.model.access_policy import AccessPolicyArtifact


def request():
    return _typed_request(MeshIntent(side_length=2), endpoints=4, tp=4, payload_bytes=512)


def compiled(req=None):
    c = FabricCompiler().compile(req if req is not None else request())
    assert c.status == "COMPILED", c.error
    return c


def test_compiler_owns_a_single_root_and_root_revalidates():
    c = compiled()
    root = c.compiled_system
    assert isinstance(root, CompiledSystemArtifact)
    assert root is c.compiled_system
    assert root.request is c.request and root.fabric is c.bundle
    root.revalidate()
    assert root.child_identities()["authored_design"] == c.request.design_hash()
    assert root.child_identities()["resolved_fabric_hash"] == c.bundle.resolved_fabric.resolved_fabric_hash
    assert root.child_identities()["routing_policy"] == root.routing_policy.artifact_id()
    assert root.child_identities()["dependency_proof"] == root.dependency_proof.artifact_id()


def test_system_root_manifest_roundtrips_against_resolved_children():
    root = compiled().compiled_system
    doc = json.loads(json.dumps(root.to_dict()))
    assert "resources" not in doc and "rules" not in doc
    assert CompiledSystemArtifact.from_dict(doc, parents=root) is root
    doc["children"]["resource_graph"] = "0" * 64
    with pytest.raises(EvidenceInvalid):
        CompiledSystemArtifact.from_dict(doc, parents=root)


@pytest.mark.parametrize("change", [dict(schema_version=True), dict(schema_version=99), dict(extra="unknown")])
def test_system_versioned_reader_is_closed(change):
    root = compiled().compiled_system
    with pytest.raises(InvalidInput):
        CompiledSystemArtifact.from_dict({**root.to_dict(), **change}, parents=root)


def test_v5_clock_access_sideband_changes_system_not_base_hardware_identity():
    base = request()
    neutral = CompileRequestV5(base_v4=base)
    roots = [compiled(neutral).compiled_system]
    sources = (ClockSource("pll", ClockSourceKind.PLL, 1_000_000_000),)
    for hz, divider in ((500_000_000, 2), (250_000_000, 4)):
        roots.append(compiled(replace(neutral, clock_sources=sources,
            clock_domains=(ClockDomain("core", "pll", hz, divider_num=divider),))).compiled_system)
    roots.append(compiled(replace(neutral, access_policy=AccessPolicyArtifact(()))).compiled_system)
    roots.append(compiled(replace(neutral, sideband_interfaces=(SidebandInterface(
        "irq", SidebandKind.INTERRUPT, Direction.OUTPUT, 1),))).compiled_system)
    assert len({r.system_hash() for r in roots}) == len(roots)
    assert len({r.fabric.resolved_fabric.resolved_fabric_hash for r in roots}) == 1
    assert roots[1].child_identities()["clock_domains"] == roots[1].clock_domains.content_hash
    assert roots[-1].sidebands is not None
    for root in roots:
        root.revalidate()


def test_root_resource_deletion_refuses_even_with_a_new_root_hash():
    root = compiled().compiled_system
    changed = replace(root, resource_graph=replace(root.resource_graph, resources=root.resource_graph.resources[:-1]))
    assert changed.system_hash() != root.system_hash()
    with pytest.raises(EvidenceInvalid):
        changed.revalidate()


def test_root_cached_graph_and_policy_mutation_refuse():
    root = compiled().compiled_system
    changed_graph = replace(root.dependency_proof.graph, edges=())
    for changes in (
        dict(dependency_proof=replace(root.dependency_proof, graph=changed_graph)),
        dict(routing_policy=replace(root.routing_policy, source_policy_id="other-source")),
        dict(allocation=replace(root.allocation, buffer_policy={"invented_buffer_depth": 1024})),
    ):
        with pytest.raises(EvidenceInvalid):
            replace(root, **changes).revalidate()


def test_undeclared_or_foreign_children_refuse():
    root = compiled().compiled_system
    with pytest.raises(EvidenceInvalid, match="undeclared"):
        replace(root, access_system=AccessPolicyArtifact(())).revalidate()
    with pytest.raises(EvidenceInvalid, match="authored design"):
        replace(root, request=replace(root.request, workload=replace(root.request.workload, model_name="foreign"))).revalidate()


@pytest.mark.parametrize("preset", ["gec_mecs16", "gec_hybrid16", "srota32_rank", "srota32_plane_c", "torus25"])
def test_pending_stateful_and_plane_migrations_keep_exact_legacy_artifacts(preset):
    c = compiled(build_typed_preset_request(preset))
    root = c.compiled_system
    root.revalidate()
    assert root.fabric is c.bundle and root.network_certificate is c.certificate
    if root.routing_policy is None:
        assert root.normalization_refusal
        assert root.to_dict()["scopes"]["routing"] == "LEGACY_ADAPTER_RETAINED"
    if c.control_plane is not None:
        assert root.control_plane is c.control_plane
        assert root.to_dict()["scopes"]["control_plane"] == "DECLARED_STRUCTURE_ONLY"
        with pytest.raises(EvidenceInvalid, match="control-plane"):
            replace(root, control_plane=None).revalidate()


def test_legacy_scientific_child_identities_are_unchanged():
    c = compiled()
    before = c.bundle.root_hashes()
    c.compiled_system.revalidate()
    assert c.bundle.root_hashes() == before
    assert {k: c.compiled_system.child_identities()[k] for k in before} == before


def test_compilation_and_artifact_chain_export_system_root():
    from veritx_dse.application.views import compilation_view, artifact_chain_view
    c = compiled()
    for view in (compilation_view(c), artifact_chain_view(c)):
        assert view["compiled_system"] == c.compiled_system.to_dict()
        assert view["system_hash"] == "sha256:" + c.compiled_system.system_hash()
    nodes = {node["artifact"]: node for node in artifact_chain_view(c)["nodes"]}
    assert nodes["compiled_system"]["hash"] == "sha256:" + c.compiled_system.system_hash()
    assert "resource_graph" in nodes["compiled_system"]["parents"]


def test_failed_compile_has_no_system_root():
    from veritx_dse.model.domain_intent import PowerDomain, PowerPolicy
    bad = CompileRequestV5(base_v4=request(), power_domains=(PowerDomain("p", PowerPolicy.ALWAYS_ON),))
    c = FabricCompiler().compile(bad)
    assert c.status == "UNSUPPORTED" and c.compiled_system is None
