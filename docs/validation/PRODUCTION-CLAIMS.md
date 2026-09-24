# VERITX Production Claim Inventory

Status: DRAFT v1 (baseline audit at `prod/production-readiness` = `cf626566a99be7a2b8fbd4f2ebff1ef01deb62b5`)

This document inventories every major product claim currently made or implied
by VERITX and classifies its validation status. It exists so that no claim can
be shown in the frontend, in a report, or in this repository's prose without an
explicit, recorded authority.

## Status vocabulary (no generic PASS)

| status | meaning |
|--------|---------|
| `VALIDATED` | an independent authority (hand arithmetic, different engine, or executed-route observation) confirms the claim inside an explicitly declared domain |
| `PARTIALLY_VALIDATED` | validated for a sub-domain; the limit is recorded |
| `INTEGRATION_ONLY` | the component executes and produces output; no independent authority has confirmed its semantics |
| `NOT_ESTABLISHED` | the claim has no independent authority; it must not be certified |
| `UNSUPPORTED` | VERITX does not model this at all; any display would be fabrication |

## Authority classes (from validation/README.md)

`hand_calculated` and other-engine authorities (`rtl`, `ramulator`, `hardware`)
are **independent**. `standalone_booksim` against the canonical path is
**semi_independent** (shared engine): it can catch projector defects, not
BookSim-internal defects. This distinction is preserved everywhere below.

---

## Claim inventory

### Compilation and fabric derivation

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-01 | intent compilation → canonical `CompileRequest`/`CompileRequestV3` | PARTIALLY_VALIDATED | schema validation + identity tests (`test_design_intent_identity.py`); no external authority | internal-consistency only |
| C-02 | topology derivation (mesh presets, AnyNet) | PARTIALLY_VALIDATED | corpus V04 monotonicity + hand-route checks on small meshes | large/irregular topologies not independently checked |
| C-03 | mapping artifact | INTEGRATION_ONLY | `validate_against` only | no independent mapping oracle exists |
| C-04 | agent attachment | INTEGRATION_ONLY | `validate_against` only | same |
| C-05 | address decode | INTEGRATION_ONLY | `validate_against` only | same |
| C-06 | routing intent → resolved route (router-level) | PARTIALLY_VALIDATED | corpus hand-route (V01/V02/V07–V10), F-0002 documents the +1 ejection convention | identity, not optimality |
| C-07 | VC assignment | PARTIALLY_VALIDATED | fail-closed authoring/persistence (`a0b934b6`); CDG/deadlock tools exist | deadlock-freedom proof not exercised end-to-end on production fabrics |
| C-08 | deadlock freedom | PARTIALLY_VALIDATED | `verification/channel_vc_cdg.py`, `protocol_vc.py` | formal track exists (t4-formal) but is not wired into production corpus |
| C-09 | packetization / packet format | PARTIALLY_VALIDATED | `workload_lowering_conservation` ring oracle (V09/V10) exact | ring ALLREDUCE only; other collectives not yet oracle-checked (§11 program) |
| C-10 | collective lowering (ALLREDUCE ring) | VALIDATED (network-level) | independent ring oracle: messages/bytes/flits/packets exact (V10) | see C-16 scope note |
| C-11 | collective lowering (ALLGATHER / REDUCESCATTER / ALLTOALL / BROADCAST) | INTEGRATION_ONLY | executes; no per-collective independent oracle | §11 audit required before any upgrade; F-0004 precedent shows RING was wrong once |
| C-12 | multicast semantics | NOT_ESTABLISHED | none | no independent multicast oracle |
| C-13 | multi-plane semantics | NOT_ESTABLISHED | none | production reachability itself unproven |

### Network execution (BookSim)

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-14 | BookSim packet/flit conservation | VALIDATED | V02/V09/V10 conservation checks exact; prepared-input v3 binds `expected_flits` | strongest currently qualified path |
| C-15 | BookSim `completion_cycles` | VALIDATED (post F-0001) | `Completion time is` (last-ejection) parser; window-invariance regression; standalone parity exact | F-0001 fixed the sampling-window artifact |
| C-16 | collective semantics of network traffic | PARTIALLY_VALIDATED | ring law conformance (V09/V10) | **NETWORK-LEVEL COLLECTIVE SEMANTICS ONLY**: no chunk_id / reduction ownership / RS-then-AG data semantics. Do not claim full reduction-data semantics |
| C-17 | executed routes equal resolved routes | PARTIALLY_VALIDATED | P0.10 closed (`c2748f9a`/`bd973e6c`): the fork's first-hop dump is compared destination-by-destination against the canonical table (coverage, exact next-router equality, malformed/dump refusal) → `EXECUTED_ROUTE_OBSERVED` + `route_dump_sha256` in evidence v3 | **first-hop scope only**: the fork dumps a first-hop table; path identity beyond the first hop is not observed. Covered for mesh-DOR and AnyNet. Until full-path observation exists, this stays PARTIALLY_VALIDATED |
| C-18 | saturation / contention behavior | NOT_ESTABLISHED | F-0003 shows completion is injection-schedule-bound at low pressure; departure regime unmeasurable in current trace model | §15 sweep program required |

### Memory (Ramulator)

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-19 | Ramulator memory behavior | PARTIALLY_VALIDATED | integration battery 16/16 (drain, backpressure, replay determinism, locality/bank sensitivity) | qualified within battery scope; not coupled to production network runs |

### RTL

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-20 | RTL executes canonical traces (injection/ejection conservation) | VALIDATED (in domain) | V06–V10 `rtl_execution_conservation`, independent engine | small meshes only |
| C-21 | RTL-calibrated completion parity | PARTIALLY_VALIDATED | V06–V10 `rtl_completion` exact on corpus | calibrated hop-equivalent is path LENGTH, not route identity |

### ASTRA-Sim

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-22 | ASTRA runtime executes VERITX projections | VALIDATED (execution only) | real binary runs on `astra_tiny` fixture, rc=0, cycles>0 | runtime gate PASS |
| C-23 | ASTRA absolute cycle numbers | **NOT_ESTABLISHED** | none | aggregate 30,010,310 c / exposed 30,003,310 c unexplained (see below). Must not enter any scientific comparison or be shown as certified |
| C-24 | ASTRA projection (ET generation) | INTEGRATION_ONLY | `test_astra_projection.py` | fixture-based; no timing oracle |
| C-25 | ASTRA qualification domains (P2P / ring / compute+comm / multi-round / serving / MoE) | NOT_ESTABLISHED | none | §19 program required |

**F-ASTRA-0001 (open investigation).** The production ASTRA result shows
`exposed_comm = 30,003,310` and the tiny fixture shows `30,310`. The delta is
`30,000,000` — an exactly round dominant constant added to a small residual,
which is the signature of a default / horizon / configuration term, not
network physics. Cause unknown. Instrumentation required (§17). Do not change
parameters until understood.

### LLMServingSim / serving

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-26 | canonical serving integration executes | VALIDATED (execution only) | real multi-instance runs | liveness diagnostics exist |
| C-27 | TP / DP / EP / MoE semantics | INTEGRATION_ONLY | unit-level; no independent expected-operation-table comparison | §20 S2 required |
| C-28 | scheduling semantics (batching, prefill/decode, retirement) | INTEGRATION_ONLY | vLLM-modeled scheduler; no hand-checkable-trace validation | §20 S1 required |
| C-29 | serving round → ASTRA submission correspondence | INTEGRATION_ONLY | runtime ledger exists; dispatched-instance-must-have-execution-evidence rule not enforced corpus-wide | §20 S3 required |
| C-30 | TTFT / latency definitions | NOT_ESTABLISHED | definitions not independently verified | must be verified before display as science |
| C-31 | multi-instance liveness | PARTIALLY_VALIDATED | no-progress diagnostics + long-run cases | production-like corpus runs not yet executed |
| C-32 | TTFT / throughput / latency **numbers** | NOT_ESTABLISHED | depends on C-23 (ASTRA timing) + C-27..C-30 | may be shown only as measured-by-engine, never certified |

### Model support (W1 pipeline traversal)

| model | config present | traverses canonical pipeline | status |
|-------|----------------|------------------------------|--------|
| Llama-3.1-8B | yes (`meta-llama`) | to be proven | INTEGRATION_ONLY until W1 run |
| Llama-3.1-70B | yes | to be proven | INTEGRATION_ONLY until W1 run (practicality limit to record) |
| Qwen3-32B | yes | to be proven | INTEGRATION_ONLY until W1 run |
| Qwen3-30B-A3B (MoE) | yes (`Qwen3-30B-A3B-Instruct-2507`) | to be proven | INTEGRATION_ONLY until W1 run |
| Mixtral-8x7B | yes (`mistralai`) | to be proven | INTEGRATION_ONLY until W1 run |
| Phi-mini-MoE | yes | out of corpus scope | recorded, not claimed |

Profiler data exists for RTXPRO6000 × {Llama-3.1-8B, Qwen3-32B, Qwen3-30B-A3B} × bf16 × {tp1, tp2} — provenance via `profiler/` pipeline (meta.yaml). `HARDWARE_CALIBRATION: COMPONENT_CALIBRATED` at best; never `HARDWARE_MEASURED` for full runs.

### Optimizer

| # | claim | status | authority | notes |
|---|-------|--------|-----------|-------|
| C-33 | optimizer objective ranks candidates by network physics | PARTIALLY_VALIDATED | F-0001 fix restored meaning of `completion_cycles`; F-0003 limits what it can rank at low pressure | packetization-dominated regime documented |
| C-34 | Pareto selection / eligibility | PARTIALLY_VALIDATED | explicit eligibility rule; Studio contract tests | eligibility rule itself has no independent check |
| C-35 | multi-workload Pareto | INTEGRATION_ONLY | `multi_workload_pareto.py` | no independent oracle |

---

## Registry of displayed metrics (§3 contract)

Every frontend-displayed metric must resolve to a row here or to a new row
added by a reviewable commit. Current registry:

| metric | definition | unit | producer | validated by | status | limitations |
|--------|-----------|------|----------|--------------|--------|-------------|
| `completion_cycles` | last-ejected-flit cycle | cycles | qualified BookSim execution | ring oracle, standalone parity, RTL parity, conservation | QUALIFIED_IN_BOOKSIM_DOMAIN | low-pressure regime (F-0003); trace injection ≤1 pkt/cycle |
| `sample_window_cycles` | BookSim sampling window | cycles | same | diagnostic only | never latency | F-0001 |
| `latency_avg` | mean packet latency | cycles | same | V01 hand arithmetic | QUALIFIED_IN_BOOKSIM_DOMAIN | — |
| packet/flit counts | injected vs delivered | count | same | conservation + ring oracle | QUALIFIED | — |
| route identity (first hop) | `(src router, dst) → next router` executed vs resolved | — | qualified BookSim execution + `route_observation.py` | destination-aware first-hop dump comparison (P0.10, `c2748f9a`) | EXECUTED_ROUTE_OBSERVED (first-hop scope) | path beyond first hop not observed; mesh-DOR/AnyNet covered |
| ASTRA `aggregate_cycles` | ASTRA-reported total | cycles | ASTRA-Sim | none | NOT_ESTABLISHED | F-ASTRA-0001 |
| ASTRA `exposed_comm_cycles` | ASTRA-reported exposed comm | cycles | ASTRA-Sim | none | NOT_ESTABLISHED | F-ASTRA-0001 |
| serving TTFT / latency | engine-reported | — | LLMServingSim | none | NOT_ESTABLISHED (definitions unverified) | C-30 |
| memory latency/bandwidth counters | Ramulator counters | — | Ramulator2 | integration battery | QUALIFIED_IN_BATTERY_SCOPE | not coupled to network runs |

## Upgrade paths (what would change a status)

1. **C-17 → VALIDATED**: extend route observation beyond the first hop
   (full-path identity), per §14's original intent; first-hop closure landed
   in `c2748f9a`/`bd973e6c`.
2. **C-23 → QUALIFIED_<domain>**: §16 cycle-accounting + F-ASTRA-0001 root cause
   + preregistered-tolerance agreement (§24, §57).
3. **C-11 → VALIDATED per collective**: §11 independent audit, implementation
   under test never used as its own oracle.
4. **C-27..C-32**: §20 S1/S2/S3 + §21 liveness corpus + §22 matrix.
5. **C-18**: §15 saturation sweeps (requires sub-cycle/burst injection model —
   a known model limitation, recorded, not hidden).
