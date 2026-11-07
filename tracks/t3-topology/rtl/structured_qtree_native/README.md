# structured_qtree_native

Implements the existing structured `qtree` identity from `k_ary_tree_graph(radix=4, tiers=2)`: breadth-first routers 0..20, parent `floor((r-1)/4)`, children `4r+1..4r+4` for routers 0..4, and one endpoint at every router. Ports are children 0..3, parent 4, local endpoint 5. This is deliberately distinct from the native QTree leaf-only terminal placement in `rtl/qtree_native`.

Routing follows the tree's unique path: eject locally when destination equals router ID, descend when destination is a direct child, otherwise route to parent. The protocol is a one-flit complete-packet simplification, not a multi-flit network protocol. No performance claim is made.

Run `./verify.sh` for Verilator lint and an all-pairs test with deterministic egress backpressure, conservation, endpoint identity, and drain checks. The verification runner uses a unique `mktemp` build directory beneath `$JCODE_SCRATCH_DIR` or `~/.jcode/scratch` and removes only that generated directory.
