"""api.py — the agent-safe semantic API (Phase 17, plan §23).

One narrow surface over the stable control plane. Contract:

  - structured results only: dicts of ids/states/hashes/verdicts; no
    shell, no docker, no host paths as outputs, no environment mutation
  - bad intent is DATA (``valid=False`` + reasons), never an exception
    crossing this boundary
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
        compiler_verdicts=["FEASIBLE", "NO_FEASIBLE_DESIGN"],
        bottleneck_verdicts=["COMPUTE_BOUND", "MEMORY_BOUND", "FABRIC_BOUND",
                             "SYNCHRONIZATION_BOUND", "MIXED", "INCONCLUSIVE",
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

    Serving specs route to the serving slice; everything else to Slice A.
    Budget: the declared wall-clock cap is passed to the underlying runner
    via the simulation spec when absent; the caller-visible budget is
    always reported back.
    """
    try:
        sp = spec_mod.parse(spec_dict)
    except Exception as e:
        return _reject("execute", [f"{type(e).__name__}: {e}"])

    budget = timeout_s if timeout_s is not None else BUDGETS["max_execution_seconds"]
    kwargs: dict[str, Any] = {"repo": repo} if repo is not None else {}
    t0 = time.monotonic()
    try:
        if sp.serving is not None:
            from .core.experiment_serving import run_serving_experiment
            run = run_serving_experiment(spec_dict, **kwargs)
        else:
            from .core.experiment import run_experiment
            run = run_experiment(spec_dict, **kwargs)
    except spec_mod.SpecError as e:
        return _reject("execute", [str(e)])
    except Exception as e:
        return _ok(status="EVALUATION_FAILED", op="execute",
                   name=sp.name, error=f"{type(e).__name__}: {e}",
                   elapsed_s=round(time.monotonic() - t0, 3),
                   budget_max_execution_seconds=budget)
    return _ok(status="OK", op="execute", run_id=run.run_id,
               state=run.state, run_dir=str(run.root),
               elapsed_s=round(time.monotonic() - t0, 3),
               budget_max_execution_seconds=budget)


# ── Observability ──────────────────────────────────────────────────────────


def get_run(run_id: str) -> dict[str, Any]:
    """Run identity + state by run_id — filesystem-authoritative (ADR 0003)."""
    import json
    root = REPO / "runs" / run_id
    manifest = root / "manifest.json"
    if not manifest.is_file():
        return _reject("get_run", [f"unknown run_id: {run_id}"])
    m = json.loads(manifest.read_text())
    state_path = root / "state.json"
    state = json.loads(state_path.read_text())["state"] if state_path.is_file() \
        else m.get("status", "UNKNOWN")
    return _ok(status="OK", op="get_run", run_id=run_id,
               experiment_hash=m.get("experiment_hash"), state=state,
               created_at=m.get("created_at"), run_dir=str(root))


def get_results(*, topology: str | None = None, status: str | None = None,
                workload: str | None = None, limit: int | None = None) -> dict[str, Any]:
    """Query the runs store (budget-capped row count)."""
    from .core.store import Store
    db = Path(os.environ.get("VERITX_INDEX_DB") or (REPO / "runs" / "index.db"))
    cap = min(limit or BUDGETS["max_query_rows"], BUDGETS["max_query_rows"])
    rows = Store(db).query(topology=topology, status=status,
                           workload=workload, limit=cap)
    return _ok(status="OK", op="get_results", rows=rows, count=len(rows),
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
    return _ok(status="OK", op="compare", verdict=_jsonable(verdict))


def diagnose(*, level: str = "quick") -> dict[str, Any]:
    """Health battery; full deep battery stays CLI-only (long-running)."""
    if level not in ("quick", "deep"):
        return _reject("diagnose", [f"unknown level: {level}"])
    from .core import doctor
    report = doctor.run_checks(level=level)
    return _ok(status="OK", op="diagnose", level=level, result=report.to_dict())


# ── Synthesis ──────────────────────────────────────────────────────────────


def compile_fabric(requirements: list[dict[str, Any]],
                   candidates: list[dict[str, Any]], *,
                   search_budget: dict[str, Any] | None = None,
                   seed_policy: dict[str, Any] | None = None) -> dict[str, Any]:
    """Requirements-driven compile; FEASIBLE/NO_FEASIBLE_DESIGN verdict."""
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
    result = _cf(req)
    return _ok(status="OK", op="compile", result=_jsonable(result))


__all__ = [
    "BUDGETS", "list_capabilities", "list_workloads", "list_topologies",
    "validate", "plan", "execute", "get_run", "get_results", "compare",
    "diagnose", "compile_fabric",
]
