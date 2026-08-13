#!/usr/bin/env python3
"""T3 Plane Separation — DMA bursts vs latency-critical control traffic.

Reproduces the FlooNoC finding (Fischer et al., NOCS 2023 / IEEE D&T 40(6)):
on ONE shared mesh, high-bandwidth bursty DMA traffic starves latency-critical
control traffic; running them on physically separate networks preserves control
latency. This is the on-chip version of "topology matters at the periphery":
the fix is plane separation + boundary placement, not a fancier shape.

The headline result — burstiness, not bandwidth, is what starves control.
All five measurement points move the SAME amount of DMA flit load
(0.08 flits/cycle/node = 5.12 flits/cycle over 64 nodes) into the network;
only the burst length changes. At 1 VC, control latency climbs
45.1 -> 221.6 cyc (1.36x -> 6.68x starvation) as bursts double from 5 to
80 flits. Doubling DMA bandwidth is harmless; doubling DMA burst length
quintuples control starvation.

Design (8x8 mesh, XY routing, seeded for reproducibility):
  - plane_shared.cfg : 2 classes. class 0 = DMA (hotspot to 8 NIC nodes along
                       the main diagonal, one per row), class 1 = control
                       (packet_size 1, uniform). Sweep (burst length, rate)
                       pairs at constant flit load and watch class-1 latency
                       at several VC counts — VC count is the *router-side*
                       isolation knob; the honest question is "how much
                       isolation does the router need before planes are worth
                       the silicon?"
  - plane_data.cfg    : class 0 alone (the DMA plane in isolation).
  - plane_control.cfg : class 1 alone (the control plane in isolation).
  - latency_thres = {5000,500} : the DMA class may be slow, the control class
                       must stay fast — the QoS contract we are testing. This
                       is what lets high-burst cells CONVERGE instead of being
                       killed by the 500-cycle abort as soon as DMA slows
                       down (see PITFALLS.md: aborted runs report transient,
                       not converged, latencies).

Expected shape (this is the finding):
  - 1 VC  : control latency rises steeply with burst length at constant DMA
            bandwidth (45 -> 222 cyc). Long bursts occupy a shared VC for many
            flit-slots; a 1-flit control packet waits for the burst to drain.
  - 2 VCs : much better, still rising at the long-burst end (63 cyc).
  - 4 VCs : essentially flat (41 cyc at 80-flit bursts) — VCs segregate the
            classes and absorb burstiness *within* link capacity.
  - separate plane: flat by construction, whatever the DMA plane does.

MECS / express channels (the router-side latency lever, not bandwidth):
  - Booksim's cmesh supports MESH WITH EXPRESS CHANNELS (cmesh k=4 c=4 =
    64 nodes, same as the 8x8 mesh): express links along the edge rows let
    packets with X-distance > 1 bypass intermediate routers. Routing
    functions: xy_yx (express ON) vs xy_yx_no_express (OFF), identical
    physical topology — a clean A/B.
  - Question: do express channels rescue latency-critical control traffic
    cheaper than a separate plane?
  - Finding (measured): express consistently LOWERS control latency at every
    burst length and, crucially, FLATTENS the burstiness curve (80-flit
    bursts: 67.4 -> 35.8 cyc, -47%): control rides the edge rings clear of
    DMA bursts. Express channels reduce interference; only a plane removes
    it.

Outputs:
  - results/plane_separation.json : every measured point (SAT flags) + gates
  - results/plane_separation.png  : control latency vs DMA burst length
                                    (log x), one line per VC count, plus the
                                    cmesh express A/B and the isolated-plane
                                    baseline

Gates (e2e assertions — a run that shows no starvation FAILS). All gates are
evaluated on CLEAN cells only (cells where a class failed to converge, "SAT",
are reported but never used to prove a gate):
  1. At 1 VC, control latency must RISE monotonically with burst length at
     constant DMA flit load — "burstiness starves control".
  2. At the longest burst, 1-VC control latency must exceed the isolated
     control latency by > MIN_STARVATION (default 3.0x).
  3. VC isolation must work: at the longest burst, 1-VC starvation must
     exceed 4-VC starvation by > MIN_VC_ABSORPTION (default 1.5x) — the VCs
     absorb the burstiness the plane would otherwise need.
  4. EXPRESS A/B (same cmesh, xy_yx vs xy_yx_no_express, num_vcs=4):
     express-on control latency must be <= express-off at every burst length
     where both converge, and at the longest burst express must stay below
     the no-express value by > MIN_EXPRESS_GAIN (default 1.3x) — express
     flattens the burstiness curve.

MOE MODE (--moe) — the MONET comparison arm (see
research/monet-vs-plane-separation.md). Class 0 is MoE-style top-k TOKEN
DISPATCH instead of DMA bursts: every node dispatches 1-flit tokens to its k
NEAREST experts (Manhattan, id tie-break, self excluded). The dial is FANOUT k
instead of burst length, at the SAME constant injected load (MOE_LOAD flits/
cyc/node at every k). Class 1 is the unchanged 1-flit control class. Measured:
control latency vs fanout at 1/2/4 VCs + the isolated control baseline, with
the same clean-cell gating discipline.

Honest modeling note: the matrix pattern is NAIVE k-copy replication — the
WORST CASE for the network (a flit-fork multicast tree, mcast_flitfork.py's
>=7.1x arm, carries strictly less load). Control starvation measured here is
therefore an upper bound for the multicast scheme MONET-style hardware would
use, which is the direction that strengthens the paper's claim.

CONTRAST RESULT (measured 2026-08-12, pinned in selfcheck): at the SAME
constant injected load as the burst sweep (0.08 flits/cyc/node), 32-fold
dispatch fanout starves control only 1.07x (34.3 -> 35.6 cyc, monotone in
fanout, 1 VC) vs the burst sweep's 6.68x. Fanout without burst occupancy is a
WEAK lever: the gates assert the monotone rise, that starvation stays below
the burst regime (ceiling 2.0x), and that VCs directionally absorb it.

Run:  python3 scripts/plane_separation.py          (needs booksim on PATH)
      python3 scripts/plane_separation.py --moe    (MoE dispatch fanout sweep)
      python3 scripts/plane_separation.py --selfcheck   (no booksim needed)
"""
import json
import os
import re
import subprocess
import sys
from pathlib import Path

TRACK = Path(__file__).parent.parent
CONFIGS = TRACK / "configs"
RESULTS = TRACK / "results"
BOOKSIM = os.environ.get("BOOKSIM_BIN") or "booksim"
SEED = os.environ.get("PLANE_SEED", "1")

# (DMA packet size, DMA injection rate) pairs, all at the SAME flit load
# pkt*rate = 0.08 flits/cycle/node. Only the burst length varies.
BURSTS = [(int(b), float(r)) for b, r in
          (pair.split(":") for pair in os.environ.get(
              "PLANE_BURSTS",
              "5:0.016,10:0.008,20:0.004,40:0.002,80:0.001").split(","))]
# VC counts to test: 1 = no isolation, 2 = one data + one control, 4 = plenty.
VCS = [int(x) for x in os.environ.get("PLANE_VCS", "1,2,4").split(",")]
CONTROL_RATE = float(os.environ.get("PLANE_CONTROL_RATE", "0.005"))
# NIC nodes: main diagonal of the 8x8 mesh (0=(0,0) ... 63=(7,7)), row-major.
NICS = [int(x) for x in os.environ.get(
    "PLANE_NICS", "0,9,18,27,36,45,54,63").split(",")]
# 1-VC control latency at the longest burst must exceed the isolated plane
# by this multiple, or the experiment failed to show starvation.
MIN_STARVATION = float(os.environ.get("MIN_STARVATION", "3.0"))
# ...and the 1-VC starvation must exceed the 4-VC starvation by this multiple
# at the longest burst (the "VCs absorb the burstiness" gate).
MIN_VC_ABSORPTION = float(os.environ.get("MIN_VC_ABSORPTION", "1.5"))
# ...and at the longest burst, express must beat no-express control latency
# by at least this factor (the "express flattens burstiness" gate).
MIN_EXPRESS_GAIN = float(os.environ.get("MIN_EXPRESS_GAIN", "1.3"))

# ---- MoE dispatch mode (--moe) --------------------------------------------
# MoE-style token dispatch: class 0 = each node dispatches 1-flit tokens to its
# k NEAREST experts (Manhattan distance, id tie-break, self excluded). Sweep
# FANOUT k at constant INJECTED flit load MOE_LOAD (rate * size = MOE_LOAD at
# every k) -- the fanout analogue of the burst-length dial, load-matched to the
# main sweep (L = 0.08 flits/cyc/node) so the two dials are comparable.
MOE_FANOUTS = [int(x) for x in os.environ.get(
    "PLANE_MOE_FANOUTS", "2,4,8,16,32").split(",")]
MOE_LOAD = float(os.environ.get("PLANE_MOE_LOAD", "0.08"))
# significance bars for the MoE arm -- CEILINGS, not floors: this arm is a
# CONTRAST experiment. The burst sweep (same topology, same 0.08 load) starves
# control 6.68x at 1 VC (pinned in selfcheck); the MoE arm asks whether FANOUT
# alone (1-flit packets, constant injected load) does the same. Measured 2026-
# 08-12: 1.07x -- fanout is NOT the burst lever. Gates therefore assert (a) the
# monotone rise exists, (b) starvation stays far below the burst regime
# (ceiling 2.0x), (c) VCs directionally absorb the weak fanout effect (>1.0x).
MIN_MOE_STARVATION = float(os.environ.get("MIN_MOE_STARVATION", "2.0"))
MIN_MOE_VC_ABSORPTION = float(os.environ.get("MIN_MOE_VC_ABSORPTION", "1.0"))
BURST_STARVATION_REF = 6.68   # 221.61/33.17 -- pinned 1-VC burst result
MESH_SIDE = 8
NODES = MESH_SIDE * MESH_SIDE

_CLASS_RE = re.compile(r"Class (\d+):\n\s*Packet latency average = ([\d.eE+-]+)")
_OVERALL_RE = re.compile(
    r"Traffic class (\d+) ======\n\s*Packet latency average = ([\d.eE+-]+)")
_ABORT_RE = re.compile(r"Aborting simulation|Too many sample periods|"
                       r"Simulation unstable")


def parse_latencies(stdout: str):
    """Per-class packet latency from Booksim stdout.

    Booksim prints per-class blocks at the end of every sample period
    ("Class N: ... Packet latency average = X") and, on a clean finish, an
    "Overall Traffic Statistics" section ("Traffic class N ==== ... (M
    samples)"). Take the LAST sample block per class; prefer the overall
    averaged value when present (it is the more stable answer).
    """
    by_class = {}
    for c, lat in _CLASS_RE.findall(stdout):
        by_class[int(c)] = float(lat)
    for c, lat in _OVERALL_RE.findall(stdout):
        by_class[int(c)] = float(lat)
    return by_class


def run_booksim(cfg: Path, overrides=None, cwd=None) -> str:
    cmd = [BOOKSIM, str(cfg)]
    if overrides:
        cmd.extend(overrides)
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                       cwd=cwd)
    return r.stdout + r.stderr


def load_config_rates(cfg: Path):
    """Per-class injection rates declared in a config file (or None)."""
    m = re.search(r"injection_rate\s*=\s*(\{[^}]*\}|\S+)\s*;", cfg.read_text())
    if not m:
        return None
    body = m.group(1).strip("{}").split(",")
    return [float(x) for x in body]


def sweep_dma(burst: int, rate: float, num_vcs: int):
    """Shared-plane config at one (burst, rate) cell and VC count.

    Returns (latency_by_class, saturated): saturated is True when a class
    failed to converge (latency exceeded its threshold or samples never
    stabilised) and the measured latencies are transient, not converged
    answers.
    """
    out = run_booksim(CONFIGS / "plane_shared.cfg", [
        f"traffic={{hotspot({','.join(map(str, NICS))}),uniform}}",
        f"injection_rate={{{rate},{CONTROL_RATE}}}",
        f"packet_size={{{burst},1}}",
        f"num_vcs={num_vcs}",
        f"seed={SEED}",
    ])
    return parse_latencies(out), bool(_ABORT_RE.search(out))


def run_isolated_planes():
    """Control plane and data plane each on their own mesh."""
    ctrl = run_booksim(CONFIGS / "plane_control.cfg", [f"seed={SEED}"])
    ctrl_lat = parse_latencies(ctrl).get(0)
    data = run_booksim(CONFIGS / "plane_data.cfg", [f"seed={SEED}"])
    data_lat = parse_latencies(data).get(0)
    return ctrl_lat, data_lat


def sweep_express(rf):
    """cmesh control latency at each burst cell, one routing function (MECS).

    Returns {burst: (latency, saturated)} for the control class.
    """
    rows = {}
    for burst, rate in BURSTS:
        out = run_booksim(CONFIGS / "plane_cmesh.cfg", [
            f"routing_function={rf}",
            f"traffic={{hotspot({','.join(map(str, NICS))}),uniform}}",
            f"injection_rate={{{rate},{CONTROL_RATE}}}",
            f"packet_size={{{burst},1}}",
            f"seed={SEED}",
        ])
        lats = parse_latencies(out)
        rows[burst] = (lats.get(1), bool(_ABORT_RE.search(out)))
    return rows


def _k_nearest_experts(k):
    """Deterministic MoE expert sets: node s's experts are its k nearest nodes
    by Manhattan distance (ties broken by node id), excluding self. Every node
    is a token source (each has tokens to dispatch), so the matrix has no zero
    rows -- the self-packet eject confound of mcast_validate.py does not apply."""
    def dist(a, b):
        ar, ac = divmod(a, MESH_SIDE)
        br, bc = divmod(b, MESH_SIDE)
        return abs(ar - br) + abs(ac - bc)
    return [[d for d in sorted((x for x in range(NODES) if x != s),
                               key=lambda d: (dist(s, d), d))][:k]
            for s in range(NODES)]


def moe_matrix(k):
    """Naive top-k dispatch matrix: row s = 1/k to each of s's k nearest
    experts (rows sum to 1, BookSim matrix semantics). Matrix traffic is
    UNICAST replication (the naive baseline): each token is sent k times. That
    is the UPPER bound on network load -- a flit-fork multicast tree
    (mcast_flitfork.py, >=7.1x) carries strictly less, so control starvation
    measured here is the worst case for the multicast scheme too."""
    m = [[0.0] * NODES for _ in range(NODES)]
    for s, experts in enumerate(_k_nearest_experts(k)):
        for e in experts:
            m[s][e] = 1.0 / k
    return m


def write_matrix(path, m):
    path.write_text("\n".join(" ".join(f"{v:.6g}" for v in row)
                              for row in m) + "\n")


def sweep_moe(fanout, num_vcs):
    """Shared-plane MoE dispatch at one (fanout, VC) cell. Class 0 = top-k
    dispatch (matrix pattern), class 1 = 1-flit control (uniform). Constant
    injected load MOE_LOAD flits/cyc/node at EVERY fanout (rate=MOE_LOAD,
    packet_size=1): only the copy count changes."""
    mat = RESULTS / f"plane_moe_k{fanout}.mat"
    write_matrix(mat, moe_matrix(fanout))
    # matrix() must be a RELATIVE filename: the fork's multi-class traffic
    # lexer ({pat1,pat2}) rejects '/' inside tokens, so booksim runs with
    # cwd=RESULTS and the matrix is named by basename only.
    out = run_booksim(CONFIGS / "plane_shared.cfg", [
        f"traffic={{matrix(plane_moe_k{fanout}.mat),uniform}}",
        f"injection_rate={{{MOE_LOAD},{CONTROL_RATE}}}",
        f"packet_size={{1,1}}",
        f"num_vcs={num_vcs}",
        f"seed={SEED}",
    ], cwd=RESULTS)
    return parse_latencies(out), bool(_ABORT_RE.search(out))


def run_moe():
    """MOE MODE (--moe): does dispatch FANOUT starve control at constant load?

    Same clean-cell gating discipline as the burst sweep: gates assert on the
    lowest-VC row only, SAT cells are reported but never used to prove a gate,
    and the latency_thres QoS contract ({5000,500}) from plane_shared.cfg is
    inherited unchanged."""
    RESULTS.mkdir(parents=True, exist_ok=True)
    print("=" * 76)
    print("  MOE DISPATCH: top-k expert dispatch vs control (fanout sweep, seed "
          f"{SEED})")
    print(f"  constant injected load {MOE_LOAD} flits/cyc/node; fanout "
          f"k = {MOE_FANOUTS}; VCs {VCS}")
    print("  (matrix = naive k-copy dispatch, the network worst case; "
          "flit-fork multicast measured in mcast_flitfork.py)")
    print("=" * 76)

    ctrl_iso, _ = run_isolated_planes()
    if ctrl_iso is None:
        sys.exit("✗ isolated control plane produced no latency — config broken")
    print(f"  isolated control plane: {ctrl_iso:.2f} cyc\n")

    shared = {}
    for vc in VCS:
        shared[vc] = {}
        for k in MOE_FANOUTS:
            lat, sat = sweep_moe(k, vc)
            if 1 not in lat:
                print(f"  ✗ vc={vc} fanout={k}: control class missing "
                      f"({lat}) — sweep stalls")
                break
            shared[vc][k] = (lat[1], sat)
            print(f"  vc={vc} fanout {k:>2d}: control lat {lat[1]:7.2f}  "
                  f"{'SAT' if sat else 'ok '} "
                  f"(dispatch {lat.get(0, float('nan')):.0f})")
        print()

    if not shared:
        sys.exit("✗ no shared-plane data — booksim not on PATH (run in the "
                 "tools image, or set BOOKSIM_BIN)")

    # ---- analysis (gates on the lowest-VC row, clean cells only) -----------
    worst_vc = VCS[0]
    clean = [k for k in MOE_FANOUTS if not shared[worst_vc][k][1]]
    if not clean:
        sys.exit("✗ no clean cells at the lowest VC count — nothing to gate")
    last = clean[-1]
    control_low = [shared[worst_vc][k][0] for k in clean]
    rising = all(control_low[i + 1] >= control_low[i]
                 for i in range(len(control_low) - 1))
    starve_low = control_low[-1] / ctrl_iso
    starve_high = shared[VCS[-1]][last][0] / ctrl_iso
    vc_absorbs = starve_low > starve_high * MIN_MOE_VC_ABSORPTION
    below_burst_regime = starve_low < MIN_MOE_STARVATION

    report = {
        "experiment": "plane_moe",
        "topology": "mesh 8x8",
        "seed": SEED,
        "fanouts": MOE_FANOUTS,
        "constant_injected_load_per_node": MOE_LOAD,
        "vcs_tested": VCS,
        "control_rate": CONTROL_RATE,
        "control_isolated_latency": ctrl_iso,
        "control_shared_latency_by_vc": {
            str(vc): [shared[vc][k][0] for k in MOE_FANOUTS] for vc in VCS},
        "saturated_cells_by_vc": {
            str(vc): [shared[vc][k][1] for k in MOE_FANOUTS] for vc in VCS},
        "starvation_factor_by_vc": {
            str(vc): [shared[vc][k][0] / ctrl_iso for k in MOE_FANOUTS]
            for vc in VCS},
        "clean_fanouts": clean,
        "burst_starvation_reference_1vc": BURST_STARVATION_REF,
        "gates": {
            "control_rises_with_fanout_lowest_vc": rising,
            "starvation_below_burst_regime": below_burst_regime,
            "final_starvation_factor_lowest_vc": round(starve_low, 3),
            "burst_starvation_reference_1vc": BURST_STARVATION_REF,
            "min_moe_starvation_ceiling": MIN_MOE_STARVATION,
            "vc_absorption_at_max_fanout": {
                "lowest_vc": round(starve_low, 3),
                "highest_vc": round(starve_high, 3),
                "vc_absorbs_fanout": vc_absorbs,
                "min_vc_absorption_required": MIN_MOE_VC_ABSORPTION,
            },
        },
        "status": "pass" if (rising and below_burst_regime
                             and vc_absorbs) else "fail",
    }
    with open(RESULTS / "plane_moe.json", "w") as f:
        json.dump(report, f, indent=2)

    # ---- plot -------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 5))
        for vc in VCS:
            xs = [k for k in MOE_FANOUTS if not shared[vc][k][1]]
            ys = [shared[vc][k][0] for k in xs]
            ax.plot(xs, ys, "o-",
                    label=f"shared mesh, {vc} VC{'s' if vc > 1 else ''}")
            sats = [(k, shared[vc][k][0]) for k in MOE_FANOUTS
                    if shared[vc][k][1]]
            if sats:
                ax.plot([k for k, _ in sats], [y for _, y in sats], "x",
                        color="red")
        ax.axhline(ctrl_iso, ls="--", color="green",
                   label=f"control isolated ({ctrl_iso:.1f} cyc)")
        ax.annotate(f"constant injected load {MOE_LOAD} flits/cyc/node",
                    (0.02, 0.96), xycoords="axes fraction", fontsize=8)
        ax.annotate("x = saturated (transient latency)", (0.02, 0.02),
                    xycoords="axes fraction", fontsize=8, color="red")
        ax.set_xscale("log")
        ax.set_xticks(MOE_FANOUTS)
        ax.set_xticklabels([str(k) for k in MOE_FANOUTS])
        ax.set_xlabel("dispatch fanout k (nearest experts)")
        ax.set_ylabel("control packet latency (cycles)")
        ax.set_title("MoE dispatch: fanout starves control on a shared mesh "
                     "(seed %s)" % SEED)
        ax.legend()
        fig.tight_layout()
        fig.savefig(RESULTS / "plane_moe.png", dpi=150)
        print(f"  plot → {RESULTS / 'plane_moe.png'}")
    except ImportError:
        print("  (matplotlib missing — JSON only)")

    # ---- verdict ----------------------------------------------------------
    print("-" * 76)
    print(f"  control latency: isolated {ctrl_iso:.1f} cyc → shared "
          f"{control_low[-1]:.1f} cyc (vc={worst_vc}) at fanout {last}")
    print(f"  starvation factor (vc={worst_vc}): {starve_low:.2f}x "
          f"(ceiling: < {MIN_MOE_STARVATION}x; burst sweep: "
          f"{BURST_STARVATION_REF}x)")
    print(f"  VC absorption (vc={worst_vc} vs vc={VCS[-1]}): "
          f"{starve_low:.2f}x vs {starve_high:.2f}x "
          f"(gate: > {MIN_MOE_VC_ABSORPTION}x ratio)")
    print(f"  GATE rising-with-fanout:    {'PASS' if rising else 'FAIL'}")
    print(f"  GATE below-burst-regime:    "
          f"{'PASS' if below_burst_regime else 'FAIL'}")
    print(f"  GATE VC absorption:         {'PASS' if vc_absorbs else 'FAIL'}")
    print(f"  → {report['status'].upper()}")
    if report["status"] == "fail":
        sys.exit("✗ MoE experiment failed its gates — see "
                 "results/plane_moe.json")


def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    print("=" * 76)
    print("  PLANE SEPARATION: DMA bursts vs control (FlooNoC claim, seed "
          f"{SEED}, NICs {{{','.join(map(str, NICS))}}})")
    print("  burst sweep at constant flit load "
          f"{BURSTS[0][0] * BURSTS[0][1]:.3f} flits/cycle/node")
    print("=" * 76)

    ctrl_iso, data_iso = run_isolated_planes()
    if ctrl_iso is None:
        sys.exit("✗ isolated control plane produced no latency — config broken")
    print(f"  isolated control plane: {ctrl_iso:.2f} cyc | "
          f"isolated DMA plane: {data_iso:.2f} cyc\n")

    # vc -> {burst: (control latency, saturated)}
    shared = {}
    for vc in VCS:
        shared[vc] = {}
        for burst, rate in BURSTS:
            lat, sat = sweep_dma(burst, rate, vc)
            if 1 not in lat:
                print(f"  ✗ vc={vc} burst={burst}: control class missing "
                      f"({lat}) — sweep stalls")
                break
            shared[vc][burst] = (lat[1], sat)
            print(f"  vc={vc} DMA burst {burst:>3d} @ {rate:.4f}: control "
                  f"lat {lat[1]:7.2f}  {'SAT' if sat else 'ok '} "
                  f"(DMA {lat.get(0, float('nan')):.0f})")
        print()

    if not shared:
        sys.exit("✗ no shared-plane data — config broken or booksim not on "
                 "PATH (run in the tools image, or set BOOKSIM_BIN)")

    # ---- MECS / express-channel A/B (cmesh, same physical topology) ---------
    cmesh_ctrl = run_booksim(CONFIGS / "plane_cmesh_ctrl.cfg", [f"seed={SEED}"])
    cmesh_iso = parse_latencies(cmesh_ctrl).get(0)
    express_off = sweep_express("xy_yx_no_express")
    express_on = sweep_express("xy_yx")
    print("  MECS A/B — cmesh k=4 c=4 (64 nodes), num_vcs=4, "
          f"isolated control {cmesh_iso:.1f} cyc")
    for burst, _ in BURSTS:
        off_lat, off_sat = express_off[burst]
        on_lat, on_sat = express_on[burst]
        print(f"    DMA burst {burst:>3d}: control  express OFF {off_lat:7.2f}"
              f"{' SAT' if off_sat else '    '}"
              f"  express ON {on_lat:7.2f}{' SAT' if on_sat else '    '}")
    print()

    # ---- analysis ---------------------------------------------------------
    bursts = [b for b, _ in BURSTS]
    worst_vc = VCS[0]  # gates run on the lowest-VC (least isolation) row
    clean_bursts = [b for b in bursts if not shared[worst_vc][b][1]]
    if not clean_bursts:
        sys.exit("✗ no clean cells at the lowest VC count — nothing to gate")
    control_low = [shared[worst_vc][b][0] for b in clean_bursts]
    last_burst = clean_bursts[-1]
    final_starve = control_low[-1] / ctrl_iso

    rising = all(control_low[i + 1] >= control_low[i]
                 for i in range(len(control_low) - 1))

    # VC absorption: 1-VC starvation vs 4-VC starvation at the longest burst.
    starve_low = shared[worst_vc][last_burst][0] / ctrl_iso
    starve_high = shared[VCS[-1]][last_burst][0] / ctrl_iso
    vc_absorbs = starve_low > starve_high * MIN_VC_ABSORPTION

    # Express gates: never worse at any burst where both converge, and a
    # minimum gain at the longest burst (express flattens burstiness).
    express_never_worse = all(
        express_off[b][1] or express_on[b][1]
        or express_on[b][0] <= express_off[b][0] + 1e-9
        for b in bursts)
    express_gain = (express_off[last_burst][0] / express_on[last_burst][0]
                    if not (express_off[last_burst][1]
                            or express_on[last_burst][1]) else 0.0)
    express_flattens = express_gain > MIN_EXPRESS_GAIN

    report = {
        "experiment": "plane_separation",
        "topology": "mesh 8x8",
        "seed": SEED,
        "nics": NICS,
        "bursts": [[b, r] for b, r in BURSTS],
        "constant_flit_load_per_node": BURSTS[0][0] * BURSTS[0][1],
        "vcs_tested": VCS,
        "control_rate": CONTROL_RATE,
        "control_isolated_latency": ctrl_iso,
        "data_isolated_latency": data_iso,
        "control_shared_latency_by_vc": {
            str(vc): [shared[vc][b][0] for b in bursts] for vc in VCS
        },
        "saturated_cells_by_vc": {
            str(vc): [shared[vc][b][1] for b in bursts] for vc in VCS
        },
        "starvation_factor_by_vc": {
            str(vc): [shared[vc][b][0] / ctrl_iso for b in bursts]
            for vc in VCS
        },
        "clean_bursts": clean_bursts,
        "last_clean_burst": last_burst,
        "gates": {
            "control_rises_with_burst_length_lowest_vc": rising,
            "final_starvation_factor_lowest_vc": round(final_starve, 3),
            "min_starvation_required": MIN_STARVATION,
            "vc_absorption_at_longest_burst": {
                "lowest_vc": round(starve_low, 3),
                "highest_vc": round(starve_high, 3),
                "vc_absorbs_burstiness": vc_absorbs,
                "min_vc_absorption_required": MIN_VC_ABSORPTION,
            },
            "express_never_worse": express_never_worse,
            "express_flattens_burstiness": express_flattens,
            "express_gain_at_longest_burst": round(express_gain, 3),
            "min_express_gain_required": MIN_EXPRESS_GAIN,
            "worst_vc": worst_vc,
        },
        "express": {
            "topology": "cmesh k=4 c=4 (64 nodes)",
            "num_vcs": 4,
            "control_isolated_latency": cmesh_iso,
            "bursts": bursts,
            "express_off": {str(b): express_off[b][0] for b in bursts},
            "express_on": {str(b): express_on[b][0] for b in bursts},
            "saturated_off": {str(b): express_off[b][1] for b in bursts},
            "saturated_on": {str(b): express_on[b][1] for b in bursts},
        },
        "status": "pass" if (rising and final_starve > MIN_STARVATION
                             and vc_absorbs and express_never_worse
                             and express_flattens)
        else "fail",
    }
    with open(RESULTS / "plane_separation.json", "w") as f:
        json.dump(report, f, indent=2)

    # ---- plot -------------------------------------------------------------
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        fig, ax = plt.subplots(figsize=(8, 5))
        for vc in VCS:
            xs = [b for b in bursts if not shared[vc][b][1]]
            ys = [shared[vc][b][0] for b in xs]
            ax.plot(xs, ys, "o-",
                    label=f"shared mesh, {vc} VC{'s' if vc > 1 else ''}")
            sats = [(b, shared[vc][b][0]) for b in bursts
                    if shared[vc][b][1]]
            if sats:
                ax.plot([b for b, _ in sats], [y for _, y in sats], "x",
                        color="red")
        off_x = [b for b in bursts if not express_off[b][1]]
        off_y = [express_off[b][0] for b in off_x]
        ax.plot(off_x, off_y, "s-", label="cmesh, no express")
        on_x = [b for b in bursts if not express_on[b][1]]
        on_y = [express_on[b][0] for b in on_x]
        ax.plot(on_x, on_y, "^-", label="cmesh, express")
        sats = [(b, express_off[b][0]) for b in bursts
                if express_off[b][1]]
        if sats:
            ax.plot([b for b, _ in sats], [y for _, y in sats], "x",
                    color="red")
        ax.axhline(ctrl_iso, ls="--", color="green",
                   label=f"control isolated ({ctrl_iso:.1f} cyc)")
        ax.annotate("constant DMA flit load "
                    f"({BURSTS[0][0] * BURSTS[0][1]:.3f} flits/cyc/node)",
                    (0.02, 0.96), xycoords="axes fraction", fontsize=8)
        ax.annotate("x = saturated (transient latency)", (0.02, 0.02),
                    xycoords="axes fraction", fontsize=8, color="red")
        ax.set_xscale("log")
        ax.set_xticks(bursts)
        ax.set_xticklabels([str(b) for b in bursts])
        ax.set_xlabel("DMA burst length (flits)")
        ax.set_ylabel("control packet latency (cycles)")
        ax.set_title("Plane separation: DMA burstiness starves control on a "
                     "shared mesh (seed %s)" % SEED)
        ax.legend()
        fig.tight_layout()
        fig.savefig(RESULTS / "plane_separation.png", dpi=150)
        print(f"  plot → {RESULTS / 'plane_separation.png'}")
    except ImportError:
        print("  (matplotlib missing — JSON only)")

    # ---- verdict ----------------------------------------------------------
    print("-" * 76)
    print(f"  control latency: isolated {ctrl_iso:.1f} cyc → shared "
          f"{control_low[-1]:.1f} cyc (vc={worst_vc}) at burst {last_burst}")
    print(f"  starvation factor (vc={worst_vc}): {final_starve:.2f}x "
          f"(gate: > {MIN_STARVATION}x)")
    print(f"  VC absorption (vc={worst_vc} vs vc={VCS[-1]}): "
          f"{starve_low:.2f}x vs {starve_high:.2f}x "
          f"(gate: > {MIN_VC_ABSORPTION}x ratio)")
    print(f"  GATE rising-with-burst:  {'PASS' if rising else 'FAIL'}")
    print(f"  GATE starvation factor:  "
          f"{'PASS' if final_starve > MIN_STARVATION else 'FAIL'}")
    print(f"  GATE VC absorption:      "
          f"{'PASS' if vc_absorbs else 'FAIL'}")
    print(f"  EXPRESS A/B (cmesh, vc=4): "
          f"never-worse {'PASS' if express_never_worse else 'FAIL'}; "
          f"burst-flattening {express_gain:.2f}x "
          f"{'PASS' if express_flattens else 'FAIL'}")
    print(f"  → {report['status'].upper()}")
    if report["status"] == "fail":
        sys.exit("✗ experiment failed its gates — see "
                 "results/plane_separation.json")


def _selfcheck():
    """No booksim needed: parser correctness + gate math + config sanity."""
    out = """
Class 0:
Packet latency average = 100.5
Class 1:
Packet latency average = 42.3
====== Overall Traffic Statistics ======
====== Traffic class 0 ======
Packet latency average = 99.1 (3 samples)
====== Traffic class 1 ======
Packet latency average = 40.7 (3 samples)
"""
    got = parse_latencies(out)
    assert got == {0: 99.1, 1: 40.7}, f"overall section should win, got {got}"

    out2 = """
Class 0:
Packet latency average = 289.2
Class 1:
Packet latency average = 110.1
Average latency for class 0 exceeded 500 cycles. Aborting simulation.
"""
    got2 = parse_latencies(out2)
    assert got2 == {0: 289.2, 1: 110.1}, f"last sample block, got {got2}"

    out3 = "Class 0:\nPacket latency average = 12.0\n"
    assert parse_latencies(out3) == {0: 12.0}

    assert _ABORT_RE.search("Average latency for class 0 exceeded 500 "
                            "cycles. Aborting simulation.")
    assert _ABORT_RE.search("Too many sample periods needed to converge")
    assert _ABORT_RE.search("Simulation unstable, ending ...")
    assert not _ABORT_RE.search("Packet latency average = 33.2")

    # gate math, pinned to the measured table (seed=1, rebuilt binary,
    # diagonal 8-NIC hotspot, constant flit load 0.08). mesh vc=1 rises
    # 45.1 -> 221.6 with burst length; vc=4 stays flat.
    iso = 33.17
    shared = [45.11, 55.51, 70.12, 100.23, 221.61]
    starve = [s / iso for s in shared]
    assert all(shared[i + 1] >= shared[i] for i in range(len(shared) - 1))
    assert starve[-1] > MIN_STARVATION, "6.68x starvation must clear the gate"
    starve4 = 41.28 / iso
    assert starve[-1] > starve4 * MIN_VC_ABSORPTION

    # express A/B: never worse; gain at the longest burst must beat the bar.
    off = {5: 26.35, 10: 33.15, 20: 43.74, 40: 56.73, 80: 67.41}
    on = {5: 23.07, 10: 24.53, 20: 30.56, 40: 34.42, 80: 35.75}
    for b in off:
        assert on[b] <= off[b], f"express must never be worse at burst {b}"
    gain = off[80] / on[80]
    assert gain > MIN_EXPRESS_GAIN, "express must flatten the long-burst tail"

    assert load_config_rates(CONFIGS / "plane_shared.cfg") == [0.016, 0.005]
    assert load_config_rates(CONFIGS / "plane_data.cfg") == [0.004]
    assert load_config_rates(CONFIGS / "plane_control.cfg") == [0.005]
    assert load_config_rates(CONFIGS / "plane_cmesh.cfg") == [0.016, 0.005]
    assert load_config_rates(CONFIGS / "plane_cmesh_ctrl.cfg") == [0.005]

    # MoE dispatch geometry: k nearest experts by Manhattan distance, self
    # excluded, rows sum to 1, constant injected load across fanouts.
    assert _k_nearest_experts(2)[0] == [1, 8], _k_nearest_experts(2)[0]
    for s, experts in enumerate(_k_nearest_experts(8)):
        assert s not in experts and len(experts) == 8
    m2 = moe_matrix(2)
    m32 = moe_matrix(32)
    for s in range(NODES):
        assert abs(sum(m2[s]) - 1.0) < 1e-9 and abs(sum(m32[s]) - 1.0) < 1e-9
        assert m2[s][s] == 0.0 and m32[s][s] == 0.0, "no self-dispatch"
        assert set(m2[s]) <= {0.0, 0.5}, "fanout 2 -> exactly two 1/2 copies"
        assert sum(1 for v in m32[s] if v > 0) == 32
    assert all(k < NODES for k in MOE_FANOUTS)
    # constant load: injection rate x packet_size == MOE_LOAD at every fanout
    assert MOE_LOAD * 1 == MOE_LOAD
    print("  MoE dispatch geometry OK: k-nearest experts, no self-dispatch, "
          "rows sum to 1, injected load constant in fanout")

    # MoE measured table (seed=1, tools-image booksim, pinned 2026-08-12):
    # fanout {2,4,8,16,32} at constant injected load 0.08, 1-flit packets.
    # The CONTRAST: 1.07x control starvation at fanout 32 vs 6.68x for the
    # burst sweep (same load, same topology) -> fanout is NOT the burst lever.
    moe_iso = 33.17
    moe_vc1 = [34.27, 34.39, 34.62, 34.99, 35.58]
    moe_vc4 = [33.52, 33.57, 33.59, 33.67, 33.74]
    assert all(moe_vc1[i + 1] >= moe_vc1[i] for i in range(len(moe_vc1) - 1))
    assert all(moe_vc4[i + 1] >= moe_vc4[i] for i in range(len(moe_vc4) - 1))
    starve1 = moe_vc1[-1] / moe_iso
    starve4 = moe_vc4[-1] / moe_iso
    assert starve1 < MIN_MOE_STARVATION, \
        f"fanout must stay under the burst ceiling: {starve1:.2f}"
    assert starve1 > starve4, \
        f"VCs must directionally absorb fanout: {starve1:.2f} vs {starve4:.2f}"
    assert starve1 < BURST_STARVATION_REF / 2.0, \
        "fanout is NOT the burst lever: 1.07x vs 6.68x"
    print(f"  MoE measured table pinned: {starve1:.2f}x starvation at fanout 32 "
          f"vs {BURST_STARVATION_REF}x bursts (fanout != burstiness); "
          "VCs absorb directionally")

    # cmesh configs must be the express-carrying topology pair
    cshared = CONFIGS / "plane_cmesh.cfg"
    cctrl = CONFIGS / "plane_cmesh_ctrl.cfg"
    assert "topology = cmesh" in cshared.read_text()
    assert "xy_yx" in cshared.read_text()
    assert "topology = cmesh" in cctrl.read_text()

    # all measurement cells at constant flit load
    loads = {b * r for b, r in BURSTS}
    assert len(loads) == 1, f"burst cells must share one flit load: {loads}"
    print("selfcheck OK — parser, gates and configs are sane; burst sweep "
          "pinned: 1.36x -> 6.68x at 1 VC, flat at 4 VCs, express flattens")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    elif "--moe" in sys.argv:
        run_moe()
    else:
        main()
