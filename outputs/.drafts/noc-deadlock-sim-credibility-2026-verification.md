# Verification Findings — `noc-deadlock-sim-credibility-2026-cited.md`

- **Reviewer role:** adversarial audit (verification pass), 2026-08-14
- **Method:** full read of the cited draft; scripted `[S#]` extraction (body §0–§8 vs. Sources S1–S95); cross-checks against `research-t1.md`–`research-t4.md`; audit of the URL verification report. Draft **not** edited.
- **Bottom line:** the survey body is usable with targeted hedges; the appended verification report fails its own accounting. No body `[S#]` dangles — numbering integrity is otherwise clean.

---

## FATAL

- **[F1] Verification-report arithmetic contradicts itself** ("Result summary", line 317; status table lines 319–327). "reachable = 89/89 source records" is unreconcilable with the 95 numbered entries in Sources (94 unique — S19 = S76). The five status buckets sum to ~101 (~62+~19+11+4+5) and 11 sources are double-listed across mutually-exclusive buckets (S55, S58, S69, S95, S44 in buckets 2&3; S15, S21, S24, S46 in buckets 2&4; S5, S85 in buckets 2&5). No combination yields 89. The headline statistic is unsupportable as written.

- **[F2] The pass certifies "No unsupported claims required removal" while its own flags contradict that** (flag #11, line 340 vs. flags #4/#5, lines 332–333, and body lines 14, 62). The exec summary's flat "No 2025–2026 paper gates a software NoC simulator against RTL at flit/cycle granularity" (line 14) stands uncorrected even though §2.1 (line 62) records UniCNet's README claim of RTL verification at **unknown** granularity — a live potential counterexample the report itself flags. A certification statement that its own content refutes is fatal to the verification section's credibility.

## MAJOR

- **[M1] "ISPASS 2026 Best Paper" asserted three times in the body, only "Nominee" confirmed** (exec #3 line 14; §2.2 line 70; exec #6 line 17 "the year's Best-Paper example"). The verifier's own flag #5 (line 333) and Sources S31 caveat (line 236) confirm the ISPASS program page marks LLMServingSim 2.0 with ★ = "Best Paper Nominee" only. The comparative claim "stronger than the year's Best-Paper example" (line 17) outruns the evidence. *(Overstated confidence / unsupported claim.)*

- **[M2] DICE's validation numbers are single-source, body-level, presented as headline facts** (exec #5 line 16; §4.1 line 127). "29.4% RMSE vs real AMD EPYC C2C latency (vs 46.4%)" plus 89.5/141.2 cycles and "97.8% FEC" rest on [S37]; Sources S37 caveat (line 242) states these figures are **not in the abstract** (arXiv HTML v2, read by T4 only). The "deepest chiplet/hardware validation found" ranking (exec #5) and the RMSE-rung comparison (exec #6, §6.2 line 175) rest entirely on this unverifiable-at-abstract source. *(Single-source critical claim.)*

- **[M3] Q-StaR DOR premise quote presented as fact in the body despite the verifier's own caveat** (§1.1 line 24; exec #1 line 12: "opens from the premise that DOR is … 'guaranteed deadlock freedom'"). Sources S2 caveat (line 207): the quote "does not appear in the fetched abstract; it is body-level (paper full text, not parsed)." Additionally, the T1 brief's own source table (research-t1.md line 87) labels the same claim "primary (abstract)" — a brief-vs-cited-draft provenance discrepancy the cited draft does not surface in the body. *(Unsupported claim at verified level; internal contradiction across artifacts.)*

- **[M4] "single-VC-safe mechanism" (DFBM) is an interpretive gloss presented as fact** (exec #1 line 12). The verified HPCA page content (Sources S3; research-t1.md line 14) records only packet-injection control + ~2.5% area — no VC-count content appears in the verified record. It feeds the load-bearing §6.1 inference ("a single-VC bridge is a recognized deadlock configuration") and should be relabeled as inference. *(Unsupported claim.)*

- **[M5] Headline negative findings omit the document's own qualifiers** (exec #3 line 14; exec #6 line 17; §6.2 line 175). "Would exceed every published 2025–2026 validation norm" and "Every quantified validation norm … is coarser" drop the "within the searched sources" bound §5.1 establishes and ignore the UniCNet unknown-granularity counterexample (§2.1 line 62). The 83–98% project-internal numbers compared against are themselves unsourced here. *(Overstated confidence.)*

- **[M6] Verification self-certification vs. its own flags** (flag #11 line 340 vs. flags #4/#5, lines 332–333). The report certifies cleanliness while recording that "Best Paper" (line 333) and multiple body-level numbers (line 332) were not independently confirmed — and the body's "Best Paper" usage was left standing. *(Internal contradiction / overstated confidence.)*

## MINOR

- **[m1] Duplicate citation numbers:** S19 (line 224) and S76 (line 281) are the same arXiv record, cited as distinct in §1.6 and §4.1/§4.4; 95 numbers for 94 unique records. Flagged in Sources, retained by design — acceptable, but inflates the apparent inventory. *(Citation-number integrity.)*

- **[m2] "ReNoC-ML" is an unverifiable named example** (§2.4 line 83) listed among BookSim's 2025–2026 citing works inside the [S46] cluster but absent from Sources. Either anchor or delete it. *(Citation integrity.)*

- **[m3] PAC-NoC correction contradicts its own citation:** §3.4 (line 113) asserts the venue is "IEEE TVLSI preprint … not CSDL/JSS", yet the supporting URL (Sources S68, line ~280) is itself a `computer.org/csdl/…` URL. The "not CSDL" half of the correction is refuted by the URL cited for it. *(Internal contradiction.)*

- **[m4] Frontier appears in two postures in the §4.2 ladder** (line 132 "Request/token-level % vs real serving engine"; line 138 "Sim-vs-sim deltas"). Same source, two rows whose labels imply distinct validation classes; the throughput-error figure is vs. real H800 hardware while the latency deltas are vs. SOTA baselines. Split the numbers or merge the row. *(Table consistency.)*

- **[m5] Orphan sources retained in a "cited" draft:** S11, S12 (Sources lines 216–217; flag #10 line 338) are cited nowhere in body sections §0–§8. Disclosed and flagged, but they belong in a notes file, not the Sources of a cited draft. *(Citation integrity.)*

## Verdict

**Reject-with-revisions / re-verify.** The survey's substance (Q1–Q4, §5 caveats, toolchain facts) is largely well-anchored and unusually honest about its limits; all 95 body `[S#]` tokens resolve to existing entries, and the verifier's correction list (flag #2) checks out on re-audit. But the document cannot ship as-is: the verification report's counts (F1) and cleanliness certification (F2, M6) are self-contradictory, and the exec summary — the section most likely to be quoted — carries four unhedged claims (M1–M5) that the document's own caveats undermine. Confidence in the survey conclusions: medium-high; in the verification appendix: low.

## Revision plan (priority order)

1. Redo the status-bucket table; derive counts programmatically from the 95-entry list; state the unique-record count (94) and the S19/S76 duplicate explicitly in the Result summary (F1).
2. Global replace "Best Paper" → "Best Paper Nominee"/unconfirmed in exec #3, §2.2, exec #6 (M1); update the "year's Best-Paper example" sentence (M6).
3. Propagate hedges into the exec summary: "no per-flit gate found *within searched sources*"; add the UniCNet unknown-granularity caveat where "exceeds every norm" appears (M5); relabel DICE numbers and the Q-StaR quote as body-level/single-source in the body text, not only in Sources (M2, M3); relabel "single-VC-safe" as inference (M4).
4. Collapse S76 into S19 and delete/move S11, S12 (m1, m5); drop or source ReNoC-ML (m2); fix the "not CSDL" wording (m3); restructure the Frontier rows (m4).

---

## Sources (additionally inspected)

- Cited draft: `outputs/.drafts/noc-deadlock-sim-credibility-2026-cited.md` (lines cited above)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t1.md` (DFBM record, line 14; Q-StaR source table, line 87)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-research-t4.md` (DICE body-level quotes, lines 81, 155)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-draft.md` (pre-citation version, for provenance comparison — not quoted)
