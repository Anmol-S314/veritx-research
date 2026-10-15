# Loom project document v1 (frozen contract)

Status: **frozen**. Tracker task M0-01 ("Freeze project.json v1 contract"),
with M0-03 (`schema_version` + `compiler_semantics_version`), M0-04 (versioned
migration), M0-16 (canonical validation result model) and M0-19 (deterministic
serialization) defined by the same document.

## Files

| Artifact | Path | Role |
| --- | --- | --- |
| Document schema | `contracts/loom/v1/project.document.schema.json` | The unified `project.json` envelope |
| Graph schema | `contracts/loom/v1/project.schema.json` | The embedded graph authoring document |
| TypeScript model | `apps/studio/src/project/document.ts` | Parse, migrate, validate, canonicalize, fingerprint |
| Migration pipeline | `apps/studio/src/project/migrate.ts` | Generic versioned migration |
| Graph validator | `apps/studio/src/graph/project.ts` | Graph issues + canonical graph form |
| Contract test | `apps/studio/src/contract/project-document.contract.test.ts` | Proves the obligations below |

## Envelope

A `project.json` is one object. Unknown fields are refused
(`additionalProperties: false`).

```jsonc
{
  "schema_version": 1,               // const; reader migrates up, refuses newer
  "compiler_semantics_version": 1,   // integer >= 1; recorded by every run
  "metadata": {                      // id, name, created_at, updated_at
    "id": null, "name": null, "created_at": null, "updated_at": null
  },
  "graph": { /* contracts/loom/v1/project.schema.json */ },
  "catalog_refs": null,              // object | array | null
  "agents":       null,              // object | array | null
  "domains":      null,              // object | array | null
  "access":       null,              // object | array | null
  "floorplan":    null,              // object | array | null
  "workload":     null               // object | array | null
}
```

Every named section is **required but nullable**: absent means the project does
not carry it, and `null` is the canonical empty value. Deep shapes of
`catalog_refs`, `agents`, `domains`, `access`, `floorplan` and `workload` are
owned by their own contracts; the envelope validates them structurally
(`object`, `array` or `null`) and refuses anything else.

`graph` is the versioned graph authoring document: `schemaVersion` const `1`,
`presetHint`, `nodes` (≤ 256) and `edges` (≤ 512), with node/edge identity,
endpoint, degree and connectivity invariants enforced by the graph validator.
The graph is authoring state, not a compiled fabric or an execution claim.

## Identity rules (M0-02)

- A node is identified by `node.id` and an edge by `edge.id`; both are
  non-empty strings, unique within their collection. A duplicate id is an
  error.
- **Coordinates are never identifiers.** `node.x`/`node.y` are layout numbers
  only; renaming or moving an object never changes its id, and an id is never
  derived from a position, a display label, or a `R{x},{y}` coordinate.
- Every reference (`edge.src`, `edge.dst`, trace keys, selectors) is by id. An
  edge to an unknown id is an error.
- Identity survives save/load and migration unchanged. Copy/paste assigns
  fresh ids and rewrites the pasted edges to point at the copies, leaving the
  originals untouched.
- `pipelineStages` is a per-edge field in the canonical edge object (M0-05);
  there is no side map, and a legacy document that carries one is migrated or
  rejected rather than silently merged.

## Versioning and migration

- `schema_version` is the document version. This build implements
  `PROJECT_DOCUMENT_SCHEMA_VERSION = 1`.
- A document **without** `schema_version` that carries the flat graph fields is
  the legacy form, project schema version `0`
  (`LEGACY_PROJECT_SCHEMA_VERSION`).
- `migrateProjectDocument` lifts v0 to v1 with the single step
  `project.v0_to_v1`: it copies the flat form into `graph`, promotes a
  graph-local `firewall` to the top-level `access` section and a graph-local
  `workload` to the top-level `workload` section, and stamps the current
  `compiler_semantics_version`. Migration deep-clones its input and never
  mutates it.
- A document **newer** than this build is refused with
  `migration.future_version`, naming both versions. There is no silent guess
  and no downgrade.

## Canonical serialization

`canonicalizeProjectDocument` fixes top-level field order, applies the graph's
canonical form (fixed node/edge field order, dropped empty optionals), and
key-sorts the open sections. Two semantically equal documents therefore
serialize to byte-identical text, so diffs are meaningful and
`fingerprintProjectDocument` (a stable, non-cryptographic content hash) is
stable. `serializeProjectDocument` refuses to serialize a document with errors
and always emits a trailing newline.

## Validation result model

Every validator returns `ProjectIssue[]` with the same shape:

- `severity` — `error` | `warning`. Errors block every path; warnings are
  authoring-legal (for example a disconnected graph while editing, escalated to
  an error at compile/run time).
- `code` — a stable machine code (e.g. `graph.disconnected`).
- `message` — a human-readable explanation.
- `objectRef` — a stable reference to the object at fault (`$.nodes[id=n3]`).
- `components?` — component membership for `graph.disconnected`.
- `quickFix?` — optional safe, mechanical fix metadata (`{ label, code }`) a UI
  may offer.

`validateProjectDocument` validates the envelope (versions, metadata, sections)
and re-roots embedded graph issue paths under `$.graph` so one document yields
one flat issue list with unambiguous locations.

## Change policy

v1 is frozen. A shape change that a v1 reader could not read safely requires a
new `schema_version` plus a registered migration step; it is never a silent
edit to v1.
