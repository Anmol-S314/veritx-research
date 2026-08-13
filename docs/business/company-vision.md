# VeritX — Company Vision: The NoC company that proves its numbers

**Status: draft v1 (2026-08-10).** Long-term vision for VeritX as a real company with
senior engineering staff, not a BTech programme. This document supersedes the
programme-scoped framing (`programme-v2.md`, `validation-services.md`) as the
*strategic* north star: those documents describe what the lab ships in the next six
months; this one describes what the company is in ten years. The two are compatible:
the programme is the seed capital of talent and methodology that grows into this
company.

---

## 1. The company in one sentence

> **VeritX builds the interconnect that comes with its proof.** We design and license
> NoC and chiplet-fabric IP — on-die, die-to-die, and across the package — where every
> shipped claim (latency, bandwidth, QoS, safety) is backed by a measurement chain:
> co-sim against a reference model, formal properties, and counters from real silicon.
> Our products ship with evidence; our competitors' ship with marketing.

The market doesn't need another NoC generator. It needs someone who will tell the
truth about interconnect performance — and the 2026 record says the way to do that at
scale is to *own the fabric*: measure it, prove it, and license it with the proof
attached.

## 2. Why this, why now (the evidence, 2026)

| fact (sourced in `research/custom-noc-landscape-2026.md`) | what it means |
|---|---|
| On-die NoC is a configurable commodity (Arteris FlexNoC, Cadence Janus, Arm CMN, Baya WeaveIP); even Tenstorrent buys on-die NoC IP | we do NOT compete on generic on-die topology — that game is over and won |
| Value and funding moved up one tier: UCIe 3.0 (64 GT/s, 2025), Eliyan at $1B, Ayar optical at $3.75B, Bosch-led CHASSIS automotive chiplets | the chiplet/fabric tier is where interconnect decisions and money are moving — the incumbent (FlexNoC) is an on-die company |
| The 2025–26 literature (MECS collectives, LOKI KV-over-NoC, Maia planes) corroborates our own findings: the lever is *mechanisms* (multicast, QoS, plane/VC separation) and data movement, not topology | our plane-separation law and multicast analysis are the right things to own — as mechanisms, not as "AI-native IP" hype |
| Every independent interconnect startup got absorbed (Groq→Nvidia, Alphawave→Qualcomm, Graphcore→SoftBank, Esperanto dead, Blue Cheetah→Tenstorrent) | standalone interconnect companies survive only with a differentiated position and strategic backing — we must be bought-for-capability, not bought-out-for-cheap |
| Nobody sells independent interconnect truth | the "verified" category does not exist; the company that owns it owns the story |

## 3. The product family (ten-year arc)

Three products, one platform underneath. The platform — our measurement toolchain
(BookSim-faithful co-sim, RTL, formal properties, FPGA counters) — is the moat; the
products are how it earns.

### Product 1 — VeritX Core (on-die NoC IP). Years 0–3.

What we already have as a seed: a parameterized mesh/fabric in RTL (1–4 VCs, iSLIP,
credit flow control) cycle-exact co-simulated against BookSim, with formal properties
(P1–P8) and an FPGA leg planned.

What it becomes: a licensed NoC IP product for AI-accelerator and compute SoC teams,
differentiated by **mechanisms we can prove**: plane/VC separation (the burstiness law:
control starves 6.68× at 1 VC, ~1.24× with the right plane configuration), multicast
and collectives, QoS under mixed traffic.

Every release ships a **VeritX Verified evidence package**: the burst curve reproduced
cell-for-cell in RTL co-sim, FPGA counter dumps, the formal property list with method
stated. Buyers (and their Series-A investors) get a headline number plus the chain
that proves it.

### Product 2 — VeritX Fabric (chiplet/die-to-die interconnect). Years 2–5.

The tier where the market is actually spending. UCIe-compliant fabric, die-to-die KV
multicast, package-level coherence, optical-ready interfaces. Our fabric law (D(G):
degree-8 crossover ~2026–27, the hop law at the chiplet boundary) becomes the design
framework for how many dies, how they talk, and where multicast forks live.

This is where we beat the incumbents, because FlexNoC is an on-die company and the
chiplet tier is still being defined (UCIe 3.0, CHASSIS, Ayar/Eliyan ecosystems). We
enter with the same proof discipline.

### Product 3 — VeritX Verify (the toolchain + certification). Years 1–10.

The measurement platform as a product: trace-driven co-sim harness, calibration
audits, and the **VeritX Verified mark** — for our own IP first, then as a paid
service for third-party interconnect claims (the validation-services business, now
positioned as the toolchain we monetize, not the company's reason for being).

The mark is the compounding asset: every chip that carries it carries our brand, and
the mark's credibility is what keeps FlexNoC and friends out of this game — they would
have to audit themselves.

## 4. Why we win (honest competitive analysis)

| incumbent | their position | our position |
|---|---|---|
| Arteris FlexNoC | 20-year on-die generator, integration automation, ISO 26262 | we don't fight for the generic-SoC license; we win where mechanisms + proof matter: AI fabric, chiplet tier, and any buyer whose claims must survive diligence |
| Cadence Janus | configurable IP in an EDA portfolio | EDA vendors sell tools; nobody at Cadence signs their name to your performance number |
| Arm CMN | de-facto standard mesh for Neoverse | serving a standard is not serving proof; and CMN doesn't reach the chiplet tier we're aiming at |
| Baya WeaveIP | correctness-focused integration, backed by Synopsys/Intel | integration correctness is table stakes for us, too — the differentiator is *measured performance*, which Baya does not sell |
| Open-source (Constellation, BookSim+) | free | free is the floor, not the product; we sell the proof and the silicon record the free tools can't produce |

The moat, stated plainly: **measurement chain + silicon record + certified claims.**
No one else has all three. It takes years to build (which is why it's worth building),
and it compounds: each FPGA run and each formal proof makes the next product faster to
certify.

## 5. What we are not (and never say in a pitch)

1. **Not a cheaper FlexNoC.** We do not compete on price or on generic on-die
   topology. That game is over; our own research says so.
2. **Not "AI-native NoC IP."** The phrase is dead in this repo for a reason
   (PITFALLS §18, CONCLUSION.md). We sell mechanisms backed by measured law, not
   claims of architectural novelty.
3. **Not a consultancy.** Services exist to fund and validate the platform, not to be
   the business. The business is product: IP licenses and royalties (the Arteris
   model) plus the Verified mark (which Arteris doesn't have).
4. **Not an ASIL-B certification body.** Automotive safety certification is a
   multi-year process (T4's honest verdict). We build safety mechanisms into the
   fabric and let the certification market do what it does — our product is
   certifiable, we don't sell the certificate.

## 6. The company shape (senior team, 10 years)

| function | what they do | when |
|---|---|---|
| Architecture (interconnect systems) | workload analysis, the laws (plane separation, D(G), multicast), requirements → mechanisms | day 1 |
| RTL design (senior) | Core, then Fabric; parameterized, formally-minded, review-disciplined | day 1 (seed exists) |
| Verification/formal | co-sim harness, P1–P8-style properties, UVM collateral, the evidence package | day 1 |
| FPGA/silicon bring-up | counters, board bring-up, silicon record | year 1 |
| Software/tooling | the generator, the trace pipeline, the Verified dashboard | year 1–2 |
| Applications engineering | customer workload bring-up, traffic capture, the "give us your trace" front end | year 2 |
| Safety engineering (ISO 26262) | mechanisms + documentation for automotive | year 3–4 |
| Business development / sales | design wins, VC/ODM diligence, licensing | year 1–2 |

The BTech programme feeds this org in two ways: it is the R&D lab that produces the
methodology and case studies, and it is the recruiting pipeline — students who pass
through the gates graduate into the company with the discipline already installed.
The programme is the farm team; the company is the majors.

## 7. Ten-year milestones (exit criteria, not vibes)

| year | milestone | gate |
|---|---|---|
| 0–1 | VeritX Core RTL complete: Gate R1 (burst table cell-for-cell), Gate R4 (formal P1–P8), Gate R2/R3 (FPGA) | all four RTL-ARC gates pass, published |
| 1–2 | First design wins: 2–3 AI-accelerator customers at cost, "VeritX Verified" evidence package as the deliverable; FPGA silicon record public | customers' Series-A data carries our mark |
| 2–3 | Core licensed for revenue; Verify toolchain opens to third-party audits | first royalty-bearing license |
| 3–5 | VeritX Fabric: chiplet-tier product, UCIe-aligned, first multi-die customer | fabric law (D(G)) demonstrated on silicon at the package tier |
| 5–10 | The Verified mark is a standard buyers ask for; VeritX is the interconnect company that survived the consolidation wave | acquisitions/strategic partnerships happen on our terms, or we are the platform others build on |

## 8. Risks, stated plainly

1. **Capital.** Silicon IP is capital-hungry and slow; the first design wins must fund
   the growth or a strategic partner must back us early. The services revenue is the
   bridge, not the destination.
2. **Consolidation.** 2025–26 absorbed every independent interconnect startup. Our
   mitigation is differentiation (proof) plus a deliberate early-strategic-partner
   path — better to be bought for capability at a premium than to be irrelevant.
3. **Category risk.** The "verified interconnect" category doesn't exist yet. We must
   create it with the first few design wins — same play the audit plan envisioned,
   now in service of a product company.
4. **Certification moats.** Automotive safety is a multi-year grind. We enter
   automotive through mechanisms and measurement, not certification claims.
5. **The honesty risk, internalized.** We are the company whose pitch is "trust our
   numbers." One rushed product claim ends the company. The gate discipline is
   company policy, not a student exercise: every shipped number runs through the same
   gates the lab holds itself to, and PITFALLS is required reading for every engineer.

## 9. What happens next (this quarter)

1. The RTL leg finishes its current phase (Gate R1 — the burst table reproduces in
   RTL co-sim). That is the first *product* artifact, not just a research artifact.
2. The FPGA leg closes (Gates R2/R3) — the silicon record that the whole "Verified"
   story rests on.
3. The Verify toolchain gets productized in parallel with the audits already planned.
4. The company document set gets reconciled: `validation-services.md` becomes "the
   services arm of a product company," not the business plan.

The six-month programme builds the seed. This document is the tree.
