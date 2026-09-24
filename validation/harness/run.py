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
from .compare import (
    EXACT, monotonicity_check, network_claims_quarantined, run_checks,
    run_rtl_checks,
)
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
         "detail": c.detail, "values": c.values,
         "quarantined": c.quarantined, "finding": c.finding}
        for c in checks]


def _experiment_status(checks: list[dict]) -> str:
    """PASS | FAIL | QUARANTINED. A quarantined mismatch is never a PASS."""
    counted = [c for c in checks if not c.get("quarantined")]
    if not counted:
        raise ValueError("every check is quarantined; refusing a vacuous pass")
    if any(c["verdict"] != EXACT for c in counted):
        return "FAIL"
    if any(c.get("quarantined") for c in checks):
        return "QUARANTINED"
    return "PASS"


def _status_ok(status: str, allow_quarantine: bool) -> bool:
    if status == "PASS":
        return True
    if status == "QUARANTINED":
        return allow_quarantine
    return False


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
        first_sub = None
        first_built = None
        for value in spec.sweep.values:
            sub = spec.sweep.apply(spec, value)
            run = _run_single(sub, binary, work_root)
            if first_built is None:
                first_sub, first_built = sub, run["built"]
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
        if spec.sweep.quantity == "completion_cycles" \
                and network_claims_quarantined(first_sub, first_built):
            mono = dataclasses.replace(
                mono, quarantined=True, finding="F-0004")
        checks.insert(0, _checks_to_dicts([mono])[0])
        if not checks:
            raise ValueError(f"{spec.id} produced zero checks")
        return {**base, "sweep": {
            "param": spec.sweep.param, "quantity": spec.sweep.quantity,
            "direction": spec.sweep.direction,
            "values": list(spec.sweep.values), "points": points},
            "checks": checks,
            "status": _experiment_status(checks),
            "passed": _experiment_status(checks) == "PASS",
            "quarantined_findings": sorted(
                {c["finding"] for c in checks if c.get("finding")})}

    run = _run_single(spec, binary, work_root)
    built, vstats, auth = run["built"], run["veritx_stats"], run["authority"]
    checks = _checks_to_dicts(run["checks"])
    if not checks:
        raise ValueError(f"{spec.id} produced zero checks")
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
            "status": _experiment_status(checks),
            "passed": _experiment_status(checks) == "PASS",
            "quarantined_findings": sorted(
                {c["finding"] for c in checks if c.get("finding")})}


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
            name = c["name"]
            if name == "trace_execution_conservation":
                value = (f"packets={v['packets']}, flits={v['flits']}, "
                         f"auth_flits={v['authority_injected_flits']}/"
                         f"{v['authority_accepted_flits']}")
            elif name == "workload_lowering_conservation":
                value = (f"messages={v.get('messages')}, "
                         f"bytes={v.get('total_bytes')}, "
                         f"flits={v.get('total_flits')}, "
                         f"packets={v.get('total_packets')}")
            elif name.startswith("hand_route"):
                value = (f"hand={v['hand_router_hops']} "
                         f"({v.get('route_hops_provenance')}), "
                         f"canonical={v['canonical_hops_avg']}, "
                         f"authority={v['authority_hops_avg']}")
            elif name.startswith("hand_counts"):
                value = (f"packets={v['packets']} "
                         f"({v.get('packets_provenance')}), "
                         f"flits={v['flits']} ({v.get('flits_provenance')})")
            elif name.startswith("standalone_parity"):
                value = (f"{v['veritx_completion']} == "
                         f"{v['authority_completion']}")
            elif name.startswith("window_invariance"):
                value = f"completion={v['completion']}, windows={v['windows']}"
            elif name == "monotonicity":
                value = (f"series={v['series']} "
                         f"authority={v['authority_series']}")
            elif name == "rtl_execution_conservation":
                value = (f"flits rtl={v['rtl_dump_flits']} "
                         f"canonical={v['canonical_flits']}")
            elif name == "rtl_calibrated_hop_equivalent":
                value = (f"hop-equiv={v.get('rtl_hop_equivalents')} "
                         f"hand={v['hand_router_hops']} "
                         f"({v.get('route_hops_provenance')})")
            elif name == "rtl_completion":
                value = (f"rtl={v['rtl_completion']} vs "
                         f"canonical={v['veritx_completion']} "
                         f"(delta {v['delta']:+d}, tol {v['tolerance']})")
            else:
                value = json.dumps(v, sort_keys=True)
            verdict = c["verdict"]
            if c.get("quarantined"):
                verdict = f"{verdict} (QUARANTINED {c.get('finding')})"
            lines.append(f"| {c['name']} | {c['authority_class']} | "
                         f"{c['independence']} | {value} | {verdict} |")
        lines.append("")
        lines.append(f"**{r.get('status', 'PASS' if r['passed'] else 'FAIL')}**")
        if r.get("quarantined_findings"):
            lines.append("")
            lines.append(f"quarantined findings: "
                         f"{r['quarantined_findings']}")
        lines.append("")
    total = sum(len(r["checks"]) for r in reports)
    exact = sum(1 for r in reports for c in r["checks"]
                if c["verdict"] == EXACT)
    counted = sum(1 for r in reports for c in r["checks"]
                  if not c.get("quarantined"))
    categories: dict[str, list[int]] = {}
    provenance: dict[str, list[int]] = {}
    for r in reports:
        for c in r["checks"]:
            bucket = categories.setdefault(c["independence"], [0, 0])
            bucket[1] += 1
            if c["verdict"] == EXACT:
                bucket[0] += 1
            if c["independence"] == "independent_oracle":
                prov = _oracle_provenance(c)
                pbucket = provenance.setdefault(prov, [0, 0])
                pbucket[1] += 1
                if c["verdict"] == EXACT:
                    pbucket[0] += 1
    lines.append("---")
    lines.append("")
    lines.append(f"checks exact: {exact}/{total} "
                 f"({total - counted} quarantined by a filed finding)")
    lines.append("")
    lines.append("by independence category (exact/total):")
    for name in sorted(categories):
        got, tot = categories[name]
        lines.append(f"  {name:34} {got}/{tot}")
    if provenance:
        lines.append("")
        lines.append("independent_oracle by provenance (exact/total):")
        for name in sorted(provenance):
            got, tot = provenance[name]
            lines.append(f"  {name:34} {got}/{tot}")
    return "\n".join(lines) + "\n"


def _oracle_provenance(check: dict) -> str:
    name = check["name"]
    values = check.get("values", {})
    if name == "workload_lowering_conservation" \
            or name == "collective_graph_conformance":
        return "preregistered_oracle"
    if name == "hand_route":
        return values.get("route_hops_provenance", "unstated")
    if name == "hand_counts":
        return values.get("flits_provenance",
                          values.get("packets_provenance", "unstated"))
    if name == "monotonicity":
        return "preregistered_physics"
    return "unstated"


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


def _metamorphic_markdown(results) -> str:
    lines = ["# VERITX Metamorphic Report", "",
             "Transforms with a known invariant; the physics must not move.",
             "", "| transform | invariant | result | detail |", "|---|---|---|---|"]
    for m in results:
        lines.append(f"| {m.name} | {m.invariant} | "
                     f"{'PASS' if m.passed else '**FAIL**'} | {m.detail} |")
    passed = sum(1 for m in results if m.passed)
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"invariants held: {passed}/{len(results)}")
    return "\n".join(lines) + "\n"


def _engines_markdown(results) -> str:
    lines = ["# VERITX Engine Gate Report", "",
             "Independent engines: availability and self-consistency.", "",
             "| engine | result | numerical validity | detail |",
             "|---|---|---|---|"]
    for e in results:
        validity = "established" if e.validated else "**NOT_ESTABLISHED**"
        lines.append(f"| {e.name} | {'PASS' if e.passed else '**FAIL**'} | "
                     f"{validity} | {e.detail} |")
    passed = sum(1 for e in results if e.passed)
    unvalidated = [e.name for e in results if not e.validated]
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append(f"engines passing: {passed}/{len(results)}")
    if unvalidated:
        lines.append(f"unvalidated numerical output: {sorted(unvalidated)}")
    return "\n".join(lines) + "\n"


def _intervention_markdown(verdict: dict) -> str:
    lines = ["# VERITX F-0003 Schedule Intervention", "",
             "Same packets, topology, routing and sizes; only the injection",
             "schedule changes. If completion tracks the injection horizon",
             "the metric is injection-bound (F-0003 supported).", "",
             "| schedule | spacing | horizon | completion | drain |",
             "|---|---|---|---|---|"]
    for row in verdict["rows"]:
        lines.append(f"| {row['schedule']} | {row['spacing']} | "
                     f"{row['horizon']} | {row['completion']} | "
                     f"{row['drain']} |")
    lines.append("")
    lines.append(f"drain spread: {verdict['drain_spread']} cycles")
    lines.append("")
    lines.append(f"**F-0003 {'SUPPORTED' if verdict['supported'] else 'REFUTED'}**")
    for problem in verdict["problems"]:
        lines.append(f"- {problem}")
    return "\n".join(lines) + "\n"


def _aggregate(flag: bool, results, attr: str, where: str) -> bool:
    """Fold a result set into the overall verdict, refusing an empty set."""
    if not results:
        raise ValueError(f"{where} produced zero results; an empty all() is "
                         "not a PASS")
    return flag and all(getattr(r, attr) for r in results)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="validation.harness.run")
    parser.add_argument("experiments", nargs="*",
                        help="experiment JSON files")
    parser.add_argument("--all", action="store_true",
                        help="run every experiment in validation/experiments")
    parser.add_argument("--mutations", action="store_true",
                        help="also run the negative mutation layer")
    parser.add_argument("--metamorphic", action="store_true",
                        help="also run the metamorphic invariant layer")
    parser.add_argument("--engines", action="store_true",
                        help="also run the independent engine gates")
    parser.add_argument("--intervention", action="store_true",
                        help="also run the F-0003 injection-schedule "
                             "intervention")
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    parser.add_argument("--allow-quarantine", action="store_true",
                        help="exploratory mode: a QUARANTINED experiment "
                             "(active filed finding) does not fail the run; "
                             "seal/release mode (default) returns nonzero "
                             "while any active quarantine exists")
    args = parser.parse_args(argv)
    allow_quarantine = args.allow_quarantine

    paths: list[Path] = []
    if args.all:
        paths = sorted(DEFAULT_EXPERIMENTS.glob("V*.json"))
    paths += [Path(p) for p in args.experiments]
    if not paths and not args.mutations and not args.metamorphic \
            and not args.engines and not args.intervention:
        parser.error("no experiments given (pass files, --all, --mutations, "
                     "--metamorphic, --engines or --intervention)")

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
        print(f"{spec.id}: {report['status']} "
              f"({len(report['checks'])} checks)")
        for c in report["checks"]:
            flag = (f" QUARANTINED:{c['finding']}" if c.get("quarantined")
                    else "")
            print(f"  [{c['verdict']:>8}]{flag:<16} {c['name']:<28} "
                  f"({c['authority_class']}, {c['independence']}) "
                  f"{c['detail']}")
        ok = ok and _status_ok(report["status"], allow_quarantine)

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
        ok = _aggregate(ok, mutations, "caught", "mutation layer")
        print(f"mutations: {reports_dir / 'MUTATIONS.md'}")

    if args.metamorphic:
        from .metamorphic import run_metamorphic
        meta = run_metamorphic(binary, work_root)
        (reports_dir / "METAMORPHIC.md").write_text(
            _metamorphic_markdown(meta))
        (reports_dir / "metamorphic.json").write_text(json.dumps(
            [dataclasses.asdict(m) for m in meta], indent=2) + "\n")
        print("\nmetamorphic layer:")
        for m in meta:
            print(f"  [{'pass' if m.passed else 'FAIL'}] {m.name}: {m.detail}")
        ok = _aggregate(ok, meta, "passed", "metamorphic layer")
        print(f"metamorphic: {reports_dir / 'METAMORPHIC.md'}")

    if args.engines:
        from .engines import run_engines
        engines = run_engines(REPO_ROOT, work_root)
        (reports_dir / "ENGINES.md").write_text(_engines_markdown(engines))
        (reports_dir / "engines.json").write_text(json.dumps(
            [dataclasses.asdict(e) for e in engines], indent=2) + "\n")
        print("\nengine gates:")
        for e in engines:
            print(f"  [{'pass' if e.passed else 'FAIL'}] {e.name}: {e.detail}")
        ok = _aggregate(ok, engines, "passed", "engine gates")
        print(f"engines: {reports_dir / 'ENGINES.md'}")

    if args.intervention:
        from .intervention import (
            intervention_verdict, run_schedule_intervention,
        )
        rows = run_schedule_intervention(binary, work_root)
        if not rows:
            raise ValueError("intervention produced zero rows; not a PASS")
        verdict = intervention_verdict(rows)
        (reports_dir / "INTERVENTION.md").write_text(
            _intervention_markdown(verdict))
        (reports_dir / "intervention.json").write_text(
            json.dumps(verdict, indent=2) + "\n")
        print("\nF-0003 schedule intervention:")
        for row in rows:
            print(f"  {row.schedule:<14} horizon={row.horizon:>6} "
                  f"completion={row.completion:>6} drain={row.drain:>5}")
        print(f"  F-0003 {'SUPPORTED' if verdict['supported'] else 'REFUTED'}"
              f" (drain spread {verdict['drain_spread']})")
        ok = ok and verdict["supported"]
        print(f"intervention: {reports_dir / 'INTERVENTION.md'}")

    shutil.rmtree(work_root, ignore_errors=True)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
