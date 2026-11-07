# Topology RTL Completion Matrix

**Status checked:** 2026-11-07  
**Purpose:** Track family-faithful RTL, not merely whether a family has a graph model or generic RTL preview.

## Acceptance rule

A family is complete only when emitted or maintained RTL preserves its topology's physical connectivity, endpoint attachment/injection/ejection semantics, routing law, channel and VC behavior, and flow-control contract, and passes an end-to-end RTL simulation with packet/flit conservation, destination correctness, and drain. Lint, a route-table proof, a model/backend run, or a generic point-to-point lowering is useful evidence but is not family RTL acceptance. Performance comparisons additionally require identical traffic and an explicit resource/cost accounting.

## Current evidence

- The product preview emitter (`scripts/rtlgen/gen_rtl.py`, `dse/veritx_dse/product/rtl_export.py`) emits 64-bit, two-VC free/escape routers over connected reciprocal point-to-point graphs. Its own manifest states that family routing law, compiler controls, endpoint adaptation, and shared-wire semantics are not generally realized.
- Research graph RTL prototypes exist for mesh4, torus4, ring8, flatfly k=4/n=2, and GEC Express k=4. They normalize routing and port numbering to that emitter. An identical 64-packet trace passed on mesh4, torus4, flatfly and GEC Express: each delivered 256/256 flits with no wrong destinations or outstanding traffic. This demonstrates the graph bridge, not those families' native RTL.
- `rtl/t3/` contains retained mesh-derived 2D/3D RTL, but its README records multicast corner failures for the 2D design, calls 3D functional-only, and marks 4D incomplete/stub. It is not blanket acceptance evidence for the catalog.
- `rtl/srota/` has extracted routing, allocator, credit, side-buffer, drop-cell, and row/column channel primitives. Its local lint/directed suite passes, including 11 shared-channel checks, but `srota_top` is a one-router smoke wrapper, not a connected KxK fabric.
- The family registry includes 20 identities. Registry stages such as MATERIALIZABLE, ROUTABLE, or EXECUTABLE refer to model/backend capabilities, not RTL completion.

## Family-by-family RTL acceptance

| Registry family | RTL-faithful status | Semantics that acceptance must preserve | Required end-to-end evidence |
|---|---|---|---|
| mesh | Partial research RTL; generic preview passes graph trace | Mesh adjacency, endpoint seats, declared width/VC/flow-control and intended routing law | Full mesh packet simulation and conservation, then equivalence against intended traffic contract |
| torus | Generic graph preview only | Wrap links plus torus routing/deadlock handling, including dateline/VC assignment | Wrap-link traversal, route correctness, deadlock-safe VC use and drain |
| concentrated_mesh | No catalog-faithful RTL demonstrated | Multiple terminals per router, exact seat mapping, mesh routing and endpoint arbitration | Inject/eject at every seat, contention/backpressure, conservation |
| fat_tree | No catalog-faithful RTL demonstrated | Exact internal/leaf router count, radix, terminal placement and up/down or NCA routing | All source/destination pairs, contention, routing legality and drain |
| gec mesh | No separate family RTL; graph preview collapses to mesh | Must match the selected GEC mesh mode's exact materialized graph | Exact adjacency/port checks plus packet simulation |
| gec_express | Generic graph preview only | Express point-to-point channels, channel identity and intended route policy | Exercise every express channel, compare next hops and prove conservation |
| gec_mecs | No integrated shared-channel RTL | One transmitter with multiple passive taps, selected-drop credits, multicast acceptance and shared-resource routing | All-or-nothing credit tests, tap acceptance/multicast checks, shared-wire congestion and full traffic drain |
| gec_hybrid | No integrated hybrid RTL | Runtime choice between mesh and MECS, preserving common resource identity and VC/routing rules | Exercise both choices under shared contention, transition safety and conservation |
| srota | Primitive RTL only; no connected fabric | Concentrated mesh plus row/column MECS, route-shape policy, allocator, credit, side-buffer and multicast semantics | Connected multi-router fabric under each enabled path shape, backpressure, end-to-end packets and deadlock checks |
| flatfly | Generic graph preview only | Native k-ary n-fly adjacency, port law and destination routing | Native route differential over full router/terminal pairs plus packet simulation |
| ring_native | Generic ring8 graph prototype only | 64-router wrap, fixed +/- port law, dateline VC halves, terminal map | Full 64-node route coverage and RTL traffic including wrap and antipodal paths |
| tree4_native | No family RTL demonstrated | 28-router topology, four roots/eight middles/sixteen leaves, leaf seats and legal upward choice union | Every router/terminal route choice, climb/descend and packet delivery |
| fly_native | No family RTL demonstrated | 48-router stages, 128 directed links, 64 terminals with distinct injection and ejection routers | Stage-by-stage destination-tag routing and asymmetric endpoint injection/ejection checks |
| qtree_native | No family RTL demonstrated | 21-router/40-channel native hierarchy, leaf terminal placement and NCA routing | Full router-terminal next-hop comparison and packet simulation |
| qtree (structured) | No family-faithful RTL demonstrated | This structured family is not interchangeable with qtree_native | Its own exact adjacency, terminal map and NCA validation |
| tree4 (structured) | No family-faithful RTL demonstrated | Balanced single-root tree, distinct from tree4_native's multi-root choice topology | Its own exact adjacency, endpoint and route validation |
| ring (fixture) | Test fixture only; not a user topology target | Preserve fixture identity; do not conflate with ring_native | No product-family acceptance claim |
| custom | Generic graph preview only for supported reciprocal point-to-point subset | Exact graph edges; any unsupported directions, endpoint multiplicity or shared resources must refuse | Adjacency equivalence plus traffic simulation; explicit refusal tests outside subset |
| gec (aggregate) | Not a single RTL architecture | Resolve to a concrete GEC subfamily; never infer one implementation from aggregate identity | Accept the selected subfamily, not this aggregate label |
| flattened_butterfly | No canonical materializer in registry | Separate from native BookSim fly and from a generic custom graph | First define canonical graph/endpoint/routing contract, then RTL acceptance |
| dragonfly | No canonical materializer in registry | Group/global-link semantics and terminal placement | First define canonical contract, then RTL acceptance |

## Work order

1. Establish shared router and endpoint contracts, then complete the simpler point-to-point families with their native routing: mesh, torus, ring, flatfly, GEC Express.
2. Add endpoint-structure families: concentrated mesh, fat-tree, QTree, Tree4, Fly.
3. Integrate shared resources: GEC MECS and hybrid, then connect and qualify the complete SROTA fabric.
4. Keep unsupported or under-specified cases as explicit typed refusals. Do not fill contract gaps by guessing.

## Known specification blocker

TOPO-003's MECS channel credit mask selects bitmap targets when the multicast bitmap is nonzero. Its drop match expression is destination-index equality OR bitmap membership. The reviewed ROUTE-001/VC-002/TOPO-003 text does not explicitly require the destination index to be included in the multicast bitmap. The local SROTA README records this hazard. Preserve the literal extracted RTL until the architecture contract resolves the mismatch; add tests for both the specified expression and the chosen resolution once agreed.

## Completion status

**The user's all-topology RTL goal is not complete.** Current passes cover graph previews and SROTA primitives only. Every authorable user/research family still lacks the stated family-faithful RTL acceptance evidence. Fixture/aggregate entries remain explicitly non-target identities, and flattened_butterfly/dragonfly first need canonical materialization contracts.
