# Native fly RTL prototype

This directory contains a connected ready/valid implementation of the canonical native BookSim fly, pinned to `k=4`, `n=3`.

- Exactly 48 routers, numbered `stage * 16 + address`, and 128 explicit directed interstage channels.
- Each stage-0 router has four terminal ingress ports. Terminal `t` injects at router `t/4`, port `t%4`.
- Each stage-2 router has four terminal egress ports. Terminal `t` ejects at router `32+t/4`, port `t%4`. Injection and ejection are distinct attachment locations.
- Port connectivity follows `fly_net.py`'s inverse `_InChannel` construction. Stage-0 output `p` enters stage-1 port `zero`; stage-1 output `p` enters stage-2 port `zero`.
- Routing is fixed by destination tag: stage 0 uses `(dest/4)/4`, stage 1 uses `(dest/4)%4` only in its matching digit class, and stage 2 selects `dest%4` at the matching egress router.
- Each router input has one ready/valid storage slot; output conflicts use round-robin arbitration.

## Validation

Run `./verify.sh`. The runner builds Verilator output in a temporary directory and removes it afterward. The self-checking test sends all 4,096 ordered terminal source/destination pairs, with all sources offering traffic simultaneously, deterministic periodic egress backpressure, payload/destination checks, exact accept/delivery accounting, duplicate/loss detection, and drain.

## Protocol slice and limitations

This implementation deliberately specifies a **one-flit packet protocol**: each accepted flit is a complete packet, and its destination field is retained end-to-end. It is not a BookSim-microarchitecture-compatible multi-flit router. There are no head/body/tail semantics, VC allocation, packet reservation, configurable buffer depths, or performance/PPA claims. It implements the canonical topology, port law, endpoint map, and fixed destination-tag route, with a minimal ready/valid router/arbiter sufficient for this slice.
