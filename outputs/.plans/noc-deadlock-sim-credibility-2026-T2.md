# T2 Brief — Simulator↔RTL Validation & NoC Simulator Credibility (2025–2026)

**Researcher task:** Produce `noc-deadlock-sim-credibility-2026-research-t2.md` (in `outputs/.drafts/`).

## Objective
Survey 2025–2026 literature (calendar 2026 primary, 2025 for context) on how NoC/interconnect simulators are validated against RTL or hardware: per-flit/cycle-exact agreement vs aggregate-curve agreement (latency/throughput vs load), co-simulation flows, and what validation depth reviewers/venues expect. This feeds the project's credibility gate: an RTL 8×8 mesh NoC co-simulated against BookSim, currently ~83–98% exact-per-flit agreement with characterized residual families.

## Key questions to answer
1. Any 2025–2026 work that gates a software NoC simulator against RTL at per-flit/per-cycle granularity (bit-exact or near-bit-exact co-simulation)? Look for successors to rtl2booksim, SynFull-RTL, UVM-based co-sim, FPGA-in-the-loop, or "RTL-in-the-loop NoC simulation".
2. What validation depth do recent NoC papers report (2025–2026)? Aggregate curves within X%? Simulator-vs-simulator? Simulator-vs-hardware? None at all? (Quantify what you find — e.g., "≤5% latency", "MAPE 18%" etc.)
3. New validation/credibility methodology papers (2025–2026): reproducibility, artifact evaluation, "simulator credibility", calibration, or sensitivity analysis in computer architecture.
4. Any 2025–2026 papers on cycle-accurate NoC simulation tooling (new simulators with validation sections, RTL models validated against simulators or vice versa).
5. Note (context, not new work): the BookSim 2.0 ISPASS 2013 validation claims (≤5% latency, ≤3% throughput vs RTL router) and GARNET's simulator-vs-simulator validation are the historical baseline — flag whether 2025–2026 papers cite or exceed them.

## Sources
- arXiv 2025–2026: "NoC simulator validation", "cycle-accurate NoC RTL co-simulation", "simulator RTL agreement network", "network simulator validation hardware".
- Google Scholar via web search: "NoC simulator validation 2025 2026", "RTL co-simulation network-on-chip 2026", "cycle-exact NoC simulator 2025", "simulator credibility computer architecture 2026".
- Venues: ISPASS 2025/2026, NOCS 2025/2026, ISCA 2025/2026, MICRO 2025, HPCA 2025/2026, ASPLOS 2025/2026, plus artifact-evaluation docs (ACM/ASPLOS/ISCA/MICRO AE criteria) if 2025–2026 revisions exist.
- Background (read, do not redo): `docs/research/simulator-credibility-noc-literature.md` — this survey must EXTEND it with 2025–2026 sources, not re-derive it.

## Rules
- 2025–2026 window; 2026 items first. Historical baseline only as one-line context.
- Do NOT fetch/parse PDF bodies (no alpha_get_paper, no raw .pdf fetch). Use metadata, abstracts, HTML, and web snippets. If only a PDF exists, cite the PDF URL from search metadata and mark full-text parsing as blocked.
- Every claim needs a source URL. No invented sources, numbers, or benchmark claims. If a claim is uncertain (e.g., snippet-only), say so.
- Record the exact search queries you ran at the end of the brief (a "Search log" section).
- Output: Markdown, structured by question, each finding with source URL and a one-line quote or paraphrase, explicit uncertainty markers.
