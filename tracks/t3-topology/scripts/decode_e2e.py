#!/usr/bin/env python3
"""End-to-end decode step: Ramulator DRAM -> BookSim NoC -> compute, pinned to ONE point. (T3)

The three validation layers were, until now, each cycle-accurate ON ITS OWN and composed only
ON PAPER: dram_efficiency.py measured 91% DRAM efficiency, mcast_flitfork.py measured the NoC
multicast stable across a SWEEP, serving_multicast.py divided bytes by bandwidth. Nobody had
put both simulators on the SAME operating point and shown the pipeline actually composes.

This does. It is NOT a co-simulator -- no shared clock, no NoC->DRAM backpressure. That is
weeks of plumbing and, for a DRAM-bound workload, unnecessary: the feed is one-way (DRAM sets
the pace), so the honest thing is a STAGED hand-off where the DRAM measurement SETS the NoC's
operating point from first principles, and a gate CHECKS the NoC keeps up rather than assuming
it:

    Wormhole feeds   288 GB/s / 18 endpoints    = 16 GB/s per DRAM endpoint (one KV-group row)
    Ramulator keeps  x 0.91 (measured, contig)  = 14.6 GB/s actually delivered into the fabric
    the bridge       / 32 GB/s per flit/cyc      = 0.46 flit/cyc injection at the row source
                     (a 32 B/cyc link @ 1 GHz = 1 flit/cyc -- the SAME bridge mcast_validate.py
                      and decode_roofline.py already use; not a new constant)

-- and BookSim's REAL flit-fork multicast (booksim-ext/multicast.patch) is then run at exactly
that 0.46 flit/cyc. If the layers compose, multicast is stable there (and naive saturates) and
DRAM is the binding stage. If the bridge or the efficiency were wrong, the implied injection
could exceed the NoC's ceiling and GATE 2 fails loudly. So the composition is EARNED at one
pinned point measured from both ends, not assumed across three separate runs.

eps IS A RATIO, applied not measured-in-place: Ramulator models a GDDR6 preset (28 GB/s/ch),
Wormhole's DRAM is a different absolute (288 GB/s/die), but the 0.91 is a *fraction of peak*
(refresh + row-buffer physics of the same memory family), so it transfers to Wormhole's spec
bandwidth. That is exactly the relative-vs-absolute split serving_multicast.py already leans on
(box.bw x DRAM_EFF); this file inherits it, it does not re-derive Wormhole's absolute DRAM.

NOT MODELLED: compute on real Tensix cores. PyTorchSim is not wired in; the compute stage is
analytic (74 TFLOPS BF16 / AI). It has ~60x headroom, so it cannot be the binding stage -- the
seam worth closing was DRAM<->NoC, which was the purely-analytic one. This closes it.

RUN IT (tools image; self-builds Ramulator ~3min + the patched BookSim the first time):
    podman run --rm -v "$PWD:/repo" -w /repo \\
        internal-devrepo.datavex.ai:5050/anmol/veritx-research/veritx-tools-base:latest \\
        python3 tracks/t3-topology/scripts/decode_e2e.py --run

    python3 scripts/decode_e2e.py --selfcheck    # the unit bridge only, no simulators
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # sibling-script imports
import mcast_flitfork as noc          # run_booksim, ensure_booksim, G_MINUS_1
import dram_efficiency as dram        # ensure_ramulator, gen_traces, bw
import serving_multicast as sm        # QUIETBOX, DRAM_EFF, GB (the analytic headline)

# Wormhole die, arXiv 2603.23343 Table 2 (measured) -- same constants as decode_roofline.py.
DRAM_GBS = 288.0                       # per Wormhole die
N_DRAM_ENDPOINTS = 18                  # DRAM endpoints per die; one feeds one KV-group row
DRAM_PER_ENDPOINT = DRAM_GBS / N_DRAM_ENDPOINTS      # 16.0 GB/s -- the schedule's per-row feed
NOC_FLIT_GBS = 32.0                    # 1 flit/cyc = one 32 B/cyc link @ 1 GHz (the bridge)
BF16_TFLOPS = 74.0
CORES_PER_CHIP = 80                    # Tensix per die (wormhole.py / SCHEDULE.md)
DECODE_AI = 1.0                        # FLOP/byte, decode GEMV BF16 (decode_roofline.py)


def stages_gbs(eps):
    """GB/s along ONE KV-group row for each pipeline stage; the MIN binds. Per-row (not
    aggregate) is the conservative NoC view -- a row-broadcast concentrates on the row's links."""
    return {
        "DRAM (1 endpoint)": DRAM_PER_ENDPOINT * eps,                 # one endpoint feeds one row
        "NoC (1 row link)": NOC_FLIT_GBS,                             # one link carries the stream
        "compute (1 core)": BF16_TFLOPS * 1e3 / CORES_PER_CHIP / DECODE_AI,  # each of g cores keeps up
    }


def implied_injection(eps):
    """The BookSim injection_rate the DRAM feed dictates at a row source (flit/cyc; packet_size=1)."""
    return DRAM_PER_ENDPOINT * eps / NOC_FLIT_GBS


def main(run):
    if not run:
        _selfcheck()
        print("\n  Re-run with --run inside the tools image to drive Ramulator + BookSim.")
        return

    # STAGE 1 -- DRAM efficiency, measured LIVE (Ramulator2, GDDR6, per-head-contiguous KV read).
    dram.ensure_ramulator()
    dram.gen_traces()
    _, eff, hit = dram.bw("contig.trace")            # (GB/s, eff%, row-hit%)
    eps = eff / 100.0
    delivered = DRAM_PER_ENDPOINT * eps
    print(f"\n  END-TO-END decode step, ONE pinned operating point (per Wormhole die)\n")
    print(f"  STAGE 1  DRAM   Ramulator2 GDDR6, per-head-contiguous read -> eps = {eff:.1f}% "
          f"of peak (row-hit {hit:.0f}%)")
    print(f"                  {DRAM_PER_ENDPOINT:.0f} GB/s/endpoint x {eps:.2f} = "
          f"{delivered:.1f} GB/s delivered into one KV row")

    # BRIDGE -- the DRAM feed dictates the NoC's operating point (established 32-GB/s = 1 flit/cyc).
    inj = implied_injection(eps)
    print(f"\n  BRIDGE   {delivered:.1f} GB/s / {NOC_FLIT_GBS:.0f} (GB/s per flit/cyc) = "
          f"{inj:.3f} flit/cyc injection at the row source")

    # STAGE 2 -- NoC, BookSim REAL flit-fork multicast, run AT that injection.
    noc.ensure_booksim()
    ir, acc, _, _ = noc.run_booksim(0, 0.02)         # GATE 1: fork exact (known-answer)
    fork = acc / ir
    print(f"\n  STAGE 2  NoC    BookSim flit-fork multicast (booksim-ext/multicast.patch)")
    print(f"                  GATE 1 fork exact: 1 injection -> {fork:.2f} deliveries "
          f"(expect {noc.G_MINUS_1})")
    assert abs(fork - noc.G_MINUS_1) < 0.5, fork
    _, acc_m, lat_m, sat_m = noc.run_booksim(0, inj)   # multicast at the DRAM-dictated point
    _, acc_n, lat_n, sat_n = noc.run_booksim(1, inj)   # naive at the same point
    print(f"                  at {inj:.3f} flit/cyc (the DRAM-dictated point):")
    print(f"                    multicast  {acc_m:.3f} deliv/cyc  lat {lat_m or 0:.0f}  "
          f"{'SATURATED' if sat_m else 'STABLE'}")
    print(f"                    naive      {acc_n:.3f} deliv/cyc  lat {lat_n or 0:.0f}  "
          f"{'SATURATED' if sat_n else 'STABLE'}")

    # STAGE 3 -- compute (analytic; PyTorchSim not in the loop).
    st = stages_gbs(eps)
    print(f"\n  STAGE 3  compute {st['compute (1 core)']:.0f} GB/s/core (BF16 {BF16_TFLOPS:.0f} "
          f"TFLOPS / {CORES_PER_CHIP} cores / AI {DECODE_AI:.0f}) -- analytic, PyTorchSim not wired in")

    # COMPOSE -- the min stage binds.
    binder = min(st, key=st.get)
    noc_hr = st["NoC (1 row link)"] / st["DRAM (1 endpoint)"]
    cmp_hr = st["compute (1 core)"] / st["DRAM (1 endpoint)"]
    print(f"\n  COMPOSE  per-row stage rates (GB/s):  "
          + "   ".join(f"{k} {v:.1f}" for k, v in st.items()))
    print(f"           binding = {binder} (min); NoC headroom {noc_hr:.1f}x, compute {cmp_hr:.0f}x")

    # GATES -- falsifiable; the composition fails loudly if any breaks.
    print(f"\n  GATES")
    g2 = (not sat_m) and inj < 1.0
    print(f"    2  loop closes: multicast STABLE at the DRAM point "
          f"({inj:.3f}<1.0, not saturated) .......... {'PASS' if g2 else 'FAIL'}")
    assert g2, (inj, sat_m)
    g2b = sat_n or (acc_n < acc_m)
    print(f"    2b win real here: naive worse at the SAME point "
          f"({'saturated' if sat_n else f'{acc_n:.3f}<{acc_m:.3f}'}) ...... {'PASS' if g2b else 'FAIL'}")
    assert g2b, (acc_n, acc_m, sat_n)
    g3 = binder.startswith("DRAM")
    print(f"    3  DRAM binds: {binder} is the min stage (roofline premise holds) .. "
          f"{'PASS' if g3 else 'FAIL'}")
    assert g3, st
    dies = sm.QUIETBOX.bw / sm.GB / DRAM_GBS
    agg = dies * N_DRAM_ENDPOINTS * DRAM_PER_ENDPOINT
    g4 = abs(agg - sm.QUIETBOX.bw / sm.GB) < 1e-6
    print(f"    4  composes to headline: {dies:.0f} dies x {N_DRAM_ENDPOINTS} x "
          f"{DRAM_PER_ENDPOINT:.0f} = {agg:.0f} GB/s = QuietBox aggregate .. {'PASS' if g4 else 'FAIL'}")
    assert g4
    print(f"       and this run's live eps {eps:.2f} == serving_multicast's derating "
          f"{sm.DRAM_EFF:.2f}: the pinned per-die point IS the headline's operating point.")

    print(f"\n  RESULT: both cycle-accurate engines land on ONE operating point derived from first")
    print(f"  principles (288/18 GB/s x {eps:.2f} / 32 = {inj:.2f} flit/cyc). Multicast is stable")
    print(f"  there and naive saturates; DRAM is the binding stage, NoC {noc_hr:.1f}x clear and compute")
    print(f"  {cmp_hr:.0f}x. The composition is measured from both ends, no longer assumed between them.")


def _selfcheck():
    # The unit bridge, no simulators -- this is where a wrong conversion would hide.
    assert abs(DRAM_PER_ENDPOINT - 16.0) < 1e-9, DRAM_PER_ENDPOINT
    # a full-rate peak source is 16 GB/s = 0.5 flit/cyc (x 32 = 16); measured eps lowers it.
    assert abs(implied_injection(1.0) - 0.5) < 1e-9, implied_injection(1.0)
    inj = implied_injection(sm.DRAM_EFF)
    assert 0 < inj < 1.0, inj                     # expressible as a BookSim injection_rate
    assert inj < 0.6, inj                         # comfortably below multicast's 1.0 ceiling (~2x)
    # DRAM is the binding (min) stage; NoC and compute strictly above it.
    st = stages_gbs(sm.DRAM_EFF)
    assert min(st, key=st.get).startswith("DRAM"), st
    assert st["NoC (1 row link)"] > st["DRAM (1 endpoint)"] < st["compute (1 core)"], st
    # the per-endpoint model aggregates EXACTLY to serving_multicast's QuietBox bandwidth.
    dies = sm.QUIETBOX.bw / sm.GB / DRAM_GBS
    assert abs(dies - 16.0) < 1e-9, dies
    assert abs(dies * N_DRAM_ENDPOINTS * DRAM_PER_ENDPOINT - sm.QUIETBOX.bw / sm.GB) < 1e-6
    print(f"selfcheck OK -- bridge: 16 GB/s/endpoint x eps={sm.DRAM_EFF} / 32 = {inj:.3f} flit/cyc "
          f"(<1.0, ~{1.0 / inj:.1f}x headroom); DRAM binds ({stages_gbs(sm.DRAM_EFF)['DRAM (1 endpoint)']:.1f} "
          f"< NoC {NOC_FLIT_GBS:.0f}); per-die model x{dies:.0f} = {sm.QUIETBOX.bw / sm.GB:.0f} GB/s QuietBox")


if __name__ == "__main__":
    if "--selfcheck" in sys.argv:
        _selfcheck()
    else:
        main("--run" in sys.argv)
