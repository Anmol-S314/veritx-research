# Design-bound physical runner (P9)

Updated: 2026-11-13. Scope: the stage that turns an emitted NoC design into
placement, routing and signoff evidence.

## What existed before

`scripts/complete_design.py` had a physical stage that could only say
`NOT_RUN` (not requested) or `BLOCKED` with
`DESIGN_BOUND_PHYSICAL_RUNNER_NOT_WIRED`. A LibreLane spike existed at
`~/librelane-spike/project_top`, but it used a fixed copy of an old slice, so no
run there could be an implementation of the design the product emits.

## What is wired now

`tracks/t3-topology/dse/veritx_dse/product/physical_runner.py` implements the
stage against the emitted design directory:

* the RTL file list comes from the design's own `meta.json`; testbenches,
  object directories and non-RTL files are excluded;
* the top module is located by name, so a file whose first module is not the
  top (for example `initiator_slice` before `project_top`) still yields the
  correct clock ports;
* every clock-like top-level input is handed to LibreLane as `CLOCK_PORT`, so
  the two-clock slice (`clk`, `init0_clk`) is not silently constrained as one;
* the design and config hashes, LibreLane version, PDK root, tool paths and
  clock period are recorded with the metrics;
* the flow backends (`openroad`, `yosys`, `verilator`, `magic`, `netgen`,
  `klayout`) are checked before the run starts. Absent tooling is `BLOCKED`,
  never a failed-design claim.

`scripts/complete_design.py` now calls this runner and records
`physical-evidence.json` with its hash, per-gate verdicts, metrics and the
LibreLane log. `--physical-design` selects the design directory and
`--physical-clock-ns` sets the constraint.

## Gates (all must be measured and satisfied)

| Gate | Source metric | Failure mode if absent |
|---|---|---|
| unmapped cells | `design__instance_unmapped__count` | `NOT_MEASURED` |
| setup slack | `timing__setup__ws*` (worst corner) | `NOT_MEASURED` |
| hold slack | `timing__hold__ws*` (worst corner) | `NOT_MEASURED` |
| DRC | pooled `*drc*error*` / `*drc*violation*` | `NOT_MEASURED` |
| LVS | pooled `*lvs*` | `NOT_MEASURED` |
| antenna | pooled `*antenna*violation*` | `NOT_MEASURED` |

Any `NOT_MEASURED` gate fails the run. A staged invocation (`--only`) reports
`PARTIAL` and states that a staged run can never establish signoff.

Focused tests: `tracks/t3-topology/dse/tests/test_physical_runner.py` (16) and
`tests/test_complete_design.py` (47) — 63 pass.

## Environment findings (2026-11-13)

A bounded four-router design made from the shipped path was generated and
passes its own lint/simulation gates:

* `runs/physical-bounded-mesh2x2/input-request.json` — 2×2 mesh, two AXI5
  agents on one clock domain;
* `runs/physical-bounded-mesh2x2/hw-only/manifest.json` — `PASS_WITH_NOT_RUN`
  (hardware PASS, physical not requested), design hash
  `50dded4dc3a5721579d1408a2ee5df6f5784bcc09945b9a1f01b4a9a4ecffa7e`,
  design reachable at `runs/physical-bounded-mesh2x2/hw-only/hardware/rtl`
  four routers / four directed links / two VCs / depth eight.

The physical run cannot start on this host, and the reason is tooling, not the
design:

* the LibreLane install at `~/librelane-spike/.venv` is a Python 3.14 venv
  whose interpreter has no `tkinter`, so LibreLane aborts while evaluating the
  PDK config (`ModuleNotFoundError: No module named 'tkinter'`);
* the previous working install ran from `/nix/store/...python3-3.13.9-env`,
  and that nix store is gone;
* no physical backend binary is on `PATH` — `openroad`, `magic`, `netgen` and
  `klayout` are all absent, only `yosys` and `verilator` remain;
* the PDK is intact: `~/librelane-spike/pdks/sky130A` still carries
  `libs.ref` (including `sky130_sram_macros`) and `libs.tech`
  (`magic`, `netgen`, `klayout`, `openlane`).

So P9 stays `BLOCKED`, but now for a measured environment reason with the
runner, the gates and the design in place, instead of an unwired stage.
Restoring the toolchain is what remains before a real placed design exists.

## RTL defect found while preparing the physical run

Verilator's lint of the bounded design reported a real multiple-driver
condition, not a style warning:

```
%Warning-MULTIDRIVEN: project_top.sv:47:16: Bits [0:0] of signal 'noc_out_ready'
  have multiple combinational drivers
    project_top.sv:272:24: ... Location of first driver
    project_top.sv:509:24: ... Location of other driver
    project_top.sv:47:16: ... Only the first driver will be respected
```

`INIT_SLICE_TEMPLATE` in `veritx_dse/product/project_top_rtl.py` emitted
`assign noc_out_ready = noc_out_ready_tap;` twice in the same module. Synthesis
rejects multiple drivers, so this would have stopped the physical flow for a
reason unrelated to the fabric itself. The duplicate was removed (exactly one
template occurrence); the project_top-level wrapper's own assignment is a
different module and stays.

After the fix, the regenerated design
(`runs/physical-bounded-mesh2x2/hw-v2/hardware/rtl`) lints with
`MULTIDRIVEN` count 0 (was 1). The remaining lint findings are the known
`UNUSEDSIGNAL`/`UNUSEDPARAM`/`BLKSEQ` categories already recorded for this
family.

## Synthesis findings (2026-11-13)

The physical flow needs a gate-level netlist, and that is where the emitted RTL
and the available synthesizers disagree. Measured in a container with a working
LibreLane 3.0.17 + Sky130A flow (`localhost/librelane-ll`, built from
`docker.io/efabless/openlane`, which supplies `openroad`, `yosys`, `verilator`,
`magic`, `netgen` and `klayout`), running `Yosys.Synthesis` on the bounded 2x2
design:

| Attempt | Front-end error | Resolution |
|---|---|---|
| 1 | `router.sv:58: syntax error, unexpected TOK_ID` | `return <expr>;` in functions is not supported; rewritten to `<name> = <expr>;` in `tracks/t3-topology/rtl/mot_htree/router_template.sv` (8 sites, semantics identical) |
| 2 | `router.sv:840: syntax error, unexpected TOK_FINAL` | an empty `final begin ... end` debug block removed from the same template (it contained no statements) |
| 3 | `router.sv:311: ERROR: 2nd expression of procedural for-loop is not constant!` | **open** |

Front-end choice is not the issue: LibreLane's `USE_SLANG` path needs the
compiled `yosys-slang` plugin, which is not installable here (no compiler in the
toolchain image, no `yosys-slang` wheel, and the image's yosys 0.38 has neither
Python nor slang support). The plain yosys front-end is what is available, and
yosys requires constant procedural-loop conditions.

Four sites guard a loop with a live signal instead of a constant:

- `router.sv:311` `for (int _ev = 1; _ev < NUM_VCS && !esc_valid[_o]; _ev++)`
- `router.sv:425` `for (int p2 = 0; p2 < LOCAL_PORT && !ej_done_mark; p2++)`
- `router.sv:582` `for (int pass2 = NUM_VCS-1; pass2 >= 0 && !done_ej; pass2--)`
- `router.sv:587` `for (int p2 = 0; p2 <= LOCAL_PORT && !done_ej; p2++)`

Each is an early-exit scan inside the router's allocation/ejection logic. The
rewrite (constant bound plus an `if (!flag)` body guard) is semantically
plausible but touches arbitration code, so it needs its own reviewed change and
a full re-simulation, not an opportunistic edit during a physical attempt.

Consequence: the bounded design is Verilator-simulatable but **not yet
yosys-synthesizable**, so no placed-and-routed artifact exists for it. This is
the concrete blocker behind P9 now, together with the platform approval the
plan already records.

A copy-based sweep (`/home/datavex/veritx-tmp/phys-ll/src`) established the full
transform chain and where it stops:

1. `return <expr>;` in functions — fixed in the template.
2. Empty `final begin ... end` — fixed in the template.
3. Four loop conditions guarded by live signals — transform designed
   (constant bound + `if (!flag)` body guard). Equivalent on inspection, but it
   edits allocation/ejection code.
4. Two `continue;` statements — the same treatment (`if (<inverse cond>) begin`
   around the rest of the loop body).
5. Declarations with initializers inside procedural blocks
   (`automatic logic [N-1:0] v = expr;`) — yosys rejects them, and the naive
   fix (declaration plus assignment) makes SystemVerilog illegal because a later
   `logic x;` in the same block then follows a statement. The real fix is a
   declarations-first cleanup of those blocks.
6. `$time` inside an unguarded `$display` diagnostic — needs the diagnostic
   guarded (`` `ifndef SYNTHESIS ``) rather than stripped; a blanket strip of
   `$display` statements also breaks those blocks for the same
   declaration-order reason as (5).

Steps 3-6 are a real RTL cleanup of the router's allocation, ejection and
enqueue blocks. They must land as a reviewed change with a full re-simulation,
not as opportunistic edits during a physical attempt.

## Environment note (2026-11-13)

The host hit an XFS project quota (`OSError: [Errno 122] Disk quota exceeded`)
while a 27-test slice sweep was running, which produced 27 spurious Verilator
build failures and also killed in-flight background runs. After clearing the
old spike scratch directories the same suite passes (`test_composed_family_lints_and_sims`:
12/12 families lint and simulate). Failures that report `Disk quota exceeded`
are environment failures, not RTL regressions, and must be re-run before they
are counted either way.

## Historical note on the old spike

The spike reached `openroad-resizertimingpostcts` at a 10 ns constraint with
continuous negative slack (worst reported slack around −11 ns, TNS about −1.6e5
in the resizer report) before it was stopped, and its first attempt failed
synthesis with 12 unmapped Yosys instances. Neither outcome says anything about
the currently emitted design; both are recorded here only so the old spike is
never cited as design-bound evidence.

## Toolchain skew in the LibreLane image

The flow image installs a current LibreLane over an older OpenROAD and Yosys.
Seven report/helper statements in the LibreLane scripts assume the newer
binaries, so the image carries these local edits:

| file | edit | why |
| --- | --- | --- |
| `scripts/openroad/sta/corner.tcl` | drop `-group_path_count` from `report_checks`/`find_timing_paths` | the bundled OpenROAD does not accept the flag |
| `scripts/openroad/sta/corner.tcl` | `_corner_clock_is_propagated` helper, `catch` around the clock report blocks | `is_propagated`/`is_virtual`/`is_generated` properties are missing |
| `scripts/openroad/common/set_global_connections.tcl` | `global_connect` called without arguments when `-verbose` is rejected | older OpenROAD takes no arguments |
| `scripts/openroad/sta/corner.tcl` | `est::check_corner_wire_cap` queried through `catch` | the estimate API is missing |
| `scripts/openroad/cts.tcl` | the two buffer-derate options are not passed; `-apply_ndr` is passed as a flag | the bundled OpenROAD has neither option and rejects the trailing value |
| `bin/yosys` | shim over the `pyosys` bindings (`-y` script mode and `-p` pass mode) | the image publishes Yosys only as a Python module |

None of these changes synthesis or steering: they make the bundled reporting
scripts run on the bundled binaries. The netlist, the SDC and the numbers the
flow reports come from the real tools.

The flow is also given a hand-written SDC (`dual-clock.sdc`) because the base
SDC constrains only the first entry of `CLOCK_PORT`, which would leave the AXI
clock domain unchecked on a two-clock design.
