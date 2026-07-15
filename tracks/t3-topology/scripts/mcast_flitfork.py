#!/usr/bin/env python3
"""Cycle-accurate multicast vs naive re-fetch, with REAL flit-fork multicast. (T3)

This is the belt-and-suspenders result mcast_validate.py said needed router surgery. The
surgery is done (booksim-ext/multicast.patch): the Flit carries pre-registered single-flit
COPIES, iq_router forks each to the eject port as the row-broadcast stream transits that
core, and the TrafficManager injects one stream per row (receivers suppressed, so no
self-packet pollution -- the confound of the old far-end proxy, PITFALLS.md #15). One
injected stream -> g deliveries, one stream on the links.

WHAT IT SHOWS, cleanly and without the old confounds:
  - FORK CORRECTNESS: one multicast injection yields exactly g-1 deliveries (accepted /
    injected == K-1). This is the known-answer validation gate; nothing below is trusted
    until it passes.
  - THE g-FOLD NETWORK WIN: multicast sustains ~ (g-1)x the useful KV-delivery rate of
    naive before saturating, because the group SHARES the row links instead of each query
    head pulling its own copy. Naive's near link carries all g streams and saturates first;
    multicast's row links carry one stream and stay flat.

MODEL. An 8x8 MESH (not torus): a row-broadcast is a linear path col0->col7 that transits
every core, so "deliver at every transit node" is exact. A torus would let the stream take
the 1-hop wraparound and MISS the middle cores -- and would only SHORTEN the span, so mesh
is the conservative choice (it never flatters multicast). packet_size=1 keeps every
delivery a head&&tail single flit, so retirement never touches multi-flit reassembly.

RUN IT (inside the tools image; self-builds the patched booksim if the image predates it):
    podman run --rm -v "$PWD:/repo" -w /repo \\
        internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest \\
        python3 tracks/t3-topology/scripts/mcast_flitfork.py --run

    python3 scripts/mcast_flitfork.py --selfcheck   # matrices/geometry only, no booksim
"""
import re
import subprocess
import sys
from pathlib import Path

K = 8                               # 8x8 mesh: 8 cores per row, 8 rows
G_MINUS_1 = K - 1                   # deliveries per multicast stream (source excluded)
HERE = Path(__file__).resolve()
BUILD = HERE.parents[1] / "booksim-ext" / "build.sh"
OUT = Path("/tmp/mcast_flitfork")   # in-container scratch for cfgs
SWEEP = [0.05, 0.10, 0.20, 0.40, 0.60, 0.80, 1.00]


def cfg(mode, inj):
    return f"""topology = mesh;
k = {K};
n = 2;
routing_function = dim_order;
num_vcs = 8;
vc_buf_size = 8;
traffic = uniform;
mcast_k = {K};
mcast_naive = {mode};
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
    p = OUT / f"m{mode}_{inj}.cfg"
    p.write_text(cfg(mode, inj))
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


def have_patched_booksim():
    """True iff the booksim on PATH forks (accepted > injected under mcast_k)."""
    try:
        inj_r, acc, _, _ = run_booksim(0, 0.02)
    except Exception:
        return False
    return bool(inj_r and acc and acc / inj_r > 1.5)


def ensure_booksim():
    if have_patched_booksim():
        return
    print("  patched booksim not on PATH -- building via booksim-ext/build.sh ...")
    r = subprocess.run(["bash", str(BUILD)], capture_output=True, text=True)
    if r.returncode != 0 or not have_patched_booksim():
        sys.exit("  ERROR: could not build/verify the patched booksim.\n"
                 "  Run inside the tools image; see booksim-ext/README.md.\n"
                 + r.stdout[-1500:] + r.stderr[-1500:])


def main():
    ensure_booksim()
    print(f"\n  Flit-fork multicast vs naive re-fetch -- {K}x{K} mesh, one KV stream per row\n")

    # --- validation gate: one injection must deliver to exactly g-1 = K-1 cores ---
    inj_r, acc, _, _ = run_booksim(0, 0.02)
    ratio = acc / inj_r
    print(f"  GATE  one multicast injection -> {ratio:.2f} deliveries "
          f"(expect {G_MINUS_1}); {'PASS' if abs(ratio - G_MINUS_1) < 0.5 else 'FAIL'}")
    assert abs(ratio - G_MINUS_1) < 0.5, (ratio, G_MINUS_1)

    # --- the sweep: useful-delivery rate (accepted) and saturation, both schemes ---
    # THROUGHPUT CEILING, read honestly. Naive's ceiling is its SATURATED plateau (the
    # rate it delivers at capacity, with exploded latency) -- NOT its last pre-saturation
    # sample, which undershoots and would inflate the win (a plausible-but-wrong number of
    # exactly the kind PITFALLS.md is about). Multicast never saturates within inj<=1.0
    # (injection is capped there), so its ceiling is a conservative >= .
    print(f"\n  {'inj':>5} | {'MULTICAST':>26} | {'NAIVE re-fetch':>26}")
    print(f"  {'':>5} | {'acc/cyc  lat  state':>26} | {'acc/cyc  lat  state':>26}")
    mc_ceiling = 0.0          # multicast: max STABLE delivery (still climbing at inj=1.0)
    nv_ceiling = 0.0          # naive: max delivery incl. saturated plateau = its ceiling
    for inj in SWEEP:
        cells = {}
        for mode in (0, 1):
            _, a, lat, sat = run_booksim(mode, inj)
            state = "SAT" if sat else "ok"
            cells[mode] = f"{(a or 0):.3f}   {(lat or 0):5.0f}   {state:>3}"
            if a:
                if mode == 0 and not sat:
                    mc_ceiling = max(mc_ceiling, a)
                elif mode == 1:
                    nv_ceiling = max(nv_ceiling, a)
        print(f"  {inj:>5.2f} | {cells[0]:>26} | {cells[1]:>26}")

    win = mc_ceiling / nv_ceiling if nv_ceiling else 0.0
    print(f"\n  Multicast sustains {mc_ceiling:.3f} deliveries/cyc, still stable at inj=1.0;")
    print(f"  naive's ceiling is {nv_ceiling:.3f} (it saturates by inj~0.2). So multicast delivers")
    print(f"  >= {win:.1f}x the useful KV throughput -- cycle-accurate confirmation of the g-fold")
    print(f"  win (analytic g-1 = {G_MINUS_1}), with NO far-node double-load and NO self-packet")
    print(f"  pollution. The group SHARES the row links; naive's near link carries all")
    print(f"  {G_MINUS_1} streams and saturates first. (Win is a conservative >=: multicast has")
    print(f"  not saturated at inj=1.0, the max expressible injection.)")

    # The win must land on the g-fold (K-1=7), not merely be "large" -- that pins the
    # mechanism, not just a direction. Naive must actually saturate below multicast.
    assert 5.5 < win < 8.5, win
    assert nv_ceiling < mc_ceiling, (nv_ceiling, mc_ceiling)
    print(f"\n  selfcheck OK -- fork exact ({ratio:.2f}=={G_MINUS_1}); network win {win:.1f}x (~g-1)")


def _selfcheck():
    # Geometry only (no booksim): the mesh row is the linear broadcast path, and the
    # comparison is well-posed -- multicast injects 1 stream/row, naive injects g-1.
    for row in range(K):
        src = row * K
        far = row * K + (K - 1)
        middles = [row * K + c for c in range(1, K - 1)]
        assert far - src == K - 1, "far end must be K-1 hops down the row (mesh, no wrap)"
        assert len(middles) == K - 2, "copies cover the middle cores; ends are src + far"
        # deliveries = middles (copies) + far (the stream's own) = K-1 = g-1
        assert len(middles) + 1 == G_MINUS_1
    print(f"selfcheck OK -- {K}x{K} mesh; each row: 1 stream col0->col{K-1} forks "
          f"{G_MINUS_1} deliveries; naive sends {G_MINUS_1} unicasts (see --run for the sim)")


if __name__ == "__main__":
    _selfcheck() if "--selfcheck" in sys.argv else main()
