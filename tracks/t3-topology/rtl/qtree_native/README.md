# qtree_native RTL slice

This directory implements the canonical radix-4, three-level QTree router
shape: router IDs 0 (root), 1..4 (level 1), and 5..20 (level 2 leaves). Every
non-leaf has child ports 0..3 and parent port 4. The fabric connects all 64 canonical terminals, four seats on each of the 16 leaves, using terminal ID `4*leaf+seat`.

Each router has a one-entry input buffer per physical input, ready/valid links,
and per-output round-robin arbitration. Routing follows `qtree_nca_next` for
terminal destinations: at level L, compare the current position with the
terminal's ancestor position `terminal / 4**(2-L)`. If the router is that
ancestor, descend through the corresponding child port; otherwise take parent
port 4. At the destination leaf, eject through terminal port `terminal%4`.

Protocol is strictly one flit per packet. One accepted flit is one complete
packet and is delivered once to its destination. There is no header/body/tail
framing, wormhole flow control, or multi-flit packet support. Run `./verify.sh`
for Verilator lint and all 4096 ordered source/destination pairs with
concurrent injection and deterministic egress backpressure.
