# Srota / VeriTX — Final Engineering Program

**Status:** implementation authority
**Date:** 2026-09-17
**Purpose:** complete the VeriTX execution substrate, Srota Fabric Compiler, verification path, and first trustworthy Srota Studio product surface without sacrificing scientific correctness.

---

# 0. Mission

Finish the system we have been building.

The end state is not merely a simulator CLI and not merely a web UI.

The intended system is:

```text
SROTA STUDIO
    Human-facing design/product surface
            │
            ▼
SROTA FABRIC COMPILER
    intent / workload / requirements
            │
            ├── workload semantics
            ├── topology synthesis
            ├── routing / VC derivation
            ├── feasibility
            ├── verification
            └── candidate selection
            │
            ▼
VERITX
    reproducible scientific execution substrate
            │
            ├── BookSim
            ├── LLMServingSim
            ├── ASTRA analytical
            ├── RTL / Verilator
            └── formal / implementation evidence
            │
            ▼
CANONICAL RESULTS + EVIDENCE
            │
            ▼
comparison / Pareto / verification / export
```

The product must ultimately allow a user to describe a workload and requirements, generate candidate fabrics, understand why they are feasible or infeasible, evaluate them at explicit fidelity levels, inspect verification evidence, compare scientifically compatible candidates, and export a reproducible design/evidence bundle.

The engineering constitution is:

> No result, proof, estimate, generated artifact, or product claim may lose the exact chain of evidence connecting it to the immutable intent, resolved workload/design semantics, implementation parameters, toolchain, assumptions, and execution that produced it.

A run that produces numbers is not automatically a valid result.

A tool returning exit code 0 is not automatically success.

A generated assertion is not automatically a proof.

A replay is not automatically a network simulation.

A certificate is not valid unless it certifies the behavior actually executed.

A comparison is not meaningful unless compatibility has been established.

---

# 1. Current verified checkpoint

Treat source, executable tests, and runtime artifacts as authority.

Documents and handoffs are useful context but are never the oracle.

Current live-tree checkpoint is approximately:

```text
Branch: epic/booksim-forward-port
Recent live suite: 971 passed, 1 skipped

Integrity PR A      VERIFIED
Integrity PR B      VERIFIED
Integrity PR C      VERIFIED
Integrity PR D      VERIFIED
Integrity PR E      VERIFIED

PR5 protocol fixture                 VERIFIED
PR5 liveness machinery               IMPLEMENTED / VERIFIED
historical replay livelock tests     PARTIAL EVIDENCE
real serving→BookSim golden          NOT YET ESTABLISHED
PR6 new control-plane serving slice  NOT YET COMPLETE
Studio                               NOT STARTED
```

The important known defects/open gaps are:

```text
NS-3 binary unavailable in current environment.

VeriTX does not preflight all serving feasibility before spawning.

Default BookSim serve path can be TRACE_REPLAY rather than real
network simulation.

Replay has historically been labeled in ways that can be mistaken
for full BookSim simulation.

pp_stage_boundaries is currently unsupported by the converter and
has been ignored in successful runs.

cmd_serve historically treated process exit 0 as success.

Existing cycle-accurate serving tests have not yet proven actual
fabric traffic strongly enough.

Historical multi-instance tests currently establish scheduler-side
progress using replay; they do not prove network-simulation correctness.

Routing certification has a BookSim stopgap but no final common
route representation shared by certifier, simulator, and RTL.

ASTRA/LLMServingSim/Timeloop metrics are not yet fully normalized.

ComparisonSpec exists but is not yet the universal enforced
scientific-comparison gate.

Requirements/E2 exist but still do not fully drive synthesis.

RTL generation exists but regression/equivalence evidence remains weak.

Formal infrastructure exists, but successful proof evidence is not
yet established.

Srota Studio has not been built.
```

Do not regress the already completed integrity work.

---

# 2. Agent operating rules

The following rules apply throughout the entire program.

## 2.1 Evidence hierarchy

When information disagrees, prefer in this order:

```text
real runtime behavior
    >
tests that exercise the real boundary
    >
current source code
    >
generated artifacts/manifests
    >
comments
    >
handoff documents
    >
old roadmap/PRD claims
```

Do not silently reconcile contradictions.

Record them.

---

## 2.2 Never repair scientific failures with guardrails

Do not solve:

* livelocks;
* missing progress;
* invalid routing;
* dropped workload semantics;
* simulator disagreement;
* invalid comparisons;

by introducing arbitrary timeouts, retry loops, max-round limits, filtering, or result suppression.

Timeouts may remain as containment/backstop mechanisms.

They are not root-cause fixes.

---

## 2.3 Fail closed

Unknown or unsupported load-bearing semantics must fail loudly.

Examples:

```text
unsupported communication kind
unknown PP lowering
ambiguous participant semantics
weighted topology without proven routing parity
unknown unit
incompatible comparison
route hash mismatch
unavailable backend
missing simulator executable
invalid model-memory placement
```

Never warn-and-continue when the ignored field can change scientific behavior.

---

## 2.4 Preserve bottom-up architecture

Do not create speculative abstraction hierarchies such as:

```text
BackendFactory
UniversalSimulator
ProviderManager
GenericRunnerFramework
ExecutionPluginRegistry
SessionServiceFactory
```

Concrete execution slices come first.

Extract shared mechanisms only after at least two or preferably three real paths demonstrate meaningful repeated semantics.

Use the deletion test:

> If deleting an abstraction would cause complex, error-prone semantics to be duplicated across several real call sites, it may be justified.

Otherwise leave the code concrete.

---

## 2.5 Immutable scientific identity

Every official execution must ultimately retain:

* resolved experiment/design identity;
* workload identity;
* topology identity;
* route identity;
* simulator/backend identity;
* relevant binary SHA256;
* dependency/environment identity;
* seed/randomness policy;
* exact generated simulator inputs;
* units;
* fidelity;
* assumptions;
* semantic losses;
* tool versions;
* result provenance.

Presentation metadata must not change scientific identity.

---

## 2.6 Commit discipline

Finish each phase as a bounded patch/commit.

Do not keep implementing through a failed gate.

At the end of each phase produce a short handoff containing:

```text
files changed
tests added
tests run
runtime artifacts created
known residuals
newly discovered contradictions
gate result: PASS / FAIL
next permitted phase
```

---

# 3. Target evidence chain

The eventual evidence chain is:

```text
CompileRequest / Experiment Intent
            │
            ▼
Immutable Design Revision
            │
            ▼
Resolved Design
            │
            ├── Workload semantic artifact
            ├── topology artifact
            ├── route artifact
            ├── VC artifact
            └── physical/model assumptions
            │
            ▼
Validation Certificate
            │
            ▼
Experiment Plan
            │
            ▼
Generated Simulator Inputs
            │
            ▼
Execution Attempts
            │
            ▼
Raw Results
            │
            ▼
Canonical Typed Metrics
            │
            ▼
Verification Evidence
            │
            ▼
Comparison / Pareto
            │
            ▼
Selected Design
            │
            ▼
Export Bundle
```

Every immutable object should eventually carry a content hash/schema version.

Downstream evidence refers to exact parent hashes rather than relying on future re-derivation.

---

# 4. Phase 0 — Freeze the current baseline

Before additional implementation:

1. Ensure A–E + PR5 + currently accepted liveness work are committed in coherent commits.
2. Push the branch.
3. Run the declared Python compatibility CI matrix.
4. Run the complete DSE test suite.
5. Record the baseline commit SHA in the next handoff.
6. Do not include unrelated generated files/caches in the commit.

Baseline gate:

```text
full relevant suite green
CI package install from declared metadata works
working tree does not contain accidental changes from previous sessions
baseline SHA recorded
```

If CI 3.12/3.13/3.14 exposes dependency/runtime errors, fix the environment contract before continuing.

---

# 5. Phase 1 — SERVE-INTEGRITY tranche

Implement these three tasks together because they establish whether `veritx serve` can be trusted.

---

## T1. Serving preflight

### Objective

Detect invalid serving execution before LLMServingSim is spawned.

### Required checks

At minimum:

```text
backend selected and supported
backend binary exists
backend binary executable
backend execution mode valid
dataset exists
cluster file exists
cluster structurally valid
model can fit configured NPU memory
TP/DP/PP/instance configuration structurally feasible
converter supports every load-bearing semantic required by workload
requested fidelity/mode is available
```

Do not replace LLMServingSim's own safety checks.

Mirror enough deterministic validation to fail earlier.

The original downstream validation remains a second line of defense.

### Required structured failure reasons

At minimum:

```text
BACKEND_UNAVAILABLE
BACKEND_BINARY_MISSING
BACKEND_BINARY_NOT_EXECUTABLE
DATASET_MISSING
CLUSTER_INVALID
MODEL_DOES_NOT_FIT
UNSUPPORTED_PARALLELISM
UNSUPPORTED_WORKLOAD_SEMANTIC
UNSUPPORTED_EXECUTION_MODE
```

Error messages should include concrete relevant values.

Example:

```text
SERVING_PREFLIGHT_FAILED

reason: MODEL_DOES_NOT_FIT
cluster: moe_tight_mem.json
node: 0
instance: 0
required_weight_memory_gib: 56
available_npu_memory_gib: 16
```

### NS-3 policy

Do not spend this phase building NS-3.

If the binary is absent:

```text
backend: ns3
availability: UNAVAILABLE
reason: BACKEND_BINARY_MISSING
```

and fail cleanly.

NS-3 does not block PR6.

### Tests

Include:

* missing backend binary refuses before spawn;
* non-executable binary refuses;
* model-too-large refuses before spawn;
* missing dataset refuses;
* PP workload/converter incompatibility refuses;
* known valid PP-free BookSim config passes preflight.

### Non-goals

No generic validation framework.

No NS-3 build system project.

No serving scheduling changes.

---

## T2. PP semantics fail closed

### Objective

Stop scientifically invalid DP/TP/PP runs from succeeding while discarding `pp_stage_boundaries`.

### Current policy

Until real PP lowering exists:

```text
pp_size > 1
AND converter cannot represent the exact PP semantics
→ UNSUPPORTED_WORKLOAD_SEMANTIC
→ fail before simulation
```

Do not merely print:

```text
pp_stage_boundaries ignored
```

and continue.

### Requirements

* vendored/source converter must raise;
* calling layer must surface structured reason;
* installed/imported converter must actually be the modified code;
* update vendored metadata describing the current unsupported capability;
* tests prove `pp_size == 1` behavior remains unchanged;
* tests prove PP configuration cannot return exit 0.

### Future degraded mode

Do not add `--allow-lossy` unless there is a concrete research requirement.

If such a mode is ever added, it must emit:

```text
fidelity: DEGRADED
semantic_losses:
  - pp_stage_boundaries
```

and automatically become ineligible for:

```text
goldens
certification
scientific ranking
requirements validation
```

---

## T3. Execution fidelity identity

### Objective

Make it impossible for TRACE_REPLAY to be confused with real network simulation.

### Required result fields

Every serving result must contain machine-readable fields equivalent to:

```json
{
  "engine": "llmservingsim",
  "network_backend": "booksim2",
  "network_mode": "REAL_SIMULATION",
  "fidelity": "SYSTEM_SIMULATION",
  "semantic_losses": []
}
```

or:

```json
{
  "engine": "llmservingsim",
  "network_backend": "booksim2",
  "network_mode": "TRACE_REPLAY",
  "fidelity": "TRACE_REPLAY",
  "semantic_losses": []
}
```

Allowed execution-mode vocabulary should be closed.

Do not derive validity from stdout wording.

### Golden eligibility

Define a helper/contract equivalent to:

```text
passes_serving_golden_gate =
    terminal_success
    AND network_mode == REAL_SIMULATION
    AND semantic_losses == []
    AND required metrics validated
    AND backend identity known
```

TRACE_REPLAY must explicitly fail the real-network golden gate.

### Exit-code behavior

`cmd_serve` may not equate `returncode == 0` with scientific success.

Success additionally requires:

```text
terminal completion semantics valid
all required requests retired
expected result schema valid
execution fidelity known
semantic losses acceptable for requested mode
```

### Phase 1 gate

The phase passes only when:

```text
the three previously observed failures are classified correctly:

NS-3 missing binary
→ preflight failure

oversized model
→ preflight failure

PP + replay case
→ PP fails closed before producing misleading success

and:

replay-only remains supported where useful
but cannot masquerade as real BookSim simulation.
```

STOP and produce handoff.

---

# 6. Phase 2 — Liveness evidence

Do not change scheduling behavior yet.

---

## T4. Complete liveness observability

Use the existing liveness/progress machinery instead of creating a second model.

Required observation state per serving round:

```text
round number
frontend simulated time
backend reported time/cycle
pending requests
deferred requests
retired requests
inflight batches
backend completion events
dispatch activity
last logical backend command
per-instance pending/inflight/retired state
```

Define useful-progress classifications equivalent to:

```text
USEFUL_PROGRESS

BACKEND_NOT_RESPONDING

BACKEND_RESPONSIVE_NO_TIME_ADVANCE

SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS

SCHEDULER_NO_DISPATCH

INFLIGHT_NO_COMPLETION
```

These labels describe observation states.

They do not claim root cause.

Record the complete logical command, not only a normalized `pass` category.

### Tests

Construct each state synthetically and prove it is distinguishable.

Reuse PR5's real-pipe `waiting_without_progress` fixture.

Do not alter timeout/spin thresholds to make tests pass.

---

## T5. Historical multi-instance baseline

Use the two known historical multi-instance configurations.

Run them with liveness instrumentation.

Archive:

```text
resolved config
command
progress fingerprints
per-instance retirement
final state
backend mode
fidelity
```

The current historical tests may use TRACE_REPLAY.

That is acceptable for validating scheduler-side progress only.

Do not call these network correctness tests.

### Required outcome

Each instance expected to receive work must actually demonstrate service/retirement.

Do not use only total request counters.

If either historical configuration hangs:

```text
STOP FEATURE WORK
    ↓
identify earliest invariant that stops changing
    ↓
trace owner of that state
    ↓
root-cause
    ↓
minimal fix
    ↓
permanent exact regression
```

A timeout/spin-abort is not a valid fix.

### Phase 2 gate

Pass if:

```text
liveness classifications are deterministic
historical configs terminate for understood reasons
per-instance progress evidence archived
no timeout threshold was used as the fix
```

STOP and produce handoff.

---

# 7. Phase 3 — T6: Prove real serving → BookSim execution

This is a mandatory architecture checkpoint.

Do not implement PR6 yet.

### Objective

Prove that the repository currently contains a real path:

```text
LLMServingSim
    ↓
AstraSim_BookSim2
    ↓
actual BookSim fabric activity
    ↓
network completion
    ↓
serving progress
```

Use the smallest possible:

```text
single instance
PP-free
tiny request
tiny topology/configuration
--cycle-accurate
```

### Required proof

Process exit 0 is insufficient.

TTFT/ITL output is insufficient.

At least one direct form of network evidence is required:

```text
nonzero packet/flit injection and ejection

OR BookSim network completion statistics tied to the workload

OR explicit execution ledger showing BookSim fabric calls

OR exposed communication/network cycles whose behavior demonstrably
depends on network activity
```

Prefer multiple independent indicators.

### Replay control experiment

Run the equivalent TRACE_REPLAY version.

Demonstrate that:

```text
REAL_SIMULATION and TRACE_REPLAY are machine-distinguishable
```

and that the real run has evidence unavailable in replay mode.

### Hard stop

If a real serving→BookSim path does not exist or cannot be demonstrated:

**STOP.**

Do not continue to PR6 under the assumption that it exists.

Write a root-cause/architecture handoff explaining whether:

```text
the backend path is unimplemented
the flag does not reach the backend
the workload never injects traffic
completion cannot propagate
the BookSim frontend is misconfigured
another boundary is broken
```

PR6 then changes from an integration task into implementation/fix of the real backend path.

### Phase 3 gate

Artifact must prove:

```text
network_mode = REAL_SIMULATION
semantic_losses = []
actual BookSim activity > 0
request completes
clean child shutdown
exact backend binary identity recorded
```

STOP and produce handoff.

---

# 8. Phase 4 — PR6: Official serving → BookSim vertical slice

Only begin if T6 passes.

### Objective

Add serving execution to the new VeriTX control plane.

Target:

```text
ExperimentSpec(mode=serving)
        ↓
strict resolve / hash
        ↓
immutable VeriTX run
        ↓
LLMServingSim
        ↓
real BookSim backend
        ↓
all requests retire
        ↓
typed serving result
        ↓
terminal validated run
```

### Required cases

#### Golden A — single instance

Tiny deterministic serving workload.

Must prove:

```text
all requests retire
real network activity exists
network_mode == REAL_SIMULATION
semantic_losses == []
terminal state valid
typed metrics valid
binary identity recorded
children terminated
```

#### Golden B — multi instance

Tiny workload that guarantees meaningful work reaches multiple instances.

Do not use a one-request case where one instance legitimately remains idle.

Assertions must be per-instance.

Must detect/reject incorrect completion rebinding.

### Process ownership

All processes/child process groups must have explicit lifecycle ownership.

Ctrl-C and failure must terminate owned children.

Malformed/partial backend output must fail loudly.

### Result requirements

Serving result must include:

```text
request count
completed/retired count
simulation time/clock
TTFT where defined
TPOT where defined
ITL where defined
wall time
network backend
network mode
fidelity
semantic losses
backend binary identity
relevant workload/config hashes
```

Units must be explicit.

Do not rename `clocks` to `cycles` unless proven equivalent.

### Negative tests

Required:

```text
TRACE_REPLAY cannot satisfy real BookSim golden

semantic loss cannot satisfy golden

partial backend output cannot become success

backend crash cannot produce terminal scientific result

malformed reply cannot produce partial accepted metrics

missing backend fails preflight

invalid memory configuration fails preflight
```

### PR6 Definition of Done

All of the following:

```text
[ ] strict ExperimentSpec serving mode
[ ] single-instance real BookSim golden
[ ] multi-instance real BookSim golden
[ ] fabric activity proven by test
[ ] all requests retire
[ ] per-instance ownership proven
[ ] zero semantic losses
[ ] typed metrics
[ ] binary/tool provenance
[ ] clean process ownership
[ ] negative replay test
[ ] malformed output test
[ ] immutable terminal run
```

---

# 9. Phase 5 — Serving metric semantics

Now define what serving numbers actually mean.

Create a canonical serving vocabulary.

At minimum distinguish:

```text
sim_clock
request_arrival_time
request_completion_time
request_latency
TTFT
TPOT
ITL
requests_submitted
requests_retired
backend/network exposed communication
wall_time
```

For every metric store:

```text
name
value
unit
producer
fidelity
scope
formula/derivation where nontrivial
```

Do not silently convert:

```text
clocks ↔ cycles
bytes ↔ flits
seconds ↔ simulated clocks
```

Conversions must be explicit and provenance-recorded.

Metric schemas should be versioned.

---

# 10. Phase 6 — PR7: Serving → analytical

Create a second concrete serving slice.

Do not pretend analytical is a single homogeneous backend.

PR5 established different frontend behavior.

Explicitly represent at least:

```text
analytical_congestion_aware
analytical_congestion_unaware
```

or an equivalent concrete capability distinction.

Backend selection must become data/provenance rather than silent implementation detail.

### Required goldens

One tiny supported golden for every analytical frontend intended to remain product-supported.

Record:

```text
backend binary
protocol command form
network mode
fidelity
payload semantics
units
```

### Critical requirement

If the congestion-aware and congestion-unaware binaries fundamentally require incompatible serving semantics that cannot be represented honestly behind one serving loop:

**STOP and architecture-review the boundary.**

Do not hide incompatibility inside conditional string handling.

---

# 11. Phase 7 — Semantic-compression architecture review

At this point there should be three trustworthy paths:

```text
standalone BookSim
serving → BookSim
serving → analytical
```

Now compare them.

Extract shared mechanisms only where warranted.

Likely shared mechanisms may include:

```text
run initialization/finalization
process ownership
binary identity/provenance
artifact writing
metric typing
failure classification
diagnostic attachment
```

Do not unify semantics that actually differ.

Do not build a universal simulator inheritance tree.

Document the final control-plane boundaries.

---

# 12. Phase 8 — Scientific comparison integrity

Activate `ComparisonSpec`.

A comparison/ranking operation must declare:

```text
experimental variables
controlled dimensions
allowed structural differences
replication policy
```

Before comparing candidates, validate relevant dimensions including:

```text
workload hash
node count
participant count
packetization/flitization
routing identity
VC configuration
simulator
fidelity
payload/message size
seed policy
model/tool version
```

A difference must be:

```text
the intended experimental variable
OR explicitly acknowledged as accepted
```

otherwise comparison refuses.

### Stochastic runs

Record at least:

```text
seed list
sample count
mean
spread / standard deviation
confidence interval where appropriate
```

### Candidate visibility

Failed candidates remain visible.

Do not silently remove failed/error candidates from Pareto construction.

Pareto statements must clearly describe the evaluated candidate scope.

---

# 13. Phase 9 — Canonical Workload semantic artifact

The current independent lowering paths are too lossy.

Introduce a persisted workload semantic representation only after examining the real BookSim/ASTRA/serving needs.

It must preserve enough information to prevent semantic divergence, including as applicable:

```text
phases
communication kinds
participants
source/destination semantics
message sizes
collectives
dependencies
ordering
tensor/dataflow meaning where required
compute gaps
serving phases
synchronization
parallelism structure
```

Avoid a universal theoretical IR.

Model only semantics the current system demonstrably needs.

### LoweringManifest

Every projection/lowering produces a manifest with at least:

```text
source workload hash
lowerer version
operation/class counts
packet/message counts
total bytes
participant counts
unsupported classes
semantic losses
output artifact hashes
```

### Conservation tests

Golden workloads must prove preservation of:

```text
participants
collective count
message count
byte volume
ordering/dependencies where semantically required
```

### BROADCAST

The current "first participant = source" behavior remains PROVISIONAL unless the source schema explicitly guarantees ordering.

Do not make it a product semantic by convention.

Either:

```text
prove the existing schema defines it
```

or introduce explicit:

```text
source
destinations
```

semantics.

---

# 14. Phase 10 — RouteArtifact: one routing truth

The temporary BookSim certification stopgap is not the final design.

Create one content-addressed exact routing artifact.

Conceptually:

```text
RouteArtifact
    schema_version
    topology_hash
    routing_algorithm
    tie_break_policy
    weights/latencies if applicable
    per (router,destination[,class]) next-hop behavior
    route_table_hash
```

Eventually:

```text
certifier consumes RouteArtifact
BookSim consumes/verifies RouteArtifact
RTL consumes/verifies RouteArtifact
```

No subsystem should independently reinterpret the routing algorithm and merely hope it agrees.

### Weighted topology policy

Keep weighted AnyNet rejected until weight semantics are proven and preserved end-to-end.

Do not silently reduce weighted graphs to unit adjacency.

### VC artifact

Once routing truth is stable, represent VC assignment explicitly.

The eventual deadlock certificate must reason over:

```text
(channel, VC)
```

where the routing implementation actually uses VC classes.

Do not claim VC-aware deadlock proof while only checking physical channel CDG.

---

# 15. Phase 11 — RTL credibility

Build automated RTL regression infrastructure before making stronger product claims.

Start small:

```text
4×4
8×8
```

Test:

```text
build succeeds
routing tables match authoritative artifact
reachability
packet delivery
packet conservation
ordering where required
credit/flow behavior
timeout/no-stall
clean completion
```

Use Verilator in CI where practical.

### BookSim ↔ RTL correlation

Do not demand raw cycle equality without first establishing matching microarchitectural semantics.

Treat separately:

```text
zero-load latency
pre-knee latency trend
accepted throughput
saturation/knee
post-knee behavior
flit timing where genuinely equivalent
```

Investigate the historical large post-knee mismatch.

Define a correlation contract before defining a parity threshold.

A correlation failure is evidence, not something to normalize away.

---

# 16. Phase 12 — Formal proof execution

The project already contains formal/SVA infrastructure.

Move from:

```text
assertions emitted
formal attempt exists
```

to:

```text
property actually proven
```

One property at a time.

Every formal property should record:

```text
property ID
scope
formal statement
assumptions
tool/version
proof result
counterexample if failed
artifact hash
```

No `PASS` without a successful prover result.

Generated SVA remains `NOT_RUN` until proof executes.

If Yosys/SymbiYosys parsing currently fails, repair the smallest harness/tool compatibility issue first.

Do not downgrade unsupported RTL constructs merely to get green proof unless behavioral equivalence is demonstrated.

---

# 17. Phase 13 — Requirements-driven Fabric Compiler

This is where Srota becomes a real intent-to-fabric compiler.

Today E2 Requirements largely exist as data.

They must actively constrain synthesis/evaluation.

Requirements should map to:

```text
hard constraints
soft optimization objectives
explicit preferences
```

Examples:

```text
latency bound
throughput floor
power budget
area budget
radix constraint
link-length constraint
reliability/verification requirement
allowed topology/fidelity
```

### Compiler result

The compiler must return one of:

```text
FEASIBLE
    candidate set
    evaluated metrics
    constraints satisfied
    Pareto evidence

NO_FEASIBLE_DESIGN
    violated constraints
    evidence
    candidate/search scope
    useful relaxation information where possible
```

Never silently relax a hard requirement.

### Candidate set

Preserve:

```text
candidate identity
generation method
search budget
objective values
constraint verdicts
failed evaluations
pruning reason
fidelity
seed policy
```

Do not store only a winner.

---

# 18. Phase 14 — Finish VeriTX control-plane migration

Migrate remaining functionality behind the new library control plane.

Order approximately:

```text
sweep
compare
workload
trace
report
history/run browser
diagnostics
```

Make Python CLI thin.

`t3` should gradually become compatibility forwarding rather than owning semantics.

Do not rewrite working functionality simply for aesthetic reasons.

### Run store

Wire discovery/indexing to immutable `veritx-runs` manifests.

The index remains rebuildable and non-authoritative.

### Recovery

Implement stale-run classification:

```text
RUNNING + dead owner / restart
→ INTERRUPTED
```

Do not automatically claim retry/resume semantics.

### Attempts

If retry becomes necessary, preserve attempts instead of overwriting execution evidence.

### Resume/cache

Only add after a stable dependency fingerprint exists.

Never use:

```text
output file exists → skip
```

Resume/cache identity must include relevant:

```text
scientific inputs
simulator binary identity
tool version
generated configuration
seed
routing/workload hashes
```

---

# 19. Phase 15 — Srota Studio v0

Only start after the core truth gates above are satisfied.

Studio v0 is deliberately narrow.

Required flows:

```text
1. Define workload / choose workload preset
2. Define system requirements
3. Compile/generate candidate fabrics
4. Inspect candidate topology
5. Inspect route/verification evidence
6. Run supported evaluations
7. Compare scientifically compatible candidates
8. Understand infeasibility/failure
9. Select design
10. Export reproducible evidence bundle
```

Required views:

```text
Workload / Requirements
Candidate List
Logical Topology
Verification Evidence
Runs / Diagnostics
Comparison / Pareto
Export
```

Do not begin with:

```text
full physical floorplan editor
multi-user collaboration
distributed scheduling
Kubernetes
complex permissions
generic agent marketplace
plugin system
```

### Live updates

UI results must be tagged by exact revision/hash.

If a user changes the draft while a run is executing, stale results cannot be attached to the new draft.

Conceptually:

```text
draft_revision_id
input_hash
result_parent_hash
```

must agree before UI displays a result as current.

---

# 20. Verification maturity model

Use explicit evidence levels instead of one vague "verified" label.

Recommended:

```text
V0 STRUCTURAL
topology/connectivity/basic totality

V1 ROUTING
exact route artifact + routing validation

V2 DEADLOCK / VC
VC-aware transition proof/certificate

V3 FUNCTIONAL RTL
delivery/conservation/ordering/flow-control simulation evidence

V4 FORMAL
properties proven by formal engine

V5 IMPLEMENTATION
synthesis / STA / physical evidence
```

Every product claim states its level.

Example:

```text
Deadlock-free
Verification level: V2
Artifact: ...
Route hash: ...
Assumptions: ...
```

Do not use V4 wording for generated but unproven assertions.

---

# 21. Fidelity model

Every result must identify fidelity.

A useful hierarchy is:

```text
L0 ESTIMATE
analytical / quick model

L1 NETWORK
BookSim or equivalent network simulation

L2 SYSTEM
LLMServingSim + network model

L3 RTL
cycle/detail RTL execution

L4 IMPLEMENTATION
synthesis / STA / physical evidence
```

TRACE_REPLAY is a separate execution mode and should not masquerade as L1/L2 simulation.

Every number should expose:

```text
producer
fidelity
assumptions
calibration status
unit
```

Analytical area/power/Fmax outputs remain **estimates** until calibrated against implementation/tool evidence.

Do not label them sign-off reports.

---

# 22. Artifact/export bundle

Once the compiler/result semantics stabilize, build a reproducible export.

Bundle should contain as applicable:

```text
resolved design
workload semantic artifact
topology
RouteArtifact
VC artifact
RTL
UVM/SVA
verification certificates
formal evidence
simulation results
typed metrics
requirements verdict
tool/provenance manifest
checksums
```

The existing HMAC seam is not full PKI.

Use explicit naming:

```text
CHECKSUMMED_UNSIGNED
HMAC_SIGNED
```

until proper signing infrastructure exists.

Do not imply cryptographic identity/authenticity beyond the implemented mechanism.

---

# 23. Agent-safe semantic API

Do this only after the control plane is stable.

Expose narrow semantic operations such as:

```text
list_capabilities
list_workloads
list_topologies

validate
compile
plan
execute

get_run
get_results
compare
diagnose
cancel
```

The agent should not receive arbitrary:

```text
shell
Docker commands
host paths
environment mutation
```

Resource budgets should exist:

```text
max tasks
max parallelism
runtime budget
output budget
trace expansion budget
expensive-run threshold
```

MCP, if added, is a thin adapter to these semantic operations.

It is not the architecture itself.

---

# 24. Further improvements after Studio v0

These are legitimate future improvements but are not allowed to block the main program.

## NS-3 backend enablement

After BookSim/analytical paths are trustworthy:

```text
build/pin NS-3
record binary identity
add tiny network golden
integrate preflight
give it explicit fidelity
```

Do not merely make the path exist.

---

## Physical-estimate calibration

Correlate analytical area/power/Fmax models against:

```text
RTL synthesis
STA
floorplan/P&R
real library/PVT assumptions
```

Attach:

```text
process node
library
PVT
calibration source
expected error range
```

to estimates.

---

## SystemC

Add only if a concrete integration/customer need justifies it.

Do not implement because the old PRD once mentioned it.

---

## Better reproducibility

Eventually capture:

```text
container image digest
host/kernel identity when relevant
dirty-patch identity
native shared-library identity
solver version/thread settings
random tie-break behavior
```

Official reproducibility mode should deliberately pin nondeterministic settings.

---

## Integrity scans

Add artifact checksum verification and eventually backup/replication for immutable run evidence.

---

## On-prem/security

Preserve engine separability so core compilation/execution can run locally/on-prem.

Imported topology/workload files should be treated as hostile input.

Workers should not possess unrelated cloud credentials or signing keys.

---

## Multi-user/distributed execution

Only after local semantics are stable.

If distributed execution is added:

```text
task identity
attempt identity
idempotency
ownership
cancellation
result finalization
```

must already be explicit.

Do not let distributed infrastructure become the owner of scientific semantics.

---

# 25. Mandatory stop conditions

Immediately stop the current phase and create an architecture/root-cause handoff if any of the following occurs:

```text
No real LLMServingSim → BookSim network path can be demonstrated.

The only way to make multi-instance serving terminate is a timeout,
round guard, or ignored work.

PP semantics cannot be represented without fundamentally changing the
current workload model.

Completion events cannot be reliably rebound to the correct instance
or request.

Analytical frontend protocols cannot be supported without silently
changing serving semantics.

Routing executed by simulator cannot be represented/certified by the
canonical route model.

A generated design satisfies requirements only because a hard
constraint was silently relaxed.

A result requires discarding load-bearing semantics.

A comparison requires mixing unknown/incompatible units or fidelity.

RTL correlation reveals that the assumed network model and generated
RTL represent fundamentally different architectures.

Formal proof requires changing the RTL behavior rather than repairing
the proof harness.

Any "fix" consists primarily of lowering an abort threshold.
```

Do not continue merely to preserve roadmap momentum.

---

# 26. Testing strategy

Maintain layered tests.

## Level 1 — pure scientific/domain semantics

```text
spec validation
hash identity
lowering conservation
route artifact identity
comparison compatibility
requirements feasibility
metric typing
```

## Level 2 — real OS/process fixtures

```text
success
nonzero exit
hang
SIGTERM ignored
stderr flood
unexpected EOF
partial output
Ctrl-C
descendant cleanup
```

## Level 3 — protocol fixtures

```text
startup
command/reply
Waiting
delayed reply
no-progress
malformed reply
EOF
crash
shutdown
```

## Level 4 — tiny real simulator goldens

At minimum eventually:

```text
standalone BookSim
serving → BookSim
serving → analytical aware
serving → analytical unaware if supported
RTL small topology
formal small property
```

## Level 5 — migration parity

When replacing old `t3` semantics:

run old and new on the same tiny corpus.

Differences must be classified as:

```text
expected improvement
old bug
new bug
simulator nondeterminism
semantic change
```

Neither implementation is automatically the oracle.

---

# 27. Definition of final program completion

The current program is considered complete enough for Srota Studio v0 when all of the following are true:

```text
[ ] Environment installs reproducibly from declared metadata

[ ] Immutable run identity/lifecycle is stable

[ ] Backend preflight prevents known impossible executions

[ ] Replay and real simulation cannot be confused

[ ] Load-bearing unsupported semantics fail closed

[ ] Single-instance real serving→BookSim golden passes

[ ] Multi-instance real serving→BookSim golden passes

[ ] Analytical serving goldens pass for supported variants

[ ] Historical multi-instance livelock has a root-cause regression,
    not merely a guardrail

[ ] Workload lowering is conservation-checked

[ ] Canonical workload artifact exists

[ ] Canonical routing artifact exists

[ ] Certification references exact executed routing

[ ] ComparisonSpec is enforced

[ ] Typed metric/unit/fidelity schema is used by official paths

[ ] Failed candidates remain visible

[ ] Requirements constrain synthesis

[ ] Infeasible requirements return explicit infeasibility

[ ] RTL small-topology regression is automated

[ ] RTL routing matches authoritative route artifact

[ ] Simulator↔RTL correlation contract exists

[ ] Formal status distinguishes emitted/attempted/proven

[ ] At least the targeted formal properties have successful proof evidence

[ ] Python control plane owns official scientific semantics

[ ] Legacy t3 functionality is forwarding or explicitly legacy

[ ] Index is rebuildable from immutable run artifacts

[ ] Studio can create/inspect/run/compare/export a design

[ ] Studio never attaches stale results to a changed design revision

[ ] Export bundle contains exact scientific evidence chain
```

---

# 28. Immediate implementation order

Unless a stop condition fires, execute in this exact order:

```text
PHASE 0
Freeze baseline / CI

PHASE 1
T1 Serving preflight
T2 PP fail-closed
T3 Execution-mode identity

PHASE 2
T4 Liveness completion
T5 Historical livelock evidence/root-cause if needed

PHASE 3
T6 Prove real BookSim fabric execution
*** HARD CHECKPOINT ***

PHASE 4
PR6 serving → BookSim

PHASE 5
Serving metric contract

PHASE 6
PR7 serving → analytical

PHASE 7
Semantic-compression architecture review

PHASE 8
ComparisonSpec enforcement

PHASE 9
Canonical Workload semantic artifact

PHASE 10
RouteArtifact + eventual VC artifact

PHASE 11
RTL regression + simulator/RTL correlation

PHASE 12
Formal proof execution

PHASE 13
Requirements-driven synthesis / candidate set / Pareto

PHASE 14
Remaining VeriTX control-plane migration + recovery

PHASE 15
Srota Studio v0

PHASE 16
Reproducible export + agent-safe semantic API

POST-V0
NS-3, physical calibration, stronger signing, on-prem hardening,
distributed execution/multi-user only when justified
```

---

# 29. How to work through this program

You may continue from one successful phase into the next without asking routine questions.

However:

* make bounded commits;
* run the appropriate tests at each phase;
* preserve evidence;
* produce a short handoff after every phase;
* do not skip gates;
* do not reinterpret failed gates as "good enough";
* do not broaden scope merely because an adjacent feature is easy to add.

When a stop condition fires, stop implementation and write the evidence/root-cause handoff.

The objective is not maximum code volume.

The objective is that, at the end, Srota and VeriTX can make claims that are actually true.

---

# 30. Final product standard

The finished system should make the following workflow possible:

```text
User:
"I have this workload and these requirements."

Srota:
"I resolved that intent into this exact workload/design representation."

Srota:
"These candidate fabrics are feasible.
These were rejected for these explicit reasons."

VeriTX:
"I evaluated these candidates under these exact simulator/fidelity
conditions with these exact binaries, seeds, routes, workloads, units,
and assumptions."

Verification:
"These exact properties were checked.
These passed.
These were assumptions.
These were not run.
These were formally proven."

Comparison:
"These candidates are scientifically compatible for this comparison.
These are the intended variables.
Here is the Pareto frontier for the evaluated scope."

User:
"Select this one."

Srota:
"Here is the resolved design, RTL, verification collateral,
simulation evidence, metrics, provenance, and reproducible export
bundle corresponding exactly to the design you selected."
```

That is the finish line.

Do not optimize for looking complete before the evidence chain is complete.

