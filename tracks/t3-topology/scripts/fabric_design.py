#!/usr/bin/env python3
"""The die-array fabric design — derived from the KV matrix, not from a catalog (T3)

die_to_die_matrix.py built the workload's die-to-die KV matrix and the placement
law D(G) = KV_AGG x (G-1)/G. This file SOLVES the fabric design problem against
it. Key observation: in this schedule the fabric's ONLY job is intra-block KV
delivery — weights are read from per-die DRAM, and the schedule deliberately has
no per-step cross-die reductions — so the 16-die network problem degenerates into
INDEPENDENT BLOCK FABRICS:

  G=1  batch-split     no fabric at all (the ~37K envelope, viable today)
  G=2  die-pair        ONE direct link per pair, >=164 GB/s -> 1.6T UEC (2026)
  G=4  quadrant 2x2    2-link bisection, >=246 GB/s -> 3.2T optics (2027)
  G=8  half 4x2        >=574 GB/s single-lane (no roadmap); with degree-8 I/O
                       (2x parallel links) >=287 GB/s -> 3.2T optics (2027)
  G=16 dense 4x4       >=615 GB/s = 5 Tb/s-class ports -> on NO roadmap

The block-local view is STRICTER than the global bisection view at G>=4 (the
binding cut is the BLOCK's, not the box's); the views only agree at G=2, where
the 'fabric' is a point-to-point link, not a network.

THE SOLUTION (computed, selfchecked):
  1. The 2026 answer is the G=2 PAIRED-DIE design: 1.6T UEC links double the
     context envelope (73K tokens), close the bisection at 1.2x margin, run the
     per-die remote demand at 2.4x headroom, and leave decode DRAM-bound — so
     the 5.4x multicast win survives untouched. No network, no topology, no
     deadlock, no coverage problem: one link per pair.
  2. 2027 optics (3.2T) unlock G=4 quadrants (146K) and degree-8 G=8 halves
     (293K) — the era table below.
  3. Any block fabric that IS a network (G>=4) must be mesh-shaped: the measured
     multicast-coverage constraint (fabric_sweep Q1) rules out torus. G=2 needs
     no network at all, so it inherits no topology constraint.
  4. Fabric energy at G=2 is exactly 5x lower than dense sharding: 1-hop deliveries at
     half the volume, ~42 W @4 pJ/bit on a ~3 kW box.
  5. Verification leg: BookSim configs for the block fabrics are emitted for the
     tools-image run (the patched mcast fork machinery, fabric_sweep Q1-style).

The niche is worth it: the matrix-derived design lands the fabric a year EARLIER
than the worst-case crossover (2026 at G=2, not 2027 at 3.2T) and doubles the
context envelope for free.

RUN: python3 scripts/fabric_design.py --selfcheck
"""
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling-script imports
import serving_multicast as sm      # QUIETBOX, MODELS
import fabric_sweep as fs           # N_DIES, SEQ, B, kv_rate_gbs
import die_to_die_matrix as ddm     # demand_gbps, context_ceiling_tokens, matrices

N = fs.N_DIES
KV_AGG = fs.kv_rate_gbs()
PER_DIE_KV = KV_AGG / N             # 164 GB/s: per-die KV read demand at the headline

# G-die KV-sharing blocks as (cols, rows) shapes on the 4x4 array
BLOCKS = {1: (1, 1), 2: (2, 1), 4: (2, 2), 8: (4, 2), 16: (4, 4)}

# per-direction GB/s per port by era (packet fabrics, from fabric_crossover TECH)
ERA = [(12.5, "100GbE (today)", "2023"),
       (100.0, "800GbE / IB-XDR", "2025"),
       (200.0, "UEC / UALink 1.6T", "2026"),
       (400.0, "co-packaged optics 3.2T", "2027")]

SERDES_PJ_BIT = 4.0
BOX_W = 3000.0


def block_bisection_links(shape):
    """Min cut of an (cols, rows) grid: the smaller dimension."""
    return min(shape)


def avg_hops(shape):
    """Exact average Manhattan distance over ordered pairs, excluding self."""
    c, r = shape
    tot = pairs = 0
    for a in range(c * r):
        for b in range(c * r):
            if a != b:
                tot += abs(a % c - b % c) + abs(a // c - b // c)
                pairs += 1
    return tot / pairs


def link_requirement_gbps(G):
    """Per-link (per direction) GB/s the block's own bisection must carry."""
    return ddm.local_bisection_gbps(G) / block_bisection_links(BLOCKS[G])


def closes_in_era(G, degree8=False):
    """(rate, era-name, year, margin) of the first era that closes G, or None."""
    req = link_requirement_gbps(G) / (2 if degree8 else 1)
    for rate, name, year in ERA:
        if rate >= req:
            return rate, name, year, rate / req
    return None


def fabric_power_w(G):
    """Fabric energy at G: demand x bits x pJ x avg hop distance (block-local)."""
    return ddm.demand_gbps(G) * 1e9 * 8 * SERDES_PJ_BIT * 1e-12 * avg_hops(BLOCKS[G])


def block_matrix_fractions(G):
    """GxG BookSim matrix() fractions for ONE representative block (rows sum to 1)."""
    m = ddm.blocked_matrix_gbps(G)
    g0 = 0
    return ddm.matrix_row_fractions([row[g0:g0 + G] for row in m[g0:g0 + G]])


def booksim_cfg(G, matrix_file, inj=0.02):
    """Block-fabric config for the patched BookSim (mesh, dim_order, matrix traffic).

    Topology per block: G=2 -> 2-node line (k=2,n=1); G=4 -> 2x2 (k=2,n=2);
    G=16 -> 4x4 (k=4,n=2). G=8's 4x2 block is not expressible as a square 2D
    mesh, so it is modeled as a conservative 8-node line (k=8,n=1): bisection 1
    link instead of 2 -- the harder cut, so any verdict it gives is pessimistic.
    matrix() traffic is unicast per row (the mcast fork does not combine with it).
    """
    if G == 2:
        k, n = 2, 1
    elif G == 4:
        k, n = 2, 2
    elif G == 8:
        k, n = 8, 1          # conservative 1D line, see docstring
    else:
        k, n = 4, 2
    return f"""topology = mesh;
k = {k};
n = {n};
routing_function = dim_order;
num_vcs = 8;
vc_buf_size = 8;
traffic = matrix({matrix_file});
injection_rate = {inj};
packet_size = 1;
output_buffer_size = -1;
sim_type = latency;
sample_period = 2000;
warmup_periods = 2;
max_samples = 5;
"""


def run_booksim(cfg_path):
    """(injected, accepted, latency, saturated) for one matrix-driven cfg."""
    r = subprocess.run(["booksim", str(cfg_path)], capture_output=True, text=True,
                       timeout=240)
    inj_r = acc = lat = None
    sat = ("unstable" in r.stdout) or ("Aborting" in r.stdout)
    for line in r.stdout.splitlines():
        if "Injected packet rate average" in line:
            inj_r = fs.noc._num(line)
        elif "Accepted packet rate average" in line:
            acc = fs.noc._num(line)
        elif "Packet latency average" in line:
            lat = fs.noc._num(line)
    return inj_r, acc, lat, sat


def _selfcheck():
    # block geometry: bisection links and exact average hops
    assert block_bisection_links(BLOCKS[2]) == 1
    assert block_bisection_links(BLOCKS[4]) == 2
    assert block_bisection_links(BLOCKS[8]) == 2
    assert block_bisection_links(BLOCKS[16]) == 4
    assert abs(avg_hops((2, 2)) - 4 / 3) < 1e-9            # 2x2: 1.33
    assert abs(avg_hops((4, 4)) - 8 / 3) < 1e-9            # 4x4: 2.67 (matches crossover)
    # per-link requirements (block-local view, computed from the model)
    for G, req in ((2, 164), (4, 246), (8, 574), (16, 615)):
        assert abs(link_requirement_gbps(G) - req) < 2, (G, link_requirement_gbps(G))
    # verdicts: G=2 closes at 1.6T (2026); G=4 needs 3.2T (2027); G=8 needs degree-8
    # + 3.2T; G=16 never
    assert closes_in_era(2)[1] == "UEC / UALink 1.6T"
    assert closes_in_era(4)[1] == "co-packaged optics 3.2T"
    assert closes_in_era(8) is None
    assert closes_in_era(8, degree8=True)[1] == "co-packaged optics 3.2T"
    assert closes_in_era(16) is None
    # energy: blocking monotonically cuts fabric energy; G=2 is exactly 5x below dense
    w = {G: fabric_power_w(G) for G in (2, 4, 8, 16)}
    assert w[2] < w[4] < w[8] < w[16]
    assert w[16] / w[2] >= 5.0 - 1e-9, w[16] / w[2]
    # throughput: at G=2, half of each die's KV is remote = 82 GB/s on a 200 GB/s
    # link (2.4x headroom); decode stays DRAM-bound so the 5.4x survives
    assert abs(PER_DIE_KV / 2 - 82) < 1
    assert PER_DIE_KV / 2 < 200.0 / 2.4 + 1
    # context: G=2 doubles the envelope
    assert abs(ddm.context_ceiling_tokens(2) / ddm.context_ceiling_tokens(1) - 2) < 1e-9
    print(f"selfcheck OK -- link reqs 164/246/574/615 GB/s at G=2/4/8/16; "
          f"G=2 -> 1.6T (2026), G=4 -> 3.2T (2027), G=8 -> degree-8+3.2T, G=16 never; "
          f"fabric energy {w[2]:.0f}W at G=2 vs {w[16]:.0f}W dense "
          f"({w[16]/w[2]:.1f}x); G=2 link headroom {200.0/(PER_DIE_KV/2):.1f}x")


def main():
    print(f"\n  Die-array fabric design derived from the KV matrix "
          f"({sm.MODELS[1].name}, {fs.SEQ//1024}K, batch {fs.B}, {N} dies)")
    print(f"  per-die KV demand {PER_DIE_KV:.0f} GB/s; the fabric's only job is "
          f"intra-block KV delivery\n")

    print(f"  {'G':>3} {'block':>10} {'bisect':>7} {'link need':>10} {'closes in':>24}"
          f"{'ctx':>7} {'fabric W':>9} {'hops':>5}")
    for G in (1, 2, 4, 8, 16):
        if G == 1:
            print(f"  {G:>3} {'local':>10} {'0':>7} {'—':>10} {'nothing needed':>24}"
                  f"{ddm.context_ceiling_tokens(1)/1000:>6.0f}K {'0':>9} {'0':>5}")
            continue
        shape = BLOCKS[G]
        req = link_requirement_gbps(G)
        cell = closes_in_era(G)
        if cell is None:
            cell8 = closes_in_era(G, degree8=True)
            closes = "none (deg-8: " + (f"{cell8[1]} {cell8[2]}" if cell8 else "none") + ")"
        else:
            closes = f"{cell[1]} ({cell[2]}, {cell[3]:.2f}x)"
        print(f"  {G:>3} {str(shape)+' grid':>10} "
              f"{block_bisection_links(shape):>7} {req:>8.0f} "
              f"{closes:>24} {ddm.context_ceiling_tokens(G)/1000:>6.0f}K "
              f"{fabric_power_w(G):>8.0f} {avg_hops(shape):>5.2f}")

    print(f"\n  THE SOLUTION -- the 2026 fabric is the G=2 PAIRED-DIE design:")
    print(f"    1.6T UEC link per die-pair (>=164 GB/s needed, 200 GB/s available,")
    print(f"    1.2x bisection margin); remote demand per die 82 GB/s = 2.4x headroom;")
    print(f"    decode stays DRAM-bound -> the 5.4x multicast win survives untouched.")
    print(f"    No network, no topology, no routing: the fabric degenerates to one")
    print(f"    point-to-point link per pair -- the multicast-coverage constraint and")
    print(f"    the deadlock hazard both vanish with the network itself.")
    print(f"    Context ceiling doubles to ~73K tokens; fabric energy exactly 5x lower than")
    print(f"    dense sharding (~{fabric_power_w(2):.0f} W @4 pJ/bit on a ~{BOX_W/1000:.0f} kW box).")
    print(f"    2027 optics (3.2T) extend it: G=4 quadrants (146K ctx) or degree-8")
    print(f"    G=8 halves (293K) -- mesh-shaped blocks only (coverage constraint).")

    out = Path("/tmp/fabric_design")
    out.mkdir(exist_ok=True)
    for G in (4, 8, 16):
        (out / f"matrix_g{G}.txt").write_text(
            "\n".join(" ".join(f"{v:.8f}" for v in row)
                      for row in block_matrix_fractions(G)))
        (out / f"block_g{G}.cfg").write_text(
            booksim_cfg(G, f"/tmp/fabric_design/matrix_g{G}.txt"))
    print(f"\n  Verification leg (tools image): {out}/block_g4.cfg, block_g8.cfg,")
    print(f"    block_g16.cfg -- patched BookSim, matrix()-driven unicast (the mcast")
    print(f"    fork does not combine with matrix traffic; the mechanism is already")
    print(f"    Q1-verified at die scale on uniform traffic). Run with --run.")

    _selfcheck()


def main_run():
    """--run: matrix-driven acceptance on the block fabrics (tools image)."""
    fs.noc.ensure_booksim()
    out = Path("/tmp/fabric_design")
    out.mkdir(exist_ok=True)
    print(f"\n  Matrix-driven block fabrics (the KV matrix, not uniform traffic)")
    SWEEP = (0.05, 0.10, 0.20, 0.40, 0.60)
    print(f"  {'G':>3} {'block':>10} | {'inj':>5} | {'acc/cyc':>9} {'lat':>6} {'state':>5}")
    for G in (4, 8, 16):
        (out / f"matrix_g{G}.txt").write_text(
            "\n".join(" ".join(f"{v:.8f}" for v in row)
                      for row in block_matrix_fractions(G)))
        peaks = []
        for inj in SWEEP:
            cfgp = out / f"block_g{G}.cfg"
            cfgp.write_text(booksim_cfg(G, f"/tmp/fabric_design/matrix_g{G}.txt", inj))
            inj_r, acc, lat, sat = run_booksim(cfgp)
            state = "SAT" if sat else "ok"
            if acc:
                peaks.append((acc, inj_r, sat))
            print(f"  {G:>3} {str(BLOCKS[G])+' grid':>10} | {inj:>5.2f} | "
                  f"{acc or 0:>9.3f} {lat or 0:>6.0f} {state:>5}")
        stable = [a for a, _, sat in peaks if not sat]
        if stable:
            print(f"    -> peak stable acceptance {max(stable):.3f} flits/cyc")
    _selfcheck()


if __name__ == "__main__":
    if "--run" in sys.argv:
        main_run()
    else:
        main()
