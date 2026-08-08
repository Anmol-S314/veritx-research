# VeritX Research Programme — v2 Re-scope (Months 3–6, Aug–Nov 2026)

**Supersedes the claims and targets in `VeritX_BTech_6Month_Programme.txt`** (kept
for reference only, `archive/`-bound). The v1 programme set out to "validate core
VeritX IP architecture claims." Our own research falsified that premise:

- on-chip NoC topology is a second-order knob for transformer accelerators
  (`tracks/t3-topology/CONCLUSION.md` — double-anchored, measured, honest),
- the one mechanism we found (KV multicast) is already shipped by Tenstorrent
  (PITFALLS §18),
- the single most valuable artifact produced so far is a *methodology*
  (PITFALLS.md — 18 documented ways interconnect models produce confident wrong
  numbers, and how to catch them).

**What the programme is now:** the lab of an interconnect-credibility services firm
(see `docs/business/validation-services.md`). Students produce the methodology, the
case studies, and the toolchain that the services business sells. Nothing about the
research quality changes; the *framing* and the *output targets* change.

---

## 1. The reframe, in one line for every audience

| audience | what you say now |
|---|---|
| Students | "You're learning to measure interconnect performance so the numbers survive contact with reality — and co-authoring the methodology for doing it." |
| Institutes/faculty | "An industry research programme in AI-interconnect measurement and simulation credibility." |
| Investors | "We sell truth about interconnect performance claims; the programme is our R&D lab and talent pipeline." |
| Anyone | NOT "validating VeritX IP." Dead phrase. |

## 2. Deliverables for the remaining four months

The programme now ships one product-shaped deliverable per month, all
traceable to the existing repo:

| month | deliverable | builds on | who |
|---|---|---|---|
| **M3 (Aug)** | **Audit Playbook v0** — PITFALLS.md formalised into a 30-point audit checklist (claim → what must be true → what check kills it → our past failure as the worked example) | `tracks/t3-topology/PITFALLS.md` | T3 team, Nachiket edits |
| **M3 (Aug)** | **On-silicon measurement #1** — run `hardware/noc_multicast_bw.cpp` on a rented TT card; the answer (flat-in-fanout or not) decides the 5.4× ceiling claim | `tracks/t3-topology/hardware/` | T3, 1 student |
| **M4 (Sep)** | **Case study pack v1** — three public (redacted) case studies: (1) the honest 5.4× decode number incl. DRAM-efficiency derating, (2) the D(G) fabric law / "keep KV off the fabric", (3) T2's deadlock-validation study as a worked audit of a deadlock-freedom claim | `serving_multicast.py`, `die_to_die_matrix.py`, T2 sweep | T3 + T2 |
| **M4 (Sep)** | **Pilot audit #1** — at-cost credibility audit of one external startup's NoC pipeline, run through the playbook | Playbook v0 | Nachiket + 2 best students, senior sign-off |
| **M5 (Oct)** | **Pilot audits #2–3** + **Audit Playbook v1** (updated with what pilots broke) | pilots | Nachiket + teams |
| **M5 (Oct)** | **Methodology paper** — "Eighteen ways an interconnect model lied to us" (PITFALLS condensed) submitted to a workshop; T4's sim-vs-formal coverage study as a companion | PITFALLS, T4 wk-15 study | T3 + T4 leads |
| **M6 (Nov)** | **Demo day = services portfolio demo**: playbook v1 + 3 case studies + 3 pilot results + services catalog with pricing; all datasets/code handed over | everything | all 15 |

Explicitly dropped: the ISCA/DAC/DATE 2027 conference targets, the
"PRESET_INFERENCE topology default," the "ASIL-B package," and all patent-flag
checkpoints. Papers are now marketing collateral with a workshop-level target, not
revenue.

## 3. Track remapping

| track | v1 goal (dead) | v2 goal |
|---|---|---|
| T1 — KV-cache QoS | gem5 QoS routing → ISCA paper | **Optional.** Only if the gem5 build lands; otherwise becomes a methodology contribution: "why a 4–6 h build deferred is the first calibration check" (a Pitfall in its own right). Students fold into T3 case study work. |
| T2 — Deadlock | XY vs UGAL + SPIN proof → NOCS paper | **Worked audit #3**: take a deadlock-freedom claim (theirs or a textbook one), run it through the gate discipline, produce a public case study on *how to validate such a claim*. SPIN kept only as an optional demo. |
| T3 — Topology | topology Pareto → VeritX's PRESET | **Flagship lab**: completes the honest analysis series (5.4× with all deratings, D(G) fabric law, decode roofline), the on-silicon multicast measurement, and the Audit Playbook. Already 80% of the way there. |
| T4 — Formal | ASIL-B property package | **Formal-verification service arm**: property-writing playbook, the sim-vs-formal coverage study (wk 15 — the strongest result), bug-injection demo. Sells as a service, never as certification. |

## 4. Student terms (fix these now — they are a recruiting and legal poison)

1. **Delete "BTech students may NOT be listed as inventors"** (programme doc §8).
   Replace with: students co-author every paper they contribute to; their
   dissertation rights are untouched; client work is anonymous but credited.
2. **NDA stays, reframed**: it protects *client* confidentiality and our toolchain,
   not a fictitious IP estate.
3. **Institute pitch updated**: no more "validating core VeritX IP architecture
   claims." The SRA, if signed, must describe the programme as it now is.
4. **Tell the students this week.** The reframe costs none of them anything — they
   get more credit than under v1. The ones who joined for "secret IP" are few; the
   ones who stay for learning + paper + stipend are the majority.

## 5. Sequencing and risk

| month | critical path | kill condition |
|---|---|---|
| M3 | playbook v0 → pilot-ready; silicon run | if the TT card is not rentable, Service C case study falls back to a documented *protocol* + expected-shape analysis (weaker, still publishable) |
| M4 | pilot #1 signed | if no startup takes the at-cost audit, pivot pilots to VCs (diligence packs) — the product is the same |
| M5 | pilots #2–3 + paper | if pilots expose playbook failures, that is the *result* — version it and say so |
| M6 | demo day + services catalog | — |

The discipline that made T3 worth anything — pre-committed gates, selfchecks,
calibrated numbers, known-answer tests — now applies to the *business*: every
deliverable has a defined failure mode and a defined response. Same methodology,
new subject.
