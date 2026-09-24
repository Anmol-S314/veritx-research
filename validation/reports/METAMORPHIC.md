# VERITX Metamorphic Report

Transforms with a known invariant; the physics must not move.

| transform | invariant | result | detail |
|---|---|---|---|
| M1_request_key_reorder | identity and physics unchanged under JSON key reordering | PASS | prepared_id and physics identical |
| M2_requirement_threshold | non-physical field does not move physics | PASS | physics identical |
| M3_output_format | non-physical field does not move physics | PASS | physics identical |
| M4_model_rename | non-physical field does not move physics | PASS | physics identical |
| M5_duplicate_requirement | non-physical field does not move physics | PASS | physics identical |
| M6_seed_is_prepared_identity | seed is part of prepared identity; different seed changes it | PASS | same seed stable; different seed changes config, prepared_id and evidence_id |
| M7_repeat_run | two runs of one input share evidence identity | PASS | evidence_id and stats identical |
| M8_run_dir_independence | moving the run directory does not move scientific identity | PASS | evidence_id identical |

---

invariants held: 8/8
