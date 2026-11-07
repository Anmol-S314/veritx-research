# Native torus RTL prototype

This is a parameterized, point-to-point 2D torus with cardinal `+x`, `-x`, `+y`, `-y` ports and a local terminal port. The acceptance test pins the project default `k=8, n=2`: 64 routers and 64 terminals, one terminal per router, with wrap links on both dimensions.

Routing is deterministic minimal dimension order (X before Y, shortest direction with a fixed tie break). Each physical input has two one-entry VC slots. Route selection chooses the downstream VC from the actual dateline edge crossing and holds the packet in the escape phase after crossing. Arbitration checks readiness for the selected output VC, not the input VC.

Run `./verify.sh` for Verilator lint/build and the self-checking all-pairs test. It sends one complete flit per packet, checks exact source/destination identity, exercises deterministic output backpressure, detects duplicates/misdirection/loss, and checks drain.

This remains a single-flit prototype, not the configured BookSim/ESP multi-flit microarchitecture. It does not model head/body/tail framing, packet-level VC reservation, configured buffer depth, or PPA. Its cycle count must not be presented as a topology performance comparison.
