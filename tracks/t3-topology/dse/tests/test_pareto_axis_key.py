"""Direct Pareto callers read the composite ``(metric, traffic_class)`` axis.

The optimizer projects objective keys before calling ``pareto_ids``; these
tests pin the same contract for external callers that pass ``Objective``
objects (or raw objective mappings) straight to ``optimization.pareto``.
Aggregate axes keep the historical bare metric key, and a missing class
value refuses instead of silently reading the bare metric.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.comparison import ComparisonSpecError  # noqa: E402
from veritx_dse.optimization.definition import (  # noqa: E402
    Objective,
    metric_axis_key,
)
from veritx_dse.optimization.pareto import (  # noqa: E402
    pareto_ids,
    pareto_with_sealed_gate,
)

BARE = "packet_latency_avg"
EP = metric_axis_key(BARE, "ep_dispatch")
TP = metric_axis_key(BARE, "tp_collective")


def _two_class_objectives():
    return (
        Objective(BARE, "MIN", traffic_class="ep_dispatch"),
        Objective(BARE, "MIN", traffic_class="tp_collective"),
    )


def test_two_class_objectives_are_independent_axes_for_direct_callers():
    values = {
        "ep_first": {EP: 10.0, TP: 200.0},
        "tp_first": {EP: 200.0, TP: 10.0},
        "dominated": {EP: 200.0, TP: 200.0},
    }
    assert set(pareto_ids(values, _two_class_objectives())) == {
        "ep_first", "tp_first"}
    # One candidate still reads both class axes from the same value map.
    assert pareto_ids({"only": {EP: 10.0, TP: 20.0}},
                      _two_class_objectives()) == ("only",)


def test_aggregate_objective_is_unchanged():
    objective = Objective("completion_cycles", "MIN")
    assert objective.key == "completion_cycles"
    assert pareto_ids(
        {"a": {"completion_cycles": 5.0},
         "b": {"completion_cycles": 5.0},
         "c": {"completion_cycles": 6.0}},
        (objective,)) == ("a", "b")


def test_projected_axis_mappings_still_read_their_metric_slot():
    projected = ({"metric": EP, "direction": "MIN"},
                 {"metric": TP, "direction": "MIN"})
    values = {"a": {EP: 1.0, TP: 5.0}, "b": {EP: 5.0, TP: 1.0}}
    assert set(pareto_ids(values, projected)) == {"a", "b"}


def test_raw_objective_mapping_with_traffic_class_reads_composite_axis():
    objective = {"metric": BARE, "direction": "MIN",
                 "traffic_class": "ep_dispatch"}
    assert pareto_ids({"a": {EP: 1.0}, "b": {EP: 2.0}},
                      (objective,)) == ("a",)


def test_missing_class_value_refuses_instead_of_reading_the_bare_metric():
    objective = Objective(BARE, "MIN", traffic_class="ep_dispatch")
    # The bare aggregate reading is present, but it is NOT the class axis.
    with pytest.raises(KeyError):
        pareto_ids({"a": {BARE: 1.0}}, (objective,))
    with pytest.raises(KeyError):
        pareto_ids({"a": {TP: 1.0}}, (objective,))


def test_present_class_value_wins_over_the_bare_aggregate_value():
    objective = Objective(BARE, "MIN", traffic_class="ep_dispatch")
    # Reading the bare value would make "bare_low" win; the class axis
    # makes "class_low" win.
    values = {"class_low": {BARE: 999.0, EP: 1.0},
              "bare_low": {BARE: 0.0, EP: 2.0}}
    assert pareto_ids(values, (objective,)) == ("class_low",)
    checked = pareto_with_sealed_gate(
        values, (objective,), {k: "QUALIFIED" for k in values})
    assert checked["front"] == ("class_low",)
    assert checked["scope"]["front"] == ["class_low"]


def test_declared_empty_key_refuses_instead_of_falling_back():
    from types import SimpleNamespace
    objective = SimpleNamespace(metric=BARE, key=None, direction="MIN")
    with pytest.raises(ValueError):
        pareto_ids({"a": {BARE: 1.0}}, (objective,))


def test_sealed_gate_accepts_two_classes_of_one_metric():
    values = {
        "ep_first": {EP: 10.0, TP: 200.0},
        "tp_first": {EP: 200.0, TP: 10.0},
        "dominated": {EP: 200.0, TP: 200.0},
    }
    checked = pareto_with_sealed_gate(
        values, _two_class_objectives(),
        {k: "QUALIFIED" for k in values})
    assert set(checked["front"]) == {"ep_first", "tp_first"}
    assert set(checked["scope"]["front"]) == set(checked["front"])
    assert checked["scope"]["objectives"] == [EP, TP]
    assert checked["scope"]["excluded"] == []


def test_sealed_gate_missing_class_value_refuses():
    objective = Objective(BARE, "MIN", traffic_class="ep_dispatch")
    with pytest.raises(KeyError):
        pareto_with_sealed_gate(
            {"a": {BARE: 1.0}}, (objective,), {"a": "QUALIFIED"})


def test_sealed_gate_keeps_missing_and_mixed_fidelity_refusals():
    objective = Objective(BARE, "MIN")
    values = {"a": {BARE: 1.0}, "b": {BARE: 2.0}}
    with pytest.raises(ComparisonSpecError, match="no fidelity"):
        pareto_with_sealed_gate(values, (objective,), {"a": "QUALIFIED"})
    with pytest.raises(ComparisonSpecError, match="mixed fidelities"):
        pareto_with_sealed_gate(
            values, (objective,),
            {"a": "QUALIFIED", "b": "DIAGNOSTIC"})
