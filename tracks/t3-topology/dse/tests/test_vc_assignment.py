"""Wave B3.3a tests — VCAssignmentArtifact + no silent VC clamping."""
from __future__ import annotations

import pytest

from veritx_dse.core.constants import PLANE_C_MAX_VC
from veritx_dse.core.route_artifact import ANYNET_MIN_HOPS, RouteArtifact
from veritx_dse.model.attachment import derive_attachment
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CollectiveKind, CollectiveOp, CompileRequest, DepKind,
    Dependency, DependencyGraph, ModelFamily, NocConfig,
    TopologyFamily, Workload, derive_topology_spec,
    derive_vc_assignment, derive_vc_assignment_artifact, derive_vc_count,
)
from veritx_dse.model.mapping import derive_mapping
from veritx_dse.model.placement import build_inventory
from veritx_dse.model.resolved_route import derive_resolved_route
from veritx_dse.model.topology_artifact import materialize_topology
from veritx_dse.model.vc_assignment import (
    VCAssignmentArtifact, VCAssignmentError as VCAErr,
    make_vc_assignment_artifact,
)

VCAssignmentError = VCAErr


def _cr(agents=4, deps=(), collectives=()):
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1,
                          collectives=tuple(collectives)),
        requirements=[],
        agents=[Agent(kind=AgentKind.COMPUTE_TILE, count=agents)],
        dependencies=DependencyGraph(list(deps)),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    )


def _resolved_route(cr):
    inv = build_inventory(cr)
    topo = materialize_topology(inv, cr)
    att = derive_attachment(design=cr, inventory=inv, topology=topo)
    rr = RouteArtifact.from_topology(topo, name="t")
    return derive_resolved_route(topo, att, rr)


class TestBuilder:
    def test_defaults_are_honest(self):
        cr = _cr()
        rra = _resolved_route(cr)
        art = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [0], "B": [1]},
            derivation="unit",
        )
        assert art.vc_ids == (0, 1)
        assert art.vc_to_routing_class == ((0, ANYNET_MIN_HOPS),
                                           (1, ANYNET_MIN_HOPS))
        # VC-preserving transitions only, no invented escape VC.
        assert art.allowed_transitions == ((0, 0), (1, 1))
        assert art.escape_vcs == ()
        assert art.resolved_route_hash == rra.resolved_route_hash()

    def test_parent_hash_bound_to_resolved_route(self):
        cr = _cr()
        rra = _resolved_route(cr)
        art = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=1,
            traffic_class_to_vcs={"A": [0]}, derivation="unit")
        art.validate_against(rra)
        assert art.resolved_route_hash == rra.resolved_route_hash()

    def test_unknown_routing_class_refused(self):
        cr = _cr()
        rra = _resolved_route(cr)
        with pytest.raises(VCAErr):
            make_vc_assignment_artifact(
                resolved_route=rra, vc_count=1,
                traffic_class_to_vcs={"A": [0]},
                vc_to_routing_class={0: "ESCAPE"},  # not in resolved route
                derivation="unit")

    def test_deterministic_hash_and_roundtrip(self):
        cr = _cr()
        rra = _resolved_route(cr)
        kw = dict(resolved_route=rra, vc_count=3,
                  traffic_class_to_vcs={"B": [2], "A": [0, 1]},
                  derivation="unit")
        a = make_vc_assignment_artifact(**kw)
        b = make_vc_assignment_artifact(**kw)
        assert a.vc_assignment_hash() == b.vc_assignment_hash()
        assert VCAssignmentArtifact.from_dict(a.to_dict()) \
            .vc_assignment_hash() == a.vc_assignment_hash()

    def test_each_semantic_change_changes_hash(self):
        cr = _cr()
        rra = _resolved_route(cr)
        base = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [0], "B": [1]}, derivation="unit")
        more_vcs = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=3,
            traffic_class_to_vcs={"A": [0], "B": [1]}, derivation="unit")
        moved = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [1], "B": [1]}, derivation="unit")
        other_prov = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [0], "B": [1]}, derivation="other")
        semantic = {base.vc_assignment_hash(), more_vcs.vc_assignment_hash(),
                    moved.vc_assignment_hash()}
        assert len(semantic) == 3
        # derivation is provenance: it does NOT change identity
        assert other_prov.vc_assignment_hash() == base.vc_assignment_hash()

    def test_derivation_is_provenance_not_identity(self):
        """Same VC semantics + different derivation => same hash."""
        cr = _cr()
        rra = _resolved_route(cr)
        a = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [0], "B": [1]},
            derivation="two blocking dependency cycles")
        b = make_vc_assignment_artifact(
            resolved_route=rra, vc_count=2,
            traffic_class_to_vcs={"A": [0], "B": [1]},
            derivation="compiler pass 7 determined 2 VCs")
        assert a.vc_assignment_hash() == b.vc_assignment_hash()
        # ...while the provenance still round-trips for explanation.
        assert a.to_dict()["derivation"] == "two blocking dependency cycles"
        loaded = VCAssignmentArtifact.from_dict(b.to_dict())
        assert loaded.derivation == "compiler pass 7 determined 2 VCs"
        assert loaded.vc_assignment_hash() == a.vc_assignment_hash()
        assert "derivation" not in a.identity_dict()


class TestStructuralIntegrity:
    def _artifact(self, **over):
        cr = _cr()
        rra = _resolved_route(cr)
        kw = dict(resolved_route_hash=rra.resolved_route_hash(), vc_count=2,
                  vc_ids=(0, 1),
                  traffic_class_to_vcs=(("A", (0,)), ("B", (1,))),
                  vc_to_routing_class=((0, "DEFAULT"), (1, "DEFAULT")),
                  allowed_transitions=((0, 0), (1, 1)), escape_vcs=(),
                  derivation="unit")
        kw.update(over)
        return VCAssignmentArtifact(**kw)

    def test_sparse_vc_ids_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(vc_ids=(0, 2))

    def test_missing_vc_routing_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(vc_to_routing_class=((0, "DEFAULT"),))

    def test_escape_out_of_range_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(escape_vcs=(2,))

    def test_unsorted_traffic_classes_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(traffic_class_to_vcs=(("B", (1,)), ("A", (0,))))

    def test_unsorted_transitions_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(allowed_transitions=((1, 1), (0, 0)))

    def test_tampered_hash_refused(self):
        art = self._artifact()
        d = art.to_dict()
        d["vc_count"] = 3
        with pytest.raises(VCAErr):
            VCAssignmentArtifact.from_dict(d)

    def test_unknown_field_refused(self):
        art = self._artifact()
        d = art.to_dict()
        d["extra"] = 1
        with pytest.raises(VCAErr):
            VCAssignmentArtifact.from_dict(d)

    def test_bool_vc_id_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(vc_ids=(0, True))

    def test_float_vc_count_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(vc_count=2.0)

    def test_bool_traffic_vc_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(
                traffic_class_to_vcs=(("A", (False,)), ("B", (1,))))

    def test_bool_escape_vc_refused(self):
        with pytest.raises(VCAErr):
            self._artifact(escape_vcs=(True,))

    def test_persisted_impostors_are_rejected_not_repaired(self):
        art = self._artifact()
        mutations = (
            lambda d: d.update(vc_ids=[0, True]),
            lambda d: d.update(escape_vcs=[False]),
            lambda d: d.update(
                traffic_class_to_vcs=[["A", [0]], ["B", [True]]]),
            lambda d: d.update(
                vc_to_routing_class=[["0", "DEFAULT"], [1, "DEFAULT"]]),
        )
        for mutate in mutations:
            d = art.to_dict()
            mutate(d)
            with pytest.raises(VCAErr):
                VCAssignmentArtifact.from_dict(d)

    def test_parent_mismatch_refused(self):
        art = self._artifact()
        cr = _cr()
        rra = _resolved_route(cr)
        object.__setattr__(art, "resolved_route_hash", "0" * 64)
        with pytest.raises(VCAErr):
            art.validate_against(rra)


class TestNoClamp:
    @staticmethod
    def _cycles(n):
        deps = []
        for i in range(n):
            deps.append(Dependency(f"A{i}", f"B{i}", DepKind.BLOCKING))
            deps.append(Dependency(f"B{i}", f"A{i}", DepKind.BLOCKING))
        return DependencyGraph(deps)

    def test_raw_count_not_clamped(self):
        g = self._cycles(PLANE_C_MAX_VC + 1)
        assert derive_vc_count(g) == PLANE_C_MAX_VC + 2

    def test_over_limit_is_unsupported(self):
        cr = _cr(deps=[
            Dependency(f"A{i}", f"B{i}", DepKind.BLOCKING)
            for i in range(PLANE_C_MAX_VC)
        ] + [
            Dependency(f"B{i}", f"A{i}", DepKind.BLOCKING)
            for i in range(PLANE_C_MAX_VC)
        ])
        with pytest.raises(VCAssignmentError, match="UNSUPPORTED"):
            derive_vc_assignment(cr)

    def test_collective_floor_over_limit_is_unsupported(self):
        colls = [CollectiveOp(kind=CollectiveKind.ALLREDUCE, group_size=4)
                 for _ in range(PLANE_C_MAX_VC + 1)]
        cr = _cr(collectives=colls)
        with pytest.raises(VCAssignmentError, match="UNSUPPORTED"):
            derive_vc_assignment(cr)

    def test_topology_spec_uses_exact_vc_count(self):
        deps = [Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING)]
        spec = derive_topology_spec(_cr(deps=deps))
        assert spec.params["num_vcs"] == 2
        plain = derive_topology_spec(_cr())
        assert plain.params["num_vcs"] == 1


class TestCompileSeam:
    def test_assignment_artifact_from_compile_request(self):
        deps = [Dependency("A", "B", DepKind.BLOCKING),
                Dependency("B", "A", DepKind.BLOCKING)]
        cr = _cr(deps=deps)
        rra = _resolved_route(cr)
        art = derive_vc_assignment_artifact(cr, rra)
        assert art.vc_count == 2
        assert art.resolved_route_hash == rra.resolved_route_hash()
        # VC 1 exists solely to break the cycle: provenance records it,
        # no escape claim is made.
        assert art.escape_vcs == ()
        assert "cycle_separated=" in art.derivation
        art.validate_against(rra)
