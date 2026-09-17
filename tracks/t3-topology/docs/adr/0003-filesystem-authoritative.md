# ADR 0003 — Files on disk are the authoritative research record

Status: accepted (2026-09-17)
Context: control-plane redesign §3.4, §14. The legacy flow scattered
authoritative state across a shared mutable sweep JSON plus whatever logs
happened to survive; results/ cleanup passes in the past have destroyed data
that existed nowhere else.

## Decision

The immutable run directory (manifest, resolved spec, logs, results) **is** the
research record. Indexes and summaries are derived views:

- SQLite (`index.db`), if introduced, is a rebuildable cache. `veritx index
  rebuild` must be able to reconstruct it entirely from run manifests. Its
  deletion must never make a run un-findable or un-reproducible.
- In-memory state (CLI sessions, TUI state) is presentation, never authority.
- Any "results" store that is not backed by files inside run directories is
  provisional by definition.

Writes to authoritative files are atomic: temp file on the same filesystem,
then rename (`core.recovery.atomic_write`). Never truncate-and-rewrite a live
manifest or state file.

## Consequences

- Archival = copying run directories. No database dump is ever required.
- The purge/cleanup lesson from 2026-09-16 is encoded: deleting `results/` or
  `index.db` must be safe; deleting `runs/<run_id>/` is the only way to lose a
  run, and it is loud.
- Downstream tools (compare, reports, plots) read run directories directly, so
  they keep working when the index is stale or absent.
