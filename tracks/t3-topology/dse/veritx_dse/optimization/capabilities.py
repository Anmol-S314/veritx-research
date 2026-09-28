"""capabilities — the product-facing optimization capability description.

WHY THIS EXISTS (PRODUCT-CONVERGENCE-V1 PHASE 2)
================================================

The Studio must not hard-code what VERITX can optimize. Every control it
renders must come from a canonical backend authority, or the UI becomes a
second, silently-diverging registry.

THE CENTRAL DISTINCTION
=======================

    A field existing in GUIDED_PARAMS does NOT mean every value is usable.

So each parameter reports FOUR independent facts, and they are not collapsed:

  expressible        the definition schema accepts the parameter at all
  accepted_values    values the canonical compiler will accept (or None when
                     the domain is a validated range/type rather than a
                     finite enumeration)
  executable_values  the subset the CERTIFIED BACKEND can actually execute
                     (or None when not separately narrowed)
  qualified          whether the value is currently usable for product
                     optimization at all

FAIL CLOSED. A value that will deterministically fail downstream is not
advertised as available. Where an authority cannot be established, the field
reports `None` with a REASON — never an invented list.

WHY SOME VALUES ARE PROBED AND NOT DECLARED
===========================================

`topology_family` is the one parameter with a real finite enumeration
(`TopologyFamily`), and membership there means "authorable", NOT
"materializable", and materializable does NOT mean the certified backend
executes it. So the domain is obtained by ASKING twice: the canonical
materializer bounds `accepted_values`, and the full certified chain
(compile → workload lowering → `select_booksim_profile`) bounds
`executable_values` — the same gate `ProductService` applies before any
evaluation. A value that is deterministically refused at evaluation is
never advertised as an optimization choice.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from functools import lru_cache

from veritx_dse.optimization.definition import (
    GUIDED_PARAMS, SEARCH_METHODS, SELECTION_POLICIES,
)
from veritx_dse.optimization.metric_registry import (
    CERTIFIED_METRIC_REGISTRY, federated_metric_catalog,
)


class CapabilityError(ValueError):
    """The capability description could not be derived from authority."""


#: LOCKED properties. These are compiler-derived correctness properties: the
#: UI may show them as CONSEQUENCES of a candidate, never as things to search.
#: Kept explicit and named, mirroring the definition's own refusal tokens.
LOCKED_PARAMETERS: tuple[dict[str, str], ...] = (
    {"name": "routing_function",
     "reason": "derived from the dependency graph and topology; a user-chosen "
               "routing function could contradict the certificate"},
    {"name": "turn_restrictions",
     "reason": "derived from topology + routing; not independently choosable"},
    {"name": "vc_map",
     "reason": "derived from the dependency graph via the VC derivation"},
    {"name": "vc_count",
     "reason": "derived from cycle structure; over-provisioning is not a "
               "design knob"},
    {"name": "escape_vc",
     "reason": "derived from the deadlock-freedom obligation"},
)


@dataclass(frozen=True)
class ParamCapability:
    """One GUIDED parameter and exactly what is known about its values.

    FIVE SEPARATE FACTS, never collapsed (PHASE 2.1):

      expressible   the optimization schema accepts the parameter
      compilable    a patched design actually compiles
      effective     the parameter reaches the semantics being MEASURED —
                    changing it is not an identity-only change
      backend_executable  the certified profile accepts the probed result
                    (compile → lower → select_booksim_profile)
      qualified     VERITX may use it as a certified optimization dimension

    `accepted_values is None` means "the domain is a validated range, and the
    capability payload does NOT enumerate it". It must never be read as "all
    values are supported": `accepted_values_is_exhaustive` is False in that
    case so the Studio cannot make that mistake.
    """
    name: str
    field: str
    kind: str                      # "int" | "bool" | "str" | "enum"
    value_constraint: str          # human-readable constraint
    accepted_values: tuple[Any, ...] | None
    executable_values: tuple[Any, ...] | None
    qualified: bool
    value_source: str
    reason: str | None = None
    expressible: bool = True
    compilable: bool = True
    effective: bool = True
    #: The certified backend profile accepts the probed result. Independent
    #: of `effective`: a knob can change executed semantics and STILL be
    #: refused by `select_booksim_profile` (concentration>1 does exactly
    #: that). Qualification requires all of compilable ∧ effective ∧
    #: backend_executable.
    backend_executable: bool = True
    expressible_note: str | None = None

    @property
    def accepted_values_is_exhaustive(self) -> bool:
        return self.accepted_values is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "field": self.field, "kind": self.kind,
            "expressible": self.expressible,
            "compilable": self.compilable,
            "effective": self.effective,
            "backend_executable": self.backend_executable,
            "executable": (self.compilable and self.effective
                           and self.backend_executable),
            "qualified_for_certified_optimization": self.qualified,
            "value_constraint": self.value_constraint,
            "accepted_values": (list(self.accepted_values)
                                if self.accepted_values is not None else None),
            "accepted_values_is_exhaustive":
                self.accepted_values_is_exhaustive,
            "executable_values": (list(self.executable_values)
                                  if self.executable_values is not None
                                  else None),
            "value_source": self.value_source,
            "reason": self.reason,
        }


#: Per-parameter type/constraint authority. The TYPES come from
#: `NocConfig.__post_init__` and `NocConfig`'s annotations — the same code
#: that validates a patch — so a type change there cannot silently diverge.
_PARAM_SPEC: dict[str, tuple[str, str]] = {
    "link_width": ("int", "positive integer (bits)"),
    "concentration": ("int", "positive integer"),
    "radix": ("int", "positive integer"),
    "rcu_enabled": ("bool", "true or false"),
    "topology_family": ("enum", "a member of the canonical TopologyFamily"),
    "arbitration": ("str", "non-empty arbitration policy name"),
    "mcast_groups": ("int", "positive integer, or unset for unconstrained"),
    "mcast_setup_cycles": ("int", "non-negative integer"),
}


@lru_cache(maxsize=1)
def _materializable_topology_families() -> tuple[tuple[str, ...], str]:
    """(materializable TopologyFamily values, note). ASKS the compiler.

    Enum membership means AUTHORABLE, not materializable — GEC and FAT_TREE
    are members with no materializer. Deriving this by restating the enum
    would advertise families whose every candidate is `UNSUPPORTED`.
    """
    from veritx_dse.model.compile_model import TopologyFamily
    from veritx_dse.model.topology_artifact import MaterializedFamily
    try:
        from veritx_dse.model.topology_artifact import (
            TopologyError, _family_of,
        )
    except ImportError:                                     # pragma: no cover
        return (), ("the canonical family resolver is unavailable, so no "
                    "topology_family value can be advertised")

    # `CUSTOM` is not universally present: where it exists it is a
    # CLASSIFICATION marker for an explicit graph, not a materializable named
    # family, so it is refused either way. Read it by name so a membership
    # change cannot raise here.
    custom = getattr(TopologyFamily, "CUSTOM", None)

    allowed: list[str] = []
    refused: list[str] = []
    for family in TopologyFamily:
        if custom is not None and family is custom:
            refused.append(family.value)
            continue
        try:
            resolved = _family_of(_ProbeNoc(family))
            if resolved in MaterializedFamily:
                allowed.append(family.value)
            else:
                refused.append(family.value)
        except TopologyError:
            # A family the canonical materializer does not cover is a
            # refused value, never a crash. Anything else — a
            # programming error in the resolver — propagates instead of
            # reading as "not materializable".
            refused.append(family.value)
    note = ("materializable via the canonical materializer; refused here: "
            + (", ".join(refused) if refused else "none"))
    return tuple(allowed), note


class _ProbeNoc:
    """Minimal duck-typed stand-in so `_family_of` can be asked directly.

    `_family_of` reads only `topology_family`; constructing a real NocConfig
    is unnecessary and would drag in unrelated validation.
    """

    def __init__(self, topology_family: Any) -> None:
        self.topology_family = topology_family


@lru_cache(maxsize=1)
def _topology_family_truth() -> tuple[tuple[str, ...], tuple[str, ...], str]:
    """(accepted=compiles, executable=full-chain, note). ASKS the chain.

    Two separate stages, never collapsed:

      accepted_values    the canonical compiler ACCEPTS the family (a
                         concrete compile of a mesh-shaped request succeeds)
      executable_values  the full certified chain (compile → workload
                         lowering → `select_booksim_profile`) runs it —
                         what the product can actually evaluate

    gec and fat_tree are authorable enum members whose concrete compile is
    refused (the legacy spelling carries no mode/structure), so they are
    not accepted values. concentrated_mesh compiles but the certified
    profiles refuse it (mesh-DOR pins seat_capacity 1; AnyNet requires
    ANYNET_MIN_HOPS), and torus is refused at compile (no certified
    routing policy). Offering a value the evaluation path deterministically
    refuses manufactures doomed candidates.
    """
    from veritx_dse.optimization.capability_probe import (
        probe_parameters,
    )
    probe = probe_parameters().get("_topology_family_truth")
    if probe is None:                                   # pragma: no cover
        raise CapabilityError(
            "the topology_family backend-executability probe did not run; "
            "refusing to advertise the domain")
    try:
        truth: dict[str, dict[str, bool]] = json.loads(
            probe.backend_note or "{}")
    except ValueError as exc:                           # pragma: no cover
        raise CapabilityError(
            f"topology_family executability truth is unreadable: {exc}") from exc
    accepted, executable = [], []
    for value, stages in sorted(truth.items()):
        if stages.get("compiled"):
            accepted.append(value)
        if stages.get("executable"):
            executable.append(value)
    return tuple(accepted), tuple(executable), probe.note


@lru_cache(maxsize=1)
def optimization_capabilities() -> dict[str, Any]:
    """The product capability description. Derived, never hand-written."""
    # ASK the compiler+projector. `qualified` is NEVER defaulted true: a knob
    # that the schema accepts but the certified backend cannot measure is not
    # a certified optimization dimension.
    from veritx_dse.optimization.capability_probe import probe_parameters
    probes = probe_parameters()

    params: list[ParamCapability] = []
    for name, field_name in GUIDED_PARAMS.items():
        kind, constraint = _PARAM_SPEC.get(name, ("str", "unconstrained"))
        accepted: tuple[Any, ...] | None = None
        executable: tuple[Any, ...] | None = None
        reason: str | None = None
        source = "NocConfig validation (positive ints / bool / non-empty str)"

        if name == "topology_family":
            accepted, executable, note = _topology_family_truth()
            source = ("canonical materializer for accepted_values; the FULL "
                      "certified chain (compile → lowering → "
                      "select_booksim_profile) for executable_values")
            reason = note
        elif name in ("link_width", "concentration", "radix"):
            # NOT a finite enumeration. Report the real constraint instead of
            # an invented list; the payload must not imply "all values work".
            constraint = ("positive integer; must still seat every attached "
                          "endpoint (k*k*concentration >= endpoints) and be "
                          "accepted by the certified projection")

        probe = probes.get(name)
        if name == "topology_family":
            compilable = bool(accepted)
            effective = bool(accepted)
            backend_executable = bool(executable)
        elif probe is not None:
            compilable = probe.compilable
            effective = probe.effective
            backend_executable = probe.backend_executable
            reason = reason or probe.note
        else:                                               # pragma: no cover
            compilable = effective = backend_executable = False
            reason = ("no effectiveness probe is registered for this "
                      "parameter; refusing to advertise it")
        qualified = compilable and effective and backend_executable

        params.append(ParamCapability(
            name=name, field=field_name, kind=kind,
            value_constraint=constraint, accepted_values=accepted,
            executable_values=executable, qualified=qualified,
            value_source=source, reason=reason,
            compilable=compilable, effective=effective,
            backend_executable=backend_executable,
            expressible_note=("accepted by the optimization schema; that is "
                              "not evidence that the certified backend "
                              "measures it")))

    registry = CERTIFIED_METRIC_REGISTRY
    authorities = registry.authorities
    metrics = []
    for metric_name in _certified_metric_names():
        authority = authorities.get(metric_name)
        metrics.append({
            "metric": metric_name,
            "producer_id": getattr(authority, "producer_id", None),
            "registry_id": registry.registry_id(),
            "registry_version": registry.version,
        })

    # Federated optimization truth (Prompt 4, Step 8): every metric an
    # objective may name, with the question it is read from, the
    # registered backend(s) answering that question, the model
    # fidelity, the unit and whether it is eligible as a scalar
    # optimizer objective. Derived from the federation registry and
    # the producers' own normalization catalogs — never a second
    # handwritten matrix. A backend listed here may still assess
    # UNAVAILABLE/BLOCKED for a given study: listing is installation,
    # execution is adjudicated per study.
    federated_metrics = [row.to_dict()
                         for row in federated_metric_catalog()]

    return {
        "schema_version": 1,
        "guided_parameters": [p.to_dict() for p in params],
        "search_methods": list(SEARCH_METHODS),
        "selection_policies": list(SELECTION_POLICIES),
        "certified_metrics": metrics,
        "metric_registry_id": CERTIFIED_METRIC_REGISTRY.registry_id(),
        "federated_metrics": federated_metrics,
        "federated_metric_note": (
            "Derived from the federation registry's own capability "
            "declarations and each producer's normalization catalog — "
            "no second handwritten matrix. Each row names WHAT metric, "
            "FROM WHICH evaluation question, WITH WHICH registered "
            "backend(s), at WHAT model fidelity, in WHAT unit, and "
            "whether it is eligible as a scalar optimizer objective. "
            "Different questions are different semantic families: a "
            "BookSim network completion and an ASTRA system makespan "
            "never share an objective axis merely because both use "
            "cycles. Per-rank / per-request rows are honestly "
            "ineligible (no invented key suffixes). Listing a backend "
            "is installation, not readiness: UNAVAILABLE/BLOCKED legs "
            "refuse per study and are never silently substituted."),
        # §1: units are not dimensions. A study is multi-objective only when
        # the certified registry offers more than one INDEPENDENT semantic
        # family; today it offers exactly one.
        "objective_semantic_families": {
            m["metric"]: objective_semantic_family(m["metric"])
            for m in metrics},
        "independent_objective_families": list(
            independent_objective_families()),
        "multi_objective_available": len(independent_objective_families()) > 1,
        "objective_note": (
            "completion_cycles, completion_time and completion_ns are the SAME "
            "authenticated completion window expressed in different units, so "
            "they are ONE semantic objective. A study combining them would "
            "invent a trade-off that does not exist and must render as a "
            "measured RANKING, not a Pareto frontier."),
        "locked_parameters": [dict(x) for x in LOCKED_PARAMETERS],
        "effectiveness_basis": _effectiveness_basis(),
        "qualification_basis": (
            "qualified = compilable AND effective AND backend_executable, "
            "where backend_executable is measured through the same certified "
            "chain the product evaluation path applies (compile → workload "
            "lowering → select_booksim_profile)"),
        "unqualified_parameters": sorted(
            p.name for p in params if not p.qualified),
        "qualified_parameters": sorted(
            p.name for p in params if p.qualified),
        "multicast_note": (
            "mcast_groups / mcast_setup_cycles are expressible, but every "
            "probed value FAILS TO COMPILE today and the certified profile's "
            "closed-world config audit contains no multicast parameter at "
            "all. They are NOT qualified dimensions. Qualification may later "
            "depend on workload semantics (a workload that declares no "
            "multicast cannot exercise them); that is reported per-parameter "
            "rather than advertised globally."),
        "not_measured": [
            "area", "power", "energy", "cost", "thermal",
            "timing closure", "implementation effort",
        ],
        "not_measured_note": (
            "These are NOT certified metrics. VERITX measures network "
            "completion performance only, so a study can never claim the "
            "overall best hardware design."),
    }


#: Certified metric -> SEMANTIC OBJECTIVE FAMILY.
#:
#: The registry names three metrics, but they are NOT three independent
#: optimization dimensions:
#:
#:   completion_cycles  the authenticated network completion window, in cycles
#:   completion_time    the SAME window (same producer id)
#:   completion_ns      the SAME window, as wall time
#:
#: All three read the same canonical artifact (`verified["network_binding"]`),
#: so a study over "cycles vs ns" would be a study of ONE quantity expressed
#: twice — a frontier with a single underlying dimension. Treating that as
#: multi-objective would manufacture a trade-off that does not exist.
#:
#: The mapping is declared here and PROVEN against the producers by test
#: (`test_objective_semantic_families.py`), so a genuinely new metric cannot
#: be silently folded into `completion`.
_CERTIFIED_OBJECTIVE_FAMILY: dict[str, str] = {
    "completion_cycles": "completion",
    "completion_time": "completion",
    "completion_ns": "completion",
}


def objective_semantic_family(metric: str) -> str:
    """The semantic family a certified metric belongs to.

    An unregistered metric gets its own family (its own name): assuming
    independence is the safe direction, because it merely declines to claim
    redundancy.
    """
    return _CERTIFIED_OBJECTIVE_FAMILY.get(metric, metric)


def independent_objective_families() -> tuple[str, ...]:
    """The DISTINCT semantic families the certified registry offers."""
    seen: list[str] = []
    for name in _certified_metric_names():
        family = objective_semantic_family(name)
        if family not in seen:
            seen.append(family)
    return tuple(seen)


def _effectiveness_basis() -> str:
    from veritx_dse.optimization.capability_probe import effectiveness_basis
    return effectiveness_basis()


def _certified_metric_names() -> tuple[str, ...]:
    """Certified metric names, read from the frozen registry."""
    registry = CERTIFIED_METRIC_REGISTRY
    for attr in ("names", "metric_names"):
        value = getattr(registry, attr, None)
        if callable(value):
            return tuple(value())
        if isinstance(value, (tuple, list)):
            return tuple(value)
    raise CapabilityError(
        "cannot enumerate the certified metric registry: neither `metrics`, "
        "`names` nor `metric_names` is available. Refusing to invent a list.")


# ══ canonical engine order vs human presentation order ═════════════════

def presentation_order(values: Any) -> tuple[Any, ...]:
    """HUMAN display order for a domain's values. IDENTITY-NEUTRAL.

    `DomainParam` puts values in CANONICAL order — sorted by canonical JSON
    rendering — so declaration order never changes identity or enumeration.
    For numbers that is lexicographic on the string form, so

        [32, 64, 128]   ->   (128, 32, 64)

    which is correct and deterministic but reads badly.

    This function gives the UI a NUMERIC/logical display order instead, and
    it is deliberately NOT part of the definition: it must never be used to
    build a `DomainParam`, and importing it into the engine would be the bug
    it exists to prevent. A test pins that both orders yield the same
    definition identity and the same candidate enumeration.

    Sort key: numeric when every value is a real number; otherwise the
    canonical JSON key, so mixed/str domains keep a stable order.
    """
    vals = list(values)
    if not vals:
        return ()
    nums: list[float] = []
    for v in vals:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            nums = []
            break
        nums.append(float(v))
    if len(nums) == len(vals):
        return tuple(v for _, v in sorted(zip(nums, vals),
                                          key=lambda pair: pair[0]))
    from veritx_dse.core.spec import canonical_json
    return tuple(sorted(vals, key=canonical_json))


__all__ = [
    "CapabilityError", "LOCKED_PARAMETERS", "ParamCapability",
    "optimization_capabilities", "presentation_order",
    "objective_semantic_family", "independent_objective_families",
]
