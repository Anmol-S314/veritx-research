"""PHASE 2 — the optimization capability description is DERIVED, not declared.

The Studio must not hard-code what VERITX can optimize. Every control it
renders comes from a canonical backend authority. These tests fail if the
description ever drifts from those authorities, or if it starts advertising a
value that would deterministically fail downstream.

The central law: a field existing in GUIDED_PARAMS does NOT mean every value
is usable, so `expressible` and `executable` are reported separately.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.capabilities import (  # noqa: E402
    LOCKED_PARAMETERS, optimization_capabilities,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    GUIDED_PARAMS, SELECTION_POLICIES, SEARCH_METHODS, DomainParam, Objective,
    OptimizationDefinition,
)
from veritx_dse.optimization.metric_registry import (  # noqa: E402
    CERTIFIED_METRIC_REGISTRY,
)


@pytest.fixture(scope="module")
def caps():
    return optimization_capabilities()


# ══ derived from authority, not restated ══════════════════════════════

def test_guided_parameters_are_exactly_the_backend_set(caps):
    assert {p["name"] for p in caps["guided_parameters"]} == set(GUIDED_PARAMS)


def test_search_methods_are_exactly_the_backend_set(caps):
    assert caps["search_methods"] == list(SEARCH_METHODS) == \
        ["grid", "enumeration", "random"]


def test_selection_policies_are_exactly_the_backend_set(caps):
    assert caps["selection_policies"] == list(SELECTION_POLICIES) == \
        ["min_first_objective", "lexicographic", "none"]


def test_certified_metrics_are_exactly_the_registry(caps):
    """No invented PPA. The certified set is completion performance only."""
    assert {m["metric"] for m in caps["certified_metrics"]} == \
        set(CERTIFIED_METRIC_REGISTRY.metric_names())
    assert {m["metric"] for m in caps["certified_metrics"]} == \
        {"completion_cycles", "completion_time", "completion_ns"}


def test_every_certified_metric_names_a_real_producer(caps):
    for m in caps["certified_metrics"]:
        assert m["producer_id"], m
        assert m["registry_id"] == CERTIFIED_METRIC_REGISTRY.registry_id()


def test_no_invented_ppa_metric_is_advertised(caps):
    """Area/power/energy/cost/thermal are NOT certified. They may appear only
    in the explicit not-measured list, never as a certifiable objective."""
    certified = {m["metric"] for m in caps["certified_metrics"]}
    for invented in ("area", "power", "energy", "cost", "thermal",
                     "timing_closure"):
        assert invented not in certified
    assert {"area", "power", "energy", "cost", "thermal"} <= \
        set(caps["not_measured"])


# ══ LOCKED properties stay non-searchable ═════════════════════════════

def test_locked_properties_are_named_and_not_guided(caps):
    locked = {p["name"] for p in caps["locked_parameters"]}
    assert "routing_function" in locked
    assert "turn_restrictions" in locked
    assert "vc_map" in locked
    # ...and none of them is offered as a searchable guided parameter.
    assert not (locked & {p["name"] for p in caps["guided_parameters"]})


@pytest.mark.parametrize("locked", ["routing", "vc_count", "escape_vc",
                                    "turn_restrictions"])
def test_a_locked_name_is_refused_by_the_definition(locked):
    """The claim in the capability payload is enforced, not decorative."""
    with pytest.raises(Exception):
        DomainParam(locked, (1,))


# ══ expressible vs executable — the central distinction ═══════════════

def test_topology_family_values_are_materializable_not_merely_authorable(caps):
    """`TopologyFamily` membership means AUTHORABLE. GEC and FAT_TREE are
    members with no materializer, so they must NOT be advertised."""
    from veritx_dse.model.compile_model import TopologyFamily
    param = next(p for p in caps["guided_parameters"]
                 if p["name"] == "topology_family")
    accepted = set(param["accepted_values"])
    assert accepted == {"mesh", "torus", "concentrated_mesh"}
    assert "gec" not in accepted
    assert "fat_tree" not in accepted
    # ...and the refusal is real, not hypothetical: the enum does contain them.
    assert "gec" in {f.value for f in TopologyFamily}


def test_no_advertised_topology_family_is_rejected_by_the_compiler(caps):
    """FAIL CLOSED: a value in the payload must not deterministically fail
    downstream."""
    from veritx_dse.model.compile_model import TopologyFamily
    from veritx_dse.model.topology_artifact import (
        MaterializedFamily, _family_of,
    )
    param = next(p for p in caps["guided_parameters"]
                 if p["name"] == "topology_family")
    for value in param["accepted_values"]:
        resolved = _family_of(_Noc(TopologyFamily(value)))
        assert resolved in MaterializedFamily, value
        assert resolved.value == value, value


class _Noc:
    def __init__(self, topology_family):
        self.topology_family = topology_family


def test_an_unenumerable_domain_reports_None_with_a_reason_not_a_guess(caps):
    """link_width/concentration/radix are validated ranges, not finite
    enumerations. Inventing `[32, 64, 128]` here would be the frontend's
    hard-coded list smuggled into the backend."""
    for name in ("link_width", "concentration", "radix"):
        param = next(p for p in caps["guided_parameters"] if p["name"] == name)
        assert param["accepted_values"] is None
        assert param["value_source"]


def test_every_parameter_declares_its_value_source(caps):
    for p in caps["guided_parameters"]:
        assert p["value_source"], p["name"]
        assert p["kind"] in ("int", "bool", "str", "enum")


# ══ the payload cannot silently drift ═════════════════════════════════

def test_advertised_methods_are_accepted_by_the_definition(caps):
    for method in caps["search_methods"]:
        OptimizationDefinition(
            domain=(DomainParam("link_width", (64,)),),
            objectives=(Objective("completion_cycles", "MIN"),),
            method=method,
            seed=7 if method == "random" else None)


def test_advertised_selection_policies_are_accepted(caps):
    for policy in caps["selection_policies"]:
        assert OptimizationDefinition(
            domain=(DomainParam("link_width", (64,)),),
            objectives=(Objective("completion_cycles", "MIN"),),
            selection=policy).selection == policy


def test_advertised_metrics_are_usable_as_objectives(caps):
    for m in caps["certified_metrics"]:
        d = OptimizationDefinition(
            domain=(DomainParam("link_width", (64,)),),
            objectives=(Objective(m["metric"], "MIN"),))
        assert d.objectives[0].metric == m["metric"]


def test_the_description_is_cache_stable(caps):
    assert optimization_capabilities() is caps


# ══ PHASE 2c — canonical engine order vs presentation order ═══════════

def test_presentation_order_is_numeric_and_canonical_order_is_not():
    from veritx_dse.optimization.capabilities import presentation_order
    assert DomainParam("link_width", (32, 64, 128)).values == (128, 32, 64)
    assert presentation_order([32, 64, 128]) == (32, 64, 128)
    assert presentation_order([8, 16, 4]) == (4, 8, 16)


def test_presentation_order_does_not_alter_definition_identity():
    """The trap: showing 32/64/128 must not change what the study IS."""
    from veritx_dse.optimization.capabilities import presentation_order
    declared = (32, 64, 128)
    shown = presentation_order(declared)
    a = OptimizationDefinition(
        domain=(DomainParam("link_width", declared),),
        objectives=(Objective("completion_cycles", "MIN"),))
    b = OptimizationDefinition(
        domain=(DomainParam("link_width", tuple(reversed(declared))),),
        objectives=(Objective("completion_cycles", "MIN"),))
    assert shown != DomainParam("link_width", declared).values
    assert a.definition_id() == b.definition_id()
    # The engine still enumerates canonically, not numerically.
    assert a.domain[0].values == (128, 32, 64)


def test_presentation_order_does_not_alter_candidate_enumeration():
    from veritx_dse.optimization.capabilities import presentation_order
    from veritx_dse.optimization.search import enumerate_candidates
    d = OptimizationDefinition(
        domain=(DomainParam("link_width", (32, 64, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),))
    base = _base_request()
    canonical = [c.guided_patch["link_width"] for c in enumerate_candidates(base, d)]
    # A UI that displayed numeric order must not change the search order.
    assert presentation_order([32, 64, 128]) == (32, 64, 128)
    assert canonical == [128, 32, 64]


def test_presentation_order_handles_non_numeric_domains():
    from veritx_dse.optimization.capabilities import presentation_order
    assert set(presentation_order(["mesh", "torus"])) == {"mesh", "torus"}
    assert presentation_order([]) == ()


def _base_request():
    """A minimal v3 request so enumeration can be exercised."""
    import json
    from veritx_dse.model.compile_model import CompileRequestV3
    doc = json.loads(
        (DSE.parents[2] / "tracks/t3-topology/examples/"
         "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    return CompileRequestV3.from_dict(doc)


# ══ PHASE 2.1 — capability truth is PROBED, not defaulted ═════════════
#
# The defect this closes: every non-topology parameter was initialized
# `qualified=True` on the strength of "NocConfig accepts this field". That
# conflated EXPRESSIBLE with "the certified backend measures it". Four of the
# eight advertised knobs are not usable as certified optimization dimensions.

def _by_name(caps):
    return {p["name"]: p for p in caps["guided_parameters"]}


def test_expressible_is_not_qualified(caps):
    """(1) An expressible but backend-ineffective field must not be
    advertised as certified."""
    p = _by_name(caps)["arbitration"]
    assert p["expressible"] is True
    assert p["compilable"] is True          # the design does compile
    assert p["effective"] is False          # ...but execution is identical
    assert p["qualified_for_certified_optimization"] is False
    assert "identity-only" in p["reason"]


def test_uncompilable_parameters_are_not_qualified(caps):
    """`rcu_enabled` and the multicast knobs do not merely do nothing —
    a design that sets them FAILS TO COMPILE."""
    by = _by_name(caps)
    for name in ("rcu_enabled", "mcast_groups", "mcast_setup_cycles"):
        p = by[name]
        assert p["expressible"] is True, name
        assert p["compilable"] is False, name
        assert p["qualified_for_certified_optimization"] is False, name
        assert "does not compile" in p["reason"], name


def test_the_unqualified_set_is_explicit(caps):
    assert caps["unqualified_parameters"] == [
        "arbitration", "mcast_groups", "mcast_setup_cycles", "rcu_enabled"]
    assert caps["qualified_parameters"] == [
        "concentration", "link_width", "radix", "topology_family"]


def test_every_qualified_knob_changes_executed_semantics(caps):
    """(4) Every qualified knob must change or participate in canonical
    executed semantics — proven by the probe, not asserted here."""
    from veritx_dse.optimization.capability_probe import probe_parameters
    probes = probe_parameters()
    for name in caps["qualified_parameters"]:
        assert probes[name].effective, name
        assert probes[name].compilable, name
    for name in caps["unqualified_parameters"]:
        assert not probes[name].qualified, name


def test_arbitration_is_identity_only_by_direct_measurement(caps):
    """The strongest form of the claim: compile with two arbitration values
    and compare the CANONICAL ARTIFACT IDENTITIES the certified projection is
    a pure function of. Identical artifacts => identical backend bytes."""
    from veritx_dse.optimization.capability_probe import (
        _artifact_identity, _base_request,
    )
    a, _ = _artifact_identity(_base_request())
    b, _ = _artifact_identity(_base_request(arbitration="round_robin"))
    assert a is not None and b is not None
    assert a == b, ("arbitration changed a projection input — it may now be "
                    "effective, so the capability payload must be updated")


def test_materializable_is_not_backend_executable(caps):
    """(2) The materializer accepting a design does not imply every certified
    projection accepts it: `topology_family` values are the materializable
    subset, and each is separately bounded by the projection's own
    qualification."""
    from veritx_dse.model.compile_model import TopologyFamily
    p = _by_name(caps)["topology_family"]
    assert p["accepted_values_is_exhaustive"] is True
    for value in p["accepted_values"]:
        # materializable ...
        assert value in {f.value for f in TopologyFamily}
    # ...but the mesh-DOR profile pins seat_capacity 1, so a concentrated
    # fabric is NOT executable by that profile even though it materializes.
    assert "concentrated_mesh" in p["accepted_values"]
    assert "concentration" in caps["qualified_parameters"]
    conc = _by_name(caps)["concentration"]
    assert conc["value_constraint"], "the seat constraint must be stated"


def test_an_unenumerated_domain_is_not_all_values(caps):
    """`accepted_values=None` must NOT be readable as 'everything works'."""
    by = _by_name(caps)
    for name in ("link_width", "concentration", "radix"):
        p = by[name]
        assert p["accepted_values"] is None
        assert p["accepted_values_is_exhaustive"] is False
        assert p["value_constraint"]
    # Only the topology domain is exhaustively enumerable.
    exhaustive = [p["name"] for p in caps["guided_parameters"]
                  if p["accepted_values_is_exhaustive"]]
    assert exhaustive == ["topology_family"]


def test_capability_status_comes_from_compiler_authority_not_frontend(caps):
    """(3) The status must be re-derivable from the compiler. Two independent
    computations must agree, so a hand-edited table cannot survive."""
    from veritx_dse.optimization.capability_probe import probe_parameters
    probes = probe_parameters()
    for p in caps["guided_parameters"]:
        if p["name"] not in probes:
            continue
        assert p["compilable"] == probes[p["name"]].compilable
        assert p["effective"] == probes[p["name"]].effective
        assert p["qualified_for_certified_optimization"] == \
            probes[p["name"]].qualified


def test_studio_can_safely_disable_unqualified_capabilities(caps):
    """(5) Every parameter carries enough information to hide or disable it."""
    for p in caps["guided_parameters"]:
        assert isinstance(p["qualified_for_certified_optimization"], bool)
        assert p["reason"] or p["qualified_for_certified_optimization"], (
            f"{p['name']} is unqualified without a reason — Studio could not "
            "explain why it is hidden")
    assert caps["effectiveness_basis"]
    assert caps["multicast_note"]


def test_multicast_qualification_is_not_advertised_globally(caps):
    """Multicast may depend on workload semantics; the payload says so
    instead of advertising the knob as meaningful for every workload."""
    assert "workload" in caps["multicast_note"]
    for name in ("mcast_groups", "mcast_setup_cycles"):
        p = _by_name(caps)[name]
        assert p["qualified_for_certified_optimization"] is False
