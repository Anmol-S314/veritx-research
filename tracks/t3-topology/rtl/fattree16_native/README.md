# `fattree16_anynet` native RTL prototype

Canonical inputs inspected:
- `configs/fattree16.cfg`: `fattree`, `k=4`, `n=2`, native routing name `nca`, 4 VCs, buffer size 8, packet size 5.
- `configs/supported16/fattree16_anynet/topology.anynet`: 8 router records (0..7), 16 terminals (0..15), and 16 undirected edge/core adjacencies. Router ids 0..3 own four terminals each and connect to every upper switch 4..7. Each upper router connects back to all four edge routers.
- The family materializer's `fat_tree_graph(switch_radix=4, level_count=2)` rule yields `per_tier=4`, 8 routers, and lower `l` connects to upper `4+((l+j)%4)` for j=0..3. The supported AnyNet projection has the same complete-bipartite edge/core graph. Edges have unit latency in that artifact.
- `supported16/fattree16_anynet/config.cfg` names AnyNet `min`, not native `nca`; the pinned AnyNet is the explicit graph + minimum-hop routing. On this two-tier graph every inter-edge route has two links and the chosen middle switch may be any of four. This RTL uses a deterministic valid choice `upper = 4 + ((src_leaf + dst_leaf) % 4)`.

Each accepted flit is one complete packet. Multi-flit packet framing, wormhole behavior, VC allocation, and the native config's 4-VC/8-buffer/5-flit simulation contract are not implemented.

The connected prototype uses separate four-seat terminal ports and four transit ports on edge routers, plus four transit ports on upper routers. A wiring defect that indexed upper transit inputs by the lower router's local upper-link port instead of the source edge-router ID was fixed. The ready/valid arbiter also now holds `out_valid` and the selected payload stable while `out_ready` is low. The testbench's earlier uncounted prelude traffic was removed so its conservation and unique-delivery checks cover exactly the all-pairs workload.

Fresh `verify.sh` acceptance passes all 256 ordered one-flit pairs exactly once, with 256 accepted and delivered, 127 observed stalls, complete drain, and 171 cycles. This verifies only the supported `fattree16_anynet` graph with deterministic min-hop routing. It does not verify native `fattree16.cfg` NCA tie-breaking or the full 4-VC/8-buffer/5-flit router contract.
`verify.sh` uses a unique `mktemp` scratch directory and scoped cleanup.
