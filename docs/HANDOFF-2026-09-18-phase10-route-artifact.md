# HANDOFF — Phase 10: RouteArtifact (one routing truth)

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port` @ `08ad0bc6`
**Prior gate:** Phase 9 (1135 passed, 1 skipped)
**Next permitted:** Phase 11 (RTL credibility) — **STOP here until reviewed.**

## What landed

One content-addressed **RouteArtifact** (`core/route_artifact.py`): the
exact per-router next-hop behavior the simulator executes, versioned and
hash-verified, so consumers reference `artifact_hash` instead of
re-deriving (and hoping) the same routes.

The audit found the routing truth already existed as code — the
certifier's `booksim_first_hop_table` (an exact AnyNet::route() replica
with documented tie-breaks) — plus a CSV export stopgap and an F6 stub
pinned on "pending RouteArtifact". Phase 10 promotes the replica; it
does not invent a second one.

## Flow (actual)

```text
anynet file ──► core/anynet.py (ONE parser; non-unit weights recorded)
                    │
                    ▼
core/route_artifact.py
    _anynet_replica_first_hops(n, adj)   ← the AnyNet::route() replica
    RouteArtifact.from_adjacency(...)    ← validate + hash (fail-closed)
    equivalence_report(artifact, executed) ← per-flow divergence report
                    │
                    ▼
tools/deadlock_routing.py          (thin delegation — one implementation)
    deadlock_certificate(method="booksim") now embeds the artifact
    cert JSON: {…, "route_artifact": {schema_version, topology_hash,
                routing_algorithm, tie_break_policy, entries,
                route_table_hash, artifact_hash}}
    .routes.csv stays as the human diff seam (unchanged contract)
                    │
                    ▼
model/compile_model.py F6_routing_correctness
    NOT_RUN → PASS (COMPARABLE evidence, artifact re-verified by hash)
            → FAIL (DIVERGENT evidence, per-flow pin, or tampered artifact)
```

## Schema (v1) and why

```text
schema_version      1 (v2 reserves the per-class axis with the VC artifact)
topology_hash       sha256 over the CANONICAL graph serialization
                    (sorted adjacency list-of-lists). Not raw file
                    bytes: comment/whitespace/attachment-order noise is
                    transport, not routing identity.
routing_algorithm   "anynet_dijkstra_hops" — the EXECUTED semantics,
                    not the design label ("dor"/"dim_order" are names,
                    not proofs)
tie_break_policy    the documented anynet.cpp tie-break string
                    (ascending rlist first-strict-min; strict-<
                    first-predecessor-sticks; ascending neighbors)
entries             {(src,dst): next_hop} — all-pairs minus diagonal,
                    next hop must be an actual neighbor of src
route_table_hash    sha256 over entries ONLY — the hash a consumer
                    (BookSim/RTL later) can verify without trusting the
                    rest of the artifact
artifact_hash       sha256 over {schema_version, topology_hash,
                    routing_algorithm, tie_break_policy, route_table_hash}
```

Identity vs transport (Phase-9 lesson applied): `name` rides the
serialized artifact but is excluded from `artifact_hash`.

## Rulings

**Weighted topologies — refused (PR D policy, now enforced at
construction).** The replica is hop-count based; BookSim's AnyNet
Dijkstra uses stored weights as edge distance. Certifying a weighted
graph would certify route set A while BookSim runs route set B. Weights
must flow through the replica end-to-end before weighted certification
exists. `from_adjacency(weights=…)` and `artifact_from_anynet` on a
weighted parse both raise.

**Partial coverage — refused.** All-pairs minus diagonal is the AnyNet
contract; a table with gaps "lies about coverage". Per-entry legality
(neighbor, in-range, integer) is checked before coverage so the
offending flow is named first.

**Per-class axis — deferred to v2.** §14: no VC-aware deadlock claims
while only physical channels are checked. The certificate's
`escape_vcs_required`/CDG verdicts keep their existing honest scope
language.

**BookSim verification of the artifact — eventual, not claimed.** No
BookSim-side route dump exists in the fork. The certifier emits the
artifact from the same replica BookSim follows; equivalence against an
externally produced table is exactly what `equivalence_report` +
F6 exist for (RTL will consume this in Phase 11).

## F6 contract (evidence seam)

```text
evidence["route_equivalence"]  the equivalence_report dict
evidence["route_artifact"]     the serialized artifact (optional but
                               recommended; re-verified on load)
```

- COMPARABLE + hash-verified artifact → PASS with
  `route_table_hash` and matched/total flow counts in the detail
- DIVERGENT → FAIL pinning the first mismatched flow
  `(src,dst): artifact X vs executed Y`
- Tampered artifact (entries edited post-hash) → FAIL with
  "RouteArtifact failed hash verification" even if the report says
  COMPARABLE — the report is only as good as the table it compared
- No evidence → NOT_RUN (unchanged)

`from_dict` re-verifies both hashes on every load: an artifact whose
table was edited after signing cannot be constructed.

## Tests added

`tests/test_route_artifact.py` — **22 tests**: construction
(executed-semantics recorded, unknown algorithm refused, weighted
refused, disconnected refused, bad next hop named, incomplete coverage
refused), hashing (same semantics → same hashes; name excluded;
route change moves table hash not topology hash; topology change moves
topology hash; roundtrip preserves hashes; tampered entries detected on
load), extraction (entries == AnyNet replica on a grid and on the real
`anynet16.links`; canonical topology hash absorbs construction noise),
equivalence (COMPARABLE with counts; divergence pinned per-flow;
missing executed flow visible in its own bucket), F6 (PASS on
comparable evidence with hash in detail; FAIL on divergence; NOT_RUN
without evidence; FAIL on tampered artifact).

`tests/test_routing_stopgap.py` — +1: booksim cert carries the
artifact; reloads hash-verified.

## Full-suite result

**1158 passed, 1 skipped** (Phase 9: 1135 → +23). `make -C
tracks/t3-topology lint` PASS. Live: `deadlock_routing --method booksim`
on `anynet16.links` emits a 240-entry artifact in the cert JSON that
reloads hash-verified.

## Known residuals (honest list)

1. **BookSim does not yet *consume* the artifact** (no route dump in the
   fork). Certifier-emits + hash-reference is the Phase-10 state;
   executed-side verification is `equivalence_report` when a table
   arrives from a backend (RTL first, Phase 11).
2. **VC artifact not started** — v2 axis reserved only; per §14 VC
   assignment becomes explicit only after routing truth is stable.
3. `mclb`/`shortest`/`escape` methods still produce plain tables
   (no artifact embedding — only `booksim` is the certified executed
   semantics). Their certs are unchanged.
4. The CSV stopgap remains by design as a human diff seam; the JSON
   artifact is now the machine truth.

## Phase gate (§14)

```text
[x] one content-addressed exact routing artifact exists (schema v1)
[x] topology identity is canonical, not file-bytes
[x] executed routing semantics recorded as data (algorithm + tie-break)
[x] per-(router,destination) next-hop behavior, all-pairs coverage enforced
[x] route_table_hash verifiable independently of the rest
[x] certifier consumes RouteArtifact (deadlock cert embeds it)
[x] F6 upgrades from NOT_RUN on equivalence evidence, fails closed on divergence
[x] tampered artifacts cannot load (hash re-verified)
[x] weighted AnyNet still refused end-to-end
[x] no VC-aware claims beyond physical-channel scope (v2 deferred honestly)
[x] full suite passes
```

**Gate: PASS.** STOP before Phase 11 (RTL credibility) — awaiting review.
