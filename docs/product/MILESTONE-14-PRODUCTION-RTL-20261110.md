# Production-readiness milestone — 14 topologies against the pinned workloads — 2026-11-10

Refined goal (operator-stated 2026-11-10): **production-ready RTL for all 14 topologies, bound to the pinned workload set** (`docs/product/evidence/release-workloads-20261110.json`, 17 approved captures, full-size Mixtral revision `p-fd7e5e31be77-r02`, 74 agents / 81 routers / 8 VCs / 162 shared wires).

## What "production-ready" means here (and what it says about where we are)

A family is production-ready only if **every** gate below is green on one exact composed top:

| Gate | Meaning |
|---|---|
| L0 | Emitted composed top parses; no inferred latches/zero-width refs; Slang-clean |
| L1 | Spec-compliant behavior sim (AXI5 B/R/RLAST/DECERR/SLVERR/OKAY paths, ordering, conservation, reset) |
| L2 | Request→hardware binding proven per family (bad-design witness suite fully asserted; no `NOT_COVERED`) |
| L3 | Workload-driven RTL qualification with the pinned workloads (no synthetic-only traffic); conservation/credit/reset across packet sizes, all VC classes, in-order + escape |
| L4 | Physical: synthesizable clean, floorplan+CTS, post-STA vs declared clock, route, DRC; signoff-style bounds |
| L5 | `final_implementation=true` lawful; release evidence pinned; reproduction green |

## Measured state per family (this tree, this machine, today)

| Family | L0 | L1 | L2 | L3 | L4 | L5 | Notes |
|---|---|---|---|---|---|---|---|
| Mesh (2×2 slice + 8×8) | ✓ | ✓ (38/38, re-arbitrated tree; 8×8: 13 scenarios, 157 s) | ✓ exact rematerialized topology-vs-request witness | ✗ no pinned-workload run through RTL | ✗ | ✗ | S26/S27 contention pass, AW-first cadence |
| Torus (3×3) | ✓ | ✓ | ✓ exact wrap/channel graph witness | ✗ | ✗ | ✗ | |
| ConcentratedMesh 4×4 c=4 | △ candidate concentrator; lint/sim pending | ✗ | ✓ binding-mutation witness (hardware conformance pending) | ✗ | ✗ | ✗ | router-local arbitration/demux and endpoint-ID routing added; no composed Verilator qualification yet |
| Ring 64 | ✓ | ✓ | ✓ exact router/dateline graph witness | ✗ | ✗ | ✗ | |
| MECS / GEC-MECS | ✓ | ✓ (shared path) | ✓ exact per-wire tap identity witness | ✗ | ✗ | ✗ | |
| Fly (r4, l3) | ✓ (multi-seat via concentrator: 3 seats on one router, lint PASS / sim PASS 13/13) | ✓ | ✓ binding-mutation witness | ✗ | ✗ | ✗ | multi-seat works via the concentrator; the ejection split is still unverified |
| QTree (r4, l3) | ✓ (multi-seat via concentrator: 3 seats on one router, lint PASS / sim PASS 13/13) | ✓ | ✓ binding-mutation witness | ✗ | ✗ | ✗ | |
| Tree4 (r4, l3) | ✓ (multi-seat via concentrator: 3 seats on one router, lint PASS / sim PASS 13/13) | ✓ | ✓ binding-mutation witness | ✗ | ✗ | ✗ | |
| Fatfly (4×2) | ✓ | ✓ | ✓ exact stage/channel graph witness | ✗ | ✗ | ✗ | |
| SROTA | ✓ | ✓ | ✓ intent checks plus exact rematerialized topology witness | ✗ | ✗ | ✗ | reference row |
| GEC hybrid | ✓ | ✓ (shared path) | ✓ exact per-wire tap identity witness | ✗ | ✗ | ✗ | |
| Fat-tree (sr4 lc2) | ✓ (multi-seat via concentrator: 3 seats on one router, lint PASS / sim PASS 13/13) | ✓ | ✓ binding-mutation witness | ✗ | ✗ | ✗ |  |
| DragonflyNew | ✓ | ✓ (kwarg fix) | ✓ exact radix/group graph witness | ✗ | ✗ | ✗ | |
| KNCube (radix 3 × 2 dims) | ✓ general intent (StructuredTopologyIntent kncube) | ✓ lint PASS, sim PASS 13/13 from a real KNCube request (measured 2026-11-10) | ✓ exact saved-intent↔graph mutation witness | ✗ | ✗ | ✗ |  native equivalence vs the external Constellation source remains open (operator-owned)

**Multi-instance update (2026-11-10):** the "one instance per agent group" refusal is **gone** — a group with `count=2` compiles, emits two endpoint adapter paths on two distinct routers, and the composed top lints PASS / simulates PASS 13/13. What still blocks L3/L4 for every family is unchanged: no pinned workload has been run through RTL, and no family has been placed.

**L2 update (2026-11-10):** binding conformance is asserted for all 14 families — the parallel session wired "saved topology intent vs compiled bundle" checks into the product checkers with a mutation witness per family (`tests/test_family_bad_design.py`, `BINDING_MUTATIONS` = 13 + SROTA's own; 58/58 green). The open binding-axis gaps are therefore *emission*, not the guard: the multi-instance expansion (emitter patch specified, seat planner green 7/7) and the co-seat concentrator.

**Score: 0/14 production-ready.** 8/14 have L0+L1. 5/14 still lack a connected composed top; KNCube remains harness-only for RTL qualification. Mutation witnesses now check saved-intent↔materialized-topology identity for all 14 families (including KNCube wrap mutation and SROTA semantics); that is graph-identity evidence, not proof of emitted-hardware routing/packet conformance. 14/14 still have zero L3/L4/L5 evidence — **none has carried a pinned workload through RTL with packet/credit/reset accounting.**

## Distance to completion (dependency order)

1. **P3 finish line** — bindings + multi-seat concentrators + per-instance adapters + the selected 74-agent target: the biggest single piece; weeks.
2. **L2 binding guards** — exact request-to-materialized-topology comparison now covers all 14 families with asserted corruption witnesses. Keep native implementation equivalence and runtime route/packet compliance separate from this graph-binding result.
3. **Workload→RTL qualification (L3)** — feed the 17 pinned captures through the composed tops with VC/credit/reset invariants; needs P3 multi-instance support to be exact on the full-size contract.
4. **P9 platform** — operator PDK decision + reset/debug-tap fixes + route/DRC/signoff; currently WNS −4.424 ns sky130A and no signoff path.
5. **P11 release** — clean tree, green matrix re-run (kncube/dragonflynew), pinned reproduction.
6. **KNCube** — general saved intent and graph mutation witness exist; use the operator-owned Constellation fork/source to prove native parameter and routing equivalence before moving past harness smoke.

## The honest percentage

- RTL composition machinery to generate the 14 tops with the current knobs: **done (≈ all 14 emit, 8 simulate)**.
- Verification to a workload binding: **≈ 0%**; L3 remains 0/14.
- Physical/signoff: **blocked on operator + RTL reset/debug-tap fixes + at least one routed run**.
- Release eligibility: **0 (dirty tree, untagged, matrix FAIL recorded)**.

Short answer: we are past *feasibility* (code exists and 14 tops compile/sim) and nowhere near *production* (0/14 across L2-L5; the pinned workload corpus has never touched RTL). The pin-to-hardware gap is weeks of P3/P4/L3 work plus an operator PDK decision; no row is fakeable without breaking the product's own contract.
