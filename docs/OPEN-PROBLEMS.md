# VeritX open problems

_Last updated: 2026-10-05. Branch `integration/studio-reconciliation`._

> Snapshot policy: do **not** hand-maintain a HEAD in this file. This line has
> already gone `825b45c6` → `246fa118` → `9477c710` while agents worked the same
> branch. Record only a dated snapshot or a tag; if a commit id is needed,
> generate it.

This is the durable list of known gaps, so they survive session and agent
turnover. When you close an item, move it to **Resolved** with the commit that
closed it — do not delete it. When you discover a gap, add it here in the same
breath as fixing the easy part.

**Markers.** `[V]` = reproduced first-hand (ran the gate / read the exact line).
`[A]` = reported by the 2026-09-30 read-only audit and not yet run end-to-end;
treat as a strong hypothesis, not a measurement. Failure modes are tagged
**FAIL-CLOSED** (refuses) or **SILENT** (emits a plausible wrong value — the
dangerous class).

---

## Where the heterogeneous-link work stands

Three original issues. Two are end-to-end; the third is simulator-only.

| Issue | Status | Commits |
|---|---|---|
| 1. Different-speed links (was silently flattened) | **Solved** for latency; bandwidth modeled as lanes | `d29c1709`, `786aa96a`, `1a5b05aa` |
| 2. Unidirectional links | **Solved** (AnyNet one-way + strong-connectivity gate) | `a6e78010` |
| 3. Shared bus / multidrop | **Simulator solved; compiler gated** (see B) | `1a5b05aa` |

What "solved" means, precisely:

- **Per-link latency** (`latency_ns`) reaches `DirectedChannel.latency_cycles`
  and is emitted as the AnyNet per-link weight, while routing stays hop-count
  because the link's **cost** token is pinned to 1 (`ANYNET_ROUTE_COST`).
- **Per-link bandwidth** is modeled as **parallel lanes** (width ratio = lane
  count). Aggregate bandwidth scales; a single packet is pinned to one lane
  (`pid % lane_count`) so it never reorders — the physically correct behaviour
  of a non-striped wide wire.
- **One-way links** are expressible, and a graph that is not strongly connected
  (which would make `AnyNet::route` spin) is refused up front.
- **Buses** build a real `MultiDropChannel` with drop-index addressing and
  single-slot contention; proven via the routing dump (dest 1 → drop 0,
  dest 2 → drop 1).

Proven with the real binary: one-way → clean refusal `rc=255`; symmetric,
bus and lane graphs → `rc=0`. `make -j4` green.

---

# Part 1 — Compiler / topology problems (B–I)

### B — Compiler cannot route a shared wire (bus) end-to-end  ·  LARGE

**Symptom.** A topology that declares a bus (`SharedLink`) is refused by
`derive_route` and both BookSim projection seams. The simulator supports buses;
the compiler cannot produce a route for one, so `CompileRequest → execute` with
a bus is not possible.

**Why.** `RouteArtifact.entries[(class, src, dst)] = channel_id` is a single
first-hop **channel**. `_validate_channels` proves totality and termination by
walking `channel.dst_router`. A bus has no `DirectedChannel`, and
`_anynet_channel_entries` builds its adjacency from `topology.channels` only —
so a bus is invisible to routing.

**A bus hop is `(shared wire, drop index)`**, not a channel: only declared taps
are reachable, and the wire is single-slot.

**Option B1 — tagged channels (shortest).**
Lower a bus to one `DirectedChannel` per tap, each carrying `shared_link_id` +
`drop`. Route entries stay `int`; validator/VC plumbing mostly unchanged; the
projector groups by `shared_link_id` into the one `multidrop` line it already
emits. Must hold three invariants or it is a silent semantic loss:
1. projection emits exactly **one** multidrop line, never N p2p links;
2. the channel dependency graph treats the group as **one** resource;
3. taps get per-tap VC sub-ranges (`num_vcs >= taps`).

**Option B2 — union hop (honest, bigger).**
Entry value becomes `channel_id | (shared_link_id, drop)`; RouteArtifact schema
bumps to v3. Structurally impossible to misread, but every `entries` consumer
changes (resolved route, VC assignment, projection, evaluators, certificate
serialization/hashing) plus explicit migration.

**Recommendation: B1 with the three invariants pinned as tests.** Matches the
"shortest honest path" instinct; B2 only if the artifact must *structurally*
prove the shared resource.

**Layers either way.**
1. route entries + adjacency include bus hops (driver → each tap);
2. validation walks bus hops (only declared taps; drop must match tap index);
3. **VC assignment + CDG** — the shared wire is one dependency node; false
   sharing otherwise;
4. projection round-trip accepts buses;
5. deadlock-proof implications of a shared resource.

**Files:** `core/route_artifact.py`, `model/routing.py`,
`model/topology_artifact.py`, `model/vc_assignment.py`,
`verification/channel_vc_cdg.py`, `backend/booksim.py`,
`backend/booksim_projection.py`, `model/routing_materialize.py`.

---

### C — Bandwidth is aggregate lanes, not per-channel width  ·  DECISION

A wide link is modeled as N lanes; a single flow gets one lane/cycle. This is
the correct behaviour of a non-striped wide wire. Per-channel width inside
BookSim would mean rate control in `Channel` — credits, buffering, and the
timing assumptions behind the liveness proof. Every honest alternative is worse
than aggregate lanes.

**Action: document this as the supported semantics**, not code. The only future
extension is flit-level striping, which reorders unless the receiver reassembles
— not worth it now.

---

### E — Verification debt  ·  MEDIUM

- **No end-to-end test that a bus compiles, projects and executes.** The
  simulator is proven by hand-written anynet files; the compiler path is refused,
  so nothing exercises it.
- The route-dump format is a de facto interface. `1a5b05aa` added
  `drop <n> lanes <n>` to the trailer and broke the Python parser for every
  AnyNet-backed family (fixed in `825b45c6`). Add a test that the parser accepts
  the trailer **and** the old spelling, so adding a field cannot silently break
  the network leg again.
- `SharedLink` is created and serialized but, until B lands, read by no
  downstream stage other than the refusal sites — a canary for "accepted and
  ignored".

---

### F — Explicit graphs are scored on generic min-hop routing  ·  MEDIUM

**Symptom.** Any `kind=custom`/`anynet` graph (including every synthesized
candidate) is routed with `ANYNET_MIN_HOPS` (hop count). Two graphs that intend
different routing rules are indistinguishable, and a graph that *is* a 4x4 mesh
scores worse than the same graph declared natively — `9a1e72a3` records 734176
via AnyNet vs 488806 natively, so the optimiser was choosing on a biased
surface.

**Escape hatch.** `recognize_family` exact-matches a graph against the canonical
family generators, so a graph that *is* a family can be re-declared and scored
natively. It is deliberately exact (never a degree/diameter heuristic), because
claiming a family buys that family's routing and certificate.

**Gap.** Exact match only. A genuinely irregular but routable graph stays on
min-hop. That is the correct conservatism, but it means topology comparisons are
exact on **structure** and approximate on **routing**. Do not present them as
routing-exact.

---

### G — `recognize_family` is restored but has no caller  ·  SMALL

**Symptom.** `recognize_family` (`model/topology_artifact.py:944`) is defined
and covered by tests, but referenced by nothing (`grep` shows only the def).
Commit `9a1e72a3` says it exists "so a synthesized candidate can be re-declared
as the family it actually is" — but the synthesis/candidate path never calls it,
so the de-biasing it promises in F is not live.

**Action.** Wire it into synthesis / candidate promotion, or park it with an
explicit caller plan. An unreferenced capability is the same class of gap as an
accepted-and-ignored field.

---

### H — Analytical (ASTRA) leg is per-dimension only  ·  MEDIUM

**Symptom.** `to_analytical_yml` / `_default_dims`
(`model/topology_ir.py:646`) express topology/count/bandwidth/latency as
**per-dimension** arrays. A regular grid maps onto dimensions; an irregular
graph, a one-way fabric, or a bus has no analytical projection, and per-link
latency cannot be expressed there at all. Those topologies have only the
cycle-accurate BookSim leg.

**Action.** Decide whether the analytical leg is a supported deliverable for
arbitrary graphs or explicitly BookSim-only, and say so in capability truth.

---

### I — Certification covers only mesh + concentrated_mesh  ·  DECISION

**Symptom.** `_POLICY_BY_FAMILY` maps every materialized family to a routing
policy, but `_CERTIFIED_FAMILIES` (`model/routing.py:22`) is only `MESH` and
`CONCENTRATED_MESH`. Torus / flatfly / gec / custom execute and are qualified
differently, but the strongest certificate claim stops there. "Not certified"
reads as "not working" unless the capability truth says *why* (no qualification
record).

**Action.** Surface the reason in `capability_truth`, then decide which families
to qualify next.

---

# Part 2 — Full audit, 2026-09-30

Four read-only subagent lanes (gates/CI, compiler→execution semantics,
epistemic integrity, debloat) run against `246fa118` (branch later advanced to
`9477c710`; only `docs/OPEN-PROBLEMS.md` changed). IDs are prefixed to avoid
colliding with B–I. Where an item extends an existing one, it says so.

## GATE — CI, gates, release hermeticity

### GATE-1 · P0 · CI red, and one failure masks five gates  `[V]`
`make -C tracks/t3-topology product-gates` fails at its **first** recipe line
(`tracks/t3-topology/Makefile:32` → `scripts/check_intent_ontology.py`, **22
problems**), and because the recipe has no `-` prefix, the other five gates
(`:33-37`) never report. `check_intent_ontology.py` is red because 13 `cite:
file:line` cites are now out of range (line-number drift from the docstring
debloat) plus 9 UI class-name errors. The exact CI job `t3-topology` failed on
"Product registry gates (T3 only)"; onboarding/t1/t2/t4 passed.
**Fix:** re-anchor the cites; run the six gates as independent steps (`make -k`)
so one red gate cannot hide five.

### GATE-2 · P1 · `cite: file:line` is a bounds proxy, not a semantic check  `[V]`
`scripts/check_intent_ontology.py:76-94` only asserts the file exists and
`1 ≤ line ≤ len(file)`. A citation pointing at **unrelated** code passes.
~60 ontology rows cite `line 1` of a prose doc (the title); and
`comm.isolation` (`intent-ontology.yaml:3477`) cites
`model/compile_model.py:1730`, which is a `collectives` field, not the
QoS-isolation classification it claims. Failure mode: **SILENT**.
**Fix:** cite an anchor (`file:symbol`) and assert the symbol resolves; require
heading/id anchors for prose, never `:1`.

### GATE-3 · P1 · The UI-admission check is defeated by one rename (and mis-fires)  `[V]`
`check_intent_ontology.py:42-43` hardcodes
`apps/studio/src/components/DesignViewV2Editor.tsx` and `:196` only runs the
check `if DESIGN_EDITOR.is_file()` — no `else`, so renaming/moving the editor
makes check #6 vanish silently. Its regex `^  '([A-Za-z_]+\.[a-z_]+)':` cannot
match a class name containing a digit, so `WorkloadV3.*` / `RequirementV3.*`
(11 of the editor's 32 `LOCATIONS` keys) are never checked; it also happens to
match the `FIELD_LABELS` dictionary and produces the spurious current failure
`'DependencyGraph.dependencies' but no ontology row covers it`. Failure modes:
**SILENT** (rename) + false-positive FAIL.
**Fix:** glob the components dir and assert ≥1 editor found; anchor to the
`LOCATIONS` map, and widen the class-name pattern to `[A-Za-z_][A-Za-z0-9_]*`.

### GATE-4 · P1 · `check_capability_truth.py` is an orphan gate — it never runs  `[V]`
Repo-wide search finds this script in **no** Makefile, workflow, or test; only
in itself and prose. `product-gates` lists six checks, none of them this one.
The advertised authority preventing the family registry from claiming
unimplemented stages is therefore not enforced. It is also keyed to 7 hardcoded
family strings while `derive_all_stages()` returns more. Failure mode:
**SILENT** (registry can claim `QUALIFIED: YES` for a family with no
implementation).
**Fix:** add it to `product-gates`; derive the family set from the registry.

### GATE-5 · P1 · The release/quality gates do not run on this branch  `[V]`
`release.yml` triggers only on `prod/**`, tags, PR→`main`, dispatch — **not**
`integration/**`. On this branch CI reduces to a no-op lint plus `product-gates`
plus a sanity test that always passes (see GATE-9). So a green CI here means
very little. Failure mode: **SILENT**.
**Fix:** add `integration/**` to `release.yml` (or move the DSE suite +
hermeticity guards into `ci.yml`).

### GATE-6 · P1 · Five "build environments", one moving tag, digest enforced only on tags  `[V]`
`make release-build` runs in ≥5 non-equivalent environments: `ci.yml` tools
image; `release.yml` (`:latest` default, digest asserted **only** for
`refs/tags/*`, `release.yml:110-113`); `studio-live-e2e.yml` on plain
`ubuntu-latest` with pip-only deps; `.gitlab-ci.yml` on a **different** registry
image; and the host toolchain (which is what `Makefile:69-72` documents and what
`RELEASE_CXX` implies). The install in `studio-live-e2e.yml` has no `protoc`, so
`make release-build` fails at `third_party/astra-sim/build/astra_booksim2/build.sh:27`
→ `[Makefile:74: release-build] Error 127`, before Studio/federation/browser
steps run. Failure mode: **SILENT** (a "reproducible" release that is not).
**Fix:** pin `VERITX_TOOLS_IMAGE` by digest repo-wide; make `studio-live-e2e`
use the same image (or install the toolchain contract); record compiler
version/distro in each manifest.

### GATE-7 · P2 · The toolchain guard is a token-presence scan  `[A]`
`check_release_toolchain.py:34-62` proves only that the strings `cmake`,
`protobuf-compiler`, `g++`, `make`, `python3`, … appear in the runtime stage.
Ramulator's build does `find_package(Python 3.10 REQUIRED COMPONENTS
Interpreter Development.Module)` (`third_party/ramulator2/CMakeLists.txt:55-57`)
with bindings ON by default, while `python3-dev` is installed **only in the
builder stage** (`Dockerfile:43`) and not copied forward. The gate can be green
while the release build fails at Ramulator configure. **Fix:** assert a
configure dry-run, or add `python3-dev` to the runtime stage + the required list.

### GATE-8 · P2 · Third-party fetches escape the pin guard  `[A]`
`check_dockerfile_pins.py:52-62` only scans `FROM` lines and `RUN … git clone`.
Ramulator's CMake `FetchContent_Declare`s yaml-cpp/fmt/nanobind by **tag**
(`third_party/ramulator2/CMakeLists.txt:34-66`), fetched over the network at
configure time. **Fix:** pin fetch tags to 40-hex SHAs (or vendor) and extend the
guard to scan `CMakeLists.txt`/`*.cmake`.

### GATE-9 · P2 · Two CI steps for the flagship track cannot fail  `[V]`
`tracks/t3-topology/Makefile:29` lints with `py_compile … 2>/dev/null || true`;
`tracks/t3-topology/scripts/sanity_test.py:35` writes `"status": "pass"`
unconditionally and never exits non-zero (verified: no `sys.exit`). T2/T4 sanity
tests **do** `sys.exit(1)`. **Fix:** drop `|| true`; mirror t2/t4 failure
behaviour.

### GATE-10 · P2 · `ci.yml` defects on main-only jobs  `[A]`
The `report` job runs `docker pull` **inside a container job** on the tools image
(`ci.yml:56-57,85`) which ships no docker client → job errors when it runs. The
dashboard job publishes via `peaceiris/actions-gh-pages@v4` pinned by tag, not
SHA, holding `contents: write` (`ci.yml:100,121-123`). **Fix:** run `report` on
the plain runner; pin the action by SHA.

### GATE-11 · P2 · Release manifest can record facts that were not used  `[A]`
`write_release_manifest.py:91-99` records `gpp: g++ --version` regardless of
`RELEASE_CXX`; `validate_release_manifest.py` never inspects
`container.pinned_by_digest`. With `RELEASE_CXX=clang++` the manifest says `g++`.
**Fix:** record `RELEASE_CXX` + version; fail validation when
`pinned_by_digest` is false on a non-dispatch run.

### GATE-12 · P2 · `.gitlab-ci.yml` is a divergent second CI  `[V]`
It runs `setup/lint/test` per track but **never** `product-gates` and never the
DSE suite, on a different image. "CI green" is forge-dependent. **Fix:** one
`scripts/ci_gate.sh` invoked identically by both forges, or delete the mirror.

---

## SEM — Compiler → routing → execution closure

### SEM-1 · P1 · Two route-dump parsers disagree; the strict one rejects the fork's own output  `[A]`
`backend/booksim.py:1124-1125` uses `^… port (\d+)$` (no trailer) inside
`compare_route_realization` (`:1162`, called at `:1425`) on the standalone
certified path, whose profile pins `topology = "anynet"`
(`backend/booksim_profile.py:57-58`). The fork's `AnyNet::buildRoutingTable`
always writes `… port P drop D lanes L`
(`third_party/booksim2/src/networks/anynet.cpp:367-371`), so route equivalence
can never reach EXACT on a real AnyNet run. The tolerant parser lives on the
other path (`backend/route_observation.py:23-25`). FAIL-CLOSED (valid evidence
refused). **Fix:** one parser, one ABI — call `route_observation` from
`booksim.py`; delete the duplicate.

### SEM-2 · P1 · The bus refusal lives only at the `derive_route` call site  `[A]`  (extends B)
`RouteArtifact.from_topology` / `validate_against` read `topology.channels`
only, so a **direct** call on a bus fabric yields a content-addressed route
table that is silently bus-less. The only guard is `model/routing.py:138-144`.
Production callers currently go through `derive_route`, so the gap is latent,
but the artifact seam should encode its own precondition. **Fix:** add the
`shared_links` precondition to `from_topology`/`from_adjacency`.

### SEM-3 · P2 · `parse_route_dump` is not forward-compatible  `[V]`  (extends E)
`backend/route_observation.py:23-25` ends in `(?: drop (-?\d+) lanes (\d+))?$`,
so **any** new trailer field makes the whole line malformed
(`RouteObservationError`). The comment at `:46` ("adding trailer fields cannot
break it") overstates it. FAIL-CLOSED. **Fix:** parse the four pinned fields
then tokenise key/value pairs; give the dump a version.

### SEM-4 · P2 · `escape_vcs` is invisible to the native projections  `[A]`
Standalone BookSim binds non-empty `escape_vcs` → `UNREPRESENTABLE` +
`BLOCKS_EXACT_FABRIC` (`backend/booksim.py:433-443`, `backend/meshdor.py:395-404`),
but the native qualifiers (`qualify_native_mesh_dor` etc. in
`backend/booksim_projection.py`) never test it, and the resource they consume
drops it (`model/vc_resource.py:336`). A declared deadlock-freedom policy is
neither executed nor reported on that path. Failure mode: **SILENT** (latent —
reachability not confirmed). **Fix:** pass `escape_vcs` into the native
qualifiers and refuse/bind a loss.

### SEM-5 · P2 · TopologyIR has no enforced schema version  `[V]`
`model/topology_ir.py:16` declares `SCHEMA_VERSION = "0"`, which is **never
read** anywhere; `schema_version` is not in `_DOC_KEYS` (`:32`). Sibling
artifacts all enforce a version. An in-place semantic change to an existing key
is accepted as v0. **Fix:** validate + emit `schema_version`, or delete the
constant and state v0 is the only shape. (Real cost: artifacts cannot be
migrated or hash-diffed by version.)

### SEM-6 · P2 · The BookSim backend name is decided in three places, and the prose one is wrong  `[A]`
`docs/product/topology-family-registry.yaml:168,179` says `ftree` / `dragonfly`;
`model/family_registry.py:233,236` says `fly` / `dragonflynew`; the vendored fork
dispatches only `fly` and `dragonflynew`
(`third_party/booksim2/src/networks/network.cpp:102,120`); a third copy (the
never-read `"booksim"` key) sits in `model/topology_artifact.py:785-809`.
`check_topology_family_registry.py` never validates `backend_projection`.
**Fix:** generate the yaml column from `family_registry`, and assert membership
in `BOOKSIM_TOPOLOGIES`.

### SEM-7 · P2 · Dead `_CERTIFIED_FAMILIES` is still cited as `derive_route`'s gate  `[A]`  (extends I)
`model/routing.py:22-25` defines it; the live decision is
`_POLICY_BY_FAMILY`/`routing_policy_for`. The dead constant is cited by
`docs/product/INTENT-FABRIC.md:680`, `feature-reclamation-registry.yaml:330`,
and `scripts/gen_feature_reclamation.py:168`. **Fix:** delete it, or make
`routing_policy_for` consult it so the documented invariant is the executed one.

### SEM-8 · P2 · `_edge_key` docstring contradicts its code; both it and `recognize_family` are dead  `[A]`  (extends G)
`model/topology_artifact.py:835` says a shared link expands to one edge per tap,
but `:842` skips every `directed` link and shared wires are always
`directed=True` (`topology_ir.py:380-381`) — so a bus can never contribute edges.
**Fix:** delete the dead pair, or make the skip explicit for `shared` and fix
the docstring.

### SEM-9 · P2 · The torus registry evidence contradicts the implemented dateline CDG  `[A]`
`docs/product/topology-family-registry.yaml:68,73` says a static `(channel,VC)`
CDG "cannot express the dateline partition" (`VERIFIABLE: "NO"`), but
`verification/channel_vc_cdg.py:23,143-168` implements
`DATELINE_RESTRICTED_EXPANSION` and `tests/test_torus_e2e_qualify.py` asserts a
PASS certificate through it. One of the two is stale. **Fix:** re-derive the
evidence field (state the exact domain: 1-VC fails, 2-VC exact-halves passes).

### SEM-10 · P2 · Duplicated statement in the dateline expansion  `[A]`
`verification/channel_vc_cdg.py:180-181` assigns `channel_by_id = {…}` twice
identically. **Fix:** delete line 181.

---

## INT — Epistemic integrity (silent wrongness over explicit refusal)

### INT-1 · P1 · Compute provenance is validated at the boundary and ignored downstream  `[A]`
`model/compute_intent.py:109-175` types the source as
`measured|derived|declared|unspecified` with enforced preconditions — but the
**only** consumer is the lowering view (`application/views.py:436-440`). It is
absent from `application/comparison.py` (`KNOWN_DIMENSIONS`), from the
persisted `wave_e` keys (`application/wave_e_resources.py:40-46`), and from the
optimization fidelity gate. A `measured` source needs only a non-empty free-text
`reference` — no digest binding, unlike every other measured claim here. So a
`QUALIFIED` artifact reads identically whether its durations were measured or
typed in. Failure mode: **SILENT**. This is the same class as the documented
`tests/test_compute_provenance.py:3-8` position ("the fabric's QUALIFIED verdict
is about the fabric…").
**Fix:** persist `compute.source` into result/plan/study fidelity context; gate
or explicitly degrade certified objectives whose evidence rests on a
non-`measured` compute source.

### INT-2 · P1 · A failed BookSim run becomes the plausible latency `1000.0`, which BO optimizes against  `[V]`
`synthesis/bo_synthesizer.py:283-289` returns `1000.0` when the latency regex
misses and in `except (subprocess.TimeoutExpired, Exception)`; `:333-335`
accepts it into `_best_lat`, and `:438-444` prints `Best latency: 1000.0 cycles`
and writes `best_latency`. Reachable via `cli/cli.py:218-233` (`veritx
synthesize bo`). The product-path adapter **bans exactly these sentinels** —
`synthesis/rho_grpo_adapter.py:36` `BANNED_OBJECTIVES = {1000.0, 1e9}`, pinned by
`tests/test_rho_grpo_adapter.py:60` — so the guard exists and the legacy script
bypasses it. Failure mode: **SILENT** — a totally failed search reports a
winner.
**Fix:** raise a typed failure; never return a value that can win a `<`.

### INT-3 · P1 · `bo_synthesizer` fabricates collective demand when traffic is missing  `[V]`
The module's own law (`:142-145`) says "deliberately NO uniform fallback — a
synthesizer run on invented demand would fabricate a result", yet `:387-415`
catches every exception, injects `trace_col_*` allreduce events, and if still
empty hard-codes `trace_col_0`, which the analytical scorer then consumes
(`:329-331`). Trigger: a nonexistent `--traffic` path. Failure mode: **SILENT**.
**Fix:** refuse on an unreadable/demand-less traffic source; delete the fallback.

### INT-4 · P1 · A profile with no `provenance` block is silently labelled `measured` — and a shipped workload does it  `[V]`
`performance/profile_ingest.py:169-172` defaults
`ComputeSource(kind="measured", …, reference=source or origin)` when
`"provenance"` is absent; `source` is optional. The registry ships
`astr-llm-70b-tp4` bound to
`tracks/t3-topology/examples/profiles/astr-llm-70b-profile.json`, which has **no**
`provenance` key and is described in its own registry entry as an "example
profile document". It reaches the product catalog as a **measurement**. The
sibling `ska-low-correlator-profile.json` **does** declare `{"kind":"declared"}`
and `tests/test_compute_provenance.py:118-137` asserts as much — so the pattern
is known but not required. Failure mode: **SILENT**.
**Fix:** make `provenance` required in the profile schema (or default to
`declared`), and add a registry gate that refuses a product-mounted profile
without an explicit source.

### INT-5 · P2 · ASTRA floors every compute stage to 1 µs  `[A]`
`backend/astra.py:297` maps a missing duration to `0`; `:407-417` and `:615-617`
then compute `max(1, duration_ns // 1000)` µs. So 1 ns → 1000 cycles (1000×), 999
ns → 1000 cycles, and a duration-less stage → 1000 cycles **with no refusal**.
This feeds `declared_compute_cycles()` and `system_makespan_cycles`.
Failure mode: **SILENT** (quantization presented as exact). **Fix:** refuse a
duration that is not an exact µs multiple, or carry exact rational ns into
Chakra.

### INT-6 · P2 · `pareto_with_sealed_gate` hardcodes one fidelity, defeating the mixed-fidelity refusal  `[A]`
`optimization/pareto.py:40-52` stamps `fidelity: "FAKE_DETERMINISTIC"` on every
candidate before calling `core.comparison.pareto_with_scope`, which refuses
mixed fidelity by comparing exactly that field. Caller values are never
consulted, so the gate cannot fire by construction. Test-only today and already
documented as single-fidelity. Failure mode: **SILENT** (latent). **Fix:** take
fidelity per candidate and assert uniformity.

### INT-7 · P2 · `VerifiedEvaluationClaims.backend_profile` is populated with a fidelity class  `[A]`
`application/authenticated_evaluation.py:476,486` sets `backend_profile =
evidence_doc["execution_fidelity"]`, whose vocabulary is
`{QUALIFIED, DIAGNOSTIC_UNPINNED_PRODUCER, TEST_INJECTED}`
(`backend/evidence.py:41-43`). Everywhere else `backend_profile` means a profile
id. Currently unconsumed. Latent mislabel. **Fix:** rename the field or populate
it from `profile_id`.

### INT-8 · P2 · The shipped "capability truth" registry is hardcoded prose, and one literal decides a study status  `[A]`
`application/capabilities.py:9-64`'s docstring says "derived from sealed
modules", but only version strings are imported; `execution` / `route_evidence`
etc. are literals. `application/studies.py:126-151` reads
`capability_registry()["backends"][target]["execution"]` to relabel a study
error. `SERVING_BOOKSIM2` is permanently `"execution": "BLOCKED"` (`:40`) while
the readiness probe returns `READY` when the binary is present
(`backend/serving_adapter.py:141-160,225-235`). The sibling
`application/capability_truth.py:94-100` exists precisely to avoid this pattern
for topology families. Failure mode: **SILENT** (status label). **Fix:** derive
`execution` from adapter readiness, or mark the table explicitly as declared
policy, not "truth".

---

# Part 3 — Debloat inventory & policy

### DEB-7 · Comments are a non-problem — do **not** mass-strip docstrings  `[V]`
Measured, not asserted:
- commented-out code in `veritx_dse` (`^\s*#\s*(self\.|return |raise |if |for |…`): **0**
- `TODO|FIXME|XXX|HACK` in `veritx_dse`: **0**; in `apps/studio/src`: **0**
- `#` comment lines in `backend/`: ~20 of 17,438; `application/`: 3 of 12,673
- `Rationale:` docstring links: **206** files (the "564" circulating earlier is
  wrong), and `docs/product/intent-ontology.yaml` holds **473** `cite: file:line`
  references.

There is nothing to gain by removing comments, and every removed docstring line
shifts a `cite:` anchor. **Policy: keep docstrings and `Rationale:` links.**
Debloat by *authority boundary* (DEB-8), not by deleting prose.

### DEB-1 · P1 · `veritx synthesize-grid` runs a script whose dependency is deleted, then prints success  `[A]`
`cli/cli.py:248-250` runs `dse/scripts/run.py` and ignores the return code;
`run.py:9` `from evaluator import BOOKSIM_BIN` and `search.py:12` `from
evaluator import run_booksim`, but **no `evaluator.py` exists anywhere**. The CLI
still prints `Grid search complete`. Failure mode: **SILENT**. **Fix:** restore
`evaluator.py`, or delete `run.py`/`search.py`/`objective.py`/`space.py` and the
subcommand; at minimum check `returncode`.

### DEB-2 · P1 · Duplicated stand-alone script trees with contradictory authority  `[A]`
`dse/scripts/` (CLI-invoked: `cli.py:37`, `core/paths.py`) and
`dse/veritx_dse/tools/` (package copies) overlap; `veritx_dse/tools/README.md`
claims `tools/` is canonical while the CLI reads `scripts/`. `tools/flow_certifier.py`
vs `scripts/milestone_c.py`; `tools/multi_workload_pareto.py` (761 ln) vs
`scripts/multi_workload_pareto.py` (262 ln). This is the class of hazard that
causes fixes to land in the dead copy. **Fix:** pick one home and delete/repoint
the other; correct the README.

### DEB-3 · P1 · `tracks/t3-topology/runs/` = 4.0 GB ignored output  `[V]` — **REMOVED**
`studio-store` held 5,220 files / 4.0 GB, gitignored via `.gitignore:22` and
untracked. Removed in this cleanup (project ids recorded: `p-069d80f406aa`,
`p-070623e5124b`, `p-20d95eff51b7`, `p-263ae32b6dd3`, `p-4827ad18350d`,
`p-5624b5b52adb`, `p-7ec82a0cc33c`, `p-a8d49ace5aa9`, `p-dd4654bb127b`,
`p-e145601418a3`). Regenerable.

### DEB-4 · P2 · `scripts/archive/` looks dead but is registry-pinned  `[V]` — **RETAIN**
31 tracked `.py` files have no *code* importers, but
`docs/product/feature-reclamation-registry.yaml:204-205` and
`scripts/gen_feature_reclamation.py:85-87` reference
`tracks/t3-topology/scripts/archive/*`. Delete only its ignored `__pycache__`.

### DEB-5 · P2 · Byte-duplicate fixtures  `[A]`
`dse/tests/fixtures/astra_tiny/one-coll.et` ≡ `.et.0.et` … `.et.15.et` (17
files, 124 B each, identical md5); several `serving_chakra/dense_tp2` files are
byte-identical to `dense_tp4`. **Fix:** generate via one source + loop.

### DEB-6 · P2 · Byte-duplicate RTL/C++ sources  `[A]`
`rtl/mot_htree/islip.sv` ≡ `rtl/t3/islip.sv`; `matrixtraffic.cpp` is
byte-identical in `third_party/booksim2/src/`,
`third_party/astra-sim/extern/network_backend/booksim2/booksim2/src/`, and
`tracks/t3-topology/booksim-ext/`. **Fix:** confirm authoritative copy; delete or
document the vendored mirror.

### DEB-8 · P2 · Oversized modules — split by authority, not line count  `[A]`
Python (`dse/`, lines): `product/service.py` 3764 · `model/compile_model.py`
2658 (two frozen contract versions) · `backend/booksim_projection.py` 1993 ·
`cli/cli.py` 1774 · `backend/booksim.py` 1566 · `optimization/result.py` 1385 ·
`backend/meshdor.py` 1218 · `model/topology_artifact.py` 1209 ·
`application/results.py` 1148 · `core/route_artifact.py` 1057 ·
`application/federated_evaluator.py` 974.
Studio: `styles.css` 3025 · `pages/index.tsx` 1860 · `api/types.ts` 1555 ·
`DesignViewV2Editor.tsx` 1303 · `pages/synthesize.tsx` 1068 ·
`pages/evaluate.tsx` 985.
Rule: **one orchestration owner per user operation, one derivation owner per
scientific artifact.** Do not split merely to reduce lines.

### DEB-9 · P2 · Stale script inventory in `dse/README.md`  `[A]`
`README.md:255-280` and `:960` list `bo_synthesizer.py`,
`iterative_synthesizer.py`, `ppa_evaluator.py`, `surrogate.py`,
`deadlock_routing.py` — none exist in `dse/scripts/`. **Fix:** generate the table
from `ls`.

### DEB-10 · VERIFIED-RETAINED — do not delete  `[V]`
`veritx_dse/application/inventory.py` (asserted by `tests/test_lineage_pipeline.py`),
`veritx_dse/workload/migration.py` (asserted by
`tests/test_workload_origin_parity.py:102,119`), root `archive/` (referenced by
`apps/studio/src/components/ImplementationLab/capabilityLedger.ts:222-240`),
`tracks/t3-topology/product/`, `dse/inputs/` (12 MB, referenced by tests and
READMEs), `dse/qualification/ramulator.py` (used by
`validation/harness/engines.py:51`).

### DEB-11 · Ignored/generated artifacts — reconciled  `[V]`
Removed in the 2026-09-30 cleanups (4.8 GB → 690 MB):
- `tracks/t3-topology/runs/` — 4.0 GB, 5,220 files (Studio store; DEB-3).
- root `runs/` — 716 KB; `tracks/t3-topology/dse/runs/` — empty dir.
- untracked `*.log` — **98 MB**, almost all
  `third_party/llmservingsim/astra-sim/log/log.{1..9}.log` (~11 MB each) plus
  `log.log`; gitignored via `*.log`.
- `__pycache__` (64 dirs), `.pytest_cache`, `.hypothesis`, `apps/studio/dist`,
  `scripts/archive/__pycache__`.

Left in place **deliberately** — are build products, not runs:
- `third_party/booksim2/src/booksim` (21 MB) — the binary the live gates set
  `VERITX_BOOKSIM_BIN` to.
- `third_party/*/build`, `*.o`, `*.a`, `*.so`, `chakra/…/et_def.pb.{cc,h}` —
  linked by the live gates, and 
  `make release-build` cannot currently regenerate them in CI (GATE-6, no
  `protoc`). Do **not** `rm -rf` `third_party/astra-sim/build` — it contains
  **tracked** `build.sh`/`CMakeLists.txt` (DEB-10).
- `apps/studio/node_modules` (173 MB) — a working dependency install;
  `npm ci` regenerates it.

---

## Resolved

| Problem | Closed by |
|---|---|
| SEALED PREPARED-INPUT drift: `test_prepared_backend_input_bytes_are_unchanged` was red 2026-09-30 → 2026-10-05. `a6e78010` added the AnyNet route-cost token, so each `.anynet` link line became `<dst> <latency> <cost>`; that moved `anynet/2x2_explicit.topology_bytes_sha256` (`4aedbac2` → `4f8c4327`) and, because it binds the topology bytes, `prepared_id`. The commit updated the projection tests but not this fixture. Re-frozen deliberately, with the reason recorded in `scripts/gen_sealed_input_golden.py:PROVENANCE` and emitted into the golden itself, so the fixture now carries its own audit trail | `f1d2e230` |
| D: dead asymmetric-native refusal; direction-losing `sequential_adj`; stale cost/latency docs in `docs/decisions/modules/backend.md` | `b2e37219` |
| `NETWORK_COMPLETION` died for the 4 structured families (route-dump trailer regression) | `825b45c6` |
| `recognize_family` lost to the OOM; restored, with arithmetic edge pre-check + bounded sweep | `9a1e72a3` |
| Fat-tree seat capacity dropped in structured dispatch (16 agents refused) | `9a1e72a3` |
| One-way / non-strongly-connected fabric hung `AnyNet::route` | `a6e78010` |
| Heterogeneous latency refused because latency was the route cost | `786aa96a` |
| Unknown `link_attrs` key silently flattened; explicit-topology latency dropped | `9175f6de` |
| AnyNet collapsed parallel links; no cost token separate from latency | `a6e78010` |
| Multidrop / lane pinning absent from the simulator | `1a5b05aa` |
| Docs: routing-fidelity, `recognize_family` caller, analytical-leg and certification gaps recorded | `9477c710` |

---

## Coordination

Two agents have worked this branch concurrently. To avoid two writers colliding,
partition by area: the topology/AnyNet C++ + link model, and the
evaluation/`application` + `backend/route_observation.py` path. Never commit a
blanket `git add -A` while the other agent has a dirty tree.

---

## Suggested next cycle (audit's recommendation, for the record)

Fix the four contracts before adding features: (1) green + hermetic release path
(GATE-1/5/6); (2) shared-resource routing end-to-end (B, SEM-1/2); (3) backend
representability as one generated artifact, not prose (GATE-4, SEM-6, INT-8);
(4) compute/placement provenance carried into every decision (INT-1/2/4).
Postpone new topology families, BO/RL work, and extra Studio pages until then.
