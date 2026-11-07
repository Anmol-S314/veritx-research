# Native ring RTL prototype

This directory contains a standalone 64-router credit-aware ring for the `ring_native` family. Its topology and route rules follow the canonical registry/model contract:

- 64 routers and 64 attached terminals, with wraparound `+1` and `-1` neighbors.
- Native output port 0 sends to `router+1`; port 1 sends to `router-1`; port 2 is local injection/ejection.
- Minimal direction routing, with either direction legal for an even-ring antipode. The integrated router uses the packet's VC half to select one legal direction there.
- Two independent one-entry input buffers per physical input, one per VC. VC half is fixed at injection as `source > destination` and carried on every link.
- One flit can be transferred on each output per cycle when its downstream VC has room. Per-VC ready signals act as credits, so arbitration selects only a VC that can advance and one blocked VC does not hide a ready VC.

## Validation

Run `bash verify.sh` from this directory. It performs:

1. Verilator lint on the route block and connected fabric.
2. Exhaustive RTL route simulation across all 4,096 router/destination pairs, both antipode tie choices, and the VC-half rule (8,192 checks).
3. A connected 64-router simulation sending exactly one 32-bit flit-packet for every ordered source/destination pair, including local delivery. It checks accepted/delivered conservation, payload identity, correct terminal, duplicate/loss detection, deterministic endpoint backpressure, and drain.

Latest run passed: `packets=4096 accepted=4096 cycles=2949`; route coverage passed all 8,192 cases.

## Scope and limitations

This is topology-faithful RTL for the declared **single-flit packet** protocol, not a drop-in implementation of the BookSim/ESP router microarchitecture. Each input VC has depth one. There are no multi-flit head/body/tail packets, packet-level VC reservation, booksim-matched arbitration/buffer timing, or PPA claims. `out_valid` is credit-qualified by the selected VC's downstream readiness, rather than a fully decoupled ready/valid source that holds valid and payload stable through arbitrary stalls. An integration requiring conventional decoupled ready/valid must add an output holding stage or bind a different specified interface contract. Do not use its cycle count as a VERITX-vs-ESP performance result. A later integration must first bind the canonical flit and buffer/allocator/handshake contract, then rerun the same all-pairs traffic against that contract.
