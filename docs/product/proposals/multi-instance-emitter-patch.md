# Multi-instance emitter patch — exact change set for the composed family path

Status: **APPLIED 2026-11-10 (main session)**, with the zero-regression proof below. The seat-planning half landed first and green: `veritx_dse/product/multi_instance_seats.py` + `tests/test_multi_instance_seats.py` (7/7). The emitter half landed after the parallel session's in-flight edits settled; it was applied against a snapshot taken at 18:26 (`runs/` scratch copy), and every existing design's rendered RTL is byte-identical afterwards.

**What was applied (the naming design that made it small):**

- `INIT_ID` stays the **group** id (permissions, `req_id`, adapter module selection are group properties) — so the slice template needed **no change** and the zero-regression property holds.
- The composed top and its testbench became **endpoint-keyed** in signal names only: `init{endpoint}`, `dbg_imm{endpoint}`, `slice_inj/ej/imm{endpoint}_w`, `u_slice{endpoint}`, `do_write{endpoint}` / `do_read{endpoint}`, per-endpoint sequence counters and per-endpoint data patterns.
- `SliceInitiator` gained `instance_index` and `endpoint_index`.
- `composed_family_params_from_request` now derives initiators from the seat plan (one per compiled agent instance) instead of one per group; the old `count != 1` refusal is gone, and a co-seated plan refuses **by name** (concentrator + response demux missing).
- The composed builder's own manifest/expected-scenario tables key off the endpoint, so the TB's expectations follow each endpoint's group permissions.

**Zero-regression proof (measured, not asserted):** the torus composed top and its testbench rendered **byte-identical** before and after the change (`project_top.sv` sha256 prefix `b548dcc5bc8b0e272f927845`, `tb_family.sv` `f3064577f75c73e7f1b31854`), because for one-instance-per-group designs the endpoint index equals the group index.

**Also fixed while in the file (a pre-existing breakage from the parallel session's in-flight concentrator work):** `run_composed_family` referenced `concentrated` without defining it, so **every** composed-family run raised `NameError` at the manifest step. One line restored (`concentrated = params.family == "concentrated_mesh"`).

## Preconditions (measured today)

- The compiler seats every instance on its own router on concentration-1 fabrics: `Agent(COMPUTE_TILE, count=3)` → endpoints `(group 0, inst 0, r0)`, `(group 0, inst 1, r1)`, `(group 0, inst 2, r2)`; `seat_capacity == 1`.
- `bundle.attachment.endpoints` carries `(agent.group_index, agent.instance_index, router_id, port_id)` — everything the emitter needs.
- `req_id` is **group**-indexed by design (`project_top_rtl.py:3991`: "req_id is the agent GROUP idx tied to the initiator port by project_top (trusted ingress); never inferred from wire bits"), and permissions are per group (`AgentIntentV4` per group). **Instances of one group therefore share `req_id` and permissions — no decoder change is needed.**

## Change set

### 1. `composed_family_params_from_request` — admission + per-endpoint initiators
Current (`:4606-4609`):
```python
    # The composed wrapper has one initiator/target port per group, not per seat.
    if any(int(a.count) != 1 for a in request.agents):
        raise _refuse_family(
            "composed endpoint adapters require one instance per agent group; "
            "multiple instances would be omitted from the generated top")
```
Replace with: no count restriction. Build the initiator list from the attachment via the applied `plan_endpoint_seats(request, compiled)`; a co-seated plan raises `MultiSeatUnsupported` → convert to `_refuse_family(str(exc))` (message already names the concentrator + response demux). Keep the memory group out of the initiator list (it is the destination).

### 2. `SliceInitiator` — carry the instance identity
Add `instance_index: int = 0` (endpoint order is the list order; `group_idx` stays the permission/req_id identity).

### 3. Slice template — adapter by group, req_id by group
The family slice template currently selects the adapter with `if (INIT_ID == 0) adapter_axi5_g0 else adapter_axi5_g1` and passes `.req_id((INIT_ID != 0))`. Both are group-keyed assumptions. Change to:
- parameter `GROUP_ID` (int) added to `initiator_slice`;
- the adapter generate becomes a case over `GROUP_ID` enumerating exactly the groups present in this design (emitted per design, not a fixed 0/1 pair);
- `.req_id(REQ_ID_W'(GROUP_ID))`.

`INIT_ID` then becomes the *endpoint* index (unique per slice instance) and is used only for uniqueness/debug.

### 4. Composed top emitter — endpoint-keyed nets
In `render_family_project_top` and `render_family_tb`, every signal name of the form `"init" + str(gi) + "_…"` becomes endpoint-keyed. **Zero-regression naming rule:** the endpoint index equals the group index for today's 1-instance-per-group designs, so every existing name and every existing test expectation stays byte-identical. Multi-instance designs get `init{endpoint}` names in endpoint order (group ascending, instance ascending).
Sites: top ports (`:5868-5896`), slice instantiation (`:5958-5966`), `dbg_*`/`slice_*` counters (`:5945-5952`), CDC cells (`:1066`, `up_cells` dict at `:1101`), TB nets/seq counters/`hero` selection (`:6033-6352`).

### 5. TB — drive every endpoint
The family TB already loops over `params.initiators`; the keys become endpoint-indexed. Permission expectations follow the **group** (`ini.writable` / `ini.readable` are group properties) — so two instances of a read-only group are both read-only, and the "deny_write_init1" style scenario generalizes to "deny write for every read-only endpoint".

### 6. Manifest
`family_params.initiators` entries gain `instance_index` and `endpoint_index` so the evidence shows which instance sits where.

### 7. Mutation guard (anti-false-green)
New test: build a multi-instance design, then remove one instance from the emitted top → conservation MUST fail. Without this, a dropped instance could pass silently — the exact failure mode the endpoint-loss guard exists to catch.

## MEASURED — 2026-11-10: landed and proven

**Result: a two-instance agent group now compiles, emits two distinct endpoint paths, and simulates green end-to-end.**

| Measure | Value |
|---|---|
| Multi-instance composed top (group 0 with `count=2`, plus one HBM group, mesh 2x2) | **lint PASS, sim PASS, 13/13 scenarios true** — `allow_write_init0`, `allow_read_init0`, `allow_write_init1`, `allow_read_init1`, `error_miss`, `error_slv`, `ordering_stall`, `ordering_inorder`, `backpressure_stall`, `backpressure_release`, `concurrent`, `conservation`, `drain` |
| Emitted top | **two** `initiator_slice` instances with **two** distinct endpoint port sets (`init0_*`, `init1_*`) and separate sequence state per endpoint |
| Regression tests | `tests/test_multi_instance_composed.py` + `tests/test_multi_instance_seats.py` → **12/12 green** |
| Zero regression | torus composed top and its testbench render **byte-identical** to the pre-change baseline (`project_top.sv` `b548dcc5bc8b0e272f927845`, `tb_family.sv` `f3064577f75c73e7f1b31854`); the torus family test passes |

**What the change actually was (smaller than the original plan):** `INIT_ID` stays the **group** id, so the slice template needed no change at all — permissions, `req_id` and adapter-module selection are group properties. Only the *top-level naming* became endpoint-keyed (`init{endpoint}`, `dbg_imm{endpoint}`, `slice_inj/ej/imm{endpoint}_w`, `u_slice{endpoint}`, `do_write{endpoint}`/`do_read{endpoint}`), together with per-endpoint sequence counters and per-endpoint data patterns. The builder's initiator list now comes from the seat plan (one per compiled agent instance), and the old "one instance per agent group" refusal is gone.

**Honest record of the two bugs I introduced and fixed during this work (both caught by measurement, not by inspection):**

1. A blanket `str(gi) → ek` substitution also rewrote the *sequence-counter reset loop* (`for gi in next_seq: next_seq[gi] = 0`) into a form that reset only the last initiator's counter. Symptom: the post-reset write timed out in **both** the one-instance and the multi-instance designs; the torus family test went red. Fixed by restoring the loop, after which the torus TB rendered byte-identical again and the torus test passed.
2. A "drain before reset" guard was added to the **parameterized** TB by mistake (wrong builder). It was removed rather than left in — the multi-instance case passes without it, so the guard is not needed.

**Still open (unchanged):** co-seated fabrics (concentration>1) still refuse by name — they need the concentrator wired between the per-seat slices and the router local port (`multi-seat-concentrator.md` has the proven primitive; the wiring is the remaining work). The full-size 74-agent Mixtral still needs its own multi-instance run through the same path, and KNCube native equivalence stays operator-blocked.

1. Steps 1+2 — unit-level: `plan_endpoint_seats` on a 3-instance request returns 3 distinct routers; the composed path no longer refuses `count > 1`. No RTL change yet, so the family suite must stay green.
2. Steps 3+4 — emitter: lint PASS for a multi-instance family top; the 1-instance designs must produce **byte-identical** RTL to today (compare sha256 of `project_top.sv` before/after) — that is the zero-regression proof.
3. Step 5 — TB drives N endpoints; per-endpoint conservation and `outstanding == 0` at drain.
4. Step 6 — manifest carries instance identity.
5. Step 7 — mutation guard.
6. Then: the full-size Mixtral (74 agents) can be attempted end-to-end; the concentrator (co-seated fabrics) remains a separate proposal.

## What this does NOT close

- Co-seated families (concentration>1: cmesh; any fabric whose seat law puts two endpoints on one router) still refuse — they need `multi-seat-concentrator.md` (injection arbiter + per-seat response demux).
- Multi-flit packets, credit pools, tap aliasing (P4 audit rows 4.1/4.3/4.4) are untouched by this change; the P4 audit remains the authority on those.
- `final_implementation` stays `false`.
