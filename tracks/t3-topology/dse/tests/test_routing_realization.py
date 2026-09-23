"""RoutingRealizationArtifact v1 tests — executable routing identity.

The realization normalizes either the deterministic route chain or the
adaptive relation chain into one hardware-execution identity, retaining
source artifact hashes as non-identity provenance.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import itertools

import pytest

from veritx_dse.core.route_artifact import (
    ANYNET_MIN_HOPS, DOR_XY, RouteArtifact,
)
from veritx_dse.model import routing_realization as rr
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.routing_policy import (
    CandidateMode, DeadlockProofObligation, DecisionScope, PathMode,
    RandomnessMode, RoutingPolicyDefinition, RoutingResourceRole,
    RoutingResourceRoleKind, RoutingStateKind, RoutingStateRequirement,
    RuntimeObservation, SelectionLocus,
)
from veritx_dse.model.routing_realization import (
    RoutingRealizationArtifact, RoutingRealizationError,
    RoutingRealizationKind, adaptive_routing_semantics_hash,
    adaptive_vc_routing_semantics_hash, deterministic_vc_routing_semantics_hash,
    make_adaptive_routing_realization, make_deterministic_routing_realization,
    policy_execution_semantics_dict, relation_execution_semantics_dict,
    routing_policy_execution_semantics_hash,
    routing_relation_execution_semantics_hash,
)
from veritx_dse.model.routing_relation import (
    RoutingAction, RoutingActionKind, RoutingContext, RoutingDecision,
    RoutingStateBinding, RoutingStateDomain, build_routing_relation,
)
from veritx_dse.model.routing_relation_materialize import (
    materialize_routing_relation,
)
from veritx_dse.model.routing_resource_binding import (
    RoutingResourceBindingArtifact,
)
from veritx_dse.model.topology_artifact import (
    MaterializedFamily, materialize_family,
)
from veritx_dse.model.vc_assignment import make_vc_assignment_artifact
from veritx_dse.model.vc_resource import (
    VCResourceArtifact, vc_resources_from_assignment,
)

GOLDEN_DET_DOR_2X2 = (
    "a0e458c54bcd6eda3c02356ea8411e26c1d1ae1aede164ea95ff4bdbc340eb07")
GOLDEN_DET_ANYNET_2X2 = (
    "bb38d475132a9459ba0fb12fdadecae54995e5aa2abcc784a5411b3d352568aa")
GOLDEN_ADAPTIVE_2X2 = (
    "f760e7584c3d48b56a5d3b415a5e6e51c8b0352aadd0238b145e806471488de5")
GOLDEN_ADAPTIVE_3X3 = (
    "6f4f89b208f6ec7801bbca7ce20d265da8274ad37b444be767b30cf019f6ee58")
GOLDEN_MIN_ADAPT_POLICY_EXEC = (
    "5552469caef55e4f253c59ad8aad16415f732e704024ea9bbdfba78195f3df58")
GOLDEN_MIN_ADAPT_VC_ROUTING = (
    "c2f4d4afb0c4f15a4b2d575f87a479342091b84b25bc448131c931b7528da891")

_MIN_ADAPT_TRANSITIONS = (
    (0, 0), (1, 0), (1, 1), (1, 2), (1, 3),
    (2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (3, 1), (3, 2), (3, 3),
)

SCHEMA_FIELDS = {
    "kind", "topology_hash", "vc_resource_hash", "routing_semantics_hash",
    "vc_routing_semantics_hash", "source_hashes", "schema_version",
    "routing_realization_hash",
}
IDENTITY_KEYS = {
    "type", "schema_version", "kind", "topology_hash", "vc_resource_hash",
    "routing_semantics_hash", "vc_routing_semantics_hash",
}
SERIALIZED_KEYS = SCHEMA_FIELDS | {"type"}
DETERMINISTIC_SOURCES = (
    "resolved_route_hash", "route_hash", "vc_assignment_hash")
ADAPTIVE_SOURCES = (
    "policy_hash", "relation_hash", "routing_resource_binding_hash")


# ── fixtures ───────────────────────────────────────────────────────────────

def _min_adapt_policy(**over) -> RoutingPolicyDefinition:
    kw = dict(
        id="min_adapt_like", algorithm="per_hop_min_adaptive",
        algorithm_version=1, path_mode=PathMode.MINIMAL,
        decision_scope=DecisionScope.PER_HOP,
        candidate_mode=CandidateMode.CANDIDATE_SET,
        selection_locus=SelectionLocus.ROUTER_ALLOCATOR,
        randomness=RandomnessMode.NONE,
        deadlock_proof_obligation=DeadlockProofObligation.ESCAPE_SUBFUNCTION,
        runtime_observations=(RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,),
        resource_roles=(
            RoutingResourceRole(id="adaptive",
                                kind=RoutingResourceRoleKind.ADAPTIVE),
            RoutingResourceRole(id="escape",
                                kind=RoutingResourceRoleKind.ESCAPE)),
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape")))
    kw.update(over)
    return RoutingPolicyDefinition(**kw)


def _min_adapt_vc(transitions=_MIN_ADAPT_TRANSITIONS,
                  count: int = 4) -> VCResourceArtifact:
    return VCResourceArtifact(
        vc_count=count, vc_ids=tuple(range(count)),
        traffic_class_to_vcs=(("default", tuple(range(count))),),
        allowed_transitions=transitions)


def _canonical_binding(vc=None, policy=None):
    vc = vc if vc is not None else _min_adapt_vc()
    policy = policy if policy is not None else _min_adapt_policy()
    return RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash, vc_resource_hash=vc.artifact_hash,
        role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))


def _mesh(n: int):
    return materialize_family(MaterializedFamily.MESH, endpoint_count=n)


def _adaptive(topo, policy=None, vc=None, binding=None,
              relation=None) -> RoutingRealizationArtifact:
    policy = policy if policy is not None else _min_adapt_policy()
    vc = vc if vc is not None else _min_adapt_vc()
    binding = binding if binding is not None else _canonical_binding(vc, policy)
    relation = (relation if relation is not None
                else materialize_routing_relation(topo, policy))
    return make_adaptive_routing_realization(
        topology=topo, policy=policy, relation=relation, vc_resource=vc,
        binding=binding)


def _deterministic(classes, *, vc_to_routing_class=None, escape=(),
                   vc_count: int = 1, topo=None):
    topo = topo if topo is not None else _mesh(4)
    design = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=[], noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inventory = build_inventory(design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topo)
    route = RouteArtifact.from_topology(topo, name="r", routing_classes=classes)
    resolved = derive_resolved_route(topo, attachment, route)
    mapping = (vc_to_routing_class if vc_to_routing_class is not None
               else {i: classes[0] for i in range(vc_count)})
    assignment = make_vc_assignment_artifact(
        resolved_route=resolved, derivation="d", vc_count=vc_count,
        traffic_class_to_vcs={"default": list(range(vc_count))},
        vc_to_routing_class=mapping,
        allowed_transitions=tuple((i, i) for i in range(vc_count)),
        escape_vcs=escape)
    vc_resource = vc_resources_from_assignment(assignment)
    realization = make_deterministic_routing_realization(
        topology=topo, attachment=attachment, route=route,
        resolved_route=resolved, vc_assignment=assignment,
        vc_resource=vc_resource)
    return attachment, route, resolved, assignment, vc_resource, realization


def _total_relation(policy, topology, state_domains=()):
    """Build a fully total, valid legal-action relation for any policy."""
    roles = sorted(role.id for role in policy.resource_roles)
    router_ids = sorted(router.router_id for router in topology.routers)
    by_src: dict[int, list] = {}
    for channel in topology.channels:
        by_src.setdefault(channel.src_router, []).append(channel)
    transitions = set(policy.allowed_role_transitions)
    domains = {domain.name: domain.values for domain in state_domains}
    names = sorted(domains)
    combos = (list(itertools.product(*(domains[n] for n in names)))
              if names else [()])
    decisions = []
    for router_id in router_ids:
        for destination in router_ids:
            for role in [None] + roles:
                for combo in combos:
                    state = tuple(RoutingStateBinding(n, v)
                                  for n, v in zip(names, combo))
                    if router_id == destination:
                        actions = (RoutingAction(
                            kind=RoutingActionKind.EJECT, channel_id=None,
                            next_role_id=None, next_state=(), priority=0),)
                    else:
                        actions = []
                        for channel in by_src.get(router_id, []):
                            for next_role in roles:
                                if role is None \
                                        or (role, next_role) in transitions:
                                    actions.append(RoutingAction(
                                        kind=RoutingActionKind.FORWARD,
                                        channel_id=channel.channel_id,
                                        next_role_id=next_role,
                                        next_state=state, priority=0))
                        actions = tuple(dict.fromkeys(actions))
                    decisions.append(RoutingDecision(
                        context=RoutingContext(router_id, destination, role,
                                               state),
                        actions=actions))
    return build_routing_relation(policy, topology, decisions,
                                  state_domains=state_domains)


def _rebind(relation, policy):
    return dataclasses.replace(relation, policy_hash=policy.policy_hash,
                               relation_hash="")


def _rebind_binding(binding, policy):
    return dataclasses.replace(binding, policy_hash=policy.policy_hash,
                               binding_hash="")


# ── vocabulary and source-hash authority ───────────────────────────────────

def test_kind_vocabulary_is_exactly_pinned():
    assert [(m.name, m.value) for m in RoutingRealizationKind] == [
        ("DETERMINISTIC", "deterministic"), ("ADAPTIVE", "adaptive")]


def test_source_hash_sets_are_exactly_pinned():
    assert rr._SOURCE_NAMES_BY_KIND[RoutingRealizationKind.DETERMINISTIC] \
        == DETERMINISTIC_SOURCES
    assert rr._SOURCE_NAMES_BY_KIND[RoutingRealizationKind.ADAPTIVE] \
        == ADAPTIVE_SOURCES


def test_source_hashes_are_excluded_from_identity():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    assert "source_hashes" not in realization.identity_dict()
    twin = dataclasses.replace(realization, source_hashes=(
        ("resolved_route_hash", "a" * 64),
        ("route_hash", "sha256:" + "b" * 64),
        ("vc_assignment_hash", "c" * 64)))
    assert twin.routing_realization_hash == realization.routing_realization_hash


# ── golden pins ────────────────────────────────────────────────────────────

def test_golden_deterministic_dor_2x2():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    assert realization.kind is RoutingRealizationKind.DETERMINISTIC
    assert realization.routing_realization_hash == GOLDEN_DET_DOR_2X2


def test_golden_deterministic_anynet_2x2():
    _att, _r, _rr, _va, _vc, realization = _deterministic((ANYNET_MIN_HOPS,))
    assert realization.routing_realization_hash == GOLDEN_DET_ANYNET_2X2


def test_golden_adaptive_2x2():
    realization = _adaptive(_mesh(4))
    assert realization.kind is RoutingRealizationKind.ADAPTIVE
    assert realization.routing_realization_hash == GOLDEN_ADAPTIVE_2X2


def test_golden_adaptive_3x3():
    realization = _adaptive(_mesh(9))
    assert realization.routing_realization_hash == GOLDEN_ADAPTIVE_3X3


def test_golden_min_adapt_policy_execution_semantics():
    policy = _min_adapt_policy()
    assert routing_policy_execution_semantics_hash(policy) \
        == GOLDEN_MIN_ADAPT_POLICY_EXEC


def test_golden_adaptive_vc_routing_semantics():
    binding = _canonical_binding()
    assert adaptive_vc_routing_semantics_hash(binding) \
        == GOLDEN_MIN_ADAPT_VC_ROUTING


# ── policy field classification hard gate ──────────────────────────────────

def test_policy_classification_covers_every_identity_field():
    policy = _min_adapt_policy()
    identity = set(policy.identity_dict()) - {"type", "schema_version"}
    classified = (set(rr._POLICY_EXECUTION_FIELDS)
                  | set(rr._POLICY_PRESENTATION_FIELDS)
                  | set(rr._POLICY_VERIFICATION_FIELDS))
    assert identity == classified
    assert rr._POLICY_PRESENTATION_FIELDS == ("id",)
    assert rr._POLICY_VERIFICATION_FIELDS == ("deadlock_proof_obligation",)
    assert "id" not in rr._POLICY_EXECUTION_FIELDS
    assert "deadlock_proof_obligation" not in rr._POLICY_EXECUTION_FIELDS


def test_unclassified_policy_field_fails_closed(monkeypatch):
    policy = _min_adapt_policy()
    original = RoutingPolicyDefinition.identity_dict

    def injected(self):
        data = original(self)
        data["brand_new_field"] = 1
        return data

    monkeypatch.setattr(RoutingPolicyDefinition, "identity_dict", injected)
    with pytest.raises(RoutingRealizationError,
                       match="unclassified RoutingPolicyDefinition"):
        policy_execution_semantics_dict(policy)


def test_policy_execution_projection_excludes_presentation_and_proof():
    policy = _min_adapt_policy()
    projected = policy_execution_semantics_dict(policy)
    assert set(projected) == set(rr._POLICY_EXECUTION_FIELDS)
    assert "id" not in projected
    assert "deadlock_proof_obligation" not in projected


def test_relation_and_binding_identity_field_sets_are_pinned():
    relation = materialize_routing_relation(_mesh(4), _min_adapt_policy())
    assert set(relation.identity_dict()) == rr._RELATION_IDENTITY_FIELDS
    binding = _canonical_binding()
    assert set(binding.identity_dict()) == rr._BINDING_IDENTITY_FIELDS


def test_relation_projection_retains_every_action_semantic():
    relation = materialize_routing_relation(_mesh(4), _min_adapt_policy())
    projected = relation_execution_semantics_dict(relation)
    assert set(projected) == {"topology_hash", "state_domains", "decisions"}
    assert "policy_hash" not in projected
    assert projected["decisions"] == [d.to_dict() for d in relation.decisions]
    blob = repr(projected)
    for token in ("channel_id", "next_role_id", "next_state", "priority",
                  "eject"):
        assert token in blob


# ── deterministic semantics and VC-routing projection ─────────────────────

def test_deterministic_semantics_is_the_resolved_route_hash():
    _att, _r, resolved, _va, _vc, realization = _deterministic((DOR_XY,))
    assert realization.routing_semantics_hash == resolved.resolved_route_hash()
    # the resolved-route identity is execution-semantic only
    assert set(resolved.canonical_dict()) == {
        "type", "schema_version", "topology_hash", "attachment_hash",
        "router_route_hash", "endpoint_to_router", "routing_classes",
        "endpoint_route_table_hash"}


def test_deterministic_vc_routing_projection_is_only_class_map():
    _att, _r, _rr, assignment, _vc, realization = _deterministic((DOR_XY,))
    assert realization.vc_routing_semantics_hash \
        == deterministic_vc_routing_semantics_hash(assignment)
    twin = dataclasses.replace(assignment, vc_to_routing_class=(
        (0, DOR_XY),))
    assert deterministic_vc_routing_semantics_hash(twin) \
        == realization.vc_routing_semantics_hash


def test_deterministic_escape_designation_does_not_move_identity():
    _a1, _r1, _rr1, va1, vc1, without_escape = _deterministic((DOR_XY,),
                                                              escape=())
    _a2, _r2, _rr2, va2, vc2, with_escape = _deterministic((DOR_XY,),
                                                           escape=(0,))
    assert va1.vc_assignment_hash() != va2.vc_assignment_hash()
    assert vc1.artifact_hash == vc2.artifact_hash
    assert without_escape.routing_realization_hash \
        == with_escape.routing_realization_hash
    # escape_vcs is proof designation, not execution semantics
    assert without_escape.vc_routing_semantics_hash \
        == with_escape.vc_routing_semantics_hash


def test_vc_to_routing_class_change_moves_identity():
    _a1, _r1, rr1, _va1, vc1, first = _deterministic(
        (ANYNET_MIN_HOPS, DOR_XY), vc_to_routing_class={0: DOR_XY})
    _a2, _r2, rr2, _va2, vc2, second = _deterministic(
        (ANYNET_MIN_HOPS, DOR_XY), vc_to_routing_class={0: ANYNET_MIN_HOPS})
    assert rr1.resolved_route_hash() == rr2.resolved_route_hash()
    assert vc1.artifact_hash == vc2.artifact_hash
    assert first.routing_realization_hash != second.routing_realization_hash


def test_changed_exact_route_moves_identity():
    _a1, _r1, _rr1, _va1, _vc1, dor = _deterministic((DOR_XY,))
    _a2, _r2, _rr2, _va2, _vc2, anynet = _deterministic((ANYNET_MIN_HOPS,))
    assert dor.routing_realization_hash != anynet.routing_realization_hash


def test_changed_vc_resource_moves_identity():
    _a1, _r1, _rr1, _va1, vc1, first = _deterministic((DOR_XY,))
    _a2, _r2, _rr2, _va2, vc2, second = _deterministic((DOR_XY,), vc_count=2)
    assert vc1.artifact_hash != vc2.artifact_hash
    assert first.routing_realization_hash != second.routing_realization_hash


def test_changed_topology_moves_identity():
    _a1, _r1, _rr1, _va1, _vc1, small = _deterministic((DOR_XY,))
    _a2, _r2, _rr2, _va2, _vc2, large = _deterministic((DOR_XY,), topo=_mesh(9))
    assert small.topology_hash != large.topology_hash
    assert small.routing_realization_hash != large.routing_realization_hash


# ── adaptive invariance gates ──────────────────────────────────────────────

def test_policy_id_change_does_not_move_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    renamed = dataclasses.replace(policy, id="renamed_policy", policy_hash="")
    renamed_relation = _rebind(relation, renamed)
    renamed_binding = _rebind_binding(binding, renamed)
    twin = _adaptive(topo, renamed, vc, renamed_binding, renamed_relation)

    assert policy.policy_hash != renamed.policy_hash
    assert relation.relation_hash != renamed_relation.relation_hash
    assert binding.binding_hash != renamed_binding.binding_hash
    assert base.routing_semantics_hash == twin.routing_semantics_hash
    assert base.vc_routing_semantics_hash == twin.vc_routing_semantics_hash
    assert base.routing_realization_hash == twin.routing_realization_hash


def test_proof_obligation_change_does_not_move_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    alternate = dataclasses.replace(
        policy, deadlock_proof_obligation=DeadlockProofObligation.EXTERNAL,
        policy_hash="")
    alternate_relation = _rebind(relation, alternate)
    alternate_binding = _rebind_binding(binding, alternate)
    twin = _adaptive(topo, alternate, vc, alternate_binding,
                     alternate_relation)

    assert policy.policy_hash != alternate.policy_hash
    assert relation.relation_hash != alternate_relation.relation_hash
    assert binding.binding_hash != alternate_binding.binding_hash
    assert base.routing_realization_hash == twin.routing_realization_hash


# ── adaptive execution-semantic mutation gates ────────────────────────────

_POLICY_ONLY_MUTATIONS = [
    ("algorithm", "weighted_shortest_path"),
    ("algorithm_version", 2),
    ("parameters", {"weight": 7}),
    ("decision_scope", DecisionScope.SOURCE_COMMIT),
    ("candidate_mode", CandidateMode.SINGLETON),
    ("selection_locus", SelectionLocus.ROUTE_COMPUTE),
    ("randomness", RandomnessMode.RNG),
    ("runtime_observations", (RuntimeObservation.OUTPUT_CREDIT_OCCUPANCY,
                              RuntimeObservation.INGRESS_CHANNEL)),
    ("resource_roles", (
        RoutingResourceRole(id="adaptive",
                            kind=RoutingResourceRoleKind.PHASE),
        RoutingResourceRole(id="escape",
                            kind=RoutingResourceRoleKind.ESCAPE))),
]


@pytest.mark.parametrize("field,value", _POLICY_ONLY_MUTATIONS)
def test_policy_execution_mutation_moves_identity(field, value):
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    mutated = dataclasses.replace(policy, policy_hash="", **{field: value})
    twin = _adaptive(topo, mutated, vc, _rebind_binding(binding, mutated),
                     _rebind(relation, mutated))
    assert routing_policy_execution_semantics_hash(policy) \
        != routing_policy_execution_semantics_hash(mutated)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_state_requirement_mutation_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    stateful = dataclasses.replace(
        policy, policy_hash="",
        state_requirements=(RoutingStateRequirement(name="phase",
                                                    kind=RoutingStateKind.PHASE),))
    stateful_relation = _total_relation(
        stateful, topo,
        state_domains=(RoutingStateDomain(name="phase", values=(0, 1)),))
    twin = _adaptive(topo, stateful, vc, _rebind_binding(binding, stateful),
                     stateful_relation)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_allowed_role_transition_mutation_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    relation = materialize_routing_relation(topo, policy)
    base = _adaptive(topo, policy, _min_adapt_vc(), _canonical_binding(),
                     relation)

    widened = dataclasses.replace(
        policy, policy_hash="",
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape"),
                                  ("escape", "adaptive")))
    widened_vc = _min_adapt_vc(_MIN_ADAPT_TRANSITIONS + ((0, 1),))
    widened_binding = RoutingResourceBindingArtifact(
        policy_hash=widened.policy_hash,
        vc_resource_hash=widened_vc.artifact_hash,
        role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))
    twin = _adaptive(topo, widened, widened_vc, widened_binding,
                     _rebind(relation, widened))
    assert routing_policy_execution_semantics_hash(policy) \
        != routing_policy_execution_semantics_hash(widened)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_role_to_vc_partition_change_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy(
        id="symmetric",
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape"),
                                  ("escape", "adaptive")))
    vc = _min_adapt_vc(((0, 0), (0, 1), (1, 0), (1, 1)), count=2)
    relation = _total_relation(policy, topo)
    left_binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash, vc_resource_hash=vc.artifact_hash,
        role_to_vcs=(("adaptive", (1,)), ("escape", (0,))))
    right_binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash, vc_resource_hash=vc.artifact_hash,
        role_to_vcs=(("adaptive", (0,)), ("escape", (1,))))
    left = _adaptive(topo, policy, vc, left_binding, relation)
    right = _adaptive(topo, policy, vc, right_binding, relation)
    assert left_binding.vc_resource_hash == right_binding.vc_resource_hash
    assert left.vc_routing_semantics_hash != right.vc_routing_semantics_hash
    assert left.routing_realization_hash != right.routing_realization_hash


def _first_forward(relation, predicate):
    for decision in relation.decisions:
        for index, action in enumerate(decision.actions):
            if action.kind is RoutingActionKind.FORWARD \
                    and predicate(decision, action):
                return decision, index
    raise AssertionError("no matching forward action")


def _replace_action(relation, target_decision, target_index, **changes):
    decisions = tuple(
        dataclasses.replace(decision, actions=tuple(
            dataclasses.replace(action, **changes)
            if decision is target_decision and index == target_index
            else action for index, action in enumerate(decision.actions)))
        if decision is target_decision else decision
        for decision in relation.decisions)
    return dataclasses.replace(relation, relation_hash="", decisions=decisions)


def test_relation_action_channel_mutation_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    decision, index = _first_forward(relation,
                                     lambda d, a: len(d.actions) > 1)
    current = decision.actions[index]
    alternate = next(channel.channel_id for channel in topo.channels
                     if channel.src_router == decision.context.router_id
                     and channel.channel_id != current.channel_id)
    mutated = _replace_action(relation, decision, index,
                              channel_id=alternate)
    twin = _adaptive(topo, policy, vc, binding, mutated)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_relation_action_priority_mutation_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    decision, index = _first_forward(relation, lambda d, a: True)
    mutated = _replace_action(relation, decision, index,
                              priority=decision.actions[index].priority + 1)
    twin = _adaptive(topo, policy, vc, binding, mutated)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_relation_next_role_mutation_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    decision, index = _first_forward(
        relation,
        lambda d, a: d.context.current_role_id == "adaptive"
        and a.next_role_id == "adaptive"
        and not any(other.kind is RoutingActionKind.FORWARD
                    and other.next_role_id == "escape"
                    and other.channel_id == a.channel_id
                    for other in d.actions))
    mutated = _replace_action(relation, decision, index,
                              next_role_id="escape")
    twin = _adaptive(topo, policy, vc, binding, mutated)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_relation_next_state_mutation_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    base_policy = dataclasses.replace(
        policy, policy_hash="",
        state_requirements=(RoutingStateRequirement(name="phase",
                                                    kind=RoutingStateKind.PHASE),))
    state_domains = (RoutingStateDomain(name="phase", values=(0, 1)),)
    relation = _total_relation(base_policy, topo, state_domains=state_domains)
    binding = _rebind_binding(_canonical_binding(vc, policy), base_policy)
    base = _adaptive(topo, base_policy, vc, binding, relation)

    decision = next(d for d in relation.decisions
                    if d.context.router_id != d.context.destination_router_id)
    index = next(i for i, action in enumerate(decision.actions)
                 if action.kind is RoutingActionKind.FORWARD
                 and action.next_state[0].value == 0)
    mutated = _replace_action(
        relation, decision, index,
        next_state=(RoutingStateBinding("phase", 1),))
    twin = _adaptive(topo, base_policy, vc, binding, mutated)
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_adaptive_vc_resource_change_moves_identity():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    base = _adaptive(topo)
    other_vc = _min_adapt_vc(_MIN_ADAPT_TRANSITIONS + ((0, 1),))
    other_binding = RoutingResourceBindingArtifact(
        policy_hash=policy.policy_hash, vc_resource_hash=other_vc.artifact_hash,
        role_to_vcs=(("adaptive", (1, 2, 3)), ("escape", (0,))))
    widened_policy = dataclasses.replace(
        policy, policy_hash="",
        allowed_role_transitions=(("adaptive", "adaptive"),
                                  ("adaptive", "escape"),
                                  ("escape", "escape"),
                                  ("escape", "adaptive")))
    other_binding = dataclasses.replace(
        other_binding, policy_hash=widened_policy.policy_hash,
        binding_hash="")
    relation = materialize_routing_relation(topo, policy)
    twin = _adaptive(topo, widened_policy, other_vc, other_binding,
                     _rebind(relation, widened_policy))
    assert base.vc_resource_hash != twin.vc_resource_hash
    assert base.routing_realization_hash != twin.routing_realization_hash


def test_adaptive_topology_change_moves_identity():
    small = _adaptive(_mesh(4))
    large = _adaptive(_mesh(9))
    assert small.topology_hash != large.topology_hash
    assert small.routing_realization_hash != large.routing_realization_hash


# ── kind is semantic ───────────────────────────────────────────────────────

def test_kind_is_part_of_identity():
    _att, _r, _rr, _va, _vc, deterministic = _deterministic((DOR_XY,))
    contrived = dataclasses.replace(
        deterministic, routing_realization_hash="",
        kind=RoutingRealizationKind.ADAPTIVE,
        source_hashes=(("policy_hash", "a" * 64),
                       ("relation_hash", "b" * 64),
                       ("routing_resource_binding_hash", "c" * 64)))
    assert contrived.topology_hash == deterministic.topology_hash
    assert contrived.vc_resource_hash == deterministic.vc_resource_hash
    assert contrived.routing_semantics_hash \
        == deterministic.routing_semantics_hash
    assert contrived.vc_routing_semantics_hash \
        == deterministic.vc_routing_semantics_hash
    assert contrived.routing_realization_hash \
        != deterministic.routing_realization_hash


# ── strict source validation / tamper gates ───────────────────────────────

def test_forged_source_hashes_fail_parent_validation():
    topo = _mesh(4)
    policy = _min_adapt_policy()
    vc = _min_adapt_vc()
    relation = materialize_routing_relation(topo, policy)
    binding = _canonical_binding(vc, policy)
    base = _adaptive(topo, policy, vc, binding, relation)

    forged = dataclasses.replace(base, source_hashes=(
        ("policy_hash", "0" * 64),
        ("relation_hash", relation.relation_hash),
        ("routing_resource_binding_hash", binding.binding_hash)))
    loaded = RoutingRealizationArtifact.from_dict(forged.to_dict())
    assert loaded.routing_realization_hash == base.routing_realization_hash
    with pytest.raises(RoutingRealizationError, match="source_hashes"):
        loaded.validate_against_adaptive(
            topology=topo, policy=policy, relation=relation,
            vc_resource=vc, binding=binding)


def test_forged_topology_hash_fails_parent_validation():
    topo = _mesh(4)
    base = _adaptive(topo)
    forged = dataclasses.replace(base, routing_realization_hash="",
                                topology_hash="0" * 64)
    with pytest.raises(RoutingRealizationError, match="topology_hash"):
        forged.validate_against_adaptive(
            topology=topo, policy=_min_adapt_policy(),
            relation=materialize_routing_relation(topo, _min_adapt_policy()),
            vc_resource=_min_adapt_vc(), binding=_canonical_binding())


def test_kind_specific_validation_methods_are_strict():
    _att, _r, _rr, _va, _vc, deterministic = _deterministic((DOR_XY,))
    adaptive = _adaptive(_mesh(4))
    with pytest.raises(RoutingRealizationError, match="DETERMINISTIC"):
        adaptive.validate_against_deterministic(
            topology=_mesh(4), attachment=_att, route=_r, resolved_route=_rr,
            vc_assignment=_va, vc_resource=_vc)
    with pytest.raises(RoutingRealizationError, match="ADAPTIVE"):
        deterministic.validate_against_adaptive(
            topology=_mesh(4), policy=_min_adapt_policy(),
            relation=materialize_routing_relation(_mesh(4),
                                                  _min_adapt_policy()),
            vc_resource=_min_adapt_vc(), binding=_canonical_binding())


def test_non_artifact_parents_are_refused():
    with pytest.raises(RoutingRealizationError, match="TopologyArtifact"):
        make_adaptive_routing_realization(
            topology=object(), policy=_min_adapt_policy(),
            relation=materialize_routing_relation(_mesh(4),
                                                  _min_adapt_policy()),
            vc_resource=_min_adapt_vc(), binding=_canonical_binding())
    with pytest.raises(RoutingRealizationError, match="AgentAttachmentArtifact"):
        make_deterministic_routing_realization(
            topology=_mesh(4), attachment=object(), route=object(),
            resolved_route=object(), vc_assignment=object(),
            vc_resource=_min_adapt_vc())


def test_deterministic_projection_mismatch_is_refused():
    _att, route, resolved, assignment, _vc, _real = _deterministic((DOR_XY,))
    wrong_vc = _min_adapt_vc()
    with pytest.raises(RoutingRealizationError, match="projection"):
        make_deterministic_routing_realization(
            topology=_mesh(4), attachment=_att, route=route,
            resolved_route=resolved, vc_assignment=assignment,
            vc_resource=wrong_vc)


# ── strict serialization ───────────────────────────────────────────────────

def test_roundtrip_is_lossless():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    loaded = RoutingRealizationArtifact.from_dict(realization.to_dict())
    assert loaded == realization
    assert loaded.to_dict() == realization.to_dict()


def test_serialized_keys_are_exactly_the_schema():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    assert set(realization.identity_dict()) == IDENTITY_KEYS
    assert set(realization.to_dict()) == SERIALIZED_KEYS
    assert {f.name for f in dataclasses.fields(RoutingRealizationArtifact)} \
        == SCHEMA_FIELDS


def test_unknown_and_missing_fields_are_refused():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["extra"] = 1
    with pytest.raises(RoutingRealizationError, match="unknown fields"):
        RoutingRealizationArtifact.from_dict(persisted)
    for field in sorted(SERIALIZED_KEYS):
        persisted = realization.to_dict()
        persisted.pop(field)
        with pytest.raises(RoutingRealizationError):
            RoutingRealizationArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", [None, "srota/ResolvedRouteArtifact", 7])
def test_type_tag_is_strict(bad):
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    if bad is None:
        persisted.pop("type")
    else:
        persisted["type"] = bad
    with pytest.raises(RoutingRealizationError, match="type"):
        RoutingRealizationArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", [0, 2, "1", True])
def test_schema_version_is_strict(bad):
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["schema_version"] = bad
    with pytest.raises(RoutingRealizationError, match="schema_version"):
        RoutingRealizationArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", ["AUTO", "hybrid", "custom", 1])
def test_kind_is_strict(bad):
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["kind"] = bad
    with pytest.raises(RoutingRealizationError, match="kind"):
        RoutingRealizationArtifact.from_dict(persisted)


def test_source_rows_must_be_pairs_and_lists():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["source_hashes"] = {"route_hash": "a" * 64}
    with pytest.raises(RoutingRealizationError, match="source_hashes"):
        RoutingRealizationArtifact.from_dict(persisted)
    persisted = realization.to_dict()
    persisted["source_hashes"] = [["route_hash", "a" * 64, "extra"]]
    with pytest.raises(RoutingRealizationError, match="source_hashes"):
        RoutingRealizationArtifact.from_dict(persisted)


def test_source_names_are_kind_specific():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["source_hashes"] = [
        ["policy_hash", "a" * 64],
        ["relation_hash", "b" * 64],
        ["routing_resource_binding_hash", "c" * 64]]
    with pytest.raises(RoutingRealizationError, match="source hashes"):
        RoutingRealizationArtifact.from_dict(persisted)


def test_source_hash_order_must_be_canonical():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["source_hashes"] = list(reversed(persisted["source_hashes"]))
    with pytest.raises(RoutingRealizationError, match="source hashes"):
        RoutingRealizationArtifact.from_dict(persisted)


@pytest.mark.parametrize("bad", ["", "a" * 63, "A" * 64, "g" * 64, 7])
def test_source_hash_shape_is_strict(bad):
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted["source_hashes"][1][1] = bad
    with pytest.raises(RoutingRealizationError, match="hash"):
        RoutingRealizationArtifact.from_dict(persisted)


def test_source_hashes_accept_sha256_prefix():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    assert realization.source_hash("route_hash").startswith("sha256:")
    loaded = RoutingRealizationArtifact.from_dict(realization.to_dict())
    assert loaded.source_hash("route_hash") \
        == realization.source_hash("route_hash")


def test_identity_hash_shapes_are_strict():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    for field in ("topology_hash", "vc_resource_hash",
                  "routing_semantics_hash", "vc_routing_semantics_hash"):
        persisted = realization.to_dict()
        persisted[field] = "sha256:" + "a" * 64
        with pytest.raises(RoutingRealizationError, match=field):
            RoutingRealizationArtifact.from_dict(persisted)


def test_hash_must_be_present_and_match():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    persisted = realization.to_dict()
    persisted.pop("routing_realization_hash")
    with pytest.raises(RoutingRealizationError, match="routing_realization"):
        RoutingRealizationArtifact.from_dict(persisted)
    persisted = realization.to_dict()
    persisted["routing_realization_hash"] = "0" * 64
    with pytest.raises(RoutingRealizationError, match="does not match"):
        RoutingRealizationArtifact.from_dict(persisted)


def test_unsupported_relation_schema_fails_closed():
    relation = materialize_routing_relation(_mesh(4), _min_adapt_policy())
    object.__setattr__(relation, "schema_version", 99)
    with pytest.raises(RoutingRealizationError, match="UNSUPPORTED"):
        relation_execution_semantics_dict(relation)


def test_unsupported_binding_schema_fails_closed():
    binding = _canonical_binding()
    object.__setattr__(binding, "schema_version", 99)
    with pytest.raises(RoutingRealizationError, match="UNSUPPORTED"):
        adaptive_vc_routing_semantics_hash(binding)


# ── immutability ───────────────────────────────────────────────────────────

def test_artifact_is_frozen_and_source_hashes_immutable():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    with pytest.raises(dataclasses.FrozenInstanceError):
        realization.kind = RoutingRealizationKind.ADAPTIVE
    assert isinstance(realization.source_hashes, tuple)
    with pytest.raises(TypeError):
        realization.source_hashes[0] = ("route_hash", "a" * 64)


def test_to_dict_returns_fresh_data():
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    first = realization.to_dict()
    first["source_hashes"].clear()
    first["kind"] = "tampered"
    second = realization.to_dict()
    assert len(second["source_hashes"]) == 3
    assert second["kind"] == "deterministic"
    assert realization.routing_realization_hash == GOLDEN_DET_DOR_2X2


# ── endpoint seam invariant ────────────────────────────────────────────────

def test_adaptive_topology_endpoints_reference_real_routers():
    topo = _mesh(4)
    design = CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
        requirements=[], agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=4)],
        dependencies=[], noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    inventory = build_inventory(design)
    attachment = derive_attachment(design=design, inventory=inventory,
                                   topology=topo)
    attachment.validate_against_topology(topo)
    router_ids = {router.router_id for router in topo.routers}
    assert {endpoint.router_id for endpoint in attachment.endpoints} \
        <= router_ids
    realization = _adaptive(topo)
    assert realization.topology_hash == topo.topology_hash()


# ── scope sentinels ────────────────────────────────────────────────────────

def test_no_certificate_or_verification_fields():
    for token in ("certificate", "verdict", "proof_obligation",
                  "deadlock_proof", "timestamp", "pass_fail"):
        assert not hasattr(rr, token)
    names = {f.name for f in dataclasses.fields(RoutingRealizationArtifact)}
    assert not any("certificate" in n or "verdict" in n or "proof" in n
                   for n in names)
    _att, _r, _rr, _va, _vc, realization = _deterministic((DOR_XY,))
    blob = repr(realization.to_dict()).lower()
    for token in ("certificate", "verdict", "proof", "timestamp", "seed",
                  "backend", "run_id", "git_sha"):
        assert token not in blob, token


def test_module_imports_only_allowed_layers():
    tree = ast.parse(inspect.getsource(rr))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    local = {name for name in imported if name.startswith("veritx_dse")}
    assert local == {
        "veritx_dse.core.artifact",
        "veritx_dse.core.route_artifact",
        "veritx_dse.model.attachment",
        "veritx_dse.model.resolved_route",
        "veritx_dse.model.routing_policy",
        "veritx_dse.model.routing_relation",
        "veritx_dse.model.routing_resource_binding",
        "veritx_dse.model.topology_artifact",
        "veritx_dse.model.vc_assignment",
        "veritx_dse.model.vc_resource",
    }
    forbidden = ("packet_format", "router_behavior", "address_decode",
                 "verification", "booksim", "astra", "backend", "cli")
    for name in imported:
        assert not any(token in name.lower() for token in forbidden), name
