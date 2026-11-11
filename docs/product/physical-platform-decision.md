# Physical platform decision — 2026-11-10

## Decision (operator directive, 2026-11-10 session)

**sky130A (LibreLane v3.0.17) is the declared diagnostic placement platform for this release cycle.** ASAP7 remains the declared target for the Mixtral 7-nm request and is **not** substituted by this decision.

## What is unblocked (by this decision)

- Full-top LibreLane flow on the delivered `project_top` (synthesis → floorplan → placement → CTS → STA) may proceed with sky130A files.
- All numbers from sky130A runs are diagnostics of the hardware flow, never claims about 7-nm timing, area or power.
- This decision does not claim an ASAP7 timing platform, sign-off, or GDS for 7 nm. `final_implementation` stays `false`.

## What remains blocked

- **ASAP7 platform**: no registered/downloadable ASAP7 PDK, timing libraries or license was obtainable in this checkout (ciel/volare serve sky130A, gf180mcu and ihp-sg13g2 only). P0.8's 7-nm leg stays blocked until the platform, libraries, clock and die bounds are provided.
- **Die/core bounds, pinout, macro strategy** for the full network: no approved thermal/die floorplan exists for the Mixtral 74-endpoint design. The 1×1 `HybridCreditRouter` placed/routed slice is a tool-infrastructure diagnostic only.
- **Queue storage**: flop-based per-VC queues map to ~4.26 Mµm² of cell area for the 36-router top (~100% sequential) — SRAM macros (or an explicitly approved smaller buffer contract) are required before the full network can place.
- **Sign-off**: CTS/ECO/routing/DRC and final STA on the full top are NOT_RUN pending the resizer `+0.4 ns → 0 WNS` close (see `docs/design/asap7-librelane-spike.md`).

## How to resume

1. Provide ASAP7 (or an approved substitute) platform + libraries + license + target clock + die bounds → rerun the full flow on it (P9).
2. Until then, sky130A diagnostics continue and stay labeled sky130A everywhere.
3. The operator may instead approve sky130A as the release diagnostic platform and accept that no 7-nm sign-off is claimed — the release report must then keep `final_implementation: false`.
