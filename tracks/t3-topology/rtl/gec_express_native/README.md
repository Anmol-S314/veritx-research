# Native GEC Express RTL prototype

This directory is a standalone, family-faithful **single-flit functional prototype**, not product RTL and not a generic point-to-point graph preview.

## Pinned supported instance

The prototype pins `gec_express16` from `tracks/t3-topology/configs/supported16/gec_express16/`: `k=4`, `c=1`, `o=3`, `d=1`, 16 routers, 16 terminals, `num_vcs=2`, `router=iq`, `routing_function=min`, `use_noc_latency=0`, `priority=none`. The topology is four rows and four columns of routers, with complete directed point-to-point connectivity within each row and each column. There are 16*3*2=96 directed express channels (48 reciprocal physical pairs), plus one local terminal attachment per router.

## Exact ports, channels and route

Router IDs are row-major: `r=y*k+x`. Local terminal `t` has port `t` in `[0,c)`. For `c=1`, this is port 0. The `k-1` row outputs follow in ascending peer-column order, excluding self. The next `k-1` column outputs follow in ascending peer-row order, excluding self. Thus for router `(x,y)`, row peer `q` has `peer_idx = q < x ? q : q-1` and port `c+peer_idx`; column peer `q` has `peer_idx = q < y ? q : q-1` and port `c+(k-1)+peer_idx`. The native channel identity is the directed `(source_router, source_port)` and its exact destination router. Reciprocal directions are separate directed channels, as in BookSim's GEC construction. This preserves the exact adjacency and port order of `topology.anynet`.

Routing is the native `dor_gec` rule: inject over the full VC range; at each router, eject locally when `router == dest/c`, otherwise take one direct row/express hop toward the destination column when `x != dx`, then one direct column/express hop toward destination row. This X-then-Y policy has at most two network hops. With `d=1`, `drop` is always zero and both express hops use the full VC range. The test selects the corresponding phase VC deterministically only to exercise both configured VC values; the RTL carries that VC unchanged.

## Prototype limits

Packets are exactly one flit. Each input has one slot per VC, arbitration is round-robin per output, and ready/valid link transfer is modeled without the configured BookSim router's multi-flit packet state, exact IQ allocator pipeline, channel/credit latency, or performance/timing model. The verifier establishes graph/route behavior, all-pairs one-flit delivery, backpressure handling, conservation, and drain only. It does not qualify full BookSim equivalence or claim PPA/performance.

## Verify

Run `./verify.sh`. It runs Verilator lint and a timed RTL simulation. All build products are placed in a unique `mktemp` directory below `${JCODE_SCRATCH_DIR}`, or `${TMPDIR}`, or `/tmp`, and removed on exit. The test checks every express output channel is covered by route traffic and executes all 256 ordered source/destination pairs under deterministic ejection backpressure.
