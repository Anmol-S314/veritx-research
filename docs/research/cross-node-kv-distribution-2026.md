# Cross-Node KV Distribution — Google TPU 8 Disclosures + Literature Ownership (2026-08-12)

Research pass for the "KV multicast across the die boundary" decision (UCIE-ARC Phase 2).
Two questions, answered from primary sources only:

1. What does Google publicly disclose about KV cache distribution on TPU 8t/8i?
2. Who in the academic literature owns the cross-node KV multicast / distribution slice?

Sources: Google Cloud blog (TPU 8 technical deep dive, blog.google announcement, Next '26
infrastructure post, cloud.google.com/tpu) and arXiv (full-text API, 9 targeted queries).
Raw dumps: `third_party/` none — scraped pages archived at `/tmp/opencode/kv_google_*.txt`
and `/tmp/opencode/kv_lit_report.md` (session of 2026-08-12).

---

## 0. Bottom line

1. **Google's answer to KV is capacity, not distribution.** TPU 8i sizes 384 MB of on-chip
   SRAM to the KV-cache footprint of production reasoning models, so KV "entirely on
   silicon" never has to move. **No primary source discloses any cross-chip KV multicast,
   replication, or read-sharing mechanism.** The CAE accelerates collectives (reduction/
   sync), not KV distribution.
2. **The hardware-level cross-node KV multicast slice is open.** The literature owns the
   problem at the software/rack level (PTStore, CDN-style replication) and at the 3D-stack
   level (3DLS), but **nothing owns fetch-once-multicast-many for KV at the chip-to-chip
   NoC/UCIe rung**. Direct queries returned zero hits for KV+NoC, UCIe+NoC+multicast,
   key-value-cache+network-on-chip, and LLM-serving+multicast+topology.
3. **Google's own numbers now give the motivation sentence.** 8i: 3× on-chip SRAM, 2× ICI
   bandwidth (19.2 Tb/s), network diameter reduced >50% (Boardfly), CAE cuts on-chip
   latency up to 5×. Once KV is a first-class architectural object, the question is not
   "how much bandwidth" but "how efficiently can replicated KV state reach the chips that
   need it."
4. **Caveat:** "Google reloads KV per chip" remains **unverified** and must not be claimed.
   What the sources support: Google's disclosed design avoids distribution by capacity.
   The slice's motivation is the *footprint that does not fit* (long context, agentic
   loops, multi-tenant concurrency) — which Google's own agentic-era framing invites.

---

## 1. Google TPU 8t/8i — verified disclosures

Primary sources (all fetched 2026-08-12):

| Source | URL | Status |
|---|---|---|
| TPU 8t/8i technical deep dive | https://cloud.google.com/blog/products/compute/tpu-8t-and-tpu-8i-technical-deep-dive | 200 |
| "Two chips for the agentic era" | https://blog.google/innovation-and-ai/infrastructure-and-cloud/google-cloud/eighth-generation-tpu-agentic-era/ | 200 |
| AI infrastructure at Next '26 | https://cloud.google.com/blog/products/compute/ai-infrastructure-at-next26 | 200 |
| cloud.google.com/tpu | https://cloud.google.com/tpu | 200 |

### 1.1 KV cache: capacity, not distribution

> "Large on-chip SRAM: With 3x more on-chip SRAM over the previous generation, TPU 8i can
> host a larger KV Cache entirely on silicon, significantly reducing the idle time of the
> cores during long-context decoding." (deep dive)

> "SRAM capacity in TPU 8i was sized for the KV cache footprint of reasoning models at
> production scale." (blog.google)

> "hosting massive KV Caches entirely on silicon" (Next '26)

> "By tripling on-chip SRAM to 384 MB and increasing high-bandwidth memory (HBM) to 288 GB,
> it breaks the memory wall" (Next '26)

**Interpretation (careful):** Google's disclosed design avoids cross-chip KV movement by
making the cache fit. This is a *capacity* solution. The disclosed material says nothing
about what happens when the footprint exceeds 384 MB — long-context agentic loops,
multi-tenant concurrency, prefill/decode disaggregation. That silence is the slice's
motivation, not evidence of any specific mechanism.

### 1.2 CAE: collectives, not KV distribution

> "To solve the sampling bottleneck, TPU 8i uses the CAE, which aggregates results across
> cores with near-zero latency, specifically accelerating the reduction and synchronization
> steps required during auto-regressive decoding and 'chain-of-thought' processing."
> (deep dive)

> "Our new on-chip Collectives Acceleration Engine (CAE) offloads global operations,
> reducing on-chip latency by up to 5x" (blog.google)

> "SparseCore-Collectives Acceleration Engine (SC-CAE) to offload global communication
> tasks" (cloud.google.com/tpu)

**Distinction that matters:** CAE = reduction/all-gather/sync acceleration (collective
*operations*). Cross-chip KV multicast = replicated *read distribution* of a large state
object. Google has disclosed the former. The latter is unclaimed territory at this rung.

### 1.3 Topology: Boardfly (8i) vs 3D torus (8t) — workload-specialized

> "TPU 8i: ... a new serving-optimized network topology called Boardfly." (deep dive)

> "Boardfly ICI topology: While the 3D torus allows connecting thousands of chips to be
> used in cohesion, a large mesh does have more hops between chips and higher all-to-all
> latencies. For 8i, we changed how the chips connect together in f[avor of fewer hops]"

> "By slashing the hops required for all-to-all communication (the heart of MoE and
> reasoning models), Boardfly achieves up to a 50% improvement in latency for
> communication-intensive workloads." (deep dive)

> "TPU 8i hierarchical Boardfly topology building up from a building block of four fully
> connected chips into a fully connected group of eight boards, with 36 of such groups
> fully connected into a TPU 8i pod" (blog.google)

> "linked through Optical Circuit Switches (OCS), ensuring a maximum latency of seven hops
> for any chip-to-chip communication." (deep dive)

> 8t: "utilizes our proven 3D torus network topology at an even larger scale of 9,600 chips
> in a single superpod" (deep dive)

**Relevance:** Google validated workload-specialized topology at the system level (torus
for training, Boardfly for serving). This is the "traffic-driven topology" principle at
the scale-up rung — the same rung our KV multicast slice occupies.

### 1.4 Performance headline numbers (for the motivation section)

| | TPU 8t (training) | TPU 8i (inference) |
|---|---|---|
| Network topology | 3D torus, 9,600 chips/pod | Boardfly (hierarchical, ≤7 hops via OCS) |
| On-chip SRAM | 128 MB | 384 MB (3× prior gen) |
| HBM | 216 GB, 6,528 GB/s | 288 GB, 8,601 GB/s |
| ICI bandwidth | 19.2 Tb/s (2× Ironwood) | 19.2 Tb/s (2× Ironwood) |
| CAE | — | yes (on-chip collectives, up to 5× lower latency) |
| FP4 peak | 12.6 PFLOPS | 10.1 PFLOPS |

---

## 2. Literature ownership — the cross-node KV slice (arXiv, 2026-08-12)

Query method: arXiv API, full-text search (`all:`), 9 queries, relevance-sorted.
Full results: `/tmp/opencode/kv_lit_report.md`.

### 2.1 Direct hits — the slice is open at the hardware rung

Queries with **zero results**:
- `all:"KV cache" AND all:"NoC"` → none
- `all:"cross-chip" AND all:"KV cache"` → none
- `all:"UCIe" AND all:"NoC" AND all:"multicast"` → none
- `all:"key-value cache" AND all:"network-on-chip"` → none
- `all:"LLM serving" AND all:"multicast" AND all:"topology"` → none

### 2.2 Occupants at adjacent rungs (must be cited and distinguished)

| Paper | What they own | The gap vs our slice |
|---|---|---|
| **3DLS** (2607.01617, 2026-07) | 3D logic-stacked disaggregated LLM serving; notes "layer-wise prefill-to-decode KV-cache transfer [and] decode-side TP collectives share the same lateral die-to-die (D2D) interconnect" | 3D-stacking-specific; the D2D sharing *problem* is named, the multicast-fork mechanism is not owned |
| **TPLA** (2508.15881, 2025-08) | Disaggregated prefill/decode + MLA: "in TP each device must load the full cache" — solves via latent attention (software) | The redundant-load *problem* stated; solution is algorithmic, not a NoC mechanism |
| **PTStore** (2607.22648, 2026-06) | Distributed prefix KV caching + replication, CDN-inspired, at rack/node level | Software replication, not chip-to-chip fabric |
| **DAK** (2604.26074, 2026-04) | Direct-access GPU memory offloading, tiered memory | Memory-tier, not NoC |
| **FairKV** (2502.15804, 2025-02) | Per-head KV balancing on multi-GPU | Allocation, not distribution fabric |
| **Sangam** (2511.12286, 2025-11) | Chiplet DRAM-PIM + CXL for LLM | PIM compute, not KV multicast |
| **CHIME** (2601.19908, 2025-12) | Chiplet edge multimodal LLM, near-memory | Edge/small-scale |

### 2.3 What this means

The **fetch-once-multicast-many** primitive for KV at the chip-to-chip NoC/UCIe rung has
no direct occupant in the literature. The closest neighbors (3DLS, TPLA) *name* the
redundant-transfer problem and solve it architecturally (3D stacking) or algorithmically
(latent attention / compression) — neither owns a NoC multicast-fork mechanism for
replicated KV state at the package fabric.

---

## 3. How the thesis holds (or falls)

**Survives Google contact:** Google's capacity solution does not cover footprint-miss
cases; no disclosed distribution mechanism competes. The slice's motivation is sharper
than before: *when KV does not fit on-chip, how is it distributed to the chips that need
it?*

**Survives literature contact:** adjacent rungs are occupied (software replication at
rack level; 3D-stack D2D sharing problem), the hardware multicast-fork slice at the
chip-to-chip rung is not.

**Claim language (safe):**
> "Once KV cache is a first-class architectural object, the question is not merely how
> much memory bandwidth the accelerator has, but how efficiently replicated KV state can
> be distributed to the chips that need it."

**Claim language (unsafe, do not publish without primary evidence):**
> "Google's TPU 8i reloads KV independently per chip." — unverified; Google discloses
> nothing about cross-chip KV movement.

**Naming the competition for the paper:** 3DLS (2607.01617) and TPLA (2508.15881) must be
the baselines discussed in related work; our mechanism's upside is precisely their
KV-transfer cost line-item.

---

## 4. Source index

| # | Item | URL |
|---|---|---|
| 1 | TPU 8t/8i technical deep dive | https://cloud.google.com/blog/products/compute/tpu-8t-and-tpu-8i-technical-deep-dive |
| 2 | "Two chips for the agentic era" (blog.google) | https://blog.google/innovation-and-ai/infrastructure-and-cloud/google-cloud/eighth-generation-tpu-agentic-era/ |
| 3 | AI infrastructure at Next '26 | https://cloud.google.com/blog/products/compute/ai-infrastructure-at-next26 |
| 4 | cloud.google.com/tpu (8i/SC-CAE) | https://cloud.google.com/tpu |
| 5 | 3DLS | https://arxiv.org/abs/2607.01617 |
| 6 | TPLA | https://arxiv.org/abs/2508.15881 |
| 7 | PTStore | https://arxiv.org/abs/2607.22648 |
| 8 | DAK | https://arxiv.org/abs/2604.26074 |
| 9 | FairKV | https://arxiv.org/abs/2502.15804 |
| 10 | Sangam | https://arxiv.org/abs/2511.12286 |
| 11 | CHIME | https://arxiv.org/abs/2601.19908 |

## 5. Method notes

- All Google claims quoted verbatim from fetched pages (2026-08-12); raw text archived at
  `/tmp/opencode/kv_google_{tpu8_deepdive,blog_google_8gen,next26_infra,tpu_landing}.txt`.
- Literature search = arXiv full-text API; `all:` matches metadata + abstract (not full
  PDF text — so "zero hits" means zero in abstract/metadata, which for this slice is the
  conservative interpretation).
- TPM's Next Platform TPU-8 article (April 2026) corroborates the numbers but is marked
  with informed-guess caveats (2.2 GHz, 2 nm process guesses) — treat as secondary, use
  only Google's own blog numbers in the paper.
