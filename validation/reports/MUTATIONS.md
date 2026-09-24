# VERITX Mutation Report

Deliberate corruptions the canonical path must refuse.

| mutation | expected refusal | result | detail |
|---|---|---|---|
| M1_window_only_completion | `BookSimExecutionError: Completion time` | CAUGHT | refused: missing required completion evidence 'Completion time is N cycles' (the last-ejected-flit cycle; F-0001) — refusing to t |
| M2_completion_after_window | `BookSimExecutionError: exceeds the run window` | CAUGHT | refused: completion evidence 99 exceeds the run window 10 — inconsistent timing evidence |
| M3_trace_tamper_after_prepare | `BookSimExecutionError: modified after preparation` | CAUGHT | refused: prepared input does not match the externally held prepared_id (sha256:12312cd1116a805474e5cd2fc6c1f64e85144144053aed4143 |
| M4_config_tamper_in_run_dir | `BookSimExecutionError: different bytes` | CAUGHT | refused: /home/datavex/veritx-scratch/validation-work-t2k0cd2i/m4/config.cfg already holds different bytes; refusing to overwrite |
| M5_binary_swap_after_identification | `ProducerError: changed between identification` | CAUGHT | refused: BookSim binary changed between identification and execution (6294b6bf519e162c71fccfb59e95dc58c91b3b132fd9dff69a754c146d4 |
| M6_evidence_byte_flip | `BackendEvidenceError: modified after execution` | CAUGHT | refused: evidence file /home/datavex/veritx-scratch/validation-work-t2k0cd2i/m-real/backend-evidence.json digest a8fd1268c3a4e784 |
| M7_wrong_producer_sha | `BackendEvidenceError: different BookSim binary` | CAUGHT | refused: evidence was produced by a different BookSim binary; refusing reuse |
| M8_evidence_transplant | `BackendEvidenceError: prepared_id` | CAUGHT | refused: evidence prepared_id does not match the prepared input |

---

mutations caught: 8/8
