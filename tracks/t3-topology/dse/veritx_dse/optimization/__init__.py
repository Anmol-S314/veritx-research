"""veritx_dse.optimization — P2 guided optimization (above the compiler).

Deterministic search + Pareto over GUIDED CompileRequest knobs with a
fake deterministic evaluator (the real P1B/P1C adapter arrives at
integration — see evaluators.py for its contract).

    OptimizationDefinition  what to search (definition.py)
    Candidate               base request + GUIDED patch (candidate.py)
    search_candidates       grid/enumeration/seeded-random (search.py)
    evaluate_all            constraint verdicts (constraints.py)
    pareto_ids              frontier (pareto.py)
    Optimizer.optimize      search -> evaluate -> Pareto (result.py)
    FakeDeterministicEvaluator  in-dev port (evaluators.py)

Every candidate recompiles LOCKED properties (routing, VC
count/structure, turn restrictions, escape VC) via FabricCompiler.
The optimizer never sets them: they are structurally inexpressible in
the definition domain and the patch keys.
"""
from veritx_dse.optimization.candidate import (
    Candidate, CandidateError, apply_patch, candidate_id_for,
    make_candidate,
)
from veritx_dse.optimization.constraints import (
    evaluate_all, evaluate_constraint_value,
)
from veritx_dse.optimization.definition import (
    GUIDED_PARAMS, Constraint, DomainParam, Objective,
    OptimizationDefinition, OptimizationDefinitionError,
)
from veritx_dse.optimization.evaluators import (
    CandidateEvaluation, CandidateEvaluationPort, FakeDeterministicEvaluator,
)
from veritx_dse.optimization.pareto import pareto_front, pareto_ids
from veritx_dse.optimization.result import (
    CandidateRecord, OptimizationResult, OptimizationResultError, Optimizer,
)
from veritx_dse.optimization.search import search_candidates

__all__ = [
    "GUIDED_PARAMS", "Candidate", "CandidateError",
    "CandidateEvaluation", "CandidateEvaluationPort", "CandidateRecord",
    "Constraint", "DomainParam", "FakeDeterministicEvaluator", "Objective",
    "OptimizationDefinition", "OptimizationDefinitionError",
    "OptimizationResult", "OptimizationResultError", "Optimizer",
    "apply_patch", "candidate_id_for", "evaluate_all",
    "evaluate_constraint_value", "make_candidate", "pareto_front",
    "pareto_ids", "search_candidates",
]
