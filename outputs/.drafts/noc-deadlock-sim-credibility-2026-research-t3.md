# T3 Research Brief — NoC Simulator Landscape 2026: New Tools & Releases

- **Date:** 2026-08-14
- **Scope:** 2025–2026 NoC/interconnect simulation tooling — new simulators, frameworks, major releases, and the validation/credibility evidence each ships. 2026 items first.
- **Relation to background:** extends `docs/research/simulator-landscape-2026.md` (compiled 2026-08-12) with fresh primary-source checks (including everything re-checked on 2026-08-14, i.e., after that doc was written). §7 lists corrections to that doc.
- **Method note:** no PDF bodies were fetched or parsed. Claims come from HTML pages, GitHub READMEs/repos, arXiv abstract pages, vendor docs, and API metadata. Where only a PDF exists, the PDF URL is cited and full-text parsing is marked **blocked**.

---

## 1. Key question answers (summary)

| # | Question | One-line answer |
|---|----------|-----------------|
| 1 | ASTRA-sim 3.0 (2026) | Paper + ISCA 2026 tutorial exist (arXiv:2606.10440); adds cache-line load-store granularity, detailed GPU model, MSCCL++ collectives, InfraGraph. **Not in the public repo yet** — README still says v2.0; issue #380 asking for the 3.0 release timeline is open with zero comments as of 2026-08-14 [1][2][3][4] |
| 2 | gem5 v25.x NoC changes | **No major NoC/Garnet changes** in v25.0/v25.1 release notes (CPU/ISA-focused). Garnet3/vnets are baseline features since ~2020, not new in v25.1 [7][8][10] |
| 3 | New simulators: NoCDAS, CHIPSIM, LEGOSim, SCALE-Sim v3/TPU | NoCDAS: MIT, functional-only validation, low activity. CHIPSIM: initial-release quality, **no LICENSE file**, uses **Garnet not BookSim**. LEGOSim: MICRO 2025, active, **no LICENSE file**. SCALE-Sim v3: legacy repo, main repo is SCALE-Sim; TPU edition validated vs TPU v4 (+v6e per tutorial) [12][15][17][21][22][19][20] |
| 4 | BookSim 2025–26 | **No upstream activity since 2024-06-24; no BookSim 3.x exists.** Effectively unmaintained upstream; community forks carry extensions [25][26][46] |
| 5 | Other notable 2025–26 | tt-npe (Tenstorrent NoC estimator, Apache-2.0, active), ttsim v1.10.0, DICE (ISCA 2026 chiplet sim, all-3-artifact), PAC-NoC (TVLSI preprint), MLSys 2026 collective NoC, CAMINOS (Rust), Noxim April 2026 release, PLENA simulator. Industry: NVIDIA DSX Air + NVLink 6 blog; AMD Versal NoC sim docs — **no open-source NVIDIA/Intel NoC simulator found** in window (absence-of-results inference, see §6) [27][28][32][34][35][36][31][42][43][44] |
| 6 | Per-tool (a)–(d) | §2 per-tool blocks + §3 matrix |

---

## 2. Per-tool blocks

### 2.1 ASTRA-sim 3.0 (2026) — *paper & tutorial exist; code not yet public*

**(a) What it models.** Distributed-ML (scale-out/scale-up) simulation: workload scheduling, collective-communication algorithms, compute/memory/network hardware. v3 (per paper abstract) adds: simulation at cache-line-sized (≈128 B) **load-store granularity**, a **detailed GPU execution model** (compute units, wavefronts, HBM channels, I/O ports), **MSCCL++** custom-collective support, and **InfraGraph** — a vendor-neutral graph representation of network infrastructure [1][4]. Per the ISCA 2026 tutorial (AMD + Georgia Tech, 2026-06-27), v3 also covers inter-GPU protocols (Simple/LL/LL128), HTSim (Ultra Ethernet) as a new network backend, ns-3, memory tiering via extended Chakra traces, and Chakra `.et` trace input [4].

**(b) Validation/calibration evidence.** The abstract reports design-space exploration (collective algorithms, network requirements, GPU architecture), **not** hardware-validation numbers [1]. The alphaXiv overview (secondary, AI-generated) reports an evaluation showing simulation time scaling linearly to 128 GPUs [6]. The *public 2.0 repo* ships a calibrated example: `examples/network/analytical/HGX-H100-validated.yml` (8-GPU switch topology, 400 GB/s, 936.25 ns latency) [5]. The 3.0 paper's own validation numbers could not be checked (PDF body — blocked).

**(c) License/repo.** MIT; `github.com/astra-sim/astra-sim` [2].

**(d) Activity status.** Repo README still says "ASTRA-sim is currently at **version 2.0**" (confirmed 2026-08-14) [2]. Last code push 2026-04-25 (GitHub API, checked 2026-08-14) [45]. Issue #380 ("Question about the release timeline for ASTRA-sim 3.0", opened 2026-06-29) — **open, zero comments** [3]. → 3.0 is paper/tutorial-level today; users must track the repo for the release.

### 2.2 gem5 v25.x (2025–2026)

**(a) Releases.** v25.0.0.0 (2025-03-ish), v25.0.0.1 hotfix (2025-08-25), v25.1.0.0 (2025-12-31), v25.1.0.1 hotfix (2026-04-21, RISC-V checkpoint + Arm KVM fixes). **No v25.2 or v26.0 as of 2026-08-14** [7][8][9][48].

**(b) NoC/Garnet changes in v25.x: essentially none.** v25.1 highlights are CPU/ISA work (Neoverse V2 core model, SVE2, decoupled front end, distributed IQ, multi-GPU framebuffer). Network-adjacent items in the v25.x notes are minor: Ruby software-prefetch early response ([#2311]) and CHI-TLM interface port-based connection ([#2689]) [8]. Garnet3/HeteroGarnet (clock-domain islands, vnets) is documented as a pre-existing feature — the gem5 20.2 release renamed network types to `garnet`, and HeteroGarnet blogged 2020-05-27 [10][8]. Garnet vnets are a baseline capability (Garnet_standalone defines 3 vnets; `--inj-vnet` in Garnet synthetic traffic) [10][11].

**(c) Validation updates.** None NoC-specific in v25.x release notes. The Garnet Synthetic Traffic framework (Garnet_standalone) remains the network-only testing path [11].

**(d) Activity.** BSD-3-Clause; very active — pushed 2026-08-13 [45]. Inference: background doc's "Garnet3 NoC with vnets [in v25.1]" framing should be read as "available, pre-existing", not a v25.1 feature (see §7).

### 2.3 NoCDAS — cycle-accurate NoC DNN accelerator simulator

**(a) What it models.** NoC-based DNN accelerator execution: PE arrays, routers with VCs, wormhole routing, memory-controller (MC) placement, DNN layer graphs (Conv2D/Pool/Dense) — LeNet (FE+RE), AlexNet, DarkNet, VGG16 examples on 8×8 mesh; C++14; config via `src/parameters.hpp` [12].

**(b) Validation.** TOMACS 2025 (DOI 10.1145/3729169) abstract states "the correctness of inference output is validated" (functional correctness vs inference reference), with flexible NoC definitions to quantify end-to-end latency [13]. **No RTL or silicon timing validation** stated in the abstract. (ACM DL page itself returned HTTP 403 to the fetcher; abstract recovered via Semantic Scholar API — see Coverage Status.)

**(c) License/repo.** MIT; `github.com/CRDloghorizon/NoCDAS`; 9 stars [12][45].

**(d) Activity.** Last master commits: 2025-03-10 (code), 2025-05-30 (README). Repo `pushed_at` metadata says 2026-05-13 (GitHub API; possibly non-master ref) [45]. Low-but-alive; no issues open.

### 2.4 CHIPSIM — chiplet co-simulation (⚠️ several background-doc claims corrected)

**(a) What it models.** Co-simulation of parallel DNN execution on chiplet-based systems: computation (analog **in-memory compute** via CIMLoop API container, plus analytical CMOS compute) and communication over a **Network-on-Interposer (NoI)** with cycle-accurate network simulation [14][15]. Per README: `comm_simulator: "Garnet"` (gem5, AnyNET mode converts the NoI adjacency matrix to a gem5 topology); **"Booksim not implemented"** — i.e., it does **not** use BookSim [15]. Optional DSENT interconnect power and microsecond-granularity power/thermal profiling [14][15].

**(b) Validation.** Abstract claims "up to 340% accuracy improvement" over conventional simulators and power/thermal analysis capability [14]. No silicon validation stated in the abstract. README caveat: "**Simulator is in its initial release, full correct functionality not yet guaranteed**" [15].

**(c) License/repo.** `github.com/LukasPfromm/CHIPSIM` — **no LICENSE file (HTTP 404)** [15]. 17 stars. Paper: IEEE Open Journal of the Solid-State Circuits Society, DOI 10.1109/OJSSCS.2025.3626314; arXiv:2510.25958 [14][16].

**(d) Activity.** GitHub mirror synced from a GitLab stable branch; last sync 2026-02-16 [15].

### 2.5 LEGOSim (MICRO 2025) — multi-chiplet integration framework

**(a) What it models.** Unified parallel simulation for multi-chiplet heterogeneous systems: runs gem5, Sniper, GPGPU-Sim, and an NoI simulator (popnet) as parallel "simlets" with an on-demand synchronization protocol (adaptive time quanta, non-global fencing) and an interchiplet communication glue layer [17][18]. It is an integration layer, not a NoC model itself.

**(b) Validation.** MICRO 2025 abstract claims the sync protocol "ensur[es] synchronization only when necessary, thus reducing overhead while maintaining correctness" [18]. Artifact directory shipped in repo (DSE, HBM/DDR, MLP experiments) [17]. Paper's full validation details: PDF only — blocked.

**(c) License/repo.** `github.com/FCAS-LAB/LEGOSIM_MICRO` — **no LICENSE file (HTTP 404)** [17]. 30 stars. MICRO 2025 DOI 10.1145/3725843.3756068 [18].

**(d) Activity.** Commits through 2026-07-28 [45].

### 2.6 SCALE-Sim v3 + SCALE-Sim TPU

**(a) What it models.** Systolic-array accelerator simulation (cycle-accurate timing, memory bandwidth, energy). v3 (ISPASS 2025, pp. 186–200; arXiv:2504.15377) adds multi-core spatio-temporal partitioning, SpMM/layer-row sparsity, Ramulator DRAM integration, on-chip data-layout modeling, Accelergy energy [19][23][24]. Not a NoC simulator (no packet-level routing).

**(b) Validation.** SCALE-Sim TPU (arXiv:2603.22535, 2026-03-23) validates the systolic GEMM model against **measured Google TPU v4** runtimes (strong linear correlation of simulated cycles with hardware latency; learned latency models for elementwise ops with **<3% median relative error**; StableHLO frontend for JAX/PyTorch) [20]. The official ISCA 2026 tutorial page (2026-06-28, Georgia Tech) additionally states validation on **TPU v4 and TPU v6e**, "up to **R² = 0.99** vs. measured TPU fusion-kernel runtimes", WS/IS dataflows, and TPUv7 (Ironwood) deployment studies [19]. ⚠️ Nuance: the tutorial's v6e/R² numbers go beyond the arXiv abstract (which names only TPU v4); treat the stronger claim as official-tutorial-sourced, not paper-sourced.

**(c) License/repo.** MIT. ⚠️ `scale-sim-v3` is **legacy** — README: "will not have any external updates unless there is a critical bug"; main repo is `scalesim-project/SCALE-Sim` (504 stars, pushed 2026-06-28) [21][22][45].

**(d) Activity.** Main repo active; tutorial says "used by over 100 organizations… more than 500 GitHub stars" [19].

### 2.7 BookSim (2025–26 status)

**(a) What it models.** The reference cycle-accurate interconnection-network simulator (mesh/torus/flatfly, routing algorithms, router microarchitecture options); unchanged in 2025–26 [25].

**(b) Validation.** Historical (ISPASS 2013 paper); no new validation releases [25].

**(c) License/repo.** Stanford-style license ("Other"/NOASSERTION on GitHub); `github.com/booksim/booksim2`; 451 stars, 229 forks, 21 open issues [25][45].

**(d) Activity.** **No commits since 2024-06-24** (GitHub API). Releases page shows only the 2014-era SVN imports [46]. **No BookSim 3.x exists** in the `booksim` org (repos: booksim2, booksim 1.0 last-push 2014, netrace) [26]. Verdict: **upstream unmaintained**; extensions live in community forks (e.g., 3D-mesh forks) — consistent with this repo's own vendored fork carrying the multicast/per-flit extensions.

### 2.8 Other notable 2025–26 releases

- **tt-npe** (Tenstorrent) — lightweight NoC **performance estimator** for Tensix (Wormhole B0, Blackhole): trace-driven (tt-metal profiler NoC traces) or synthetic workloads; congestion modeling on by default; Python/C++ APIs; integrates with tt-metal profiler and ttnn-visualizer. Apache-2.0; pushed 2026-08-07; 15 stars, 32 open issues. **No explicit validation numbers in README** [27][45].
- **ttsim** (Tenstorrent) — now at **v1.10.0 (2026-08-07)**, weekly cadence since June (v1.8.2 → v1.10.0). v1.8.2 (2026-06-11) added WH Galaxy (32-chip Wormhole) and BH Galaxy (32-chip Blackhole) configs plus outbound iATU/DMA and host-to-device multicast [28][29]. Apache-2.0; 146 stars [45].
- **polaris** (Tenstorrent) — high-level accelerator performance model; Apache-2.0; pushed 2026-08-14 (today) [30][45].
- **DICE** (ISCA 2026) — Detailed Inter-Chiplet End-to-End Simulator on gem5 modeling AMD EPYC chiplets with detailed **PHY (physical-layer) modeling**; repo created 2026-06-30, pushed 2026-07-28; BSD-3-Clause; 6 stars. Per its README, the ISCA 2026 paper received **all three artifact badges (available, evaluated, reproduced)**; arXiv:2607.24221 (existence verified; content not read) [32][33][45].
- **PAC-NoC** (2026, IEEE TVLSI preprint) — bandwidth-tapered fat-tree NoC with "aggregated multicast" as the core primitive (SSOA/DAC/hardwired slicing); abstract reports **−52% latency / −52% energy** vs baselines, −49%/−57% vs bandwidth-equivalent competitors on Transformer benchmarks. DOI 10.1109/TVLSI.2026.3717165. **No repo found**; ⚠️ abstract does **not** mention NoCDAS (background doc's "built on NoCDAS" unverified — see §7) [34].
- **MLSys 2026 oral — collective-capable NoC** — in-network multicast + reduction + barrier with "Direct Compute Access" (16.5% router area overhead); 2.9×/2.5× geomean speedups on multicast/reduction (1–32 KiB); up to 2.1× estimated GEMM gains vs baseline unicast NoC [35]. No repo found.
- **CAMINOS** — new phit-level NoC simulator **written in Rust** (Univ. de Cantabria); component-composition config, SLURM integration, TeX-friendly plots; JPDC Vol 204 (Oct 2025), DOI 10.1016/j.jpdc.2025.105136; MIT/Apache-2.0 via crates.io (`caminos-lib` 0.6) [36][37][38].
- **Noxim** — April 2026 update: deterministic regression suite with pinned YAML configs + golden outputs (`./regression.sh`), cycle-by-cycle mesh visualizer (`visualNoxim`), scoped VCD tracing, CSV/JSON stats export, Markdown+PDF user guide. GPL; pushed 2026-06-09; 333 stars [31][45].
- **PLENA_Simulator** (2026) — multi-level simulator for a long-context LLM accelerator (transaction-level Rust emulator + analytic TTFT/TPS latency models); repo created 2026-01-28, pushed 2026-08-11; **no LICENSE file**; paper arXiv:2509.09505 (existence verified) [39][40][45].
- **Industry (proprietary, no open-source NoC simulator found):** NVIDIA **DSX Air** (cloud simulation of AI-factory infrastructure incl. networking) [42]; NVIDIA NVLink 6th-gen specs blog (3.6 TB/s per GPU, 130 TFLOPS in-network compute) [43]; AMD/Xilinx **Versal NoC simulation** (SystemVerilog/SystemC behavioral NoC models in Vivado, UG1273 v2026.1) [44].

---

## 3. Summary matrix

| Tool | Type | What it models | Validation evidence (as stated by source) | License | Activity @2026-08-14 |
|---|---|---|---|---|---|
| ASTRA-sim 3.0 | scale-out ML sim | cache-line load-store GPU model, MSCCL++, InfraGraph, Chakra traces | none in abstract; 2.0 repo ships HGX-H100-validated.yml; alphaXiv: linear scaling to 128 GPUs (secondary) | MIT | code not released; README v2.0; issue #380 open [1][2][3][4][5][6] |
| gem5 v25.x | full-system | CPU/cache/GPU; Garnet3 NoC (pre-existing) | no NoC validation updates in v25.x notes | BSD-3-Clause | very active (pushed 08-13) [7][8][10] |
| NoCDAS | NoC+DNN accel | PE array + VC NoC, wormhole, MC placement | "correctness of inference output is validated" (functional only) | MIT | low (code 2025-03; push metadata 2026-05) [12][13][45] |
| CHIPSIM | chiplet co-sim | IMC chiplets + NoI; Garnet (not BookSim); power/thermal | abstract: "up to 340% accuracy improvement"; initial-release caveat | **none (no LICENSE file)** | GitHub mirror sync 2026-02-16 [14][15][16] |
| LEGOSim | chiplet integration | gem5/Sniper/GPGPU-Sim/popnet as simlets + sync protocol | abstract: correctness-preserving sync; artifacts in repo | **none (no LICENSE file)** | commits 2026-07-28 [17][18][45] |
| SCALE-Sim v3 / TPU | systolic dataflow | multi-core, sparsity, Ramulator, Accelergy; TPU variant | TPU v4 (paper); v4+v6e, R²≤0.99 (tutorial) | MIT | v3 legacy; main repo active [19][20][21][22] |
| BookSim 2 | NoC core | meshes/tori/flatfly, routing, router μarch | ISPASS 2013 (historical) | Stanford-style | **unmaintained since 2024-06-24**; no 3.x [25][26][46] |
| tt-npe | NoC perf estimator | Tensix NoC traces, congestion, multicast | none stated in README | Apache-2.0 | active (pushed 08-07) [27][45] |
| ttsim | full-system (Tenstorrent) | Wormhole/Blackhole incl. Galaxy 32-chip, multicast, DMA | functional/bit-exact (per background doc; re-verified activity only) | Apache-2.0 | very active; v1.10.0 (08-07) [28][29][45] |
| DICE | chiplet sim (gem5) | AMD EPYC chiplets, detailed PHY | ISCA 2026; 3 artifact badges (per README) | BSD-3-Clause | new repo, active [32][33][45] |
| PAC-NoC | NoC arch (paper) | aggregated-multicast fat tree | abstract: −52% lat / −52% en; −49%/−57% vs optimized | n/a (no repo) | preprint [34] |
| MLSys'26 collective NoC | NoC arch (paper) | in-network multicast/reduce, DCA | abstract: 2.9×/2.5×; 16.5% area | n/a (no repo) | oral [35] |
| CAMINOS | phit-level NoC sim (Rust) | router microarchitecture, composable configs | JPDC 2025 (abstract via page highlights) | MIT/Apache-2.0 (crates.io) | crates.io 0.6 [36][37][38] |
| Noxim | NoC sim (SystemC) | mesh, VCs, wireless, power | 2026 regression suite w/ golden outputs (self-test, not HW validation) | GPL | active (pushed 06-09) [31][45] |
| PLENA_Simulator | accel simulator | long-context LLM accelerator (TLM + analytic) | none stated in README | **none (no LICENSE file)** | active (pushed 08-11) [39][40][45] |

---

## 4. Bottom-line implications for this project (toolchain: BookSim2, gem5/Garnet, Timeloop, Accelergy, Verilator)

1. **No 2025–26 tool replaces the repo's own core stack.** No new published per-flit RTL↔sim gate exists; BookSim remains the standard but is **upstream-dormant**, reinforcing the value of this repo's maintained fork.
2. **ASTRA-sim 3.0 is not yet obtainable** — do not plan on it; the 2.x repo (Chakra input, HGX-H100-validated example) remains the practical scale-out leg, and 3.0's load-store/GPU model is worth tracking in the repo's issues.
3. **The cross-simulator credibility add should prefer NoCDAS** (MIT, functional-validation documented) over CHIPSIM (no license, initial-release caveat, Garnet-based NoI — and *not* BookSim-based as the background doc believed).
4. **Licensing flags:** CHIPSIM, LEGOSim, and PLENA_Simulator ship **no LICENSE file** — do not vendor any of them without contacting the authors. tt-npe (Apache-2.0) is the clean Tenstorrent-side NoC estimator if needed.
5. **Garnet3 + vnets are available in gem5 v25.x as baseline features** (useful for per-class VC "plane" studies) — but they were not introduced in v25.1; claims must be phrased accordingly.

---

## 5. Coverage Status

**Checked directly (fetched, read):**
- ASTRA-sim: repo README + file tree, issue #380 (state + comments), ISCA 2026 tutorial page, HGX-H100-validated.yml, arXiv abstract 2606.10440.
- gem5: releases page, RELEASE-NOTES.md (v25.0–v25.1 sections grepped for NoC/Garnet/network terms), v25.1.0.0 release notes, v25.1.0.1 PR, HeteroGarnet + Garnet Synthetic Traffic docs.
- NoCDAS repo (README + tree); CHIPSIM repo (README incl. `comm_simulator` option + note); LEGOSim repo (README); scale-sim-v3 + SCALE-Sim repos; tt-npe repo (README); ttsim releases + tags; Noxim README; DICE repo (README); PLENA_Simulator repo (README); PAC-NoC CSDL page; MLSys 2026 abstract page; SCALE-Sim ISCA 2026 tutorial page; arXiv abstract pages (2603.22535, 2510.25958); Semantic Scholar abstracts (NoCDAS, LEGOSim, CHIPSIM, CAMINOS).
- GitHub API metadata (stars/forks/license/pushed_at/commit dates) for 17 repos on 2026-08-14.

**Blocked / not parsed (per brief rules):**
- PDF bodies: ASTRA-sim 3.0 full text (validation numbers unread), LEGOSim paper, PAC-NoC paper, CAMINOS paper, CHIPSIM IEEE full text, MLSys paper.
- ACM DL pages returned HTTP 403 to the fetcher; abstracts recovered via Semantic Scholar Graph API instead (marked accordingly).
- DICE arXiv:2607.24221 and PLENA arXiv:2509.09505 — existence verified (HTTP 200); contents not read; DICE claims sourced from its README only.

**Uncertain / needs follow-up:**
- PAC-NoC "built on NoCDAS" (background doc) — not visible in the TVLSI abstract; full text would settle it (PDF blocked).
- ASTRA-sim 3.0 validation numbers — only in the PDF.
- SCALE-Sim TPU v6e + R²=0.99 claims — official tutorial page only; not in the arXiv abstract.
- CHIPSIM "340% accuracy improvement" — abstract-level; baseline definition unread.
- tt-npe vs-silicon accuracy — no statement found in README; docs site returned 404 on the fetched path.
- Whether a gem5 v26.0 release lands before year-end (repo active on develop/stable; only hotfixes since v25.1.0.1).

---

## 6. Search log (exact queries & fetches, 2026-08-14)

**web_search (Perplexity/Exa/Gemini provider chain, 5–6 results per query, includeContent on primary candidates):**
1. "ASTRA-sim 3.0 distributed ML simulator 2026 release" · "gem5 v25 NoC Garnet network changes release notes 2025" · "NoCDAS cycle-accurate NoC DNN accelerator simulator open source" · "CHIPSIM chiplet co-simulation deep learning arXiv"
2. "SCALE-Sim v3 TPU SCALE-Sim ISPASS 2025" · "LEGOSim MICRO 2025 multi-chiplet simulation" · "BookSim 3 network simulator update 2025 2026" · "new NoC simulator 2026 open source AI accelerator"
3. "booksim2 last commit 2025 2026 unmaintained github activity" · "gem5 v25.2 OR v26.0 release 2026" · "Intel OR NVIDIA OR AMD open source NoC simulator 2025 2026 interconnect" · "gem5 Garnet3 vnet virtual network NoC 2025 changes"
4. "booksim3 repository fork BookSim 3.0 network simulator" · "CAMINOS interconnection networks simulator Rust github" · "SCALE-Sim TPU ISCA 2026 tutorial" · "NVIDIA open source network simulator 2026 NVLink modeling"
5. "PAC-NoC fat-tree multicast NoCDAS 2026" · "Garnet network simulator validation gem5 2025 paper" · "ttsim v1.8 multicast L1 MMIO release notes Tenstorrent"

**Direct URL fetches (fetch_content / raw):** github.com/astra-sim/astra-sim (+issue/380), astra-sim.github.io/tutorials/isca-2026, github.com/gem5/gem5/releases, raw.githubusercontent.com/gem5/gem5/stable/RELEASE-NOTES.md, github.com/CRDloghorizon/NoCDAS, github.com/LukasPfromm/CHIPSIM, github.com/FCAS-LAB/LEGOSIM_MICRO, github.com/scalesim-project/scale-sim-v3, github.com/booksim/booksim2, github.com/tenstorrent/tt-npe, github.com/RashidAGP/DICE-Simulator, github.com/AICrossSim/PLENA_Simulator, scalesim-project.github.io/tutorial-isca2026.html, raw.githubusercontent.com/davidepatti/noxim/master/README.md, arxiv.org/abs/2606.10440, arxiv.org/abs/2603.22535, arxiv.org/abs/2510.25958, computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6, mlsys.org/virtual/2026/oral/3804, dl.acm.org/doi/10.1145/3729169 (403), dl.acm.org/doi/10.1145/3725843.3756068 (403), alphaxiv.org/overview/2606.10440, docs.tenstorrent.com/tt-npe/ (404), tenstorrent.github.io/tt-npe/ (301).

**API queries (bash + curl):** GitHub REST API for 17 repos (pushed_at/updated_at/stars/forks/issues/license), astra-sim issue #380 + comments, ttsim releases/tags (v1.10.0…v1.8.1), gem5 release tag v25.1.0.1, commit lists for NoCDAS/LEGOSIM/CHIPSIM, raw-file existence checks (CHIPSIM/LICENSE, LEGOSIM/LICENSE → 404; HGX-H100-validated.yml → 200); arXiv abs-page HTTP checks (2504.15377, 2509.09505, 2607.24221 → 200); Semantic Scholar Graph API (NoCDAS, LEGOSim, CHIPSIM, SCALE-Sim TPU, CAMINOS).

---

## 7. Corrections / staleness flags vs `docs/research/simulator-landscape-2026.md`

| Background-doc claim | Check result (2026-08-14) | Verdict |
|---|---|---|
| CHIPSIM "Uses BookSim underneath" | README: `comm_simulator: "Garnet"`, **"Booksim not implemented"** | ❌ Correct — uses Garnet (gem5) [15] |
| CHIPSIM models "die-to-die (UCIe) boundaries" | Models in-memory-compute chiplets + Network-on-Interposer (adjacency-matrix topologies); UCIe not mentioned | ⚠️ Reframe [14][15] |
| gem5 v25.1 "Garnet3 NoC with vnets" as a v25.1 feature | No NoC/Garnet items in v25.0/v25.1 release notes; Garnet3/vnets baseline since ~2020 (gem5 20.2, HeteroGarnet 2020 blog) | ⚠️ Misattributed — feature is pre-existing [8][10] |
| PAC-NoC "built on NoCDAS", venue "IEEE CSDL / JSS" | Venue is **IEEE TVLSI preprint** (DOI 10.1109/TVLSI.2026.3717165); abstract does **not** mention NoCDAS | ⚠️ Venue wrong; NoCDAS link unverified (PDF blocked) [34] |
| ttsim "v1.8.1 (June 2026)" | Now **v1.10.0 (2026-08-07)**; v1.8.2 added 32-chip Galaxy configs + multicast/DMA | 🔄 Update (still Apache-2.0, active) [28][29] |
| SCALE-Sim TPU "validates vs TPUv4/TPUv6e" | Tutorial confirms v4+v6e (R²≤0.99); arXiv abstract names only TPU v4 | ⚠️ Keep, cite tutorial for v6e/R² [19][20] |
| scale-sim-v3 as the SCALE-Sim repo | Repo declares itself **legacy**; main repo is scalesim-project/SCALE-Sim | 🔄 Update [21][22] |
| ASTRA-sim 3.0 "arXiv:2606.10440" | ID correct; **3.0 code not public** (README v2.0; issue #380 open, 0 comments) | ⚠️ Add availability caveat [1][2][3] |
| NoCDAS validation "functional, not RTL" | Confirmed by TOMACS abstract ("correctness of inference output is validated") | ✅ Confirmed [13] |

---

## 8. Evidence table

| # | Source | URL | Key claim | Type | Confidence |
|---|--------|-----|-----------|------|------------|
| 1 | ASTRA-sim 3.0 (arXiv abstract) | https://arxiv.org/abs/2606.10440 | v3 = load-store granularity, GPU model, MSCCL++, InfraGraph; no HW-validation numbers in abstract | primary (abstract) | high |
| 2 | astra-sim/astra-sim README | https://github.com/astra-sim/astra-sim | Repo still "currently at version 2.0"; MIT; Chakra input | primary (repo) | high |
| 3 | ASTRA-sim issue #380 | https://github.com/astra-sim/astra-sim/issues/380 | 3.0 release timeline question; open, zero comments | primary (issue) | high |
| 4 | ASTRA-sim ISCA 2026 tutorial | https://astra-sim.github.io/tutorials/isca-2026 | v3 feature detail (MSCCLPP, GPU model, protocols, InfraGraph, HTSim/ns-3), AMD+GT organizers | primary (official) | high |
| 5 | HGX-H100-validated.yml | https://github.com/astra-sim/astra-sim/blob/master/examples/network/analytical/HGX-H100-validated.yml | 2.x ships calibrated HGX-H100 analytical config (8 GPUs, 400 GB/s, 936.25 ns) | primary (repo file) | high |
| 6 | alphaXiv ASTRA-sim 3.0 overview | https://www.alphaxiv.org/overview/2606.10440 | Secondary summary: NoC-level (CU/HBM/IO) modeling; eval scales linearly to 128 GPUs | secondary | medium |
| 7 | gem5 releases page | https://github.com/gem5/gem5/releases | Releases: v25.0.0.0, v25.0.0.1, v25.1.0.0, v25.1.0.1; no later release | primary | high |
| 8 | gem5 RELEASE-NOTES.md | https://github.com/gem5/gem5/blob/stable/RELEASE-NOTES.md | No NoC/Garnet major changes in v25.0/v25.1 (CPU/ISA focus); minor Ruby items only | primary | high |
| 9 | gem5 v25.1.0.1 hotfix PR | https://github.com/gem5/gem5/pull/3082 | Hotfix (2026-04-21): RISC-V checkpoint + Arm KVM build fix | primary | high |
| 10 | gem5 HeteroGarnet docs | https://www.gem5.org/documentation/general_docs/ruby/heterogarnet/ | Garnet3/HeteroGarnet = clock-domain islands, vnets; pre-existing (2020-era) | primary (docs) | high |
| 11 | gem5 Garnet Synthetic Traffic docs | https://www.gem5.org/documentation/general_docs/debugging_and_testing/directed_testers/garnet_synthetic_traffic/ | Network-only testing path; vnet injection control | primary (docs) | high |
| 12 | NoCDAS repo | https://github.com/CRDloghorizon/NoCDAS | Cycle-accurate NoC DNN sim; MIT; LeNet 8×8 example; MC placement config | primary (repo) | high |
| 13 | NoCDAS TOMACS 2025 | https://dl.acm.org/doi/10.1145/3729169 | "correctness of inference output is validated"; functional-level validation; ACM page 403, abstract via Semantic Scholar | primary (abstract via API) | high |
| 14 | CHIPSIM arXiv | https://arxiv.org/abs/2510.25958 | Co-sim for DNN on chiplet systems; "up to 340% accuracy improvement"; power/thermal | primary (abstract) | high |
| 15 | CHIPSIM repo | https://github.com/LukasPfromm/CHIPSIM | Garnet (not BookSim); initial-release caveat; **no LICENSE file**; GitLab sync 2026-02-16 | primary (repo) | high |
| 16 | CHIPSIM OJSSCS DOI | https://doi.org/10.1109/OJSSCS.2025.3626314 | Published venue + DOI confirmed | primary (metadata) | high |
| 17 | LEGOSim repo | https://github.com/FCAS-LAB/LEGOSIM_MICRO | gem5/Sniper/GPGPU-Sim/popnet + interchiplet; **no LICENSE file**; commits to 2026-07-28 | primary (repo) | high |
| 18 | LEGOSim MICRO 2025 | https://dl.acm.org/doi/10.1145/3725843.3756068 | On-demand sync protocol reduces overhead, maintains correctness; ACM 403, abstract via Semantic Scholar | primary (abstract via API) | high |
| 19 | SCALE-Sim ISCA 2026 tutorial | https://scalesim-project.github.io/tutorial-isca2026.html | TPU variant validated vs TPU v4+v6e, R²≤0.99; 100+ orgs, 500+ stars; v3 features | primary (official) | high |
| 20 | SCALE-Sim TPU arXiv | https://arxiv.org/abs/2603.22535 | Validation vs TPU v4; <3% median rel. error (elementwise); StableHLO frontend | primary (abstract) | high |
| 21 | scale-sim-v3 repo | https://github.com/scalesim-project/scale-sim-v3 | Declared **legacy**, no external updates except critical bugs; MIT | primary (repo) | high |
| 22 | SCALE-Sim main repo | https://github.com/scalesim-project/SCALE-Sim | Active main repo; 504 stars; pushed 2026-06-28 | primary (repo) | high |
| 23 | SCALE-Sim v3 IEEE Xplore | https://ieeexplore.ieee.org/document/11096402 | ISPASS 2025 paper record (pp. 186–200) | primary (metadata) | high |
| 24 | SCALE-Sim v3 arXiv | https://arxiv.org/abs/2504.15377 | v3 paper (preprint) | primary (abstract) | high |
| 25 | booksim/booksim2 | https://github.com/booksim/booksim2 | No commits since 2024-06-24 (API); 451 stars; unmaintained upstream | primary (repo+API) | high |
| 26 | booksim org | https://github.com/booksim | No BookSim 3.x in org; booksim 1.0 last push 2014 | primary (repo) | high |
| 27 | tt-npe repo | https://github.com/tenstorrent/tt-npe | NoC perf estimator for Tensix (WH B0, BH); trace-driven; congestion model; Apache-2.0; no validation numbers in README | primary (repo) | high |
| 28 | ttsim releases | https://github.com/tenstorrent/ttsim/releases | v1.10.0 (2026-08-07); weekly cadence June–Aug 2026 | primary (repo) | high |
| 29 | ttsim v1.8.2 | https://github.com/tenstorrent/ttsim/releases/tag/v1.8.2 | 32-chip WH/BH Galaxy configs; outbound iATU/DMA + host-to-device multicast | primary (release notes) | high |
| 30 | polaris repo | https://github.com/tenstorrent/polaris | Tenstorrent perf model; Apache-2.0; pushed 2026-08-14 | primary (repo) | high |
| 31 | Noxim repo | https://github.com/davidepatti/noxim | Apr 2026 release: regression suite + golden outputs, visualNoxim, VCD, CSV/JSON export; GPL | primary (repo) | high |
| 32 | DICE repo | https://github.com/RashidAGP/DICE-Simulator | gem5-based chiplet sim for AMD EPYC w/ PHY modeling; ISCA 2026, 3 artifact badges (per README); BSD-3-Clause | primary (repo) | high |
| 33 | DICE arXiv | https://arxiv.org/abs/2607.24221 | Existence verified (HTTP 200); content not read | primary (existence only) | medium |
| 34 | PAC-NoC (TVLSI preprint) | https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6 | Aggregated-multicast fat-tree NoC; −52% lat / −52% en; **NoCDAS not mentioned**; DOI 10.1109/TVLSI.2026.3717165 | primary (abstract) | high |
| 35 | MLSys 2026 oral (collective NoC) | https://mlsys.org/virtual/2026/oral/3804 | In-network multicast/reduce + DCA; 16.5% router area; 2.9×/2.5×; up to 2.1× GEMM gains | primary (abstract) | high |
| 36 | CAMINOS (JPDC) | https://www.sciencedirect.com/science/article/pii/S0743731525001030 | New Rust phit-level NoC sim; JPDC Vol 204, Oct 2025; full text PDF-only | primary (highlights) | medium |
| 37 | CAMINOS project page | https://www.atc.unican.es/sw_caminos.html | Rust, modular; MIT or Apache-2.0; distributed via crates.io | primary (project) | high |
| 38 | caminos-lib docs.rs | https://docs.rs/caminos-lib/latest/caminos_lib/ | Crate `caminos-lib` 0.6 published | primary (registry) | high |
| 39 | PLENA_Simulator repo | https://github.com/AICrossSim/PLENA_Simulator | Multi-level LLM-accelerator simulator; **no LICENSE file**; created 2026-01-28, pushed 2026-08-11 | primary (repo) | high |
| 40 | PLENA paper arXiv | https://arxiv.org/abs/2509.09505 | Existence verified (HTTP 200); content not read | primary (existence only) | medium |
| 41 | SemiEngineering on CHIPSIM | https://semiengineering.com/co-simulation-framework-for-parallel-dnn-execution-on-chiplet-based-systems-univ-of-wisconsin-madison-washington-state-univ/ | UW–Madison + WSU authorship context (secondary coverage) | secondary | medium |
| 42 | NVIDIA DSX Air blog | https://developer.nvidia.com/blog/design-simulate-and-scale-ai-factory-infrastructure-with-nvidia-dsx-air/ | NVIDIA cloud AI-factory simulation (proprietary; incl. networking) | self-reported | medium |
| 43 | NVIDIA NVLink blog | https://developer.nvidia.com/blog/nvidia-nvlink-the-scale-up-network-for-ai-factories/ | NVLink 6th gen: 3.6 TB/s per GPU; 130 TFLOPS in-network compute | self-reported | medium |
| 44 | AMD Versal NoC Simulation (UG1273) | https://docs.amd.com/r/en-US/ug1273-versal-acap-design/NoC-Simulation | Versal NoC behavioral simulation (SV/SystemC) in Vivado tooling | self-reported (vendor docs) | medium |
| 45 | GitHub API metadata | https://api.github.com/repos/{repo} (17 repos, 2026-08-14) | pushed_at / stars / forks / open issues / license per repo | primary (API) | high |
| 46 | booksim2 releases page | https://github.com/booksim/booksim2/releases | Only 2014-era SVN import releases | primary | high |
| 47 | Background doc (internal) | docs/research/simulator-landscape-2026.md | Baseline survey compiled 2026-08-12; corrected in §7 above | internal | — |
| 48 | gem5 v25.0.0.1 release | https://github.com/gem5/gem5/releases/tag/v25.0.0.1 | Hotfix release 2025-08-25 (no NoC content) | primary | high |

---

## 9. Sources (numbered, matching the evidence table)

1. ASTRA-sim 3.0 arXiv abstract — https://arxiv.org/abs/2606.10440
2. ASTRA-sim repo — https://github.com/astra-sim/astra-sim
3. ASTRA-sim issue #380 — https://github.com/astra-sim/astra-sim/issues/380
4. ASTRA-sim ISCA 2026 tutorial — https://astra-sim.github.io/tutorials/isca-2026
5. ASTRA-sim HGX-H100-validated.yml — https://github.com/astra-sim/astra-sim/blob/master/examples/network/analytical/HGX-H100-validated.yml
6. alphaXiv overview of 2606.10440 — https://www.alphaxiv.org/overview/2606.10440
7. gem5 releases — https://github.com/gem5/gem5/releases
8. gem5 RELEASE-NOTES.md — https://github.com/gem5/gem5/blob/stable/RELEASE-NOTES.md
9. gem5 v25.1.0.1 PR — https://github.com/gem5/gem5/pull/3082
10. gem5 HeteroGarnet (Garnet 3.0) docs — https://www.gem5.org/documentation/general_docs/ruby/heterogarnet/
11. gem5 Garnet Synthetic Traffic docs — https://www.gem5.org/documentation/general_docs/debugging_and_testing/directed_testers/garnet_synthetic_traffic/
12. CRDloghorizon/NoCDAS — https://github.com/CRDloghorizon/NoCDAS
13. NoCDAS (ACM TOMACS) — https://dl.acm.org/doi/10.1145/3729169
14. CHIPSIM arXiv — https://arxiv.org/abs/2510.25958
15. LukasPfromm/CHIPSIM — https://github.com/LukasPfromm/CHIPSIM
16. CHIPSIM IEEE OJ-SSCS — https://doi.org/10.1109/OJSSCS.2025.3626314
17. FCAS-LAB/LEGOSIM_MICRO — https://github.com/FCAS-LAB/LEGOSIM_MICRO
18. LEGOSim (MICRO 2025) — https://dl.acm.org/doi/10.1145/3725843.3756068
19. SCALE-Sim ISCA 2026 tutorial — https://scalesim-project.github.io/tutorial-isca2026.html
20. SCALE-Sim TPU arXiv — https://arxiv.org/abs/2603.22535
21. scalesim-project/scale-sim-v3 — https://github.com/scalesim-project/scale-sim-v3
22. scalesim-project/SCALE-Sim — https://github.com/scalesim-project/SCALE-Sim
23. SCALE-Sim v3 IEEE Xplore — https://ieeexplore.ieee.org/document/11096402
24. SCALE-Sim v3 arXiv — https://arxiv.org/abs/2504.15377
25. booksim/booksim2 — https://github.com/booksim/booksim2
26. booksim org — https://github.com/booksim
27. tenstorrent/tt-npe — https://github.com/tenstorrent/tt-npe
28. tenstorrent/ttsim releases — https://github.com/tenstorrent/ttsim/releases
29. ttsim v1.8.2 release — https://github.com/tenstorrent/ttsim/releases/tag/v1.8.2
30. tenstorrent/polaris — https://github.com/tenstorrent/polaris
31. davidepatti/noxim — https://github.com/davidepatti/noxim
32. RashidAGP/DICE-Simulator — https://github.com/RashidAGP/DICE-Simulator
33. DICE arXiv — https://arxiv.org/abs/2607.24221
34. PAC-NoC (IEEE TVLSI preprint) — https://www.computer.org/csdl/journal/si/5555/01/11641269/2iGhoU40Ir6
35. MLSys 2026 oral: Collective-Capable NoC — https://mlsys.org/virtual/2026/oral/3804
36. CAMINOS (JPDC) — https://www.sciencedirect.com/science/article/pii/S0743731525001030
37. CAMINOS project page (UC) — https://www.atc.unican.es/sw_caminos.html
38. caminos-lib on docs.rs — https://docs.rs/caminos-lib/latest/caminos_lib/
39. AICrossSim/PLENA_Simulator — https://github.com/AICrossSim/PLENA_Simulator
40. PLENA paper arXiv — https://arxiv.org/abs/2509.09505
41. SemiEngineering: CHIPSIM — https://semiengineering.com/co-simulation-framework-for-parallel-dnn-execution-on-chiplet-based-systems-univ-of-wisconsin-madison-washington-state-univ/
42. NVIDIA DSX Air blog — https://developer.nvidia.com/blog/design-simulate-and-scale-ai-factory-infrastructure-with-nvidia-dsx-air/
43. NVIDIA NVLink blog — https://developer.nvidia.com/blog/nvidia-nvlink-the-scale-up-network-for-ai-factories/
44. AMD UG1273: NoC Simulation (Versal) — https://docs.amd.com/r/en-US/ug1273-versal-acap-design/NoC-Simulation
45. GitHub REST API metadata (queried 2026-08-14) — https://api.github.com/repos/{owner}/{repo}
46. booksim2 releases — https://github.com/booksim/booksim2/releases
47. Background: simulator-landscape-2026.md — docs/research/simulator-landscape-2026.md
48. gem5 v25.0.0.1 release — https://github.com/gem5/gem5/releases/tag/v25.0.0.1
