# Capability Reclamation Pass (B–E)

**Status:** RECONNAISSANCE COMPLETE — classification only, no code changed.
**Base:** `d878cf5e` (`wave-e/system-performance`, Wave E not yet sealed).
**Scope:** every capability that exists in this repository but is NOT on a
sealed authoritative path, classified by status, target wave, and promotion
cost.

> This pass does not reopen B–E. A seal means *everything claimed inside the
> supported domain is mechanically trustworthy*. It does not mean *everything
> useful in the repository is inside that domain*. B–E were optimized for
> correctness closure; capability that predated them stayed outside. This
> document exists so Wave F consumes what exists instead of rebuilding a
> smaller version of it.

---

## 1. Two registries, one division of labour

There is already a Wave-C classification registry:
`veritx_dse/application/inventory.py` (19 rows). It classifies **execution
surfaces** as `AUTHORITATIVE / MIGRATE / LEGACY_INTERNAL / TEST_ONLY /
DELETE` and answers *"is this reachable from a certified surface?"*

This pass classifies **capabilities** and answers *"what exists, does it
work, what would promotion cost, which wave owns it?"*

The two must not contradict. Where both apply, the Wave-C ledger decides
product reachability and this ledger decides reclamation value.

**Proposed seam (not done in this pass):** extend the existing ledger with
the capability dimension rather than adding a parallel registry module. One
classification authority, two dimensions.

Canonical paths for the sealed plane, used throughout for reachability
checks:

```
application/service.py   SrotaControlPlane          (control plane)
model/topology_artifact.py → backend/bundle.py      (B: fabric truth)
waved/                                              (D: workload truth)
wavee/                                              (E: performance truth)
```

---

## 2. Taxonomy

```
status
  ALREADY_AUTHORITY       on a sealed path and consumed there
  VALID_BUT_DISCONNECTED  works and is tested; not reachable from the sealed plane
  RESEARCH_PROTOTYPE      works but assumption-based / not certified
  SUPERSEDED              replaced by a sealed path
  UNSAFE_INCORRECT        known wrong, or self-quarantined
  THIRD_PARTY_ONLY        vendored tree, no VeriTX adaptation

target            B | C | D | E | F | G

promotion_cost
  BRIDGE_ONLY             wire an existing, tested artifact into a sealed path
  NEEDS_IDENTITY          must gain content-addressed identity/binding first
  NEEDS_VERIFIER          must gain a re-derivation/verification edge first
  NEEDS_SEMANTIC_REWRITE  the model itself must change to fit the sealed model
  DO_NOT_PROMOTE          must not become evidence
```

---

## 3. Method

Every row below was established by four checks, not by reading summaries:

1. the file exists and how large it is (`wc -l`);
2. the candidate's own test suite was **executed** (results in §4);
3. a reachability grep: does anything under `application/`, `waved/`,
   `wavee/`, or `backend/` import it?
4. where a build is implied, whether the build output exists.

---

## 4. The headline finding: there are TWO coherent stacks

The disconnected capability is **not a pile of orphans**. It is a second,
internally coherent, tested stack that predates the sealed one:

```
RESEARCH STACK (Phase 2 / 9 / 14 / 15 / 16 + Timeloop pipeline)
  CanonicalWorkload (workload/canonical.py, Phase 9)
        → MemoryArtifact (core/memory.py ← workload/memory_lowering.py, Phase 14b)
        → Ramulator ReadWriteTrace (Phase 15b)  → Ramulator2 execution
        → Timeline / attribution (workload/timeline.py, Phase 16)
  synthesis/  (Phase 2: MILP + BO + iterative search)
  scripts/    (Timeloop → cycles/energy/area; Megatron TP mapping)

SEALED STACK (B / D / E)
  SrotaControlPlane
        → CompileRequest → FabricArtifact/ResolvedFabric   (B)
        → WaveDWorkload                                     (D)
        → WaveEPerformanceModel                             (E)
```

Reachability is a clean zero, verified this pass:

```
$ grep -rn "MemoryArtifact|memory_lowering|ramulator|topology_ir|deadlock" \
      dse/veritx_dse/{application,waved,wavee}/
(no matches)
```

So the reclamation work is **bridging two stacks**, not reimplementing
missing science. That is a materially cheaper and safer job than the
"build memory/energy/topology from scratch inside F" path.

### Empirical status of the research stack (run this pass)

```
topology_ir + topology_artifact + deadlock_seam + mapping   105 passed, 1 skipped
memory_artifact + memory_lowering + ramulator (unit)        109 passed, 2 skipped
serving (spec/metrics/provenance/liveness/protocol/experiment) 106 passed, 9 skipped
broad DSE suite                                            27 failed / 3150 passed / 41 skipped
```

One caveat on reading those numbers, found while checking them: the
`mapping` in the first line is `test_mapping.py`, which tests the **sealed
Wave-B `MappingArtifact`** — it is *not* evidence for the research-stack
`scripts/mapping_strategy.py`, which has no tests at all (see §10.7). Test
counts are only evidence for the module they actually import.

The broad failed-node set is **identical to the pre-Wave-D baseline** and is
environment-dependent (gitignored trace assets, unbuilt vendored binaries,
report tooling). Two of those failures are themselves evidence:
`test_pipeline_preflight::test_real_repo_vendored_binary_exists` is the
missing Timeloop binary, and the Ramulator skips say *"ramulator backend not
built"*.

---

## 5. Ledger — target B (fabric truth)

| # | Capability | Where | Evidence | Status | Cost | Note |
|---|---|---|---|---|---|---|
| B1 | `TopologyIR`: 7 kinds (`mesh`, `torus`, `ring`, `star`, `switch`, `anynet`, `custom`), explicit links, `expand()`, diameter/stats/ascii, translations to BookSim cfg / `.anynet` / analytical yml / preset | `model/topology_ir.py` (529 L) | `test_topology_ir.py` passes | VALID_BUT_DISCONNECTED | BRIDGE_ONLY + NEEDS_IDENTITY | B materializes **4** families (`MESH`, `TORUS`, `RING`, `CONCENTRATED_MESH`); `_family_of` refuses the rest: *"not materializable in B3.1 … no silent fallback"*. Gap = `star`, `switch`, `anynet`, `custom` + explicit-link graphs |
| B2 | MCLB routing ILP, escape VCs, CDG cycle check, deadlock certificate, route-table export, **BookSim-exact** first-hop replication | `tools/deadlock_routing.py` (481 L) | `test_deadlock_seam.py` passes (in the 105) | VALID_BUT_DISCONNECTED | NEEDS_IDENTITY (+BRIDGE) | CLI-reachable via `SCRIPTS_DIR` = `veritx_dse/tools` (`cli.py:1879`); **not** an evidence type on the fabric artifact |
| B3 | `channel_vc_cdg`: `ChannelVCCDG`, `DeadlockCertificate`, `certify_channel_vc_deadlock`, binding hashes | `verification/channel_vc_cdg.py` | exported from package `__init__`; tests pass | VALID_BUT_DISCONNECTED | BRIDGE_ONLY | **B already names this artifact as its missing evidence** — see below |
| B4 | Flow-Class-Aware Certification Engine | `tools/flow_certifier.py` (483 L) | CLI-reachable (`cli.py:1919`) | VALID_BUT_DISCONNECTED | NEEDS_IDENTITY | separate concern from B3 (flow classes vs channel/VC cycles) |
| B5 | `.anynet` parser | `core/anynet.py` | used by B3, `presets`, tools | ALREADY_AUTHORITY | — | the one-parser invariant; keep |

### B's reclamation is already designed for

`verify_design()` (F1–F8) states its own limit in the emitted evidence text:

```
F1_deadlock_freedom  PASS  "Abstract dependency graph is acyclic"
  detail: "No blocking cycles in the abstract dependency graph. Scope:
           abstract graph only — NOT a (channel,VC) CDG deadlock certificate."
  header: "a full deadlock claim requires the (channel,VC) CDG certificate (PR D+)"
```

B3 is that certificate. Wiring it turns a heuristic-scope PASS into a
(channel,VC)-scope certificate. This is the cheapest real hardening in the
whole pass: the artifact exists, the consumer already declares it, and the
gate vocabulary is already there.

**These two rows are on the critical path for F**, because F's search space
is exactly custom topologies and deadlock-free routing:

```
F searches over topologies      → B1 (custom/anynet must be materializable)
F must not propose deadlocks    → B2/B3 (certificate must be an evidence type)
```

---

## 6. Ledger — target C (control plane)

| # | Capability | Status | Note |
|---|---|---|---|
| C1 | legacy commands / runs / sweeps / results / sqlite index / synthesis commands | LEGACY_INTERNAL (deliberate) | Correct decision. Do not reopen C. F and later enter through `SrotaControlPlane`. |

Nothing to reclaim. The only risk is the converse: treating `LEGACY_INTERNAL`
as "never inspect again" — which is how `synthesis/` came to be scoped out of F.

---

## 7. Ledger — target D (workload truth)

| # | Capability | Where | Evidence | Status | Cost | Note |
|---|---|---|---|---|---|---|
| D1 | `MemoryArtifact` / `MemoryRegion` / `MemoryAccess` / `MemoryPlacement` / `AddressMappingPolicy` + conservation report | `core/memory.py` (668 L) | `test_memory_artifact.py` passes | VALID_BUT_DISCONNECTED | NEEDS_IDENTITY | content-addressed, strict lowering already |
| D2 | `CanonicalWorkload` (Phase 9) + serve-level canonicalization + backend lowering | `workload/canonical.py` (719 L), `serve.py`, `lowering.py` (551 L) | consumed by the whole research stack | VALID_BUT_DISCONNECTED | NEEDS_SEMANTIC_REWRITE | a *parallel* workload authority to `WaveDWorkload`; must not become a second one — translate, don't adopt |
| D3 | Timeline / attribution (Phase 16): `OpRecord`, `ServiceBinding`, `Attribution`, `build_timeline` | `workload/timeline.py` (487 L) | Phase 16 handoff | RESEARCH_PROTOTYPE | NEEDS_SEMANTIC_REWRITE | Wave E has *execution*; this has *bottleneck attribution*. Different capability, not a duplicate |
| D4 | collective packet generation (`ring_allreduce_packets`, allgather, reducescatter, alltoall, broadcast, p2p) | `simulation/model_to_trace.py` (444 L) | — | SUPERSEDED for the D path by `waved/traffic.py` | DO_NOT_PROMOTE (D) | Wave D's collective equations + conservation laws + oracles replace this; keep for the legacy run path only |
| D5 | **Megatron TP mapping**: Regime A (tiles ≤ heads) / Regime B, head-group all-reduce, global TP all-reduce, tile↔head assignment | `scripts/mapping_strategy.py` (197 L) + `scripts/distribute.py` | **no test coverage**; only consumer is `run_spatial_pipeline.py` (whose Timeloop binary is unbuilt) | RESEARCH_PROTOTYPE | NEEDS_IDENTITY + NEEDS_VERIFIER + NEEDS_SEMANTIC_REWRITE | **the model-shape → operation synthesis source.** Zero `veritx_dse` imports (pure stdlib + `tl_ir`/`distribute`): it is not a package citizen, so it has no identity, no artifact, and no verifier today |
| D6 | serving semantics: TP/PP/DP/EP, MoE, multi-instance, prefill/decode disaggregation, remote KV, CXL, PIM | `third_party/llmservingsim/serving/core/` (`scheduler` 576 L, `kv_cache_manager` 563, `block_pool` 522, `memory_model` 545, `pim_model` 186, `router` 327, `trace_generator` 1982, `config_builder` 928) | vendored, with a VeriTX seam `veritx_certified.py` (120 L) | THIRD_PARTY_ONLY | NEEDS_SEMANTIC_REWRITE | D's residual list ("multi-instance DEFERRED", "expert routing UNSUPPORTED") is largely *translation*, not invention |

---

## 8. Ledger — target E (performance truth)

| # | Capability | Where | Evidence | Status | Cost | Note |
|---|---|---|---|---|---|---|
| E1 | Ramulator 2.1 standalone backend: drain-aware verdicts, typed `MemoryEvidence`, coalesced-write reconciliation | `simulation/ramulator.py` (535 L) | 17 passed / 2 skipped (*"backend not built"*) | VALID_BUT_DISCONNECTED | NEEDS_BUILD + NEEDS_IDENTITY | vendored `third_party/ramulator2`, **not built**. Closes E's `memory latency UNSUPPORTED` honestly |
| E2 | `MemoryArtifact → Ramulator ReadWriteTrace` lowering with conservation asserts | `workload/memory_lowering.py` (627 L, Phase 14b) | `test_ramulator_lowering.py` passes | VALID_BUT_DISCONNECTED | NEEDS_IDENTITY | this is the actual seam Wave E would consume |
| E3 | Timeloop pipeline: HF config → Megatron TP shapes → Timeloop → cycles/energy/area → traffic matrix | `scripts/run_spatial_pipeline.py` (+ `tl_ir`, `timeloop_runner`, `energy_report`, `timeloop_stats`, `timeloop_to_matrix`) | binary missing (`test_pipeline_preflight` fails) | VALID_BUT_DISCONNECTED | NEEDS_BUILD + NEEDS_IDENTITY | `run_timeloop_pipeline.py` is RETIRED (stub) → use `run_spatial_pipeline.py` |
| E4 | Accelergy NoC energy bridge (BookSim/ASTRA → NoC energy) | `scripts/noc_energy_bridge.py` (354 L) | — | RESEARCH_PROTOTYPE | NEEDS_IDENTITY | **Accelergy is not vendored at all**; this needs a third vendoring decision |
| E5 | BookSim power instrumentation (`buffer_monitor`, `switch_monitor`, `power_module`) | `third_party/booksim2/src/power/` | compiled objects present | THIRD_PARTY_ONLY | NEEDS_SEMANTIC_REWRITE | upstream BookSim power code; no VeriTX evidence binding |
| E6 | analytical serving execution (congestion-aware / congestion-unaware) | vendored `astra-sim/astra-sim/network_frontend/analytical`; sealed refusals in `backend/analytical.py` | `build/` contains **only** `astra_booksim2` | VALID_BUT_DISCONNECTED (needs build) + sealed path refuses by design | NEEDS_BUILD + NEEDS_IDENTITY | see §9 correction 3 — the sealed module is a *refuser*, not a disabled engine |
| E7 | network saturation / injection-rate frontier measurement | `simulation/booksim.py`, `reports/reports.py`, `tools/flow_certifier.py`, docs | research docs only | RESEARCH_PROTOTYPE | NEEDS_VERIFIER | E's `throughput UNSUPPORTED` conflates *network saturation* (measurable today) with *request-serving throughput* (needs a denominator contract) |
| E8 | area / power / timing estimates: `estimate_router_area`, `estimate_link_area`, `estimate_nic_area`, `estimate_fabric_area`, `estimate_dynamic_power` | `reports/reports.py` (532 L) | not imported by the sealed plane | RESEARCH_PROTOTYPE | NEEDS_IDENTITY | calibrated to published CMN-600/DAC figures — provenance is literature, not measurement |
| E9 | LLMServingSim as reference/validation model | `third_party/llmservingsim/` | vendored | THIRD_PARTY_ONLY | NEEDS_SEMANTIC_REWRITE | use as *comparison*, never as truth; it has vLLM benchmark validation |

---

## 9. Ledger — target F (optimization) and G (RTL)

| # | Capability | Where | Status | Cost |
|---|---|---|---|---|
| F1 | MILP topology synthesis v2 | `synthesis/milp_topology_v2.py` (582 L) | LEGACY_INTERNAL | NEEDS_SEMANTIC_REWRITE |
| F2 | Bayesian-optimization synthesizer | `synthesis/bo_synthesizer.py` (690 L) | LEGACY_INTERNAL | NEEDS_SEMANTIC_REWRITE |
| F3 | iterative synthesizer + fabric-compiler bridge | `synthesis/iterative_synthesizer.py` (508 L), `bridge.py` (150 L), `compiler.py` (384 L) | LEGACY_INTERNAL | NEEDS_SEMANTIC_REWRITE |
| F4 | requirements evaluator + event objective + result schema | `synthesis/evaluator.py` (889 L), `event_objective.py` (166 L), `results.py` (153 L) | LEGACY_INTERNAL | NEEDS_SEMANTIC_REWRITE |
| F5 | traffic-aware Pareto evaluation | `tools/multi_workload_pareto.py` (862 L) | VALID_BUT_DISCONNECTED | NEEDS_IDENTITY (partly absorbed into `synthesis/evaluator.py`) |
| G1 | UVM testbench generator | `verification/uvm_gen.py` (505 L) | RESEARCH_PROTOTYPE | (G) NEEDS_VERIFIER |
| G2 | RTL artifacts: CDC, mot_htree, spec translation | `rtl/` | RESEARCH_PROTOTYPE | (G) NEEDS_VERIFIER |
| G3 | RTL generation pipeline | `scripts/rtlgen/` | RESEARCH_PROTOTYPE | (G) NEEDS_VERIFIER |

**F's whole search stack is `LEGACY_INTERNAL`** (3522 L in `synthesis/`), and
that is correct — it drives handcrafted BookSim configs and direct
subprocesses, exactly what B sealed. F must re-enter through the control
plane. But its *search science* (MILP, BO, objectives) is real and should be
re-used behind the sealed seam rather than rewritten.

---

## 10. Corrections to the brief (found while verifying)

1. **`mapping_strategy.py` is not in the package.** It lives at
   `tracks/t3-topology/scripts/mapping_strategy.py` (197 L), i.e. inside the
   tree the Wave-C ledger already classifies *"research-only, not product"*.
   That does not reduce its value, but it changes the promotion cost: it has
   no package identity, no imports from `veritx_dse` beyond `distribute`.
2. **B materializes four families, not three:** `MESH`, `TORUS`, `RING`,
   `CONCENTRATED_MESH`. The disconnected kinds from `TopologyIR`'s seven are
   `star`, `switch`, `anynet`, `custom` (plus arbitrary explicit-link graphs).
3. **`backend/analytical.py` is a refuser, not a disabled engine.** It
   validates and then refuses with structured reasons: the artifacts carry
   channel width in **bits** and latency in **cycles**, while the analytical
   engines consume **GB/s** and **ns**, and no clock period / bandwidth-unit
   derivation exists. `capabilities.py` reporting
   `lowering: METADATA_ONLY, execution: UNSUPPORTED` is therefore *honest*,
   not an accidental regression. The historical "analytical golden works"
   evidence belongs to the vendored ASTRA-sim analytical frontend, which is
   present as source but **not built** in this checkout (`build/` contains
   only `astra_booksim2`).
4. **`memory_miss_model.py` is self-quarantined.** Its docstring states it is
   `EXPERIMENTAL / ASSUMPTION_BASED`, that `bank_contention` implements a
   topology-invariant M/D/1 scalar which measured **+0.0 cycles on real
   traces**, and that the `compare --memory` path is deprecated and refused
   fail-closed. Status `UNSAFE_INCORRECT`, cost `DO_NOT_PROMOTE`. Memory
   reclamation runs through **E1/E2 (Ramulator + MemoryArtifact)**, not here.
   This is a good example of the repository policing itself.
5. **Build/vendoring gaps, verified:** Ramulator2 vendored but not built;
   Timeloop vendored but not built; **Accelergy not vendored**; ASTRA
   analytical frontend present but not built. Four of the ten headline
   reclamation targets are blocked on a *build or vendoring* step, not on
   science.
6. **`run_timeloop_pipeline.py` is RETIRED** and now a stub pointing at
   `run_spatial_pipeline.py`.
7. **A name collision worth knowing about.** `test_mapping.py` does *not*
   test `scripts/mapping_strategy.py`. It tests
   `veritx_dse/model/mapping.py`, which is **Wave B2's `MappingArtifact`**
   ("which hardware AgentInstance hosts each logical workload rank") — a
   sealed module with a completely different question. So there are two
   "mapping" modules at opposite ends of the trust boundary, and the tested
   one is the sealed one. Any promotion of D5 should rename on the way in;
   reusing the name would make the sealed/unsealed distinction unreadable.
   (This pass caught it because an evidence attribution looked convenient
   and turned out to be false — the same failure mode as a trusted
   relationship.)
8. **Stale error text in `_family_of`.** The refusal message reads
   `"not materializable in B3.1 (supported: mesh, torus, concentrated_mesh)"`,
   but the mapping five lines above it also admits `RING`. The message
   under-reports the supported set. Same class of defect as the stale
   `inventory.py` row: a hand-maintained list drifting from the code it
   describes.

### Stale text found in the existing ledger

`application/inventory.py`, `synthesis/` row: `"replacement": "none in Wave C
(synthesis science is Wave E)"`. Wave E is *performance*; synthesis science is
**F**. One-line fix, not done in this pass (classification only). The pass
found exactly one stale row out of twenty.

---

## 11. Recommended reclamation order

Ordered by promotion cost, not by appeal.

**Tier 1 — bridge only, artifact exists and passes tests**

| Order | Item | Why first |
|---|---|---|
| 1 | B3 + B2 → sealed deadlock evidence | the sealed gate already names the missing artifact; turns an abstract-graph PASS into a (channel,VC) certificate |
| 2 | B1 → `TopologyIR` anynet/custom into `FabricArtifact` | unblocks F's custom-topology search; otherwise F searches 4 families and invents the rest |
| 3 | E2 + E1 → `MemoryArtifact` → Ramulator → Wave-E memory timing | needs one build; closes E's `memory latency UNSUPPORTED` with a qualified backend instead of a formula |
| 4 | D5 → model-shape → Wave-D operation synthesis | largest *semantic* gap (model → ops), and the only Tier-1 item with **no tests** today |

**Tier 2 — needs a build or a vendoring decision**

```
E3 Timeloop        (vendored, unbuilt)   → compute cycles/energy/area
E4 Accelergy       (NOT vendored)        → NoC energy
E6 ASTRA analytical(vendored, unbuilt)   → congested/unaware cross-check
```

**Tier 3 — needs semantic rewrite**

```
D6 serving semantics (multi-instance, P/D, MoE) → Wave-D declarations
E9 LLMServingSim as reference/validation
D3 attribution (Phase 16) → Wave-E reporting
E7 saturation evidence → an explicit evidence type
```

**Tier 4 — do not promote**

```
memory_miss_model.bank_contention   (measured wrong: +0.0 cycles)
abstract-graph F1 as a deadlock proof (keep as ASSUMPTION scope)
```

---

## 12. The single strongest recommendation

**Reclaim Tier-1 items 1–2 before Wave F starts.**

F's search space *is* custom topologies and deadlock-free routing. Starting F
without B1/B2/B3 would force it to either (a) search only the four
materialized families, or (b) re-derive deadlock reasoning that already
exists, tested, in `deadlock_routing.py` + `channel_vc_cdg.py`, while its
results could not be certified as deadlock-free at (channel,VC) scope
anyway — because that certificate is not an evidence type on the fabric
artifact.

That is the difference between:

```
existing repo capability → RECLAIM → B/D/E → F
```

and

```
ignore everything old → rebuild smaller versions inside F
```

---

## 13. What this pass did NOT do

- No code changed. No tests added. No registry module added.
- Did not classify: `third_party/ns3`, `htsim` frontends, `profiler/`,
  `bench/`, most of `verification/`, the `rtl/` internals, `acceptance/`,
  `reports/` beyond E8, `docs/` history.
- Did not attempt to build Ramulator2/Timeloop/ASTRA-analytical (that is a
  Tier-2 decision, and a build is not a classification).
- Did not begin Wave F.

## 14. Battery (unchanged; no code changed)

```
broad DSE suite         27 failed / 3150 passed / 41 skipped
                        failed-node set IDENTICAL to the pre-Wave-D baseline
candidate suites        topology/artifact/deadlock/mapping  105 passed, 1 skipped
                        memory/ramulator (unit)            109 passed, 2 skipped
                        serving (legacy)                   106 passed, 9 skipped
git diff --check        clean
```
