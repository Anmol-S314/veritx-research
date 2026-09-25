# ASTRA Qualification (C6 / R2)

Status: **internally qualified under a declared model**, not a hardware
calibration. ASTRA executes correctly and its timing follows an exact,
closed-form accounting law on the release binary; it is **not** a physical
bandwidth/latency model and no certified metric may be sourced from ASTRA
absolute timing. Authority is source + tests + runtime output.

The required numerical evidence is now an **independent** oracle, not the
two-binary differential: `tracks/t3-topology/dse/tests/test_astra_timing_oracle.py`.
The two-binary differential (`VERITX_ASTRA_REF_BIN`) is a shared-engine
cross-check and is no longer release-critical.

## Model M — quantized-stepping ring accounting

The embedded BookSim frontend advances the shared fabric in fixed
1,000-cycle chunks (`third_party/astra-sim/extern/network_backend/booksim2/
Booksim2Fabric.hh`: `constexpr int64_t CHUNK = 1000`) and returns as soon as
a packet retires, so a ring step needing fewer than 1,000 fabric cycles is
billed a full chunk. Each collective event also pays the declared
`endpoint-delay` (10). Hence, for a ring ALLREDUCE over N ranks and a payload
that fits one chunk per step:

```text
steps(N)       = 2 * (N - 1)                 # closed-form ring law
comm_cycles(N) = (1000 + 10) * steps(N) + 10
               = 1010 * 2 * (N - 1) + 10
compute_cycles = declared durations (ns == cycles, ns_per_cycle = 1.0)
```

Falsifiable checks (all exact on the release binary):

| case | expected | observed |
|------|----------|----------|
| A0 compute-only, 1,000 ns | 1,000 | 1,000 |
| A0 compute-only, 7,000 ns | 7,000 | 7,000 |
| A0 compute-only, 10,000 ns | 10,000 | 10,000 |
| A0 compute-only, 1,234,000 ns | 1,234,000 | 1,234,000 |
| A2 ring, N=2, comm | 2,030 | 2,030 |
| A2 ring, N=4, comm | 6,070 | 6,070 |
| A2 ring, N=8, comm (held out) | 14,150 | 14,150 |
| A2 ring, N=16, comm | 30,310 | 30,310 |
| A5 2 rounds, N=16, comm | 60,620 | 60,620 |
| A5 3 rounds, N=16, comm | 90,930 | 90,930 |

## Timing decomposition (canonical microcase: N=16, 10,000 ns compute, 1 ring ALLREDUCE)

| component | expected | observed |
|-----------|----------|----------|
| compute (declared) | 10,000 | 10,000 |
| ring steps (2(N-1) = 30) x 1,000-cycle chunk | 30,000 | 30,000 |
| endpoint delay (30 steps + 1 closing) x 10 | 310 | 310 |
| **aggregate** | **40,310** | **40,310** |
| residual | 0 | 0 |

No unexplained residual. The 30310 comm component matches the historically
qualified tiny-fixture value (`F-ASTRA-0001`).

## Domain grades

| domain | status | evidence |
|--------|--------|----------|
| `ASTRA_COMPUTE` (A0) | QUALIFIED | exact for 4 durations; `test_real_compute_only_is_exactly_the_declared_compute` |
| `ASTRA_RING_COLLECTIVE` (A2/A3) | QUALIFIED under model M | exact for N=2,4,8,16 incl. a held-out N=8; `test_real_ring_collective_matches_the_closed_form` |
| `ASTRA_COMPUTE_COMM` (A4) | QUALIFIED under model M | compute exact + comm law exact; same tests |
| `ASTRA_MULTI_ROUND` (A5) | QUALIFIED under model M | additive over 1-3 sequential collectives; `test_real_multi_round_collectives_are_additive` |
| `ASTRA_P2P_SIMPLE` (A1) | NOT_ESTABLISHED | no send/recv microcase exercised (the embedded frontend's send/recv path is untested here) |
| `ASTRA_MULTI_INSTANCE` (A6) | NOT_ESTABLISHED | the frontend instantiates the whole fabric; independent instance groups not established |
| `ASTRA_MOE` (A7) | NOT_ESTABLISHED | no expert/EP collective lowered to ASTRA in this qualification |
| `ASTRA_ABSOLUTE_LATENCY` | NOT_ESTABLISHED | F-ASTRA-0002: comm is payload-insensitive below ~64 KiB, so absolute timing is an accounting model, not a physical one |

There is no global ASTRA PASS. Integration/liveness (that a round executes
and advances) is separate from numerical validity and is exercised by the
serving loop.

## Finding F-ASTRA-0002 (open limitation)

Comm cycles are quantized to the 1,000-cycle chunk and flat across payloads
from 64 B to 64 KiB (64 B and 64 KiB both cost 30,310 cycles at N=16).
Recorded in `validation/FINDINGS.md`; the regression guard is
`test_real_small_payload_comm_is_quantized_not_bandwidth_limited`.

## What is required to change a NOT_ESTABLISHED grade

For each remaining domain, derive expected timing independently of the ASTRA
parser (compute, communication, endpoint delay, collective scheduling,
BookSim network delay, synchronization, unit conversions) and, for any case
requiring tolerance, pre-register the metric, expected value, tolerance and
reason before looking at final output. Do not widen a tolerance after a
failure.

## Current consequence

- ASTRA results are labelled with model M wherever surfaced and
  `NOT_ESTABLISHED` for absolute latency.
- No certified metric may be sourced from ASTRA absolute timing.
- Integration/qualification code uses the repository release binary
  (`astra.resolve_runtime_binary()`); developer-local archived binaries are
  not a candidate.
