"""F-0003 intervention: is completion injection-schedule-bound?

F-0003 was recorded as a hypothesis, not a conclusion. This layer tests it
by INTERVENTION: take one canonical packet list (same packets, topology,
routing and sizes) and re-time its injection, then measure whether the
completion follows the injection horizon or departs from it as offered
load rises.

The intervention runs on the authority engine (standalone BookSim), the
same engine the canonical path uses, so it measures the engine's response
to the schedule rather than VERITX's (fixed) projection schedule. A
departure would refute the hypothesis; tracking it supports it.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from .authority import run_standalone
from .fabric import build
from .spec import ExperimentSpec

#: spacing (cycles between consecutive packet injections)
SCHEDULES = (("per_cycle", 1), ("half_rate", 2), ("quarter_rate", 4),
             ("eighth_rate", 8))


@dataclass(frozen=True)
class InterventionRow:
    schedule: str
    spacing: int
    horizon: int
    completion: int
    drain: int


def _retimed_trace(trace_text: str, spacing: int) -> str:
    lines = [ln.split() for ln in trace_text.splitlines() if ln.strip()]
    out = []
    for index, (cyc, src, cl, dst, sz) in enumerate(lines):
        out.append(f"{index * spacing} {src} {cl} {dst} {sz}")
    return "\n".join(out) + "\n"


def run_schedule_intervention(binary: Path, work_root: Path,
                              experiment: str = "V02-allreduce-4x4.json"
                              ) -> list[InterventionRow]:
    root = Path(__file__).resolve().parents[1]
    spec = ExperimentSpec.load(root / "experiments" / experiment)
    built = build(spec)
    rows: list[InterventionRow] = []
    for name, spacing in SCHEDULES:
        retimed = _retimed_trace(built.prepared.trace_text, spacing)
        prepared = dataclasses.replace(built.prepared, trace_text=retimed)
        horizon = (built.packets - 1) * spacing
        run_dir = Path(work_root) / f"intervention-{name}"
        result = run_standalone(spec_fabric=spec.fabric, prepared=prepared,
                                binary=binary, run_dir=run_dir, timeout_s=600)
        rows.append(InterventionRow(
            schedule=name, spacing=spacing, horizon=horizon,
            completion=result.completion_cycles,
            drain=result.completion_cycles - horizon))
    return rows


def intervention_verdict(rows: list[InterventionRow]) -> dict:
    """Support or refute the injection-bound hypothesis from the rows.

    Injection-bound means the completion is dominated by the injection
    horizon: completion >= horizon always, and the drain beyond the
    horizon is small relative to it. A departure (drain growing with the
    horizon) would refute it.
    """
    if len(rows) < 2:
        raise ValueError("intervention needs at least two schedules")
    problems: list[str] = []
    for r in rows:
        if r.completion < r.horizon:
            problems.append(
                f"{r.schedule}: completion {r.completion} precedes its own "
                f"injection horizon {r.horizon}")
        budget = max(50, r.horizon // 20)   # 5% of the horizon, min 50
        if r.drain > budget:
            problems.append(
                f"{r.schedule}: drain {r.drain} exceeds {budget} "
                f"({r.drain / max(r.horizon, 1):.1%} of horizon) — completion "
                "departs from the injection horizon")
    for a, b in zip(rows, rows[1:]):
        if b.completion < a.completion:
            problems.append(
                f"{a.schedule}->{b.schedule}: completion fell "
                f"{a.completion}->{b.completion} as the horizon rose")
    drains = [r.drain for r in rows]
    return {
        "supported": not problems,
        "problems": problems,
        "drains": drains,
        "drain_spread": max(drains) - min(drains),
        "rows": [dataclasses.asdict(r) for r in rows],
    }
