"""veritx_dse.optimization.definition — OptimizationDefinition (P2).

Rationale: docs/decisions/modules/optimization.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

from veritx_dse.application.evaluation_question import EvaluationQuestion

DOMAIN = "veritx/optimization-definition/v2"

SEARCH_METHODS = ("grid", "enumeration", "random")
SELECTION_POLICIES = ("min_first_objective", "lexicographic", "none")

GUIDED_PARAMS: dict[str, str] = {
    "link_width": "link_width",
    "concentration": "concentration",
    "radix": "radix",
    "rcu_enabled": "rcu_enabled",
    "topology_family": "topology_family",
    "arbitration": "arbitration",
    "mcast_groups": "mcast_groups",
    "mcast_setup_cycles": "mcast_setup_cycles",
}

_LOCKED_TOKENS = (
    "routing",
    "vc",
    "turn",
    "escape",
)

class OptimizationDefinitionError(ValueError):
    """Invalid optimization definition (typed, fail-closed)."""

def _normalize_param_name(name: str) -> str:
    if not isinstance(name, str) or not name:
        raise OptimizationDefinitionError("parameter name must be a non-empty string")
    short = name.split(".")[-1].strip()
    if not short:
        raise OptimizationDefinitionError(f"parameter name {name!r} has no leaf field")
    return short

def _check_guided(name: str) -> str:
    short = _normalize_param_name(name)
    squashed = short.lower().replace("_", "")
    for tok in _LOCKED_TOKENS:
        if tok in squashed:
            raise OptimizationDefinitionError(
                f"parameter {name!r} names a LOCKED property ({tok}): routing, "
                "VC count/structure, turn restrictions and escape VC are "
                "compiler-derived and structurally inexpressible here — "
                "every candidate recompiles them via FabricCompiler")
    if short not in GUIDED_PARAMS:
        raise OptimizationDefinitionError(
            f"unknown GUIDED parameter {name!r}; supported: {sorted(GUIDED_PARAMS)}")
    return short

def _canonical_value(v: Any) -> Any:
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, str)):
        return v
    if v is None:
        raise OptimizationDefinitionError(
            "None is not a domain value — omit the parameter to leave it at base")
    raise OptimizationDefinitionError(
        f"unsupported domain value {v!r}; P2 v1 supports int/str/bool")

@dataclass(frozen=True)
class DomainParam:
    """One finite GUIDED design-variable domain."""
    name: str
    values: tuple[Any, ...]

    def __post_init__(self):
        short = _check_guided(self.name)
        object.__setattr__(self, "name", short)
        vals = self.values
        if isinstance(vals, list):
            vals = tuple(vals)
        if not isinstance(vals, tuple) or not vals:
            raise OptimizationDefinitionError(
                f"parameter {self.name!r} needs a non-empty value tuple/list")
        canon = tuple(_canonical_value(v) for v in vals)
        if len(set(canonical_json(v) for v in canon)) != len(canon):
            raise OptimizationDefinitionError(
                f"parameter {self.name!r} has duplicate domain values")
        ordered = tuple(sorted(canon, key=canonical_json))
        object.__setattr__(self, "values", ordered)

@dataclass(frozen=True)
class ObjectiveSource:
    """WHAT metric / FROM WHICH question / WITH WHICH backend constraint.

Rationale: docs/decisions/modules/optimization.md
    """

    metric_key: str
    question: EvaluationQuestion = EvaluationQuestion.NETWORK_COMPLETION
    backend_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.metric_key, str) or not self.metric_key:
            raise OptimizationDefinitionError(
                "objective source needs a metric key")
        object.__setattr__(self, "question",
                            _coerce_question(self.question))
        if self.backend_id is not None and (
                not isinstance(self.backend_id, str)
                or not self.backend_id):
            raise OptimizationDefinitionError(
                "objective backend constraint must be a backend id "
                f"string or None, got {self.backend_id!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"metric_key": self.metric_key,
                "question": self.question.value,
                "backend_id": self.backend_id}

def _coerce_question(value: Any) -> EvaluationQuestion:
    """EvaluationQuestion or its canonical name -> EvaluationQuestion."""
    if isinstance(value, EvaluationQuestion):
        return value
    if isinstance(value, str):
        try:
            return EvaluationQuestion[value]
        except KeyError:
            for question in EvaluationQuestion:
                if question.value == value:
                    return question
            raise OptimizationDefinitionError(
                f"unknown evaluation question {value!r}; supported: "
                f"{[q.value for q in EvaluationQuestion]}") from None
    raise OptimizationDefinitionError(
        f"evaluation question must be an EvaluationQuestion or its "
        f"name, got {value!r}")

@dataclass(frozen=True)
class Objective:
    """One optimization objective: metric + direction + evaluation policy.

Rationale: docs/decisions/modules/optimization.md
    """
    metric: str
    direction: str
    question: EvaluationQuestion = EvaluationQuestion.NETWORK_COMPLETION
    backend_id: str | None = None

    def __post_init__(self):
        if not isinstance(self.metric, str) or not self.metric:
            raise OptimizationDefinitionError("objective needs a metric name")
        if self.direction not in ("MIN", "MAX"):
            raise OptimizationDefinitionError(
                f"objective direction must be MIN or MAX, got {self.direction!r}")
        object.__setattr__(self, "question",
                            _coerce_question(self.question))
        if self.backend_id is not None and (
                not isinstance(self.backend_id, str)
                or not self.backend_id):
            raise OptimizationDefinitionError(
                "objective backend constraint must be a backend id "
                f"string or None, got {self.backend_id!r}")

    @property
    def source(self) -> ObjectiveSource:
        """This objective's explicit evaluation policy."""
        return ObjectiveSource(metric_key=self.metric,
                               question=self.question,
                               backend_id=self.backend_id)

@dataclass(frozen=True)
class Constraint:
    """One hard constraint: metric + operator + threshold."""
    metric: str
    op: str
    threshold: float

    def __post_init__(self):
        if not isinstance(self.metric, str) or not self.metric:
            raise OptimizationDefinitionError("constraint needs a metric name")
        if self.op not in ("<=", ">="):
            raise OptimizationDefinitionError(
                f"constraint operator must be <= or >=, got {self.op!r}")
        if isinstance(self.threshold, bool) or not isinstance(
                self.threshold, (int, float)):
            raise OptimizationDefinitionError(
                f"constraint threshold must be a real number, got {self.threshold!r}")
        import math
        if not math.isfinite(float(self.threshold)):
            raise OptimizationDefinitionError("constraint threshold must be finite")
        object.__setattr__(self, "threshold", float(self.threshold))

@dataclass(frozen=True)
class OptimizationDefinition:
    """What to search: domain + objectives + constraints + budget + seed.

Rationale: docs/decisions/modules/optimization.md
    """
    domain: tuple[DomainParam, ...] = ()
    objectives: tuple[Objective, ...] = ()
    constraints: tuple[Constraint, ...] = ()
    method: str = "grid"
    budget: dict[str, Any] = field(default_factory=dict)
    seed: int | None = None
    selection: str = "min_first_objective"

    def __post_init__(self):
        params = self.domain
        if isinstance(params, list):
            params = tuple(params)
            object.__setattr__(self, "domain", params)
        objectives = self.objectives
        if isinstance(objectives, list):
            objectives = tuple(objectives)
            object.__setattr__(self, "objectives", objectives)
        constraints = self.constraints
        if isinstance(constraints, list):
            constraints = tuple(constraints)
            object.__setattr__(self, "constraints", constraints)
        for p in params:
            if not isinstance(p, DomainParam):
                raise OptimizationDefinitionError(
                    f"domain must contain DomainParam, got {type(p).__name__}")
        for o in objectives:
            if not isinstance(o, Objective):
                raise OptimizationDefinitionError(
                    f"objectives must contain Objective, got {type(o).__name__}")
        for c in constraints:
            if not isinstance(c, Constraint):
                raise OptimizationDefinitionError(
                    f"constraints must contain Constraint, got {type(c).__name__}")
        names = [p.name for p in params]
        if len(names) != len(set(names)):
            raise OptimizationDefinitionError("duplicate parameter names")
        if not objectives:
            raise OptimizationDefinitionError("at least one objective is required")
        obj_metrics = [o.metric for o in objectives]
        dup_obj = sorted({m for m in obj_metrics if obj_metrics.count(m) > 1})
        if dup_obj:
            raise OptimizationDefinitionError(
                f"duplicate objective metric(s) {dup_obj}: each requested "
                "objective must be declared exactly once")
        con_metrics = [c.metric for c in constraints]
        dup_con = sorted({m for m in con_metrics if con_metrics.count(m) > 1})
        if dup_con:
            raise OptimizationDefinitionError(
                f"duplicate constraint metric(s) {dup_con}: one constraint "
                "per metric; two bounds over the same metric would "
                "silently overwrite each other — refused at construction, "
                "never last-write-wins")
        if self.method not in SEARCH_METHODS:
            if self.method in ("bayes", "bo", "milp", "sa", "rho", "grpo"):
                raise OptimizationDefinitionError(
                    f"search method {self.method!r} refused: Bayes/MILP only "
                    "after deterministic correctness is established — use "
                    "'grid'/'enumeration'/'random'")
            raise OptimizationDefinitionError(
                f"unknown search method {self.method!r}; "
                f"supported: {list(SEARCH_METHODS)}")
        if self.selection not in SELECTION_POLICIES:
            raise OptimizationDefinitionError(
                f"unknown selection policy {self.selection!r}; "
                f"supported: {list(SELECTION_POLICIES)}")
        budget = dict(self.budget or {})
        for key in ("max_candidates", "max_evaluations"):
            if budget.get(key) is not None:
                v = budget[key]
                if type(v) is not int or v < 1:
                    raise OptimizationDefinitionError(
                        f"budget {key} must be a positive int, got {v!r}")
        unknown = sorted(set(budget) - {"max_candidates", "max_evaluations"})
        if unknown:
            raise OptimizationDefinitionError(
                f"budget has unknown fields {unknown} (schema close)")
        object.__setattr__(self, "budget", budget)
        if self.seed is not None and type(self.seed) is not int:
            raise OptimizationDefinitionError(
                f"seed must be an int or None, got {self.seed!r}")
        if not params:
            raise OptimizationDefinitionError(
                "the guided domain is empty: an optimization with no guided "
                "dimension would only re-evaluate the base design, and its "
                "empty patch is illegal. Declare at least one DomainParam.")
        if self.method == "random" and self.seed is None:
            raise OptimizationDefinitionError(
                "search method 'random' requires an explicit seed for determinism")

    def definition_id(self) -> str:
        return content_id(DOMAIN, {
            "parameters": [{"name": p.name, "values": list(p.values)}
                           for p in sorted(self.domain, key=lambda p: p.name)],
            "objectives": [{"metric": o.metric, "direction": o.direction,
                            "question": o.question.value,
                            "backend_id": o.backend_id}
                           for o in self.objectives],
            "constraints": [{"metric": c.metric, "op": c.op,
                             "threshold": c.threshold}
                            for c in self.constraints],
            "method": self.method,
            "budget": dict(sorted(self.budget.items())),
            "seed": self.seed,
            "selection": self.selection,
        })

    def to_dict(self) -> dict[str, Any]:
        return {
            "objectives": [{"metric": o.metric, "direction": o.direction,
                            "question": o.question.value,
                            "backend_id": o.backend_id}
                           for o in self.objectives],
            "constraints": [{"metric": c.metric, "op": c.op,
                             "threshold": c.threshold}
                            for c in self.constraints],
            "method": self.method,
            "budget": dict(self.budget),
            "seed": self.seed,
            "selection": self.selection,
            "domain": {p.name: list(p.values) for p in self.domain},
        }

def required_questions(definition: "OptimizationDefinition"
                       ) -> tuple[EvaluationQuestion, ...]:
    """The federation questions a study must execute, in declaration order.

    One execution per question, shared by every objective reading it:
    three objectives over NETWORK_COMPLETION + DRAM_TIMING need one
    BookSim run and one Ramulator run, not three runs. The federation
    planner adjudicates each question once; objectives only read.
    """
    seen: list[EvaluationQuestion] = []
    for objective in definition.objectives:
        question = _coerce_question(objective.question)
        if question not in seen:
            seen.append(question)
    return tuple(seen)

SEARCHABLE_FABRIC_PARAMS: dict[str, str] = {
    "link_width": "link_width",
    "concentration": "concentration",
    "radix": "radix",
    "topology_family": "topology_family",
    "arbitration": "arbitration",
}

DEAD_KNOBS: dict[str, str] = {
    "rcu_enabled": "removed from v4: no structural router-reduction "
                     "artifact exists; not a searchable dimension",
    "mcast_groups": "removed from v4: constrains a switch multicast "
                       "engine with no execution; not searchable",
    "mcast_setup_cycles": "removed from v4: see mcast_groups",
    "output_formats": "not a physical-performance dimension: output "
                         "selection cannot change measured performance",
    "obfuscation_level": "not a physical-performance dimension",
}

PARALLELISM_DIMS = ("tp", "pp", "ep", "dp")

PLACEMENT_DIM = "placement"

PLACEMENT_POLICIES = ("rank_order",)

def _check_study_dimension(name: str) -> tuple[str, str]:
    """Validate a study dimension name -> (namespace, short name)."""
    short = _normalize_param_name(name)
    squashed = short.lower().replace("_", "")
    for tok in _LOCKED_TOKENS:
        if tok in squashed:
            raise OptimizationDefinitionError(
                f"study dimension {name!r} names a LOCKED property "
                f"({tok}): VC count/map, routing, turn restrictions and "
                "escape VCs are compiler-derived and structurally "
                "inexpressible — every candidate recompiles them")
    if short in DEAD_KNOBS:
        raise OptimizationDefinitionError(
            f"study dimension {name!r} refused: {DEAD_KNOBS[short]}")
    if short in PARALLELISM_DIMS:
        return ("workload", short)
    if short == PLACEMENT_DIM:
        return ("placement", short)
    if short in SEARCHABLE_FABRIC_PARAMS:
        return ("fabric", short)
    raise OptimizationDefinitionError(
        f"unknown study dimension {name!r}; searchable fabric: "
        f"{sorted(SEARCHABLE_FABRIC_PARAMS)}, workload: "
        f"{list(PARALLELISM_DIMS)}, placement: [{PLACEMENT_DIM}]")

@dataclass(frozen=True)
class StudyParam:
    """One finite study design-variable domain (namespace-aware)."""
    name: str
    values: tuple[Any, ...]

    def __post_init__(self):
        namespace, short = _check_study_dimension(self.name)
        object.__setattr__(self, "name", short)
        object.__setattr__(self, "namespace", namespace)
        vals = self.values
        if isinstance(vals, list):
            vals = tuple(vals)
        if not isinstance(vals, tuple) or not vals:
            raise OptimizationDefinitionError(
                f"study parameter {short!r} needs a non-empty value tuple/list")
        if namespace == "workload":
            for v in vals:
                if type(v) is not int or v < 1:
                    raise OptimizationDefinitionError(
                        f"parallelism dimension {short!r} needs int sizes "
                        f">= 1, got {v!r}")
            canon = tuple(vals)
        elif namespace == "placement":
            for v in vals:
                if not isinstance(v, str) or v not in PLACEMENT_POLICIES:
                    raise OptimizationDefinitionError(
                        f"placement policy {v!r} has no canonical "
                        f"constructor; qualified: {list(PLACEMENT_POLICIES)}")
            canon = tuple(vals)
        else:
            canon = tuple(_canonical_value(v) for v in vals)
        if len(set(canonical_json(v) for v in canon)) != len(canon):
            raise OptimizationDefinitionError(
                f"study parameter {short!r} has duplicate domain values")
        ordered = tuple(sorted(canon, key=canonical_json))
        object.__setattr__(self, "values", ordered)

    namespace: str = "fabric"

@dataclass(frozen=True)
class ScenarioObjective:
    """One objective bound to exactly one scenario (None = every scenario)."""
    metric: str
    direction: str
    question: EvaluationQuestion = EvaluationQuestion.NETWORK_COMPLETION
    backend_id: str | None = None
    scenario: str | None = None

    def __post_init__(self):
        if not isinstance(self.metric, str) or not self.metric:
            raise OptimizationDefinitionError("objective needs a metric name")
        if self.direction not in ("MIN", "MAX"):
            raise OptimizationDefinitionError(
                f"objective direction must be MIN or MAX, got {self.direction!r}")
        object.__setattr__(self, "question",
                            _coerce_question(self.question))
        if self.backend_id is not None and (
                not isinstance(self.backend_id, str)
                or not self.backend_id):
            raise OptimizationDefinitionError(
                "objective backend constraint must be a backend id "
                f"string or None, got {self.backend_id!r}")
        if self.scenario is not None and (
                not isinstance(self.scenario, str)
                or not self.scenario):
            raise OptimizationDefinitionError(
                "objective scenario must be a scenario id string or "
                f"None, got {self.scenario!r}")

@dataclass(frozen=True)
class ScenarioConstraint:
    """One hard constraint bound to exactly one scenario (None = every)."""
    metric: str
    op: str
    threshold: float
    scenario: str | None = None

    def __post_init__(self):
        if not isinstance(self.metric, str) or not self.metric:
            raise OptimizationDefinitionError(
                "constraint needs a metric name")
        if self.op not in ("<=", ">="):
            raise OptimizationDefinitionError(
                f"constraint operator must be <= or >=, got {self.op!r}")
        if isinstance(self.threshold, bool) or not isinstance(
                self.threshold, (int, float)):
            raise OptimizationDefinitionError(
                "constraint threshold must be a real number, got "
                f"{self.threshold!r}")
        import math
        if not math.isfinite(float(self.threshold)):
            raise OptimizationDefinitionError(
                "constraint threshold must be finite")
        object.__setattr__(self, "threshold", float(self.threshold))
        if self.scenario is not None and (
                not isinstance(self.scenario, str)
                or not self.scenario):
            raise OptimizationDefinitionError(
                "constraint scenario must be a scenario id string or "
                f"None, got {self.scenario!r}")

_EFFECTIVENESS: dict[tuple[str, str], tuple[str, str]] = {
    ("link_width", "completion_cycles"): (
        "EFFECTIVE",
        "link width sets flit serialization/bandwidth: a direct "
        "physical effect on network completion"),
    ("link_width", "critical_path"): (
        "NO_DIRECT_EFFECT",
        "Wave-E critical_path is the longest EXPLICIT dependency chain "
        "by scheduled durations; resource serialization (bandwidth) is "
        "excluded by definition, so link width cannot move it"),
    ("tp", "completion_cycles"): (
        "EFFECTIVE",
        "TP changes collective participation and traffic shape: "
        "workload/system semantics change"),
    ("pp", "completion_cycles"): (
        "EFFECTIVE",
        "PP changes stage/lowering structure: workload semantics change"),
    ("ep", "completion_cycles"): (
        "EFFECTIVE",
        "EP changes expert dispatch/combine participation: workload "
        "semantics change"),
    ("dp", "completion_cycles"): (
        "EFFECTIVE",
        "DP changes replica/group algebra: workload semantics change"),
    ("placement", "completion_cycles"): (
        "EFFECTIVE",
        "host assignment changes rank->endpoint locality through the "
        "canonical mapping artifact"),
    ("concentration", "completion_cycles"): (
        "EFFECTIVE",
        "concentration changes endpoint-per-router structure"),
    ("radix", "completion_cycles"): (
        "EFFECTIVE",
        "radix changes fabric geometry"),
    ("topology_family", "completion_cycles"): (
        "EFFECTIVE",
        "topology family changes the routed graph"),
    ("arbitration", "completion_cycles"): (
        "EFFECTIVE",
        "arbitration changes router resource contention as qualified"),
}

EFFECTIVENESS_VERDICTS = ("EFFECTIVE", "NO_DIRECT_EFFECT", "UNKNOWN")

def assess_effectiveness(dimension: str, metric: str
                         ) -> tuple[str, str]:
    """(verdict, rationale) for one dimension x metric combination."""
    short = _normalize_param_name(dimension)
    entry = _EFFECTIVENESS.get((short, metric))
    if entry is not None:
        return entry
    return ("UNKNOWN",
            f"no proven causal relation between {short!r} and "
            f"{metric!r}: warn, do not prevent")

__all__ = [
    "DOMAIN", "GUIDED_PARAMS", "SEARCH_METHODS", "SELECTION_POLICIES",
    "Constraint", "DomainParam", "Objective", "ObjectiveSource",
    "OptimizationDefinition", "OptimizationDefinitionError",
    "required_questions",
    "SEARCHABLE_FABRIC_PARAMS", "DEAD_KNOBS", "PARALLELISM_DIMS",
    "PLACEMENT_DIM", "PLACEMENT_POLICIES", "StudyParam",
    "ScenarioObjective", "ScenarioConstraint",
    "EFFECTIVENESS_VERDICTS", "assess_effectiveness",
]
