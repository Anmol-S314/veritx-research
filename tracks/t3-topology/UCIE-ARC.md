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
| Synopsys/Arteris/Cadence IP | Products, not analysis | — |

No work found that analyzes **multicast fork placement across a NoC-to-NoC bridge** for
serving traffic, or derives a **bridge-port placement law** from a KV multicast matrix.
That is the slice.

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
