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

## Reset under traffic

`tb_reset.sv` asserts asynchronous reset while eight router slots hold flits and
while upstream holds `inj_valid` high across the reset edge. It requires
`inj_ready` to be low during reset, egress valid to be low with no X data,
every busy slot and every payload register to clear, and then a full
4096-pair sweep to deliver exactly after release.

It found a real defect: `inj_ready` was asserted (all ones) during reset. The
asynchronous reset branch of the register wins over the accept branch, so an
upstream beat was silently discarded rather than held. `inj_ready` is now
gated by `rst_n`. Receipt: `runs/srota64-native-reset-under-traffic-20261111.json`.

## Workload replay

`replay_workload.py` replays a captured trace from
`tracks/t3-topology/dse/inputs/traces/` through this prototype and audits every
delivery independently.

| Trace | Packets | Source routers | Destination routers | Distinct pairs | Result |
|---|---|---|---|---|---|
| `test_dynamic.trace` | 1000 | 64 | 64 | 488 | PASS, 1000/1000 |
| `chakra_converted.trace` | 2688 | 4 | 4 | 6 | PASS, 2688/2688 |

Abstraction: one captured packet replays as one 80-bit fabric packet. The
replay reproduces the trace's ordered (src, dst, send-cycle) stream, not its
byte volume or its original flit framing. Injection is head-of-line in trace
order with an always-ready sink, so measured latency includes driver stalls.
Latency is 2 to 5 cycles because an express segment crosses a whole row or
column in one cycle.

Provenance: these are traces shipped in this repository, not an
operator-approved capture set. Receipts:
`runs/srota64-native-workload-replay-test-dynamic-20261111.json`,
`runs/srota64-native-workload-replay-20261111.json`.

Still not covered: transactions, multi-flit framing, credit timing, physical
implementation.

## AXI5 transactions through the fabric

`axi5_srota_ep.sv` is a per-endpoint bridge between an AXI5 port and one router
of this fabric. `tb_axi5_fabric.sv` instantiates 64 of them, so a transaction
issued at endpoint S and answered by endpoint D really crosses the fabric
model.

Address contract: address bits [11:6] select the destination router, bits [5:2]
select the word in that endpoint's 16-word region. Fabric flits carry
`op[73:72] peer[71:66] id[65:58] word[57:54] wstrb[53:50] data[49:18]`, so a
delivery names its requester and its own reply target.

Checked by `run_axi5_fabric.py` (Verilator):

| Check | Result |
|---|---|
| All 4096 ordered pairs: AXI5 write (AW+W+B) then read (AR+R) | PASS, BID and RID equal the issued ids, read data equals written data |
| Byte strobes `1010` then `0001` | PASS, per-lane merge, not word replace |
| Two independent transactions in flight on different pairs | PASS |
| Drain | PASS, every router slot empty, no reply outstanding |

Use Verilator for this suite: under Icarus with 64 bridges the same test needs
roughly 20 ms of wall clock per simulated cycle, so it does not finish in a
reasonable time. Receipt: `runs/srota64-native-axi5-transactions-20261111.json`.

Scope limit: one beat per transaction, `awlen`/`arlen` ignored, no bursts, no
exclusive or atomic access, no cache/domain/QoS semantics, one outstanding write
and one outstanding read per endpoint. This proves transaction correctness
through the prototype fabric, not production timing or throughput.

## Synthesis

`synth_srota64.py --top bridge` runs Yosys (`proc; memory -nomap; opt -fast;
stat`) over `axi5_srota_ep`: 246 generic cells, 44 flops, no latches, no inferred
memories. `--top fabric` targets the 64-router fabric, which is a behavioural
model with unrolled combinational segment arrays and takes hours at this size;
`--from-log` regenerates a receipt from a completed run.

Synthesis only. There is no place and route, no static timing analysis and no
approved target platform on this machine, so no physical result is claimed.
