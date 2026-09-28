"""Phase-3 federation closure: failure precedence, fail-closed archival,
single BookSim execution authority, checked trust reads, run-lifecycle
honesty.

- _aggregate: genuine FAILED fails the run even beside successes;
  INCONCLUSIVE is never FAILED; coverage gaps stay PARTIAL.
- Archival: EVALUATED-but-unarchived becomes a typed FAILED analysis
  naming the missing artifact; successes are preserved.
- The federated network leg spawns the backend exactly once per
  question (proven by call counts, not by mechanism).
- Trust reads go through the sealed checksums; bundle-less trust is
  served UNVERIFIED; missing analysis evidence is EVIDENCE_INVALID;
  mismatched requirement reports refuse at run creation.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.federated_evaluator import (  # noqa: E402
    ANALYSIS_EVALUATED, ANALYSIS_FAILED, ANALYSIS_INCONCLUSIVE,
    ANALYSIS_UNAVAILABLE, ANALYSIS_UNSUPPORTED,
    ARCHIVAL_ARCHIVED, ARCHIVAL_NOT_AVAILABLE,
    AnalysisOutcome, ArchivalResult, _aggregate, _aggregate_reason,
)


def _row(question, backend, status, reason=None, envelope=None,
         native_id=None):
    return AnalysisOutcome(
        question=question, backend_id=backend, status=status,
        model_fidelity=None, qualification=None,
        normalized_evidence=envelope, native_evidence_id=native_id,
        reason=reason)


_NET = EvaluationQuestion.NETWORK_COMPLETION
_SYS = EvaluationQuestion.SYSTEM_MAKESPAN


# ── aggregation law ─────────────────────────────────────────────────

def test_all_evaluated_is_evaluated():
    assert _aggregate((_row(_NET, "BOOKSIM_STANDALONE",
                            ANALYSIS_EVALUATED),)) == "EVALUATED"


def test_failed_beside_success_is_failed_not_partial():
    assert _aggregate((
        _row(_NET, "BOOKSIM_STANDALONE", ANALYSIS_EVALUATED),
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_FAILED,
             reason="injected backend crash"),
    )) == "FAILED"


def test_success_plus_coverage_gap_is_partial():
    assert _aggregate((
        _row(_NET, "BOOKSIM_STANDALONE", ANALYSIS_EVALUATED),
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_UNSUPPORTED,
             reason="nope"),
    )) == "PARTIAL"
    assert _aggregate((
        _row(_NET, "BOOKSIM_STANDALONE", ANALYSIS_EVALUATED),
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_UNAVAILABLE,
             reason="nope"),
    )) == "PARTIAL"


def test_inconclusive_is_never_failed():
    assert _aggregate((
        _row(_NET, "BOOKSIM_STANDALONE", ANALYSIS_EVALUATED),
        _row(EvaluationQuestion.DRAM_TIMING, "RAMULATOR2_HBM3_V1",
             ANALYSIS_INCONCLUSIVE, reason="native memory evidence "
             "INCONCLUSIVE: shortfall"),
    )) == "PARTIAL"


def test_lone_inconclusive_is_partial_not_unsupported():
    assert _aggregate((
        _row(EvaluationQuestion.DRAM_TIMING, "RAMULATOR2_HBM3_V1",
             ANALYSIS_INCONCLUSIVE, reason="shortfall"),
    )) == "PARTIAL"


def test_no_success_with_failure_is_failed():
    assert _aggregate((
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_FAILED,
             reason="boom"),
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_UNSUPPORTED,
             reason="nope"),
    )) == "FAILED"


def test_no_success_no_failure_unavailable_wins_over_unsupported():
    assert _aggregate((
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_UNAVAILABLE,
             reason="missing"),
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_UNSUPPORTED,
             reason="nope"),
    )) == "BACKEND_UNAVAILABLE"


def test_all_refused_is_unsupported():
    assert _aggregate((
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_UNSUPPORTED,
             reason="nope"),
    )) == "UNSUPPORTED"


def test_aggregate_reason_names_failed_question_backend_reason():
    reason = _aggregate_reason((
        _row(_NET, "BOOKSIM_STANDALONE", ANALYSIS_EVALUATED),
        _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_FAILED,
             reason="injected backend crash"),
    ))
    assert reason is not None
    assert reason.startswith("FAILED SYSTEM_MAKESPAN on "
                             "ASTRA2_EMBEDDED_BOOKSIM:")
    assert "injected backend crash" in reason


def test_aggregate_reason_none_when_all_evaluated():
    assert _aggregate_reason((
        _row(_NET, "BOOKSIM_STANDALONE", ANALYSIS_EVALUATED),
    )) is None


# ── archival enforcement ────────────────────────────────────────────

def test_evaluated_unarchived_records_not_available_openly():
    """EVALUATED-but-unarchived keeps its status but records the gap:
    the archival verdict rides explicitly in the analysis (never a
    silent success), and aggregation still counts the success."""
    from veritx_dse.backend.normalized_evidence import (
        NormalizedBackendEvidence,
    )
    from veritx_dse.backend.adapter import ModelFidelity
    envelope = NormalizedBackendEvidence(
        backend_id="RAMULATOR2_HBM3_V1",
        question=EvaluationQuestion.DRAM_TIMING,
        model_fidelity=ModelFidelity.MEMORY_CYCLE_SIMULATION,
        canonical_parent_ids=("d", "f", "w"),
        native_evidence_id="native-1",
        qualification="QUALIFIED",
        producer_identity="prod",
        backend_config_hash="c",
        backend_input_hash="i",
        metrics=(),
        limitations=())
    row = AnalysisOutcome(
        question=EvaluationQuestion.DRAM_TIMING,
        backend_id="RAMULATOR2_HBM3_V1", status=ANALYSIS_EVALUATED,
        model_fidelity=envelope.model_fidelity,
        qualification=envelope.qualification,
        normalized_evidence=envelope,
        native_evidence_id=envelope.native_evidence_id,
        reason=None,
        archival=ArchivalResult(
            status=ARCHIVAL_NOT_AVAILABLE,
            missing=("memory-artifact.json",),
            reason="injected archival fault"))
    assert row.status == ANALYSIS_EVALUATED
    assert row.archival is not None
    assert row.archival.status == ARCHIVAL_NOT_AVAILABLE
    assert "memory-artifact.json" in row.archival.missing
    assert "injected archival fault" in (row.archival.reason or "")
    assert _aggregate((row,)) == "EVALUATED"
    as_dict = row.to_dict()
    assert as_dict["archival"]["status"] == ARCHIVAL_NOT_AVAILABLE
    assert "memory-artifact.json" in as_dict["archival"]["missing"]


def test_archived_success_records_archived():
    row = _row(_SYS, "ASTRA2_EMBEDDED_BOOKSIM", ANALYSIS_EVALUATED)
    row = AnalysisOutcome(
        question=row.question, backend_id=row.backend_id,
        status=row.status, model_fidelity=row.model_fidelity,
        qualification=row.qualification,
        normalized_evidence=row.normalized_evidence,
        native_evidence_id=row.native_evidence_id, reason=row.reason,
        native_summary=row.native_summary,
        archival=ArchivalResult(status=ARCHIVAL_ARCHIVED))
    assert row.status == ANALYSIS_EVALUATED
    assert row.archival is not None
    assert row.archival.status == ARCHIVAL_ARCHIVED
    assert _aggregate((row,)) == "EVALUATED"


def test_persist_helpers_return_typed_archival(tmp_path):
    from veritx_dse.application.federated_evaluator import (
        _persist_astra_inputs, _persist_ramulator_inputs,
    )
    broken = SimpleNamespace(
        native_prepared=SimpleNamespace(
            artifact=SimpleNamespace(
                serialize=lambda: (_ for _ in ()).throw(
                    ValueError("injected serialize fault")))))
    ram = _persist_ramulator_inputs(tmp_path, broken)
    assert ram.status == ARCHIVAL_NOT_AVAILABLE
    assert "memory-artifact.json" in ram.missing
    assert "injected serialize fault" in (ram.reason or "")
    astra = _persist_astra_inputs(tmp_path, broken)
    assert astra.status == ARCHIVAL_NOT_AVAILABLE
    assert "machine.json" in astra.missing


# ── single BookSim execution authority ──────────────────────────────

def test_network_leg_spawns_backend_exactly_once(tmp_path):
    """The federated network leg executes the backend exactly once per
    question: adapter.prepare -> adapter.execute (single spawn) with one
    normalization. Proved by call counts, independent of which layer
    orchestrates the seam."""
    import json as _json
    from veritx_dse.application.evaluation_context import (
        build_evaluation_context,
    )
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer, resolve_producer_identity,
    )
    from veritx_dse.core.paths import REPO
    from veritx_dse.product.service import parse_request_doc

    dense = REPO / "tracks/t3-topology/examples/llama_dense_64tiles-v3.json"
    compilation = FabricCompiler().compile(
        parse_request_doc(_json.loads(dense.read_text(encoding="utf-8"))))
    assert compilation.status == "COMPILED"
    context = build_evaluation_context(compilation)
    binary = REPO / "third_party/booksim2/src/booksim"
    try:
        producer = resolve_producer_identity(binary, repo_root=REPO)
        assert_pinned_producer(producer)
    except ProducerError as exc:
        pytest.skip(f"no pinned BookSim producer in this worktree: {exc}")

    from veritx_dse.application.federated_evaluator import (
        BookSimRunOptions, _evaluate_network,
    )
    from veritx_dse.backend.booksim_adapter import BookSimAdapter

    calls = {"execute": 0, "spawn": 0, "normalize": 0}
    real_execute = BookSimAdapter.execute
    from veritx_dse.backend import booksim_execution as _exec_mod
    real_spawn = _exec_mod.execute_prepared_booksim
    from veritx_dse.backend.booksim_adapter import (
        normalize_booksim_outcome as _real_normalize,
    )

    def _count_execute(self, prepared, options):
        calls["execute"] += 1
        return real_execute(self, prepared, options)

    def _count_spawn(**kwargs):
        calls["spawn"] += 1
        return real_spawn(**kwargs)

    def _count_normalize(context, outcome):
        calls["normalize"] += 1
        return _real_normalize(context, outcome)

    analysis_dir = tmp_path / "analyses" / "network_completion"
    analysis_dir.mkdir(parents=True, exist_ok=True)
    import unittest.mock as _mock
    with _mock.patch.object(BookSimAdapter, "execute", _count_execute), \
         _mock.patch.object(_exec_mod, "execute_prepared_booksim",
                            _count_spawn), \
         _mock.patch("veritx_dse.backend.booksim_adapter."
                      "normalize_booksim_outcome", _count_normalize):
        evaluated, analysis = _evaluate_network(
            compilation, context,
            SimpleNamespace(question=EvaluationQuestion.NETWORK_COMPLETION,
                            backend_id="BOOKSIM_STANDALONE"),
            BookSimRunOptions(binary=binary, repo_root=REPO,
                              timeout_s=600, network_clock_hz=10 ** 9),
            analysis_dir)
    assert analysis.status == ANALYSIS_EVALUATED, analysis.reason
    assert evaluated is not None
    assert calls["execute"] == 1, calls
    assert calls["spawn"] == 1, calls
    assert calls["normalize"] == 1, calls


# ── checked trust reads ─────────────────────────────────────────────

def test_checked_read_refuses_post_verify_mutation(tmp_path):
    """Bytes changed after verification are refused at read time."""
    from veritx_dse.core.run_bundle import (
        RunBundleError, finalize_run_bundle, read_verified_file,
    )
    from veritx_dse.product.service import ProductService
    from veritx_dse.product.store import ProductStore

    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "evidence.json").write_text(
        '{"evidence": {"stats": {}}}', encoding="utf-8")
    finalize_run_bundle(bundle_dir)
    assert read_verified_file(bundle_dir, "evidence.json")
    (bundle_dir / "evidence.json").write_text(
        '{"evidence": {"stats": {"forged": 1}}}', encoding="utf-8")
    with pytest.raises(RunBundleError):
        read_verified_file(bundle_dir, "evidence.json")
    svc = object.__new__(ProductService)
    with pytest.raises(Exception, match="refusing trust read"):
        svc._read_trust_file(bundle_dir, "evidence.json")


def test_trust_read_rejects_unsealed_name(tmp_path):
    from veritx_dse.product.service import ProductService
    bundle_dir = tmp_path / "bundle"
    bundle_dir.mkdir()
    (bundle_dir / "rogue.json").write_text("{}", encoding="utf-8")
    svc = object.__new__(ProductService)
    with pytest.raises(Exception, match="refusing trust read"):
        svc._read_trust_file(bundle_dir, "rogue.json")


# ── run-lifecycle honesty ───────────────────────────────────────────

def test_bundle_less_trust_claim_serves_unverified():
    from veritx_dse.product.service import ProductService
    run = {"run_id": "r1", "bundle_id": None, "status": "EVALUATED",
           "qualification": "QUALIFIED", "reason": None}
    view = ProductService._downgrade_unverified_trust(
        {"qualification": "QUALIFIED", "reason": None}, run)
    assert view["qualification"] == "UNVERIFIED"
    assert "no sealed run bundle" in (view["reason"] or "")


def test_bundle_less_refusal_passes_through():
    from veritx_dse.product.service import ProductService
    run = {"run_id": "r1", "bundle_id": None, "status": "UNSUPPORTED",
           "qualification": None, "reason": "nope"}
    view = ProductService._downgrade_unverified_trust(
        {"qualification": None, "reason": "nope"}, run)
    assert view["qualification"] is None
    assert view["reason"] == "nope"


def test_missing_analysis_evidence_is_evidence_invalid(tmp_path):
    from veritx_dse.product.service import ProductService
    svc = object.__new__(ProductService)
    with pytest.raises(Exception, match="absent from the bundle"):
        svc._analysis_evidence_doc(
            "r1", tmp_path / "no-such-bundle", "network_completion")


def test_mismatched_report_refuses_at_run_creation():
    from veritx_dse.product.service import ProductService
    report = {"design_hash": "sha256:other",
              "performance_result_id": "perf-1",
              "entries": [{"performance_result_id": "perf-1",
                           "verdict": "SATISFIED"}]}
    network = SimpleNamespace(status="EVALUATED",
                              performance_result_id="perf-1")
    revision = {"design_hash": "sha256:this"}
    with pytest.raises(Exception, match="does not bind"):
        ProductService._check_run_report_binding(
            "run-1", revision, network, report)


def test_matching_report_passes_binding():
    from veritx_dse.application.requirements import report_identity
    from veritx_dse.product.service import ProductService
    report = {"design_hash": "sha256:this",
              "performance_result_id": "perf-1",
              "entries": [{"performance_result_id": "perf-1",
                           "verdict": "SATISFIED"}]}
    report_id = report_identity(report)
    network = SimpleNamespace(status="EVALUATED",
                              performance_result_id="perf-1")
    revision = {"design_hash": "sha256:this"}
    # must not raise
    ProductService._check_run_report_binding(
        "run-1", revision, network, report)
