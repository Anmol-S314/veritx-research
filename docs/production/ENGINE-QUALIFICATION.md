# VERITX Engine Qualification (C7 / C10)

Five backends appear in the product. They are **not** five independent
engines. Independence is a property of the evidence, and this file classes
each backend by what its numbers can legitimately support.

| backend | role | independence | numerical validity | evidence |
|---------|------|--------------|--------------------|----------|
| Embedded BookSim (fork) | canonical network execution engine | the engine under test | qualified (F-0001 fixed; conservation enforced) | `backend/booksim_execution.py`, `test_backend_booksim_execution.py`, real mesh/anynet gates |
| Standalone BookSim (harness authority) | shared-engine differential | semi-independent (same simulator, separate build/config) | qualified at the differential level | `validation/harness/authority.py`, `standalone_parity` checks |
| RTL / Verilator | independent execution engine | independent within the RTL domain | established (R0 self-check) | `rtl_selfcheck` engine gate |
| Ramulator | memory engine / integration | independent | established (16/16) | `ramulator_battery` engine gate |
| ASTRA-Sim | runtime / integration | shares the BookSim network engine | **EXECUTES; internally qualified under model M; ABSOLUTE LATENCY NOT_ESTABLISHED** | `astra_runtime` gate, `test_astra_timing_oracle.py` |

## ASTRA is the bounded domain

The engine gate reports:

```text
ASTRA_RUNTIME_EXECUTES=PASS; ASTRA_RING_COLLECTIVE=QUALIFIED_UNDER_MODEL_M
  (comm 30310c == closed form (1000+10)*2*(N-1)+10 for N=16);
ASTRA_ABSOLUTE_LATENCY=NOT_ESTABLISHED (F-ASTRA-0002)
```

2026-09-25 (F-ASTRA-0001): the ~30M-cycle component was a `run_cycles`
quantization regression in the embedded BookSim2 frontend (every collective
step billed one 1M-cycle chunk). Fixed; the gate now reads
`aggregate 40310c, exposed_comm 30310c`.

R2 then added an **independent** closed-form oracle (model M) on the release
binary: compute-only cycles equal the declared nanoseconds (exact for four
durations); a ring ALLREDUCE of N ranks costs `1010 * 2(N-1) + 10` cycles
(exact for N=2/4/8/16, N=8 held out) and multi-round collects additively.
Domains: `ASTRA_COMPUTE`, `ASTRA_RING_COLLECTIVE`, `ASTRA_COMPUTE_COMM` and
`ASTRA_MULTI_ROUND` are QUALIFIED under model M; `ASTRA_P2P_SIMPLE`,
`ASTRA_MULTI_INSTANCE` and `ASTRA_MOE` are NOT_ESTABLISHED.

Finding F-ASTRA-0002 bounds the claim: comm cycles are quantized to the
1,000-cycle frontend chunk and payload-insensitive below ~64 KiB (64 B and
64 KiB both cost 30,310 cycles at N=16). ASTRA absolute timing is therefore
an internal accounting model, not a physical bandwidth/latency model, and
must not enter a scientific comparison or a certified objective. There is no
global ASTRA PASS.

## What "qualified" means per axis

- **Conservation:** a certified BookSim execution must prove
  `loaded == injected == delivered == declared` packets and
  `flits_injected == flits_accepted == declared` flits. Missing counter =
  failure. (`test_booksim_conservation.py`.)
- **Route realization:** the executed first-hop table equals the canonical
  route for every (src router, destination) pair; missing/divergent dump
  refuses. First hop only (the fork dumps one hop).
- **Producer:** the executed binary is pinned by build manifest (source
  revision, dirty=false, sha256, size, compiler, recipe) and the evidence
  binds that manifest + recipe. Unpinned producers cannot certify.

## Unowned / not claimed

- No engine claims end-to-end application runtime from a network
  completion time (F-0003: completion is injection-schedule-bound).
- No engine is treated as a second independent oracle merely because it
  produces a number; the oracle class is stated in each validation check.
