# VERITX Mutation Report

Deliberate corruptions the canonical path must refuse.

| mutation | expected refusal | result | detail |
|---|---|---|---|
| M1_window_only_completion | `BookSimExecutionError: Completion time` | CAUGHT | refused: missing required completion evidence 'Completion time is N cycles' (the last-ejected-flit cycle; F-0001) — refusing to t |
| M2_completion_after_window | `BookSimExecutionError: exceeds the run window` | CAUGHT | refused: completion evidence 99 exceeds the run window 10 — inconsistent timing evidence |
| M3_trace_tamper_after_prepare | `BookSimExecutionError: modified after preparation` | CAUGHT | refused: prepared input does not match the externally held prepared_id (sha256:f3eed7787d070a5e220003e6c175e2b4f5e0120d9efbffc1aa |
| M4_config_tamper_in_run_dir | `BookSimExecutionError: different bytes` | CAUGHT | refused: /tmp/validation-work-5deivwsu/m4/config.cfg already holds different bytes; refusing to overwrite a prepared input |
| M5_binary_swap_after_identification | `ProducerError: changed between identification` | CAUGHT | refused: BookSim binary changed between identification and execution (936aeefdfab9dfac4aa9a28e84987cec47ea5431145bcfdd4b7f291bbec |
| M6_evidence_byte_flip | `BackendEvidenceError: modified after execution` | CAUGHT | refused: evidence file /tmp/validation-work-5deivwsu/m-real/backend-evidence.json digest 685e3cfe288ddfcadb70f783456878e0071121ca |
| M7_wrong_producer_sha | `BackendEvidenceError: different BookSim binary` | CAUGHT | refused: evidence was produced by a different BookSim binary; refusing reuse |
| M8_evidence_transplant | `BackendEvidenceError: prepared_id` | CAUGHT | refused: evidence prepared_id does not match the prepared input |

---

mutations caught: 8/8
