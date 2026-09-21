"""veritx_dse.optimization — Wave F: design optimization (§159).

One orchestration layer ABOVE the sealed control plane:

    OptimizationDefinition (content-addressed)
        -> finite design space -> canonical candidate assignments
        -> scenario intents resolved through the sealed intent system
        -> sealed SrotaControlPlane evaluation (reuse included)
        -> verified candidate results (load_verified_result only)
        -> typed metric extraction -> hard-constraint verdicts
        -> comparability gate -> scoped Pareto frontier
        -> optional explicit selection policy
        -> verified OptimizationResult

Optimization cannot make the underlying model more truthful: a Wave-F
conclusion is always conditional on the fidelity of the verified Wave-E
parents, and an uncalibrated model yields "best under that model",
never "best hardware".

Public surface:

    OptimizationDefinition      declared request (definition.py)
    build_candidates            finite space enumeration (space.py)
    extract_metric/...          verified metric extraction (metrics.py)
    evaluate_constraint/...     constraint truth table (constraints.py)
    compute_frontier/select     Pareto + selection (pareto.py)
    OptimizationRun.build       result artifact builder (result.py)
    load_verified_optimization_result   full re-deriving verifier
"""
from veritx_dse.optimization.definition import (
    METRIC_REGISTRY, OPTIMIZATION_SCHEMA_VERSION, PARAM_REGISTRY,
    HardConstraintSpec, MetricDef, ObjectiveSpec, OptimizationDefinition,
    OptimizationDefinitionError, ParamDef, ParameterSpec, ScenarioSpec,
    registered_param,
)
from veritx_dse.optimization.space import (
    NOT_EVALUATED, budget_accounting, budget_plan, build_candidates,
    candidate_identity, hardware_signature, iter_raw_assignments,
    raw_cardinality,
)

__all__ = [
    "METRIC_REGISTRY", "NOT_EVALUATED", "OPTIMIZATION_SCHEMA_VERSION",
    "PARAM_REGISTRY", "HardConstraintSpec", "MetricDef", "ObjectiveSpec",
    "OptimizationDefinition", "OptimizationDefinitionError", "ParamDef",
    "ParameterSpec", "ScenarioSpec", "aggregate_status",
    "budget_accounting", "budget_plan", "build_candidates",
    "candidate_identity", "compute_frontier", "extract_metric",
    "hardware_signature", "iter_raw_assignments",
    "load_verified_optimization_result", "registered_param",
    "raw_cardinality", "select",
]


def __getattr__(name: str):  # late bindings keep import order simple
    if name == "compute_frontier":
        from veritx_dse.optimization.pareto import compute_frontier
        return compute_frontier
    if name == "extract_metric":
        from veritx_dse.optimization.metrics import extract_metric
        return extract_metric
    if name == "load_verified_optimization_result":
        from veritx_dse.optimization.result import (
            load_verified_optimization_result)
        return load_verified_optimization_result
    if name == "aggregate_status":
        from veritx_dse.optimization.result import aggregate_status
        return aggregate_status
    if name == "select":
        from veritx_dse.optimization.pareto import select
        return select
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
