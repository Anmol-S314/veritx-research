"""Run validation experiments and emit per-check evidence.

Usage:
    PYTHONPATH=tracks/t3-topology/dse python3 -m validation.harness.run \\
        validation/experiments/V02-allreduce-4x4.json
    PYTHONPATH=tracks/t3-topology/dse python3 -m validation.harness.run --all
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from .authority import run_standalone
from .compare import EXACT, monotonicity_check, run_checks, run_rtl_checks
from .fabric import build
from .spec import ExperimentSpec

HERE = Path(__file__).resolve().parent
VALIDATION_ROOT = HERE.parent
REPO_ROOT = VALIDATION_ROOT.parent
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


def _run_single(spec: ExperimentSpec, binary: Path, work_root: Path) -> dict:
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
        if "rtl_parity" in spec.checks:
            from .rtl import run_authority as run_rtl_authority
            rtl = run_rtl_authority(spec=spec, built=built,
                                    repo_root=REPO_ROOT,
                                    work_root=work_root)
            checks = list(checks) + run_rtl_checks(
                spec=spec, built=built, veritx_stats=veritx_stats, rtl=rtl)
    finally:
        shutil.rmtree(run_root, ignore_errors=True)
    return {"built": built, "veritx_stats": veritx_stats,
            "authority": authority, "checks": checks}


def _checks_to_dicts(checks, suffix: str = "") -> list[dict]:
    return [
        {"name": c.name + suffix, "authority_class": c.authority_class,
         "independence": c.independence, "verdict": c.verdict,
         "detail": c.detail, "values": c.values}
        for c in checks]


def run_experiment(spec: ExperimentSpec, binary: Path,
                   work_root: Path) -> dict:
    base = {
        "schema_version": 1,
        "id": spec.id,
        "title": spec.title,
        "fabric": {
            "compute_tiles": spec.fabric.compute_tiles,
            "tp": spec.fabric.tp,
            "link_width": spec.fabric.link_width,
            "num_vcs": spec.fabric.num_vcs,
        },
        "workload": spec.workload.kind,
    }

    if spec.sweep is not None:
        points: list[dict] = []
        checks: list[dict] = []
        for value in spec.sweep.values:
            sub = spec.sweep.apply(spec, value)
            run = _run_single(sub, binary, work_root)
            vstats = run["veritx_stats"]
            auth = run["authority"]
            built = run["built"]
            quantity = (vstats["completion_cycles"]
                        if spec.sweep.quantity == "completion_cycles"
                        else built.flits)
            authority_quantity = (
                auth.completion_cycles
                if spec.sweep.quantity == "completion_cycles"
                else auth.injected_flits)
            points.append({
                "value": value, "quantity": quantity,
                "authority_quantity": authority_quantity,
                "packets": built.packets, "flits": built.flits,
                "completion_cycles": vstats["completion_cycles"],
                "authority_completion": auth.completion_cycles})
            checks.extend(_checks_to_dicts(run["checks"],
                                           suffix=f"@{value}"))
        mono = monotonicity_check(spec, points)
        checks.insert(0, _checks_to_dicts([mono])[0])
        return {**base, "sweep": {
            "param": spec.sweep.param, "quantity": spec.sweep.quantity,
            "direction": spec.sweep.direction,
            "values": list(spec.sweep.values), "points": points},
            "checks": checks,
            "passed": all(c["verdict"] == EXACT for c in checks)}

    run = _run_single(spec, binary, work_root)
    built, vstats, auth = run["built"], run["veritx_stats"], run["authority"]
    checks = _checks_to_dicts(run["checks"])
    return {**base,
            "profile_id": built.profile_id,
            "veritx": {
                "packets": built.packets,
                "flits": built.flits,
                "completion_cycles": vstats["completion_cycles"],
                "sample_window_cycles": vstats.get("sample_window_cycles"),
                "canonical_hops_avg": built.canonical_hops_avg,
            },
            "authority": {
                "class": "standalone_booksim",
                "completion_cycles": auth.completion_cycles,
                "sample_window_cycles": auth.sample_window_cycles,
                "injected_flits": auth.injected_flits,
                "accepted_flits": auth.accepted_flits,
                "hops_avg": auth.hops_avg,
            },
            "checks": checks,
            "passed": all(c["verdict"] == EXACT for c in checks)}


def _markdown(reports: list[dict]) -> str:
    lines = ["# VERITX Validation Report", ""]
    for r in reports:
        lines.append(f"## {r['id']} — {r['title']}")
        lines.append("")
        if "sweep" in r:
            s = r["sweep"]
            lines.append(f"sweep `{s['param']}` → `{s['quantity']}` "
                         f"({s['direction']})  ·  fabric: {r['fabric']}")
            lines.append("")
            lines.append(f"| {s['param']} | packets | flits | VERITX "
                         f"{s['quantity']} | authority |")
            lines.append("|---|---|---|---|---|")
            for p in s["points"]:
                lines.append(
                    f"| {p['value']} | {p['packets']} | {p['flits']} | "
                    f"{p['quantity']} | {p['authority_quantity']} |")
            lines.append("")
        else:
            lines.append(f"profile: `{r['profile_id']}`  ·  "
                         f"fabric: {r['fabric']}  ·  workload: {r['workload']}")
            lines.append("")
        lines.append("| check | authority | independence | value | verdict |")
        lines.append("|---|---|---|---|---|")
        for c in r["checks"]:
            v = c["values"]
            if c["name"].startswith("conservation"):
                value = (f"packets={v['packets']}, flits={v['flits']}, "
                         f"auth_flits={v['authority_injected_flits']}/"
                         f"{v['authority_accepted_flits']}")
            elif c["name"].startswith("hand_route"):
                value = (f"hand={v['hand_router_hops']}, "
                         f"canonical={v['canonical_hops_avg']}, "
                         f"authority={v['authority_hops_avg']} "
                         f"(expected {v['authority_expected']})")
            elif c["name"].startswith("standalone_parity"):
                value = (f"{v['veritx_completion']} == "
                         f"{v['authority_completion']}")
            elif c["name"].startswith("window_invariance"):
                value = f"completion={v['completion']}, windows={v['windows']}"
            elif c["name"] == "monotonicity":
                value = (f"series={v['series']} "
                         f"authority={v['authority_series']}")
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


def _mutations_markdown(results) -> str:
    lines = ["# VERITX Mutation Report", "",
             "Deliberate corruptions the canonical path must refuse.", "",
             "| mutation | expected refusal | result | detail |",
             "|---|---|---|---|"]
    for m in results:
        lines.append(
            f"| {m.name} | `{m.expected}` | "
            f"{'CAUGHT' if m.caught else '**MISSED**'} | {m.detail} |")
    caught = sum(1 for m in results if m.caught)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"mutations caught: {caught}/{len(results)}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.harness.run")
    parser.add_argument("experiments", nargs="*",
                        help="experiment JSON files")
    parser.add_argument("--all", action="store_true",
                        help="run every experiment in validation/experiments")
    parser.add_argument("--mutations", action="store_true",
                        help="also run the negative mutation layer")
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    args = parser.parse_args(argv)

    paths: list[Path] = []
    if args.all:
        paths = sorted(DEFAULT_EXPERIMENTS.glob("V*.json"))
    paths += [Path(p) for p in args.experiments]
    if not paths and not args.mutations:
        parser.error("no experiments given (pass files, --all or --mutations)")

    binary = _binary()
    reports_dir = Path(args.reports)
    reports_dir.mkdir(parents=True, exist_ok=True)
    work_root = Path(tempfile.mkdtemp(prefix="validation-work-"))

    ok = True
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
            print(f"  [{c['verdict']:>8}] {c['name']:<24} "
                  f"({c['authority_class']}, {c['independence']}) "
                  f"{c['detail']}")
        ok = ok and report["passed"]

    if reports:
        (reports_dir / "REPORT.md").write_text(_markdown(reports))
        print(f"\nreport: {reports_dir / 'REPORT.md'}")

    if args.mutations:
        from .mutations import run_mutations
        mutations = run_mutations(binary, work_root)
        (reports_dir / "MUTATIONS.md").write_text(
            _mutations_markdown(mutations))
        (reports_dir / "mutations.json").write_text(json.dumps(
            [dataclasses.asdict(m) for m in mutations], indent=2) + "\n")
        print("\nmutation layer:")
        for m in mutations:
            print(f"  [{'caught' if m.caught else 'MISSED'}] {m.name}: "
                  f"{m.detail}")
        ok = ok and all(m.caught for m in mutations)
        print(f"mutations: {reports_dir / 'MUTATIONS.md'}")

    shutil.rmtree(work_root, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
