# Chipyard RTL source — all 14 topologies

Source delivery only. Exporting this bundle does **not** run sbt, Java,
Verilator, lint, simulation or hardware compilation.

| Target | Native RTL exporter |
|---|---|
| Mesh | `CatalogRtlMeshExport` |
| Torus | `CatalogRtlTorusExport` |
| Concentrated mesh | `CatalogRtlCmeshExport` |
| Ring | `CatalogRtlRingExport` |
| GEC MECS | `CatalogRtlGecMecsExport` |
| Fly / butterfly | `CatalogRtlFly64Export` |
| QTree | `CatalogRtlQTreeExport` |
| Tree4 | `CatalogRtlTree4Export` |
| Flatfly | `CatalogRtlFlatFlyExport` |
| SROTA | `CatalogRtlSrotaExport` |
| GEC hybrid | `CatalogRtlHybridExport` |
| Fat-tree | `CatalogRtlFattreeExport` |
| DragonflyNew | `CatalogRtlDragonflyExport` |
| KNCube | `CatalogRtlKNCubeExport` |

`AllTopologyRtlExport` dispatches to these actual family-specific implementations.
It never substitutes the product's generic 2-VC router. KNCube adds configurable
k-ary n-dimensional mesh/torus wiring and dimension-ordered routing with
per-dimension, per-direction dateline VC phases.

## Existing Chipyard setup

The source archive includes the complete configured Constellation source tree,
resources, its BSD license, the dispatcher and the KNCube implementation. It
uses the existing Chipyard dependencies; it is not a standalone sbt project.

The operator can later configure the `constellation` project in the existing
Chipyard sbt session, replacing `BUNDLE` with the extracted absolute directory:

```text
project constellation
set Compile / unmanagedSourceDirectories := Seq(file("BUNDLE/scala"))
set Compile / unmanagedResourceDirectories := Seq(file("BUNDLE/resources"))
```

These commands are **documentation, not executed by source export**. Any later
heavy execution must use the existing private capped runner and its ownership
preflight. Do not launch sbt from the gateway worker.

The dispatcher takes a native target ID and a **new** output directory:

```text
runMain constellation.veritx.AllTopologyRtlExport --list
runMain constellation.veritx.AllTopologyRtlExport mesh8x8 /fresh/output/mesh
runMain constellation.veritx.AllTopologyRtlExport kncube /fresh/output/cube 4 3 true 128 8
```

Canonical IDs are `mesh8x8`, `torus8x8`, `cmesh`, `ring`, `gec_mecs`, `fly64`,
`qtree`, `tree4`, `flatfly`, `srota8x8`, `gec_hybrid`, `fattree`,
`dragonflynew`, `kncube`. Each family retains its own native profile and checks.
Extra arguments are forwarded unchanged to that exporter. The dispatcher does
not resize a workload or infer that a research profile matches a project.

## Boundaries

- All 14 are source-delivery targets, including formerly optional DragonflyNew
  and non-target KNCube. This does not rewrite the historical twelve-family
  qualification matrix.
- `standalone-check/` is a local unit-test harness for the router and policy
  sources. It is not part of the exported bundle and is not a Chipyard build.
- Native fixed profiles are not arbitrary compiled-project emitters. Their
  packet formats, routing laws, VC policies and shared-resource treatments are
  not interchangeable. Inspect the family source and pinned parameters.
- KNCube is new source, not previously compiled or qualified.
- Existing SROTA connected tests failed. Bundling their source is not a fix or
  a qualification result.
- GEC/SROTA tap-expanded research lowering is not electrical shared-wire or
  cycle-accurate parity evidence.
- Archives record per-file hashes and `NOT_RUN` generation/lint/simulation.
  Presence, source delivery and hardware qualification remain separate.

## Parameterized project contracts

`CompiledFabricPreview.scala` is the topology-independent physical fabric core.
`product/chipyard_fabric.py` exports an existing compiled bundle into exact
resource lists, endpoint maps, packet fields, route alternatives and VC masks.
It does not choose a fixed research geometry, infer shortest paths, or expand
one shared resource into independent per-tap links.

The revision-specific archive includes `SelectedFabric.scala`, this core and a
SHA-bound `resources/selected-fabric.bin`. Route tables are data resources,
not enormous generated JVM initializers. The injection interface carries a
flit and an explicit index among the recorded route alternatives. The core
retains an allowed incoming VC or chooses the lowest recorded legal VC.
This source-routed SINGLE-flit preview is not a native adaptive selector or a
credit/iSLIP router. See `RTL-PARAMETERIZED-FABRIC-SOURCE.md` in the repository
for its exact limits. No tools have been run for it.

Future normal revision creation freezes inputs from the already available
compiler bundle. The source download endpoint never starts or reruns compilation;
old revisions without that snapshot receive an explicit refusal.

## Selected GEC contract experiment

`CompiledGecPreview.scala`, `chipyard_gec.py` and `make_testbench.py` are a
separate selected-contract preview experiment. They preserve the exported
physical shared resources, packet fields and deterministic route bindings, but
use ready/valid, round-robin and per-router VC queues.

`CompiledGecCreditPreview.scala` is a separate experimental top that binds the
same frozen GEC-MECS contract to `CreditRouter` instances and preserves the
compiled VC, router timing, wire-latency and credit-return settings. It uses a
static deterministic route table, not an adaptive selector, and raw-flit
endpoints: no AXI/CHI/TileLink adapters, ordering, CDC, or electrical shared-
wire implementation is included. The experiment is not yet qualified and is
not the normal ProductService source-archive path or a replacement for the
fourteen native exporters above. Source delivery alone authorizes no build.
