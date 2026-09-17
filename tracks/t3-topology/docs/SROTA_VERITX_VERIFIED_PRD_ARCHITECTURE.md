# Srota / VeriTX — Verified Product Requirements & Target Architecture

**Document ID:** SROTA-VERITX-PRD-ARCH-002  
**Revision:** 1.0 — independently reconstructed from workspace source  
**Date:** 17 September 2026  
**Status:** Implementation authority after approval  
**Supersedes:** the implementation/build-order portions of `SROTA-STUDIO-PRD-001.md` and the remaining roadmap in `VERITX_ARCHITECTURE_HANDOFF.md` where this document explicitly differs  
**Preserves:** the control-plane invariants and semantic-compression discipline from `VERITX_ARCHITECTURE_HANDOFF.md`

---

## 0. Authority, evidence basis, and how to read this document

This document was not produced by trusting the prior workspace audit. The audit was used only as a list of claims to investigate. The current architecture and roadmap below were reconstructed independently from the uploaded workspace snapshot.

### 0.1 Snapshot identity

Source snapshot inspected:

```text
veritx-research-snapshot.tar.gz
SHA256 8bae314ef02a8d66aa75d0a06c3804a6d3cc78407405e670ee4c4e4ecd243a96
size   220,904,719 bytes
files  9,309 extracted files
```

The snapshot itself reports Git HEAD `fa71db29...`, but the workspace was dirty and contained substantial uncommitted/untracked source. Therefore **the Git commit alone is not an identity for the audited implementation**. Until the workspace is cleanly committed, the snapshot hash above is the stronger reference for this document.

### 0.2 Evidence classes

Every current-state claim should be interpreted using these classes:

| Class | Meaning |
|---|---|
| **SOURCE-VERIFIED** | Directly confirmed in the source snapshot. |
| **TEST-VERIFIED** | Confirmed by a test that was independently executed against this snapshot/environment. |
| **ARTIFACT-VERIFIED** | Confirmed by a persisted run/report/log artifact in the snapshot. |
| **REPORTED** | Reported by the prior worker/audit, but not independently reproduced. |
| **CONTRADICTED** | A stronger source/runtime observation contradicts the previous claim. |
| **NOT IMPLEMENTED** | No working implementation was found for the claimed capability. |
| **UNKNOWN** | Evidence is insufficient; the implementation must not guess. |

A feature may have multiple classes. For example, a process supervisor can be SOURCE-VERIFIED while the full historical test count is only REPORTED.

### 0.3 Evidence precedence

When evidence conflicts, use this order:

1. reproducible current runtime behavior;
2. focused tests exercising the public seam;
3. current source code actually on the execution path;
4. current generated artifacts whose parent inputs can be identified;
5. documentation/comments;
6. prior audit/model summaries.

A comment, dataclass, enum, test name, or output filename does not establish a capability by itself.

### 0.4 Test-suite qualification

The prior audit reports **869 passed, 1 skipped**. That result is retained as historical evidence, but it was **not independently reproduced** from the snapshot because the packaged environment is incomplete:

- `pyproject.toml` declares `requires-python = ">=3.10"` and `dependencies = []`;
- current source imports runtime packages including Pydantic, NumPy, SciPy and `skopt`;
- `skopt` was absent in the independent environment;
- `core/runs.py` calls `uuid.uuid7()`, while the independent Python 3.13.5 runtime does not provide that API;
- a focused `test_run_core.py` invocation therefore fails at run-ID creation.

This is a reproducibility defect, not proof that the reported historical test run was fabricated.

### 0.5 What this document does not do

This is not a request for a big-bang rewrite. It does not prescribe a hierarchy of generic runners, providers, factories, services, repositories, or plugins. It defines **semantic contracts and proof obligations** where the current implementation has already demonstrated real divergence. Concrete paths should remain concrete until repeated behavior justifies extraction.

---

# 1. Executive position

Srota and VeriTX should be treated as three layers with different responsibilities:

```text
┌─────────────────────────────────────────────────────────────┐
│                         SROTA STUDIO                        │
│ Customer-facing authoring, inspection, evidence and export │
└────────────────────────────┬────────────────────────────────┘
                             │ design intent
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                    SROTA FABRIC COMPILER                    │
│ intent → resolved candidate fabrics → exact implementation │
│ workload / requirements / topology / route / VC / RTL      │
└────────────────────────────┬────────────────────────────────┘
                             │ experiments + exact artifacts
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                            VERITX                           │
│ reproducible execution / diagnosis / metrics / comparison  │
│ BookSim / ASTRA / LLMServingSim / RTL / later tool flows   │
└─────────────────────────────────────────────────────────────┘
```

The project is **not starting from zero**. It already contains substantial research-grade synthesis, simulation, certification, RTL-generation, reporting and control-plane work.

The primary blocker to productization is not missing breadth. It is **semantic disagreement between representations**:

- the route certified is not guaranteed to be the route BookSim executes;
- RTL derives another route-table scheme;
- workload operations can be silently dropped during lowering;
- separate simulator paths use incompatible or implicit units and packetization semantics;
- a comparison schema exists but is not enforced before ranking;
- E2 requirements exist but do not constrain synthesis;
- several F1–F8 verification results are reported as `PASS` without executing the described check;
- formal infrastructure exists, but the persisted formal run fails before a proof engine establishes a result;
- artifact “signing” is a prototype HMAC with a default secret, not product signing.

Therefore the next phase is **not Studio UI development**. The next phase is making the engine truthful and evidence-preserving.

---

# 2. Product thesis

The original product thesis remains valid:

> A chip team describes the system and workload it needs. Srota derives candidate NoC fabrics, evaluates them using appropriate fidelity levels, proves the properties it can actually prove, generates implementation collateral, and returns an inspectable evidence chain showing exactly why the design was selected and what has or has not been verified.

The important correction is that Srota must not claim to return “a verified fabric” as one undifferentiated state. Verification is a set of explicit evidence dimensions.

The customer experience should be:

```text
Intent
  ↓
Resolved design requirements
  ↓
Candidate fabrics
  ↓
Exact routes + VC policy
  ↓
Scientific evaluation
  ↓
Requirement feasibility + Pareto set
  ↓
Selected design
  ↓
RTL / verification collateral / reports
  ↓
Evidence-backed export bundle
```

At every step the user must be able to inspect what Srota derived, even when the field is not user-editable.

**LOCKED means compiler-owned, not hidden.**

---

# 3. Independently verified current state

## 3.1 Control-plane foundation

### Strict experiment boundary — SOURCE-VERIFIED

`dse/veritx_dse/core/spec.py` contains a strict Pydantic experiment model, resolved specifications, experiment hashing, replication policy and `ComparisonSpec`.

The architecture direction is sound: scientific intent is distinct from execution identity.

### Run model — SOURCE-VERIFIED, durability caveats

`core/runs.py` contains:

- explicit lifecycle states;
- transition guards;
- UUIDv7 intent for sortable run IDs;
- provenance capture;
- a separate `state.json`;
- result registration;
- terminal mutation checks.

However current implementation is not yet as durable as the documentation implies:

1. `new_run_id()` directly invokes `uuid.uuid7()` despite `>=3.10` package compatibility.
2. initial `spec.resolved.json`, `provenance.json` and `manifest.json` are written directly after directory creation rather than staged atomically;
3. the manifest calls itself frozen but is later mutated by `add_result()`;
4. the manifest embeds `status: CREATED`, while lifecycle state is separately stored in `state.json`, creating two status concepts;
5. recovery does not yet classify stale `RUNNING` records after restart;
6. attempts/retries are not modeled explicitly.

### One-shot process supervision — SOURCE-VERIFIED

`core/process.py` is a real deep module and should be retained. It provides:

- argv-array execution rather than shell strings;
- a separate process session/group;
- concurrent stdout/stderr draining;
- bounded head/tail output capture;
- timeout classification;
- TERM → grace → KILL escalation;
- Ctrl-C cleanup of the owned process group.

This is the correct primitive for one-shot tools such as standalone BookSim. It is **not** an interactive LLMServingSim protocol abstraction and must not be forced into that role.

Current limitation: the proven primitive is not yet used by all legacy ASTRA/Timeloop/tool invocation paths.

---

## 3.2 LLMServingSim protocol — SOURCE-VERIFIED with multiple dialects

The basic protocol is now knowable from source rather than inferred from command names.

### Controller behavior

`third_party/llmservingsim/serving/core/controller.py`:

- writes commands as text plus newline and flushes stdin;
- reads backend output until `Waiting` or `Checking Non-Exited Systems ...`;
- breaks on EOF instead of spinning on a dead pipe.

### BookSim frontend behavior

The ASTRA BookSim frontend implements an interactive protocol with:

- initial completion data followed by `Waiting`;
- `load <path>` queueing without an immediate reply;
- `run` applying queued loads and running to quiescence;
- legacy bare-path load+run;
- `pass [t]` time advancement;
- `done` returning `Waiting` rather than globally exiting;
- `exit` terminating the loop;
- `std::endl`, providing output flushing.

### Analytical frontend discrepancy

There are two analytical backends with **different protocol behavior**:

**Congestion-aware:** supports queued `load`, `run`, `pass`, `done`, `exit`, and bare-path compatibility.

**Congestion-unaware:** supports `pass`, `done`, `exit`, and otherwise interprets the input line as the workload path. It does not implement the same queued `load`/`run` contract.

LLMServingSim selects congestion-unaware for multi-dimensional analytical configurations as an optimistic lower-bound fallback.

Therefore the architecture must not treat “analytical backend” as one protocol implementation until the frontends are aligned or their capability difference is modeled explicitly.

### Serving liveness

Current serving code already contains some progress/spin instrumentation and fail-loud EOF logic, so the prior audit statement that there are “no counters” is too broad. What is still missing is the deterministic real-pipe protocol fixture required to prove behavior under:

- repeated `Waiting` without useful progress;
- malformed replies;
- missing terminator;
- backend EOF/crash;
- partial completion bursts;
- multi-instance completion ordering;
- protocol-dialect mismatch;
- parent cancellation.

---

## 3.3 Routing/certification — SOURCE-VERIFIED integrity gap

This is currently the most important scientific mismatch.

### BookSim actual routing

BookSim AnyNet uses internal Dijkstra routing. Its distance relaxation uses the link weight/latency stored in the AnyNet file.

### Python “BookSim-exact” route replica

`deadlock_routing.py::booksim_first_hop_table()` replicates important tie-breaking behavior, but uses:

```python
nd = dist[u] + 1
```

The canonical AnyNet parser validates an optional weight token but intentionally discards it for adjacency.

Therefore the Python route replica is only exact when all router-router edge weights are one.

### Main pipeline mismatch

The normal certification leg invokes `deadlock_routing.py` without `--method`, whose default is `mclb`.

A normal BookSim AnyNet evaluation uses BookSim internal `min_anynet` routing.

Thus the pipeline can certify MCLB routes while simulating different Dijkstra routes.

### RTL mismatch

The RTL generator independently derives route tables. Its current default `--tables auto` uses:

- dimension-order routing when grid structure is recognized;
- otherwise an up/down route-table construction;
- Dijkstra only when explicitly selected.

This is another independent routing truth.

### Immediate conclusion

The current system may produce three individually plausible but non-identical route realizations:

```text
certifier routes
BookSim routes
RTL routes
```

A product must never call a design “certified” under this condition.

---

## 3.4 VC/deadlock semantics — PARTIAL, not unified

The Python certification path currently reasons about channel dependencies for selected routes.

The RTL generator implements its own two-class scheme with a FREE class and an escape/up-down class.

BookSim's current `min_anynet` path exposes VCs as buffering resources; merely setting `num_vcs` does not instantiate the RTL escape-routing semantics.

The abstract `derive_vc_count()` / `derive_vc_assignment()` logic in `compile_model.py` reasons from a higher-level dependency graph. It is not a substitute for an exact `(channel, VC)` dependency proof over the route/VC realization that the simulator and RTL execute.

Therefore:

> dependency-derived VC counts may be used as candidate-generation heuristics, but they are not proof of deadlock freedom.

---

## 3.5 Workload lowering — SOURCE-VERIFIED silent corruption risk

`model_to_trace.py` supports several collectives and P2P, but an unknown `comm_type` currently causes:

```text
WARNING: unknown comm_type '...', skipping
```

and conversion continues.

A real model in the repository uses `BROADCAST`, which is not in that decomposer table.

The same lowering code silently filters participant IDs outside `[0, n_nodes)`, and silently emits no traffic when fewer than two participants remain.

This means a malformed or unsupported source workload can become a lighter network workload without making the experiment fail.

There is also no canonical Workload IR. BookSim traces, traffic matrices and ASTRA/Chakra artifacts are produced through separate transformations.

This must be fixed before workload-driven topology ranking can be trusted.

---

## 3.6 Metrics and units — SOURCE-VERIFIED fragmentation

There is no canonical metric schema.

Examples:

- BookSim latency: cycles;
- BookSim injection/accepted rate: packet-oriented simulator units;
- standalone BookSim `packet_size`: flits/packet;
- ASTRA embedded path: explicit bytes→flits conversion with its own flit-byte parameter;
- ASTRA completion: cycles under its own model;
- LLMServingSim: clocks / serving-derived time metrics;
- Timeloop: energy in tool-specific units/granularity;
- area/power/Fmax reports: analytical estimates.

These values can be stored together without a universal unit/fidelity/derivation contract.

This is unsafe for automatic ranking and for agent-driven experimentation.

---

## 3.7 Comparison/DSE — implementation exists, scientific gate does not

`ComparisonSpec` exists in the experiment schema, but is not consumed by the main compare paths.

Generic comparison can therefore rank systems that differ in uncontrolled scientific dimensions.

The newer multi-workload Pareto code is more honest than the prior audit suggested: it classifies failed rows and computes aggregate scores over common successful cases. That behavior should be retained.

What remains missing is a mandatory comparison protocol before a result can be called comparable or ranked.

---

## 3.8 Fabric compiler / requirements — foundation exists, core thesis incomplete

`CompileRequest` and the E1–E5 model are real. LOCKED/GUIDED/FREE is represented structurally.

However E2 Requirements do not drive the topology synthesizers. Searches over the synthesis package show no meaningful consumption of the Requirements model.

Therefore current behavior is closer to:

```text
intent is recorded
→ a topology is synthesized using its own optimization inputs
→ results are reported
```

not yet:

```text
requirements
→ candidate feasibility
→ constrained synthesis/search
→ evidence that the selected candidate satisfies them
```

Requirements-driven synthesis is therefore a product milestone, not an existing feature.

---

## 3.9 RTL and Verilator — real foundation, weak maintained evidence

The RTL generator is substantive:

- SystemVerilog generation exists;
- arbitrary/AnyNet input exists;
- wormhole/credit behavior exists;
- route-table generation exists;
- two VC-class behavior exists;
- generated RTL trees exist in the workspace.

However:

- there is no maintained RTL regression in the main Python suite;
- the route realization is not tied to the same artifact as BookSim/certification;
- the documented BookSim↔RTL experiment shows significant post-knee divergence;
- the exact correlation contract has not been defined.

No generic “BookSim == RTL” gate should be invented until the models' intended equivalence is defined.

---

## 3.10 Formal verification — harness exists; proof not established

The repository contains SymbiYosys configuration (`router_formal.sby`, `router_bmc.sby`) and a persisted formal run.

That persisted run is **ERROR**, with Yosys rejecting `router.sv` before the SMT engine returns a proof status.

Therefore the correct claim is:

> Formal properties/harness infrastructure exists, but this snapshot does not establish a successful formal proof.

“Formal-ready” or “formal harness present” is acceptable language. “Formally verified” is not.

---

## 3.11 F1–F8 verification reporting — HIGH-SEVERITY integrity defect

`compile_model.py::verify_design()` currently emits `PASS` for several properties without executing the verification described by their names.

Examples include:

- F2 liveness: unconditional PASS based on a topology name string;
- F3 packet conservation: PASS describing BookSim accounting without receiving a BookSim result;
- F4 ordering: PASS inferred from a derived VC assignment rather than checking ordering;
- F5 flow control: PASS based on the intended credit-based architecture;
- F6 routing correctness: PASS based on a derived routing label;
- F8 timeout: PASS describing BookSim bounded latency without a simulation result.

F1 also operates on an abstract dependency graph rather than the actual VC-expanded channel dependency graph.

`reports.generate_report()` includes these statuses in customer-facing report data.

This must be corrected **before any new verification/product UI work**. A product may report `NOT_RUN`, `UNSUPPORTED`, `ASSUMPTION`, or `ESTIMATE`; it may not emit `PASS` without evidence.

---

## 3.12 Reports — useful estimates, not sign-off

The current report code explicitly carries useful accuracy caveats:

- area approximately ±30% for relative comparison;
- power without process corners/thermal guarantees;
- Fmax requiring STA for guaranteed frequency.

That honesty should become part of the canonical metric model rather than prose only.

Current area/power/timing should be described as **analytical estimates**.

---

## 3.13 Artifact signing/export — prototype only

HMAC-SHA256 helpers and revision-chain concepts exist.

However:

- a default shared secret is embedded in source;
- HMAC is not a public-verification PKI/signing system;
- `generate_artifacts()` can return metadata entries for RTL/UVM/report files before checksums exist and without proving those files were actually generated.

Therefore current code is an integrity/provenance prototype, not a product-grade signed export pipeline.

---

# 4. Non-negotiable product invariants

These invariants override convenience, backward compatibility and UI requirements.

## 4.1 No false PASS

A verification result may be `PASS` only when a defined check actually ran against the exact referenced artifact and produced evidence satisfying its acceptance rule.

Allowed statuses:

```text
PASS
FAIL
NOT_RUN
UNSUPPORTED
INCONCLUSIVE
ASSUMPTION
```

`WARN` may supplement one of these states but must not blur whether a property was actually checked.

## 4.2 Certified means executed

No routing/deadlock claim is valid unless the verifier reasons about the same exact route/VC realization that the target simulator or RTL executes.

## 4.3 Unsupported workload semantics fail closed

No source workload operation, participant, dependency or byte count may disappear during lowering without causing a hard failure or an explicit user-approved exclusion recorded in the experiment intent.

## 4.4 Units are data

Persisted scientific numbers must carry explicit unit and semantic definition. Naked values such as `latency: 42` are not a stable product interface.

## 4.5 Fidelity is data

Analytical estimate, network simulation, serving/system simulation, RTL measurement, and implementation-tool results must not be presented as equivalent evidence.

## 4.6 Comparability is declared, not inferred from filenames

Two successful result files are not automatically comparable.

## 4.7 Reproducibility includes the executable environment

A reproducible run identity includes enough information to identify source, inputs, simulator binaries/images, relevant configuration, units/conversion rules and random sources.

## 4.8 Started scientific intent is immutable

Changing scientific intent creates a new run/design revision. Mutable lifecycle state and retry attempts must not rewrite the original intent.

## 4.9 Compiler-owned does not mean hidden

LOCKED routing/VC fields must be inspectable, explainable and evidence-linked even when the user cannot edit them.

## 4.10 No silent scientific fallback

Fallback to a lower-fidelity or semantically different backend must be explicit in the result. Example: congestion-unaware analytical execution must be labeled as that model, not simply “analytical.”

---

# 5. Target semantic architecture

This section defines semantic artifacts, not required Python class names.

```text
Mutable Working Draft
        │ commit
        ▼
Immutable DesignRevision
        │
        ├─────────────── Workload intent
        ├─────────────── Requirements
        ├─────────────── Agents/addressing
        └─────────────── Guided/free preferences
        │
        ▼
Fabric Compiler
        │
        ├── WorkloadIR
        ├── TopologyIR
        ├── RouteArtifact
        ├── VCAssignmentArtifact
        └── CandidateFabric
        │
        ▼
ExperimentSpec / Plan
        │
        ▼
VeriTX execution
   ┌────┼───────────────┐
   ▼    ▼               ▼
BookSim ASTRA      LLMServingSim
                       │
                 network backend
        │
        ├─────────────── RTL / Verilator
        ▼
Raw Results + Evidence
        │
        ▼
Canonical Metrics
        │
        ▼
ComparisonProtocol
        │
        ▼
Requirement Evaluation / Pareto Set
        │
        ▼
Selected ResolvedDesign
        │
        ├── RTL
        ├── UVM/assertions
        ├── verification evidence
        ├── reports
        └── export manifest
```

---

# 6. Core semantic artifacts

## 6.1 DesignRevision

Immutable committed customer/compiler intent.

Must contain or reference content-addressed versions of:

- workload input;
- requirements;
- agent/address map;
- GUIDED/FREE preferences;
- compiler version;
- schema version.

A mutable UI draft is **not** a DesignRevision.

## 6.2 WorkloadIR v0

Do not design a universal workload language. Build only what current BookSim/ASTRA/LLMServingSim paths already require.

Minimum representation:

```text
operation_id
phase_id
operation_kind
participants / group reference
bytes
invocation count
dependencies / ordering
optional start/arrival timing when known
traffic/QoS class when known
source provenance
```

The IR must preserve information that an average traffic matrix loses: collective synchronization, phases, dependencies, bursts, participant groups and compute/network boundaries where they are known.

### Projections

WorkloadIR may project to:

- BookSim trace;
- ASTRA/Chakra ET;
- traffic matrix for fast/synthesis use;
- LLMServingSim scenario/request representation where applicable.

Traffic matrix is **a projection**, not the canonical workload.

## 6.3 LoweringManifest

Every projection must emit a machine-readable lowering manifest containing at least:

```text
source_workload_hash
projection_type
projection_version
operation counts by kind
participants/groups used
source bytes by operation/class
output message/packet/flit counts
conversion parameters (e.g. flit bytes)
unsupported operations = []
dropped operations = []
output artifact hashes
```

For supported semantics, `unsupported` and `dropped` must be empty.

Golden tests must verify conservation appropriate to each operation rather than merely asserting that a file exists.

## 6.4 TopologyIR

Minimum fields:

```text
routers
endpoints
endpoint→router attachment
router-router directed links
link weight / latency
link width where known
physical metadata where known
source/generator provenance
```

### Weighted AnyNet policy

**Immediate v1 policy:** reject non-unit router-router AnyNet weights in paths that use the current Python certification representation.

This is preferable to silently certifying an unweighted projection of a weighted BookSim topology.

**Later:** TopologyIR preserves weights end-to-end and routing/certification uses them exactly.

## 6.5 RouteArtifact

The long-term source of routing truth.

Minimum contents:

```text
schema/version
TopologyIR hash
routing algorithm + exact version
all required src/dst or router/destination next-hop entries
equal-cost tie-breaking rule
endpoint mapping assumptions
per-entry/per-class VC eligibility if routing depends on VC
content hash
```

### Migration rule

Today BookSim internally computes AnyNet routes. Until BookSim can directly consume the compiler's RouteArtifact, one of these must be true:

1. BookSim dumps the actual route table and the certifier certifies that exact dumped table; or
2. the existing BookSim fork gains a narrow route-table ingestion path and consumes the compiler artifact.

Do **not** pretend a generic `routing_function=table` exists today.

Long-term preference: the Fabric Compiler owns the exact route artifact, and all consumers ingest or mechanically verify it.

## 6.6 VCAssignmentArtifact

Minimum contents:

```text
RouteArtifact hash
traffic/protocol class → allowed VC set
escape/adaptive transition rules if used
per-hop restrictions
VC count
proof assumptions
content hash
```

Deadlock certification must operate over the actual `(channel, VC)` dependency graph when a VC-based escape theorem is being claimed.

## 6.7 CandidateFabric

A candidate is not just a topology name. It binds:

```text
TopologyIR
RouteArtifact
VCAssignmentArtifact
router/link parameters
implementation assumptions
WorkloadIR version used for evaluation
```

Its identity is content-addressed.

## 6.8 ExperimentSpec and Plan

Retain the successful existing separation:

```text
ExperimentSpec = scientific intent
Resolved Experiment = defaults/references fully materialized
Plan = exact tasks + exact immutable inputs + expected outputs
Run = one execution of that plan
```

The plan must include hashes for every input whose change would alter the scientific result.

## 6.9 Metric

Canonical normalized metric records must include:

```text
name
value
unit
semantic_definition
producer/tool/model
fidelity
aggregation_scope
source_run/task
source_artifact_hash
derivation/conversion rule
model/tool version
uncertainty / calibration information when applicable
```

Raw results are retained in addition to normalized metrics.

## 6.10 VerificationEvidence

Every property result contains:

```text
property_id
status
statement/scope
method
tool + version
input artifact hashes
assumptions
evidence artifact references
counterexample/failure artifact when applicable
timestamp
```

A report displays evidence; it does not invent verification status.

## 6.11 ComparisonProtocol

The existing `ComparisonSpec` concept should become executable.

It must state:

```text
intentional variables
controlled dimensions
acknowledged structural consequences
allowed fidelity relationships
replication/statistics policy
required metrics
```

The comparison engine validates this before ranking.

---

# 7. Routing and deadlock architecture

## 7.1 Short-term safe behavior

Until the unified RouteArtifact path lands:

1. certification for BookSim AnyNet must explicitly use the BookSim route semantics;
2. only unit-weight AnyNet is accepted by that equivalence path;
3. the exact route table used for certification is persisted and hashed;
4. cyclic BookSim route CDG is reported as a failure/unsupported condition;
5. do not claim that “additional VCs” fix the problem unless the executed route/VC algorithm actually implements the required escape discipline;
6. RTL route equivalence is reported `NOT_RUN` until mechanically compared.

## 7.2 Long-term route flow

```text
TopologyIR
    ↓
route derivation
    ↓
RouteArtifact
    ├──→ VC assignment
    │      ↓
    │  VCAssignmentArtifact
    │      ↓
    │  expanded CDG certificate
    │
    ├──→ BookSim exact ingestion/verification
    └──→ RTL exact ingestion/verification
```

## 7.3 Prohibited state

The following must be impossible in a product run:

```text
certificate: PASS on route set A
BookSim: executes route set B
RTL: implements route set C
```

---

# 8. Workload correctness architecture

## 8.1 Fail-closed rules

The lowering boundary rejects:

- unknown communication operation;
- participant outside declared system range;
- participant group collapsing below the operation's required cardinality;
- unknown units;
- negative/overflowing sizes;
- unresolved group references;
- unsupported dependency semantics.

No warning-and-continue path is allowed for scientific input loss.

## 8.2 Conservation tests

Representative golden workloads must assert, as appropriate:

- source operation count;
- source total communication bytes;
- participant membership;
- number of collective invocations;
- generated messages/packets/flits;
- dependency/order preservation;
- no unsupported/dropped operations.

For collective decomposition, expected network byte multiplication must be defined by the algorithm rather than compared blindly to source tensor bytes.

## 8.3 Existing BROADCAST

Because the repository already contains a `BROADCAST` model, the immediate implementation may choose either:

- implement a precisely defined BROADCAST decomposition and tests; or
- reject that model as unsupported.

Silently deleting it is not an option.

---

# 9. Execution architecture

## 9.1 One-shot process execution

Use `supervised_run()` (or a later deep equivalent proven by real repetition) for one-shot tools:

- standalone BookSim;
- Timeloop;
- one-shot converters;
- non-interactive formal/synthesis tools;
- one-shot Verilator harnesses.

Migrate existing bare `subprocess.run` call sites incrementally.

## 9.2 Interactive serving session

Create a concrete LLMServingSim protocol module only after/with the real-pipe fixture.

Do not create a generic `InteractiveRunner` framework.

The protocol implementation must represent the actual state machine:

```text
backend starts
    ↓
initial Waiting-terminated burst
    ↓
load*        (where dialect supports it; no immediate reply)
    ↓
run          (Waiting-terminated reply)
    ↓
pass t       (Waiting-terminated reply)
    ↓
done         (Waiting-terminated reply; not global termination)
    ↓
exit         (backend exits)
```

## 9.3 Backend protocol capabilities

Until the analytical frontends are aligned, capability metadata must distinguish at least:

```text
booksim_interactive: load/run supported
analytical_aware:   load/run supported
analytical_unaware: bare-path only for workload replacement
```

Preferred fix: align congestion-unaware to the same `load/run` contract and test it with the shared protocol fixture. That is protocol convergence, not speculative abstraction.

## 9.4 Progress model

Track independent progress dimensions:

```text
wall clock
backend command/reply sequence
backend simulated time
serving scheduler state
per-instance inflight/completed work
request retire count
network completion evidence where available
```

A live process is not proof of progress.

No-progress diagnostics should classify, not merely timeout:

- backend protocol stalled;
- backend returns `Waiting` but state unchanged;
- simulated time advances but no request retires;
- scheduler spins without dispatch/progress;
- network work remains without completions.

---

# 10. Durable run/evidence model

## 10.1 Run creation

Current direct initial writes should be replaced by a staging transaction:

```text
create .tmp-<run_id>/
write resolved spec
write provenance
write initial identity metadata
validate hashes
atomically publish run directory or completion marker
then enter CREATED/VALIDATED lifecycle
```

A partially initialized directory must never be mistaken for a valid run.

## 10.2 Separate immutable identity from mutable state

Recommended persisted structure:

```text
runs/<run_id>/
  identity.json              immutable
  spec.resolved.json         immutable
  plan.json                  immutable once execution begins
  provenance.json            immutable baseline
  state.json                 mutable lifecycle only
  tasks/
    <task_id>/
      attempts/
        0001/
          invocation.json
          provenance.json
          stdout.log
          stderr.log
          raw-result...
          result.json
  metrics.json               derived, versioned
  evidence/
  manifest.final.json        immutable final inventory
```

Do not duplicate lifecycle status inside an otherwise “frozen” manifest.

## 10.3 Attempts and resume

- retry preserves previous attempt;
- resume is allowed only if the plan/dependency fingerprint matches;
- different scientific intent creates a new run;
- stale `RUNNING` after restart is classified `INTERRUPTED`, not silently continued;
- “file exists” is never sufficient for reuse.

## 10.4 Provenance minimum

Capture at least:

```text
source snapshot/commit + dirty state identity
input artifact hashes
resolved configuration hashes
simulator binary SHA256 or immutable container digest
simulator/version strings where available
host/kernel/runtime identity for native tools
Python version and package lock/environment identity
seeds/random sources
start/end timestamps
exit status / timeout / signal
conversion/model versions
```

---

# 11. Environment and packaging contract

Reproducibility starts before simulation.

## 11.1 Fix declared Python compatibility

Choose one of:

- require a Python version that actually provides every used stdlib API; or
- retain the intended Python range and use an explicit tested UUIDv7 implementation/dependency.

Do not declare `>=3.10` while directly depending on a later stdlib API.

## 11.2 Declare runtime dependencies

`pyproject.toml` must declare the packages required by normal VeriTX execution. Do not rely on a developer machine having NumPy/SciPy/Pydantic/scikit-optimize by accident.

## 11.3 Lock/record environment

Use a reproducible lock/constraints mechanism and record its identity with runs. The exact package manager is an implementation choice; the scientific requirement is not.

## 11.4 CI/environment matrix

At minimum test the supported minimum Python and primary development Python. A package compatibility claim requires CI evidence.

---

# 12. Verification evidence model

Do not collapse verification to a single green “verified” badge.

Studio and exports should expose independent dimensions:

| Dimension | Example evidence |
|---|---|
| Structural | topology parse/connectivity/endpoint validity |
| Workload | lowering/conservation manifest |
| Routing | route completeness and exact route hash |
| Deadlock | channel or `(channel,VC)` dependency certificate |
| Simulation | BookSim/ASTRA/system run evidence |
| RTL functional | Verilator packet-delivery/regression evidence |
| Formal | successful property proof/counterexample |
| Physical | synthesis/STA/P&R/tool evidence |

Each is independently `PASS/FAIL/NOT_RUN/...`.

## 12.1 F1–F8 remediation

The existing names may be retained if they are valuable, but their implementation must be evidence-backed.

Until then, replace fabricated PASS states with `NOT_RUN`, `ASSUMPTION`, or an accurately named heuristic check.

Examples:

- “dependency graph has no cycles” is not “NoC deadlock freedom”;
- “credit-based architecture selected” is not “flow control verified”;
- “BookSim can measure latency” is not “timeout property passed.”

## 12.2 Formal proof

A formal property becomes PASS only when the selected tool successfully elaborates the exact generated RTL/property set and returns a proof status.

A `.sby` file or emitted SVA is not a proof.

---

# 13. Metrics and fidelity

## 13.1 Evidence/fidelity categories

Use explicit categories rather than implying a simple monotonic ladder:

```text
ANALYTICAL_ESTIMATE
NETWORK_SIMULATION
SYSTEM_SERVING_SIMULATION
RTL_SIMULATION
FORMAL_PROOF
SYNTHESIS_STA_PHYSICAL
```

A metric records its producer and category.

## 13.2 Live Studio values

“Live consequence” remains a good UX principle only if the UI labels fidelity.

Example:

```text
Estimated packet latency: 42 cycles
Model: analytical-v3
Fidelity: ANALYTICAL_ESTIMATE
Calibration: none
Not a BookSim/RTL result
```

Never display `Latency: 42 ns` when the underlying model produced cycles with no explicit clock conversion.

## 13.3 Physical estimates

Current area/power/Fmax code may support early exploration, with the current caveats surfaced structurally.

Sign-off values require real implementation-tool evidence. Do not blur them with analytical reports.

---

# 14. Scientific comparison and DSE contract

## 14.1 Mandatory comparison validation

Before ranking, validate at least:

- workload identity or intentionally varied workload;
- endpoint/node count;
- topology variable declaration;
- route/VC policy;
- packet/flit semantics;
- payload/message-size semantics;
- simulator/model/fidelity;
- seeds/replication mode;
- required metric units and definitions.

A difference can be allowed only if it is either:

1. the declared independent variable; or
2. an acknowledged consequence of that variable.

## 14.2 Failed/partial candidates

Never silently drop a failed candidate from a claimed complete search.

A Pareto report must include:

```text
requested candidates
success count
failed count
failure classifications
unevaluated/pruned count
fidelity used
```

If the search is incomplete, say so.

## 14.3 Stochastic experiments

Stochastic routing/search must record all seeds and report dispersion. Do not rank one stochastic sample against a deterministic result as if equivalent.

## 14.4 Selection language

Use:

> selected candidate / Pareto-optimal among evaluated candidates under objective profile X

Avoid:

> globally optimal / winner

unless a method actually proves global optimality over the declared search space.

---

# 15. Requirements-driven Fabric Compiler

This is the product transition from “research suite” to “intent-to-fabric compiler.”

## 15.1 Requirement schema

A requirement should contain at least:

```text
metric / property
scope
operator
threshold
unit
hard vs soft
priority/weight for soft objectives
fidelity requirement, where relevant
```

## 15.2 Hard constraints

A hard requirement is never silently relaxed.

If no evaluated candidate satisfies all hard constraints, return `INFEASIBLE` or `NOT_ESTABLISHED`, not an arbitrary winner.

## 15.3 Soft objectives

Soft objectives drive Pareto/selection only after hard feasibility.

## 15.4 Uncertainty-aware pruning

An analytical estimate near a hard threshold must not eliminate a candidate if the estimator's uncertainty can cross that threshold.

Example:

```text
estimated latency 104 ns
known model envelope ±10 ns
requirement <=100 ns
```

This candidate is uncertain, not proven infeasible.

## 15.5 Explainability

Every GUIDED override or compiler decision should be inspectable:

```text
requested mesh
→ rejected/modified because constraint X could not be met at evaluated fidelity
→ alternatives considered
→ evidence links
```

---

# 16. Srota Studio v0 product scope

Studio v0 should be deliberately smaller than the original PRD.

## 16.1 Build only after engine semantic gates are stable

Do not build the customer-facing Studio workflow while route truth, workload lowering, units and comparison semantics remain unstable. Otherwise the UI merely makes unreliable conclusions easier to consume.

## 16.2 v0 workflow

```text
Create/edit Draft
    ↓
Define workload + requirements + agents
    ↓
Commit DesignRevision
    ↓
Generate candidates
    ↓
Inspect topology / derived routing / VC evidence
    ↓
Run/evaluate candidates
    ↓
Compare under validated ComparisonProtocol
    ↓
Inspect verification matrix
    ↓
Select design
    ↓
Export evidence-backed bundle
```

## 16.3 v0 screens

Only the following are required initially:

1. **Intent** — workload, requirements, agents, GUIDED/FREE settings.
2. **Candidate** — topology and derived implementation details.
3. **Runs** — status, diagnostics, fidelity, artifacts.
4. **Compare** — validated comparisons/Pareto evidence.
5. **Verify** — property/evidence matrix.
6. **Export** — exact artifact inventory and provenance.

## 16.4 Deferred from v0

- full editable physical floorplan;
- multi-tenant enterprise administration;
- arbitrary live topology editing without recompilation;
- Kubernetes-specific operational UI;
- sign-off P&R/STA claims without integrated tools;
- generic plugin marketplace.

## 16.5 Draft/result race safety

Every asynchronous UI calculation must be bound to a draft/revision hash. A result for an older draft must never overwrite the visible state of a newer draft.

---

# 17. Export and trust model

## 17.1 Export bundle

A product export is an immutable bundle containing only actual files and evidence, not placeholder URIs.

Minimum inventory:

```text
design revision
resolved CandidateFabric
WorkloadIR + lowering manifests
TopologyIR
RouteArtifact
VCAssignmentArtifact
RTL
UVM/assertions
verification evidence
reports/metrics
raw tool provenance
bundle manifest
```

## 17.2 Checksums before signatures

Every actual artifact gets a SHA256 checksum first.

## 17.3 Signing modes

Initial research/local mode may be:

```text
CHECKSUMMED / UNSIGNED
```

Product signing requires managed keys. The source-code default HMAC secret must not be used as a security boundary.

Possible future modes:

```text
SIGNED_LOCAL
SIGNED_SROTA_SERVICE
SIGNED_CUSTOMER_ON_PREM
```

The cryptographic mechanism is a later security design choice; truthful status is required now.

---

# 18. Security and deployment requirements

## 18.1 Engine independence

The core compiler/VeriTX engine must remain runnable without SaaS infrastructure. This supports:

- local research;
- single-tenant deployment;
- customer VPC;
- on-prem/offline deployment.

Do not hardwire Postgres, Redis, Celery/Ray or Kubernetes into scientific core logic.

## 18.2 Untrusted imports

Future CSV/IP-XACT/JSON/archive ingestion must treat input as hostile:

- resource limits;
- no path traversal;
- safe XML parsing;
- archive extraction guards;
- file-size/count limits;
- no arbitrary host-path references.

## 18.3 Tool workers

Native EDA/simulator jobs should not automatically inherit application secrets or unrestricted host/network access.

---

# 19. Agent interface

Agents come after stable semantic operations.

## 19.1 Order of exposure

```text
read/discover
→ validate
→ plan
→ estimate cost
→ controlled execute
→ compare/diagnose
```

## 19.2 Prohibited agent primitives

Do not expose:

- arbitrary shell;
- arbitrary Docker/podman;
- arbitrary binary path;
- arbitrary host path;
- arbitrary environment injection.

## 19.3 Candidate semantic tools

Only after the underlying seams are stable:

```text
list_capabilities
describe_workload/topology
validate_design
plan_experiment
execute_plan
get_run
get_results
diagnose_run
compare_runs
cancel_run
```

No MCP layer should contain scientific logic.

---

# 20. Revised implementation sequence

The sequence below intentionally inserts integrity work **before PR5**, then returns to the vertical-slice migration already established by the handoff.

## Phase 0 — Truth and reproducibility repairs

These are small/high-value blockers. No new architecture framework.

### Integrity PR A — Environment contract

Implement:

- accurate Python compatibility;
- working UUIDv7 strategy across supported versions;
- declared runtime Python dependencies;
- reproducible environment/lock identity;
- CI/test on supported Python versions.

**Gate A:** clean environment can install VeriTX from declared metadata and execute focused core tests without undeclared packages.

### Integrity PR B — Verification honesty

Implement:

- remove unsupported F1–F8 PASS claims;
- add `NOT_RUN/UNSUPPORTED/INCONCLUSIVE/ASSUMPTION` statuses;
- every PASS must require evidence input;
- reports display evidence references;
- formal harness reported honestly as unproven until it passes;
- artifact placeholders are not presented as generated files.

**Gate B:** no code path can produce a PASS for a property without executing its acceptance check.

### Integrity PR C — Workload fail-closed

Implement:

- unknown `comm_type` => hard failure;
- invalid participants => hard failure;
- define or reject BROADCAST;
- LoweringManifest v0;
- golden conservation tests for at least allreduce, allgather, reducescatter, alltoall, P2P and any newly supported BROADCAST semantics.

**Gate C:** representative source workloads lower with zero silently dropped operations and explicit conservation evidence.

### Integrity PR D — Routing stopgap

Before full route unification:

- BookSim-targeted cert uses BookSim route semantics explicitly;
- reject weighted AnyNet on the current Python cert path;
- persist/export the certified route table and hash;
- remove/qualify escape-VC claims that are not executed by BookSim;
- add tests covering equal-cost tie-break hazards and weight rejection.

**Gate D:** a BookSim-targeted certificate cannot silently refer to MCLB/shortest/escape routes that BookSim did not execute.

### Integrity PR E — Units/provenance baseline

Add explicit unit/model/fidelity fields to new-style results and complete critical executable provenance (binary hash/container digest/version where feasible).

Do not migrate every legacy report at once.

**Gate E:** new vertical slices cannot emit a core scientific metric whose unit/producer is unknown.

---

## Phase 1 — PR5: real LLMServingSim protocol fixture

Create a small real child process implementing the exact protocol semantics.

Required fixture modes:

- normal initial Waiting;
- `load* → run`;
- bare-path compatibility;
- `pass`;
- `done`;
- `exit`;
- multi-line/multi-NPU completion burst;
- delayed Waiting;
- repeated Waiting with no useful progress;
- malformed reply;
- missing terminator;
- EOF before completion;
- non-zero crash;
- stderr flood;
- ignore graceful shutdown;
- cancellation.

Test the congestion-unaware dialect explicitly until it is aligned.

**Gate 1:** protocol behavior is deterministic under real pipes and all failure classes are diagnosable without an expensive simulator.

---

## Phase 2 — PR6: LLMServingSim → BookSim vertical slice

Implement the concrete path first.

Required:

- exact protocol/session ownership;
- immutable run evidence;
- per-instance progress diagnostics;
- fail-loud backend EOF;
- deterministic tiny single-instance golden;
- deterministic tiny multi-instance golden/regression for the historical livelock class;
- cancellation cleanup.

**Gate 2:** a tiny multi-instance serving workload completes reproducibly and no-progress failures are classified rather than hidden behind a wall-clock timeout.

---

## Phase 3 — PR7: LLMServingSim → analytical vertical slice

Prefer to align congestion-unaware with the established `load/run` protocol before relying on it in multi-instance/system experiments.

Keep the analytical model identity explicit (`aware` vs `unaware/lower-bound`).

**Gate 3:** both supported analytical modes have defined protocol semantics and their results carry the correct model/fidelity identity.

Only now perform the semantic-compression review across BookSim and analytical serving sessions.

---

## Phase 4 — Semantic truth artifacts

This is where justified cross-cutting artifacts land, because divergence has been demonstrated in real paths.

Implement incrementally:

1. WorkloadIR v0 + LoweringManifest for current paths.
2. TopologyIR with endpoint mapping and weights.
3. RouteArtifact.
4. VCAssignmentArtifact where required.
5. canonical Metric schema.
6. executable ComparisonProtocol.

### Route migration

Add either BookSim route-table ingestion or BookSim route-table dump-as-authority during transition. Mechanically prove route-table equality before certificate PASS.

### VC migration

If adaptive+escape routing is desired, define the actual transition rules and certify the expanded `(channel, VC)` CDG. Do not infer it from VC count.

**Gate 4:** every network evaluation can answer exactly which workload, topology, route and VC artifacts it executed.

---

## Phase 5 — Comparison/DSE integrity

Implement:

- ComparisonSpec enforcement;
- unit/fidelity compatibility;
- explicit failed candidate handling;
- stochastic aggregation/dispersion;
- search coverage metadata;
- Pareto selection language.

**Gate 5:** invalid 16-vs-64-vs-72-node or incompatible packetization/fidelity comparisons cannot accidentally produce a ranked “winner.”

---

## Phase 6 — RTL/evidence credibility

Implement maintained regression rather than one-off scripts.

Minimum:

- 4×4 and 8×8 generated RTL build/run smoke;
- functional packet reachability/conservation checks;
- exact RouteArtifact/RTL table equivalence;
- VC policy equivalence where claimed;
- zero-load/basic latency sanity;
- defined BookSim↔RTL correlation experiments across pre-knee and saturation regions;
- repair SymbiYosys parse/elaboration and run selected formal properties;
- persist proof/counterexample evidence.

Do **not** set an arbitrary latency percentage parity gate until model-equivalence scope is established.

**Gate 6:** generated RTL is automatically checked against the same semantic fabric artifact used by the verifier; formal status reflects actual tool outcomes.

---

## Phase 7 — Requirements-driven synthesis

Wire E2 into candidate feasibility and optimization.

Implement:

- hard constraints;
- soft objectives;
- requirement evaluation from typed metrics;
- uncertainty-aware early pruning;
- candidate-set provenance;
- explicit infeasible/not-established outcomes;
- explainable GUIDED overrides.

**Gate 7:** tests demonstrate that changing an E2 requirement changes feasibility/search behavior, not merely report text.

---

## Phase 8 — Finish control-plane migration

Now migrate legacy verbs vertically:

- thin Python CLI;
- `t3` forwarding shim;
- sweep;
- compare;
- trace/workload operations;
- reports;
- history/index rebuilt from authoritative new run manifests;
- `diagnose`.

Delete migrated Bash semantics rather than maintaining two permanent implementations.

**Gate 8:** CLI/TUI contain no simulator/scientific logic; deleting local index does not lose authoritative history.

---

## Phase 9 — Srota Studio v0

Build the six-screen workflow from §16.

No distributed scheduler required initially. A single-machine/single-writer engine API is sufficient until real concurrency appears.

**Gate 9:** Studio is a thin client over the same validated compiler/VeriTX seams used by CLI/tests. No web-only scientific path exists.

---

## Phase 10 — Agent interface

Read/discover first, then plan, then controlled execute.

**Gate 10:** an agent can perform useful experiments without arbitrary shell/filesystem/process primitives, and budget limits are enforced.

---

## Phase 11 — Multi-user/distributed/on-prem scaling only when demanded

Only after real workloads require it consider:

- persistent API service;
- Postgres/object store;
- worker queue;
- multi-client coordinator;
- Kubernetes;
- customer VPC/on-prem packaging.

The scientific core remains independent.

---

# 21. Immediate next work — exact order

Do **not** hand the worker the old “next 10” list unchanged.

The next implementation queue should be:

```text
1. Environment/packaging contract
2. Remove false verification PASS states
3. Fail-closed workload lowering + LoweringManifest v0
4. BookSim-targeted routing cert stopgap + reject weighted AnyNet
5. Core unit/fidelity/provenance fields for new-style results
6. PR5 protocol fixture (including backend-dialect cases)
7. Serving liveness/progress evidence
8. PR6 serving→BookSim + multi-instance golden
9. PR7 serving→analytical + protocol alignment
10. Semantic-compression review, then RouteArtifact/WorkloadIR/Metric contracts
```

Items 1–5 should be narrow integrity PRs, not a redesign detour.

---

# 22. Failure model and adversarial acceptance scenarios

A release gate must intentionally test the opposite of the happy path.

## 22.1 Input/lowering

- unsupported collective;
- malformed participant group;
- endpoint outside system range;
- zero/overflow payload;
- conflicting workload units;
- source changes after planning;
- a projection would drop an operation.

Expected: hard failure with source location/context; no partial “successful” workload.

## 22.2 Routing/topology

- disconnected topology;
- directed-link asymmetry where not allowed;
- weighted AnyNet entering an unweighted cert path;
- equal-cost route tie-breaking difference;
- certificate route hash differs from simulator route hash;
- RTL route table differs from RouteArtifact;
- cyclic CDG;
- claimed escape VC absent from execution configuration.

Expected: no certification PASS.

## 22.3 Process/session

- executable missing;
- non-zero exit;
- exit zero + malformed output;
- stderr flood;
- child ignores SIGTERM;
- grandchild remains alive;
- parent Ctrl-C;
- backend EOF;
- backend Waiting forever without progress;
- backend time moves without request retirement;
- protocol dialect receives unsupported command.

Expected: classified terminal state + preserved evidence + no leaked owned process tree where enforceable.

## 22.4 Filesystem/state

- crash during initial run creation;
- disk full during result finalization;
- partial temp file;
- stale RUNNING after restart;
- duplicate writer;
- retry after simulator completed but state finalization failed.

Expected: never misclassify partial/stale output as a completed reusable result.

## 22.5 Provenance

- Docker tag points to new image;
- native binary changes at same path;
- dirty source changes;
- old schema;
- package environment differs;
- seed omitted.

Expected: fingerprint difference, explicit incompatibility or new run.

## 22.6 Metrics/comparison

- cycles compared with clocks;
- different flit bytes;
- different payload sizes;
- different node counts;
- different route policy;
- analytical lower bound compared as if equivalent to RTL;
- failed candidate hidden from Pareto;
- stochastic single sample ranked against deterministic result.

Expected: comparison refusal or explicit non-equivalent/acknowledged mode with no misleading winner.

## 22.7 Verification/reporting

- assertion file exists but formal tool fails to elaborate;
- BookSim not run;
- RTL not generated;
- route mismatch;
- analytical estimate lacks calibration.

Expected: `NOT_RUN/FAIL/INCONCLUSIVE`, never PASS inferred from configuration intent.

## 22.8 UI concurrency

- draft edited while old estimate is in flight;
- user starts run then changes draft;
- reconnect after browser closes;
- stale result arrives after newer result.

Expected: result is keyed by input/revision hash and cannot overwrite a different current draft.

## 22.9 Agent abuse/error

- enormous sweep;
- repeated retry loop;
- arbitrary path/binary attempt;
- invented topology ID;
- attempt to bypass comparison gate;
- request exceeding cost budget.

Expected: semantic validation/budget refusal, not shell execution.

---

# 23. What not to build yet

Until a concrete need proves otherwise, do not add:

- generic Runner/Backend/Provider/Factory hierarchies;
- generic workflow DSL;
- Celery/Ray merely because the old PRD listed it;
- Redis;
- Kubernetes;
- mandatory daemon;
- remote execution framework;
- arbitrary MCP shell;
- plugin framework;
- full physical floorplan editor;
- complex YAML inheritance;
- universal simulator base class;
- giant shared configuration object hiding backend-specific semantics;
- PKI infrastructure before a real signed-distribution requirement;
- a web UI that reimplements scientific logic.

---

# 24. Open questions that must remain explicit

Do not guess these in implementation:

1. Should congestion-unaware analytical be brought to the full `load/run` protocol, or intentionally remain a reduced dialect?
2. Is `Checking Non-Exited Systems ...` still a legitimate protocol terminator for every supported backend, or only legacy/specific modes?
3. What are the exact random sources and seed controls inside LLMServingSim scheduling/routing and the analytical backend?
4. What is the authoritative ASTRA `network.json` bandwidth unit and every conversion into simulator time?
5. What exactly is the intended granularity of Timeloop energy used by current reports?
6. What BookSim↔RTL properties are required to correlate exactly: zero-load latency, flit timing, throughput knee, topology ordering, or some subset?
7. Is the 2-die RTL path still load-bearing product work or research/archive material?
8. Which weighted-link semantics are required by planned Srota topologies? Until answered, keep weighted AnyNet out of certified v1 flow.
9. Which F1–F8 names should survive once each property is restated as an executable proof obligation?
10. What minimum implementation-tool integrations are required before the product may use “sign-off” language?

---

# 25. Definition of Done for the trusted engine before Studio productization

The engine is ready to support Studio v0 only when all of the following are true:

- package/runtime environment installs reproducibly from declared metadata;
- supported Python versions are truthful and tested;
- no verification path emits PASS without evidence;
- unsupported workload operations fail closed;
- representative workload lowering has conservation evidence;
- exact units/fidelity are persisted for new core metrics;
- BookSim-targeted certification uses the exact executed route semantics;
- weighted topology cannot silently pass through an unweighted certificate;
- LLMServingSim real-pipe protocol fixture passes normal and adversarial cases;
- tiny single- and multi-instance serving→BookSim goldens pass;
- serving→analytical semantics are explicitly validated per backend dialect/model;
- no-progress runs are diagnosable;
- plan/input/provenance fingerprints prevent stale reuse;
- initial run creation cannot be mistaken for complete after a partial write;
- comparison validation actively prevents uncontrolled ranking;
- failed candidates are visible;
- RTL route realization is mechanically tied to/checked against the authoritative route artifact;
- automated RTL functional smoke exists;
- formal status is derived from actual tool execution;
- E2 hard requirements affect candidate feasibility/search;
- analytical area/power/timing are labeled as estimates with assumptions;
- export includes actual files, hashes and evidence rather than placeholder artifact records.

A full customer “verified fabric” claim additionally requires the specific verification dimensions promised for that product tier to be PASS.

---

# 26. Definition of Done for Srota Studio v0

Studio v0 is done when:

- a user can author a mutable Draft and commit an immutable DesignRevision;
- the UI exposes LOCKED/GUIDED/FREE truthfully;
- LOCKED derived data is inspectable and evidence-linked;
- candidates can be generated and evaluated using the same engine APIs as CLI/tests;
- each visible metric shows unit, producer and fidelity;
- stale async results cannot attach to a different draft/revision;
- comparison cannot rank scientifically incompatible runs silently;
- verification shows an evidence matrix rather than one generic green status;
- selected design rationale references requirements and evaluated evidence;
- export bundle is content-addressed and reproducible enough to identify every input/tool artifact;
- no scientific logic exists only in React/FastAPI/UI code.

---

# 27. Evidence appendix — key independently inspected source locations

Paths are relative to the uploaded repository snapshot unless noted.

| Finding | Evidence |
|---|---|
| Package claims Python >=3.10 with no runtime deps | `tracks/t3-topology/dse/pyproject.toml:11,15` |
| UUIDv7 direct stdlib dependency | `tracks/t3-topology/dse/veritx_dse/core/runs.py:45-46` |
| Initial run files written directly | `.../core/runs.py:133-148` |
| Manifest later mutated by add_result | `.../core/runs.py:185-195` |
| Process group supervision | `.../core/process.py:48,118,177` |
| Unknown comm type skipped | `.../simulation/model_to_trace.py:148-156` |
| Invalid participants filtered/silently skipped | `.../simulation/model_to_trace.py:160-164` |
| Real BROADCAST input exists | `tracks/t3-topology/dse/models/automotive_adas.json` around flow-class definitions |
| Certifier defaults to MCLB | `.../tools/deadlock_routing.py:416` |
| Main cert leg omits method | `.../cli/cli.py:1760+` |
| Python BookSim replica uses +1 edge distance | `.../tools/deadlock_routing.py:279-309` |
| Canonical AnyNet parser discards weight after validation | `.../core/anynet.py:103-105` |
| BookSim AnyNet Dijkstra uses stored edge weight | `third_party/booksim2/src/networks/anynet.cpp:255-317`, especially 283 |
| LLM controller Waiting read boundary | `third_party/llmservingsim/serving/core/controller.py:30+` |
| LLM controller newline+flush write | `.../controller.py:63+` |
| Analytical multi-dim selects unaware lower-bound engine | `third_party/llmservingsim/serving/__main__.py:688-726` |
| Aware analytical supports queued load/run | `third_party/astra-sim/.../analytical/congestion_aware/main.cc:149-223` |
| Unaware analytical treats generic line as workload path | `.../analytical/congestion_unaware/main.cc:121-160` |
| RTL auto route-table behavior | `tracks/t3-topology/scripts/rtlgen/gen_rtl.py:915-960` |
| F1–F8 verification implementation | `.../model/compile_model.py:1337-1448` |
| Placeholder artifact records | `.../model/compile_model.py:1462+` |
| Default HMAC secret | `.../reports/artifact.py:27` |
| Physical-estimate caveats | `.../reports/reports.py:412-415` |
| ComparisonSpec exists | `.../core/spec.py:76+` |
| Formal harness exists | `tracks/t3-topology/scripts/rtlgen/router_formal.sby` |
| Formal run failed before proof | `tracks/t3-topology/scripts/rtlgen/router_formal/logfile.txt:6,11`; `router_formal/status` |
| Original product vision | `tracks/t3-topology/docs/SROTA-STUDIO-PRD-001.md` |
| Control-plane invariants/vertical-slice discipline | `tracks/t3-topology/docs/VERITX_ARCHITECTURE_HANDOFF.md` |

---

# 28. Final architecture position

The original Srota vision should be retained, but its old software stack/build order should not drive implementation.

The project should now optimize for one property:

> **Every customer-visible result must retain a mechanically checkable chain from immutable intent → exact derived fabric/workload artifacts → exact tool execution → typed metrics → explicit verification evidence.**

This does not require a giant framework. It requires removing the semantic duplications that have already proven dangerous:

- multiple route truths;
- multiple workload lowerings without conservation evidence;
- multiple metric vocabularies without units;
- verification statuses disconnected from actual checks;
- results disconnected from executable-environment identity.

Once those contracts are stable, the existing synthesis/simulation/RTL work becomes a strong foundation for Srota Studio rather than a collection of research paths that happen to agree on good days.

The immediate engineering instruction is therefore:

```text
Do the five narrow integrity repairs.
Then resume PR5 → PR6 → PR7.
Then extract only the semantic artifacts justified by those working paths.
Do not start Studio UI until the truth gates in this document are met.
```
