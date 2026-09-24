"""Experiment specification: the declarative contract of the corpus.

An experiment states a fabric, a workload, the checks to run, and — for
the hand-calculable layers — the expected answer computed outside VERITX.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1

KNOWN_CHECKS = frozenset({
    "conservation", "hand_route", "hand_counts",
    "standalone_parity", "window_invariance", "monotonicity",
})

#: sweep parameter -> (field, quantity that must be monotone, direction)
#: direction is stated for ASCENDING parameter values.
SWEEP_RULES = {
    "link_width": ("fabric", "completion_cycles", "non_increasing"),
    "payload_bytes": ("workload", "flits", "non_decreasing"),
}

_P2P = "p2p"
_COLLECTIVE = "collective"


class SpecError(ValueError):
    """The experiment specification is malformed — fail closed."""


@dataclass(frozen=True)
class FabricSpec:
    compute_tiles: int
    tp: int
    link_width: int
    concentration: int = 1
    num_vcs: int = 1
    topology_family: str = "mesh"

    @property
    def rank_count(self) -> int:
        return self.compute_tiles


@dataclass(frozen=True)
class WorkloadSpec:
    kind: str
    collective_kind: str | None = None
    payload_bytes: int = 1024
    src_rank: int | None = None
    dst_rank: int | None = None

    def __post_init__(self) -> None:
        if self.kind == _P2P:
            if self.src_rank is None or self.dst_rank is None:
                raise SpecError("p2p workload requires src_rank and dst_rank")
        elif self.kind == _COLLECTIVE:
            if not self.collective_kind:
                raise SpecError("collective workload requires collective_kind")
        else:
            raise SpecError(f"unknown workload kind {self.kind!r}")


@dataclass(frozen=True)
class Expected:
    packets: int | None = None
    flits: int | None = None
    route_hops: int | None = None
    route_hops_avg: float | None = None
    notes: str = ""


@dataclass(frozen=True)
class SweepSpec:
    param: str
    values: tuple[int, ...]
    field: str
    quantity: str
    direction: str

    def apply(self, spec: "ExperimentSpec", value: int) -> "ExperimentSpec":
        """Return a copy of ``spec`` with the swept field set to ``value``."""
        import dataclasses
        if self.field == "fabric":
            fabric = dataclasses.replace(spec.fabric, **{self.param: value})
            return dataclasses.replace(spec, fabric=fabric, sweep=None)
        workload = dataclasses.replace(spec.workload, **{self.param: value})
        return dataclasses.replace(spec, workload=workload, sweep=None)


def _parse_sweep(doc: dict[str, Any]) -> SweepSpec | None:
    raw = doc.get("sweep")
    if raw is None:
        return None
    param = str(raw.get("param", ""))
    if param not in SWEEP_RULES:
        raise SpecError(
            f"unknown sweep param {param!r}; known: {sorted(SWEEP_RULES)}")
    values = tuple(int(v) for v in raw.get("values", ()))
    if len(values) < 2:
        raise SpecError("a sweep needs at least two values")
    if list(values) != sorted(set(values)):
        raise SpecError(
            f"sweep values must be strictly ascending and unique, got "
            f"{list(values)}")
    field, quantity, direction = SWEEP_RULES[param]
    return SweepSpec(param=param, values=values, field=field,
                     quantity=quantity, direction=direction)


@dataclass(frozen=True)
class ExperimentSpec:
    id: str
    title: str
    fabric: FabricSpec
    workload: WorkloadSpec
    expected: Expected
    checks: tuple[str, ...]
    seed: int = 0
    timeout_s: int = 600
    path: Path | None = None
    sweep: SweepSpec | None = None

    @classmethod
    def from_dict(cls, doc: Any, *, path: Path | None = None
                  ) -> "ExperimentSpec":
        if not isinstance(doc, dict):
            raise SpecError("experiment must be a JSON object")
        if doc.get("schema_version") != SCHEMA_VERSION:
            raise SpecError(
                f"unsupported experiment schema_version "
                f"{doc.get('schema_version')!r}")
        for key in ("id", "title", "fabric", "workload", "checks"):
            if key not in doc:
                raise SpecError(f"experiment is missing {key!r}")
        if not str(doc["id"]).startswith("V"):
            raise SpecError(f"experiment id must look like V01, got {doc['id']!r}")

        fab = doc["fabric"]
        for key in ("compute_tiles", "tp", "link_width"):
            if key not in fab:
                raise SpecError(f"fabric is missing {key!r}")
        fabric = FabricSpec(
            compute_tiles=int(fab["compute_tiles"]), tp=int(fab["tp"]),
            link_width=int(fab["link_width"]),
            concentration=int(fab.get("concentration", 1)),
            num_vcs=int(fab.get("num_vcs", 1)),
            topology_family=str(fab.get("topology_family", "mesh")))
        if fabric.topology_family != "mesh":
            raise SpecError("the corpus currently covers mesh fabrics only")

        wl = doc["workload"]
        workload = WorkloadSpec(
            kind=str(wl["kind"]),
            collective_kind=(str(wl["collective_kind"])
                             if wl.get("collective_kind") else None),
            payload_bytes=int(wl.get("payload_bytes", 1024)),
            src_rank=(int(wl["src_rank"]) if wl.get("src_rank") is not None
                      else None),
            dst_rank=(int(wl["dst_rank"]) if wl.get("dst_rank") is not None
                      else None))

        exp_doc = doc.get("expected", {})
        expected = Expected(
            packets=(int(exp_doc["packets"])
                     if exp_doc.get("packets") is not None else None),
            flits=(int(exp_doc["flits"])
                   if exp_doc.get("flits") is not None else None),
            route_hops=(int(exp_doc["route_hops"])
                        if exp_doc.get("route_hops") is not None else None),
            route_hops_avg=(float(exp_doc["route_hops_avg"])
                            if exp_doc.get("route_hops_avg") is not None
                            else None),
            notes=str(exp_doc.get("notes", "")))

        checks = tuple(str(c) for c in doc["checks"])
        unknown = set(checks) - KNOWN_CHECKS
        if unknown:
            raise SpecError(f"unknown checks {sorted(unknown)}")
        if not checks:
            raise SpecError("an experiment must declare at least one check")
        return cls(id=str(doc["id"]), title=str(doc["title"]), fabric=fabric,
                   workload=workload, expected=expected, checks=checks,
                   seed=int(doc.get("seed", 0)),
                   timeout_s=int(doc.get("timeout_s", 600)), path=path,
                   sweep=_parse_sweep(doc))

    @classmethod
    def load(cls, path: str | Path) -> "ExperimentSpec":
        p = Path(path)
        return cls.from_dict(json.loads(p.read_text()), path=p)
