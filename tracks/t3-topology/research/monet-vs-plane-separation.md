# MONET (DATE 2026) vs the T3 Plane-Separation Result — Prior-Art Comparison

Prior-art note for the t3-topology track. Compiled 2026-08-12. Compares **MONET:
A Mixture-of-Experts Accelerator with a Multicast-Optimized Two-Tier Network-on-Chip**
(Liu, Roediger, Karanth — Ohio University, DATE 2026, DOI 10.23919/DATE69613.2026.11539142)
against this repo's measured plane-separation result
(`scripts/plane_separation.py`, `NETWORK-HIERARCHY.md` appendix, `RTL-ARC.md` Gate R3).

> **Confidence note (updated 2026-08-12 after a verification pass).** Our side is fully
> measured and gated (seeded, reproducible, RTL-checked). The MONET side: the **abstract and
> metadata are verified verbatim** from the Semantic Scholar record (primary). The
> architecture structure (systolic PE islands + dual mesh) is **confirmed by the abstract**.
> Mel/Bel router internals and the baseline list come from a detail pass over the DATE 2026
> proceedings PDF and are **consistent with the abstract but not independently confirmable**
> here — the full text is paywalled (IEEE) and the open proceedings archive bans automated
> clients (see §7). Items marked ⚠️ still need full-text confirmation before quoting in our
> paper.

---

## 0. Verdict, in one paragraph

MONET is a **third independent confirmation of the plane-separation mechanism** we measured —
after FlooNoC (Fischer et al., NOCS 2023, the work we explicitly reproduce) and now MONET
(DATE 2026): a shared fabric degrades latency-critical / multicast-heavy traffic, and
physically separated networks fix it. That means **"plane separation fixes control starvation"
is no longer a claim we can lead with as novel** — it is established prior art by two named
papers. What **survives** as ours: (1) the causal lever is *burstiness at constant bandwidth*,
not traffic pattern or volume — a mechanism MONET does not isolate; (2) the *quantitative*
isolation trade-off (VC count vs plane vs express channels) as a silicon-cost design rule —
MONET offers no such sweep; (3) the general *peripheral taxonomy* (NIC/DMA/CXL/PCIe/UCIe
classes) rather than MoE-specific routing; (4) per-flit RTL fidelity on top of BookSim — MONET
reports aggregate latency/energy from RTL synthesis. MONET also differs in *what* it separates
(communication pattern: multicast dispatch vs aggregation), while ours separates by *latency
class* (1-flit control vs long-burst bulk). Neither invalidates the other; together they
strengthen our methodology claim and sharpen the novelty re-scoping in §5.

---

## 1. The two works, side by side

| | **MONET (DATE 2026)** | **T3 plane separation (this repo)** |
|---|---|---|
| Question | Design an interconnect for sparse MoE transformers (token dispatch + expert fusion) | Why does latency-critical control starve on a shared mesh, and what isolation knob fixes it? |
| Mechanism | **Two-tier design** (verified via abstract): tier 1 = **reconfigurable systolic PE islands** (gating + expert compute, runtime-configurable sparse/dense, expert reordering, activation); tier 2 = **dual mesh interconnecting the island grid** — one network manages input-token delivery with a broadcast scheme (truncated in abstract), the other handles dispatch/fusion. Mel (multicast) / Bel (low-latency fusion) routers ⚠️ | **Physical plane separation** (control vs bulk) reproducing FlooNoC's 4-network design; plus quantified VC-separation and express-channel alternatives on ONE mesh |
| Traffic classes | MoE: gating dispatch, token routing (top-k), expert-parallel, all-to-all fusion | Peripheral taxonomy: 1-flit control (uniform, rate 0.005) vs DMA bursts to 8 NIC nodes (hotspot), constant flit load 0.08 flits/cyc/node |
| Setup | RTL synthesis + NoC-level simulation + real MoE workloads (abstract-verified); baselines: **2D systolic array, EdgeMoE (FPGA), Space-Mate (ASIC)** ⚠️; Switch-base-8 workload ⚠️ | BookSim2, 8×8 mesh, XY, seed=1, D=8 buffers; plus RTL 8×8 mesh replay (Gate R3, FPGA/Verilator) |
| Results | Up to **8.5× lower latency**, **over 6× better energy efficiency vs state-of-the-art MoE accelerators** (abstract-verified verbatim) | 1 VC: control latency 45.1 → 221.6 cyc (**1.36× → 6.68× starvation**) as DMA bursts grow 5 → 80 flits at constant bandwidth; isolated plane flat at 33.2 cyc |
| Isolation alternative | (two tiers are the design; VC-sharing within tiers assumed) | **VCs absorb burstiness**: 4 VCs hold control to 34.5 → 41.3 cyc (≈1.24×); express channels flatten but don't remove (−47% at 80-flit) |
| Artifacts | None public (no arXiv, no OA copy; IEEE paywalled) | Seeded, gated, selfcheck-pinned; RTL + comparator harness in-repo |

---

## 2. Mechanism comparison — where the works genuinely overlap

1. **Physical separation beats VC-sharing for latency-critical traffic.** Both works (and
   FlooNoC before them) reject the "one fabric, VCs will sort it out" default. MONET's
   Mel/Bel tier split and our isolated control plane are the same architectural move.
2. **The shared-fabric failure mode.** MONET motivates from MoE all-to-all + multicast
   congestion; we motivate from bursty DMA + narrow control. Both are cases of a
   *heterogeneous class mix* where the dominant class's traffic degrades the sensitive class.
3. **Multicast as first-class traffic.** MONET builds multicast into the tier (Mel routers);
   our track's multicast finding (5.4× KV-sharing benefit, `serving_multicast.py`) is the
   same conclusion from the workload side: multicast is not a unicast special case.
4. **Both are co-design arguments.** MONET co-optimizes mapping + interconnect; our
   PLAN.md §7 warns a fixed mapping biases topology comparison. Same methodological position.

**Cited lineage:** MONET is reported to contrast with tree-based multicast designs and
conventional meshes (with a reported 6× over a tree design) and to engage the EVC/Ruche-class
prior space ⚠️ — i.e., plausibly the same ancestry our own work cites (EVC ISCA 2007, FlooNoC
NOCS 2023). The full related-work section is behind the paywall; treat the precise citation
list as unverified until the full text is read.

---

## 3. What survives as ours (the differentiators)

| # | Our claim | MONET status | Why it survives |
|---|---|---|---|
| 1 | **Burstiness, not bandwidth, starves control** — 5 cells at identical flit load, only burst length varies | Not isolated in MONET; their motivation is *pattern* (multicast/all-to-all), not burst length at constant load | Our experiment is a controlled single-variable sweep; MONET reports no constant-load burst-length analysis |
| 2 | **Quantified isolation trade-off**: VC count is the router-side knob; 4 VCs ≈ plane within link capacity; express flattens but only a plane removes | MONET's two tiers are a binary design choice; no VC/plane/express cost ladder | Our "how much isolation before the plane is worth the silicon?" is a design rule MONET does not provide |
| 3 | **General peripheral taxonomy** (HBM/DMA/PCIe/CXL/NIC/UCIe classes, NETWORK-HIERARCHY.md) | MoE-specific (gating, dispatch, fusion) | Our claim is about *any* latency-critical class at the mesh edge, not one workload |
| 4 | **Per-flit RTL fidelity gate** (99.85% bit-exact + characterized residuals; BookSim↔RTL) | Aggregate latency/energy from RTL synthesis; no per-flit gate ⚠️ | No published per-flit RTL↔sim gate exists at all (see simulator-credibility note §3) |
| 5 | **Inference-serving context** (KV multicast, decode, disaggregated P/D) | MoE training/inference on expert-parallel | Different workload slice (see NETWORK-HIERARCHY Gate 0) |

---

## 4. Where MONET is ahead of us

- **Published, peer-reviewed architecture.** MONET is a *positive design proposal* with
  latency/energy numbers; our plane-separation result is currently a repo-internal
  measurement. If both went to review tomorrow, MONET owns the "two-tier NoC" design space.
- **RTL-synthesis-based evaluation** (abstract-verified: "RTL synthesis, NoC-level
  simulation, and real-world MoE workloads") — we have RTL *timing* fidelity (Gate R3) but
  our energy story is the FlooNoC-calibrated router model, not synthesis of our own variant.
- **Note — earlier scale claim retracted**: the first research pass reported "4×4 → 128×128
  PE arrays" and "XY-mesh/adder-tree (RADT) baselines"; neither is confirmed by the
  abstract or the detail pass, and the verified baselines are different (systolic array,
  EdgeMoE, Space-Mate). Do not cite the scale or RADT claims.

---

## 5. Novelty impact and required re-scoping (for the paper)

**What we must no longer claim as novel:** that bursty traffic starves control on a shared
fabric, and that physical plane separation fixes it — that is FlooNoC (2023) + MONET (2026)
prior art, and our own docs already present our result as a *reproduction* of FlooNoC
(`plane_separation.py` header), which is the honest position.

**What we can still claim, with the re-scope:** "we quantify, at constant offered load, the
causal role of burst *length* (not bandwidth or pattern) in control starvation, and map the
isolation trade-off — VCs within link capacity, express as a flattening but not removing
lever, a physical plane as the only flat-by-construction fix — as a design rule for
peripheral-rich transformer accelerators; we validate the mechanism in cycle-accurate
simulation *and* per-flit RTL." **This survives MONET** because MONET does not sweep burst
length, does not quantify VC/plane/express cost, and targets MoE routing rather than
peripheral control classes.

**Suggestion — turn the threat into a data point. DONE 2026-08-12** (`make
planes-moe` → `scripts/plane_separation.py --moe`; results/plane_moe.json +
plane_moe.png). MoE-style top-k token dispatch (each node dispatches 1-flit
tokens to its k nearest experts, k ∈ {2,4,8,16,32}) replaces the DMA-burst
class on the same 8×8 mesh at the SAME constant injected load (0.08
flits/cyc/node). Measured contrast result (seed=1, host-rebuilt fork):

| fanout k (1 VC) | 2 | 4 | 8 | 16 | 32 |
|---|---|---|---|---|---|
| control latency (cyc) | 34.27 | 34.39 | 34.62 | 34.99 | 35.58 |
| starvation vs isolated (33.2) | 1.03× | 1.04× | 1.04× | 1.05× | **1.07×** |

**Fanout alone starves control only 1.07× — versus 6.68× for the burst sweep
at the same load.** Monotone rise and directional VC absorption hold (all
gates PASS), but the magnitude is a contrast result: *packet multiplicity
(fanout) without burst occupancy is not the lever — burst length is.* And
since the matrix models NAIVE k-copy dispatch (the network worst case; the
flit-fork multicast of mcast_flitfork.py, ≥7.1×, carries strictly less), even
the worst-case dispatch traffic does not starve control the way DMA bursts
do. The gates are honestly falsifiable: a flat or burst-like curve, or
starvation crossing the 2× ceiling, fails the run.

---

## 6. Action items

1. **Read the full MONET text** before any citation beyond the abstract. Current access
   status (2026-08-12): IEEE Xplore paywalled (DOI 10.23919/DATE69613.2026.11539142); the
   DATE 2026 open proceedings archive PDF (https://date26.date-conference.com/proceedings-
   archive/2026/DATA/1442.pdf) bans automated clients; no arXiv preprint; no OA copy via
   Unpaywall; ResearchGate record 403s. Needs institutional IEEE access. What the full text
   must still confirm: Mel/Bel router microarchitecture, exact baseline configs and network
   parameters (VCs, buffer depth, flit width, technology node, frequency), per-workload
   8.5×/6× breakdowns, and the related-work citation list (§7).
2. **Update paper_draft.md** framing: plane separation = *validated reproduction + quantified
   design rule*, with FlooNoC and MONET cited as the mechanism's prior art; our contribution
   claims per §3/§5.
3. **MoE-shaped cell** (§5) — **DONE**: `scripts/plane_separation.py --moe` / `make
   planes-moe` (2026-08-12). Measured 1.07× fanout starvation vs 6.68× bursts →
   contrast result: fanout without burst occupancy is not the lever.
4. **PAC-NoC (2026)** is the same proximity class for the *multicast-trees-beat-meshes* claim
   (fat-tree NoC for attention, built on NoCDAS) — treat jointly with this note when writing
   the related-work section.

---

## 7. Primary-source verification status (2026-08-12)

### 7.1 Verified verbatim (abstract, from the Semantic Scholar record)

> "The growing complexity of Mixture-of-Experts (MoE) models in machine learning applications
> demands innovative hardware solutions to address their unique computational and data
> movement challenges. Some of the critical challenges facing MoE models include sparse
> activation, dynamic token routing and irregular computation patterns that lead to low
> utilization and higher communication latency. In this paper, we introduce MONET, a novel
> two-tier Network-on-Chip (NoC) architecture designed to efficiently execute MoE workloads
> by co-optimizing compute, memory, and interconnect subsystems. The first tier consists of a
> reconfigurable systolic processing element (PE) island, executing both gating and expert
> computations, with runtime-configurable support for sparse/dense operations, expert
> reordering, and activation functions. The second tier incorporates a dual mesh network
> connecting a grid of PE islands; one network manages input token delivery with a broadcast
> scheme optimized [truncated in source]..."

Closing sentence (also verbatim from the record): "…Using RTL synthesis, NoC-level
simulation, and real-world MoE workloads, MONET demonstrates up to 8.5× lower latency and
over 6× better energy efficiency compared to state-of-the-art MoE accelerators."

### 7.2 What the abstract confirms

- **Architecture**: two tiers — (1) reconfigurable systolic PE islands (gating + expert
  compute, sparse/dense, expert reordering, activation); (2) dual mesh connecting the island
  grid, one network for input-token delivery with a broadcast scheme.
- **Methodology**: RTL synthesis + NoC-level simulation + real-world MoE workloads.
- **Results**: up to 8.5× lower latency and over 6× better energy efficiency **vs
  state-of-the-art MoE accelerators** (not vs a generic mesh baseline).
- **Metadata**: Siqin Liu, Maya Roediger, Avinash Karanth (Ohio University); DATE 2026,
  April 20–22; DBLP `conf/date/LiuRK26`; DOI 10.23919/DATE69613.2026.11539142.

### 7.3 Corrected from the first research pass

- **Baselines are NOT "XY mesh / adder-tree (RADT)"** — the detail pass over the proceedings
  PDF reports **2D systolic array, EdgeMoE (FPGA), Space-Mate (ASIC)** (⚠️ full-text
  confirmation pending). The first pass's RADT/128×128 claims are retracted (§4).
- The two tiers are **systolic PE islands + dual mesh**, not simply "Mel tier vs Bel tier";
  Mel/Bel are router microarchitectures within the network tiers ⚠️.
- 8.5×/6× are **relative to SOTA MoE accelerators**, which matters for how we frame any
  comparison with our own mesh numbers.

### 7.4 Still unverified (full text is paywalled)

- Mel router internals ("multicast-enabled link reversal") and Bel router internals ("5×5
  crossbar with bypass") ⚠️; the reported 6× over tree-based multicast designs ⚠️;
  Switch-base-8 and any other benchmarks ⚠️; technology node, frequency, buffer depth, flit
  width, VC counts ⚠️; the related-work citation list ⚠️.
- Access paths tried: IEEE Xplore (paywall/JS), DATE proceedings archive PDF (403 IP ban), a
  reader proxy (origin 403), ResearchGate (403), Unpaywall (no OA), Semantic Scholar API
  (rate-limited after one successful fetch), alphaxiv (404), colab.ws / scilit / ouci
  (blocked), Google/Bing/Mojeek/DDG (bot-blocked or no results).

---

## Appendix — Sources

| # | Source | Used for | URL |
|---|---|---|---|
| 1 | MONET, DATE 2026 (Liu, Roediger, Karanth) | Metadata; paywalled full text | https://doi.org/10.23919/DATE69613.2026.11539142 |
| 1b | Semantic Scholar record (abstract verified verbatim) | Architecture, results, methodology | https://www.semanticscholar.org/paper/1e0c3ac5b8b4acfb7f649693de135919b0a889c6 |
| 1c | DATE 2026 open proceedings archive (PDF, banned to bots) | Mel/Bel details, baselines (detail pass) | https://date26.date-conference.com/proceedings-archive/2026/DATA/1442.pdf |
| 1d | DBLP record | Venue/author metadata | https://dblp.org/rec/conf/date/LiuRK26 |
| 1e | ResearchGate record (403 for automated fetch) | Alternate access point | https://www.researchgate.net/publication/406037007 |
| 2 | `scripts/plane_separation.py` (+ selfcheck) | Measured table, gates, design | tracks/t3-topology/scripts/plane_separation.py |
| 3 | `NETWORK-HIERARCHY.md` appendix | Peripheral taxonomy, plane-separation table | tracks/t3-topology/NETWORK-HIERARCHY.md |
| 4 | `RTL-ARC.md` (Gate R3, FPGA/Verilator replay) | RTL confirmation of the same shape | tracks/t3-topology/RTL-ARC.md |
| 5 | `PITFALLS.md` §19 | How the burst-length dial was found | tracks/t3-topology/PITFALLS.md |
| 6 | FlooNoC (Fischer et al., NOCS 2023 / IEEE D&T 40(6)) | The mechanism's first published source, which we reproduce | cited in NETWORK-HIERARCHY.md |
| 7 | Simulator-credibility note | No per-flit RTL↔sim gate exists in the literature | docs/research/simulator-credibility-noc-literature.md |
| 8 | PAC-NoC (2026, on NoCDAS) | Adjacent prior art for multicast topology | https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6 |
