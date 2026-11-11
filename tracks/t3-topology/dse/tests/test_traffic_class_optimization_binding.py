"""Per-class objectives and constraints through the optimizer result surface.

The definition already carries the optional ``traffic_class`` selector. These
tests pin the rest of the chain: the real evaluator reads the dimensioned
envelope row, the optimizer resolves a class-scoped constraint from that same
row, and the v2 study view (plus its schema) exposes the selector while the
v1 lossy view stays unchanged.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BOOKSIM_MODEL_FIDELITY,
)
from veritx_dse.backend.normalized_evidence import (  # noqa: E402
    MetricValue, NormalizedBackendEvidence,
)
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.model.compile_model import CompileRequestV3  # noqa: E402
from veritx_dse.optimization.definition import (  # noqa: E402
    Constraint, DomainParam, Objective, OptimizationDefinition,
)
from veritx_dse.optimization.evaluators import (  # noqa: E402
    AUTHORITY_ANALYTIC_FAKE, CandidateEvaluation,
)
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    RealCandidateEvaluator,
)
from veritx_dse.optimization.result import Optimizer  # noqa: E402

NETWORK = EvaluationQuestion.NETWORK_COMPLETION
DIGEST = "sha256:" + "0" * 64
NATIVE = "native-bx-1"


def _envelope(*rows: MetricValue) -> NormalizedBackendEvidence:
    return NormalizedBackendEvidence(
        backend_id="BOOKSIM_STANDALONE", question=NETWORK,
        model_fidelity=BOOKSIM_MODEL_FIDELITY,
        canonical_parent_ids=(DIGEST,),
        native_evidence_id=NATIVE, qualification="QUALIFIED",
        producer_identity=DIGEST, metrics=tuple(rows))


def _dimensioned(metric: str, traffic_class: str,
                 value: float) -> MetricValue:
    return MetricValue(
        key=metric, value=value, unit=None, source_metric_key=None,
        dimensions=(("traffic_class", traffic_class),))


def _analysis(envelope: NormalizedBackendEvidence) -> SimpleNamespace:
    return SimpleNamespace(
        question=NETWORK, status="EVALUATED", reason=None,
        backend_id="BOOKSIM_STANDALONE",
        model_fidelity=BOOKSIM_MODEL_FIDELITY,
        qualification="QUALIFIED", native_evidence_id=NATIVE,
        normalized_evidence=envelope)


def _base_request() -> CompileRequestV3:
    doc = json.loads(
        (REPO / "tracks/t3-topology/examples/"
         "dense_tp2dp2_4tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    return CompileRequestV3.from_dict(doc)


def test_the_real_evaluator_binds_a_per_class_network_reading(tmp_path):
    aggregate = Objective("completion_cycles", "MIN")
    latency = Objective("packet_latency_avg", "MIN",
                        traffic_class="a0")
    missing = Objective("p50", "MIN", traffic_class="b0")
    evaluator = RealCandidateEvaluator(
        binary="/bin/true", run_root=tmp_path,
        objectives=(aggregate, latency, missing))
    envelope = _envelope(
        MetricValue(key="completion_cycles", value=100.0, unit=None,
                    source_metric_key="completion_cycles"),
        _dimensioned("packet_latency_avg", "a0", 10.0))
    values, provenance, miss = evaluator._bind_federated_objectives(
        {NETWORK: _analysis(envelope)})
    latency_key = "packet_latency_avg@traffic_class=a0"
    assert values == {latency_key: 10.0}
    assert provenance[latency_key].native_evidence_id == NATIVE
    # The aggregate completion objective keeps the proof authority; it is
    # never read from the envelope here.
    assert "completion_cycles" not in values
    # A class the evidence does not carry is absent, never zero.
    assert "p50@traffic_class=b0" not in values
    assert "traffic class 'b0'" in miss["p50@traffic_class=b0"]


def test_a_class_objective_with_only_an_aggregate_row_is_unmeasured(tmp_path):
    objective = Objective("packet_latency_avg", "MIN",
                          traffic_class="a0")
    evaluator = RealCandidateEvaluator(
        binary="/bin/true", run_root=tmp_path, objectives=(objective,))
    envelope = _envelope(MetricValue(
        key="packet_latency_avg", value=10.0, unit=None,
        source_metric_key="packet_latency_avg"))
    values, _provenance, miss = evaluator._bind_federated_objectives(
        {NETWORK: _analysis(envelope)})
    assert values == {}
    assert "only as an aggregate" in miss[
        "packet_latency_avg@traffic_class=a0"]


class _PerClassPort:
    def evaluate(self, candidate):
        envelope = _envelope(
            _dimensioned("flits_injected", "a0", 100.0),
            _dimensioned("flits_accepted", "b0", 5.0))
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={
                "flits_injected@traffic_class=a0": 100.0},
            locked_consequences={},
            evaluation_authority=AUTHORITY_ANALYTIC_FAKE,
            federated_analyses=(_analysis(envelope),))


def _classed_definition() -> OptimizationDefinition:
    return OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("flits_injected", "MIN",
                              traffic_class="a0"),),
        constraints=(Constraint("flits_accepted", ">=", 10,
                                traffic_class="b0"),),
        method="grid")


def test_a_per_class_constraint_reads_its_own_class_not_the_objective():
    objective_key = "flits_injected@traffic_class=a0"
    constraint_key = "flits_accepted@traffic_class=b0"
    result = Optimizer().optimize_with_port(
        _base_request(), _classed_definition(), _PerClassPort())
    assert len(result.records) == 2
    for record in result.records:
        assert record.objective_values[objective_key] == 100.0
        assert record.objective_availability[objective_key] == "MEASURED"
        # The objective's a0 reading is 100; the b0 constraint value is 5.
        # A metric-key-only resolver would wrongly pass it.
        assert record.constraint_verdicts[constraint_key] == "VIOLATED"
        assert record.constraint_details[0]["metric"] == "flits_accepted"
        assert record.constraint_details[0]["traffic_class"] == "b0"
        assert record.constraint_details[0]["measured"] == 5.0

    view = result.to_study_view()
    assert view["definition"]["objectives"] == [{
        "metric": "flits_injected", "direction": "MIN",
        "question": "NETWORK_COMPLETION", "backend_id": None,
        "traffic_class": "a0", "key": objective_key}]
    assert view["definition"]["constraints"] == [{
        "metric": "flits_accepted", "op": ">=", "threshold": 10.0,
        "traffic_class": "b0", "key": constraint_key}]
    for candidate in view["candidates"]:
        assert candidate["constraint_verdicts"] == {
            constraint_key: "VIOLATED"}
        assert candidate["objective_values"] == {objective_key: 100.0}
    jsonschema = pytest.importorskip("jsonschema")
    schema = json.loads(
        (DSE.parent.parent.parent / "contracts" / "srota" / "v2" /
         "optimization.study.view.schema.json").read_text())
    jsonschema.validate(view, schema)


def test_the_product_parser_accepts_the_optional_class_selector():
    from veritx_dse.product.service import ProductService

    doc = ProductService._parse_definition({
        "domain": [{"name": "link_width", "values": [64]}],
        "objectives": [{"metric": "packet_latency_avg", "direction": "MIN",
                        "traffic_class": "a0"}],
        "constraints": [{"metric": "flits_accepted", "op": ">=",
                         "threshold": 10, "traffic_class": "b0"}],
        "method": "grid",
    })
    assert doc["objectives"][0]["traffic_class"] == "a0"
    assert doc["constraints"][0]["traffic_class"] == "b0"
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
    assert definition.objectives[0].traffic_class == "a0"
    assert definition.constraints[0].traffic_class == "b0"

    plain = ProductService._parse_definition({
        "domain": [{"name": "link_width", "values": [64]}],
        "objectives": [{"metric": "flits_injected", "direction": "MIN"}],
        "method": "grid",
    })
    assert "traffic_class" not in plain["objectives"][0]


def test_an_aggregate_definition_stays_byte_identical_and_v1_is_lossy():
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64,)),),
        objectives=(Objective("flits_injected", "MIN"),),
        constraints=(Constraint("flits_accepted", ">=", 10),),
        method="grid")

    class _Port(_PerClassPort):
        def evaluate(self, candidate):
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                design_hash=candidate.request.design_hash(),
                status="EVALUATED",
                objective_values={"flits_injected": 100.0,
                                  "flits_accepted": 20.0},
                locked_consequences={},
                evaluation_authority=AUTHORITY_ANALYTIC_FAKE)

    result = Optimizer().optimize_with_port(
        _base_request(), definition, _Port())
    v2 = result.to_study_view()
    assert v2["definition"]["objectives"] == [{
        "metric": "flits_injected", "direction": "MIN",
        "question": "NETWORK_COMPLETION", "backend_id": None}]
    assert v2["definition"]["constraints"] == [{
        "metric": "flits_accepted", "op": ">=", "threshold": 10.0}]
    assert "traffic_class" not in json.dumps(v2["definition"])

    v1 = result.to_study_view(contract_version=1)
    assert v1["definition"]["constraints"] == ["flits_accepted>=10"]
    assert "traffic_class" not in json.dumps(v1["definition"])
