#!/usr/bin/env python3
"""Cycle-accurate shared-prefix broadcast: 1 inject -> B-1 deliveries, on a real mesh. (T3 ext)

prefix_multicast.py showed ANALYTICALLY that broadcasting a shared prefix to B concurrent
requests beats the g-fold GQA multicast once the shared fraction clears ~(g-1)/g -- a bigger
win on the redundancy that agentic serving is exploding. This is the cycle-accurate half: the
same flit-fork primitive as mcast_flitfork.py, extended from a 1-D ROW broadcast (g cores) to
a full-mesh broadcast (all B cores) from ONE source.

MECHANISM (reuses multicast.patch's eject-fork UNCHANGED). One source (node 0) injects a single
`mcast` stream that follows a HAMILTONIAN "snake" route (routing_function=snake, snakeroute.cpp)
visiting every node; at each node the router forks the pre-registered copy destined there to the
eject port. So one injection delivers to all N-1 other cores. The naive baseline (bcast_all=2)
is N-1 unicasts from node 0 -- node 0's egress is the bottleneck, exactly as the shared prefix's
single DRAM endpoint would be.

WHAT IT SHOWS, and the HONEST caveat:
  - FORK/BROADCAST CORRECTNESS: one injection -> exactly N-1 deliveries (the known-answer gate).
  - THE B-FOLD WIN: the broadcast keeps every link at one stream (rate r), stable to high
    injection; the naive baseline swamps the source's egress and saturates early.
  - CONSERVATIVE ON LATENCY, faithful on throughput: a snake PATH is longer than a dimension-
    ordered broadcast TREE (63 hops vs ~14 to the far node), so its per-delivery LATENCY is an
    over-estimate. But each link still carries exactly one stream at rate r, so the SATURATION /
    throughput result (the load-bearing one -- latency is hidden by pipelining in decode) is
    the same a tree would give. The tree is the natural refinement; this is the safe first pass,
    reusing the validated eject-fork with zero new link-traversing router-spawned flits.

RUN IT (tools image; self-builds/patches booksim the first time):
    podman run --rm -v "$PWD:/repo" -w /repo \\
        internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest \\
        python3 tracks/t3-topology/scripts/prefix_broadcast_flitfork.py --run

    python3 scripts/prefix_broadcast_flitfork.py --selfcheck   # geometry only, no booksim
"""
import re
import subprocess
import sys
from pathlib import Path

K = 8                                # 8x8 mesh
N = K * K                            # 64 nodes
B_MINUS_1 = N - 1                    # deliveries per broadcast (source excluded) = 63
HERE = Path(__file__).resolve()
BUILD = HERE.parents[1] / "booksim-ext" / "build.sh"
OUT = Path("/tmp/prefix_bcast")
SWEEP = [0.01, 0.02, 0.03, 0.05, 0.10, 0.20, 0.40, 0.70, 1.00]


def snake_end(k):
    """Terminal node of the boustrophedon snake on a k x k mesh (matches snakeroute.cpp)."""
    return (k - 1) * k if (k - 1) & 1 else k * k - 1


def cfg(mode, inj):
    return f"""topology = mesh;
k = {K};
n = 2;
routing_function = snake;
num_vcs = 8;
vc_buf_size = 8;
traffic = uniform;
bcast_all = {mode};
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


def run_booksim(mode, inj):
    """Return (injected_rate, accepted_rate, latency, saturated)."""
    OUT.mkdir(parents=True, exist_ok=True)
    p = OUT / f"b{mode}_{inj}.cfg"
    p.write_text(cfg(mode, inj))
    r = subprocess.run(["booksim", str(p)], capture_output=True, text=True, timeout=300)
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


def have_bcast_booksim():
    """True iff the booksim on PATH does the snake broadcast (accepted/injected ~ N-1)."""
    try:
        inj_r, acc, _, _ = run_booksim(1, 0.01)
    except Exception:
        return False
    return bool(inj_r and acc and acc / inj_r > N / 2)


def ensure_booksim():
    if have_bcast_booksim():
        return
    print("  booksim without snake-broadcast on PATH -- building via booksim-ext/build.sh ...")
    r = subprocess.run(["bash", str(BUILD)], capture_output=True, text=True)
    if r.returncode != 0 or not have_bcast_booksim():
        sys.exit("  ERROR: could not build/verify the snake-broadcast booksim.\n"
                 "  Run inside the tools image; see booksim-ext/README.md.\n"
                 + r.stdout[-1500:] + r.stderr[-1500:])


def main():
    ensure_booksim()
    print(f"\n  Shared-prefix broadcast vs naive re-fetch -- {K}x{K} mesh, one source -> all {B_MINUS_1}\n")

    # --- validation gate: one broadcast injection must deliver to exactly N-1 = 63 cores ---
    inj_r, acc, _, _ = run_booksim(1, 0.01)
    ratio = acc / inj_r
    ok = abs(ratio - B_MINUS_1) < 2.0
    print(f"  GATE  one broadcast injection -> {ratio:.1f} deliveries "
          f"(expect {B_MINUS_1}); {'PASS' if ok else 'FAIL'}")
    assert ok, (ratio, B_MINUS_1)

    # --- the sweep: useful-delivery rate (accepted) and saturation, both schemes ---
    print(f"\n  {'inj':>5} | {'BROADCAST (snake)':>26} | {'NAIVE re-fetch':>26}")
    print(f"  {'':>5} | {'acc/cyc  lat  state':>26} | {'acc/cyc  lat  state':>26}")
    bc_ceiling = 0.0     # broadcast: max STABLE delivery
    nv_ceiling = 0.0     # naive: max delivery incl. saturated plateau = its ceiling
    for inj in SWEEP:
        cells = {}
        for mode in (1, 2):
            _, a, lat, sat = run_booksim(mode, inj)
            cells[mode] = f"{(a or 0):.3f}   {(lat or 0):5.0f}   {'SAT' if sat else 'ok':>3}"
            if a:
                if mode == 1 and not sat:
                    bc_ceiling = max(bc_ceiling, a)
                elif mode == 2:
                    nv_ceiling = max(nv_ceiling, a)
        print(f"  {inj:>5.2f} | {cells[1]:>26} | {cells[2]:>26}")

    win = bc_ceiling / nv_ceiling if nv_ceiling else 0.0
    print(f"\n  Broadcast sustains {bc_ceiling:.3f} deliveries/cyc; naive's ceiling is {nv_ceiling:.3f}")
    print(f"  (it saturates early -- node 0's egress carries all {B_MINUS_1} streams). So the shared-")
    print(f"  prefix broadcast delivers >= {win:.0f}x the useful KV rate, cycle-accurate, on the SAME")
    print(f"  flit-fork primitive as the g-fold row multicast -- now on the request axis (B-fold).")
    print(f"  CAVEAT: snake path over-estimates LATENCY vs a dimension-ordered tree; the throughput/")
    print(f"  saturation result (the load-bearing one) is faithful. Tree is the refinement.")

    assert nv_ceiling < bc_ceiling, (nv_ceiling, bc_ceiling)
    print(f"\n  selfcheck OK -- broadcast exact ({ratio:.0f}=={B_MINUS_1}); win {win:.0f}x (naive egress-bound)")


def _selfcheck():
    # Geometry only (no booksim): the snake visits every node exactly once, neighbours only.
    k = K
    order = []
    for y in range(k):
        xs = range(k) if y % 2 == 0 else range(k - 1, -1, -1)
        for x in xs:
            order.append(y * k + x)
    assert len(order) == N and len(set(order)) == N, "snake must be a permutation of all nodes"
    # consecutive snake nodes are physical neighbours (differ by 1 in x, or step up a row)
    for a, b in zip(order, order[1:]):
        ax, ay, bx, by = a % k, a // k, b % k, b // k
        assert (ay == by and abs(ax - bx) == 1) or (ax == bx and by == ay + 1), (a, b)
    assert order[0] == 0, "snake starts at the source (node 0)"
    assert order[-1] == snake_end(k), f"snake ends at {snake_end(k)}, got {order[-1]}"
    # one injection covers the source's own node (no delivery) + N-1 others
    assert order[0] not in order[1:] and len(order[1:]) == B_MINUS_1
    print(f"selfcheck OK -- {K}x{K} snake is a Hamiltonian path 0..{snake_end(k)} over all {N} "
          f"nodes; 1 broadcast -> {B_MINUS_1} deliveries (see --run for the sim)")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
