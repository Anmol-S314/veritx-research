# 2026 MoE Serving Landscape — Scoop Check & Motivation Refresh (2026-08-13)

Research pass for the UCIE-ARC decision ("multicast fork placement across the NoC-to-NoC
die/chiplet bridge for KV-cache distribution in LLM serving"). Compiled 2026-08-13 from
primary sources: arXiv API (metadata + abstract full-text, ~25 queries), GitHub API
(tt-metal, gem5, BookSim2, PyTorchSim, ttsim), Hugging Face (official DeepSeek model
configs), uciexpress.org, IEEE DOI resolution. Companion to
[cross-node-kv-distribution-2026.md](cross-node-kv-distribution-2026.md) (2026-08-12) and
[simulator-landscape-2026.md](simulator-landscape-2026.md) (2026-08-12).

> **Confidence note.** Every claim carries a URL and check date. "Zero hits" means zero in
> arXiv metadata+abstract (conservative — PDF body not indexed). ⚠️ marks items resting on a
> secondary write-up or a source not fetchable at primary level. IEEE-paywalled items are
> cited via DOI only. The core verdicts (slice still unclaimed; MoE serving is the fastest
> moving adjacent literature; sparse attention shrinks but does not eliminate the KV
> distribution problem) do not depend on any single ⚠️ item.

---

## (a) Verdict

1. **The slice is still unclaimed as of 2026-08-13.** Re-ran the ownership queries from
   the 2026-08-12 pass: `KV cache + multicast` → 2 hits (both known: DAK, one unrelated);
   `UCIe + multicast` → 0; `LLM serving + multicast` → 0; `network-on-chip + KV` → 0;
   `KV cache + chiplet` → 3 (3DLS, CHIME, Sangam — all known). Nothing publishes
   **fetch-once-multicast-many for KV at the chip-to-chip/bridge rung**.
2. **The window is closing faster than the 08-12 pass suggested.** Three post-2026-06
   developments bracket the slice from both sides: **MoX** (2607.20220) publishes
   multicast-tree routing for MoE dispatch/combine on direct-connect fabrics (rack rung);
   **FlatAttention v2** (2604.02110) plus the Benini group's **collective-capable NoC**
   (2603.26438) push on-chip multicast/reduction collectives onto multi-die wafer-scale
   serving (die rung); **3DLS** (CAL 2026) already occupies "physically isolate KV transfers
   from TP collectives at the die-to-die rung." Our contribution must now be explicitly the
   *multicast fork for replicated KV state crossing a package-level bridge*, distinguished
   from all three by rung and mechanism.
3. **The motivation is refreshed, not weakened, by the 2026 model wave.** DeepSeek-V4
   (April 2026; 1.6T/49B-activated, 384 experts, top-6, MLA-family latent attention, 1M
   token context, "10% of V3.2 KV cache") and the sparse-attention hardware wave
   (KARAT, NELSSA, GVR, Salca, PADE — all 2026) make KV state smaller but still *replicated,
   shared, and hot* — and now served at million-token scale where it does not fit on one
   die. Sparse attention changes the *size* of the KV object, not the *distribution*
   problem the slice owns.
4. **UCIe 3.0 (2026) has no multicast/broadcast data-plane semantics** in its public
   highlights; it does add *priority sideband packets* and (2.0) a management fabric (UDA)
   — which is traffic-class separation at the protocol level, useful citation for the
   plane-separation leg, not competition for the multicast fork.

---

## (b) Per-topic findings

### 1. MoE serving workloads — the 2026 model wave

**DeepSeek-V4 is the new flagship open MoE (April 2026), and it is MLA-family.** Verified
from the official arXiv report and the official Hugging Face configs:

| Fact | Value | Source (fetched 2026-08-13) |
|---|---|---|
| V4-Pro | 1.6T params, 49B activated, 1M-token context | https://arxiv.org/abs/2606.19348 |
| V4-Flash | 284B params, 13B activated | https://arxiv.org/abs/2606.19348 |
| V4-Pro config | 61 layers, 128 heads, **1 KV head**, q_lora_rank=1536, o_lora_rank=1024, **384 routed experts, top-6**, fp4 experts | https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/raw/main/config.json |
| V4-Flash config | 43 layers, 64 heads, 1 KV head, q_lora_rank=1024, **256 routed experts, top-6** | https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash/raw/main/config.json |
| Attention | hybrid CSA (Compressed Sparse Attention) + HCA (Heavily Compressed Attention); "27% of single-token FLOPs and 10% of KV cache vs V3.2" | https://arxiv.org/abs/2606.19348 |
| Checkpoints | V4-Pro/Flash + Base, DSpark variants, Flash-0731 (304B, Jul 2026) | https://huggingface.co/collections/deepseek-ai/deepseek-v4 |
| Post-training at scale | SLAI T-Rex: full-parameter post-training of V4 family on Ascend SuperPOD, 34.22% MFU | https://arxiv.org/abs/2607.20145 |

**MLA persists through V3.2.** The V3.2 report (Dec 2025) instantiates DeepSeek Sparse
Attention (DSA) *under MLA* (section "Instantiate DSA Under MLA"; appendix "MHA and MQA
Modes of MLA") — i.e., the latent-cache structure is retained and sparse selection is
layered on top. https://arxiv.org/abs/2512.02556 (HTML checked 2026-08-13)

**Qwen family.** Qwen3-MoE remains the referenced open MoE alternative in 2026 serving
work (Qwen3-235B-A22B on H200s in Moebius, 2606.26607). Qwen3.5/Qwen3.7 exist by mid-2026
(evidenced in Qwen-Scope 2605.11887 and Qwen-CUA 2608.02352, the latter a 397B-A17B MoE
backbone); no verified Qwen3.5/3.7 MoE technical report with full serving numbers was found
in this pass — do not cite architecture specifics for them without primary verification.

**Interconnect findings for MoE serving (motivation support):**
- **MoX** (2607.20220, Jul 2026, Technion): offline-optimized multicast-tree routing makes
  MoE dispatch/combine work on static direct-connect (expander/Boardfly) fabrics; 1.8×
  over min-hop routing; **validated on ASTRA-sim and a 1024-TPU Boardfly model**. Confirms
  multicast-for-MoE is a live research theme at the rack rung. https://arxiv.org/abs/2607.20220
- **"Rethinking Network Topologies for Cost-Effective MoE LLM Serving"** (2605.00254, Apr
  2026, UC Berkeley — Shenker/Ratnasamy/Shao/Nikolic): switchless 3D full-mesh beats
  scale-up for MoE serving by 20.6–56.2% cost-effectiveness; scale-up link bandwidth
  over-provisioned (up to 27% better $/throughput with less bandwidth). Direct support for
  "serving interconnect is cost-critical and topology-driven." https://arxiv.org/abs/2605.00254
- **Moebius** (2606.26607, Jun 2026): runtime EP↔TP switching on Qwen3-235B-A22B; KV cache
  and expert weights reshared between ranks in 215–434 ms on 8×H200 — KV state is a
  first-class movable object in 2026 serving stacks. https://arxiv.org/abs/2606.26607
- **FinDEP** (2512.21487, Dec 2025): disaggregated expert parallelism for DeepSeek-V2 /
  Qwen3-MoE, 1.61× throughput. https://arxiv.org/abs/2512.21487
- DeepSeek's own serving-interconnect disclosures remain the ISCA'25 industry paper
  (MLA + Multi-Plane Network Topology, training-focused): https://arxiv.org/abs/2505.09343.

### 2. Scoop risk on the slice (post-2026-06 sweep)

Direct ownership queries, arXiv API, 2026-08-13:

| Query | Hits | Verdict |
|---|---|---|
| `all:"KV cache" AND all:"multicast"` | 2 | DAK (2604.26074, known) + unrelated agentic-AI paper (2603.21321) |
| `all:"UCIe" AND all:"multicast"` | 0 | open |
| `all:"LLM serving" AND all:"multicast"` | 0 | open |
| `all:"network-on-chip" AND all:"KV"` | 0 | open |
| `all:"KV cache" AND all:"chiplet"` | 3 | 3DLS, CHIME, Sangam (all known, adjacent rungs) |
| `all:"KV cache" AND all:"die-to-die"` | 1 | 3DLS only |
| `all:"MoE" AND all:"multicast"` | 1 | MoX (new, rack rung — see §b.1) |

Follow-up status of the cited anchors:
- **MONET** (DATE 2026): confirmed at primary level via DOI —
  Liu, S., Roediger, M., & Karanth, A., "MONET: A Mixture-of-Experts Accelerator with a
  Multicast-Optimized Two-Tier Network-on-Chip," DATE 2026, pp. 1–7.
  https://doi.org/10.23919/DATE69613.2026.11539142 (paywalled; no arXiv copy found). No
  follow-up from this group surfaced on arXiv in this pass.
- **FlatAttention** v1 (2505.18824) → **v2** (2604.02110, Apr 2026, submitted IEEE TC):
  same group now evaluates fabric-collective attention **end-to-end on a wafer-scale
  multi-die system with DeepSeek-V3 FP8 decoding** (1.9× throughput, 1.4× latency
  reduction). Multi-die fabric collectives for attention = the closest live neighbor to
  our rung. https://arxiv.org/abs/2604.02110
- **tt-metal #40733** ("fused ring-joint SDPA with fabric KV forwarding"): closed/merged
  2026-04-13 per GitHub API. It is ring *forwarding* (all-gather overlap), intra-chip
  mesh (Blackhole GLX 8×4), **not a multicast fork** — and no KV-multicast follow-up PR
  was found in a title search. https://github.com/tenstorrent/tt-metal/pull/40733
- **PAC-NoC**: not on arXiv (IEEE CSDL only, per simulator-landscape-2026.md §3). No
  arXiv-visible follow-up.

### 3. UCIe ecosystem 2026

Verified at https://www.uciexpress.org/specifications (2026-08-13): specs now at **1.0,
1.1, 2.0, 3.0**.
- **UCIe 3.0**: 48 GT/s and 64 GT/s data rates (2× UCIe 2.0's 32 GT/s), extended sideband
  to 100 mm, **priority sideband packets for deterministic low-latency signaling**, fast
  throttle/emergency shutdown, open-drain pins, runtime recalibration. No multicast or
  broadcast data-plane semantics appear anywhere in the public highlights.
- **UCIe 2.0**: 3D packaging (hybrid bonding, 1–25 µm bump pitches) + UDA management
  fabric (test/telemetry/debug sideband "within each chiplet"). A *sideband control
  fabric separate from the data plane is already a UCIe standard concept* — a usable
  citation for the plane-separation leg, and a distinction from our multicast fork (which
  is data-plane).
- Blog (2026): Chiplet Summit 2026 "UCIe momentum across a growing ecosystem"
  (Mar 2026), member posts (Socionext May 2026, GUC Mar 2026, Shanghai UniVista Jun 2026).
  **No public 2026 chiplet product with explicit LLM-serving traffic on UCIe** was
  disclosed in these posts. https://www.uciexpress.org/blog
- Adjacent protocol-level capability at the board rung: UALink 2.0 in-network
  collectives (INK) (Apr 2026) — collectives, not data multicast; already documented in
  simulator-landscape-2026.md §4.

### 4. MLA vs KV-cache — hardware consequences we must cite

- **MLA is now the mainstream open-model attention (not just DeepSeek).** V3.2 retains MLA
  under DSA (§b.1); V4 configs keep the MLA signature (1 KV head + q/o_lora_rank); the
  latent-cache story is now the *compressed KV* story at 1M context.
- **"Rethinking LLM Inference Bottlenecks: Insights from Latent Attention and
  Mixture-of-Experts"** (2507.15465, v3 Jan 2026 — Kim/Ahn group, SNU): MLA raises
  attention arithmetic intensity 100×+ (compute-bound, not bandwidth-bound), and the
  dominant bottleneck shifts to **high-bandwidth interconnects and expert workload
  balancing across accelerators**. This is the strongest published support for "the
  interconnect, not the KV object, is the 2026 serving bottleneck." https://arxiv.org/abs/2507.15465
- Hardware-centric MLA analysis (2506.02523, Electronics Letters 2025) — first
  hardware-centric MLA treatment; reuse-vs-recompute execution schemes. https://arxiv.org/abs/2506.02523
- **Sparse-attention hardware wave (2026)** — all treat KV as a distributed, fetched
  object: KARAT (2608.03555, PNM KV-resident accelerator for retrieval-based sparse
  attention), NELSSA (2607.26633, MICRO 2026, GPU+PNM CXL serving), Dynamic Sparse
  Attention access-pattern study (2603.13430), Salca (2604.24820), PADE (HPCA 2026,
  2512.14322), FAST-Prefill (2602.20515). None touches a package-level multicast fork.
- **GVR** (2604.22312, NVIDIA authors, TensorRT-LLM on Blackwell): production
  optimization of DeepSeek-V3.2 DSA Top-K selection — vendor evidence that sparse-attention
  serving is shipping in NVIDIA's stack in 2026. https://arxiv.org/abs/2604.22312
- **ESS** (2512.10576): latent-cache offload for DeepSeek-V3.2-Exp decode — the latent
  cache is now big enough to need its own management layer. https://arxiv.org/abs/2512.10576
- **Vendor KV-interconnect disclosures, 2026:** Google TPU 8i capacity-only (already
  documented 2026-08-12). NVIDIA: no primary-source KV multicast/Rubin-era disclosure
  found; measured B300 NVLink P2P = 510 GB/s inside CVMs (Serialized Bridge,
  2606.23969, Jun 2026). Cerebras/Groq: no 2026 KV-interconnect disclosure found on
  arXiv; ⚠️ only third-party benchmarking (xPU-athalon, ISPASS 2026, 2604.10852).
  Tenstorrent: ttsim v1.10.0 + Blackhole GA (May 2026) as previously documented.

### 5. Plane separation — 2026 extensions

- **3DLS** (2607.01617, CAL 2026, DOI 10.1109/LCA.2026.3709108): physical isolation —
  route prefill→decode KV transfers through vertical interconnects, keep TP collectives on
  lateral D2D; 1.49× throughput / 60.2% E2E latency vs shared planar fabric, and beats a
  priority-managed planar baseline. **Closest 2026 occupant of "separate traffic classes
  at the D2D rung"** — must be the primary plane-separation baseline. https://arxiv.org/abs/2607.01617
- **Preemptive VCs** (2607.01430, Jul 2026, Benini group): multiplane (FlooNoC-style)
  vs VC-based AXI traffic-class separation for deadlock freedom; preemptive VCs save up
  to 76% of link resources vs multiplane at 3% router area. Extends the plane-separation
  design space at the architecture level (deadlock motivation, not starvation).
  https://arxiv.org/abs/2607.01430
- FlooNoC: no 2026 follow-up beyond the TVLSI 2025 journal version (2409.17606v2).
  MONET (DATE 2026) remains the direct "multicast-optimized two-tier NoC for MoE" prior
  art at the accelerator rung (DOI above).

### 6. Simulation credibility — 2026 status

| Tool | Status (checked 2026-08-13) | Evidence |
|---|---|---|
| BookSim2 | **Frozen since 2017** — stable reproducibility anchor; no drift risk | https://github.com/booksim/booksim2 (commits API) |
| gem5 | v25.1.0.1 (2026-04-21) | https://github.com/gem5/gem5/releases |
| PyTorchSim | Active (docs/tutorial updates Apr–May 2026) | https://github.com/PSAL-POSTECH/PyTorchSim (commits API) |
| ASTRA-sim 3.0 | arXiv 2606.10440 (Jun 2026) — load-store granularity, InfraGraph | https://arxiv.org/abs/2606.10440 |
| LLMServingSim 2.0 | arXiv 2602.23036v2 (Mar 2026); 0.95% average error vs real deployments | https://arxiv.org/abs/2602.23036 |
| Frontier | arXiv 2605.21312v2 (Jun 2026); <4% throughput error on 16×H800; repo `NetX-lab/Frontier` | https://arxiv.org/abs/2605.21312 |
| CHIPSIM | ⚠️→verified: IEEE OJ-SSCS 2025, DOI 10.1109/OJSSCS.2025.3626314 (chiplet/NoI co-sim) | https://arxiv.org/abs/2510.25958 |
| ttsim | v1.10.0 (2026-08-07); v1.9.x weekly cadence; NoC multicast modeling (since 1.8.1) | https://github.com/tenstorrent/ttsim/releases |
| DeepStack / Voxel | 3D-accelerator DSE sims (Apr 2026): DeepStack validated vs NS-3 (2.12%) and 8×B200 vLLM (12.18%) | https://arxiv.org/abs/2604.04750, https://arxiv.org/abs/2604.26821 |
| Official model for validation | **DeepSeek-V4 open weights on HF** (Apr–Jun 2026) — new, current, reproducible simulation target | https://huggingface.co/collections/deepseek-ai/deepseek-v4 |
| Multicast-in-sim precedent | MoX validates multicast-claim results on ASTRA-sim (Boardfly 1024-TPU model) — reviewers accept serving-multicast claims anchored in ASTRA-sim | https://arxiv.org/abs/2607.20220 |

No BookSim3 exists (github.com/booksim/booksim3 → 404). BookSim2's immutability plus the
maturing trace ecosystem (Chakra/LLMServingSim/ASTRA-sim) keeps the three-layer stack
recommendation in simulator-landscape-2026.md valid, with MoX as a new precedent for the
"multicast results via ASTRA-sim" credibility move.

---

## (c) Threat list (things that hurt us)

1. **FlatAttention v2 (2604.02110) + collective-capable NoC (2603.26438)** — the Benini
   group has fabric collectives (multicast+reduction, DCA) and a multi-die wafer-scale
   DeepSeek-V3 serving evaluation. If they add a KV-distribution object at the die rung,
   they own our intersection. Their gap today: attention dataflow and weight distribution,
   not replicated KV state crossing a package bridge. **Re-check monthly.**
   https://arxiv.org/abs/2604.02110 · https://arxiv.org/abs/2603.26438
2. **MoX (2607.20220)** — multicast trees for MoE serving traffic, published 2026-07-22,
   i.e., post-2026-06. Rack rung, dispatch/combine (not KV), but proves multicast-aware
   routing for serving is publishable and currently hot. https://arxiv.org/abs/2607.20220
3. **3DLS (2607.01617, CAL 2026)** — occupies "KV transfers vs TP collectives, physically
   isolated, at the D2D rung" for PD-disaggregated serving. Our plane-separation result
   must be scoped as the *multicast-fork mechanism on a shared lateral bridge*, with 3DLS
   (physical isolation, 3D stacking) and MONET (two-tier multicast NoC) as the baselines.
4. **MONET (DATE 2026)** and **PAC-NoC (2026)** — multicast-optimized NoC topologies for
   MoE/attention are now prior art at the accelerator rung; reviewers will map our fork
   onto them. Differentiate by rung (chip-to-chip bridge vs intra-chip) and object (KV
   state vs weights/activations).
5. **Torrent (DATE 2026, 2512.17589)** — P2MP without network multicast (chained DMA)
   attacks the "multicast vs replicated unicast" framing itself; cite as the baseline
   alternative mechanism.

## (d) Opportunity list (things that help us)

1. **Slice verified still unclaimed (2026-08-13)** — six direct ownership queries, zero
   occupants at the chip-to-chip/bridge rung (§b.2).
2. **DeepSeek-V4 refreshes the motivation with official numbers**: 1.6T/49B-activated,
   384 experts top-6, 1M context, 10% of V3.2 KV — the *replicated, shared, hot* KV object
   at scale, with open weights for reproducible simulation (§b.1).
3. **The 2026 literature argues our thesis for us**: MLA/compute-bound shift makes
   interconnect the bottleneck (2507.15465); MoE serving topology is cost-critical
   (2605.00254); KV is a movable first-class object (Moebius 2606.26607, Harvest
   2602.00328, MMA 2512.16056, Topology-Aware 2607.28633).
4. **Sparse-attention hardware wave (KARAT/NELSSA/Salca/PADE/GVR)** proves the KV
   distribution problem is where 2026 hardware research is heading — but at the
   memory/PNM rung, not the fabric rung. We occupy the unclaimed fabric rung in a crowded
   neighborhood.
5. **UCIe 3.0/2.0 give standards-level hooks**: priority sideband packets (3.0) and the
   UDA management fabric (2.0) are traffic-class separation at the protocol layer — cite
   for the plane-separation leg; their silence on data-plane multicast is the gap we
   fill (uciexpress.org/specifications).
6. **Sim-credibility stack is in the best state yet**: BookSim2 frozen (reproducible),
   ASTRA-sim 3.0 + LLMServingSim 2.0 + Frontier for serving-level traces, ttsim v1.10.0
   with multicast modeling, and MoX's ASTRA-sim-anchored multicast evaluation as a
   reviewer-precedent for our own validation path (§b.6).
7. **MLA-persistence fact (V3.2 "DSA under MLA"; V4 configs)** lets us claim the latent
   cache *inherits* the distribution problem — TPLA's algorithmic compression (2508.15881)
   and our fabric mechanism are complements, not substitutes (§b.1, §b.4).

## (e) Open questions

1. Does any UCIe 3.0 adopter implement multicast/broadcast at the D2D protocol layer?
   Nothing public as of 2026-08-13; spec text is member-gated (⚠️ could not verify spec
   internals — highlights only).
2. DeepSeek-V4's exact latent-cache mechanics (kv_lora_rank semantics, CSA/HCA layout
   per layer, shared-prefix replication across dies) — the V4 config shows MLA-family
   structure but the report's architecture section was not fully read in this pass;
   verify before quoting cache-shape numbers beyond the abstract's 10%-of-V3.2 claim.
3. Qwen3.5/Qwen3.7 architecture specifics (MoE sizes, expert counts, MLA?) — no verified
   technical report found in this pass; Qwen-CUA (397B-A17B) and Qwen-Scope references
   only.
4. Vendor KV-interconnect disclosures for 2026-era NVIDIA (Rubin) / AMD (MI4xx) /
   Cerebras / Groq: no primary source found in this pass — official blog/newsroom
   surfaces not fully crawled; ⚠️ pending.
5. Is "Google reloads KV per chip" (TPU 8i) verifiable in any 2026 source? Still
   unverified per the 08-12 pass; do not claim.
6. MONET/PAC-NoC citation impact: no arXiv-visible follow-ups, but IEEE Xplore citation
   data was not checked (paywalled) — the next pass should check whether anyone cites
   MONET for KV distribution.

## Source index (all fetched 2026-08-13)

| # | Item | URL |
|---|---|---|
| 1 | DeepSeek-V4 report | https://arxiv.org/abs/2606.19348 |
| 2 | DeepSeek-V4 HF collection + configs | https://huggingface.co/collections/deepseek-ai/deepseek-v4 · https://huggingface.co/deepseek-ai/DeepSeek-V4-Pro/raw/main/config.json · .../DeepSeek-V4-Flash/raw/main/config.json |
| 3 | DeepSeek-V3.2 (DSA under MLA) | https://arxiv.org/abs/2512.02556 |
| 4 | SLAI T-Rex (V4 on Ascend) | https://arxiv.org/abs/2607.20145 |
| 5 | ESS (latent-cache serving) | https://arxiv.org/abs/2512.10576 |
| 6 | MoX (multicast MoE routing) | https://arxiv.org/abs/2607.20220 |
| 7 | MoE topologies cost-effectiveness | https://arxiv.org/abs/2605.00254 |
| 8 | Moebius (EP↔TP switch) | https://arxiv.org/abs/2606.26607 |
| 9 | FinDEP | https://arxiv.org/abs/2512.21487 |
| 10 | FlatAttention v2 (multi-die) | https://arxiv.org/abs/2604.02110 |
| 11 | Collective-capable NoC (DCA) | https://arxiv.org/abs/2603.26438 |
| 12 | Torrent (P2MP DMA) | https://arxiv.org/abs/2512.17589 |
| 13 | HyNoC | https://arxiv.org/abs/2607.02729 |
| 14 | MONET (DATE 2026) | https://doi.org/10.23919/DATE69613.2026.11539142 |
| 15 | 3DLS (CAL 2026) | https://arxiv.org/abs/2607.01617 · https://doi.org/10.1109/LCA.2026.3709108 |
| 16 | Preemptive VCs (AXI separation) | https://arxiv.org/abs/2607.01430 |
| 17 | MLA/MoE bottlenecks (SNU) | https://arxiv.org/abs/2507.15465 |
| 18 | MLA hardware-centric analysis | https://arxiv.org/abs/2506.02523 |
| 19 | GVR (NVIDIA DSA Top-K) | https://arxiv.org/abs/2604.22312 |
| 20 | KARAT / NELSSA / DSA-access / Salca / PADE / FAST-Prefill | https://arxiv.org/abs/2608.03555 · 2607.26633 · 2603.13430 · 2604.24820 · 2512.14322 · 2602.20515 |
| 21 | Serialized Bridge (B300 NVLink) | https://arxiv.org/abs/2606.23969 |
| 22 | xPU-athalon (ISPASS 2026) | https://arxiv.org/abs/2604.10852 |
| 23 | tt-metal #40733 | https://github.com/tenstorrent/tt-metal/pull/40733 |
| 24 | UCIe specs | https://www.uciexpress.org/specifications |
| 25 | UCIe blog 2026 | https://www.uciexpress.org/blog |
| 26 | gem5 v25.1.0.1 | https://github.com/gem5/gem5/releases |
| 27 | BookSim2 (frozen) | https://github.com/booksim/booksim2 |
| 28 | PyTorchSim (active) | https://github.com/PSAL-POSTECH/PyTorchSim |
| 29 | ttsim v1.10.0 | https://github.com/tenstorrent/ttsim/releases |
| 30 | ASTRA-sim 3.0 | https://arxiv.org/abs/2606.10440 |
| 31 | LLMServingSim 2.0 | https://arxiv.org/abs/2602.23036 |
| 32 | Frontier | https://arxiv.org/abs/2605.21312 |
| 33 | CHIPSIM (verified) | https://arxiv.org/abs/2510.25958 · https://doi.org/10.1109/OJSSCS.2025.3626314 |
| 34 | DeepStack / Voxel | https://arxiv.org/abs/2604.04750 · 2604.26821 |
| 35 | Qwen-CUA / Qwen-Scope (Qwen3.5/3.7 evidence) | https://arxiv.org/abs/2608.02352 · 2605.11887 |
| 36 | DAK / Harvest / MMA / Topology-Aware KV | https://arxiv.org/abs/2604.26074 · 2602.00328 · 2512.16056 · 2607.28633 |

## Method notes

- arXiv via export.arxiv.org API; `all:` matches metadata+abstract only — zero-hit
  verdicts are the conservative interpretation.
- GitHub facts (tt-metal PR state/merge date, repo activity, releases) via GitHub REST
  API. BookSim2 "frozen" = no commits since 2017-06.
- DeepSeek-V4 architecture facts from the official released `config.json` (primary);
  V3.2 facts from arXiv HTML full text (TOC + section titles checked for "Instantiate
  DSA Under MLA").
- IEEE-paywalled items (MONET, 3DLS DOI) cited from DOI metadata only.
- ⚠️ items: Cerebras/Groq/AMD/NVIDIA-Rubin 2026 KV-interconnect disclosures (no primary
  source found); UCIe 3.0 spec internals (member-gated); Qwen3.5/3.7 report (none found).
