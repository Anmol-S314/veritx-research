"""Stage-5 real adapter: candidates through the genuine pipeline.

No fake metrics anywhere: objectives are evidenced measurements,
infeasible candidates stay visible but out of Pareto, and transplanted
evaluations are refused by the Optimizer's identity asserts (P2 suite).
"""
from __future__ import annotations

from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    QoSClass,
    RequirementV3,
    ServingMode,
    TopologyFamily,
    WorkloadV3,
)
from veritx_dse.optimization.definition import (
    DomainParam,
    Objective,
    OptimizationDefinition,
)
from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
from veritx_dse.optimization.result import Optimizer
from veritx_dse.simulation.booksim import find_booksim_bin


def _base(**kw):
    noc = dict(topology_family=TopologyFamily.MESH, concentration=1)
    noc.update(kw.pop("noc", {}))
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=4, dp=1,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=2048,
                traffic_class="tp_collective"),)),
        requirements=(RequirementV3(
            qos_class=QoSClass.LATENCY_CRITICAL,
            traffic_class="tp_collective",
            latency_ceiling_cycles=10 ** 9, binding=True),),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(**noc))


def _defn(**kw):
    base = dict(
        domain=(DomainParam("link_width", (64, 128)),),
        objectives=(Objective("completion_cycles", "MIN"),),
        constraints=(),
        method="grid",
    )
    base.update(kw)
    return OptimizationDefinition(**base)


def _port(tmp_path, **kw):
    # The study declares the network clock explicitly (adapter default
    # None would honestly adjudicate cycles-only UNSUPPORTED instead).
    kw.setdefault("network_clock_hz", 10 ** 9)
    return RealCandidateEvaluator(
        binary=str(find_booksim_bin(REPO)),
        run_root=str(tmp_path / "runs"), timeout_s=600, **kw)


def test_real_grid_end_to_end(tmp_path):
    result = Optimizer().optimize(
        _base(), _defn(), _port(tmp_path))
    assert len(result.records) == 2
    for record in result.records:
        assert record.evaluation_status == "EVALUATED"
        assert record.performance_result_id is not None
        assert not record.performance_result_id.startswith("fake:")
        assert "completion_cycles" in record.objective_values
        assert "area" not in record.objective_values
        assert record.locked_consequences["routing_classes"] == ["DOR_XY"]
        assert record.all_binding_satisfied is True
    assert len(result.pareto_ids) >= 1
    assert result.selected_candidate_id in result.pareto_ids
    assert len({r.design_hash for r in result.records}) == 2
    assert result.result_id()


def test_uncertified_corner_stays_visible_but_infeasible(tmp_path):
    from veritx_dse.optimization.definition import Constraint
    result = Optimizer().optimize(
        _base(), _defn(
            domain=(DomainParam("rcu_enabled", (False, True)),),
            objectives=(Objective("completion_cycles", "MIN"),),
            constraints=(Constraint("completion_cycles", "<=", 10 ** 12),),
        ),
        _port(tmp_path))
    by_patch = {tuple(sorted(r.guided_patch.items())): r
                for r in result.records}
    bad = by_patch[(("rcu_enabled", True),)]
    assert bad.evaluation_status != "EVALUATED"
    assert bad.compilation_status in ("COMPILE_FAILED", "UNSUPPORTED")
    assert bad.candidate_id not in result.pareto_ids
    assert bad.performance_result_id is None
    # Infeasibility stays visible in the record: non-passing verdicts
    # on every declared constraint, never a pass, never Pareto.
    assert bad.requirement_details, "refusal must bind its verdicts"
    assert all(d["verdict"] != "SATISFIED"
               for d in bad.requirement_details)
    good = by_patch[(("rcu_enabled", False),)]
    assert good.evaluation_status == "EVALUATED"


def _pp_request():
    import dataclasses
    req = _base()
    wl = dataclasses.replace(
        req.workload,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE,
            dimension=CollectiveDimension.PP,
            payload_bytes=2048,
            traffic_class="tp_collective"),))
    return dataclasses.replace(req, workload=wl)


def _invalid_root_request():
    import dataclasses
    req = _base()
    wl = dataclasses.replace(
        req.workload,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.BROADCAST,
            dimension=CollectiveDimension.TP,
            payload_bytes=1024,
            traffic_class="tp_collective",
            source_rank=99),))
    return dataclasses.replace(req, workload=wl)


def test_lowering_refusals_are_typed_not_raised(tmp_path):
    """RT-9: the adapter's catch covers the lowerer's full declared
    space — out-of-domain semantics are UNSUPPORTED, malformed input is
    INVALID, and neither escapes as an exception."""
    from types import SimpleNamespace
    port = RealCandidateEvaluator(
        binary="/no-such-booksim", run_root=str(tmp_path / "runs"))
    pp = port.evaluate(SimpleNamespace(
        candidate_id="pp-lowering-refusal", request=_pp_request()))
    assert pp.status == "UNSUPPORTED"
    assert pp.performance_result_id is None
    assert "UnsupportedSemantics" in (pp.error or "")
    assert "PP-dimension" in (pp.error or "")
    bad = port.evaluate(SimpleNamespace(
        candidate_id="invalid-lowering-input",
        request=_invalid_root_request()))
    assert bad.status == "INVALID"
    assert bad.performance_result_id is None
    assert "InvalidInput" in (bad.error or "")
