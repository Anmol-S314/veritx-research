"""veritx_dse.core.experiment — Slice A: standalone BookSim end-to-end
(control-plane redesign PR 3).

The deep module of the new control plane: callers hand over a raw
experiment spec dict (the JSON a user or agent writes) and get back a
finished, immutable run directory. Everything between — strict parsing,
registered-ID resolution, trace validation, planning, process launch,
result parsing, state transitions, provenance — is implementation behind
one function (ADR 0001/0002/0005/0006).

    run_experiment(spec_dict) -> Run

Deliberately concrete: no Runner/Backend classes, no ASTRA generalization
yet (redesign §6 Slice A). The serving slices (B/C) will get their own
entry points; shared mechanics get extracted only after B and C expose
what actually repeats (§7 deletion test).
"""
from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import replace
from pathlib import Path
from typing import Any

from ..core.paths import DSE_DIR, REPO
from ..core.runs import Run, RunError
from ..core.spec import SpecError, parse, plan as plan_spec, resolve
from ..core.errors import BookSimError, TraceError
from ..simulation.booksim import detect_trace_stats, run_topology_eval
from ..model.presets import lookup_topo, topo_size


def _resolve_trace(ref: str) -> Path:
    """Trace reference -> absolute path. Relative refs resolve against the
    dse/ archive (the canonical trace home); absolute paths pass through."""
    p = Path(ref)
    return p if p.is_absolute() else DSE_DIR / p


def _trace_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run_experiment(
    spec_dict: dict[str, Any],
    *,
    repo: Path = REPO,
    ctx: Any = None,
    runner: Any | None = None,
) -> Run:
    """Execute one resolved experiment end-to-end (Slice A: BookSim).

    spec_dict: raw experiment spec (see core.spec.ExperimentSpec). Unknown
        fields and type coercion are rejected before anything is created.
    runner: optional booksim runner injection (the seam run_booksim already
        documents); real executions leave it None.

    Returns the finished Run (state SUCCEEDED or FAILED; a spec/trace
    rejection leaves CANCELLED with the reason recorded — evidence, not
    silence).

    Raises nothing on scientific failure (that is a *result*); raises
    RunError only for control-plane bugs (illegal state, immutable write).
    """
    from ..core.logging import Ctx
    ctx = ctx or Ctx()

    # ── validate (strict boundary; nothing on disk yet) ────────────────
    spec = parse(spec_dict)  # SpecError propagates: caller wrote bad intent
    resolved = resolve(spec)
    if spec.simulation.mode != "latency":
        raise SpecError("simulation.mode must be latency for standalone BookSim")
    if spec.simulation.network_simulator != "booksim":
        raise SpecError("simulation.network_simulator must be booksim for Slice A")
    if spec.system.tp_size != 1:
        raise SpecError("system.tp_size is not modeled by standalone BookSim; use 1")
    if spec.system.instances_per_node != 1:
        raise SpecError("system.instances_per_node is not modeled by standalone BookSim; use 1")
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", spec.network.routing):
        raise SpecError("network.routing must be a BookSim routing identifier")
    topo = lookup_topo(spec.network.topology)
    if topo is None:
        # Registered-ID check is the trusted-config join point (ADR 0005):
        # specs cannot carry paths, so an unregistered ID is unrunnable.
        raise SpecError(
            f"unknown topology id '{spec.network.topology}' — not in the "
            "registered presets; specs reference simulators/topologies by ID"
        )
    nodes, _ = topo_size(topo)
    if spec.system.nodes != nodes:
        raise SpecError(
            f"system.nodes {spec.system.nodes} does not match topology "
            f"'{spec.network.topology}' ({nodes} nodes)"
        )
    topo = replace(topo, routing=spec.network.routing)
    trace_path = _resolve_trace(spec.workload.trace)

    # ── run directory (immutable from here) ────────────────────────────
    run = Run.create(repo=repo, resolved_spec=resolved, argv=list(sys.argv))

    def _cancel(reason: str) -> Run:
        # Rejection evidence contract lives on Run (Phase 7 extraction;
        # identical closure existed in both slices).
        run.cancel(reason)
        return run

    try:
        stats = detect_trace_stats(str(trace_path))
    except TraceError as e:
        return _cancel(f"trace invalid: {e}")
    if stats.num_packets == 0:
        return _cancel(f"trace has no parseable packets: {trace_path}")
    if stats.max_node >= nodes:
        return _cancel(f"trace node {stats.max_node} is outside topology's {nodes} nodes")

    run.transition("VALIDATED", note=f"trace: {stats.num_packets} pkts, "
                                     f"max_node {stats.max_node}")

    # ── plan (persist via Run; one plan-file contract, Phase 7) ────────
    p = plan_spec(resolved)
    run.record_plan(p)

    # ── execute (one task per seed; real process, real parse) ──────────
    trace_hash = _trace_sha256(trace_path)
    failures: list[str] = []
    try:
        for task in p["tasks"]:
            try:
                r = run_topology_eval(
                    ctx, topo, str(trace_path),
                    repo_root=repo, seed=task["seed"],
                    timeout=task["timeout_s"], sim_type=spec.simulation.mode,
                    runner=runner,
                )
                run.add_result(task["task_id"],
                               {"trace_sha256": trace_hash, **r})
            except BookSimError as e:  # includes TimeoutError subclass
                failures.append(f"{task['task_id']}: {e}")
                run.add_result(task["task_id"],
                               {"error": str(e), "trace_sha256": trace_hash})
    except KeyboardInterrupt:
        # UI cancellation is not process cancellation — but here the
        # owning loop IS the process owner: mark INTERRUPTED (evidence)
        # and re-raise so the shell sees a real interrupt.
        run.transition("INTERRUPTED", note="KeyboardInterrupt during execution")
        raise

    if failures:
        run.finalize("FAILED", note="; ".join(failures)[:500])
    else:
        run.finalize("SUCCEEDED")
    return run
