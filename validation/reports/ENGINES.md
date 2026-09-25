# VERITX Engine Gate Report

Independent engines: availability and self-consistency.

| engine | result | numerical validity | detail |
|---|---|---|---|
| ramulator_battery | PASS | established | 2.0s, 16/16 checks; 16/16 checks |
| rtl_selfcheck | PASS | established | GATE R0: ALL CHECKS PASSED |
| astra_runtime | PASS | **NOT_ESTABLISHED** | ASTRA_RUNTIME_EXECUTES=PASS; ASTRA_NUMERICAL_VALIDITY=NOT_ESTABLISHED (aggregate 40310c = declared compute 10000c + comm 30310c; the dominant over-count was fixed by F-ASTRA-0001, but absolute timing remains unqualified pending independent per-domain oracles and must not enter a scientific comparison) |

---

engines passing: 3/3
unvalidated numerical output: ['astra_runtime']
