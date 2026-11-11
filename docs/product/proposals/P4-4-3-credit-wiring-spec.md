# P4 4.3 wiring spec — per-tap credits inside the multidrop shared fabric

Status: **applied to the product's shared fabric** (2026-11-11). The credit pool is built and formally proven (`tracks/t3-topology/rtl/tap_credit/tap_credit_pool.sv`); this file says exactly how to put it into the shared fabric, what must hold, and what proves it.

## What was applied, and where

`veritx_dse/product/gec_mecs_credited.py` transforms the shipped fabric template into the credited fabric — the template is transformed, not re-implemented, so the routing logic stays single-sourced, and every replacement is anchored: if an anchor is missing the transformation **refuses** instead of emitting a half-wired fabric.

* **Credit domain.** One `tap_credit_pool` per router per wire (row, column). The pool is already per (tap, VC), so one instance per wire IS the (port, tap, VC) domain the contract names — no pool change was needed.
* **VC and tap echo in the flit.** The shared flit gains a VC field and a tap-echo field. The VC is what the credit is claimed against; the tap echo is what the far end returns, so a release comes back to the exact (tap, VC) it was taken from — no alias.
* **Credited grant.** A candidate is only offered if its exact (tap, VC) has a credit, so an exhausted tap never blocks the other taps of the same wire. The credit is claimed **when the flit actually moves onto the wire** — claiming it for a flit the wire cannot take would burn a credit that no dequeue would ever return.
* **Release path.** The far end's dequeue produces a credit return for the exact (tap, VC). The return is **held by the destination until the fabric has taken it** (a one-cycle pulse is lost whenever the fabric serves another source that cycle), and the fabric serves the holding destinations round robin per source, so no return is lost and no destination is starved.
* **Observable.** The fabric exposes per-router credit state (available, outstanding, alias-detected), so the accounting is checkable from outside the DUT instead of being asserted in prose.

Gate test: `tests/test_gec_mecs_credited_fabric.py` (lint + simulation at the full 81-router shape, the pool-source check, the anchor-refusal check, and the historical-16-router-untouched check).

## A defect the accounting tests found: the tap index was truncated

The credit path took the **tap index** from the template's `row_vc`/`col_vc` outputs. In the shipped template those ports are **2 bits wide** — the native GEC-MECS design has three taps per wire and encodes the tap in the VC ("one VC per tap"), so `row_vc` was 2 bits by construction. A scalable shape has five taps per wire (`TAP_W = 3`), so the tap index was truncated on its way to the credit pool: tap 4 became tap 0.

The failure was silent and asymmetric, which is why it survived the first round of tests:

* the **claim** side read the truncated value, so the credit was charged to the wrong (tap, VC) pool;
* the **release** side recomputed the index from the topology, so the credit came back to the pool it was *not* charged to;
* that pool's `outstanding` counter decremented from zero and wrapped (0 → 15 in a 4-bit field), so the aggregate read 81 outstanding against a capacity of 4.

It reproduced only at five taps or more, which is why the small shape passed and the 36- and 81-router shapes failed. The arithmetic that identified it: a sound pool satisfies `available + outstanding == capacity` per (tap, VC); the observed 99 + 81 against a capacity of 100 is exactly five pools that underflowed.

The fix takes the tap index from the TAP_W-wide `drop_idx` directly and leaves the template's 2-bit `row_vc`/`col_vc` outputs at their native width and meaning. The credit path no longer depends on a port whose width the template chose for a different design.

## What the measurement does and does not show

The directed over-subscription scenario in the generated testbench proves the accounting end to end at the full 81-router shape: a credit is claimed when the flit moves onto the wire, it is still outstanding while the flit is in flight, it never exceeds the capacity, no return is ever aliased to another tap, and it comes back when the far end dequeues the flit.

The limit is the wire **model**, not the accounting: the wire delivers one flit per wire per cycle to one destination, so the credit is rarely the *binding* constraint today — the model's own per-destination queue depth is what throttles. Making the credit the binding constraint needs a pipelined wire model (several flits in flight per wire), which is a fabric-model change, not a credit-wiring change.

The pinned historical 16-router artifact is deliberately left byte-identical: it is cited evidence, so the credited fabric is emitted for the scalable (product) path.

## The gap, measured

The shared GEC-MECS fabric (`GEC_MECS_FABRIC_SV`) contains **zero** credit accounting — no `cred` signal exists in it. Each router owns one row wire and one column wire; each wire carries `d` taps, and the receiver's position selects the tap (`drop_idx = (dest_x < my_x) ? dest_x : dest_x - 1`). So a wire is a multidrop bus whose taps are independent destinations, but the flow control is per *port*, not per *tap* — two taps on the same wire cannot be distinguished in the credit domain, which is precisely what the pinned contract (162 wires × 3–8 taps × 8 VCs) requires.

## What must change (the fabric router module)

1. **Credit domain.** Credits are held per **(output port, tap, VC)**: the port is the row wire, the col wire or the local port; the tap is the drop index on that wire (0 … d−1); the VC is the virtual channel. The existing `drop_idx` computation already yields the tap for a granted row/col flit — it becomes the credit-pool index.
2. **Instance the proven pool.** One `tap_credit_pool` per router, with `N_TAPS = d` and `NUM_VCS = <bundle vc count>`, plus the required `PORT` dimension (the pool is per (tap, VC) today; it must be instantiated per output port, or extended to (port, tap, VC) — the latter is one extra index dimension in the pool and keeps a single instance per router).
3. **Grant path.** A row/col grant consumes a credit of `(port, tap=drop_idx, vc=flit_vc)`; the pool's `req_grant` replaces the current "always allowed" behaviour. A grant that finds no credit must not forward the flit — the flit stays queued.
4. **Release path.** When a flit is dequeued at the far end of a wire, the source's pool must be told `(port, tap, vc)` — today the fabric has no release path at all. The release must carry the *tap* the flit was sent to, so the credit returns to the same tap it was taken from (no alias).
5. **Latency.** The pool's return latency (`LATENCY`) must match the wire's declared latency (`latency_cycles` in the bundle's shared links); a mismatch silently over- or under-subscribes a tap.
6. **VC extraction.** The flit carries its VC in a fixed field (the composed path's `[W-DEST_W-2 .. W-DEST_W-1]`-style slot — confirm the exact offsets for the shared fabric before wiring).

## What must hold (the properties to prove)

| # | Property | How to check |
|---|---|---|
| W1 | Credits + outstanding == capacity per (port, tap, VC) | extend the formal harness: `tap_credit_formal.sv` with the port dimension and the release path driven from the fabric's own dequeue events |
| W2 | No tap may exceed its capacity while another tap on the same wire is idle | property over the pool with per-tap environments (the existing proof covers cross-tap isolation; add the port dimension) |
| W3 | A release returns the credit to the exact (port, tap, VC) it came from | the pool's `alias_detected` output must stay low under the fabric's real release pattern |
| W4 | No flit is forwarded on a wire whose tap has no credit | an assertion in the fabric: `grant ⇒ credit_consumed` |
| W5 | The fabric's behaviour is unchanged when credits are never exhausted | the existing shared TB must stay green (it is: `tests/test_project_top_shared.py`) |

## Verification plan (each step independently checkable)

1. **Pool extension**: add the port dimension to `tap_credit_pool.sv`; re-run the formal proof (expect PASS with the same properties, one dimension wider) and the simulation.
2. **Fabric wiring**: instantiate the pool per router; convert the row/col grant path to a credited grant; add the release path from the far-end dequeue with the tap carried in the flit (the kernel field is free in the default profile — verify before use).
3. **Directed over-subscription test**: drive more flits to one tap than its capacity and prove (a) the excess is NOT forwarded, (b) the other taps keep flowing, (c) the credits recover after release.
4. **Regression**: the shared TB (k=4 and the pinned k=9) must stay green, and the pinned-shape gate (`tests/test_gec_mecs_pinned_shape.py`) must still pass.

## Honest scope note

This is the last mile for plan row **P4 4.3** and it is *not* a small edit: it changes the grant path of the shared fabric router, adds a release path across the wire, and needs a directed over-subscription test. It is also the change that makes the 81-router contract's flow control real rather than nominal. The substrate (pool + proof) is done and locked; this file is the wiring recipe, sized so it can be applied as one reviewed change.
