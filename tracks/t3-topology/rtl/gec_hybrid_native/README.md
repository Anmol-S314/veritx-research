# GEC hybrid RTL assessment: typed blocker

**Outcome: RTL not implemented.** The canonical topology and route law are clear, including the per-hop mesh-versus-MECS choice. However, the repository's pinned supported profile does not pin the exact router buffer capacities/state needed to reproduce the route selector's live credit operands. Implementing a local queue-occupancy heuristic would be an approximation, not evidence that it preserves native resource choice. No pseudo-fabric, ordinary mesh substitute, or generic point-to-point preview is emitted here.

## Blocker ID

`GEC_HYBRID_LIVE_CREDIT_STATE_UNPINNED`

## Evidence inspected

- `tracks/t3-topology/configs/supported16/gec_hybrid16/config.cfg` pins `k=4`, `c=1`, `o=1`, `d=3`, `hybrid=1`, `routing_function=hybrid_gec`, `num_vcs=6`, `router=iq`, and `priority=none`. It does not declare `buf_size` or `vc_buf_size`, which determine IQ router buffering through BookSim's configuration defaults.
- `tracks/t3-topology/dse/veritx_dse/model/gec_hybrid_route.py:29-76` defines the candidate-law shape, six-VC phase/tap partition and legal phase transitions; `:107-161` derives both topology candidates and the exact cost comparison, `mesh_used_credit * mesh_hops < mecs_used_credit`, with ties selecting MECS.
- `tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py:902-936` materializes the union of mesh channels and MECS shared wires, and explicitly says the fabric materializes but does not have a deterministic route table because the choice uses live credit.
- `third_party/booksim2/src/networks/gec.cpp:1031-1046, 1109-1194` defines the native per-hop decision, X-before-Y phase, mesh remaining-distance cost, MECS tap cost, tie behavior, and VC ranges.
- `third_party/booksim2/src/routers/router.hpp:153-156` defines `GetUsedCredit` as occupancy for a selected downstream output buffer/tap. `third_party/booksim2/src/routers/iq_router.cpp:2531-2545` implements it by returning `_NextBuf(o, drop)->Occupancy()` (or aggregating tap occupancy when no drop is specified). This is not simply an arbitrary local input FIFO occupancy signal.

## Why this blocks a faithful prototype now

The topology and comparison equation are sufficient, but the native route's decision depends on the actual next-buffer occupancies for the selected mesh output and selected MECS tap. The checked-in supported config leaves buffer sizing to simulator defaults, while the product-facing candidate model does not bind a runtime `GetUsedCredit` state model to RTL queue depths, credit return timing, or visibility cycle. Picking one-entry FIFOs and calling their occupancy the native credit would invent a new selection trajectory. Since hybrid may re-evaluate this comparison at every router while a dimension remains unresolved, those differences can change both selected physical resources and route length. This is a qualification blocker, not a claim that the GEC hybrid route law is unknown.

## Unblock requirements

1. Pin and document the BookSim IQ router's effective buffer settings for the supported hybrid profile, including global/per-VC capacity and relevant credit pipeline timing.
2. Define the RTL prototype's `GetUsedCredit`-equivalent observable and update/return timing for ordinary mesh output and each MECS tap. Bind each observable to the exact output resource/tap identity, rather than a guessed input queue.
3. Add differential evidence against the native `hybrid_gec` implementation over the selector input tuple `(mesh_credit, mecs_credit, mesh_hops)` and selected output kind/port/tap/VC, including tie cases and nonzero occupancy, before claiming resource-choice fidelity.
4. Then implement the connected mesh + MECS graph from `materialize_gec_hybrid`, and run all-pairs one-flit delivery with contention, backpressure, conservation and complete drain under that pinned credit contract.

No files outside this new assessment directory were changed. No commit was made.
