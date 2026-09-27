"""topology_intent — the typed, family-specific topology authority.

WHY THIS EXISTS
===============

`NocConfig` carried `topology_family` + `radix` + `concentration`. That is a
mesh-shaped vocabulary, and it is already insufficient:

  * GEC needs a grid side, concentration, an express-channel grouping and the
    number of destinations each express channel reaches;
  * FlatFly needs a per-dimension radix, a dimension count and concentration;
  * Torus needs extents and wrap semantics;
  * fat-tree / dragonfly will need different structural parameters again.

The wrong fix is to let `NocConfig` accumulate every backend parameter. The
other wrong fix is to expose BookSim's `k`/`n`/`c`/`o`/`d` as the scientific
API because the backend happens to use those letters.

So topology intent is TYPED. Each variant owns exactly the parameters its
family's science needs, under scientific names. Backend spellings live only
in the projection layer, and a parameter that is meaningless for a family is
not expressible for it.

WHAT THIS IS NOT
================

Topology intent describes PHYSICAL STRUCTURE only. It never carries a routing
function, a backend config, a backend profile or a VC policy — routing is
downstream of topology, and backend projection is downstream of both.

`ExplicitTopologyIntent` is a marker: for an explicit graph the graph IS the
input (a `TopologyIR`), so there are no shape parameters to type.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
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
        return {"kind": self.kind, **self.parameters()}

    def intent_id(self) -> str:
        """Content identity of the DECLARED INTENT (not of the artifact).

        Two requests declaring the same topology science have the same
        intent id regardless of ordering or of unrelated NoC controls.
        """
        body = json.dumps(self.to_dict(), sort_keys=True,
                          separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(
            b"veritx/topology-intent/v1\0" + body).hexdigest()


# ── the typed variants ──────────────────────────────────────────────────────

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
class GecExpressIntent(TopologyIntent):
    """GEC point-to-point express.

    `express_channel_count` express channels leave each router, and each
    reaches `destinations_per_express_channel` destinations. A value of 1 is
    the point-to-point (non-tapped) case; values > 1 are the multi-drop
    (MECS) case, which is NOT representable with ordinary directed channels
    and is refused here rather than silently flattened.
    """
    grid_side_length: int
    concentration: int
    express_channel_count: int
    destinations_per_express_channel: int = 1
    kind: ClassVar[str] = "gec_express"

    def __post_init__(self):
        _as_int("grid_side_length", self.grid_side_length, minimum=2)
        _as_int("concentration", self.concentration, minimum=1)
        _as_int("express_channel_count", self.express_channel_count, minimum=1)
        _as_int("destinations_per_express_channel",
                self.destinations_per_express_channel, minimum=1)
        if self.destinations_per_express_channel != 1:
            raise TopologyIntentError(
                "GEC express with destinations_per_express_channel > 1 is the "
                "MULTI-DROP (MECS) case: one shared, tapped wire. It is not "
                "representable as independent point-to-point directed "
                "channels, so this intent refuses it rather than silently "
                "flattening a shared resource into N unrelated links. See "
                "docs/product/capability-archaeology.yaml (GEC-MECS).")

    def parameters(self):
        return {"grid_side_length": self.grid_side_length,
                "concentration": self.concentration,
                "express_channel_count": self.express_channel_count,
                "destinations_per_express_channel":
                    self.destinations_per_express_channel}


@dataclass(frozen=True)
class ExplicitTopologyIntent(TopologyIntent):
    """Marker: the physical graph comes from an explicit `TopologyIR`.

    Carries no shape parameters on purpose — for an explicit graph the graph
    IS the input, and duplicating its shape here would create a second
    authority that could disagree with it.
    """
    kind: ClassVar[str] = "explicit"

    def parameters(self):
        return {}


_KIND_TO_CLASS: dict[str, type[TopologyIntent]] = {
    "mesh": MeshIntent,
    "concentrated_mesh": ConcentratedMeshIntent,
    "torus": TorusIntent,
    "flatfly": FlatFlyIntent,
    "gec_express": GecExpressIntent,
    "explicit": ExplicitTopologyIntent,
}

_FIELDS: dict[str, frozenset[str]] = {
    "mesh": frozenset({"kind", "side_length", "concentration"}),
    "concentrated_mesh": frozenset({"kind", "side_length", "concentration"}),
    "torus": frozenset({"kind", "side_length", "concentration"}),
    "flatfly": frozenset({"kind", "radix_per_dimension", "dimension_count",
                          "concentration"}),
    "gec_express": frozenset({"kind", "grid_side_length", "concentration",
                              "express_channel_count",
                              "destinations_per_express_channel"}),
    "explicit": frozenset({"kind"}),
}


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
    return cls(**kwargs)


# ── the v2 representation / compatibility layer ─────────────────────────────

#: The v2-style spelling (`NocConfig.topology_family`) -> typed intent.
#: This is the COMPATIBILITY layer: v2 documents keep their meaning, and the
#: derived intent is the in-memory authority. It is NOT a second authority —
#: the two can never disagree because one is derived from the other.
def topology_intent_from_noc_config(
        family: Any, *, radix: int | None, concentration: int | None,
) -> TopologyIntent:
    """Derive a typed intent from the v2-style family + shape spelling."""
    value = getattr(family, "value", family)
    conc = concentration or 1
    if value in (None, "mesh"):
        return MeshIntent(side_length=radix or 1, concentration=conc)
    if value == "concentrated_mesh":
        return ConcentratedMeshIntent(side_length=radix or 1,
                                      concentration=max(2, conc))
    if value == "torus":
        return TorusIntent(side_length=radix or 1, concentration=conc)
    if value == "flatfly":
        return FlatFlyIntent(radix_per_dimension=radix or 4,
                             dimension_count=2, concentration=conc)
    if value == "gec":
        return GecExpressIntent(grid_side_length=radix or 8,
                                concentration=conc,
                                express_channel_count=1)
    if value == "custom":
        return ExplicitTopologyIntent()
    raise TopologyIntentError(
        f"topology family {value!r} has no typed intent: it is RECOGNIZED "
        "and AUTHORABLE but no intent variant exists for it yet — no silent "
        "fallback to another family's parameters")


def migrate_topology_intent(family: Any, *, radix: int | None,
                            concentration: int | None
                            ) -> tuple[TopologyIntent, dict[str, Any]]:
    """v2-style spelling -> (typed intent, NON-SEMANTIC provenance).

    The provenance records that a migration happened and what it read. It is
    linkage only: it must never enter a design identity, or a migrated
    document would differ from the identical hand-written one.
    """
    intent = topology_intent_from_noc_config(
        family, radix=radix, concentration=concentration)
    provenance = {
        "migrated_from": "noc_config.topology_family",
        "read": {"topology_family": getattr(family, "value", family),
                 "radix": radix, "concentration": concentration},
        "intent_kind": intent.kind,
        "intent_id": intent.intent_id(),
    }
    return intent, provenance


__all__ = [
    "TopologyIntent", "TopologyIntentError",
    "MeshIntent", "ConcentratedMeshIntent", "TorusIntent", "FlatFlyIntent",
    "GecExpressIntent", "ExplicitTopologyIntent",
    "topology_intent_from_dict", "topology_intent_from_noc_config",
    "migrate_topology_intent",
]
