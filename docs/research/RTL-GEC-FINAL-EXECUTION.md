# Bounded GEC implementation execution

Goal: finish the approved small end-to-end paths without substituting flit smoke tests for AXI transactions or diagnostics for physical signoff.

## Checked platform facts

`docs/product/physical-platform-decision.md` approves Sky130A / LibreLane diagnostic full-top work, not ASAP7 release signoff. Both sky130A and sky130B directories exist under `~/librelane-spike/pdks`; this is not evidence of approved network bounds/pins or successful timing. No new physical decision is inferred.

## Plan and acceptance

1. Wire the existing credited GEC AXI top into the completion runner and repair emitted hierarchy attribution. Check dispatch with unit witnesses; generate a fresh durable request-bound artifact and independently verify its file/log hashes.
2. Make final-verdict lint evidence fail closed on warnings, missing logs, or empty scenarios. Check positive and negative witnesses. Do not make functional smoke success depend on zero style warnings.
3. Build the shared-buffer dependency graph for actual GEC X-then-Y express hops (VCs share physical ingress storage), reuse the existing rank proof engine, and retain input/RTL/proof hashes. Check real SBY prove plus wrong-topology/route mutation witnesses. This proves absence of circular channel waits, not fairness or arbitrary endpoint progress.
4. Extend connected transaction acceptance to four outstanding transactions and multi-beat packet framing using existing adapter owners. Check queue-full backpressure, different IDs, stalls, and burst readback; do not equate sequential downstream execution with four accepted requests unless acceptance/storage is exercised.
5. Exercise existing asynchronous CDC and reset cells in the connected GEC hierarchy with independent clocks and reset-in-flight. Check no duplicate/stale completion after reset and credit drain.
6. Reproduce the bounded matrix and bind every result to exact request, generated RTL, tools, and producer sources. Keep final false for any missing gate, including approved physical requirements.

## Plan critique

The current completion runner still dispatches GEC to a flit-only top, so a passing direct AXI unit test is not product closure. The current CDG proof splits VCs although the dedicated shared fabric has physical single-entry ingress storage: it must analyze the merged storage graph. Four-outstanding and burst framing are state-machine work, not evidence-file edits. Reuse the existing proof/adapter/CDC owners; no new framework or scope-out decision.

## Progress

- Initial repository/platform inspection complete; platform wording corrected in the session.
- Step 1 code change: `scripts.complete_design.generate_hardware` now dispatches GEC-MECS to the composed credited-AXI runner, and the bridge refuses missing/malformed row/column wires, wrong width/latency, or insufficient payload. Added dispatch and mutation witnesses. Connected generation and simulation complete successfully at `scope=COMPOSED_FAMILY`; the bundle hashes are in `/tmp/veritx-gec-connected-Fw6n55/` (`archive_sha256=d19b7c37eec246a486908ef8e03d3183b20f137e92d669da95904ce54425a8f4`).
- Step 2 code change: A1/A2 evidence now requires nonempty all-`True` scenarios, actual logs, zero Verilator `%Warning` lines, and a PASS simulation marker. Stored stale A1/A2 rows no longer override current measured evidence. Added positive and negative witnesses. The real build has 13 passing scenarios and a PASS sim, but **272 lint warnings** (164 PINMISSING, 45 UNUSEDSIGNAL, 28 UNUSEDPARAM, 26 UNDRIVEN, and 9 others); A2 correctly remains OPEN. Missing AXI pins and undriven nets are real connected-hierarchy gaps, not clean-lint noise.
- Request-to-hardware binding is now checked at run time: request/design hash and family/router binding must match, and each generated slice instance must match its compiled endpoint seat and router. The emitted top source hash is captured in A3 evidence. Added a corrupted-router mutation witness; binding evidence now retains failed measurements too.
- Targeted regressions passed after this change: **62 passed** (`test_gec_axi_binding.py`, `test_complete_design.py`, `test_scope_evidence_lint.py`, `test_final_implementation_evidence.py`; 39.77s). Pytest reports an existing unknown `timeout` config option warning.
- A fresh connected build with the new binding check is running under `/tmp` so the regenerated manifest and archive remain available.
- Step 3: GEC now derives one dependency graph over merged physical ingress storage (not separate VC graphs) using the emitted X-then-Y direct shared-wire hops. The existing unbounded SBY rank proof passes on all 16 routers: **144 dependency edges, 96 channels**, COMPLETE scope over the extracted graph. A topology mutation that removes an emitted hop is refused.
- Step 4 (evidence gate): the composed runner ran unbounded SBY proofs against its compiled address decoder and GEC shared-storage graph. In `/tmp/veritx-gec-full-evidence-jP1rbp/`, A6 and A7 both closed, with the proof harnesses and `result.json` files retained under `rtl/proofs/`. The run had A3 closed, A2 open (272 lint warnings), and 13/13 simulation scenarios pass; final remains false. That build used a pre-fix archiver and reported duplicate `evidence/result.json` ZIP entries. Source now gives each proof a distinct archive path, hashes lint/build/sim logs and proof artifacts in the manifest, includes those files in the archive, and records Python/Verilator/Icarus/SBY/Yosys/Z3 versions. A fresh archive verification is still required.
- Connected CDC topology check: a cross-domain GEC request asserts both generated CDC directions and an asynchronous source clock. The first connected reset-in-flight run exposed testbench races: its AXI tasks sampled `ready` on the fabric clock instead of the initiator clock. The run showed the reset-flush scenario but failed other transactions. The connected cross-clock run exposed two real CDC bugs. The generated return-path (`cdc_slice_down`) reversed the CDC cell's source/destination clocks and used the opposite reset in its toggle flops. Separately, the FIFO pointers stayed in aligned reset while public `wr_full`/`rd_empty` could still advertise readiness, dropping early traffic. I fixed the wrapper direction/reset mapping and backpressure the public interface until both reset domains are aligned; the generated test clock now has a genuinely different period. The standalone skew/reset simulation checks for acceptance during alignment and immediate remote-reset assertion. Its focused CDC/formal tests pass (14 tests). The next connected simulation exposed a TB race: valid was deasserted in the same active edge as the DUT handshake. The generated per-initiator drivers now hold valid through the rising-edge sample and deassert at the following falling edge; a fresh connected GEC build is pending.
- Still open: four-outstanding transaction storage/retirement, AXI burst framing end-to-end, connected CDC/reset proof, and the request-bound reproducible release matrix. The current generated manifest correctly says one effective outstanding transaction. `final_implementation` remains false.
- Workspace has hundreds of unrelated pre-existing modifications/untracked artifacts; preserve them and do not run cleanup/reset operations.

### 2026-11-12 — shipped family closes; cross-clock variant measured

- **Shipped `gec_mecs` closes its composed scope.** `scripts.complete_design.generate_hardware(make_family_request("gec_mecs"), ...)` now returns `final_implementation: true`: scope `COMPOSED_FAMILY`, A1–A10 all CLOSED, Verilator lint **0 warnings**, simulation PASS with **13/13** scenarios true (`archive_sha256=5ae574dec371e59554e9f4fdc0f6e5a70b4deaa9d0866de8f4377dd2d2e80c89`). A8 (paired BookSim/RTL parity), A9 (directed AXI5 suite) and A10 (multi-flit reassembly) come from the recorded bundle keyed to this design hash, not from a hand-written row.
- **Cross-clock variant measured, not asserted.** With `agents[0].clock_domain = "compute_clk"` the emission generates both CDC directions, lints at **0 warnings**, and passes **14/14** scenarios, including `cdc_reset_inflight` (reset with a flit in flight, then no stale B and a clean post-reset transaction). Its A8–A10 remain OPEN: the bundle is keyed to the shipped design hash and evidence is not transferred across designs.
- **Three real defects found by measuring, and fixed:**
  1. `word_w` packing. `_widen_family_initiator_src` rewrote `beat_off_w[11:2]` to `beat_off_w[11:0]` whenever no data widening was applied, so a 7-bit `word_w` kept the low seven *byte* bits. Every access above `0x1000` indexed the wrong SRAM word. It now packs `beat_off_w[8:2]` (9:3 and 10:4 for 64/128-bit data).
  2. Unsynchronised response status. The slice sampled `noc_out_flit[55:54]` for the response status. On a crossed slice that is the raw asynchronous input, so an out-of-range read came back OKAY instead of SLVERR. The crossed emission now reads `cdc_ret_flit[55:54]` and `cdc_ret_flit[31:0]`; the single-domain emission keeps `noc_out_flit`.
  3. `fabric_clk` pin. `project_top` connected the slice's `fabric_clk` only on the crossing initiator, so the non-crossing slice instance tripped PINMISSING. The top now connects it for every slice once any initiator crosses, and a non-crossing slice consumes the port with an `unused_` tie-off.
  The CDC wrapper modules are also emitted one per file, because a single multi-module container file trips DECLFILENAME.
- **Testbench drivers corrected.** The generated AXI tasks drove `bready`/`rready` while a response was still being consumed and sampled `ready` on the wrong clock, which produced duplicate handshakes and phantom failures. The per-initiator drivers now hold `valid` across the sampling edge, deassert on the following falling edge, and assert that no stale B/R survives a completed handshake. Scenario expectations were also wrong in two places: `backpressure_release` and the post-reset completion string, which now accepts the crossed variant's own evidence line.
- **Still open (as of that run):** AXI burst framing and more than one outstanding request per initiator. Both are state-machine work, not evidence wiring. The burst half is addressed in the section below; the outstanding limit is not.

### 2026-11-13 — burst framing executes in the emitted slice

- **Burst framing is now measured, not refused.** The family slice captures `awlen`/`arlen` into `total_beats_q`, buffers every `W` beat with its `wstrb`, checks `wlast` against the expected beat index, issues each beat as its own flit at the incremented address, closes a write burst with exactly one `B`, and presents one `R` per beat with `RLAST` on the final beat. `awlen > 15` and non-word sizes stay refused (`DECERR`) because the buffer is 16 entries.
- **Re-measured shipped family.** `complete_design.generate_hardware(make_family_request("gec_mecs"))` returns `final_implementation: true`, A1–A10 CLOSED, lint **0 warnings**, simulation PASS, **15/15** scenarios true, `burst_framing: true`, `archive_sha256=47017dfa4f504bd69424b7956f47da64e65b4a5863ab7684d8098bd8a3c427d7`. The refreshed bundle (`docs/product/evidence/final-implementation/gec_mecs.json`, design hash `03fec67d…`) records `scenarios: 14`.
- **Cross-clock variant re-measured.** Same request with a second clock domain: lint 0 warnings, simulation PASS, **16/16** scenarios (the CDC reset-in-flight scenario plus the burst and outstanding-acceptance scenarios). `final_implementation` stays `false` there because the recorded bundle is keyed to the shipped design hash and evidence does not transfer.
- **Two real testbench defects were found by measuring, and fixed:**
  1. The non-crossed `S8` release path sampled `bvalid` with `bready` still low and then dropped the transaction, leaving a `B` pending in the slice's `S_RESP` state. The next scenario then captured a stale `AW` and pushed beats into the wrong transaction. The path now consumes the response (`bready` high for one cycle) before moving on.
  2. The burst scenario issued its read with the write's starting `seq` instead of the sequence after the four write beats, so the ordering FSM (mode 1) refused every read beat as out-of-order. The read now starts at `seq + 4`.
  Additionally, the per-handshake wait bounds in the generated tasks were 100 cycles, which silently expired during a credit stall and dropped `W` data; they are now 8000 cycles, and a write that never reaches the fabric fails the scenario instead of passing on a stale response.
- **Lint regressions from the burst work were fixed**, not suppressed: the burst capture left `cap_len_q` and `wstrb_buf_q` unread and computed 52 unused bits of `beat_addr_w`. The dead signals are gone and the beat address is computed in 12 bits.
- **Scope of the burst scenario.** It runs on `gec_mecs` only. Every other composed family emits `SKIP: S10 burst framing (not measured for <family>)` and records a `burst_framing_skipped` scenario key, so no family claims a burst it did not measure. Making the same stimulus green on the concentrator and the small-buffer families is a testbench-pacing job, not an RTL change.
- **Cross-clock status reduction fixed.** Measuring the crossed variant exposed one more instance of the synchronisation bug already fixed for read status: the write-status reduction compared beat status against the raw asynchronous `noc_out_flit`, so on a crossed slice an error status on a burst beat could have been aggregated as OKAY. It now reads `cdc_ret_flit`, the synchronised return flit.
- **The outstanding limit is measured, not declared.** A new `S15` probe in the emitted testbench issues a transaction, holds its `B` off, and presents a second `AW`; it reports whether the slice accepted it as `MEASURE: max_outstanding_per_initiator=<n>` and requires one `B` per accepted transaction. `run_composed_family` parses that number into `ordering_realization` as `measured_max_outstanding_per_initiator` next to `declared_max_outstanding_per_initiator`, and **fails the run** if the two disagree, so the manifest cannot publish a limit the simulation did not observe. The shipped family measures **1**: the second `AW` is refused while the first `B` is pending, which is what the state machine is written to do.
- **Still open at this scope:** more than one outstanding request per initiator. It is now a measured limit of 1 rather than a declared one, and raising it is a real feature, not an evidence edit: the AXI5 adapter holds a single `aw_busy_q`/`w_busy_q` context (`in_awready` requires both idle) and the slice holds a single `cap_*` context, so four outstanding needs an `AW` context queue in the adapter, per-context `W` demux, per-context beat/response tracking in the slice, tagged `B`, new acceptance/storage scenarios, and a re-measured evidence bundle.
- **Regressions:** composed-family slice suite **38/38**, focused evidence/binding/CDC set **33/33**.

### 2026-11-13 — the emitter, not a hand edit, writes tool-portable RTL

- **What was wrong.** The emitted GEC fabric/router was readable SystemVerilog that only Verilator could parse: functions with early `return`s, `automatic` function-local declarations, and `initial`-block `$fatal` parameter-contract checks. Yosys rejected it in 0.04 s (`syntax error, unexpected TOK_AUTOMATIC`, then `Can't resolve task name 'return'`). The workaround was `scripts/portabilize_gec_rtl.py` run by hand, so `runs/selected-r02-gec-c4-portable-20261112/rtl/` was a corrected copy nobody could regenerate from the product.
- **What changed.** The rewrite moved into the product as `veritx_dse.product.sv_portable.portable_sv`, and every synthesizable module the emitters write now goes through one choke point (`project_top_rtl._write_rtl`). Testbenches are written verbatim: they are simulation-only and Yosys never reads them. `scripts/portabilize_gec_rtl.py` is now the CLI over the same function, so there is one implementation.
- **It is the same rewrite, byte for byte.** Running the product function over `runs/selected-r02-gec-mecs-seats-c4-20261112/rtl/gec_mecs16_fabric.sv` reproduces `runs/selected-r02-gec-c4-portable-20261112/rtl/gec_mecs16_fabric.sv` exactly (`diff` empty): 150 case returns, 4 tail returns, 4 `automatic` locals, 1 guarded `$fatal` block. So the hand-fixed file was this transform and nothing else, and it is now regenerable.
- **Regenerating does not change behaviour.** A fresh `run_composed_family("gec_mecs")` from the patched emitter lints clean (0 warnings) and simulates PASS with 15/15 scenarios — the same numbers as the pre-fix emission.
- **The rewrite refuses rather than guesses.** A `return` that is not the last action on its path raises `SystemExit`; the second pass over already-ported text is a no-op, so re-emitting cannot double-guard the `$fatal` blocks.
- **Yosys now reads the shipped fabric**, which is the precondition C6 was blocked on: `read_verilog -sv gec_mecs16_fabric.sv tap_credit_pool.sv; hierarchy -top gec_mecs16_fabric; proc; opt -fast; stat` elaborates 16 router instances plus the credit pools with only benign "replacing memory with registers" notes.
- **Tests:** `tracks/t3-topology/dse/tests/test_emitted_rtl_portable.py` pins the rewrite (case/tail return, `$fatal` guard, refusal of a non-tail return, idempotence), pins that the raw emitter output still needs it and that `_write_rtl` applies it, and — when Yosys is installed — elaborates the ported fabric. **7/7 pass.**

### 2026-11-13 — physical loop opens: LibreLane runs, and what it rejects

- **The tooling claim was wrong, and is now measured.** `~/librelane-spike/.venv312/bin/librelane` (3.0.17) with podman and sky130A on this box runs the flow; the earlier "Yosys only" reading was a PATH artefact. Two prerequisites were real defects: the 3.14 venv has no `tkinter` (LibreLane evaluates PDK Tcl through it), and the local Yosys 0.52 cannot run LibreLane's `-y` pyosys scripts, so the flow runs `--containerized` against `ghcr.io/librelane/librelane:3.0.17` (Yosys 0.62 + slang).
- **First defect the flow found: a 32-bit mapping function.** `route_destination` returned `int unsigned`, so every coordinate decode fed a 32-bit `% K` / `/ K`. At the 16-router shape the synthesiser spent its whole memory budget inside ABC building 32-bit dividers. The emitter now derives the width from the domain: `localparam int ROUTE_W = $clog2(K*K + 1)`, the function returns `logic [ROUTE_W-1:0]`, and the sentinel is `ROUTE_W'(K*K)` — a seven-bit comparison instead of a machine-int division.
- **Second defect: block-scope temporaries with no stored meaning.** Declaring the scan temporaries inside the `always_comb` (and letting the portable subset drop `automatic`) made Yosys carry an undefined initial value for them and then refuse to merge it (`Conflicting init values for signal 1'0 (…candidate_dest[5] = 1'x != 1'0)` at `OPT_MERGE`). The rule the two tools force is now the one implemented: `automatic` is redundant in a *function* and load-bearing in a *block*, and a block local must be declared before the block's first statement. `sv_portable` therefore strips it in function scope, keeps it in block scope, and hoists a late declaration to its block top.
- **What the emitter now writes, measured:** lint 0 warnings, simulation PASS, 15/15 scenarios, and Yosys 0.52 elaborates the emitted fabric with `proc; opt -fast; stat`.
- **Three fixes landed from the flow's own complaints, all measured:** the route map is seat-width (`ROUTE_W = $clog2(K*K+1)`) instead of `int`; the fabric's `pd`/`row_dst`/`col_dst` are seat-width too; and the vestigial `bready_w` wire that Verilator reported as undriven is gone (0 lint warnings, simulation PASS, 15/15 scenarios).
- **A latent routing bug fell out of the sentinel change.** `pd = -1` marked "no route", but `route_destination_f` returns `K*K` for an endpoint that maps to no router, and `K*K` satisfied the old `pd >= 0` test: the row driver then computed `(src / K) * K + (K*K % K)` and could deliver an unmapped flit to column 0 of the source's own row. The sentinel is now `K*K` itself, so "no route" and "unmapped endpoint" are one case and neither routes.
- **Evidence re-recorded from the current emitter:** `test_final_implementation_evidence_positive.py` is **12/12**, so every family that claims `final_implementation: true` is claiming it from a bundle measured on the bytes this emitter produces.
- **Still open for C6, and now located precisely.** LibreLane's synthesis step for the 16-router fabric is still killed at the memory limit (11 GB container on a 14 GB machine) inside ABC, and the netlist it is mapping still carries `$sub` cells with a 32-bit operand against 60–63-bit ones, i.e. another machine-int arithmetic chain outside the coordinate decode. A bare `proc; opt` on the selected 81-router fabric exceeded **3000 s** without finishing. Until that arithmetic is found and narrowed the same way, no P&R number for this design exists on this machine, and C6 stays open with a named cause rather than a claim.

**Lookahead routing is now in the emitter** (`gec_mecs_credited.py`, step 8b):
`route_destination` is decoded once when a flit is accepted, into `dest_q[p]`
beside `flit_q[p]`, and the three priority scans plus the grant block compare
`dest_q[scan_idx]` instead of re-running the decode case inside arbitration.
It is behaviour-preserving by construction — `dest_q[p]` is written on the same
edge as `valid_q[p]`, and every read is `valid_q`-guarded — and the emission
still measures lint PASS with 0 warnings, simulation PASS, 15/15 scenarios,
and `proc; check` 0 problems.

**Partitioning the paths separates the design from the harness.** On the
routed 25 ns product netlist (`ss_100C_1v60` liberty + nominal SPEF), STA
split into three reports:

| path class | slack at 25 ns | implied path |
|---|---|---|
| register → register (the router's own logic) | **+0.752 ns (MET)** | 24.248 ns |
| register → output port | −2.982 ns | 27.98 ns |
| worst overall | −2.982 ns | 27.98 ns |

The register-to-register sweep is linear and constant: +0.752 at 25 ns,
−4.248 at 20, −9.248 at 15, −11.748 at 12.5, −14.248 at 10 — every one of
them `period − slack = 24.248 ns`. So the emitted router's internal logic
closes **25 ns (40 MHz) with +0.75 ns at the slow corner**, and the only
setup failures are register-to-die-edge-pin paths, which a router inside a
fabric never has: its flit outputs drive the next router's flops, i.e. the
register-to-register class. 100 MHz would need the 24.25 ns chain cut to
under 10 ns, which is arbitration pipelining, and that is not claimed.

Three hypotheses were measured and eliminated first, each on the same clock:
lookahead routing (−3.75 ns overall, no change — the destination decode was
not the head of the chain), `OUTPUT_CAP_LOAD` 33 fF → 3 fF (−3.57, no change —
the load was not manufacturing the buffer ladder), and hold repair capped
(margin 0, 10% buffers: −3.56, no change). A fourth route — a harness that
registers the router's outputs to measure the fabric context directly — was
abandoned because dfflibmap left 212 `$_DFF_PN0_` cells unmapped on the
harness flops; STA path partitioning answered the same question on the
product netlist instead, without a harness to justify.

**The next unit is a design change, and it is now named precisely.** The
combinational chain that misses is decode → credit compare → 7-port priority
scan → flit output mux, all in one cycle. Two standard fixes, in order of
leverage: register the direction/credit decision per input port at flit
acceptance (lookahead), which deletes the decode and credit compare from the
arbitration cycle; then register the grant stage so the output mux is the only
thing between a register and the flit bus. Both are cycle-model changes and
therefore need the 15 scenario expectations re-derived, which is why they are
a unit of work rather than a knob.

### 2026-11-13 — the physical flow runs, and what it caught

LibreLane 3.0.17 + sky130A runs on this box: `podman` with `--containerized`
Yosys 0.62 + slang, because the host's Python 3.14 venv has no `tkinter` (the
PDK's Tcl) and the local Yosys 0.52 cannot run the `-y` pyosys flow.

**Three defects only synthesis saw.** Verilator lint was clean and every
scenario passed while the router carried: a 32-bit divider at every coordinate
decode (`route_destination`, `row_tap`/`col_tap`, and `% PORTS` on an `int`
round-robin index — 21 scan sites per router); block-scope temporaries whose
initial value synthesis does not carry (`Conflicting init values for signal
1'0 (…candidate_dest[5] = 1'x != 1'0)`); and, in `tap_credit_pool.sv`, a
module-scope `integer t; integer v;` used by two different `always @*` blocks,
which is a 32-bit latch per block and **two conflicting drivers** on the credit
nets — bits 0 and 2..31 conflicting with `1'0` and bit 1 with `1'1`, exactly
`CAPACITY = 2`. The counters are now per loop (`for (int t = …)`) and
`proc; check` reports 0 problems where it reported 2.

**Router-scale physical result** (one `gec_mecs_router`, sky130_fd_sc_hd,
`FP_CORE_UTIL 30`, die 174,065 µm², 70,504 µm² of std cells):

| clock | route DRC | violations | hold WS (worst corner) | setup WS (nom_ss) | reg-reg violations at nom_ss |
|---|---|---|---|---|---|
| 10 ns | 0 | 0 | +0.105 ns | −8.66 ns | 109 |
| 20 ns | 0 | 0 | +0.105 ns | −2.29 ns | **0** |
| 25 ns | 0 | 0 | +0.105 ns | −3.55 ns (path arrives 23.30 ns) | 0 |
| 30 ns | 0 | 0 | +0.107 ns | −6.15 ns (−620 TNS) | 0 |

**A fixed-layout STA sweep separated the design from the flow.** Fixing one
routed database (the 25 ns run) and re-timing it at several periods while
changing nothing else gives a perfectly linear result — 20 ns: −8.546,
25 ns: −3.546, 30 ns: **0.000 with +1.454 ns worst slack** — i.e. a constant
28.546 ns path at `ss_100C_1v60` with nominal SPEF. The 25 ns figure
reproduces the flow's own signoff number (−3.55) to the millivolt, so the
method is sound. **The earlier "longer period made setup worse" claim is
retracted:** separate runs built different netlists (70k vs 82k std cells,
174k vs 204k µm² die), and the 30 ns run that did worse was the one with
`SYNTH_STRATEGY: DELAY 0`. The clock was never the variable. On this netlist
the router closes setup at 30 ns (33 MHz) and misses 25 ns by 3.55 ns; that
chain is what lookahead routing would shorten, and it is a performance
decision, not a correctness one.

The uncorrected sweep (no SPEF) is also worth keeping as a caution: it read
+2.36 ns at 25 ns, because without parasitics the wire delay of exactly this
chain disappears — a clean reminder that a timing number is only as good as
the extraction behind it.
 (20 ns → −2.29, 25 ns → −3.55,
30 ns → −6.15 at nom_ss) while DRC stayed 0 and hold stayed positive. That is
not a missing timing budget and it is not what a resizer normally does; with
more slack the flow packs and sizes differently and the wire delay of the same
logical chain grows faster than the slack it gains. The chain is unchanged
across all four runs, so the number to carry forward is the chain, not the
clock: every setup violation at every period is `reg-out` on the flit buses,
and there are **zero `reg-reg` violations at 20 ns and above**.

So the internal logic closes at 20 ns and the remaining violation is one long
combinational chain that terminates on a flit output port: `_7186_/Q` →
`xor2` → `buf` → `o21a` → `dlymetal` → `a21oi` → `a221o` → `a31o` → `a221oi`
→ `a31oi` → `a221o` → `a21boi` → `and3b` → `a211o` → `a2111o` →
`local_flit[5]`, arriving at 18.04 ns of a 20 ns period. That chain is the
grant/select muxing, and in a fabric it feeds the next router, so it is the
design's critical path rather than a pin-placement artifact. The emitted,
unpipelined router is therefore a ~45 MHz design in sky130 at this
utilisation; 100 MHz needs the arbitration/select stage registered, which is a
design change and is not claimed here.

### 2026-11-13 — the emitter is what the flow and the suite agree on

- **Two rules for the portable subset, both forced by a real tool.** `automatic` is redundant in a *function* and load-bearing in a *block* (a block-scope variable is static without it, and a static one hands synthesis an undefined initial value to carry: `Conflicting init values for signal 1'0 (…candidate_dest[5] = 1'x != 1'0)` at `OPT_MERGE`). An initialised declaration inside a block is split — declaration to the block top, initialiser where it stood — because a synthesis front-end refuses the combined form. A *net* declaration is never split: `wire x = e;` is a continuous assignment, and the split form is a syntax error (`initiator_slice.sv:557: unexpected '='`).
- **Coordinate decode is seat width.** `route_destination`/`route_destination_f` return `$clog2(K*K+1)` bits, the fabric's `pd`/`row_dst`/`col_dst` are declared at that width, and `% K` / `/ K` no longer run on machine ints. The old `pd = -1` sentinel also hid a routing bug: an endpoint that maps to no router returns `K*K`, which satisfied `pd >= 0`, so the row driver could deliver an unmapped flit to column 0 of the source's own row. The sentinel is `K*K`, so both cases mean "no route".
- **Emitter-level regressions fixed while the suite ran:** the composed-slice template's decode/ordering tie-offs and the adapter assert gate are now idempotent (a re-render no longer refuses its own output); `INIT_SLICE_TEMPLATE` is a string again, not a one-element tuple; the vestigial `bready_w` wire that Verilator reported as undriven is gone.
- **Measured after all of it:** composed-family slice suite **36/37** (the one failure is the pre-existing 128-bit widened-read gap, reproduced with the portability pass switched off), portability suite **11/11** including Yosys 0.52 elaboration of the emitted fabric, and the positive evidence suite **12/12** — every family that claims `final_implementation: true` claims it from a bundle measured on these bytes.

### 2026-11-13 — four outstanding transactions per initiator, measured

- **The initiator no longer stalls per transaction.** The emitted `initiator_slice` carries a four-entry capture queue (`OUTSTANDING = 4`): `AW` and `AR` are latched with their address, length, size, ID and `seq`, and each write entry owns its own sixteen-beat `W` buffer. `awready`/`arready` are driven by queue space, `wready` by the oldest entry that still expects beats, and a separate issue engine drains the head entry in capture order. AXI-side acceptance is therefore decoupled from response latency.
- **Measured, not declared.** The emitted probe (`S15`) pushes `AW`+`W` pairs without ever raising `bready`, so the first `B` stays pending, and it counts acceptances with a `posedge` monitor on the handshake — a negedge sample of `awready` misses the one-cycle pulse and undercounts. Shipped `gec_mecs` measures **requested 4 / declared 4 / measured 4 / effective 4**, and `project_top_rtl` raises if a measurement ever exceeds the queue depth so the manifest cannot publish a limit the simulation did not observe.
- **Shipped family re-measured:** `final_implementation: true`, A1–A10 CLOSED, lint **0 warnings**, simulation PASS, **15/15** scenarios, `archive_sha256=c0c4b1c9fe7535c7379f05291071d2888481a9fb4d673eb412562f5560c8d609`.
- **Cross-clock variant re-measured:** lint 0 warnings, simulation PASS, **16/16** scenarios, queue holds 4 but the probe measures **2** concurrent acceptances. The probe logs why it stopped (`MEASURE: outstanding_stop credit_full=0 cq_count=3 cq_pend0=0 aw_busy=0 w_busy=1 aw_err=0`): credits and queue space were available, the adapter's `W` channel was not. The manifest records the measured 2 as the effective limit and says so in `ordering_realization.note`; `final_implementation` stays false there because the bundle is keyed to the shipped design hash.
- **Defects fixed while measuring:**
  1. `w_buf_q` widening. The width post-processor rewrote the new two-dimensional declaration back to `[0:15]`, which silently turned the beat-buffer write into a bit select. Only bit 0 of `adap_out_wdata` was consumed and lint caught it.
  2. Testbench name capture. The `quiesce` task declared a local `integer i`, hiding the TB-wide counter; Verilator's `VARHIDDEN` made the testbench fail to build.
  3. `wstrb` widening. The new capture-path `wstrb` check sat at a different indentation than the widened line, so 64/128-bit families would have compared a wide strobe against `4'b1111`.
- **Regressions:** composed-family slice suite **38/38**, evidence gates **14/14**.
