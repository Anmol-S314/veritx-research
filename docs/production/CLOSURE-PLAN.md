# VERITX Production Closure Plan

Strict order: close scientific-authority blockers (P0) → freeze B4 (P1) →
durable runs → fault/concurrency → API/schema → reproducible build →
observability/limits → security → CI/clean-clone → seal.

Each item is one reviewable commit with tests. No item depends on a later
item. A `BLOCKER` is release-critical: the seal is refused until closed.

## P0 — scientific-authority blockers (from §5)

| id | item | mandate | status |
|----|------|---------|--------|
| P0.1 | Remove the second compile authority (`application/compile.py`); route `fabric_compiler.py`/`results.py`/`waved_resources.py` through the canonical service; restore `test_application_package_reaches_no_legacy_compiler` | §3, §5 | **DONE** (`9eb7c2e6`, B1) |
| P0.2 | Certificate fail-closed exception discipline + adversarial injection tests | §5.1, §5.2 | **DONE** (`8d61da35`) |
| P0.3 | VC-assignment authoring/persistence contract: dup keys, malformed rows, non-artifact parent, JSON-list shape, artifact_hash | §5.3 | **DONE** (`a0b934b6`) |
| P0.4 | `ScientificBackendEvidence` admissibility: closed vocabularies + cross-field invariants; self-consistent impossible documents recomputed and refused | §5.4 | **DONE** (`facf645b`) |
| P0.5 | One producer-qualification admission rule; no duplicate `reusable` checks at call sites | §5.5 | **DONE** (`978a38ed`, enforced end-to-end + manifest binding in `a274d4b0`) |
| P0.6 | Build-time manifest binding source rev + dirty + binary sha/size + compiler + recipe; execution verifies the binary against it | §5.6 | **DONE** (`43f55d94`, `48152452`); release-build target added |
| P0.7 | Seed identity: rendered → prepared_id → evidence; not overrideable at execution; search vs sim seed distinct | §5.7 | **DONE** (`dc858a29`, tests) |
| P0.8 | Projection closure: rendered keys == required keys; pins exact; missing required field fails | §5.8 | **DONE** (`dc858a29`) |
| P0.9 | BookSim conservation: parse/enforce loaded/injected/delivered packets and flits-injected/accepted; no unexplained `None` | §5.9 | **DONE** (`03e50675`) |
| P0.10 | Executed route realization: destination-aware next-hop observation vs resolved route; refuse to claim equivalence when unobservable | §5.10 | OPEN — honestly `ROUTE_NOT_OBSERVED` (no false claim); implementation owed |
| P0.11 | Resolve `application/results.py` (migrate or mark legacy + remove from production reachability) | §5.11 | **DONE** as option B (`c78e54af`): RT readers marked legacy, not production-reachable, inventory corrected, guard test |
| P0.12 | Authenticated evaluation: remove stale RT vocabulary from canonical code | §5.12 | **DONE** (`5d2a991b`) |
| P0.13 | Exact numeric parsing: no binary float for identity-bearing clock/frequency; test `9007199254740993`, `>2^53` | §5.13 | **DONE** (`e7a85911`) |
| P0.14 | Optimizer edge cases: reject empty guided domains; candidate identity uses full content hash | §5.14 | **DONE** (`85b7e5cf`) |

## P1 — seal B4 as a permanent contract (§6)

| id | item | status |
|----|------|--------|
| P1.1 | Final F-0004 ring repair on the production branch | DONE (base `190d04f1`) |
| P1.2 | Ring oracle exact step labels + exact phase ranges | DONE (`190d04f1`) |
| P1.3 | Scope statement: network-level ring semantics only (no chunk ownership) | DONE (`FINDINGS.md`) |
| P1.4 | Keep pre-F-0004 numbers permanently in `FINDINGS.md` | DONE |
| P1.5 | Run `validation.harness.run --all --mutations --metamorphic --engines --intervention` green from a clean build | **DONE locally** (72/72 exact, 0 quarantined); clean-build re-run owed |

## P2 — durable run bundles (§7)

Commit sequence:
1. `RunBundle` schema + content-addressed atomic write (staging dir +
   atomic rename), `checksums.json` over every scientific input/output.
2. `veritx verify-run <bundle>` — independent inspection, no simulator
   rerun.
3. `veritx reproduce <bundle>` — new execution, science comparison.
4. Crash-safety tests: no partially valid bundle survives a mid-write kill.

## P3 — crash/fault injection (§8)

`tests/production/test_failure_injection.py` covering the full list in
§8: nonzero exit, SIGKILL, hang/timeout, malformed/partial output, missing
route dump, post-qualification binary/config/trace/evidence change, disk
write failure (via the persistence boundary if disk-full is not
injectable), incompatible existing bytes, concurrent identical and
differing runs, interrupted persistence, corrupt/missing manifest, stale
and unsupported schema, directory relocation, read-only destination.

## P4 — concurrency / idempotency (§9)

Prove: two identical evaluations concurrent → no corruption; different
evaluations cannot overwrite; retries give identical scientific identity;
a crash cannot leave a valid-looking incomplete run; atomic finalization.
No timestamps in scientific identity.

## P5 — public API + schema freeze (§10, §11)

Freeze `compile, verify, evaluate, optimize, serve, reproduce, inspect`.
Versioned machine-readable results (`CompileResult`, `VerificationResult`,
`EvaluationResult`, `OptimizationResult`, `ServingResult`, `RunBundle`).
Author `docs/production/API-CONTRACT.md` and
`docs/production/SCHEMA-COMPATIBILITY.md`. Golden migration fixtures.

## P6..P16 — build, fault, security, release

Reproducible container build (`make release-build`), clean-clone
qualification, structured observability, measured resource envelopes,
performance profiling, threat model, service robustness, optimizer
production contract, engine qualification matrix, B4 release gate, test
pyramid, skip inventory, release manifest, branch retirement.

## Immediate next commits (this program, in order)

```text
P0.1  remove the second compile authority            [DONE 9eb7c2e6]
P0.2  certificate fail-closed                        [DONE 8d61da35]
P0.3  VC contract                                    [DONE a0b934b6]
P0.4  evidence admissibility + legacy reader         [DONE facf645b]
P0.5  producer admission rule                        [DONE 978a38ed]
P0.6  build-time provenance manifest                 [DONE 43f55d94]
P0.7  seed identity                                  [DONE dc858a29]
P0.8  projection closure                             [DONE dc858a29]
P0.9  BookSim conservation                           [DONE 03e50675]
P0.11 results.py legacy boundary                     [DONE c78e54af]
P0.12 authenticated evaluation vocabulary            [DONE 5d2a991b]
P0.13 exact clock parsing                            [DONE e7a85911]
P0.14 optimizer empty domain / full identity         [DONE 85b7e5cf]
P0.10 executed route realization                     [OPEN, honest NOT_OBSERVED]
B7    SemanticError taxonomy for boundaries          [DONE ff141c68]
P2    durable run bundles
P3    failure injection
P4    concurrency/idempotency
```

The seal report `docs/production/PRODUCTION-SEAL.md` is written only when
every seal condition in §30 is met. At present the verdict is
**NOT READY** (P0.10 route observation, plus the P2–P17 operational
program and clean-clone qualification).
