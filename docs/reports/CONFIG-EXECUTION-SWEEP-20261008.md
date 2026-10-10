# Configuration execution sweep — 2026-10-08

**Follow-up:** [ASTRA hybrid integration](ASTRA-HYBRID-INTEGRATION-20261009.md)
corrects the ASTRA-source diagnosis below. Rebuilding the already-configured
canonical fork and fixing the field-check source now makes the exact r04 and
64-endpoint GEC-hybrid cases complete all four analyses. This report retains
its historical sweep outcomes; those failures were not rewritten.

## Scope and evidence

No AI/provider requests. No live draft edits, branches or commits.

Executed **83 finite configuration witnesses**: all **21 shipped presets**,
explicitly labelled canonical carrier copies of the four frozen-v2 presets,
all 16 selectable topology entries, and SROTA size/mode witnesses. This is not
an exhaustive Cartesian parameter sweep or a robustness/optimality result.

- Runner: `tracks/t3-topology/dse/tools/sweep_product_configs.py`
- Initial network-only discovery: `runs/config-sweep/20261008-initial-network/`
- Main four-analysis run: `runs/config-sweep/20261008-after/`
- Follow-up/replay directories: `runs/config-sweep/20261008-*/`
- Combined findings: `runs/config-sweep/20261008-summary.json`
- Each completed worker retains request, certificate, simulator inputs,
  plan, raw evidence, result and log. Timeout workers retain stack samples.

The combined result retains older system failures when a later network-only
replay succeeds: a successful network result does **not** erase ASTRA failures.
There are **217 successful analysis observations**, 56 typed unsupported
analysis observations and six ASTRA timeout observations in the combined
matrix. Case categories: 55 evaluated, 16 unsupported, four frozen-v2
compile-only, two certificate-invalid, two timed out, two with failed system
analyses, one partial, and one invalid-intent refusal.

### Reproduce

```sh
PYTHONPATH=tracks/t3-topology/dse python \
  tracks/t3-topology/dse/tools/sweep_product_configs.py \
  --output runs/config-sweep/my-run

# Focused standalone network replay (all declared ranks active):
PYTHONPATH=tracks/t3-topology/dse python \
  tracks/t3-topology/dse/tools/sweep_product_configs.py \
  --output runs/config-sweep/srota64 --filter k4_c4_e64 --network-only
```

Use a fresh output directory after code changes. `--resume` continues the
same run without repeating saved cases. Cases have a 240-second wall deadline,
2-GiB address-space limit, and 60-second default backend deadline; cancellation
or parent death kills the owned process group. No score is inferred for a
refusal or timeout.

## SROTA results

**Endpoints are not routers.** `N = k² × concentration` endpoints. Exactly
64 endpoints use **k=4, c=4** (16 routers). **64 routers** use **k=8**; SROTA
requires concentration >=2, so this means at least 128 endpoints.

The full-load SROTA witnesses activate every endpoint as a TP rank, using an
allreduce payload of `128 × N` bytes (equal 128-byte chunks). These are
synthetic collective tests, not model runtime predictions. Comparisons across
sizes also change offered workload and therefore are not topology rankings.

| Endpoints | Routers / concentration | Row-first network cycles | Row+column | Rank/Valiant | Islands | System analyses |
|---:|---|---:|---:|---|---|---|
| 16 | 4 / 4 | 7,508 | evaluated | evaluated | evaluated | all three evaluated |
| 32 | 16 / 2 | 12,040 | evaluated | evaluated | evaluated | all three evaluated |
| 50 | 25 / 2 | 14,774 | evaluated | evaluated | evaluated | all three evaluated |
| 64 | 16 / 4 | **24,266** | **24,264** | **24,265** | **24,264** | all three evaluated |
| 72 | 36 / 2 | 30,747 | evaluated | evaluated | evaluated | all three evaluated |
| 128 | 64 / 2 | **97,611** | **97,609** | 240s case timeout | **97,609** | row/shape/islands evaluated |
| 256 | 64 / 4 | **391,759** | **391,757** | 240s case timeout | **391,757** | row: all three exceed 60s; others network-only |

Network numbers were extracted only after consumption-time authenticated
proof verification. They are network-completion windows, not hardware model
runtime, compute time, DRAM time, or serving latency. Empty requirement reports
remain **no requirement-pass claim**, per the pinned consumer rule.

Removing T or disabling the side buffer at 64 endpoints executes. This
particular traffic produces the same completion count; it does not prove those
features have no effect under other workloads.

### Remaining SROTA boundaries

- **Plane C:** all tested sizes compile structurally but fail canonical
  class/VC admission: `control_collective` and `tp_collective` share a partial
  VC envelope. The product planner now rejects this before runtime. Direct
  two-subnet simulation/flit conservation is not a complete product-level
  class/plane/VC proof; the guard was not bypassed or the workload flattened.
- **Large rank/Valiant:** the 128- and 256-endpoint cases exceed 240 seconds.
  Stack samples locate the bottleneck in repeated canonical serialization/
  hashing of `RankPolicyRoute`, reached through deterministic-realization and
  fabric-DAG revalidation. This is unresolved. No route proof was skipped,
  and no cached hash was introduced on mutable mappings.
- **No MECS:** compile refuses the unsupported SROTA routing realization.
- **Concentration 1:** intent refuses; it is not a valid SROTA configuration.
- **256-endpoint ASTRA:** row-first standalone network succeeds, but the
  three system analyses exceed the 60-second backend budget. No system metrics
  are claimed for those attempts.

## Defects repaired

### Seven-rank tree presets had non-divisible payloads

`qtree7` and `tree4_7` used TP7 with 8192 bytes: `8192 % 7 != 0`, so both
shipped presets always refused ring-collective lowering. The preset defaults
now use **7168 bytes (7 × 1024)**, preserving seven agents and the topology.
Existing saved requests/revisions were not altered. Both presets now execute
all four analyses. The production equal-chunk divisibility guard remains.

### FlatFly exceeded the native dimension limit

The native builder implements dimensions 0..3 and asserts `dim < 4`.
`k=2,n=6` previously passed preflight and aborted BookSim with SIGABRT.
Qualification now refuses **native n>4** before spawning, and profile-selection
diagnostics preserve the actual FlatFly refusal instead of a misleading mesh
error. `k=4,n=3` and `k=4,n=4` still execute with exact geometry; adjacency
qualification also avoids constructing impossible dense candidate graphs.

### GEC-MECS ASTRA routing-name ABI mismatch

Standalone accepts `routing_function=dor_gec`; ASTRA's IQRouter appends the
network suffix, looking up nonexistent `dor_gec_gec`. The embedded transform
now renders **`dor`**, after checking the vendored registration
`gRoutingFunctionMap["dor_gec"] = &dor_gec`. This is an alias for the same
function, not a routing-policy substitution. `gec_mecs16` now executes all
four analyses; standalone network completion remains **1477 cycles**.

### Product preflight disagreed with canonical VC admission

The network adapter now applies the existing canonical class/VC binding
admission during preparation. It no longer advertises READY for Plane C
configurations that the canonical evaluation consumer rejects. Generic VC
subset and evidence-integrity guards remain intact.

## Other configurations and unresolved limits

- At 64 endpoints, mesh, concentrated mesh, FlatFly 4³, qtree, tree4,
  dragonfly, flattened butterfly, GEC mesh/express/multidrop, and explicit
  graph all execute four analyses.
- Torus 7×7 and 9×9 execute four analyses with the same explicit X/Y
  dependencies as the shipped torus preset and divisible collective payloads.
  The earlier unseeded test omitted those dependencies; its one-VC deadlock
  refusal was correct and **not TP-size-dependent**. No automatic dependency
  insertion into live drafts was added.
- Even-sided native deterministic torus still refuses midpoint ties.
- Larger `fattree` and structured `fat_tree` (radix4, three tiers, 64 agents)
  fail `DEADLOCK_FREE`; the certificate is not weakened. Their smaller shipped
  presets execute. These configurations remain unqualified, not repaired.
- GEC hybrid 8×8 with d=7 requires 14 VCs, exceeding the current eight-VC
  maximum; compile correctly refuses. GEC-hybrid16 standalone succeeds, while
  ASTRA lacks the observation-field ABI and refuses its three system analyses.
- FlatFly 4⁴ with 64 active agents: standalone succeeds; ASTRA's three analyses
  exceed the 60-second deadline. The workload is not resized to hide this.
- The four legacy-v2 presets retain compile/certificate checks. Canonical
  carrier copies are separately named and explicitly authored (TP2/8192-byte
  workload); they are not claims about implied legacy workload semantics.

No claim that every possible configuration works. The repaired failures and
remaining proof/runtime boundaries are kept separate in the evidence matrix.
