#!/usr/bin/env python3
"""Run one uniform workload against every executable topology family.

Why this exists
---------------
``scripts/run_experiments.py`` globs ``configs/*.cfg``: a mix of shipped
product configs, native backend spellings, and research-only projections that
BookSim may or may not support.  Its output is what the Studio prototype
bundles as ``public/data/topology_sweep.json``.  A curve assembled from that
glob cannot answer "how do the topologies we support compare?" because the
arms differ in endpoint count, buffer budget, and even whether the family is
authorable.

This runner is deliberately narrower and explicit:

* **One workload.** Uniform random traffic (BookSim ``traffic=uniform``).
* **One size.** 16 endpoints for every arm (two fat-tree spellings excepted
  only in *routing policy*, not size).
* **One buffer/packet budget.** ``packet_size=5``, ``vc_buf_size=8``,
  ``use_noc_latency=0``, ``router=iq``.  VC count is each arm's canonical
  minimum for deadlock freedom and is reported per arm; it is not silently
  equalised because GEC-hybrid structurally needs 6 and SROTA-row needs 1.
* **One parser.** The *overall* BookSim statistics block, not the first
  per-sample line.  The per-sample line is a single transient window.

The output is byte-for-byte consumable by the Studio prototype
(``topology_sweep.json`` + ``pareto_2d.csv``) and keeps every failure as a
row instead of dropping it from the curve.

Usage
-----
    python3 scripts/sweep_supported.py
    python3 scripts/sweep_supported.py --native-power --copy-to-prototype
    python3 scripts/sweep_supported.py --rates 0.01,0.05,0.1 --jobs 4

The run directory contains ``configs/<arm>/``, ``logs/<arm>_<rate>.log``,
``topology_sweep.json``, ``pareto_2d.csv`` and ``summary.md``. With
``--native-power``, audited point-to-point arms also carry modeled W, mm² and
pJ/cycle plus snapshotted technology/binary provenance in ``native-model/``.
The legacy CSV remains a zero-load hops-based proxy, not the native frontier.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, asdict
from pathlib import Path

from native_power import NATIVE_FAMILIES, power_evidence, prepare_model

HERE = Path(__file__).resolve().parent
TRACK = HERE.parent
REPO = TRACK.parent.parent
CONFIGS = TRACK / "configs"
SUPPORTED = CONFIGS / "supported16"
DEFAULT_BOOKSIM = REPO / "third_party" / "booksim2" / "src" / "booksim"
PROTOTYPE_DATA = REPO / "apps" / "studio" / "prototype" / "public" / "data"

RATES = (0.005, 0.01, 0.02, 0.03, 0.05, 0.07, 0.10, 0.15, 0.20, 0.25, 0.30)
PJ_PER_HOP = 20.5  # same modeled constant as scripts/energy_score.py


@dataclass(frozen=True)
class Arm:
    """One declared arm: a topology family plus its routing realization."""

    arm_id: str
    family: str
    config: Path
    vcs: int
    routing: str
    qualification: str
    note: str = ""


ARMS: tuple[Arm, ...] = (
    Arm("mesh4x4", "MESH", CONFIGS / "mesh4x4.cfg", 2,
        "dor (X then Y)", "QUALIFIED",
        "shipped repo config; 4x4 mesh, 16 endpoints"),
    Arm("torus4x4", "TORUS", CONFIGS / "torus4x4.cfg", 2,
        "dim_order", "EXECUTABLE (even-side caveat)",
        "4x4 even-side torus; product refuses even-side deterministic "
        "routing dumps, raw BookSim still runs it"),
    Arm("cmesh16", "CONCENTRATED_MESH", CONFIGS / "cmesh16.cfg", 2,
        "dor", "EXECUTABLE / qualification withdrawn",
        "2x2 routers x concentration 4; 16 endpoints"),
    Arm("fattree16", "FAT_TREE", CONFIGS / "fattree16.cfg", 2,
        "nca (adaptive)", "QUALIFIED (native spelling)",
        "native BookSim fattree spelling, not the AnyNet projection"),
    Arm("fattree16_anynet", "FAT_TREE", SUPPORTED / "fattree16_anynet" / "config.cfg", 2,
        "min (AnyNet)", "QUALIFIED (product projection)",
        "canonical fat-tree graph lowered to AnyNet; deterministic "
        "min-hop routing (one path per leaf pair)"),
    Arm("flatfly16", "FLATFLY", CONFIGS / "flatfly16.cfg", 2,
        "ran_min", "QUALIFIED",
        "4-ary 2-fly, concentration 1; 16 endpoints"),
    Arm("srota16_row", "SROTA", CONFIGS / "srota16_xy.cfg", 1,
        "o1turn, row-first only", "QUALIFIED (row-first profile)",
        "Plane D side-buffer shape; 1 VC by construction"),
    Arm("srota16_rowcol", "SROTA", CONFIGS / "srota16.cfg", 4,
        "o1turn, row + column", "QUALIFIED (shape profile)",
        "both direct shapes live; 4 VCs, 2 per rank set"),
    Arm("srota16_islands", "SROTA", CONFIGS / "srota16_sb.cfg", 2,
        "o1turn, column-first islands", "QUALIFIED (islands profile)",
        "QoS island columns 0 and 3; 2 VCs"),
    Arm("gec_express16", "GEC_EXPRESS", SUPPORTED / "gec_express16" / "config.cfg", 2,
        "min (AnyNet)", "QUALIFIED",
        "point-to-point express channels lowered to AnyNet"),
    Arm("gec_mecs16", "GEC_MECS", SUPPORTED / "gec_mecs16" / "config.cfg", 3,
        "dor_gec", "QUALIFIED",
        "one shared multidrop wire per dimension, d=3 taps; 3 VCs"),
    Arm("gec_hybrid16", "GEC_HYBRID", SUPPORTED / "gec_hybrid16" / "config.cfg", 6,
        "hybrid_gec", "QUALIFIED",
        "mesh + MECS ranked candidate union; 2*d = 6 phase/tap VCs"),
    Arm("explicit16", "CUSTOM", SUPPORTED / "explicit16" / "config.cfg", 2,
        "min (AnyNet)", "PARTIAL (AnyNet path)",
        "explicit 4x4 graph declared as TopologyIR, lowered to AnyNet"),
)


def _arg_rates(text: str) -> tuple[float, ...]:
    values = tuple(float(tok) for tok in text.split(",") if tok.strip())
    if not values or any(v <= 0 for v in values):
        raise argparse.ArgumentTypeError("rates must be positive numbers")
    return tuple(sorted(set(values)))


def _booksim(path_text: str | None) -> Path:
    if path_text:
        candidate = Path(path_text)
    elif os.environ.get("BOOKSIM_BIN"):
        candidate = Path(os.environ["BOOKSIM_BIN"])
    else:
        candidate = DEFAULT_BOOKSIM
    if not candidate.is_file():
        raise SystemExit(f"BookSim binary not found: {candidate}")
    return candidate


def _last_value(text: str, key: str) -> float | None:
    """Value from the final (overall) statistics block.

    BookSim prints ``Packet latency average`` once per sample window and then
    again in the overall block.  Taking the first occurrence reports a single
    transient window, not the run average.  The overall block is the last
    occurrence, so scan backwards.
    """
    marker = text.rfind("Overall Traffic Statistics")
    block = text[marker:] if marker >= 0 else text
    for line in reversed(block.splitlines()):
        if key in line:
            for token in line.split():
                try:
                    value = float(token)
                except ValueError:
                    continue
                if math.isfinite(value):
                    return value
    return None


def _cost(text: str) -> dict[str, int | None]:
    import re
    match = re.search(
        r"Network cost: subnet=0 routers=(\d+) input_ports=(\d+) "
        r"output_ports=(\d+) crosspoints=(\d+) storage_flits=(-?\d+)",
        text)
    if not match:
        return {"routers": None, "crosspoints": None, "storage_flits": None}
    routers, _, _, crosspoints, storage = (int(v) for v in match.groups())
    return {"routers": routers, "crosspoints": crosspoints,
            "storage_flits": storage if storage >= 0 else None}


def _arm_dir(root: Path, arm: Arm) -> Path:
    target = root / "configs" / arm.arm_id
    target.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(arm.config, target / "config.cfg")
    # AnyNet configs name a sibling topology file.
    topology = arm.config.parent / "topology.anynet"
    if topology.is_file():
        shutil.copyfile(topology, target / "topology.anynet")
    return target


def _run_one(binary: Path, root: Path, arm: Arm, rate: float,
             timeout: int, native_model: dict | None = None) -> dict:
    directory = root / "configs" / arm.arm_id
    command = [
        str(binary), "config.cfg",
        "traffic=uniform", f"injection_rate={rate}",
        "injection_rate_uses_flits=0",
        "packet_size=5", "vc_buf_size=8", f"num_vcs={arm.vcs}",
        "use_noc_latency=0", "router=iq", "priority=none",
        "sim_type=latency", "warmup_periods=3", "sample_period=1000",
        "max_samples=10", "print_activity=0", "seed=1",
    ]
    native_enabled = native_model is not None and arm.family in NATIVE_FAMILIES
    command += [f"sim_power={int(native_enabled)}", "channel_width=128"]
    if native_enabled:
        command += [f"tech_file={(root / 'native-model/techfile.txt').resolve()}"]
    try:
        completed = subprocess.run(
            command, cwd=directory, capture_output=True, text=True,
            timeout=timeout)
        out, err, rc = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")) + "\nTIMEOUT"
        rc = -1

    log = root / "logs" / f"{arm.arm_id}_{rate:g}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("$ " + " ".join(command) + "\n" + out
                   + ("\n--- stderr ---\n" + err if err else ""))

    latency = _last_value(out, "Packet latency average")
    hops = _last_value(out, "Hops average")
    accepted = _last_value(out, "Accepted packet rate average")
    injected = _last_value(out, "Injected packet rate average")
    completion = _last_value(out, "Completion time is")
    if completion is not None and completion <= 0:
        completion = None

    if latency is None:
        lowered = (out + err).lower()
        if rc == -1 or "timeout" in lowered:
            status = "timeout"
        elif "unknown topology" in lowered:
            status = "unknown_topology"
        elif "must match topology node count" in lowered:
            status = "skipped_node_mismatch"
        else:
            status = "no_output"
    elif re.search(r"Simulation unstable", out + err):
        status = "unstable"
    else:
        status = "ok"

    return {
        "topology": arm.arm_id,
        "family": arm.family,
        "routing": arm.routing,
        "qualification": arm.qualification,
        "endpoints": 16,
        "packet_size_flits": 5,
        "channel_width_bits": 128,
        "vc_buf_size": 8,
        "num_vcs": arm.vcs,
        "note": arm.note,
        "injection_rate": rate,
        "traffic": "uniform",
        "latency_cycles": latency,
        "hops_avg": hops,
        "offered_rate": rate,
        "accepted_rate": accepted,
        "injected_rate": injected,
        "completion_cycles": completion,
        **_cost(out),
        **power_evidence(out, arm.family, status, rc, native_model),
        "status": status,
        "returncode": rc,
        "log": str(log.relative_to(root)),
    }


def _pareto_rows(rows: list[dict], baseline: str = "mesh4x4") -> list[dict]:
    """One zero-load operating point per topology, non-dominated front."""
    ok = [r for r in rows if r["status"] == "ok"
          and isinstance(r["latency_cycles"], (int, float))
          and isinstance(r["hops_avg"], (int, float))]
    floor = min(r["injection_rate"] for r in ok)
    points = []
    for topo in sorted({r["topology"] for r in ok}):
        candidates = [r for r in ok
                      if r["topology"] == topo and r["injection_rate"] == floor]
        if not candidates:
            continue
        row = candidates[0]
        points.append({
            "topology": topo,
            "family": row["family"],
            "injection_rate": floor,
            "zero_load_latency": round(row["latency_cycles"], 4),
            "hops_avg": round(row["hops_avg"], 5),
            "energy_score": round(row["hops_avg"] * PJ_PER_HOP, 4),
            "total_power": None,
            "total_area": None,
        })
    reference = next((p["zero_load_latency"] for p in points
                      if p["topology"] == baseline), None)
    for point in points:
        point["norm_latency"] = (
            round(point["zero_load_latency"] / reference, 6)
            if reference else None)

    # Non-dominated set: minimise (norm_latency, energy_score).  Equal
    # points both survive (BookSim noise can make them identical), which is
    # honest: neither strictly dominates the other.
    for point in points:
        x = point["norm_latency"]
        y = point["energy_score"]
        if x is None or y is None:
            point["pareto_front"] = False
            continue
        dominated = False
        for other in points:
            ox, oy = other["norm_latency"], other["energy_score"]
            if other is point or ox is None or oy is None:
                continue
            if ox <= x and oy <= y and (ox < x or oy < y):
                dominated = True
                break
        point["pareto_front"] = not dominated
    points.sort(key=lambda p: (p["norm_latency"] is None,
                               p["norm_latency"] or 0))
    return points


PARETO_FIELDS = ["topology", "injection_rate", "zero_load_latency",
                 "norm_latency", "hops_avg", "energy_score", "total_power",
                 "total_area", "pareto_front"]


def _write_csv(path: Path, points: list[dict]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=PARETO_FIELDS,
                                extrasaction="ignore")
        writer.writeheader()
        for point in points:
            writer.writerow({**point,
                             "total_power": "" if point["total_power"] is None
                             else point["total_power"],
                             "total_area": "" if point["total_area"] is None
                             else point["total_area"],
                             "pareto_front": "True" if point["pareto_front"]
                             else "False"})


def _summary(path: Path, rows: list[dict], points: list[dict],
             rates: tuple[float, ...], binary: Path) -> None:
    lines = [
        "# Supported-topology uniform sweep",
        "",
        f"- BookSim: `{binary}`",
        f"- Endpoints per arm: 16",
        f"- Workload: uniform random traffic, packet_size=5, vc_buf_size=8, "
        f"use_noc_latency=0, router=iq",
        f"- Rates: {', '.join(f'{r:g}' for r in rates)}",
        "- Parser: BookSim overall statistics block (not the first sample window)",
        "",
        "## Arms and zero-load point",
        "",
        "| arm | family | VCs | routing | status | zero-load latency | hops | accepted @ floor |",
        "|---|---|---:|---|---|---:|---:|---:|",
    ]
    by_id = {p["topology"]: p for p in points}
    for arm in ARMS:
        point = by_id.get(arm.arm_id)
        arm_rows = [r for r in rows if r["topology"] == arm.arm_id]
        statuses = {r["status"] for r in arm_rows}
        status = "ok" if statuses == {"ok"} else ", ".join(sorted(statuses))
        if point:
            lines.append(
                f"| `{arm.arm_id}` | {arm.family} | {arm.vcs} | {arm.routing} | "
                f"{status} | {point['zero_load_latency']:.2f} | "
                f"{point['hops_avg']:.3f} | "
                f"{next((r['accepted_rate'] for r in arm_rows if r['injection_rate'] == point['injection_rate']), float('nan'))} |")
        else:
            lines.append(
                f"| `{arm.arm_id}` | {arm.family} | {arm.vcs} | {arm.routing} | "
                f"{status} | — | — | — |")
    lines += ["", "## Pareto (zero-load latency vs modeled energy)", "",
              "Energy is `hops x 20.5 pJ/hop`, the repository's modeled proxy, "
              "not a measured Accelergy value.", "",
              "| topology | norm latency | energy (pJ) | on front |",
              "|---|---:|---:|---|"]
    for point in points:
        lines.append(
            f"| `{point['topology']}` | {point['norm_latency']:.4f} | "
            f"{point['energy_score']:.2f} | "
            f"{'yes' if point['pareto_front'] else 'no'} |")
    native = [r for r in rows if r.get('native_model', {}).get('status') == 'AVAILABLE']
    if native:
        lines += ['', '## Native model coverage', '',
                  f'{len(native)} available observations across {len({r["topology"] for r in native})} arms.',
                  'Native estimates are in topology_sweep.json, not the legacy proxy CSV.',
                  'Technology: 2007 ITRS 32nm prediction, 128-bit flits; not silicon calibrated.',
                  'Energy/cycle = native W / native model clock Hz * 1e12, never energy/packet.',
                  'Unsupported shared-wire/unaudited families remain unavailable.',
                  'See native-model/model.json, the technology snapshot and per-observation logs.']
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=TRACK / "runs" / "supported-sweep",
                        help="run directory (default: tracks/t3-topology/runs/supported-sweep)")
    parser.add_argument("--rates", type=_arg_rates, default=RATES)
    parser.add_argument("--booksim", default=None)
    parser.add_argument("--native-power", action="store_true",
                        help="record native modeled power, area and energy/cycle for audited point-to-point families; not silicon calibration")
    parser.add_argument("--jobs", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--timeout", type=int, default=120)
    parser.add_argument("--copy-to-prototype", action="store_true",
                        help="copy the sweep JSON and Pareto CSV into the "
                             "Studio prototype's public/data directory")
    args = parser.parse_args()

    binary = _booksim(args.booksim)
    root = args.out
    root.mkdir(parents=True, exist_ok=True)
    for arm in ARMS:
        _arm_dir(root, arm)
    native_model = prepare_model(REPO, root, binary) if args.native_power else None

    print(f"BookSim: {binary}")
    print(f"Arms: {len(ARMS)}  Rates: {len(args.rates)}  "
          f"Runs: {len(ARMS) * len(args.rates)}")
    print(f"Run directory: {root}")

    tasks = [(arm, rate) for arm in ARMS for rate in args.rates]
    with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
        futures = [pool.submit(_run_one, binary, root, arm, rate, args.timeout, native_model)
                   for arm, rate in tasks]
        rows = [future.result() for future in futures]
    rows.sort(key=lambda r: (r["topology"], r["injection_rate"]))

    sweep_path = root / "topology_sweep.json"
    sweep_path.write_text(json.dumps(rows, indent=2) + "\n")

    points = _pareto_rows(rows)
    pareto_path = root / "pareto_2d.csv"
    _write_csv(pareto_path, points)
    _summary(root / "summary.md", rows, points, args.rates, binary)

    ok = sum(1 for r in rows if r["status"] == "ok")
    fronts = [p["topology"] for p in points if p["pareto_front"]]
    print(f"\n{ok}/{len(rows)} points with numeric latency")
    print(f"{len(fronts)} on the legacy zero-load hops-proxy front: {', '.join(fronts)}")
    native = [r for r in rows if r['native_model']['status'] == 'AVAILABLE']
    print(f"Native model: {len(native)} observations across {len({r['topology'] for r in native})} arms; not silicon calibrated")
    print(f"  {sweep_path}")
    print(f"  {pareto_path}")
    print(f"  {root / 'summary.md'}")

    if args.copy_to_prototype:
        target = PROTOTYPE_DATA
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sweep_path, target / "topology_sweep.json")
        shutil.copyfile(pareto_path, target / "pareto_2d.csv")
        print(f"  copied to {target}")

    # A saturated arm is a real observation ("unstable" means BookSim
    # drained a network that never reached steady state), not a failed run.
    # Only hard failures should make the sweep exit nonzero.
    hard = {"no_output", "timeout", "unknown_topology",
            "skipped_node_mismatch"}
    failures = [r for r in rows if r["status"] in hard]
    if failures:
        print(f"\n{len(failures)} hard failures:", file=sys.stderr)
        for row in failures:
            print(f"  {row['topology']} @ {row['injection_rate']:g}: "
                  f"{row['status']} ({row['log']})", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
