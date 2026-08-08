# VeritX — Interconnect Credibility Services

**What we sell:** truth about interconnect performance claims — before your customers,
investors, or tapeout find out they were wrong.

**Status: draft v1 (2026-08-05).** Replaces the "AI-native NoC IP validation" framing,
which our own research falsified (see `tracks/t3-topology/CONCLUSION.md`). This document
is the new business north star. Everything below is built from assets that exist in this
repo today.

---

## 1. The problem we solve

The AI-silicon market runs on simulation numbers. Every accelerator startup's pitch
contains one: "our NoC does X," "our fabric saves Y%," "our KV-cache architecture
delivers Z tok/s." The buyers of these numbers — VCs, hyperscaler procurement, ODMs,
sovereign-AI programmes — cannot check them. The people who produce them cannot check
them either, because they never calibrated their simulators.

We can say this with evidence, because we did it to ourselves. The T3 study
(`tracks/t3-topology/PITFALLS.md`) catalogues **18 distinct ways our own NoC models
produced plausible, confident, wrong numbers** — and the topology verdict flipped four
times. The list is not exotic:

- a hardcoded CSV constant that made routers "95% of the die"
- a flit size that was in bytes, not bits, pinning an entire sweep
- a hand-waved path length that decided the headline and was 2.5× wrong
- a sensitivity sweep that was flat *by construction* and read as proof of robustness
- a placeholder traffic pattern shipped as a result
- a silicon anchor (FlooNoC's 0.15 pJ/B/hop) that measured *routers only* while we
  applied it to the wires carrying 72% of the energy

Every one of these is a bug a company could ship to a customer. Every AI-chip team is
running one of them right now.

**The market does not have a "measure the claims" service.** Tool vendors (Arteris,
Synopsys) sell simulators — they have no incentive to tell you the number is wrong.
Verification consultancies exist, but for RTL correctness, not for *model credibility*.
Nobody sells the audit that says "your NoC model is calibrated" or "it isn't, and here
is the magnitude of the error."

## 2. The offering

Three services, one methodology underneath. The methodology is the moat; the services
are how we monetise it.

### Service A — Credibility audit (entry product)

Review a customer's NoC/interconnect simulation pipeline against the discipline in
PITFALLS.md, turned into a 30-point checklist (deliverable: the Audit Playbook).

**What they get:** a written report that classifies every claim in their pipeline as
*calibrated*, *uncalibrated*, or *known-false*, with the size of the error where we can
measure it. Plus the checklist, so their next pipeline has it wired in.

**Price: ₹8–25L (~$10–30K)** per audit, 2–4 weeks. Target: 10–20 customers/year.

### Service B — Calibration and re-measurement (the serious one)

Build them a silicon-anchored measurement the way we did: cycle-accurate DRAM
(Ramulator2), a router energy model calibrated against published silicon (FlooNoC,
1.37×), measured floorplans instead of guessed rulers, known-answer gates
(`g−1 = 7, exactly`). This is what the repo's toolchain already does
(`scripts/`, `third_party/booksim2` flit-fork patch, `hardware/` microbenches).

**What they get:** a re-measured headline number they can put in front of a customer,
with the evidence trail behind it. This is precisely the "5.4× → honestly 244 tok/s
and here's the DRAM efficiency it assumes" move, done for their chip.

**Price: ₹40L–1.2Cr (~$50–150K)** per engagement, 6–12 weeks. Target: 5–10/year.

### Service C — On-silicon verification (where we have a real edge)

We already wrote the kernel-level microbench that checks a NoC multicast claim against
actual hardware (`tracks/t3-topology/hardware/noc_multicast_bw.cpp` — measures whether
multicast wall-time is flat in fanout, the assumption the whole KV-serving result rests
on). We rent the card (TT-Koyeb cloud), run the benchmark, and the answer decides the
claim. **Measuring assumptions on real silicon instead of asserting them** is the
single most defensible thing this team can sell.

**Price: ₹8–20L (~$10–25K)** per measurement campaign. Target: as many as the
customer base sustains.

### How the programme feeds the business

The BTech research programme stops being "validation" and becomes **the lab**:

- students produce the methodology (playbook v1 = PITFALLS formalised),
- students produce the case studies that prove the service (the honest 5.4×, the
  D(G) fabric law, the decode roofline, the deadlock and formal suites),
- the CI/Docker toolchain becomes the delivery infrastructure — every audit runs
  in the same reproducible pipeline we hold ourselves to,
- the stipend economics (₹10K/student/month) keep the cost base at a fraction of
  what a consulting shop would charge for the same labour.

That is the moat, stated plainly: **a methodology + a calibrated toolchain + a
pipeline of cheap, trained labour.** Not patents we don't have. Not claims a vendor
already shipped.

## 3. Who buys, and who pays first

| customer | why they buy | which service |
|---|---|---|
| AI chip startups (50+ funded, most with a NoC claim) | their Series-A data is about to be checked | A, then B |
| Semiconductor VCs | $50K diligence before a $50M cheque is cheap insurance | A (as diligence package) |
| Hyperscaler / ODM procurement | validating a supplier's perf claims before commit | B |
| Sovereignty/consortium programmes | they fund silicon on written promises | B, C |

First move (90 days): **five free or at-cost audits** for startups we can name as
reference customers, producing public (redacted) case studies. The playbook is the
product; the first five audits are the proof it works on someone else's pipeline,
not just ours.

## 4. What we explicitly do NOT sell anymore

1. **"AI-native NoC IP"** — our own research shows topology is not the lever
   (CONCLUSION.md) and the one mechanism we found is already shipped by Tenstorrent
   (PITFALLS §18). Dead. Saying it once more in a pitch is how we get caught.
2. **Patents as the asset** — nothing in the repo is patentable as-is, and the
   programme's "students may not be inventors" clause is both a liability and a
   recruiting poison. Drop it.
3. **"ASIL-B package"** — T4 proves toy modules; real ASIL-B is a TÜV SÜD process.
   We sell *formal verification services* (property writing, proof strategy,
   simulation-vs-formal coverage studies), not certification claims.
4. **Conference targets as deliverables** — papers are marketing, not revenue.
   Workshop-level publication of the methodology (PITFALLS-style) and the case
   studies is the honest, achievable goal.

## 5. Risks, stated plainly

- **Small market until proven.** The "credibility audit" category does not exist
  yet. We must create it with the first five engagements. Mitigation: the
  at-cost pilots + public case studies.
- **Customers may not want the honest number.** A startup that learns its headline
  is 2× off may not pay to hear it. Mitigation: position B as "re-measure it right,
  then it's *more* fundable," and target VCs/ODMs who *want* the honest number.
- **Talent quality.** BTech students are cheap and, with our supervision, have
  produced genuinely good work (PITFALLS is world-class). But audits for paying
  customers cannot be student-signed. Rule: every deliverable goes out over a
  senior engineer's name, students credited internally and on papers.
- **We are selling the thing we used to be bad at.** Credibility is the product and
  we are one rushed audit away from being the cautionary tale. The non-negotiable:
  every client engagement runs through the same gates we imposed on ourselves
  (Gate 0–4 in `tracks/t3-topology/PLAN.md`), and the checklist includes our own
  past failures by name.

## 6. What the company is in one sentence

> VeritX is the firm that finds the 18 ways your interconnect numbers are wrong —
> before your customers do — and re-measures them until they're right.
