# T3 — Phase 2: KV multicast across the NoC-to-NoC boundary (UCIe chiplet arrays)

Status: Gate-0 prior-art pass done 2026-08-05; first script selfcheck-green.

## Why this layer, why now

The die-level analysis (Phase 1, landed) settled the on-die topology question and the
Ethernet fabric question. The chiplet era makes the **package fabric** the 2026
battleground: UCIe is in mainstream production (AMD MI400: 12 chiplets; GB300: 2 reticle
dies + bridges; Apple M4 Ultra: 10 Tb/s die-to-die; Renesas X5H with UCIe chiplet
extensions). Industry framing, from the trade press (Electronic Design, 2026-06-29):

> "Don't treat die-to-die links as 'big wires.' Treat them as a network with congestion,
> traffic classes, and failure modes."

The Phase 1 mechanism — read KV once from DRAM, NoC-multicast to a row of cores (5.4×,
silicon-backed, vendor-shipped as PR #40733) — hits a wall at the die edge: a chain of
cores that spans two chiplets must cross a UCIe bridge. The open question this arc owns:

**Does the g-fold win survive the bridge, and where must the bridge sit for it to?**

## Gate-0 prior-art (2026-08-05): the slice is open, with occupants

| Published | What they own | Not covered |
|---|---|---|
| CINT-AD (2025, SciDirect) | Automated interposer **topology** generation + deadlock-free routing | Traffic-class (multicast) design, port placement |
| HPCA 2026 | Deadlock-free **coherence bridge** module | Data-plane multicast across the bridge |
| GLSVLSI 2025 (arXiv 2504.04005) | Coherence-aware **routing** + topology selection, on-die | Cross-boundary multicast, serving traffic |
| TACO 2024 | Coherence **security** on interposer NoCs | — |
| 3DLS (arXiv 2607.01617) | Chiplet LLM serving, traffic-class separation | The multicast mechanism + placement law |
| TPLA (arXiv 2508.15881) | Disaggregated prefill/decode + MLA; states the "each device loads the full cache" problem, solves it algorithmically | A NoC distribution mechanism (software solution only) |
| PTStore (arXiv 2607.22648) | Distributed prefix KV caching + replication, CDN-style, at rack/node level | Chip-to-chip fabric mechanism |
| Synopsys/Arteris/Cadence IP | Products, not analysis | — |

No work found that analyzes **multicast fork placement across a NoC-to-NoC bridge** for
serving traffic, or derives a **bridge-port placement law** from a KV multicast matrix.
That is the slice.

**Gate-0 refresh (2026-08-12, `docs/research/cross-node-kv-distribution-2026.md`):** a
primary-source pass confirmed (a) Google TPU 8i discloses a *capacity* KV solution (384 MB
on-chip SRAM, "KV entirely on silicon") with no disclosed cross-chip distribution
mechanism — CAE is collectives, not KV distribution; (b) arXiv shows zero hits for
KV+NoC, UCIe+NoC+multicast, and LLM-serving+multicast+topology — the fetch-once-multicast-
many primitive at the chip-to-chip rung is unclaimed. 3DLS and TPLA name the redundant-
transfer problem and solve it with 3D stacking / latent attention respectively; neither
owns a NoC multicast-fork mechanism. Do NOT claim "Google reloads KV per chip" — that is
unverified (see doc §3, unsafe-claim list).

## The two mechanisms (the A/B that defines the arc)

For a KV row-multicast whose chain spans a die edge, with g cores on the remote die:

- **Source-fork:** sender replicates, bridge carries g copies → bridge demand ∝ g.
- **Bridge-fork:** bridge carries 1 copy, remote die's own NoC forks to g cores →
  bridge demand ∝ 1, remote NoC does the replication (the Phase-1 mechanism, continued).

Bridge-fork vs source-fork = the same g-fold ratio as Phase 1, now at the bridge — a
known-answer gate (g−1) we already own from PITFALLS §16.

## The placement law (Phase-1 rule transplanted to the die edge)

Phase 1 found: keep the KV row-multicast on NoC0 with a row-shared sender. At the die
edge this becomes: the bridge port must sit on the multicast row's axis of the remote
die's NoC, or the remote fork adds hops the bridge bandwidth just paid for. The
interposer bisection demand D(G) analog: port placement = the new design parameter.

## Measured result (2026-08-12, BookSim leg done)

Built `configs/booksim2_configs/bridged_2die.{cfg,anynet}` — two 8×8 meshes (128
routers) joined by ONE bridge link (row 7 ↔ row 0 at col 3), driven by the existing
flit-fork multicast with a new `mcast_offset` knob (die-A source → g die-B cores).
Required a fork-location fix in `iq_router.cpp`: the eject port was hardcoded to
`_outputs-1` (correct on a uniform mesh, WRONG on anynet where node channels come
first) — now found by scanning for the sink-less output channel. Mesh regression clean.

Saturation sweep (g=8 remote cores, KV row-multicast die A → die B, packet_size 1):

| rate | bridge-fork lat | source-fork lat |
|---|---|---|
| 0.008 | 78.0 | 80.5 |
| 0.016 | 77.9 | **119.7** (knee) |
| 0.032 | 78.6 | **497.7** (saturated) |
| 0.064 | 80.7 | 376.2 |
| 0.128 | 119.4 | 366.6 |

**Bridge-fork holds ~78-cycle latency flat to rate 0.064; source-fork saturates at
~0.016-0.032 (6.3× worse at the knee, 498 vs 79 cycles).** The g-fold known-answer
gate passes at the die boundary: the bridge (scarce resource) stays unsaturated when
it carries 1 copy and the remote die forks, exactly as the analytic model predicted.
Raw cells: `results/bridge_fork_sweep.json`, `results/bridge_fork_saturation.json`.

## Placement law — MEASURED (2026-08-12)
Single KV multicast stream, node 0 → 8 cores on die-B row 0, bridge-fork (1 copy
crosses). On-axis = bridge lands on die-B row 0 (15 hops); off-axis = lands on row 7,
stream climbs col 0 then sweeps (22 hops):

| rate | on-axis lat | off-axis lat | penalty |
|---|---|---|---|
| 0.002 | 67.0 | 102.0 | **35 cyc** |
| 0.008 | 67.0 | 102.0 | 35 cyc |
| 0.032 | 67.0 | 102.0 | 35 cyc |
| 0.064 | 67.0 | 102.0 | 35 cyc |

**The placement penalty is a constant 35 cycles (7 hops × ~5 cyc/hop), load-
independent, with identical acceptance at every load.** Off-axis placement taxes every
KV multicast crossing by the full die climb — a pure distance cost, no contention
component. Law: **the bridge port must sit on the multicast row's axis of the remote
die, or every crossing pays the die-height hop count.** (Earlier multi-source runs were
confounded: each die-A row multicast to a different die-B row, so placement helped some
rows and hurt others; `mcast_single=1` gates to one stream, the clean cell.)

**RTL-verified (2026-08-12):** the placement law now holds in RTL, not just BookSim.
The 2-die RTL (`rtl/noc_2die.sv` + fork in `rtl/router.sv`, see RTL-ARC.md §10a)
reproduces the same numbers to the cycle: on-axis first copy at T52, off-axis at T87 —
**35-cycle penalty, exactly the die-height hop cost.** Both cells deliver all 7 flits
with BookSim-exact pids. The g-fold gate passes at the RTL level.

## Work plan

1. `scripts/ucie_bridge_multicast.py` — bridge-fork vs source-fork demand, UCIe link
   budget (published PHY rates 16/32/40/64 Gb/s/lane, x8–x64 bridges), selfcheck-gated.
2. BookSim leg: extend the flit-fork multicast to a 2-die (bridge) topology — a bridge
   is a router hop with per-hop cost.
3. Placement law: bridge-port row/column placement vs remote-fork hop cost; energy via
   the calibrated Accelergy pipeline (FlooCNoC 1.37× anchor applies on-die; bridge cost
   from published UCIe pJ/bit, to be sourced, not assumed).
4. Write-up + handoffs as in Phase 1.

## Honesty gates (carried from Phase 1)

- Every number selfcheck-pinned or sourced; no UCIe pJ/bit until cited.
- The mechanism at die scale is vendor-shipped (PR #40733) — this arc's contribution is
  the bridge-level form and the placement law, not the mechanism.
- Known-answer gate (g−1) on every fork count, per PITFALLS §16.
