# #20 — per-(tap, VC) credit pools for the hybrid and SROTA shared-wire fabrics

Status: **spec, not a claim.** No RTL changed by this note. Every line cite was read
from the tree at `79edf46e`. Written because #20 is the item gating both remaining
`final_implementation: false` verdicts, and because the two fabrics live in
`project_top_rtl.py` — the one file two sessions have been editing concurrently — so
the work should start from a plan, not from an edit.

## Why this item, and why first

`SROTA_SHARED_NOT_ESTABLISHED` and `GEC_HYBRID_SHARED_NOT_ESTABLISHED` each end with a
credit/claim row that keeps their verdict false, while their AXI/ordering/CDC rows
(#15, #18) describe *composition* onto the fabric. Composing protocol adaptation onto a
credit path that is still occupancy-based would qualify the wrong thing first: the
adaptation's backpressure would rest on a credit signal that is not per-(tap, VC), so a
later switch to real pools would invalidate the qualification anyway. Fix the credit
path first, then compose.

## What already exists — do not rebuild it

- **The primitive ships and is proven.** `tracks/t3-topology/rtl/tap_credit/tap_credit_pool.sv`
  is per **(tap, VC)**, not per wire: `req_tap`/`req_vc`/`req_valid` → `req_grant`
  (`:38-42`), free notification on the exact pair (`:45-47`), and packed observation
  arrays `credits`/`outstanding` shaped `[N_TAPS][NUM_VCS][CREDIT_W]` (`:51-52`) that
  stay inside the Verilog subset the formal engine reads.
- **GEC-MECS already instantiates it** — `gec_mecs_credited.py:487,497`, with the module
  copied from `POOL_SOURCE = .../tap_credit/tap_credit_pool.sv` (`:79`), and accounting
  per (wire, tap, VC) in `gec_mecs_scaled.py:22`. The emitter adds `tap_credit_pool.sv`
  to the Verilator file list only for that family (`project_top_rtl.py:7444`).
- **The grant law to copy** is already written down for GEC-MECS
  (`project_top_rtl.py:7728`): "round-robin-earliest VC whose first-hop (tap, VC) pool
  has a credit".

So #20 is a **transplant**, not a design: the same module, the same grant law, two
different router templates.

## What the refusal itself says is missing

Every hybrid refusal names the artifact verbatim, e.g. `project_top_rtl.py:8011`:

> `RTL GetUsedCredit-equivalent observable with per-output and per-tap identity,
> occupancy accounting, credit-return visibility cycle, 6VC 8flit-per-VC 48flit buffer
> pin and differential selector tie evidence`

That string is the acceptance test, in the refusal's own words: an RTL-visible
used-credit signal with **per-output and per-tap identity**, a **credit-return
visibility cycle** (when a granted flit becomes countable-free again), and the buffer
pin as **6 VC × 8 flits × 6 routers-worth** = the 48-flit-per-router figure the manifests
already carry (`vc: 6`, `taps_per_wire: 3`, `shared_wires: 32`).

## Shapes to parameterise (from the manifests, `project_top_rtl.py:11809,11883`)

| fabric | shared wires | taps/wire | VCs | pool params |
|---|---|---|---|---|
| `COMPOSED_GEC_HYBRID` (16 routers) | 32 (+48 mesh channels) | 3 | 6 | `N_TAPS=3, NUM_VCS=6, CAPACITY=8` |
| `COMPOSED_SROTA` (16 routers) | 48, island_columns `[1]` | derived from island law | 2 | `N_TAPS=?, NUM_VCS=2, CAPACITY=8` |

SROTA's tap count is the open parameter: its column tiling is island-derived
(`SROTA_VALIANT_RANK_NOT_MODELED` keeps Valiant and hop-rank out), so the pool must be
instantiated per **wire** with `N_TAPS` = that wire's own tap count, exactly as
`gec_mecs_credited.py:23` notes ("one pool per wire").

## Ordered work

1. **Emit the pool per shared wire** in both templates, sized from the wire's actual tap
   count rather than a constant. Keep `tap_credit_pool.sv` out of the file list for
   families that do not use it (`:7444` gates it on family today — that gate must widen).
2. **Replace the occupancy test** in admission with `req_grant` from the pool, preserving
   the existing **all-or-nothing multicast admission** (every selected tap's pool must be
   free before the wire is driven) — that rule is a proven claim and must not regress.
3. **Expose the observable**: `credits`/`outstanding` out to the TB, so the
   `GetUsedCredit`-equivalent is visible per output and per tap, with a
   credit-return-visibility cycle the TB can check.
4. **Assert the identity in the TB**, not in prose: `free + outstanding == CAPACITY` per
   (tap, VC) every cycle, plus conservation unchanged (`accepted == delivered`, drain to
   zero), on all 256 ordered pairs and the multicast sets already measured.
5. **Re-run the row** and record `credit_pin` in the manifest (the hybrid manifest already
   carries `"credit_pin": params.to_dict()` at `:11883` — make it describe pools).
6. **Then move the claim**: the occupancy sentence leaves `NOT_ESTABLISHED` and a
   measured sentence joins `PROVEN` — in both scopes, separately, each with its number.

## Acceptance must include the negative

An occupancy-based fabric must **fail** the same TB check. Otherwise the new identity is
passing because it is vacuous (a pool that reports `CAPACITY` forever satisfies
`free + outstanding == CAPACITY`). This is the same discipline the arbiter proof used,
where a deliberately weaker `ESC_YIELD_K` guard had to fail the encoding.

## Hazard

`project_top_rtl.py` is the contended file. Do this **after** the session that has it
open commits, or in a worktree, and never with a text-transform script over a file
containing Verilog in Python strings — that mistake is already recorded in
`docs/product/proposals/multi-seat-concentrator.md` (45 chunks deleted, 101 lines,
rebuilt from a snapshot).

Verification, once implemented, is the ordinary row re-run — the compose tests are the
expensive part (~40-60 s each), so run the two family cases before the whole file.
