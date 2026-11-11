# Multi-instance agent groups in the composed family builder — engineering map

**Status:** PROPOSAL / DESIGN MAP. Nothing described here is implemented, built, linted, simulated or pinned.
**Date:** 2026-11-10 · **Owner lane:** composed-family emission (`tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py`)
**Milestone:** P3 finish line — companion to `docs/product/proposals/multi-seat-concentrator.md` (shared-router arbitration), `docs/product/proposals/group-name-attachment-binding.md` (instance identity), `docs/product/REMAINING-WORK.md:322` (item 5), `docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md:41`, `docs/product/P2-P3-EVIDENCE-20261110.md:30,36`, `docs/product/RTL-FINAL-CLOSEOUT-STATUS.md:39`.
**Scope constraint honored:** this file is the only artifact created. No existing file was modified. No builds, Verilator runs, or pytest runs were performed.
**Why now:** for the selected 74-agent (full-size Mixtral revision `p-fd7e5e31be77-r02`, 74 agents / 81 routers / 8 VCs / 162 shared wires, per `docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md:3`) the composed family path refuses any agent group with `count > 1`, so the selected project cannot compile to hardware at all.

All line numbers are `project_top_rtl.py` as of this date (tree state 2026-11-10; md5 `c0f8f6cd6b450c9f2d3ad98a32dee6c8`, 505,479 bytes). Lines are rough (±10) and grep-verified at the time of writing; 2026-11-10. "Family path" = the 14-topology composed flow described below; "slice path" = the locked 2×2 mesh `run_rtl_slice` / `COMPOSED_SLICE`; "shared composers" = `COMPOSED_GEC_MECS` / `COMPOSED_SROTA` / `COMPOSED_GEC_HYBRID` (no initiator slices at all — separate effort, noted in §8).
The 14 supported families are `FAMILIES14` (`mesh, torus, concentrated_mesh, ring, gec_mecs, fly, qtree, tree4, flatfly, srota, gec_hybrid, fattree, dragonflynew, kncube`, line 4115) plus `gec_express` (`SUPPORTED_COMPOSED_FAMILIES`, 4116).

---

## 0. The one-line summary

`composed_family_params_from_request` intentionally drops every agent instance beyond the first of each group, then `render_family_project_top` emits one `initiator_slice` per group with one shared router-local injection port; the builder refuses rather than emit a broken top. Lifting the refusal is mostly a **mechanical per-endpoint generalization** when instances seat on **distinct routers** (typical for concentration-1 fabrics: mesh/torus/ring/flatfly/…), and it additionally requires the **multi-seat concentrator + response demux** (companion proposal) when two or more endpoints co-seat on one router (concentrated_mesh, fly, qtree, tree4, fattree). This document maps every assumption, what breaks, the minimal correct design, and a 5-checkpoint landing plan.

---

## 1. Every place the composed builder assumes exactly one instance per agent group

### 1.1 The load-bearing refusal (the "guard")

`composed_family_params_from_request(request, compiled)` — definition at **line 4576** (module `ProjectTop`, error prefix `UNSUPPORTED_COMPOSED_FAMILY`, `_refuse_family` at 4126; constant at 4114).

- **lines 4609–4614** — the guard itself:
  ```
  # The composed wrapper has one initiator/target port per group, not per seat.
  if any(int(a.count) != 1 for a in request.agents):
      raise _refuse_family(
          "composed endpoint adapters require one instance per agent group; "
          "multiple instances would be omitted from the generated top")
  ```
  Comment at 4609, condition at 4610, raise at 4611–4614. This is the refusal pinned by the repo (`tests/test_project_top_slice.py:251` `test_composed_family_never_drops_agent_instances[0|1]`, expected message `UNSUPPORTED_COMPOSED_FAMILY.*one instance per agent group`). Note the guard fires for the **memory** group too, not only compute tiles.
- **lines 4615–4618** — `total_instances = sum(int(a.count) ...)`; `total_instances < 1` refusal (multi-instance requests need this re-used, not bypassed).
- **lines 4776–4782** — seats assembly: `endpoint_list = sorted(attachment.endpoints by endpoint_id)`, `seats_raw.append((endpoint_id, group_index, instance_index, router_id, port_id))`, and `if len(seats) != total_instances: raise` (expected `endpoint count does not match agent instances`). **The `instance_index` is already captured here and serialized in `to_dict`** (line 4549, the one-line `to_dict`): `"seats": [{"endpoint_id": e, "group_idx": g, "instance_index": ix, ...}]` — it is simply never read by the emission.
- **lines 4785–4790** — `group_routers` / `group_endpoints` are built from seats with **first-endpoint-wins** semantics (`if g not in group_routers: group_routers[g] = r`). All but one instance of a group lose their router silently here.
- **lines 4791–4796** — `missing_groups` (group-granularity only — instances invisible to this check), `mem_router = group_routers[mem]`.
- **lines 4798–4799** — `initiators = tuple(SliceInitiator(group_idx=gi, router_id=group_routers[gi], ...) for gi in init_groups)` — exactly one `SliceInitiator` per group, keyed on that first endpoint's router. **This is the actual lossy step the refusal protects.**

### 1.2 Parameter data model (per-group identity only)

- `SliceInitiator` dataclass, **lines 214–221** — fields: `group_idx, router_id, domain, crossed, readable, writable`. **No `instance_index`.** Every consumer keys on `group_idx`.
- `SliceParams` (slice path, line 242) — `initiators: tuple = ()` (243), `num_initiators` property = `len(self.initiators)` (265–267), `crossed_groups` (269–271), `spare_routers` (273–276, assumes distinct used routers; silently collapses if two initiators share a router — fine today because distinct groups had distinct routers).
- `ComposedFamilyParams` (line 4484) — `initiators` and derived properties: `num_initiators` property at **4525–4527**; `to_dict` at **4549** (one giant line — serializes `initiators` without instance identity, `seats` **with** instance_index); `binding` tuple built inline in `composed_family_params_from_request` (binding rows incl. `"initiator_routers"` join and `"endpoints"/"agent_instances"` counts, lines **4843–4862**) — binding strings must become per-instance-aware or L2 mutation comparators will break.
- `family_binding_for_params` (line 4399) and `_family_dist` / `_family_full_tables` (4864/4879) — operate on `initiators[*].router_id`; safe for per-instance data (they just see more entries pointing at more routers) **for the concentration-1 case**; table sizes unchanged (keyed by `n_routers`).

### 1.3 Wrapper emission (`render_family_project_top`, line 5850)

- **5865–5893** — per-initiator port declarations keyed `init{gi}_*` (AXI + seq), one namespace per group. With 2 instances of group 0, emitting one port set `init0_*` cannot fan out — a naive lift of the guard produces **duplicate port names / duplicate drivers in `project_top`** (hard elab error, or worse with different connections).
- **5897–5904** — per-initiator debug outputs `dbg_order_violation{gi}`, `dbg_outstanding_full{gi}` and `dbg_imm{gi}` (the `dbg_imm` loop).
- **5913–5919** — per-router `noc_in_flit_/valid_/ready_{r}` and `noc_out_*_{r}` wires — **exactly one set per router**.
- **5928–5932** — destination tied to the **memory router only**: `noc_out_ready_{mem} = dest_req_ready_w`, `noc_in_valid_{mem} = dest_rsp_valid_w`, `noc_in_flit_{mem} = dest_rsp_flit_w`. **N+1 injection sources at the memory router** (N co-routed slices + `u_dest`) — see also companion doc §3.2.
- **5934** — `used = set(i.router_id for i in params.initiators) | {memory_router}`; **5936–5941** — unused-router ready ties (`unused_noc_out_{r}`), `unused_…` names keyed per router (fine).
- **5946–5948** — `dbg_imm{gi} = slice_imm{gi}_w` assigns; `inj_terms`/`ej_terms` string-joins over groups (sums on lines 5948–5949).
- **5952–5966** — slice instantiation loop — `initiator_slice #(.INIT_ID(gi), .INIT_ROUTER(r), ...) u_slice{gi} (...)` with `.INIT_ROUTER(r)` = the group's single router, `.seq_in(init{gi}_seq)`, noc taps `noc_in_flit_{r}` / `noc_out_flit_{r}` / `noc_out_valid_{r}` / `noc_out_ready_{r}`. **All co-grouped instances would drive the same `noc_in_*_{r}` net** (the multi-driven-net failure mode catalogued in the concentrator proposal §1/§3.3).
- **5969–5970** — `init0r` / `init1r` dead locals (latent cleanup; harmless today, misleading once instances multiply).
- **5973–5986** — `noc_top u_noc (...)` — one `local_in_/local_out_*_{r}` pair per router (see `_render_family_noc_top`, line 5090; the emitted `router #(...)` keeps one LOCAL_PORT — verified, lines ≈5256–5277 for the router instances).
- Also in this function family: `_apply_family_tb_widening` (5996; per-domain clock blocks keyed `clk_d{k}`, port wiring `.init{gi}_clk({_c})` at ≈6022 — group-keyed port names).

### 1.4 Initiator slice template (`_render_family_initiator_template`, line 5501)

- Parameter list at **5505–5511** (`INIT_ID, INIT_ROUTER, TARGET_ROUTER, CLASS_ID, CLASS_W, CDC_CROSSED`) — no instance parameter; `INIT_ID` is (ab)used as the group identity.
- **5696–5717** — the adapter instantiation is a **hardcoded two-branch `generate`** keyed on `INIT_ID == 0`:
  ```
  generate
      if (INIT_ID == 0) begin : g_adap0
          adapter_axi5_g0 u_adapter ( ... );
      end else begin : g_adap1
          adapter_axi5_g1 u_adapter ( ... );
      end
  endgenerate
  ```
  Consequences today: groups ≥ 2 (e.g. INIT_ID 2,3) **silently bind `adapter_axi5_g1`** — it elaborates only because every `adapter_axi5_gN` module is port-identical (name-only difference). Emitted `adapter_axi5_g{gi}.sv` for gi ≥ 2 are orphans: they are linted (via `dut_files`, line 6456) but never instantiated. For multi-instance this same block produces two slices of a group both referencing g{g} — legal SV for identical modules, but the "instance identity is only a name" assumption is baked in here.
- **5723** — `addr_decode u_decode ( .req_id((INIT_ID != 0)), ...)` — **collapses every non-zero group to req_id=1**. For 2-group requests this happens to satisfy the single-window policy; for ≥2 non-zero groups with distinct permission windows this silently merges their policies. (The locked slice path is also lossy, differently: `_render_project_top_locked` emits `.req_id((INIT_ID == 1))` — a 1-bit decode (group 0 vs the rest) at line 2045, while `INIT_SLICE_TEMPLATE` / `_widened_slice_template` emit `REQ_ID_W'(INIT_ID)` with `REQ_ID_W = 2` inside the template text at line 1510 — full 2-bit id but only reached by non-default-width variants.)
- **5741 / 5730** — embedded `cdc_bypass` / `ordering_fsm` instances; classes/order binding identical per slice (fine).
- `_widen_family_initiator_src` (widen for non-default DATA_W/VC, line 5420): **5459–5460** parameter-annotate the same `g_adap0/g_adap1` strings; **5422/5462–5495** builds a crossed-group `g_cdc{gi}` generate keyed on group id only (`_crossed = {i.group_idx ...}`).
- The locked sibling for reference: `INIT_SLICE_TEMPLATE` (one physical line, line 1510) contains the identical `generate` text (`g_adap0`/`g_adap1`), re-instantiated by `_render_project_top_locked` (1825; literal list at **2018–2041**) and by `_widened_slice_template` (1540; replaces at **1587–1588**); `_default_top` guard at **1518–1520** already pins `num_initiators == 2`, `(group_idx...) == (0,1)`, routers `(0,1)`.
- Ordering legality note: `ordering_fsm`'s `dom_sel = {initiator_in, class_in}` (`ordering_fsm_rtl.py`, `dom_sel` assign ≈line 396); the slice ties `initiator_in` to its default `'0` — all slices share domain 0 with their class. Fine per-slice (one ordering domain each); must be widened to per-instance (`initiator_in = slice_instance_id`) if a design wants distinct ordering domains per instance.

### 1.5 CDC cells and wrappers (group-keyed)

- `_cdc_cells_for_params` (line 1066) — builds cells with `insertion_point = f"cdc:slice:group{src}...group{dst}...:{direction}"` (1072–1082) — **no instance in the identity string**; `SliceCdcCell.group_idx` (1090); module name is derived from the insertion string (`cdc_cell_rtl.py:212–217` `sanitize_module_name` — deterministic, identical string ⇒ identical module, so two instances of the same crossed group would compute the *same* cell — which is actually safe for the cell, but…).
- `render_cdc_slice_wrappers` (line 1097) — `up_cells = {c.group_idx: ...}` (1101–1102) — **dict overwrite**: with ≥2 crossed instances in a group, one cell is retained and named `cdc_slice_up_{gi}` only once; both instances' slices reference the same wrapper module name — the bypass does get correct ports only if both instances are identical in domains, otherwise one crossing is silently mis-wired.
- Slice template crossing path: `_widen_family_initiator_src` generate keyed `INIT_ID == gi` (§1.4) instantiates `cdc_slice_up_{gi}` / `cdc_slice_down_{gi}` — group-keyed wrapper names, same collision.

### 1.6 Testbench (`render_family_tb`, line 6033)

All loops are keyed `ini.group_idx`; with 2 instances of group 0 every emitted name collides textually or silently narrows:

- **6040–6054** — per-group AXI signal declarations `init{gi}_*` (+ `{gi}_seq`, `{gi}_awready`, …); with count=2 the emitter would declare identical nets twice (or, if deduped, bind both slices to the same nets).
- **6057–6062** — per-group `dbg_imm{gi}` declarations (`dbg_imm0`, `dbg_imm1`, …).
- **6067–6086** — `project_top dut (...)` port hookups keyed `init{gi}_*`.
- **6098–6162** — per-group `do_write{gi}` / `do_read{gi}` tasks (task name, net names, `$display("PASS: init{gi} write bresp=...")` strings used by the sim checker — see §1.7).
- **6165–6173** — initial reset drives per-group AXI nets.
- **6176** — `next_seq = {ini.group_idx: 0 for ini in params.initiators}` — **single counter per group**; **6181–6201** — pre-S7 directed drives per group; **6199–6200** — `hero = next(i for i in params.initiators if i.readable or i.writable)` — one hero per group (collapses to the first group, second instance of the group never exercised).
- **6209–6213** — `imm_sum`/`hdr` string-joins per group; **6209** `imm_sum`, **6179** `hdr`.
- **6246–6247** — `next_seq` reset to 0 across all groups; **6258**, **6304–6305** — S8/S9 select `writer`/`reader` by `group_idx` (S9 = one write pair, one read pair — no instance dimension).
- **6344–6352** — `imm_names`, final conservation/drain/immediate checks — per-group only.

### 1.7 Sim checker / manifest / file list (`run_composed_family`, line 6381)

- **6389** — `_require_single_endpoint_per_router(params)` (def 6372–6379; called at 6389) — refuses >1 endpoint on one `router_id` (fits the concentration-1 story, fatal to concentration>1).
- **6455–6458** — `dut_files` appends `adapter_axi5_g{gi}.sv` once **per group** (list-comp over `params.initiators`) plus `dict.fromkeys` dedup (6459).
- **6505–6530** — `expected[]` built per group (`for ini in params.initiators: gi = ini.group_idx; ...`); `hero` at **6505–6506**; `concurrent`, `conservation` ("injected==ejected"), `drain`, `ordering_*`, `backpressure_*` strings checked with `PASS:` prefixes — with two instances of group 0, the TB would only drive/check instance 0 and the checker would still report PASS (false green).
- **6540–6548** — manifest hierarchy rows `u_slice{gi}`, `u_noc`, `u_dest`, `project_top` and `endpoint_map` (per-endpoint — already correct); `files` pinned to `tb_files`.
- Locked sibling (for completeness): slice-path `dut_files` list-comp at **3785**, `SLICE_DUT_FILES` locked list at **3674–3685**, `run_rtl_slice` adapter glob at **3719**, `COMPOSED_SLICE` manifest/hierarchy at **3785–3830** and **4003–4028**; slice count refusal at **523–527** (`slice_params_from_request`); `knob_map` note "adapter_axi5_g{group} + ordering_fsm ORDERING_MODE=1 …" at **366**; `SLICE_ORDERING`/`SLICE_MAX_OUTSTANDING` semantics unchanged.

### 1.8 Attachment mapping (what the compiler actually guarantees)

- `attach` = `derive_attachment` (`veritx_dse/model/attachment.py:431`): seats are enumerated **router-major, seat-index-minor** — `seats = [(r.router_id, s) for r in topology.routers for s in range(r.seat_capacity)]` (attachment.py:454–458); the canonical agent order is **group-major, instance-minor** — `build_inventory` (placement.py:198–212): `for group_index, group in enumerate(cr.agents) for instance_index in range(group.count)`. `endpoint_id` is positional: `Endpoint(endpoint_id=i, agent=agent, router_id=seats[i][0], port_id=seats[i][1])` (attachment.py:466–475). `validate_against_topology` checks `port_id < router.seat_capacity` and ejection pairing (attachment.py:303–347).
- Consequences, mechanically: with concentration = 1 (1 seat/router: mesh/torus/ring/flatfly/…), instance k of group 0 lands on router k (positions filled in order), one endpoint per router — the existing single-local-port-per-router wrapper is *structurally valid* once the emission is generalized per endpoint. With concentration ≥ 2 (concentrated_mesh c=2/4, fly stage-0 K seats, fattree/qtree/tree4 LEAF multi-seats, dragonflynew groups), consecutive instances of a group can land on the **same** router — co-seating — which the current wrapper cannot drive (single `noc_in_*` net per router) and which `_require_single_endpoint_per_router` refuses. The concrete demonstration: `ConcentratedMeshIntent(2, 2)` compiles to endpoints seated `[0, 0, 1]` (two group-0 endpoints on router 0), pinned by `tests/test_project_top_slice.py:279`.
- `seat_capacity` is otherwise **unused by the composed wrapper** (no VC binding, no port arbitration) — `params.seat_caps` (line 4804) is plumbed only into `to_dict` (4549).
- The memory group: exactly one `hbm_controller` group allowed (kinds check at ≈4587–4590), but its `count` is not restricted to 1 other than by the §1.1 guard — multi-instance HBM (multiple memory controllers) is a *distinct* multi-instance class hitting the same guard; see §8 scope note.

---

## 2. How the adapter is emitted per group, and how endpoints map to routers/seats (recap)

### 2.1 Adapter emission (per group, by design)

- The preview (`rtl_export.run_rtl_preview`, `tracks/t3-topology/dse/veritx_dse/product/rtl_export.py`, adapter block ≈lines 138–163) iterates `agent_intents`, builds **one** `build_adapter(AdapterParams(agent_idx=idx, ...))` per agent **group**; the module name is `adapter_{family}_g{idx}` (`adapter_factory_rtl.py: adapter_module_name`, ≈214–216); the emitted file is `{build.module}.sv` = `adapter_axi5_g{idx}.sv` (`filename = f'{build.module}.sv'`, rtl_export.py ≈221–226). The module body is **group-independent**: identity enters only via the module name; data/addr widths come from the (common) agent widths, `SPLIT_AT=0`, `MAX_OUTSTANDING=4` attributes are string-replaced in at emission parameterization (project_top_rtl.py 5459–5460 / 1587–1588) but never parameterize behavior per group.
- Net effect: **reusing the per-group adapter module for N instances of that group costs zero new files** — `dut_files` dedups anyway. What is missing is the per-instance *binding inside the top* (§1.4), not the adapter itself.
- The destination adapter (`_render_family_destination`, line 5284; file `destination_adapter.sv`) is a single SRAM target + single response engine, bound to the memory router; it carries no group dimension. Per request it latches `src_q` from the flit's source field and echoes it as the response's destination (rsp `dst = src_q`), so it can drive responses back to whichever router the initiator lives on — this is what makes co-routed instances of one group on **different** routers work unmodified.

### 2.2 Endpoint → router/seat mapping (canonical)

Per `derive_attachment` (§1.8): `endpoint_id` enumerates `(group, instance)` in inventory order; `seats[endpoint_id] = (router_id, port_id)` enumerates routers in id order, seats in slot order. The composed params book this as `seats = ((endpoint_id, group_idx, instance_index, router_id, port_id), ...)` (line 4780). With `count = 2` on group 0 and mesh 4×4 (1 seat/router), the seating is fully determined: endpoint 0 → (g0,i0)@r0, endpoint 1 → (g0,i1)@r1, endpoint 2 → (g1,i0)@r2, endpoint 3 → (mem)@r3 — i.e. the 2 instances of group 0 occupy routers 0 and 1 respectively (first-ready fill order, no placement choice). Any re-seating engine (placement) that exists upstream stays untouched; the composed builder consumes `attachment.endpoints` as-is and must not re-seat.

### 2.3 What the composed wrapper does with that mapping

`initiator_router = group_routers[gi]` **(first-wins, §1.1)**; one `initiator_slice` per group; noc wires per router; destination on the memory router; unused routers get `ready=1` ties. The wrapper has exactly one local injection port per router (`noc_top.local_in_*_{r}`) and no notion of `port_id`/`seat_capacity`.

---

## 3. What breaks if N > 1 per group (failure analysis)

Ordered from "loudly refuses today" (safe) to "silently wrong" (the dangerous class the guard exists for) to "engineering gaps" (the work).

### 3.1 Refuses loudly today (keep as typed refusals until the design lands)

1. `UNSUPPORTED_COMPOSED_FAMILY … one instance per agent group` (§1.1) — fires for any `count != 1`.
2. `multiple endpoint seats on one router` (`_require_single_endpoint_per_router`, 6372) — fires whenever co-seating would occur (e.g. concentration-2 fabric, or even concentration-1 with many groups vs few seats — can't happen with enough routers, but concentrated families with 3 endpoints: c=2/4, or fly K=3 with 2 compute + HBM seating [r0: ep0,ep1,ep2]).
3. `slice` path twin refusal (523–527) for non-family flows.

These refusals are **not to be deleted**; each is retired only when a mechanism (emission generalization, resp. concentrator) covers the case.

### 3.2 Silently wrong today (would be wrong if the guard were merely deleted)

S1. **Dropped instances at the builder** — `group_routers[g]` first-wins and one `SliceInitiator` per group: instance 1 of group 0 gets **no port, no slice, no CDC cell, no TB drive, no manifest row, no checker scenario**. The wrapper would still pass lint/sim/`conservation`/`drain` — **false green**, exactly the failure the INTENT-TO-PLACED-RTL audit reproduced (`docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md:110`; `docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md:390`).
S2. **Duplicate / multi-driven nets in `project_top`** — two `initiator_slice` instances on the same router each drive `noc_in_flit_{r}/noc_in_valid_{r}` (multi-driven net): x-propagation in sim, `MULTIDRIVEN` lint failure, structural short in synthesis. Even on **distinct** routers, declaring `init0_*` once for two slices both wired to it makes them **share AXI nets** — cross-talk, corrupted transactions.
S3. **Address decode merges non-zero groups** — `.req_id((INIT_ID != 0))` (line 5723): groups 1 and 2 both decode as req_id 1; permission checks (`addr_decode.sv` emitted by `render_addr_decode`, `addr_decode_rtl.py` — initiator-keyed default-deny, one `case` row per `req_id`) silently grant/deny group 2 on group 1's policy. Not caught by any current checker.
S4. **Adapter binding collapses** — any slice with `INIT_ID ≥ 2` binds `adapter_axi5_g1` (5696–5717); emitted `adapter_axi5_g2.sv` is an orphan; compiled manifest lies about the module instance's name (`u_slice2`/`adapter_axi5_g1`).
S5. **CDC cell/wrapper overwrite** — `up_cells = {c.group_idx: c}` dict overwrite and `cdc_slice_up_{gi}` wrapper naming: instance 1's crossing cell is discarded; both slices would route through instance 0's cell; if domains differ it is a plain mis-clock. Multi-clock groups are then silently broken.
S6. **TB drives instance 0 only** — per-group tasks/nets and `next_seq` per-group (6176): a count-2 request exercises only instance 0; expected[] matches; `conservation` holds — the green bar certifies a lie.
S7. **Hero/S7/S8/S9 selection** — `hero = next(...)` (6199/6505) picks one initiator — with per-group keying the second instance is invisible to the ordering/backpressure/concurrent scenarios; `next_seq` rolls the whole group as one counter — with sharing, instance 0 and instance 1 txns interleaving in one STRONG ordering domain stall permanently (`seq_gap != 0` → `S_WAIT`/OOO stall deadlock), or produce spurious `order_violation`.
S8. **Memory-side** — if HBM group were multi-instance: two controllers co-seated at the memory router inject responses (`u_dest` is a single SRAM/response engine — there is no second response path), one response consumer; `dbg_dest_rsps` accounting is per memory endpoint, not per instance.

### 3.3 Arbitration / ordering requirements that do not exist today

A1. **Injection-side arbitration at the router local port** — zero exists; one driver per port today. Co-seated instances need a mux + fair pointer arbiter (see §4).
A2. **Ejection-side demux** — co-seated slices all tap `noc_out_valid_{r}/flit_{r}`, all assert `noc_out_ready` when in `S_WAIT_RSP`; the first response would be consumed by **all** co-seated slices (each latches it, each increments `ej_q`, next response has no consumer → router LOCAL output holds forever → fabric-wide stall). Requires a response demux keyed by issue-order or seq (see §4 and companion §4.7).
A3. **`port_id`/seat VC binding** — unused today; multiple seats on one router have no VC-segregation — acceptable (they share VC0 class rules) but must be documented, not silently skipped.
A4. **Ordering domain widening** — per-instance STRONG ordering requires either per-slice seq counters (recommended; `ordering_fsm` is already per-slice) or `initiator_in` wired to a per-instance id (`INIT_W` widened in `ordering_fsm_rtl.py` params; port exists, default `'0` — backward compatible) if distinct domains are preferred. A **shared** per-group seq counter across co-seated instances deadlocks STRONG domains by construction (`expected_seq_arr` requires gap==0 per domain; interleaved allocation gives gaps) — forbidden by design.
A5. **OUTSTANDING accounting** — per-slice `MAX_OUTSTANDING=4` unchanged; the demux/concentrator must not leak grants beyond it (backstop counters, companion §4.2).

### 3.4 TB collapse mechanics (explicit)

With the guard deleted and nothing else: `render_family_tb` emits duplicate `init0_*` nets (elab error) or, if textually deduped, shares AXI nets between slices (S2); `do_write0/do_read0` drive both instances identically (same `awid/arid=0`, same addresses → undetectable cross-talk); `next_seq` (6176) hands the same seq to both instances; ordering FSM of instance 1 sees gaps (STALL); `dbg_imm0` counts only adapter-g0 activity; `expected[]` checks only listed PASS strings; `S9` concurrent pair may pick two nets wired to the same slice; conservation passes trivially with instance 1 dead. **All current sim scenarios (S1..S9, conservation, drain, imm==0) are structurally incapable of detecting a dropped instance** — which is why the checker additionally needs per-instance coverage scenarios (§4.5).

---

## 4. Minimal correct design

### 4.0 Invariants to preserve (non-negotiable)

- Router (`router.sv` from `_UNIFIED_ROUTER_TEMPLATE`, line 4996) bit-identical; no router re-qualification.
- `noc_pkg.sv`, flit format, VC/class binding, escape scheme (`esc_yield_q`) untouched.
- Per-instance ordering contract identical to today's per-group contract (STRONG, `MAX_OUTSTANDING=4`, deny/miss semantics, permission windows group-scoped — "Interface lives on the group, not the instance", `docs/product/INTENT-SYSTEM.md:201`).
- No reordering across instances within the group at the fabric; RR fairness only.

### 4.1 Step 1 — parameter model: per-endpoint instances (no RTL yet)

- `SliceInitiator` (lines 214–221) gains `instance_index: int = 0` (frozen dataclass — adding a defaulted field is source-compatible).
  - Better: introduce `SliceEndpoint` (or reuse `SliceInitiator`) as **one row per (group, instance)** with `endpoint_id` too, and keep `SliceInitiator` name to minimize churn — the tuple is built from `params.seats` directly.
- `composed_family_params_from_request`:
  - delete/replace the §1.1 guard with a typed refusal only for the still-unsupported classes (e.g. memory-group `count != 1` in v1 — §8), **keeping** `total_instances` (4615) and `len(seats) == total_instances` (4782) untouched — these are the instance-conservation guardrails.
  - build `instances` from seats: for each `(endpoint_id, g, ix, r, p)` in seats with `g != mem`: `SliceInitiator(group_idx=g, instance_index=ix, router_id=r, domain=..., crossed=..., readable=windows[g][0], writable=windows[g][1])`. Ordering of instances = seat order (deterministic; inventory order).
  - `group_routers` first-wins replaced by per-instance rows; `missing_groups` re-expressed over instances (every group must supply ≥1 instance; every instance must appear exactly once).
  - `mem_router` (4794) unchanged; fabric_domain unchanged; `initiators` tuple now length `total_instances - mem_count`.
- `ComposedFamilyParams` (4484): `initiators` → per-instance tuple; `num_initiators` property (4525) unchanged (=len); `to_dict` (4549) gains `"instance_index"` per initiator row (additive; schema stays `veritx/project-top-family/1` — note manifest consumers must tolerate the additive key).
- `binding` rows: `"initiator_routers"` → per-instance `"g{g}i{i}@{r}"` list join; add `"initiator_instances"`, `"endpoints"`, keep `"agent_instances"` = total_instances (already present) — L2 mutation comparators re-checked.
- `crossed_groups`, `spare_routers` (slice path) and `endpoint_seats`/`egress_map` (4783–4784) — unchanged semantics, now over more rows.

### 4.2 Step 2 — emit one fabric-visible bundle per instance (composition, no arbiter yet)

- `_render_family_initiator_template` (5501): drop the `generate/g_adap0/g_adap1` block (5696–5717) and emit **one direct instantiation** naming the group's adapter module baked at render time (`adapter_axi5_g{group}`), since the template is already specialized per parameter set. Pass `INSTANCE_ID`-like localparam only if debugging needs it (keep parameter list minimal; `INIT_ID` stays the *group* id and a new `INSTANCE_ID`/`ENDPOINT_ID` parameter carries the seat identity).
  - `addr_decode .req_id((INIT_ID != 0))` (5723) → `.req_id(REQ_ID_W'(INIT_ID))` equivalent with the **group** id (policy is group-scoped). Do **not** narrow per instance here (narrowing = optional P1.5 add-on, see §4.6).
  - If distinct ordering domains per instance are wanted: wire `initiator_in = INSTANCE_ID` with `ordering_fsm #(.INIT_W(INSTANCE_W))` (port already exists; default `'0` unchanged → backward compatible). Otherwise keep `initiator_in='0` (per-slice domain already distinct, since each slice has its own FSM).
- `render_family_project_top` (5850): replace per-group loops with per-instance loops — ports `init{g}_{i}_*`, `dbg_*{g}_{i}`, slice instance name `u_slice{g}_{i}`, per-instance nets `slice_inj{g}_{i}_w` etc.; `used = set(instance routers) | {mem}`; inj/ej sums over instances; memory tie unchanged (mem router carries exactly the instances co-seated there — see Step 4).
- `render_cdc_slice_wrappers` + `_cdc_cells_for_params`: key cells/wrappers by `(group_idx, instance_index)` — filenames `cdc_slice_up_{g}_{i}`; `SliceCdcCell` gains `instance_index`; `_widen_family_initiator_src` `_crossed` set keyed by pairs; `g_cdc{g}_{i}` generate keyed on both.
- `run_composed_family`: `dut_files` unchanged in set-size (one module file per group, dedup'd) — no new adapter files; manifest hierarchy rows `u_slice{g}_{i}`; `expected[]` loop over instances; sim checker messages per instance (parse `PASS: init{g}i{i} ...`).
- `render_family_tb` (6033): mechanical per-instance rework — signals `init{g}_{i}_*`, tasks `do_write{g}_{i}/do_read{g}_{i}`, `next_seq` keyed `(g, i)`, `hero`/`writer`/`reader` selection over instances (S9 pairs = distinct instances, cross-group preferred, cross-instance same-group allowed), `imm_sum`/`hdr`/`imm_names` joins over instances, `_apply_family_tb_widening` `.init{g}_{i}_clk(...)` wiring, and the expected-counter preamble — same deltas in the locked slice renderer only if/when the slice path is opened (recommended: not in v1; keep locked path pinned at 2 initiators, `(0,1)`).

### 4.3 Step 3 — concentration-1: no arbiter required (the common case)

When every endpoint seats on a distinct router (all concentration-1 families for count-uniform requests whose endpoint count ≤ routers; always true for mesh/torus/ring/flatfly at the 74-agent scale only for families whose seats permit — verify per family), the generalization in Step 2 is **complete and sufficient**:

- injection: exactly one slice drives each router's `noc_in_*_{r}`;
- ejection: exactly one slice taps each router's `noc_out_*_{r}`; that slice is the only writer of `noc_out_ready_{r}`;
- destination responses: routed by `dst = requester router` — reach the correct local port, consumed by exactly one slice;
- TB drives/checks each instance independently.

No new RTL module, no router change, no arbitration policy change. Cost ≈ purely mechanical emission/TB/checker work (lines est. §6).

### 4.4 Step 4 — concentration > 1 (co-seated): fair RR concentrator at the injection seam (reuse the companion design)

For fabrics that co-seat endpoints (concentrated_mesh c=2/4, fly stage-0 K seats, qtree/tree4 leaf multi-seat, fattree, dragonflynew), Step 2 alone leaves N slices and `u_dest` driving one `noc_in_flit_{r}` net. The correct substrate is the **multi-seat concentrator** of `docs/product/proposals/multi-seat-concentrator.md` (§3.2, §4), applied per multi-seat router:

- **Arbiter:** `concentrator_R` (emitted per multi-seat router; `_render_seat_concentrator(...)` emission function + wiring at the slice→`noc_top` seam, i.e. inside `render_family_project_top`, **not** in `router.sv`, **not** in `noc_top`, **not** inside the slices). v1 = zero-storage strict round-robin re-mux: one `rr` pointer advanced on accepted flits, one-hot `seat_ready`, packet lock for multi-flit trains (degenerates to per-flit for the current SINGLE-flit emission). Bounded skew invariant `|cnt_i − cnt_j| ≤ 1`; grant within N−1 acceptances — starvation-free. (iSLIP rejected: needs grant pre-selection state with no fairness theorem gain at N ≤ 4 seats; age-based rejected: global cross-seat age is ill-defined without a shared timestamp and unnecessary at these seat counts.)
- The companion proposal's phrase is exactly "**strict round-robin by per-seat sequence counter**" — `rr` *is* the per-seat sequence counter; fairness is structural, and it matches the user-visible contract: fair RR at the group's sequence granularity, no priority, no class override (VC/class policy stays the router's).
- **Ejection side (required, not optional):** the companion's §3.3 failure mode applies unchanged per co-seated instance. Proposed minimal fix coherent with this doc: a **grant-order response demux** (`seat_rsp_demux`): per-seat `exp_cnt_i` counter incremented on each injection grant of a SINGLE request flit from seat i, decremented per match; the shared `noc_out_*` stream is released strictly in grant order (small FIFO of seat ids, depth ≤ ΣMAX_OUTSTANDING = 4N). This preserves per-instance consecutive seq from 0 (ordering_fsm STRONG intact, §4.0), needs no window bits in seq, and cannot mis-deliver.
  - **Interaction flag, stated honestly:** the companion doc §4.7 sketches a **seq-window** demux (`seq[12:10]` = seat id). As written, that forces either (a) strided per-seat seq spaces with RELAXED ordering per domain, or (b) drops gap==0 checks — both weaken the STRONG ordering contract of §4.0. **Recommended amendment to the companion doc:** adopt grant-order FIFO demux instead; keep seq windows only if the operator explicitly approves relaxed per-domain ordering. This is a cross-document consistency item for joint review, not a code question.
- **`u_dest` co-seat:** at the memory router the source set is N instances + `u_dest` — the concentrator must accept N+1 bundles there (companion §3.2, §4.7, §5.2), and `noc_out_ready_{mem}`/`rsp_ready` stay u_dest's.
- **Refusal narrowing:** `_require_single_endpoint_per_router` (6372) narrows from "any co-seat ⇒ refuse" to typed refusals only for the residual unsupported cases (seats per router > CIN_MAX=8; missing packet fields; ejection-plane co-seating before its demux lands). mesh/torus/flatfly keep byte-identical output — concentration-1 fabrics never see the concentrator.
- **instance_index flows to `port_id`:** when >1 endpoints share a router, optional VC/class segregation by `port_id` is possible later; v1 does not use it (documented, not silently skipped).

### 4.5 Step 5 — TB, checker, manifest re-validation

- TB changes exactly as in Step 2 (per-instance), plus:
  - **instance-disjoint traffic windows** for directed cases (golden model unambiguous), e.g. seat i owns SRAM words `[i*32, i*32+31]` (same pattern as companion §6.0);
  - cross-instance **S9 concurrent** pairs for at least one same-group pair (not only cross-group writer/reader) and per-group conservation per instance;
  - `S7`/`S8` scenarios executed per hero **instance** (hero chosen per (group, instance) deterministically);
  - post-drain assertion `outstanding == 0` per instance; `dbg_imm` per instance; `imm==0` check per instance (sum check alone is insufficient — S6).
- Sim checker `expected[]`: one triple per instance; all strings unchanged in format (only names change) — `PASS: init{g}i{i} write bresp=...`.
- Manifest: hierarchy rows `u_slice{g}_{i}`; `files` unchanged per group (module reuse); `endpoint_map` already per-endpoint; design_hash re-derived (request unchanged → hash unchanged; only artifacts change).
- `run_composed_family` intentionally still fails closed until Step 4 is done for co-seating families (typed refusal lists the seat map).

### 4.6 Optional follow-on (NOT v1): per-instance permission narrowing

The decoder already supports an instance dimension — `_initiator_instance_map` / `REQ_INST_W` / `req_inst` port in `render_addr_decode` (`addr_decode_rtl.py`, ≈lines 160–172, 300–340, 427–490), pinned by `tests/test_addr_decode_instance_spoof.py` (instance rows must narrow, never widen, the group policy). Wiring `req_inst = INSTANCE_ID` and emitting per-instance `InitiatorPolicy(instance_idx=...)` rows is a pure additive change once Step 2 lands; requires explicit intent declarations (`instance_idx` in `PermissionWindow`/`InitiatorPolicy` — currently `InitiatorPolicy` has no `instance_idx` field, so model-layer work too). **Out of v1 scope**; default behavior stays group-scoped (spec: INTENT-SYSTEM.md:201).

### 4.7 Explicitly out of scope v1

- Multi-instance **HBM** groups (memory `count > 1`) — needs a second destination engine/arbitration at the memory router and duplicated SRAM addressing; typed refusal `UNSUPPORTED_COMPOSED_FAMILY: memory group instances > 1 not yet supported` (kept from the §1.1 guard, narrowed).
- Shared-wire family composers (`COMPOSED_GEC_MECS`/`SROTA`/`GEC_HYBRID`, line 6620+) — separate emission path with no slices; same class of work, separate doc/effort.
- `KNCUBE` general intent (blocked on Constellation fork; `KNCUBE_BLOCKER`, 4121) — untouched.
- Any change to `router.sv`/`noc_pkg.sv`, ordering modes, or the L2 binding comparators' semantics (they get *more rows*, same semantics).

---

## 5. Answers: which function emits N adapters, which arbiter, which TB changes

- **Adapters:** no new adapter *files*. Emission of N adapter *instances* happens inside `_render_family_initiator_template(params)` (line 5501) by instantiating each instance's slice with the group-scoped `adapter_axi5_g{group}` module directly (drop the `generate`/`g_adap0|g_adap1` hardcoding at 5696–5717). Per-group files still come from the preview `run_rtl_preview → build_adapter` path (`rtl_export.py` ≈145–163, `adapter_factory_rtl.py:214` `adapter_module_name`). The file list (`dut_files`, 6455–6459) and `SLICE_DUT_FILES` (3674–3685) stay deduplicated by `dict.fromkeys` — no file-list surgery beyond deleting the orphan branch references. If a future audit wants per-instance adapter *modules*, the correct knob is a new `instance_idx` suffix in `adapter_module_name` — explicitly **rejected** for v1 (zero functional delta, manifest churn).
- **Arbiter:** none needed for concentration = 1 (Step 3). For co-seated routers: `concentrator_{router}.sv` — zero-storage strict round-robin re-mux with a per-seat sequence pointer (`rr` advanced on accepted flits; `|cnt_i − cnt_j| ≤ 1`; grant within N−1), i.e. exactly the "fair RR by group sequence counter" discipline, emitted by a new `_render_seat_concentrator` invoked from `render_family_project_top`; companion `seat_rsp_demux` (grant-FIFO preferred — §4.4 amendment flag). Never iSLIP, never age-based, never a change to `router.sv`.
- **TB:** `render_family_tb` reworked per instance (axes enumerated in §1.6 and §4.5): net declarations, dut hookups, `do_write{g}_{i}`/`do_read{g}_{i}` tasks, `next_seq[(g,i)]` counters, hero/S9 selection over instances, disjoint data windows, per-instance `dbg_imm` + post-drain outstanding==0, `imm==0` per instance, expected[] triples per instance in `run_composed_family`'s sim checker, `_apply_family_tb_widening` port wiring, plus the co-seat TB cases A/B/C from the concentrator doc §6 once Step 4 lands.

---

## 6. Estimated delta and risk

### 6.1 Size estimate (±30%, against this tree)

| Component | Files | Delta (lines) |
|---|---|---|
| Params model: `SliceInitiator.instance_index`, per-instance `initiators` build, `binding` rows, `to_dict` additive key | `project_top_rtl.py` (4776–4862, 215–221, 4549) | +40 / −25 |
| Wrapper: port/task/module/wire loops per instance; `used` set; inj/ej sums; dead-var cleanup | same (5850–5990) | +180 / −90 |
| Initiator template: drop `generate` adapter block; `req_id` group id; optional `initiator_in` wiring | same (5501–5760) | +25 / −45 |
| CDC: `SliceCdcCell.instance_index`, wrappers keyed (g,i), widen-map `_crossed` pairs, `g_cdc{g}_{i}` | same (1066–1140, 5420–5495) | +60 / −40 |
| TB: full per-instance rework (signals, tasks, selection, checks) | same (5996–6160, 6176–6352) | +160 / −140 |
| Sim checker / manifest expected[] per instance | same (6505–6548) | +40 / −30 |
| New `_render_seat_concentrator` + `seat_rsp_demux` (Step 4 only) | same (new, after 5085) | +150 / 0 |
| Tests: rewrite `test_composed_family_never_drops_agent_instances` & siblings; new per-instance mesh/torus/ring L1/L2 cases; co-seat TB cases | `tests/test_project_top_slice.py`, `test_project_top_parameterized.py` | +250 / −80 |
| Docs: this file + ledger/remaining-work/MILESTONE/P2P3 updates at each checkpoint | `docs/product/*` | +150 |
| **Total** | | **≈ +1,100 lines / −450 lines; net ≈ +650** (excluding Step 4) |

Step 4 (co-seat) is ≈ +300 of that total; without it, the concentration-1 generalization is ≈ +350 net.

### 6.2 Risk register

- **LOW–MEDIUM** — Step 1 (params/model): mechanical; regression surface = existing family/slice tests; main hazard is hash/binding comparators in `tests/test_family_bad_design.py` (L2 mutations) noticing the new binding rows — mitigated by additive-only rows.
- **MEDIUM** — Step 2 (emission, distinct routers): collision class (duplicate nets/ports) is caught by lint immediately (-Wno-* flags do not silence MULTIDRIVEN/DUPLICATE); semantic risk is low because routing to destination and response routing are already correct per router; hazard is TB bookkeeping, not hardware.
- **MEDIUM–HIGH** — Step 2 TB + checker: every name changes; a missed site yields duplicate tasks or unchecked instances (silent false-green). Mitigation: grep-audit + the new instance-aware scenarios must *fail* when an instance is deleted (mutation test: comment out one slice → conservation must break).
- **HIGH** — Step 4 (concentrator + demux): new RTL with arbitration fairness and response routing on a shared port; failure modes are x-prop, response mis-delivery, grant starvation, and re-qualification of the concentration families' previously-green proofs. Mitigation: companion's §6 assertions (A1–A10), the unit bench for the packet lock, A/B/C seat cases, and disabling new features behind typed refusals until green.
- **HIGH (process)** — Re-qualification wall time: 14-family lint+sim sweep (+ parameterized widths/VCs) — each Verilator binary build is minutes; plan for a full overnight sweep, not a quick check. KNCube stays harness-only regardless.
- **HIGH (unknowns)** — the 74-agent target uses 8 VCs + shared wires in pinned captures: current composed path is 2-VC-ish per request (`vc_count_family` from the compiled bundle supports ≤16 but the emission sign-off is per family); multi-instance correctness for >2 VCs and 162 shared wires is unproven even at 1-instance scale — do not conflate this work with full L3/L5 qualification.

### 6.3 What is explicitly NOT claimed here

No code exists. No lint/sim has been run against the design in §4. "PASS", "clean", "production-ready" claims in this file are requirements/targets, not results. The 74-agent target remains not-compilable until this work lands and a pinned-capture RTL run is executed.

---

## 7. Implementation order — 5 checkpoints with exact pytest targets

All commands run from `tracks/t3-topology/dse` (`testpaths = ["tests"]`, `timeout = 900`; Verilator-dependent cases auto-skip if absent — `shutil.which("verilator")` gates in the tests themselves). Target-of-work files: `veritx_dse/product/project_top_rtl.py` (+ tests).

**Checkpoint 1 — parameter model & guard narrowing (no RTL change yet; everything still refuses at emission).**
Work: `SliceInitiator.instance_index`; per-instance `initiators` build from seats; `binding`/`to_dict` additive rows; split the §1.1 guard into "memory group count>1" (typed refusal, kept) vs compute groups (allowed at params level); `_require_single_endpoint_per_router` untouched.
Done = `composed_family_params_from_request` accepts a count=2 request, returns per-instance initiators; `run_composed_family` still fails only via the router-seat refusal (co-seat) or the renderer (distinct routers — expected, because renderer cannot emit duplicates).
Exact targets:
```
cd tracks/t3-topology/dse && python -m pytest \
  tests/test_project_top_slice.py::test_composed_family_never_drops_agent_instances \
  tests/test_project_top_slice.py::test_composed_family_refuses_multiple_endpoints_on_one_router \
  tests/test_project_top_slice.py::test_non_slice_mesh_profile_has_composed_family_contract \
  tests/test_addr_decode_instance_spoof.py -q
```
(The first test is rewritten to expect success at params level and refusal only at emission; assert `len(params.initiators) == 4` for the mesh2×2 count=2 case; assert instance rows carry `(0,0),(0,1),(1,0)` and mem.)
Plus: `tests/test_family_bad_design.py` — the binding/mutation rows for `initiator_routers`/`agent_instances` must be updated in the same commit; run `python -m pytest tests/test_family_bad_design.py -q` (expect rewritten expectation rows only; no new refusals).

**Checkpoint 2 — concentration-1 emission (mesh/torus/ring/flatfly) + TB + checker.**
Work: §4.2/§4.3/§4.5 — per-instance wrapper, template adapter binding, CDC keys, TB rework. Memory group stays count=1.
Done = a count=2 compute-group request on mesh4×4 lints and sims PASS end-to-end; old behaviors byte-identical when all counts == 1.
Exact targets:
```
cd tracks/t3-topology/dse && python -m pytest \
  tests/test_project_top_slice.py::test_composed_family_never_drops_agent_instances \
  tests/test_project_top_slice.py::test_family_router_interface_deterministic \
  tests/test_project_top_slice.py -q -k "test_composed_family_lints_and_sims and (torus or mesh or ring)"
```
Plus parameterized regression guards (must stay green, unmodified):
```
python -m pytest tests/test_project_top_parameterized.py -q -k "three_initiators or renderers_are_deterministic or knob_mutations"
python -m pytest tests/test_project_top_slice.py -q -k "composed_slice_lints_and_sims"
```
New tests to add in this checkpoint (same files): `test_composed_family_per_instance_mesh_count2_lints_and_sims[mesh|torus|ring|flatfly]` (skip without verilator), `test_composed_family_per_instance_conservation_checker_fails_when_instance_dropped` (mutation sanity: remove one slice from emitted text → sim FAIL expected), `test_per_instance_imm_and_drain[count2]`.

**Checkpoint 3 — co-seated concentration > 1 (concentrator + demux) per companion doc.**
Work: `_render_seat_concentrator(seats, params)` + `seat_rsp_demux`; wire in `render_family_project_top` for multi-seat routers; narrow `_require_single_endpoint_per_router`; amend/flag companion §4.7 (seq-window → grant-FIFO) for operator decision; unit bench `tb_seat_concentrator_unit.sv` renderer.
Done = FatTreeIntent(4,2)-class request (endpoints [0,0,1[,1]] seated) lint+sims; A/B/C seat cases pass.
Exact targets:
```
cd tracks/t3-topology/dse && python -m pytest \
  tests/test_project_top_slice.py::test_composed_family_lints_and_sims \
  tests/test_project_top_slice.py::test_composed_family_refuses_multiple_endpoints_on_one_router \
  tests/test_project_top_slice.py -q -k "concentrator or seat"
```
(The last target collects the new `test_seat_concentrator_case_a_two_seats`, `..._case_b_four_seats`, `..._case_c_hold_release`, `..._unit_packet_lock` and the rewritten co-seat refusal case; all skip without verilator. `test_composed_family_refuses_multiple_endpoints_on_one_router` is rewritten from a refusal expectation into a concentrator-emission expectation for cmesh when Step 3 lands; until then it pins the interim typed refusal.)
Plus matrix smoke on the previously-blocked families (no runs here — target names for the landing PR):
`python -m pytest tests/test_project_top_slice.py::test_composed_family_lints_and_sims -q -k "cmesh or fattree or qtree or tree4"` (expects PASS or typed refusal only for pre-declared residual cases; never a silent crash).

**Checkpoint 4 — checker/manifest hardening + family sweep + kncube guard.**
Work: manifest `files`/hierarchy assertions; instance-aware `expected[]` across all families; rail-guard that per-instance conservation checker catches mutated golden (meta-test); re-run entire composed-family surface; docs ledger rows flipped only per checkpoint (never mid-sweep).
Exact targets:
```
cd tracks/t3-topology/dse && python -m pytest \
  tests/test_project_top_slice.py \
  tests/test_project_top_parameterized.py \
  tests/test_family_bad_design.py \
  tests/test_addr_decode_instance_spoof.py \
  tests/test_kncube_composed_top_lints_and_sims -q
```
(Last one listed as the KNCube harness pin — must stay green as-is; multi-instance work must not perturb the harness-only kncube path.)
Full-sweep gate (operator-run, not this lane): `python -m pytest tests/ -q` on a dedicated scratch tree, record PASS/FAIL counts per file in the ledger; **not** to be run as part of this proposal.

**Checkpoint 5 — release-facing: qualification wiring + docs.**
Work: 74-agent revision (`p-fd7e5e31be77-r02`) composed at a small-but-real scale for ≥1 concentrated family and ≥1 concentration-1 family; run pinned captures through the composed tops; update `REMAINING-WORK.md` item 5, `MILESTONE-14-PRODUCTION-RTL-20261110.md` P3 row, `P2-P3-EVIDENCE-20261110.md`, `INTENT-TO-PLACED-RTL-*`, `RTL-FINAL-CLOSEOUT-STATUS.md`, ledger; cross-doc consistency fix with `multi-seat-concentrator.md` §4.7.
Exact targets:
```
cd tracks/t3-topology/dse && python -m pytest \
  tests/test_project_top_slice.py -q -k "composed_family_lints_and_sims or never_drops or per_instance"
```
Plus the qualification harness entry points in `docs/product/evidence/` (pinned capture runner) — exact runner name to be fixed when the capture pipeline is wired; expected evidence artifact: per-family lint/sim/conservation JSON rows per instance, zero drops vs `attachment.endpoints` cardinality, `dbg_dest_errors == 0`, SRAM golden compare clean.
Sign-off criteria: (a) endpoint conservation — every compiled endpoint instance present in RTL exactly once; (b) lint clean with zero MULTIDRIVEN; (c) conservation + drain + imm==0 per instance; (d) all 14 families either green or typed-refused with named blocker; (e) docs updated in the same changeset.

---

## 8. Cross-document consistency & open questions for operator sign-off

1. Companion `multi-seat-concentrator.md` §4.7 (seq-window demux) vs this doc's grant-FIFO preference — one of the two must be withdrawn or amended; affects both docs' TB sections. **Operator decision required before Checkpoint 3.**
2. Memory-group multi-instance (HBM `count > 1`): refused in v1 (§4.7) — confirm intended, or schedule as checkpoint 6 (needs destination engine generalization, ~M).
3. Per-instance permission narrowing (§4.6): confirm stays out of v1 (spec INTENT-SYSTEM.md:201).
4. The `COMPOSED_GEC_MECS`/`COMPOSED_SROTA`/`COMPOSED_GEC_HYBRID` shared composers: same multi-instance question at flit level, no slices involved — sibling document to be requested if the 74-agent target selects one of those families for the pinned captures.
5. `_default_top`'s pinned `(group_idx) == (0, 1)` locked 2×2 mesh (lines 1513–1537): recommend leaving the locked path untouched so `runs/` golden artifacts and `test_project_top_slice.py` locked expectations keep byte-stability; confirm.
6. Ordering domain per instance: default keeps `initiator_in = '0` (per-slice domains, zero module changes); wiring per-instance ids is optional and only needed if a checker wants domain-distinct trace attribution. Confirm default retained.

## 9. File inventory (as-read, this date)

- `tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py` — the emission module (all line refs above).
- `tracks/t3-topology/dse/veritx_dse/product/rtl_export.py` — preview; adapter emission per group (lines ≈138–163; file write ≈221–226); `addr_decode.sv` emission via `render_addr_decode`.
- `tracks/t3-topology/dse/veritx_dse/product/addr_decode_rtl.py` — group-keyed default-deny decoder with existing instance narrowing substrate (`REQ_INST_W`, `req_inst`, `_initiator_instance_map`, ≈lines 160–172, 300–340, 425–495).
- `tracks/t3-topology/dse/veritx_dse/product/adapter_factory_rtl.py` — `adapter_module_name` (≈214–216), `build_adapter` (≈2554), module body group-independent.
- `tracks/t3-topology/dse/veritx_dse/product/cdc_cell_rtl.py` — `sanitize_module_name` (≈212–217) — instance-identity digest changes if insertion-point strings gain instance ids (Checkpoint 2 work).
- `tracks/t3-topology/dse/veritx_dse/model/attachment.py` — `derive_attachment` (431), seat enumeration (454–458), `Endpoint` (110–193), `validate_against_topology` (303).
- `tracks/t3-topology/dse/veritx_dse/model/placement.py` — `build_inventory` (198–212) canonical instance order.
- `tracks/t3-topology/dse/veritx_dse/model/address_permission.py` — `InitiatorPolicy` (55–79) — no `instance_idx` yet (§4.6).
- tests: `tests/test_project_top_slice.py` (refusals at 251–306; family lint/sim at 349–399; immediate/conservation golden at 1008–1063), `tests/test_project_top_parameterized.py` (slice-path guards incl. `test_three_initiators` at 291), `tests/test_addr_decode_instance_spoof.py`, `tests/test_family_bad_design.py`.
- sibling proposals: `multi-seat-concentrator.md`, `group-name-attachment-binding.md`, `kncube-intent.md`, `family-binding-guards.md`, `L3-WORKLOAD-QUALIFICATION.md`.

## 10. Acceptance checklist (definition of done for the milestone item)

- [ ] `composed_family_params_from_request` accepts count>1 compute groups; seats↔instances cardinality asserted.
- [ ] `run_composed_family` on a count=2 mesh4×4 request: lint PASS (zero MULTIDRIVEN), sim PASS with per-instance scenarios listed.
- [ ] `test_composed_family_never_drops_agent_instances[0|1]` rewritten from refusal to emission expectation; suite green.
- [ ] concentration>1 families either green through the concentrator (Cases A/B/C) or typed-refused with named blocker; `_require_single_endpoint_per_router` narrowed accordingly.
- [ ] No `router.sv`/`noc_pkg.sv` diff vs base tree; `git diff --stat` touches `project_top_rtl.py` + tests + docs only.
- [ ] All 14 FAMILIES14 rows: green or typed refusal in lane evidence; KNCube remains harness-only (explicitly not claimed).
- [ ] Ledger + milestone docs flipped in the same changeset as the final green checkpoint; evidence JSONs archived next to pinned captures.
- [ ] Zero "PASS" strings claimed in any doc without a matching runner artifact behind it.


## Measured refinement (main session, 2026-11-10, after the audit lane)

Three measured facts change the shape of the work — the expansion is **smaller** than the audit assumed:

1. **The compiler already seats every instance on its own router.** A request with `Agent(kind=COMPUTE_TILE, count=3)` on `MeshIntent(side_length=4, concentration=1)` compiles and the attachment carries:

   | endpoint_id | group_index | instance_index | router_id | port_id |
   |---|---|---|---|---|
   | 0 | 0 | 0 | 0 | 0 |
   | 1 | 0 | 1 | 1 | 0 |
   | 2 | 0 | 2 | 2 | 0 |
   | 3 | 1 (HBM) | 0 | 3 | 0 |

   `seat_capacity` is 1 per router on concentration-1 fabrics. **No concentrator is needed for concentration-1 families** — the seat data the composed builder needs already exists in `bundle.attachment.endpoints` and in the `seats` tuple it derives (`project_top_rtl.py:4780`).
2. **The refusal is a builder-side artifact, not a compiler limit.** `composed_family_params_from_request` refuses `count != 1` at `:4606-4609` and then keeps only the *first* endpoint's router per group (`group_routers`, `:4785-4791`), emitting one `SliceInitiator` per group (`:4798`). Every other instance's router is silently dropped — exactly the endpoint-loss the guard exists to catch.
3. **The emitter is group-keyed, not endpoint-keyed.** Wrapper nets/slices are `init{gi}_*` (`:5850`, `:5952`), the adapter binding is hardcoded to `INIT_ID == 0` for `g_adap0|g_adap1` (`:5696-5717`), `req_id` is a 1-bit "non-zero group" flag (`:5723`), CDC cells are group-keyed (`:1066`, with an `up_cells` dict overwrite at `:1101`), and the family TB drives one initiator per group (`:6033-6352`).

### Minimal implementation (concentration-1 families)

| # | Change | Where | Effect |
|---|---|---|---|
| 1 | Delete the `count != 1` refusal; replace with a **co-seat** refusal | `project_top_rtl.py:4606-4609` | multi-instance requests proceed; co-seated endpoints (two endpoints on one router, i.e. concentration>1 or a family whose seats demand it) still refuse, naming the concentrator that is missing |
| 2 | Build `initiators` from the `seats` table (one per endpoint, memory group excluded), each carrying `group_idx`, `instance_index`, `router_id`, `port_id` | `:4798` | every compiled instance reaches the hardware; no instance is dropped |
| 3 | Extend `SliceInitiator` with `instance_index` / `port_id` | `:214` (dataclass) | the emitter can address instance-local nets |
| 4 | Rename emitter nets `init{gi}_*` → `init{gi}_{ix}_*`; instantiate **one adapter per initiator** (same adapter module, distinct `INIT_ID`); bind each adapter to *its own* router local port | `:5696-5717`, `:5850`, `:5952` | N instances ⇒ N adapters ⇒ N injection paths |
| 5 | Make `req_id` carry the endpoint id (not a 1-bit group flag) and keep permission policy per endpoint | `:5723` | per-instance permission isolation survives |
| 6 | Key CDC cells by endpoint, not group | `:1066`, `:1101` | no cross-instance state overwrite |
| 7 | Family TB: drive every initiator, assert per-initiator conservation and `outstanding == 0` at drain | `:6033-6352` | the new capability is proven, not asserted |
| 8 | Mutation test: remove one instance from the emitted top ⇒ conservation MUST fail | new test | guards against false-green (the failure mode the audit warned about) |

Co-seat families (concentration>1: cmesh, and any fabric whose seat law puts two endpoints on one router) additionally need the concentrator + response demux from `multi-seat-concentrator.md`; until that lands they keep a **typed refusal naming the concentrator**.

### Order of work (each step independently verifiable)

1. Steps 1+2 (+ the refusal rename) — compile-level multi-instance admission; unit-testable without Verilator.
2. Steps 3-6 — emitter expansion; verified by lint + the existing family TB (no new scenario needed: the 3-agent request already has 3 seats).
3. Step 7 — TB per-initiator assertions.
4. Step 8 — mutation guard.
5. Then: multi-seat concentrator + demux (separate proposal), then the KNCube general path (already green), then L3 workload qualification on the now-multi-instance slice.
