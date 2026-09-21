"""veritx_dse.optimization.definition — OptimizationDefinition (§8).

Wave F is an orchestration/search layer ABOVE the sealed control plane.
It never launches a backend: every candidate is evaluated through
``SrotaControlPlane.evaluate`` and every number is extracted from a
VERIFIED candidate result (``load_verified_result``).

This module owns the DECLARED side of an optimization:

    scenarios        explicit workload scenarios (PREFILL/DECODE/...)
    parameters       CLOSED registry of design variables (§12)
    objectives       ObjectiveSpec (metric, direction, scenario) (§38)
    hard_constraints HardConstraintSpec (metric, operator, bound) (§45)
    search policy    EXHAUSTIVE_GRID | BUDGETED_GRID (§21)
    search budget    max_design_candidates/max_scenario_evaluations (§25)
    selection policy NONE | SINGLE_OBJECTIVE | LEXICOGRAPHIC (§57)

Design-space identity (§16) is canonical: declaration order and domain
value order do NOT change a mathematically identical space (§83/§84),
while any result-affecting semantic change (constraint bound, budget,
direction) DOES change the ID (§80/§81/§79).

All metric values are exact (Fraction) until reporting (§39).
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Any

from veritx_dse.core.spec import canonical_json

OPTIMIZATION_SCHEMA_VERSION = 1
_OPT_TAG = "srota/optimization/definition/v1"

SEARCH_POLICIES = ("EXHAUSTIVE_GRID", "BUDGETED_GRID")
SELECTION_POLICIES = ("NONE", "SINGLE_OBJECTIVE", "LEXICOGRAPHIC")
DIRECTIONS = ("MINIMIZE", "MAXIMIZE")
OPERATORS = ("<=", ">=")


class OptimizationDefinitionError(ValueError):
    """Invalid optimization request (typed, fail-closed)."""


# ── closed design-parameter registry (§12) ───────────────────────────────

@dataclass(frozen=True)
class ParamDef:
    """One registered design variable.

    ``kind`` distinguishes hardware/design variables from workload
    semantics (§12); ``scenario_key`` is the intent-dict path the value
    patches (currently the verified ``fabric_overrides`` seam).
    """
    name: str
    kind: str                     # HARDWARE | WORKLOAD
    scenario_key: str             # "fabric_overrides" (the verified seam)
    intent_key: str               # key inside the intent dict
    allowed: tuple[Any, ...]      # finite closed domain


def _canonical_value(v: Any) -> Any:
    """JSON-safe canonical form of one domain value (int over bool)."""
    if isinstance(v, bool):
        raise OptimizationDefinitionError(
            f"bool domain values are ambiguous JSON ints: {v!r}")
    if isinstance(v, (int, str)):
        return v
    raise OptimizationDefinitionError(
        f"unsupported domain value {v!r}; Wave-F v1 supports int/str")


#: The closed registry. Only paths the sealed intent system actually
#: accepts (verified seam: ``fabric_overrides`` -> strict dotted-path
#: override of an existing CompileRequest leaf, see
#: ``application.presets.derive_request``). Registering a path here is
#: the ONLY way a parameter can patch an intent (§12: no arbitrary JSON
#: paths). Parallelism knobs feed Wave-D geometry; topology/link-width
#: feed Wave-B fabric derivation.
PARAM_REGISTRY: dict[str, ParamDef] = {}
for _name in ("workload.tp", "workload.pp", "workload.ep", "workload.dp"):
    PARAM_REGISTRY[_name] = ParamDef(
        name=_name, kind="HARDWARE", scenario_key="fabric_overrides",
        intent_key=_name, allowed=())
for _name, _key in (("fabric.topology", "noc_config.topology_family"),
                    ("fabric.link_width", "noc_config.link_width")):
    PARAM_REGISTRY[_name] = ParamDef(
        name=_name, kind="HARDWARE", scenario_key="fabric_overrides",
        intent_key=_key, allowed=())


def registered_param(name: str) -> ParamDef:
    try:
        return PARAM_REGISTRY[name]
    except KeyError:
        raise OptimizationDefinitionError(
            f"unknown design parameter {name!r}; supported: "
            f"{sorted(PARAM_REGISTRY)}") from None


def patched_scenario_template(template: dict[str, Any],
                              assignment: dict[str, Any]) -> dict[str, Any]:
    """Scenario template with a candidate's overrides applied — the ONE
    patching implementation (§12/§107). Builder, verifier and evaluator
    all call this; a candidate's structural metrics see exactly the
    intent its evaluation saw."""
    patched = dict(template)
    overrides = dict(patched.get("fabric_overrides") or {})
    for pname, value in assignment.items():
        overrides[registered_param(pname).intent_key] = value
    patched["fabric_overrides"] = overrides
    return patched


# ── spec types ───────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ParameterSpec:
    """One declared finite design-variable domain (§15)."""
    name: str
    values: tuple[Any, ...]

    @classmethod
    def parse(cls, doc: Any) -> "ParameterSpec":
        if not isinstance(doc, dict):
            raise OptimizationDefinitionError(
                f"parameter must be an object, got {type(doc).__name__}")
        unknown = sorted(set(doc) - {"name", "values"})
        if unknown:
            raise OptimizationDefinitionError(
                f"parameter has unknown fields {unknown} (schema close)")
        name = doc.get("name")
        if not isinstance(name, str) or not name:
            raise OptimizationDefinitionError("parameter needs a name")
        registered_param(name)          # must be registered (§12)
        values = doc.get("values")
        if not isinstance(values, list) or not values:
            raise OptimizationDefinitionError(
                f"parameter {name!r} needs a non-empty values list")
        canon = tuple(_canonical_value(v) for v in values)
        # §84: domain-value order is not semantic; canonical sort.
        # §82: a duplicated domain value canonicalizes away — it does
        # not change the space or the identity.
        ordered = tuple(dict.fromkeys(
            sorted(canon, key=lambda v: (str(type(v)), str(v)))))
        return cls(name=name, values=ordered)

    def identity(self) -> dict[str, Any]:
        return {"name": self.name, "values": list(self.values)}


@dataclass(frozen=True)
class ScenarioSpec:
    """One explicitly declared workload scenario (§9)."""
    name: str
    intent: dict[str, Any]         # canonical intent document (template)

    @classmethod
    def parse(cls, doc: Any) -> "ScenarioSpec":
        if not isinstance(doc, dict):
            raise OptimizationDefinitionError(
                f"scenario must be an object, got {type(doc).__name__}")
        unknown = sorted(set(doc) - {"name", "intent"})
        if unknown:
            raise OptimizationDefinitionError(
                f"scenario has unknown fields {unknown} (schema close)")
        name = doc.get("name")
        if not isinstance(name, str) or not name:
            raise OptimizationDefinitionError("scenario needs a name")
        intent = doc.get("intent")
        if not isinstance(intent, dict):
            raise OptimizationDefinitionError(
                f"scenario {name!r} needs an intent object")
        return cls(name=name, intent=intent)


@dataclass(frozen=True)
class ObjectiveSpec:
    """One objective (§38): no implicit 'lower is better'."""
    metric: str
    direction: str                  # MINIMIZE | MAXIMIZE
    scenario: str | None            # None = scenario-free metric

    @classmethod
    def parse(cls, doc: Any) -> "ObjectiveSpec":
        if not isinstance(doc, dict):
            raise OptimizationDefinitionError(
                f"objective must be an object, got {type(doc).__name__}")
        unknown = sorted(set(doc) - {"metric", "direction", "scenario"})
        if unknown:
            raise OptimizationDefinitionError(
                f"objective has unknown fields {unknown} (schema close)")
        metric = doc.get("metric")
        if not isinstance(metric, str) or not metric:
            raise OptimizationDefinitionError("objective needs a metric")
        if metric not in METRIC_REGISTRY:
            raise OptimizationDefinitionError(
                f"objective metric {metric!r} is not in the metric registry")
        direction = doc.get("direction")
        if direction not in DIRECTIONS:
            raise OptimizationDefinitionError(
                f"objective {metric!r} direction must be one of "
                f"{DIRECTIONS}, got {direction!r}")
        scenario = doc.get("scenario")
        if scenario is not None and (not isinstance(scenario, str)
                                     or not scenario):
            raise OptimizationDefinitionError(
                f"objective {metric!r} scenario must be a string or null")
        return cls(metric=metric, direction=direction, scenario=scenario)

    def identity(self) -> dict[str, Any]:
        return {"metric": self.metric, "direction": self.direction,
                "scenario": self.scenario}


@dataclass(frozen=True)
class HardConstraintSpec:
    """One hard constraint (§45): value/==/</> truth table, no parsing."""
    metric: str
    scenario: str | None
    operator: str                   # <= | >=
    bound: Fraction                 # exact rational bound
    unit: str

    @classmethod
    def parse(cls, doc: Any) -> "HardConstraintSpec":
        if not isinstance(doc, dict):
            raise OptimizationDefinitionError(
                f"hard constraint must be an object, got "
                f"{type(doc).__name__}")
        unknown = sorted(set(doc) - {"metric", "scenario", "operator",
                                     "bound", "unit"})
        if unknown:
            raise OptimizationDefinitionError(
                f"hard constraint has unknown fields {unknown} "
                f"(schema close)")
        metric = doc.get("metric")
        if not isinstance(metric, str) or not metric:
            raise OptimizationDefinitionError(
                "hard constraint needs a metric")
        if metric not in METRIC_REGISTRY:
            raise OptimizationDefinitionError(
                f"constraint metric {metric!r} is not in the metric "
                f"registry")
        scenario = doc.get("scenario")
        if scenario is not None and (not isinstance(scenario, str)
                                     or not scenario):
            raise OptimizationDefinitionError(
                f"constraint {metric!r} scenario must be a string or null")
        operator = doc.get("operator")
        if operator not in OPERATORS:
            raise OptimizationDefinitionError(
                f"constraint {metric!r} operator must be one of "
                f"{OPERATORS}, got {operator!r}")
        bound = _exact(doc.get("bound"),
                       f"constraint {metric!r} bound")
        unit = doc.get("unit")
        expected_unit = METRIC_REGISTRY[metric].unit
        if unit != expected_unit:
            raise OptimizationDefinitionError(
                f"constraint {metric!r} unit {unit!r} does not match "
                f"the metric registry unit {expected_unit!r}")
        return cls(metric=metric, scenario=scenario, operator=operator,
                   bound=bound, unit=unit)

    def identity(self) -> dict[str, Any]:
        return {"metric": self.metric, "scenario": self.scenario,
                "operator": self.operator, "bound": _frac_doc(self.bound),
                "unit": self.unit}


def _exact(value: Any, what: str) -> Fraction:
    """Exact rational from JSON (int, "num/den", float via str, or the
    canonical {numerator, denominator} document that identity()
    itself emits — round-trip closure)."""
    if isinstance(value, bool):
        raise OptimizationDefinitionError(f"{what} must be numeric")
    if isinstance(value, int):
        return Fraction(value)
    if isinstance(value, dict):
        return frac_from_doc(value, what)
    if isinstance(value, str):
        try:
            return Fraction(value)
        except (ValueError, ZeroDivisionError):
            raise OptimizationDefinitionError(
                f"{what} must be an exact rational, got {value!r}") from None
    if isinstance(value, float):
        # Floats arrive from JSON; convert via their exact repr so the
        # declared bound round-trips identically on every host.
        return Fraction(repr(value))
    raise OptimizationDefinitionError(f"{what} must be numeric, got "
                                      f"{value!r}")


def _frac_doc(f: Fraction) -> dict[str, int]:
    """Canonical exact-rational JSON document ({numerator, denominator})."""
    return {"numerator": f.numerator, "denominator": f.denominator}


def frac_from_doc(doc: Any, what: str) -> Fraction:
    """Rebuild an exact Fraction from its canonical document form."""
    if not isinstance(doc, dict) or set(doc) != {"numerator",
                                                 "denominator"}:
        raise OptimizationDefinitionError(
            f"{what} must be an exact rational document "
            f"{{numerator, denominator}}, got {doc!r}")
    num, den = doc["numerator"], doc["denominator"]
    if not isinstance(num, int) or not isinstance(den, int) or den == 0 \
            or isinstance(num, bool) or isinstance(den, bool):
        raise OptimizationDefinitionError(
            f"{what} numerator/denominator must be nonzero-safe ints")
    return Fraction(num, den)


# ── closed metric registry (§31) ─────────────────────────────────────────

@dataclass(frozen=True)
class MetricDef:
    """One registered metric with its provenance contract."""
    name: str
    unit: str
    source: str                     # WAVE_E | WAVE_D_CHAIN | STRUCTURAL
    fidelity: str                   # EXACT_STRUCTURAL | MODEL_DERIVED
    applicability: str              # WAVE_E_TIMING | WAVE_D_TRAFFIC | ANY


#: Registry entries declare the unit and provenance of every metric a
#: request may name (§31: no arbitrary "foo": 17.3). Extraction lives in
#: optimization.metrics; unsupported/missing stays UNMEASURABLE there —
#: the registry only defines WHAT a metric means.
METRIC_REGISTRY: dict[str, MetricDef] = {
    "system.makespan_s": MetricDef(
        "system.makespan_s", "s", "WAVE_E", "MODEL_DERIVED",
        "WAVE_E_TIMING"),
    "network.window_s": MetricDef(
        "network.window_s", "s", "WAVE_E", "MODEL_DERIVED",
        "WAVE_E_TIMING"),
    "request.mean_latency_s": MetricDef(
        "request.mean_latency_s", "s", "WAVE_E", "MODEL_DERIVED",
        "WAVE_E_TIMING"),
    "request.p95_latency_s": MetricDef(
        "request.p95_latency_s", "s", "WAVE_E", "MODEL_DERIVED",
        "WAVE_E_TIMING"),
    "network.delivered_packets": MetricDef(
        "network.delivered_packets", "packets", "WAVE_D_CHAIN",
        "MODEL_DERIVED", "WAVE_D_TRAFFIC"),
    "fabric.router_count": MetricDef(
        "fabric.router_count", "routers", "STRUCTURAL",
        "EXACT_STRUCTURAL", "ANY"),
    "fabric.endpoint_count": MetricDef(
        "fabric.endpoint_count", "endpoints", "STRUCTURAL",
        "EXACT_STRUCTURAL", "ANY"),
    "fabric.channel_count": MetricDef(
        "fabric.channel_count", "channels", "STRUCTURAL",
        "EXACT_STRUCTURAL", "ANY"),
}


# ── the definition ───────────────────────────────────────────────────────

@dataclass(frozen=True)
class OptimizationDefinition:
    """Immutable, content-addressed optimization request (§8)."""
    name: str
    scenarios: tuple[ScenarioSpec, ...]
    parameters: tuple[ParameterSpec, ...]
    objectives: tuple[ObjectiveSpec, ...]
    hard_constraints: tuple[HardConstraintSpec, ...]
    search_policy: str
    budget: dict[str, int]
    selection_policy: str
    selection_metric_order: tuple[dict[str, Any], ...] = ()

    def scenario_names(self) -> list[str]:
        """Declared scenario names (canonical order)."""
        return [s.name for s in self.scenarios]

    def identity_dict(self) -> dict[str, Any]:
        # Canonical: scenarios/parameters sorted by name (§83), values
        # pre-sorted canonically (§84), everything else declaration order
        # with explicit meaning (objective/constraint order IS lexicographic
        # priority, and is declared, not accidental).
        return {
            "schema_version": OPTIMIZATION_SCHEMA_VERSION,
            "name": self.name,
            "scenarios": [
                {"name": s.name, "intent": _order_json(s.intent)}
                for s in sorted(self.scenarios, key=lambda s: s.name)],
            "parameters": [
                p.identity() for p in
                sorted(self.parameters, key=lambda p: p.name)],
            "objectives": [o.identity() for o in self.objectives],
            "hard_constraints": [c.identity()
                                 for c in self.hard_constraints],
            "search_policy": self.search_policy,
            "budget": {k: int(self.budget[k]) for k in sorted(self.budget)},
            "selection_policy": self.selection_policy,
            "selection_metric_order": list(self.selection_metric_order),
        }

    def definition_id(self) -> str:
        body = _OPT_TAG + "\0" + canonical_json(self.identity_dict())
        return hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {"resource_type": "optimizationdef",
                "schema_version": OPTIMIZATION_SCHEMA_VERSION,
                "resource_id": self.definition_id(),
                "artifact": self.identity_dict()}

    @classmethod
    def parse(cls, doc: Any) -> "OptimizationDefinition":
        if not isinstance(doc, dict):
            raise OptimizationDefinitionError(
                f"optimization request must be an object, got "
                f"{type(doc).__name__}")
        # schema_version is embedded in identity_dict so the persisted
        # resource round-trips; when present it must match exactly.
        if "schema_version" in doc and \
                doc["schema_version"] != OPTIMIZATION_SCHEMA_VERSION:
            raise OptimizationDefinitionError(
                f"schema_version {doc['schema_version']!r} != "
                f"{OPTIMIZATION_SCHEMA_VERSION}")
        unknown = sorted(set(doc) - {"name", "scenarios", "parameters",
                                     "objectives", "hard_constraints",
                                     "search_policy", "budget",
                                     "selection_policy",
                                     "selection_metric_order",
                                     "schema_version"})
        if unknown:
            raise OptimizationDefinitionError(
                f"optimization request has unknown fields {unknown} "
                f"(schema close)")
        name = doc.get("name")
        if not isinstance(name, str) or not name:
            raise OptimizationDefinitionError("needs a non-empty name")

        scenarios_raw = doc.get("scenarios")
        if not isinstance(scenarios_raw, list) or not scenarios_raw:
            raise OptimizationDefinitionError(
                "scenarios must be a non-empty list")
        scenarios = tuple(ScenarioSpec.parse(s) for s in scenarios_raw)
        snames = [s.name for s in scenarios]
        if len(set(snames)) != len(snames):
            raise OptimizationDefinitionError(
                f"duplicate scenario names {snames}")

        params_raw = doc.get("parameters")
        if not isinstance(params_raw, list) or not params_raw:
            raise OptimizationDefinitionError(
                "parameters must be a non-empty list")
        parameters = tuple(ParameterSpec.parse(p) for p in params_raw)
        pnames = [p.name for p in parameters]
        if len(set(pnames)) != len(pnames):
            raise OptimizationDefinitionError(
                f"duplicate parameter names {pnames}")

        obj_raw = doc.get("objectives")
        if not isinstance(obj_raw, list) or not obj_raw:
            raise OptimizationDefinitionError(
                "objectives must be a non-empty list")
        objectives = tuple(ObjectiveSpec.parse(o) for o in obj_raw)

        hc_raw = doc.get("hard_constraints", [])
        if not isinstance(hc_raw, list):
            raise OptimizationDefinitionError(
                "hard_constraints must be a list")
        hard = tuple(HardConstraintSpec.parse(c) for c in hc_raw)

        policy = doc.get("search_policy")
        if policy not in SEARCH_POLICIES:
            raise OptimizationDefinitionError(
                f"search_policy must be one of {SEARCH_POLICIES}, got "
                f"{policy!r}")
        budget_doc = doc.get("budget", {})
        if not isinstance(budget_doc, dict):
            raise OptimizationDefinitionError("budget must be an object")
        budget = _parse_budget(policy, budget_doc)

        sel_policy = doc.get("selection_policy", "NONE")
        if sel_policy not in SELECTION_POLICIES:
            raise OptimizationDefinitionError(
                f"selection_policy must be one of {SELECTION_POLICIES}, "
                f"got {sel_policy!r}")
        sel_order_raw = doc.get("selection_metric_order", [])
        if not isinstance(sel_order_raw, list):
            raise OptimizationDefinitionError(
                "selection_metric_order must be a list")
        sel_order = tuple(_parse_sel_metric(m, scenarios, objectives)
                          for m in sel_order_raw)
        _validate_selection(doc_name=name, sel_policy=sel_policy,
                            sel_order=sel_order, objectives=objectives,
                            scenarios=scenarios)

        return cls(name=name, scenarios=scenarios, parameters=parameters,
                   objectives=objectives, hard_constraints=hard,
                   search_policy=policy, budget=budget,
                   selection_policy=sel_policy,
                   selection_metric_order=sel_order)


def _parse_budget(policy: str, doc: dict[str, Any]) -> dict[str, int]:
    unknown = sorted(set(doc) - {"max_design_candidates",
                                 "max_scenario_evaluations"})
    if unknown:
        raise OptimizationDefinitionError(
            f"budget has unknown fields {unknown} (schema close)")
    out: dict[str, int] = {}
    for key in ("max_design_candidates", "max_scenario_evaluations"):
        val = doc.get(key)
        if val is None:
            continue
        if not isinstance(val, int) or isinstance(val, bool) or val < 1:
            raise OptimizationDefinitionError(
                f"budget.{key} must be a positive integer, got {val!r}")
        out[key] = val
    if policy == "BUDGETED_GRID" and not out:
        raise OptimizationDefinitionError(
            "BUDGETED_GRID requires a budget (max_design_candidates "
            "and/or max_scenario_evaluations)")
    if policy == "EXHAUSTIVE_GRID" and out:
        raise OptimizationDefinitionError(
            "EXHAUSTIVE_GRID evaluates every valid candidate (§22); "
            "a budget contradicts the declared policy — use "
            "BUDGETED_GRID")
    return out


def _parse_sel_metric(doc: Any, scenarios: tuple[ScenarioSpec, ...],
                      objectives: tuple[ObjectiveSpec, ...]
                      ) -> dict[str, Any]:
    if not isinstance(doc, dict) or sorted(doc) != ["metric", "scenario"]:
        raise OptimizationDefinitionError(
            "selection_metric_order entries must be "
            "{metric, scenario} objects")
    metric, scenario = doc["metric"], doc["scenario"]
    if not isinstance(metric, str) or metric not in METRIC_REGISTRY:
        raise OptimizationDefinitionError(
            f"selection metric {metric!r} is not in the metric registry")
    if scenario is not None and scenario not in \
            tuple(s.name for s in scenarios):
        raise OptimizationDefinitionError(
            f"selection metric {metric!r} names unknown scenario "
            f"{scenario!r}")
    matches = [o for o in objectives
               if o.metric == metric and o.scenario == scenario]
    if not matches:
        raise OptimizationDefinitionError(
            f"selection metric {metric}/{scenario} is not a declared "
            f"objective")
    return {"metric": metric, "scenario": scenario}


def _validate_selection(*, doc_name: str, sel_policy: str,
                        sel_order: tuple[dict[str, Any], ...],
                        objectives: tuple[ObjectiveSpec, ...],
                        scenarios: tuple[ScenarioSpec, ...]) -> None:
    if sel_policy == "NONE":
        if sel_order:
            raise OptimizationDefinitionError(
                "selection_metric_order requires selection_policy "
                "SINGLE_OBJECTIVE or LEXICOGRAPHIC")
        return
    if sel_policy == "SINGLE_OBJECTIVE":
        # The objective set must define exactly one value dimension:
        # single scenario-bearing objective, or one scenario-free metric
        # (§58: a plain min/max over exactly one objective).
        dims = {(o.metric, o.scenario) for o in objectives}
        if len(dims) != 1:
            raise OptimizationDefinitionError(
                "SINGLE_OBJECTIVE selection requires exactly one "
                "objective dimension; use LEXICOGRAPHIC or NONE")
        declared = sel_order[0] if sel_order else None
        metric, scenario = next(iter(dims))
        if declared is not None and (declared["metric"] != metric
                                     or declared["scenario"] != scenario):
            raise OptimizationDefinitionError(
                "selection_metric_order disagrees with the single "
                "declared objective")
    if sel_policy == "LEXICOGRAPHIC" and not sel_order:
        raise OptimizationDefinitionError(
            "LEXICOGRAPHIC selection requires selection_metric_order")
    if len(sel_order) != len({(m["metric"], m["scenario"])
                              for m in sel_order}):
        raise OptimizationDefinitionError(
            "selection_metric_order repeats a metric/scenario")


def _order_json(value: Any) -> Any:
    """Recursively sort dict keys for canonical embedding.

    Lists preserve order EXCEPT the intent's fabric_overrides mapping,
    which is a dict and therefore sorted by canonical_json anyway.
    """
    if isinstance(value, dict):
        return {k: _order_json(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_order_json(v) for v in value]
    return value
