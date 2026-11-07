# Concentrated mesh native RTL prototype

This prototype instantiates the canonical `concentrated_mesh` topology for 64 terminals, radix 4: 16 routers in a 4x4 row-major grid, concentration 4, terminal `t` attached to router `t/4` at local slot `t%4`. The canonical materializer's sorted grid adjacency is represented by directional links E/W/S/N, with absent boundary links tied off. Route selection is deterministic XY dimension-order routing, horizontal before vertical, then local ejection.

**Packet contract limitation:** one accepted flit is one complete packet. The prototype does not implement multi-flit packet framing/assembly, virtual channels, VC allocation, or the full project packet/VC contract. It uses one-entry per-input buffering and ready/valid flow control.

Run `./verify.sh` to lint, build and execute the Verilator test. The script uses an unpredictable `mktemp` directory under `${JCODE_SCRATCH_DIR:-${TMPDIR:-/tmp}}` and removes only that generated directory on exit.
