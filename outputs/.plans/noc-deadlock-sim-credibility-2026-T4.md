# T4 Brief — AI-Accelerator / LLM-Serving Interconnect Simulation (2025–2026)

**Researcher task:** Produce `noc-deadlock-sim-credibility-2026-research-t4.md` (in `outputs/.drafts/`).

## Objective
Survey 2025–2026 literature (calendar 2026 primary) on interconnect/NoC simulation for AI accelerators and LLM serving systems: wafer-scale NoCs, KV-cache serving on meshes, chiplet interconnects, and what validation norms these works report (aggregate % vs hardware, request/token-level vs cycle-level, simulator-vs-simulator). This feeds the project's T1 (KV-cache QoS, gem5/Garnet/ASTRA-sim) and T3 (topology) tracks and the paper's validation-posture arguments.

## Key questions to answer
1. ISCA 2026 / MICRO 2025 / HPCA 2025–2026 / ASPLOS 2025–2026 papers on wafer-scale or mesh-based KV-cache/LLM serving systems: what simulators do they use, and what validation evidence do they report (e.g., ASTRA-sim-based, gem5-based, custom cycle-accurate, request-level)?
2. ASTRA-sim / ASTRA-sim 3.0 validation claims (2025–2026) and any new comparative studies of distributed-training/serving simulators (e.g., vs real GPU clusters, % error claims).
3. New 2025–2026 simulation work specifically on NoCs inside AI accelerators (DNN/transformer chips): NoCDAS, SCALE-Sim v3, and any others — validation evidence?
4. Chiplet/die-to-die interconnect simulation 2025–2026 (LEGOSim MICRO 2025, UCIe-based modeling, OpenURMA, CLIPGen): validation depth and gaps.
5. What do 2025–2026 papers in this space treat as sufficient validation (aggregate %? curve shapes? none?) — quantify examples with numbers.
6. Anything 2025–2026 on KV-cache traffic characterization that validates simulated traffic against real inference workloads (traces vs synthetic).

## Sources
- arXiv 2025–2026: "KV cache serving", "wafer-scale LLM", "LLM inference interconnect", "ASTRA-sim", "NoC DNN accelerator simulation 2026", "chiplet simulation 2026".
- Google Scholar via web search: "KV cache serving mesh 2026", "wafer scale LLM ISCA 2026", "ASTRA-sim validation 2026", "LLM inference network simulator 2025".
- Venues: ISCA 2026, MICRO 2025, HPCA 2025/2026, ASPLOS 2025/2026, NOCS 2025/2026, MLSys 2025/2026, OSDI/NSDI 2025/2026 (serving systems).
- Background (read, do not redo): `docs/research/2026-moe-serving-landscape.md`, `docs/research/cross-node-kv-distribution-2026.md`, `docs/research/llm-serving-trace-pipeline.md` — extend with fresh 2025–2026 sources.

## Rules
- 2025–2026 window; 2026 items first.
- Do NOT fetch/parse PDF bodies (no alpha_get_paper, no raw .pdf fetch). Use metadata, abstracts, HTML, and web snippets. If only a PDF exists, cite the PDF URL from search metadata and mark full-text parsing as blocked.
- Every claim needs a source URL. No invented systems, papers, or validation numbers. Distinguish reported numbers from your interpretation.
- Record the exact search queries you ran at the end of the brief (a "Search log" section).
- Output: Markdown, structured by question, each finding with source URL and a one-line quote or paraphrase, explicit uncertainty markers.
