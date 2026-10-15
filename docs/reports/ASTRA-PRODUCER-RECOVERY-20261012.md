# ASTRA producer recovery — 2026-10-12

## Live result

Project `p-b2ed4e030a8a`, revision `p-b2ed4e030a8a-r08`, now has a completed live evaluation:

- Job: `job-daf5ffd72b66` (`COMPLETED`).
- Run: `01a12f5e-3fbc-7970-8c8d-e4d29513438d` (`EVALUATED`, freshness `CURRENT`).
- Questions: `SYSTEM_MAKESPAN`, `COMMUNICATION_EXPOSURE`, `PER_RANK_COMPLETION`; all `EVALUATED`.
- Makespan: 223,237 simulator cycles; exposed communication: 160,979 simulator cycles.
- The canonical project draft was not changed by this recovery.

These are projected-machine simulation results, not calibrated wall-clock latency, hardware equivalence, or physical signoff.

## Producer

The previously installed executable had been replaced without its manifest being updated. Rebuilding edited source then produced a correctly marked dirty manifest, which cannot pass the production spawn gate. Relabelling that build as clean would not fix provenance.

A separate clean detached worktree at the previous v1 producer revision `3d47fbb86a4d297e61d4f7a35126dfd9c2a0f0ff` was built and tested, then its executable and verified build-time manifest were installed at the canonical ASTRA binary path. No source edits, staging, commits, resets, or stashes were made in the main checkout.

- Recipe: `astra-sim+booksim2/v1`.
- Source dirty: `false` in the isolated build; the main checkout remains dirty.
- Binary SHA-256: `1365ffdbe2f821783130e9cbf57926a3696b907c085bc0a22fe5482840cb29f5`.
- Manifest SHA-256: `b04901346ceccdf50fe987561d59f815712858d144acba6185cdb2d8bc3df72c`.
- Compiler: g++ 15.2.0; Release configuration.
- `resolve_astra_identity()` and `assert_pinned_producer()` both pass for the installed producer.

The edited developer executable and its dirty manifest were retained in `/home/datavex/.cache/veritx-astra-recovery-20261012/developer-binary/`. The edited `Workload.cc` source remains untouched.

An independent clean HEAD build was also tried. It failed live execution: the HEAD BookSim `EmbedTM` requires a host flit limit before injection, but the ASTRA wrapper does not set it. Thus this recovery restores the older working v1 producer; it does **not** qualify the HEAD producer or close W6/native multicast acceptance. Rebuilding HEAD into the canonical path would reintroduce this separate integration failure.

## Exact compute timing

The project contains a 61,200-ns compute stage. Truncating it to 61 microseconds would change the workload.

The production Chakra writer now defaults to a v1-compatible exact encoding: whole-microsecond compute plus a dependent chain of at most 999 one-nanosecond compute nodes. The unmodified v1 runtime assigns one nanosecond to a compute node with `duration_micros=0`. Zero-duration authored compute adds no node. Auxiliary IDs are outside the logical node-ID range; subsequent communication waits for the complete remainder chain. Declared compute floors sum exact nanoseconds rather than passing through `compute_micros()`.

Real native tests cover 1, 999, 1000, 1001, and 61,200 ns, both with and without the optional exact-ns attributes. Decoded ET tests cover zero duration, dependency ordering, unique IDs, and conservation of represented compute time. The single-node exact-ns format remains an explicit diagnostic option for the edited runtime, not the default production format.

## Verification and operation

- Focused ASTRA, machine/namespace, gateway/product federation, and build-manifest regression selection: **316 passed, 4 skipped**.
- The actual project was evaluated through the Python federation path before gateway deployment and through the live HTTP gateway after deployment; both returned the same reported makespan and exposure.
- The gateway was gracefully restarted only after checking that no compile/evaluation/optimization/AI-search jobs were active. Its command, environment, port, and project storage were preserved.
- All three live ASTRA evaluation-plan rows are now `READY`.

Disk evidence: `/home/datavex/.cache/veritx-astra-recovery-20261012/` contains clean build logs/worktrees, `regression.log`, before/after live plans, the actual-project scratch execution, and the persisted live job/run response copies.

To reproduce the producer build, use an isolated worktree at the source revision above, build BookSim first (generating flex/bison parser sources), run ASTRA's tracked `build/astra_booksim2/build.sh`, then write its adjacent manifest with `--repo-root` pointing to that isolated worktree, recipe v1, and source paths `third_party/astra-sim` plus `third_party/booksim2`. Verify the producer and perform a real execution before installing it. Never regenerate a clean-source manifest against an edited checkout.
