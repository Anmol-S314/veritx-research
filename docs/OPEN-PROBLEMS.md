# VeritX open problems

_Last updated: 2026-09-30. Branch `integration/studio-reconciliation`, base HEAD `246fa118`._

This is the durable list of known gaps, so they survive session and agent
turnover. When you close an item, move it to **Resolved** with the commit that
closed it — do not delete it. When you discover a gap, add it here in the same
breath as fixing the easy part.

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

## Open problems

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

## Resolved

| Problem | Closed by |
|---|---|
| D: dead asymmetric-native refusal; direction-losing `sequential_adj`; stale cost/latency docs in `docs/decisions/modules/backend.md` | `b2e37219` |
| `NETWORK_COMPLETION` died for the 4 structured families (route-dump trailer regression) | `825b45c6` |
| `recognize_family` lost to the OOM; restored, with arithmetic edge pre-check + bounded sweep | `9a1e72a3` |
| Fat-tree seat capacity dropped in structured dispatch (16 agents refused) | `9a1e72a3` |
| One-way / non-strongly-connected fabric hung `AnyNet::route` | `a6e78010` |
| Heterogeneous latency refused because latency was the route cost | `786aa96a` |
| Unknown `link_attrs` key silently flattened; explicit-topology latency dropped | `9175f6de` |
| AnyNet collapsed parallel links; no cost token separate from latency | `a6e78010` |
| Multidrop / lane pinning absent from the simulator | `1a5b05aa` |

---

## Coordination

Two agents have worked this branch concurrently. To avoid two writers colliding,
partition by area: the topology/AnyNet C++ + link model (this file's owner), and
the evaluation/`application` + `backend/route_observation.py` path. Never commit
a blanket `git add -A` while the other agent has a dirty tree.
