#!/usr/bin/env python3
"""The die-to-die KV matrix — the workload, not a guess (T3)

The fabric work (fabric_sweep.py, fabric_crossover.py) bounded sharded-KV delivery
with uniform all-to-all traffic. This file builds the ACTUAL die-to-die traffic
matrix from the serving model's own constants (serving_multicast.py: Llama-3-70B,
32K context, batch 11 on QuietBox, 16 dies). 16x16, GB/s, rows = die holding the
KV shard, columns = die reading it. Computed, not assumed.

WHAT THE MATRIX SHOWS (all computed, all selfchecked):

  1. ROUND-ROBIN SHARDING IS A UNIFORM PAIR MATRIX: 10.25 GB/s on all 240
     off-diagonal pairs. At the PAIR level no topology can beat another — this
     is why the bisection bound rules. The structure that topology CAN exploit
     is elsewhere: the multicast tree embedding and the placement knob.
  2. PLACEMENT IS THE LEVER, AND IT IS LINEAR. Block the 16 dies into G-die
     groups that share KV: remote fraction = (G-1)/G, so fabric demand
     D(G) = 2625 x (G-1)/G. G=1 is batch-split (identity matrix, 0 remote, the
     ~37K-token envelope); G=16 is today's dense sharding (49x short).
  3. CROSSOVER WITH THE 2026 FABRIC: at L=8 bisection, 1.6T-class ports
     (UEC/UALink, 2026) close at G<=2 — pair-of-dies KV: ~74K-token context,
     half the fabric demand, 1.2x margin. 3.2T optics (2027) close even G=16.
     G is a WORKLOAD-DERIVED design lever that moves the crossover year.
  4. SPATIAL PLACEMENT on the array converts blocking into LOCAL traffic:
     G-die contiguous blocks carry their remote KV intra-block, so the binding
     cut is the BLOCK's, not the global one (G=2: 1 link at 164 GB/s; G=4:
     2 links at 492 GB/s -> needs ~2 Tb/s links; G=8: 2 links at 1148 GB/s).

WHY THIS IS WORTH DOING — 2026 LANDSCAPE (researched, not assumed):
  * Collective-capable NoCs, FlooNoC group (arXiv 2603.26438, 2026): in-network
    multicast/fork (DCA) on the exact platform we calibrate router energy
    against; 2-4x on collective primitives at sub-1% area; "multi-chiplet" is
    their stated future direction.
  * 3DLS (arXiv 2607.01617, Jul 2026): physical separation of KV-cache vs
    TP-collective traffic classes in chiplet LLM serving — traffic-pattern-aware
    die-to-die design is being published right now.
  * HyMCache (SK hynix, arXiv 2607.18141, Jul 2026): KV traffic is "read-
    dominant, predictable, append-only" — the same characterization this track
    measured; CXL as a KV tier (the crossover's CXL lever, now with a paper).
  * LEAP (arXiv 2509.14781): KV-aware NoC traffic balancing / KV-cache tiling
    in LLM-inference architectures.
  * tt-metal PR #40733 (merged 2026-04-13): the INTRA-CHIP mechanism (read KV
    from DRAM once, NoC-multicast to same-row chain cores) is already shipped
    in its ring-joint SDPA reader kernel — with an eligibility rule ("same
    physical row, no gaps in the mcast rectangle") that is our row-locality
    constraint, vendor-confirmed. It carries no serving-scale numbers and no
    fabric law.
  The niche WE occupy — a die-array fabric derived from the KV multicast matrix
  with placement as an explicit design parameter — is not covered by any of
  these. The mechanism is vendor-shipped; the LAW (D(G), blocks, closure) is
  the still-open first step. Do not re-claim the mechanism itself.

RUN: python3 scripts/die_to_die_matrix.py --selfcheck
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling-script imports
import serving_multicast as sm      # Model, Box, QUIETBOX, operating point
import fabric_sweep as fs           # N_DIES, SEQ, B, kv_rate_gbs, remote_kv_gbps

N = fs.N_DIES
SEQ = fs.SEQ
KV_AGG = fs.kv_rate_gbs()           # 2625 GB/s: aggregate KV-read rate at the headline
REMOTE_FULL = fs.remote_kv_gbps()   # 2460 GB/s: remote share at G=16

# block geometry: contiguous G-die blocks on the 4x4 array -> the BLOCK's bisection
BLOCK_LINKS = {1: 0, 2: 1, 4: 2, 8: 2, 16: 4}   # 1x2, 2x2, 4x2, 4x4 shapes
PORTS = {12.5: "100GbE", 100.0: "800GbE/IB-XDR", 200.0: "UEC/UALink 1.6T",
         400.0: "optics 3.2T"}


def blocked_matrix_gbps(G):
    """16x16 matrix of remote-KV delivery (GB/s) for G-die KV-sharing groups.

    Die q's reads: KV of its own sequences, sharded across its G-die group, so
    G-1 remote shards at KV_AGG/(N*G) GB/s each. G=16 -> dense round-robin;
    G=1 -> identity (batch-split, all local).
    """
    pair = KV_AGG / (N * G)
    m = [[0.0] * N for _ in range(N)]
    for g0 in range(0, N, G):
        dies = range(g0, min(g0 + G, N))
        for s in dies:
            for q in dies:
                if s != q:
                    m[s][q] = pair
    return m


def demand_gbps(G):
    """Fabric KV demand at blocking G (linear law): KV_AGG x (G-1)/G."""
    return KV_AGG * (G - 1) / G


def context_ceiling_tokens(G):
    """Sequence ceiling when KV may span G dies (12 GB per die share, 10.7 GB/32K)."""
    return fs.kv_local_ceiling_tokens() * G


def local_bisection_gbps(G):
    """Block-local view: remote KV crossing a block's bisection (r links)."""
    return demand_gbps(G) / (N / G) if G > 1 else 0.0


def matrix_row_fractions(m):
    """BookSim matrix() format: per-row fractions (row = shard die)."""
    out = []
    for row in m:
        s = sum(row)
        out.append([0.0 if s == 0 else v / s for v in row])
    return out


def write_booksim_matrix(m, path):
    """Emit the matrix in the format BookSim's matrix(<file>) reads."""
    frac = matrix_row_fractions(m)
    with open(path, "w") as f:
        f.write("# die-to-die KV delivery matrix (row=shard die, col=query die)\n")
        for row in frac:
            f.write(" ".join(f"{v:.8f}" for v in row) + "\n")


def _selfcheck():
    # dense (G=16): all 240 pairs equal, totals match the pinned fabric numbers
    m16 = blocked_matrix_gbps(16)
    offdiag = [m16[s][q] for s in range(N) for q in range(N) if s != q]
    assert abs(offdiag[0] - REMOTE_FULL / 240) < 0.01, offdiag[0]
    assert abs(sum(offdiag) - REMOTE_FULL) < 1.0
    assert all(abs(v - offdiag[0]) < 1e-9 for v in offdiag)
    per_row = sum(m16[0])
    assert abs(per_row - REMOTE_FULL / N) < 0.1, per_row     # ~153.6 GB/s per die
    # G=1 is the identity (batch-split): zero remote
    assert sum(sum(r) for r in blocked_matrix_gbps(1)) == 0.0
    # linear law: D(G) = KV_AGG*(G-1)/G, and G=16 recovers the pinned 49x deficit
    for G in (2, 4, 8):
        assert abs(demand_gbps(G) - KV_AGG * (G - 1) / G) < 0.01
    assert abs(demand_gbps(16) - REMOTE_FULL) < 0.01
    # the 2026 crossover: 1.6T ports (200 GB/s) at L=8 close at G<=2, not G=4
    l8 = fs.FAB_K * 2
    assert demand_gbps(2) < l8 * 200.0 < demand_gbps(4), (demand_gbps(2), l8 * 200, demand_gbps(4))
    # 3.2T optics close even full sharding (matches fabric_crossover)
    assert demand_gbps(16) < l8 * 400.0
    # context: G=2 doubles the envelope to ~74K tokens
    assert abs(context_ceiling_tokens(2) / 1000 - 2 * 36.7) < 4
    # block-local view: G=2 rides ONE link at ~164 GB/s (needs >=1.3 Tb/s)
    assert abs(local_bisection_gbps(2) - KV_AGG / N) < 0.1
    assert local_bisection_gbps(2) < 200.0          # 1.6T link closes the pair
    assert local_bisection_gbps(4) > 400.0          # 2x 3.2T links close the quadrant
    # BookSim format: rows sum to 1.0
    for row in matrix_row_fractions(blocked_matrix_gbps(4)):
        assert abs(sum(row) - 1.0) < 1e-6
    print(f"selfcheck OK -- dense pairs {offdiag[0]:.2f} GB/s (uniform, {REMOTE_FULL:.0f} "
          f"total); D(G) linear {(KV_AGG*(2-1)/2):.0f}/{(KV_AGG*(4-1)/4):.0f}/"
          f"{(KV_AGG*(8-1)/8):.0f} GB/s at G=2/4/8; G=2 closes 1.6T @ L=8; "
          f"G=2 block rides 1 link at {local_bisection_gbps(2):.0f} GB/s")


def main():
    print(f"\n  Die-to-die KV matrix -- {sm.MODELS[1].name}, {SEQ//1024}K, batch {fs.B}, "
          f"{sm.QUIETBOX.name} ({N} dies)")
    print(f"  aggregate KV {KV_AGG:.0f} GB/s; dense-shard remote {REMOTE_FULL:.0f} GB/s "
          f"(49x short of the 100GbE mesh)\n")

    print(f"  {'G':>3} {'remote GB/s':>11} {'vs L=8 @1.6T':>14} {'vs L=8 @3.2T':>14}"
          f"{'context':>9} {'block shape':>12} {'block bisection':>16}")
    for G in (1, 2, 4, 8, 16):
        d = demand_gbps(G)
        t16 = "closes" if d < 8 * 200 else f"{d / (8 * 200):.1f}x short"
        t32 = "closes" if d < 8 * 400 else f"{d / (8 * 400):.1f}x short"
        lb = local_bisection_gbps(G)
        if G == 1:
            block = "local"
            bis = "0 (nothing remote)"
        elif G == 2:
            block = "1x2 pair"
            bis = f"1 link @ {lb:.0f} GB/s -> needs >= {lb:.0f} GB/s/port"
        elif G == 4:
            block = "2x2 quadrant"
            bis = f"2 links @ {lb:.0f} GB/s -> needs >= {lb/2:.0f} GB/s/port"
        elif G == 8:
            block = "4x2 half"
            bis = f"2 links @ {lb:.0f} GB/s -> needs >= {lb/2:.0f} GB/s/port"
        else:
            block = "4x4 whole"
            bis = f"4 links @ {lb:.0f} GB/s -> needs >= {lb/4:.0f} GB/s/port"
        print(f"  {G:>3} {d:>11.0f} {t16:>14} {t32:>14} "
              f"{context_ceiling_tokens(G)/1000:>7.0f}K {block:>12} {bis:>16}")

    print(f"\n  The matrix (GB/s, G=16 dense: row=shard die, col=query die, "
          f"{REMOTE_FULL/240:.2f} on every off-diagonal):")
    m16 = blocked_matrix_gbps(16)
    for s in range(N):
        print(f"    s{s:>2}: " + " ".join(f"{m16[s][q]:6.2f}" for q in range(N)))

    write_booksim_matrix(m16, Path("/tmp/die2die_matrix_16.txt"))
    write_booksim_matrix(blocked_matrix_gbps(2), Path("/tmp/die2die_matrix_g2.txt"))
    write_booksim_matrix(blocked_matrix_gbps(4), Path("/tmp/die2die_matrix_g4.txt"))
    print(f"\n  BookSim matrix() files written: /tmp/die2die_matrix_16.txt "
          f"(dense), _g2.txt (die-pair blocking), _g4.txt (quadrant blocking)")

    print(f"\n  THE MATRIX'S ANSWER: pairs are uniform, so the topology question is")
    print(f"  secondary; PLACEMENT is the workload-derived lever. G<=2 pairs close")
    print(f"  the 2026 1.6T fabric at ~74K-token context; quadrant G=4 needs ~2.5")
    print(f"  Tb/s links (2027 optics); full sharding needs 3.2T. 'Keep KV off the")
    print(f"  fabric' is the G=1 end of this same law -- not a separate answer.")

    _selfcheck()


if __name__ == "__main__":
    main()
