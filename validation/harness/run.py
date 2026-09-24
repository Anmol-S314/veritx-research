"""Run validation experiments and emit per-check evidence.

Usage:
    PYTHONPATH=tracks/t3-topology/dse python3 -m validation.harness.run \\
        validation/experiments/V02-allreduce-4x4.json
    PYTHONPATH=tracks/t3-topology/dse python3 -m validation.harness.run --all
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .authority import run_standalone
from .compare import EXACT, run_checks
from .fabric import build
from .spec import ExperimentSpec

HERE = Path(__file__).resolve().parent
VALIDATION_ROOT = HERE.parent
DEFAULT_EXPERIMENTS = VALIDATION_ROOT / "experiments"
DEFAULT_REPORTS = VALIDATION_ROOT / "reports"


def _binary() -> Path:
    override = os.environ.get("VERITX_BOOKSIM_BIN")
    if override:
        path = Path(override)
    else:
        from veritx_dse.core.paths import BOOKSIM_BIN
        path = BOOKSIM_BIN
    if not path.is_file():
        raise SystemExit(
            f"BookSim binary not found at {path}; build it (make tool-build "
            "TOOL=booksim2) or set VERITX_BOOKSIM_BIN. The corpus refuses to "
            "skip a differential check silently.")
    return path


def _execute_veritx(spec, built, binary: Path, run_dir: Path) -> dict:
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    record = execute_prepared_booksim(
        prepared=built.prepared, binary=binary, run_dir=run_dir,
        timeout=spec.timeout_s, seed=spec.seed)
    return record.evidence.stats


def run_experiment(spec: ExperimentSpec, binary: Path,
                   work_root: Path) -> dict:
    run_root = Path(tempfile.mkdtemp(prefix=f"{spec.id}-", dir=str(work_root)))
    try:
        built = build(spec)
        veritx_stats = _execute_veritx(spec, built, binary, run_root / "veritx")
        authority = run_standalone(
            spec_fabric=spec.fabric, prepared=built.prepared, binary=binary,
            run_dir=run_root / "authority", timeout_s=spec.timeout_s)
        authority_alt = None
        if "window_invariance" in spec.checks:
            authority_alt = run_standalone(
                spec_fabric=spec.fabric, prepared=built.prepared,
                binary=binary, run_dir=run_root / "authority-alt",
                timeout_s=spec.timeout_s, window_margin=3000)
        checks = run_checks(spec=spec, built=built, veritx_stats=veritx_stats,
                            authority=authority, authority_alt=authority_alt)
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
    return {
        "schema_version": 1,
        "id": spec.id,
        "title": spec.title,
        "profile_id": built.profile_id,
        "fabric": {
            "compute_tiles": spec.fabric.compute_tiles,
            "tp": spec.fabric.tp,
            "link_width": spec.fabric.link_width,
            "num_vcs": spec.fabric.num_vcs,
        },
        "workload": spec.workload.kind,
        "veritx": {
            "packets": built.packets,
            "flits": built.flits,
            "completion_cycles": veritx_stats["completion_cycles"],
            "sample_window_cycles": veritx_stats.get("sample_window_cycles"),
            "canonical_hops_avg": built.canonical_hops_avg,
        },
        "authority": {
            "class": "standalone_booksim",
            "completion_cycles": authority.completion_cycles,
            "sample_window_cycles": authority.sample_window_cycles,
            "injected_flits": authority.injected_flits,
            "accepted_flits": authority.accepted_flits,
            "hops_avg": authority.hops_avg,
        },
        "checks": [
            {"name": c.name, "authority_class": c.authority_class,
             "independence": c.independence, "verdict": c.verdict,
             "detail": c.detail, "values": c.values}
            for c in checks],
        "passed": all(c.verdict == EXACT for c in checks),
    }


def _markdown(reports: list[dict]) -> str:
    lines = ["# VERITX Validation Report", ""]
    for r in reports:
        lines.append(f"## {r['id']} — {r['title']}")
        lines.append("")
        lines.append(f"profile: `{r['profile_id']}`  ·  "
                     f"fabric: {r['fabric']}  ·  workload: {r['workload']}")
        lines.append("")
        lines.append("| check | authority | independence | value | verdict |")
        lines.append("|---|---|---|---|---|")
        for c in r["checks"]:
            v = c["values"]
            if c["name"] == "conservation":
                value = (f"packets={v['packets']}, flits={v['flits']}, "
                         f"auth_flits={v['authority_injected_flits']}/"
                         f"{v['authority_accepted_flits']}")
            elif c["name"] == "hand_route":
                value = (f"hand={v['hand_router_hops']}, "
                         f"canonical={v['canonical_hops_avg']}, "
                         f"authority={v['authority_hops_avg']} "
                         f"(expected {v['authority_expected']})")
            elif c["name"] == "standalone_parity":
                value = (f"{v['veritx_completion']} == "
                         f"{v['authority_completion']}")
            elif c["name"] == "window_invariance":
                value = f"completion={v['completion']}, windows={v['windows']}"
            else:
                value = json.dumps(v, sort_keys=True)
            lines.append(f"| {c['name']} | {c['authority_class']} | "
                         f"{c['independence']} | {value} | {c['verdict']} |")
        lines.append("")
        lines.append(f"**{'PASS' if r['passed'] else 'FAIL'}**")
        lines.append("")
    total = sum(len(r["checks"]) for r in reports)
    exact = sum(1 for r in reports for c in r["checks"]
                if c["verdict"] == EXACT)
    lines.append("---")
    lines.append("")
    lines.append(f"checks exact: {exact}/{total}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.harness.run")
    parser.add_argument("experiments", nargs="*",
                        help="experiment JSON files")
    parser.add_argument("--all", action="store_true",
                        help="run every experiment in validation/experiments")
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    args = parser.parse_args(argv)

    paths: list[Path] = []
    if args.all:
        paths = sorted(DEFAULT_EXPERIMENTS.glob("V*.json"))
    paths += [Path(p) for p in args.experiments]
    if not paths:
        parser.error("no experiments given (pass files or --all)")

    binary = _binary()
    reports_dir = Path(args.reports)
    reports_dir.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="validation-work-"))

    reports: list[dict] = []
    for path in paths:
        spec = ExperimentSpec.load(path)
        report = run_experiment(spec, binary, work_root)
        reports.append(report)
        (reports_dir / f"{spec.id}.json").write_text(
            json.dumps(report, indent=2) + "\n")
        print(f"{spec.id}: {'PASS' if report['passed'] else 'FAIL'} "
              f"({len(report['checks'])} checks)")
        for c in report["checks"]:
            print(f"  [{c['verdict']:>8}] {c['name']:<18} "
                  f"({c['authority_class']}, {c['independence']}) "
                  f"{c['detail']}")

    (reports_dir / "REPORT.md").write_text(_markdown(reports))
    shutil.rmtree(work_root, ignore_errors=True)
    print(f"\nreport: {reports_dir / 'REPORT.md'}")
    return 0 if all(r["passed"] for r in reports) else 1


if __name__ == "__main__":
    sys.exit(main())
