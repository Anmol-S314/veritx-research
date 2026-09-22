"""P1-RT.A8 — mandatory adversarial suite for optimization truth.

One test per mandated case:

 1 real evaluator + missing objective -> UNMEASURABLE/ineligible, no KeyError
 2 missing-objective candidate never Pareto
 3 report identity carried into CandidateRecord
 4 changing verdict/authority changes report identity
 5 transplanted requirement provenance refuses (or moves result identity)
 6 product requirements vs optimization constraints stay separate
 7 VIOLATED survives the study view
 8 UNMEASURABLE survives the study view
 9 duplicate same-metric constraints do not overwrite
10 duplicate objective declaration refuses
11 same evaluator object, same candidate, twice
12 same CLI run root twice immediately, no sleep
13 repeated runs preserve candidate/design identity
14 repeated runs allocate distinct slots

Real-BookSim tests use the vendored binary through the qualified
producer; everything else uses stub ports so the adversarial property is
isolated from backend behavior.

RT-final A4 attacks (final repair, half 2):

 6  unregistered objective with a numeric evaluator value ->
    UNMEASURABLE, ineligible, never Pareto (constraint variant too)
 7  registered metric with an evaluator value different from the
    proof's extracted value -> refuses
 8  real FabricEvaluator execution authenticates and stays eligible
 9  requirement violation stays EVALUATED but ineligible
    (`test_ap02_requirement_violation_stays_evaluated`)
10  BookSimError stays FAILED
    (`test_ap02_backend_failed_preserved_into_record`)
11  arbitrary programmer error escapes the verifier taxonomy
12  `python -O` cannot bypass the proof/registry gates

A3 attacks (self-declared certified double, fabricated report over a
genuine proof, empty report vacuity) remain in place.

RT-final v2 boundary corrections:

 C1  subclass factory override cannot hijack the certified evaluator
 C2  certified registry not caller-selectable; registry identity binds
     declared producer semantics and is bound into the result
 C3  quiescence is mandatory for CERTIFIED_PRODUCT (not a config knob)
"""
from __future__ import annotations

import argparse
import hashlib
import json

import pytest

from test_p1_optimize_booksim import _fixture as _cli_fixture
from test_p2_real_adapter import _base as _real_base
from test_p2_real_adapter import _port as _real_port
from test_p2_real_adapter import _pp_request

from p2_verified_support import (  # noqa: E402
    TEST_METRIC_REGISTRY,
    certified_evaluation,
    run_certified_mechanics_for_tests,
)


def _optimize(base, defn, port):
    """Adversarial-study helper: certified test doubles drive the
    CERTIFIED pipeline with the test-owned FROZEN registry (R1/R2); real
    ports drive the certified pipeline with the production registry;
    everything else uses the analytic entry point."""
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY,
    )
    from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
    if getattr(port, "certified_pipeline", False):
        return run_certified_mechanics_for_tests(base, defn, port,
                                            TEST_METRIC_REGISTRY)
    if isinstance(port, RealCandidateEvaluator):
        return Optimizer()._optimize(base, defn, port,
                                     certified_mode=True,
                                     metric_registry=CERTIFIED_METRIC_REGISTRY)
    return Optimizer().optimize_with_port(base, defn, port)

from veritx_dse.application.requirements import report_identity
from veritx_dse.optimization.constraints import (
    ConstraintError,
    evaluate_all,
)
from veritx_dse.optimization.definition import (
    Constraint,
    DomainParam,
    Objective,
    OptimizationDefinition,
    OptimizationDefinitionError,
)
from veritx_dse.optimization.evaluators import (
    AUTHORITY_ANALYTIC_FAKE,
    AUTHORITY_CERTIFIED_BACKEND,
    CandidateEvaluation,
    FakeDeterministicEvaluator,
)
from veritx_dse.optimization.result import (
    OptimizationResultError,
    Optimizer,
)


# ── stub ports ───────────────────────────────────────────────────────────

def _report_for(design_hash: str, *, verdict: str = "SATISFIED",
                authority: str = "test", perf: str = "perf:fixed") -> dict:
    return {
        "contract_version": 1,
        "design_hash": design_hash,
        "performance_result_id": perf,
        "entries": [{
            "requirement_index": 0,
            "traffic_class": "tp_collective",
            "qos_class": "latency_critical",
            "verdict": verdict,
            "binding": True,
            "required": 600.0,
            "measured": 10.0,
            "metric_authority": authority,
            "performance_result_id": perf,
            "reason": "adversarial-suite",
        }],
    }


class _StubPort:
    """EVALUATED candidate with given values and an optional report.

    A3: this is deliberately the SELF-DECLARED certified double — it
    labels itself ``certified-backend``, makes up a
    ``performance_result_id`` and fabricates a locally consistent
    RequirementReport, without carrying the verified performance result
    that is the actual proof. It exists only so the adversarial test can
    prove such a claim is REFUSED; use ``_VerifiedStubPort`` when a test
    needs a genuinely certified candidate.
    """

    def __init__(self, values, *, report_verdict=None, authority="test",
                 evaluation_authority=AUTHORITY_CERTIFIED_BACKEND):
        self.values = values
        self.report_verdict = report_verdict
        self.authority = authority
        self.evaluation_authority = evaluation_authority

    def evaluate(self, candidate):
        report = None
        if self.report_verdict is not None:
            report = _report_for(
                "sha256:" + candidate.request.design_hash(),
                verdict=self.report_verdict, authority=self.authority)
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values=dict(self.values),
            locked_consequences={},
            performance_result_id="perf:fixed" if report else None,
            requirement_report=report,
            requirement_report_id=(report_identity(report)
                                   if report is not None else None),
            evaluation_authority=self.evaluation_authority)


class _VerifiedStubPort:
    """Certified port that carries REAL proof (A3/R1 test seam).

    Same observable shape as _StubPort — EVALUATED candidates with the
    given objective values — but every candidate carries the exact
    lowered WorkloadGraph and a genuinely verified performance result,
    and the report is the one the Optimizer independently re-derives
    from them. ``cycles`` chooses the report verdict against the base
    request's latency ceiling (100 cycles -> SATISFIED; 2e9 -> VIOLATED).
    """

    certified_pipeline = True

    def __init__(self, values, *, cycles=100):
        self.values = values
        self.cycles = cycles

    def evaluate(self, candidate):
        return certified_evaluation(
            candidate, cycles=self.cycles,
            objective_values=dict(self.values))


class _ForeignReportPort:
    """Returns another design's report under this candidate's identity."""

    def evaluate(self, candidate):
        foreign = "ab" * 32
        return CandidateEvaluation(
            candidate_id=candidate.candidate_id,
            design_hash=candidate.request.design_hash(),
            status="EVALUATED",
            objective_values={"latency": 10.0},
            locked_consequences={},
            performance_result_id="perf:foreign",
            requirement_report=_report_for("sha256:" + foreign,
                                           perf="perf:foreign"),
            requirement_report_id="forged")


def _defn(**kw):
    base = dict(
        domain=(DomainParam("link_width", (32, 128)),),
        objectives=(Objective("latency", "MIN"),),
        method="grid")
    base.update(kw)
    return OptimizationDefinition(**base)


# ── 1-2: missing objective with the REAL evaluator ──────────────────────

def test_ap01_fake_v2_pareto_refusal_for_authority():
    """A-P0.1: an analytic fake evaluation is visible but structurally
    ineligible in the authoritative v2 view — no Pareto, no selection."""
    result = _optimize(
        _real_base(), _defn(), FakeDeterministicEvaluator(seed=7))
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    assert "analytic-fake" in (result.selection_rationale or "")
    view = result.to_study_view()
    assert view["contract_version"] == 2
    assert view["pareto_ids"] == []
    assert view["selected_candidate_id"] is None
    for cand in view["candidates"]:
        assert cand["evaluation_authority"] == AUTHORITY_ANALYTIC_FAKE
        assert cand["pareto_eligible"] is False
        assert cand["pareto_member"] is False
        assert cand["eligibility_reason"]
        assert "analytic-fake" in cand["eligibility_reason"]
    # The same candidate mechanics with REAL proof (carried verified
    # performance result + re-derivable report) do reach the frontier:
    # the refusal is proof-driven, not a broken study.
    certified = _optimize(
        _real_base(), _defn(), _VerifiedStubPort({"latency": 10.0}))
    assert certified.pareto_ids
    assert certified.selected_candidate_id in certified.pareto_ids


def test_self_declared_certified_evaluator_cannot_enter_authoritative_pareto():
    """A3 mandatory: a self-declared certified evaluator is REFUSED.

    This is precisely the double the suite used to admit into Pareto:
    status EVALUATED, evaluation_authority 'certified-backend', a
    made-up performance_result_id, a locally consistent
    RequirementReport and finite objective values — but no verified
    performance result. The label is descriptive; the proof is B's
    boundary, so the optimizer refuses before any Pareto indexing.
    """
    from veritx_dse.optimization.candidate import make_candidate

    fake = _StubPort({"latency": 10.0}, report_verdict="SATISFIED")
    probe = make_candidate(_real_base(), {"link_width": 64})
    out = fake.evaluate(probe)
    assert out.status == "EVALUATED"
    assert out.evaluation_authority == AUTHORITY_CERTIFIED_BACKEND
    assert out.performance_result_id == "perf:fixed"  # made up
    assert out.requirement_report["entries"]  # locally consistent
    assert out.objective_values == {"latency": 10.0}  # finite
    assert out.verified_performance_result is None
    assert out.workload is None
    with pytest.raises(OptimizationResultError,
                       match="verified performance result"):
        _optimize(_real_base(), _defn(), fake)
    # Positive control: genuinely proven certified evaluations still
    # reach authoritative Pareto in the same study shape.
    genuine = _optimize(
        _real_base(), _defn(), _VerifiedStubPort({"latency": 10.0}))
    assert genuine.pareto_ids


def test_empty_requirement_report_is_never_a_vacuous_pass():
    """A3: report_passes() refuses an empty entry set explicitly.

    An empty report is evidence for nothing (it cannot be distinguished
    from a fabricated empty stand-in), so "no entries => not satisfied"
    — never a vacuous success."""
    from veritx_dse.application.requirements import report_passes

    assert report_passes({"entries": []}) is False
    assert report_passes({}) is False
    assert report_passes(_report_for("sha256:" + "ab" * 32)) is True


def test_fabricated_report_over_genuine_verified_result_refuses():
    """A3: carrying B's proof is necessary but not sufficient — the
    carried report must be the one Worker B's verifier derives.

    A port that keeps the genuine authenticated proof and rewrites the
    verdict (while keeping the report internally consistent) is refused
    by the derived-claims comparison, not by the authority label."""
    import dataclasses

    class _FabricatedVerdict(_VerifiedStubPort):
        def evaluate(self, candidate):
            ev = super().evaluate(candidate)
            report = json.loads(json.dumps(ev.requirement_report))
            for entry in report["entries"]:
                entry["verdict"] = "VIOLATED"
                entry["measured"] = float(entry["required"]) + 1.0
            return dataclasses.replace(
                ev, requirement_report=report,
                requirement_report_id=report_identity(report))

    with pytest.raises(OptimizationResultError,
                       match="authenticated proof derives"):
        _optimize(
            _real_base(), _defn(),
            _FabricatedVerdict({"latency": 10.0}))


def test_6_unregistered_objective_with_evaluator_value_is_unmeasurable_never_pareto():
    """A4 attack 6: a numeric evaluator value for an UNREGISTERED metric
    is not a certified measurement. The requested objective is typed
    UNMEASURABLE, the candidate is ineligible, and nothing enters Pareto
    (no KeyError)."""
    result = _optimize(
        _real_base(),
        _defn(objectives=(Objective("magic_score", "MIN"),)),
        _VerifiedStubPort({"magic_score": 999999.0}))
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    for r in result.records:
        assert r.evaluation_status == "EVALUATED"
        assert r.pareto_eligible is False
        assert r.pareto_member is False
        assert "magic_score" not in r.objective_values
        assert r.objective_availability["magic_score"] == "UNMEASURABLE"
        entry = next(dict(d) for d in r.objective_details
                     if d["metric"] == "magic_score")
        assert entry["state"] == "UNMEASURABLE"
        assert "no registered metric authority" in entry["reason"]
        assert "without a registered metric authority" in \
            (r.eligibility_reason or "")
    # The same rule binds optimization constraints: an unregistered
    # constraint metric is UNMEASURABLE, never scored from the port.
    constrained = _optimize(
        _real_base(),
        _defn(constraints=(Constraint("magic_score", "<=", 5.0),)),
        _VerifiedStubPort({"magic_score": 1.0}))
    assert constrained.pareto_ids == ()
    assert constrained.selected_candidate_id is None
    for r in constrained.records:
        assert r.constraint_verdicts["magic_score"] == "UNMEASURABLE"
        assert r.constraints_satisfied is not True
        assert r.pareto_eligible is False


def test_7_registered_metric_misreport_refuses():
    """A4 attack 7: for a registered metric the proof's extracted value
    is authoritative; an evaluator value that disagrees refuses."""
    port = _VerifiedStubPort({"completion_cycles": 12345.0}, cycles=100)
    with pytest.raises(OptimizationResultError, match="misreported"):
        _optimize(
            _real_base(),
            _defn(objectives=(Objective("completion_cycles", "MIN"),)),
            port)


def test_8_real_fabric_evaluator_execution_authenticates_and_stays_eligible(
        tmp_path):
    """A4/R1 attack 3+8: the PUBLIC certified entry point
    (``Optimizer.optimize_certified``, which owns RealCandidateEvaluator)
    authenticates a genuine FabricEvaluator/BookSim execution and stays
    Pareto-eligible."""
    from veritx_dse.core.paths import REPO
    from veritx_dse.optimization.candidate import make_candidate
    from veritx_dse.optimization.result import CertifiedBackendConfig
    from veritx_dse.simulation.booksim import find_booksim_bin

    # Port-level: the real adapter carries the authenticated proof.
    port = _real_port(tmp_path)
    out = port.evaluate(make_candidate(_real_base(), {"link_width": 64}))
    assert out.status == "EVALUATED"
    proof = out.authenticated_proof
    assert proof is not None
    assert proof.producer_identity
    assert proof.binding.evidence_sha256 == proof.evidence_ref.sha256
    assert proof.verified_result["resource_id"] == \
        out.performance_result_id
    # Public certified entry point (optimizer-owned evaluator).
    result = Optimizer().optimize_certified(
        _real_base(),
        _defn(objectives=(Objective("completion_cycles", "MIN"),)),
        backend_config=CertifiedBackendConfig(
            binary=str(find_booksim_bin(REPO)),
            run_root=str(tmp_path / "certified-runs"),
            network_clock_hz=10 ** 9, timeout_s=600))
    assert result.result_class == "CERTIFIED_PRODUCT"
    assert result.pareto_ids
    assert result.selected_candidate_id in result.pareto_ids


def test_r1_synthetic_evidence_cannot_enter_certified_entry_point():
    """R1 attack 1: fully self-consistent synthetic evidence produced
    without FabricEvaluator cannot enter the certified entry point.

    The synthetic proof (persisted evidence bytes + real builder +
    verifier) is refused by the analytic entry point, and the certified
    entry point accepts no evaluator/port at all — the optimizer owns it.
    """
    import inspect

    port = _VerifiedStubPort({"latency": 10.0})
    with pytest.raises(OptimizationResultError,
                       match="verified performance result"):
        Optimizer().optimize_with_port(_real_base(), _defn(), port)
    params = inspect.signature(Optimizer.optimize_certified).parameters
    assert "evaluator" not in params
    assert "port" not in params
    assert "backend_config" in params
    # The certified entry refuses a port masquerading as its config.
    with pytest.raises(OptimizationResultError, match="CertifiedBackendConfig"):
        Optimizer().optimize_certified(_real_base(), _defn(),
                                       backend_config=port)


def test_r1_optimize_with_port_is_research_only_never_certified():
    """R1 attack 4: the analytic entry point still works for research
    and can never produce certified Pareto."""
    result = Optimizer().optimize_with_port(
        _real_base(), _defn(), FakeDeterministicEvaluator(seed=7))
    assert result.result_class == "ANALYTIC_RESEARCH"
    assert result.records
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    view = result.to_study_view()
    assert view["result_class"] == "ANALYTIC_RESEARCH"
    assert view["pareto_ids"] == []


def test_11_arbitrary_programmer_error_escapes(monkeypatch):
    """A4 attack 11: only the documented refusal taxonomy is caught; an
    unexpected programming error in the verifier authority escapes."""
    import veritx_dse.optimization.result as result_module

    def _bug(request, proof):
        raise KeyError("injected programming bug")

    monkeypatch.setattr(result_module,
                        "verify_authenticated_backend_evaluation", _bug)
    with pytest.raises(KeyError):
        _optimize(
            _real_base(), _defn(), _VerifiedStubPort({"latency": 10.0}))


def test_12_python_O_cannot_bypass_the_eligibility_gates():
    """A4 attack 12: the proof/registry gates are explicit conditionals,
    not asserts — they survive ``python -O``. Static audit plus a real
    ``-O`` subprocess run of the named attacks."""
    import ast
    import os
    import subprocess
    import sys
    from pathlib import Path

    dse = Path(__file__).resolve().parents[1]
    for relative in ("veritx_dse/optimization/result.py",
                     "veritx_dse/application/authenticated_evaluation.py"):
        source = (dse / relative).read_text()
        asserts = [node.lineno for node in ast.walk(ast.parse(source))
                   if isinstance(node, ast.Assert)]
        assert asserts == [], (relative, asserts)
    env = dict(os.environ)
    pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(dse) + (os.pathsep + pypath if pypath else "")
    proc = subprocess.run(
        [sys.executable, "-O", "-m", "pytest", "-q",
         "-p", "no:cacheprovider",
         "tests/test_p2_optimization_truth.py::"
         "test_self_declared_certified_evaluator_cannot_enter_"
         "authoritative_pareto",
         "tests/test_p2_optimization_truth.py::"
         "test_r1_synthetic_evidence_cannot_enter_certified_entry_point",
         "tests/test_p2_optimization_truth.py::"
         "test_r1_optimize_with_port_is_research_only_never_certified",
         "tests/test_p2_optimization_truth.py::"
         "test_c1_subclass_cannot_hijack_the_certified_evaluator",
         "tests/test_p2_optimization_truth.py::"
         "test_c2_certified_registry_is_not_caller_selectable",
         "tests/test_p2_optimization_truth.py::"
         "test_c2_registry_identity_binds_declared_producer_semantics",
         "tests/test_p2_optimization_truth.py::"
         "test_c3_quiescence_is_mandatory_for_certified",
         "tests/test_p2_optimization_truth.py::"
         "test_r2_certified_registry_is_frozen_and_experimental_is_"
         "isolated",
         "tests/test_p2_optimization_truth.py::"
         "test_6_unregistered_objective_with_evaluator_value_is_"
         "unmeasurable_never_pareto",
         "tests/test_p2_optimization_truth.py::"
         "test_7_registered_metric_misreport_refuses"],
        cwd=str(dse), capture_output=True, text=True, timeout=900,
        env=env)
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_r2_certified_registry_is_frozen_and_experimental_is_isolated():
    """R2 attack 2: no runtime mutation of the certified registry.

    Registration either refuses (builder duplicate) or affects only an
    explicitly non-certified plugin registry, which the certified path
    refuses — it can never yield CERTIFIED_PRODUCT Pareto."""
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY,
        CertifiedMetricRegistry,
        ExperimentalMetricRegistry,
        MetricRegistryBuilder,
        MetricRegistryError,
    )

    # The frozen registry exposes no mutation API; its producer mapping
    # is read-only.
    assert not hasattr(CERTIFIED_METRIC_REGISTRY, "register")
    assert not hasattr(CERTIFIED_METRIC_REGISTRY, "unregister")
    before = CERTIFIED_METRIC_REGISTRY.registry_id()
    with pytest.raises(TypeError):
        CERTIFIED_METRIC_REGISTRY.authorities["magic_score"] = \
            lambda verified: 1e-6
    # A plugin registry may register/replace freely — isolated from the
    # certified authority.
    experimental = ExperimentalMetricRegistry("plugin-v1")
    experimental.register("completion_cycles", lambda verified: 1.0)
    experimental.register("magic_score", lambda verified: 1e-6)
    assert experimental.extract("completion_cycles", {}) == 1.0
    assert CERTIFIED_METRIC_REGISTRY.registry_id() == before
    assert not CERTIFIED_METRIC_REGISTRY.has_metric("magic_score")
    # The certified extraction path refuses an experimental registry.
    with pytest.raises(OptimizationResultError,
                       match="CertifiedMetricRegistry"):
        _optimize_registry(
            _real_base(), _defn(),
            _VerifiedStubPort({"latency": 10.0}), experimental)
    # A builder-produced frozen registry is a NEW identity/version; the
    # certified global is untouched.
    built = (MetricRegistryBuilder("test-v2",
                                   base=CERTIFIED_METRIC_REGISTRY)
             .register("latency", lambda verified: 1.0,
                       producer_id="test-latency")
             .freeze())
    assert isinstance(built, CertifiedMetricRegistry)
    assert built.registry_id() != CERTIFIED_METRIC_REGISTRY.registry_id()
    assert built.has_metric("latency")
    assert not CERTIFIED_METRIC_REGISTRY.has_metric("latency")
    with pytest.raises(MetricRegistryError, match="already registered"):
        (MetricRegistryBuilder("dup")
         .register("x", lambda verified: 1, producer_id="x")
         .register("x", lambda verified: 2, producer_id="x"))


def _optimize_registry(base, defn, port, registry):
    return run_certified_mechanics_for_tests(base, defn, port, registry)


def test_c1_subclass_cannot_hijack_the_certified_evaluator(tmp_path):
    """C1 attack 1: the certified evaluator factory is a module-private
    function, not an overridable method. A subclass override is never
    consulted, the real evaluator runs, and no synthetic port can
    manufacture certified eligibility."""
    from veritx_dse.optimization.result import CertifiedBackendConfig

    calls = []

    class _Hijack(Optimizer):
        def _build_certified_evaluator(self, backend_config):
            calls.append(backend_config)
            return _VerifiedStubPort({"latency": 10.0})

    result = _Hijack().optimize_certified(
        _real_base(),
        _defn(objectives=(Objective("completion_cycles", "MIN"),)),
        backend_config=CertifiedBackendConfig(
            binary="/no-such-booksim", run_root=str(tmp_path / "hijack")))
    assert calls == []  # the override was never consulted
    assert result.result_class == "CERTIFIED_PRODUCT"
    assert result.pareto_ids == ()
    for r in result.records:
        assert r.evaluation_status == "BACKEND_UNAVAILABLE"
        assert r.pareto_eligible is False


def test_c2_certified_registry_is_not_caller_selectable():
    """C2 attack 2: the public certified entry point has no registry
    parameter; a caller-minted registry (e.g. magic_score) cannot reach
    certified execution."""
    import inspect

    from veritx_dse.optimization.metric_registry import (
        ExperimentalMetricRegistry,
    )
    from veritx_dse.optimization.result import CertifiedBackendConfig

    params = inspect.signature(Optimizer.optimize_certified).parameters
    assert "metric_registry" not in params
    with pytest.raises(TypeError):
        Optimizer().optimize_certified(
            _real_base(), _defn(),
            backend_config=CertifiedBackendConfig(
                binary="/no-such-booksim", run_root="/tmp/x"),
            metric_registry=ExperimentalMetricRegistry("plugin-v1"))


def test_c2_registry_identity_binds_declared_producer_semantics():
    """C2 attack 3: registry_id() binds metric + producer_id +
    semantics_version; the result binds the registry identity and a
    semantics change moves result_id()."""
    from veritx_dse.optimization.metric_registry import (
        CERTIFIED_METRIC_REGISTRY,
        MetricRegistryBuilder,
    )

    def _same(verified):
        return 10.0

    def _build(producer_id):
        return (MetricRegistryBuilder("same-version",
                                      base=CERTIFIED_METRIC_REGISTRY)
                .register("latency", _same, producer_id=producer_id)
                .freeze())

    reg_a = _build("sem-a")
    reg_a2 = _build("sem-a")   # same declared semantics
    reg_b = _build("sem-b")    # different declared semantics
    assert reg_a.registry_id() != reg_b.registry_id()
    assert reg_a.registry_id() == reg_a2.registry_id()

    def _run(registry):
        return run_certified_mechanics_for_tests(
            _real_base(), _defn(), _VerifiedStubPort({"latency": 10.0}),
            registry)

    res_a = _run(reg_a)
    res_a2 = _run(reg_a2)
    res_b = _run(reg_b)
    assert res_a.metric_registry_id == reg_a.registry_id()
    assert res_a.metric_registry_version == "same-version"
    assert res_a.result_id() == res_a2.result_id()
    assert res_a.result_id() != res_b.result_id()
    view = res_a.to_study_view()
    assert view["metric_registry_id"] == reg_a.registry_id()
    assert view["metric_registry_version"] == "same-version"


def test_c3_quiescence_is_mandatory_for_certified():
    """C3 attack 4: quiescence is not a certified config knob; certified
    execution always requires it, so a caller cannot disable a
    certification obligation and still be certified."""
    import dataclasses

    from veritx_dse.optimization.result import (
        CertifiedBackendConfig,
        _make_real_certified_evaluator,
    )

    names = {f.name for f in dataclasses.fields(CertifiedBackendConfig)}
    assert "require_quiescence" not in names
    with pytest.raises(TypeError):
        CertifiedBackendConfig(binary="x", run_root="y",
                               require_quiescence=False)
    evaluator = _make_real_certified_evaluator(
        CertifiedBackendConfig(binary="/no-such-booksim", run_root="/tmp/x"))
    assert evaluator.require_quiescence is True


def test_1_missing_objective_unmeasurable_ineligible_no_keyerror(tmp_path):
    result = _optimize(
        _real_base(), _defn(objectives=(Objective("area", "MIN"),)),
        _real_port(tmp_path))
    assert len(result.records) == 2
    for record in result.records:
        assert record.evaluation_status == "EVALUATED"
        assert record.pareto_eligible is False
        assert record.objective_availability["area"] == "UNMEASURABLE"
        assert "area" not in record.objective_values
        entries = [dict(d) for d in record.objective_details
                   if d["metric"] == "area"]
        assert entries and entries[0]["state"] == "UNMEASURABLE"


def test_2_missing_objective_candidate_never_pareto(tmp_path):
    result = _optimize(
        _real_base(), _defn(objectives=(Objective("area", "MIN"),)),
        _real_port(tmp_path))
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    assert all(r.pareto_member is False for r in result.records)
    assert "area" in (result.selection_rationale or "")


def test_ap02_backend_unavailable_preserved_into_record(tmp_path):
    """A-P0.2: a backend-unavailable outcome keeps its own status through
    the real adapter and the Optimizer (never collapsed to UNSUPPORTED)."""
    from veritx_dse.optimization.candidate import make_candidate
    from veritx_dse.optimization.real_evaluator import (
        RealCandidateEvaluator,
    )
    port = RealCandidateEvaluator(
        binary="/no-such-booksim", run_root=str(tmp_path / "runs"),
        network_clock_hz=10 ** 9, timeout_s=60)
    out = port.evaluate(make_candidate(_real_base(), {"link_width": 64}))
    assert out.status == "BACKEND_UNAVAILABLE"
    assert out.evaluation_authority == AUTHORITY_CERTIFIED_BACKEND
    assert out.performance_result_id is None
    result = _optimize(_real_base(), _defn(), port)
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    for r in result.records:
        assert r.evaluation_status == "BACKEND_UNAVAILABLE"
        assert r.pareto_eligible is False
        assert "BACKEND_UNAVAILABLE" in (r.eligibility_reason or "")
    view = result.to_study_view()
    assert view["pareto_ids"] == []
    for cand in view["candidates"]:
        assert cand["evaluation_status"] == "BACKEND_UNAVAILABLE"
        assert cand["compilation_status"] == "COMPILED"
        assert cand["evaluation_reason"]


def test_ap02_backend_failed_preserved_into_record(tmp_path, monkeypatch):
    """A-P0.2: a backend execution failure keeps FAILED through the real
    adapter and the Optimizer (never collapsed to UNSUPPORTED).

    B-P1.4 narrowed the evaluator's execution seam to its documented
    taxonomy, so the injected failure is a documented ``BookSimError``
    (an arbitrary RuntimeError is a programming bug and must escape).
    """
    from veritx_dse.core.errors import BookSimError
    from veritx_dse.optimization.candidate import make_candidate

    def _boom(*args, **kwargs):
        raise BookSimError("synthetic backend crash")

    # The mesh base request routes to the certified meshdor path; patch
    # both runners so the synthetic crash is exercised regardless.
    monkeypatch.setattr(
        "veritx_dse.backend.meshdor.run_waved_meshdor", _boom)
    monkeypatch.setattr(
        "veritx_dse.backend.projection.run_waved_booksim", _boom)
    port = _real_port(tmp_path)
    out = port.evaluate(make_candidate(_real_base(), {"link_width": 64}))
    assert out.status == "FAILED"
    assert out.evaluation_authority == AUTHORITY_CERTIFIED_BACKEND
    result = _optimize(_real_base(), _defn(), port)
    assert result.pareto_ids == ()
    for r in result.records:
        assert r.evaluation_status == "FAILED"
        assert r.pareto_eligible is False
        assert "FAILED" in (r.eligibility_reason or "")
    view = result.to_study_view()
    assert view["pareto_ids"] == []
    for cand in view["candidates"]:
        assert cand["evaluation_status"] == "FAILED"
        assert cand["evaluation_reason"]


def test_ap02_requirement_violation_stays_evaluated(tmp_path):
    """A-P0.2: a simulated run that violates a binding product
    requirement stays EVALUATED with measurements and a typed reason,
    and the Optimizer keeps it visible but not eligible."""
    import dataclasses

    from veritx_dse.model.compile_model import QoSClass, RequirementV3
    from veritx_dse.optimization.candidate import make_candidate

    req = dataclasses.replace(_real_base(), requirements=(
        RequirementV3(qos_class=QoSClass.LATENCY_CRITICAL,
                      traffic_class="tp_collective",
                      latency_ceiling_cycles=1, binding=True),))
    port = _real_port(tmp_path)
    out = port.evaluate(make_candidate(req, {"link_width": 64}))
    assert out.status == "EVALUATED"
    assert out.objective_values.get("completion_cycles") is not None
    assert "binding requirements not satisfied" in (out.error or "")
    defn = _defn(domain=(DomainParam("link_width", (64,)),))
    result = _optimize(req, defn, port)
    (record,) = result.records
    assert record.evaluation_status == "EVALUATED"
    assert record.product_requirements_satisfied is False
    assert record.pareto_eligible is False
    assert record.pareto_member is False
    assert "binding product requirements" in \
        (record.eligibility_reason or "")
    assert result.pareto_ids == ()
    assert result.selected_candidate_id is None
    view = result.to_study_view()
    (cand,) = view["candidates"]
    assert cand["evaluation_status"] == "EVALUATED"
    assert cand["compilation_status"] == "COMPILED"
    assert cand["product_requirements"]["satisfied"] is False
    assert "binding requirements not satisfied" in \
        (cand["evaluation_reason"] or "")
    assert cand["pareto_eligible"] is False


# ── 3-4: report identity transitively carried ───────────────────────────

def test_ap02_unsupported_and_compile_failed_preserved_in_v2(tmp_path):
    """A-P0.2/A-P1.4: lowering-UNSUPPORTED and compile-failed outcomes
    keep their taxonomy and are renderable from v2 status/reason."""
    from veritx_dse.optimization.candidate import make_candidate
    from veritx_dse.optimization.real_evaluator import (
        RealCandidateEvaluator,
    )

    port = RealCandidateEvaluator(
        binary="/no-such-booksim", run_root=str(tmp_path / "runs"),
        network_clock_hz=10 ** 9, timeout_s=60)
    # Lowering refusal (PP-dimension collective) stays UNSUPPORTED.
    pp_req = _pp_request()
    out = port.evaluate(make_candidate(pp_req, {"link_width": 64}))
    assert out.status == "UNSUPPORTED"
    result = _optimize(
        pp_req, _defn(domain=(DomainParam("link_width", (64,)),)), port)
    (record,) = result.records
    assert record.evaluation_status == "UNSUPPORTED"
    (cand,) = result.to_study_view()["candidates"]
    assert cand["evaluation_status"] == "UNSUPPORTED"
    assert cand["evaluation_reason"]
    # Compile refusal (rcu_enabled=True) is COMPILE_FAILED with the
    # compiler's own verdict preserved separately.
    result2 = _optimize(
        _real_base(),
        _defn(domain=(DomainParam("rcu_enabled", (True,)),)), port)
    (record2,) = result2.records
    assert record2.evaluation_status == "COMPILE_FAILED"
    assert record2.compilation_status in ("INVALID", "UNSUPPORTED")
    (cand2,) = result2.to_study_view()["candidates"]
    assert cand2["evaluation_status"] == "COMPILE_FAILED"
    assert cand2["compilation_status"] in ("INVALID", "UNSUPPORTED")
    assert cand2["evaluation_reason"]


def test_ap14_status_and_reason_bound_into_result_id():
    """A-P1.4: compilation_status, evaluation_status and
    evaluation_reason are exposed in v2 and bound into result_id."""
    import dataclasses

    base = _real_base()
    port = _VerifiedStubPort({"latency": 10.0})
    result = _optimize(base, _defn(), port)
    view = result.to_study_view()
    for cand in view["candidates"]:
        assert cand["compilation_status"] == "COMPILED"
        assert cand["evaluation_status"] == "EVALUATED"
        assert cand["evaluation_reason"] is None
    target = result.records[0]

    def _with(replacement):
        return dataclasses.replace(result, records=tuple(
            replacement if r.candidate_id == target.candidate_id else r
            for r in result.records))

    assert _with(dataclasses.replace(
        target, evaluation_reason="changed reason")).result_id() != \
        result.result_id()
    assert _with(dataclasses.replace(
        target, evaluation_status="FAILED")).result_id() != \
        result.result_id()
    assert _with(dataclasses.replace(
        target, compilation_status="UNSUPPORTED")).result_id() != \
        result.result_id()


def test_ap13_min_vs_max_definition_distinction():
    """A-P1.3: objective direction is explicit in v2, and MIN vs MAX
    changes the definition payload and the result identity."""
    base = _real_base()
    port = _VerifiedStubPort({"latency": 10.0})
    minimize = _optimize(
        base, _defn(), port)
    maximize = _optimize(
        base, _defn(objectives=(Objective("latency", "MAX"),)), port)
    v_min = minimize.to_study_view()
    v_max = maximize.to_study_view()
    assert v_min["definition"]["objectives"] == [
        {"metric": "latency", "direction": "MIN"}]
    assert v_max["definition"]["objectives"] == [
        {"metric": "latency", "direction": "MAX"}]
    assert v_min["definition"] != v_max["definition"]
    assert v_min["definition"]["definition_id"] != \
        v_max["definition"]["definition_id"]
    assert v_min["optimization_result_id"] != \
        v_max["optimization_result_id"]
    assert v_min["optimization_result_id"] == minimize.result_id()


def test_ap13_selection_policy_definition_distinction():
    """A-P1.3: the selection policy is explicit in v2 and changing it
    changes the definition payload."""
    base = _real_base()
    port = _VerifiedStubPort({"latency": 10.0})
    first = _optimize(base, _defn(), port)
    lexicographic = _optimize(
        base, _defn(selection="lexicographic"), port)
    v_first = first.to_study_view()
    v_lex = lexicographic.to_study_view()
    assert v_first["definition"]["selection"] == "min_first_objective"
    assert v_lex["definition"]["selection"] == "lexicographic"
    assert v_first["definition"] != v_lex["definition"]
    assert v_first["definition"]["definition_id"] != \
        v_lex["definition"]["definition_id"]


def test_3_report_identity_in_candidate_record():
    result = _optimize(
        _real_base(), _defn(), _VerifiedStubPort({"latency": 10.0}))
    assert result.records
    for record in result.records:
        assert record.requirement_report_id
        assert record.product_requirements_satisfied is True
        assert record.product_requirement_details
    # The bound result identity moves when the report identity moves.
    good = _optimize(
        _real_base(), _defn(), _VerifiedStubPort({"latency": 10.0}))
    flipped = _optimize(
        _real_base(), _defn(),
        _VerifiedStubPort({"latency": 10.0}, cycles=2 * 10 ** 9))
    assert good.result_id() != flipped.result_id()


def test_4_changing_verdict_or_authority_moves_report_identity():
    base = _report_for("sha256:" + "cd" * 32)
    base_id = report_identity(base)
    # Every field the report contract binds must move the identity:
    # top-level provenance, per-entry verdict evidence, and per-entry
    # scope. No repr/object identity is involved (canonical JSON only).
    top_level = {
        "design_hash": "sha256:" + "ef" * 32,
        "performance_result_id": "perf:other",
    }
    entries = {
        "requirement_index": 1,
        "traffic_class": "dp_collective",
        "qos_class": "bandwidth_critical",
        "verdict": "VIOLATED",
        "binding": False,
        "required": 601.0,
        "measured": 11.0,
        "metric_authority": "another-authority",
        "performance_result_id": "perf:entry-other",
        "reason": "another reason",
    }
    for field, value in top_level.items():
        mutated = json.loads(json.dumps(base))
        mutated[field] = value
        assert report_identity(mutated) != base_id, field
    for field, value in entries.items():
        mutated = json.loads(json.dumps(base))
        mutated["entries"][0][field] = value
        assert report_identity(mutated) != base_id, field


# ── 5: transplant refusal ───────────────────────────────────────────────

def test_5_transplanted_requirement_provenance_refuses():
    with pytest.raises(OptimizationResultError, match="transplanted"):
        _optimize(_real_base(), _defn(), _ForeignReportPort())
    # A report whose design_hash belongs to THIS candidate but whose
    # carried identity is forged is refused too (never trusted).
    class _ForgedIdentity(_ForeignReportPort):
        def evaluate(self, candidate):
            report = _report_for("sha256:" + candidate.request.design_hash(),
                                 perf="perf:foreign")
            return CandidateEvaluation(
                candidate_id=candidate.candidate_id,
                design_hash=candidate.request.design_hash(),
                status="EVALUATED",
                objective_values={"latency": 10.0},
                locked_consequences={},
                performance_result_id="perf:foreign",
                requirement_report=report,
                requirement_report_id="forged")
    with pytest.raises(OptimizationResultError, match="forged"):
        _optimize(_real_base(), _defn(), _ForgedIdentity())


# ── 6: separate authorities ─────────────────────────────────────────────

def test_6_product_requirements_and_constraints_stay_separate():
    defn = _defn(constraints=(Constraint("latency", "<=", 5.0),))
    # Product passes, study constraint fails.
    product_ok = _optimize(
        _real_base(), defn, _VerifiedStubPort({"latency": 10.0}))
    for r in product_ok.records:
        assert r.product_requirements_satisfied is True
        assert r.constraints_satisfied is False
        assert r.constraint_verdicts["latency"] == "VIOLATED"
        assert r.pareto_eligible is False
    # Product binding fails, study constraint passes.
    constraint_ok = _optimize(
        _real_base(), _defn(),
        _VerifiedStubPort({"latency": 10.0}, cycles=2 * 10 ** 9))
    for r in constraint_ok.records:
        assert r.product_requirements_satisfied is False
        assert r.constraints_satisfied is True
        assert r.pareto_eligible is False
    # The two authorities answer different questions in one record.
    both = _optimize(
        _real_base(), _defn(constraints=(Constraint("latency", "<=", 600.0),)),
        _VerifiedStubPort({"latency": 10.0}))
    for r in both.records:
        assert r.product_requirements_satisfied is True
        assert r.constraints_satisfied is True
        assert r.pareto_eligible is True


# ── 7-8: three-state study semantics survive ────────────────────────────

def test_7_violated_survives_study_view():
    result = _optimize(
        _real_base(),
        _defn(constraints=(Constraint("latency", "<=", 1.0),)),
        FakeDeterministicEvaluator(seed=7))
    view = result.to_study_view()
    assert view["contract_version"] == 2
    for cand in view["candidates"]:
        assert cand["constraint_verdicts"]["latency"] == "VIOLATED"
        assert cand["pareto_eligible"] is False
    legacy = result.to_study_view(contract_version=1)
    for cand in legacy["candidates"]:
        assert cand["constraint_verdicts"]["latency"] is False


def test_8_unmeasurable_survives_study_view():
    result = _optimize(
        _real_base(),
        _defn(constraints=(Constraint("energy", "<=", 1.0),)),
        FakeDeterministicEvaluator(seed=7))
    view = result.to_study_view()
    assert view["contract_version"] == 2
    for cand in view["candidates"]:
        assert cand["constraint_verdicts"]["energy"] == "UNMEASURABLE"
    legacy = result.to_study_view(contract_version=1)
    for cand in legacy["candidates"]:
        # v1 booleans are LOSSY by design: UNMEASURABLE collapses to
        # false; only v2 preserves the distinction.
        assert cand["constraint_verdicts"]["energy"] is False


# ── 9-10: duplicate identity refuses ────────────────────────────────────

def test_9_duplicate_same_metric_constraints_do_not_overwrite():
    with pytest.raises(OptimizationDefinitionError,
                       match="duplicate constraint"):
        _defn(constraints=(Constraint("latency", "<=", 100.0),
                           Constraint("latency", ">=", 50.0)))
    with pytest.raises(ConstraintError, match="duplicate constraint"):
        evaluate_all((Constraint("latency", "<=", 100.0),
                      Constraint("latency", ">=", 50.0)),
                     {"latency": 75.0})


def test_10_duplicate_objective_declaration_refuses():
    with pytest.raises(OptimizationDefinitionError,
                       match="duplicate objective"):
        _defn(objectives=(Objective("latency", "MIN"),
                          Objective("latency", "MAX")))


# ── 11: same evaluator object, same candidate, twice ────────────────────

def test_11_same_evaluator_same_candidate_twice(tmp_path):
    from veritx_dse.optimization.candidate import make_candidate
    port = _real_port(tmp_path)
    cand = make_candidate(_real_base(), {"link_width": 64})
    first = port.evaluate(cand)
    second = port.evaluate(cand)
    assert first.status == second.status == "EVALUATED"
    assert first.candidate_id == second.candidate_id
    assert first.design_hash == second.design_hash == \
        cand.request.design_hash()
    assert first.objective_values == second.objective_values
    slots = sorted(p for p in (tmp_path / "runs" / cand.candidate_id).iterdir()
                   if p.is_dir())
    assert len(slots) == 2
    assert all(p.name.startswith("eval-") for p in slots)


# ── 12-14: same CLI run root, immediately, no sleep ─────────────────────

def _cli_args(fixture, study_out, run_root):
    return argparse.Namespace(
        fixture=fixture, search="grid", link_widths="64,128",
        concentrations="1", latency_ceiling=None, max_candidates=None,
        study_out=study_out, evaluate="booksim", binary=None,
        network_clock_hz=10 ** 9, run_root=run_root, timeout=600, seed=7)


@pytest.fixture(scope="module")
def two_cli_runs(tmp_path_factory):
    """Two immediate CLI studies against ONE explicit run root (no sleep)."""
    from veritx_dse.cli.cli import cmd_optimize
    from veritx_dse.core.logging import Ctx
    work = tmp_path_factory.mktemp("rt-a8-cli")
    fixture = _cli_fixture(work)
    shared_root = work / "runs"
    views = []
    for tag in ("a", "b"):
        study_out = work / f"study-{tag}.json"
        ctx = Ctx(verbosity=0)
        cmd_optimize(ctx, _cli_args(fixture, str(study_out),
                                    str(shared_root)))
        assert not ctx.failed
        views.append(json.loads(study_out.read_text()))
    return shared_root, views[0], views[1]


def test_12_same_cli_run_root_twice_immediately(two_cli_runs):
    shared_root, first, second = two_cli_runs
    assert first["candidates"] and second["candidates"]
    assert first["pareto_ids"] and second["pareto_ids"]
    tokens = sorted(p for p in shared_root.iterdir() if p.is_dir())
    assert len(tokens) == 2, [p.name for p in tokens]
    assert tokens[0].name != tokens[1].name


def test_13_repeated_runs_preserve_candidate_design_identity(two_cli_runs):
    _, first, second = two_cli_runs
    assert [c["candidate_id"] for c in first["candidates"]] == \
        [c["candidate_id"] for c in second["candidates"]]
    assert [c["evaluation_ids"]["design_hash"]
            for c in first["candidates"]] == \
        [c["evaluation_ids"]["design_hash"]
         for c in second["candidates"]]


def test_14_repeated_runs_allocate_distinct_slots(two_cli_runs):
    shared_root, _, _ = two_cli_runs
    tokens = sorted(p for p in shared_root.iterdir() if p.is_dir())
    digests = []
    for token in tokens:
        found = sorted(
            hashlib.sha256(p.read_bytes()).hexdigest()
            for p in token.rglob("evidence/*.json"))
        assert found, token
        digests.append(found)
    assert digests[0] != digests[1]
