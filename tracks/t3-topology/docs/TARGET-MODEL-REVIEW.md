# Destination model review — veritx-target-architecture

Reviewed the architect's target-state archive against this repository.
Archive integrity was verified rather than assumed:

```
SHA-256 manifest   61/61 files OK
structure          matches the declared tree (src/ layout)
suite              15 passed, exit 0   (PYTHONPATH=src pytest tests)
```

The archive is a **destination model**, not a patch. Nothing here is
applied; this note records what it resolves, what it dissolves, and the
one capability it appears to drop.

## What it confirms

- `WorkloadGraph` as the only workload authority — the direction 2c.4a/b
  are already committed to.
- `participant_count` independent of `world_size`, with an explicit
  `MappingArtifact(participant_count, rank_to_endpoint, fabric_id)` whose
  `endpoint_for(rank)` refuses out-of-range ranks. This is the same law as
  2c.4b §14/§15, but it makes the mapping a **first-class artifact with
  its own id and domain** rather than a gate inside the lowering path.
  That is strictly better than the plan I was working from: it means the
  participant→endpoint correspondence is persisted and identified, so
  the "world_size=8, participant_count=4" case refuses because no mapping
  exists, not because a comparison happened to fail.
- PIM as a channel state machine, not nesting — this repo already does
  that (`canonical_graph.py:803`, from 2c.3), so the archive's
  `test_source_migration.py` corroborates rather than requires work.
- `ScientificChain` is five ids: workload, messages, traffic, fabric,
  mapping — verified by exact `__dict__` comparison.

## What it dissolves

`ScientificChain` has no plan/experiment/result layer and no
backend-evidence digest, and the destination carries a single schema
generation everywhere (`schema_version = 2`) because there is no history
to protect.

Consequence for the in-flight work: the v1/v2 generationing in 2c.4a
(`chain_schema_version`, `PLAN_CHAIN_KEYS_V1/V2`, dual loaders) is
**transitional machinery that the destination deletes**. That does not
make it wrong — it exists to keep historical evidence verifiable *during*
the migration — but it must not be mistaken for part of the destination.

## The gap: evidence authentication

Current repository, `wavee/network.py`: a timing binding refuses to bind
unless it can name the sha256 of the exact authenticated evidence bytes
(§42 anti-fabrication), and the binding carries `stats_sha256` alongside.

Destination, `backend/base.py`:

```python
@dataclass(frozen=True)
class BackendEvidence:
    backend: str
    input_id: str
    counters: tuple[tuple[str, int], ...]
    raw_summary: tuple[tuple[str, Any], ...] = ()
```

No content digest, and no digest anywhere in the evidence path. The
result identity (`application/results.py`) includes backend, input_id and
counters — so a result names the traffic it claims to describe, but
nothing authenticates the counters against the bytes a backend actually
produced.

So adopting the destination as-is **drops** an anti-fabrication property
this repo currently enforces. That is a decision to make explicitly, not
a simplification to inherit. If it is kept, it belongs in
`BackendEvidence` (a digest of the raw summary) and in the result
identity; if it is dropped, the §42 contract must be retired on purpose.

This is also the answer to the four `NetworkWindowBinding` sites found in
the 2c.4b pre-flight (ledger 3.1–3.4): the destination does not need to
version that structure because it has no such structure. The current repo
still does, so the binding-generation decision is a **live** problem for
the migration regardless of where the destination ends up.

## Cutover ordering

`MIGRATION_CUTOVER.md` step 1 is "finish the current WorkloadGraph runtime
cutover", which is exactly 2c.4b/4c. The ordering below is the same one,
with the two corrections this review adds (mapping as an artifact, and an
explicit evidence decision) placed before the writer switch:

```
finish WorkloadGraph cutover (messages v2, traffic v2, dual loaders)
  -> NetworkWindowBinding generation      (ledger 3.1-3.4)
  -> MappingArtifact as a persisted authority
  -> decide and record the evidence-authentication question
  -> writer switch, then 4c differential proof
  -> delete WaveD/WaveE authority, move performance/ out of wavee/
```
