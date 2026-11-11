#!/usr/bin/env python3
"""PA-13 — Buffer/VC energy design-space exploration.

Mini Pareto sweep over buffer and virtual-channel sizing:
  num_vcs    ∈ {2, 4, 8}
  vc_buf_size ∈ {2, 4, 8, 16}

For each combination, either:
  (a) runs Booksim on a reference topology (mesh4x4) if available, or
  (b) estimates latency/power from the existing sweep data using
      analytical scaling relationships.

Outputs a mini-Pareto chart data CSV identifying the "knee" —
the point of diminishing returns where additional buffer resources
yield negligible latency improvement but significant power increase.

Usage
-----
    python3 scripts/buffer_sweep.py                     # analytical mode
    python3 scripts/buffer_sweep.py --run               # live Booksim sweep
    python3 scripts/buffer_sweep.py --selfcheck         # regression tests
"""

import argparse
import csv
import json
import math
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

HERE    = Path(__file__).parent
TRACK   = HERE.parent
CONFIGS = TRACK / "configs"
RESULTS = TRACK / "results"
OUTPUT  = TRACK / "output"

# Design space
NUM_VCS_OPTIONS     = [2, 4, 8]
VC_BUF_SIZE_OPTIONS = [2, 4, 8, 16]

# Reference topology for the sweep
REF_TOPOLOGY = "mesh4x4"
REF_CFG      = CONFIGS / "mesh4x4.cfg"

# Reference injection rate (low load — cleaner signal)
REF_RATE = 0.02

# Baseline values from actual sweep data (mesh4x4 @ 0.01, num_vcs=4, vc_buf_size=8)
BASELINE = {
    "num_vcs": 4,
    "vc_buf_size": 8,
    "latency": 23.905,      # from topology_sweep.json
    "total_power": 6.480,   # from topology_sweep.json
    "total_area": 0.331,    # from topology_sweep.json
}


# ---------------------------------------------------------------------------
# Analytical model (when Booksim is unavailable)
# ---------------------------------------------------------------------------

def estimate_latency(num_vcs: int, vc_buf_size: int) -> float:
    """Estimate latency for a given VC/buffer configuration.

    Scaling model (from NoC literature):
    - More VCs → lower HOL blocking → lower latency (diminishing returns)
    - Larger buffers → fewer credit stalls → lower latency (diminishing returns)
    - Below a threshold, latency rises steeply (insufficient buffering)

    Returns estimated latency in cycles.
    """
    base_lat = BASELINE["latency"]

    # VC scaling: log-based diminishing returns vs baseline
    vc_ratio = math.log2(num_vcs) / math.log2(BASELINE["num_vcs"])
    vc_factor = 1.0 / (0.5 + 0.5 * vc_ratio)  # more VCs → lower factor

    # Buffer scaling: sqrt-based diminishing returns
    buf_ratio = vc_buf_size / BASELINE["vc_buf_size"]
    buf_factor = 1.0 / (0.5 + 0.5 * math.sqrt(buf_ratio))

    # Very small configs get a penalty (credit stalls)
    if vc_buf_size <= 2:
        buf_factor *= 1.3  # 30% latency penalty for tiny buffers
    if num_vcs <= 2 and vc_buf_size <= 2:
        buf_factor *= 1.2  # compounding penalty

    return round(base_lat * vc_factor * buf_factor, 3)


def estimate_power(num_vcs: int, vc_buf_size: int) -> float:
    """Estimate power for a given VC/buffer configuration.

    Power scales roughly linearly with total buffer capacity:
      total_bufs = num_vcs × vc_buf_size (per port)
    Plus a fixed router-logic overhead.
    """
    base_power = BASELINE["total_power"]
    base_bufs = BASELINE["num_vcs"] * BASELINE["vc_buf_size"]
    new_bufs = num_vcs * vc_buf_size

    # Buffer power ~ 60% of total; router logic ~ 40% fixed
    buf_fraction = 0.6
    fixed_fraction = 1.0 - buf_fraction

    power = base_power * (fixed_fraction + buf_fraction * (new_bufs / base_bufs))
    return round(power, 3)


def estimate_area(num_vcs: int, vc_buf_size: int) -> float:
    """Estimate area for a given VC/buffer configuration.

    Area scales similarly to power — dominated by buffer SRAM.
    """
    base_area = BASELINE["total_area"]
    base_bufs = BASELINE["num_vcs"] * BASELINE["vc_buf_size"]
    new_bufs = num_vcs * vc_buf_size

    buf_fraction = 0.7  # buffers are larger fraction of area
    fixed_fraction = 1.0 - buf_fraction

    area = base_area * (fixed_fraction + buf_fraction * (new_bufs / base_bufs))
    return round(area, 4)


def analytical_sweep() -> list[dict]:
    """Run analytical sweep over the design space."""
    rows = []
    for nv in NUM_VCS_OPTIONS:
        for bs in VC_BUF_SIZE_OPTIONS:
            lat = estimate_latency(nv, bs)
            pwr = estimate_power(nv, bs)
            area = estimate_area(nv, bs)
            total_bufs = nv * bs
            rows.append({
                "topology":      REF_TOPOLOGY,
                "num_vcs":       nv,
                "vc_buf_size":   bs,
                "total_bufs":    total_bufs,
                "latency":       lat,
                "total_power":   pwr,
                "total_area":    area,
                "power_per_buf": round(pwr / total_bufs, 4),
                "source":        "analytical",
            })
    return rows


# ---------------------------------------------------------------------------
# Live Booksim sweep (when booksim binary is available)
# ---------------------------------------------------------------------------

def booksim_sweep(cfg_path: Path, rate: float = REF_RATE) -> list[dict]:
    """Run actual Booksim sweep over the VC/buffer design space."""
    booksim = os.environ.get("BOOKSIM_BIN", "booksim")
    tech_file = os.environ.get(
        "TECH_FILE",
        "/opt/booksim2/src/power/techfile.txt"
    )
    topology = cfg_path.stem

    rows = []
    for nv in NUM_VCS_OPTIONS:
        for bs in VC_BUF_SIZE_OPTIONS:
            cmd = [
                booksim, str(cfg_path),
                f"injection_rate={rate}",
                f"num_vcs={nv}",
                f"vc_buf_size={bs}",
                "sim_power=1",
                f"tech_file={tech_file}",
            ]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                lat = pwr = area = None
                for line in result.stdout.splitlines():
                    if "Packet latency average" in line:
                        for p in line.split():
                            try: lat = float(p); break
                            except ValueError: pass
                    elif "Total Power:" in line:
                        for p in line.split():
                            try: pwr = float(p); break
                            except ValueError: pass
                    elif "Total Area:" in line:
                        for p in line.split():
                            try: area = float(p); break
                            except ValueError: pass
            except (FileNotFoundError, subprocess.TimeoutExpired):
                lat = pwr = area = None

            total_bufs = nv * bs
            rows.append({
                "topology":      REF_TOPOLOGY,
                "num_vcs":       nv,
                "vc_buf_size":   bs,
                "total_bufs":    total_bufs,
                "latency":       lat,
                "total_power":   pwr,
                "total_area":    area,
                "power_per_buf": round(pwr / total_bufs, 4) if pwr else None,
                "source":        "booksim",
            })
            status = f"lat={lat:.2f}" if lat else "FAILED"
            print(f"  vcs={nv} buf={bs}  → {status}")

    return rows


# ---------------------------------------------------------------------------
# Knee detection
# ---------------------------------------------------------------------------

def find_knee(rows: list[dict]) -> Optional[dict]:
    """Find the "knee" point — best latency/power tradeoff.

    The knee is the configuration where:
      - latency improvement per additional buffer resource
        drops below a threshold (diminishing returns)
      - Specifically: the point with the best latency/(power × area) ratio
    """
    valid = [r for r in rows if r["latency"] is not None and r["total_power"] is not None]
    if not valid:
        return None

    # Score: lower is better (latency × power — joint minimization)
    for r in valid:
        r["score"] = r["latency"] * r["total_power"]

    return min(valid, key=lambda r: r["score"])


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _selfcheck():
    """Regression tests."""
    # Analytical estimates should be monotonic in expected ways
    rows = analytical_sweep()
    assert len(rows) == len(NUM_VCS_OPTIONS) * len(VC_BUF_SIZE_OPTIONS), \
        f"expected {len(NUM_VCS_OPTIONS) * len(VC_BUF_SIZE_OPTIONS)} rows, got {len(rows)}"

    # All rows should have values
    for r in rows:
        assert r["latency"] is not None
        assert r["total_power"] is not None
        assert r["total_area"] is not None
        assert r["total_bufs"] == r["num_vcs"] * r["vc_buf_size"]

    # More VCs at same buf size → lower or equal latency
    for bs in VC_BUF_SIZE_OPTIONS:
        lats = [r["latency"] for r in rows if r["vc_buf_size"] == bs]
        # Should be generally non-increasing (more VCs → less HOL blocking)
        assert lats[0] >= lats[-1], \
            f"expected latency to decrease with more VCs at buf={bs}, got {lats}"

    # More bufs at same VCs → higher power
    for nv in NUM_VCS_OPTIONS:
        pwrs = [r["total_power"] for r in rows if r["num_vcs"] == nv]
        assert pwrs[0] <= pwrs[-1], \
            f"expected power to increase with larger bufs at vcs={nv}, got {pwrs}"

    # Knee detection should work
    knee = find_knee(rows)
    assert knee is not None, "knee detection failed"
    assert "score" in knee

    # Smallest config (vcs=2, buf=2) should have worst latency
    smallest = [r for r in rows if r["num_vcs"] == 2 and r["vc_buf_size"] == 2][0]
    largest = [r for r in rows if r["num_vcs"] == 8 and r["vc_buf_size"] == 16][0]
    assert smallest["latency"] >= largest["latency"], \
        "smallest config should have highest latency"
    assert smallest["total_power"] <= largest["total_power"], \
        "smallest config should have lowest power"

    print("selfcheck OK")


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--run", action="store_true",
                    help="run live Booksim sweep (default: analytical model)")
    ap.add_argument("--cfg", default=None,
                    help=f"Booksim config for live sweep (default: {REF_CFG})")
    ap.add_argument("--rate", type=float, default=REF_RATE,
                    help=f"injection rate for sweep (default: {REF_RATE})")
    ap.add_argument("--out", default=None,
                    help="output CSV path (default: output/buffer_pareto.csv)")
    ap.add_argument("--selfcheck", action="store_true")
    args = ap.parse_args()

    if args.selfcheck:
        _selfcheck()
        return

    if args.run:
        cfg = Path(args.cfg) if args.cfg else REF_CFG
        print(f"\n=== PA-13: Buffer/VC Sweep (Booksim, {cfg.stem}) ===\n")
        rows = booksim_sweep(cfg, args.rate)
    else:
        print(f"\n=== PA-13: Buffer/VC Sweep (analytical model, {REF_TOPOLOGY}) ===\n")
        rows = analytical_sweep()

    # Print table
    print(f"\n  {'topology':<12s} {'vcs':>4s} {'buf':>4s} {'total':>5s} "
        f"{'latency':>8s} {'power':>8s} {'area':>7s} {'pwr/buf':>8s}")
    print(f"  {'-'*12} {'-'*4} {'-'*4} {'-'*5} "
        f"{'-'*8} {'-'*8} {'-'*7} {'-'*8}")
    for r in sorted(rows, key=lambda x: x["total_bufs"]):
        lat_s = f"{r['latency']:.2f}" if r["latency"] else "—"
        pwr_s = f"{r['total_power']:.3f}" if r["total_power"] else "—"
        area_s = f"{r['total_area']:.4f}" if r["total_area"] else "—"
        ppb_s = f"{r['power_per_buf']:.4f}" if r["power_per_buf"] else "—"
        print(f"  {r['topology']:<12s} "
      f"{r['num_vcs']:>4d} {r['vc_buf_size']:>4d} "
      f"{r['total_bufs']:>5d} {lat_s:>8s} {pwr_s:>8s} "
      f"{area_s:>7s} {ppb_s:>8s}")

    # Knee detection
    knee = find_knee(rows)
    if knee:
        print(f"\n  ★ Knee point: vcs={knee['num_vcs']}, buf={knee['vc_buf_size']} "
              f"(total_bufs={knee['total_bufs']})")
        print(f"    latency={knee['latency']:.2f}, power={knee['total_power']:.3f}, "
              f"score={knee['score']:.2f}")
        print(f"    → Best latency×power tradeoff — diminishing returns beyond this point")

    # Write CSV
    out = Path(args.out) if args.out else OUTPUT / "buffer_pareto.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="") as f:
        keys = list(rows[0].keys())
        w = csv.DictWriter(f, fieldnames=keys)
        w.writeheader()
        w.writerows(rows)
    print(f"\n  → {out}  ({len(rows)} configurations)")


if __name__ == "__main__":
    main()
