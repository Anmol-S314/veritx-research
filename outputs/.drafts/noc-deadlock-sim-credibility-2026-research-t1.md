# T1 Research Brief — NoC Deadlock Analysis & Formal Deadlock-Freedom Verification (2025–2026)

**Date:** 2026-08-14
**Scope:** Calendar 2026 primary, 2025 for context; older work only as one-line grounding.
**Method constraints honored:** No PDF bodies parsed (no `alpha get`/raw `.pdf` fetches). All claims sourced from arXiv abs/HTML pages, conference landing pages, index/venue pages, and web snippets. Where only a PDF URL exists, it is cited from search metadata with full-text parsing marked `blocked`.
**Project thread this feeds:** 2D-mesh RTL NoC vs BookSim where routing divergence between Dijkstra/table-based routing and dimension-order routing (DOR) produced a cross-die hang (channel-dependency cycle); multi-die bridge topology with a single VC.

---

## Q1 — Deadlock-freedom of deterministic routing (DOR/XY), table-based routing, and VC allocation (2025–2026)

**Finding 1.1 (2026).** DOR (XY/YX) on a 2D mesh is treated in 2026 literature as the reference deadlock-free scheme whose guarantees you give up when you deviate from it. Q-StaR (arXiv:2603.10637, Mar 2026) opens from the premise that DOR is "widely adopted for its favorable properties like low hardware cost, in-order transmission, and guaranteed deadlock freedom," and proposes BiDOR (a bidirectional DOR variant) + an N-Rank load-trend metric to rebalance load while "retaining simplicity and predictability" [2]. Direct relevance: it is a 2026 example of *relaxing* DOR while keeping its deadlock-free skeleton — the same class of decision the project thread faces when mixing Dijkstra/table routes with DOR.

**Finding 1.2 (2026).** Deadlock-freedom in multi-die / chiplet-bridge topologies is an active 2026 topic. HPCA 2026 (Feb 2, 2026 session "Cache Coherence and Chiplet Interconnects") includes "Deadlock-Free Bridge Module for Inter-Chiplet Communication in Open Chiplet Ecosystem" (Chen, Fu, Wang, Zhou; NUDT): inter-chiplet deadlock arises when integrating chiplets onto an interposer; prior fixes (turn restrictions, VC isolation, injection control, escape channels, bubble flow control) require knowledge of each chiplet's internal NoC; their DFBM instead infers inter-chiplet packet transmission behavior from coherence-protocol flow dependencies and uses packet-injection control to isolate inter- vs intra-chiplet traffic, at ~2.5% area overhead [3]. Direct relevance: this is the closest 2026 analog to the project's "multi-die bridge with a single VC" scenario, and it argues that single-VC bridge deadlock is a recognized failure mode that is normally solved by isolation/injection control rather than extra VCs.

**Finding 1.3 (2026).** VC allocation is being revisited specifically to *avoid* multiplane link duplication while keeping AXI4 traffic-class separation deadlock-free. "Physically-Aware Preemptive Virtual Channels for Deadlock-Free AXI Networks-on-Chip" (Leone, Colagrande, Benini — PULP; arXiv:2607.01430, Jul 1 2026) evaluates four deadlock-free AXI4 traffic-class separation schemes (one multiplane baseline + three VC designs) and proposes Preemptive VCs that "save up to 76% of link resources with comparable frequency and only 3% router area overhead" versus multiplane. Key premise quoted: "In AXI4 systems, protocol-level dependencies between read and write traffic can create circular waits at the network endpoints, even when the routing algorithm itself is deadlock-free" [1]. This is the clearest 2026 statement that *protocol-level* (not just routing-level) dependency cycles are the live problem in real NoC fabrics.

**Finding 1.4 (2025).** VC-less deadlock freedom via link ordering / embedded subnetworks: "Deadlock-free routing for Full-mesh networks without using Virtual Channels" (TERA; HOTI 2025, arXiv:2510.14730, Oct 16 2025). TERA "employs an embedded physical subnetwork to provide deadlock-free non-minimal paths without using VCs," beating link-ordering routing by 80% on adversarial traffic and cutting buffer requirements 50% vs VC-based approaches [7]. Direct relevance: demonstrates that single-VC/low-VC designs can be made deadlock-free through routing structure (embedded acyclic subnetwork) rather than VC count — an option for the project's single-VC bridge.

**Finding 1.5 (2025).** Table-based / lookup routing + deadlock is addressed explicitly in the AI-datacenter context by UB-Mesh (Liao et al., arXiv:2503.20377, Mar 26 2025): its All-Path Routing (APR) "combines Source Routing, Structured Addressing & Linear Table Lookup and Deadlock-Free Flow Control mechanisms to enable adaptive routing, minimize forwarding overhead and avoid deadlock" [11]. Caveat: this is a datacenter-scale AI network (NPU interconnect), not a NoC; it is evidence that linear-table-lookup routing needs an explicit deadlock-free flow-control mechanism bolted on — table routing alone does not give deadlock freedom, unlike DOR. *(Snippet-level; full text not parsed — see coverage.)*

**Finding 1.6 (2025, journal).** Deterministic–adaptive hybrid routing: "A Deadlock-Free Deterministic–Adaptive Hybrid Routing Algorithm for Efficient Network-on-Chip Communication" (Ji & Yang, Xidian; *Electronics* 14(5):845, published Feb 21 2025) claims a deterministic–adaptive hybrid (DAHR) that "leverages pre-fetched deterministic information and real-time congestion" while ensuring deadlock-free operation [12]. *(Abstract-level only.)*

**Finding 1.7 (2025).** Torus (mesh with wraparound) deadlock-free routing construction formalized: Das, Das, Karfa, "Developing Deadlock-Free Routing Algorithms in Torus NoC: A Formal Approach" (ACM TECS 24(5s), 2025; also CODES+ISSS 2025) — "very few deadlock-free routing algorithms for torus-based NoC exist that do not have significant implementation [costs]" and the paper gives a formal approach to constructing them [6]. This is the 2025 formal-treatment exemplar for mesh-family topologies with cyclic channels.

**Finding 1.8.** No 2025–2026 work found specifically analyzing *Dijkstra/shortest-path table-based routing* inside a NoC (as opposed to datacenter networks or HPC fabrics). Nearest matches are Q-StaR (static-route load imbalance vs DOR [2]) and UB-Mesh (linear table lookup + deadlock-free flow control [11]). The gap is itself a finding: per-destination table routing's deadlock freedom is not treated as a given in 2025–2026 NoC literature; the only guaranteed-deadlock-free baselines named are DOR and turn-restricted/VC-structured schemes [2][3][7].

---

## Q2 — Automated deadlock detection: CDG analysis, SAT/SMT, model checking, routing-table analysis (2025–2026)

**Finding 2.1 (2026, industrial formal).** DVCon US 2026 session [58]: "Scaling Formal Verification of Network On Chip Using Path Decomposition" (Ahmed, Yaqoob, Zafar — 10xEngineers; Din — LUMS) — abstract states simulation "struggle[s] to handle the distributed, parallel, and reactive behavior of modern NoC architectures... limiting coverage and confidence in detecting critical behaviors such as deadlock, livelock, and starvation," and presents a scalable path-decomposition methodology to prove deadlock/livelock freedom in complex mesh architectures [8]. PDF only; body `blocked`.

**Finding 2.2 (2025, industrial formal).** DVCon US 2025: "Hierarchical Formal Verification and Progress Checking of Network-On-Chip Design" (Roy, Yeung, Hong, Desai, Raj, Agarwal, Patel) — formal testbenches with "guaranteed data delivery and forward progress checking" at top level, drilling into undetermined blocks (e.g., routers); deadlock/end-to-end formal checks noted as difficult due to tool capacity [9]. PDF only; body `blocked`.

**Finding 2.3 (2025, academic CDG construction).** The TECS 2025 torus paper (Finding 1.7) is the 2025 academic exemplar of constructing and proving deadlock freedom from channel-dependency reasoning for cyclic mesh-family topologies [6]. *(Abstract-level.)*

**Finding 2.4 (2025, theory — existence of deadlock-free routing).** "Existence of Deadlock-Free Routing for Arbitrary Networks" (Mendlovic, arXiv:2503.04583, Mar 6 2025, math category) proves a necessary-and-sufficient graph condition for the existence of a deadlock-free message routing: the directed graph must contain two edge-disjoint directed trees rooted at the same node, one into the root and one away. Authors note it is "not directly applicable to the construction of deadlock-free routing schemes" but provides insight "that may lead to the development of improved tools for designing and verifying such schemes" [4]. Relevant as the 2025 theoretical characterization underlying "can this topology/routing be deadlock-free at all."

**Finding 2.5 (2026, complexity, tangential).** "Complexity of Perfect and Ideal Resilience Verification in Fast Re-Route Networks" (Bentert et al., arXiv:2601.03934, Jan 7 2026): checking whether a given set of *static routing/rerouting rules* ensures resilience is coNP-complete (with linear-time special cases) [17]. Domain is datacenter fast re-routing, not NoC; included because it is the closest 2026 result on the *verification complexity of static routing-rule sets* and supports the general point that static routing-rule analysis is algorithmically hard.

**Finding 2.6 — explicitly searched, not found.** No 2025–2026 paper found that applies SAT/SMT solvers (Z3 etc.) or nuSMV/Spin-style model checking specifically to NoC deadlock/CDG cycle detection. Existing results in that space are older (context only): ILP-based deadlock-free routing construction (IEEE 10387838, 2023 [cited via metadata, `blocked`]); EbDa CDG-based design/verification theory (Ebrahimi & Daneshtalab, ISCA 2017, pp. 703–715, ACM 10.1145/3079856.3080253); GeNoC-style theorem-proving for NoCs (ACM TODAES 17(2), 2012, 10.1145/2071356.2071357). **No 2025–2026 SAT/SMT/model-checking paper found for NoC deadlock** — valid finding per brief.

**Finding 2.7 (2025, adjacent, HPC fabric).** "Leveraging InfiniBand Controller to Configure Deadlock-Free Routing Engines for Dragonflies" (arXiv:2502.01214, Feb 3 2025) — configuring deadlock-free routing in InfiniBand-based Dragonflies; off-chip/HPC domain, included as adjacent 2025 work on *automated configuration of deadlock-free routing* [18]. *(Abstract-level.)*

---

## Q3 — Bufferless and deflection routing deadlock results (2025–2026)

**Finding 3.1 (2025).** "A protocol to reduce worst-case latency in deflection-based on-chip networks" (Indrusiak group, York; arXiv:2510.11361, Oct 13 2025): protocol "enforces the deflection of the header of a packet but not its payload," cutting network traffic and worst-case packet latency via reduced pre-injection latency [13]. Note: abstract frames the problem as latency/worst-case behavior, not deadlock per se; deadlock/livelock claims not confirmed from abstract. *(Full author list not captured; corresponding author Leandro Soares Indrusiak per search metadata.)*

**Finding 3.2 (2025).** "Toward Predictable Deflection Routing in Routerless NoCs for Real-Time Systems" (Sayuti & Soares Indrusiak, IEEE MCSoC 2025, Dec 15–18 2025, DOI 10.1109/MCSoC67473.2025.00054): bounds worst-case deflections of communication flows in routerless NoCs via evolutionary optimization; result: selective per-flow deflection increase "outperformed" uniform increase with statistically significant improvement in maximum deflection [14]. Again a *timing/predictability* result, not a deadlock proof — consistent with the literature pattern that bufferless/deflection systems trade deadlock for livelock/worst-case-latency concerns.

**Finding 3.3 — searched, mostly older.** Searches for "bufferless NoC deadlock 2025/2026" surface pre-2025 bufferless/deflection work (BLESS 2010/2012, CHIPPER HPCA 2011, MinBD NOCS 2012, scheduled deflection NOCS 2020, IPDeN 2.0 RTNS 2023) rather than new deadlock results. **No 2025–2026 deadlock-freedom result specific to bufferless NoCs found**; the two 2025 items above (3.1, 3.2) are the only in-window deflection-routing results surfaced, and neither centers on deadlock.

---

## Q4 — Deadlock in AI-accelerator NoCs / wafer-scale / chiplet interconnects (2025–2026)

**Finding 4.1 (2026).** TONS, "Throughput-Optimized Networks at Scale" (Green et al., arXiv:2605.27963, May 27 2026; Google TPU v4/5p use case): introduces "a deadlock-free routing scheme compatible with limited virtual channels and optical switch faults," enabling synthesized topologies to realize 2.1x/1.6x geometric-mean speedups (uniform random / all-to-all) over the best TPU torus variants [10]. This is the clearest 2026 statement that AI-accelerator (TPU-class) networks must co-design topology + routing with a limited-VC deadlock-free scheme.

**Finding 4.2 (2026).** Wafer-scale: "Network Design for Wafer-Scale Systems with Wafer-on-Wafer Hybrid Bonding" (Iff et al., arXiv:2603.05266, Mar 5 2026) — reticle placement shapes the 2D mesh-like network; four placements improve throughput up to 250%, latency −36%, energy −38% [19]. No explicit deadlock claim in the abstract (assumes wormhole + credit flow control); adjacent context for wafer-scale routing topology. *(Abstract-level.)*

**Finding 4.3 (2026).** "Shiftfly: Scaling the Accelerator Interconnect Past the Pod with a Shift-Routed Optical Tier" (Krause et al., arXiv:2608.00897, Aug 1 2026) — TPU 8i/Boardfly background; Shiftfly replaces the global complete-graph tier with a Kautz digraph, "routes without tables by a shift register"; explicit deadlock-freedom is not a stated contribution in the abstract [20]. *(Abstract-level; include as adjacent AI-interconnect routing work, no deadlock claim.)*

**Finding 4.4 (2026).** Chiplet bridge deadlock — HPCA 2026 DFBM (Finding 1.2) is squarely Q1+Q4: inter-chiplet deadlock resolved at a bridge without touching chiplet-internal NoCs [3].

**Finding 4.5 (2025).** UB-Mesh APR (Finding 1.5) again: AI-scale network where table-lookup routing is paired with explicit deadlock-free flow control [11].

**Finding 4.6 — context (2024, out of window).** "ReD: A Reliable and Deadlock-Free Routing for 2.5-D Chiplet-Based Interposer Networks" (Taheri, Pasricha, Nikdast; IEEE TCAD 43(12):4599–4612, Dec 2024) [21]; and DeFT, "A Deadlock-Free and Fault-Tolerant Routing Algorithm for 2.5D Chiplet Networks" (arXiv:2112.09234, Dec 2021) [22] — the 2021/2024 chiplet-interposer deadlock-free routing lines that the 2026 DFBM work builds on/competes with.

---

## Q5 — Classic grounding: Dally & Seitz channel-dependency theory (context only)

**Finding 5.1.** Dally & Seitz, "Deadlock-Free Message Routing in Multiprocessor Interconnection Networks," *IEEE Trans. Computers* C-36(5):547–553, May 1987. Abstract (via IEEE/OSTI metadata): "A deadlock-free routing algorithm can be generated for arbitrary interconnection networks using the concept of virtual channels. A necessary and sufficient condition for deadlock-free routing is the absence of cycles in the channel dependency graph" [15]. Per the brief, the 1987 body was not read; cited from metadata only.

**Finding 5.2 — recent papers still build on it.** 2025–2026 sources that explicitly anchor to the CDG theory: (a) the TECS 2025 torus formal approach is framed as solving Dally-theory's scalability limit ("finding such acyclic graph has been very challenging, which limits Dally's theory to networks with a low number of channels" — EbDa ISCA 2017 formulation, restated in the 2025 line of work) [6]; (b) a 2026 industry blog on deadlock verification opens with "Dally and Seitz showed that a deadlock-free routing algorithm... depends on the absence of cycles in the channel dependency graph, and that virtual channels can be used to remove dependency cycles" [16]; (c) the 2025 existence theorem (Finding 2.4) is a graph-theoretic extension of the same dependency-acyclicity view [4]. *Inference: CDG acyclicity remains the operative standard for judging routing deadlock in 2025–2026 literature* — every in-window paper found either preserves it structurally (DOR, turn restrictions, embedded acyclic subnetworks, link ordering) or adds recovery/isolation mechanisms (bubbles, injection control, preemptive VCs) [1][3][7][10].

---

## Evidence table

| # | Source | URL | Key claim | Type | Confidence |
|---|--------|-----|-----------|------|------------|
| 1 | Leone, Colagrande, Benini — Physically-Aware Preemptive Virtual Channels for Deadlock-Free AXI NoCs (arXiv:2607.01430, 2026-07-01) | https://arxiv.org/abs/2607.01430 | AXI4 read/write protocol dependencies create endpoint circular waits even with deadlock-free routing; Preemptive VCs save up to 76% link resources, ~3% area vs multiplane | primary (abstract) | high |
| 2 | Zhang, Zhao, Wang, Ren — Q-StaR: A Quasi-Static Routing Scheme for NoCs (arXiv:2603.10637, 2026-03-11) | https://arxiv.org/abs/2603.10637 | DOR is "guaranteed deadlock free"; BiDOR+N-Rank improves throughput +42.9% vs DOR while retaining simplicity | primary (abstract) | high |
| 3 | Chen, Fu, Wang, Zhou (NUDT) — Deadlock-Free Bridge Module for Inter-Chiplet Communication (HPCA 2026, Feb 2 2026) | https://2026.hpca-conf.org/details/hpca-2026-main-conference/76/Deadlock-Free-Bridge-Module-for-Inter-Chiplet-Communication-in-Open-Chiplet-Ecosystem | Inter-chiplet deadlock is solved by a bridge module using injection control derived from coherence-flow dependencies; 2.5% area overhead, 1–7% perf gain | primary (conf. abstract) | high |
| 4 | Mendlovic — Existence of Deadlock-Free Routing for Arbitrary Networks (arXiv:2503.04583, 2025-03-06) | https://arxiv.org/abs/2503.04583 | Necessary & sufficient graph condition for existence of deadlock-free routing (two edge-disjoint directed trees, in/out of root) | primary (abstract) | high |
| 5 | Srivastava, Rydell, Goens, Nagarajan, Sorin — Efficient Deadlock Avoidance by Considering Stalling, Message Dependencies, and Topology (IEEE CAL 24(2), 2025) | https://scholars.duke.edu/publication/1692103 (PDF: https://www.goens.org/publications/cal25.pdf) | Fewer virtual networks via stall analysis has a shortcoming that can cause deadlock; combining stall, message-dependency and topology analyses avoids it | primary (abstract; PDF body blocked) | medium |
| 6 | Das, Das, Karfa — Developing Deadlock-Free Routing Algorithms in Torus NoC: A Formal Approach (ACM TECS 24(5s), 2025 / CODES+ISSS 2025) | https://dl.acm.org/doi/10.1145/3762650 | Formal construction of deadlock-free torus NoC routing; few existing deadlock-free torus algorithms without implementation cost | primary (metadata/abstract) | medium |
| 7 | Cano et al. — TERA: Deadlock-free routing for Full-mesh networks without using Virtual Channels (HOTI 2025 / arXiv:2510.14730, 2025-10-16) | https://arxiv.org/abs/2510.14730 (DOI: https://doi.org/10.1109/hoti66940.2025.00020) | Embedded acyclic subnetwork gives deadlock-free non-minimal paths without VCs; 80% better than link ordering on adversarial traffic; 50% less buffering vs VC approaches | primary (abstract) | high |
| 8 | Ahmed, Yaqoob, Zafar, Din — Scaling Formal Verification of Network On Chip Using Path Decomposition (DVCon US 2026, session [58]) | https://dvcon.org/program/2026/2026-technical-sessions (PDF: https://10xengineers.ai/wp-content/uploads/DVcon_submission_final-1.pdf) | Simulation limits coverage for deadlock/livelock/starvation; path-decomposition methodology scales formal proof for mesh NoCs | primary (session listing + abstract; PDF body blocked) | medium |
| 9 | Roy, Yeung, Hong, Desai, Raj, Agarwal, Patel — Hierarchical Formal Verification and Progress Checking of Network-On-Chip Design (DVCon US 2025) | https://dvcon-proceedings.org/document/hierarchical-formal-verification-and-progress-checking-of-network-on-chip-design/ | Hierarchical formal flow with forward-progress checks; deadlock/end-to-end formal checks hard due to tool capacity | primary (landing page; PDF body blocked) | medium |
| 10 | Green et al. — Throughput-Optimized Networks at Scale / TONS (arXiv:2605.27963, 2026-05-27) | https://arxiv.org/abs/2605.27963 | Deadlock-free routing scheme compatible with limited VCs and optical-switch faults; 2.1x/1.6x speedups over TPU v4/5p torus variants | primary (abstract) | high |
| 11 | Liao et al. — UB-Mesh (arXiv:2503.20377, 2025-03-26) | https://arxiv.org/abs/2503.20377 | All-Path Routing combines source routing + linear table lookup + deadlock-free flow control to avoid deadlock | primary (abstract) | medium (datacenter, not NoC) |
| 12 | Ji & Yang — A Deadlock-Free Deterministic–Adaptive Hybrid Routing Algorithm (Electronics 14(5):845, 2025-02-21) | https://www.mdpi.com/2079-9292/14/5/845 | DAHR combines deterministic info + real-time congestion while ensuring deadlock-free operation | primary (abstract) | medium |
| 13 | Indrusiak group — A protocol to reduce worst-case latency in deflection-based on-chip networks (arXiv:2510.11361, 2025-10-13) | https://arxiv.org/abs/2510.11361 | Deflecting header-not-payload cuts traffic and worst-case latency in deflection networks | primary (abstract; full author list not captured) | medium |
| 14 | Sayuti & Soares Indrusiak — Toward Predictable Deflection Routing in Routerless NoCs (IEEE MCSoC 2025, Dec 2025) | https://eprints.whiterose.ac.uk/id/eprint/234673/ | Selective per-flow deflection bounding outperforms uniform bounding for worst-case deflection | primary (abstract) | high |
| 15 | Dally & Seitz — Deadlock-Free Message Routing in Multiprocessor Interconnection Networks (IEEE TC C-36(5):547–553, 1987) | https://ieeexplore.ieee.org/document/1676939 (record: https://authors.library.caltech.edu/records/fd0yr-br438) | Deadlock-free routing ⟺ no cycles in channel dependency graph; virtual channels break cycles | primary (metadata/abstract; 1987 body not read per brief) | high (for citation), n/a (body) |
| 16 | LUBIS EDA — Deadlocks in SoC: Why Simulation Falls Short (blog, 2026; no author/date shown) | https://lubis-eda.com/deadlocks-in-socs-why-livelock-and-starvation-escape/ | Deadlock/livelock/starvation escape simulation because they need rare state+traffic+timing alignment; formal verification asks reachability instead | secondary (vendor blog) | low–medium (no author/date) |
| 17 | Bentert et al. — Complexity of Perfect and Ideal Resilience Verification in Fast Re-Route Networks (arXiv:2601.03934, 2026-01-07) | https://arxiv.org/abs/2601.03934 | Checking static rerouting rules for perfect resilience is coNP-complete; linear-time special cases | primary (abstract) | medium (tangential domain) |
| 18 | Leveraging InfiniBand Controller to Configure Deadlock-Free Routing Engines for Dragonflies (arXiv:2502.01214, 2025-02-03) | https://arxiv.org/abs/2502.01214 | Configuring deadlock-free routing engines for InfiniBand Dragonflies | primary (abstract) | medium (off-chip domain) |
| 19 | Iff et al. — Network Design for Wafer-Scale Systems with Wafer-on-Wafer Hybrid Bonding (arXiv:2603.05266, 2026-03-05) | https://arxiv.org/abs/2603.05266 | Reticle placement improves wafer-scale mesh-like throughput up to 250%; no deadlock claim in abstract | primary (abstract) | medium |
| 20 | Krause et al. — Shiftfly (arXiv:2608.00897, 2026-08-01) | https://arxiv.org/abs/2608.00897 | Kautz-digraph global tier, table-free shift-register routing for accelerator interconnects; no deadlock claim in abstract | primary (abstract) | medium |
| 21 | Taheri, Pasricha, Nikdast — ReD (IEEE TCAD 43(12):4599–4612, Dec 2024) | https://ieeexplore.ieee.org/document/10529122 | Reliable and deadlock-free routing for 2.5-D chiplet interposer networks | primary (metadata; out of window, context) | medium |
| 22 | DeFT — Deadlock-Free and Fault-Tolerant Routing for 2.5D Chiplet Networks (arXiv:2112.09234, 2021) | https://arxiv.org/abs/2112.09234 | Deadlock-free fault-tolerant 2.5D chiplet routing | primary (metadata; context) | medium |
| 23 | Ebrahimi & Daneshtalab — EbDa (ISCA 2017, pp. 703–715) | https://dl.acm.org/doi/10.1145/3079856.3080253 | Three theorems extending Dally's CDG theory to scalable design/verification of deadlock-free networks | primary (metadata; context) | medium |
| 24 | Systematic Construction of Deadlock-Free Routing for NoC Using Integer Linear Programming (IEEE, 2023) | https://ieeexplore.ieee.org/document/10387838 | ILP-based construction of deadlock-free NoC routing | primary (metadata; context, body blocked) | low (no abstract captured) |
| 25 | Zhao, Zhu, Bai, Chen — PAIR: Periodically Alternate the Identity of Routers to Ensure Deadlock Freedom in NoC (ASP-DAC 2024, pp. 7–12) | https://researchr.org/publication/ZhaoZBC24 | Periodic router-identity alternation + express path breaks deadlock cycles (2024, context) | primary (metadata; body blocked) | medium |

---

## Findings (narrative, inline citations)

1. **DOR remains the reference deadlock-free baseline in 2026, and it is explicitly a *structural* guarantee.** Q-StaR (Mar 2026) names "guaranteed deadlock freedom" among DOR's properties while proposing a DOR-family variant that keeps the guarantee [2]. For the project thread: the Dijkstra/table-based route set that diverged from DOR is precisely the kind of deviation that removes the CDG-acyclicity guarantee DOR provides by construction. This is an inference from [2][15], not a claim any paper states about the project's specific setup.

2. **Cross-domain (chiplet/bridge) deadlock is a named, active 2026 problem, and injection control at a bridge is the current best-practice answer.** HPCA 2026 DFBM resolves inter-chiplet deadlock without touching chiplet-internal NoCs, at 2.5% area [3]. This maps directly onto the "multi-die bridge with a single VC" scenario: DFBM's premise is that even deadlock-free intra-die routing does not make the bridge safe, and isolation (injection control) is the mechanism — same class of conclusion as the single-VC bridge needing structural protection.

3. **The literature is moving *away* from VCs as the default deadlock mechanism** — TERA (no-VC, embedded subnetwork, HOTI 2025) [7], DFBM (injection control, HPCA 2026) [3], Preemptive VCs (link-area savings vs multiplane, arXiv Jul 2026) [1], TONS (deadlock-free routing under a *limited* VC budget, arXiv May 2026) [10]. For a single-VC bridge, this is good news: 2025–2026 results demonstrate deadlock freedom with one or zero VCs via routing structure (embedded acyclic subnetwork, link ordering) or injection control.

4. **Protocol-level (endpoint) dependency cycles are the dominant "new" deadlock source in 2025–2026 NoC discourse, distinct from routing cycles.** The AXI4 preemptive-VC paper states routing-deadlock-free networks can still deadlock at endpoints from read/write class dependencies [1]; the CAL 2025 paper fixes a shortcoming in stall-analysis-based deadlock avoidance by combining message-dependency and topology analysis [5]. This supports treating the cross-die hang as possibly multi-cause: routing CDG cycle *and/or* protocol dependency cycle.

5. **Formal/automated deadlock verification in 2025–2026 is dominated by industrial property-based flows (DVCon 2025/2026), not new SAT/SMT or nuSMV/Spin academic tooling.** The two DVCon papers both argue simulation cannot reliably expose deadlock and offer hierarchical/path-decomposition formal strategies [8][9]. The 2026 coNP-completeness result [17] and the 2025 existence theorem [4] are the academic theory side. **No 2025–2026 paper was found applying Z3/SMT or nuSMV/Spin specifically to NoC deadlock detection** — stated per the brief's "no work found" rule.

6. **Bufferless/deflection 2025–2026 results are about worst-case latency and deflection bounds, not deadlock-freedom proofs** [13][14]. The deadlock-related theory for bufferless designs remains pre-2025 (BLESS/CHIPPER/MinBD line); nothing in-window was found claiming new bufferless deadlock-freedom results.

7. **Simulation credibility: the in-window industrial consensus is that deadlock hangs escape simulation by construction** (rare state+traffic+timing alignment), and that reachability-style formal analysis is the complementary evidence [8][9][16]. The vendor blog is the only source making this argument in prose directly comparable to the project's "RTL vs BookSim divergence" narrative, and it explicitly invokes Dally & Seitz CDG acyclicity [16]. Treat as secondary (no author/date visible), but it corroborates the DVCon papers.

8. **Gap note:** no 2025–2026 paper was found that compares DOR vs table/Dijkstra routing deadlock-freedom in a mesh, or that provides an automated tool analyzing a NoC routing table for CDG cycles (the closest 2025 analog is the InfiniBand Dragonfly configuration work [18], and the 2023 ILP construction [24] as context). If the project needs a routing-table CDG checker, the TECS 2025 formal approach [6] and EbDa theory [23] are the nearest methodological anchors.

---

## Coverage Status

**Checked directly (abstracts/landing pages read):** [1][2][3][4][7][10][11][14][16][17][19][20]; DVCon listings [8][9]; metadata via researchr/DBLP/venue pages for [6][21][22][23][25].
**Blocked (PDF-only; cited from search metadata, body not parsed):** [5] (goens.org PDF; abstract captured via search snippet + Duke/PCS landing pages), [8][9] (DVCon PDFs; abstracts via search), [24] (IEEE, no abstract captured), [25] (ASP-DAC PDF).
**Out of window (context only):** [15] (1987, body not read per brief), [21] (Dec 2024), [22] (2021), [23] (2017), [24] (2023), [25] (2024).
**Uncertain:** [13] full author list not captured (corresponding author Indrusiak per metadata); [16] no author/date on blog page (images dated 2026-06); [5][8][9][12][18][19][20] claims rest on abstracts/snippets only.
**Could not complete:** `alpha search` (alphaXiv) failed with network error ("fetch failed") after successful login — arXiv coverage substituted via web search + arXiv abs-page fetches; arXiv API (export.arxiv.org) rate-limited initially (HTTP 429/503), succeeded on retry for two sweep queries (cs.AR "deadlock", cs.NI/cs.DC "deadlock-free routing") — results consistent with the web-search corpus; NOCS 2025/2026 program pages not reachable (nocs2025.github.io 404; no deadlock-specific NOCS papers surfaced in any search).

---

## Search log (exact queries run, 2026-08-14)

Web searches (Perplexity/Exa/Gemini auto provider; results per query varied 4–10):
1. "NoC deadlock deadlock-free routing 2025 2026 network-on-chip"
2. "deadlock-free routing network-on-chip 2025 arXiv" *(provider error — rate limit; retried via other queries)*
3. "channel dependency graph deadlock detection NoC 2025 2026"
4. "SAT SMT formal verification deadlock freedom routing network-on-chip 2025 2026"
5. "model checking deadlock NoC router nuSMV spin Z3 2025 2026"
6. "routing table deadlock freedom analysis verification 2025 2026"
7. "bufferless NoC deflection routing deadlock 2025 2026"
8. "AI accelerator NoC deadlock wafer-scale chiplet interconnect 2025 2026"
9. "NOCS 2025 2026 symposium papers deadlock routing"
10. "virtual channel allocation deadlock avoidance NoC 2025 2026"
11. "table-based routing deadlock freedom mesh 2025 2026 deterministic"
12. "\"Developing Deadlock-Free Routing Algorithms in Torus NoC\" TECS 2025"
13. "ReD reliable deadlock-free routing 2.5D chiplet Nikdast 2025"
14. "\"Deadlock-Free Routing for Full-Mesh Networks Without Using Virtual Channels\""
15. "Dally Seitz 1987 deadlock-free message routing multiprocessor interconnection networks citation"
16. "goens \"Efficient Deadlock Avoidance\" protocol stalls 2025 IEEE Computer Architecture Letters"
17. "PAIR ASP-DAC 2025 \"Periodically Alternate the Identity of Routers\" deadlock NoC"
18. "NOCS 2025 accepted papers network-on-chip symposium deadlock"
19. "\"deflection\" OR \"bufferless\" deadlock freedom 2025 2026 NoC livelock"
20. "arxiv 2510.11361 deflection-based on-chip networks protocol worst-case latency abstract"
21. "NOCS 2025 19th international symposium networks-on-chip program papers"
22. "DVCon 2025 \"Scaling Formal Verification of Network On Chip\" deadlock livelock starvation"
23. "arXiv listing cs.AR deadlock 2026 network-on-chip new submissions"
24. (domainFilter=arxiv.org) "deadlock network-on-chip 2026 arXiv"
25. (domainFilter=arxiv.org) "deadlock-free routing NoC 2025 arXiv mesh"
26. (domainFilter=arxiv.org) "deadlock detection routing 2025 2026 arXiv chiplet"
27. "\"Physically-Aware Preemptive Virtual Channels\" deadlock-free AXI 2026 authors"
28. "\"Deterministic–Adaptive Hybrid Routing\" Electronics 2025 845 authors DAHR"
29. "10xengineers \"Scaling Formal Verification of Network On Chip\" DVCon 2025 2026"
30. "Q-StaR quasi-static routing BiDOR N-Rank authors arXiv"
31. "\"worst-case latency in deflection-based on-chip networks\" authors arXiv 2510.11361"
32. "EbDa theory design verification deadlock-free interconnection networks ISCA 2017 authors"

arXiv API sweep queries (export.arxiv.org, Atom, metadata only):
33. `all:"deadlock" AND cat:cs.AR` — submittedDate desc, 20 results (2026-07-03 → 2020)
34. `all:"deadlock-free routing" AND (cat:cs.NI OR cat:cs.DC)` — submittedDate desc, 15 results (2026-05-27 → 2013)

alphaXiv CLI: `alpha search "NoC deadlock"` (+ variants, semantic and "both" modes) — **failed with "fetch failed"** (network error despite authenticated session); noted here for reproducibility.

Page fetches (HTML only, no PDF bodies): arXiv abs pages 2607.01430, 2603.10637, 2503.04583, 2510.11361, 2510.14730, 2601.03934, 2603.05266, 2608.00897, 2503.20377, 2605.27963; HPCA 2026 program page (DFBM session); ACM DL landing (blocked by bot-check; metadata via researchr/DOI instead); MDPI Electronics 14(5) 845; White Rose eprints (MCSoC 2025); LUBIS EDA blog; dvcon-proceedings.org document page; dvcon.org 2026 technical sessions; nocs2025.github.io (404).

---

## Sources

1. L. Leone, L. Colagrande, L. Benini — Physically-Aware Preemptive Virtual Channels for Deadlock-Free AXI Networks-on-Chip (arXiv:2607.01430, 2026) — https://arxiv.org/abs/2607.01430
2. Y. Zhang, Y. Zhao, X. Wang, F. Ren — Q-StaR: A Quasi-Static Routing Scheme for NoCs (arXiv:2603.10637, 2026) — https://arxiv.org/abs/2603.10637
3. Z. Chen, W. Fu, Y. Wang, H. Zhou (NUDT) — Deadlock-Free Bridge Module for Inter-Chiplet Communication in Open Chiplet Ecosystem (HPCA 2026) — https://2026.hpca-conf.org/details/hpca-2026-main-conference/76/Deadlock-Free-Bridge-Module-for-Inter-Chiplet-Communication-in-Open-Chiplet-Ecosystem
4. U. Mendlovic — Existence of Deadlock-Free Routing for Arbitrary Networks (arXiv:2503.04583, 2025) — https://arxiv.org/abs/2503.04583
5. S. Srivastava, F. Rydell, A. Goens, V. Nagarajan, D. J. Sorin — Efficient Deadlock Avoidance by Considering Stalling, Message Dependencies, and Topology (IEEE Computer Architecture Letters 24(2), 2025) — https://scholars.duke.edu/publication/1692103 (PDF: https://www.goens.org/publications/cal25.pdf)
6. S. Das, A. Das, C. Karfa — Developing Deadlock-Free Routing Algorithms in Torus NoC: A Formal Approach (ACM TECS 24(5s), 2025 / CODES+ISSS 2025) — https://dl.acm.org/doi/10.1145/3762650
7. A. Cano et al. — Deadlock-free routing for Full-mesh networks without using Virtual Channels / TERA (HOTI 2025; arXiv:2510.14730, 2025) — https://arxiv.org/abs/2510.14730 (DOI: https://doi.org/10.1109/hoti66940.2025.00020)
8. B. Ahmed, U. Yaqoob, B. Zafar, M. Din — Scaling Formal Verification of Network On Chip Using Path Decomposition (DVCon US 2026, session [58]) — https://dvcon.org/program/2026/2026-technical-sessions (PDF: https://10xengineers.ai/wp-content/uploads/DVcon_submission_final-1.pdf)
9. P. Roy, P. Yeung, J. Hong, A. Desai, A. Raj, C. Agarwal, D. Patel — Hierarchical Formal Verification and Progress Checking of Network-On-Chip Design (DVCon US 2025) — https://dvcon-proceedings.org/document/hierarchical-formal-verification-and-progress-checking-of-network-on-chip-design/
10. C. Green et al. — Throughput-Optimized Networks at Scale / TONS (arXiv:2605.27963, 2026) — https://arxiv.org/abs/2605.27963
11. H. Liao et al. — UB-Mesh: a Hierarchically Localized nD-FullMesh Datacenter Network Architecture (arXiv:2503.20377, 2025) — https://arxiv.org/abs/2503.20377
12. N. Ji, Y. Yang — A Deadlock-Free Deterministic–Adaptive Hybrid Routing Algorithm for Efficient Network-on-Chip Communication (Electronics 14(5):845, 2025) — https://www.mdpi.com/2079-9292/14/5/845
13. L. S. Indrusiak et al. — A protocol to reduce worst-case latency in deflection-based on-chip networks (arXiv:2510.11361, 2025) — https://arxiv.org/abs/2510.11361
14. M. N. S. M. Sayuti, L. Soares Indrusiak — Toward Predictable Deflection Routing in Routerless NoCs for Real-Time Systems (IEEE MCSoC 2025) — https://eprints.whiterose.ac.uk/id/eprint/234673/
15. W. J. Dally, C. L. Seitz — Deadlock-Free Message Routing in Multiprocessor Interconnection Networks (IEEE Trans. Computers C-36(5):547–553, 1987) — https://ieeexplore.ieee.org/document/1676939 ; record: https://authors.library.caltech.edu/records/fd0yr-br438
16. LUBIS EDA — Deadlocks in SoC: Why Simulation Falls Short (blog, 2026, no author/date shown) — https://lubis-eda.com/deadlocks-in-socs-why-livelock-and-starvation-escape/
17. M. Bentert et al. — Complexity of Perfect and Ideal Resilience Verification in Fast Re-Route Networks (arXiv:2601.03934, 2026) — https://arxiv.org/abs/2601.03934
18. Leveraging InfiniBand Controller to Configure Deadlock-Free Routing Engines for Dragonflies (arXiv:2502.01214, 2025) — https://arxiv.org/abs/2502.01214
19. P. Iff et al. — Network Design for Wafer-Scale Systems with Wafer-on-Wafer Hybrid Bonding (arXiv:2603.05266, 2026) — https://arxiv.org/abs/2603.05266
20. E. E. Krause et al. — Shiftfly: Scaling the Accelerator Interconnect Past the Pod with a Shift-Routed Optical Tier (arXiv:2608.00897, 2026) — https://arxiv.org/abs/2608.00897
21. E. Taheri, S. Pasricha, M. Nikdast — ReD: A Reliable and Deadlock-Free Routing for 2.5-D Chiplet-Based Interposer Networks (IEEE TCAD 43(12):4599–4612, Dec 2024) — https://ieeexplore.ieee.org/document/10529122
22. DeFT: A Deadlock-Free and Fault-Tolerant Routing Algorithm for 2.5D Chiplet Networks (arXiv:2112.09234, 2021) — https://arxiv.org/abs/2112.09234
23. M. Ebrahimi, M. Daneshtalab — EbDa: A New Theory on Design and Verification of Deadlock-free Interconnection Networks (ISCA 2017, pp. 703–715) — https://dl.acm.org/doi/10.1145/3079856.3080253
24. Systematic Construction of Deadlock-Free Routing for NoC Using Integer Linear Programming (IEEE, 2023) — https://ieeexplore.ieee.org/document/10387838
25. Z. Zhao, X. Zhu, J. Bai, G. Chen — PAIR: Periodically Alternate the Identity of Routers to Ensure Deadlock Freedom in NoC (ASP-DAC 2024, pp. 7–12) — https://researchr.org/publication/ZhaoZBC24
