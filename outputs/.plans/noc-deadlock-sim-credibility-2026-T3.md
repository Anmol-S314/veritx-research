# T3 Brief — NoC Simulator Landscape 2026: New Tools & Releases

**Researcher task:** Produce `noc-deadlock-sim-credibility-2026-research-t3.md` (in `outputs/.drafts/`).

## Objective
Survey 2025–2026 NoC/interconnect simulation tooling: new simulators, frameworks, and major releases, plus the validation stories they ship. This feeds toolchain decisions in the project (currently BookSim 2.0, gem5/Garnet, Timeloop, Accelergy, Verilator). Focus on what is NEW in 2025–2026 and what validation/credibility evidence each tool ships.

## Key questions to answer
1. ASTRA-sim 3.0 (2026): what is it, what does it add, what validation does it report? (Official docs + papers.)
2. gem5 v25.x (2025–2026): major NoC/network changes? Garnet version updates? Validation updates?
3. New open-source NoC simulators 2025–2026: NoCDAS, CHIPSIM, LEGOSim (MICRO 2025), SCALE-Sim v3 / SCALE-Sim TPU — status, capability, validation evidence, repo health.
4. BookSim updates 2025–2026: any new releases/commits/forks of significance (e.g., BookSim 3.x, maintenance activity)? Note if it looks unmaintained.
5. Any other notable 2025–2026 releases: chiplet/die-to-die simulators, NoC + accelerator co-simulation, AI-NoC design tools (e.g., from industry: Intel, NVIDIA, AMD, Tenstorrent open-sourced tools if any).
6. For each tool: (a) what it models, (b) validation/calibration evidence, (c) license/repo, (d) activity status. Keep it a scannable matrix or per-tool blocks.

## Sources
- Official docs/repos (GitHub, readthedocs, project sites) via web search and direct fetch of HTML pages (not PDFs).
- arXiv 2025–2026 papers announcing the tools.
- Google Scholar via web search for tool names + "2025"/"2026" + "validation".
- Background (read, do not redo): `docs/research/simulator-landscape-2026.md` — this survey must EXTEND it with fresh 2025–2026 checks (esp. anything after 2026-08-12), not re-derive it. Flag anything in that doc that appears stale or changed.

## Rules
- 2025–2026 window; 2026 items first. Older tools only as one-line context.
- Do NOT fetch/parse PDF bodies. Use HTML docs, repo READMEs (via GitHub), metadata, abstracts, and web snippets. If only a PDF exists, cite the PDF URL from search metadata and mark full-text parsing as blocked.
- Every claim needs a source URL. No invented tools, versions, or validation numbers. Distinguish "official docs say X" from "paper abstract says X" from "I inferred X".
- Record the exact search queries you ran at the end of the brief (a "Search log" section).
- Output: Markdown, per-tool blocks + a summary matrix, each claim with source URL, explicit uncertainty markers.
