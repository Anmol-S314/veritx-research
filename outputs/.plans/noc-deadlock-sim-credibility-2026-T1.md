# T1 Brief — NoC Deadlock Analysis & Formal Deadlock-Freedom Verification (2025–2026)

**Researcher task:** Produce `noc-deadlock-sim-credibility-2026-research-t1.md` (in `outputs/.drafts/`).

## Objective
Survey the 2025–2026 literature (calendar 2026 primary, 2025 for context) on network-on-chip (NoC) deadlock analysis, deadlock-free routing proofs, and formal/automated deadlock detection for routers and networks. This feeds a live project thread: a 2D-mesh RTL NoC vs BookSim where routing divergence between Dijkstra/table-based routing and dimension-order routing produced a cross-die hang (a channel-dependency cycle), plus a multi-die bridge topology with a single VC.

## Key questions to answer
1. New 2025–2026 results on deadlock-freedom of deterministic routing (DOR/XY), table-based (lookup) routing, and VC allocation strategies. Any results specific to mesh or multi-die/bridge topologies?
2. Automated deadlock detection in routers/NoCs: cycle-dependency analysis (channel dependency graphs), SAT/SMT-based approaches, model checking (e.g., using Z3, nuSMV, spin), or tools that analyze routing tables for deadlock. Any 2025–2026 papers or tools?
3. Bufferless routing and deflection routing deadlock results (2025–2026).
4. Any 2025–2026 work on deadlock in AI-accelerator NoCs or wafer-scale/chiplet interconnects.
5. The classic grounding: Dally & Seitz channel dependency theory — note if recent papers still build on it (context only, no need to read the 1987 paper body).

## Sources
- arXiv (2025–2026): use paper search (alpha search) and arXiv listing pages. Query ideas: "NoC deadlock 2025", "deadlock-free routing network-on-chip", "channel dependency graph deadlock", "formal verification deadlock NoC", "deadlock detection router 2025", "bufferless NoC deadlock 2026".
- Google Scholar via web search: "deadlock NoC 2025 2026", "deadlock-free routing verification 2026", "NoC deadlock SAT/SMT", "routing table deadlock freedom".
- Venues: NOCS 2025/2026, ISCA 2025/2026, MICRO 2025, HPCA 2025/2026, ASPLOS 2025/2026, DATE 2025/2026, DAC 2025.

## Rules
- 2025–2026 window; 2026 items first. Older foundational work only as one-line context with citation.
- Do NOT fetch/parse PDF bodies (no alpha_get_paper, no raw .pdf fetch). Use metadata, abstracts, HTML (arXiv abs pages, ACM/IEEE landing pages), and web snippets. If only a PDF exists, cite the PDF URL from search metadata and mark full-text parsing as blocked.
- Every claim needs a source URL (arXiv ID preferred). No invented papers. If a search turns up nothing for a question, say "no 2025–2026 work found" — that is a valid finding.
- Record the exact search queries you ran at the end of the brief (a "Search log" section).
- Output: Markdown, structured by question, each finding with source URL and a one-line quote or paraphrase, explicit uncertainty markers where the snippet is ambiguous.
