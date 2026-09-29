"""Federated optimization backend-neutrality: non-network studies are real.

Hole (a): RealCandidateEvaluator runs ASTRA-only / Ramulator-only studies
with binary=None (only NETWORK_COMPLETION legs need the BookSim binary);
a network question with binary=None refuses at construction.

Hole (b): Pareto eligibility binds per-objective authentic evidence, not
performance_result_id. A design carrying binding NETWORK requirements can
still be Pareto-eligible in a non-network study: the network requirement
is out of the study's answerable scope, so it stays visibly unevaluated
(product_requirements_satisfied None, never True) instead of poisoning
measured objectives. Explicit NOT_EVALUATED marks still poison every
study; network studies still demand the bound report.
"""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(DSE / "tests"))

from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.model.compile_model import (  # noqa: E402
    RequirementApplicability,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    DomainParam, Objective, OptimizationDefinition,
)
from veritx_dse.optimization.real_evaluator import (  # noqa: E402
    EvaluationError, RealCandidateEvaluator,
)
from veritx_dse.optimization.result import (  # noqa: E402
    CertifiedBackendConfig, Optimizer,
)
from test_federated_optimizer import (  # noqa: E402
    _base, _scripted_registry,
)

SYSTEM = EvaluationQuestion.SYSTEM_MAKESPAN
DRAM = EvaluationQuestion.DRAM_TIMING
NETWORK = EvaluationQuestion.NETWORK_COMPLETION


def _certified_port(config, definition, registry):
    from veritx_dse.optimization import result as R  # noqa: E402

    real_cls = RealCandidateEvaluator
    orig = R._make_real_certified_evaluator

    def patched(cfg, defn=None):
        return real_cls(
            binary=cfg.binary, run_root=cfg.run_root,
            network_clock_hz=cfg.network_clock_hz, timeout_s=30,
            repo_root=None,
            objectives=tuple(defn.objectives) if defn is not None else None,
            registry=registry, require_quiescence=True)

    R._make_real_certified_evaluator = patched
    try:
        return Optimizer().optimize_certified(
            _base(), definition, backend_config=config)
    finally:
        R._make_real_certified_evaluator = orig


def _run(tmp_path, *, objectives, questions_binary_none=True):
    registry, _, _ = _scripted_registry()
    definition = OptimizationDefinition(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=tuple(objectives))
    config = CertifiedBackendConfig(
        binary=None, run_root=str(tmp_path / "runs"),
        network_clock_hz=10 ** 9)
    return _certified_port(config, definition, registry)


def test_astra_only_study_needs_no_booksim_binary(tmp_path):
    """Hole (a): no BookSim binary anywhere, ASTRA-only study evaluates."""
    res = _run(tmp_path, objectives=(
        Objective("system_makespan_cycles", "MIN", question=SYSTEM),))
    assert all(r.evaluation_status == "EVALUATED" for r in res.records)
    assert res.pareto_ids, "measured authentic evidence must be eligible"


def test_ramulator_only_study_needs_no_booksim_binary(tmp_path):
    res = _run(tmp_path, objectives=(
        Objective("average_read_latency_cycles", "MIN", question=DRAM),))
    assert all(r.evaluation_status == "EVALUATED" for r in res.records)
    assert res.pareto_ids


def test_mixed_astra_dram_study_eligible_without_network(tmp_path):
    res = _run(tmp_path, objectives=(
        Objective("average_read_latency_cycles", "MIN", question=DRAM),
        Objective("system_makespan_cycles", "MIN", question=SYSTEM)))
    assert all(r.evaluation_status == "EVALUATED" for r in res.records)
    assert res.pareto_ids


def test_binding_network_requirement_stays_visibly_unevaluated(tmp_path):
    """Hole (b): the base design's binding latency requirement does not
    poison the frontier, and is never shown as satisfied either."""
    res = _run(tmp_path, objectives=(
        Objective("system_makespan_cycles", "MIN", question=SYSTEM),))
    assert res.pareto_ids
    for record in res.records:
        if record.pareto_eligible:
            assert record.product_requirements_satisfied is None


def test_explicit_not_evaluated_still_poisons(tmp_path):
    """An explicit NOT_EVALUATED mark wins over question scoping."""
    import veritx_dse.optimization.result as R  # noqa: E402

    registry, _, _ = _scripted_registry()
    base = _base()
    reqs = tuple(
        replace(r, applicability=RequirementApplicability.NOT_EVALUATED)
        for r in base.requirements)
    assert reqs, "base fixture must carry a binding requirement"
    real_cls = RealCandidateEvaluator
    orig = R._make_real_certified_evaluator

    def patched(cfg, defn=None):
        return real_cls(
            binary=None, run_root=cfg.run_root,
            network_clock_hz=cfg.network_clock_hz, timeout_s=30,
            repo_root=None,
            objectives=tuple(defn.objectives) if defn is not None else None,
            registry=registry, require_quiescence=True)

    R._make_real_certified_evaluator = patched
    try:
        res = Optimizer().optimize_certified(
            replace(base, requirements=reqs),
            OptimizationDefinition(
                domain=(DomainParam("link_width", (64, 128)),),
                objectives=(Objective(
                    "system_makespan_cycles", "MIN", question=SYSTEM),)),
            backend_config=CertifiedBackendConfig(
                binary=None, run_root=str(tmp_path / "runs"),
                network_clock_hz=10 ** 9))
    finally:
        R._make_real_certified_evaluator = orig
    assert res.pareto_ids == ()
    assert all(not r.pareto_eligible for r in res.records)
    assert all("NOT_EVALUATED" in (r.eligibility_reason or "")
               for r in res.records)


def test_network_question_without_binary_refuses(tmp_path):
    """Hole (a) boundary: NETWORK_COMPLETION with binary=None fails loud."""
    registry, _, _ = _scripted_registry()
    with pytest.raises(EvaluationError, match="backend binary"):
        RealCandidateEvaluator(
            binary=None, run_root=str(tmp_path / "runs"),
            network_clock_hz=10 ** 9, timeout_s=30,
            objectives=(Objective("completion_cycles", "MIN"),),
            registry=registry)
