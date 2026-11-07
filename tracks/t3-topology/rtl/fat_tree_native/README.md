# Native RTL: canonical `fat_tree4`

This directory targets the structured `fat_tree4` preset, not the separately
named `fattree16` configuration. Its source is
`tracks/t3-topology/dse/veritx_dse/application/presets.py::_fat_tree4_request`:
radix 2, tiers 2, four terminals. The canonical generator is
`model/topology_artifact.py::fat_tree_graph` and computes
`per_tier = radix ** (tiers - 1) = 2`, hence four tier-major routers. It emits
links using `(lower_position + uplink) % per_tier`, giving 0->{2,3} and
1->{3,2}. `STRUCTURED_FAMILIES["fat_tree"]` sets seat capacity to radix, and
`attachment.py::attach_agents` enumerates seats router-major then seat-major.
Thus terminal IDs 0,1 attach to router 0; IDs 2,3 to router 1.

The synthesizable SystemVerilog builds those four routers and four physical
inter-tier links. It routes destination-tagged single flits with elastic
per-input buffers and per-output round-robin arbitration. Each accepted
injection is exactly one complete flit. This is intentionally not advertised as
full packet/VC RTL: packet framing, multi-flit wormhole flow control, VCs,
virtual-channel deadlock guarantees, and fidelity to the full simulator packet
contract are out of scope.

Run `./verify.sh`. It compiles/lints and simulates using a uniquely allocated
`mktemp` directory, removed by a scoped EXIT trap. It never removes a fixed
path. The testbench checks every source/destination route and delivers one
flit for every pair under deterministic egress backpressure, checking payload
identity, exact-once conservation, and final drain.
