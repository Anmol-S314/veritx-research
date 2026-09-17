# ADR 0006 — Provenance is automatic; execution is argv-only

Status: accepted (2026-09-17)
Context: control-plane redesign §3.6–3.7, §3.12, §15. Legacy `t3` built
commands through shell word-splitting (quoting loss), and provenance existed
only where a script author remembered to record it.

## Decision

**No-shell boundary.** The execution layer launches processes exclusively with
argv arrays (`subprocess.run([...], shell=False)` — the default). No
`shell=True`, no f-string command assembly, no `os.system`. Frontends (CLI,
TUI, web, future agents) never receive arbitrary-execution primitives; they
call semantic operations that internally build argv.

**Automatic provenance.** Every run captures, without opt-in: git commit +
dirty state, resolved-spec hash (ADR 0002), input content hashes, simulator
binary SHA-256 or container **digest** (never a mutable tag alone), execution
environment type (native/container), actual argv, Python version, start/end
timestamps, seeds, exit status. Environment variables are captured from an
allowlist only — never a full env dump (credential leakage).

Provenance fields are exactly the fingerprint inputs of ADR 0004: one capture
path, two consumers.

## Consequences

- Shell-quoting bugs are structurally impossible in the new plane; the legacy
  `t3` quoting fix remains only for the compat shim.
- Runs executed with a dirty tree or `:latest`-tagged image are *detectably*
  less reproducible — the manifest says so instead of hiding it.
- Provenance capture lives in run initialization (PR 2), so no experiment
  author can forget it, and no experiment author can get it subtly wrong.
