"""api.py — the agent-safe semantic API (Phase 17, plan §23).

One narrow surface over the stable control plane. Contract:

  - structured results only: dicts of ids/states/hashes/verdicts; no
    shell, no docker, no host paths as outputs, no environment mutation
  - bad intent is DATA (``valid=False`` + reasons), never an exception
    crossing this boundary
  - no Python callables cross this boundary — structurally, by
    signature: compile takes registered evaluator IDs, and the DI seam
    (``_compile_fabric_with_evaluator``) is private, for host embeddings
    and tests only
  - resource budgets are DECLARED (visible via ``list_capabilities``)
    and enforced where cheap (execution limits)
  - MCP/CLI/TUI are thin adapters to these functions, not alternatives

Semantic operations (plan §23): list_capabilities, list_workloads,
list_topologies, validate, plan, compile, execute, get_run, get_results,
compare, diagnose.
"""

from __future__ import annotations

import dataclasses
import os
import time
from pathlib import Path
from typing import Any

from .core import spec as spec_mod
from .core.paths import REPO, TRACK_RUNS_DIR

# ── Declared resource budgets (the only policy this module owns) ──────────

BUDGETS: dict[str, Any] = {
    "max_execution_seconds": 1800,
    "max_candidates_per_compile": 256,
    "max_query_rows": 500,
    "single_sample_no_confidence_interval": True,
}

SCHEMA_VERSION = 1


def _ok(**kw: Any) -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, **kw}


def _reject(op: str, reasons: list[str]) -> dict[str, Any]:
    return _ok(status="INVALID", op=op, valid=False, reasons=reasons)


def _jsonable(x: Any) -> Any:
    """Best-effort structured conversion for dataclass results."""
    if hasattr(x, "to_dict"):
        return x.to_dict()
    if dataclasses.is_dataclass(x) and not isinstance(x, type):
        return dataclasses.asdict(x)
    return x


def _strip_host_paths(x: Any) -> Any:
    """Remove filesystem locations from an output doc — this surface
    reports identity (ids/hashes/states), never host paths."""
    if isinstance(x, dict):
        return {k: _strip_host_paths(v) for k, v in x.items()
                if k not in ("run_dir", "bundle", "manifest", "root")}
    if isinstance(x, list):
        return [_strip_host_paths(v) for v in x]
    return x


# ── Discovery (no execution) ──────────────────────────────────────────────


def list_capabilities() -> dict[str, Any]:
    """Machine-readable vocabulary: backends, fidelities, verdicts, budgets."""
    return _ok(
        status="OK",
        network_backends=["booksim", "analytical"],
        network_fidelities=["NETWORK_CYCLE_SIMULATION", "ANALYTICAL_ESTIMATE"],
        memory_backends={"analytical": "MEMORY_ESTIMATE", "ramulator": "MEMORY_CYCLE_SIMULATION"},
        serving_frontends=["congestion_aware", "congestion_unaware"],
        comparison_kinds=["DESIGN_COMPARISON", "CROSS_FIDELITY_CALIBRATION"],
        candidate_statuses=["COMPARABLE", "FAILED_EXECUTION", "INCOMPATIBLE",
                            "MISSING_METRIC", "SEMANTIC_LOSS", "INVALID_FIDELITY",
                            "INSUFFICIENT_PROVENANCE"],
        compiler_verdicts=["FEASIBLE", "NO_FEASIBLE_DESIGN",
                           "EVALUATION_FAILED", "SEARCH_INCOMPLETE",
                           "CONSTRAINT_UNMEASURABLE"],
        # SYNC_BOUND is NOT advertised: the v1 canonical op set has no
        # barrier semantics, so the timeline can never produce it
        # (workload/timeline.py — honest vocabulary only).
        bottleneck_verdicts=["COMPUTE_BOUND", "MEMORY_BOUND", "FABRIC_BOUND",
                             "MIXED", "INCONCLUSIVE",
                             "NETWORK_NOT_THE_BOTTLENECK"],
        budgets=BUDGETS,
    )


def list_workloads() -> dict[str, Any]:
    """Named serving workloads available for spec intent."""
    wl_dir = TRACK_RUNS_DIR.parent / "workloads"
    names = sorted(p.stem for p in wl_dir.glob("*.json")) if wl_dir.is_dir() else []
    return _ok(status="OK", workloads=names, count=len(names))


def list_topologies() -> dict[str, Any]:
    """Named topology presets with resolved identity (immutable, Phase 13+)."""
    from .model.presets import _TOPO_BY_NAME

    topos = {}
    for name, t in sorted(_TOPO_BY_NAME.items()):
        topos[name] = {"backend": t.backend, "routing": t.routing, "params": dict(t.params)}
    return _ok(status="OK", topologies=topos, count=len(topos))


# ── Intent lifecycle: validate → plan → execute ───────────────────────────


def validate(spec_dict: dict[str, Any]) -> dict[str, Any]:
    """Validate experiment intent. Errors are data, never raised."""
    try:
        sp = spec_mod.parse(spec_dict)
    except spec_mod.SpecError as e:
        return _reject("validate", [str(e)])
    except Exception as e:  # pydantic ValidationError etc. — still data
        return _reject("validate", [f"{type(e).__name__}: {e}"])
    return _ok(status="OK", op="validate", valid=True, name=sp.name)


def plan(spec_dict: dict[str, Any]) -> dict[str, Any]:
    """Resolve intent to a deterministic execution plan WITHOUT running."""
    try:
        sp = spec_mod.parse(spec_dict)
        resolved = spec_mod.resolve(sp)
    except spec_mod.SpecError as e:
        return _reject("plan", [str(e)])
    except Exception as e:
        return _reject("plan", [f"{type(e).__name__}: {e}"])
    return _ok(status="OK", op="plan", name=sp.name, resolved=resolved)


def execute(spec_dict: dict[str, Any], *, repo: Path | None = None,
            timeout_s: int | None = None) -> dict[str, Any]:
    """Run one experiment; returns run identity + terminal state.

    The API budget is a MAXIMUM, not decorative: the requested timeout
    (explicit timeout_s, else the spec's simulation.timeout_s) is checked
    against BUDGETS["max_execution_seconds"] and OVER-BUDGET intent is
    REJECTED — never silently clamped (clamping would alter declared
    intent). The accepted value is written into the spec before parse so
    the runner enforces the same number.
    """
    doc = dict(spec_dict)
    try:
        sim = dict(doc.get("simulation") or {})
        requested = int(timeout_s) if timeout_s is not None \
            else int(sim.get("timeout_s", 60))
        if requested > BUDGETS["max_execution_seconds"]:
            return _reject("execute", [
                f"timeout {requested}s exceeds API maximum "
                f"{BUDGETS['max_execution_seconds']}s"])
        sim["timeout_s"] = requested
        doc["simulation"] = sim
        sp = spec_mod.parse(doc)
        budget = int(sp.simulation.timeout_s)
    except Exception as e:
        return _reject("execute", [f"{type(e).__name__}: {e}"])

    kwargs: dict[str, Any] = {"repo": repo} if repo is not None else {}
    t0 = time.monotonic()
    try:
        if sp.serving is not None:
            from .core.experiment_serving import run_serving_experiment
            run = run_serving_experiment(doc, **kwargs)
        else:
            from .core.experiment import run_experiment
            run = run_experiment(doc, **kwargs)
    except spec_mod.SpecError as e:
        return _reject("execute", [str(e)])
    except Exception as e:
        return _ok(status="EVALUATION_FAILED", op="execute",
                   name=sp.name, error=f"{type(e).__name__}: {e}",
                   elapsed_s=round(time.monotonic() - t0, 3),
                   budget_max_execution_seconds=budget)
    return _ok(status="OK", op="execute", run_id=run.run_id,
               state=run.state,
               elapsed_s=round(time.monotonic() - t0, 3),
               budget_max_execution_seconds=budget)


# ── Observability ──────────────────────────────────────────────────────────


def get_run(run_id: str) -> dict[str, Any]:
    """Run identity + state by run_id — filesystem-authoritative (ADR 0003).

    Immutable runs live under runs/veritx-runs/<run_id> (where Run.create
    allocates them). The run_dir is NOT returned: it is a host path, and
    this surface reports identity, never filesystem location.
    """
    import json
    root = REPO / "runs" / "veritx-runs" / run_id
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return _reject("get_run", [f"unknown run_id: {run_id}"])
    m = json.loads(manifest.read_text())
    state_path = root / "state.json"
    state = json.loads(state_path.read_text())["state"] if state_path.is_file() \
        else m.get("status", "UNKNOWN")
    return _ok(status="OK", op="get_run", run_id=run_id,
               experiment_hash=m.get("experiment_hash"), state=state,
               created_at=m.get("created_at"))


def get_results(*, topology: str | None = None, status: str | None = None,
                workload: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Query the runs store (budget-capped row count)."""
    from .core.store import Store
    db = Path(os.environ.get("VERITX_INDEX_DB") or (REPO / "runs" / "index.db"))
    cap = min(limit or BUDGETS["max_query_rows"], BUDGETS["max_query_rows"])
    rows = Store(db).query(topology=topology, status=status,
                           workload=workload, limit=cap)
    return _ok(status="OK", op="get_results", rows=_strip_host_paths(rows),
               count=len(rows),
               budget_max_query_rows=BUDGETS["max_query_rows"])


def compare(candidates: list[dict[str, Any]], *, metrics: list[str],
            experimental_variables: list[str] | None = None,
            comparison_kind: str = "DESIGN_COMPARISON") -> dict[str, Any]:
    """ComparisonSpec-gated comparison; verdict is machine-readable."""
    from .core.comparison import evaluate_comparability, resolve_intent
    intent = resolve_intent({
        "metrics": metrics,
        "experimental_variables": experimental_variables or [],
        "comparison_kind": comparison_kind,
    })
    verdict = evaluate_comparability(candidates, intent)
    return _ok(status="OK", op="compare", verdict=_strip_host_paths(_jsonable(verdict)))


def diagnose(*, level: str = "quick") -> dict[str, Any]:
    """Health battery; full deep battery stays CLI-only (long-running)."""
    if level not in ("quick", "deep"):
        return _reject("diagnose", [f"unknown level: {level}"])
    from .core import doctor
    report = doctor.run_checks(level=level)
    return _ok(status="OK", op="diagnose", level=level, result=report.to_dict())


# ── Synthesis ──────────────────────────────────────────────────────────────


REGISTERED_EVALUATORS = ("booksim", "analytical")


def compile_fabric(requirements: list[dict[str, Any]],
                   candidates: list[dict[str, Any]], *,
                   evaluator_id: str | None = None,
                   trace_path: str | None = None,
                   seed: int = 0,
                   timeout: int = 600,
                   search_budget: dict[str, Any] | None = None,
                   seed_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Requirements-driven compile; FEASIBLE/NO_FEASIBLE_DESIGN verdict.

    External-API contract, structurally enforced: no Python callables
    cross this boundary — the signature has no ``evaluate`` parameter.
    The evaluator is selected by REGISTERED ID — ``booksim`` resolves the
    one real evaluation path (synthesis.bridge._spec_evaluator over
    evaluator.evaluate_spec, requiring trace_path), ``analytical`` is
    registered as UNSUPPORTED (declared, not invented).

    Budgets: ``timeout`` is a MAXIMUM (``1 <= timeout <=``
    ``BUDGETS["max_execution_seconds"]``) — over-budget intent is
    REJECTED, never clamped; candidate count is capped by
    ``max_candidates_per_compile``.
    """
    if timeout < 1 or timeout > BUDGETS["max_execution_seconds"]:
        return _reject("compile", [
            f"timeout {timeout}s outside API budget "
            f"[1, {BUDGETS['max_execution_seconds']}]s — over-budget "
            "intent is rejected, never clamped"])
    if evaluator_id is None:
        return _reject("compile", [
            "compile requires evaluator_id (registered: "
            f"{', '.join(REGISTERED_EVALUATORS)}) — an agent-safe API "
            "never takes Python callables"])
    if evaluator_id not in REGISTERED_EVALUATORS:
        return _ok(status="UNSUPPORTED", op="compile",
                   valid=False,
                   reasons=[f"evaluator_id {evaluator_id!r} is not "
                            f"registered — supported: "
                            f"{', '.join(REGISTERED_EVALUATORS)}"])
    if evaluator_id == "analytical":
        return _ok(status="UNSUPPORTED", op="compile",
                   valid=False,
                   reasons=["evaluator_id 'analytical' has no compiler "
                            "resolution yet — declared UNSUPPORTED, "
                            "never invented"])
    if not trace_path:
        return _reject("compile", [
            "evaluator_id 'booksim' requires trace_path (the real "
            "evaluation path measures the candidate against a trace)"])
    from .synthesis.bridge import _spec_evaluator
    evaluate = _spec_evaluator(trace_path=str(Path(trace_path).resolve()),
                               seed=seed, timeout=timeout)
    return _compile_fabric_with_evaluator(
        requirements, candidates, evaluate=evaluate,
        search_budget=search_budget, seed_policy=seed_policy)


def _compile_fabric_with_evaluator(
        requirements: list[dict[str, Any]],
        candidates: list[dict[str, Any]], *,
        evaluate: Any,
        search_budget: dict[str, Any] | None = None,
        seed_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """INTERNAL dependency-injection seam for compile (host embeddings
    and tests). NOT part of the public agent-safe API: it takes a Python
    callable by design. The public surface is :func:`compile_fabric`.
    """
    if len(candidates) > BUDGETS["max_candidates_per_compile"]:
        return _reject("compile", [
            f"candidate count {len(candidates)} exceeds budget "
            f"{BUDGETS['max_candidates_per_compile']}"])
    from .synthesis.compiler import CompilerRequest, compile_fabric as _cf
    req = CompilerRequest(
        requirements=requirements,
        candidates=candidates,
        search_budget=search_budget or {},
        seed_policy=seed_policy or {},
    )
    result = _cf(req, evaluate)
    return _ok(status="OK", op="compile",
               result=_strip_host_paths(_jsonable(result)))


# ── Export (plan §22) ───────────────────────────────────────────────────────


def export_run(run_id: str, *, out_dir: str | Path | None = None) -> dict[str, Any]:
    """Checksummed export bundle for one immutable run (CHECKSUMMED_UNSIGNED
    unless an HMAC key is declared via VERITX_EXPORT_HMAC_KEY)."""
    from .core.export import export_run as _export
    target = REPO / "runs" / "veritx-runs" / run_id
    if not target.is_dir():
        return _reject("export", [f"unknown run_id: {run_id}"])
    try:
        result = _export(target, out_dir or (REPO / "runs" / "exports"),
                         run_id=run_id)
    except Exception as e:
        return _ok(status="EVALUATION_FAILED", op="export",
                   error=f"{type(e).__name__}: {e}")
    # Identity only: bundle/manifest are host paths — report their
    # checksums, never their filesystem locations.
    return _ok(status="OK", op="export", run_id=run_id,
               manifest_sha256=result["manifest_sha256"],
               archive_sha256=result["archive_sha256"],
               signing=result["signing"], file_count=result["file_count"])


__all__ = [
    "BUDGETS", "list_capabilities", "list_workloads", "list_topologies",
    "validate", "plan", "execute", "get_run", "get_results", "compare",
    "diagnose", "compile_fabric", "export_run",
]
