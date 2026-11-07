# Native 4x4 mesh RTL prototype

This directory implements a distinct, non-concentrated 4x4 mesh: 16 row-major routers and exactly one endpoint per router. Each router has local, east, west, south and north ports. Inter-router links connect only cardinal neighbors, boundary links are tied off, and routing is deterministic XY (X before Y) followed by local ejection.

Each input has a one-flit buffer with ready/valid flow control and round-robin output arbitration. `./verify.sh` runs Verilator lint and a bounded test that sends one flit for every ordered source/destination pair (including self-pairs), applies deterministic endpoint stalls, checks accepted/ejected conservation, unique delivery and destination correctness, and checks drain. Build products use a temporary directory and are removed on exit.

**Scope limits:** one flit represents one complete packet. This is not a multi-flit packet network and does not implement virtual channels, VC allocation, project-level packet semantics, or formal liveness proof. The test validates this finite 256-flit workload and deterministic stall schedule, not arbitrary traffic or all possible backpressure patterns. `K` is parameterized but the included regression is 4x4.
