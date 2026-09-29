"""topology_intent — the typed, family-specific topology authority (v4).

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar

from veritx_dse.core.errors import SemanticError


class TopologyIntentError(ValueError, SemanticError):
    """The declared topology intent cannot represent a physical structure."""


def _as_int(name: str, value: Any, *, minimum: int) -> int:
    if type(value) is not int or isinstance(value, bool):
        raise TopologyIntentError(f"{name} must be an int, got {value!r}")
    if value < minimum:
        raise TopologyIntentError(
            f"{name} must be >= {minimum}, got {value}")
    return value


class TopologyIntent:
    """Base class. Subclasses declare ``kind`` and their own parameters."""

    kind: ClassVar[str] = ""

    def parameters(self) -> dict[str, Any]:      # pragma: no cover - abstract
        raise NotImplementedError

    def to_dict(self) -> dict[str, Any]:
        """LOSSLESS persistence form."""
        return {"kind": self.kind, **self.parameters()}

    def scientific_dict(self) -> dict[str, Any]:
        """IDENTITY projection. Defaults to the lossless form; a variant
        overrides this only to strip something that is not design science
        (e.g. an explicit graph's presentation name)."""
        return self.to_dict()

    def intent_id(self) -> str:
        """Content identity of the DECLARED INTENT (not of the artifact).

        Built from the SCIENTIFIC projection, so an explicit graph's
        presentation name cannot change which design science this is.
        """
        body = json.dumps(self.scientific_dict(), sort_keys=True,
                          separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(
            b"veritx/topology-intent/v1\0" + body).hexdigest()


# ── named families ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MeshIntent(TopologyIntent):
    """A k x k nearest-neighbour mesh; each router seats `concentration`
    endpoints. `side_length` is the number of ROUTERS per side."""
    side_length: int
    concentration: int = 1
    kind: ClassVar[str] = "mesh"

    def __post_init__(self):
        _as_int("side_length", self.side_length, minimum=1)
        _as_int("concentration", self.concentration, minimum=1)

    def parameters(self):
        return {"side_length": self.side_length,
                "concentration": self.concentration}


@dataclass(frozen=True)
class ConcentratedMeshIntent(TopologyIntent):
    """A k x k mesh whose routers each seat `concentration` endpoints.

Rationale: docs/decisions/modules/model.md
    """
    side_length: int
    concentration: int
    kind: ClassVar[str] = "concentrated_mesh"

    def __post_init__(self):
        _as_int("side_length", self.side_length, minimum=1)
        _as_int("concentration", self.concentration, minimum=2)

    def parameters(self):
        return {"side_length": self.side_length,
                "concentration": self.concentration}


@dataclass(frozen=True)
class TorusIntent(TopologyIntent):
    """A k x k torus (wraparound in every dimension). Wraparound is what
    MAKES it a torus, so it is not a knob."""
    side_length: int
    concentration: int = 1
    kind: ClassVar[str] = "torus"

    def __post_init__(self):
        _as_int("side_length", self.side_length, minimum=1)
        _as_int("concentration", self.concentration, minimum=1)

    def parameters(self):
        return {"side_length": self.side_length,
                "concentration": self.concentration}


@dataclass(frozen=True)
class FlatFlyIntent(TopologyIntent):
    """A flattened butterfly: `dimension_count` dimensions, each a complete
    graph over `radix_per_dimension` routers, with concentration."""
    radix_per_dimension: int
    dimension_count: int
    concentration: int
    kind: ClassVar[str] = "flatfly"

    def __post_init__(self):
        _as_int("radix_per_dimension", self.radix_per_dimension, minimum=2)
        _as_int("dimension_count", self.dimension_count, minimum=1)
        _as_int("concentration", self.concentration, minimum=1)

    def parameters(self):
        return {"radix_per_dimension": self.radix_per_dimension,
                "dimension_count": self.dimension_count,
                "concentration": self.concentration}


@dataclass(frozen=True)
class FatTreeIntent(TopologyIntent):
    """A hierarchical indirect fat-tree.

Rationale: docs/decisions/modules/model.md
    """
    switch_radix: int
    level_count: int
    kind: ClassVar[str] = "fattree"

    def __post_init__(self):
        _as_int("switch_radix", self.switch_radix, minimum=2)
        _as_int("level_count", self.level_count, minimum=1)

    def parameters(self):
        return {"switch_radix": self.switch_radix,
                "level_count": self.level_count}

    @property
    def endpoint_capacity(self) -> int:
        return self.switch_radix ** self.level_count

    @property
    def switch_count(self) -> int:
        return self.level_count * self.switch_radix ** (self.level_count - 1)


# ── GEC ─────────────────────────────────────────────────────────────────────

class GecMode(str, Enum):
    """The four physical GEC constructions.

Rationale: docs/decisions/modules/model.md
    """
    MESH = "mesh"
    EXPRESS = "express"
    MULTIDROP = "multidrop"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class GecTopologyIntent(TopologyIntent):
    """GEC (a grid of routers plus long-range express channels).

Rationale: docs/decisions/modules/model.md
    """
    mode: GecMode
    grid_side_length: int
    concentration: int
    express_channel_groups_per_dimension: int | None = None
    destinations_per_express_channel: int | None = None
    kind: ClassVar[str] = "gec"

    def __post_init__(self):
        mode = self.mode if isinstance(self.mode, GecMode) else GecMode(
            self.mode)
        object.__setattr__(self, "mode", mode)
        _as_int("grid_side_length", self.grid_side_length, minimum=2)
        _as_int("concentration", self.concentration, minimum=1)
        groups = self.express_channel_groups_per_dimension
        dests = self.destinations_per_express_channel

        if mode is GecMode.MESH:
            if groups is not None or dests is not None:
                raise TopologyIntentError(
                    "GEC mesh mode is the NEAREST-NEIGHBOUR graph only: the "
                    "express-channel partitioning model does not apply to "
                    "it, so express_channel_groups_per_dimension and "
                    "destinations_per_express_channel are not expressible "
                    "(source: gec.cpp refuses mesh=1 with o/d other than "
                    "1/1). Declare GecMode.EXPRESS to build express "
                    "channels.")
            return

        if groups is None or dests is None:
            raise TopologyIntentError(
                f"GEC mode {mode.value!r} needs BOTH "
                "express_channel_groups_per_dimension and "
                "destinations_per_express_channel: the express channels "
                "span the grid exactly once, so neither can be defaulted "
                "without silently inventing a different physical design")
        _as_int("express_channel_groups_per_dimension", groups, minimum=1)
        _as_int("destinations_per_express_channel", dests, minimum=1)
        if mode is GecMode.EXPRESS and dests != 1:
            raise TopologyIntentError(
                "GEC express mode is POINT-TO-POINT: each express channel "
                f"reaches exactly one destination, got {dests}. Use "
                "GecMode.MULTIDROP for shared/tapped express channels.")
        if mode is GecMode.MULTIDROP and dests < 2:
            raise TopologyIntentError(
                "GEC multidrop (MECS) mode needs "
                f"destinations_per_express_channel >= 2, got {dests}: with "
                "one destination per channel there is no shared wire and "
                "the design is point-to-point express.")
        if groups * dests != self.grid_side_length - 1:
            raise TopologyIntentError(
                "GEC express channels must span the grid exactly once: "
                "express_channel_groups_per_dimension "
                f"({groups}) x destinations_per_express_channel ({dests}) "
                f"= {groups * dests} != grid_side_length - 1 "
                f"({self.grid_side_length - 1}). This is the source's "
                "o*d == k-1 law.")

    def parameters(self):
        return {"mode": self.mode.value,
                "grid_side_length": self.grid_side_length,
                "concentration": self.concentration,
                "express_channel_groups_per_dimension":
                    self.express_channel_groups_per_dimension,
                "destinations_per_express_channel":
                    self.destinations_per_express_channel}

    @property
    def shares_express_channels(self) -> bool:
        """True when express channels are a SHARED resource (one wire read by
        several destinations), which ordinary independent directed channels
        cannot represent."""
        return (self.destinations_per_express_channel or 1) > 1


# ── explicit graph ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ExplicitTopologyIntent(TopologyIntent):
    """An explicit graph IS the topology: the `TopologyIR` is the input.

Rationale: docs/decisions/modules/model.md
    """
    graph: Any
    kind: ClassVar[str] = "explicit"

    def __post_init__(self):
        from veritx_dse.model.topology_ir import TopologyIR
        if not isinstance(self.graph, TopologyIR):
            raise TopologyIntentError(
                f"explicit topology needs a TopologyIR graph, got "
                f"{type(self.graph).__name__}")
        if self.graph.kind not in ("custom", "anynet"):
            raise TopologyIntentError(
                f"explicit topology graph kind {self.graph.kind!r} is a "
                "TEMPLATE: a named family must be declared through its typed "
                "intent, not as an explicit graph")

    def parameters(self):
        return {"graph": self.graph.to_dict()}

    def scientific_dict(self):
        return {"kind": self.kind, "graph": self.graph.scientific_dict()}


# ── registry ────────────────────────────────────────────────────────────────

_KIND_TO_CLASS: dict[str, type[TopologyIntent]] = {
    "mesh": MeshIntent,
    "concentrated_mesh": ConcentratedMeshIntent,
    "torus": TorusIntent,
    "flatfly": FlatFlyIntent,
    "fattree": FatTreeIntent,
    "gec": GecTopologyIntent,
    "explicit": ExplicitTopologyIntent,
}

_FIELDS: dict[str, frozenset[str]] = {
    "mesh": frozenset({"kind", "side_length", "concentration"}),
    "concentrated_mesh": frozenset({"kind", "side_length", "concentration"}),
    "torus": frozenset({"kind", "side_length", "concentration"}),
    "flatfly": frozenset({"kind", "radix_per_dimension", "dimension_count",
                          "concentration"}),
    "fattree": frozenset({"kind", "switch_radix", "level_count"}),
    "gec": frozenset({"kind", "mode", "grid_side_length", "concentration",
                      "express_channel_groups_per_dimension",
                      "destinations_per_express_channel"}),
    "explicit": frozenset({"kind", "graph"}),
}

AUTHORABLE_INTENT_KINDS: tuple[str, ...] = tuple(sorted(_KIND_TO_CLASS))


def topology_intent_from_dict(d: Any) -> TopologyIntent:
    """Strict load. Unknown kinds and unknown keys are refused — a typo must
    not become a silently ignored parameter."""
    if not isinstance(d, dict):
        raise TopologyIntentError("topology intent must be an object")
    kind = d.get("kind")
    if kind not in _KIND_TO_CLASS:
        raise TopologyIntentError(
            f"unknown topology intent kind {kind!r} "
            f"(known: {sorted(_KIND_TO_CLASS)})")
    unknown = set(d) - _FIELDS[kind]
    if unknown:
        raise TopologyIntentError(
            f"topology intent {kind!r} has unknown fields {sorted(unknown)} "
            f"(allowed: {sorted(_FIELDS[kind])})")
    cls = _KIND_TO_CLASS[kind]
    kwargs = {k: v for k, v in d.items() if k != "kind"}
    if kind == "explicit":
        from veritx_dse.model.topology_ir import TopologyIR
        from veritx_dse.model.topology_ir import from_dict as _ir_from_dict
        raw = kwargs.get("graph")
        if isinstance(raw, dict):
            try:
                kwargs["graph"] = _ir_from_dict(raw, source="topology.graph")
            except Exception as e:                            # noqa: BLE001
                raise TopologyIntentError(
                    f"invalid explicit topology graph: {e}") from e
        elif not isinstance(raw, TopologyIR):
            raise TopologyIntentError(
                "explicit topology needs a graph document or a TopologyIR, "
                f"got {type(raw).__name__}")
    return cls(**kwargs)


def capability_family_label(intent: TopologyIntent) -> str:
    """The label capability truth reports this intent under.

    GEC is ONE registered kind but FOUR physical modes, and they progress
    differently (mesh/express/multidrop/hybrid all stop at different
    bridges). Reporting them as one row would hide that, so the label keeps
    the subfamily. This is a reporting label, never a design parameter.
    """
    if isinstance(intent, GecTopologyIntent):
        return f"gec_{intent.mode.value}"
    return intent.kind


# ── v2/v3 representation compatibility layer ────────────────────────────────

V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION = 4


def topology_intent_from_noc_config(
        family: Any, *, radix: int | None, concentration: int | None,
) -> TopologyIntent:
    """Derive a typed intent from the LEGACY (v2/v3) family + shape spelling.

Rationale: docs/decisions/modules/model.md
    """
    value = getattr(family, "value", family)
    conc = concentration or 1
    if value in (None, "mesh"):
        return MeshIntent(side_length=radix or 1, concentration=conc)
    if value == "concentrated_mesh":
        return ConcentratedMeshIntent(
            side_length=radix or 1,
            concentration=concentration
            or V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION)
    if value == "torus":
        return TorusIntent(side_length=radix or 1, concentration=conc)
    if value == "flatfly":
        raise TopologyIntentError(
            "the legacy 'flatfly' spelling does not determine a physical "
            "design: a flattened butterfly needs a per-dimension radix, a "
            "dimension count and a concentration, and the legacy shape "
            "carries only one number. Supply a FlatFlyIntent instead of "
            "guessing which of the three it meant.")
    if value in ("gec", "fattree", "fat_tree"):
        raise TopologyIntentError(
            f"the legacy {value!r} spelling does not determine a physical "
            "design: it carries no mode/structure. Supply a "
            f"{'GecTopologyIntent' if value == 'gec' else 'FatTreeIntent'} "
            "explicitly — no default to the source's internal fallback.")
    if value == "custom":
        raise TopologyIntentError(
            "the legacy 'custom' spelling names an explicit GRAPH, which "
            "must be carried by an ExplicitTopologyIntent(graph=...) — the "
            "graph is the design, so it cannot be derived from a family name")
    raise TopologyIntentError(
        f"topology family {value!r} has no typed intent: it is RECOGNIZED "
        "and AUTHORABLE but no intent variant exists for it yet — no silent "
        "fallback to another family's parameters")


__all__ = [
    "TopologyIntent", "TopologyIntentError", "GecMode",
    "MeshIntent", "ConcentratedMeshIntent", "TorusIntent", "FlatFlyIntent",
    "FatTreeIntent", "GecTopologyIntent", "ExplicitTopologyIntent",
    "AUTHORABLE_INTENT_KINDS", "capability_family_label",
    "topology_intent_from_dict", "topology_intent_from_noc_config",
    "V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION",
]
