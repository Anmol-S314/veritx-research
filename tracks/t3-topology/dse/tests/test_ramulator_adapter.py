"""PROMPT 3 — the certified Ramulator adapter.

Offline part (always): capability truth, semantic refusal for workloads
with no resolvable memory demand, UNAVAILABLE honesty when the compiled
extension is absent, identity binding across prepare/execute/normalize,
unit-preserving normalization with absent-metrics honesty, drain-PASS
gating (INCONCLUSIVE never normalizes), transplant refusal, and the
federated DRAM_TIMING leg mapping.

Live part (VERITX_LIVE_RAMULATOR=1 only): the compiled extension must be
present and a real trace must drain PASS. Under the marker a missing
backend is FAILURE, never a skip.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_context import (  # noqa: E402
    CanonicalEvaluationContext,
)
from veritx_dse.application.evaluation_plan import EvaluationPlanner  # noqa: E402
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.federated_evaluator import (  # noqa: E402
    ANALYSIS_EVALUATED, ANALYSIS_FAILED, ANALYSIS_INCONCLUSIVE,
    ANALYSIS_UNAVAILABLE, ANALYSIS_UNSUPPORTED,
)
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendReadiness, ModelFidelity, PreparedExecution, SupportLevel,
)
from veritx_dse.backend.ramulator_adapter import (  # noqa: E402
    BACKEND_ID, MODEL_ASSUMPTION, QUALIFICATION_PROFILE,
    RAMULATOR_MODEL_FIDELITY, RamulatorAdapter, RamulatorBackendAbsent,
    RamulatorPreparation, RamulatorSemanticRefusal, certified_geometry,
    ramulator_evidence_id,
)
from veritx_dse.backend.registry import default_backend_registry  # noqa: E402
from veritx_dse.model.placement import ParallelismShape  # noqa: E402
from veritx_dse.simulation import ramulator as _sim  # noqa: E402
from veritx_dse.workload.graph import (  # noqa: E402
    KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
    collective_detail, compute_detail,
)

DRAM = EvaluationQuestion.DRAM_TIMING
LIVE = os.environ.get("VERITX_LIVE_RAMULATOR") == "1"

def _graph(*, with_memory: bool):
    if with_memory:
        par = ParallelismShape(tp=1, pp=1, ep=1, dp=1)
        ops = (
            OperationNode(
                operation_id="c0", kind=KIND_COMPUTE,
                detail=compute_detail(
                    duration_ns=100, input_bytes=4096, weight_bytes=8192,
                    output_bytes=2048, participant_count=1)),
        )
        return WorkloadGraph(
            parallelism=par, participant_count=1, operations=ops)
    par = ParallelismShape(tp=2, pp=1, ep=1, dp=1)
    ops = (
        OperationNode(
            operation_id="ar", kind=KIND_COLLECTIVE,
            detail=collective_detail(
                collective_kind="ALLREDUCE", participants=(0, 1),
                payload_bytes=1024, participant_count=2)),
    )
    return WorkloadGraph(
        parallelism=par, participant_count=2, operations=ops)

def _context(graph) -> CanonicalEvaluationContext:
    # The request declares its hardware: one HBM controller, so memory
    # demand resolves against declared hardware rather than a phantom pool.
    # Designs under test that need no hardware declare none and refuse.
    request = SimpleNamespace(
        design_hash=lambda: "sha256:" + "ab" * 32,
        agents=[SimpleNamespace(kind="hbm_controller", count=1)])
    bundle = SimpleNamespace(resolved_fabric=SimpleNamespace(
        resolved_fabric_hash="sha256:" + "cd" * 32))
    return CanonicalEvaluationContext(
        request=request, compilation=None,
        lowered_workload=SimpleNamespace(unified_traffic_class="default"),
        workload=graph, bundle=bundle)

def _vendor_with_ext(tmp_path: Path) -> Path:
    """A fake vendor tree whose extension file exists (ready, offline)."""
    import sysconfig
    suffix = sysconfig.get_config_var("EXT_SUFFIX")
    ext = tmp_path / "vendor" / "python" / "ramulator" / f"_ramulator{suffix}"
    ext.parent.mkdir(parents=True, exist_ok=True)
    ext.write_bytes(b"fake-ramulator-extension")
    return tmp_path / "vendor"

class _Runner:
    """Fake backend: writes the given stats.json on call (as the real
    driver would). stdout stays log-only."""

    def __init__(self, stats):
        self._stats = stats

    def __call__(self, cmd, cwd=None, timeout=None, env=None):
        (Path(cwd) / "stats.json").write_text(json.dumps(self._stats))
        return SimpleNamespace(cmd=cmd, returncode=0,
                               stdout="RAMULATOR_DONE stats.json\n",
                               stderr="")

def _pass_stats(read_tx: int, write_tx: int) -> dict:
    return {"cycles": 1345, "num_read_reqs": read_tx,
            "num_write_reqs": write_tx,
            "num_read_reqs_served": read_tx,
            "num_write_reqs_served": write_tx,
            "num_write_reqs_coalesced": 0,
            "avg_read_latency": 275.0, "avg_write_latency": 310.5,
            "row_hits": 160, "row_misses": 1, "row_conflicts": 0,
            "read_queue_len_avg": 2.5, "write_queue_len_avg": 0.5}

def _execute_offline(monkeypatch, tmp_path, *, stats=None):
    """Run the full adapter execute() offline: fake ready backend plus a
    canned runner whose counters reconcile with the real manifest."""
    import veritx_dse.core.process as proc
    from veritx_dse.workload.memory_lowering import (
        lower_to_ramulator_trace,
    )
    context = _context(_graph(with_memory=True))
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    prepared = adapter.prepare(context, DRAM)
    probe = tmp_path / "probe.trace"
    manifest = lower_to_ramulator_trace(
        prepared.native_prepared.artifact,
        prepared.native_prepared.geometry, out_path=probe)
    counts = manifest.to_dict()["counts"]
    runner = _Runner(stats if stats is not None else _pass_stats(
        counts["read_transactions"], counts["write_transactions"]))
    monkeypatch.setattr(proc, "supervised_run", runner)
    run_dir = tmp_path / "run"
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=run_dir, timeout_s=60))
    return adapter, context, prepared, evidence, run_dir

def _synthetic_evidence(prepared, *, status="PASS", metrics=None,
                        failure_reason=""):
    return _sim.MemoryEvidence(
        status=status,
        producer={"name": "ramulator", "version": "2.1.0",
                  "commit_sha": "x" * 40, "binary_sha256": "ab" * 32},
        fidelity="MEMORY_CYCLE_SIMULATION",
        memory_artifact_hash=prepared.native_prepared.memory_artifact_hash,
        lowering_manifest_hash="sha256:" + "ef" * 32,
        backend_input_hash="sha256:" + "01" * 32,
        backend_config_hash=prepared.native_prepared.backend_config_hash,
        metrics=metrics if metrics is not None else {},
        assumptions=(), semantic_losses=(),
        failure_reason=failure_reason, raw={})

def test_backend_id_is_the_model_envelope_not_bare_ramulator():
    adapter = RamulatorAdapter()
    assert adapter.backend_id == "RAMULATOR2_HBM3_V1"
    assert adapter.backend_id == BACKEND_ID

def test_capability_declares_dram_timing_at_memory_fidelity():
    (capability,) = RamulatorAdapter().capabilities()
    assert capability.question is DRAM
    assert capability.support is SupportLevel.SUPPORTED
    assert capability.fidelity is ModelFidelity.MEMORY_CYCLE_SIMULATION
    assert capability.fidelity is RAMULATOR_MODEL_FIDELITY
    assert capability.fidelity is not ModelFidelity.FULL_SYSTEM_SIMULATION
    assert MODEL_ASSUMPTION in capability.limitations

def test_assess_wrong_question_is_unsupported_never_ready():
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    for question in (EvaluationQuestion.NETWORK_COMPLETION,
                     EvaluationQuestion.SYSTEM_MAKESPAN,
                     EvaluationQuestion.SERVING_TTFT):
        assessment = adapter.assess(context, question)
        assert assessment.support is SupportLevel.UNSUPPORTED
        assert assessment.readiness is not BackendReadiness.READY

def test_assess_no_memory_operands_is_unsupported_never_zero_cost():
    adapter = RamulatorAdapter()
    assessment = adapter.assess(_context(_graph(with_memory=False)), DRAM)
    assert assessment.support is SupportLevel.UNSUPPORTED
    assert assessment.readiness is BackendReadiness.BLOCKED
    assert assessment.reason

def test_assess_memory_workload_without_extension_is_unavailable(tmp_path):
    adapter = RamulatorAdapter(vendor_dir=tmp_path / "empty-vendor")
    assessment = adapter.assess(_context(_graph(with_memory=True)), DRAM)
    assert assessment.support is SupportLevel.SUPPORTED
    assert assessment.readiness is BackendReadiness.UNAVAILABLE
    assert assessment.reason

def test_assess_ready_with_built_extension(tmp_path):
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    assessment = adapter.assess(_context(_graph(with_memory=True)), DRAM)
    assert assessment.support is SupportLevel.SUPPORTED
    assert assessment.readiness is BackendReadiness.READY
    assert assessment.qualification_profile == QUALIFICATION_PROFILE
    assert assessment.fidelity is ModelFidelity.MEMORY_CYCLE_SIMULATION

def test_prepare_binds_memory_hashes_and_config():
    from veritx_dse.workload.memory_lowering import backend_config_payload
    import hashlib
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    assert isinstance(prepared, PreparedExecution)
    native = prepared.native_prepared
    assert isinstance(native, RamulatorPreparation)
    assert prepared.backend_id == BACKEND_ID
    assert prepared.projection_identity == native.memory_artifact_hash
    assert prepared.projection_identity == \
        native.artifact.artifact_hash
    assert native.access_stream_hash == \
        native.artifact.access_stream_hash
    assert native.backend_config_hash == "sha256:" + hashlib.sha256(
        backend_config_payload(native.geometry, "sequential_bankstriped_v1")
    ).hexdigest()
    assert prepared.qualification_identity == native.backend_config_hash

def test_prepare_wrong_question_refuses_typed():
    adapter = RamulatorAdapter()
    with pytest.raises(RamulatorSemanticRefusal):
        adapter.prepare(_context(_graph(with_memory=True)),
                        EvaluationQuestion.NETWORK_COMPLETION)

def test_prepare_no_memory_refuses_typed_never_builds():
    adapter = RamulatorAdapter()
    with pytest.raises(RamulatorSemanticRefusal):
        adapter.prepare(_context(_graph(with_memory=False)), DRAM)

def test_planner_routes_dram_timing_to_ramulator_envelope():
    context = _context(_graph(with_memory=True))
    plan = EvaluationPlanner().plan(
        context, (DRAM,), default_backend_registry())
    row = plan.analyses[0]
    assert row.backend_id == "RAMULATOR2_HBM3_V1"

def test_planner_dram_without_memory_is_unbound_unsupported():
    context = _context(_graph(with_memory=False))
    plan = EvaluationPlanner().plan(
        context, (DRAM,), default_backend_registry())
    row = plan.analyses[0]
    assert row.backend_id is None
    assert row.support is SupportLevel.UNSUPPORTED

def test_explicit_wrong_backend_for_dram_is_unsupported_without_fallback():
    context = _context(_graph(with_memory=True))
    plan = EvaluationPlanner().plan(
        context, (DRAM,), default_backend_registry(),
        requested_backend="BOOKSIM_STANDALONE")
    row = plan.analyses[0]
    assert row.backend_id is None
    assert row.support is SupportLevel.UNSUPPORTED

def test_serving_questions_plan_supported_blocked_never_crash():
    context = _context(_graph(with_memory=True))
    plan = EvaluationPlanner().plan(
        context,
        (EvaluationQuestion.SERVING_TTFT,
         EvaluationQuestion.SERVING_COMPLETION),
        default_backend_registry())
    for row in plan.analyses:
        assert row.backend_id == "CANONICAL_SERVING"
        assert row.support is SupportLevel.SUPPORTED
        assert row.readiness is not None

def test_execute_missing_extension_is_absent_not_a_verdict(tmp_path):
    adapter = RamulatorAdapter(vendor_dir=tmp_path / "empty-vendor")
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    with pytest.raises(RamulatorBackendAbsent, match="not built"):
        adapter.execute(
            prepared, SimpleNamespace(run_dir=tmp_path / "run",
                                      timeout_s=60))

def test_execute_offline_drains_pass_and_persists_bundle(
        monkeypatch, tmp_path):
    adapter, context, prepared, evidence, run_dir = _execute_offline(
        monkeypatch, tmp_path)
    assert evidence.status == "PASS", evidence.failure_reason
    ram_dir = run_dir / "ramulator"
    for name in ("memory.trace", "lowering-manifest.json",
                 "memory-artifact.json", "memory-evidence.json"):
        assert (ram_dir / name).is_file(), name
    assert (ram_dir / "run" / "stats.json").is_file()
    assert evidence.memory_artifact_hash == \
        prepared.native_prepared.memory_artifact_hash

def test_persisted_bundle_is_tamper_evident(monkeypatch, tmp_path):
    _, _, _, _, run_dir = _execute_offline(monkeypatch, tmp_path)
    ram_dir = run_dir / "ramulator"
    from veritx_dse.core.memory import MemoryArtifact
    stored_artifact = MemoryArtifact.from_dict(json.loads(
        (ram_dir / "memory-artifact.json").read_text(encoding="utf-8")))
    from veritx_dse.workload.memory_lowering import (
        MemoryLoweringManifest,
    )
    stored_manifest = MemoryLoweringManifest(**json.loads(
        (ram_dir / "lowering-manifest.json").read_text(encoding="utf-8")))
    trace = ram_dir / "memory.trace"
    trace.write_text(trace.read_text(encoding="utf-8")
                     + "R 0 0,0,0,0,0,0,0\n")
    from veritx_dse.simulation.ramulator import RamulatorBackend
    import sysconfig
    pkg = tmp_path / "pkg"
    (pkg / "ramulator").mkdir(parents=True)
    ext = pkg / "ramulator" / \
        f"_ramulator{sysconfig.get_config_var('EXT_SUFFIX')}"
    ext.touch()
    with pytest.raises(_sim.RamulatorError, match="trace_sha256"):
        _sim.execute(stored_artifact, stored_manifest, trace,
                     backend=RamulatorBackend(
                         python_exe=sys.executable, package_dir=pkg,
                         ext_path=ext),
                     run_dir=tmp_path / "rerun")

def test_normalize_pass_preserves_units_and_skips_wall_time():
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    evidence = _synthetic_evidence(prepared, metrics={
        "completion_cycles": {"value": 1345, "unit": "cycles"},
        "average_read_latency_cycles": {"value": 275.0, "unit": "cycles"},
        "row_hits": {"value": 160, "unit": "requests"},
        "completed_read_bytes": {"value": 12288, "unit": "bytes"},
        "wall_time_s": {"value": 1.2, "unit": "seconds"},
    })
    envelope = adapter.normalize(context, DRAM, prepared, evidence)
    assert envelope.backend_id == BACKEND_ID
    assert envelope.question is DRAM
    assert envelope.model_fidelity is ModelFidelity.MEMORY_CYCLE_SIMULATION
    assert envelope.metric("completion_cycles").value == 1345.0
    assert envelope.metric("completion_cycles").unit == "cycles"
    assert envelope.metric("average_read_latency_cycles").unit == "cycles"
    assert envelope.metric("row_hits").unit == "requests"
    assert envelope.metric("completed_read_bytes").unit == "bytes"
    assert envelope.metric("wall_time_s") is None
    assert envelope.qualification == "PASS"
    assert envelope.producer_identity == "ab" * 32
    assert envelope.native_evidence_id == ramulator_evidence_id(evidence)
    assert MODEL_ASSUMPTION in envelope.limitations
    assert prepared.native_prepared.memory_artifact_hash in \
        envelope.canonical_parent_ids
    assert context.design_hash in envelope.canonical_parent_ids
    assert context.workload_id in envelope.canonical_parent_ids

def test_normalize_absent_metric_stays_absent_never_zero():
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    evidence = _synthetic_evidence(prepared, metrics={
        "completion_cycles": {"value": 10, "unit": "cycles"},
    })
    envelope = adapter.normalize(context, DRAM, prepared, evidence)
    assert envelope.metric("completion_cycles") is not None
    assert envelope.metric("average_read_latency_cycles") is None
    assert envelope.metric("row_hits") is None

def test_normalize_inconclusive_refuses_never_pass(monkeypatch, tmp_path):
    import veritx_dse.core.process as proc
    from veritx_dse.workload.memory_lowering import (
        lower_to_ramulator_trace,
    )
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    probe = tmp_path / "probe.trace"
    manifest = lower_to_ramulator_trace(
        prepared.native_prepared.artifact,
        prepared.native_prepared.geometry, out_path=probe)
    counts = manifest.to_dict()["counts"]
    monkeypatch.setattr(proc, "supervised_run", _Runner(dict(
        _pass_stats(counts["read_transactions"],
                    counts["write_transactions"]),
        num_read_reqs_served=0)))
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=tmp_path / "run",
                                  timeout_s=60))
    assert evidence.status == "INCONCLUSIVE"
    with pytest.raises(_sim.RamulatorError, match="INCONCLUSIVE"):
        adapter.normalize(context, DRAM, prepared, evidence)

def test_normalize_failed_and_unsupported_evidence_refuse():
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    for status in ("EVALUATION_FAILED", "UNSUPPORTED"):
        with pytest.raises(_sim.RamulatorError):
            adapter.normalize(
                context, DRAM, prepared,
                _synthetic_evidence(
                    prepared, status=status,
                    failure_reason="backend blew up"))

def test_normalize_transplanted_evidence_refuses():
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    evidence = _synthetic_evidence(prepared, metrics={
        "completion_cycles": {"value": 1, "unit": "cycles"}})
    import dataclasses
    transplanted = dataclasses.replace(
        evidence, memory_artifact_hash="sha256:" + "ff" * 32)
    with pytest.raises(_sim.RamulatorError, match="transplant"):
        adapter.normalize(context, DRAM, prepared, transplanted)

def test_evidence_identity_ignores_wall_time_and_host_paths():
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    prepared = adapter.prepare(context, DRAM)
    base = {"completion_cycles": {"value": 10, "unit": "cycles"}}
    first = _synthetic_evidence(prepared, metrics=dict(
        base, wall_time_s={"value": 1.0, "unit": "seconds"}))
    repeat = _synthetic_evidence(prepared, metrics=dict(
        base, wall_time_s={"value": 9.9, "unit": "seconds"}))
    assert ramulator_evidence_id(first) == ramulator_evidence_id(repeat)

def _leg(monkeypatch, tmp_path, *, evidence=None, execute_error=None):
    from veritx_dse.application.federated_evaluator import (
        RamulatorRunOptions, _evaluate_ramulator,
    )
    from veritx_dse.application.evaluation_plan import EvaluationPlanner
    context = _context(_graph(with_memory=True))
    plan = EvaluationPlanner().plan(
        context, (DRAM,),
        default_backend_registry(
            ramulator_vendor_dir=_vendor_with_ext(tmp_path)))
    (row,) = plan.analyses
    assert row.readiness is BackendReadiness.READY

    real = RamulatorAdapter(
        vendor_dir=_vendor_with_ext(tmp_path))

    class _Double:
        backend_id = BACKEND_ID

        def prepare(self, ctx, question):
            return real.prepare(ctx, question)

        def execute(self, prepared, options):
            if execute_error is not None:
                raise execute_error
            return evidence

        def normalize(self, ctx, question, prepared, native):
            return real.normalize(ctx, question, prepared, native)

    analysis_dir = tmp_path / "analyses" / "dram_timing"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    return _evaluate_ramulator(
        context, row, _Double(), RamulatorRunOptions(),
        analysis_dir)

def test_leg_evaluated_on_pass(monkeypatch, tmp_path):
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(_context(_graph(with_memory=True)), DRAM)
    outcome = _leg(monkeypatch, tmp_path, evidence=_synthetic_evidence(
        prepared, metrics={
            "completion_cycles": {"value": 1345, "unit": "cycles"}}))
    assert outcome.status == ANALYSIS_EVALUATED
    assert outcome.backend_id == BACKEND_ID
    assert outcome.model_fidelity is ModelFidelity.MEMORY_CYCLE_SIMULATION
    assert outcome.normalized_evidence is not None
    assert outcome.native_summary["status"] == "PASS"

def test_leg_failed_on_crash_and_inconclusive(monkeypatch, tmp_path):
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(_context(_graph(with_memory=True)), DRAM)
    crashed = _leg(monkeypatch, tmp_path, evidence=_synthetic_evidence(
        prepared, status="EVALUATION_FAILED", failure_reason="boom"))
    assert crashed.status == ANALYSIS_FAILED
    assert "boom" in (crashed.reason or "")
    inconclusive = _leg(monkeypatch, tmp_path, evidence=_synthetic_evidence(
        prepared, status="INCONCLUSIVE", failure_reason="shortfall"))
    assert inconclusive.status == ANALYSIS_INCONCLUSIVE
    assert "INCONCLUSIVE" in (inconclusive.reason or "")

def test_leg_unsupported_evidence_is_unsupported(monkeypatch, tmp_path):
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(_context(_graph(with_memory=True)), DRAM)
    outcome = _leg(monkeypatch, tmp_path, evidence=_synthetic_evidence(
        prepared, status="UNSUPPORTED", failure_reason="DDR5"))
    assert outcome.status == ANALYSIS_UNSUPPORTED

def test_leg_missing_backend_is_unavailable(monkeypatch, tmp_path):
    outcome = _leg(
        monkeypatch, tmp_path,
        execute_error=RamulatorBackendAbsent("not built"))
    assert outcome.status == ANALYSIS_UNAVAILABLE

def test_ramulator_integrity_reports_drain_not_packets(
        monkeypatch, tmp_path):
    from veritx_dse.product.service import ProductService
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(_context(_graph(with_memory=True)), DRAM)
    outcome = _leg(monkeypatch, tmp_path, evidence=_synthetic_evidence(
        prepared, metrics={
            "completion_cycles": {"value": 1345, "unit": "cycles"}}))
    record = ProductService._ramulator_integrity(outcome.to_dict())
    assert record["kind"] == "memory_drain_integrity"
    assert record["backend"] == BACKEND_ID
    assert "packet_conservation" not in record
    refused = ProductService._ramulator_integrity({
        "backend_id": BACKEND_ID, "status": "BACKEND_UNAVAILABLE",
        "reason": "no extension"})
    assert refused["status"] == "BACKEND_UNAVAILABLE"
    assert refused["reason"] == "no extension"

def test_reproduce_without_evidence_is_not_available(tmp_path):
    from veritx_dse.backend.reproduce_ramulator import (
        reproduce_ramulator_run_bundle,
    )
    from veritx_dse.core.run_bundle import RunBundleError
    with pytest.raises(RunBundleError, match="NOT_AVAILABLE"):
        reproduce_ramulator_run_bundle(tmp_path / "analyses" / "dram_timing")

def test_reproduce_dispatch_without_backend_is_not_available(tmp_path):
    from veritx_dse.product.service import ProductConfig, ProductService
    svc = ProductService(ProductConfig(projects_root=tmp_path / "projects"))
    result = svc._reproduce_ramulator_analysis(
        tmp_path, tmp_path / "analyses" / "dram_timing", BACKEND_ID)
    assert result["outcome"] == "REPRODUCTION_NOT_AVAILABLE"

@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_ramulator_spawns_and_drains(tmp_path):
    backend = _sim.discover()
    assert backend.ready, (
        "VERITX_LIVE_RAMULATOR=1 requires the compiled Ramulator "
        f"extension at {backend.ext_path}; a missing backend is FAILURE, "
        "never a skip")
    adapter = RamulatorAdapter()
    context = _context(_graph(with_memory=True))
    assessment = adapter.assess(context, DRAM)
    assert assessment.readiness is BackendReadiness.READY
    prepared = adapter.prepare(context, DRAM)
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=tmp_path / "live",
                                  timeout_s=600))
    assert evidence.status == "PASS", evidence.failure_reason
    envelope = adapter.normalize(context, DRAM, prepared, evidence)
    assert envelope.metric("completion_cycles") is not None
    assert {"row_hits", "row_misses", "row_conflicts"} <= {
        m.key for m in envelope.metrics}

@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_two_pool_dispatch_reconciles_dependencies_and_replay(tmp_path):
    backend = _sim.discover()
    assert backend.ready, (
        "VERITX_LIVE_RAMULATOR=1 requires the compiled Ramulator extension")
    graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="c0", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=70, weight_bytes=35,
                output_bytes=15, input_loc="LOCAL:0",
                weight_loc="LOCAL:1", output_loc="LOCAL:0",
                participant_count=1)),))
    context = _context_with_agents(
        graph, [SimpleNamespace(kind="hbm_controller", count=2)])
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(context, DRAM)
    run_dir = tmp_path / "multi-hbm"
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=run_dir, max_transactions=100,
                                  max_native_ticks=20_000))
    assert evidence.status == "PASS", evidence.failure_reason
    assert evidence.metrics["issued_read_transactions"]["value"] == 5
    assert evidence.metrics["issued_write_transactions"]["value"] == 1
    assert evidence.metrics["completed_requests"]["value"] == 6
    assert evidence.metrics["native_clock_period"]["value"] > 0
    manifest = json.loads((run_dir / "ramulator" /
                           "dispatch-manifest.json").read_text())
    rows = manifest["transactions"]
    same_address = [r for r in rows if r["native_address"] == 0 and
                    r["device_id"] in (0, 1)]
    assert {r["device_id"] for r in same_address} == {0, 1}
    assert {r["native_channel"] for r in same_address} == {0, 1}
    assert manifest["bytes"] == {
        "logical_bytes": 120, "generated_bytes": 192,
        "padding_bytes": 72}
    pool_stats = evidence.raw["pool_stats"]
    assert [(p["declared_device_id"],
             {k: p["expected"][k] for k in ("read", "write")},
             p["accepted"], p["completed"]) for p in pool_stats] == [
        (0, {"read": 3, "write": 1}, {"read": 3, "write": 1},
         {"read": 3, "write": 1}),
        (1, {"read": 2, "write": 0}, {"read": 2, "write": 0},
         {"read": 2, "write": 0})]
    assert [p["expected"]["padding_bytes"] for p in pool_stats] == [43, 29]
    events = evidence.raw["events"]
    first_callbacks = next(i for i, e in enumerate(events)
                           if e["event"] == "callback")
    assert events[0]["event"] == events[1]["event"] == "accepted"
    assert events[0]["native_channel"] != events[1]["native_channel"]
    input_callbacks = [i for i, e in enumerate(events)
                       if e["event"] == "callback" and
                       e["transaction_id"].startswith("acc.c0.input:")]
    weight_callbacks = [i for i, e in enumerate(events)
                        if e["event"] == "callback" and
                        e["transaction_id"].startswith("acc.c0.weight:")]
    output_accepts = [i for i, e in enumerate(events)
                      if e["event"] == "accepted" and
                      e["transaction_id"].startswith("acc.c0.output:")]
    assert max(input_callbacks + weight_callbacks) < min(output_accepts)
    assert first_callbacks < min(output_accepts)
    normalized = adapter.normalize(context, DRAM, prepared, evidence)
    assert normalized.metric("completion_cycles") is not None

    from veritx_dse.backend.reproduce_ramulator import (
        reproduce_ramulator_run_bundle,
    )
    replay = reproduce_ramulator_run_bundle(run_dir)
    assert replay["matched"] and replay["status"] == "PASS"
    import shutil
    tampered = tmp_path / "tampered"
    shutil.copytree(run_dir, tampered)
    tamper_path = tampered / "ramulator" / "dispatch-manifest.json"
    tampered_manifest = json.loads(tamper_path.read_text())
    tampered_manifest["transactions"][0]["device_id"] = 1
    tamper_path.write_text(json.dumps(tampered_manifest))
    from veritx_dse.core.run_bundle import RunBundleError
    with pytest.raises(
            RunBundleError,
            match="^stored multi-HBM dispatch manifest differs from the "
                  "independently rebuilt artifact ledger$"):
        reproduce_ramulator_run_bundle(tampered)
    stale_engine = tmp_path / "stale-engine"
    shutil.copytree(run_dir, stale_engine)
    stale_manifest_path = stale_engine / "ramulator" / "dispatch-manifest.json"
    stale_manifest = json.loads(stale_manifest_path.read_text())
    stale_manifest["dispatcher"] = "ordered_callback_dispatch_v1"
    stale_manifest_path.write_text(json.dumps(stale_manifest))
    with pytest.raises(RunBundleError, match="V1 dispatcher has an unknown retry policy"):
        reproduce_ramulator_run_bundle(stale_engine)


@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_two_pool_tick_bound_is_inconclusive_and_cannot_normalize(tmp_path):
    graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="bounded", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=70, weight_bytes=35,
                output_bytes=15, input_loc="LOCAL:0",
                weight_loc="LOCAL:1", output_loc="LOCAL:0",
                participant_count=1)),))
    context = _context_with_agents(
        graph, [SimpleNamespace(kind="hbm_controller", count=2)])
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(context, DRAM)
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=tmp_path / "tick-bound",
                                  max_transactions=100,
                                  max_native_ticks=1))
    assert evidence.status == "INCONCLUSIVE"
    assert "exceeded 1 native ticks" in evidence.failure_reason
    with pytest.raises(_sim.RamulatorError, match="INCONCLUSIVE"):
        adapter.normalize(context, DRAM, prepared, evidence)


@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_two_pool_native_queue_backpressure_drains(tmp_path):
    graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="pressure", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=4096, weight_bytes=4096,
                output_bytes=4096, input_loc="LOCAL:0",
                weight_loc="LOCAL:1", output_loc="LOCAL:0",
                participant_count=1)),))
    context = _context_with_agents(
        graph, [SimpleNamespace(kind="hbm_controller", count=2)])
    adapter = RamulatorAdapter()
    prepared = adapter.prepare(context, DRAM)
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=tmp_path / "queue-pressure",
                                  max_transactions=1000,
                                  max_native_ticks=100_000))
    assert evidence.status == "PASS", evidence.failure_reason
    assert evidence.metrics["accepted_requests"]["value"] == 384
    assert evidence.metrics["completed_requests"]["value"] == 384
    assert 0 < evidence.raw["backpressure_retry_attempts"] < 384
    assert evidence.raw["native_tx_bytes"] == 32
    assert evidence.raw["native_tCK_ps"] == 312


@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_two_pool_8ch_profile_uses_distinct_native_groups(tmp_path):
    graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="c0", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=64, weight_bytes=96,
                output_bytes=32, input_loc="LOCAL:0",
                weight_loc="LOCAL:1", output_loc="LOCAL:0",
                participant_count=1)),))
    context = _context_with_agents(
        graph, [SimpleNamespace(kind="hbm_controller", count=2)])
    adapter = RamulatorAdapter(geometry_profile="CERTIFIED_RAMULATOR_HBM3_8CH_V1")
    prepared = adapter.prepare(context, DRAM)
    evidence = adapter.execute(
        prepared, SimpleNamespace(run_dir=tmp_path / "multi-8ch",
                                  max_transactions=100,
                                  max_native_ticks=20_000))
    assert evidence.status == "PASS", evidence.failure_reason
    assert len(evidence.raw["controller_stats"]) == 16
    assert evidence.raw["pool_stats"][0]["native_channels"] == list(range(8))
    assert evidence.raw["pool_stats"][1]["native_channels"] == list(range(8, 16))
    assert sum(c["accepted"]["read"] + c["accepted"]["write"]
               for c in evidence.raw["controller_stats"]) == 6


def _two_pool_graph(inp=128, weight=192, out=64):
    return WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="c0", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=inp, weight_bytes=weight,
                output_bytes=out, input_loc="LOCAL:0", weight_loc="LOCAL:1",
                output_loc="LOCAL:0", participant_count=1)),))


@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_coalesced_write_callback_is_deferred_until_send_returns(tmp_path):
    """A second write to an already-buffered flat address makes Ramulator
    callback synchronously inside send(). The dispatcher must not commit it
    before acceptance, and the native counters must reconcile."""
    import hashlib
    from veritx_dse.workload.memory_lowering import (
        lower_to_ramulator_dispatch,
    )
    context = _context_with_agents(
        _two_pool_graph(inp=32, weight=32, out=32),
        [SimpleNamespace(kind="hbm_controller", count=2)])
    adapter = RamulatorAdapter()
    native = adapter.prepare(context, DRAM).native_prepared
    geometry = certified_geometry()
    manifest = lower_to_ramulator_dispatch(
        native.artifact, geometry, device_ids=native.device_ids,
        native_transaction_bytes=32,
        backend_config_hash=native.backend_config_hash,
        mapping=native.mapping)
    writes = [r for r in manifest["transactions"]
              if r["operation"] == "WRITE"]
    assert len(writes) == 1
    duplicate = dict(writes[0], transaction_id=writes[0]["transaction_id"] + ":dup")
    manifest["transactions"].append(duplicate)
    ledger = manifest["device_ledger"][str(duplicate["device_id"])]
    ledger["write_transactions"] += 1
    ledger["generated_bytes"] += 32
    manifest["counts"]["transactions"] += 1
    manifest["counts"]["write_transactions"] += 1
    manifest["bytes"]["generated_bytes"] += 32
    manifest["bytes"]["padding_bytes"] += 32
    manifest.pop("dispatch_input_hash")
    manifest["dispatch_input_hash"] = "sha256:" + hashlib.sha256(json.dumps(
        manifest, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

    evidence = _sim.execute_dispatch(
        native.artifact, manifest, backend=_sim.discover(),
        run_dir=tmp_path / "coalesced")
    assert evidence.status == "PASS", evidence.failure_reason
    assert evidence.metrics["completed_requests"]["value"] == \
        manifest["counts"]["transactions"]
    assert evidence.metrics["outstanding_requests"]["value"] == 0
    coalesced = sum(c["native_stats"].get("num_write_reqs_coalesced", 0)
                    for c in evidence.raw["controller_stats"])
    assert coalesced == 1, evidence.raw["aggregate_native_stats"]
    callbacks = [e for e in evidence.raw["events"]
                 if e["event"] == "callback"]
    assert len(callbacks) == manifest["counts"]["transactions"]
    assert len({e["transaction_id"] for e in callbacks}) == len(callbacks)
    assert ramulator_evidence_id(evidence) == ramulator_evidence_id(
        _sim.execute_dispatch(
            native.artifact, manifest, backend=_sim.discover(),
            run_dir=tmp_path / "coalesced-again"))


def test_dispatcher_outstanding_override_refused_not_ignored(tmp_path):
    """The outstanding bound is hashed into the config identity, so a
    conflicting request refuses instead of being silently dropped."""
    from veritx_dse.backend.ramulator_adapter import (  # noqa: E402
        RamulatorSemanticRefusal,
    )
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    context = _context_with_agents(
        _two_pool_graph(), [SimpleNamespace(kind="hbm_controller", count=2)])
    prepared = adapter.prepare(context, DRAM)
    with pytest.raises(RamulatorSemanticRefusal, match="outstanding limit"):
        adapter.execute(prepared, SimpleNamespace(
            run_dir=tmp_path / "override", max_transactions=1000,
            max_outstanding=7))


@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_two_pool_federated_leg_archives_and_replays(tmp_path):
    """The full DRAM_TIMING leg on two pools: native run, archival,
    normalization and a replay of the same ordered dispatcher."""
    from veritx_dse.application.evaluation_plan import EvaluationPlanner
    from veritx_dse.application.federated_evaluator import (
        RamulatorRunOptions, _evaluate_ramulator,
    )
    from veritx_dse.backend.registry import default_backend_registry
    from veritx_dse.backend.reproduce_ramulator import (
        reproduce_ramulator_run_bundle,
    )
    context = _context_with_agents(
        _two_pool_graph(), [SimpleNamespace(kind="hbm_controller", count=2)])
    plan = EvaluationPlanner().plan(
        context, (DRAM,), default_backend_registry())
    (row,) = plan.analyses
    assert row.readiness is BackendReadiness.READY
    analysis_dir = tmp_path / "analyses" / "dram_timing"
    analysis_dir.mkdir(parents=True)
    outcome = _evaluate_ramulator(
        context, row, RamulatorAdapter(), RamulatorRunOptions(), analysis_dir)
    assert outcome.status == ANALYSIS_EVALUATED, outcome.reason
    assert outcome.native_summary["status"] == "PASS"
    assert outcome.normalized_evidence is not None
    assert outcome.normalized_evidence.model_fidelity is \
        ModelFidelity.MEMORY_CYCLE_SIMULATION
    assert any("multi-pool" in text
               for text in outcome.normalized_evidence.limitations)
    prepared_doc = json.loads(
        (analysis_dir / "ramulator-inputs" / "prepared.json").read_text())
    assert prepared_doc["device_ids"] == [0, 1]
    assert prepared_doc["dispatch_engine"] == "ordered_callback_dispatch_v2"
    replay = reproduce_ramulator_run_bundle(analysis_dir)
    assert replay["matched"] and replay["status"] == "PASS"


@pytest.mark.skipif(not LIVE, reason="needs VERITX_LIVE_RAMULATOR=1")
def test_live_three_pool_padded_controller_dispatch_replays(tmp_path):
    from veritx_dse.application.federated_evaluator import (
        RamulatorRunOptions, _evaluate_ramulator,
    )
    from veritx_dse.backend.reproduce_ramulator import (
        reproduce_ramulator_run_bundle,
    )
    graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="three", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=32, weight_bytes=32,
                output_bytes=32, input_loc="LOCAL:0",
                weight_loc="LOCAL:1", output_loc="LOCAL:2",
                participant_count=1)),))
    context = _context_with_agents(
        graph, [SimpleNamespace(kind="hbm_controller", count=3)])
    plan = EvaluationPlanner().plan(
        context, (DRAM,), default_backend_registry())
    (row,) = plan.analyses
    assert row.readiness is BackendReadiness.READY
    analysis_dir = tmp_path / "analyses" / "dram_timing"
    analysis_dir.mkdir(parents=True)
    outcome = _evaluate_ramulator(
        context, row, RamulatorAdapter(), RamulatorRunOptions(), analysis_dir)
    assert outcome.status == ANALYSIS_EVALUATED, outcome.reason
    evidence = json.loads((analysis_dir / "ramulator" /
                           "memory-evidence.json").read_text())
    assert evidence["status"] == "PASS", evidence["failure_reason"]
    assert evidence["raw"]["controller_padding"] == {
        "policy": "inactive_power_of_two_tail_v1",
        "active_channels": 3, "native_controller_count": 4,
        "inactive_channels": [3]}
    assert len(evidence["raw"]["controller_stats"]) == 4
    assert evidence["raw"]["controller_stats"][3]["expected"] == {
        "read": 0, "write": 0}
    prepared = json.loads((analysis_dir / "ramulator-inputs" /
                           "prepared.json").read_text())
    assert prepared["device_ids"] == [0, 1, 2]
    replay = reproduce_ramulator_run_bundle(analysis_dir)
    assert replay["matched"] and replay["status"] == "PASS"


def _context_with_agents(graph, agents):
    request = SimpleNamespace(
        design_hash=lambda: "sha256:" + "ab" * 32, agents=agents)
    bundle = SimpleNamespace(resolved_fabric=SimpleNamespace(
        resolved_fabric_hash="sha256:" + "cd" * 32))
    return CanonicalEvaluationContext(
        request=request, compilation=None,
        lowered_workload=SimpleNamespace(unified_traffic_class="default"),
        workload=graph, bundle=bundle)


def test_memory_design_counts_declared_controllers():
    from veritx_dse.backend.ramulator_adapter import (
        memory_design_for_request,  # noqa: E402
    )
    agents = [SimpleNamespace(kind="compute_tile", count=4),
              SimpleNamespace(kind="hbm_controller", count=1)]
    design = memory_design_for_request(SimpleNamespace(agents=agents))
    assert design.hbm_devices == (0,)


def test_memory_design_preserves_declared_multi_hbm_ids():
    from veritx_dse.backend.ramulator_adapter import (  # noqa: E402
        memory_design_for_request,
    )
    design = memory_design_for_request(SimpleNamespace(
        agents=[SimpleNamespace(kind="hbm_controller", count=2)]))
    assert design.hbm_devices == (0, 1)


def test_prepare_preserves_explicit_multi_hbm_operand_placement():
    graph = WorkloadGraph(
        parallelism=ParallelismShape(tp=1, pp=1, ep=1, dp=1),
        participant_count=1,
        operations=(OperationNode(
            operation_id="c0", kind=KIND_COMPUTE,
            detail=compute_detail(
                duration_ns=100, input_bytes=128, weight_bytes=192,
                output_bytes=64, input_loc="LOCAL:0",
                weight_loc="LOCAL:1", output_loc="LOCAL:0",
                participant_count=1)),))
    context = _context_with_agents(
        graph, [SimpleNamespace(kind="hbm_controller", count=2)])
    prepared = RamulatorAdapter().prepare(context, DRAM)
    regions = {r.region_id: r for r in prepared.native_prepared.artifact.regions}
    assert {rid: region.placement.device for rid, region in regions.items()} == {
        "c0.input": 0, "c0.weight": 1, "c0.output": 0}


def test_memory_design_without_agents_block_refuses():
    from veritx_dse.backend.ramulator_adapter import (  # noqa: E402
        memory_design_for_request,
    )
    from veritx_dse.workload.memory_lowering import (  # noqa: E402
        LoweringError,
    )
    with pytest.raises(LoweringError, match="no agents block"):
        memory_design_for_request(SimpleNamespace())


def test_demand_without_declared_hbm_refuses_never_readies(tmp_path):
    """Memory demand against a design with no HBM controller resolves
    against nothing: BLOCKED, never READY on a phantom pool."""
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    context = _context_with_agents(
        _graph(with_memory=True),
        [SimpleNamespace(kind="compute_tile", count=1)])
    assessment = adapter.assess(context, DRAM)
    assert assessment.support is SupportLevel.UNSUPPORTED
    assert assessment.readiness is BackendReadiness.BLOCKED
    assert assessment.reason


def test_multi_hbm_bare_local_refuses_as_ambiguous(tmp_path):
    """Two pools require explicit LOCAL:<id> placement."""
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    context = _context_with_agents(
        _graph(with_memory=True),
        [SimpleNamespace(kind="hbm_controller", count=2)])
    assessment = adapter.assess(context, DRAM)
    assert assessment.support is SupportLevel.UNSUPPORTED
    assert assessment.readiness is BackendReadiness.BLOCKED
    assert "ambiguous" in (assessment.reason or "").lower()


def test_undeclared_hardware_never_readies(tmp_path):
    adapter = RamulatorAdapter(vendor_dir=_vendor_with_ext(tmp_path))
    request = SimpleNamespace(design_hash=lambda: "sha256:" + "ab" * 32)
    bundle = SimpleNamespace(resolved_fabric=SimpleNamespace(
        resolved_fabric_hash="sha256:" + "cd" * 32))
    context = CanonicalEvaluationContext(
        request=request, compilation=None,
        lowered_workload=SimpleNamespace(unified_traffic_class="default"),
        workload=_graph(with_memory=True), bundle=bundle)
    assessment = adapter.assess(context, DRAM)
    assert assessment.readiness is BackendReadiness.BLOCKED
    assert assessment.reason
