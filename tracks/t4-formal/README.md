# T4 — Formal Verification with SymbiYosys + Yosys + CBMC

> **2026-08-05 — v2 role: formal-verification service arm.** The deliverable is a
> property-writing playbook plus the simulation-vs-formal coverage study (the
> strongest result this track has). This sells as a *service* (property writing,
> proof strategy, coverage studies) — never as an ASIL-B certification claim, which
> requires a real certification body on real RTL (see
> [docs/business/programme-v2.md](../../docs/business/programme-v2.md)).

Formally verify RTL designs (SystemVerilog) for AI accelerator NoC components: counters, FIFOs, arbiters, routers.

## What You Edit

| File | What it does | Your research |
|------|-------------|---------------|
| `rtl/counter.sv` | Simple counter | Write your own RTL modules |
| `rtl/fifo.sv` | Synchronous FIFO | Add properties (assertions) |
| `rtl/arbiter.sv` | Round-robin arbiter | Prove correctness with induction |
| `configs/*.sby` | SymbiYosys proof configs | Add BMC depths, induction, covers |

## Core Workflow

```
rtl/*.sv  ──→  sby -f configs/*.sby  ──→  pass/fail + VCD traces (on fail)
```

SymbiYosys runs BMC and inductive proofs. If a proof fails, a VCD waveform is captured automatically.

## CI Pipeline

```
make setup   → verify Yosys + SymbiYosys + CBMC + z3
make lint    → syntax-check SV files
make test    → sanity proof (counter BMC10)
make sim     → full suite: counter/fifo/arbiter × BMC10/BMC20/prove
```

## Expected Output

```
  counter BMC10    → PASS
  counter BMC20    → PASS
  counter prove    → PASS
  fifo    BMC10    → PASS
  fifo    BMC20    → PASS
  fifo    prove    → PASS
  arbiter BMC10    → PASS
  arbiter BMC20    → PASS
  arbiter prove    → PASS
```

All green = the properties hold for all states (induction) and for the first 10/20 clock cycles (BMC).

> **Contract caveat (F5/30bd, 2026-08-16):** the formal properties are *logical*
> properties, not a cycle model — proof of a property does not certify
> cycle-accurate latency or power (same caveat as the 3D/4D stacks in
> RTL-ARC §10). Snapshot RTL (`configs/router_g1/src/`) must be re-proven
> whenever the source router changes (a893).

## When Proofs Fail

If `sby` finds a counterexample, it writes a `.vcd` trace to `results/`. Load it with:

```bash
gtkwave results/<module>_<mode>_trace.vcd
```

(Install gtkwave locally — not in the CI container.)

## Research Path

1. **Weeks 1-3**: Understand formal property writing, run existing proofs, add covers
2. **Weeks 4-8**: Write your own RTL modules (router allocator, VC buffer manager, crossbar) with properties
3. **Weeks 9-16**: Prove correctness of novel NoC component designs, compare proof complexity across solvers

## Reference

- [SymbiYosys](https://github.com/YosysHQ/sby)
- [Yosys](https://github.com/YosysHQ/yosys)
- [CBMC](https://github.com/diffblue/cbmc)

## Scope caveat (2026-08-15, seed a893)

`rtl/router_g1_formal.sv` is an intentional **reduced model** (59 lines vs the
591-line `noc_router`) for BMC depth-10. It abstracts away the 2-die bridge
parameters (DIE_BASE/BRIDGE_COL/BRIDGE_ROW), multicast (mcast/copy_lo/hi), and
the eject-FIFO. Formal proofs therefore cover only the simplified router's
properties — they do NOT cover the 2-die / mcast / eject features of the
shipped RTL. Those features are covered by the RTL↔BookSim co-sim gate
(rtl_r1.py) instead. Re-targeting the formal model to `noc_router` for 2-die
properties is out of scope (would need BMC depth >> 10 for the full state
space).
