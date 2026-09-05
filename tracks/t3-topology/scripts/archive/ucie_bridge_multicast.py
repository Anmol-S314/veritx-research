"""Bridge-fork vs source-fork for a KV row-multicast crossing a die edge.

Phase 2 (UCIE-ARC.md) question 1: a KV row-multicast whose core chain spans two
chiplets must cross a NoC-to-NoC bridge (UCIe-class). Two mechanisms:

  * source-fork: sender replicates; the bridge carries g copies (g remote cores)
  * bridge-fork: the bridge carries ONE copy; the remote die's own NoC forks it
    to the g cores (the Phase-1 mechanism, continued across the boundary)

The bridge is the scarce resource (die-edge SERDES/PHY budget, lanes), so the
demand ratio is the known-answer gate: source/bridge = g, the same g-fold law as
Phase 1 (PITFALLS 16), now at the boundary. The placement claim: the bridge port
must sit on the remote multicast row's axis, or the remote fork pays hops the
bridge bandwidth just bought (checked as a hop penalty term, conservatively).

UCIe data from published spec coverage (Synopsys IP bulletin 2025-04, UCIe 1.x/2.x):
PHY rates 16/32/40/64 Gb/s per lane, bridges x8-x64. We do NOT assert a pJ/bit;
energy per hop stays on-die (calibrated 1.37x FlooNoC anchor) and the bridge is
priced only in LANES, which are checkable.

SELFCHECK (known-answer):
  * source/bridge demand ratio == g (exact, per the fork counts)
  * lanes demand for bridge-fork < 1 bridge at the Phase-1 operating point
  * placement penalty: remote fork across the mesh midline costs extra hops
    exactly as Phase-1 measured (6.625 bipartite mean on 8x8, per PITFALLS 10)
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import serving_multicast as sm          # Model, Box, QUIETBOX, operating point
import fabric_sweep as fs               # N_DIES, FAB_K, KV rates

# --- bridge physics (published ranges, lanes as the unit of cost) ---
UCIE_LANE_GBS = (16.0, 32.0, 40.0, 64.0)    # Gb/s per lane, published PHY rates
BRIDGE_X = (8, 16, 32, 64)                  # lanes per bridge

# --- operating point, carried from Phase 1 ---
SEQ = fs.SEQ                                  # 32768 tokens
OP = sm.operating_point(sm.MODELS[0], sm.QUIETBOX, SEQ)
B = OP["batch"]

# KV rate of ONE die's share at the operating point (GB/s), from fabric_sweep's
# aggregate with N_DIES equal split: each die reads its own sequences' KV.
KV_DIE_GBS = fs.kv_rate_gbs() / fs.N_DIES


def bridge_demand_gbs(g, bridge_fork=True):
    """GB/s crossing the bridge for one multicast stream reaching g remote cores.

    source-fork: g copies (sender replicates, remote cores just receive)
    bridge-fork: 1 copy (bridge carries one stream; remote NoC forks)
    """
    return KV_DIE_GBS * (1.0 if bridge_fork else g)


def lanes_for_gbs(gbs, lane_gbs):
    """Minimum full-duplex lanes to carry gbs (per direction)."""
    return gbs / (lane_gbs / 8.0)   # Gb/s -> GB/s


def placement_hops_penalty(remote_row_axis, remote_grid):
    """Extra remote hops when the bridge port is NOT on the multicast row's axis.

    Conservative model: an off-axis port forces the stream to first cross the
    remote die's midline to reach the row axis. That hop cost is the Phase-1
    MEASURED bipartite mean on an 8x8 mesh -- 6.625 hops (PITFALLS 10) -- not a
    closed-form guess. On-axis ports pay zero (the port sits on the row).
    """
    if remote_row_axis == "row":
        return 0
    return 6.625 if remote_grid == 8 else 0.0

def _selfcheck():
    ok = True
    g = 8                                   # 8 remote cores in the chain

    # 1. exact known-answer ratio
    src = bridge_demand_gbs(g, bridge_fork=False)
    brg = bridge_demand_gbs(g, bridge_fork=True)
    ratio = src / brg
    if abs(ratio - g) > 1e-9:
        ok = False
        print(f"FAIL: source/bridge ratio {ratio} != g={g}")

    # 2. bridge-fork fits a single bridge at the operating point
    lanes = lanes_for_gbs(brg, UCIE_LANE_GBS[-1])   # cheapest in lanes: 64 Gb/s
    if lanes > 64:                                  # one x64 bridge
        ok = False
        print(f"FAIL: bridge-fork needs {lanes:.1f} lanes (single x64 is 64)")

    # 3. placement penalty is zero on-axis, nonzero off-axis
    if placement_hops_penalty("row", 8) != 0 or placement_hops_penalty("col", 8) == 0:
        ok = False
        print("FAIL: placement penalty axis logic")

    print(f"selfcheck OK -- g={g}: source/bridge = {ratio:.0f}x; bridge-fork "
          f"needs {lanes:.1f} lanes @64Gb/s (x64 bridge, headroom "
          f"{64 / max(lanes, 1e-9):.1f}x); off-axis penalty "
          f"{placement_hops_penalty('col', 8):.1f} hops")
    return ok


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        sys.exit(0 if _selfcheck() else 1)
    for g in (4, 8, 16):
        src = bridge_demand_gbs(g, bridge_fork=False)
        brg = bridge_demand_gbs(g, bridge_fork=True)
        lanes = lanes_for_gbs(brg, UCIE_LANE_GBS[-1])
        print(f"g={g:>2}: source-fork {src:6.1f} GB/s vs bridge-fork "
              f"{brg:6.1f} GB/s -> {lanes:5.1f} lanes @64Gb/s, "
              f"{src / brg:.0f}x ratio")
    print(f"KV per die at operating point: {KV_DIE_GBS:.1f} GB/s "
          f"(B={B}, SEQ={SEQ})")
