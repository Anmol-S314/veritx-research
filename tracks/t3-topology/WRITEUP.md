# T3 — KV-Multicast Serving and the Die-to-Die Fabric: One-Page Write-up

Status: analysis complete and selfcheck-green; mechanism attribution corrected against
tt-metal (2026-08-04). Every number below is produced by a script with a passing
`--selfcheck`; nothing here is extrapolated beyond what the scripts compute.

---

## The question

For LLM inference serving on a die-array (Tenstorrent-class) box, where does the NoC
matter, what does it buy, and what happens when KV must cross the die boundary?

## The chain (each link independently verified)

1. **5.4× decode-serving win, silicon-backed** (`scripts/serving_multicast.py`,
   `hardware/`, `scripts/dram_efficiency.py`). Reading each KV block from DRAM once and
   NoC-multicasting it to a row of cores beats per-core re-fetch by up to **5.4×** at the
   Llama-3-70B / 32K / B=11 operating point on QuietBox (8× n300d-class). The multicast
   bandwidth is Tenstorrent's own measured silicon (`mcast_measured`: 29.79 B/cyc); the
   DRAM side is cycle-accurate Ramulator2, achieving **91%** of peak with per-head
   contiguous KV layout — **66%** with vLLM-style interleaved layout (a design rule, not
   an assumption).

2. **The NoC is never eliminated** (`scripts/decode_e2e.py`). The 5.4× lives on the
   intra-die NoC0 multicast floor; even after KV-local batch-split placement, decode e2e
   carries a measured NoC0 floor. The win survives as a *schedule* (which sequence's KV
   is multicast to which row), not as a topology.

3. **The fabric envelope** (`scripts/fabric_sweep.py`). Beyond ~37K-token context per
   sequence, KV must shard across dies and the Ethernet fabric loses: ~2.5 TB/s remote
   KV demand vs ~50 GB/s mesh bisection = **49× short**. The answer at QuietBox scale is
   "keep KV off the fabric" (batch-split, KV-local), not "which fabric".

4. **The crossover, exact** (`scripts/fabric_crossover.py`). If a future box shards KV:
   the mesh die-array is dead on any roadmap (needs 5 Tb/s-class ports); the viable
   shape is L=8 fat-tree, closing at **1.6T UEC/UALink (2026) for G≤2 die-pairs, 3.2T
   optics (2027) beyond**; mesh-vs-FFT hops corrected to exact 8/3 (mesh) and 4 (FFT);
   fabric energy delta is 157–394 W on a ~3 kW box (5–13%), SERDES hops only — the
   on-die 1.65× fat-tree penalty (FINDINGS) does not transfer.

5. **The placement law** (`scripts/die_to_die_matrix.py`). The 16×16 KV-multicast matrix
   derives the demand law D(G) = KV·(G−1)/G: **G=2 closes the 2026 1.6T fabric at ~74K
   token context; G=4 needs 2027 3.2T; G=8 needs degree-8 I/O; G=16 never**. Placement
   (which sequence's KV sits on which die) is the design parameter; "keep KV off the
   fabric" is the G=1 end of this same law.

6. **The block design** (`scripts/fabric_design.py`). G-block folds are exact (4×8 at
   G=4, 8×4 at G=8); link requirements 164/246/574/615 GB/s at G=2/4/8/16; fabric
   energy 42 W at G=2 vs 210 W dense (5.0×); G=2 link headroom 2.4×. G=8's 4×2 block is
   not expressible as a square 2D mesh → modeled conservatively as an 8-node 1D line.
   The G=16 3.2T/degree-8 path is **recorded as no claim** (no sourced 2027 reference).

7. **The sim leg** (`scripts/fabric_design.py --run`, patched BookSim2). G=4 linear to
   inj 0.60 (lat 14–15); G=8 saturates ~0.5–0.6 (lat 567, stable peak 0.382); G=16
   linear to 0.60 (lat 20–25). Matrix-driven unicast (the mcast fork does not combine
   with matrix traffic; the mechanism is Q1-verified at die scale on uniform traffic).

## Corrected prior (2026-08-04) — what is already done, and why the analysis is still ours

The intra-chip mechanism is **not ours to claim**. tt-metal PR #40733 (merged
2026-04-13) ships a ring-joint SDPA reader kernel that reads KV from DRAM once and
NoC-multicasts it along same-row chain cores — "only one DRAM read per K/V chunk per
head". Full detail in PITFALLS §18. Three consequences:

- **Attribution:** the mechanism is Tenstorrent's; any write-up that presents KV-NoC-
  multicast as novel is wrong and must cite #40733.
- **Corroboration:** their mcast eligibility rule (same physical row, no gaps in the
  mcast rectangle, uniform Q chunks) *is* our row-locality placement constraint —
  vendor-confirmed, computed per-chain at runtime; our law derives it from the KV
  matrix so the schedule is built to be eligible.
- **What remains unclaimed:** the serving-scale form — the 5.4× / 37K quantification
  (their PR has no serving numbers, it is a fused-op kernel), and the die-array fabric
  law D(G) / G-blocks / 1.6T closure (they forward inside a fixed ring; they do not
  design the fabric). The niche is a die-array fabric derived from the KV-multicast
  matrix with placement as an explicit design parameter — open as of the 2026-07-17
  Gate-0 pass and re-checked 2026-08-04.

## Handoffs

- **T2 (deadlock, BookSim):** the G=2 die-pair fabric is point-to-point — deadlock
  vanishes by construction, no VC/dateline machinery needed; only the L=8 fat-tree
  (not the torus — dim-order skips middle dies, breaking multicast coverage) carries
  the G≥4 loads worth studying.
- **T4 (formal):** the BookSim flit-fork multicast router (third_party/booksim2) is a
  ~100-line artifact — a natural formal proof target (exactly-g−1 delivery, the
  known-answer gate PITFALLS §16).

## Open items

- G=16 full-sharding fabric: no claim (no sourced 2026–27 3.2T/degree-8 reference).
- Pipeline status on the internal GitLab: unreachable from this machine; needs a
  Web-UI check.
