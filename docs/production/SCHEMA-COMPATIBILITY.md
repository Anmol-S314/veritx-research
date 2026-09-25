# VERITX Schema Compatibility (C8 / P5)

Persisted scientific documents are versioned and **refused, never
migrated silently**, when their generation is incompatible. A document is
re-authenticated by recomputing its content hash and re-proving its
semantic invariants; a version mismatch is a typed refusal.

Policy:

- A generator bump is a **hard incompatibility** when the change alters
  identity-bearing inputs (e.g. the convergence window) or the meaning of a
  field. Old documents are not reread as the new version.
- A document that is self-consistent but semantically impossible is refused
  after all hashes are recomputed (`test_evidence_admissibility.py`).
- Unknown declared schema versions refuse.

## Key versions at the release candidate

| document | constant | value | incompatible with |
|----------|----------|-------|-------------------|
| CompileRequest | `COMPILE_REQUEST_SCHEMA_VERSION` | 2 | v1 |
| compiler semantics | `COMPILER_SEMANTICS_VERSION` | 2 | — |
| attachment | `ATTACHMENT_SCHEMA_VERSION` | 3 | <3 |
| packet format | `PACKET_FORMAT_SCHEMA_VERSION` | 2 | 1 |
| resolved route | `RESOLVED_ROUTE_SCHEMA_VERSION` | 2 | 1 |
| address decode | `ADDRESS_DECODE_SCHEMA_VERSION` | 3 | <3 |
| router behavior | `ROUTER_BEHAVIOR_SCHEMA_VERSION` | 3 | <3 |
| logical messages | `LOGICAL_MESSAGE_SCHEMA_VERSION_V2` | 2 | v1 (removed) |
| prepared BookSim input | `BOOKSIM_PROJECTION_SCHEMA_VERSION` | **5** | v1–v4 (v4 lacked route rows; v<5 had the packet-count window) |
| backend evidence | `EVIDENCE_SCHEMA_VERSION` | **3** | v1 (no manifest), v2 (no route dump) |
| BookSim parser | `PARSER_VERSION` | `veritx/booksim-stats-parser/v2` | v1 (window metric) |
| trace schedule | `TRACE_SCHEDULE_VERSION` | `srota/booksim-trace-schedule/v2` | v1 (packet-count window) |
| build manifest | `BUILD_MANIFEST_SCHEMA_VERSION` | 1 | — |
| backend config | `BACKEND_CONFIG_SCHEMA_VERSION` | 2 | 1 |
| serving round / ledger | `SERVING_ROUND_SCHEMA_VERSION` / `LEDGER_SCHEMA_VERSION` | 1 / 1 | — |

## Recent hard bumps and why

- **prepared v3→v4 / evidence v2→v3:** executed route realization (P0.10).
  Evidence must bind the route dump digest; a v2 document cannot prove the
  executed route.
- **prepared v4→v5 / schedule v1→v2:** F-0007 convergence window is now the
  per-source injection horizon, which is identity-bearing. A v4 prepared
  input encodes a window that can truncate concentrated traces.
- **parser v1→v2 / evidence v1→v2:** F-0001 completion metric
  (`Completion time is`), and provenance binding (manifest + recipe).

## Golden fixtures

Migration fixtures are owed (`tests/` golden documents per generation).
Today the contract is proven adversarially: an old-generation document
refuses; a self-consistent rehashed impossible document refuses.
