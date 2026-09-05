# DSE Production Tool — Calibration & Validation Plan (8055)

**Handoff doc** — written 2026-08-22 after the correctness-fix session. Everything an
agent needs to pick up the remaining work without re-deriving context.

Epic: `veritx-research-ee9d` (plan `pl-1af6`) · This doc targets **`veritx-research-8055`**
(Validation anchors) plus loose ends discovered on the way.

---

## 1. State of the world (what is DONE and verified)

All fixes below are **verified but UNCOMMITTED** — see §7 for the file list.

| Item | Seed | Evidence |
|---|---|---|
| DSE grid cache fixed (stable sha1 key; values-dict round-trip) | `3bd4` closed | key identical across processes; 6/6 cache hits |
| 2-router "packet loss" root-caused: TB reset left `clk=1`, cycle 0 had no posedge. **RTL was correct.** Fix: `top->clk=0` post-reset | `384c` closed | `inj=787 ej=787 out=0 w=0 PASS`; lost seq=1 accept_cycle=0 |
| RTL debug counters live (`ej_local_count`, `last_ej_seq`, `last_enq_seq`) | `15cd` closed | R0 inj=397/ej=390, R1 inj=390/ej=397 — cross-traffic reconciles exactly |
| 8407 scope gap implemented: `arbiter` axis → `sw_allocator`/`vc_allocator`; `workload_type` axis → llm_traffic-synthesized traces; `_config_hash` extended (was aliasing!) | `a3aa` closed | 6-point sweep distinct lats (dor+islip 34.06 … min_adapt+pim 35.58); workload physics sane (tp_allreduce lat=15.8 hops=2.8 vs moe_dispatch 33.9/6.2) |

**Key environment facts (do not re-discover):**
- Vendored BookSim2 (`third_party/booksim2/src/booksim`) is **build-artifacts only** (binary + .o, no source).
  - Allocators valid for BOTH sw+vc: `islip`, `wavefront`, `pim`. `matrix` is sw-only (VC rejects it).
  - Mesh routing registered: `dor`, `dim_order`, `min_adapt`, `planar_adapt`, `romm`, `chaos`, `adaptive_xy_yx`. **`nca` is NOT registered for mesh** (`_default_routing` maps fattree→nca only).
  - Sim-length keys: this fork has NO `sim_cycles` / `latency_thres` ("Unknown integer field"). Defaults apply; use `sample_period`/`max_samples`.
- Python 3.14 + ProcessPoolExecutor(forkserver): scripts run via stdin heredoc crash workers; any script calling `grid_search` MUST have a `if __name__ == "__main__":` guard.
- `router_template.sv` was refactored mid-session by another agent (344→509 lines: esc/free arbitration, ESC_YIELD_K starve guard, per-(out,VC) credits). Our counter fixes are re-applied on top.
- RAM rule: ONE build at a time (GATE-R1-COORD); check `bash comm/read.sh alerts` before builds.

---

## 2. ~~IMMEDIATE NEXT ACTION — fix the RTL proof leg (exit 255)~~ RESOLVED (2026-08-22)

**Finding:** The "exit 255" is BookSim's own exit code (latency threshold reached),
NOT a pipeline failure. The full pipeline completes successfully:

```
report.json: booksim_exit=255, rtl_exit=0, gate_pass=true
  30870/30870 flits matched, 79.45% exact, mean Δ +0.11
```

BookSim exits255 after printing valid stats; RTL replays and diff passes. The
`noc_frontend.py run` process exits 0. The exit255 was misleading — it appeared in
the `run_sim` print statement (`(exit {r.returncode})`) but the pipeline continued
and completed.

**Action taken:** Confirmed by running `noc_frontend.py build` + checking report.json.
No code change needed — the pipeline is functional as-is.

---

## 3. THEN — build the calibration table (the actual 8055 artifact)

Once §2 passes, produce the first real anchor artifact: **BookSim vs RTL on the same trace**.

```bash
cd tracks/t3-topology/dse
python3 recommend.py --trace inputs/test_dynamic.trace --mode grid --proof --proof-top 3
```

Write results to `tracks/t3-topology/results/dse_calibration/calibration-<date>.md`:

| config | BookSim lat (cyc) | BookSim hops | RTL replay lat | RTL flits delivered | delta % |
|---|---|---|---|---|---|
| mesh_vcs4_vcbuf8 | 24.50 | 4.45 | (from proof) | (from proof) | … |

Notes:
- Only MESH configs are provable (dse_to_frontend rejects torus/fattree — serving-leg RTL is mesh-only).
  Recommend proves best-MESH even when fattree wins the ranking; document that explicitly.
- The FlooNoC energy number in recommend.py output (`hops*64*0.15 pJ`) is the *anchor applied*,
  NOT a validation. Label it as such in the table.

---

## 4. FlooNoC leg (vendored, partially tooled)

Vendored: `floonoc/` (+ venv, floogen 0.8.4, bender checkouts, Verilator tb from earlier work:
`scripts/verilator/compile_{dut,tb}.sh`, `tb_minimal/tb_moe.sv` does AXI write cluster(0,0)→HBM(0)).

Scope for 8055:
1. Generate a 64-node fabric config matching the DSE mesh (floogen yaml akin to
   `floogen/examples/nw_mesh_xy.yml` but 8×8 clusters).
2. Drive the SAME dynamic trace through a FlooNoC TB (extend tb_moe.sv pattern:
   AXI writes per trace event, measure write-latency distribution).
3. Add columns to the calibration table: FlooNoC lat vs BookSim vs RTL.

This is the biggest remaining chunk (~a day of agent work). Do NOT attempt while
any other build is running (RAM).

## 5. gem5-Garnet leg (validator-only per D9) — DEFERRED

gem5 is NOT vendored. Building gem5 ≈ hours + several GB. Decision needed from owner:
vendor gem5 (real disk is fine, ~60G free) or drop the Garnet leg and record the
decision on seed 8055. Do not silently skip.

## 6. Open anomalies worth a look (cheap, high value)

1. **Identical latencies within topology**: on the dynamic-trace grid, ALL torus points = 22.2 cyc
   and ALL fattree points = 16.8 regardless of vcs/vc_buf. Either traffic is too light to
   differentiate buffers (plausible at IR 0.08) or routing for those topologies isn't engaging.
   One-hour check: rerun at IR 0.16/0.32 — if still flat, inspect the generated cfg
   (evaluator writes it into `.scratch/<tmp>/dse.cfg`; add `--keep` if needed).
2. **BO path ignores microarch axes**: `bo_search()` hardcodes its suggest_categorical list;
   `--microarch` only affects grid mode. Wire axes into bo_search or print a warning.
3. **1239** (surrogate on dynamic-trace data): checkpoints exist from Aug 20 but trained on
   static matrix data; regenerate dataset via `--workload-type` traces, then document test MSE.

## 6b. SOLVED since first draft — real dynamic traffic works (4f65)

The ASTRA-sim chain is live end-to-end (2026-08-22):
```
LLMServingSim → Chakra ET → AstraSim_BookSim2 (15,625,155 cyc, bit-exact vs README)
  → flit_dump 42.7M flits → scripts/astra_flitdump_to_trace.py --segment 64
  → dse/inputs/qwen3_serving_astra.trace (668K pkts × 64 flits over the REAL 15.6M-cycle window)
```
Invocation gotchas: `--booksim2-extra` is SEMICOLON-separated; run from `serving/astra-sim`;
workload path `qwen_slice/qwen_slice`, network cfg needs the `astra-sim/` prefix.
Consumed OK by roofline + run_booksim on slices; full-trace eval is heavy by nature.
Known limits filed on seed `4f65`: roofline.classify_trace super-linear (>100s @668K lines);
evaluator assumes square k×k mesh (non-square y_dim silently mismatches matrix size).

## 7. ~~Uncommitted work~~ COMMITTED (2026-08-22)

**Commit 1** `de5de55`: dse: stable cache key + microarch/workload-type/proof axes
  - `dse/{search,evaluator,recommend}.py`, `dse/objective.py`, `configs/noc_specs/mesh_k8_vcs4_ir0.08.json`

**Commit 2** `d91ca44`: rtl: VC_BUF parameterization + rtlgen R2 + TB Verilator fix
  - `rtl/{noc_pkg,router,nic,mesh}.sv`, `tb/noc_tb.sv`, `scripts/rtlgen/{router_template.sv,gen_rtl.py,axi4_flit.sv}`, `scripts/noc_frontend.py`

**Commit 3** `954b8c5`: fix(bo): dynamically include microarch axes in BO suggest_categorical
  - `dse/recommend.py`

Still dirty from OTHER sessions (do not blindly include):
`AGENTS.md`, `serving/astra-sim/build/...`, `.seeds/issues.jsonl`.

Seeds filed/closed this session: `3bd4`, `384c`, `15cd`, `a3aa` (all closed with evidence).
Still open: `8055` (this plan), `1239`, `4f65`, `b266`, `ebc4`, `T3-005`, `T3-006`, `30bd`.

## 8. Quick command reference

```bash
# microarch sweep demo (6 pts)
cd tracks/t3-topology/dse && python3 test_microarch_axes.py
# workload axis demo
python3 test_workload_axis.py
# 2-router regression (must stay PASS)
cd ../../.noc_p0/rtl2 && make && ./obj_dir/Vnoc_top
# diagnostic variant (prints LOST seqs)
g++ -O1 -std=gnu++14 -fno-pie -I obj_dir -I /usr/share/verilator/include \
  -I /usr/share/verilator/include/vltstd -c tb_diag.cpp -o diag_build/tb_diag.o
g++ -no-pie -o diag_build/Vnoc_diag diag_build/tb_diag.o diag_build/verilated*.o diag_build/verilated_vcd_c.o obj_dir/Vnoc_top__ALL.a
```
