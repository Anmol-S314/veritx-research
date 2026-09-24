# VERITX Production Seal

**Release decision: NOT READY**

This document is the release-seal report required by the production
program. It is written at each candidate; the verdict is `NOT READY`
until every seal condition is met.

## 1. Release candidate SHA

`prod/production-readiness` HEAD (local, unpushed). Base `190d04f1`
(B4 freeze). See `BASELINE.md` for the exact per-commit list. The branch
has not been tagged, and `main` has not been modified.

## 2. Base SHAs

| Ref | SHA |
|-----|-----|
| `origin/main` | `4be11e484aa81aa36799a9098f132f1eacfe2d2c` |
| `github/veritx-integrate` | `39a180ecc87c90241a674d59d1c4f14deda721bb` |
| `github/validation/b4-campaign` | `190d04f1` (F-0004 hardening + full campaign freeze) |

## 3. Authority map summary

See `AUTHORITY-MAP.md`. B1 (second compile authority) and B6 (shadow
`CompileRequest`/`migrate_design`) are CLOSED. Open blockers: B2
(`application/results.py` RT vocabulary), B3 (evidence admissibility is
now closed; the single producer admission rule remains), B4 (no build
manifest), B5 (timestamped run dirs), B7 (ValueError-rooted semantic
taxonomy).

## 4. Closed findings

| finding | severity | root cause | fix | regression test |
|---------|----------|------------|-----|-----------------|
| VC builder collapsed malformed/duplicate authoring into valid artifacts | high | `dict()`/set conversion before validation | `a0b934b6` | `test_vc_assignment.py` |
| Certificate converted any exception into a design verdict; `except Exception: pass` on PASS path | critical | broad exception handling | `8d61da35` | `test_certificate_failclosed.py` |
| Two `CompileRequest`/`migrate_design` definitions; older shadowed canonical | high | reclamation duplicate `a5b806fe` | `8c32ccc2` | `test_design_intent_identity.py` |
| Clock parse through binary float lost Hz above 2^53 | high | `float(str(text))` | `e7a85911` | `test_clock_parsing_exact.py` |
| `_validate_legacy_v1` called but undefined (NameError on legacy evidence) | high | reclamation dropped the function | `facf645b` | `test_evidence_admissibility.py` |
| Evidence accepted impossible documents (unknown/contradictory fidelity/transport) | high | content-only validation | `facf645b` | `test_evidence_admissibility.py` |
| Second compile authority `application/compile.py` reachable | high | unremoved legacy surface | `9eb7c2e6` | `test_application_service.py` |

Historical scientific findings F-0001 and F-0004 are FIXED in
`validation/FINDINGS.md`; F-0002 ACCEPTED.

## 5. Remaining limitations

- P0.5 single producer-qualification admission rule not yet centralized.
- P0.6 no build-time provenance manifest (ambient git HEAD only).
- P0.7–P0.10, P0.12, P0.14 not closed/verified.
- `application/results.py` still persists RT-vocabulary resources.
- Run directories are timestamped, not content-addressed/atomic.
- No clean-clone qualification has been run.
- Report files embed ephemeral scratch paths.
- `bash third_party/ramulator2/build.sh` fails silently (must use `./build.sh`).

## 6. Schema / version matrix

See `SCHEMA-COMPATIBILITY.md` (owed). Version constants inventoried in
`AUTHORITY-MAP.md`; a formal matrix is not yet written.

## 7. Engine qualification matrix

| backend | role | independence | numerical validity |
|---------|------|--------------|--------------------|
| Embedded BookSim | canonical network execution engine | engine under test | qualified (F-0001 fixed) |
| Standalone BookSim | shared-engine differential | semi-independent | qualified |
| RTL / Verilator | independent execution engine | independent within RTL domain | established (R0 self-check) |
| Ramulator | memory engine / integration | independent | established (16/16) |
| ASTRA-Sim | runtime/integration | shares BookSim engine (not independent) | **NOT_ESTABLISHED** |

The five categories are NOT "five independent engines".

## 8. B4 results by independence category

72/72 checks exact, 0 quarantined. Independent oracle checks
(`hand_calculated`, ring oracle), semi-independent shared-engine
(`standalone_booksim`), independent execution engines (RTL, Ramulator),
and ASTRA liveness (numerical validity excluded). Scope: network-level
ring semantics only; chunk ownership is not modeled.

## 9. Full regression results

- Fast DSE tier: `3458 passed, 13 skipped, 0 failed` (103 s).
- Validation pytest: `16 passed` (306 s).
- Validation harness: 72/72 exact.
- Live-backend tier: 160 tests deselected from the fast tier; not yet run
  as a timed release job.

## 10. Failure-injection results

Not implemented (`tests/production/test_failure_injection.py` owed).

## 11. Concurrency results

Not implemented.

## 12. Clean-clone results

Not run. This is a release blocker.

## 13. Performance / scale envelope

Not measured (`SUPPORTED-LIMITS.md` owed).

## 14. Security review

Not performed (`THREAT-MODEL.md` owed).

## 15. Reproducibility proof

Partial: source-only build of BookSim/ASTRA/Ramulator works; no manifest,
no lockfile, no container-qualified clean clone. Owed.

## 16. Known unsupported domains

- ASTRA numerical comparison (NOT_ESTABLISHED).
- Reduce-scatter/all-gather chunk ownership/rotation (not modeled).
- Injection faster than one packet per cycle (trace model limit).

## 17. Dirty-tree status

Clean at the time of writing.

## 18. Branch status

Historical branches untouched (no cleanup performed). `main` untouched.
`prod/production-readiness` tracks no upstream; push is a human decision.

## 19. Release decision

**NOT READY.** Open release-critical items: P0.5, P0.6, P0.7–P0.10,
P0.11, P0.12, P0.14, failure injection, concurrency, clean-clone
qualification, resource envelopes, security review, and schema/API
freezes.
