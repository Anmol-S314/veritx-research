# ADR 0002 — Run identity and experiment identity are different questions

Status: accepted (2026-09-17)
Context: control-plane redesign §3.1–3.2. The legacy layout keyed results by
`results/<command>/<timestamp>_seed/` — a display label, not an identity; two
runs of the same command were distinguished only by wall-clock time.

## Decision

Two identifiers, deliberately not interchangeable:

- **run_id** — one realized execution. ULID-style (uuid7, sortable, unique per
  execution). A rerun of the identical experiment gets a *new* run_id.
- **experiment_hash** — the scientific intent. SHA-256 over the canonical JSON
  serialization of the fully **resolved** spec (every default materialized,
  every reference expanded, deterministic key order). Two runs share an
  experiment_hash iff they intended the same experiment.

Answers:

- "Which execution produced this artifact?" → run_id.
- "Were these two runs the same experiment?" → equal experiment_hash.

The hash covers resolved *scientific* content only. Presentation fields
(notes, display labels) are excluded by an explicit allowlist in
`core/spec.py`, not by silently stripping unknown keys.

## Consequences

- Parity/comparison tooling can group runs by experiment_hash instead of
  guessing from names.
- The hash must be stable across processes and machines: canonical
  serialization (sorted keys, fixed separators, resolved values only) is tested
  in `tests/test_run_core.py`.
- Changing the resolution rules changes the hash — that is correct and desired,
  but the schema_version in the spec must be bumped when it happens.
