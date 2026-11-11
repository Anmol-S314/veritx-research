# Final-implementation status — 2026-11-11 (after the lint work)

Companion to `FINAL-IMPLEMENTATION-HANDOFF-20261111.md`. It records what the
lint work closed, what is still open, and the commands that produce the
evidence.

## Closed: the composed lint is warning-free

Every family that carries the `COMPOSED_FAMILY` scope now lints with **zero
warnings** under the product's own lint command
(`verilator --lint-only -sv -Wall -Wno-fatal -Wno-WIDTH -Wno-PINNOTFOUND
-Wno-UNOPTFLAT --top-module project_top <dut_files>`), and the simulations stay
green:

| family | warnings before | warnings now | sim |
|---|---|---|---|
| mesh, torus, concentrated_mesh, ring, qtree, tree4, flatfly, fattree, dragonflynew | 535 | 0 | PASS |
| fly | 768 | 0 | PASS |
| gec_mecs | 41 | 0 | PASS |

The findings were fixed by **wiring**, not by a blanket flag:

- **project_top** — a seat-less router's local port is tied off and its
  outputs are consumed by named sinks.
- **router** — the knobs the router does not implement
  (`SWITCH_ALLOC_CYCLES`, `ALLOC_ITER`, `ALLOCATOR_ISLIP`) and the dead
  round-robin state are gone; the field bounds now come from `noc_pkg`; the
  grant scan's per-candidate values are hoisted so no branch can leave the
  lint inferring a latch; the ascending-index convention is switched off
  **by name, with the reason stated** (flipping the ranges would reorder the
  ports, because the noc_top concatenates them in the same order).
- **noc_pkg / initiator_slice / destination_adapter / noc_top** — the package
  publishes only what the RTL reads; the slice's inert `CDC_CROSSED` knob and
  its unused `fabric_clk` port are gone (a crossed slice gets the port back
  on demand); the tied AXI pins keep their per-pin reason; the next-hop table
  entries a family does not consult are consumed; the fly family's
  non-reciprocal ports are tied off.
- **gec_mecs** — the proven credit pool and the router now travel in their
  own files (one module per file), the package is reduced to what the family
  reads, the fabric's reset is asynchronous like the slices', and the fabric's
  unused bookkeeping nets are consumed.

**Two rules worth keeping** (both cost a full re-lint):

1. A sink must carry an **explicit width**. Verilator treats a sink whose
   width is inferred as a one-bit placeholder, so it does not consume the
   source signal's other bits — the difference between 133 warnings and 0.
2. A sink whose name starts with `unused` is exempt from its own warning,
   but its read does **not** count as a use of the source.

**A real defect was found on the way**: the emitted destination adapter
assigned a Verilog *string literal* to the read-data register (a mis-escaped
Python literal), so the out-of-range/error read path returned garbage instead
of zero. Fixed.

## Closed: the evidence path

- **A8 (BookSim/RTL parity)** was already repaired: the harness gets an
  AnyNet *path* and a real RTL directory.
- **Positive evidence bundle** — `tests/test_final_implementation_evidence_positive.py`
  measures A3/A6/A7/A8/A9/A10 per family, measures A1/A2/A4/A5 from the
  family's own emission, writes
  `docs/product/evidence/final-implementation/<family>.json` keyed to
  `request.design_hash()`, and asserts the verdict closes. The negative test
  stays as it was.

## The release, measured

`python3 scripts/complete_design.py --release --out <dir>` ran all 14 families
green. The newest run (the one that also carries the Scope B verdicts) was
checked before the scratch directory was cleaned up; the numbers are the table
below. Every family that carries the `COMPOSED_FAMILY` scope reads
`final_implementation: true` with `open_rows == []`:

| family | scope | flag | open rows | lint warnings |
|---|---|---|---|---|
| mesh, torus, ring, concentrated_mesh, qtree, tree4, flatfly, fattree, dragonflynew | COMPOSED_FAMILY | true | `[]` | 0 |
| fly | COMPOSED_FAMILY | true | `[]` | 0 |
| gec_mecs | COMPOSED_FAMILY | true | `[]` | 0 |
| kncube | COMPOSED_FAMILY | true | `[]` | 0 |
| gec_hybrid | COMPOSED_GEC_HYBRID | false | 4 of 9 criteria open (own scope) | 0 |
| srota | COMPOSED_SROTA | false | 5 of 9 criteria open (own scope) | 0 |

The twelve evidence bundles under `docs/product/evidence/final-implementation/`
all carry every required row closed and are keyed to their design's hash
(a bundle measured on another design is ignored, which is why a stale bundle
cannot carry the flag).

`gec_hybrid` and `srota` carry their own scopes and their own claim lists.
Their fabric lint is clean (0 warnings) and their simulation is green, and
their manifests now carry a per-criterion verdict — 9 rows each, the
established criteria CLOSED and the rest OPEN — so the false is auditable
row by row instead of a bare flag.

## Open

- **Scope B (GEC-hybrid, SROTA)** keeps its own claim lists. Their lint and
  simulation are green and their manifests now carry a per-criterion verdict
  (`final_implementation_verdict`), so the remaining gap is named row by row:
  multi-flit framing and the VC/credit pipeline, multicast semantics, the
  physical multidrop, and AXI/OrderingFSM/CDC composition for those flit-level
  tops. Closing those is feature work, not evidence work — promoting either
  family to `COMPOSED_FAMILY` means composing the full project top (slices,
  adapters, the ordering FSM and the CDC) around the shared-wire transport and
  then proving its channel dependency graph and its BookSim parity, which the
  A rows require and the flit-level tops do not model.

- **The evidence bundles for `kncube` and `gec_mecs`** are now written by the
  positive test, and the release after them reads them (12/12 in
  `/home/datavex/veritx-tmp/release-final3`).
- **Operational rule, worth keeping:** the release manifests must be
  regenerated *after* the bundles are complete, because the manifest verdict
  merges the bundle measured on that design. A release run whose bundles
  predate the evidence rows will show those rows open even though the RTL is
  clean.
- **The lint command keeps its pre-existing `-Wno-WIDTH -Wno-PINNOTFOUND
  -Wno-UNOPTFLAT`.** Under a plain `-Wall` the families are clean except for
  ~45 width findings in the router (`int` against narrow signals). Those are
  real, but they are a separate change with simulation risk, and the lint
  command is part of the product's established contract.


## Commands

```bash
cd tracks/t3-topology/dse
TMPDIR=/home/datavex/veritx-tmp PYTHONPATH=. python3 -m pytest \
  tests/test_final_implementation_evidence_positive.py -q
cd ../..
TMPDIR=/home/datavex/veritx-tmp python3 scripts/complete_design.py --release \
  --out /home/datavex/veritx-tmp/release-final
```

Heavy work runs sequentially; scratch stays under `/home/datavex/veritx-tmp`.
`docs/product/evidence/` is never deleted.
