from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import itertools, math, random, re

KNOWN_SIM_FIELDS = {"topology", "injection_rate", "sim_cycles", "traffic"}

_SIMPOINT_DEFAULTS = {
    "topology": None,
    "injection_rate": 0.08,
    "sim_cycles": 1_000_000,
    "traffic": "uniform",
}


@dataclass(frozen=True)
class Axis:
    name: str
    values: Tuple[Any, ...]

    def __post_init__(self):
        if not self.values:
            raise ValueError(f"axis {self.name!r} has no values")


@dataclass(frozen=True)
class DesignPoint:
    assignments: Tuple[Tuple[str, Any], ...]

    @property
    def values(self) -> Dict[str, Any]:
        return dict(self.assignments)

    def slug(self) -> str:
        return "_".join(f"{k}-{v}" for k, v in self.assignments)


@dataclass
class DesignSpace:
    axes: List[Axis]
    defaults: Dict[str, Any] = field(default_factory=dict)

    def size(self) -> int:
        return math.prod(len(a.values) for a in self.axes)

    def enumerate(self) -> List[DesignPoint]:
        value_lists = [a.values for a in self.axes]
        return [
            DesignPoint(tuple(zip([a.name for a in self.axes], combo)))
            for combo in itertools.product(*value_lists)
        ]

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DesignSpace":
        import yaml
        with open(path) as fh:
            raw = yaml.safe_load(fh)
        axes = [Axis(name=tuple(spec.values()) if isinstance(spec, dict) else tuple(spec))
                for name, spec in raw.get("axes", {}).items()
                for spec in [raw["axes"][name]]]
        return cls(
            axes=axes,
            defaults=raw.get("defaults", {}),
        )


@dataclass
class SimResult:
    point: DesignPoint
    avg_latency: Optional[float] = None
    avg_hops: Optional[float] = None
    throughput: Optional[float] = None
    energy_pj: Optional[float] = None
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.avg_latency is not None and self.error is None
