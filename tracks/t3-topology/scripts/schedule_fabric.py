#!/usr/bin/env python3
"""Both schedule primitives on one fabric: row-multicast + column-reduce. (T3)

mcast_flitfork.py validated the FIRST primitive (row-multicast, the g-fold win). SCHEDULE.md
has a SECOND: when a KV head's context is too big for one core's L1, split it down a column
and combine the partial attentions with an online-softmax **column-reduce**. This validates
that second primitive and, more importantly, that BOTH run on the same mesh at once without
the fabric binding -- the "does the whole schedule fit on the NoC" question.

KEY MODELLING POINT (why reduce needs no router surgery, unlike multicast). The online-
softmax COMBINE is in-core compute, not a network operation. So a column-reduce is just each
core relaying its partial ONE hop up the column to its parent (toward the root at row 0); the
parent combines locally and relays its own. The network only moves partials -- ordinary
1-hop unicasts, no fork, no merge. Link load = one partial per column link. (The pipeline
dependency "parent waits for child" is a latency effect, not a link-load one, so this models
the saturation question exactly; it does not model the reduce's end-to-end latency.)

CONSERVATISM, STATED. We inject reduce partials at the SAME rate as the KV stream. Physically
the reduce fires ONCE per decode step while the KV streams many tiles, so equal-rate wildly
OVER-represents the reduce -- the combined saturation knee here is a pessimistic floor, not
the operating point. The load-bearing check is the fabric at the schedule's actual DRAM-bound
load (inj ~0.10 = 16 GB/s), where all three regimes are stable with room to spare.

RUN IT (inside the tools image; self-builds the patched booksim if the image predates it):
    podman run --rm -v "$PWD:/repo" -w /repo \\
        internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest \\
        python3 tracks/t3-topology/scripts/schedule_fabric.py --run

    python3 scripts/schedule_fabric.py --selfcheck   # geometry only, no booksim
"""
import re
import subprocess
import sys
from pathlib import Path

K = 8                                   # 8x8 mesh
HERE = Path(__file__).resolve()
BUILD = HERE.parents[1] / "booksim-ext" / "build.sh"
OUT = Path("/tmp/schedule_fabric")
OP_LOAD = 0.10                          # schedule's DRAM-bound load (16 GB/s), the anchor

# (mcast_naive, reduce_col): the three regimes we compare at the operating load.
REGIMES = [("multicast", 0, 0), ("reduce", 2, 1), ("combined", 0, 1)]


def cfg(naive, reduce_col, inj):
    return f"""topology = mesh;
k = {K};
n = 2;
routing_function = dim_order;
num_vcs = 8;
vc_buf_size = 8;
traffic = uniform;
mcast_k = {K};
mcast_naive = {naive};
reduce_col = {reduce_col};
injection_rate = {inj};
packet_size = 1;
output_buffer_size = -1;
sim_type = latency;
sample_period = 2000;
warmup_periods = 2;
max_samples = 5;
"""


def _num(line):
    m = re.search(r"=\s*([0-9.eE+-]+)", line)
    return float(m.group(1)) if m else None


def run(naive, reduce_col, inj):
    """Return (injected, accepted, latency, saturated)."""
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"n{naive}_r{reduce_col}_{inj}.cfg"
    p.write_text(cfg(naive, reduce_col, inj))
    r = subprocess.run(["booksim", str(p)], capture_output=True, text=True, timeout=240)
    inj_r = acc = lat = None
    sat = ("unstable" in r.stdout) or ("Aborting" in r.stdout)
    for line in r.stdout.splitlines():
        if "Injected packet rate average" in line:
            inj_r = _num(line)
        elif "Accepted packet rate average" in line:
            acc = _num(line)
        elif "Packet latency average" in line:
            lat = _num(line)
    return inj_r, acc, lat, sat


def have_patched():
    try:
        i, a, _, _ = run(0, 0, 0.02)
    except Exception:
        return False
    return bool(i and a and a / i > 1.5)


def ensure_booksim():
    if have_patched():
        return
    print("  patched booksim not on PATH -- building via booksim-ext/build.sh ...")
    r = subprocess.run(["bash", str(BUILD)], capture_output=True, text=True)
    if r.returncode != 0 or not have_patched():
        sys.exit("  ERROR: could not build/verify the patched booksim; run inside the tools "
                 "image (booksim-ext/README.md).\n" + r.stdout[-1200:] + r.stderr[-1200:])


def main():
    ensure_booksim()
    print(f"\n  Full schedule on one fabric -- {K}x{K} mesh: row-multicast + column-reduce\n")

    # --- gate 1: the reduce is a pure 1-hop relay (no fork) -> accepted == injected ---
    i, a, lat, sat = run(2, 1, 0.10)          # reduce-only at the operating load
    ratio = a / i
    print(f"  GATE  column-reduce is a 1-hop relay -> accepted/injected = {ratio:.2f} "
          f"(expect 1.0); {'PASS' if abs(ratio - 1) < 0.1 else 'FAIL'}")
    assert abs(ratio - 1) < 0.1, ratio

    # --- gate 2: reduce alone is cheap -- stable well past the operating load ---
    _, _, lat_hi, sat_hi = run(2, 1, 0.60)
    print(f"  GATE  reduce alone stays cheap at inj 0.60 (lat {lat_hi:.0f}, "
          f"{'stable' if not sat_hi else 'SAT'}); {'PASS' if not sat_hi else 'FAIL'}")
    assert not sat_hi, "reduce alone should not saturate at inj 0.60 (it is 1-hop)"

    # --- the load-bearing table: both primitives at the schedule's operating load ---
    print(f"\n  At the schedule's DRAM-bound load (inj {OP_LOAD} = 16 GB/s), latency + state:")
    print(f"  {'regime':>10} | {'latency':>8} | {'state':>6}")
    op = {}
    for name, naive, rc in REGIMES:
        _, _, lat, sat = run(naive, rc, OP_LOAD)
        op[name] = (lat, sat)
        print(f"  {name:>10} | {lat:>8.1f} | {'ok' if not sat else 'SAT':>6}")
    for name in ("multicast", "reduce", "combined"):
        assert not op[name][1], f"{name} should be stable at the operating load"

    # --- headroom: combined still stable at 2x the operating load (robust; the exact
    #     equal-rate saturation knee is near-threshold noisy and not load-bearing) ---
    _, _, lat_2x, sat_2x = run(0, 1, 2 * OP_LOAD)
    print(f"\n  Both primitives are STABLE with headroom at the operating load "
          f"(combined lat {op['combined'][0]:.0f}), and still stable at 2x it "
          f"(inj {2 * OP_LOAD}, lat {lat_2x:.0f}, {'ok' if not sat_2x else 'SAT'}).")
    print(f"  Column-reduce is a cheap 1-hop relay and coexists with the multicast on the")
    print(f"  same mesh. The equal-rate combined does eventually saturate (it carries more")
    print(f"  total traffic than multicast alone) -- but that regime injects reduce as fast")
    print(f"  as the KV stream, vs its real once-per-step, so it OVER-drives the reduce and")
    print(f"  is a conservative floor, well above the operating point.")
    assert not sat_2x, "combined should still be stable at 2x the operating load"
    print(f"\n  selfcheck OK -- reduce relay exact (ratio {ratio:.2f}); both primitives fit "
          f"the fabric at load, with headroom")


def _selfcheck():
    # geometry: column-reduce is K independent columns, each relaying K-1 partials up to
    # the root at row 0; every hop is nearest-neighbour, so link load is one partial per link.
    senders = 0
    for col in range(K):
        for row in range(1, K):                 # rows 1..K-1 each relay to row-1
            parent = (row - 1) * K + col
            child = row * K + col
            assert parent == child - K, "parent must be the one-hop column neighbour (row-1)"
            senders += 1
    assert senders == K * (K - 1), senders       # 8x8 -> 56 relays, root row (8 cores) idle
    print(f"selfcheck OK -- {K} columns x {K - 1} relays = {K * (K - 1)} one-hop partials up "
          f"to the row-0 roots; combine is in-core, so the NoC only relays (see --run)")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
