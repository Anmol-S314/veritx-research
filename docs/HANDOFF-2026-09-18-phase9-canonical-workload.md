# HANDOFF — Phase 9: canonical workload semantics

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port`
**Prior gate:** Phase 8 (1087 passed, 1 skipped)
**Next permitted:** Phase 10 (RouteArtifact) — **STOP here until reviewed.**

## What landed

One versioned, content-addressed **WorkloadArtifact** (`veritx_dse/workload/`)
that is the semantic parent of the serving execution path — proven by the
reviewer's sufficiency test: **both backend inputs are regenerable from the
artifact alone, byte-identical to what the child actually executed**, on a
real run.

```
veritx_dse/workload/canonical.py   artifact, validation, hashing, conservation
veritx_dse/workload/lowering.py    rows projection + ET lowering + LoweringManifest
veritx_dse/workload/serve.py       run-level canonicalization (traces → artifacts → index)
```

## Audit map (§2) — what the live paths actually carry

```text
Path B (serving):  request/batch → trace_generator.generate_trace
                   [SEMANTIC SOURCE: comm_type/comm_size/involved_dim,
                   TP=ALLREDUCE, MoE=ALLGATHER/REDUCESCATTER or ALLTOALL,
                   PP=NONE rows → converter SEND/RECV pairs]
                   → text trace (persisted under run-owned inputs root)
                   → in-process chakra LLMConverter → llm.<npu>.et
                   (compute chained per-rank; EXPERT rows → group
                   collectives; mem nodes from inp/wt/out sizes and
                   LOCAL/REMOTE:<dev> locations; PP → SEND/RECV comm_tag)
                   → ASTRA Workload.cc → BookSim | AnalyticalAstra(Unaware)

Path A (standalone): traffic_model.json → model_to_trace decomposers
                   (fail-closed validate + LoweringManifest — PR C).
                   NOT rewritten in Phase 9 (residual, see below).

EXISTS:    kinds, byte sizes, dim scopes, participants, compute ns,
           mem sizes, mem locations (LOCAL/REMOTE:<dev>), batch tags
INFERRED:  PP send/recv (adjacent layer sizes), comp_time (perf DB),
           EXPERT membership (instance group), npu_id mapping
DEFAULTED: involved_dim None → backend fabricates ALL dims;
           bcast_root defaults 0; npus_per_group==1 silently disables
           ALLREDUCE (use_comm=False)
DROPPED:   (Slice A only) compute/memory nodes
UNKNOWN:   BROADCAST source — no emitter in serving; Slice-A convention
           provisional → resolved this phase (ruling below)
```

## Schema (§3/§22) — derived from audit, not invented

`WorkloadArtifact` (frozen dataclass, `SCHEMA_VERSION = 1`):

```text
schema_version · workload_id · source_kind · parallelism{tp,dp,ep,pp}
num_participants · ops[tuple[WorkloadOp]] · artifact_hash (computed)
```

`WorkloadOp` (frozen, one class — no plugin registry, no visitors):

```text
op_id · kind · label (presentation, hash-excluded)
COMPUTE:  duration_ns · input/weight/output_bytes · input/weight/output_loc
          (loc = explicit "LOCAL" | "REMOTE:<dev>[.<chan>]" | "CXL" |
          "STORAGE", validated) · batch_tag
SEND/RECV: bytes · src/dst · comm_tag
ALL_REDUCE/ALL_GATHER/REDUCE_SCATTER/ALL_TO_ALL/BARRIER:
          bytes · participants · scope (explicit tuple of dims or
          ALL_DIMENSIONS sentinel — never absence)
BROADCAST: bytes · participants · source (explicit int) · destinations
EXPERT_BEGIN/EXPERT_END: enum · optional comm_kind/bytes/participants/scope
```

Why: every field maps to something a live consumer reads (converter,
ASTRA `Workload.cc` dispatch, or conservation math). No SSA, no DAG
framework, no arbitrary nesting (§22 honored).

## Rulings

**BROADCAST (§6) — Case B.** No source format guarantees
`participants[0] = source`: serving never emits BROADCAST, and Slice A's
`traffic_model.json` has no source field. The canonical representation
therefore carries **explicit `source` + `destinations`** (ASTRA already
has `bcast_root`). The old first-member convention is gone from the
canonical layer; lowering to ET **refuses** (`UnsupportedSemantic`) until
the converter emits `bcast_root` — an inspection projection with
per-row roots exists for BROADCAST workloads instead. No zero-loss
manifest is possible from an unsupported semantic (§11).

**involved_dim / scope (§7).** Scope is either an explicit dim tuple or
the `ALL_DIMENSIONS` sentinel — **absence is not representable**. The
canonicalizer maps the source's documented `involved_dim=None` semantics
("all dims", per the generator contract) *to the sentinel explicitly*;
the backend's fabrication fallback is never relied upon, because the
lowered rows always carry an explicit `:1,0`-style scope. The Phase-9
involved-dim tripwire (fabric-vs-spec) stays armed at run level.

**PP (§8).** The artifact can *represent* PP (parallelism.pp, and
SEND/RECV ops are representable), but canonicalization of traces with
`pp_stage_boundaries` **refuses** (Phase 1 T2: the converter has no PP
semantics and would hand every rank the unpartitioned graph). Capability
and lowering capability stay separated; nothing re-enabled PP.

**Units (§10).** Bytes are explicit logical bytes end to end; the trace
grammar's mem columns are byte sizes (converter-verified); no unit
conversion happens anywhere in canonicalization or lowering.

**Locations (new ruling, found by the byte-parity gate).** The trace's
`inp_loc/wt_loc/out_loc` columns are converter-consumed semantics — ASTRA
dispatches `issue_remote_mem` on `tensor_loc`/`tensor_device`. The first
canonicalizer dropped them (defaulting LOCAL); the live byte-parity test
caught it (2/534 nodes differed). Canonical form: the location string
carried verbatim and validated against the converter grammar
(`LOCAL | REMOTE:<dev>[.<chan>] | CXL | STORAGE`), part of identity —
REMOTE→LOCAL changes memory-side timing.

## Labels: presentation vs identity (§16)

ET node names embed source layer labels (`embedding_0`); ASTRA dispatches
purely on node type/attrs (`Workload.cc:244`) — names feed debug logs, so
they are **presentation**. Resolution: labels ride the serialized artifact
as a **presentation sidecar** (so lowering can reproduce executed bytes
exactly) but are **stripped from `_identity_dict`** — the artifact hash
never covers them. Pinned by `test_label_is_presentation_not_identity`
plus the roundtrip sufficiency test.

## Conservation (§13)

`check_conservation(source, lowered)` — order-sensitive, mechanical:

```text
op count preserved (with kind-by-kind diff on mismatch)
per-op: kind preserved · participants preserved · scope preserved
        bytes preserved (comm ops)
```

`et_readback_conservation` verifies a lowering against **real ET bytes**
(read back via `et_def_pb2`, accepting both `uint64_val` and `int64_val`
attr encodings seen across converter versions): per-rank comm bytes,
op classes, participants, per-rank dim scopes. Conservation failure is a
`ConservationError` — a lowering failure, never a warning.

## Hashing rules (§16)

Content identity = sorted-ops JSON of `_identity_dict` (labels excluded,
op order included — the ET lowering chains nodes positionally, so order
is semantic). Same semantics → same hash even if batches/instances were
saved separately (verified on the real tree: 179 traces → 120 distinct
hashes; identical batches across instances collapse). Semantic change
(participant, size, scope, dependency position, location) → different
hash. No timestamps, no paths, no run IDs.

## Integration (§14/§17)

- **Run provenance**: the slice runs the child with a run-owned
  `--inputs-root` + `--save-trace-text` + `--run-id`; after a verified
  run, every saved trace canonicalizes to
  `<run>/workload/<name>.workload.json` + deterministic
  `workload/index.json`; the result carries
  `workload: {identity: sha256:…, certified: true, artifact_count: N}`.
  Canonicalization failure **fails the run** (`WORKLOAD_CANONICALIZATION_FAILED`).
- **ComparisonSpec**: `fingerprint_from_run` consumes the canonical
  identity when the index exists (`workload_certified=True`); legacy rows
  remain `certified: false` / `INSUFFICIENT_PROVENANCE` — not weakened.
- **Fake runs** in tests now save a production-grammar trace (what the
  real child writes) instead of the slice tolerating trace-less runs.

## Goldens (§19/§21) — live evidence

- **PR6 Golden-A** (serving → embedded **BookSim**, REAL_SIMULATION):
  run SUCCEEDs with `workload.certified=True`; artifact-alone
  regeneration via `rows_from_artifact → lower_to_et` (the exact
  production converter) produces ETs **byte-identical** (sha256) to the
  child's executed `inputs/workload/**/llm.*.et`. 70/70 nodes + metadata
  match on the debugged run; 534/534 nodes matched after the location fix.
- **PR7 Golden-C/D** (analytical aware / unaware): both SUCCEED with the
  same canonical provenance riding the run; the unaware engine's
  `exposed_communication=0` honesty from Phase 8 is untouched.
- Pre/post parity: the executed backend inputs *are* the pre-Phase-9
  artifacts; byte-identity of regeneration is the parity proof (stronger
  than metric comparison). Serving metrics within the run unchanged
  (same ETs → same simulation).

## Tests added

`tests/test_workload_canonical.py`: **48 tests** — construction/fail-closed
(unknown op, bad participants, out-of-range rank, bad membership, unknown
comm_type), BROADCAST explicit-source pinning, scope sentinel vs explicit,
PP refusal, units, location grammar, hashing rules (incl. label exclusion
and roundtrip), rows parsing (both on-disk shapes, marker rows),
conservation (count/order/bytes/participants/scope), ET read-back
conservation on real bytes, manifest (transformations vs losses;
`UnsupportedSemantic` cannot yield zero-loss), sufficiency (rows + ET
byte-identity from artifact alone), run-level canonicalization
(determinism, no-traces error, fingerprint consumption).

`tests/test_serving_experiment.py`: Golden-A extended with provenance +
end-to-end sufficiency assertions on the live run.

## Full-suite result

**1135 passed, 1 skipped** (Phase 8: 1087 → +48). `make -C tracks/t3-topology lint` PASS
(py_compile, bash -n, collect-only, selfchecks).

## Known residuals (honest list)

1. **Slice A (standalone traffic_model) is not canonicalized through
   WorkloadArtifact yet** — its PR-C fail-closed lowering + manifest is
   retained. The §24 gate item "real BookSim workload traces to canonical
   hash" is satisfied by the serving→BookSim path (Golden-A); unifying
   Slice A is deferred with its owner slice.
2. Runs persist `workload/*.workload.json` + `index.json` (the §23
   "or equivalent" shape); a per-run `lowering.*.json` manifest is built
   by lowering callers but not yet persisted into the run dir by the slice.
3. Confidence intervals remain deferred (Phase 8 note): n=1 is stated as
   n=1; fingerprinted seed policy does not manufacture confidence.
4. `CXL`/`STORAGE` location types are validated and carried but no current
   generator emits them (grammar completeness, tested synthetically).

## Phase gate (§24)

```text
[x] one versioned canonical workload semantic artifact exists
[x] deterministic workload content hash exists
[x] real BookSim workload traces to canonical workload hash (Golden-A, embedded BookSim)
[x] real analytical workload traces to canonical workload hash (Golden-C/D)
[x] unknown operations fail closed
[x] invalid participants fail closed
[x] units are explicit (logical bytes everywhere; no conversion)
[x] BROADCAST semantics are resolved rather than provisional (Case B, explicit source)
[x] dimensional collective scope is represented explicitly (tuple or sentinel)
[x] required multi-D scope cannot silently fall back to all dimensions (absence unrepresentable; tripwire armed)
[x] PP unsupported lowering remains fail-closed (pp_stage_boundaries refusal stands)
[x] LoweringManifest distinguishes transformations from losses
[x] operation/participant/volume conservation is mechanically checked (incl. real-ET read-back)
[x] zero semantic loss is required for official execution (canonicalization failure fails the run)
[x] comparison fingerprint consumes canonical workload identity when available
[x] representative pre/post migration goldens retain expected behavior (byte-parity sufficiency)
[x] full suite passes (1135 passed, 1 skipped; lint PASS)
```

**Gate: PASS.** STOP before Phase 10 (RouteArtifact) — this phase is
awaiting review.
