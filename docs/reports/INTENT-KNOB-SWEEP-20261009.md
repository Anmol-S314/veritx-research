# Intent/control sweep — 2026-10-09

## Result and limits

A finite **167-case** isolated sweep varied supported controls, invalid boundaries, and selected interactions. Final results:

| Outcome | Cases |
|---|---:|
| EVALUATED — all four analyses | 70 |
| COMPILED — not executed | 44 |
| UNSUPPORTED | 25 |
| REFUSED during request parsing | 28 |
| Unexpected failure / timeout | 0 |

The 70 executed cases produced **280 EVALUATED analysis observations**: network completion, system makespan, communication exposure, and per-rank completion. These are different model outputs, not durations to add together. Empty requirements are not a requirements PASS.

Evidence: `runs/knob-sweep/20261009-final/results.json`, with per-case request, certificate, compiled artifacts, evaluation plan, simulator output/evidence and worker log alongside it. Runner: `tracks/t3-topology/dse/tools/sweep_intent_knobs.py`.

No live project drafts or historical runs were edited. No branches/commits, external AI calls, or runtime binary rebuilds. This is not exhaustive knob coverage, multi-seed robustness, protocol conformance, or hardware signoff. The existing running gateway was not restarted; the source repairs were exercised by fresh isolated workers.

## Coverage

| Area | Witnesses and interpretation |
|---|---|
| VC derivation | Dependency graphs derive **1–8 VCs**; requesting a ninth derived VC refuses. These dependency cases above one VC compile but preflight blocks their class-specific subsets: compilation is not execution support. There is no authorable v4 `vc_count` override. |
| Executed VC counts | **1, 2, 4, 6, 8** through qualified SROTA/GEC configurations. No measured 3/5/7-VC claim. |
| Link width | 8/16/32/64/128/256/512 bits, plus invalid 0/7. Executed 32/64/128/256. Small widths that cannot hold the required header refuse; 16/512 were compile-only witnesses. |
| Arbitration | Default, `islip`, `round_robin`, `rr` execute; unknown policy refuses. |
| RCU / multicast | Neutral settings execute. RCU enable, hardware multicast groups, and even explicitly authored zero multicast setup cost refuse where no canonical implementation artifact exists. No replacement with ordinary unicast. |
| Generation settings | Empty/JSON/SystemVerilog+UVM format choices and obfuscation 0/1/3 compile; unknown formats and negative obfuscation refuse. This sweep did not generate or execute the resulting RTL/UVM products. |
| SROTA | Row, row+column shape policy, rank/Valiant; D/T/C plane boundaries; drop/telemetry latency, telemetry period, side-buffer enable/watermark, row/column MECS, island columns. Invalid combinations refuse. Plane-C compilation is not a class/plane/VC execution proof. |
| GEC | k3/c2/d2, k4/c2/d3, k5/c2/o2/d2, k5/c2/d4 execute all four analyses. k8/d7 still correctly refuses **14 required VCs > 8**. |
| Topology interactions | FlatFly, GEC-hybrid, SROTA, odd torus and explicit graph, each crossed with three width/allocator combinations: **15 fully evaluated cases**. |
| Clock / width | 250/500/1000/2000 MHz × 64/256-bit links execute. Zero/negative clock values refuse. Cycles alone do not establish heterogeneous timing or physical frequency scaling. |
| Agent interfaces | Protocol labels, data/address widths, clock/power labels. Invalid width boundaries refuse. Protocol labels, including an arbitrary string, compile; this is not AXI/CHI/APB transaction verification. |
| Physical context | Process-node labels, default widths, power-domain count. Multiple physical power domains refuse because isolation/level-shifting semantics are absent. Process labels do not establish area/power/timing estimates. |
| Workload payload | Small/divisible payloads execute; zero and non-divisible collective payloads refuse. Workload is not resized silently. |
| Address regions | Single/adjacent/disjoint/unaligned regions, containment/overlap, 64-bit top boundary, 8/32/64-bit target interfaces, missing targets and multi-instance groups. See below. |
| Non-authorable knobs | Direct `vc_count`, `input_buffer_depth`, `credit_return_latency` fields refuse in v4 rather than silently becoming controls. |

### Selected execution witnesses

| Case | Attached endpoints / routers / native capacity | Active TP | VCs | Network cycles |
|---|---:|---:|---:|---:|
| SROTA32 row | 32 / 16 / 32 | 32 | 1 | 12,040 |
| SROTA32 row+column | 32 / 16 / 32 | 32 | 2 | 12,035 |
| SROTA32 rank/Valiant | 32 / 16 / 32 | 32 | 4 | 12,035 |
| GEC k3/c2/d2 | 16 / 9 / 18 | 16 | 4 | 1,478 |
| GEC k4/c2/d3 | 16 / 16 / 32 | 16 | 6 | 1,479 |
| GEC k5/c2/o2/d2 | 16 / 25 / 50 | 16 | 4 | 1,478 |
| GEC k5/c2/d4 | 16 / 25 / 50 | 16 | 8 | 1,479 |

GEC cases retain sixteen authored agents/TP ranks: excess concentrator seats are idle capacity, not additional active ranks. These are different configurations, not an optimization ranking.

## Address-region findings

- Valid adjacent and disjoint half-open ranges compile; five address cases also execute collective analyses.
- Overlap/contained overlap, out-of-range targets, interface-width overflow and 64-bit address-domain overflow refuse.
- The final legal byte of the 64-bit domain is accepted; exceeding it is not.
- Multi-instance target groups refuse because no canonical range-selection/interleave policy exists.
- Unaligned ranges are structurally accepted; there is no invented alignment requirement.
- Artifacts record each region's start, last included address, exclusive end and target endpoint, preserving IDENTITY forwarding and ERROR for unmatched addresses.

**Collectives do not issue memory-address transactions.** These results verify structural decode intent and canonical validation, not HBM accesses, memory performance, protocol transactions, or synthesized-decoder execution.

## Clock-domain findings

V4 clock/power names are labels, not typed heterogeneous-clock or power-gating machinery. Changing those labels preserved the same **2,775 network cycles / 4,010 system makespan cycles** in this witness. That neutrality is not CDC behavior or power-state evidence.

Separate focused gates exercised typed V5 clock-source/domain exact-frequency and rational-divider laws, reset dependencies, crossing compatibility/refusals, and clocked asynchronous-FIFO reference behavior. These establish architectural/reference-model properties, not metastability, physical CDC/RDC/UPF signoff, or full heterogeneous-clock BookSim/ASTRA product execution. V5 product-boundary/compiler/design-binding gates were included rather than treating domain labels as a substitute.

## Defects found and repaired

### Invalid sweep identities — harness only

The initial harness mutated `to_dict()` documents while retaining serialized design/guardrail hashes. Those hash-mismatch refusals were invalid knob evidence. Snapshot construction now copies the document and drops only the computed identity assertions; the canonical parser recomputes identities for each new request. No product hash guard was bypassed. A regression checks every generated input for stale identities. `20261009-main/` is retained but superseded, not counted here.

### ASTRA spare-node namespace — two responsible mechanisms

Four GEC cases initially measured network traffic successfully but failed all three system analyses on apparently foreign ranks.

1. `model/family_registry.py` read a nonexistent GEC config `size` field, falling back to attached-agent count. The native constructor actually computes **k² × c** terminal nodes. The registry now follows that constructor, not an attachment-based guess.
2. `backend/astra_execution.py` compared native `Sys.id` reports against attached-endpoint count instead of the separately declared native namespace. It now checks against `machine.astra_sys_count`, while preserving the attached-endpoint scope of the existing idle-endpoint evidence field.

Every native non-participant is still checked for unrequested communication; out-of-fabric ranks, autonomous traffic, missing participants, zero participant completion and silent non-simulation remain errors. Regression tests prove spare nodes can be idle but cannot carry extra communication, and rogue nodes still refuse.

The four corrected GEC witnesses replayed **all four analyses EVALUATED**, without adding agents, changing TP, dropping observation fields, changing routing, or weakening certificates.

Historical failure evidence remains in `20261009-valid-inputs/` and `20261009-idle-node-replay/`; `20261009-gec-fixed/` isolates the successful replay. Final cohort is `20261009-final/`.

## Verification

- Focused combined gate: **644 passed, 2 skipped** across knob regressions, family registry, ASTRA machine/adapter/multiclass/hybrid, address decode, domain intent, clocked FIFO, exact clock parsing, router behavior and V5 boundaries.
- Final sweep: **167 cases; 280 successful analysis observations; no unexpected failures/timeouts**.
- `git diff --check` passed.
- Pytest still warns that the `timeout` plugin option is unavailable. Sweep workers enforce their own 150-second process-group deadline, 30-second backend budgets and 2-GiB address-space limit.

Remaining limits include class-specific VC subsets, Plane-C product execution, full typed-domain backend consumption, memory transaction workloads and hardware-generation validation. Earlier larger-scale refusals/timeouts in `CONFIG-EXECUTION-SWEEP-20261008.md` are not superseded by these smaller witnesses.
