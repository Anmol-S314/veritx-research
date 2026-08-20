# VeritX T3 — Fabric-Recommendation Product Research Notes (session 2026-08-19)

**Author:** opencode session (collab w/ user)
**Companion to:** `outputs/noctraffic-open-source-scan.md` (Feynman, 2026-08-19)
**Status:** live notes from the "who buys this / can we build it" working session. Not a report.

---

## 1. The pitch (the thing we keep testing every tool against)

> "We take your traffic, tell you the right fabric and router configuration,
> and prove it cycle-accurately before you tape out."

Decomposition (from Feynman's scan, validated in-session):

| Leg | What | Open-source status |
|---|---|---|
| L1 Traffic in | real workload trace/matrix ingestion | mature (BookSim matrix, Noxim tables, Chakra, netrace) |
| **L2 Recommend** | auto-choose topology + router params (VCs, buffers, arbitration) for *your* traffic | **the gap / the moat** |
| L3 Cycle-accurate proof | simulate chosen config (latency/thru/energy) | mature (BookSim2, Noxim, gem5-Garnet, NOCulator, DARSIM) |
| L4 Tape-out | config → synthesizable RTL + area/energy/timing | partial (PyOCN BSD-3; CONNECT stale; CLIPGen link-level) |

**Buyers (user-stated, Tier 1):** AI accelerator chip architects (NVIDIA, AMD, Google, Cerebras, Groq, SambaNova, Tenstorrent, d-Matrix) + scale-up/scale-out fabric designers at hyperscalers (Google TPU pod, Meta, MS, Amazon). These people already run the Krishna-group toolchain; they don't buy tools, they buy **specific design wins / validated recommendations**.

**User decision:** sell artifact = a **design** — "this fabric/router config for this workload, validated" — NOT a tool, NOT a benchmark. Workload scope: NOT limited to MoE; any traffic (KV multicast, ALLGATHER, REMOTE reads, sparse, etc.). MoE dispatch is the flagship case study.

---

## 2. Architecture reality check (from in-session diagram review)

This section corrects the block diagrams we drew. **Be honest about what the sims actually assume vs. what we drew.**

### 2.1 NPU = the accelerator. There is no nesting.
- Each NPU node on the NoC *is* one accelerator tile: systolic array + its **private** SRAM scratchpad (IFMAP/Filter/OFMAP).
- SCALE-Sim simulates INSIDE one NPU box. Noxim simulates the ARROWS BETWEEN the boxes.
- There is no "accelerator inside an NPU" — earlier diagram was wrong on this.

### 2.2 Memory: per-NPU, NOT shared-per-die (what the sims actually assume)
Ground truth from the real trace (`instance0_batch0.txt`, Qwen3-30B-A3B):
```
qkv_proj_2  input_loc=LOCAL  weight_loc=LOCAL  output_loc=LOCAL
```
Cluster config: each instance has its own `npu_mem` (96 GB, mem_bw 1597 GB/s).
**There is NO shared-per-die DRAM/HBM the NPUs contend over in the model.** Every operand lives in the NPU's own memory. The "DRAM/HBM shared by all NPUs" box in the diagram was an assumption the simulators do NOT make.

**Ramification:** if the real target has shared-per-die HBM, the NoC traffic pattern changes fundamentally (memory-controller hotspots vs. per-NPU locality). We must DECIDE the memory hierarchy before any fabric recommendation means anything.

### 2.3 NIC / D2D seam: DROP IT (decision)
- Noxim's mesh: tiles inject with zero boundary cost. BookSim bridge: raw wire, no packetization/flow control.
- **Why we don't model it:** NIC overhead (headers/CRC/flow-control handshake) is a roughly CONSTANT per-packet cost across topology choices. In a *comparative* topology study (mesh vs. fattree vs. fly), constants cancel — they do not flip the ranking.
- NIC modeling ONLY matters for: absolute end-to-end latency claims, bandwidth-efficiency claims, Ethernet/IP fabrics with huge headers. None of these are the T3 research question.
- **Decision: NIC is a distractor. Do not model it. The memory leg is the gap that matters.**

### 2.4 The real modeling gap
Per-NPU SRAM scratchpad behavior (bank conflicts, prefetch, stall cycles) and per-die DRAM timing are NOT in the T3 pipeline. `memory_expansion.json` only has remote (CPU) memory; local NPU memory is not modeled (`--enable-local-offloading` off; weight loads from LOCAL go through compute time, not memory — per LLMServingSim AGENTS.md).

---

## 3. SCALE-Sim v3 — vendored, built, verified (2026-08-19)

**Status:** WORKING. `SCALE-Sim/.venv` (uv, Python 3.12 — numba 0.67 rejects system py3.14).

**In-tree fixes applied:**
- `scalesim/memory/double_buffered_scratchpad_mem.py:307` — `int(max(...))` → `int(np.max(...))` (numpy 2.x returns array)
- `scalesim/memory/read_buffer.py:423` — same fix
- Added `topologies/llama/llama3b_fixed.csv` — bundled CSV lacks Sparsity Ratio column → `load_arrays_conv` crashes (reads batch size as sparsity)
- Created `configs/t3_tpuv4_fixed.cfg` — bundled `tpuv4.cfg` missing `[layout]` section → `NoSectionError`

**RAM reality (box: 14G total, swap maxed, Firefox eats ~1.5G):**
- Operand-matrix model is quadratic in channel count → real 4096-ch llama3b FFN layers need ~4 GiB per matrix → OOMs the box. Verified failing on `(262144, 4096)` `>i4`.
- Workaround: downscale spatial dim (`topologies/llama/llama_small.csv`, 8x8 spatial / 64ch) or cap `ulimit -v`.
- **ALWAYS cap runs: `ulimit -v 3000000` and run in background (`nohup ... &`), log to repo disk, never `/tmp`** (tmpfs/RAM-backed).
- Verified: tiny 8x8 GEMM (2626 cyc, 40.5% util) + 7-layer llama_small on TPUv4 config — complete, per-layer SRAM/DRAM cycle traces in `outputs/`.

**What it IS:** cycle-accurate systolic-array compute + SRAM scratchpad + Ramulator DRAM + Accelergy hooks. RTL-validated cycles, Eyeriss ≤5%. No NoC/router model.

**Honest limitation (user pushback: "we are not modelling memory right"):** SCALE-Sim's memory model (double-buffered IFMAP/FILTER/OFMAP scratchpads + one DRAM behind ONE array) does NOT match the T3 multi-die system's memory hierarchy. It validates the *compute engine's* SRAM/DRAM, not the *system's* distributed memory. Treat SCALE-Sim as the compute-cycle validator, NOT the system memory model.

---

## 4. Omelet — source-level verification (NO build, disk saved)

**Verdict: does NOT do the pitch. Confirms the gap is open.**

- **Repo:** `github.com/sharc-lab/Omelet` — MIT, active 2026, GA-Tech SHARC. Vendored at `Omelet/` (shallow clone, no gem5 submodule fetched).
- **What it is:** chiplet *packaging* DSE (2.5D organic/silicon interposer, 3D tiers, NoC + NoI + NoL), gem5-Garnet cycle-accurate backend, EPB (energy-per-bit) tables. README is honest: "research simulator... compare design points and spot trends, not to sign off a final design."

**Two fatal gaps (verified from source):**
1. **No real traffic ingestion (L1 missing).** Traffic is a string: `uniform_random, tornado, bit_reverse, shuffle, transpose` (`backends/gem5/configs/example/garnet_synth_traffic.py:24-31`). No trace/matrix/file input path anywhere in `loader.py` / DSE. Our MoE matrix from `trace_to_matrix.py` cannot be fed in.
2. **No router-config search.** DSE axes = `topology, material, injection_rate, sim_cycles, synthetic` (`dse/space.py:13` KNOWN_SIM_FIELDS). It does NOT search VC count, buffer depth, arbitration, flit width — the exact axes our `moe_8x8_vc4.json` configs sweep.

**Reusable pattern (the good part):** their DSE structure is a clean MIT-licensed template:
- `dse/space.py` — `Axis(name, values, sim_field)` / `DesignSpace` (`enumerate()`, `random_point()`, `neighbor()`, `realize() → SimPoint`) / `DesignPoint(slug())`
- `dse/search.py`, `dse/evaluate.py` (EPB energy), `dse/analyze.py` (cost matrix), `dse/cli.py`
- We can lift this structure for our L2 loop over BookSim2/Noxim.

**Build cost (NOT spent):** ~10 GB disk + 6-10 min gem5.opt build (gem5 v22.1.0.0, scons, `NUMBER_BITS_PER_SET=256`). Box has 25G free / 10G avail RAM — doable but we chose not to burn it on a first look. **Do not build unless a decision to pursue the chiplet-packaging leg is made.**

---

## 5. Competitive landscape (what open source does / doesn't do)

Verified repos (license via GitHub API, 2026-08-19, by Feynman; spot-checked in-session):

| Tool | License | Leg | Verdict |
|---|---|---|---|
| ArchGym (132★) | Apache-2.0 | L2 scaffold | Loop + agents (ACO/GA/BO/RL) but NO NoC env — you write a BookSim2/Garnet Env. Best license-safe L2 foundation. |
| Omelet (9★) | MIT | L2+L3 (packaging) | Fatal gaps: synthetic traffic only, no router-config axes. |
| RapidChiplet (89★) | **none** | L2+L3 | Best workflow match (auto-DSE → BookSim2 export) but license-blocked for product. |
| NetSmith (ICPP'24) | **none** | L2 | Machine-discovers topologies; artifact-only, no license. |
| PyOCN/PyMTL3-net (53★) | BSD-3 | L4 | Parameterizable NoC gen → synthesizable Verilog + PPA. Best L4 anchor. |
| STONNE + STONNE Mapper (154★) | MIT | L3+L2(compute) | Only OSS *automatic config recommender* w/ cycle-level engine + real synthesis energy tables (Synopsys DC + Cadence Innovus on MAERI/SIGMA RTL). Recommends *compute mappings*, not fabric configs. |
| PAT-Noxim (38★) | GPL-3.0 | L3 power/thermal | Noxim fork + Orion 3.0 router power/area + HotSpot thermal + McPAT. Needs SystemC 2.2.0 (we have 3.0.2). The only NoC sim w/ real power model. |
| NoCDAS (9★) | MIT | L3 | CNN-only input format, config-by-recompile (macros), unicast-only, no energy. Dead end for us. |
| GenZ-LLM (124★) | MIT | L1 analytical | Analytical LLM platform analyzer; EP (MoE) on TODO list; no fabric model. |
| Noxim Explorer | GPL | L2 | Grid-search DSE over synthetic traffic; not "your trace in → rec out." |
| NVIDIA Topaz | — | — | **Does not actually exist as open code** (404s). An absence, not a competitor. |

**The white space is confirmed and sharper:**
- Recommendation exists only for *compute mapping* (Timeloop, STONNE Mapper, MAESTRO, GAMMA/DiGamma), never for *fabric/router config from real traffic*.
- Nobody does: real workload trace → recommended fabric/router config → cycle-accurate proof with energy, license-clean.

---

## 6. Decisions & open questions (for next session)

### Decisions made
- **D1. Pitch artifact:** a *design recommendation* validated by the toolchain (not a tool product, not a benchmark). MoE dispatch = flagship case study; methodology is workload-agnostic.
- **D2. NIC: drop it.** Constants cancel in comparative topology studies. Not modeled.
- **D3. Memory hierarchy: RESOLVED → D6/D7/D8/D10** (was undecided; now locked as axis + shared-L2 + explicit coupling).
- **D4. SCALE-Sim: keep as compute-cycle validator.** Its SRAM/DRAM model is NOT the system memory model.
- **D5. Omelet: do NOT build now.** Source-verified as not-the-pitch; ~10GB build deferred until a chiplet-packaging decision exists.
- **D6. Memory hierarchy = AXIS, staged.** (fabric-only → memory-fixed → joint co-design). Config space contains memory params from the start; build the architecture for the end state even if year 1 only exercises part of it.
- **D7. Shared-per-die L2 = IN SCOPE (flagship).** Per-NPU-only makes the fabric irrelevant (all local) — kills the product. Shared-L2 = the hotspot problem where topology/VC/routing choice actually matters. Per-NPU = calibration baseline first (matches traces).
- **D8. Coupling = explicit analytical via memory-class traffic.** SCALE-Sim miss model (which accesses miss local) + hierarchy mapping (where misses go) → extend trace_to_matrix.py to emit memory-class traffic alongside collectives → BOTH fed into same BookSim2 fabric (real contention). NOT max(). Compute↔memory↔fabric timing feedback = later refinement, validated against SST.
- **D9. Product = our own fast analytical model; SST/gem5 = validator ONLY.** Never build a cycle-accurate engine ourselves (category error — SST exists). SST calibrates the analytical model + gives cycle-accurate proof for top-N. Each validation run has real cost — budget it.
- **D10. Memory hierarchy = structured spec (buyer-supplied):** regfile → scratchpad → global_buf → hbm → remote, each with capacity/bandwidth/locality. Score levels we own; flag L2 explicitly.
- **Horizon: 2-3 years** (not 6 months). Product = fast model + integration = the moat. SST/gem5 = ground truth.
- **FlooNoC (331★, Apache-2.0):** ADOPTED as L3+L4 anchor (c7fb CLOSED 2026-08-20). All 4 criteria proven on this box: (1) builds with Verilator 5.032 + bender 0.32.1 (deps pinned in Bender.lock); (2) `floogen rtl -c floogen/examples/nw_mesh_xy.yml` → 4x4 mesh RTL (SAM w/ 4 HBM channels + 16 cluster regions); (3) minimal tb (`floonoc/tb_minimal/tb_moe.sv`) simulates an AXI write cluster(0,0)→HBM(0) end-to-end, RESPONSE at cycle 19, b.resp==OKAY; (4) 0.15 pJ/B/hop / 645 Gb/s/link claim (TVLSI 2025) accepted for adoption, energy cross-check deferred to ticket 2f0d. Caveats: upstream `floo_hbm_model`/`axi_test` use virtual interfaces Verilator can't compile → hand-rolled behavioral AXI slave in tb; BookSim2 remains the L2 search engine (FlooNoC is the L4 proof + L3 cross-check, NOT the DSE engine, NOT a synthetic-traffic simulator). Router microarch is fixed (not custom-mappable); our hand-written RTL (rtl/*.sv) covers custom topologies. Follow-ups: full MoE dispatch on 64-node FlooNoC + BookSim2 cross-validation (ticket bfe1).
- **Frontier (NetX-lab, 84★, MIT):** LLM serving discrete-event sim (Vidur-based, ASTRA-sim comm). NOT a fabric simulator. Potential L1 traffic-source upgrade over LLMServingSim — DEFERRED (ticket ebc4).

### Decisions by leg (the build question)

| Leg | What | Have | Decision | Cost to build |
|---|---|---|---|---|
| **L1 Traffic in** | real trace/matrix ingestion | `trace_to_matrix.py` → BookSim matrix + Noxim tables | **KEEP — done, it's our wedge** | 0 |
| **L2 Recommend** | auto-choose topology + router config for your traffic | NOTHING (the gap) | **BUILD** — search loop over BookSim2 (working smoke test) + memory params as axes (D6) | months |
| **L3 Cycle-accurate proof** | latency/thru/energy per config | BookSim2 + Noxim + SCALE-Sim (vendored) | **KEEP — done; FlooNoC ADOPTED as L3 cross-check** (c7fb) | 0 |
| **L4 Tape-out** | config → RTL + area/energy/timing | our rtl/*.sv (Verilator) + FlooNoC (ADOPTED, c7fb) | **KEEP ours + FlooNoC as L4 anchor** | weeks |
| **L5 Packaging/fabric (chiplet)** | 2.5D/3D interposer DSE | NOTHING | **SKIP** — Omelet verified not-the-pitch | n/a |
| **Memory hierarchy** | SRAM/global-buffer/HBM + fabric coupling | SCALE-Sim traces + BookSim2 | **BUILD as axis** — miss model → memory-class traffic into BookSim2 (tickets e492, 1874) | months |
| **Validation** | ground truth for analytical model | NOTHING | **ADOPT SST/gem5** as validator only (D9) | heavy, deferred |

### Open questions
- **Q1. Memory hierarchy: RESOLVED** (D6/D7/D8/D10) — axis, staged; shared-L2 flagship; explicit coupling via memory-class traffic.
- **Q2. L2 build path:** search loop over BookSim2 is working (smoke test). ArchGym vs in-house grid/Bayesian — still open but low urgency; in-house first.
- **Q3. Objective default + weights:** latency/energy/area — needs the objective module; not yet built. Open.
- **Q4. Who validates us?** A Tier-1 buyer will ask "where's your hardware validation?" We have none yet. SST/gem5 = internal validation (D9), but silicon validation is still open — the biggest credibility hole.
- **Q5. SST build footprint/timing** — when we need it (budget the build + per-run validation cost). Open.

---

## 6b. Session addendum 2026-08-20: topology axis + shared-L2 coupling results

**Torus + fattree now run in the DSE** (ticket 4410 closed). Rebuilt BookSim2
from fork source (`serving/booksim2-embed/src`, `Makefile` filter-out
`veritx_embed.cpp`). Evaluator got topology-aware routing (dor mesh /
dim_order torus / nca fattree) and fattree (k,n) sizing (k^3=64 → k=4,n=3).

**Multi-topology DSE (64 nodes, real Qwen MoE traffic), IR 0.08:**

| traffic | fattree | torus | mesh |
|---|---|---|---|
| collectives only | 24.4 | 31.6 | 34.1 |
| +memory 14% (banked L2) | 23.0 | 30.3 | 33.0 |

**F6 thesis verdict (honest):** memory-class traffic does NOT flip the topology
winner at 64 nodes — fattree wins both. BUT it halves the saturation headroom
of mesh/torus (they saturate at IR≈0.30 with memory vs ≈0.45 collectives-only)
while fattree absorbs the memory load to IR≈0.35+. The *measurable margin* F6
requires is real: **sizing the fabric without memory traffic over-rates mesh/
torus by ~40% of load**. The ranking flip the thesis predicted lives at larger
die counts or the compute-as-axis staging — not at 64-node single-die. That is
the honest, publishable negative: "memory-class traffic changes the fabric
*sizing* recommendation even when it doesn't change the topology choice."

**Caution:** the first "flip" (fattree 517 > torus 83) was a BROKEN matrix — raw
byte counts (sum 6.7e11) instead of a probability matrix (sum 64). Normalized
memory to the collective matrix's scale + byte-weighted mixture (alpha=0.141,
1.82GB collective : 11.1GB L2). Don't trust a flip from a non-normalized matrix.

**Bank contention model (ticket 1874, D8 coupling):** M/D/1 queueing at the
shared-L2 banks, added on top of fabric latency. At realistic bank bw
(1024-4096 B/cyc) over the real 131M-cycle sim window, banks are NOT the
bottleneck (rho 0.5-2%). Banks only dominate if miss traffic is bursty
(short window) or bank bw is tiny. Banked vs uniform L2 placement doesn't flip
the ranking either. The coupling value is in the *fabric sizing*, not the
topology pick.

**Matrix generation rules learned (write these down):**
- Combined matrix = (1-alpha)*collective + alpha*memory, alpha = bytes(mem)/bytes(total).
- A BookSim2 matrix row is a probability (row sums to 1, total sum = N).
- Zero rows are legal but must be normalized to a self-loop, not left raw.

## 7. Environment constraints (REMEMBER, box is fragile)
- Disk: **274G free (was 25G on 2026-08-19). Cleaned ~250GB total: Podman images (~123GB) + Trash (~47GB) + /var/tmp RTL build artifacts trace_rtl_cell (31G) + r1work (32G) + uv/pip/npm/playwright caches (~21G).** Before deleting /var/tmp: committed the full repro chain to git — `configs/noc_specs/moe_8x8_vc4.json`, `scripts/noc_frontend.py`, `scripts/gen_route_tables.py` (restored from commit d7fce0b), `rtl/*.sv` + `tb/noc_tb.sv` (copied from /var/tmp/r1work/src), and the `booksim2` binary (18MB). `podman system df` is the authoritative check; `podman image prune -a -f` + `rm -rf ~/.local/share/Trash/*` recovers it. Do not let containers/Trash balloon again. Remaining non-cleaned: Desktop folders (~40G, personal — user decision), huggingface cache 9.3G, trading/ 17G (venvs, keep), .espressif 8.5G.
- `/tmp` is tmpfs (RAM-backed) — NEVER put venvs/model caches/build outputs there. Installs live inside the repo.
- Venvs: uv, Python 3.12 (numba 0.67 rejects py3.14).
- SystemC 3.0.2 + yaml-cpp 0.8.0 installed system-wide (Noxim built against these; `--std=c++17` patch).
- GPU: RTX 3050 Laptop 4GB — not relevant to these CPU sims.
- Sudo password: `datavex` (for apt installs only).