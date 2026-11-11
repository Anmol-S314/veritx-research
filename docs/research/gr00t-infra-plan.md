# GR00T dataset-to-simulator infrastructure plan

Goal: reproducible source/CLI infrastructure from the pinned G1 dataset sample to simulator inputs and real tool execution, with optional Timeloop. Do not change desktop bundles or claim a complete GR00T execution trace before implementing model extraction.

1. [x] Inspect dataset ingestion, existing BookSim runners, and Timeloop build/run contracts in parallel (GPT-6 Luna, read-only). Three source-backed reports returned.
2. [x] Implement source-only CLI, optional export requirements, docs and tests. Initial worker delivery was incomplete; parent repaired it after review. Pinned fetch/export pass, BookSim executes real packets, optional Timeloop executes a tiny GEMM. Worker violated no-commit instruction with e86f515b; disclosed, history preserved.
3. [x] Two independent GPT-6 Luna reviews completed; parent repaired missing action stream/execution plus fetch/hash/overwrite errors, with regression tests. Retained reviewer challenged native trace selection; source inspection and real integration test resolved it. Final run 40229df1-558f-4b0d-b353-775c175a30f1 reports no findings, verdict OK.
4. [x] Parent validation: 132 tests pass; sample regeneration byte-identical; BookSim 33 packets/511 flits, exit 0; Timeloop sandbox builds and 16^3 GEMM reports 4096 computes/cycles, exit 0. See gr00t-infra-results.md and runs/gr00t-infra/2026-11-05-smoke/.

Scope: first bounded infrastructure slice. The existing episode ledger is sensor/trajectory evidence, NOT internal model traffic. A packet trace derived only from it must be labeled sensor/trajectory projection. Timeloop smoke GEMM must be labeled an infrastructure test, NOT a reconstructed GR00T model. Real architecture/model extraction is a subsequent stage.

Plan critique: avoid a custom orchestrator/framework, no giant dataset/checkpoint download, no app/catalog edits, no duplicate BookSim runner if an existing seam fits. Keep tools optional and research dependencies out of desktop runtime. Dirty source means no managed Git worktrees; serialize implementation in the checkout and keep reviewers/scouts read-only. User explicitly authorized GPT-6 Luna delegation.
