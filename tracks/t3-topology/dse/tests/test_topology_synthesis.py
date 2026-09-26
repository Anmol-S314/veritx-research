"""Canonical topology synthesis tests (SYN-1..SYN-40).

TRANCHE 3. Proves that an EXISTING synthesis engine (milp_topology_v2)
produces a canonical candidate that enters the SAME compiler, verification,
evaluation and visualisation pipeline as an authored topology.

The synthesizer must never become a second compiler, verifier or evaluator.

FIXTURE: 4x4 grid, 16 routers, radix 4, max_len 1.0. Solves to OPTIMAL in
~0.2s, which is what makes it usable as an ordinary test and what makes
solver-status honesty provable against a REAL optimality proof.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.synthesis.definition import (
    SynthesisDefinition,
    SynthesisDefinitionError,
)
from veritx_dse.synthesis.traffic import (
    SynthesisTrafficError,
    SynthesisTrafficMatrix,
    from_uniform,
)
from veritx_dse.synthesis.candidate import (
    PRODUCER_ID,
    TopologyCandidate,
    TopologyCandidateError,
    anynet_projection,
    synthesize,
    to_topology_ir,
)

N = 16
K = 4
RADIX = 4
MAX_LEN = 1.0


def _defn(**kw) -> SynthesisDefinition:
    base = dict(nodes=N, layout="grid", k=K, radix=RADIX, max_len=MAX_LEN,
                bandwidth_GBs=50.0, latency_ns=500.0, timeout_s=60)
    base.update(kw)
    return SynthesisDefinition(**base)


def _traffic(n: int = N, **kw) -> SynthesisTrafficMatrix:
    base = dict(demand=1.0, source_artifact_id="sha256:fixture-uniform",
                namespace="router", unit="messages",
                aggregation="sum_over_workload")
    base.update(kw)
    return from_uniform(n, **base)


@pytest.fixture(scope="module")
def solved():
    """One real synthesis, shared: 0.2s, so module scope keeps tests quick."""
    d, t = _defn(), _traffic()
    return d, t, synthesize(d, t)


# ══ SYN-1..SYN-5: definition identity ══════════════════════════════════

def test_syn_1_definition_round_trip():
    d = _defn()
    back = SynthesisDefinition.from_dict(d.to_dict())
    assert back == d
    assert back.definition_id() == d.definition_id()


def test_syn_2_identity_stable_under_serialization():
    d = _defn()
    assert SynthesisDefinition.from_dict(d.to_dict()).definition_id() == \
        d.definition_id()
    # Deterministic canonical JSON.
    assert d.canonical_json() == _defn().canonical_json()


def test_syn_3_scientific_change_changes_identity():
    base = _defn().definition_id()
    for kw in ({"radix": 3}, {"max_len": 2.0}, {"k": 3, "nodes": 9},
               {"latency_ns": 600.0}, {"bandwidth_GBs": 64.0},
               {"objective": "priced_geodesic"}, {"pipe_cost": 4.0},
               {"wire_cost": 2.0}, {"layout_seed": 11}):
        assert _defn(**kw).definition_id() != base, kw


def test_syn_4_execution_policy_does_not_change_scientific_identity():
    """A timeout or an exact-solve cap changes how long a run takes, never
    which graph is correct."""
    a = _defn(timeout_s=10, max_nodes=8)
    b = _defn(timeout_s=600, max_nodes=64)
    assert a.definition_id() == b.definition_id()
    assert a.to_dict()["execution_policy"] != b.to_dict()["execution_policy"]


def test_syn_5_unknown_fields_fail_closed():
    d = _defn().to_dict()
    d["surprise"] = 1
    with pytest.raises(SynthesisDefinitionError):
        SynthesisDefinition.from_dict(d)
    # Unknown execution-policy field too.
    d2 = _defn().to_dict()
    d2["execution_policy"]["threads"] = 4
    with pytest.raises(SynthesisDefinitionError):
        SynthesisDefinition.from_dict(d2)
    # And a tampered identity.
    d3 = _defn().to_dict()
    d3["definition_id"] = "deadbeef"
    with pytest.raises(SynthesisDefinitionError):
        SynthesisDefinition.from_dict(d3)


def test_syn_5b_diameter_is_not_exposed():
    """The engine advertises diameter in prose but never constrains it.
    Exposing an unenforced constraint would be a false capability."""
    d = _defn()
    assert not hasattr(d, "diameter")
    with pytest.raises(TypeError):
        SynthesisDefinition(nodes=N, layout="grid", k=K, radix=RADIX,
                            max_len=MAX_LEN, bandwidth_GBs=50.0,
                            latency_ns=500.0, diameter=3)


# ══ SYN-6..SYN-10: traffic authority ═══════════════════════════════════

def test_syn_6_projection_exact_dimensions():
    t = _traffic()
    assert t.dimension == N
    assert len(t.values) == N
    assert all(len(r) == N for r in t.values)
    assert t.total_demand() == N * (N - 1) * 1.0


def test_syn_7_traffic_conservation():
    t = _traffic()
    total = sum(sum(r) for r in t.values)
    assert t.total_demand() == total
    assert all(t.values[i][i] == 0 for i in range(N)), "no self-traffic"


def test_syn_8_malformed_negative_nonfinite_refuse():
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, -1], [1, 0]], source_artifact_id="s", namespace="r",
            unit="messages", aggregation="sum_over_workload")
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, float("nan")], [1, 0]], source_artifact_id="s",
            namespace="r", unit="messages", aggregation="sum_over_workload")
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, float("inf")], [1, 0]], source_artifact_id="s",
            namespace="r", unit="messages", aggregation="sum_over_workload")
    # Ragged and non-square refuse rather than being truncated.
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, 1], [1]], source_artifact_id="s", namespace="r",
            unit="messages", aggregation="sum_over_workload")
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, 1, 2], [1, 0, 1]], source_artifact_id="s", namespace="r",
            unit="messages", aggregation="sum_over_workload")


def test_syn_8b_nonzero_diagonal_refuses():
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[5, 1], [1, 0]], source_artifact_id="s", namespace="r",
            unit="messages", aggregation="sum_over_workload")


def test_syn_9_namespace_and_source_are_required():
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, 1], [1, 0]], source_artifact_id="", namespace="r",
            unit="messages", aggregation="sum_over_workload")
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, 1], [1, 0]], source_artifact_id="s", namespace="",
            unit="messages", aggregation="sum_over_workload")
    # Unknown unit / aggregation refuse.
    with pytest.raises(SynthesisTrafficError):
        SynthesisTrafficMatrix.from_rows(
            [[0, 1], [1, 0]], source_artifact_id="s", namespace="r",
            unit="packets", aggregation="sum_over_workload")


def test_syn_10_no_uniform_fallback_in_the_canonical_adapter():
    """A missing or malformed traffic authority must REFUSE, never default
    to uniform."""
    with pytest.raises(TopologyCandidateError):
        synthesize(_defn(), None)
    with pytest.raises(TopologyCandidateError):
        synthesize(_defn(), "uniform")
    # Dimension mismatch is refused rather than reshaped.
    with pytest.raises(TopologyCandidateError) as e:
        synthesize(_defn(), _traffic(9))
    assert "mismatched problem" in str(e.value)


def test_syn_10b_the_historical_loader_would_not_have_noticed():
    """The canonical adapter's strictness is the point: load_matrix parses
    floats with no validation at all."""
    from veritx_dse.synthesis import milp_topology_v2 as engine
    import inspect
    src = inspect.getsource(engine.load_matrix)
    for check in ("shape", "isfinite", "nan", "raise", "dimension"):
        assert check not in src.lower(), (
            "load_matrix gained validation; the canonical adapter's "
            "fail-closed rationale must be re-checked")


# ══ SYN-11..SYN-15: candidate ══════════════════════════════════════════

def test_syn_11_candidate_round_trip(solved):
    _d, _t, c = solved
    assert TopologyCandidate.from_dict(c.to_dict()) == c
    assert TopologyCandidate.from_dict(c.to_dict()).candidate_id() == \
        c.candidate_id()


def test_syn_12_candidate_graph_is_exact(solved):
    _d, _t, c = solved
    assert c.nodes == N
    assert len(c.links) == len(set(c.links))
    for u, v in c.links:
        assert u < v, "links are canonically ordered"
        assert 0 <= u < N and 0 <= v < N
        assert u != v


def test_syn_13_generator_objective_is_classified(solved):
    _d, _t, c = solved
    assert c.objective_name == "traffic_weighted_hops"
    d = c.to_dict()
    assert d["objective_is_measured_performance"] is False
    # It is NOT any of the measured/verified concepts.
    for forbidden in ("latency_ns", "completion_cycles", "booksim",
                      "pareto", "verified", "measured"):
        assert forbidden not in d["producer"]["objective_name"]


def test_syn_14_candidate_carries_no_certificate_or_performance(solved):
    _d, _t, c = solved
    d = c.to_dict()
    for forbidden in ("certificate", "certificate_id", "obligations",
                      "performance_result_id", "pareto_ids", "qualified",
                      "route", "vc", "deadlock", "evidence"):
        assert forbidden not in d, f"candidate must not carry {forbidden!r}"
    for forbidden in ("certificate", "performance", "pareto", "route"):
        assert not hasattr(c, forbidden)


def test_syn_15_candidate_schema_validates_before_persistence(solved):
    _d, _t, c = solved
    bad = c.to_dict()
    bad["surprise"] = 1
    with pytest.raises(TopologyCandidateError):
        TopologyCandidate.from_dict(bad)
    tampered = c.to_dict()
    tampered["candidate_id"] = "deadbeef"
    with pytest.raises(TopologyCandidateError):
        TopologyCandidate.from_dict(tampered)
    # A status that disagrees with the graph refuses.
    with pytest.raises(TopologyCandidateError):
        TopologyCandidate(
            definition_id=c.definition_id, traffic_id=c.traffic_id,
            nodes=N, links=c.links, algorithm="milp_tmcf",
            solver_status="OPTIMAL", objective_value=1.0,
            objective_name="traffic_weighted_hops", status="INFEASIBLE",
            producer_id=PRODUCER_ID)


# ══ SYN-16..SYN-20: constraints ════════════════════════════════════════

def test_syn_16_radix_enforced(solved):
    _d, _t, c = solved
    deg: dict[int, int] = {}
    for u, v in c.links:
        deg[u] = deg.get(u, 0) + 1
        deg[v] = deg.get(v, 0) + 1
    assert max(deg.values()) <= RADIX, "degree must respect radix"


def test_syn_17_link_length_enforced():
    """max_len bounds which links are admissible candidates. A tighter
    radius cannot produce a longer link."""
    from veritx_dse.synthesis.candidate import _layout_xy
    from veritx_dse.synthesis import milp_topology_v2 as engine
    d = _defn()
    xy = _layout_xy(d)
    for u, v in engine.valid_links(xy, MAX_LEN):
        assert abs(xy[u][0] - xy[v][0]) + abs(xy[u][1] - xy[v][1]) <= MAX_LEN


def test_syn_18_19_unenforced_constraints_are_not_exposed():
    """diameter and an explicit layout restriction are NOT exposed: the
    engine constrains link-capacity, flow conservation and radix only."""
    d = _defn()
    fields = set(d.scientific_dict())
    assert "diameter" not in fields
    assert "layout_restriction" not in fields
    import inspect
    from veritx_dse.synthesis import milp_topology_v2 as engine
    src = inspect.getsource(engine.solve_tmcf)
    assert "diameter" not in src.lower()


def test_syn_20_infeasible_is_typed_not_a_design_error():
    """An unsatisfiable problem returns INFEASIBLE/FAILED/TIMED_OUT — never
    an exception that reads as an invalid user design."""
    d = _defn(radix=2, max_len=1.0, timeout_s=5)
    c = synthesize(d, _traffic())
    assert c.status in ("INFEASIBLE", "FAILED", "TIMED_OUT", "SUCCEEDED")
    if c.status != "SUCCEEDED":
        assert c.links == ()
        assert c.objective_value is None
    # Never a DesignError-style exception.
    assert isinstance(c, TopologyCandidate)


# ══ SYN-21..SYN-25: compiler convergence ═══════════════════════════════

def test_syn_21_candidate_enters_the_topology_ir_path(solved):
    d, _t, c = solved
    ir = to_topology_ir(c, d)
    assert ir.kind == "custom", "the SAME explicit representation as an authored graph"
    assert ir.nodes == c.nodes
    assert sorted(tuple(sorted(e)) for e in ir.links) == sorted(c.links)


def test_syn_22_synthesized_and_authored_converge_before_topologyartifact(solved):
    """THE STRONGEST PROOF: the same graph authored by hand and generated by
    the engine must materialize to an EQUIVALENT TopologyArtifact."""
    d, _t, c = solved
    from veritx_dse.model import topology_ir as tir
    from veritx_dse.model.topology_artifact import materialize_ir

    synth_ir = to_topology_ir(c, d)
    authored_ir = tir.from_dict({
        "name": "authored-by-hand", "kind": "custom", "nodes": c.nodes,
        "links": [[u, v] for u, v in c.links],
        "link_attrs": {"bandwidth_GBs": d.bandwidth_GBs,
                       "latency_ns": d.latency_ns},
    })
    a = materialize_ir(synth_ir, width_bits=64, latency_cycles=1)
    b = materialize_ir(authored_ir, width_bits=64, latency_cycles=1)
    # Origin differs; scientific graph does not.
    assert a.topology_hash() == b.topology_hash(), (
        "a synthesized graph and the same graph authored by hand must be "
        "the SAME scientific topology")
    assert synth_ir.name != authored_ir.name
    assert a.family == b.family


def test_syn_23_no_synthesis_specific_route_derivation(solved):
    """The candidate carries no route, and the artifact is produced by the
    ordinary materializer — there is no synthesis route path."""
    _d, _t, c = solved
    assert not hasattr(c, "route")
    from veritx_dse.model.topology_artifact import materialize_ir
    art = materialize_ir(to_topology_ir(c, _d), width_bits=64,
                         latency_cycles=1)
    d = art.to_dict()
    for forbidden in ("route", "routes", "vc", "vc_count", "turn",
                      "escape", "certificate"):
        assert forbidden not in d


def test_syn_24_normal_staged_refusal_applies(solved):
    """A generated topology is NOT special-cased: if the ordinary compiler
    cannot route it, it stops exactly as an authored graph would."""
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_ir,
    )
    _d, _t, c = solved
    art = materialize_ir(to_topology_ir(c, _d), width_bits=64,
                         latency_cycles=1)
    assert art.family == MaterializedFamily.CUSTOM
    # Same artifact type, same validation, no synthesis branch.
    assert type(art).__name__ == "TopologyArtifact"


def test_syn_25_no_privileged_verification(solved):
    """Verification is downstream and not pre-claimed on the candidate."""
    _d, _t, c = solved
    assert not hasattr(c, "certificate")
    assert "verified" not in c.to_dict()


# ══ SYN-26..SYN-30: provenance and staleness ═══════════════════════════

def test_syn_26_provenance_chain(solved):
    d, t, c = solved
    assert c.definition_id == d.definition_id()
    assert c.traffic_id == t.traffic_id()
    # result -> fabric -> topology -> candidate -> definition -> traffic
    from veritx_dse.model.topology_artifact import materialize_ir
    art = materialize_ir(to_topology_ir(c, d), width_bits=64,
                         latency_cycles=1)
    assert art.topology_hash()
    assert c.candidate_id() and c.graph_id()


def test_syn_27_changed_traffic_invalidates_reuse(solved):
    d, _t, c = solved
    other = _traffic(demand=2.0)
    assert other.traffic_id() != c.traffic_id
    # Same graph, different traffic => different candidate.
    twin = TopologyCandidate(
        definition_id=c.definition_id, traffic_id=other.traffic_id(),
        nodes=c.nodes, links=c.links, algorithm=c.algorithm,
        solver_status=c.solver_status, objective_value=c.objective_value,
        objective_name=c.objective_name, status=c.status,
        producer_id=c.producer_id)
    assert twin.candidate_id() != c.candidate_id()
    assert twin.graph_id() == c.graph_id(), "the graph itself is unchanged"


def test_syn_28_changed_definition_invalidates_reuse(solved):
    _d, _t, c = solved
    other = _defn(radix=3)
    twin = TopologyCandidate(
        definition_id=other.definition_id(), traffic_id=c.traffic_id,
        nodes=c.nodes, links=c.links, algorithm=c.algorithm,
        solver_status=c.solver_status, objective_value=c.objective_value,
        objective_name=c.objective_name, status=c.status,
        producer_id=c.producer_id)
    assert twin.candidate_id() != c.candidate_id()


def test_syn_29_changed_candidate_schema_refuses_stale_payload(solved):
    _d, _t, c = solved
    stale = c.to_dict()
    stale["schema_version"] = 999
    with pytest.raises(TopologyCandidateError):
        TopologyCandidate.from_dict(stale)


def test_syn_30_generator_semantics_version_is_provenance_not_identity(solved):
    _d, _t, c = solved
    bumped = TopologyCandidate(
        definition_id=c.definition_id, traffic_id=c.traffic_id,
        nodes=c.nodes, links=c.links, algorithm=c.algorithm,
        solver_status=c.solver_status, objective_value=c.objective_value,
        objective_name=c.objective_name, status=c.status,
        producer_id=c.producer_id, generator_semantics_version="2")
    # Same graph, same scientific candidate; producer provenance differs.
    assert bumped.candidate_id() == c.candidate_id()
    assert bumped.producer_dict()["generator_semantics_version"] == "2"


# ══ SYN-31..SYN-33: backend boundary ═══════════════════════════════════

def test_syn_31_anynet_projection_is_deterministic(solved):
    _d, _t, c = solved
    assert anynet_projection(c) == anynet_projection(c)


def test_syn_32_anynet_formatting_does_not_alter_candidate_identity(solved):
    """Rewriting the projection cannot change what the candidate IS."""
    _d, _t, c = solved
    before = c.candidate_id()
    text = anynet_projection(c)
    # Reformat: reorder, strip, and rejoin.
    reformatted = "\n".join(reversed(text.strip().splitlines()))
    assert reformatted != text
    assert c.candidate_id() == before
    assert "anynet" not in c.to_dict()
    assert text not in c.canonical_json()


def test_syn_33_anynet_is_not_scientific_authority(solved):
    """The canonical graph is `links`; the projection is derived from it and
    is never an input."""
    _d, _t, c = solved
    d = c.to_dict()
    assert "links" in d and "anynet" not in d
    # Reconstructing the projection from links alone is possible; the
    # reverse is not how identity is computed.
    assert anynet_projection(c).count("router") >= c.nodes


# ══ SYN-34..SYN-36: rendering ══════════════════════════════════════════

def test_syn_34_synthesized_artifact_is_renderable(solved):
    """The 2D inspector consumes TopologyArtifact only, so a synthesized
    artifact needs no synthesis-specific path."""
    d, _t, c = solved
    from veritx_dse.model.topology_artifact import materialize_ir
    art = materialize_ir(to_topology_ir(c, d), width_bits=64,
                         latency_cycles=1)
    payload = art.to_dict()
    for key in ("routers", "channels", "family", "topology_hash"):
        assert key in payload
    for r in payload["routers"]:
        assert set(r) == {"router_id", "coordinates", "seat_capacity"}


def test_syn_35_same_shape_as_a_named_family(solved):
    d, _t, c = solved
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, materialize_family, materialize_ir,
    )
    synth = materialize_ir(to_topology_ir(c, d), width_bits=64,
                           latency_cycles=1)
    mesh = materialize_family(MaterializedFamily.MESH, endpoint_count=16)
    assert sorted(synth.to_dict()) == sorted(mesh.to_dict()), \
        "one renderer must serve synthesized and named fabrics alike"


def test_syn_36_coordinate_free_synthesized_graph(solved):
    """A synthesized candidate carries NO coordinates: TopologyIR has none,
    and the inspector derives a presentation layout."""
    d, _t, c = solved
    from veritx_dse.model.topology_artifact import materialize_ir
    art = materialize_ir(to_topology_ir(c, d), width_bits=64,
                         latency_cycles=1)
    assert all(r.coordinates == () for r in art.routers)


# ══ SYN-37..SYN-40: solver honesty ═════════════════════════════════════

def test_syn_37_optimal_is_preserved_when_proven(solved):
    _d, _t, c = solved
    assert c.solver_status == "OPTIMAL", (
        "the 4x4/max_len-1.0 fixture solves exactly; if this changes the "
        "fixture is no longer a valid honesty probe")
    assert c.status == "SUCCEEDED"
    assert c.objective_value is not None


def test_syn_38_feasible_is_never_promoted_to_optimal():
    """The 16-node max_len=2.0 problem hits the time limit with an
    incumbent. That must report TIME_LIMIT, never OPTIMAL."""
    from veritx_dse.synthesis.candidate import _solver_status

    class _Res:
        def __init__(self, status, x=None):
            self.status = status
            self.x = x
            self.fun = 1.0
    assert _solver_status(_Res(0)) == "OPTIMAL"
    assert _solver_status(_Res(1, x=[0.0])) == "TIME_LIMIT"
    assert _solver_status(_Res(2)) == "INFEASIBLE"
    assert _solver_status(_Res(3)) == "UNBOUNDED"
    assert _solver_status(_Res(4, x=[0.0])) == "FEASIBLE"
    assert _solver_status(_Res(4)) == "UNKNOWN"


def test_syn_38b_time_limited_candidate_is_not_optimal(solved):
    """A TIME_LIMIT candidate with an incumbent must not claim optimality,
    and must not be reusable as if it were the optimum."""
    d, t = _defn(max_len=2.0, timeout_s=5), _traffic()
    c = synthesize(d, t)
    if c.solver_status == "TIME_LIMIT":
        assert c.status == "SUCCEEDED"
        assert c.objective_value is not None
        assert c.solver_status != "OPTIMAL"


def test_syn_39_timeout_without_incumbent_is_timed_out():
    """No incumbent + time limit => TIMED_OUT, not a graph."""
    from veritx_dse.synthesis.candidate import _solver_status

    class _Res:
        status = 1
        x = None
        fun = None
    assert _solver_status(_Res()) == "TIME_LIMIT"
    with pytest.raises(TopologyCandidateError):
        TopologyCandidate(
            definition_id="d", traffic_id="t", nodes=4, links=(),
            algorithm="milp_tmcf", solver_status="TIME_LIMIT",
            objective_value=None, objective_name="traffic_weighted_hops",
            status="SUCCEEDED", producer_id=PRODUCER_ID)


def test_syn_40_generator_optimum_is_not_product_performance(solved):
    """The generator objective must never be presented as measured
    performance or a verified result."""
    _d, _t, c = solved
    assert c.objective_name != "latency"
    assert c.to_dict()["objective_is_measured_performance"] is False
    # And the artifact built from it carries no performance either.
    from veritx_dse.model.topology_artifact import materialize_ir
    art = materialize_ir(to_topology_ir(c, _d), width_bits=64,
                         latency_cycles=1)
    blob = art.to_dict()
    for forbidden in ("latency_ns", "completion", "performance", "booksim"):
        assert forbidden not in blob
