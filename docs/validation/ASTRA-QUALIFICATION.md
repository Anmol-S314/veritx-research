# ASTRA Qualification (C6)

Status: **NOT ESTABLISHED** for absolute timing. ASTRA **executes**
correctly; its numerical validity is not proven. This file is deliberately
not a PASS.

## Engine-gate result

```text
astra_runtime: ASTRA_RUNTIME_EXECUTES=PASS
               ASTRA_NUMERICAL_VALIDITY=NOT_ESTABLISHED
               (aggregate 30010310c, exposed_comm 30000310c unexplained)
```

The ~30M-cycle aggregate/exposed-comm component dominates the run and is
not explained by the workload model. Until it is, ASTRA timing must not
enter a scientific comparison or a certified objective.

## Qualification domains (each independently graded)

| domain | status | evidence |
|--------|--------|----------|
| `ASTRA_P2P_SIMPLE` | NOT_ESTABLISHED | owed: independent hand-derived timing |
| `ASTRA_RING_COLLECTIVE` | NOT_ESTABLISHED | owed |
| `ASTRA_COMPUTE_COMM` | NOT_ESTABLISHED | owed |
| `ASTRA_MULTI_ROUND` | NOT_ESTABLISHED | owed |
| `ASTRA_MULTI_INSTANCE` | NOT_ESTABLISHED | owed |
| `ASTRA_MOE` | NOT_ESTABLISHED | owed |

There is no global ASTRA PASS. Integration/liveness (that a round executes
and advances) is separate from numerical validity and is exercised by the
serving loop.

## What is required to change a grade

For each microcase, derive expected timing **independently** of the ASTRA
parser, accounting for compute, communication, endpoint delay, collective
scheduling, BookSim network delay, synchronization, trace timestamps and
unit conversions. If ASTRA disagrees, open a finding (F-ASTRA-0001 shape:
reproduction, expected, observed, root cause, affected claims) before
tuning any parameter.

## Current consequence

- ASTRA results are labelled `NOT_ESTABLISHED` wherever surfaced.
- No certified metric may be sourced from ASTRA timing.
- The two-binary ASTRA reference differential is gated on
  `VERITX_ASTRA_REF_BIN`; under the release gate its absence fails the
  session rather than skipping (`tests/conftest.py`).
