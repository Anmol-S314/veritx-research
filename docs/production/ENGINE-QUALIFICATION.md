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
| ASTRA-Sim | runtime / integration | shares the BookSim network engine | **EXECUTES; NUMERICAL VALIDITY NOT_ESTABLISHED** | `astra_runtime` gate |

## ASTRA is the open domain

The engine gate reports:

```text
ASTRA_RUNTIME_EXECUTES=PASS
ASTRA_NUMERICAL_VALIDITY=NOT_ESTABLISHED
  (aggregate 30010310c, exposed_comm 30000310c are unexplained and
   must not enter a scientific comparison)
```

The ~30M-cycle dominant component is unexplained, so ASTRA timing is
excluded from scientific comparison and from certified objectives. C6
owes per-domain qualification (`ASTRA_P2P_SIMPLE`, `ASTRA_RING_COLLECTIVE`,
`ASTRA_COMPUTE_COMM`, `ASTRA_MULTI_ROUND`, `ASTRA_MULTI_INSTANCE`,
`ASTRA_MOE`), each `QUALIFIED` / `PARTIAL` / `NOT_ESTABLISHED`. There is no
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
