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
