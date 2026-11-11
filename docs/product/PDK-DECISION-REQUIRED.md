# PDK / platform decision required from the operator

Date: 2026-11-10. Decision owner: operator. Neither the agent nor the plan can substitute a technology the operator has not approved. Two numbers below drive the recommendation.

## The problem

Post-CTS STA on the full `project_top` is measured on `RUN_2026-11-10_07-07-09` (sky130A, `CLOCK_PERIOD=10.0`): **setup WNS = −4.424 ns / TNS = −11.4 µs**, hold clean. A router re-pipeline landed this morning (grant decision now registered; `esc_yield_q` replaces the starving-counter comb; 4-VC dwell extension) and the critical class moved: the binding classes are now **7,212 × async-reset fanout flop** (`rst_n → /D`) and **1,470 × reg-reg/out** (incl. two-level 32-bit debug-tap adders in `project_top.sv` into output ports, worst ≈ −2.86 ns). The arbiter is no longer binding. The LibreLane run died in stage 37/38 (`ResizerTimingPostCTS`, killed twice, ~0.01 ns/iter, 23,570 setup-violating endpoints — not converging); routing / DRC / signoff are **NOT_RUN**. No clock change is permitted as a fix.

## What exists today (sky130A, LibreLane v3.0.17)

| Stage | Result | Numbers |
|---|---|---|
| Synthesis (Yosys) | PASS | 90,415 instances, 1.14 Mµm² |
| Slang lint (Slang 05) | PASS | 0 errors |
| Floorplan | PASS | die 2,325,120 µm², util 50.1% |
| Detailed placement | PASS | 0 violations |
| CTS | PASS | 46,647 µm², worst setup skew +0.44 ns |
| Post-CTS STA | **FAIL** | setup WNS −6.02 ns; hold WNS/TNS = 0; slew 25 |
| Resiser after CTS | NOT_RUN (killed at ~90 min) | — |
| Routing / DRC / signoff | NOT_RUN | — |

## Why sky130A specifically is weak here

- Sky130A is a 180 nm open PDK and this top is register-dense (90 k instances, 454 k µm² sequential). Library delay at 180 nm is ~5–8× an A-RTS/S-high spec at 7 nm. The −6 ns gap here is *library + topology*, not a tool verdict about 7 nm.
- Sky130A is the only PDK obtainable in this checkout (ciel/volare serve sky130A/GF180MCU/ihp-sg13g2; ASAP7 was never found registered anywhere).

## What the operator must supply or approve

1. **PDK**: one of
   - sky130A (continue as the diagnostic placement reference; timing at 10 ns does **not** close — the remaining classes are async-reset fanout (fixable via reset-tree constraint/design review, not resizer) and debug-tap adder output ports (fixable with a pipeline stage on the debug taps), not the grant arbiter; and even then a 180 nm library makes a 7-nm-class verdict impossible), or
   - an accessible ASAP7 set (GitHub `efabless/asap7` "asap7sc7p5t_rvt" timing/tech files or equivalent; agent cannot download or license it), or
   - another approved 3.3 V/1.8 V/1.4 V open PDK (GF180MCU is the closest sky130-class alternative; `volare` manifests cover it).
2. **Clock** for the full net: one declared `default_clock_freq_mhz` (V4 requires it; a stored request lacking it will now refuse — that refusal is intentional and matches the plan).
3. **Die/core bounds** and a **pinout** for the network block. No approved bounds exist (§12 P8 records the blocker).
4. **Whether a full-network placed/routed design or "network slice signed off" is the release claim.** The latter is honestly reachable today (CTS passes, timing recovery in flight); the former overlaps the ASAP7 question.

## Recommendation (not a decision)

- For *today's* honest claim: keep sky130A as the **diagnostic placement reference** for the network block, and record the 20 nm-vs-7 nm gap as "library-caused gap, not a tooling verdict".
- For a *release* signoff claim: need ASAP7 or an equivalent approved 7-nm platform. Without it, `final_implementation` stays `false` and no DRC/signoff claim can be made — the current honest state.
- Do **not** present 1×1 `HybridCreditRouter` (GDS, setup +0.564 ns, hold +0.118 ns) as full-network evidence.

## What is already proven that doesn't need the PDK

- Composed tops for all 14 families lint+simulate clean at their declared configs (Mesh 8x8 TB 18/18; torus 9R; ring 64R; cmesh/qtree/tree4 un-supported-and-honestly-refused at multi-seat; mesh identity evidence pinned).
- Full AXI5 + CHI-full + TileLink-1.8.1 modules lint clean; ordering FSM, address decoder, CDC cell, shared-wire MECS/Srota testbenches pass on their own routing laws.
- 74-agent/81-router Mixtral revision is identifiable (`docs/product/evidence/mixtral-74-81-8-162/`).
- 63/63 IP-catalog tests; 54/54 bad-design-witness tests; 42/42 placement; 327 frontend unit tests; 8/8 delivery e2e; 14-family *lint* evidence exists but 5 families are honestly blocked at multi-seat (typed refusal, not faked).

## What this PDK decision unblocks

| Decision | Unblocks |
|---|---|
| Sky130A-only | Diagnostic placement numbers for the block; resizer verdict on the pipelined-arbiter redesign; no release signoff |
| ASAP7 or approved 7 nm | Full signoff path (repair→route→DRC→LVS→GDS); the real finish line |
| GF180MCU | Independent timing confirmation (closes credible-SET risk), not a 7-nm claim |
| No decision | Nothing moves; `final_implementation` stays `false`; the P9 row stays blocked |

## RTL prerequisite for any close (independent of PDK)

Done, and it moved the wall: the grant-arbiter re-pipeline (registered stage B for every decision bit, `esc_yield_q` priority state, 4-VC dwell extension) is landed and the composed top re-verified (38/38). The remaining violators are async-reset clear-muxes (7,212 flops; the reset tree needs a constraint/design-review pass — not resizer work) and the 32-bit debug-tap adders in `project_top.sv` (1,470 reg-reg/out). Closing at 10 ns additionally requires addressing those two classes or a slower CLOCK_PERIOD, and the PDK decision above. No signoff-PDK exists for this design on sky130A.
