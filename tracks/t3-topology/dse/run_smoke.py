#!/usr/bin/env python3
"""Minimal DSE smoke test — 6 BookSim2 points, should run in <30s.

Usage: python tracks/t3-topology/dse/run_smoke.py
"""
import itertools, os, re, subprocess, sys, time
from dataclasses import dataclass
from pathlib import Path

BOOKSIM = Path(__file__).resolve().parent.parent.parent.parent / "third_party/booksim2/src/booksim"


@dataclass(frozen=True)
class Point:
    topology: str
    vcs: int
    injection_rate: float
    def slug(self): return f"{self.topology}_vcs{self.vcs}_ir{self.injection_rate}"


@dataclass
class Result:
    point: Point
    latency: float = None
    hops: float = None
    error: str = None
    @property
    def ok(self): return self.latency is not None and self.error is None


def gen_cfg(p: Point) -> str:
    routing = {"mesh": "dor", "torus": "valiant"}.get(p.topology, "dor")
    return f"""\
topology = {p.topology};
k = 8;
n = 2;
num_vcs = {p.vcs};
vc_buf_size = 8;
routing_function = {routing};
traffic = uniform;
sim_type = latency;
injection_rate = {p.injection_rate};
seed = 42;
"""


def run_one(p: Point) -> Result:
    rundir = Path(__file__).parent / "test_run"
    rundir.mkdir(exist_ok=True)
    cfg_path = rundir / f"{p.slug()}.cfg"
    cfg_path.write_text(gen_cfg(p))
    try:
        r = subprocess.run([str(BOOKSIM), str(cfg_path)],
                           capture_output=True, text=True, timeout=60, cwd=str(rundir))
    except subprocess.TimeoutExpired:
        return Result(p, error="timeout")
    if r.returncode != 0:
        # check if output has valid data despite non-zero exit (known BookSim2 behavior)
        has_latency = any("Packet latency average" in l for l in r.stdout.splitlines())
        if not has_latency:
            return Result(p, error=f"exit {r.returncode}: {(r.stderr or r.stdout)[-200:]}")
    lat = hops = None
    for line in r.stdout.splitlines():
        m = re.search(r"Packet latency average\s*=\s*([0-9.]+)", line)
        if m: lat = float(m.group(1))
        m = re.search(r"Hops average\s*=\s*([0-9.]+)", line)
        if m: hops = float(m.group(1))
    if lat is None:
        return Result(p, error=f"no latency: {r.stdout[-200:]}")
    return Result(p, latency=lat, hops=hops)


def main():
    points = [
        Point("mesh", vcs, ir)
        for vcs in [2, 4, 8]
        for ir in [0.02, 0.04, 0.08, 0.16, 0.32]
    ]

    print(f"DSE smoke: {len(points)} points | booksim={BOOKSIM}")
    if not BOOKSIM.exists():
        sys.exit(f"ERROR: booksim not found at {BOOKSIM}")

    t0 = time.time()
    results = []
    for i, p in enumerate(points, 1):
        r = run_one(p)
        tag = f"lat={r.latency:.1f}" if r.ok else f"ERR: {r.error}"
        print(f"  [{i}/{len(points)}] {p.slug():<20} {tag}")
        results.append(r)

    ok = sorted([r for r in results if r.ok], key=lambda r: r.latency)
    print(f"\n{'Rank':<6}{'Config':<22}{'Latency':<12}{'Hops':<8}")
    print("-" * 48)
    for i, r in enumerate(ok, 1):
        hops = f"{r.hops:.1f}" if r.hops is not None else "-"
        print(f"{i:<6}{r.point.slug():<22}{r.latency:<12.1f}{hops:<8}")

    failed = [r for r in results if not r.ok]
    if failed:
        print(f"\n{len(failed)} failed:")
        for r in failed:
            print(f"  {r.point.slug()}: {r.error}")

    print(f"\n{time.time()-t0:.1f}s total for {len(points)} points")


if __name__ == "__main__":
    main()
