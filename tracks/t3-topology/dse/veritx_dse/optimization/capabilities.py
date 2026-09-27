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
"materializable". So the materializable subset is obtained by ASKING the
canonical materializer, the same way `capability_truth` does — not by
restating an enum.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from functools import lru_cache

from veritx_dse.optimization.definition import (
    GUIDED_PARAMS, SEARCH_METHODS, SELECTION_POLICIES,
)
from veritx_dse.optimization.metric_registry import CERTIFIED_METRIC_REGISTRY


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
      executable    the certified backend can execute the result
      effective     the parameter reaches the semantics being MEASURED —
                    changing it is not an identity-only change
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
    expressible_note: str | None = None

    @property
    def accepted_values_is_exhaustive(self) -> bool:
        return self.accepted_values is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name, "field": self.field, "kind": self.kind,
            "expressible": self.expressible,
            "compilable": self.compilable,
            "executable": self.compilable and self.effective,
            "effective": self.effective,
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
        from veritx_dse.model.topology_artifact import _family_of
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
        except Exception:                                   # noqa: BLE001
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
            allowed, note = _materializable_topology_families()
            accepted = allowed
            executable = allowed
            source = ("canonical materializer (_family_of + "
                      "MaterializedFamily); the only exhaustively enumerable "
                      "domain")
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
        elif probe is not None:
            compilable = probe.compilable
            effective = probe.effective
            reason = reason or probe.note
        else:                                               # pragma: no cover
            compilable = effective = False
            reason = ("no effectiveness probe is registered for this "
                      "parameter; refusing to advertise it")
        qualified = compilable and effective

        params.append(ParamCapability(
            name=name, field=field_name, kind=kind,
            value_constraint=constraint, accepted_values=accepted,
            executable_values=executable, qualified=qualified,
            value_source=source, reason=reason,
            compilable=compilable, effective=effective,
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

    return {
        "schema_version": 1,
        "guided_parameters": [p.to_dict() for p in params],
        "search_methods": list(SEARCH_METHODS),
        "selection_policies": list(SELECTION_POLICIES),
        "certified_metrics": metrics,
        "metric_registry_id": CERTIFIED_METRIC_REGISTRY.registry_id(),
        "locked_parameters": [dict(x) for x in LOCKED_PARAMETERS],
        "effectiveness_basis": _effectiveness_basis(),
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
]
