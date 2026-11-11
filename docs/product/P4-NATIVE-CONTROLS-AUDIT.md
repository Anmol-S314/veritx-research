# P4 — packet router / native controls audit
**Date:** 2026-11-10 · **Scope:** INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md §P4 rows 4.1–4.12
**Repo root:** /home/datavex/bruh/veritx-research
**Method:** read-only source audit; no builds/lints/sims executed. Every verdict names the
file and the function/string, or the refusal constant, that proves it. RTL embedded as
single-line Python string literals is cited by parameter/token name (line = its definition).
**Verdict scale:** IMPLEMENTED = code + integration evidence that the pass condition holds ·
BUILT-NOT-VERIFIED = code exists, pass condition unproven · MISSING = not present/refused/unwired.

## 0. Product artifact inventory (what "the router" is in this tree)
| Artifact | Path | Notes |
|---|---|---|
| Composed-family unified router | `tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py:4991` (`_UNIFIED_ROUTER_TEMPLATE`, params substituted at `:5041-5081` in `_render_family_router`) | Only product RTL with wormhole reservation, per-port/VC queues, credits, iSLIP-flag, hybrid-UGAL, SROTA kernel (Valiant/rank/island), side buffer, PLANE_D_END |
| Family pkg + type fields | `_render_family_pkg` `:4942-4990` (`FT_HEAD/BODY/TAIL/SINGLE` `:4970-4973`, `BLOCK_K` `:4968`) | |
| Composed-family top/TB | `render_family_project_top` `:5845-5990`, `render_family_tb` `:6028-6365`, `run_composed_family` `:6381-6553` | TB checks 32-bit AXI beats + SINGLE flits only; manifest `final_implementation: False` (`:6545`) |
| Certified slice router (4×4 mesh, 2-VC free/escape) | emitted by `tracks/t3-topology/scripts/rtlgen/gen_rtl.py` from `tracks/t3-topology/rtl/mot_htree/` (`router_template.sv` 842 ln, `gen_rtl_htree.py`, `noc_pkg.sv`); product seam `veritx_dse/product/rtl_export.py` | demotion ACTIVE in emitted `scripts/rtlgen/router.sv` (~ln 496); DISABLED (`if (0 && ...)` ln 686) in the `rtl/mot_htree/router_template.sv` reference copy |
| Slice TB | `project_top_rtl.py` `_render_tb_project_top_locked` (`NOT_RUN:` list `:3230-3242`) | |
| Shared pinned tops (single-flit prototypes) | `GEC_MECS_FABRIC_SV:6837`/TB `:7056`; `SROTA_FABRIC_SV:7242`/TB `:7629`; `GEC_HYBRID_FABRIC_SV:7860` (+TB inside) | each 1-flit stage/port, no per-VC queues/credits; `run_gec_mecs_shared` `:8760`, `run_srota_shared` `:8827`, `run_hybrid_shared` `:8894` |
| Shared-VC/hybrid model (Python) | `veritx_dse/product/clock_power_cdc.py` (`hybrid_select:53`, `hybrid_native_choice:63`, `hybrid_used_credit:36`, `hybrid_credit_visible_cycle:49`) | selector math only — plan calls this supplemental |
| Model controls | `veritx_dse/model/noc_controls.py` (`NocControls`, `ROUTER_CONTROL_FIELDS:109`), `veritx_dse/model/router_behavior.py` (`RouterBehaviorArtifact`, defaults `:19-27`) | behavior→hash bound to bundle; slice/family paths read it differently |
| UNREALIZED constant | `veritx_dse/product/project_top_rtl.py:74-78` `UNREALIZED_ROUTER_CONTROLS = (credit_return_latency_cycles, allocator_iterations, route_compute_cycles, vc_alloc_cycles, switch_alloc_cycles, switch_traversal_cycles)` | slice refuses any declared knob (`:561-569`); asserted by `tests/test_p8_mesh2x2_contention.py:85-87` and `test_project_top_slice.py:108+153` |
| Research RTL (NOT product-wired) | `tracks/t3-topology/rtl/t3/` (iSLIP VA/SA `router.sv`+`islip.sv`), `rtl/srota/` (`srota_fiu_pathsel.sv` flow-epoch cache, `srota_sidebuf.sv`, `srota_credit_mgr.sv`), `mot_htree/islip.sv` (standalone) | see per-row notes |

## 1. Row verdicts
| Row | Verdict | One-line proof |
|---|---|---|
| 4.1 framing / full-width | **BUILT-NOT-VERIFIED** | framing in `_UNIFIED_ROUTER_TEMPLATE` + `FT_*` pkg; **zero multi-flit integration test**; `NOT_RUN: HEAD/BODY/TAIL` `:3239` |
| 4.2 per-port/VC queues, real output storage | **BUILT-NOT-VERIFIED** | `q[NUM_PORTS*NUM_VCS][BUF_DEPTH]`, `out_r/out_vld/out_hold/(port,VC)` in template; declared `output_stage_depth_flits_per_vc` never consumed (stage is hard-wired 1 flit); shared tops have no queues |
| 4.3 free credits / delayed returns / tap alias | **BUILT-NOT-VERIFIED** | `cred[port][vc]` in template/mot_htree; invariant free+in-flight==capacity never checked (`NOT_RUN: credit-pool balance` `:3237`); LAT≥2 credit return path broken by code read |
| 4.4 output ownership for whole packet / tail release | **BUILT-NOT-VERIFIED** | `rt_alloc/rt_out` continuity in template (+ mot_htree `:76-84,516-524,556-564,612-615`); switch lock `HOLD_SWITCH`; no multi-flit test; `release_on_tail_send` credit path dead |
| 4.5 allocation, iteration count, switch locking | **BUILT-NOT-VERIFIED** (iteration count **MISSING**) | grant stage template (esc-first + `esc_starve` yield, `ALLOCATOR_AGE`/first-match); `ALLOCATOR_ISLIP`/`ALLOC_ITER` params **dead**; `rr_ptr/rr_acc` write-only; no directed test |
| 4.6 declared route/alloc/switch/output delays | **MISSING** | `UNREALIZED_ROUTER_CONTROLS` `:74-78`; slice refusal `:561-569`; family consumption is a `q_age >= ROUTE_CYCLES+VC_ALLOC_CYCLES` gate (not a pipeline); `router_timing_model` `:4401` has **no callers**; no directed timing test exists |
| 4.7 hybrid selection vs real per-port/per-drop credits | **BUILT-NOT-VERIFIED** | selector in template (`used_mesh/used_mecs`, ties→express) reads real `cred` but **per output port, not per drop**; `gec_hybrid16_fabric` credits are **0/1 synthesized from `node_dbg_valid_q`**, single-flit stage; pinned 6VC/8flit/48flit/latency-1 contract unrealized in RTL; `GEC_HYBRID_BLOCKER = GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED` `:6566` |
| 4.8 SROTA flow cache & telemetry | **MISSING** | refusal `SROTA_TELEMETRY_BLOCKER = SROTA_TELEMETRY_NOT_MODELED` `:6580,6733-6734`; no hash/bank/epoch/sampling/publication delay in any product artifact; research leaf `rtl/srota/srota_fiu_pathsel.sv` **not wired** (README §Integration limits) |
| 4.9 shape / Valiant intermediate / leg / rank / island | **BUILT-NOT-VERIFIED** | `ker_step()` kernel rewrite in template; `SHAPE_TAB` from island cols (`_family_full_tables:4931-4940`); valiant/rank **refused** in pinned SROTA top (`SROTA_VALIANT_BLOCKER`, `:6739-6744`); injection/transit agreement & stall-stability never exercised |
| 4.10 enabled side-buffer admission/drain/watermarks | **MISSING** | pinned SROTA refuses (`SROTA_SIDEBUT_BLOCKER`); unified-template side-admit path broken by code read (`in_side_ready` never exported → same flit copied to `side_q` every cycle); no side slots' credits; research `srota_sidebuf.sv` unwired |
| 4.11 control/telemetry planes, independent | **MISSING** | model `model/multi_plane_vc.py` (MultiPlaneVCAssignment) exists, **zero product wiring**; pinned top refuses planes≠`{d}` (`:6733-6734`); `PLANE_D_END` is only an escape-demotion VC filter |
| 4.12 explicit reset for buffers / ownership / caches / planes | **BUILT-NOT-VERIFIED** | template resets q_cnt/q_age/rt_alloc/rt_out/esc_mode/lock_*/side_*/cred/out_vld on `!rst_n`; payload contents not cleared (occupancy-tracked); **no reset-epoch test** through any instantiated router; nothing exists (caches/planes) to reset |

**No P4 row is IMPLEMENTED.** Recorded (not re-verified here) L1 results: mesh 38/38, S26/S27 contention, torus/ring/flatfly/dragonflynew/srota/mecs/hybrid sim PASS, 36-router GEC credit-router baseline 32×32 (recorded, `PROGRESS.md:148`; completion plan ~L590). None of those exercise multi-flit packets, credit pools across taps, or the pinned 81-router scale.

## 2. Per-row evidence

### 4.1 HEAD/BODY/TAIL/SINGLE framing — BUILT-NOT-VERIFIED
- RTL: framing constants/types `_render_family_pkg:4970-4973`; `is_head/is_tail` (template);
  mot_htree `router_template.sv:49-53,129-137`; transfer of full FLIT_W via `q` arrays.
- Product never emits multi-flit packets anywhere: slice `multi_flit_policy: "stay single-flit"`
  (`:3994`), `NOT_ESTABLISHED` "HEAD/BODY/TAIL wormhole packets and flit reassembly … not
  exercised" (`:100-105`), TB `NOT_RUN: HEAD/BODY/TAIL wormhole packet interleaving … missing
  primitive SLICE_MULTI_FLIT` (`:3239`), family TB injects SINGLE flits only (32-bit rdata checks),
  initiators emit 1 beat = 1 SINGLE.
- **High bits:** never asserted (payload checks are 32-bit; DST/VC/type fields never checked at
  upper FLIT_W bits). **Partial final beats:** no implementation, no test anywhere.
- Shared fabrics declare "Configured multi-flit framing … not established; single-flit unicast
  prototype only" (`GEC_MECS_SHARED_NOT_ESTABLISHED:6594-6599`, `SROTA_…:6606-6612`,
  `GEC_HYBRID_SHARED_NOT_ESTABLISHED:6620-6625`).
- `packet_format.py` FLIT_TYPE_ENCODING + `test_packet_format.py` are model-level, supplemental.

### 4.2 SEPARATE input-port/VC queues + real output storage — BUILT-NOT-VERIFIED
- Implemented: `q [NUM_PORTS*NUM_VCS][BUF_DEPTH]`, `q_cnt`, per-VC escape-VC handling, registered
  per-(output port, VC) stage `out_r/out_vld/out_hold` (template); same in mot_htree/scripts
  (`q` `router_template.sv:65-66`, `out_r` `:114`, per-VC stages `:494-570`).
- Declared-vs-usable mismatch: `input_buffer_depth_flits_per_vc` → `BUF_DEPTH` (pkg) ✔ matches;
  **`output_stage_depth_flits_per_vc` never reaches the RTL** — no parameter; the stage is always
  exactly 1 flit/(port,VC). Silent deviation whenever declared≠1 (default=1 hides it). No refusal.
- Shared tops: `gec_mecs_router/gec_hybrid_router/srota_composed_router` hold one `flit_q` per
  port + `valid_q` — **no VC-indexed storage at all**; the 48-flit/6VC/8-flit-per-VC pin exists
  only in the Python pin (`clock_power_cdc.py:14-35`), never synthesized as RTL storage.

### 4.3 FREE-CREDITS / delayed returns / tap-VC alias — BUILT-NOT-VERIFIED
- Implemented: `cred[0:NUM_PORTS-1][0:NUM_VCS-1]`, `BUF_DEPTH` init (template reset), −1 at
  grant load, `+` through `cred_hist` at accept; mot_htree equivalent `:90-101,457-458,498-510`.
- Never proven: slice TB `NOT_RUN: credit-pool balance free+inflight==capacity … no credit tap
  port (missing primitive SLICE_CREDIT_TAP)` (`:3237`); family path has no SVA and no observation
  tap; mot_htree SVA exists but only under `SIM_FORMAL` (any test exercise: none found —
  `grep SIM_FORMAL tests/` empty).
- **Code-read defect:** credit return only executes under `VC_REUSE_TAIL_CREDIT != 0`
  (wait_for_tail_credit); `release_on_tail_send` ⇒ `VC_REUSE_TAIL_CREDIT = 0` ⇒ **credits never
  return** (`_render_family_router:5007`; template accept branch). And for
  `CREDIT_RETURN_LATENCY ≥ 2` the `cred_hist` shift iterates only `LAT-1` slots so the tapped
  entry (`LAT-1`) is never written ⇒ credits never return for LAT≥2 as well (only LAT=1, the
  default/pin, functions). LAT=0 over-returns (unclamped cumulative `cred_hist[0]`). No test hits
  these; the slice path is saved only by refusing the knob outright
  (`UNREALIZED_ROUTER_CONTROLS`, `:74-78,561-569`; refusal asserted at
  `test_project_top_slice.py:108,153-167` and `test_p8_mesh2x2_contention.py:85-87`); the family
  path does **not** refuse LAT≥2 (passes it straight into `CREDIT_RETURN_LATENCY`).
- Tap alias: no artifact carries per-tap credit pools; GEC-MECS shared fabric has **no credit
  counters** (credits are 0/1 from neighbor `node_dbg_valid_q` — code read, `GEC_HYBRID_FABRIC_SV`
  ~ln 8300-8371 of the single-line literal); no check exists for alias across taps/VCs.
- Recorded evidence outside this checkout: 36-router GEC credit-router 32×32 sweep + stalls +
  contention + reset **PASS**, 12 GiB, `execution/credit-gec-v18-baseline-12g/runs/attempt-1/receipt.json`
  (PROGRESS.md:148; completion plan §P3-ish ~line 590). "No 81-router simulation pass is claimed."

### 4.4 OUTPUT OWNERSHIP for the entire packet — BUILT-NOT-VERIFIED
- Implemented: head grant sets `rt_alloc/rt_out`; `cand_out` follows `rt_out` while `rt_alloc`
  (template); TAIL/SINGLE dequeue clears `rt_alloc`/`esc_mode`; switch lock `HOLD_SWITCH` →
  `lock_active/lock_owner/lock_vc`, checked in candidate predicates (`lock_ok`), cleared on tail;
  mot_htree equivalent (`:76-84,516-524,556-564,608-615`).
- Unproven: no HEAD/BODY/TAIL packet is ever injected in any product test (see 4.1) → "BODY/TAIL
  follow their head" is untested through an instantiated router; tail-credit VC-reuse semantics
  ("VC allocation held until tail **credit** returns") are **not implemented** — `rt_alloc` clears
  at tail *send*, irrespective of credit; configured `release_on_tail_send` kills credit return
  (see 4.3) — so only `wait_for_tail_credit` is functional, and that only for LAT=1.
- OrderingFSM (`product/ordering_fsm_rtl.py`, `build_ordering_fsm`/`render_ordering_fsm`) is
  endpoint-side; unrelated to router output ownership.

### 4.5 ALLOCATION / iteration count / switch locking — BUILT-NOT-VERIFIED (iteration count MISSING)
- Implemented grant stage (template): per-output esc-first + free-class stages, `ESC_YIELD_K=4`
  starvation guard via `esc_starve`, `ALLOCATOR_AGE` oldest-`q_age` pick else first-match;
  distinct VC classes ⇒ no duplicate grant by construction; switch lock honored (`lock_ok`);
  ejection scan esc-class-first.
- **iSLIP not realized:** `ALLOCATOR_ISLIP` and `ALLOC_ITER` parameters declared, **never
  consumed** (occurrence count 1 = declaration); `rr_ptr/rr_acc` are write-only (never read for
  selection — in mot_htree, rr_ptr *is* read, `:324-325`). The declared default allocator is
  ISLIP (`router_behavior.py:104, derive_router_behavior` → ISLIP; `qualify_router_controls`
  demands ISLIP for BookSim) — the slice refuses `arbitration="islip"` outright (`:580-586`;
  test `test_project_top_slice.py:109+151-167`), and the family path **silently emits
  first-match/age with `ALLOCATOR_ISLIP=1` dead** (`_render_family_router:5008`,
  `arb_policy == ASLIP` `:4670-4678`) — a silent substitution, against the product's own rule.
- `tracks/t3-topology/rtl/t3/` has a real iSLIP VA/SA router (`router.sv`, `islip.sv`) —
  RETAIN_RESEARCH, known-broken multicast corners, not product-wired (README; `test_uvm_dut_binding.py`
  lints/binds only).
- Eligible-competitor service: starvation guard exists; **no directed test** proves it; no formal
  property exercised (mot_htree SVA `S5` explicitly unenforced).

### 4.6 DECLARED route/alloc/switch/output delays — MISSING
- `UNREALIZED_ROUTER_CONTROLS:74-78`; slice refusal message at `:565-569` ("no pipeline
  re-timing … the slice refuses instead of composing a router with different timing than
  declared"); declared latency knob ⇒ `UNSUPPORTED_SLICE_PROFILE` (test `:108`), asserted
  `test_p8_mesh2x2_contention.py:85-87`.
- Family path consumption is a gate, not a pipeline: `q_age[c] >= ROUTE_CYCLES + VC_ALLOC_CYCLES`
  before eligibility (template); `SWITCH_TRAVERSAL + OUTPUT_DELAY` = `out_hold` countdown before
  `out_valid`; **`SWITCH_ALLOC_CYCLES` declared, never consumed**; **`ALLOC_ITER` declared, never
  consumed**; `CREDIT_RETURN_LATENCY` only LAT=1 functional (code read); `ROUTE_CYCLES` substituted
  but never a real route-compute stage.
- `router_timing_model` `project_top_rtl.py:4401-4442` is **exported, never called** (grep finds no
  call sites); analytic expectation only, and explicitly **not** "directed timing tests … actual
  configured stage behavior".
- No test anywhere measures configured stage timing (grep `credit|latency|timing|alloc` across
  `tests/` finds only refusals and manifest fields). Shared tops have no delay pipeline at all.

### 4.7 HYBRID selection vs real per-port/per-drop credit state — BUILT-NOT-VERIFIED
- Comparison/tie rule: implemented in template UGAL branch —
  `used_mesh = BUF_DEPTH - cred[p_mesh][0]`, `used_mecs = BUF_DEPTH - cred[p_mecs][ESC_VC]`,
  `cost_mesh = used_mesh × get_dist(dst)`, express iff `used_mecs <= cost_mesh` ⇒ **ties choose
  MECS (express)**; consistent with native model `clock_power_cdc.py hybrid_select:53-62 /
  hybrid_native_choice:63-68` (`<` strict ⇒ ties→mecs) and with
  `test_project_top_shared.py:227-259` (exhaustive 200+ cases incl. tie list) — *supplemental
  selector math, explicitly not the integration result.*
- Real **per-port**, real counters (family path) — but **not per-drop/tap** and express only via
  `ESC_VC`; remaining-distance uses `get_dist` (RT_DIST table).
- Shared `gec_hybrid16_fabric` (`GEC_HYBRID_FABRIC_SV:7860`): `take_mesh = (mesh_credit_val *
  mesh_h < mecs_credit_val)` — **inputs `west_credit…col_credit2` are `6'd1/6'd0` synthesized from
  neighbor `node_dbg_valid_q`** (fabric top), i.e., a nonempty-stage proxy, **not occupancy
  counters** and **not the pinned 6VC/8-flit/48-flit/latency-1 buffer** (router here = 1 flit/port).
  TB reads those wires to predict selector outcomes (`selector_tie`); recorded PASS in
  `test_project_top_shared.py:287-305` and `GEC_HYBRID_SHARED_PROVEN:6613-6619` — **recorded,
  not re-verified here**, and it validates consistency with the proxy, not real credit state.
- Refusal standing for the pinned observability contract: `GEC_HYBRID_BLOCKER =
  "GEC_HYBRID_CREDIT_OBSERVABILITY_CONTRACT_UNVERIFIED"` `:6566` (raised only for shape/behavior
  mismatch, `hybrid_shared_params_from_request:6789-6828`). The demanded contract ("RTL
  GetUsedCredit-equivalent observable with per-output and per-tap identity, occupancy accounting,
  credit-return visibility cycle, 6VC 8flit-per-VC 48flit buffer pin") is unimplemented —
  `hybrid_used_credit`/`hybrid_credit_visible_cycle` are Python-only models.
- Row is **not satisfied at production quality** for GEC-hybrid either.

### 4.8 SROTA FLOW CACHE + TELEMETRY — MISSING
- `check_srota_shared_profile`/`srota_shared_params_from_request` refuse planes≠`{d}`:
  `"srota telemetry and control planes stay refused … Plane T telemetry vectors and Plane C fixed
  XY control mesh not wired"` — `SROTA_TELEMETRY_BLOCKER` `:6580`, raised `:6733-6734`; identical
  refusal for `t` and `c` in the bad-design suite (`test_family_bad_design.py:195-199`).
- `tel_period`/`tel_latency` are accepted in the intent but **never consumed** (recorded in
  `srota_tuple`, `project_top_rtl.py:4828`; no synthesis use anywhere — grep `tel_period` →
  only intent/sweep/example files).
- Flow cache: absent from every product RTL string. Research leaf
  `rtl/srota/srota_fiu_pathsel.sv` implements epoch-tag lazy-valid flow cache (`flow_hash` input,
  `epoch_ctr`, `cache_epoch_tag`, 16-entry cache, `tel_row_vec/tel_col_vec` inputs) — but "leaf
  module, not wired into router ingress" and "not wired into the product preview emitter"
  (`rtl/srota/README.md` lines 8-12, 119-123); the hash itself is an **input** (no source-bank hash
  in RTL); no sampling/publication delay exists (tel_* treated as quasi-static inputs); no
  collision/publication-delay behavior modeled. `srota_credit_mgr.sv` is for side buffers only.
- `SROTA_SHARED_NOT_ESTABLISHED:6606-6612` repeats the refusal in the shipped manifest.

### 4.9 SHAPE / VALIANT INTERMEDIATE / LEG / RANK / ISLAND — BUILT-NOT-VERIFIED
- Kernel mechanism (template): `ker_step()` — on HEAD, `ISLAND_MASK≠0` ⇒ `SHAPE_TAB[dst]` sets the
  shape bit; `PKT_VALIANT` ⇒ intermediate `ker_intm = (dst*13 + src*7 + 17) % N_ROUTERS`,
  `ker_leg=0`; flips `ker_leg` when `ker_intm == ID`; `PKT_RANK` ⇒ `rank+1` (saturate at VC count)
  and writes the VC field; `PLANE_D_END` gates escape demotion to `(c % NUM_VCS) < PLANE_D_END`.
  Island shape table built as `shape_t` (1 if dst column ∈ island) — `_family_full_tables:4931-4940`.
- **Injection/transit agreement unproven:** initiator slices never write kernel bits; commitment
  arises in-router via `ker_step` on the first router — no test asserts the committed intermediate/
  shape at injection vs transit; no stalled-packet commitment test (no HOLD/stall scenario on a
  routed packet); `ker_step`'s Valiant hash is not verified against any commit rule elsewhere.
- Island: family-path composition exists (ISLAND_MASK path above) — shared/pinned top instead
  **pins island to col 1** and refuses all else (`SROTA_ISLAND_BLOCKER`, `:6582,6752-6755`;
  recorded TB check `island=36` in `run_srota_shared:8860-8874` — recorded).
- Valiant / rank / hop-rank VCs: **refused** in pinned top (`SROTA_VALIANT_BLOCKER`,
  `:6581,6739-6744`); in the family point-to-point path `PKT_VALIANT/PKT_RANK` can be emitted, but
  the only product-level check of shapes is the column-first `ker_shape` branch — no pinned-tap
  multidrop semantics, no through-router valiant test, no `valiant="..."` witness.
- "stalled packets do not change commitment": no mechanism/test proves it; `ker_step` is pure
  per-transmission rewrite (not stall-dependent) ≈ committed-shape stability by construction for the
  kernel bits, but this is a code-read claim, unexercised.

### 4.10 ENABLED SIDE-BUFFER ADMISSION / DRAIN PRIORITY / WATERMARKS — MISSING
- Pinned SROTA refuses: `"srota side buffer stays refused … side-buffer write handshake, multi-loser
  staging, credit manager drain-before-fill and watermark bypass not wired"` — `SROTA_SIDEBUT_BLOCKER`
  `:6579,6726-6728`; `test_family_bad_design.py:197` asserts it.
- Unified template path (only reachable via srota `sidebuf_enable=true` in the *family* path — not
  the pinned shared top): `SIDE_DEPTH>0` `side_q`, `side_write/side_read/side_wm_hold`, watermark
  sets `side_wm_hold` when `side_write >= SIDE_WM`, clears on `side_write == side_read`, drain
  moves one side→main slot/cycle when main has room. **Code-read defect:** side admission sets
  `in_side_ready[p]=1` while `in_ready_all[p]` stays 0 — `in_side_ready` is
  never OR'd into `n_in_ready`; the always-FF enqueue loads the **same held flit into `side_q`
  every cycle** (until `side_write == SIDE_DEPTH`) while upstream never sees ready=1. The side path
  cannot operate correctly as written; no directed test exists (grep `side_` in `tests/` ⇒ none).
- Side slots carry **no credits** (bounded only by `SIDE_DEPTH`/`SIDE_WM`); drain is not
  prioritized vs main-admit by any fairness rule (drain fires whenever main has room, regardless of
  head/main starvation) — unverified either way.
- Research leaf `rtl/srota/srota_sidebuf.sv` (one-hot write handshake, drain-before-fill, FULL
  decode) + `srota_credit_mgr.sv` exist and have a standalone TB (`tb_srota_sidebuf.sv`,
  `sim_sidebuf.sh`); per README they are unwired ("srota_router_d ties the side-buffer request
  off"). BUILT-NOT-VERIFIED there, **MISSING** for the product.
- Row's "disabling the feature cannot stand in for a pass" applies verbatim to today's pinned tops.

### 4.11 CONTROL / TELEMETRY PLANES, INDEPENDENT — MISSING
- Model exists, product does not use it: `model/multi_plane_vc.py` + `control_plane.py`
  (MultiPlaneVCAssignment: per-subnet independent VC index spaces; Plane C = plain XY) —
  **never imported by `veritx_dse/product/`** (grep ⇒ 0 hits); no RTL emitter references it.
- Pinned SROTA shared top refuses Plane C/T entirely — same `SROTA_TELEMETRY_BLOCKER` as 4.8
  (`:6733-6734`); the manifest `SROTA_SHARED_NOT_ESTABLISHED` repeats it (`:6606-6612`).
- Template's only plane logic: `PLANE_D_END` escape-demotion filter (data-plane VCs get demoted;
  VCs ≥ PLANE_D_END don't) — **not** an independent plane with its own routes/resources/wires.
- No telemetry vectors, no Plane C XY control mesh, no FIU Plane-T-weighted selection; no reset
  state exists for either plane (ties to 4.12).

### 4.12 EXPLICIT RESET for buffers / ownership / caches / planes — BUILT-NOT-VERIFIED
- Template `!rst_n` resets: `q_cnt, q_age, rt_alloc, rt_out, esc_mode` per queue; per port
  `rr_ptr, rr_acc, esc_starve, lock_active/owner/vc, side_write/read/wm_hold`, `side_q[pi][0]`
  (**index 0 only**), `cred` (→BUF_DEPTH), `cred_hist` (→0), `out_vld/out_hold`. mot_htree
  equivalent `:439-458` additionally covers `blk_cnt, out_valid_all, out_src_vc, esc_yield_q`.
- q/side_q **payload contents not cleared** — inert because occupancy counters reset to 0 (stale
  entries unreadable) — but a `case`-equality or `X`-prop reset test does not exist; combined
  `side_q[1:]` staleness note recorded.
- **No test proves no leakage into the next reset epoch**: family TB asserts only
  "post-reset immediate == 0" (immediates, `render_family_tb` tail section); slice TB S11/S12
  same; nothing resets mid-traffic then checks queues/credits/ownership; planes and flow caches
  do not exist to reset (4.8/4.11).
- Recorded (not re-verified): 36-router GEC baseline "reset checks pass" (PROGRESS.md:148);
  family TB "PASS: S7 ordering in-order **after reset**" (`render_family_tb`) — not an epoch
  test.

## 3. Which row blocks the Mixtral contract at production quality
The pinned contract is revision `p-fd7e5e31be77-r02`: **GEC-MECS**, 81 routers, **8 VCs**, 162
shared wires (0 channels), 128-bit emitted flits, routing class `DOR_GEC_MECS`
(`docs/product/evidence/mixtral-74-81-8-162/topology-p-fd7e5e31be77-r02.json` counts{};
revision hashes `router_behavior/vc_assignment`). Production quality requires L1–L5
(MILESTONE-14-PRODUCTION-RTL-20261110.md); none is claimed, and the pinned full-size shape is
**unemittable today** three ways: composed-family path refuses >1 seat/router
(`_require_single_endpoint_per_router` `project_top_rtl.py:6367-6380`; 74 agents on 81 routers),
the shared MECS top is pinned to k=4/16 routers/3 VCs single-flit (`:6636-6637,6714-6718`;
`run_gec_mecs_shared` `:8760`), and **no 81-router simulation pass is claimed anywhere**
(completion plan, ~line 590: "Keep the 81-router job gated; no 81-router simulation pass is
claimed").

**Row that blocks (single answer): 4.3 — free-credit counts / consumption / delayed returns /
no alias across taps/VCs.** The contract's whole flow-control substrate is tap-specific credit
pools across 162 three-tap shared wires × 8 VCs ("GEC ordered taps and tap-specific credit
pools" is named P4-adjacent in RTL-FINAL-CLOSEOUT-PLAN.md §4). No shipped artifact has any of it:
the MECS shared fabric has no credit counters whatsoever (proxy `valid_q` bits only), the family
unified router has counters but treats shared wires as undirected adjacency links with one
port-level pool — no tap/pool identity, no multidrop exclusion, `cred_hist` only correct at
LAT=1 — and the knob `credit_return_latency_cycles` is exactly what `UNREALIZED_ROUTER_CONTROLS`
`:74-78` refuses in the slice and mis-implements for LAT≥2 in the family path. Without 4.3 there
is no credit invariant to check on the pinned fabric, and the plan's own P8/L3 acceptance
("each physical credit pool balances … reset balance accepted/delivered/flushed") cannot be run.

Co-blocking (unavoidably in the same answer): **4.1/4.4** (the only MECS artifact produces
SINGLE flits — "not the compiled per-input credit/iSLIP/packet-reservation pipeline",
RTL-GEC-MECS-CHIPYARD-INTEGRATION-PLAN.md; no multi-flit ownership test) and **4.6** for the
knob-level path: any declared route/alloc/latency control is refused outright
(`UNREALIZED_ROUTER_CONTROLS`), so even the contract's declared router behavior cannot be honored.
**4.5** (compiled iSLIP/reservation) fails for the same artifact. Rows 4.7–4.11 are SROTA/GEC-hybrid
features not required by the MECS pin (they block those qualification rows instead). **Bottom
line: no P4 row passes for the pinned Mixtral contract; the row whose absence makes production
quality unattainable first is 4.3** (with 4.1/4.4/4.5/4.6 co-required), quite apart from the
scale/emission-impossibility blockers which are P3/P6-class, not P4.

## 4. Cross-cutting code-read defects (unexercised, but unambiguous)
1. `cred_hist` returns credits only for LAT=1; LAT≥2 ⇒ structurally zero returns; LAT=0
   over-returns unclamped (`_UNIFIED_ROUTER_TEMPLATE`, `CREDIT_RETURN_LATENCY` path;
   `_render_family_router:5003`).
2. `VC_REUSE_TAIL_CREDIT = 0` (release_on_tail_send) disables **all** credit returns on accept
   (`:5007`).
3. Side-admit handshake defect: `in_side_ready` never reaches `n_in_ready`; same flit re-copied per
   cycle while upstream is stalled (template in_ready/`side_admit` blocks).
4. `ALLOCATOR_ISLIP`, `ALLOC_ITER`, `SWITCH_ALLOC_CYCLES`: declared parameters with **zero** consuming
   logic; `rr_ptr` (family path) & `rr_acc` write-only; iSLIP is the declared-but-silently
   substituted default in the composed family path.
5. `_tmp_router.py` (product dir) is a stale 552-line duplicate of `_UNIFIED_ROUTER_TEMPLATE` —
   footgun, untracked scratch, not referenced (`wc -l` verified). Not edited per task scope.
6. `router_timing_model` exported but uncalled (`:4401`).
7. mot_htree `router_template.sv` demotion is hard-disabled (`if (0 && blk_cnt …)` ln 686) while the
   emitted `scripts/rtlgen/router.sv` variant has it live (single-flit flip only) — divergence
   between the reference and the emitter; both are the same "2-VC certified" claim.
8. Shared-fabric credits are `6'd1/6'd0` neighbor-valid proxies; the pinned buffer/8-flit/VC
   contract (`clock_power_cdc.py:14-35`) has no RTL counterpart.

## 5. Tests read, and what they do/don't prove
- `tests/test_family_bad_design.py`: binding/corruption refusal witnesses only (13 NOT_COVERED
  missing-guard rows, `:39-53`); proves typed refusals, **nothing about router semantics**.
- `tests/test_protocol_violation.py` **does not exist** (nearest: `test_serving_protocol.py::
  TestProtocolViolations` — serving transport, EOF/exit-code; unrelated to NoC). Model-adjacent:
  `tests/test_protocol_vc.py` (VC-separation certificates — model-level, supplemental per plan
  preamble).
- `tests/test_m2_ordering_fsm.py`, `test_m2_ordering_fsm_handshake.py`, `test_ordering_multidomain.py`:
  endpoint OrderingFSM source/lint/parity-smoke evidence; **not** router allocation/credit proof.
- `tests/test_project_top_slice.py` / `test_p8_mesh2x2_contention.py`: assert the UNREALIZED knob
  refusals and 18-scenario slice conservation — **SINGLE flits only**.
- `tests/test_project_top_shared.py`: shared-top pin/guard/differential tests; record PASS for
  lint/sim/selector ties — recorded, not re-verified by this audit; pins vs RTL reality gap documented in §4.
- `tests/test_uvm_dut_binding.py` + `rtl/t3/*` + `test_complete_design.py`: research-track binding
  smoke; `hardware_evidence_status` helper gates L1-style flags (drain/reset) — not instantiated-
  router credit proof.
- No test anywhere references `q_age`, `esc_starve`, `HOLD_SWITCH`, `SIDE_DEPTH`, `PLANE_D_END`,
  `ker_step`, `cred_hist`, `rt_alloc` (grep over `tests/` ⇒ ∅).

## 6. UNVERIFIED items (reason)
- All recorded Verilator results for composed family/shared tops (L1 passes, MILESTONE-14 table,
  RTL-FINAL-CLOSEOUT-STATUS "P4 PARTIAL"): **UNVERIFIED in this audit** — no build executed;
  docs cited as inventory, not truth.
- 36-router credit-router receipt (PROGRESS.md:148): **UNVERIFIED** — artifact outside this
  checkout (`~/.cache/veritx-noc-lab/…`); no 81-router pass claimed in any doc.
- SROTA TB `island=36/row_first=108/drop=384/stall_cycles=6` scenario counts: **UNVERIFIED**
  (recorded expectations in `run_srota_shared:8869-8880`; no build run).
- Variant divergence mot_htree vs emitted rtlgen demotion: **UNVERIFIED** consequences (no sim).
- BookSim cycles "1938 cyc" claims elsewhere: out of scope/material absent from this tree.
- The **credited-MECS** contract at Mixtral scale: **UNVERIFIED by construction** — the artifact
  does not exist (Section 4).

## 7. Bottom line
P4 is at **0/12 IMPLEMENTED**: 8 BUILT-NOT-VERIFIED (4.1, 4.2, 4.3, 4.4, 4.5, 4.7, 4.9, 4.12),
4 MISSING (4.6, 4.8, 4.10, 4.11). No emitted product artifact exercises a multi-flit packet,
a tap-aliased credit pool, a flow cache, a side buffer, or a second plane; the only parametrized
delay controls are refused at the slice boundary and silently trivial/dead in the family path.
**The row blocking the Mixtral contract at production quality is 4.3** (co-required 4.1/4.4,
knob-block 4.6); scale and emission impossibility are additional P3/P6-class blockers.


---

## Update 2026-11-10 (late): the per-tap credit substrate now EXISTS and is PROVEN

Row **4.3** (free-credit counts / consumption / delayed returns / no alias across taps and VCs) had no artifact at all in this tree. It now has one, isolated so it can be proven on its own:

| Artifact | Path | Status |
|---|---|---|
| Per-(tap, VC) credit pool | `tracks/t3-topology/rtl/tap_credit/tap_credit_pool.sv` | lints clean; **formally proven** (bounded model check, smtbmc + z3, two independent runs) and **simulated** (5 scenarios) |
| Behaviour testbench | `tracks/t3-topology/rtl/tap_credit/tb_tap_credit_pool.sv` | 5/5 PASS |
| Formal harness + script | `tracks/t3-topology/rtl/tap_credit/tap_credit_formal.sv`, `tap_credit_formal.sby` | **PASS** |
| Gate test | `tracks/t3-topology/dse/tests/test_tap_credit_pool.py` | 2 passed + formal test (opt-in via `VERITX_RUN_FORMAL=1`, minutes) |

**Proven properties** (for 3 taps × 8 VCs × capacity 4, return latency 2, over every interleaving of requests, frees and returns):
- P1 credits + outstanding == capacity, per (tap, VC) — conservation;
- P2 credits and outstanding stay within capacity;
- P3 a grant is only given against a credit of the same (tap, VC);
- P4 a matured return affects only its own (tap, VC) — the per-tap sums are independent, so a mis-routed return breaks P1 immediately;
- P5 the module's own alias detector never fires on a well-formed sequence.

**The environment assumption is explicit, not hidden:** a free notification always matches a distinct grant on that exact (tap, VC) — the router only frees a slot it took credit for. The formal run found this out: the first two proof attempts failed because the *environment* was freeing credits that were never outstanding (a double-free), which is exactly the class of bug row 4.3 is about.

**What this does NOT change:** the shipped router and the shipped shared fabric still keep one credit pool per (port, VC) and the shared fabric has **no** credit counters at all. The substrate now exists and is proven; **wiring it into the router (`cred[port][vc]` → per-tap pools) and into the multidrop shared fabric is the remaining work**, and until that lands row 4.3 stays OPEN for the pinned contract.
