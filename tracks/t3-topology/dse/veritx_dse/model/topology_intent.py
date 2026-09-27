"""topology_intent — the typed, family-specific topology authority (v4).

WHY THIS EXISTS
===============

`NocConfig` carried `topology_family` + `radix` + `concentration`. That is a
mesh-shaped vocabulary, and it is already insufficient:

  * GEC needs a grid side, concentration, express-channel grouping, a
    destinations-per-channel count AND a physical mode;
  * FlatFly needs a per-dimension radix, a dimension count and concentration;
  * Torus needs extents and wrap semantics;
  * fat-tree needs a switch radix and a level count.

The wrong fix is to let `NocConfig` accumulate every backend parameter. The
other wrong fix is to expose BookSim's `k`/`n`/`c`/`o`/`d` as the scientific
API because the backend happens to use those letters.

So topology intent is TYPED. Each variant owns exactly the parameters its
family's science needs, under scientific names, and a parameter that is
meaningless for a family is not expressible for it.

THE CENTRAL LAW (PHASE B.1 §5)
==============================

    THE INTENT MUST BE ABLE TO EXPRESS THE PHYSICAL DESIGN EVEN WHEN NO
    MATERIALIZER EXISTS YET.

Authorability and materializability are DIFFERENT stages. A multidrop GEC
design is real physical science (BookSim implements it over shared, tapped
`MultiDropChannel`s). Saying "this is a multidrop GEC design" must be legal
even though the canonical `TopologyArtifact` cannot represent a shared
resource yet. So the intent accepts it and MATERIALIZATION refuses it.

Refusing MECS *materialization* is correct. Refusing MECS *design intent* is
not.

WHAT THIS IS NOT
================

Topology intent describes PHYSICAL STRUCTURE only. It never carries a routing
function, a backend config, a backend profile or a VC policy — routing is
downstream of topology, and backend projection is downstream of both.

For an explicit graph the graph IS the input, so `ExplicitTopologyIntent`
carries the `TopologyIR` itself. That keeps v4 to ONE topology field: two
topology authorities cannot even be expressed, let alone disagree.
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

    Distinct from MeshIntent because the concentration is the scientific
    point of the family, not a default: a concentrated mesh at concentration
    1 is a mesh, and saying so explicitly is a different declaration.
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

    Source: `third_party/booksim2/src/networks/fattree.cpp`. The physical
    structure is fixed by two facts:

      switch_radix (source `k`)  ports per DIRECTION at a switch. A switch
                                 therefore has 2*switch_radix total ports,
                                 except at the top level which has
                                 switch_radix.
      level_count  (source `n`)  hierarchy levels.

    From those, endpoint capacity = switch_radix ** level_count and switch
    count = level_count * switch_radix ** (level_count - 1). The intent
    carries the STRUCTURE; the derived counts are properties, not knobs.

    Authorable now, materializable later — no materializer is invented here.
    """
    switch_radix: int
    level_count: int
    concentration: int = 1
    kind: ClassVar[str] = "fattree"

    def __post_init__(self):
        _as_int("switch_radix", self.switch_radix, minimum=2)
        _as_int("level_count", self.level_count, minimum=1)
        _as_int("concentration", self.concentration, minimum=1)

    def parameters(self):
        return {"switch_radix": self.switch_radix,
                "level_count": self.level_count,
                "concentration": self.concentration}

    @property
    def endpoint_capacity(self) -> int:
        return (self.switch_radix ** self.level_count) * self.concentration

    @property
    def switch_count(self) -> int:
        return self.level_count * self.switch_radix ** (self.level_count - 1)


# ── GEC ─────────────────────────────────────────────────────────────────────

class GecMode(str, Enum):
    """The four physical GEC constructions.

    `mesh` and `hybrid` are mutually exclusive in the source; `mesh` forbids
    the express-channel partitioning entirely.
    """
    MESH = "mesh"
    EXPRESS = "express"
    MULTIDROP = "multidrop"
    HYBRID = "hybrid"


@dataclass(frozen=True)
class GecTopologyIntent(TopologyIntent):
    """GEC (a grid of routers plus long-range express channels).

    Source: `third_party/booksim2/src/networks/gec.cpp`. Physical facts:

      * a `grid_side_length` x `grid_side_length` grid of routers, each
        seating `concentration` endpoints;
      * `express_channel_groups_per_dimension` express-channel groups leave
        each router per dimension, each group reaching
        `destinations_per_express_channel` destinations;
      * for every NON-mesh mode the source law is

            express_channel_groups_per_dimension
              x destinations_per_express_channel
              == grid_side_length - 1

        (this is `o * d == k - 1` in the source, and it is the reason the
        express channels span the grid exactly once);
      * `mesh` mode is the nearest-neighbour graph ONLY: the partitioning
        model does not apply, so express parameters are not expressible;
      * `multidrop` mode is MECS: one shared, tapped wire per express
        channel, with several destinations reading the same transmission.

    THE MODE IS PHYSICAL SCIENCE, NOT A BACKEND KNOB. `destinations_per_
    express_channel > 1` is a legal declaration here; whether the canonical
    artifact can represent a shared resource is a MATERIALIZATION question,
    answered downstream.
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

    Carrying the graph HERE (rather than in a sibling request field) is what
    keeps v4 to ONE topology field, so two topology authorities cannot even
    be expressed.

    The graph's scientific content is design identity. Its `name` is
    presentation and is excluded — a synthesized candidate and the identical
    hand-authored graph must be the same design science.
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
    "fattree": frozenset({"kind", "switch_radix", "level_count",
                          "concentration"}),
    "gec": frozenset({"kind", "mode", "grid_side_length", "concentration",
                      "express_channel_groups_per_dimension",
                      "destinations_per_express_channel"}),
    "explicit": frozenset({"kind", "graph"}),
}

#: Every topology kind a v4 design may declare. Capability truth DERIVES its
#: probe coverage from this, so a newly registered kind cannot be silently
#: ungated (PHASE B.1 §18.1).
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
        # The persisted form carries the graph as a plain document; the
        # in-memory form carries a TopologyIR. Convert HERE and nowhere else,
        # so a persisted intent always reloads to the same object.
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

#: Frozen v3 default concentration for concentrated mesh, used ONLY by the
#: migration. It is a literal on purpose: reading a mutable current default
#: would make a migration's meaning depend on when it ran.
V3_CONCENTRATED_MESH_DEFAULT_CONCENTRATION = 4


def topology_intent_from_noc_config(
        family: Any, *, radix: int | None, concentration: int | None,
) -> TopologyIntent:
    """Derive a typed intent from the LEGACY (v2/v3) family + shape spelling.

    This is the compatibility layer used by the internal normalization seam.
    It is NOT a second authority: the typed intent is derived from the legacy
    spelling, so the two can never disagree.

    It deliberately REFUSES families whose legacy spelling does not determine
    a physical design (GEC's four modes, fat-tree's structure) rather than
    defaulting to a plausible-looking guess.
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
