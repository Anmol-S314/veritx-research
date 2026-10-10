# ASTRA GEC-hybrid integration — 2026-10-09

## Root cause correction

The earlier diagnosis that ASTRA fundamentally lacked the canonical fork was
incomplete. Its CMake cache already selected
`BOOKSIM2_SRC_DIR=third_party/booksim2`, and both frontend headers and the
BookSim2Fabric library use that path. The installed binary was stale (built
October 5). The earlier Python config-field gate additionally read ASTRA's
**unused nested copy**, incorrectly rejecting a field the configured canonical
fork supports.

The existing build was rebuilt against the current canonical fork, without
porting or deleting the hybrid observation mechanism. The config-field and
routing-alias checks now use the canonical source selected by the qualified
build, not the nested fallback tree. Build-time producer provenance was
regenerated and `assert_pinned_producer` accepts the new runtime. No dirty-source
or evidence guard was bypassed; no branches or commits were created.

- Old ASTRA SHA256: `2eb2c3238fccca0f36f2fcac804487945df4d526d8e12a8d9b301ce14e46fca8`
- New ASTRA SHA256: `b130a834c23ec4c08a363fe03c2aee359b9f22c56cae2737eff0a70f6c38f022`
- Build log: `/tmp/veritx-astra-rebuild.log`
- Old binary and manifest: `runs/astra-hybrid-integration/20261009/rollback/`
- Acceptance inputs, plans, simulator files and evidence:
  `runs/astra-hybrid-integration/20261009/acceptance/`
- Regression: `tests/test_astra_hybrid_integration.py`

Build commands:

```sh
JOBS=2 bash third_party/astra-sim/build/astra_booksim2/build.sh
python scripts/write_build_manifest.py \
  third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2 \
  --recipe-version astra-sim+booksim2/v1 \
  --source-path third_party/astra-sim --source-path third_party/booksim2
```

Restoring the archived binary **and matching manifest** is the rollback. A
rollback restores the older parser too; it must not be claimed to support the
new hybrid field. Historical runs/evidence were not rewritten.

## Verified cases

Every row completed all four selected analyses: NETWORK_COMPLETION,
SYSTEM_MAKESPAN, COMMUNICATION_EXPOSURE and PER_RANK_COMPLETION. No observations
were disabled to pass the GEC-hybrid parser.

| Design | Endpoints / routers | TP | Network cycles | System makespan / exposure cycles |
|---|---|---:|---:|---:|
| Exact user revision r04 (Llama-3.1-8B, GEC-hybrid, 64-bit links) | 16 / 16 | 8 | 2600 | 3875 |
| Llama request copy with 64 endpoints, original TP/workload retained | 64 / 16 | 8 | 2628 | 3740 |
| GEC-hybrid, all 64 endpoints active | 64 / 16 | 64 | 8085 | 4041 |
| SROTA, all 64 endpoints active | 64 / 16 | 64 | 24266 | 12324 |

These are different workload/projection measurements, not additive durations
or end-to-end model runtimes. The first 64-endpoint copy leaves 56 endpoints
idle; the separate TP64 test exercises all 64 ranks. Keeping those two cases
separate avoids claiming full-load coverage from a TP8 trace.

## Studio publication

The original live draft was preserved byte-for-byte. Re-evaluation of r04
created fresh evidence; historical FAILED/PARTIAL runs were not overwritten.

- Repaired r04 run: `01a11d0d-aa17-7b30-b605-3b3dc564e5db` — EVALUATED, 4/4.
- Separate 64-endpoint TP8 copy: project `p-35a65d7b80be`, revision
  `p-35a65d7b80be-r01`, run `01a11d0d-dec2-76c4-8db6-aa4b96fcfdce` —
  EVALUATED, 4/4. The source project was not resized.

## Node-count scope

64 endpoints on GEC-hybrid or SROTA are represented here by a 4×4 router grid
with concentration 4. This is **not 64 routers**. SROTA with 64 routers and
concentration 2 has 128 endpoints (previous sweep).

Support is not unrestricted 'any node count': grid/radix geometry, capacity,
collective payload divisibility, VC budget, routing/certificate constraints,
ABI and runtime budgets still apply. In particular GEC-hybrid 8×8 routers
with d=7 needs 14 VCs, beyond the current eight-VC model limit. We did not
silently reshape it, increase the limit globally, flatten classes or substitute
routing merely to make a run pass.

## Remaining provenance limitation

The field check is derived from the configured build's source, not a runtime
self-description API. It requires rebuilding and updating the producer manifest
when parser/routing sources change. The producer binary/digest checks and actual
execution regressions remain necessary; readable source alone does not prove
that a stale or arbitrary externally supplied runtime implements those fields.
