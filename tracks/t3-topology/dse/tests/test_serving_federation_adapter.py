"""Serving as a registered federation backend.

Proves the planner is universal: SERVING_TTFT / SERVING_COMPLETION
plan through the same EvaluationPlanner every other question uses,
with the serving adapter adjudicated like any backend — READY only
for a bound, valid experiment on a present runtime; BLOCKED for
missing/invalid inputs; UNAVAILABLE for a missing runtime;
UNSUPPORTED for anything but serving questions (and for serving
questions when no adapter is registered — never fake coverage).

No live serving execution happens here: spawning the full stack is
the product serving path's covered behavior. These tests prove
adjudication, preparation binding, normalization selection and every
refusal — plus the federated plumbing shapes that carry them.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_plan import EvaluationPlanner  # noqa: E402
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendReadiness, ModelFidelity, SupportLevel,
)
from veritx_dse.backend.canonical_serving import (  # noqa: E402
    CanonicalServingEvidence, RequestMetric, ServingBoundaryError,
)
from veritx_dse.backend.registry import BackendRegistry  # noqa: E402
from veritx_dse.backend.serving_adapter import (  # noqa: E402
    BACKEND_ID, ServingAdapter, ServingExperiment, ServingNativeExecution,
    ServingSemanticRefusal, _evidence_from_doc,
)
from veritx_dse.backend.serving_normalization import (  # noqa: E402
    SERVING_BACKEND_ID,
)

REPO = Path(__file__).resolve().parents[4]
CLUSTER = ("third_party/llmservingsim/configs/cluster/"
           "single_node_4_instance_2TP.json")
DATASET = "third_party/llmservingsim/workloads/example_trace.jsonl"


def _experiment(**over) -> ServingExperiment:
    args: dict = {"cluster_config": CLUSTER, "dataset": DATASET}
    args.update(over)
    return ServingExperiment(**args)


def _context():
    return types.SimpleNamespace(
        design_hash="sha256:" + "0d" * 32,
        workload_id="workload-test",
        request=types.SimpleNamespace(
            to_dict=lambda: {"topology": "mesh"}),
        bundle=types.SimpleNamespace(resolved_fabric=types.SimpleNamespace(
            resolved_fabric_hash="sha256:" + "0f" * 32)))


def _evidence(**over) -> CanonicalServingEvidence:
    fields: dict = {
        "workload_id": "serve-test",
        "serving_config_id": "cfg/test",
        "service_profile_id": "sha256:" + "01" * 32,
        "machine_id": "machine-test",
        "namespace_id": "namespace-test",
        "participant_mapping_id": "mapping-test",
        "serving_binding_id": "binding-test",
        "backend_id": "backend-test",
        "astra_binary_sha256": "ab" * 32,
        "astra_binary_size": 123,
        "astra_source_revision": "deadbeef",
        "embedded_fabric_abi_version": "v1",
        "standalone_config_sha256": "sha256:" + "02" * 32,
        "network_evidence_tier": "ASTRA_OWNED_COLLECTIVE_EXECUTION",
        "expansion_authority": "astra_comm_coll",
        "execution_mode": "LIVE_CANONICAL_EXECUTION",
        "instance_count": 2,
        "served_instances": (0, 1),
        "instances_with_completions": (0, 1),
        "request_count": 2,
        "request_metrics": (
            RequestMetric(request_id="req-a", ttft_cycles=100,
                          completion_cycles=500),
            RequestMetric(request_id="req-b", ttft_cycles=200,
                          completion_cycles=700),
        ),
        "rounds": 3,
        "endpoint_completions": ((0, 2),),
        "backend_evidence_ids": ("e1",),
    }
    fields.update(over)
    return CanonicalServingEvidence(**fields)


# ── one authority string ─────────────────────────────────────────────

def test_backend_id_is_the_envelope_authority():
    assert BACKEND_ID == SERVING_BACKEND_ID == "CANONICAL_SERVING"


def test_capabilities_are_exactly_the_serving_questions():
    adapter = ServingAdapter()
    assert [c.question for c in adapter.capabilities()] == [
        EvaluationQuestion.SERVING_TTFT,
        EvaluationQuestion.SERVING_COMPLETION]
    for capability in adapter.capabilities():
        assert capability.support is SupportLevel.SUPPORTED
        assert capability.fidelity is \
            ModelFidelity.FULL_SYSTEM_SIMULATION


# ── assess ───────────────────────────────────────────────────────────

def test_non_serving_questions_are_unsupported():
    adapter = ServingAdapter(experiment=_experiment())
    row = adapter.assess(
        _context(), EvaluationQuestion.NETWORK_COMPLETION)
    assert row.support is SupportLevel.UNSUPPORTED
    assert row.reason


def test_unbound_adapter_is_blocked_not_ready():
    adapter = ServingAdapter()
    for question in (EvaluationQuestion.SERVING_TTFT,
                     EvaluationQuestion.SERVING_COMPLETION):
        row = adapter.assess(_context(), question)
        assert row.support is SupportLevel.SUPPORTED
        assert row.readiness is BackendReadiness.BLOCKED
        assert "no serving experiment bound" in row.reason


def test_missing_inputs_are_blocked():
    adapter = ServingAdapter(experiment=_experiment(
        cluster_config="third_party/llmservingsim/configs/cluster/nope.json"))
    row = adapter.assess(_context(), EvaluationQuestion.SERVING_TTFT)
    assert row.readiness is BackendReadiness.BLOCKED
    assert "not found" in row.reason


def test_nonsense_counts_are_blocked():
    adapter = ServingAdapter(experiment=_experiment(num_reqs=0))
    row = adapter.assess(_context(), EvaluationQuestion.SERVING_TTFT)
    assert row.readiness is BackendReadiness.BLOCKED
    assert "num_reqs" in row.reason


def test_bound_valid_experiment_assesses_ready_or_unavailable():
    """READY iff the runtime is present, else UNAVAILABLE — never READY
    by declaration. Either verdict proves the gates ran."""
    adapter = ServingAdapter(experiment=_experiment())
    row = adapter.assess(_context(), EvaluationQuestion.SERVING_TTFT)
    assert row.readiness in (BackendReadiness.READY,
                             BackendReadiness.UNAVAILABLE)
    if row.readiness is BackendReadiness.READY:
        assert row.reason is None
        assert row.qualification_profile is not None
    else:
        assert row.reason


# ── prepare ──────────────────────────────────────────────────────────

def test_prepare_refuses_without_experiment():
    adapter = ServingAdapter()
    with pytest.raises(ServingSemanticRefusal):
        adapter.prepare(_context(), EvaluationQuestion.SERVING_TTFT)


def test_prepare_binds_this_design(monkeypatch):
    """Preparation carries the context's own compile-request document —
    the run serves the evaluated fabric, never a derived one."""
    import veritx_dse.backend.serving_adapter as _mod
    monkeypatch.setattr(
        _mod, "_runtime_probe", lambda _binary: (True, ""))
    adapter = ServingAdapter(experiment=_experiment())
    context = _context()
    design_doc = {"topology": "mesh", "workload": "dense"}
    context.request = types.SimpleNamespace(
        to_dict=lambda: design_doc)
    prepared = adapter.prepare(context, EvaluationQuestion.SERVING_TTFT)
    assert prepared.backend_id == BACKEND_ID
    assert prepared.native_prepared.design_doc == design_doc
    assert prepared.native_prepared.design_hash == context.design_hash
    assert prepared.native_prepared.workload_id == context.workload_id


# ── normalize ────────────────────────────────────────────────────────

def _prepared(design_hash="sha256:" + "0d" * 32):
    from veritx_dse.backend.serving_adapter import ServingPreparation
    return types.SimpleNamespace(native_prepared=ServingPreparation(
        experiment_id="sha256:" + "ee" * 32,
        cluster_config=CLUSTER, dataset=DATASET, num_reqs=2,
        profile_overrides=(), astra_binary=None, timeout_s=900,
        design_doc={}, design_hash=design_hash,
        workload_id="workload-test"))


def _native(evidence=None, design_hash="sha256:" + "0d" * 32):
    return ServingNativeExecution(
        evidence=evidence or _evidence(), design_hash=design_hash,
        run_dir="/tmp/serving-test", requests_completed=2,
        requests_expected=2, rounds=3, machine_id="machine-test",
        namespace_id="namespace-test")


def test_normalize_selects_the_asked_envelope():
    adapter = ServingAdapter()
    ttft = adapter.normalize(
        _context(), EvaluationQuestion.SERVING_TTFT,
        _prepared(), _native())
    assert ttft.question is EvaluationQuestion.SERVING_TTFT
    assert ttft.backend_id == BACKEND_ID
    assert [m.key for m in ttft.metrics] == ["ttft_cycles"] * 2
    completion = adapter.normalize(
        _context(), EvaluationQuestion.SERVING_COMPLETION,
        _prepared(), _native())
    assert [m.key for m in completion.metrics] == \
        ["completion_cycles"] * 2


def test_normalize_refuses_transplanted_runs():
    adapter = ServingAdapter()
    with pytest.raises(ServingBoundaryError):
        adapter.normalize(
            _context(), EvaluationQuestion.SERVING_TTFT,
            _prepared(design_hash="sha256:" + "00" * 32), _native())


def test_normalize_refuses_replay_evidence():
    adapter = ServingAdapter()
    with pytest.raises(ServingBoundaryError):
        adapter.normalize(
            _context(), EvaluationQuestion.SERVING_TTFT, _prepared(),
            _native(evidence=_evidence(
                execution_mode="REPLAY_ONLY")))


def test_evidence_round_trip_recomputes_identity():
    doc = _evidence().to_dict()
    rebuilt = _evidence_from_doc(doc)
    assert rebuilt.evidence_id() == doc["evidence_id"]


def test_evidence_substitution_refuses():
    doc = _evidence().to_dict()
    doc["request_metrics"][0][1] = 99999
    with pytest.raises(ServingBoundaryError):
        _evidence_from_doc(doc)


def test_evidence_schema_drift_refuses():
    doc = _evidence().to_dict()
    doc["future_field"] = "science from the future"
    with pytest.raises(ServingBoundaryError):
        _evidence_from_doc(doc)


# ── planner ──────────────────────────────────────────────────────────

def test_planner_selects_serving_for_serving_questions():
    adapter = ServingAdapter(experiment=_experiment())
    registry = BackendRegistry((adapter,))
    plan = EvaluationPlanner().plan(
        _context(),
        (EvaluationQuestion.SERVING_TTFT,
         EvaluationQuestion.SERVING_COMPLETION),
        registry)
    assert [a.backend_id for a in plan.analyses] == \
        [BACKEND_ID, BACKEND_ID]
    # readiness follows the real gates (READY only on a present
    # runtime), but the backend binding is exact either way.
    for analysis in plan.analyses:
        assert analysis.backend_id == BACKEND_ID


def test_explicit_pin_is_authoritative():
    adapter = ServingAdapter(experiment=_experiment())
    registry = BackendRegistry((adapter,))
    plan = EvaluationPlanner().plan(
        _context(), (EvaluationQuestion.SERVING_TTFT,), registry,
        requested_backend=BACKEND_ID)
    assert plan.analyses[0].backend_id == BACKEND_ID


def test_serving_questions_without_adapter_are_unsupported():
    """No adapter, no fake coverage: the universal planner still
    answers every question — with an honest UNSUPPORTED row."""
    registry = BackendRegistry(())
    plan = EvaluationPlanner().plan(
        _context(), (EvaluationQuestion.SERVING_TTFT,), registry)
    row = plan.analyses[0]
    assert row.support is SupportLevel.UNSUPPORTED
    assert row.backend_id is None


# ── federated plumbing ───────────────────────────────────────────────


def _serving_options(**over):
    from veritx_dse.application.federated_evaluator import (  # noqa: E402
        ServingRunOptions,
    )
    args: dict = {"cluster_config": CLUSTER, "dataset": DATASET}
    args.update(over)
    return ServingRunOptions(**args)


def test_federated_run_without_options_leaves_serving_unsupported():
    """evaluate_federated without serving options never invents an
    experiment: serving rows stay UNSUPPORTED and nothing spawns."""
    import json as _json  # noqa: E402
    from veritx_dse.application.fabric_compiler import (  # noqa: E402
        FabricCompiler,
    )
    from veritx_dse.application.federated_evaluator import (  # noqa: E402
        evaluate_federated,
    )
    from veritx_dse.backend.registry import (  # noqa: E402
        default_backend_registry,
    )
    from veritx_dse.core.paths import REPO  # noqa: E402
    from veritx_dse.product.service import (  # noqa: E402
        parse_request_doc,
    )
    dense = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"
    compilation = FabricCompiler().compile(
        parse_request_doc(_json.loads(dense.read_text(encoding="utf-8"))))
    assert compilation.status == "COMPILED"
    outcome = evaluate_federated(
        compilation, (EvaluationQuestion.SERVING_TTFT,),
        default_backend_registry())
    row = outcome.analysis(EvaluationQuestion.SERVING_TTFT)
    assert row.status == "UNSUPPORTED"
    assert row.normalized_evidence is None


def test_evaluate_serving_without_options_refuses():
    """A serving row that somehow reaches execution without run
    options refuses instead of executing an unbound experiment."""
    import types as _types  # noqa: E402
    from veritx_dse.application.federated_evaluator import (  # noqa: E402
        _evaluate_serving,
    )
    adapter = ServingAdapter(experiment=_experiment())
    row = _types.SimpleNamespace(
        question=EvaluationQuestion.SERVING_TTFT,
        backend_id=BACKEND_ID)
    outcome = _evaluate_serving(
        _context(), row, adapter, None, Path("/tmp/serving-test"))
    assert outcome.status == "FAILED"
    assert "absent" in outcome.reason


def test_evaluate_serving_absent_runtime_is_unavailable():
    """A bound experiment on a missing runtime is UNAVAILABLE —
    never a semantic verdict, never a fabrication."""
    import types as _types  # noqa: E402
    from veritx_dse.application.federated_evaluator import (  # noqa: E402
        ANALYSIS_UNAVAILABLE, _evaluate_serving,
    )

    class _Gone(ServingAdapter):
        def execute(self, prepared, options):
            from veritx_dse.backend.serving_adapter import (  # noqa: E402
                ServingRuntimeAbsent,
            )
            raise ServingRuntimeAbsent("gone")

    adapter = _Gone(experiment=_experiment())
    row = _types.SimpleNamespace(
        question=EvaluationQuestion.SERVING_TTFT,
        backend_id=BACKEND_ID)
    outcome = _evaluate_serving(
        _context(), row, adapter, _serving_options(),
        Path("/tmp/serving-test"))
    assert outcome.status == ANALYSIS_UNAVAILABLE
    assert "gone" in outcome.reason
