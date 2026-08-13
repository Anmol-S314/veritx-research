# T3 — Custom / domain-specific NoC design: 2025–2026 landscape probe

**Status:** desk research, 2026-08-09. Question posed for the VeritX business pivot: is "we build custom NoCs for different use cases" a real, defensible business direction in 2026, or does the industry answer domain needs some other way?

**Headline:** Domain-specific *requirements* are real and growing, but the industry does **not** sell bespoke topologies per customer. It sells **configurable NoC generators + domain overlays** (safety, QoS, multicast/collectives, chiplet/optical fabric) from a small set of established players (Arteris, Cadence, Arm, Baya) plus system builders who buy that IP (Tenstorrent, Alphawave→Qualcomm, Eliyan, Ayar). The value has visibly moved **up one tier — package/chiplet/fabric — and sideways into mechanisms**, which corroborates the repo's own T3 finding. "Build custom NoCs per use case" as a standalone service business is **not evidenced in the 2025–2026 record**; the defensible VeritX wedge remains credibility/validation plus mechanism-level expertise at the chiplet tier.

---

## TL;DR / key verdicts

1. **The merchant NoC IP market exists but is small and concentrated.** Only one public pure-play (Arteris): Q2 2026 revenue $24.1M (+46% YoY), ACV+royalties $99.5M, RPO $135M, positive FCF (TradingKey summary of Arteris Q2 2026 release, 2026-08-07). Cadence entered with configurable Janus NoC (2024). Synopsys has **no merchant NoC IP** found in this probe and instead invested in Baya Systems (2025).
2. **Every commercial player sells configurable generators, not bespoke RTL per customer**: Arteris FlexNoC/Ncore + integration-automation software; Cadence Janus ("highly configurable soft IP"); Arm CMN family (incl. automotive variant CMN S3(AE)); Baya WeaveIP. The closest thing to "custom" is *parameterization + automation*.
3. **Domain-specific NoC is real but expressed as overlays on generated fabric**: automotive = safety/resilience (ISO 26262 Resilience Package, sold since 2019; Arm CMN S3(AE); Bosch-led CHASSIS chiplet consortium, Jan 2026); AI = multicast/collectives, QoS, planes (Maia 200; MECS collective NoC, arXiv 2026); chiplet = UCIe 3.0 at 48/64 GT/s (Aug 2025) + die-to-die IP (Blue Cheetah→Tenstorrent) + optical (Ayar's first UCIe optical chiplet, Apr 2025).
4. **The industry direction corroborates the repo's T3 verdict.** On-die topology is commoditized; the 2025–2026 evidence (UCIe 3.0 manageability, optical CPO at $3.75B valuation, MECS collectives, LOKI KV-cache-over-NoC, Microsoft Maia planes) pushes interconnect value to the **fabric/chiplet tier and to mechanisms — not to topology choice**.
5. **Business models are license + royalty** (Arteris 10-K), plus tooling/AI automation, plus custom-silicon co-design (Alphawave, Tenstorrent IP licensing). **No evidence of a pure "custom NoC as a service" market.** Nearest analogs are Tenstorrent's "flexible IP per workload — license now" and Alphawave's custom silicon + chiplets.
6. **VeritX verdict:** "build custom NoCs per use case" is the wrong pitch — it contradicts the repo's own evidence and faces entrenched generator incumbents. The defensible position is **independent interconnect credibility/validation + mechanism-level (multicast/QoS/collectives/safety) expertise at the chiplet tier**, where the 2026 market is actually spending.

---

## 1. The NoC IP market in 2026: players and strategy

| Player | What they sell | Strategy | Source |
|---|---|---|---|
| Arteris (Nasdaq: AIP) | FlexNoC/Ncore NoC IP + SoC Integration Automation software | Configurable NoC generators; "license fee and a royalty business model"; explicitly markets as reducing the risk/cost of "building and maintaining in-house NoC teams" | [Arteris FY2025 10-K (PDF)](https://stocklight.com/stocks/us/nasdaq-aip/arteris/annual-reports/nasdaq-aip-2025-10K-25636059.pdf); [FY2025 10-K summary (MetaTrader)](https://www.metatrader.com/en/symbols/nasdaq/aip/documents/244315-annual-report-fy2025) |
| Cadence | Janus NoC — "new highly configurable soft IP" (July 2024) | EDA incumbent entering NoC IP to ease SoC integration | [SemiEngineering, 2024-07-17](https://semiengineering.com/cadence-janus-noc-system-ip) |
| Arm | CMN coherent mesh family | De-facto standard configurable mesh for Neoverse-class + autonomous/automotive (CMN S3(AE)) | [Arm CMN S3AE product page](https://www.arm.com/products/silicon-ip-system/neoverse-interconnect/cmn-s3ae); [CMN S3(AE) tech ref](https://documentation-service.arm.com/static/67ac4cf66dbc975ccea92cd0) |
| Baya Systems | WeaveIP fabric IP (CHI/ACE5-Lite/AXI5) + WeaverPro | "System-of-chips"; correctness-focused integration; $36M Series B led by Maverick Silicon with **Synopsys strategic investment** + Intel Capital (Jan 2025) | [DCD, 2025-01-23](https://www.datacenterdynamics.com/en/news/chiplet-startup-baya-systems-announces-36m-series-b-funding-round/) |
| Synopsys | No merchant NoC IP found in this probe | Chose to **invest** in Baya rather than build; otherwise focused on interface IP (UCIe, PCIe, SerDes) | same Baya source |
| Tenstorrent (customer) | Buys NoC/fabric IP (Arteris; Baya; die-to-die from Blue Cheetah, then acquired Blue Cheetah) | Builds domain-specific *system* fabric, not generic on-die NoC in-house | [Electronics Specifier, 2024-11-06](https://www.electronicspecifier.com/news/tenstorrent-extends-arteris-noc-ip-to-next-gen-chiplet-ai-solutions/); [HPCwire, 2025-07-03](https://www.hpcwire.com/off-the-wire/tenstorrent-acquires-blue-cheetah-analog-design/) |

**Scale:** Only Arteris is public and pure-play. Q2 2026: revenue $24.1M (+46% YoY from $16.5M), ACV+royalties $99.5M, RPO $135M, positive FCF $8.6M, GAAP loss widened ([TradingKey, 2026-08-07](https://www.tradingkey.com/news/earnings/262086605-tradingkey); [semiiphub pulse of Arteris PR](https://semiiphub.com/pulse/news/arteris-q2-2026-financial-results)). That is roughly a $96M annualized run rate — a real but small market relative to processor/interface IP.

**Honesty note:** No primary market-sizing study was retrieved in this probe. Secondary-market "NoC IP market $X billion" figures appear in vendor/analyst blogs but were not verified against primary sources; treat them as unverified.

**Consolidation is the theme:** Qualcomm agreed to acquire Alphawave Semi at ~$2.4B EV for its high-speed wired connectivity, custom silicon and chiplets ([Qualcomm PR, 2025-06-09](https://investor.qualcomm.com/news-events/press-releases/news-details/2025/Qualcomm-to-Acquire-Alphawave-Semi/default.aspx)). Nvidia agreed to acquire Groq's assets/IP for ~$20B ([CNBC, 2025-12-24](https://www.cnbc.com/2025/12/24/nvidia-buying-ai-chip-startup-groq-for-about-20-billion-biggest-deal.html)). Graphcore was acquired by SoftBank (July 2024, ~$500M) and is now building "Izanagi" for Stargate ([Jon Peddie Research, 2026-06-16](https://www.jonpeddie.com/news/graphcores-ipu-doing-well-at-softbank/)). Esperanto wound down its chip business in 2025, seeking a technology buyer ([EE Times via XPU.pub, 2025-07-05](https://xpu.pub/2025/07/05/esperanto/)). Independent interconnect/compute startups are being absorbed by hyperscaler-scale buyers — a structural point for any new entrant.

## 2. Domain-specific / custom NoC activity by domain

### AI accelerators
- **Tenstorrent** is the clearest "domain-specific fabric" builder that deliberately *buys* NoC IP: licensed Arteris NoC IP for "next-generation chiplet AI solutions" (Nov 2024), uses Baya, and acquired its die-to-die interconnect vendor Blue Cheetah (Jul 2025). Homepage now positions "Flexible IP for Specific Workloads — License now" ([tenstorrent.com](https://tenstorrent.com/), retrieved 2026-08) — i.e., it sells licenses, not bespoke NoC builds.
- **Groq → Nvidia** (~$20B, Dec 2025): inference architecture (including its interconnect/IP) absorbed into Nvidia; Groq remains a separate entity on a non-exclusive license ([CNBC 2025-12-24](https://www.cnbc.com/2025/12/24/nvidia-buying-ai-chip-startup-groq-for-about-20-billion-biggest-deal.html); [Pulse2, 2025-12-27](https://pulse2.com/nvidia-groq-20-billion)).
- **Graphcore/SoftBank**: IPU's 1,472-tile BSP architecture now re-targeted as "Izanagi" for SoftBank's Stargate build-out (Jon Peddie, 2026-06-16) — a continuation of the "every accelerator has a custom on-chip network" pattern, but owned by a hyperscaler project.
- **Cerebras** pulled its IPO and remains private after a fresh private round ([Bitget wiki summary, 2026-07-09](https://www.bitget.com/wiki/cerebras-stock-ipo); low-quality source, low weight).
- **Pattern:** of the 2019–2024 "custom AI NoC" chip startups, most are consolidated (Groq, Graphcore) or exited (Esperanto). Survivors monetize IP licensing. The custom interconnect work lives inside big system teams (Microsoft Maia — see §3), not in merchant custom-NoC vendors.

### Automotive / functional safety
- **Arteris FlexNoC Resilience Package** for ISO 26262 has been productized since at least 2019 (e.g., Semidrive ADAS license) ([Arteris PR, 2019-05-07](https://www.arteris.com/press-releases/semidrive-arteris-ip-flexnoc-adas-iso26262)) — safety is an *overlay feature* on a configurable NoC, not a custom topology.
- **Arm CMN S3(AE)**: "scalable and configurable coherent AMBA5 CHI interconnect… for high-end networking, enterprise compute, and server-class automotive applications" ([Arm docs](https://documentation-service.arm.com/static/67ac4cf66dbc975ccea92cd0)) — the same configurable mesh, automotive-flavored.
- **CHASSIS** (Bosch-led, Jan 2026): 18-member open automotive **chiplet** ecosystem — BMW, Renault/Ampere, Stellantis, Valeo, NXP, Infineon, Arteris, Tenstorrent, Siemens, Fraunhofer, imec, CEA, etc. ([Fraunhofer IIS PR, 2026-01-19](https://www.eas.iis.fraunhofer.de/en/media_press/press_releases/pr_20260119_EN.html)). This is the strongest evidence that automotive interconnect per-domain work is happening at the **chiplet/fabric tier**, in a consortium, not as bespoke on-die NoC RTL.

### Chiplet / die-to-die (the most active 2025–2026 arena)
- **UCIe 3.0** (Aug 2025): 48/64 GT/s, doubling UCIe 2.0's 32 GT/s, plus system-level **manageability** defined in the chiplet stack ([UCIe specs](https://www.uciexpress.org/specifications); [Design & Reuse, 2025-08-05](https://www.design-reuse.com/news/202529142-ucie-consortium-introduces-3-0-specification-with-64-gt-s-performance-and-enhanced-manageability/)).
- **Eliyan** — NuLink PHY + NuGear with UMI (Universal Memory Interface) for die-to-die and die-to-memory; $145M Series C at $1B valuation, Jul 2026 ([DCD, 2026-07-29](https://www.datacenterdynamics.com/en/news/chiplet-interconnect-startup-eliyan-valued-at-1bn-following-145m-series-c-funding-round/)).
- **Ayar Labs** — first UCIe optical interconnect chiplet (Apr 2025), CPO solution (Sep 2025), then a $500M round at $3.75B valuation backed by Nvidia and AMD ([DCD, 2026-07-22](https://www.datacenterdynamics.com/en/news/optical-interconnect-startup-ayar-labs-closes-500m-funding-round-backed-by-nvidia-and-amd/)).
- **Alphawave Semi** — chiplets + high-speed connectivity, being acquired by Qualcomm for data-center expansion ([Qualcomm PR, 2025-06-09](https://investor.qualcomm.com/news-events/press-releases/news-details/2025/Qualcomm-to-Acquire-Alphawave-Semi/default.aspx)).

### Industrial / embedded
- **No good primary evidence found** in this probe of a 2025–2026 domain-specific embedded/industrial NoC product or startup. This space is served by the same configurable generators (Arteris/Cadence/Arm) and SoC integration automation. State explicitly: absence of evidence in this probe, not evidence of absence.

### Open-source NoC
- **Constellation** (UC Berkeley; Jerry Zhao et al.) remains the most prominent open-source NoC RTL generator — irregular SoC-capable, decoupled spec, VC wormhole routing ([IEEE](https://ieeexplore.ieee.org/document/9911299); [NSF PAR](https://par.nsf.gov/servlets/purl/10439921)). It is *generation*, not per-domain specialization.
- **No major 2025–2026 open NoC generator entry surfaced** in this probe (no good evidence found — say so).
- **Automation trend:** ML-driven NoC design-space exploration over BookSim (~150k points; conditional diffusion models) ([arXiv:2512.07877, 2025-11-27](https://arxiv.org/abs/2512.07877)) — "custom" is increasingly done by tools, not human RTL authorship.

## 3. Is "custom per use case" the direction the industry is moving?

Three evidence-backed claims:

**Claim A — Chiplets move the interconnect decision up one tier (package/fabric), where it matters more.** UCIe 3.0's 64 GT/s + manageability ([UCIe](https://www.uciexpress.org/specifications)); Baya's "system-of-chips" framing ([DCD 2025-01-23](https://www.datacenterdynamics.com/en/news/chiplet-startup-baya-systems-announces-36m-series-b-funding-round/)); Ayar's "thousands of GPUs operating as a unified system" via CPO ([DCD 2026-07-22](https://www.datacenterdynamics.com/en/news/optical-interconnect-startup-ayar-labs-closes-500m-funding-round-backed-by-nvidia-and-amd/)); CHASSIS for automotive ([Fraunhofer, 2026-01-19](https://www.eas.iis.fraunhofer.de/en/media_press/press_releases/pr_20260119_EN.html)). This matches the repo's existing NETWORK-HIERARCHY.md claim ("inverts as you climb").

**Claim B — On-die NoC is a configurable commodity, not a differentiator.** Arteris markets itself as removing the risk of "in-house NoC teams" ([10-K](https://stocklight.com/stocks/us/nasdaq-aip/arteris/annual-reports/nasdaq-aip-2025-10K-25636059.pdf)); Cadence's Janus is "highly configurable" ([SemiEngineering 2024-07-17](https://semiengineering.com/cadence-janus-noc-system-ip)); the most AI-forward chip company (Tenstorrent) *buys* on-die NoC IP ([Electronics Specifier 2024-11-06](https://www.electronicspecifier.com/news/tenstorrent-extends-arteris-noc-ip-to-next-gen-chiplet-ai-solutions/)).

**Claim C — Value shifts to mechanisms, not topologies.** Evidence: Microsoft Maia 200's plane/VC/QoS separation (Microsoft blog, 2026-01-30, as recorded in this repo's own [noc-traffic-mix-2026.md](noc-traffic-mix-2026.md)); collective-capable NoC for large-scale ML accelerators ([arXiv:2603.26438, 2026-03-27](https://arxiv.org/abs/2603.26438)); KV-cache-over-NoC design (LOKI, [Semantic Scholar record](https://www.semanticscholar.org/paper/LOKI%3A-An-LLM-Accelerator-with-Optimized-KV-Cache-Harkishanka-Tyagi/504b73eff6c78effabcb739c20b046a63265341e)); UCIe 3.0 manageability; ISO 26262 resilience overlays.

**Verdict:** the direction is real, but it is "domain-tailored **mechanisms** on generated/configurable fabric, at the chiplet tier" — not "custom topology per customer." Nobody in the 2025–2026 primary record sells per-use-case bespoke on-die NoC RTL as a service.

## 4. What the 2025–2026 literature says

- **Corroboration of the repo's finding** (on-die topology is not the transformer-accelerator lever; fabric/chiplet tier + multicast mechanisms are):
  - MECS — collective-capable NoC (barrier sync + high-bandwidth on-chip collectives) for large-scale ML accelerators ([arXiv:2603.26438, 2026-03-27, v2 2026-05-12](https://arxiv.org/abs/2603.26438)); the repo's earlier probe ([noc-traffic-mix-2026.md](noc-traffic-mix-2026.md)) already summarized its ~2.9–3.8× GEMM collectives wins. Mechanisms, not topology.
  - LOKI — NoC-based LLM accelerator built around system-level KV-cache distribution and importance-driven pruning ([Semantic Scholar record](https://www.semanticscholar.org/paper/LOKI%3A-An-LLM-Accelerator-with-Optimized-KV-Cache-Harkishanka-Tyagi/504b73eff6c78effabcb739c20b046a63265341e)). Memory-system and data-movement levers, not a topology claim.
  - WaferLLM (OSDI 2025) and Microsoft Maia 200 (Jan 2026) — both already cited in the repo's own T3 and traffic-mix docs; both reinforce wiring-cost/plane-based reasoning.
  - The chiplet/fabric tier dominates the commercial record (§2, §3).
- **Contradiction:** none found in this probe — no 2025–2026 paper was retrieved arguing that on-die mesh *topology* is the binding constraint for transformer accelerators, or that per-use-case bespoke on-die topologies beat configurable generators at scale.
- **Automation/generation literature:** AI-driven NoC DSE with 150k BookSim samples ([arXiv:2512.07877, 2025-11-27](https://arxiv.org/abs/2512.07877)); open-source irregular-NoC generation (Constellation) — the literature's "customization" is about parameterized generation, consistent with the commercial record.
- **Honesty note:** this probe was web-search-based; the NOCS 2025 program was not accessible/verifiable in this session. Absence of contradiction is not proof of absence — but the strongest negative evidence (nobody shipping bespoke topology per customer) is corroborated by both the market and the literature probes.

## 5. Business models and monetization

- **License fee + royalty** — explicit in Arteris's own 10-K ([10-K](https://stocklight.com/stocks/us/nasdaq-aip/arteris/annual-reports/nasdaq-aip-2025-10K-25636059.pdf)); the "ACV + royalties" metric ($99.5M in Q2 2026) shows royalties are material ([TradingKey 2026-08-07](https://www.tradingkey.com/news/earnings/262086605-tradingkey)).
- **Tool/software subscriptions** — Arteris bundles NoC IP with SoC Integration Automation software ([10-K](https://stocklight.com/stocks/us/nasdaq-aip/arteris/annual-reports/nasdaq-aip-2025-10K-25636059.pdf)); Cadence monetizes Janus within its IP/tools portfolio ([SemiEngineering 2024-07-17](https://semiengineering.com/cadence-janus-noc-system-ip)); ML-driven DSE ([arXiv 2512.07877](https://arxiv.org/abs/2512.07877)) points toward automation-as-product.
- **Custom silicon + IP co-design** — Alphawave's stated businesses: IP, custom silicon, connectivity products, chiplets ([Qualcomm PR 2025-06-09](https://investor.qualcomm.com/news-events/press-releases/news-details/2025/Qualcomm-to-Acquire-Alphawave-Semi/default.aspx)); Tenstorrent sells products *and* licenses IP ("Flexible IP for Specific Workloads — License now", [tenstorrent.com](https://tenstorrent.com/)).
- **"Custom NoC as a service"** — **no pure-play evidence found.** Nearest analogs are Tenstorrent-style licensable IP and Alphawave-style custom silicon. A VeritX "we build you a custom NoC" service would be *creating* a category, not *entering* one — and would compete against free/cheap configurable generators.
- **Moat analysis:** incumbents' moats are silicon-proven track records, standards compliance (AMBA CHI/AXI, UCIe), safety certification (ISO 26262 — sold since 2019), tooling and now AI-driven automation. Baya's positioning ("correct by construction"-style integration, WeaveIP across CHI/ACE5-Lite/AXI5, backed by Synopsys/Intel) shows the market sells **correctness and integration speed**, not topology novelty ([DCD 2025-01-23](https://www.datacenterdynamics.com/en/news/chiplet-startup-baya-systems-announces-36m-series-b-funding-round/)). The one thing no incumbent sells is **independent validation of interconnect claims** — the space VeritX's validation-services.md already occupies.

## Implications for VeritX

### (a) What is defensible
- **Interconnect credibility / validation services** — more defensible in 2026 than "custom NoC construction," because the market is full of unverifiable performance claims (AI chip startups, chiplet startups, IP vendors) and consolidation means buyers need independent due diligence. No incumbent sells this.
- **Mechanism-level expertise at the chiplet/fabric tier** — multicast/collectives, QoS, plane/VC separation, KV-cache data movement, safety overlays — packaged as audits, design guidance, or narrow licensable IP. This is where the 2025–2026 record shows value and funding (UCIe 3.0, Ayar, Eliyan, MECS, LOKI, CHASSIS).
- Domain-translation consulting (e.g., automotive safety requirements → fabric mechanisms) is plausible, but must compete with FlexNoC Resilience and CMN S3(AE) bundling.

### (b) What our own findings say
- T3's conclusion — on-die topology is not the lever for transformer accelerators; the levers are memory bandwidth/capacity, mapping, and multicast of shared K/V ([CONCLUSION.md](../CONCLUSION.md)) — is **corroborated, not contradicted**, by every 2025–2026 source in this probe. The traffic-mix probe already concluded mixed traffic is answered by plane/VC/QoS separation on the same mesh ([noc-traffic-mix-2026.md](noc-traffic-mix-2026.md)).
- Pivoting to "we build custom NoCs per use case" would **contradict the repo's own evidence**: the industry answer to domain needs is configurable generators + domain mechanisms, and the value is above the die. If VeritX builds custom *meshes*, it competes with free tools and entrenched IP for a problem its own research says is second-order.
- The honest pivot, if any: custom **mechanisms** (multicast/collectives, QoS, memory semantics) at the chiplet/fabric tier + validation of others' claims — not custom topologies.

### (c) Risks
1. **Commoditization:** FlexNoC/Janus/CMN/WeaveIP + ML-driven DSE cover most "custom" requests; a custom-RTL service competes on cost against parameterized IP.
2. **Consolidation:** 2025–2026 absorbed Groq, Graphcore, Esperanto, Alphawave, Blue Cheetah; standalone interconnect startups survive only with strategic backing (Baya: Synopsys/Intel; Eliyan/Ayar: hyperscaler-class investors). A small lab entering as a merchant is structurally late.
3. **Safety certification is a multi-year moat** (ISO 26262 resilience sold since 2019; CHASSIS is consortium-paced).
4. **Validation-market risk:** credibility services are unproven as a paid category; first-customer problem remains unsolved.
5. **Standards risk:** UCIe 3.0 control (spec, PHY, compliance) sits with incumbents; VeritX has no package/PHY assets — it can consult on fabric-tier mechanisms but cannot own the standard.

## Scope & limitations
- Web-accessible primary sources (company sites, press releases, arXiv, standards bodies, SEC filings summaries) retrieved 2026-08; dates as published.
- Public financials only exist for Arteris; other market-size claims in secondary reports were not verified and are excluded.
- NOCS 2025 program/DBLP was not accessible in this session; academic coverage is arXiv-anchored.
- "No evidence found" statements are explicit and reflect probe coverage, not proof of absence.

## Sources (primary where possible)
- Arteris FY2025 10-K: https://stocklight.com/stocks/us/nasdaq-aip/arteris/annual-reports/nasdaq-aip-2025-10K-25636059.pdf ; summary: https://www.metatrader.com/en/symbols/nasdaq/aip/documents/244315-annual-report-fy2025
- Arteris Q2 2026 results (press release summary): https://semiiphub.com/pulse/news/arteris-q2-2026-financial-results ; https://www.tradingkey.com/news/earnings/262086605-tradingkey (2026-08-07)
- Cadence Janus NoC: https://semiengineering.com/cadence-janus-noc-system-ip (2024-07-17)
- Arm CMN S3(AE): https://www.arm.com/products/silicon-ip-system/neoverse-interconnect/cmn-s3ae ; https://documentation-service.arm.com/static/67ac4cf66dbc975ccea92cd0
- Baya Systems Series B: https://www.datacenterdynamics.com/en/news/chiplet-startup-baya-systems-announces-36m-series-b-funding-round/ (2025-01-23)
- Tenstorrent×Arteris: https://www.electronicspecifier.com/news/tenstorrent-extends-arteris-noc-ip-to-next-gen-chiplet-ai-solutions/ (2024-11-06); Blue Cheetah: https://www.hpcwire.com/off-the-wire/tenstorrent-acquires-blue-cheetah-analog-design/ (2025-07-03); https://tenstorrent.com/
- Qualcomm×Alphawave: https://investor.qualcomm.com/news-events/press-releases/news-details/2025/Qualcomm-to-Acquire-Alphawave-Semi/default.aspx (2025-06-09)
- Nvidia×Groq: https://www.cnbc.com/2025/12/24/nvidia-buying-ai-chip-startup-groq-for-about-20-billion-biggest-deal.html (2025-12-24); https://pulse2.com/nvidia-groq-20-billion (2025-12-27)
- Graphcore/SoftBank: https://www.jonpeddie.com/news/graphcores-ipu-doing-well-at-softbank/ (2026-06-16); Esperanto exit: https://xpu.pub/2025/07/05/esperanto/ (2025-07-05)
- UCIe: https://www.uciexpress.org/specifications ; https://www.design-reuse.com/news/202529142-ucie-consortium-introduces-3-0-specification-with-64-gt-s-performance-and-enhanced-manageability/ (2025-08-05)
- Eliyan: https://www.datacenterdynamics.com/en/news/chiplet-interconnect-startup-eliyan-valued-at-1bn-following-145m-series-c-funding-round/ (2026-07-29)
- Ayar Labs: https://www.datacenterdynamics.com/en/news/optical-interconnect-startup-ayar-labs-closes-500m-funding-round-backed-by-nvidia-and-amd/ (2026-07-22)
- CHASSIS: https://www.eas.iis.fraunhofer.de/en/media_press/press_releases/pr_20260119_EN.html (2026-01-19)
- Arteris FlexNoC Resilience (ISO 26262): https://www.arteris.com/press-releases/semidrive-arteris-ip-flexnoc-adas-iso26262 (2019-05-07)
- MECS collective NoC: https://arxiv.org/abs/2603.26438 (2026-03-27, v2 2026-05-12); LOKI: https://www.semanticscholar.org/paper/LOKI%3A-An-LLM-Accelerator-with-Optimized-KV-Cache-Harkishanka-Tyagi/504b73eff6c78effabcb739c20b046a63265341e
- ML-driven NoC DSE: https://arxiv.org/abs/2512.07877 (2025-11-27); Constellation: https://ieeexplore.ieee.org/document/9911299 ; https://par.nsf.gov/servlets/purl/10439921
- Repo context: docs/business/validation-services.md; tracks/t3-topology/CONCLUSION.md; tracks/t3-topology/NETWORK-HIERARCHY.md; research/noc-traffic-mix-2026.md
