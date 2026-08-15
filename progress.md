# Progress

## Status
In Progress

## Tasks
- [x] T1 research brief: read outputs/.plans/noc-deadlock-sim-credibility-2026-T1.md
- [x] Run searches (web + arXiv API sweeps; alphaXiv CLI failed with network error — noted in brief search log)
- [x] Verify 2025–2026 sources via abstract/landing pages (no PDF body parsing)
- [x] Write outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t1.md

## Files Changed
- outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t1.md (created 2026-08-14; 25 evidence entries, findings Q1–Q5, search log, coverage status)

## Notes
- alphaXiv `alpha search` unreachable ("fetch failed") despite login; substituted arXiv API (export.arxiv.org) + abs-page fetches; API rate-limited on first attempts, succeeded on retry.
- Key items: HPCA 2026 DFBM (chiplet bridge deadlock), arXiv 2607.01430 (preemptive VCs / AXI protocol deadlock), Q-StaR (DOR baseline), TERA HOTI 2025 (VC-less deadlock freedom), TECS 2025 torus formal approach, DVCon 2025/2026 industrial formal NoC verification.
- No 2025–2026 SAT/SMT (Z3) or nuSMV/Spin NoC-deadlock papers found — reported as explicit "not found" finding per brief rules.
- PDF bodies not parsed per brief; only abstracts/landing pages/snippets used.
