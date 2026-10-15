# The unified project document

Extracted from `apps/studio/src/project/document.ts` and
`apps/studio/src/project/migrate.ts` (tracker M0-01/M0-03/M0-04).

## Decision

There is one `project.json`, and it is the unified project document.

```
contracts/loom/v1/project.document.schema.json
  schema_version            integer, const 1
  compiler_semantics_version integer, >= 1
  metadata                  { id, name, created_at?, updated_at? }
  graph                     $ref project.schema.json   (the graph sub-document)
  catalog_refs, agents, domains, access, floorplan, workload   object|array|null
```

The graph authoring document (`contracts/loom/v1/project.schema.json`) is a
*component* of this envelope, not a competing top-level format.

## Why

Before this, the only versioned document was the narrow graph form
(`schemaVersion: 1` with `nodes`/`edges`). Catalog references, agents, domains,
access, floorplan and workload had no single home, and there was no migration
chain. The workbook wants one document a reader can migrate and version-check.

## Versioning

Two independent versions, deliberately distinct:

- `schema_version` — the **document** version. Bumped when the envelope shape
  changes; a reader migrates older documents up to the version it implements.
- `compiler_semantics_version` — the **compiler semantics** the project targets.
  A generated run records the same value, so a result is never read under
  mismatched semantics. The Python canonical request
  (`veritx_dse/model/compile_request_v4.py` / `_v5.py`) and the run/revision
  contracts already carry this; the project document now carries it too.

## Migration

`apps/studio/src/project/migrate.ts` is a generic step registry: each step moves
exactly one version (`from -> from + 1`). `migrateDocument` deep-clones the
input (it never aliases or mutates the caller's value), applies steps in order
under a bounded loop, and **refuses rather than guesses**:

- a document newer than this build → `migration.future_version`;
- a version with no registered path → `migration.no_path`;
- a malformed `schema_version` → `migration.bad_version`;
- a step that does not move exactly one version → `migration.bad_step`.

`apps/studio/src/project/document.ts` registers one step today:
`project.v0_to_v1`, which recognises the legacy flat graph form (no
`schema_version`, camelCase `schemaVersion` present) as project schema **0** and
lifts it into the envelope, moving the graph-local `firewall`/`workload`
annotations into the top-level `access`/`workload` sections.

## Editor state vs file format

The in-app authoring state stays graph-scoped (the access and workload editors
read `store.doc.firewall` / `store.doc.workload`). The envelope is the **file**
format:

- `wrapProjectDocument(graph)` lifts `firewall`/`workload` into `access`/
  `workload` and emits a pure graph;
- `graphFromDocument(doc)` folds them back so the editors keep working.

Save/load therefore round-trips a project without losing the access or workload
sections, while the file on disk is the unified document.

## Scope note

Section payloads (`catalog_refs`, `agents`, `domains`, `access`, `floorplan`,
`workload`) are validated structurally here (object | array | null). Their deep
shape is owned by their own contracts as those land (M0-06 VC, M0-10 access,
M0-12 workload).

## Proof

`apps/studio/src/contract/project-document.contract.test.ts` — section coverage,
legacy lift, non-mutation, step ordering, future/no-path/malformed refusal,
save/load round-trip, deterministic serialization and stable fingerprint.
