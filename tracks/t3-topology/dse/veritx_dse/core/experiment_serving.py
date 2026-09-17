"""veritx_dse.core.experiment_serving — Slice B: serving → real BookSim.

 PR6 vertical slice. Callers hand over a raw experiment spec dict with
 ``simulation.mode == "serving"`` and get back a finished, immutable run.

Ownership boundary (review-binding): VeriTX supervises the LLMServingSim
PROCESS (lifecycle, timeout, artifacts). LLMServingSim keeps owning the
ASTRA/BookSim interactive protocol — this slice never speaks it. PR5's
ServingBackendSession stays a test fixture; it is not used here.

The slice is real-simulation-only: replay requests are refused at the
boundary (replay stays available via `veritx serve`, gated out of
goldens by passes_serving_golden_gate). Terminal truth is request
retirement + validated artifacts + process state — never the liveness
classifier, never exit code alone.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ..core.paths import DSE_DIR, LLMSIM_DIR, REPO, serving_fixture
from ..core.recovery import atomic_write
from ..core.runs import Run, binary_identity
from ..core.spec import SpecError, parse, resolve
from ..core.errors import ServingPreflightError, ServingResultError
from ..core.serving import (
    build_serve_cmd,
    fidelity_for_mode,
    locate_serve_path,
    mode_for_backend,
    preflight_serve,
    retired_from_csv,
    serve_args,
    serving_provenance,
)
from ..core.serving_metrics import SERVING_METRIC_SCHEMA, build_serving_metrics

_COLL_COMPLETE_RE = re.compile(r"\[LEDGER\]\[COLL_COMPLETE\]")
_SUBMIT_DIMS_RE = re.compile(
    r"\[LEDGER\]\[COLL_SUBMIT\][^\n]*?involved_dims=\[([^\]]*)\]")
_TOPO_RE = re.compile(r"\[LEDGER\]\[TOPO\]\s+npus=\d+\s+dims=([0-9,]+)")
_FLIT_RE = re.compile(r"retired_flits=(\d+)")


def fabric_evidence(stderr: str) -> dict[str, Any]:
    """Ledger-derived fabric facts (pure; unit-tested with synthetic logs)."""
    completes = len(_COLL_COMPLETE_RE.findall(stderr))
    flits = [int(v) for v in _FLIT_RE.findall(stderr)]
    submits: list[list[bool]] = []
    for m in _SUBMIT_DIMS_RE.finditer(stderr):
        toks = [t.strip() for t in m.group(1).split(",") if t.strip()]
        if toks and all(t in ("true", "false") for t in toks):
            submits.append([t == "true" for t in toks])
    topo = _TOPO_RE.search(stderr)
    topo_dims = ([int(x) for x in topo.group(1).split(",")]
                 if topo else [])
    return {
        "coll_completes": completes,
        "max_retired_flits": max(flits) if flits else 0,
        "submit_vectors": submits,
        "topo_dims": topo_dims,
    }


def check_involved_dim_tripwire(evidence: dict[str, Any]) -> None:
    """Early tripwire: scoped collectives must carry topology-length vectors.

    The missing-attribute fallback fabricates all-true vectors (length 4
    in the current backend). On a multi-dim topology any vector longer
    than the topology is fabrication → fail. Multi-dim runs must also
    show at least one scoped (contains-False) vector, proving scoping
    flows end to end. Single-dim runs are exempt (unscoped traces are
    correct there; only index 0 is read).
    """
    ndims = len(evidence["topo_dims"])
    vectors = evidence["submit_vectors"]
    if ndims <= 1 or not vectors:
        return
    for v in vectors:
        if len(v) != ndims:
            raise ServingResultError(
                "FABRICATION_SUSPECT",
                f"involved_dim vector length {len(v)} != topology dims "
                f"{ndims} ({evidence['topo_dims']}) — suspected "
                "missing-attribute fallback fabrication; STOP, see "
                "Phase-3 handoff residual")
    if not any(not all(v) for v in vectors):
        raise ServingResultError(
            "SCOPING_ABSENT",
            f"{len(vectors)} submits on a {ndims}-dim topology with no "
            "scoped (contains-False) vector — collective scoping is not "
            "flowing; STOP")


def run_serving_experiment(
    spec_dict: dict[str, Any],
    *,
    repo: Path = REPO,
    ctx: Any = None,
) -> Run:
    """Execute one serving experiment end-to-end (Slice B: real BookSim).

    Returns the finished Run (SUCCEEDED or FAILED; refusal leaves
    CANCELLED with the reason recorded). Raises SpecError on bad intent,
    RunError only on control-plane bugs. Owns the child process group;
    never speaks the backend protocol.
    """
    from ..core.logging import Ctx
    ctx = ctx or Ctx()

    # ── validate (strict boundary; nothing on disk yet) ──────────────
    spec = parse(spec_dict)  # SpecError propagates: caller wrote bad intent
    if spec.simulation.mode != "serving":
        raise SpecError("simulation.mode must be serving for Slice B "
                        "(use run_experiment for standalone BookSim)")
    if spec.serving is None:  # resolve() also enforces; fail fast here
        raise SpecError("simulation.mode is serving but no serving block "
                        "was provided")
    if spec.replication.mode != "deterministic":
        # Serving has no seed control — multi-seed "replication" would be
        # one identical run counted N times. Refuse instead of lying.
        raise SpecError("serving replication must be deterministic "
                        "(LLMServingSim takes no seed)")
    resolved = resolve(spec)
    sv = resolved["serving"]
    if sv["network_backend"] != "booksim" or not sv["cycle_accurate"]:
        # Slice B is real-BookSim-only. Replay/analytical stay available
        # via `veritx serve` and PR7; they cannot enter this slice.
        raise SpecError("Slice B requires network_backend=booksim with "
                        "cycle_accurate=true (real simulation only)")
    cluster_path = serving_fixture("cluster", sv["cluster"])
    dataset_path = serving_fixture("dataset", sv["dataset"])
    if not cluster_path.is_file() or not dataset_path.is_file():
        raise SpecError("registered serving fixture missing on disk")

    # ── run directory (immutable from here) ──────────────────────────
    run = Run.create(repo=repo, resolved_spec=resolved, argv=list(sys.argv))

    def _cancel(reason: str) -> Run:
        run.add_result("validate", {"error": reason})
        run.transition("CANCELLED", note=reason)
        return run

    # ── preflight (before anything spawns) ───────────────────────────
    try:
        serve_binaries = preflight_serve(
            llmsim_dir=LLMSIM_DIR, cluster_path=cluster_path,
            dataset_path=dataset_path, network_backend="booksim",
            cycle_accurate=True, cli_dtype=None)
    except ServingPreflightError as e:
        return _cancel(f"preflight {e.reason}: {e}")
    run.transition("VALIDATED", note=f"preflight passed; "
                                     f"{len(serve_binaries)} binary(ies)")

    # ── plan (one task: serving runs have no seed axis) ──────────────
    plan = {"tasks": [{"task_id": "serve",
                       "cluster": sv["cluster"],
                       "dataset": sv["dataset"],
                       "num_reqs": sv["num_reqs"],
                       "timeout_s": resolved["simulation"]["timeout_s"]}]}
    with atomic_write(run.root / "plan.json") as tmp:
        tmp.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
    run.transition("PLANNED", note="1 task")
    run.transition("RUNNING")

    # ── execute (supervised child; WE own the process, not the protocol)
    csv_path = run.root / "artifacts" / "requests.csv"
    args = serve_args(
        num_reqs=sv["num_reqs"], network_backend="booksim",
        cycle_accurate=True,
        request_routing_policy=sv["request_routing_policy"],
        output=str(csv_path), log_level="WARNING",
        timeout=resolved["simulation"]["timeout_s"])
    cmd = build_serve_cmd(
        args,
        locate_serve_path(str(cluster_path), llmsim_dir=LLMSIM_DIR,
                          repo_dir=REPO, dse_dir=DSE_DIR),
        locate_serve_path(str(dataset_path), llmsim_dir=LLMSIM_DIR,
                          repo_dir=REPO, dse_dir=DSE_DIR))
    env = {**os.environ, "VERITX_LEDGER": "1"}  # fabric evidence channel
    try:
        from ..core.process import supervised_run
        try:
            res = supervised_run(cmd, cwd=str(LLMSIM_DIR),
                                 timeout=plan["tasks"][0]["timeout_s"],
                                 env=env)
        except subprocess.TimeoutExpired as e:
            out, err = getattr(e, "stdout", ""), getattr(e, "stderr", "")
            _write_logs(run, out, err)
            run.add_result("serve", {"error": "timeout",
                                     "timeout_s": plan["tasks"][0][
                                         "timeout_s"]})
            run.finalize("FAILED", note="serving exceeded timeout")
            return run
        _write_logs(run, res.stdout, res.stderr)
        if res.returncode != 0:
            run.add_result("serve", {"error": "nonzero exit",
                                     "returncode": res.returncode,
                                     "stderr_tail": res.stderr[-2000:]})
            run.finalize("FAILED", note=f"exit {res.returncode}")
            return run
        return _verdict(run, res, csv_path, sv, serve_binaries,
                        cluster_path, dataset_path)
    except KeyboardInterrupt:
        run.transition("INTERRUPTED", note="KeyboardInterrupt during serve")
        raise


def _write_logs(run: Run, out: Any, err: Any) -> None:
    with atomic_write(run.root / "stdout.log") as tmp:
        tmp.write_text(out or "")
    with atomic_write(run.root / "stderr.log") as tmp:
        tmp.write_text(err or "")


def _verdict(run: Run, res: Any, csv_path: Path, sv: dict[str, Any],
             serve_binaries: list[str], cluster_path: Path,
             dataset_path: Path) -> Run:
    """Terminal validation: retirement + provenance + fabric + tripwire."""
    network_mode = mode_for_backend("booksim", True)
    assert network_mode == "REAL_SIMULATION"
    fidelity = fidelity_for_mode("booksim", network_mode)
    try:
        retired = retired_from_csv(csv_path)
    except FileNotFoundError as e:
        run.add_result("serve", {"error": f"missing per-request CSV: {e}"})
        run.finalize("FAILED", note="no result artifact")
        return run
    if retired != sv["num_reqs"]:
        run.add_result("serve", {"error": "RETIREMENT_MISMATCH",
                                 "retired": retired,
                                 "requested": sv["num_reqs"]})
        run.finalize("FAILED", note=f"retired {retired}/{sv['num_reqs']}")
        return run
    evidence = fabric_evidence(res.stderr or "")
    if evidence["coll_completes"] < 1 or evidence["max_retired_flits"] < 1:
        run.add_result("serve", {"error": "NO_FABRIC_ACTIVITY",
                                 "evidence": evidence})
        run.finalize("FAILED", note="backend ran but fabric shows no "
                                    "collectives/flits — replay masquerade?")
        return run
    try:
        check_involved_dim_tripwire(evidence)
    except ServingResultError as e:
        run.add_result("serve", {"error": e.reason, "detail": str(e),
                                 "evidence": {
                                     "topo_dims": evidence["topo_dims"],
                                     "n_vectors": len(
                                         evidence["submit_vectors"])}})
        run.finalize("FAILED", note=e.reason)
        return run
    provenance = serving_provenance(
        engine="llmservingsim", network_backend="booksim2",
        network_mode=network_mode, semantic_losses=[])
    try:
        bundle = build_serving_metrics(
            csv_path, num_requested=sv["num_reqs"], fidelity=fidelity,
            wall_time_s=float(getattr(res, "wall_time_s", 0.0)))
    except (KeyError, ValueError) as e:
        run.add_result("serve", {"error": f"unparseable result CSV: {e}"})
        run.finalize("FAILED", note="malformed result artifact")
        return run
    run.add_result("serve", {
        "metric_schema": bundle["schema"],
        "metrics": bundle["metrics"],
        "provenance": {**provenance, "fidelity": fidelity},
        "backend_binaries": [binary_identity(b) for b in serve_binaries],
        "cluster_sha256": binary_identity(cluster_path)["sha256"],
        "dataset_sha256": binary_identity(dataset_path)["sha256"],
        "fabric": {
            "coll_completes": evidence["coll_completes"],
            "max_retired_flits": evidence["max_retired_flits"],
        },
    })
    run.finalize("SUCCEEDED")
    return run
