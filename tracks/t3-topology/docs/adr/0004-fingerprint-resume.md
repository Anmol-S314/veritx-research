# ADR 0004 — Resume/caching requires a dependency-fingerprint match

Status: accepted (2026-09-17)
Context: control-plane redesign §3.9. Legacy resume logic was
`if result_file.exists(): skip` — a stale output from a different seed, an
older binary, or an edited trace would silently enter a comparison.

## Decision

A reusable task output may be skipped only when its **dependency fingerprint**
matches the current intent exactly. The fingerprint is a hash over:

- the task's resolved specification slice,
- content hashes of its inputs (trace bytes, config bytes),
- simulator identity (binary SHA-256 or container digest — never a tag alone),
- code identity (git commit + dirty state),
- seed(s).

Any mismatch means: recompute, or continue only after an explicit user
decision recorded in the run. **No silent reuse.** When in doubt, recompute —
sims are cheap; a contaminated comparison is not.

Until a task system exists (PR 3+), this ADR governs in spirit: nothing is
reused across runs; every run recomputes from its frozen resolved spec.

## Consequences

- Fingerprint inputs are exactly the provenance fields (ADR 0006), so the
  check reuses the capture machinery — one concept, one implementation.
- "Why did it re-run?" is answerable: the mismatched component is named.
- Deterministic replays are safe to skip; stochastic replays are skip-eligible
  only when the seeds in the fingerprint match exactly.
