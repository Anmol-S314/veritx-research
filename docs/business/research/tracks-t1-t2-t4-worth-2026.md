# Tracks T1/T2/T4 — worth pursuing? 2026 evidence probe

**Status:** desk research, 2026-08-10. Question posed against the v2 reframe
(`docs/business/programme-v2.md`): the programme is now an interconnect-credibility
services lab; T1 is marked *optional*, T2 is case-study #3, T4 is the formal service
arm. Is that stance right, and is any of the three worth keeping at all? Companion
probe to `tracks/t3-topology/research/custom-noc-landscape-2026.md`.

**Headline:** **All three are worth pursuing — but none in their v1 form, and the v2
reframe under-sells the commercial case while over-selling the tooling.** The market
for what these tracks would sell exists and is growing (formal services +19.6% YoY
while verification tools were −2.6% in the same quarter; formal-deadlock and NoC-QoS
claims are everywhere in AI-silicon marketing and nowhere in evidence). The decisive
findings are: (1) someone productized the T4 plan as a paid product two months ago
(Axiomise nocProve) — validation *and* a raised bar; (2) a simulation-only deadlock
audit (the v2 T2 plan) is **fake rigor** — deadlock absence is co-NP-complete, so the
credible product needs graph/formal analysis on the freedom side; (3) the T1 plan's
toolchain (full-system gem5 + Garnet + ASTRA-sim) is the most expensive and *least
credible* route to QoS numbers in 2026 — the field has moved to standalone/trace-driven
NoC simulation, and nobody validates Garnet against silicon.

---

## TL;DR / key verdicts

1. **T4 (formal) is the strongest commercial bet of the three.** Formal verification
   *services* are a proven, growing market (Axiomise: "multi-million dollar, zero VC",
   20+ customers; LUBIS EDA fixed-price-per-block; Synopsys Formal Consulting 25+
   projects in 5 years). The planned sim-vs-formal coverage study is a documented,
   publishable methodology (DVCon canon, CAV 2011) — and the exact "property playbook
   for NoC blocks" idea was productized by Axiomise's **nocProve (launched 2 Mar 2026)**.
   Open-source tooling is credible in 2026 (Yosys 0.68, CBMC ETAPS Test-of-Time award,
   lowRISC's all-open-source Ibex correctness proof in CI, Jan 2026).
2. **T2 (deadlock) is worth keeping only if reframed.** Simulation witnesses deadlocks;
   it cannot prove their absence (wormhole deadlock freedom is co-NP-complete — Verbeek
   thesis, Radboud 2013). A BookSim-only "audit" would be exactly the fake rigor the
   company is built to kill. The credible product pairs DDG/CDG graph analysis + VN-level
   argument (freedom side) with BookSim/Garnet stress + fuzzing (falsification side),
   with every conclusion labeled by evidence class. The unclaimed niche — deadlock
   under AI/bursty/multicast traffic — is real: even Arm CMN-700 has documented errata
   deadlocks in shipping silicon.
3. **T1 (KV-cache QoS) is worth pursuing only re-scoped.** Full-system
   gem5+Garnet+ASTRA-sim is the wrong vehicle: Garnet has no QoS/priority arbitration
   (round-robin only — you'd write the allocator yourself), ASTRA-sim 3.0 (Jun 2026)
   moved *away* from the gem5-Garnet coupling, and no 2024–26 paper in the (red-hot)
   KV-cache/NoC space uses that stack. The sellable asset is the audit: Groq
   (now NVIDIA), Cerebras, and Tenstorrent all market determinism/QoS with zero public
   NoC-level microbenchmarks, and their hardware is buyable (Wormhole n150 ≈ $999,
   GroqCloud API).
4. **The market signal cuts across all three tracks:** independent NoC/QoS/deadlock/
   formal evidence is not sold by anyone — Arteris publishes mechanisms, not proofs;
   NVIDIA/Cerebras publish nothing; the closest precedents (10xEngineers Jasper-based
   NoC formal service, Axiomise nocProve) are commercial-tool-bound, not open-source and
   not independent. That is the wedge the v2 business already claims; the research
   confirms it exists.
5. **Compute discipline is a real constraint, not a footnote.** The lab's single 32 GB
   runner supports ≈2 full-system gem5 jobs/day; statistically sound full-system
   measurements need months of wall time at ~250 KIPS. Garnet-standalone sweeps are
   minutes per point. T2 and T4 are runner-friendly; only the v1 T1 plan is not.

---

## T1 — KV-cache QoS (gem5 + Garnet + ASTRA-sim)

### Verdict

**Pursue, re-scoped.** Drop full-system gem5+ASTRA-sim as the research vehicle; use
Garnet-standalone/BookSim driven by real KV-cache traces (Georgia Tech ships a
trace-simulation patch for exactly this), and point the students' energy at the
on-silicon QoS-claim audit. The v2 "optional" status is right; the *reason* should be
updated: it is not that the build hasn't landed, it is that the toolchain is the wrong
one for the claim.

### Tooling health (verified 2026-08-10)

| tool | status | detail |
|---|---|---|
| gem5 | **Healthy** | v25.1.0.1 (Apr 2026); ~2 major releases/yr; last commit 8 Aug 2026. But API churn between releases — pin whatever you build on. |
| Garnet 2.0/3.0 | In-tree, maintained — **no QoS** | Docs (edited 10 Jul 2026): SA-I/SA-II round-robin only; priority arbitration requires modifying SwitchAllocator yourself. QoS work is *writing the allocator*, not configuring it. |
| ASTRA-sim | Active, but **moving away from Garnet** | 3.0 paper (arXiv Jun 2026) adds its own "Simple" NoC backend; the Garnet backend repo (`astra-network-garnet`) is a stale gem5 fork (19 commits, 7 stars); repo README still says v2.0. |

### Why the field validates the re-scope

- Every recent KV-cache/NoC paper builds its own standalone sim or uses trace-driven
  NoC simulation (NoCDAS TOMACS'25; LLaMCAT ICPP'25; LOKI ISCAS'26; LEAP ICCAD'25).
  **No 2024–26 paper was found doing "KV-cache QoS under NoC arbitration policies in
  gem5+Garnet"** — an unclaimed framing, but one the community has evidently judged not
  worth the cost.
- Garnet has **never been validated against silicon** (ISPASS 2009 validates against
  another simulator, PoPNet); gem5 CPU models measured at **136% mean error → 6%**
  after calibration (SC19 PMBS). This documented calibration gap is the credibility
  lab's strongest asset — and the reason T1's deliverable should be an audit, not a
  raw number.
- Compute reality: full-system gem5 ≈ 250 KIPS (SIGARCH, Jun 2026); statistically
  sound measurement windows (5–120 s of target time) = months of wall time. A
  20-point Garnet-standalone sweep is a morning's work.

### The sellable asset

| company | claim | public evidence |
|---|---|---|
| Groq (→NVIDIA, $20B, Dec 2025) | deterministic latency, zero runtime arbitration | ISCA papers + tech docs; no NoC-level latency-distribution microbenchmarks — **falsifiable via GroqCloud tail-latency stats** |
| Tenstorrent | Arteris FlexNoC QoS, "guarantee QoS between cores" | case study + tt-ISA NoC docs; no NoC-level QoS microbenchmarks — **hardware ≈ $999** |
| Cerebras | deterministic wafer-scale "Swarm" fabric | whitepapers; no NoC-latency microbenchmarks |

Sources: gem5 releases/GitHub; gem5 Garnet-2 docs; ASTRA-sim repo + arXiv 2606.10440;
GT Synergy Garnet tools page; SC19 PMBS paper; SIGARCH "Return of Rigorous Full-System
Timing Simulation" (2026); Arteris/Tenstorrent case study; NVIDIA AI Infra post.

---

## T2 — Deadlock with BookSim 2.0

### Verdict

**Pursue, reframed — and fix the rigor problem first.** The v2 plan ("worked audit of
a deadlock-freedom claim via BookSim sweeps") is credible only if simulation is used
for falsification and graph/formal analysis for freedom. A BookSim-only audit would
publish the exact category of confident-wrong conclusion PITFALLS.md exists to catch.

### Why simulation-only is fake rigor (the core finding)

- Wormhole deadlock freedom is **co-NP-complete** (Verbeek PhD thesis, Radboud 2013) —
  no polynomial automatic checker exists; N deadlock-free runs say nothing about run
  N+1.
- The 2025 TECS torus paper states it directly: DDG analysis is required *to confirm
  deadlock freedom*; simulation is insufficient. It also hands the lab a ready-made
  falsification corpus: **14 deadlock-prone arc combinations**.
- The formal line (xMAS/ACL2, Verbeek–Schmaltz, ADVOCAT) proved deadlock/livelock
  freedom for classic wormhole networks — but its tooling is **dormant** (WickedXmas
  Windows-only + unmaintained; ACL2 books "on request"). Not productizable as-is; a
  DDG/CDG checker on routing tables is the practical reimplementation.

### State of the art 2024–26 (where the interesting work is)

- **Chiplet/2.5D boundary deadlocks**: ReD (TCAD'24), Steered Bubble (TACO'25),
  Preemptive VCs (arXiv 2026), modular routing.
- **Protocol/VN-level deadlock**: ISCA'24 minimum-VN algorithm — **CHI is
  over-provisioned at 4 VNs when 2 suffice**. (A textbook audit target: "is your VN
  allocation provably minimal/deadlock-free?")
- **AI traffic**: NoCArc'24 neuromorphic work shows multicast/bursty deadlocks are
  unsettled even in the literature — the unclaimed niche, and the highest-value play.
- BookSim 2.0 is **dormant-but-reference**: no 2024–26 deadlock paper uses it as
  primary vehicle; **no built-in deadlock detector** (it will run deadlocked happily);
  "BookSim 3"/"bootsim" could not be verified from any primary source.

### Industry: the claims exist, the evidence doesn't

| company | evidence situation |
|---|---|
| Arm CMN-700 | **documented real deadlocks in errata** (SDEN-2039384) — proof the problem is live in shipping silicon |
| Tenstorrent | publishes *mechanisms* (bubble flow control, DAG routing) — auditable, unlike claims |
| NVIDIA / Cerebras | no public deadlock-freedom evidence |
| UCIe | deadlock handling delegated to streamed protocols — audit scope constraint for chiplet clients |
| Arteris | mechanisms described, **no proofs**, app notes gated |

Market precedent: 10xEngineers sells Jasper-based formal NoC verification as a
commercial service (DVCon paper) — deadlock/NoC formal evidence is already paid-for
work. VeritX's differentiation: open-source toolchain + independent-auditor
positioning + the AI-traffic niche + honest evidence-class labeling.

Sources: Verbeek thesis (Radboud 2013); TECS torus paper (10.1145/3762650); ISCA'24
min-VN (users.cs.utah.edu/~vijay/papers/isca24.pdf); NoCFuzzer (TCAD 2025); Arm CMN-700
errata; tenstorrent/tt-metal TT-Fabric tech report; booksim2 repo; 10xEngineers DVCon
submission.

---

## T4 — Formal (SymbiYosys + Yosys + CBMC)

### Verdict

**Pursue — the strongest of the three, with two guards.** The market is proven and
growing; the plan's three deliverables (property playbook, sim-vs-formal coverage
study, bug-injection demo) are exactly what paying customers already buy. Guards:
(1) scope discipline — sell *per-block exhaustive* + *network-level bounded-with-
measured-coverage* evidence; full-NoC liveness proofs are where formal dies on state
explosion, even on commercial tools; (2) fix CI first — Yosys/CBMC were removed from
the Docker image, which is self-inflicted damage to the credibility story (formal-as-a-
service in 2026 runs in CI: lowRISC, LUBIS precedent).

### The market exists (verified)

- **Axiomise** (London; founder ex-Intel/Arm/OneSpin): "multi-million dollar, zero VC,"
  20+ customers, 1600+ engineers trained; launched **nocProve (2 Mar 2026)** — pre-coded
  NoC invariants, "the user does not write properties," verified the open-source
  FlooNoC in <4h by one graduate engineer. **Someone built the T4 playbook as a product.**
- **LUBIS EDA**: "You do not need to write assertions, that is our job"; fixed price per
  block or subscription per engineer-day; runs on their licenses.
- **Synopsys Formal Consulting**: turnkey SVA + proof DB + sign-off reports; 25+ projects
  in 5 years.
- Market shape: EDA services **+19.6% YoY** vs verification-tools category **−2.6%**
  (ESD Alliance EDMD Q4 2025); ~15,000 unfilled formal-engineer positions (2025);
  mid-tier suppliers priced out of $150K–$500K/seat licenses — the open-source wedge.

### Tooling credibility (2026)

- Yosys 0.68 (5 Aug 2026), monthly releases, 310 contributors; SymbiYosys active (9 Jul
  2026); CBMC 6.10.0 + **ETAPS 2025 Test-of-Time Tool Award**.
- **lowRISC (Jan 2026)**: full Ibex correctness proof vs the RISC-V spec with an
  all-open-source flow (Slang→Yosys→rIC3) running in CI, ~900 properties <45 min —
  the credibility ceiling for "open-source formal is enough."
- Caveat: full SVA requires the paid Verific frontend (Tabby CAD Suite); the free flow
  supports an SVA subset — the playbook must target that subset and document proof
  bounds.

### The sim-vs-formal coverage study: publishable, with precedent

Documented methodology with a decade of DVCon canon (Siemens pitfalls paper; Infineon
JasperGold+NCSIM merged-coverage study — literally a master's-thesis PoC, i.e., the
right ambition level; Oracle coverage-driven formal sign-off; CAV 2011 Bjesse et al.).
A 2025 DVCon submission reports 99% formal coverage closure on a 4×4 mesh NoC.
**Verdict: publishable at DVCon level; the open-source-toolchain version is the novelty.**

### The documented wall (scope discipline)

- NoCFuzzer (TCAD 2025): SymbiYosys failed a starvation property on RTL in 24 h —
  state explosion.
- IEEE Access 2022: global deadlock/livelock "can not be verified" beyond active
  windows.
- Even 10xEngineers needed mesh reduction + path decomposition + 50–72 h on Jasper to
  close a 4×4.
- Rule for the services arm: **per-block exhaustive; fabric-level bounded + coverage-
  quantified** (the "Sign-off with Bounded Formal Proofs" DVCon methodology makes this
  defensible). Never take a contract promising full-NoC exhaustive proof — nocProve
  would win that shootout anyway.

Sources: axiomise.com + nocProve launch PR; lubis-eda.com FAQ; Synopsys FCS page; EDMD
Q4 2025 newsletter; YosysHQ GitHub; lowRISC Ibex announcement; DVCon proceedings
(Infineon ProofCore, Siemens pitfalls, Oracle sign-off); NoCFuzzer TCAD'25; IEEE Access
2022.

---

## Cross-track synthesis: what the research changes

| v2 assumption | evidence says | action |
|---|---|---|
| T1 optional "until gem5 build lands" | build is the wrong question — the stack is the wrong vehicle; the QoS-claim audit is the product | Re-scope T1 to Garnet-standalone/trace-driven + on-silicon audit; treat full-system gem5 as sunk cost only if pinned once |
| T2 = BookSim worked audit | simulation-only = fake rigor; freedom needs graph/formal side; AI-traffic deadlock is an unclaimed niche | Reframe to CDG/DDG + falsification with evidence-class labeling; borrow the torus 14-arc corpus |
| T4 = service arm | market proven; nocProve + 10xEngineers raised the bar; coverage study is publishable | Keep, sharpen differentiation (open-source reproducibility, independent auditor), restore CI formal jobs |
| Shared | independent evidence is not sold by anyone; claims outnumber evidence 100:1 across QoS, deadlock, formal | Position every track's output as evidence packages, not results |

**Suggested next step:** one decision meeting on the T2 rigor reframe (it changes what
case study #3 will say), then a T1 re-scope brief (Garnet trace-driven path + the
Wormhole/GroqCloud audit), and restoring the T4 CI cell.

---

## Open questions / gaps

- NOCS 2025/2026 proceedings not verifiable (dblp 404, IEEE paywalled) — paper tables
  skew to ISCA/ASPLOS/ICPP/DVCon/arXiv venues.
- ASTRA-sim 3.0 release status ambiguous (paper exists, README says 2.0) — one email to
  `astrasim-users@googlegroups.com` settles it.
- "BookSim 3"/"bootsim" existence unverified — drop from all materials until confirmed.
- Axiomise nocProve results ("FlooNoC <4h") are vendor claims, not independently
  reproduced.
- No public per-property/per-day prices from Axiomise/LUBIS/Synopsys; adjacent
  blockchain-formal $10K–$100K figures are willingness-to-pay proxies only.
- Free-Yosys SVA subset limits are documented but need a hands-on spike before the
  playbook commits to specific SVA features.
