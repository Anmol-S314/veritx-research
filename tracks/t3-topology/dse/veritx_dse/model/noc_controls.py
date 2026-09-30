"""noc_controls — the topology-INDEPENDENT NoC controls (v4).

Rationale: docs/decisions/modules/model.md
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compile_model import OutputFormat, _as_bool, _as_int, \
    _as_str

class NocControlsError(ValueError, SemanticError):
    """The declared NoC controls cannot be represented."""

TOPOLOGY_SHAPE_FIELD_NAMES = frozenset({
    "topology_family", "radix", "concentration", "side_length",
    "dimensions", "dimension_count", "grid_side_length", "mode",
    "express_channel_groups_per_dimension",
    "destinations_per_express_channel", "switch_radix", "level_count",
    "nodes", "links", "graph",
})

@dataclass(frozen=True)
class NocControls:
    """Topology-independent NoC controls.

Rationale: docs/decisions/modules/model.md
    """
    arbitration: str | None = None
    rcu_enabled: bool | None = None
    link_width: int | None = None
    mcast_groups: int | None = None
    mcast_setup_cycles: int | None = None
    output_formats: tuple[OutputFormat, ...] = (OutputFormat.SYSTEMVERILOG,)
    obfuscation_level: int = 0

    def __post_init__(self):
        if isinstance(self.output_formats, list):
            object.__setattr__(self, "output_formats",
                               tuple(self.output_formats))
        for o in self.output_formats:
            if not isinstance(o, OutputFormat):
                raise NocControlsError(
                    "output_formats must contain OutputFormat, got "
                    f"{type(o).__name__}")
        for name in ("link_width", "mcast_groups"):
            val = getattr(self, name)
            if val is not None:
                _as_int(f"noc_controls.{name}", val, minimum=1)
        if self.mcast_setup_cycles is not None:
            _as_int("noc_controls.mcast_setup_cycles",
                    self.mcast_setup_cycles, minimum=0)
        _as_int("noc_controls.obfuscation_level", self.obfuscation_level,
                minimum=0)
        if self.arbitration is not None:
            _as_str("noc_controls.arbitration", self.arbitration,
                    allow_empty=False)
        if self.rcu_enabled is not None:
            _as_bool("noc_controls.rcu_enabled", self.rcu_enabled)

    def to_dict(self) -> dict[str, Any]:
        return {
            "arbitration": self.arbitration,
            "rcu_enabled": self.rcu_enabled,
            "link_width": self.link_width,
            "mcast_groups": self.mcast_groups,
            "mcast_setup_cycles": self.mcast_setup_cycles,
            "output_formats": [o.value for o in self.output_formats],
            "obfuscation_level": self.obfuscation_level,
        }

    def canonical_dict(self) -> dict[str, Any]:
        """Identity envelope. `output_formats` is sorted: which artifacts are
        EMITTED is not design science, so declaration order must not change
        the design. Everything else keeps its declared value."""
        d = self.to_dict()
        d["output_formats"] = sorted(d["output_formats"])
        return d

    def controls_id(self) -> str:
        body = json.dumps(self.canonical_dict(), sort_keys=True,
                          separators=(",", ":")).encode()
        return "sha256:" + hashlib.sha256(
            b"veritx/noc-controls/v1\0" + body).hexdigest()

_NOC_CONTROL_KEYS = frozenset({
    "arbitration", "rcu_enabled", "link_width", "mcast_groups",
    "mcast_setup_cycles", "output_formats", "obfuscation_level",
})

def noc_controls_from_dict(d: Any) -> NocControls:
    """Strict load: unknown keys are refused, so a typo cannot become a
    silently ignored control, and a topology-shape field is refused by name
    (that is the whole point of the split)."""
    if not isinstance(d, dict):
        raise NocControlsError("noc_controls must be an object")
    shape = sorted(set(d) & TOPOLOGY_SHAPE_FIELD_NAMES)
    if shape:
        raise NocControlsError(
            f"noc_controls may not describe topology SHAPE: {shape}. "
            "Topology shape belongs exclusively to the topology intent "
            "(see model/topology_intent.py).")
    unknown = set(d) - _NOC_CONTROL_KEYS
    if unknown:
        raise NocControlsError(
            f"unknown noc_controls fields {sorted(unknown)} "
            f"(allowed: {sorted(_NOC_CONTROL_KEYS)})")
    formats = d.get("output_formats")
    if formats is None:
        formats = [OutputFormat.SYSTEMVERILOG.value]
    if not isinstance(formats, list):
        raise NocControlsError("output_formats must be a list")
    try:
        parsed = tuple(OutputFormat(v) for v in formats)
    except ValueError as e:
        raise NocControlsError(f"invalid output_formats: {e}") from e
    return NocControls(
        arbitration=d.get("arbitration"),
        rcu_enabled=d.get("rcu_enabled"),
        link_width=d.get("link_width"),
        mcast_groups=d.get("mcast_groups"),
        mcast_setup_cycles=d.get("mcast_setup_cycles"),
        output_formats=parsed,
        obfuscation_level=d.get("obfuscation_level", 0),
    )

def noc_controls_from_noc_config(noc: Any) -> NocControls:
    """Legacy `NocConfig` -> `NocControls` (the compatibility seam).

    Reads ONLY the topology-independent fields. The topology-shape fields
    (`topology_family`, `radix`, `concentration`) are deliberately NOT read
    here — they belong to the topology migration, and reading them twice
    would create a second authority for shape.
    """
    return NocControls(
        arbitration=getattr(noc, "arbitration", None),
        rcu_enabled=getattr(noc, "rcu_enabled", None),
        link_width=getattr(noc, "link_width", None),
        mcast_groups=getattr(noc, "mcast_groups", None),
        mcast_setup_cycles=getattr(noc, "mcast_setup_cycles", None),
        output_formats=tuple(
            getattr(noc, "output_formats", None) or (OutputFormat.SYSTEMVERILOG,)),
        obfuscation_level=getattr(noc, "obfuscation_level", 0),
    )

__all__ = [
    "NocControls", "NocControlsError", "TOPOLOGY_SHAPE_FIELD_NAMES",
    "noc_controls_from_dict", "noc_controls_from_noc_config",
]
