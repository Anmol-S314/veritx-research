# dragonfly4 native single-flit prototype

This directory implements the exact repository structured preset
`StructuredTopologyIntent('dragonfly', {'radix': 2, 'group_count': 2})`,
with `endpoints=4`. It is derived from
`tracks/t3-topology/dse/veritx_dse/model/topology_artifact.py:1115`.

## Canonical graph and route

Router numbering is `group * radix + a`: routers 0 and 1 are group 0, and
routers 2 and 3 are group 1. The within-group clique produces local links
`0-1` and `2-3`. For the only group pair `(src_group=0,dst_group=1)`,
the canonical mapping `dst_group * radix + ((a + src_group) % radix)` yields
global links `0-2` and `1-3`. Thus the exact undirected edge set is
`{(0,1),(2,3),(0,2),(1,3)}`.

A flit whose destination is the current router ejects there. Otherwise it
traverses the unique direct edge to its destination: within-group pairs use
local edges and cross-group pairs use global edges. The source-router ID is
the source endpoint ID, and destination IDs are the four endpoint IDs.

## Scope and contract

This is a minimal, isolated **single-flit** ready/valid prototype: one stored
flit per router, fixed direct routing, and no VC allocation. It is not the
repository's full packet/VC contract and does not implement multi-flit packets,
virtual channels, arbitration under contention, or protocol integration.
It is not BookSim's separate `dragonflynew` 72-terminal `dragonfly16.cfg`
topology.

## Verify

Run `./verify.sh` from any working directory. The testbench serially checks
all 16 ordered source/destination endpoint pairs, exact destination and unique
payload delivery, accepted equals delivered, deterministic output
backpressure with ready/valid data stability, and complete drain.
