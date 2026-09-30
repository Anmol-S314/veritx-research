# VeritX open problems

_Last updated: 2026-09-30. Branch `integration/studio-reconciliation`, base HEAD `825b45c6`._

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

### D — Hygiene / stale facts  ·  SMALL

- `backend/booksim.py` `_require_representable_links`: the
  `_selected_routing_class(bundle) != ANYNET_MIN_HOPS` clause can never be true,
  so the asymmetric-native refusal never fires. Delete it or make the one-way
  check actually run for native topologies.
- `core/anynet.py` `sequential_adj` is still the undirected union, so the legacy
  `artifact_from_anynet` would symmetrize a one-way file. No production caller;
  the live gate (`check_anynet_connected`) uses `router_directed`. Either
  direction-preserve it or label it legacy.
- `docs/decisions/modules/*.md` and `docs/product/*.yaml` still describe the old
  latency↔cost coupling that `786aa96a` removed.

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

## Resolved

| Problem | Closed by |
|---|---|
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
