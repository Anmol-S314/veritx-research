# SROTA64 native RTL prototype (experimental)

This is an isolated, constrained topology/route prototype, not product RTL and
not an implementation of `configs/srota64_rowcol.cfg`. That config enables
both path shapes with `srota_vc_policy=rank`; this model instead supports only
a fixed row-first path (complete X transfer, then Y transfer). No VC policy or
mixed-shape safety is asserted.

## Explicit graph and route

The implementation has 256 reserved segment slots indexed by
`(axis,line,anchor,direction)`; 224 are valid directed driver segments. A
segment has one source driver, a flit, selected outward tap/drop, and destination
peer. Each of the 7 outward peer positions is represented by the canonical
`drop = distance - 1` index. The selected tap accepts only when the peer's
aggregate input slot is free. A deterministic slot-order grant serializes
multiple segments requesting the same peer. Source flit is retained unless its
segment transfer wins. Ejection remains valid and stable until ready.

For a route `(sx,sy)->(dx,dy)`, X uses the row segment at `(line=sy,anchor=sx)`
and its signed direction/drop. If `dx != sx` and `dy != sy`, the next hop is
from `(dx,sy)` over the column segment `(line=dx,anchor=sy)` to the destination.
An X or Y leg is exactly one express-segment transfer independent of distance.

`check_graph.py` independently enumerates the canonical `_BuildExpressDim`
construction in `third_party/booksim2/src/networks/srota.cpp`: it checks 224
unique directed segments, 896 ordered taps, every same-row/column directed
source/destination/drop tuple, and the X-then-Y route legs for all 4096 pairs.
The RTL testbench separately checks live RTL segment source, destination and
drop against the route equation while exercising every ordered pair.

## Experimental flit/flow contract and limits

The flit is 80 bits: destination router index `[79:74]`, opaque payload
`[73:0]`. Traffic is one-flit unicast. Each router is represented by one
aggregate one-entry slot, not 15 real per-input buffers. Segment transfer and
slot arbitration are a behavioral ready/valid model, not BookSim channel or
credit timing. The graph's shared driver and selected tap are explicit in the
RTL model, but physical electrical fanout, pipeline stages and detailed
per-input router integration are not modeled.

Not implemented or claimed: multi-flit framing, true VC allocation/credit
timing, multicast, side-buffer integration, two-stage arbiter, concurrent
throughput/performance, timing equivalence, or a general deadlock/liveness
proof. Simultaneous ejection-and-arrival replacement and multi-source
contention are not covered by the supplied serialized-pair testbench. Do not
use this prototype as a production router or infer performance from it.

## Verification

Run `./verify.sh` (Python 3, Icarus Verilog). It runs the canonical graph oracle,
then checks all 4096 ordered source/destination pairs for exact flit delivery,
holds each egress under backpressure for three cycles and checks stable valid
and data, checks live RTL segment/drop mapping, and verifies the fabric drains.
The test is sequential by pair; it does not test concurrent arbitration.
