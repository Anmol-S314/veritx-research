# T3 — Does mixed traffic break the "topology is second-order" verdict? (2026 literature probe)

**Status:** desk research, 2026-08-09. Question posed by a skeptical reviewer: a real AI
accelerator's NoC does not carry only transformer inference traffic. Control-plane
register access, host DMA, telemetry, security, coherence, and co-tenant workloads share
the fabric. Does the T3 conclusion survive that reality?

**Headline:** The mixed-traffic argument is **real but mis-aimed**. It does not refute
the T3 conclusion. Every shipping AI accelerator we can find in the 2024–2026 literature
answers mixed traffic with **plane/VC/QoS separation on the same mesh** — not with a
different topology. Where distance and topology demonstrably *do* matter is one rung up:
chiplet/package scale, which the T3 claim already excludes and the repo already concedes
([NETWORK-HIERARCHY.md](../NETWORK-HIERARCHY.md), "inverts as you climb"). The argument
*does* sharpen the claim's scope and points at one untested counterfactual (see Verdict).

---

## The question being asked

Does the T3 conclusion — on-chip NoC topology is not the lever for transformer
accelerators — survive when the full mixed-traffic reality of a real chip is considered:
control/CSR, host interface, telemetry, security, coherence, co-tenancy, chiplet bridges,
SoC peripherals?

## Scope of the claim being probed

T3's claim, quoted from [CONCLUSION.md](../CONCLUSION.md): topology is not the binding
constraint "for **transformers** on **these** accelerators, at the scales tested."
Three anchors: (1) BookSim2+Ramulator2 EDP inside a 1.37× model error bar; (2) Tenstorrent
measured silicon (Wormhole); (3) decode roofline, NoC has 4× headroom.

The reviewer may attack: the NoC's *headroom* and the *error bar* both assume transformer
data traffic only. They may not attack: chiplet-scale fabrics — the repo already says the
verdict inverts as you climb the hierarchy, and this probe confirms it (below).

## What the evidence says

### 1. Real AI chips carry mixed traffic — and the industry answer is separation, not topology

Every primary source below describes a chip that separates traffic classes **physically
or logically**, on a mesh, and none of them changed topology to do it.

- **Microsoft Maia 200** (Microsoft Azure Infrastructure Blog, "Deep dive into the Maia 200
  architecture," 2026-01-30, https://techcommunity.microsoft.com/blog/azureinfrastructureblog/deep-dive-into-the-maia-200-architecture/4489312).
  Inference accelerator, shipped silicon. The NoC is "a mesh network spanning all
  clusters, tiles, memory controllers, and I/O units" **segmented into multiple logical
  planes**: a high-bandwidth data plane for tensors and "a dedicated control plane for
  interrupts, synchronization, and small messages. This separation ensures that
  latency-critical control traffic is never blocked behind bulk data transfers." Plus:
  QoS in fabric and memory controllers for critical traffic, and a fail-safe management
  plane isolated from the data path for telemetry/recovery. Mesh + planes, not a topology
  change.
- **FlooNoC** (Fischer, Rogenmoser, Benz, Gürkaynak, Benini, "FlooNoC: A 645 Gbps/link
  0.15 pJ/B/hop Open-Source NoC with Wide Physical Links and End-to-End AXI4 Parallel
  Multi-Stream Support," IEEE TVLSI 33(4), 2025; arXiv 2409.17606). AI-cluster NoC whose
  headline design choice is **physical channels over virtual ones** to manage diverse
  traffic types — the same reason T3 anchors its router energy to this chip. The authors
  explicitly separate "bulk-transfer" (DMA) NoCs from cache-coherent/low-latency NoCs as
  different design regimes. Control and bulk are handled by parallel streams, not by
  reshaping the mesh.
- **IBM NorthPole** (Modha et al., "Neural inference at the frontier of energy, space,
  and time," Science 382:329-335, 2023; https://www.science.org/doi/10.1126/science.adh1174).
  Inference chip, shipped silicon, 256 cores. **Four dedicated NoCs**: Activation NoC,
  Partial-Sum NoC, **Model NoC (1024-bit, weights)** and **Instruction NoC (256-bit,
  programs)**. The weight/instruction NoCs exist because reconfiguration traffic is *on
  the critical path of layer execution* — "reconfiguring the weights during the execution
  of each layer using one NoC." Control/configuration traffic is real, and it is given its
  own fabric. Note the MNoC (weight distribution) is **data plane, not control** — the
  only transformer-traffic class that got a dedicated network.
- **Tenstorrent Wormhole/Blackhole** (github.com/tenstorrent/tt-isa-documentation, "NoC"
  page). Two independent NoCs (NOC0/NOC1), 2D torus, X-major vs Y-major, opposite
  directions — read and write traffic segregated onto separate networks. Deadlock
  avoidance via plane separation. (Matches the repo's own NETWORK-HIERARCHY.md note and
  the 2603.23343 anchor.)
- **AMD Versal** (AMD docs UG1504, "NoC Throughput and Latency," 2026; UG994 "NoC and QoS
  Requirements," 2024, https://docs.amd.com/r/en-US/ug994-vivado-ip-subsystems/NoC-and-QoS-Requirements).
  Production NoC with per-connection QoS: traffic classes **Low Latency / Isochronous /
  Best Effort**, and the explicit guidance that DRAM efficiency, not the NoC, is the usual
  throughput limiter ("If the throughput is lower than expected, it is usually caused by
  DRAM efficiency").

**Reading:** the skeptic's premise is correct — the classes exist. The industry's
countermeasure is structural: dedicate planes or VCs to control/QoS classes, on a mesh.
None of these vendors treated "topology" as the answer to mixed traffic.

### 2. QoS mechanisms decouple traffic classes from topology

- **QNoC** (Bolotin et al., "QNoC: QoS architecture and design process for network on
  chip," JSA 50(2-3):105-128, 2004) — the canonical SoC traffic taxonomy: **signaling /
  real-time / RD-WR / block-transfer**. Control (signaling) is its own service class with
  latency guarantees, decades before AI chips. The fix it proposes is class-aware
  arbitration on a mesh.
- **Arteris FlexNoC** (Arteris, "End-to-End QoS for SoC Performance," 2026,
  https://www.arteris.com/learn/end-to-end-quality-of-service/) — commercial NoC IP used
  across >200 SoC vendors: QoS is "coordinated control of latency, bandwidth, arbitration,
  traffic prioritization, and flow management across the full on-chip network." The
  product is traffic-class management, and the underlying topology is mesh-class.
- **Microsoft Maia 200** (§1) and **AMD Versal** (§1) both ship QoS at fabric and memory
  controller level.

**Reading:** mixed traffic is treated as an arbitration/priority problem with a standard
solution — VCs, planes, QoS fields (AXI/CHI QoS). Once classes are segregated, the shape
of the fabric stops being the lever for the control class too: what remains is hop count
(see §5).

### 3. Chiplet/package scale: distance and topology re-enter — this is measured

This is where the 2024–2026 literature is strongest, and where it *agrees with the repo's
own hierarchy ladder*.

- **Measured AMD Infinity Fabric** (Schieffer, Shi, Markidis, Herten, Faj, Peng,
  "Understanding Data Movement in AMD Multi-GPU Systems with Infinity Fabric," SC-W '24,
  arXiv 2410.00801). Measured MI250X: GPU pairs connected by a single IF link: **<10 μs**;
  pairs on the same physical GPU: 10.5–10.8 μs; the two pairs whose
  bandwidth-maximizing path is not the shortest path: **17.8–18.2 μs**. Topology and path
  choice move measured latency ~2× at chip-to-chip scale — at a scale where each hop is a
  serialized link, not a wire.
- **AMD MI300X chiplet interconnect** (Smith, Loh, Naffziger, Wuu et al., "Interconnect
  Design for Heterogeneous Integration of Chiplets in the AMD Instinct MI300X
  Accelerator," IEEE Micro 45(1):57-66, 2025) — heterogeneous integration across 3
  packaging technologies; 8 accelerator dies + 4 I/O dies + 8 HBM3 stacks; 4.8 TB/s
  Infinity Fabric Advanced Package link bisection. The paper exists because package-level
  placement and interconnect design *matter* at this scale.
- **UCIe** (Chan Carusone et al., "Co-Design of Interchiplet, Package, and System
  Interconnect Protocols," IEEE Micro 45(1):35-40, 2025; Das Sharma et al., "UCIe:
  Standard for an Open Chiplet Ecosystem," IEEE Micro 45(1):41-49, 2025; Das Sharma, "An
  Introduction to the Universal Chiplet Interconnect Express (UCIe)," ACM Computing
  Surveys 58(13), 2026) — UCIe is a point-to-point die-to-die link; topology emerges at
  the package. The 2026 CSUR survey treats the package fabric as a first-class network
  problem.
- **UCIe-3D** (Saxena et al. [Intel], "High-performance, power-efficient three-dimensional
  system-in-package integration," Nature Electronics, 2024,
  https://www.nature.com/articles/s41928-024-01126-y) — 3D-stacked dies cut hops,
  latency, and power vs planar UCIe; explicitly modeled over mesh topologies of 64-512
  cores. Hop count is the independent variable; that is a topology statement.
- **Groq scale-out** (Abts, Kim et al., "A Software-defined Tensor Streaming Multiprocessor
  for Large-scale Machine Learning," ISCA 2022; "The Groq Software-defined Scale-out TSP,"
  Hot Chips 2022) — high-radix Dragonfly across TSPs, chosen for low diameter: "The total
  observed communication latency and variance increases with the number of hops." Chip
  scale-out chose a different *shape* because hops there cost.
- **Maia 200 scale-up** (Microsoft, 2026, §1) — Fully Connected Quad (switchless direct
  links) inside a 4-accelerator node; two-tier topology to 6,144 accelerators. Topology
  choice at node scale, explicitly to cut tensor-parallel hop latency.
- **BiFrost** (Kalsi, Wang, Howard, Fryman, Petrini et al. [Intel], "BiFrost: A Composable,
  Resilient Interconnect Network Architecture for Scalable AI Systems," IEEE Micro
  45(5):67-78, 2025) — Intel's AI interconnect architecture: composable, resilient fabric
  for AI systems, treating interconnect design as first-order.

**Reading:** at die boundaries, distance and shape are first-order (measured, 2×
latency deltas). This is exactly the repo's own claim: on-chip rung closed; chiplet rung
is where the topology question is live ([UCIE-ARC.md](../UCIE-ARC.md) already gates on
this). The reviewer's chiplet point strengthens the repo's scoping, it does not attack it.

### 4. 2024–2026 NoC work for heterogeneous AI where non-inference traffic binds

- **Survey of NoC for Heterogeneous Multicore Systems** (Biglari, Hosseini, Upadhyay,
  Zhao, MCSoC 2024, pp. 155-162) — 2024 survey of GPU/FPGA/ASIC NoC design. Core finding:
  "Conventional NoC architectures developed for CPU-based multi-core systems are not able
  to satisfy the traffic demands of heterogeneous systems" — heterogeneous traffic mixes
  are a recognized design driver. It catalogs GPU/FPGA/interposer NoCs; it does **not**
  quantify control-vs-data shares.
- **Traffic Patterns in NoCs: A Survey** (Malikov & Romanov, IEEE Access 13:148803-148815,
  2025) — the most recent traffic-pattern taxonomy. Classifies synthetic and realistic
  patterns; adds benchmarks. It does **not** quantify control/telemetry share on AI
  accelerator fabrics, and none of its realistic suites come from an AI accelerator.
- **WaferLLM** (arXiv 2502.04563, OSDI 2025) — wafer-scale LLM inference on mesh-based
  chips (Cerebras WSE, Tesla Dojo, and "even non-wafer-scale accelerators such as Meta
  MTIA, Tenstorrent ... use mesh"). Documents the constraint regime: NoC messages of a
  few bytes, routing limited to a few bits of header, latency = Manhattan distance ×
  per-hop latency. Mesh because "3D torus or tree structures are impractical due to high
  on-chip wiring costs." Independent confirmation that mesh wins on cost, not on traffic
  shape.
- **Collective-capable NoC for large-scale ML accelerators** (arXiv 2603.26438, 2026) —
  open-source in-network collectives (reduction) for tiled ML accelerators; cites MTIA,
  SN40L, Blackhole multicast. Extends the data plane with in-fabric compute; control
  plane untouched.
- **GEMINI multi-chiplet characterization** (Musavi, Irabor, Das, Alarcón, Abadal,
  "Communication Characterization of AI Workloads for Large-scale Multi-chiplet
  Accelerators," arXiv 2410.22262) — measured (simulated) multicast traffic across
  chiplet arrays; inter-chiplet (NoP) traffic exceeds 50-70% of data-movement time for
  several workloads as arrays grow. Chiplet-scale traffic is the binding class, not
  on-die.
- **Repo-internal prior-art** ([UCIE-ARC.md](../UCIE-ARC.md) gate table): CINT-AD (2025)
  interposer topology generation; HPCA 2026 deadlock-free coherence bridge; GLSVLSI 2025
  (arXiv 2504.04005) coherence-aware routing + topology selection — all chiplet-rung
  work, all consistent with "on-die shape is settled, the bridge is where it moves."

**Reading:** the active 2024–2026 research front for "non-inference traffic binds" is
chiplet/package scale, not the on-die mesh. On-die, the bind story is memory bandwidth
(§1 AMD Versal quote; T3's own roofline).

### 5. Counter-evidence: topology DOES matter for latency-critical traffic — under conditions

The reviewer's strongest point, and the literature supports it — *conditionally*:

- **At low injection, latency = hop count.** The AMD IF measurement (§3, 10.5 vs 17.8 μs
  by path choice) and Groq's diameter argument (§3) are the same physics: for
  latency-critical traffic, each hop adds a serialized stage. On-die, T3's own BookSim
  numbers show mesh vs fat-tree hop counts of 6.62 vs 6.00 ([FINDINGS.md](../FINDINGS.md)
  §2). If a control packet must meet a deadline, hops eat the deadline directly.
- **Burstiness starves control — measured in this repo.** The T3 plane-separation sweep
  ([NETWORK-HIERARCHY.md](../NETWORK-HIERARCHY.md) appendix) is the closest thing to a
  mixed-traffic topology result we have: at 1 VC (no isolation), DMA burst length 5→80
  flits inflates 1-flit control latency from 1.36× to **6.68×** at constant bandwidth;
  4 VCs hold it to 1.24×. Mechanism: control waits behind bursts, not behind bandwidth.
  But the fix measured there is **plane count and VCs** — the mesh shape is invariant
  across the sweep, and it survives (control 33.2 cycles flat on an isolated plane).
- **Coherence/control deadlines are a real protocol constraint.** AMBA CHI/CXL-class
  traffic is 1-flit and deadline-bound (the repo's own taxonomy in NETWORK-HIERARCHY.md).
  No public 2024–2026 measurement shows such traffic *binding* on a transformer
  accelerator's fabric — the chips we found (§1) separate it onto its own plane before it
  can.
- **The counterfactual where the reviewer wins:** a chip that shares one fabric, no VCs,
  no plane separation, and runs latency-critical control concurrent with bulk DMA. Under
  that design, hop count (topology) *would* matter for control tail latency even though
  mean utilization is trivial. No shipping AI accelerator we found has that design; every
  one separates classes first.

### 6. What is thin / missing in the literature

- **No public measurement of control-vs-data traffic share on a shipping AI accelerator
  NoC.** Vendor docs are qualitative ("dedicated control plane"); academic traffic suites
  (IEEE Access 2025 survey, MCSL/NoCTrace-class suites) come from CPUs/SoCs, not AI chips.
  The claim "control traffic cannot bind on the data plane" rests on **architecture
  (separation by construction)**, not on measured shares. That is a real gap, and the
  honest place for the team to add evidence is their own BookSim (below).
- **No 2024–2026 paper runs a topology sweep under a mixed traffic matrix for
  transformer serving.** Nearest: the repo's own plane-separation experiment, plus
  QNoC-class QoS reasoning. The "mixed traffic + topology" intersection is open — which
  is an opportunity and a scoop risk in one.
- Baya Systems' white paper ("Baya Systems Elevates Tenstorrent's AI Fabric," 2025-06-20,
  https://bayasystems.com/2025/06/20/tenstorrents-ai-fabric/) claims up to 66% fabric
  performance gain and 50% footprint cut over Tenstorrent's in-house fabric. **Treat as
  vendor marketing, not evidence** — fabric microarchitecture (buffers, QoS, mesh-vs-
  crossbar structure), not topology, and self-reported.

## The verdict

1. **The mixed-traffic argument does not refute the T3 conclusion.** Every primary
   source (Maia 200 2026, NorthPole Science 2023, FlooNoC TVLSI 2025, Tenstorrent ISA
   docs, AMD Versal docs) shows real chips answer control/host/telemetry traffic with
   **plane separation, VCs, and QoS on a mesh** — the topology axis is untouched, and the
   "4× headroom" claim lives in the data plane these classes are kept out of.
2. **It does sharpen the scope.** The claim should be stated as "the topology of the
   **on-die data plane** is second-order." Control-plane latency is a *structure*
   question (plane count, VC count, boundary placement) — which is exactly what
   [NETWORK-HIERARCHY.md](../NETWORK-HIERARCHY.md)'s appendix already measured, and which
   T3's "mesh is not the lever" survives intact (control stays under deadline on any
   tested topology once a plane exists).
3. **Where topology demonstrably matters, it is off the T3 claim's home rung.**
   Measured: 2× latency deltas from path choice on AMD Infinity Fabric (SC-W 2024);
   hop-driven latency reduction in UCIe-3D (Nature Electronics 2024); diameter-driven
   Dragonfly choice (Groq ISCA 2022); FCQ/2-tier scale-up (Maia 200); Intel BiFrost
   (2025). The reviewer's chiplet traffic argument is *correct* and lands exactly where
   the repo already conceded: the chiplet/package rung, which [UCIE-ARC.md](../UCIE-ARC.md)
   owns.
4. **The one untested counterfactual:** a class-unseparated fabric where latency-critical
   control shares a VC with bulk DMA. There, hop count becomes load-bearing for control
   tail latency. No shipping chip does this; a BookSim run can close the question cheaply.
5. **Bottom line:** the reviewer should not re-open the on-die topology question; they
   should read UCIE-ARC.md. Mixed traffic moves the lever from *shape* to *plane count
   and QoS* — and that is a T3-consistent result, with one gap (measured control share)
   the team can fill itself.

## Suggested next experiments / checks

1. **Mixed-class BookSim sweep (highest value, ~a day).** Same traffic matrix across
   mesh / fat-tree / torus at the T3 decode injection point (0.46 flit/cyc) plus the
   NETWORK-HIERARCHY.md appendix classes (DMA bursts, 1-flit control, CSR writes, PCIe
   traffic). Gate on **p99 control latency under a 500-cycle deadline**, not mean. If no
   topology keeps control under deadline at 1 VC but all do at 4 VCs, the verdict is
   pinned: **VCs, not shape** — exactly what the literature predicts.
2. **Test the counterfactual.** Sweep VC count 1→4 on the mesh alone; if the 1-VC mesh
   misses the deadline, the reviewer's failure mode is real — and the fix is not a new
   topology.
3. **Bridge leg (feeds UCIE-ARC.md).** Two-die config with the UCIe bridge as a router
   hop; add a CSR/control stream crossing the bridge. Test bridge-port placement
   (row/column axis) vs control deadline and vs the g-fold multicast demand. This is the
   rung where topology *and* traffic class genuinely co-bind.
4. **Subnets (the untested idea from FINDINGS.md).** `Interconnect.cc` hardcodes
   `subnet = 0`; put the control class on subnet 1 and compare against VC-based
   separation on a single mesh. ~20 lines of C++, and it directly measures "plane vs
   shape" for control traffic.
5. **Calibration check.** Run the mixed-class results through the 1.37× FlooNoC router
   model ([floonoc_calibrate.py](../scripts/floonoc_calibrate.py)) — if topology deltas
   under mixed traffic stay inside the error bar, the sweep is decoration and should be
   reported as such (PITFALLS §0 discipline).
6. **Gate for the gap.** Before claiming "control traffic cannot bind," try to find any
   measured control/telemetry share from a shipping accelerator (Maia, Trainium, TPU,
   Groq, Cerebras, MI300). If none exists — and we found none — state that the claim
   rests on architectural separation, not measurement. That is the honest form of the
   result.

## Gaps and caveats

- Public evidence on control-plane traffic *volume* on AI chips: none found. Vendor docs
  are structural, not quantitative.
- arXiv 2603.23343 (Tenstorrent anchor) is repo-internal; treated as given here.
- Baya/Tenstorrent 66% claim: vendor marketing, excluded from the verdict.
- No 2024–2026 survey quantifies control-vs-data share for AI accelerator fabrics
  (checked: IEEE Access 2025 traffic survey; MCSoC 2024 heterogeneous survey). The
  "mixed traffic + topology" intersection for transformer serving appears unclaimed —
  consistent with [NETWORK-HIERARCHY.md](../NETWORK-HIERARCHY.md) Gate-0 findings, and a
  scoop risk if the team goes public with it.

---

*Citations in body text: URL + title + year, primary sources preferred. Secondary
summaries (Cambrian AI, gpusmith, PatSnap) were used only to locate primaries and are
not load-bearing anywhere above.*
