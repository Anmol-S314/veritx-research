# ADR 0001 — Runs are immutable once execution starts

Status: accepted (2026-09-17)
Context: control-plane redesign §3.3; legacy behavior allowed later edits to
sweep JSONs in-place (`results/<CONFIG>/topology_sweep.json`), so the provenance
of a row could silently diverge from the config that produced it.

## Decision

A run's directory, resolved spec, and recorded inputs are immutable from the
moment execution starts. Any change to scientific intent — a different trace, a
different seed set, a different topology — is a **new run** with a new identity,
never an edit of an existing one.

- Post-run "corrections" happen in *derived* artifacts (plots, reports,
  comparison tables), never in the run directory.
- Deleting an entire run directory is permitted (disk hygiene); mutating
  individual files inside a completed run is not.
- Resume/repair writes only to files the state machine names as mutable
  (state.json, logs); spec.resolved.json and manifest inputs are frozen.

## Consequences

- Re-running an experiment always allocates a fresh run directory (cheap; runs
  are small — a manifest, a spec, logs, and result JSONs).
- Nothing downstream can be invalidated by an unnoticed edit: a result file's
  meaning is fixed by the spec hash captured beside it.
- Tools that used to append to shared result files (the old
  `results/<CONFIG>/topology_sweep.json`) must address an immutable run
  directory instead.

## Deletion test

Delete this rule and two things scatter: every consumer of a result must
re-validate that the spec beside it still matches the config it thinks produced
it, and "reproduce run X" becomes "reproduce run X *as it is now*", which is no
guarantee at all.
