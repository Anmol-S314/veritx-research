# Federation v1.1 — deferred capabilities ledger (P5 §15)

Each entry names the SEMANTIC PREREQUISITE for integration, not a
package to vendor. A capability enters the federation only when a
registered adapter can answer a closed-vocabulary question with
authentic evidence through the generic seam (prepare → execute →
normalize) under a pinned producer. A package merely existing in the
tree is never, by itself, a reason to integrate.

## Collective communication libraries

### SimCCL / NCCL (GPU collectives)
Prerequisite: a canonical collective-semantics lowering from declared
TP/EP/DP operations to the library's algorithm set, with a proven
intent→collective mapping per workload kind (the MoE lesson: no
representation is flattened or relabeled to fit). Plus: a pinned
producer identity for the library build and an evidence tier the
admission authority accepts.

### MSCCL / TACCL (synthesized collectives)
Prerequisite: everything SimCCL/NCCL requires, plus a canonical
artifact for the synthesized algorithm itself (what was synthesized,
for which exact topology and message sizes) so a run reproduces the
same algorithm rather than re-synthesizing.

## Scale-out and system simulation

### ns-3 / SimAI (scale-out congestion, RTL-adjacent behavior)
Prerequisite: a closed question the federation actually asks
(e.g. SCALE_OUT_CONGESTION) with normalized metrics whose units and
dimensions are declared up front; a namespace/injection discipline
equivalent to the ASTRA one (no autonomous traffic ever unattributed);
and per-domain timing oracles before any numerical claim is admitted
(the ASTRA numerical-timing bar applies equally here).

### SimCXL (CXL-attached memory)
Prerequisite: a canonical heterogeneous InfrastructureGraph, a
MemoryTransactionArtifact, and CXL address/transaction ownership
(who owns each address range, which agent issues each transaction).
Never integrate merely because a package exists: without proven
ownership, a CXL simulation cannot attribute a single byte.

## RTL and physical truth

### FlooNoC RTL (cycle-accurate NoC)
Prerequisite: the RTL engine's qualification row closed (currently the
qualification authority carries an `rtl` engine entry — integration
requires its numerical and independence gates to pass, not merely to
exist), plus a canonical RTL-behavior question with a pinned
toolchain (simulator version, flags) recorded in the build manifest.

### m4 screening (fast design-space screening)
Prerequisite: a proven fidelity contract stating exactly what the
screening model preserves and what it discards per SemanticDimension,
so a screened candidate that reaches the certified backends is a
ranking hint, never evidence.

## Estimation and observability

### Timeloop / Accelergy (compute/memory estimation)
Prerequisite: workload compute/memory demand expressed as canonical
artifacts with an explicit analytical-vs-measured label (ANALYTICAL
estimates never enter the authenticated evidence chain as measurements;
the wave-E memory rule — analytical bandwidth, deferred capacity —
already says this).

### Perfetto export (trace visualization)
Prerequisite: a canonical trace-export schema whose timestamps carry
their clock authority (SERVING_LOGICAL_CYCLE / MODEL_SERVICE_CYCLE /
NETWORK_BOOKSIM_CYCLE are never mixed). Export is a view over
authenticated evidence, never a new authority: re-importing an
exported trace must be refused as evidence.
