"""Per-class BookSim metrics: measured, named, and bindable.

BookSim standalone emits ``stats.flits_by_class`` keyed by trace class
INDEX and the fork's ``DisplayStats`` prints per-class latency inside each
``Class N:`` block. The canonical class NAME comes from
``PreparedBookSimInput.trace_class_map``. Normalization projects only the
readings the fork actually measured — flit counters and the latency fields
present in each class block — as dimensioned readings, and a per-class
objective/constraint binds through ``Objective.traffic_class``.

For a multi-class run the historical scalar latency keys match the FIRST
(``Class 0``) block, not an aggregate; normalization suppresses those
scalars and keeps only the per-class readings.
"""
from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from tools.sweep_intent_knobs import baseline  # noqa: E402
from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.fabric_evaluator import EvaluationOutcome  # noqa: E402
from veritx_dse.backend.adapter import PreparedExecution  # noqa: E402
from veritx_dse.backend.booksim_adapter import (  # noqa: E402
    BookSimAdapter, BookSimExecutionResult, _per_class_metric_values,
    normalize_booksim_outcome,
)
from veritx_dse.backend.booksim_execution import (  # noqa: E402
    parse_booksim_stats,
)
from veritx_dse.backend.evidence import (  # noqa: E402
    BOOKSIM_BUILD_RECIPE_VERSION, PARSER_VERSION,
    ScientificBackendEvidence,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4  # noqa: E402
from veritx_dse.optimization.definition import (  # noqa: E402
    Constraint, Objective,
)
from veritx_dse.optimization.metric_registry import (  # noqa: E402
    BOOKSIM_PER_CLASS_METRICS, MetricRegistryError,
    bind_traffic_class_metric, federated_metric_catalog,
    per_class_metric_names, traffic_class_readings,
)

NETWORK = EvaluationQuestion.NETWORK_COMPLETION


def _h(seed: str) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()


def _two_class_request():
    """The canonical two-class design (a0/b0) used by the class-VC evidence."""
    doc = baseline()
    for key in ("design_hash", "guardrail_hash"):
        doc.pop(key, None)
    doc["dependencies"] = [
        {"source": "a0", "target": "b0", "kind": "blocking"},
        {"source": "b0", "target": "a0", "kind": "blocking"},
    ]
    first = doc["workload"]["collectives"][0]
    first["traffic_class"] = "a0"
    second = deepcopy(first)
    second["traffic_class"] = "b0"
    doc["workload"]["collectives"].append(second)
    return CompileRequestV4.from_dict(doc)


@pytest.fixture(scope="module")
def prepared_run():
    """A REAL multi-class preparation — no BookSim binary is needed."""
    compilation = FabricCompiler().compile(_two_class_request())
    assert compilation.status == "COMPILED", compilation.error
    context = build_evaluation_context(compilation)
    adapter = BookSimAdapter()
    native = adapter._prepare_native(
        context, NETWORK,
        traffic_class=context.unified_traffic_class)
    return context, adapter, native


def _resolved(context) -> str:
    value = context.bundle.resolved_fabric.resolved_fabric_hash
    return value() if callable(value) else value


def _per_class_counters(native):
    return {index: {"injected": count, "accepted": count}
            for index, (_name, count)
            in enumerate(native.prepared.expected_flits_by_class)}


def _evidence(native, context, *, per_class=True, counters=None):
    stats = {
        "loaded_trace_packets": native.prepared.expected_packets,
        "injected_trace_packets": native.prepared.expected_packets,
        "delivered_packets": native.prepared.expected_packets,
        "completion_cycles": 100,
        "flits_injected": native.prepared.expected_flits,
        "flits_accepted": native.prepared.expected_flits,
    }
    if per_class:
        stats["flits_by_class"] = (
            _per_class_counters(native) if counters is None else counters)
    return ScientificBackendEvidence(
        prepared_id=native.realization_digest,
        profile_id=native.profile_id,
        projection_semantics_version="booksim2-fork/v2",
        config_sha256=native.config_hash,
        trace_sha256=native.input_hash,
        topology_sha256=None,
        resolved_fabric_hash=_resolved(context),
        physical_traffic_id=native.physical_traffic_id,
        message_artifact_id=native.message_artifact_id,
        binary_sha256=_h("binary"),
        binary_size=1234,
        producer_source_revision="abc123",
        producer_dirty=False,
        seed=native.prepared.seed,
        parser_version=PARSER_VERSION,
        execution_fidelity="QUALIFIED",
        route_observation="EXECUTED_ROUTE_OBSERVED",
        stats=stats,
        exit_status=0,
        transport="SUPERVISED_PROCESS",
        build_manifest_sha256=_h("manifest"),
        build_recipe_version=BOOKSIM_BUILD_RECIPE_VERSION,
        route_dump_sha256=_h("route-dump"))


def _normalize(prepared_run, monkeypatch, evidence):
    """Run the adapter's normalize seam over authenticated evidence bytes.

    ``read_verified_evidence`` is replaced with the canonical document the
    evidence would have persisted, exactly as the Phase-2 trust tests do:
    every digest still has to match the preparation.
    """
    import veritx_dse.backend.evidence as evidence_mod
    context, adapter, native = prepared_run
    document = evidence.to_dict()
    monkeypatch.setattr(
        evidence_mod, "read_verified_evidence",
        lambda ref: {"evidence": document})
    prepared = PreparedExecution(
        backend_id="BOOKSIM_STANDALONE", projection_identity="x",
        qualification_identity=native.profile_id,
        backend_config=None, backend_input=None, producer=None,
        native_prepared=native)
    result = BookSimExecutionResult(
        record=type("_Record", (), {"ref": "dummy"})(), producer=object())
    return adapter.normalize(context, NETWORK, prepared, result)


def test_the_prepared_input_binds_two_canonical_classes(prepared_run):
    _context, _adapter, native = prepared_run
    assert native.prepared.trace_class_map == ("a0", "b0")
    assert len(native.prepared.expected_flits_by_class) == 2


def test_per_class_counters_are_projected_with_canonical_names(
        prepared_run, monkeypatch):
    context, _adapter, native = prepared_run
    envelope = _normalize(
        prepared_run, monkeypatch, _evidence(native, context))
    per_class = {(m.key, dict(m.dimensions)["traffic_class"]): m.value
                 for m in envelope.metrics if m.dimensions}
    expected = dict(native.prepared.expected_flits_by_class)
    assert per_class == {
        ("flits_injected", "a0"): float(expected["a0"]),
        ("flits_injected", "b0"): float(expected["b0"]),
        ("flits_accepted", "a0"): float(expected["a0"]),
        ("flits_accepted", "b0"): float(expected["b0"]),
    }
    for metric in envelope.metrics:
        if metric.dimensions:
            assert metric.source_metric_key is None


def test_per_class_objective_and_constraint_bind_from_evidence(
        prepared_run, monkeypatch):
    """The schema dimension and the measured reading meet: an objective and
    a constraint naming a class both resolve to that class's counter."""
    context, _adapter, native = prepared_run
    envelope = _normalize(
        prepared_run, monkeypatch, _evidence(native, context))
    expected = dict(native.prepared.expected_flits_by_class)

    objective = Objective("flits_injected", "MIN",
                          traffic_class="a0")
    value = bind_traffic_class_metric(
        envelope, metric=objective.metric,
        traffic_class=objective.traffic_class)
    assert value == float(expected["a0"])

    constraint = Constraint("flits_accepted", ">=", 1,
                            traffic_class="b0")
    accepted = bind_traffic_class_metric(
        envelope, metric=constraint.metric,
        traffic_class=constraint.traffic_class)
    assert accepted == float(expected["b0"])


def test_an_unknown_class_refuses(prepared_run, monkeypatch):
    context, _adapter, native = prepared_run
    envelope = _normalize(
        prepared_run, monkeypatch, _evidence(native, context))
    with pytest.raises(MetricRegistryError, match="not evidenced"):
        bind_traffic_class_metric(
            envelope, metric="flits_injected", traffic_class="dp_collective")
    assert traffic_class_readings(envelope, "flits_injected") == {
        name: float(count)
        for name, count in native.prepared.expected_flits_by_class}


def test_a_metric_without_per_class_evidence_is_absent_not_zero(
        prepared_run, monkeypatch):
    context, _adapter, native = prepared_run
    envelope = _normalize(
        prepared_run, monkeypatch,
        _evidence(native, context, per_class=False))
    assert all(not metric.dimensions for metric in envelope.metrics)
    assert bind_traffic_class_metric(
        envelope, metric="flits_injected", traffic_class="a0") is None


def test_aggregate_objectives_are_unchanged(prepared_run, monkeypatch):
    """The aggregate reading keeps its key, its value and its empty
    dimension set — per-class rows sit beside it, never in place of it."""
    context, _adapter, native = prepared_run
    envelope = _normalize(
        prepared_run, monkeypatch, _evidence(native, context))
    aggregate = envelope.metric("flits_injected")
    assert aggregate is not None
    assert aggregate.dimensions == ()
    assert aggregate.value == float(native.prepared.expected_flits)
    assert aggregate.source_metric_key == "flits_injected"
    plain = Objective("flits_injected", "MIN")
    assert plain.traffic_class is None


def test_a_dimensioned_envelope_still_matches_its_native_document(
        prepared_run, monkeypatch):
    """The envelope/native consistency authority accepts the new rows: a
    per-class reading is a projection of a nested native counter, not a
    scalar restatement of one."""
    from veritx_dse.backend.normalized_evidence import (
        assert_envelope_matches_native,
    )
    context, _adapter, native = prepared_run
    evidence = _evidence(native, context)
    envelope = _normalize(prepared_run, monkeypatch, evidence)
    assert_envelope_matches_native(envelope, evidence)


def test_an_index_outside_the_class_map_refuses_the_projection(prepared_run):
    """Evidence whose class index the canonical map does not name would
    relabel a measurement — the whole per-class projection is refused and
    the gap is stated, never guessed."""
    _context, _adapter, native = prepared_run
    values, limitation = _per_class_metric_values(
        {"flits_by_class": {0: {"injected": 5, "accepted": 5},
                            7: {"injected": 5, "accepted": 5}}},
        native.prepared.trace_class_map)
    assert values == []
    assert "outside the canonical class map" in limitation


def test_a_non_integer_counter_refuses_the_projection(prepared_run):
    _context, _adapter, native = prepared_run
    values, limitation = _per_class_metric_values(
        {"flits_by_class": {0: {"injected": 5.5, "accepted": 5}}},
        native.prepared.trace_class_map)
    assert values == []
    assert "non-negative integer" in limitation


def test_the_federated_outcome_path_names_classes_from_context(
        prepared_run, tmp_path):
    """``normalize_booksim_outcome`` has no prepared input, so it derives the
    SAME canonical class map from the context's canonical traffic."""
    context, _adapter, native = prepared_run
    evidence = _evidence(native, context)
    raw = json.dumps(evidence.to_dict()).encode("utf-8")
    path = tmp_path / "backend-evidence.json"
    path.write_bytes(raw)
    outcome = EvaluationOutcome(
        status="EVALUATED",
        design_hash=context.design_hash,
        resolved_fabric_hash=_resolved(context),
        workload_id=context.workload_id,
        message_artifact_id=native.message_artifact_id,
        physical_traffic_id=native.physical_traffic_id,
        backend_config_hash=native.config_hash,
        backend_input_hash=native.input_hash,
        realization_digest=native.realization_digest,
        producer_identity=evidence.binary_sha256,
        raw_evidence_digest=hashlib.sha256(raw).hexdigest(),
        evidence_path=str(path),
        metrics={"completion_cycles": 100,
                 "flits_injected": native.prepared.expected_flits,
                 "flits_accepted": native.prepared.expected_flits})
    envelope = normalize_booksim_outcome(context, outcome)
    expected = dict(native.prepared.expected_flits_by_class)
    assert bind_traffic_class_metric(
        envelope, metric="flits_injected", traffic_class="b0") \
        == float(expected["b0"])
    assert envelope.metric("flits_injected").dimensions == ()


def _multi_class_stdout() -> str:
    return """Loaded text trace: 20 packets from workload.trace
Class 0:
Packet latency average = 10.5
\tminimum = 1
\tmaximum = 20
\tp50 = 10
\tp95 = 19
\tp99 = 20
\tpkt_count = 4
\thonest_avg = 9.5
Network latency average = 3
Flit latency average = 2.5
\tminimum = 1
\tmaximum = 4
Class 1:
Packet latency average = 30.5
\tminimum = 2
\tmaximum = 40
\tp50 = 30
\tp95 = 39
\tp99 = 40
\tpkt_count = 6
\thonest_avg = 29.5
Network latency average = 4
Flit latency average = 3.5
\tminimum = 2
\tmaximum = 5
Draining remaining packets ...
Class 0:
Remaining flits: (0 flits)
Class 1:
Remaining flits: (1 flits)
Trace replay complete: delivered 20 packets, drain took 5 cycles
Completion time is 55 cycles
====== Overall Traffic Statistics ======
====== Traffic class 0 ======
Packet latency average = 999 (1 samples)
====== Traffic class 1 ======
Packet latency average = 888 (1 samples)
"""


def test_the_parser_reads_every_per_class_latency_field():
    stats = parse_booksim_stats(_multi_class_stdout(), "")
    assert stats["latency_scope"] == "PER_CLASS"
    assert stats["latency_by_class"] == {
        0: {"packet_latency_avg": 10.5, "flit_latency_avg": 2.5,
            "p50": 10.0, "p95": 19.0, "p99": 20.0,
            "pkt_count": 4, "honest_latency": 9.5},
        1: {"packet_latency_avg": 30.5, "flit_latency_avg": 3.5,
            "p50": 30.0, "p95": 39.0, "p99": 40.0,
            "pkt_count": 6, "honest_latency": 29.5},
    }
    # The historical scalar keys stay present and byte-compatible; they
    # match class 0's first block, which latency_scope labels PER_CLASS.
    assert stats["packet_latency_avg"] == 10.5
    assert stats["flit_latency_avg"] == 2.5
    assert stats["latency_scope"] != "SINGLE_CLASS"


def test_per_class_latency_normalizes_with_the_canonical_class_names(
        prepared_run, monkeypatch):
    context, _adapter, native = prepared_run
    classes = native.prepared.trace_class_map
    assert len(classes) == 2
    latency = {
        0: {"packet_latency_avg": 11.0, "flit_latency_avg": 4.0,
            "p50": 10.0, "p95": 15.0, "p99": 18.0,
            "pkt_count": 3, "honest_latency": 9.0},
        1: {"packet_latency_avg": 21.0, "flit_latency_avg": 5.0,
            "p50": 20.0, "p95": 25.0, "p99": 28.0,
            "pkt_count": 4, "honest_latency": 19.0},
    }
    base = _evidence(native, context)
    evidence = replace(base, stats={
        **base.stats,
        "packet_latency_avg": 11.0,
        "flit_latency_avg": 4.0,
        "latency_by_class": latency,
        "latency_scope": "PER_CLASS",
    })
    envelope = _normalize(prepared_run, monkeypatch, evidence)
    # The scalar latency keys are class 0's block, not an aggregate: they
    # are deliberately not normalized for a multi-class run.
    for key in ("packet_latency_avg", "flit_latency_avg", "p50", "p95",
                "p99", "honest_latency", "pkt_count"):
        assert all(m.dimensions for m in envelope.metrics if m.key == key), \
            key
    rows = {(m.key, dict(m.dimensions)["traffic_class"]): m.value
            for m in envelope.metrics if m.dimensions}
    assert rows[("packet_latency_avg", classes[0])] == 11.0
    assert rows[("packet_latency_avg", classes[1])] == 21.0
    assert rows[("pkt_count", classes[1])] == 4.0
    assert any("not an aggregate" in limit
               for limit in envelope.limitations)


def test_a_missing_class_latency_is_absent_not_zero(
        prepared_run, monkeypatch):
    context, _adapter, native = prepared_run
    classes = native.prepared.trace_class_map
    base = _evidence(native, context)
    evidence = replace(base, stats={
        **base.stats,
        "latency_by_class": {
            0: {"packet_latency_avg": 11.0, "pkt_count": 3}},
    })
    envelope = _normalize(prepared_run, monkeypatch, evidence)
    assert bind_traffic_class_metric(
        envelope, metric="packet_latency_avg",
        traffic_class=classes[0]) == 11.0
    with pytest.raises(MetricRegistryError, match="not evidenced"):
        bind_traffic_class_metric(
            envelope, metric="packet_latency_avg",
            traffic_class=classes[1])


def test_the_catalog_declares_the_per_class_dimension():
    assert per_class_metric_names() == ("flits_injected", "flits_accepted")
    assert tuple(counter for _metric, counter
                 in BOOKSIM_PER_CLASS_METRICS) == ("injected", "accepted")
    rows = {(row.question, row.metric, row.dimensions): row
            for row in federated_metric_catalog()}
    row = rows[("NETWORK_COMPLETION", "flits_injected",
                ("traffic_class",))]
    assert row.scalar_bindable is True
    assert row.backends == ("BOOKSIM_STANDALONE",)
    assert row.optimization_eligible is True
    assert row.reason is None
    latency = rows[("NETWORK_COMPLETION", "packet_latency_avg",
                    ("traffic_class",))]
    assert latency.scalar_bindable is True
    assert latency.unit == "cycles"
    assert latency.backends == ("BOOKSIM_STANDALONE",)
