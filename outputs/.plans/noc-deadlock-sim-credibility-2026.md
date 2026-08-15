# Deep Research Plan: NoC Deadlock & Simulator Credibility — 2026 Literature Survey

- **Slug:** `noc-deadlock-sim-credibility-2026`
- **Date:** 2026-08-14
- **Request:** "do a proper literature survey, check out articles in Google Scholar or arXiv, check 2026"
- **Scope assumption (pending user confirmation):** survey the project's research domain — NoC routing/deadlock analysis and interconnect simulator credibility — with a 2025–2026 emphasis (calendar-year 2026 primary). This maps to live project threads: 0344/F14 deadlock forensics (BookSim vs RTL routing divergence), the sim↔RTL credibility gate, and the paper framing questions (exact% 83–98 vs 99.85).

---

## 1. Key Questions

1. **Deadlock (2025–2026):** What is the recent state of the art in NoC deadlock analysis? New results on deadlock-freedom of deterministic routing (DOR) with VC allocation, table-based routing, multi-die/bridge topologies, bufferless routing, or formal deadlock detection (SAT/SMT, model checking, cycle-dependency analysis)?
2. **Sim↔RTL credibility (2025–2026):** What do recent papers report for simulator↔RTL validation of NoC simulators — per-flit/cycle-exact vs aggregate-curve agreement? Any new bit-exact co-simulation or RTL-in-the-loop work (successors to rtl2booksim, SynFull-RTL, UVM/co-sim flows)?
3. **Landscape 2026:** What new NoC simulators, frameworks, or major releases appeared 2025–2026 (e.g., ASTRA-sim 3.0, gem5 v25.x, NoCDAS, CHIPSIM, LEGOSim, BookSim updates) and what validation stories do they ship?
4. **AI-accelerator interconnect serving (2025–2026):** Recent work on KV-cache/LLM-serving interconnect simulation and wafer-scale NoCs (ISCA 2026, MICRO 2025, HPCA 2026) — what validation norms do they report (aggregate % vs hardware, per-request vs cycle)?
5. **Cross-cutting gap check:** Is there any 2025–2026 work that gates a software NoC simulator against RTL at per-flit/per-cycle granularity (the project's claimed niche)? If none, that is a finding, not a failure.

## 2. Evidence Needed

- arXiv listings 2025–2026: NoC deadlock, routing, VC allocation, NoC simulator validation, LLM-serving systems/NoC.
- Google Scholar top hits for targeted phrases (via web_search; Scholar has no official API — snippets + linked sources).
- Conference venues: NOCS 2025/2026, ISCA 2025/2026, MICRO 2025, HPCA 2025/2026, ASPLOS 2025/2026, ISPASS 2025/2026.
- Tool release notes / official docs for ASTRA-sim, BookSim, gem5, NoCDAS, CHIPSIM, LEGOSim.
- **Background (read, extend — do not duplicate):** `docs/research/simulator-credibility-noc-literature.md` (2026-08-12) and `docs/research/simulator-landscape-2026.md` (2026-08-12).
- **Method constraints:** no `alpha_get_paper`/PDF body parsing unless explicitly requested; prefer metadata, abstracts, HTML, and web snippets. If only a PDF exists, cite the PDF URL from search metadata and mark full-text parsing blocked.

## 3. Scale Decision

**Broad, multi-faceted survey → 4 `researcher` subagents** (T1–T4), then mandatory `verifier` pass, then mandatory `reviewer` pass (sequential, never parallel with verifier). Direct-search mode not chosen: the request explicitly asks for a "proper" survey across Scholar + arXiv with a 2026 check, which spans ≥4 distinct literatures.

Task fan-out (concurrency 4, `failFast: false`):

| Task | Owner | Focus |
|---|---|---|
| T1 | researcher | NoC deadlock analysis & formal deadlock-freedom verification, 2025–2026 |
| T2 | researcher | Simulator↔RTL validation & credibility practice, 2025–2026 |
| T3 | researcher | NoC simulator landscape 2026: new tools/releases + validation stories |
| T4 | researcher | AI-accelerator / LLM-serving interconnect simulation, 2025–2026 |
| Draft | lead (me) | Synthesize into `outputs/.drafts/noc-deadlock-sim-credibility-2026-draft.md` |
| V1 | verifier | Add citations, verify URLs → `...-cited.md` |
| R1 | reviewer | Verification pass on cited draft → `...-verification.md` |

## 4. Task Ledger

| ID | Task | Owner | Status | Notes |
|---|---|---|---|---|
| T1 | Deadlock lit brief | researcher | done 2026-08-14 | `outputs/.drafts/...-research-t1.md` (4/4 parallel OK; alphaXiv API down, arXiv/web substituted) |
| T2 | Sim↔RTL credibility brief | researcher | done 2026-08-14 | `outputs/.drafts/...-research-t2.md` |
| T3 | 2026 simulator landscape brief | researcher | done 2026-08-14 | `outputs/.drafts/...-research-t3.md` (corrects background doc §7) |
| T4 | AI interconnect serving brief | researcher | done 2026-08-14 | `outputs/.drafts/...-research-t4.md` |
| S1 | Synthesize draft | lead | done | `outputs/.drafts/...-draft.md` |
| V1 | Verify + cite | verifier | done 2026-08-14 | → `...-cited.md`; 94/94 unique records reachable, 0 dead links; S90–S95 added |
| R1 | Review cited draft | reviewer | done (2 passes) | → `...-verification.md` + `...-verification2.md`; pass-2 verdict PASS; fixes → `...-revised.md` |
| D1 | Deliver | lead | done | `outputs/noc-deadlock-sim-credibility-2026.md` + `.provenance.md` |
| V1 | Verify + cite | verifier | pending | → `...-cited.md` |
| R1 | Review cited draft | reviewer | pending | → `...-verification.md`; fixes → `...-revised.md` if needed |
| D1 | Deliver | lead | pending | `outputs/noc-deadlock-sim-credibility-2026.md` + `.provenance.md` |

## 5. Verification Log

| # | Check | When | Result |
|---|---|---|---|
| V-01 | Plan approved by user before evidence gathering | start | PASS (user: "yes") |
| V-02 | All 4 research briefs written and returned | after T1–T4 | PASS (4/4 succeeded; alphaXiv API blocked, web/arXiv substituted — see D-06) |
| V-03 | Draft exists; every critical claim maps to a source/URL or is marked inference | after S1 | PASS (claims mapped to [S#] + brief files; inferences labeled) |
| V-04 | `...-cited.md` exists on disk after verifier; URLs checked | after V1 | PASS (339 lines; 94/94 unique reachable; 0 dead links) |
| V-05 | Reviewer flags recorded; FATAL fixed; fixes proven via `rg`/read | after R1 | PASS (pass-1: 2 FATAL/6 MAJOR/5 MINOR → revised; pass-2: PASS; rg checks confirmed) |
| V-06 | Required artifacts exist: plan, draft, cited, final, provenance | before delivery | PASS (all on disk, checked via ls) |
| V-07 | No invented sources/results/benchmarks (spot-check citations) | before delivery | PASS (verifier + 2 reviewer passes; all numbers trace to sources or are marked body-level/uncertain) |

## 6. Decision Log

| # | Decision | Rationale |
|---|---|---|
| D-01 | Topic scoped to project domain (NoC deadlock + simulator credibility), 2025–2026 window, 2026 primary | User request under-specified; project context (0344/F14, gate credibility, paper) makes this the most useful reading. **User may redirect in confirmation.** |
| D-02 | Scale = 4 researcher subagents | "Proper literature survey" across Scholar + arXiv, ≥4 literatures → broad survey tier. |
| D-03 | Existing repo lit docs are background, not re-do targets | They are 2 days old and focused; survey extends with 2026 checks and deadlock pillar. |
| D-04 | No PDF body parsing (`alpha_get_paper` / raw `.pdf` fetch) | Workflow rule; PDF-only sources cited from metadata with parsing marked blocked. |
| D-05 | `memory_remember` not available in this tool set | No memory tool visible; plan saved to disk only. |
| D-06 | alphaXiv API (`alpha search`) failed with network error in all 4 researchers | Recorded as blocked capability; evidence gathered via web_search + arXiv abs pages + APIs instead. |
