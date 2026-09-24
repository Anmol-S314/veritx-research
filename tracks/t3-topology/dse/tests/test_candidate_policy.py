"""Baseline candidate-generation policy tests.

The policy proposes one explicit candidate per design; these tests pin its
vocabulary, victim-selection rule, domain refusals, determinism, and the
Slice-23 integration gate.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json

import pytest

from veritx_dse.compiler import candidate_policy as cp
from veritx_dse.compiler.canonical import (
    CanonicalCompileError, CompileStage, DeterministicVCSpec,
    FabricCompileSettings, compile_deterministic_candidate,
)
from veritx_dse.compiler.candidate_policy import (
    CandidatePlan, CandidatePolicy, CandidatePolicyError, MappingPolicy,
    generate_baseline_candidate,
)
from veritx_dse.model import router_behavior as rb
from veritx_dse.model.compile_model import (
    AddressMap, Agent, AgentKind, CompileRequest, CollectiveKind,
    CollectiveOp, DepKind, Dependency, DependencyGraph, ModelFamily, NocConfig,
    TopologyFamily, Workload,
)
from veritx_dse.model.mapping import derive_mapping
from veritx_dse.model.placement import NodeInventory, build_inventory
from veritx_dse.model.routing_policy import RoutingPolicyDefinition

# Sealed Slice-10 canonical DOR_XY execution profile.
GOLDEN_DOR_POLICY_HASH = (
    "c451979bf68ac87535cf117adc1b9ff98cb45ea6a50ff42d22f7e312f68a2426")
# Slice-23 integration: baseline mesh4-equivalent candidate compiled end to
# end (NOT the Slice-22 golden — see test_golden_fixture_is_outside_domain).
# Identity-only move under compiler semantics v2 (design_hash parent moved);
# the FABRIC golden below must NOT move.
GOLDEN_BASELINE_RESOLVED = (
    "c05d4c19bf3bdd955da97f33fd665d2325441966906b1bb23290d0dcc3296fa1")
GOLDEN_BASELINE_FABRIC = (
    "d7fde891d47c7a6ffb1e0746429a784f95bd20a0014324b8757fdc2841716094")
GOLDEN_BASELINE_VC_ASSIGNMENT = (
    "447c57d5793fc951c919abe2c554618e699c11a18a475ba245a73524b481ed28")
GOLDEN_TWO_BY_TWO_TOPOLOGY = (
    "27327bba5e1339e383a74f78fb38e8ab0e07da9aaa43bc999efb044959d0fdac")

_BLOCKING = DepKind.BLOCKING


# ── fixtures (canonical equivalents of the historical product shapes) ──────

def _design(deps, *, family: TopologyFamily = TopologyFamily.MESH,
            link_width=None, tp: int = 1, compute: int = 4,
            address_map: AddressMap | None = None, agents=None,
            collectives=(), workload_collectives=()) -> CompileRequest:
    if agents is None:
        agents = (Agent(kind=AgentKind.COMPUTE_TILE, count=compute,
                        protocol="AXI", data_width=256, addr_width=64),)
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=tp, pp=1, ep=1,
                          dp=1, collectives=tuple(collectives)),
        requirements=[],
        agents=tuple(agents),
        dependencies=DependencyGraph(tuple(deps)),
        noc_config=NocConfig(topology_family=family, link_width=link_width),
        address_map=address_map or AddressMap())


ONE_CYCLE = (Dependency("A", "B", _BLOCKING),
             Dependency("B", "A", _BLOCKING))
ACYCLIC = (Dependency("A", "B", _BLOCKING),)
MULTI_CYCLE = (Dependency("A", "B", _BLOCKING), Dependency("B", "A", _BLOCKING),
               Dependency("C", "D", _BLOCKING), Dependency("D", "C", _BLOCKING))
# Two blocking cycles sharing node A; every member's blocking out-degree is
# 2, so BOTH cycles resolve to victim A (unique-victim reuse).
SHARED_VICTIM = (Dependency("A", "B", _BLOCKING),
                 Dependency("B", "A", _BLOCKING),
                 Dependency("A", "C", _BLOCKING),
                 Dependency("C", "A", _BLOCKING),
                 Dependency("B", "D", _BLOCKING),
                 Dependency("C", "E", _BLOCKING))
ORDERING_ONLY = (Dependency("A", "B", DepKind.ORDERING),
                 Dependency("B", "A", DepKind.ORDERING))


def _mesh4_design() -> CompileRequest:
    """Canonical equivalent of the historical mesh4 product fixture."""
    return _design(ONE_CYCLE)


def _plan(deps=None, **kw) -> CandidatePlan:
    design = _design(deps if deps is not None else ONE_CYCLE, **kw)
    return generate_baseline_candidate(design=design)


def _compile(plan: CandidatePlan, design: CompileRequest):
    return compile_deterministic_candidate(
        design=design, inventory=plan.inventory, mapping=plan.mapping,
        routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
        settings=plan.compile_settings)


# ── vocabulary / shape ─────────────────────────────────────────────────────

def test_policy_vocabulary_is_exactly_pinned():
    # V1 was superseded before durable application persistence: its
    # dependency-cycle witnesses were not cross-process deterministic.
    assert [(p.name, p.value) for p in CandidatePolicy] == [
        ("BASELINE_DETERMINISTIC_V2", "baseline_deterministic_v2")]
    assert [(m.name, m.value) for m in MappingPolicy] == [
        ("RANK_ORDER_V1", "rank_order_v1")]


def test_candidate_plan_fields_are_exactly_pinned():
    names = {f.name for f in dataclasses.fields(CandidatePlan)}
    assert names == {"policy", "mapping_policy", "inventory", "mapping",
                     "routing_policy", "vc_spec", "compile_settings"}
    plan = _plan()
    assert plan.policy is CandidatePolicy.BASELINE_DETERMINISTIC_V2
    assert plan.mapping_policy is MappingPolicy.RANK_ORDER_V1
    assert isinstance(plan.inventory, NodeInventory)
    for field in ("hash", "fabric", "resolved", "certificate", "backend"):
        assert not hasattr(plan, field)


def test_mapping_policy_is_proposal_provenance_only():
    plan = _plan()
    # carried by the plan, never as Fabric/ResolvedFabric identity
    assert plan.mapping_policy is MappingPolicy.RANK_ORDER_V1
    compiled = _compile(plan, _mesh4_design())
    blob = json.dumps(compiled.fabric.to_dict(), sort_keys=True)
    assert "rank_order" not in blob
    assert not hasattr(compiled.fabric, "mapping_policy")
    assert not hasattr(compiled.resolved_fabric, "mapping_policy")


def test_plan_and_specs_are_frozen():
    plan = _plan()
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.policy = CandidatePolicy.BASELINE_DETERMINISTIC_V2
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.mapping_policy = MappingPolicy.RANK_ORDER_V1
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.vc_spec.derivation = "tampered"
    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.compile_settings.max_packet_flits = 16


# ── mesh4-equivalent baseline result ───────────────────────────────────────

def test_mesh4_fixture_pins_the_whole_candidate():
    plan = _plan()
    # mapping: RANK_ORDER_V1 via the sealed canonical baseline
    assert plan.mapping.to_dict() == derive_mapping(
        _mesh4_design()).to_dict()
    assert plan.inventory == build_inventory(_mesh4_design())
    # routing: canonical Slice-10 DOR_XY profile
    assert plan.routing_policy.policy_hash == GOLDEN_DOR_POLICY_HASH
    assert plan.routing_policy.algorithm == "dimension_order"
    # VC candidate: one blocking cycle -> victim A (tie broken lexically),
    # one separated VC, every other class on VC0
    spec = plan.vc_spec
    assert spec.vc_count == 2
    assert dict(spec.traffic_class_to_vcs) == {"A": (1,), "B": (0,)}
    assert spec.vc_to_routing_class == ((0, "DOR_XY"), (1, "DOR_XY"))
    assert spec.allowed_transitions == ((0, 0), (1, 1))
    assert spec.escape_vcs == ()
    assert "baseline_deterministic_v2" in spec.derivation
    assert "proposed_vc_count=2" in spec.derivation
    assert "victims=['A']" in spec.derivation
    # settings: historical canonical baseline
    assert plan.compile_settings == FabricCompileSettings(
        max_packet_flits=8, input_buffer_depth_flits_per_vc=8,
        output_stage_depth_flits_per_vc=1)


def test_inventory_is_the_canonical_rank_order_geometry():
    plan = _plan()
    assert plan.inventory.rank_count == 1
    assert len(plan.inventory.compute_instances) == 4
    assert plan.mapping.rank_count == 1


# ── acyclic fixture ────────────────────────────────────────────────────────

def test_acyclic_graph_proposes_one_vc():
    plan = _plan(ACYCLIC)
    spec = plan.vc_spec
    assert spec.vc_count == 1
    assert dict(spec.traffic_class_to_vcs) == {"A": (0,), "B": (0,)}
    assert spec.vc_to_routing_class == ((0, "DOR_XY"),)
    assert spec.allowed_transitions == ((0, 0),)
    assert spec.escape_vcs == ()


def test_ordering_dependencies_create_no_separation():
    plan = _plan(ORDERING_ONLY)
    assert plan.vc_spec.vc_count == 1
    assert dict(plan.vc_spec.traffic_class_to_vcs) == {"A": (0,), "B": (0,)}


# ── multiple-cycle fixture ─────────────────────────────────────────────────

def test_two_disjoint_cycles_pin_victims_and_numbering():
    plan = _plan(MULTI_CYCLE)
    spec = plan.vc_spec
    assert spec.vc_count == 3
    assert dict(spec.traffic_class_to_vcs) == {
        "A": (1,), "B": (0,), "C": (2,), "D": (0,)}
    assert spec.vc_to_routing_class == ((0, "DOR_XY"), (1, "DOR_XY"),
                                        (2, "DOR_XY"))
    assert "victims=['A', 'C']" in spec.derivation


def test_dependency_declaration_order_does_not_change_candidate_semantics():
    forward = _plan(MULTI_CYCLE)
    reverse = _plan(tuple(reversed(MULTI_CYCLE)))
    assert forward.vc_spec == reverse.vc_spec
    assert forward.mapping == reverse.mapping
    assert forward.routing_policy == reverse.routing_policy
    assert forward.compile_settings == reverse.compile_settings


def test_duplicate_cycle_victims_reuse_one_separated_vc():
    plan = _plan(SHARED_VICTIM)
    spec = plan.vc_spec
    # authoritative formula is 1 + len(UNIQUE victims), not 1 + len(cycles)
    assert spec.vc_count == 2
    assert dict(spec.traffic_class_to_vcs) == {
        "A": (1,), "B": (0,), "C": (0,), "D": (0,), "E": (0,)}
    reverse = _plan(tuple(reversed(SHARED_VICTIM)))
    assert reverse.vc_spec == spec


# ── collectives ────────────────────────────────────────────────────────────

def test_multi_rank_collective_is_refused():
    design = _design(ONE_CYCLE, collectives=(
        CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=8),))
    with pytest.raises(CandidatePolicyError) as excinfo:
        generate_baseline_candidate(design=design)
    assert excinfo.value.reason == "UNSUPPORTED_POLICY_DOMAIN"
    assert "collective-context VC separation" in excinfo.value.detail


def test_single_rank_collective_does_not_alter_candidate():
    plain = _plan()
    with_one = _plan(collectives=(
        CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=1),))
    assert with_one.vc_spec == plain.vc_spec
    assert with_one.mapping == plain.mapping


# ── domain refusals ────────────────────────────────────────────────────────

def test_design_without_traffic_classes_is_refused():
    with pytest.raises(CandidatePolicyError) as excinfo:
        generate_baseline_candidate(design=_design(()))
    assert excinfo.value.reason == "UNSUPPORTED_POLICY_DOMAIN"
    assert "traffic class" in excinfo.value.detail
    assert "default" in excinfo.value.detail


def test_non_compile_request_is_refused():
    with pytest.raises(CandidatePolicyError) as excinfo:
        generate_baseline_candidate(design=object())
    assert excinfo.value.reason == "INPUT"


def test_unsupported_compiler_semantics_version_is_refused():
    design = _mesh4_design()
    # legacy semantics v1: canonical candidate generation requires CURRENT
    # semantics (migrate_design first); here the version field is forged
    # directly so no valid v1 request object needs to exist for this gate.
    object.__setattr__(design, "compiler_semantics_version", 1)
    with pytest.raises(CandidatePolicyError) as excinfo:
        generate_baseline_candidate(design=design)
    assert excinfo.value.reason == "INPUT"


def test_mapping_overflow_is_wrapped_and_chained():
    design = _design(ONE_CYCLE, tp=4, compute=1)
    with pytest.raises(CandidatePolicyError) as excinfo:
        generate_baseline_candidate(design=design)
    assert excinfo.value.reason == "MAPPING"
    assert excinfo.value.__cause__ is not None
    assert "MAPPING" in str(excinfo.value)


# ── compile settings confirmation ──────────────────────────────────────────

def test_settings_match_sealed_slice17_slice18_baseline():
    assert rb.DEFAULT_INPUT_BUFFER_DEPTH_FLITS == 8
    assert rb.DEFAULT_OUTPUT_STAGE_DEPTH_FLITS == 1
    plan = _plan()
    assert plan.compile_settings.input_buffer_depth_flits_per_vc \
        == rb.DEFAULT_INPUT_BUFFER_DEPTH_FLITS
    assert plan.compile_settings.output_stage_depth_flits_per_vc \
        == rb.DEFAULT_OUTPUT_STAGE_DEPTH_FLITS
    assert plan.compile_settings.max_packet_flits == 8


# ── Slice-23 integration gate ──────────────────────────────────────────────

def test_baseline_plan_compiles_to_resolved_fabric():
    design = _mesh4_design()
    plan = generate_baseline_candidate(design=design)
    compiled = _compile(plan, design)
    assert compiled.resolved_fabric.resolved_fabric_hash \
        == GOLDEN_BASELINE_RESOLVED
    assert compiled.fabric.fabric_hash == GOLDEN_BASELINE_FABRIC
    assert compiled.routing.vc_assignment.vc_assignment_hash() \
        == GOLDEN_BASELINE_VC_ASSIGNMENT
    assert compiled.topology.topology_hash() == GOLDEN_TWO_BY_TWO_TOPOLOGY


def test_slice22_golden_fixture_is_outside_baseline_domain():
    """The Slice-22/23 golden used dependencies=[] and a hand-authored
    'default' class; baseline v1 refuses empty dependency graphs rather
    than invent that class, so 0fba2ac3... is unreachable by this policy."""
    design = _design(
        (),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=3),
                Agent(kind=AgentKind.HBM_CONTROLLER, count=1)),
        address_map=AddressMap(ranges=()))
    with pytest.raises(CandidatePolicyError) as excinfo:
        generate_baseline_candidate(design=design)
    assert excinfo.value.reason == "UNSUPPORTED_POLICY_DOMAIN"


def test_torus_gets_no_fallback_routing():
    design = _design(ONE_CYCLE, family=TopologyFamily.TORUS)
    plan = generate_baseline_candidate(design=design)
    # candidate generation still says DOR_XY; it does not invent torus routing
    assert plan.routing_policy.policy_hash == GOLDEN_DOR_POLICY_HASH
    with pytest.raises(CanonicalCompileError) as excinfo:
        _compile(plan, design)
    assert excinfo.value.stage is CompileStage.ROUTING


# ── determinism ────────────────────────────────────────────────────────────

def _plan_snapshot(plan: CandidatePlan) -> tuple:
    return (plan.inventory.to_dict(), plan.mapping.to_dict(),
            plan.routing_policy.to_dict(), plan.vc_spec,
            plan.compile_settings, plan.policy, plan.mapping_policy)


@pytest.mark.parametrize("deps", [ONE_CYCLE, ACYCLIC, MULTI_CYCLE,
                                  SHARED_VICTIM])
def test_fifty_repeated_generations_are_identical(deps):
    first = _plan_snapshot(_plan(deps))
    for _ in range(49):
        assert _plan_snapshot(_plan(deps)) == first


# ── source-of-truth sentinels ──────────────────────────────────────────────

def _docstring_stripped_source(module) -> str:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) \
                and node.body \
                and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ranges.append((node.body[0].lineno, node.body[0].end_lineno))
    return "".join(
        line for number, line in enumerate(source.splitlines(keepends=True),
                                           start=1)
        if not any(low <= number <= high for low, high in ranges))


def test_production_contains_no_legacy_or_clamp_logic():
    source = _docstring_stripped_source(cp)
    for token in ("derive_route", "derive_vc_count", "derive_vc_assignment",
                  "collective_vc_floor", "PLANE_C_MAX_VC", "os.environ",
                  "env_int", "clamp", "VERITX_MAX_VC", "min_adapt"):
        assert token not in source, token
    # no compilation calls in production
    tree = ast.parse(inspect.getsource(cp))
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func,
                                                           ast.Name)}
    assert "compile_deterministic_candidate" not in called
    assert "compile_adaptive_candidate" not in called


def test_production_imports_are_exactly_allowed():
    tree = ast.parse(inspect.getsource(cp))
    local: set[str] = set()
    imported_names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if (node.module or "").startswith("veritx_dse"):
                local.add(node.module)
                imported_names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("veritx_dse"), alias.name
    assert local == {
        "veritx_dse.compiler.canonical",
        "veritx_dse.core.errors",
        "veritx_dse.model.compile_model",
        "veritx_dse.model.mapping",
        "veritx_dse.model.placement",
        "veritx_dse.model.routing_policy",
    }
    # only the Slice-23 VALUE OBJECTS, never the compile functions
    canonical_names = {alias.name for node in ast.walk(tree)
                       if isinstance(node, ast.ImportFrom)
                       and node.module == "veritx_dse.compiler.canonical"
                       for alias in node.names}
    assert canonical_names == {"DeterministicVCSpec", "FabricCompileSettings"}
    forbidden = ("fabric_artifact", "resolved_fabric", "verification",
                 "backend", "simulation", "application", "cli",
                 "reports", "synthesis")
    for module in local:
        assert not any(token in module for token in forbidden), module
    # exact historical module (never substring-matched against
    # the canonical veritx_dse.model.routing_policy)
    assert "veritx_dse.model.routing" not in local
    assert "build_inventory" in imported_names
    assert "derive_mapping" in imported_names


def test_canonical_compiler_never_imports_candidate_policy():
    from veritx_dse.compiler import canonical
    source = inspect.getsource(canonical)
    assert "candidate_policy" not in source


def test_new_files_have_no_cross_worktree_dependency():
    # tokens built by concatenation so this test file does not match itself
    tokens = ("/home/datavex/" + "bruh", "p4" + "/studio",
              "origin/" + "p4")
    for path in (cp.__file__, __file__):
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for token in tokens:
            assert token not in source, (path, token)
