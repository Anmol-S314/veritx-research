"""The composite ``(metric, traffic_class)`` optimization-axis identity.

Two per-class objectives or constraints may now share one metric NAME
because their value axis is ``(metric, traffic_class)``, not the metric
name alone. The stable map key is

    <metric>@traffic_class=<class>

while an aggregate axis keeps the historical bare metric name. This file
pins the whole chain: definition identity/serialization, evaluation,
constraint verdicts, provenance, Pareto input, the v2 study view, and the
byte-compatible aggregate (plus lossy v1) projections.
"""
from __future__ import annotations

import dataclasses
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_p2_real_adapter import _base as _real_base  # noqa: E402

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BOOKSIM_MODEL_FIDELITY,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    Constraint, DomainParam, Objective, OptimizationDefinition,
    metric_axis_key,
)
from veritx_dse.optimization.evaluators import (  # noqa: E402
    AUTHORITY_ANALYTIC_FAKE, CandidateEvaluation, ObjectiveProvenance,
)
from veritx_dse.optimization.result import Optimizer  # noqa: E402

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
DIGEST = "sha256:" + "0" * 64
NATIVE = "native-class-axis-1"

EP = "packet_latency_avg@traffic_class=ep_dispatch"
TP = "packet_latency_avg@traffic_class=tp_collective"


def _definition(objectives, constraints=()):
    return OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=tuple(objectives), constraints=tuple(constraints),
        method="grid")


def _two_class_objectives():
    return _definition((
        Objective("packet_latency_avg", "MIN",
                  traffic_class="ep_dispatch"),
        Objective("packet_latency_avg", "MIN",
                  traffic_class="tp_collective")))


def test_the_axis_key_format_keeps_the_aggregate_bare():
    assert metric_axis_key("completion_cycles") == "completion_cycles"
    assert metric_axis_key(
        "packet_latency_avg", "ep_dispatch") == EP
    assert Objective("completion_cycles", "MIN").key == "completion_cycles"
    assert Constraint("completion_cycles", "<=", 1).key == \
        "completion_cycles"
    assert Objective(
        "packet_latency_avg", "MIN",
        traffic_class="ep_dispatch").key == EP
    assert Constraint(
        "packet_latency_avg", "<=", 1,
        traffic_class="tp_collective").key == TP


def test_two_class_objectives_survive_identity_and_serialization():
    both = _two_class_objectives()
    ep_only = _definition((Objective(
        "packet_latency_avg", "MIN", traffic_class="ep_dispatch"),))
    tp_only = _definition((Objective(
        "packet_latency_avg", "MIN", traffic_class="tp_collective"),))
    aggregate = _definition((Objective(
        "packet_latency_avg", "MIN"),))

    ids = {both.definition_id(), ep_only.definition_id(),
           tp_only.definition_id(), aggregate.definition_id()}
    assert len(ids) == 4, "class-scoped identities collided"

    doc = both.to_dict()
    assert [o["metric"] for o in doc["objectives"]] == [
        "packet_latency_avg", "packet_latency_avg"]
    assert [o["traffic_class"] for o in doc["objectives"]] == [
        "ep_dispatch", "tp_collective"]
    # The serialization is declaration-ordered and carries no invented
    # key: the selector plus the metric already is the identity.
    assert "key" not in json.dumps(doc)

    view = _two_class_objectives_view()
    assert [o["key"] for o in view["definition"]["objectives"]] == [EP, TP]


def _two_class_objectives_view():
    return Optimizer().optimize_with_port(
        _real_base(), _two_class_objectives(), _FixedPort()
    ).to_study_view()


class _FixedPort:
    def evaluate(self, candidate):
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={EP: 10.0, TP: 20.0},
            locked_consequences={},
            evaluation_authority=AUTHORITY_ANALYTIC_FAKE)


def test_repeated_metric_with_the_same_class_is_still_refused():
    from veritx_dse.optimization.definition import (
        OptimizationDefinitionError,
    )
    with pytest.raises(OptimizationDefinitionError, match="duplicate"):
        _definition((
            Objective("packet_latency_avg", "MIN",
                      traffic_class="ep_dispatch"),
            Objective("packet_latency_avg", "MAX",
                      traffic_class="ep_dispatch")))
    with pytest.raises(OptimizationDefinitionError, match="duplicate"):
        _definition(
            (Objective("packet_latency_avg", "MIN"),),
            constraints=(
                Constraint("packet_latency_avg", "<=", 10,
                           traffic_class="ep_dispatch"),
                Constraint("packet_latency_avg", ">=", 1,
                           traffic_class="ep_dispatch")))


def _dimensioned(metric, traffic_class, value):
    return MetricValue(
        key=metric, value=value, unit=None, source_metric_key=None,
        dimensions=(("traffic_class", traffic_class),))


def _analysis(*rows):
    envelope = NormalizedBackendEvidence(
        backend_id="BOOKSIM_STANDALONE", question=NETWORK,
        model_fidelity=BOOKSIM_MODEL_FIDELITY,
        canonical_parent_ids=(DIGEST,),
        native_evidence_id=NATIVE, qualification="QUALIFIED",
        producer_identity=DIGEST, metrics=tuple(rows))
    return SimpleNamespace(
        question=NETWORK, status="EVALUATED", reason=None,
        backend_id="BOOKSIM_STANDALONE",
        model_fidelity=BOOKSIM_MODEL_FIDELITY,
        qualification="QUALIFIED", native_evidence_id=NATIVE,
        normalized_evidence=envelope)


def _provenance(value):
    return ObjectiveProvenance(
        metric_key="packet_latency_avg", question=NETWORK,
        backend_id="BOOKSIM_STANDALONE",
        model_fidelity=BOOKSIM_MODEL_FIDELITY.value,
        qualification="QUALIFIED", native_evidence_id=NATIVE,
        unit=None, value=value)


def test_the_real_evaluator_binds_two_classes_of_one_metric(tmp_path):
    from veritx_dse.optimization.real_evaluator import (
        RealCandidateEvaluator,
    )
    objectives = (
        Objective("packet_latency_avg", "MIN",
                  traffic_class="ep_dispatch"),
        Objective("packet_latency_avg", "MIN",
                  traffic_class="tp_collective"))
    evaluator = RealCandidateEvaluator(
        binary="/bin/true", run_root=tmp_path, objectives=objectives)
    values, provenance, miss = evaluator._bind_federated_objectives({
        NETWORK: _analysis(
            _dimensioned("packet_latency_avg", "ep_dispatch", 10.0),
            _dimensioned("packet_latency_avg", "tp_collective", 20.0))})
    assert values == {EP: 10.0, TP: 20.0}
    assert set(provenance) == {EP, TP}
    assert miss == {}


class _TwoClassCertifiedPort:
    """Certified double: both class axes move in opposite directions."""

    def evaluate(self, candidate):
        from p2_verified_support import certified_evaluation
        width = candidate.guided_patch["link_width"]
        ep = 10.0 if width == 64 else 200.0
        tp = 200.0 if width == 64 else 10.0
        evaluation = certified_evaluation(
            candidate, cycles=100,
            objective_values={EP: ep, TP: tp})
        return dataclasses.replace(
            evaluation,
            federated_analyses=(_analysis(
                _dimensioned("packet_latency_avg", "ep_dispatch", ep),
                _dimensioned("packet_latency_avg", "tp_collective", tp)),),
            objective_provenance={EP: _provenance(ep),
                                  TP: _provenance(tp)})


def test_two_class_objectives_reach_evaluation_provenance_and_pareto():
    result = Optimizer()._optimize_core(
        _real_base(), _two_class_objectives(),
        _TwoClassCertifiedPort(), accept_certified_claims=True)

    assert len(result.records) == 2
    for record in result.records:
        assert set(record.objective_values) == {EP, TP}
        assert record.objective_availability == {
            EP: "MEASURED", TP: "MEASURED"}
        assert record.pareto_eligible is True
        assert record.eligibility_reason is None
        rows = {row["metric_key"]: row
                for row in record.objective_provenance}
        # One bare metric, two distinguishable class rows.
        assert set(rows) == {"packet_latency_avg"}
        assert {row["traffic_class"]
                for row in record.objective_provenance} == {
            "ep_dispatch", "tp_collective"}

    # Width 64 wins on ep and loses on tp; width 128 is the mirror image.
    # A metric-name-only Pareto input would keep exactly one of them.
    assert len(result.pareto_ids) == 2
    assert len(set(result.pareto_ids)) == 2
    assert result.selected_candidate_id in result.pareto_ids

    view = result.to_study_view()
    assert [o["key"] for o in view["definition"]["objectives"]] == [EP, TP]
    for candidate in view["candidates"]:
        assert set(candidate["objective_values"]) == {EP, TP}
        assert {row["traffic_class"]
                for row in candidate["objective_provenance"]} == {
            "ep_dispatch", "tp_collective"}
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (DSE.parent.parent.parent / "contracts" / "srota" / "v2" /
         "optimization.study.view.schema.json").read_text())
    jsonschema.validate(view, schema)


class _TwoClassConstraintPort:
    """Analytic double with independent per-class counter readings."""

    def evaluate(self, candidate):
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={"completion_cycles": 100.0},
            locked_consequences={},
            evaluation_authority=AUTHORITY_ANALYTIC_FAKE,
            federated_analyses=(_analysis(
                _dimensioned("flits_accepted", "ep_dispatch", 50.0),
                _dimensioned("flits_accepted", "tp_collective", 500.0)),))


def test_two_class_constraints_get_independent_verdicts():
    ep_constraint = "flits_accepted@traffic_class=ep_dispatch"
    tp_constraint = "flits_accepted@traffic_class=tp_collective"
    definition = _definition(
        (Objective("completion_cycles", "MIN"),),
        constraints=(
            Constraint("flits_accepted", ">=", 10,
                       traffic_class="ep_dispatch"),
            Constraint("flits_accepted", "<=", 100,
                       traffic_class="tp_collective")))

    result = Optimizer().optimize_with_port(
        _real_base(), definition, _TwoClassConstraintPort())
    record = result.records[0]
    assert record.constraints_satisfied is False
    assert record.constraint_verdicts == {
        ep_constraint: "SATISFIED",
        tp_constraint: "VIOLATED"}
    details = {row.get("traffic_class"): row
               for row in record.constraint_details}
    assert details["ep_dispatch"]["metric"] == "flits_accepted"
    assert details["ep_dispatch"]["measured"] == 50.0
    assert details["ep_dispatch"]["verdict"] == "SATISFIED"
    assert details["tp_collective"]["measured"] == 500.0
    assert details["tp_collective"]["verdict"] == "VIOLATED"

    view = result.to_study_view()
    assert view["candidates"][0]["constraint_verdicts"] == {
        ep_constraint: "SATISFIED",
        tp_constraint: "VIOLATED"}


def test_the_product_parser_accepts_two_classes_of_one_metric():
    from veritx_dse.product.service import ProductService

    def _body():
        return {
            "domain": [{"name": "link_width", "values": [64]}],
            "objectives": [
                {"metric": "packet_latency_avg", "direction": "MIN",
                 "traffic_class": "ep_dispatch"},
                {"metric": "packet_latency_avg", "direction": "MIN",
                 "traffic_class": "tp_collective"}],
            "constraints": [
                {"metric": "packet_latency_avg", "op": "<=",
                 "threshold": 10, "traffic_class": "ep_dispatch"},
                {"metric": "packet_latency_avg", "op": "<=",
                 "threshold": 20, "traffic_class": "tp_collective"}],
            "method": "grid",
        }

    doc = ProductService._parse_definition(_body())
    assert [o["traffic_class"] for o in doc["objectives"]] == [
        "ep_dispatch", "tp_collective"]
    assert [c["traffic_class"] for c in doc["constraints"]] == [
        "ep_dispatch", "tp_collective"]
    definition = OptimizationDefinition(
        domain=tuple(DomainParam(d["name"], tuple(d["values"]))
                     for d in doc["domain"]),
        objectives=tuple(Objective(
            o["metric"], o["direction"],
            question=o.get("question") or "NETWORK_COMPLETION",
            backend_id=o.get("backend_id"),
            traffic_class=o.get("traffic_class"))
            for o in doc["objectives"]),
        constraints=tuple(Constraint(
            c["metric"], c["op"], c["threshold"],
            traffic_class=c.get("traffic_class"))
            for c in doc["constraints"]),
        method=doc["method"], budget=doc["budget"], seed=doc["seed"],
        selection=doc["selection"])
    assert [o.key for o in definition.objectives] == [EP, TP]

    body = _body()
    body["objectives"][1]["traffic_class"] = "ep_dispatch"
    with pytest.raises(Exception, match="duplicate optimization objective"):
        ProductService._parse_definition(body)


def test_aggregate_definition_and_v1_output_stay_byte_compatible():
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64,)),),
        objectives=(Objective("completion_cycles", "MIN"),),
        constraints=(Constraint("completion_cycles", "<=", 1000),),
        method="grid")
    assert definition.to_dict()["objectives"] == [{
        "metric": "completion_cycles", "direction": "MIN",
        "question": "NETWORK_COMPLETION", "backend_id": None}]
    assert definition.to_dict()["constraints"] == [{
        "metric": "completion_cycles", "op": "<=", "threshold": 1000.0}]

    class _Port(_FixedPort):
        def evaluate(self, candidate):
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                design_hash=candidate.request.design_hash(),
                status="EVALUATED",
                objective_values={"completion_cycles": 500.0},
                locked_consequences={},
                evaluation_authority=AUTHORITY_ANALYTIC_FAKE)

    result = Optimizer().optimize_with_port(
        _real_base(), definition, _Port())
    v2 = result.to_study_view()
    assert v2["definition"]["objectives"] == [{
        "metric": "completion_cycles", "direction": "MIN",
        "question": "NETWORK_COMPLETION", "backend_id": None}]
    assert v2["definition"]["constraints"] == [{
        "metric": "completion_cycles", "op": "<=", "threshold": 1000.0}]
    for candidate in v2["candidates"]:
        assert set(candidate["objective_values"]) == {"completion_cycles"}
        assert set(candidate["constraint_verdicts"]) == {
            "completion_cycles"}
    assert "traffic_class" not in json.dumps(v2["definition"])
    assert "@traffic_class=" not in json.dumps(v2)

    v1 = result.to_study_view(contract_version=1)
    assert v1["definition"]["objectives"] == ["completion_cycles"]
    assert v1["definition"]["constraints"] == ["completion_cycles<=1000"]
    for candidate in v1["candidates"]:
        assert set(candidate["objective_values"]) == {"completion_cycles"}
        assert candidate["constraint_verdicts"] == {
            "completion_cycles": True}
