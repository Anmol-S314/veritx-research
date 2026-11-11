# Compiled GEC preview check

Elaborates `CompiledGecPreview.scala` against a contract exported by
`veritx_dse.product.chipyard_gec.export_contract`, then builds and runs the
self-checking Verilator testbench from `make_testbench.py`.

Run from the repository root:

```text
bash scripts/check_chipyard_gec_preview.sh
```

The default contract is a 6×6 multidrop GEC (36 routers, 5 VCs, 72 shared
wires) seating the existing 32 declared agents. Override the output directory
with the first argument.

## What passing proves

- Every one of the 32×32 ordered endpoint pairs is injected, routed and
  delivered with the contract's destination and final VC.
- Four rounds of 32 sources contending for one egress complete under a stalled
  sink, and the stalled output stays stable.
- `accepted == delivered` and the network fully drains.

## What it does not prove

`CompiledGecPreview` is a topology preview: single-flit unicast, per-router
per-VC queues, round-robin arbitration and ready/valid flow control. It is not
the credit/iSLIP router, has no endpoint protocol adapters, ordering, CDC or
shared-wire electrical model, and is not synthesized or placed. It is not a
native fourteen-family qualification.

Toolchain: sbt 1.10.7, JDK 17, Scala 2.13.10, Chisel 3.6.1, Verilator 5.x
(`--binary --timing`). The 3 GiB / one-CPU cap applies to sbt only.
