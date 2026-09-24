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
| `_validate_legacy_v1` called but undefined (NameError on legacy evidence) | high | reclamation dropped the function | `facf645b` | `test_evidence_admissibility.py` |
| Second compile authority `application/compile.py` reachable | high | unremoved legacy surface | `9eb7c2e6` | `test_application_service.py` |
| No single producer qualification rule; revision/cleanliness unchecked | high | split admission logic | `978a38ed` | `test_evidence_admissibility.py` |
| Build provenance was ambient git HEAD (binary built at A attributed to B) | critical | live `git rev-parse` | `43f55d94` | `test_build_manifest.py` |
| BookSim packet/flit counters unparsed and unenforced (`None`) | high | parser stubs | `03e50675` | `test_booksim_conservation.py` |
| Projection closure only checked missing fields, not undeclared ones | medium | partial closure check | `dc858a29` | `test_projection_closure.py` |
| Candidate identity was a truncated 16-hex hash | medium | `content_id(...)[:16]` | `85b7e5cf` | `test_optimization_identity_exact.py` |
| Empty optimizer domain created an illegal empty-patch candidate | medium | late failure | `85b7e5cf` | `test_optimization_identity_exact.py` |
| Authenticated evaluation read stale RT keys (`execution_transport`/`qualification`) | medium | stale vocabulary | `5d2a991b` | `test_p2_optimization_truth.py` |
| `application/results.py` mixed canonical and RT-vocabulary readers | medium | unmarked legacy | `c78e54af` | `test_results_legacy_boundary.py` |

Historical scientific findings F-0001 and F-0004 are FIXED in
`validation/FINDINGS.md`; F-0002 ACCEPTED.

## 5. Remaining limitations

- P0.10 executed route realization is not implemented; evidence honestly
  records `DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED` (no false equivalence
  claim).
- B7: the semantic-error taxonomy is ValueError-rooted; a programmer
  fault raised as a bare `ValueError` could still be laundered at a
  boundary (the mandate's injected fault types already propagate).
- Run directories are timestamped, not content-addressed/atomic (P2).
- No clean-clone qualification has been run.
- Report files embed ephemeral scratch paths.
- `bash third_party/ramulator2/build.sh` fails silently (use `./build.sh`).
- One timing-sensitive serving test (`test_quiescence_is_bounded_under_a_
  permanent_stderr_flood`) is flaky under load.

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

- Fast DSE tier: `3489 passed, 13 skipped, 0 failed` (102 s).
- Validation pytest: `16 passed` (306 s).
- Validation harness: V01–V10 PASS, mutations M1–M8 CAUGHT, metamorphic
  M1–M8 PASS, engine gates PASS (ASTRA numerical NOT_ESTABLISHED).
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

**NOT READY.** All §5 scientific-authority P0 items are closed except
P0.10 (executed route realization, honestly unobserved) and the B7
residual. The operational program remains open: durable run bundles
(P2), failure injection (P3), concurrency/idempotency (P4), API/schema
freeze (P5), observability/limits, security review, clean-clone
qualification, and the release manifest.
