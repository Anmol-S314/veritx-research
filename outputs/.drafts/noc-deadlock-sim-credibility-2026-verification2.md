# Verification Findings — Pass 2 — `noc-deadlock-sim-credibility-2026-revised.md` (revision 2)

- **Reviewer role:** adversarial audit (second pass), 2026-08-14
- **Method:** full re-read of revision 2; greps for every pass-1 finding (F1/F2/M1–M6/m1–m5); re-audit of URL-report arithmetic; live HTTP spot-check of 6 claimed-reachable URLs (all 200). Draft **not** edited.
- **Bottom line:** all pass-1 findings resolved; residual issues are cosmetic. No new FATAL/MAJOR.

## Summary

Revision 2 propagates every pass-1 hedge and correction into the body and rewrites the verification report's accounting. The contradictory 89/89 headline is replaced by consistent 95-entries/94-unique/0-dead-links arithmetic with overlap explicitly disclosed; exec hedges added; DICE/Q-StaR/BookSim numbers marked body-level in the body; "Best Paper" → "Best Paper Nominee" throughout; ReNoC-ML deleted; S19/S76 duplicate flagged; PAC-NoC wording fixed; Frontier rows split; S11/S12 moved to Appendix A. Spot-checked links are live.

## Strengths

- [S1] **F1 fixed:** "95 numbered entries = 94 unique records (S19 and S76 are the same arXiv record)… All 94 unique records were reachable; 0 dead links," plus an explicit "classes are descriptive, not a partition" statement — internally consistent and self-disclosing.
- [S2] **F2/M6 fixed:** certification (flag 11) no longer claims cleanliness; it says no claim was removed and flags were propagated into the body — consistent with its own flags.
- [S3] **M1 verified mechanically:** zero "Best Paper" without "Nominee" (5 "Best Paper Nominee" occurrences); §5 caveat 8 confirms usage throughout. m3 fixed in §3.4 + Sources S68 (hosting-vs-venue distinction).
- [S4] **M5 fixed:** hedges in every previously-overreaching exec item, incl. UniCNet counterexample. M2/M3/M4 marks confirmed (§0/§1.1/§2.2/§4.1/§4.2/§6); no "single-VC-safe" anywhere. m1/m2/m4/m5 fixed (S19/S76 flagged; ReNoC-ML gone; Frontier rows split; S11/S12 in Appendix A).

## Weaknesses

- [W1] **MINOR:** bucket-1 ranges sum to 64, not "≈60"; S13 is listed there though its own annotation (Sources #13) says "abstract text not re-captured this pass" (and bucket 2 marks it "both classes apply"); S11 (abstract verified) appears in no bucket. Cosmetic — the table is explicitly non-partition/approximate, so F1 does not resurface.
- [W2] **MINOR:** flag 11's "no claim was removed in either pass" sits in tension with the applied m2 fix (ReNoC-ML was deleted from §2.4). Defensible (citation example, not claim), but the wording invites the same self-contradiction objection raised in pass 1.
- [W3] **MINOR:** "0 dead links" covers 94 URLs; this pass re-sampled only 6 (all 200). Claim remains un-sampled for ~88 URLs.

## Verdict

**Pass (minor cleanups).** Every pass-1 finding — F1, F2/M6, M1–M5, m1–m5 — is verifiably resolved; no new FATAL/MAJOR introduced. The verification-report arithmetic is now self-consistent, certification language is self-consistent, and exec claims carry their qualifiers. W1–W3 are non-blocking. Confidence: high on fix-completeness; medium on the unsampled remainder of "0 dead links".

## Revision Plan

1. Align bucket-1 range/count with per-source annotations (move S13 to bucket 2; correct "≈60" or the range) (W1).
2. Reword flag 11: "no factual claim removed; ReNoC-ML citation example dropped" (W2).
3. Optionally log the 6/6 sampled re-check into the report (W3).

## Inline Annotations

> "the Sources list contains **95 numbered entries = 94 unique records**… **All 94 unique records were reachable at check time; 0 dead links.** Status classes below overlap by design… descriptive, not a partition."
**[W1] MINOR (F1 fixed):** headline arithmetic now consistent; bucket sub-counts remain off (64 vs "≈60"; S13 mis-bucketed).

> "**Certification (revised):** no claim was removed in either pass… revision 2 propagates them into the body text"
**[W2] MINOR (F2/M6 fixed):** self-consistency restored. Nit: ReNoC-ML was deleted this revision; "no claim removed" holds only under a claim-vs-citation distinction the text never states.

> "the one potential counterexample — UniCNet's README-level claim… is of unknown granularity and needs a full-text check (PDF blocked)"
**[S4] (M5 fixed):** hedge in exec #3, echoed in §6; §5 caveat 4 lists the uncertain numbers.

> "Note: the URL is hosted on IEEE CSDL, which is the hosting platform — the correction concerns the *publication venue* (TVLSI PrePrints), not the hosting domain."
**[S3] (m3 fixed):** the "not CSDL" self-contradiction is gone from both §3.4 and S68.

> "Frontier appears twice by design — its throughput error is vs real H800 hardware… while its latency-error reductions are vs prior SOTA simulators…"
**[S4] (m4 fixed):** rows split with explicit reference-target note; numbers match S33's abstract.

## Sources (additionally inspected)

- `outputs/.drafts/noc-deadlock-sim-credibility-2026-revised.md` (revision 2; full read + greps)
- `outputs/.drafts/noc-deadlock-sim-credibility-2026-verification.md` (pass-1 findings)
- Live HTTP 200 spot-checks (6 URLs): CAL-UniCNet repo, researchr.org/publication/GangulyTLIM26, sarchlab.org/cams25, zenodo.org/records/19686855, DICE-Simulator repo, lubis-eda.com deadlock blog
