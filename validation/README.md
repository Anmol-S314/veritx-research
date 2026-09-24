# VERITX Independent Validation Corpus

A permanent corpus of experiments whose answers come from **outside**
VERITX. Its purpose is to answer one question that internal unit tests
cannot: *is VERITX lying to itself?*

The corpus is deliberately hostile to the product. An experiment passes
only when a second authority — hand arithmetic, an independently
authored BookSim configuration, RTL, ASTRA-Sim, Ramulator, or measured
hardware — agrees with the canonical path within a **declared** bound.

## Permanent rule

> Any future major VERITX feature must add at least one experiment to
> this corpus. A feature that only adds internal tests is not validated.

This prevents the product from becoming internally consistent but
externally fictional.

## Layers (ordered by evidentiary weight)

| layer | what it is | authority class | independence |
|---|---|---|---|
| L1 exact micro-model | tiny systems with a hand-computed answer | `hand_calculated` | independent |
| L2 conservation | packets/flits in == out, loaded == declared | `conservation` | independent |
| L3 differential | same experiment through a second execution authority | `standalone_booksim`, `canonical_altrouting`, `rtl`, `astra`, `ramulator` | semi-independent → independent |
| L4 curve shape | sweeps whose *direction* is known (monotonicity) | `monotonicity` | independent |
| L5 metamorphic / adversarial | transforms with a known invariant; deliberately corrupted runs that must fail | `metamorphic`, `mutation` | independent |

**Independence is recorded, never assumed.** Two rulers that share an
engine (VERITX supervising the same vendored BookSim binary that
standalone uses) are `semi_independent`: they can catch a projector that
silently changes physics, but not a defect inside BookSim itself. Only a
different engine (`rtl`, `astra`, `ramulator`, `hardware`) or arithmetic
(`hand_calculated`) is `independent`.

## Result format

An experiment does not report `PASS`. It reports per-check evidence:

```text
Experiment V02 — 4x4 mesh, 16-node ALLREDUCE
check                     authority             value            verdict
packet conservation       conservation          960 == 960       exact
flit conservation         conservation          4800 == 4800     exact
completion parity         standalone_booksim    990 == 990       exact
route hop parity          hand_calculated       3.667 == 3.667   exact
window invariance         standalone_booksim    990 == 990       exact
```

A disagreement is not deleted; it becomes a finding in `FINDINGS.md`
with a reason and a bound.

## Running

```bash
# one experiment
PYTHONPATH=tracks/t3-topology/dse python3 -m validation.harness.run \
    validation/experiments/V02-allreduce-4x4.json

# the whole corpus
PYTHONPATH=tracks/t3-topology/dse python3 -m validation.harness.run --all

# as tests (CI gate)
PYTHONPATH=tracks/t3-topology/dse:tracks/t3-topology/dse/tests \
    python3 -m pytest validation/tests -q
```

The BookSim binary is discovered via `veritx_dse.core.paths.BOOKSIM_BIN`
or `VERITX_BOOKSIM_BIN`. A missing binary fails the corpus; it never
silently skips a differential check.

## Layout

```text
validation/
  README.md              this contract
  FINDINGS.md            durable defect/disagreement ledger (F-0001, ...)
  schema/experiment.schema.json
  harness/               spec -> fabric -> run -> compare
  experiments/           V01.. declarative experiment definitions
  reports/               generated results (JSON + markdown)
  tests/                 pytest wrapper (CI gate)
```

## The authority must not use the code under test

`harness/authority.py` contains its **own** BookSim output parser and
its **own** configuration author. It never imports
`veritx_dse.backend.booksim_execution` or
`veritx_dse.backend.booksim_projection`. If the authority reused the
parser, a parser bug (exactly like F-0001) would agree with itself.
