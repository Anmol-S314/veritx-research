# Loom production-candidate release checklist

**Release:** __________  **Commit:** __________  **Candidate artifact(s):** __________
**Release owner:** __________  **Date:** __________

> A checked box requires a link to reproducible evidence. An unchecked item blocks release unless the release owner records an explicit, approved scope exception. `N/A` is not a pass. Do not describe browser/fixture output as a local-engine or measured result.

## Build and test

- [ ] Clean, pinned-dependency install succeeds on release build image; toolchain versions recorded.
- [ ] Typecheck and production build pass; warnings reviewed and disposition recorded.
- [ ] Full unit/contract/integration suites pass; exact command, totals, skipped tests and CI run linked.
- [ ] Required UI E2E flows pass on the candidate artifact; environment, test report and screenshots/logs linked.
- [ ] Performance budgets are approved before measurement; target-size graph, matrix and trace benchmarks meet them on named reference hardware. Raw measurements and harness version attached.
- [ ] Failure-injection and recovery tests pass (corrupt input, missing/incompatible engine, permissions, disk pressure, crash, failed update as applicable).

## Product truth, provenance and scope

- [ ] Mock, estimate, external/measured and backend-produced values are visibly distinguished; provenance audit linked.
- [ ] Unsupported engine/backend/topology/workload combinations refuse with stable, actionable reasons; no unsupported run is represented as completed.
- [ ] Run artifacts carry project fingerprint, engine/UI versions, manifest, summary and log/trace hashes; reproducibility evidence linked.
- [ ] Local/offline behavior, required network features, and data transmitted are documented and verified.
- [ ] Known limitations, supported platforms/backends, incompatible changes and remaining tracker exceptions are listed in release notes.

## Security, privacy and licensing

- [ ] Complete release dependency inventory/SBOM covers UI, desktop shell, bundled tools and embedded assets.
- [ ] Vulnerability scans cover the complete artifact dependency graph; every critical/high finding is fixed or explicitly accepted by named approver with expiry/rationale.
- [ ] Filesystem, import/export, archive extraction and external-command boundaries have security test evidence; no unreviewed path traversal or shell interpolation.
- [ ] License/entitlement failure cannot prevent project recovery/export; offline and execution-gating behavior is tested.
- [ ] Logs/support bundles have bounded retention and reviewed redaction; privacy/network settings match shipped behavior.
- [ ] Signing keys, updater metadata/channels and signatures are independently verified; no dev/beta/stable key mixing.

## Packaging and clean-machine verification

- [ ] Linux package installs, launches, opens shipped sample, health-checks, exercises supported local workflow, and uninstalls on a clean supported machine.
- [ ] Windows installer passes the same clean-machine checks on each supported Windows target.
- [ ] macOS package passes signing/notarization and clean-machine checks on each supported macOS target.
- [ ] Upgrade, interrupted/failed update rollback, and prior-version launch are verified without project-data loss.
- [ ] Installation/uninstallation instructions and prerequisites match observed clean-machine behavior.

## Documentation and artifact integrity

- [ ] Quickstart and workflow guides match shipped behavior and distinguish estimates/mock data from real tool/backend results.
- [ ] Project/trace/summary/run-manifest schemas and engine protocol references are versioned and tested against shipped formats.
- [ ] Troubleshooting covers engine, corrupt input/trace, permissions, licensing, offline use and update recovery.
- [ ] Third-party license notices are included and checked against the shipped dependency inventory.
- [ ] Each final artifact has SHA-256 (or stronger approved digest); hashes, signatures, SBOM, notices, release notes and test evidence are archived together.
- [ ] Candidate is immutable after verification; any rebuild/change invalidates prior signatures, hashes and test evidence and requires re-check.

## Release gate sign-off

Record tracker gate evidence/status in the authoritative tracker; this checklist is not a substitute for updating it.

| Gate | Evidence link / exception | Reviewer | Result |
|---|---|---|---|
| G01–G14 (contracts, migration, identity, state, editor, catalog, access, physical/workload truth, refusal, mock isolation, provenance, replay, crash recovery) |  |  | Pending |
| G15–G24 (offline, performance, security, license, updater, dependencies, install, docs) |  |  | Pending |
| G25 P0 closure |  |  | Pending |
| G26 E2E closure |  |  | Pending |

**Release decision:** ☐ GO  ☐ NO-GO  **Approver:** __________  **Date:** __________

**Unresolved exceptions / known issues:**

- 
