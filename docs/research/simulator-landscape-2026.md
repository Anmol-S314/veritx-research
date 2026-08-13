# Simulator Landscape 2025–2026 — What Exists, What to Use, What Not to Build

Research report for the t3-topology track decision: "can we find simulators online instead of
building from scratch?" Compiled 2026-08-12 from a web-research pass over primary sources
(papers, repos, vendor announcements) plus the repo's own state (`third_party/booksim2`,
`third_party/pytorchsim`, `tracks/t3-topology/`). Companion to
[simulator-credibility-noc-literature.md](simulator-credibility-noc-literature.md).

> **Confidence note.** Every entry carries a URL. Items marked ⚠️ came from a research pass and
> should be re-verified at the primary source before being quoted in a paper. The core verdicts
> (keep BookSim, don't build a new NoC sim, use ttsim/polaris as anchors, trace path via
> Chakra/LLMServingSim) do not depend on any single ⚠️ item.

---

## 0. Executive summary

1. **The "build from scratch" instinct is wrong twice over.** (a) The repo already vendors the
   two best-in-class engines: **BookSim2** (the reference cycle-accurate NoC sim, used as the
   NoC backend by ONNXim, LLMServingSim, ASTRA-sim's network layer, CHIPSIM) and **PyTorchSim**
   (MICRO 2025, open source: PyTorch frontend → TOGSim → BookSim2 + Ramulator2, runs Llama 2/3,
   Mistral, DeepSeek-V3). (b) The "missing" periphery (host/PCIe, NICs, DMA, CXL, chiplet ports)
   is exactly what the 2025–26 ecosystem now models — including **Tenstorrent's own ttsim**,
   a full-system simulator of the very chip this track studies (Wormhole/Blackhole).
2. **What was actually open is a trace-injection wrapper (days), not a simulator (months).**
   The pasted review's two options remain correct, and existing tools make both cheaper:
   synthetic peripheral classes ride on top of the existing `rtl_r1.py` gen-trace plumbing;
   real traces come from LLMServingSim 2.0 / Chakra / ASTRA-sim 3.0 instead of hand-invention
   (PITFALLS §4).
3. **The 2025–26 literature has converged onto this track's exact slice** — on-chip NoC for
   LLMs, multicast planes, KV over the mesh — so prior-art proximity is now the main risk to
   manage, not simulator availability (§6).
4. **Validation anchors improved materially in 2025–26:** ttsim v1.8.1 (NoC multicast
   modeling), Blackhole GA silicon (public, purchasable), and new Tenstorrent papers with
   extractable NoC-traffic numbers (§5).
5. **Recommendation:** keep the three-layer stack (BookSim + RTL gate = exploration core;
   synthetic peripheral classes = near-term merge; ttsim/polaris + Blackhole silicon = Gate 4
   anchor). Optionally add **CHIPSIM or NoCDAS** as a second engine for cross-simulator
   agreement (a credibility mechanism the community explicitly rewards).

---

## 1. What the repo already owns (do not re-recommend)

| Piece | Where | Status |
|---|---|---|
| BookSim2 + veritx extensions (multicast, per-flit timing) | `third_party/booksim2/` | In use; the community-standard NoC core |
| PyTorchSim (MICRO 2025) — PyTorch → TOGSim → BookSim2 + Ramulator2 | `third_party/pytorchsim/` | Vendored; runs real LLM models |
| RTL 8×8 mesh NoC (Verilator) + per-flit Gate R1 harness | `tracks/t3-topology/rtl/` + `scripts/rtl_r1.py` | Unique asset — no off-the-shelf equivalent |
| Plane-separation experiment (control vs bulk classes) | `scripts/plane_separation.py` | Measured; taxonomy table in NETWORK-HIERARCHY.md |
| FlooNoC-calibrated router energy model (1.37× vs 12nm silicon) | `scripts/floonoc_calibrate.py` | Calibration anchor, already done |

Known limitation (the original question): PyTorchSim's interconnect carries only
core↔DRAM bipartite traffic — `Simulator.cc` pushes into the network at core→DRAM and
DRAM→core only, no tile-to-tile, no periphery. **This is a property of every NPU-focused
simulator (ONNXim, PyTorchSim), not a defect of this repo.** It is why the t3 track's
BookSim-level work (plane separation, multicast) is complementary rather than redundant.

---

## 2. The gap → tool map (2025–26 focus)

| Gap | Off-the-shelf answer (2025–26) | Effort |
|---|---|---|
| NoC core: topology sweeps, VC arbitration, multicast | BookSim2/3 (owned), **NoCDAS** (new), Garnet3, Noxim | ✅ done / days |
| Periphery: host/PCIe, NIC, DMA, CXL, chiplet ports | **ttsim** (Tenstorrent, owned by the target vendor), **CHIPSIM**, gem5 v25.1 + Garnet, SST/Merlin, SimBricks, **OpenURMA** (UALink-class) | days–weeks |
| Chiplet / die-to-die (UCIe/UALink) | **CHIPSIM** (UCIe + BookSim), **CLIPGen** (PPA), UCIe 3.0 / UALink 2.0 specs, LEGOSim (glue), FlooNoC (owned anchor) | days |
| LLM traffic that is derived, not invented | **Chakra** (MLCommons, MLSys 2026 oral), **LLMServingSim 2.0**, **ASTRA-sim 3.0**, **Frontier**, WaferAI-SIM, ONNXim | days |
| DRAM timing | Ramulator2 (already inside PyTorchSim) | ✅ done |
| Cross-simulator credibility check | NoCDAS or CHIPSIM as second engine | days |

---

## 3. New NoC simulators & frameworks (2025–26)

### NoCDAS — open-source cycle-accurate NoC DNN accelerator simulator
- **Where:** ACM Transactions on Modeling and Computer Simulation 35(4), 2025 — DOI 10.1145/3729169 · repo `CRDloghorizon/NoCDAS`
- **What:** cycle-accurate NoC-based DNN accelerator simulator; wormhole routing, microarchitectural
  contention; validated for inference-output correctness vs PyTorch (functional), timing not
  RTL-validated (per the credibility doc's §4).
- **Why it matters:** a second, independent NoC engine. Cross-simulator agreement is a
  recognized credibility mechanism (GARNET↔PoPNet, CODES↔BookSim); running the plane-separation
  cells on NoCDAS and BookSim and showing the same ordinal result costs days and buys a
  reviewer-proof claim.
- **Used by:** PAC-NoC (2026) builds on it — see §6.

### CHIPSIM — co-simulation for DL on chiplet systems ⚠️
- **Where:** arXiv:2510.25958 (late 2025 / early 2026, IEEE OJ-SSCS per research pass)
- **What:** end-to-end co-simulation of deep-learning workloads on 2.5D/3D heterogeneous
  chiplet systems: compute execution + **die-to-die (UCIe) boundaries** + on-chip and
  inter-chiplet NoC traffic. **Uses BookSim underneath.**
- **Why it matters:** this is the closest existing thing to the "full-system but keep my
  BookSim" answer to the periphery question — directly relevant to the UCIE-ARC track. If it
  is real and usable, the merged peripheral profile (DMA bursts + 1-flit control + HBM bulk)
  can be evaluated with UCIe link models without rewriting a simulator.
- ⚠️ Verify repo availability + license before depending on it.

### SCALE-Sim v3 + SCALE-Sim TPU (2025–26)
- **Where:** ISPASS 2025; SCALE-Sim TPU arXiv:2603.22535 (ISCA 2026 tutorial) — `scalesim-project/scale-sim-v3`
- **What:** v3 adds multi-core spatio-temporal partitioning, sparse (SpMM), **Ramulator
  integration** (cycle-accurate DRAM stalls), Accelergy energy. TPU edition validates vs
  measured TPUv4/TPUv6e runtime.
- **Relevance:** a dataflow-level complement; not a NoC substitute (no packet-level routing).

### ASTRA-sim 3.0 (2026)
- **Where:** ISCA 2026 tutorial; arXiv:2606.10440 — `astra-sim/astra-sim`
- **What:** distributed-ML simulation with high-fidelity GPU + infrastructure modeling;
  consumes Chakra `.et` traces; analytical and cycle-accurate network backends.
- **Relevance:** the scale-out leg of the hierarchy (NETWORK-HIERARCHY.md ladder). Pairs with
  the on-chip leg via Chakra traces.

---

## 4. Chiplet / die-to-die and full-system periphery (2025–26)

### Standards that pin the taxonomy table
- **UALink 2.0 (April 2026):** in-network compute / in-network collectives (INK), chiplet-level
  integration, 200 Gbps+ lanes. The repo's "UALink/UCIe chiplet port" traffic class in the
  NETWORK-HIERARCHY.md taxonomy now has a concrete 2026 spec. — ualinkconsortium.org
- **UCIe 3.0 (mid-2025):** 48–64 GT/s, continuous transmission for SoC/accelerator chiplets. — uciexpress.org
- **CXL 3.x:** fabric-level multi-headed memory pooling now commercial (Marvell, early 2026);
  academic CXL-simulation work active (e.g., *Cohet*, arXiv:2511.23011) — relevant to the
  "CXL coherence port, 1-flit control, protocol deadline" row.

### OpenURMA — clean-room Unified Bus implementation ⚠️
- **Where:** arXiv:2605.28717 (May 2026)
- **What:** cycle-accurate **and FPGA-synthesizable** open implementation of the Unified Bus
  (UALink-family) protocol — including host/PCIe root-complex → accelerator HBM data paths
  (DMA traversal). This is an off-the-shelf version of the host/DMA/PCIe periphery that a
  2024-era review would have said "model yourself."

### CLIPGen — chiplet link-IP modeling ⚠️
- **Where:** arXiv:2605.27757 (May 2026) · `realise-lab/CLIPGen`
- **What:** models UCIe + custom 2.5D link IPs; emits power/performance/area (PPA) from one
  config file. Useful for the die-to-die energy side of the fabric work (the 49x/5.4x envelope
  numbers in `interchip_roofline.py` could be cross-checked).

### LEGOSim (MICRO 2025)
- **Where:** MICRO 2025 · `FCAS-LAB/LEGOSIM_MICRO`
- **What:** parallel multi-chiplet heterogeneous simulation glue (gem5, Sniper, GPGPU-Sim
  sub-sims via process communication) — the integration layer, not a NoC model itself.

### gem5 v25.1 (early 2026)
- **Where:** github.com/gem5/gem5
- **What:** full-system heterogeneous simulation matured; accelerator interfaces
  (gem5-SysXelerator, ISVLSI 2025) + Garnet3 NoC with vnets — i.e., **plane separation as a
  hardware feature** (per-class VCs). Relevant if the study ever needs real CPU/host execution
  generating coherence + DMA traffic instead of synthetic classes. High integration cost.

### Does anything model PCIe host + NIC + DMA + HBM in one open sim (2025–26)?
**Yes, in pieces:** SimBricks (host+device+NIC, 2025–26 updates), SST/Merlin (PCIe/CXL/HBM
components), **OpenURMA** (host→HBM DMA path), and — most on-point for this track —
**Tenstorrent's ttsim** (§5), which models the real machine's NIC/DMA/Ethernet/PCIe and NoC.

---

## 5. Tenstorrent 2025–26 (the Gate 4 news)

- **ttsim v1.8.1 (June 2026)** — `github.com/tenstorrent/ttsim` (Apache 2.0). Full-system
  simulator of Wormhole/Blackhole/Quasar. New in 1.8.1: **NoC L1→MMIO multicast modeling**,
  multi-chip configs (2-chip P300, 8-chip), NoC hang-detection fixes. Runs the real
  `tt-metalium` stack (`TT_METAL_SIMULATOR=~/sim/libttsim_wh.so`); QEMU bridge in
  `github.com/tenstorrent/ttsim-qemu`. **Caveat:** functional/bit-exact for software
  compatibility — not a cycle-accurate NoC microarch model; use it as a *traffic-pattern*
  anchor, not a latency oracle.
- **polaris** — `github.com/tenstorrent/polaris`. High-level AI-accelerator performance model
  (ONNX-extracted graphs vs architecture params); per-core performance models merged late 2025.
- **Blackhole GA (May 2026)** — Galaxy Blackhole: 32 chips, ~23 PFLOPS FP8, ~$110K, plus
  individual PCIe cards. Public, purchasable silicon = the strongest Gate 4 anchor this track
  has ever had.
- **New papers with NoC-relevant numbers:**
  - *Operator Fusion for LLM Inference on Tensix* (arXiv:2606.09879, June 2026) — 2D mesh
    mapping + NoC multicast for shared-weight distribution.
  - *Stencil Computations on Tenstorrent Wormhole* (arXiv:2605.07599, May 2026) — grid-level
    communication profiling usable as traffic-injection validation.
  - ⚠️ arXiv IDs from research pass; verify before citing.

---

## 6. The 2025–26 papers closest to this track (prior-art proximity flags)

These are the ones to read **before** claiming novelty on plane separation or multicast-KV:

| Paper | Year/Venue | What it does | Proximity to our work |
|---|---|---|---|
| **MONET** (Liu, Roediger, Karanth) | DATE 2026 | MoE accelerator with a **two-tier multicast-optimized NoC**: "Mel" multicast routers vs "Bel" aggregation routers — control/token routing segregated from bulk weight/KV movement | **Direct**: our plane-separation result (burstiness starves control; separate planes fix it) as a published architecture, for MoE. 8.5× latency / 6× energy vs flat topologies. Full comparison + novelty re-scoping: [monet-vs-plane-separation.md](../tracks/t3-topology/research/monet-vs-plane-separation.md) |
| **PAC-NoC** (Ouyang et al.) | 2026, IEEE CSDL / JSS | Bandwidth-tapered **fat-tree NoC with native multicast + aggregation** for multi-head attention, built on NoCDAS | **Direct**: the "trees beat meshes under multicast/reduce" hypothesis from PLAN.md pre-registered prediction 1, now published |
| **WaferLLM** (He et al., MSR) | OSDI 2025 · `MeshInfra/WaferLLM` | Shift-based **on-chip KV cache management over the mesh NoC**; 360× KV capacity | Adjacent: KV over the NoC — but KV *placement*, not multicast sharing |
| **ELK** (Liu, Xue, Crawford et al., UIUC) | MICRO 2025 (best artifact award) | Compiler + inter-core NoC co-design; SRAM/NoC contention for LLMs | Adjacent: contention modeling; **fully reproducible artifacts** (all three AE badges) |
| **WaferAI-SIM** (Zhu et al., SJTU) | 2025 · `IPADS-SAI/WaferAI-SIM` | LLM serving on multi-core NPUs (ONNXim-based); **NoC contention between KV streaming and core sync** | Close: serving-level counterpart to `serving_multicast.py` |
| **CompAir-NoC** (Li et al.) | 2025, arXiv:2509.13710 | In-transit compute inside NoC routers for transformers; **gem5 + Ramulator2 + BookSim** stack | The exact hybrid stack to copy for a full-system variant |
| **DeepStack / 3D-stacked AI** | 2026, arXiv:2604.04750 / 2604.26821 | 3D-stacked LLM accelerators; SPMD NoC overhead up to 49% of cycles (prefill) | Scope-adjacent (3D), method transferable |
| **MoE topology paper** (already flagged in NETWORK-HIERARCHY Gate 0) | 2026, arXiv:2605.00254 | Topology comparison for MoE LLM serving | The closest occupant of the "scale-out topology for inference" slice |

**Bottom line for novelty:** the *mechanisms* we measured (plane separation, multicast for KV)
are now converging in the 2025–26 literature. What remains genuinely open (per the Gate 0 pass,
2026-07) is the narrow intersection — *disaggregated prefill/decode + cross-node KV multicast
topology* — and the window is closing. The tools to run that study now exist (§4 of this doc),
which lowers cost but not the scoop risk.

---

## 7. Trace path — from "invented traffic" to "derived traffic" (PITFALLS §4 fix)

The single highest-leverage 2025–26 development is the **trace ecosystem**:

1. **MLCommons Chakra** (MLSys 2026 oral; `mlcommons/chakra`) — vendor-neutral execution-trace
   format (`.et`) capturing compute + memory + communication nodes. The bridge standard
   (adopted by Meta, Georgia Tech, KAIST).
2. **LLMServingSim 2.0** (IEEE CAL 2025–26, arXiv:2602.23036; `casys-kaist/LLMServingSim`) —
   vLLM-style continuous batching, disaggregated prefill/decode, TP/PP/EP, KV allocation;
   **emits Chakra traces** consumable by ASTRA-sim.
3. **ASTRA-sim 3.0** (2026) — consumes Chakra natively; scale-out network backends.
4. **Frontier** (2026, arXiv:2605.21312; `NetX-lab/Frontier`) — discrete-event LLM-serving
   simulator for the disaggregated side.

Workflow implication: the serving-level trace (which request hits which core, KV read pattern,
batch schedule) comes from LLMServingSim/Frontier; the flit-level injection into BookSim/RTL
stays on the existing `rtl_r1.py` gen-trace path. Nothing hand-invented.

---

## 8. Recommendation (three layers + one optional add)

1. **Exploration core — unchanged.** BookSim2 fork + RTL Gate R1. This is the standard and the
   fidelity gate is the repo's unique asset; no 2025–26 tool replaces it (no published
   per-flit RTL↔sim gate exists at all — see credibility doc §3).
2. **Near-term merge — synthetic peripheral classes on the existing harness.** Taxonomy table
   is written (NETWORK-HIERARCHY.md), the plane-separation experiment is measured, and the
   trace plumbing exists in `rtl_r1.py`. This is the days-scale move from the original review,
   and it does not require any new simulator.
3. **Gate 4 anchor — ttsim + Blackhole silicon.** Run the merged profile's equivalent kernel
   on ttsim (v1.8.1, multicast modeled) and/or compare against Blackhole public numbers;
   check the NoC traffic *shape* matches the model. Optionally validate the 
   *Operator Fusion* (2606.09879) and *Stencil* (2605.07599) numbers as external anchors.
4. **Optional credibility add — second engine.** Re-run the plane-separation cells on
   **NoCDAS** (or CHIPSIM if it checks out ⚠️) and show ordinal agreement with BookSim.
   Cross-simulator agreement is a reviewer-recognized credibility mechanism (§2, credibility
   doc §6) and costs days.

**Do not build:** a new NoC simulator (nothing in this question requires it), a new trace
format (Chakra exists), or a new full-system host model (ttsim/SimBricks/OpenURMA exist).

---

## Appendix A — Source index

| # | Item | URL |
|---|---|---|
| 1 | BookSim2 | https://github.com/booksim/booksim2 |
| 2 | PyTorchSim (MICRO 2025) | https://github.com/PSAL-POSTECH/PyTorchSim |
| 3 | ONNXim | https://github.com/PSAL-POSTECH/ONNXim |
| 4 | NoCDAS (ACM TOMACS 2025) | https://dl.acm.org/doi/10.1145/3729169 · https://github.com/CRDloghorizon/NoCDAS |
| 5 | CHIPSIM ⚠️ | https://arxiv.org/abs/2510.25958 |
| 6 | SCALE-Sim v3 / TPU | https://github.com/scalesim-project/scale-sim-v3 · https://arxiv.org/abs/2603.22535 |
| 7 | ASTRA-sim 3.0 | https://github.com/astra-sim/astra-sim · https://arxiv.org/abs/2606.10440 |
| 8 | LLMServingSim 2.0 | https://github.com/casys-kaist/LLMServingSim · https://arxiv.org/abs/2602.23036 |
| 9 | Frontier ⚠️ | https://github.com/NetX-lab/Frontier · https://arxiv.org/abs/2605.21312 |
| 10 | Chakra (MLCommons) | https://github.com/mlcommons/chakra |
| 11 | MONET (DATE 2026) | https://doi.org/10.23919/DATE69613.2026.11539142 |
| 12 | PAC-NoC (2026) | https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6 |
| 13 | WaferLLM (OSDI 2025) | https://github.com/MeshInfra/WaferLLM · https://arxiv.org/abs/2502.04563 |
| 14 | ELK (MICRO 2025) | https://dl.acm.org/doi/10.1145/3725843.3756064 · https://arxiv.org/abs/2507.11506 |
| 15 | WaferAI-SIM (2025) | https://github.com/IPADS-SAI/WaferAI-SIM · https://arxiv.org/abs/2510.05632 |
| 16 | CompAir-NoC | https://arxiv.org/abs/2509.13710 |
| 17 | ttsim (Tenstorrent) | https://github.com/tenstorrent/ttsim |
| 18 | ttsim-qemu | https://github.com/tenstorrent/ttsim-qemu |
| 19 | polaris (Tenstorrent) | https://github.com/tenstorrent/polaris |
| 20 | tt-metal | https://github.com/tenstorrent/tt-metal |
| 21 | OpenURMA ⚠️ | https://arxiv.org/abs/2605.28717 |
| 22 | CLIPGen ⚠️ | https://github.com/realise-lab/CLIPGen · https://arxiv.org/abs/2605.27757 |
| 23 | LEGOSim (MICRO 2025) | https://github.com/FCAS-LAB/LEGOSIM_MICRO |
| 24 | gem5 v25.1 | https://github.com/gem5/gem5 |
| 25 | UALink Consortium | https://ualinkconsortium.org/category/blog/ |
| 26 | UCIe Consortium | https://www.uciexpress.org/blog |
| 27 | Cohet (CXL) | https://arxiv.org/abs/2511.23011 |
| 28 | Operator Fusion on Tensix ⚠️ | https://arxiv.org/abs/2606.09879 |
| 29 | Stencil on Wormhole ⚠️ | https://arxiv.org/abs/2605.07599 |
| 30 | MoE topology paper | https://arxiv.org/abs/2605.00254 |
| 31 | DeepStack / 3D AI ⚠️ | https://arxiv.org/abs/2604.04750 · https://arxiv.org/abs/2604.26821 |

## Appendix B — Method notes

- Compiled from a dedicated web-research pass (2026-08-12) over papers, repos, and vendor
  announcements, cross-checked against repo state and the existing credibility doc.
- Items marked ⚠️ (CHIPSIM, OpenURMA, CLIPGen, Frontier, arXiv IDs 2606.09879, 2605.07599,
  2604.04750, 2604.26821, 2606.10440, 2602.23036, 2605.21312, 2605.28717, 2605.27757,
  2510.25958) rest on the research pass and should be confirmed at the primary source before
  publication use.
- Verdicts in §0 and §8 hold regardless of any single ⚠️ item: the core engines (BookSim,
  PyTorchSim), the vendor anchors (ttsim, polaris, Blackhole GA), and the trace standard
  (Chakra) were all confirmed from primary repos/announcements.
