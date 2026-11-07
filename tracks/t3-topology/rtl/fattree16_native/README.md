# `fattree16_anynet` native RTL prototype

Canonical inputs inspected:
- `configs/fattree16.cfg`: `fattree`, `k=4`, `n=2`, native routing name `nca`, 4 VCs, buffer size 8, packet size 5.
- `configs/supported16/fattree16_anynet/topology.anynet`: 8 router records (0..7), 16 terminals (0..15), and 16 undirected edge/core adjacencies. Router ids 0..3 own four terminals each and connect to every upper switch 4..7. Each upper router connects back to all four edge routers.
- The family materializer's `fat_tree_graph(switch_radix=4, level_count=2)` rule yields `per_tier=4`, 8 routers, and lower `l` connects to upper `4+((l+j)%4)` for j=0..3. The supported AnyNet projection has the same complete-bipartite edge/core graph. Edges have unit latency in that artifact.
- `supported16/fattree16_anynet/config.cfg` names AnyNet `min`, not native `nca`; the pinned AnyNet is the explicit graph + minimum-hop routing. On this two-tier graph every inter-edge route has two links and the chosen middle switch may be any of four. This RTL uses a deterministic valid choice `upper = 4 + ((src_leaf + dst_leaf) % 4)`.

Each accepted flit is one complete packet. Multi-flit packet framing, wormhole behavior, VC allocation, and the native config's 4-VC/8-buffer/5-flit simulation contract are not implemented.

**Current acceptance blocker:** `fattree16_native.sv` is not yet a complete connected terminal fabric. The attempted router port mapping exposed that the AnyNet artifact has four endpoint attachments plus four router links on each edge switch, while the current RTL router model has only four transit ports. `verify.sh` currently builds but fails simulation with `missing pair 0->0`; do not treat this prototype as passing. A sound next iteration must model independently the four local terminal lanes and four transit lanes per edge router, and derive exact output route choices from the canonical AnyNet `min` semantics before rerunning all-pairs.

`verify.sh` uses a unique `mktemp` scratch directory and scoped cleanup.
