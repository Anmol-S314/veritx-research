# SROTA native fabric increment

This increment deliberately stops short of fabric wiring. Inspection of the existing `srota_router_d` interface shows a generic `P=2*C+8` port vector, but there is no unambiguous physical mapping from that preview port map to cardinal neighbor ports or to the row/column shared-channel driver/taps. More importantly, the router does not implement MECS fanout, multicast packet semantics, or route-stage allocation. Connecting row/column channel primitives directly would require inventing those behaviors and could route a packet incorrectly.

## Existing contracts observed

- `srota_route_pkg.sv`: preview header offsets, `P=2*C+8` interpretation explicitly marked open (VC-R5), `ROW_FIRST`, `COLUMN_FIRST`, and `VALIANT_L1` shapes.
- `srota_route_compute.sv`: row-first/Valiant leg 1 selects row express output until X matches then column output; column-first selects column until Y matches then row output; local ejection uses destination tile.
- `srota_router_d.sv`: per-input held flits and generic output arbitration, but its own header documents no packet/VC state, multicast, or MECS fanout.
- `srota_mecs_row.sv` / `srota_mecs_col.sv`: single-driver shared channel with bitmap/unicast tap selection and all-selected-credit gating. The documented multicast match hazard means we must not infer destination encoding beyond the existing bitmap contract.

## Typed blocker

`SROTA_FABRIC_BLOCKER_MECS_ROUTER_BINDING`: No canonical connection is safe until the architecture specifies (1) router-port to mesh/MECS endpoint mapping, (2) how route-compute output port IDs identify a particular row/column channel and tap, (3) packet-level unicast destination and multicast bitmap ownership/encoding at each channel driver, and (4) return-credit ownership and packet completion/ejection behavior across routers. Consequently this directory contains no guessed fabric or claimed end-to-end packet test. Once these contracts are resolved, a minimal 2x2 concentrated mesh and shared row/column channels can be wired and tested.

No timing, performance, deadlock-freedom, or product qualification claim is made.
