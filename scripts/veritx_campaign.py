"""VERITX serving campaign runner — real experiments, honest numbers.

Runs (cluster_config, dataset, num_reqs) triples through
ProductService.submit_serving (in-process, throwaway store roots),
waits for terminal jobs, and records one JSONL row per experiment.

Laws:
- refused/failed experiments are recorded with their exact reason,
  never zero-filled, never skipped silently;
- absent metrics stay absent (null), never 0;
- time bases are explicit: cycle counts are ASTRA system cycles;
  tokens-per-kilocycle is derived from those cycles, never wall time;
- percentiles use nearest-rank on measured values only.

Usage:
    PYTHONPATH=tracks/t3-topology/dse \\
    VERITX_BOOKSIM_BIN=$PWD/third_party/booksim2/src/booksim \\
    python3 scripts/veritx_campaign.py [--out DIR] [--only NAME ...]
"""
from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import tempfile
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tracks" / "t3-topology" / "dse"))

from veritx_dse.product.jobs import TERMINAL_STATES  # noqa: E402
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig,
    ProductService,
)

CLUSTER_DIR = "third_party/llmservingsim/configs/cluster"
TRACE_DIR = "third_party/llmservingsim/workloads"

EXPERIMENTS: tuple[tuple[str, str, str, int], ...] = (
    ("dense-tp1",
     f"{CLUSTER_DIR}/single_node_single_instance.json",
     f"{TRACE_DIR}/example_trace.jsonl", 8),
    ("dense-4xTP2",
     f"{CLUSTER_DIR}/single_node_4_instance_2TP.json",
     f"{TRACE_DIR}/example_trace.jsonl", 8),
    ("moe-tp2ep2",
     f"{CLUSTER_DIR}/single_node_moe_single_instance.json",
     f"{TRACE_DIR}/example_trace.jsonl", 8),
    ("mixed-608",
     f"{CLUSTER_DIR}/single_node_single_instance.json",
     f"{TRACE_DIR}/workload_me2_01_mixed.jsonl", 608),
    ("mixed-64",
     f"{CLUSTER_DIR}/single_node_4_instance_2TP.json",
     f"{TRACE_DIR}/workload_me2_01_mixed.jsonl", 64),
)

POLL_S = 5
JOB_BUDGET_S = 1500

def _pct(values: list[float], pct: float) -> float | None:
    """Nearest-rank percentile over measured values only; None if empty."""
    import math
    if not values:
        return None
    ordered = sorted(values)
    rank = min(len(ordered) - 1, max(0, math.ceil(pct / 100 * len(ordered)) - 1))
    return float(ordered[rank])

def _stats(values: list[float]) -> dict[str, float | int | None]:
    return {
        "n": len(values),
        "mean": (sum(values) / len(values)) if values else None,
        "p50": _pct(values, 50),
        "p95": _pct(values, 95),
        "p99": _pct(values, 99),
    }

def collect_metrics(evidence: dict) -> dict:
    """Project stored serving evidence into campaign metrics.

    Never invents: anything the evidence does not carry stays null.
    """
    doc = evidence.get("document") or {}
    metrics = doc.get("request_metrics") or []
    ttfts = [float(m[1]) for m in metrics
             if len(m) > 1 and isinstance(m[1], (int, float))
             and not isinstance(m[1], bool)]
    completions = [float(m[2]) for m in metrics
                   if len(m) > 2 and isinstance(m[2], (int, float))
                   and not isinstance(m[2], bool)]
    out_tokens = [float(m[3]) for m in metrics
                  if len(m) > 3 and isinstance(m[3], (int, float))
                  and not isinstance(m[3], bool)]
    makespan = max(completions) if completions else None
    total_tokens = sum(out_tokens) if out_tokens else None
    return {
        "requests_completed": evidence.get("request_count"),
        "requests_expected": evidence.get("requests_expected"),
        "rounds": evidence.get("rounds"),
        "instances_served": doc.get("instances_with_completions"),
        "instance_count": doc.get("instance_count"),
        "makespan_cycles": makespan,
        "ttft_cycles": _stats(ttfts),
        "completion_cycles": _stats(completions),
        "output_tokens_total": total_tokens,
        "tokens_per_kilocycle": (
            None if total_tokens is None or not makespan
            else total_tokens / makespan * 1000.0),
        "backend_evidence_ids": evidence.get("evidence_ids"),
        "machine_id": evidence.get("machine_id"),
        "namespace_id": evidence.get("namespace_id"),
        "prefill_cycles": None,
        "decode_cycles": None,
        "queueing_cycles": None,
        "network_cycles": None,
        "network_exposure_cycles": None,
    }

def wait_job(svc: ProductService, job_id: str,
             budget_s: int = JOB_BUDGET_S) -> dict:
    """Poll until the job reaches a terminal state or the budget ends."""
    deadline = time.time() + budget_s
    while True:
        job = svc.get_job(job_id)
        if job["state"] in TERMINAL_STATES:
            return job
        if time.time() > deadline:
            return {**job, "state": "POLL_BUDGET_EXCEEDED"}
        time.sleep(POLL_S)

def run_experiment(svc: ProductService, project_id: str, name: str,
                   cluster: str, dataset: str, num_reqs: int,
                   timeout_s: int | None = None) -> dict:
    """Submit one serving experiment and record its honest outcome."""
    row: dict = {"experiment": name, "cluster_config": cluster,
                 "dataset": dataset, "num_reqs": num_reqs,
                 "timeout_s": timeout_s}
    body: dict = {"cluster_config": cluster, "dataset": dataset,
                  "num_reqs": num_reqs}
    if timeout_s is not None:
        body["timeout_s"] = timeout_s
    try:
        job = svc.submit_serving(project_id, body)
    except Exception as exc:  # noqa: BLE001 - submit-time refusal
        row.update({"status": "SUBMIT_REFUSED",
                    "reason": f"{type(exc).__name__}: {exc}",
                    "metrics": None})
        return row
    job = wait_job(svc, job["job_id"])
    state = job["state"]
    if state == "POLL_BUDGET_EXCEEDED":
        row.update({"status": state,
                    "reason": f"job {job['job_id']} still "
                              f"{job.get('state')} after {JOB_BUDGET_S}s; "
                              "not killed, outcome unknown",
                    "metrics": None, "job_id": job["job_id"]})
        return row
    if state != "COMPLETED":
        row.update({"status": state,
                    "reason": f"{job.get('error_code')}: "
                              f"{job.get('error_message')}",
                    "metrics": None,
                    "job_id": job["job_id"]})
        return row
    serving_id = (job.get("result") or {}).get("serving_id")
    record = svc.get_serving(serving_id)
    row.update({"status": "COMPLETED", "reason": None,
                "job_id": job["job_id"], "serving_id": serving_id,
                "metrics": collect_metrics(record.get("evidence") or {})})
    return row

def markdown_table(rows: list[dict]) -> str:
    lines = ["| experiment | status | completed | makespan_cyc | "
             "ttft_mean/p50/p95 | compl_mean/p50/p95 | tok/kcyc | reason |",
             "|---|---|---|---|---|---|---|---|"]
    for row in rows:
        metrics = row.get("metrics") or {}
        ttft = metrics.get("ttft_cycles") or {}
        comp = metrics.get("completion_cycles") or {}

        def short(stats: dict) -> str:
            if not stats or not stats.get("n"):
                return "absent"
            fmt = lambda v: "absent" if v is None else f"{v:.0f}"
            return (f"{fmt(stats.get('mean'))}/{fmt(stats.get('p50'))}/"
                    f"{fmt(stats.get('p95'))}")

        reason = (row.get("reason") or "-")
        if len(reason) > 80:
            reason = reason[:77] + "..."
        lines.append(
            f"| {row['experiment']} | {row['status']} | "
            f"{metrics.get('requests_completed')}/"
            f"{metrics.get('requests_expected')} | "
            f"{metrics.get('makespan_cycles')} | {short(ttft)} | "
            f"{short(comp)} | {metrics.get('tokens_per_kilocycle')} | "
            f"{reason} |")
    return "\n".join(lines) + "\n"

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="runs/serving-campaign-01",
                        help="output dir relative to repo root")
    parser.add_argument("--only", nargs="*", default=None,
                        help="run only these experiment names")
    parser.add_argument("--timeout-s", type=int, default=None,
                        help="per-experiment serve timeout override")
    parser.add_argument("--work-root", default=None,
                        help="fixed store root (default: fresh mkdtemp); "
                             "kept for debugging backend failures")
    args = parser.parse_args(argv)

    selected = [exp for exp in EXPERIMENTS
                if args.only is None or exp[0] in args.only]
    if not selected:
        print("no experiments selected", file=sys.stderr)
        return 2

    if args.work_root:
        root = Path(args.work_root)
        root.mkdir(parents=True, exist_ok=True)
    else:
        root = Path(tempfile.mkdtemp(prefix="veritx-campaign-"))
    print(f"store root: {root}", flush=True)
    booksim = os.environ.get("VERITX_BOOKSIM_BIN")
    svc = ProductService(ProductConfig(
        projects_root=root / "projects",
        booksim_bin=Path(booksim) if booksim else None,
        repo_root=REPO))
    project_id = svc.create_project(name="serving campaign 01")[
        "project"]["project_id"]

    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[dict] = []
    jsonl_path = out_dir / "results.jsonl"
    with open(jsonl_path, "w", encoding="utf-8") as handle:
        for name, cluster, dataset, num_reqs in selected:
            print(f"--- {name} ({cluster} x {dataset} x{num_reqs}) ---",
                  flush=True)
            row = run_experiment(svc, project_id, name, cluster, dataset,
                                 num_reqs, timeout_s=args.timeout_s)
            rows.append(row)
            handle.write(json.dumps(row) + "\n")
            handle.flush()
            print(f"    -> {row['status']}: "
                  f"{row.get('reason') or 'measured'}", flush=True)
    table = markdown_table(rows)
    (out_dir / "RESULTS.md").write_text(
        "# Serving campaign 01\n\n" + table, encoding="utf-8")
    print()
    print(table)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
