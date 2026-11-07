# GEC MECS native RTL slice

This directory implements a **shared-channel primitive only**: one transmitter, one channel, and K passive taps. It is not a GEC router, fabric generator, route decoder, VC allocator, or verified integration into the BookSim-derived fabric. The RTL interface supplies the already-resolved tap selector. This boundary is intentional because full router/fabric integration is not established in this checkout.

## Semantics and source basis

The topology model in `dse/veritx_dse/model/topology_artifact.py` materializes GEC MECS links as shared links, never point-to-point channels. Its GEC model and `dse/veritx_dse/model/gec_mecs_route.py` preserve GEC's dimension/group wire and ordered tap model. BookSim's `third_party/booksim2/src/networks/gec.cpp` builds `MultiDropChannel`s and stamps a drop/tap index in `dor_gec`. This RTL captures only the channel-side transfer contract, not that route calculation.

- There is one `tx_*` driver for a shared payload bus and K passive taps.
- A zero multicast bitmap selects exactly `1 << tx_dst_idx` (when in range).
- A nonzero multicast bitmap selects exactly its set bits and overrides `tx_dst_idx`.
- Admission is all-or-nothing: `tx_credit_ok` is true only when every selected tap has credit. Unselected credits are masked. No selected taps means no transfer and vacuous credit-ready.
- On a clock edge, `tap_valid` pulses only for selected taps when `tx_valid && tx_credit_ok`; selected payload registers capture the common payload. A denied or invalid transfer creates no tap-valid pulse.

## Destination index versus bitmap ambiguity

The GEC route/model represents a destination as a tap/drop index, whereas this primitive supports multicast through an explicit bitmap. The available GEC topology/routing source establishes unicast tap indexing, not a normative RTL packet-header convention for combining a destination index and multicast bitmap. This implementation adopts a clear interface-level convention: **zero bitmap means unicast index; nonzero bitmap means bitmap-only selection**. It does not OR the destination index into a nonzero bitmap. Confirm the packet/header contract before integrating this convention into a router.

The Srota RTL drop/row modules were not reused. They implement their own selector expression, including a documented unicast-equality term that remains active during multicast, which conflicts with the exact selector semantics above. See `rtl/srota/README.md` for that recorded hazard.

## Verification

Run `./verify.sh`. It uses a uniquely named `mktemp` directory and cleanup trap, runs directed Icarus simulation, then Verilator lint. The test covers zero/nonzero bitmap, single and multicast payload delivery, each selected tap independently denying the transaction, unselected-credit masking, bitmap precedence, and invalid-cycle no-phantom behavior. This is primitive-level verification, not fabric integration or physical qualification.
