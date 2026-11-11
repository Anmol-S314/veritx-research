# Handoff — `final_implementation` closure, 2026-11-11

**Goal.** Get the emitted manifests to carry `final_implementation: true` **honestly** — the flag must follow the acceptance checklist and measured evidence, never be asserted.

**Where the flag lives.** `tracks/t3-topology/dse/veritx_dse/product/final_implementation.py` computes it. `scope_evidence.py` gathers the per-row evidence. `project_top_rtl.py::_composed_family_verdict_for_manifest` assembles the manifest's verdict: rows A1/A2/A4/A5 come from the run's own lint/sim/scenarios, A6/A7 from the run's proofs, and A3/A8/A9/A10 are merged from the **evidence bundle** the release run wrote (`docs/product/evidence/final-implementation/<family>.json`, keyed to `request.design_hash()`, so stale evidence cannot carry the flag). A11/A12 are closed by the recorded scope-out decision in `docs/product/evidence/physical-scope-out.json`.

**Verdict rule.** Every row must be CLOSED or SCOPED_OUT; any OPEN row keeps the flag false; preview scopes never carry it.

---

## Done in this session

### 1. Credit accounting: the tap index was truncated (fixed)

`gec_mecs_credited.py` took the **tap index** for the credit pool from the template's `row_vc`/`col_vc` outputs — but those ports are **2 bits** wide, because the native GEC-MECS design has three taps per wire and encodes the tap in the VC ("one VC per tap"). A scalable shape has five taps (`TAP_W = 3`), so the tap index was truncated: **tap 4 became tap 0**.

The failure was asymmetric and therefore silent: the **claim** side read the truncated value and charged the wrong (tap, VC) pool; the **release** side recomputed the index from the topology and returned the credit to the pool it was *not* charged to. That pool's `outstanding` decremented from zero and wrapped (0 → 15 in a 4-bit field), so the aggregate read 81 outstanding against a capacity of 4.

It reproduced only at five taps or more — which is why the small shape passed and the 36- and 81-router shapes failed.

**The arithmetic that identified it:** a sound pool satisfies `available + outstanding == capacity` per (tap, VC). The observed 99 + 81 against a capacity of 100 is exactly five pools that underflowed.

**Fix** (`tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py`): take the tap index from the TAP_W-wide `drop_idx` directly; leave the template's 2-bit `row_vc`/`col_vc` outputs at their native width and meaning. The credit path no longer depends on a port whose width the template chose for a different design.

**Verified:** `tests/test_gec_mecs_scaled.py` 5/5 pass (was 1 failure); `tests/test_gec_mecs_credited_fabric.py` 9/10 pass (the one failure was the build timeout below, not a credit assertion); `tests/test_gec_mecs_pinned_shape.py` **1 passed** in 908 s once the timeout was raised (it was failing on the timeout alone).

### 2. Composed family: the testbench's stale-response check fired a cycle early (fixed)

`tests/test_project_top_slice.py` went from **20 failed / 18 passed** to **36 passed / 2 failed**.

The composed testbench was rewritten (by a session that has since stopped) to assert the AXI handshake more strictly, adding *stale B/R after handshake* checks. The checks sampled the response **one clock too early**: the AXI adapter's B/R stage register retires on the *next* edge, so `bvalid` was still high when the check looked at it.

**Fix** (`project_top_rtl.py`, the composed testbench generator): give the response one more clock to retire before the stale check — one extra `@(posedge clk); @(negedge clk);` before each of the two checks.

Isolated by bisection: new adapter + old TB → PASS; old adapter + new TB → FAIL; the TB was the sole cause.

### 3. Shared-fabric build timeout was far too tight (fixed)

The 81-router credited fabric takes **~14.5 minutes** to compile (measured: Verilator walltime 869 s, 212 MB of C++), but the shared-fabric build had a **300 s** timeout. Raised 300 s → **1800 s** at the three `obj_shared` build sites in `project_top_rtl.py`.

**Verified:** `tests/test_gec_mecs_pinned_shape.py` now passes (1 passed, 908 s) where it previously died on the timeout.

### 4. A8 parity caller passed an object, not an AnyNet path (fixed 2026-11-11 19:00)

`tests/test_final_implementation_evidence.py::_row_parity` passed
`compiled.bundle.topology` (a `TopologyArtifact`) as `network_file`. BookSim
therefore read a bogus path and exited before loading the trace; the parser then
reported the misleading `missing required trace evidence 'Loaded text trace: N
packets'`. The harness was correct; the caller was not.

The row now writes a real 2x2 AnyNet file, emits the RTL with
`tracks/t3-topology/scripts/rtlgen/gen_rtl.py`, and runs the parity smoke
against it. Measured: **CLOSED** — BookSim drain 20 cycles, RTL 17, delta 3,
payload parity exact, both sides conserve.

### 5. Slice template's "single generate block" assumption (fixed 2026-11-11 19:05)

After the `payload_field` accessors were added, the two known-failing slice
tests moved to a new defect: `_apply_axi5_adapter_tieoffs_to_slice` required
exactly one `endgenerate`, but the template now has two generate blocks
(adapter select + CDC crossover). It refused every widened slice with
`UNSUPPORTED_SLICE_PROFILE`. The sink is now inserted after the **first**
`endgenerate` (the adapter block) and the guard only requires one to exist.
`tests/test_project_top_slice.py -k
"parameterized_width_and_vc4_composes or vc4_cycles_ejection"`: **2 passed**.

### 6. Composed-family lint warnings: mesh now clean (2026-11-11 19:06)

Three real emitter defects were producing the A2 warnings:

- dead `unused_noc_out_* = noc_out_flit_*` assignments left bits [63:1]
  unused; now a reduction sink `&{1'b0, flit}` consumes every bit;
- the router's ascending packed port vectors tripped `ASCRANGE`; scoped
  `lint_off`/`lint_on` with the reason (port index is the bit position);
- `FLIT_W` / `FT_BODY` are shared package parameters unused by some families;
  scoped `UNUSEDPARAM` waivers.

Measured mesh run: **lint PASS, 0 warnings, 13/13 scenarios, sim PASS**
(`/tmp/opencode/mesh-a2b-s7mwchmu`). The manifest verdict now has only A8 open
for mesh; the remaining families still need the same sweep.

---

## Still open

### A. Composed-slice `payload_field` failure — **FIXED 2026-11-11 19:05**

The `payload_field` / `type_field` / `vc_field` properties now exist on
`SliceParams` (`project_top_rtl.py:291`), so the original `AttributeError` is
gone. The follow-on "generate block changed shape" refusal (two generate
blocks, one expected) is fixed in item 5 above.
`test_parameterized_width_and_vc4_composes` and `test_vc4_cycles_ejection`:
**2 passed**.

### B. Composed lint warnings — mesh clean, other families pending

`scope_evidence.row_from_lint_sim` closes A2 only when the lint log has **zero**
`%Warning` lines. After the three emitter fixes in item 6 above, the mesh
composed top measures **0 warnings** (was 133; the older handoff recorded 534
for the GEC connected scope). The concrete categories in the mesh log were:

| count | category | disposition |
|---|---|---|
| 127 | `UNUSEDSIGNAL` | fixed: reduction sinks consume every flit bit |
| 4 | `ASCRANGE` | waived by name: ascending port ranges are deliberate |
| 2 | `UNUSEDPARAM` | waived by name: shared package parameters |

**Still open:** run the same sweep across the other nine composed families and
the GEC/SROTA connected scopes. The GEC connected build's 272 warnings
(164 `PINMISSING`, 26 `UNDRIVEN`, …) are real wiring gaps, not this lint
noise, and need pin-level fixes or named waivers.
`tests/test_scope_evidence_lint.py` still pins the rule: `UNUSEDSIGNAL`,
`UNDRIVEN`, `WIDTH`, `LATCH` each keep A2 open.

### C. A8 parity harness — **FIXED 2026-11-11 19:00**

The failure was the caller, not the harness: `_row_parity` passed a
`TopologyArtifact` object as `network_file`, so BookSim died before loading the
trace. It now writes a real AnyNet file and emits the RTL first. Measured
**CLOSED**: BookSim 20 cycles / RTL 17, delta 3, payloads exact, conservation on
both sides.

### D. The evidence bundle must be written before a release run can close A3/A8/A9/A10

The positive pass now exists at
`tests/test_final_implementation_evidence_positive.py`: it measures the
family emission (A1/A2/A4/A5) plus A3/A6/A7/A8/A9/A10, writes
`docs/product/evidence/final-implementation/<family>.json` keyed to
`request.design_hash()`, and asserts the verdict closes. The older
`tests/test_final_implementation_evidence.py` remains the negative gate and is
isolated to a temp `BUNDLE_DIR` so it cannot overwrite positive evidence.
`tests/test_final_implementation_evidence.py::test_recorded_bundles_close_the_flag_for_measured_families`
also re-reads the committed bundles and asserts the 12 closed families still
evaluate true.

The 10 composed families are in `COMPOSED_FAMILIES` at the bottom of that test file.

**2026-11-11 update:** the negative test no longer writes the production
bundles — that was why every family read `A2 OPEN — no simulation scenarios
supplied`; it now monkeypatches `BUNDLE_DIR` to a temp directory. The `mesh`
bundle was re-measured positively (A2 from a fresh 0-warning/13-scenario run,
A10 from the repaired multi-flit test, A8 from the repaired parity caller) and
`composed_family_verdict` now returns `final_implementation: true` with
`open_rows: []`. A fresh composed run confirms it. The full sweep then closed
the same rows for all ten composed families; GEC-MECS and KNCube were added to
the bundle set with A3/A7 measured directly, so **12 of 14 families now carry
`final_implementation: true`**. `fly`'s A7 refusal was a proof-domain bug: it
proved a non-existent escape class for a 1-VC family and walked routes between
routers that can never hold an endpoint. The proof now uses the real
ingress↔egress terminal pairs and passes unbounded (512 edges / 256 channels).
GEC-hybrid and SROTA remain false under their Scope B claim lists.

### E. The release matrix must be re-run and its manifests checked

`python3 scripts/complete_design.py --release --out <dir>` — then read each family's `project-top-manifest.json` and confirm `final_implementation: true` with `final_implementation_verdict.open_rows == []`.

**Caution:** the earlier 14-family green matrix (2026-11-11 01:32) predates the credit fix, the composed-TB change and the multi-flit destination adapter. It must be re-run, not trusted.

**2026-11-11 20:34 result:** `release-final2-20261111T203409Z` completed
**14/14 family rows PASS** with **12/14 `final_implementation: true` and
`open_rows: []`** — mesh, torus, concentrated_mesh, ring, fly, qtree, tree4,
flatfly, fattree, dragonflynew, GEC-MECS and KNCube. Result is
`PASS_WITH_NOT_RUN`: physical is `NOT_RUN`, and the KNCube
native-equivalence blocker is recorded. GEC-hybrid (19 warnings) and SROTA
(12 warnings) remain `false` under their Scope B claim lists. The earlier
`release-final-20261111T201508Z` matrix is the same 14/14 rows with the ten
composed families true; it predates the GEC-MECS and KNCube bundle writes.

---

## Constraints and environment

- **Gate scratch must live outside the repo**: `TMPDIR=/home/datavex/veritx-tmp`. A repo-local `TMPDIR` breaks the BookSim verification gates.
- **Heavy work runs sequentially.** The 81-router Verilator build alone takes ~15 min and ~2.4 GB.
- **Cleanup**: `bash scripts/cleanup_runs.sh` (the user asked for regenerable run artifacts to be deleted promptly). Do **not** delete `docs/product/evidence/` — that is the evidence the flag rests on.
- **The tree is uncommitted** (huge dirty tree); `project_top_rtl.py` and the other product modules are **untracked**, so `git diff` cannot compare them against HEAD. Compare emitted artifacts instead: the 01:32 green release is preserved at `/home/datavex/veritx-tmp/release/<family>/rtl/`.
- The whole `tracks/t3-topology/dse` suite is run from `tracks/t3-topology/dse` with `PYTHONPATH=.`.
- All other sessions have stopped; the tree is now owned by one session.

## Useful commands

```bash
cd tracks/t3-topology/dse
PYTHONPATH=. TMPDIR=/home/datavex/veritx-tmp python3 -m pytest -q tests/test_project_top_slice.py
PYTHONPATH=. TMPDIR=/home/datavex/veritx-tmp python3 -m pytest -q tests/test_gec_mecs_scaled.py
PYTHONPATH=. TMPDIR=/home/datavex/veritx-tmp python3 -m pytest -q tests/test_final_implementation_evidence.py
```

## Files that matter

| file | what it does |
|---|---|
| `tracks/t3-topology/dse/veritx_dse/product/final_implementation.py` | computes the flag from evidence |
| `tracks/t3-topology/dse/veritx_dse/product/scope_evidence.py` | gathers per-row evidence; bundle read/write |
| `tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py` | emits the RTL, the TB and the manifest verdict |
| `tracks/t3-topology/dse/veritx_dse/product/gec_mecs_credited.py` | the credited shared fabric (the tap-truncation fix) |
| `tracks/t3-topology/dse/tests/test_final_implementation_evidence.py` | measures the rows and writes the bundles |
| `docs/product/FINAL-IMPLEMENTATION-TRUE.md` | the acceptance contract (A1..A12) |
| `docs/product/proposals/P4-4-3-credit-wiring-spec.md` | the credit wiring, and the tap-truncation defect record |
| `docs/product/evidence/physical-scope-out.json` | the recorded A11/A12 scope-out decision |

## Verdict rules that must not be bent

- A row without a checkable artifact **stays OPEN**.
- The evidence bundle is keyed to the design hash — a bundle measured on another design is ignored.
- The scope-out decision **scopes the claim**; it does not manufacture evidence, and A11/A12 stay visible as open in the verdict.
- No typed refusals for the 14 topology families (all compose, lint and simulate).
