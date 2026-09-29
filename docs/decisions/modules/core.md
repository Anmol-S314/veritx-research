# `core` — extracted module rationale

Extracted from the module docstrings of `veritx_dse/{name}` by the 2026-09-29 debloat. Code keeps a one-line pointer; this is the original long-form text.

## `tracks/t3-topology/dse/veritx_dse/core/anynet.py`

```text
core/anynet.py — the ONE anynet links parser.

BookSim's `AnyNet::readFile` (third_party/booksim2/src/networks/anynet.cpp)
defines exactly one grammar, and this module implements it once. Everything
that reads .anynet/.links files delegates here — deadlock_routing, flow_certifier, presets — because three independent parsers had already
diverged: deadlock_routing dropped reverse edges (one-direction link files
parsed as DIRECTED graphs, silently corrupting CDG analysis), and
presets._parse_anynet_adj required >=5 tokens per line and peer-scanning
from index 4 (two-line link files yielded EMPTY adjacency → "disconnected").

The grammar (verified against anynet.cpp readFile, not guessed):

    line := head_type head_id (body_type body_id [weight])*
    head_type, body_type ∈ {router, node}     weight defaults to 1
    router↔router : a network edge — BookSym inserts the reverse channel
                    itself, so files may declare one direction or both
    node↔router   : node attachment; a node attaches to exactly ONE router
    node↔node     : invalid (BookSim asserts)

"Router and node numbers must be sequential starting with 0" (anynet.cpp
header) — we keep that as a documented precondition, same as upstream.
```

## `tracks/t3-topology/dse/veritx_dse/core/artifact.py`

```text
veritx_dse.core.artifact — the ONE artifact primitive.

Everything content-addressed in this repository uses exactly one
implementation of four rules:

    canonical serialization   sorted keys, tight separators, UTF-8, ASCII
    content identity          domain-separated SHA-256
    immutability              a frozen value tree with no caller aliasing
    strict parsing            closed shapes for PERSISTED artifacts

These rules were previously implemented three times
(``waved/identity.py``, ``waved/immutable.py``, ``waved/strict.py``) plus a
second content-id convention inside ``performance/result.py`` (moved
from ``wavee/`` in M5). The duplicates were behaviourally identical for
plain JSON and subtly different for frozen
containers — worse than merely redundant, because a hash that depends on the
representation used to carry a value can be changed by changing the carrier.

Both hash conventions survive verbatim, because artifact identities are
sealed and may not move:

    content_id(domain, payload)          -> bare hex digest
    content_hash(tag, version, payload)  -> "sha256:" + id over "tag/vN\\0"

``tests/test_artifact_primitives.py`` pins canonical bytes and real artifact
identities to values captured before this merge.

Relationship to the two other immutability helpers (both deliberately NOT
merged here): ``core.route_artifact.py::_freeze`` encodes objects as sorted
tuple-of-pairs and ``backend.contracts._freeze_json`` uses a path-aware
frozen map whose error messages carry a field path. Both are sealed Wave-B
code, both feed content hashes, and both enforce different validation
policies. Merging them would move sealed hashes for a naming preference;
that is a Wave-B decision, not an artifact-primitive one.
```

## `tracks/t3-topology/dse/veritx_dse/core/build_manifest.py`

```text
veritx_dse.core.build_manifest — build-time binary provenance.

Ambient ``git rev-parse HEAD`` at execution time is NOT build provenance:
a binary built at commit A, left untouched while the tree is checked out
at commit B, is attributed to B. A manifest written AT BUILD TIME binds
the source revision and dirty state observed while building to the exact
binary bytes that were produced. Execution then verifies the binary
against the manifest, so the A→B counterexample is detected: the manifest
still says A, or (with no manifest) the producer is not pinned and reusable
evidence is refused.

The manifest is canonical JSON beside the binary:

    <binary>.build-manifest.json
```

## `tracks/t3-topology/dse/veritx_dse/core/comparison.py`

```text
veritx_dse.core.comparison — scientific comparison gate (Phase 8).

Core principle: a comparison is valid only when every scientifically
relevant difference is either (1) controlled and equal, or (2) an
explicitly declared experimental variable. Undeclared material
differences fail closed. This module is the gate; it is deliberately
NOT a generic data-analysis framework (Phase 8 §16).

Three seams, each pure and unit-tested at:

  * fingerprint resolution — from immutable run manifests
    (``fingerprint_from_run``) or from legacy compare rows
    (``fingerprint_from_legacy_row``, which marks what it could NOT
    resolve instead of guessing);
  * ``evaluate_comparability`` — controlled-vs-variable verdict over a
    candidate set, including the fidelity policy (§5), metric
    capability (§7), and the semantic-loss ban (§9);
  * ``pareto_with_scope`` — dominance computed only over the comparable
    set, with every excluded candidate visible and the evaluated scope
    stated in the output (§8/§11).
```

## `tracks/t3-topology/dse/veritx_dse/core/config.py`

```text
veritx_dse.config — Configuration management.

Single source of truth for all paths and settings.
Overridable via environment variables.
```

## `tracks/t3-topology/dse/veritx_dse/core/constants.py`

```text
veritx_dse.constants — Centralized magic numbers.

Single source of truth for all hardcoded values.
Every 'magic number' in the codebase should reference these.
Environment-overridable bounds use env_int() (fail fast on garbage).
```

## `tracks/t3-topology/dse/veritx_dse/core/errors.py`

```text
veritx_dse.errors — Structured error hierarchy.

All errors should inherit from VeritXError so callers can catch
specific error types instead of bare Exception.
```

## `tracks/t3-topology/dse/veritx_dse/core/logging.py`

```text
veritx_dse.logging — Structured logging with verbosity, JSON, and file output.

Every function receives a Ctx object. No global mutable state.
Also provides get_logger() for library-level logging via Python stdlib.
```

## `tracks/t3-topology/dse/veritx_dse/core/memory.py`

```text
memory.py — canonical memory semantics, v1 (MEMORY-ROADMAP Phase 14a).

A content-addressed, backend-independent representation of RESOLVED memory
demand and placement: what the workload needs living where, as semantic
accesses over logical byte addresses. Follows the Phase-9/10 artifact
pattern (workload/canonical.py, core/route_artifact.py): frozen dataclasses,
eager validation at builders (the only sanctioned constructors),
_hash-of-canonical-JSON identity, tamper-evident from_dict.

What this artifact is NOT (deliberate v1 boundaries):

* Not a workload duplicate: COMPUTE operand sizes/locations live in
  CanonicalWorkload (input/weight/output_bytes + _loc). This artifact
  references that workload by hash and resolves placement here.
* Not a backend input: NO Ramulator address vectors (channel/bank/row/col),
  NO issue cycles. The Phase-15 lowerer maps logical byte addresses to
  backend coordinates; inventing them here would smuggle backend grammar
  into canonical semantics (spike: ReadWriteTrace consumes addr_vec and
  issues one request/tick, so ready-cycle timing would be fabricated).
* Not a cache model: SCRATCHPAD tier marks explicitly on-chip-resident
  data; no hit-rate/reuse claims. Ramulator starts after an access has
  become a DRAM/HBM transaction.

Identity (what the hashes cover):

  region_table_hash  hash over regions ONLY (sorted by region_id) — the
                     placement truth a lowerer verifies without trusting
                     the rest of the artifact
  access_stream_hash hash over accesses in ARTIFACT ORDER (order is
                     execution semantics, like workload op order) — the
                     hash a Ramulator lowerer quotes as "I lowered stream
                     sha256:..."
  artifact_hash      hash over the full identity dict (schema, workload
                     hash, node count, mapping policy, both table hashes,
                     assumptions)

Excluded from identity: display name, JSON formatting, file paths.
```

## `tracks/t3-topology/dse/veritx_dse/core/paths.py`

```text
veritx_dse.core.paths — Single source of truth for all path resolution.

Instead of fragile parent.parent.parent chains, this module discovers
the repo root from the package location and exports all key paths.

Usage:
    from veritx_dse.core.paths import REPO, BOOKSIM_BIN, DSE_DIR
```

## `tracks/t3-topology/dse/veritx_dse/core/process.py`

```text
veritx_dse.core.process — one-shot process supervision (redesign PR 4).

The lifecycle mechanics handoff §21 requires for one-shot simulators,
behind one deep function:

    supervised_run(cmd, *, cwd, timeout, ...) -> SupervisedResult

  * argv-array launch, never a shell (§3.7)
  * process-group + session ownership: the child gets its own session, so
    escalation signals the whole tree — never our ancestors
  * stdout/stderr captured with BOUNDED memory (§27 "stderr floods": a
    flooding child cannot OOM the control plane)
  * timeout: SIGTERM to the group first, SIGKILL after a short grace
    window — a SIGTERM-ignoring child cannot hang the pipeline forever
  * exit-code capture, including negative signal codes
  * parent cancellation: Ctrl-C (KeyboardInterrupt) kills the group and
    propagates — UI cancellation becomes process cancellation (§21)

Why the child sits in a NEW session: a bare KeyboardInterrupt in this
process would otherwise be delivered to the whole foreground group —
i.e. shared with the child. Owning the child exclusively means the child
dies because WE decided, via the same escalation path as a timeout, not
because it happened to share our terminal's signal fan-out.

NOT for LLMServingSim: a long-lived load/run/pass/exit session is a
different execution model (§4.2) and gets its own protocol module in
Slice B. Do not force interactive sessions through this primitive.

This is the default runner behind simulation.booksim.run_booksim's
documented `runner` seam; callers that inject a runner are unaffected,
and SupervisedResult IS-A CompletedProcess, so the seam contract is
byte-identical for both.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py`

```text
route_artifact.py — one content-addressed router-level routing truth.

Routing must not be re-derived independently by each consumer. This module
materializes the routing replica into a versioned, content-addressed artifact
that downstream consumers reference by hash.

Schema v2 makes the ROUTING CLASS an explicit axis and realizes every route
as an exact hardware resource:

    routing_classes  canonical RoutingClassDefinition list
                     (id, algorithm, algorithm_version, parameters)
    entries          (routing_class_id, src_router, dst_router) -> channel_id

The exact table is execution authority. The class definition says what was
intended/derived; it never grants PASS by itself.

Identity vs transport:

  topology_hash     content identity of the parent TopologyArtifact
  route_table_hash  hash over routing_classes + entries ONLY — verifiable
                    without trusting provenance
  artifact_hash     hash over the full semantic envelope
  provenance        explanation text, transported but NOT hashed

Fail-closed at construction and parent validation: unknown algorithms,
weighted topologies (the replica is hop-count based), disconnected
graphs, non-integer resources, missing/extra coverage, a first channel
that does not leave src, non-adjacent channels, and whole-route
termination for every (class, src, dst) — a table can pick a legal first
channel for every pair and still loop forever.

Schema v1 ((src, dst) -> next_router, no class axis, no resource ids) is
REFUSED on the authoritative path. Migration is explicit:
``upgrade_v1_to_v2()`` succeeds only when every v1 next-router hop maps to
exactly one directed channel; parallel links are ambiguous and fail closed
(v1 does not contain enough information to recover the resource).

DOR_XY is a non-wrap 2D-grid class: dimension order x then y,
wraparound=false. Torus/ring geometries are UNSUPPORTED for DOR_XY —
wraparound minimal routing is a different semantics with a different
deadlock theorem and gets its own class later.
```

## `tracks/t3-topology/dse/veritx_dse/core/run_bundle.py`

```text
veritx_dse.core.run_bundle — durable, verifiable run bundles (C3).

A run bundle is a directory of scientific artifacts plus a
``checksums.json`` that content-addresses every one of them. It supports:

  * ``finalize_run_bundle`` — atomically publish a complete checksum
    manifest over the run directory (fsync file + directory);
  * ``verify_run_bundle`` — recompute and compare WITHOUT re-running any
    simulator, refusing a missing, tampered or extra file;
  * ``bundle_id`` — a path-independent content identity (relative paths
    only, never absolute scratch locations).

This is deliberately functions over a directory, not a manager hierarchy.
```

## `tracks/t3-topology/dse/veritx_dse/core/runs.py`

```text
veritx_dse.core.runs — immutable run skeleton (redesign PR 2).

Implements ADR 0001 (runs immutable once started), 0002 (run_id vs
experiment_hash), 0003 (filesystem authoritative, atomic writes), and 0006
(automatic provenance) for the standalone BookSim slice (PR 3) and beyond.

Deliberately NOT a Runner/Manager class hierarchy (redesign §0): a handful
of functions over a run directory.
```

## `tracks/t3-topology/dse/veritx_dse/core/spec.py`

```text
veritx_dse.core.spec — experiment spec boundary (redesign PR 2).

The strict boundary between scientific intent and everything else
(ADR 0005). An experiment spec:

  * names simulators/topologies by REGISTERED ID, never by path,
  * rejects unknown fields at the boundary (no silent normalization),
  * materializes into a fully-resolved, deterministic dict whose canonical
    JSON hash is the experiment identity (ADR 0002).

Pydantic is used here only at the parsing boundary; the rest of the system
consumes plain dicts/dataclasses from resolve().
```

## `tracks/t3-topology/dse/veritx_dse/core/time.py`

```text
veritx_dse.core.time — canonical exact rational time (§12/§13/§86/§87).

Wave E never mixes GPU cycles, BookSim cycles, and seconds as if they
were interchangeable. The canonical scheduler time is an exact rational
number of **seconds** (``QTime``), serialized as numerator/denominator so
persisted artifacts stay exact. ``1 / 1.4 GHz`` is not an integer number
of picoseconds — no silent rounding enters causal scheduling.

Floats are a *reporting* concern only: ``QTime.to_float()`` exists for
human-facing summaries and is never used in identity or comparisons.
```


# `core` — extracted inline comments

## `tracks/t3-topology/dse/veritx_dse/core/anynet.py`

line 31:

```text
    # Directed router->router weights as DECLARED in the file (only explicit
    # mentions; BookSim defaults an unmentioned reverse channel to 1).
    # B3.7b route-proof consumers compare these with TopologyArtifact
    # channel latencies; absent entries mean BookSim's default of 1.
```

line 105:

```text
        # optional weight token (LINK_WEIGHT state): any bare integer sets
        # the channel latency BookSim uses as edge distance. Recorded, not
        # folded into adjacency — PR D consumers enforce the policy.
```

## `tracks/t3-topology/dse/veritx_dse/core/artifact.py`

line 18:

```text
# ── errors ───────────────────────────────────────────────────────────────
# The error TAXONOMY lives in core.errors (one module, one hierarchy).
# This module re-exports the artifact-contract errors so callers that
# think in artifacts can import them from here; the class objects are the
# same, so every raise/except site is unchanged.
```

## `tracks/t3-topology/dse/veritx_dse/core/comparison.py`

line 35:

```text
# ── Metric semantics (§6) ────────────────────────────────────────────────────
# A JSON key is not a metric. These tables are the closed vocabulary a
# number must belong to before two results may be compared on it.
```

line 64:

```text
# §7: metrics an engine does not semantically produce. The congestion-
# unaware analytical frontend emits exposed communication as a constant
# 0 (no congestion model) — that zero is an engine property, never a
# measurement, so the metric is not comparable for such candidates.
```

line 160:

```text
# Required dimensions per evidence class. A memory comparison must not
# demand network VCs; a fabric comparison must not ignore packetization.
# Unknown fidelities skip this gate (kind policy still applies) — an
# unwired evidence class is not a license to invent its requirements.
```

line 200:

```text
    # Workload identity: canonical first, fixture identity as fallback.
    # Phase 9: a run whose serving slice canonicalized its saved traces
    # carries <run>/workload/index.json with content-addressed
    # WorkloadArtifact hashes — those ARE the workload identity, and the
    # fingerprint is certified. Without them, fall back to hashing the
    # resolved workload/serving inputs (fixture identity subsumes
    # cluster parallelism) and mark the identity uncertified: two runs
    # of the same fixture provably share semantics only through the
    # canonical artifact, never through config equality alone.
```

line 219:

```text
        # Shared identity rule (slice provenance uses the same); raises
        # WorkloadError on an empty artifact set — fail-closed, never a
        # guessed identity.
```

line 242:

```text
    # Fabric identity comes from the run's EXECUTED-fabric record
    # (FabricArtifact parsed from the BookSim config that actually ran),
    # not from spec claims: spec.network never reaches the serving
    # child's generated config. Unrecorded ⇒ None, uncertified.
```

line 390:

```text
    # Provenance gate (§14): a candidate whose fidelity is unknown or
    # unrecorded has no provenance contract — the set is ineligible
    # regardless of kind. Calibration exempts known-class differences,
    # never an unknown class. Two identical unknown strings are not
    # evidence of comparability.
```

line 411:

```text
    # Required controlled dimensions unrecorded for every candidate make
    # a DESIGN_COMPARISON ineligible — never comparable. Required set
    # follows the candidates' evidence class, minus declared axes.
```

line 459:

```text
    # ── generic controlled-vs-variable loop (§4) ──────────────────────
    # Kind-exempted fields: a calibration study is *about* differing
    # simulators/fidelities/modes. A declared variable that happens to be
    # constant across candidates is a degenerate axis, not an error —
    # the rule is one-directional: differing ⇒ must be declared.
```

line 496:

```text
                    # §7: the engine does not semantically produce the
                    # metric (e.g. unaware exposed=0) — never a measured
                    # zero, never silently dropped.
```

## `tracks/t3-topology/dse/veritx_dse/core/constants.py`

line 25:

```text
# ── BookSim defaults ─────────────────────────────────────────────────────────
# Canonical home for num_vcs / vc_buf_size / routing_delay / packet_size.
# NOTE: these diverge from simulation/booksim.py BASE_PARAMS
# (num_vcs 2 vs 4, vc_buf_size 4 vs 8, routing_delay 1 vs 0). BASE_PARAMS
# alignment is an explicit follow-up — do NOT change either side here.
```

line 40:

```text
# ── Area/power estimates ─────────────────────────────────────────────────────
# Canonical home for report area/power/timing knobs.
# reports/reports.py imports from here instead of defining its own.
```

line 45:

```text
# Per-link area (mm2) for a 256-bit link at 7nm — repeaters + shielding.
# Intentionally diverges from LINK_AREA_MM2_PER_MM: different abstraction
# (per-link vs per-mm). Reports use this; do NOT substitute the per-mm value.
```

line 88:

```text
# Max VCs per plane. Env-overridable: fabrics with shared-pool or
# high-radix VC budgets (e.g. PCIe6 VC0-VC7 + shared pool) need > 8.
# Import-time read (documented): changing it requires process restart.
```

## `tracks/t3-topology/dse/veritx_dse/core/memory.py`

line 24:

```text
# v1 placement tiers. HBM = off-chip traffic evaluated by the memory
# backend. SCRATCHPAD = explicitly on-chip-resident (never HBM traffic).
# DDR/CXL/STORAGE/REMOTE placements do not exist in v1: canonical locations
# implying them are UNSUPPORTED at the resolver (Phase 14b), never silently
# remapped to HBM.
```

line 459:

```text
        # Overlap is refused within one placement scope (v1 supports no
        # shared/aliased mode — overlapping claims on one memory would let
        # two tensors silently share bytes). Separate scopes (different
        # tier/device/stack = different physical memories) may reuse the
        # same numeric addresses.
```

## `tracks/t3-topology/dse/veritx_dse/core/paths.py`

line 8:

```text
# ── Discover repo root from package location ─────────────────────────────
# veritx_dse/ lives at: <repo>/tracks/t3-topology/dse/veritx_dse/
# So 5 levels up from this file = repo root
```

line 26:

```text
# SYNTH_DIR: the one home for synthesis winners + results (BO/iterative
# topo.anynet, bo_results_N*.json) — the dir the t3 pickers scan first.
# REPO runs/booksim remains as a legacy second home (pickers scan both).
```

## `tracks/t3-topology/dse/veritx_dse/core/process.py`

line 16:

```text
# SIGTERM -> SIGKILL escalation window (seconds). Long enough for a
# well-behaved simulator to flush its stats; short enough that a stuck
# run fails in seconds, not minutes.
```

line 21:

```text
# Bounded capture (§27): lines are individually capped, then the stream
# keeps its HEAD and TAIL only. Worst case per stream is bounded by
# (_HEAD_LINES + _TAIL_LINES + 1) short lines regardless of child output
# volume — a flooding child cannot balloon memory. Diagnostics need the
# banner (head) and the error (tail); the middle of a giant log is what
# artifacts/ files are for.
```

line 184:

```text
        # Parent cancellation (§21): kill the group and propagate. No
        # grace period — the user asked to stop now, and a TERM-ignoring
        # child must not trap us inside its own shutdown.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py`

line 21:

```text
# AnyNet::route() tie-breaks, exactly as replicated in
# booksim_first_hop_table (anynet.cpp: ascending std::set rlist, first
# strict minimum; strict `<` relaxation so the first predecessor sticks;
# neighbors iterated ascending via std::map).
```

line 37:

```text
# Materialization from a topology chooses the lowest channel id when a hop
# has parallel links; the choice is declared in the class parameters so it
# is part of routing identity, never silent.
```

line 65:

```text
# Naming (Wave B3.2): a standalone AnyNet graph has no TopologyArtifact,
# so this digest is a ROUTING-GRAPH hash, not a fabric topology identity.
# New fabric-bound code goes through RouteArtifact.from_topology(), which
# stores TopologyArtifact.topology_hash() in the same field.
```

line 147:

```text
# Backward-compatible private alias: earlier revisions, comments and
# diagnostics referred to this function by its private name. Same object,
# so there is exactly ONE implementation.
```

line 301:

```text
#: Wraparound dimension-order XY for square torus fabrics. X-then-Y with
#: minimal shortest-wrap per dimension; even-k midpoint ties resolve +x/+y
#: deterministically (``backend_tie`` records that the fork resolves them
#: randomly, so tied flows are carved out of COMPARABLE equivalence).
#: Deadlock-freedom is NOT by construction (wraparound rings cycle): the
#: class carries a dateline VC-partition theorem (``vc_partition`` +
#: ``dateline``) that the channel-VC CDG certificate must discharge per
#: shape. Never copy DOR_XY's no-CDG rationale here.
```

line 324:

```text
#: Minimal lowest-dimension-first routing for FlatFly fabrics. At each hop
#: the lowest dimension whose coordinates differ moves toward the
#: destination coordinate — the canonical replica of the fork's
#: ``min_flatfly`` (``flatfly_outport``). Deadlock-freedom is a
#: DETERMINISTIC_CDG obligation discharged per (k, n) shape, not a
#: by-construction claim. UGAL/xyyx/adaptive variants are separate
#: classes requiring VC splits and are out of scope.
```

line 858:

```text
            # Functional-graph reachability per destination: every src must
            # reach dst without revisiting a router. Legal first hops are
            # not enough — a table can loop forever (R0->R2 via R1 and
            # R1->R2 via R0).
```

## `tracks/t3-topology/dse/veritx_dse/core/run_bundle.py`

line 20:

```text
#: Atomic-write temp prefix used when publishing checksums.json. Stale
#: files with this prefix are our own crashed publishes: cleaned at
#: finalize start and never iterated as bundle content.
```

line 112:

```text
    # Concurrent finalizers of the SAME directory race legitimately: a
    # sibling's stale-temp sweep may unlink our temp between mkstemp and
    # replace (both write byte-identical content, so a retry is exact).
    # Retry once on FileNotFoundError only; every other failure raises.
```

line 203:

```text
        # Sealing is enforced by the file-set checks above: a manifest
        # present on disk but absent from the recorded files refuses as
        # an undeclared file before reaching this block.
```

line 212:

```text
        # A manifest that declares its own bundle identity must agree
        # with the recomputed one: a manifest swapped in from another
        # valid bundle (then re-sealed) still cannot claim this bundle's
        # id, and a stale manifest cannot ride along silently.
```

## `tracks/t3-topology/dse/veritx_dse/core/runs.py`

line 86:

```text
# Environment/lock identity (verified-PRD Integrity PR A / §11.3): a run's
# provenance must identify the installed dependency set, not assume the
# developer's machine. The lockfile is generated from the declared metadata
# (see dse/requirements.lock header) and fingerprinted here.
```

line 280:

```text
        # Frozen files — written once, never updated (ADR 0001), each
        # published atomically so a crash mid-create cannot leave a
        # partially valid run directory.
```

line 360:

```text
    # -- shared slice mechanics (Phase 7) -----------------------------------
    # Both real execution slices (standalone BookSim, serving) repeated
    # these verbatim; they are run-lifecycle mechanics, so they live on
    # Run. Behavior contracts stay pinned by test_run_core and the
    # slices' own verdict tests.
```

## `tracks/t3-topology/dse/veritx_dse/core/spec.py`

line 15:

```text
# One line per persisted format (ADR: versioned formats). Bump on any
# resolution-rule change — it deliberately changes every experiment_hash.
# v2: routing default None→preset-native (no silent override); network
# block required for latency, forbidden for serving (cluster owns fabric).
# Formats are versioned independently: an experiment-schema bump never
# moves the plan format.
```

line 33:

```text
# ── Boundary models ─────────────────────────────────────────────────────────
# extra="forbid" IS the boundary: unknown fields raise, they are never
# normalized away (redesign §32). strict=True forbids silent coercion
# ("64" -> 64) — scientific parameters must arrive as the declared type.
```

line 56:

```text
    # None = undeclared: the named preset's own routing executes. An
    # explicit value must equal the preset's routing — presets are
    # immutable, never silently overridden.
```

line 105:

```text
    # Latency mode: required (standalone fabric intent). Serving mode:
    # MUST be absent — fabric is cluster-derived, and an ignored block
    # must never ride the intent hash.
```

line 258:

```text
# ── Plan (validate -> plan -> execute seam; redesign §24) ───────────────────
# A plan is the executable expansion of one resolved experiment: one task per
# (topology?, seed) combination. Slice A has a single task per seed.
```

## `tracks/t3-topology/dse/veritx_dse/core/time.py`

line 69:

```text
            # Time is an instant or a duration: neither is negative.
            # A subtraction that would go backwards refuses here instead
            # of producing a meaningless negative instant.
```


# `core` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/core/anynet.py` :: `AnynetGraph`

```text

    ``non_unit_weights`` records which lines carried a trailing weight token.
    PR D (verified-PRD §6.4): the certification replica computes hop-count
    distances, while BookSim's AnyNet Dijkstra uses the stored weight as the
    edge distance — on weighted topologies the certified route set is NOT
    the executed route set. Certification paths must therefore reject
    non-unit weights (fail-closed) until weights flow through the replica.
```

## `tracks/t3-topology/dse/veritx_dse/core/artifact.py` :: `FrozenMap`

```text

    Items are sorted by key at construction so iteration, equality and
    hashing are order-independent; nested containers are frozen too.
    Any mutation attempt raises (no ``__setitem__`` exists at all).
```

## `tracks/t3-topology/dse/veritx_dse/core/comparison.py` :: `evaluate_comparability`

```text

    Two tiers (brief §8/§13):

      * SET-level incoherence → INVALID_COMPARISON, no comparison is
        interpretable: undeclared material differences (§4),
        TRACE_REPLAY mixed with simulation (§5), fidelity mixing under
        DESIGN_COMPARISON (§5).
      * CANDIDATE-level problems → the comparison stays valid over the
        rest; the candidate is excluded with a visible status:
        SEMANTIC_LOSS (§9), NOT_COMPARABLE (engine capability, §7),
        MISSING_METRIC (when a metric lookup is supplied).

    Declared variables that stay constant are a degenerate axis, not an
    error — the rule is one-directional: differing ⇒ must be declared.
```

## `tracks/t3-topology/dse/veritx_dse/core/errors.py` :: `SemanticError`

```text

    The input is understood and outside the supported domain, or two
    semantic facts contradict. Trust boundaries (certificate obligations,
    compiler orchestration) catch this base — never Python's built-in
    ``ValueError`` — so a programmer fault (including a bare ``ValueError``
    from an invariant that exploded) propagates and aborts certification
    instead of being laundered into a design verdict.

    Artifact/model error classes that are already ``ValueError`` subclasses
    also inherit this, so existing ``except ValueError`` call sites keep
    working while boundaries get a precise handle.
```

## `tracks/t3-topology/dse/veritx_dse/core/errors.py` :: `TimeoutError`

```text

    Subclasses BookSimError so existing ``except BookSimError`` handlers
    keep catching timeouts, while carrying returncode/stdout/stderr like
    its parent for debuggability.
```

## `tracks/t3-topology/dse/veritx_dse/core/memory.py` :: `AddressMappingPolicy`

```text

    v1 supports contiguous_aligned_v1: regions sorted by stable semantic
    identity (region_id), cursor aligned up per region, bases assigned.
    parameters must be JSON-safe (checked at build).
```

## `tracks/t3-topology/dse/veritx_dse/core/memory.py` :: `MemoryAccess`

```text

    Address = region.base_address + offset_bytes (logical byte address;
    the Phase-15 lowerer maps it to backend coordinates). dependencies =
    access_ids that must complete first (ordering, not cycles — v1 has no
    ready_cycle: the sources do not supply grounded issue timing).
```

## `tracks/t3-topology/dse/veritx_dse/core/memory.py` :: `MemoryPlacement`

```text

    tier:   HBM | SCRATCHPAD (nothing else exists in v1)
    device: owning device index (>= 0)
    stack:  HBM stack index, or None when the design does not place at
            stack granularity (normal: the lowerer owns stack/bank/row).
```

## `tracks/t3-topology/dse/veritx_dse/core/process.py` :: `SupervisedResult`

```text

    `timed_out` distinguishes "the child finished" from "we ended it at
    the budget": a result assembled after SIGKILL must never be mistaken
    for a measurement (the same rule run_booksim applies to partial
    stats after a nonzero exit).
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `RoutingClassDefinition`

```text

    The definition explains intent/derivation; the materialized entries in
    RouteArtifact are execution authority. Theorem scaffolding may later
    prove ``entries conform to definition`` + ``theorem applies``, never
    ``algorithm == 'DOR' therefore trust me''.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `_anynet_replica_first_hops`

```text

    Tie-break semantics, from the C++ source:
      * candidate scan is over std::set<int> rlist (ascending) keeping the
        FIRST strict minimum -> min() over an ascending list;
      * relaxation uses strict `<` -> the first predecessor sticks;
      * neighbor iteration is std::map (ascending id).
    All-pairs (BookSim's table covers every destination regardless of T),
    so the CDG check is a conservative superset of any traffic pattern.
    Returns {(s,t): next_hop_after_s}.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `equivalence_report`

```text

    Every difference stays visible with pinned per-flow diagnostics;
    missing/extra flows are first-class findings, never silently
    dropped (the Phase-8 failure-visibility rule, applied to routing).

    OWNERSHIP: this is the route-set comparison authority for an
    ARTIFACT. The set comparison itself is
    :func:`compare_first_hop_tables`. Adapters that obtain an executed
    table from a specific simulator (e.g. ``backend.route_observation``
    parsing the BookSim fork's routing dump) own PARSING and ID MAPPING
    only, and must delegate the verdict rather than re-implementing it.
```

## `tracks/t3-topology/dse/veritx_dse/core/runs.py` :: `Run`

```text

    Mutable files: state.json, stdout.log, stderr.log. Everything else
    (spec.resolved.json, manifest.json, provenance.json) is written once
    during initialization and frozen.
```


# `core` — extracted docstring essays

## `tracks/t3-topology/dse/veritx_dse/core/comparison.py` :: `fingerprint_from_legacy_row`

```text

    The legacy compare pipeline runs one trace against several BookSim
    topologies; rows record topology/nodes/seed/latency but not VC
    config, packetization, or tool versions. Unresolvable dimensions are
    listed in ``unresolved_dimensions`` and the fingerprint is marked
    ``certified: False`` — the comparison can still run, but its output
    can never carry a certified claim (§14).
```

## `tracks/t3-topology/dse/veritx_dse/core/comparison.py` :: `pareto_with_scope`

```text

    The banned shape is ``pareto_front([x for x in c if x.ok])`` followed
    by output that pretends the excluded candidates never existed. Here
    every requested candidate appears in ``candidates`` with a status;
    only COMPARABLE candidates with every objective present enter the
    frontier; and the output states the evaluated scope.
```

## `tracks/t3-topology/dse/veritx_dse/core/memory.py` :: `allocate_regions`

```text

    Caller groups specs by placement scope ((tier, device, stack) share one
    address space — separate physical memories must be allocated in
    separate calls, or identical addresses across scopes would collide).
    Regions sort by stable semantic identity (region_id), the cursor aligns
    up per region, bases assign. Same specs in any input order → identical
    bases. Each spec: region_id, object_type, size_bytes, placement,
    source_op_id, optional alignment_bytes (default: policy alignment).
```

## `tracks/t3-topology/dse/veritx_dse/core/paths.py` :: `new_run_dir`

```text

        <root>/<command>/<YYYYmmdd_HHMMSS>_seed<seed>/

    root defaults to RESULTS_DIR; t3 passes results/<CONFIG> so guided runs
    co-locate with their CONFIG instead of scattering across results/.
    Every command writes its result JSON *inside* its run dir (never
    overwriting a previous run), the seed sits in the name for
    reproducibility, and results/ is the single results home — one layout
    for every command. A _2 suffix breaks same-second collisions.
```

## `tracks/t3-topology/dse/veritx_dse/core/process.py` :: `supervised_run`

```text

    env is passed through untouched — environment selection is the
    CALLER's provenance policy (e.g. _timeloop_env), not this module's.

    on_timeout="complete" assembles a SupervisedResult anyway (returncode
    reflects the killing signal, e.g. -9 after SIGKILL; timed_out=True)
    for callers that want to inspect the debris; the default "raise"
    raises subprocess.TimeoutExpired with the captured output attached,
    which is what run_booksim's existing seam contract expects.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `_dor_torus_xy_channel_entries`

```text

    X-then-Y dimension order with minimal shortest-wrap per dimension.
    Even-k midpoint ties resolve deterministically toward +x/+y (see
    ``dor_torus_xy_tie_flows`` for the carved-out set: the fork resolves
    them randomly, so they are out of COMPARABLE equivalence scope).
    Accepts mesh-adjacent AND wraparound-adjacent channels; parallel hops
    are UNSUPPORTED, never approximated.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `_flatfly_min_channel_entries`

```text

    At each hop the lowest dimension whose coordinates differ moves to
    the destination's coordinate in that dimension — the canonical
    replica of the fork's ``min_flatfly``. Requires the canonical
    ``coord_i = (id // k**i) % k`` numbering and exactly one directed
    channel per dimension-step.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `from_adjacency`

```text

        ``entries`` is the algorithm's next-ROUTER table; the exact
        channel realization is derived from it.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `route_entries_from_adj`

```text

    Returns a next-ROUTER table (the algorithm's output). Callers that
    need hardware resources go through RouteArtifact, which maps each hop
    to an exact channel id. Disconnected graphs are refused here too —
    the public helper must fail closed exactly like the constructor, or
    it would hand out a partial table that looks like a route artifact.
```

## `tracks/t3-topology/dse/veritx_dse/core/route_artifact.py` :: `upgrade_v1_to_v2`

```text

    Succeeds only when every v1 next-router hop maps to EXACTLY ONE
    directed channel in ``topology``. Parallel links are refused by name
    (no min()/first invention): v1 does not contain enough information to
    recover which hardware resource was meant. The upgraded class is
    ANYNET_MIN_HOPS — never DOR_XY, because v1 tables were generated by
    shortest-hop AnyNet semantics.
```

## `tracks/t3-topology/dse/veritx_dse/core/runs.py` :: `_uuid7`

```text

    uuid.uuid7() exists only on Python >= 3.14, but this package declares
    >=3.10, so the sortable-time identity (ADR 0002) is implemented here
    rather than imported. Layout:
    unix_ts_ms[48] | ver 0111 | rand_a[12] | var 10 | rand_b[62].
    74 fresh random bits per millisecond make collision odds negligible
    at run-creation scale; monotonic sorting falls out of the timestamp.
```

## `tracks/t3-topology/dse/veritx_dse/core/time.py` :: `TimeError`

```text

    Self-contained like ``waved.errors``: no dependency on legacy error
    plumbing, machine-readable ``code``, never silent.
```
