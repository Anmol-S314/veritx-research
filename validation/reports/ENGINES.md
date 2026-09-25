# VERITX Engine Gate Report

Independent engines: availability and self-consistency.

| engine | result | numerical validity | detail |
|---|---|---|---|
| ramulator_battery | PASS | established | 2.2s, 16/16 checks; 16/16 checks |
| rtl_selfcheck | PASS | established | GATE R0: ALL CHECKS PASSED |
| astra_runtime | PASS | **NOT_ESTABLISHED** | ASTRA_RUNTIME_EXECUTES=PASS; ASTRA_NUMERICAL_VALIDITY=NOT_ESTABLISHED (aggregate 30010310c, exposed_comm 30000310c are unexplained and must not enter a scientific comparison) |

---

engines passing: 3/3
unvalidated numerical output: ['astra_runtime']
