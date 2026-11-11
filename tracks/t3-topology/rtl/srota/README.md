# Srota Plane D RTL — extracted from the three rev 0.3 sub-documents

This directory is the first extraction of the RTL-facing material in:

- `SSM-UARCH-ROUTE-001_Routing_Algorithm_rev0.3`
- `SSM-UARCH-VC-002_VC_Mapping_Allocation_rev0.3`
- `SSM-UARCH-TOPO-003_Topology_MECS_rev0.3`

It is deliberately **not** wired into the product preview emitter yet. The
product emitter remains the certified 64-bit / 2-VC free-escape preview. These
files are an extracted, partially integrated Srota RTL slice, not a complete
implementation of the documents or a product-preview control path.

## What is here

| File | Source |
|---|---|
| `srota_route_pkg.sv` | ROUTE-001 §8, §10, §11; TOPO-003 §10 |
| `srota_route_compute.sv` | ROUTE-001 §11.1 |
| `srota_arb.sv`, `srota_arb_l0_golden.sv`, `srota_arb_l1_slack.sv`, `srota_arb_l2_stc.sv` | ROUTE-001 §11.2, §8.3 |
| `srota_fiu_pathsel.sv` | ROUTE-001 §10 |
| `srota_credit_mgr.sv`, `srota_sidebuf.sv` | VC-002 §10, §11 |
| `srota_drop_cell.sv`, `srota_mecs_row.sv`, `srota_mecs_col.sv` | TOPO-003 §11 |
| `srota_router_d.sv`, `srota_top.sv` | ROUTE-001 §7; TOPO-003 §7 |
| `tb_srota_route_compute.sv` | ROUTE-001 §11.1; TOPO-003 §9.1 |
| `tb_srota_sidebuf.sv` | VC-002 §6.1; side-buffer handshake extension |
| `tb_srota_router_valiant.sv` | ROUTE-001 §13.4; internal preview transition |
| `tb_srota_router_stall.sv` | Router ready/valid stall regression |
| `lint.sh`, `sim_route.sh`, `sim_sidebuf.sh`, `sim_router_valiant.sh`, `sim_router_stall.sh`, `verify.sh` | Verilator lint and directed simulations |

## Deliberate assumptions / corrections

1. **Header layout is a preview.** The final field offsets are owned by
   SSM-UARCH-PKT-008. `srota_route_pkg.sv` states the preview layout so the
   leaf RTL can be linted; replace it when #8 lands.
2. **Port map is one VC-R5 reading.** `P = 2*c + 8`: per-tile local
   injection/ejection, four mesh neighbours, four MECS drop ports. The doc's
   P=12 at c=4 and its "≤6-port mesh stage" do not reconcile; VC-R5 remains
   open. The RTL exposes `P` and the port functions, so changing the map is a
   package edit, not a rewrite.
3. **Drop-cell credit direction.** TOPO-003 §11.2 declares
   `drop_credit_ok` as an output but never drives it, while `srota_mecs_row`
   connects it to an input. The extracted cell takes `credit_avail` as an
   input and passes it through to `drop_credit_ok`; the row channel computes
   `drv_credit_ok` from its `drop_credit` input. This is recorded rather than
   silently "fixed" in the doc.
4. **Multicast match hazard.** TOPO-003 §11.2 keeps the unicast equality
   term live during multicast: `(ch_dst_idx == cfg_my_idx) | bmp[idx]`. If a
   driver parks `drv_dst_idx` on an unselected drop while the bitmap is
   non-zero, that drop also asserts `drop_vld`. The row's `sel`/credit
   reduction uses only the bitmap, so the spurious tap is not covered by
   `drv_credit_ok`. This is inherited verbatim from the document; gating the
   equality with `~|ch_mcast_bmp` would fix it but would deviate from the
   specified expression. Recorded as an open doc hazard.
5. **Bypass path.** The nominal ST0/ST1/ST2 path is implemented first. The
   bypass equation (ROUTE-001 §9.4) is a separate term and is not claimed
   until it is wired and verified.
6. **No final qualification.** Lint is syntax/connectivity, not simulation
   equivalence, timing closure or hardware qualification.

## Deadlock scope

ROUTE-001 RT-R7 remains unresolved: the deadlock argument does not establish
safety when row-first and column-first path shapes mix. No deadlock-freedom
claim is made for enabling both shapes; use the row-first-only baseline until
the architecture issue is closed. The FIU leaf can select any enabled shape,
and the smoke router does not enforce this system-level configuration rule.

## Side-buffer write handshake

`srota_sidebuf` and `srota_credit_mgr` expose `sb_wr_ready`, `sb_wr_accept`,
and `sb_full`. `alloc_loss` is a request bitmap, but the side buffer has one
write port: only a one-hot bitmap requests capture of the candidate identified
by `sb_wr_flit`/`sb_wr_port`. `sb_wr_accept` pulses only when that candidate is
stored. A multi-bit bitmap is not accepted. Following VC-002 §6.1
drain-before-fill ordering, an already-full buffer accepts a one-hot candidate
when a same-cycle drain frees a slot; occupancy remains full after that
simultaneous drain and fill. Full without a drain still backpressures. The
upstream staging logic must retain and retry each unaccepted loser, serializing
simultaneous losers.

VC-002 is not present in this checkout, and its cited sections do not establish
a multi-loser selection/holding protocol from the available RTL references.
This handshake is therefore an explicit narrow extension, not a claim that the
router implements loss-safe loser staging. `srota_router_d` ties the side-buffer
request off, so it does not currently exercise or satisfy this contract.

## Valiant leg transition preview

At ingress to staging, `srota_router_d` checks the flit's `SROTA_VALIANT_L1`
shape against the router coordinates and the flit's cached intermediate. Only
on a match does it rewrite the staged shape to `SROTA_ROW_FIRST`; route
computation then uses that rewritten flit and targets its final destination.
The cached intermediate coordinate fields are preserved. This extracted
preview models the document's local reinjection at the internal staging
boundary, before forwarding; it does not eject the packet at the intermediate.

Run `./sim_router_valiant.sh` for the focused router-level check of both a
matching and non-matching intermediate. This is not an end-to-end Valiant
proof. Full packet/protocol #8 integration remains open.

## Verification

Run `./verify.sh` to run all checks. Individually, `./lint.sh` lints all 13
modules; `./sim_route.sh` runs 15 route/drop checks; `./sim_sidebuf.sh` checks
side-buffer handshakes; `./sim_router_valiant.sh` checks the intermediate
rewrite; and `./sim_router_stall.sh` checks ready/valid stability under
contention. These checks do not demonstrate integrated allocation, multi-loser
retry, Valiant end-to-end proof, full topology wiring, or product-preview
control reach.

## Integration limits

- `srota_top` is a one-router smoke wrapper; it does not generate or connect a
  K×K mesh/MECS fabric.
- `srota_router_d` uses a generic per-output allocator with neutral metadata;
  the document's coupled mesh/express stages and rotating stage precedence are
  not implemented here.
- The FIU path selector is a leaf module, not wired into router ingress. The
  preview header supplies route shape/intermediate fields directly.
- Side-buffer loser capture/reinjection is quiescent in the smoke router; its
  write handshake is tested separately, but multi-loser staging/retry and
  upstream credit withholding are not integrated.
- The ROUTE-001 §9.4 bypass is not wired. No timing, synthesis, deadlock,
  ordering, or end-to-end hardware qualification is claimed.
