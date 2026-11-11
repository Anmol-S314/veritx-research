"""The optional canonical ``traffic_class`` objective/constraint dimension.

An objective may name ONE canonical traffic class to read a per-class
metric. The dimension is a SELECTOR into the per-class metric surface, not
a free-form label, and it is entirely optional: a definition written before
the dimension existed keeps its exact identity payload, its ``definition_id``
and its ``to_dict`` bytes.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization import definition as definition_mod  # noqa: E402
from veritx_dse.optimization.definition import (  # noqa: E402
    Constraint, DomainParam, Objective, ObjectiveSource,
    OptimizationDefinition, OptimizationDefinitionError,
)


def _legacy_definition():
    return OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),),
        constraints=(Constraint("completion_cycles", "<=", 1000),),
        method="grid")


def _classed_definition():
    return OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("flits_injected", "MIN",
                              traffic_class="tp_collective"),),
        constraints=(Constraint("flits_accepted", ">=", 10,
                                traffic_class="dp_collective"),),
        method="grid")


def test_optional_class_defaults_to_the_aggregate_axis():
    """A bare objective/constraint is the aggregate objective it always was."""
    objective = Objective("completion_cycles", "MIN")
    assert objective.traffic_class is None
    assert objective.source.traffic_class is None
    assert objective.source.to_dict() == {
        "metric_key": "completion_cycles",
        "question": "NETWORK_COMPLETION",
        "backend_id": None}
    constraint = Constraint("completion_cycles", "<=", 10)
    assert constraint.traffic_class is None
    assert ObjectiveSource("completion_cycles").traffic_class is None


def test_legacy_serialization_keeps_the_historical_key_set():
    """An aggregate objective/constraint emits NO ``traffic_class`` key —
    the persisted bytes of a pre-dimension definition do not move."""
    doc = _legacy_definition().to_dict()
    assert doc["objectives"] == [{
        "metric": "completion_cycles", "direction": "MIN",
        "question": "NETWORK_COMPLETION", "backend_id": None}]
    assert doc["constraints"] == [{
        "metric": "completion_cycles", "op": "<=", "threshold": 1000.0}]
    assert "traffic_class" not in json.dumps(doc)


def test_legacy_identity_payload_is_byte_compatible(monkeypatch):
    """THE byte-compat proof: capture the exact ``definition_id`` payload.

    Without a traffic class the payload carries no new key in ANY nested
    document, so the content identity of an existing definition is
    unchanged (not merely 'close').
    """
    captured = {}

    def _capture(domain, payload):
        captured["domain"] = domain
        captured["payload"] = payload
        return "sha256:" + "0" * 64

    monkeypatch.setattr(definition_mod, "content_id", _capture)
    _legacy_definition().definition_id()
    payload = captured["payload"]
    assert "traffic_class" not in json.dumps(payload)
    # And the domain is untouched: no schema bump was smuggled in.
    assert captured["domain"] == definition_mod.DOMAIN


def test_optional_class_serializes_and_moves_identity():
    legacy = _legacy_definition()
    classed = _classed_definition()
    objective_doc = classed.to_dict()["objectives"][0]
    assert objective_doc["traffic_class"] == "tp_collective"
    assert objective_doc["metric"] == "flits_injected"
    constraint_doc = classed.to_dict()["constraints"][0]
    assert constraint_doc["traffic_class"] == "dp_collective"
    assert classed.definition_id() != legacy.definition_id()

    plain = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("flits_injected", "MIN"),),
        method="grid")
    assert plain.definition_id() != classed.definition_id()


def test_objective_source_carries_the_class():
    objective = Objective("flits_injected", "MIN",
                          traffic_class="tp_collective")
    source = objective.source
    assert isinstance(source, ObjectiveSource)
    assert source.traffic_class == "tp_collective"
    assert source.to_dict() == {
        "metric_key": "flits_injected",
        "question": "NETWORK_COMPLETION",
        "backend_id": None,
        "traffic_class": "tp_collective"}


@pytest.mark.parametrize("bad", ["", "   ", " tp_collective",
                                 "tp_collective ", 7, True, ["tp"]])
def test_a_non_canonical_class_is_refused(bad):
    with pytest.raises(OptimizationDefinitionError, match="traffic_class"):
        Objective("flits_injected", "MIN", traffic_class=bad)
    with pytest.raises(OptimizationDefinitionError, match="traffic_class"):
        Constraint("flits_injected", "<=", 1, traffic_class=bad)
    with pytest.raises(OptimizationDefinitionError, match="traffic_class"):
        ObjectiveSource("flits_injected", traffic_class=bad)


def test_two_classes_of_one_metric_are_distinct_axes():
    """Two per-class objectives/constraints over one metric coexist.

    The value axis is ``(metric, traffic_class)``, not the metric NAME:
    each class owns an independent reading, so the definition no longer
    treats the pair as a duplicate. The same axis declared twice is still
    refused, because it would occupy one map slot.
    """
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(
            Objective("flits_injected", "MIN",
                      traffic_class="tp_collective"),
            Objective("flits_injected", "MAX",
                      traffic_class="dp_collective")),
        constraints=(
            Constraint("flits_accepted", "<=", 10,
                       traffic_class="tp_collective"),
            Constraint("flits_accepted", ">=", 1,
                       traffic_class="dp_collective")),
        method="grid")
    assert [o.key for o in definition.objectives] == [
        "flits_injected@traffic_class=tp_collective",
        "flits_injected@traffic_class=dp_collective"]
    assert [c.key for c in definition.constraints] == [
        "flits_accepted@traffic_class=tp_collective",
        "flits_accepted@traffic_class=dp_collective"]

    with pytest.raises(OptimizationDefinitionError, match="duplicate"):
        OptimizationDefinition(
            domain=(DomainParam("link_width", (64, 128)),),
            objectives=(
                Objective("flits_injected", "MIN",
                          traffic_class="tp_collective"),
                Objective("flits_injected", "MAX",
                          traffic_class="tp_collective")),
            method="grid")
    with pytest.raises(OptimizationDefinitionError, match="duplicate"):
        OptimizationDefinition(
            domain=(DomainParam("link_width", (64, 128)),),
            objectives=(Objective("completion_cycles", "MIN"),),
            constraints=(
                Constraint("flits_accepted", "<=", 10,
                           traffic_class="tp_collective"),
                Constraint("flits_accepted", ">=", 1,
                           traffic_class="tp_collective")),
            method="grid")
