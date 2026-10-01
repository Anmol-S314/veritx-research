#!/usr/bin/env python3
"""
srota_m3.py — measurable claim M3 (SSM-UARCH-ROUTE-001 rev 0.3 section 16.4).

M3 is "slack-arbitration critical-class latency vs RR/age baselines", and
section 16.4 names three ingredients:

  1. a 2-bit slack tag in the simulator's packet format matching section 8.2
     -> Flit::slack, carried from the trace (see SROTA-NEXT-STEPS.md)
  2. the three-level arbiter as an allocator variant replacing the default
     islip/RR allocator
     -> sw_allocator = srota_arb (allocators/srota_arb.cpp)
  3. a baseline run using the default RR/age allocator on the identical
     traffic
     -> the islip arms below, same trace, same fabric, same seed

The claim is about the CRITICAL CLASS, so the headline is slack-0 tail
latency. Aggregate latency is reported alongside because an arbiter that
improves the critical class by wrecking everything else has not earned
anything, and the bulk-class column is what shows the price.

Ablations run each level alone. "The arbiter helped" is not a result if it
cannot say which of the three levels did the work.

Usage:
    python3 srota_m3.py --config <cfg> --trace <trace.csv> [--out results.json]
"""

import argparse
import csv
import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
BOOKSIM = REPO / "third_party" / "booksim2" / "src" / "booksim"

# name -> config overrides. Every arm sees the identical trace and seed.
ARMS = [
    ("islip / RR", {
        "sw_allocator": "islip", "priority": "none"}),
    ("islip / age", {
        "sw_allocator": "islip", "priority": "age"}),
    ("srota_arb (all levels)", {
        "sw_allocator": "srota_arb", "priority": "none"}),
    ("srota_arb L0 golden only", {
        "sw_allocator": "srota_arb", "priority": "none",
        "srota_arb_l1_slack": "0", "srota_arb_l2_stc": "0"}),
    ("srota_arb L1 slack only", {
        "sw_allocator": "srota_arb", "priority": "none",
        "srota_arb_l0_golden": "0", "srota_arb_l2_stc": "0"}),
    ("srota_arb L2 stc only", {
        "sw_allocator": "srota_arb", "priority": "none",
        "srota_arb_l0_golden": "0", "srota_arb_l1_slack": "0"}),
]


def derive(src, dst, trace, log, seed, overrides):
    owned = set(overrides) | {"trace_file", "trace_packet_log", "seed", "sim_type"}
    kept = [ln for ln in Path(src).read_text().splitlines()
            if ln.split("=")[0].strip() not in owned]
    kept.append("")
    kept.append("// --- injected by srota_m3.py ---")
    kept.append("sim_type = trace;")
    kept.append(f"trace_file = {trace};")
    kept.append(f"trace_packet_log = {log};")
    kept.append(f"seed = {seed};")
    for k, v in overrides.items():
        kept.append(f"{k} = {v};")
    Path(dst).write_text("\n".join(kept) + "\n")


def pct(vals, p):
    if not vals:
        return None
    s = sorted(vals)
    i = min(len(s) - 1, max(0, int(round(p / 100.0 * len(s) + 0.5)) - 1))
    return s[i]


def summarize(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    if not rows:
        return None
    per = {}
    allv = []
    for r in rows:
        lat = int(r["total_latency"])
        allv.append(lat)
        per.setdefault(int(r.get("slack", 0)), []).append(lat)
    out = {"n": len(rows),
           "horizon": max(int(r["arrival_time"]) for r in rows),
           "all": {"n": len(allv), "p50": pct(allv, 50),
                   "p95": pct(allv, 95), "p99": pct(allv, 99),
                   "mean": round(sum(allv) / len(allv), 2)}}
    out["by_slack"] = {
        s: {"n": len(v), "p50": pct(v, 50), "p95": pct(v, 95),
            "p99": pct(v, 99), "mean": round(sum(v) / len(v), 2)}
        for s, v in sorted(per.items())}
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--config", required=True)
    ap.add_argument("--trace", required=True)
    ap.add_argument("--workdir", default=None)
    ap.add_argument("--seed", default="0")
    ap.add_argument("--out", help="write results as JSON here")
    args = ap.parse_args()

    if not BOOKSIM.exists():
        sys.exit(f"booksim not built: {BOOKSIM}")

    import tempfile
    wd = Path(args.workdir) if args.workdir else Path(tempfile.mkdtemp(prefix="srota_m3_"))
    wd.mkdir(parents=True, exist_ok=True)

    results = {}
    for i, (name, ov) in enumerate(ARMS):
        cfg = wd / f"arm{i}.config"
        log = wd / f"arm{i}_packets.csv"
        out = wd / f"arm{i}.log"
        derive(args.config, cfg, args.trace, log, args.seed, ov)
        with open(out, "w") as fh:
            rc = subprocess.call([str(BOOKSIM), str(cfg)], stdout=fh,
                                 stderr=subprocess.STDOUT)
        if rc != 0:
            print(f"{name}: booksim exited {rc}, see {out}", file=sys.stderr)
            results[name] = None
            continue
        results[name] = summarize(log)

    # ---- report -------------------------------------------------------
    classes = sorted({s for r in results.values() if r
                      for s in r["by_slack"]})
    label = {0: "critical", 1: "low-slack", 2: "bulk", 3: "background"}

    w = max(len(n) for n in results)
    print()
    print("M3 — critical-class latency vs RR/age baselines")
    print(f"trace: {args.trace}")
    print()
    hdr = f"{'arm'.ljust(w)}  " + "  ".join(
        f"slack {s} ({label.get(s, '?')}) p50/p95/p99".ljust(30) for s in classes)
    print(hdr)
    print("-" * len(hdr))
    for name, r in results.items():
        if not r:
            print(f"{name.ljust(w)}  FAILED")
            continue
        cells = []
        for s in classes:
            d = r["by_slack"].get(s)
            cells.append((f"{d['p50']}/{d['p95']}/{d['p99']}" if d else "-").ljust(30))
        print(f"{name.ljust(w)}  " + "  ".join(cells))

    print()
    print(f"{'arm'.ljust(w)}  {'all p50/p95/p99'.ljust(20)}  {'mean'.ljust(8)}  horizon")
    print("-" * (w + 44))
    for name, r in results.items():
        if not r:
            continue
        a = r["all"]
        print(f"{name.ljust(w)}  "
              f"{f'{a[chr(112)+chr(53)+chr(48)]}/{a[chr(112)+chr(57)+chr(53)]}/{a[chr(112)+chr(57)+chr(57)]}'.ljust(20)}  "
              f"{str(a['mean']).ljust(8)}  {r['horizon']}")

    base = results.get("islip / RR")
    arb = results.get("srota_arb (all levels)")
    if base and arb and 0 in base["by_slack"] and 0 in arb["by_slack"]:
        b, a = base["by_slack"][0], arb["by_slack"][0]
        print()
        for k in ("p50", "p95", "p99"):
            if b[k]:
                d = 100.0 * (a[k] - b[k]) / b[k]
                print(f"  critical-class {k}: {b[k]} -> {a[k]}  ({d:+.1f}%)")

    if args.out:
        Path(args.out).write_text(json.dumps(results, indent=2))
        print(f"\nwrote {args.out}")
    if args.workdir:
        print(f"intermediates in {wd}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
