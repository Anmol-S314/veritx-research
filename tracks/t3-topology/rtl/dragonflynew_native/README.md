# BookSim `dragonflynew` k=2, n=1 RTL prototype

This directory models the exact 72-terminal configuration in
`tracks/t3-topology/configs/dragonfly16.cfg`, not the separate 4-node structured
`dragonfly` preset in `dragonfly4_native`.

## Derived topology

Pinned source: `third_party/booksim2/src/networks/dragonfly.cpp`.
For p=k=2 and n=1, BookSim computes 4 routers per group, 9 groups, 36 routers,
and 72 terminals. Router IDs are group-major. Each router attaches two
terminals, has three intra-group outputs to the other routers in its K4 group,
and two global outputs. There are 108 directed local channels and 72 directed
global channels.

The `route_next` function follows `dragonfly_port`: same-group traffic goes
directly to its destination router. Inter-group traffic first reaches the
source-group gateway selected by the destination group's rank with the source
group removed, crosses the corresponding direct global connection, then takes
at most one local hop to the destination router. This is minimum dragonfly
group-hop routing, not necessarily minimum total router hops when a nonminimal
route uses extra global channels. The independent checker transcribes BookSim's
channel-index equations and `dragonfly_port` port selection, then verifies the
RTL next hop for all endpoint pairs.

## Scope and limitations

This is a topology-specific, single-flit behavioral RTL prototype. It models
one stored flit per router and one-hop-per-cycle movement over the derived
routes in a centralized fabric block, with deterministic source ordering when
several flits contend for one router. It does not instantiate separate routers
and explicit physical link signals. It is **not** an implementation of
BookSim's complete router datapath: there is no five-flit packet framing,
four-VC allocation/credit protocol, BookSim injection-VC randomization, or
performance parity claim. It is also not an ASIC-ready router/interconnect
implementation.

## Verify

Run `./verify.sh`. The bounded Verilator test checks all 5,184 ordered pairs,
exact destination and payload conservation, ejection backpressure stability,
and complete drain.
