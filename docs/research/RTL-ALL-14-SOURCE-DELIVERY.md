# All fourteen Chipyard RTL sources

## Scope

Operator correction: all 14 topologies, code only. Do not compile, elaborate,
lint, simulate, build, or launch toolchains. No such commands were run after
this correction. No qualified hardware support is claimed.

## Parameterized project follow-up

`RTL-PARAMETERIZED-FABRIC-SOURCE.md` describes the new compiled-bundle adapter,
parameterized physical-resource/path-replay core, revision-bound source snapshot
and download API. It does not substitute a fixed native profile for an arbitrary
project. No compilation or tests were run for that follow-up either.

## Written

1. `tracks/t3-topology/rtl/chipyard/AllTopologyRtlExport.scala`
   dispatches all fourteen IDs to actual family-specific native exporters,
   refuses unknown IDs and existing output directories, and does not fall back
   to the generic 2-VC product emitter.
2. `CatalogRtlKNCubeExport.scala` adds a parameterized K-ary N-cube
   implementation: dimension geometry, wrapped/non-wrapped neighbors,
   deterministic routing, direction/dateline VC phase, NoC composition and
   inventory. This source is new and uncompiled.
3. `product/chipyard_sources.py` packages the existing full Constellation source
   and resource tree, license, native tests, all fourteen native entry points,
   the dispatcher, and KNCube source/tests. Missing one target refuses the
   archive; a partial thirteen-target export is not labeled complete.
4. Gateway routes: `GET /api/v1/catalog/rtl-sources` and
   `GET /api/v1/catalog/rtl-sources/archive`. They inspect/package source only;
   neither invokes the FabricCompiler, sbt, Java, Verilator or a shell.
5. `FinalDelivery.tsx` offers a separate **Download all 14 sources** link.
   Generated RTL readiness and historical qualification remain unchanged.
6. Source-delivery tests and pure KNCube geometry/routing tests were written,
   not executed, per the no-compilation instruction.

Targets: mesh8x8, torus8x8, cmesh, ring, gec_mecs, fly64, qtree, tree4,
flatfly, srota8x8, gec_hybrid, fattree, dragonflynew, kncube.

## Existing setup and evidence boundaries

Default existing source tree is the preserved
`execution/build/srota-component-fix-1-corrected/candidate-source` workspace.
The operator can configure `VERITX_CHIPYARD_SOURCE_ROOT`. Browser callers cannot
choose filesystem roots. The archive snapshots and hashes the source bytes;
it does not copy build products or dependency caches.

The thirteen existing native exporters retain their pinned research profiles.
This source-delivery integration does not parameterize them against every
arbitrary project or establish simulation-equivalent packet/router semantics.
GEC/SROTA research tap expansion is not proof of shared-wire electrical/cycle
semantics. Previous SROTA connected-test failures remain unresolved. Existing
research matrix labels (12 required + DragonflyNew optional + KNCube former
non-target) are historical qualification policy, not a limit on this 14-target
source delivery.

The earlier selected 81-router GEC experiment remains separate. Its capped
emission failed once at the Scala method-size limit; the source was split into
smaller methods. Its retry was blocked by foreign heavy processes. No generated
RTL or simulation evidence is claimed for it. Do not resume those jobs without
new operator permission.

## Checks

New all-target packaging, dispatcher, KNCube, API and UI changes are UNTESTED.
No build, compiler, lint or simulation was run for these changes.
