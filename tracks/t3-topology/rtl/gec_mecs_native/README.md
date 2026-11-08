# GEC MECS native RTL slice

This directory contains two bounded pieces of RTL: (1) a shared-channel primitive with explicit selected-tap credits, and (2) a connected, topology-faithful **single-flit unicast** fabric for the pinned `gec_mecs16` preset. The fabric is not the configured BookSim router implementation: it does not implement multi-flit framing, a three-VC allocator/credit pipeline, multicast header semantics, or performance/physical qualification.

## `gec_mecs16` fabric

The connected prototype models the pinned `k=4,c=1,o=1,d=3,num_vcs=3` instance: 16 routers in a 4x4 arrangement, 16 local endpoints, 16 shared row wires plus 16 shared column wires, with three passive destination taps per wire. Taps follow BookSim's ascending peer-coordinate order, excluding the transmitter.

Unicast routing follows `dor_gec`: traverse the row (x) dimension first, then the column (y) dimension. The selected tap/drop identifies the destination coordinate on that shared wire. For this specific preset, the three tap partitions map one-to-one to three reported VC indices. This models the pinned topology's route/drop mapping, not dynamic VC allocation or credit timing.

The implementation uses a single-flit complete-packet contract and one-entry input buffers. It is useful for checking connectivity, route/drop identity, transfers, backpressure, and conservation. It is not a latency/performance comparison or a claim of equivalence to the configured BookSim router.

## Shared-channel primitive and source basis

The topology model in `dse/veritx_dse/model/topology_artifact.py` materializes GEC MECS links as shared links, never point-to-point channels. Its GEC model and `dse/veritx_dse/model/gec_mecs_route.py` preserve GEC's dimension/group wire and ordered tap model. BookSim's `third_party/booksim2/src/networks/gec.cpp` builds `MultiDropChannel`s and stamps a drop/tap index in `dor_gec`.

The standalone primitive exposes an already-resolved tap selector:

- There is one `tx_*` driver for a shared payload bus and K passive taps.
- A zero multicast bitmap selects exactly `1 << tx_dst_idx` (when in range).
- A nonzero multicast bitmap selects exactly its set bits and overrides `tx_dst_idx`.
- Admission is all-or-nothing: `tx_credit_ok` is true only when every selected tap has credit. Unselected credits are masked. No selected taps means no transfer and vacuous credit-ready.
- On a clock edge, `tap_valid` pulses only for selected taps when `tx_valid && tx_credit_ok`; selected payload registers capture the common payload. A denied or invalid transfer creates no tap-valid pulse.

## Destination index versus bitmap ambiguity

The GEC route/model represents a destination as a tap/drop index, whereas the primitive supports multicast through an explicit bitmap. The available GEC topology/routing source establishes unicast tap indexing, not a normative RTL packet-header convention for combining a destination index and multicast bitmap. This implementation adopts a clear interface-level convention: **zero bitmap means unicast index; nonzero bitmap means bitmap-only selection**. It does not OR the destination index into a nonzero bitmap. Confirm the packet/header contract before integrating this convention into a router.

The Srota RTL drop/row modules were not reused. They implement their own selector expression, including a documented unicast-equality term that remains active during multicast, which conflicts with the exact selector semantics above. See `rtl/srota/README.md` for that recorded hazard.

## Verification

Run `./verify.sh`. It uses a uniquely named `mktemp` directory and cleanup trap. It runs the primitive's directed Icarus simulation and Verilator lint, checks the pinned `gec_mecs16` graph and all 256 route pairs, then builds and simulates the connected fabric. Fabric acceptance covers all 256 ordered endpoint pairs, concurrent traffic to one destination, payload/destination conservation, intentional output backpressure with stall checks, and complete drain.

Passing these tests establishes this single-flit unicast prototype and the standalone primitive only. It does not resolve multicast packet-header semantics or establish configured multi-flit/VC behavior, performance, or physical implementation quality.