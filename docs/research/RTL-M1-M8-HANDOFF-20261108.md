# RTL M1–M8: quota-safe handoff

**Next implementation session:** use [the deep twelve-family execution plan](RTL-12-OF-12-EXECUTION-PLAN.md). This handoff preserves historical findings; the new plan adds source-grounded corrections, especially strict progress versus hybrid’s proof-only hop budget, verified free-credit semantics, and reuse-first intake of the other coding agent’s newer generated artifacts.

Checkpoint: 2026-11-08, approximately 12:47 UTC. This is the parent orchestrator's durable checkpoint, not an all-milestone completion report.

## Start here

**The original goal is NOT complete. Zero of the original twelve families have been established in this session as passing every required gate.** Existing native/candidate graph proofs, generated Verilog and historical ring simulation are useful but do not establish a fresh complete qualification chain. This batch mostly produced component code/checkers; several independent review findings remain unresolved. No hardware/Scala/C++/Verilator command ran in this workflow's execution stage.

The user explicitly requested Luna orchestration across all open M1–M8 items. The user then warned that their five-hour quota was almost exhausted and requested all findings be saved. Do not restart broad reconnaissance or another model/checker-only fanout. Prioritize actual missing implementation and real execution.

### Locations

```text
LAB=/home/datavex/.cache/veritx-noc-lab/vla-native-execution/experiments/constellation_topology_rtl
ROOT=$LAB/milestone-closure-v2-20261108
```

- Original approved requirements: `$LAB/ALL_TOPOLOGIES_IMPLEMENTATION_PLAN.md`, especially §6 M1–M8 and §7 execution/evidence rules.
- Existing implementation/proofs/native contracts: `$LAB/full-connectivity-v1/`.
- Previous isolated verification effort: `$LAB/verification-isolated-v1/`, including its `CONTRACT.md`, packet checkpoint, source reproduction helpers, decoder/backend work, and SROTA factoring.
- This batch's ownership contract and runnable workflow: `$ROOT/CONTRACT.md`, `$ROOT/execute_luna.js`.
- Plan/decisions: `$ROOT/coordination/{PLAN.md,decisions.tsv}`.
- Actual private changes and each lane's detailed report: `$ROOT/m1/` through `$ROOT/m8/`; read `RESULT.md` in each.
- Parent-preserved reports: `$ROOT/handoff-evidence/`. The initial **41 reports** cover all eight inspections, implementations, fixes, both review rounds, serial-execution report, runtime audit, and lane RESULT snapshots. Terminal receipt, final integration, final report files and this handoff were added afterward. `manifest.json` plus `final-preservation-manifest.json` record SHA-256 values. These copied reports survive outside the session transcript.
- Final integrator wrote `$ROOT/reports/{MILESTONES.md,status.json,decisions.tsv}`; the parent confirmed all three exist after terminal completion. They preserve the incomplete status and remaining review findings. Copies are in `handoff-evidence/`.

### Runtime identity

- Workflow run: `9cac9f69-c32b-402a-b810-9f005f90737d`.
- Mission: `5c16f6a1-ea49-4924-84d0-54a675973b85`.
- Runtime directory: `/tmp/pi-subagents-uid-1000/async-subagent-runs/9cac9f69-c32b-402a-b810-9f005f90737d`.
- TERMINAL UPDATE: workflow completed with all 34 children complete. State is `bounded_work_complete_original_gates_still_apply`, NOT original-goal completion. Integrator child: `36f97f7e-5706-494c-8004-6f7b9101f516`. Durable terminal receipt and integrator response are copied to `handoff-evidence/workflow-receipt.json` and `integrate-milestones.md`. No active child needs to be kept alive.
- Runtime-bound child reports:
  `/home/datavex/.pi/agent/sessions/--home-datavex-bruh-veritx-research--/subagent-artifacts/outputs/9cac9f69-c32b-402a-b810-9f005f90737d/milestone-v2/`.
- All children used `openai-codex/gpt-6-luna:high`. Maximum six simultaneous agents. No external-agent/provider fallback was used.
- Do not relaunch `execute_luna.js` wholesale: it repeats completed work and has only a bounded fix/review cycle, not an until-goal-complete loop.

## Milestone findings and actual changes

### M1 — native contracts and controlled outcomes

Private implementation: `m1/controlled_outcomes.py`, `m1/tests/test_controlled_outcomes.py`, frozen `m1/inputs/`.

Adds selector/outcome auditing against frozen FlatFly native dump/config/source/probe evidence, including missing-branch/hash-drift negatives. Reports 1,920 selector rows for 960 source/destination router pairs, both selector values. **These rows are derived by correlating the deduplicated native outcome union to source branch semantics, not independent per-invocation native selector traces.** Do not equate this with all 4,096 endpoint pairs, live native reruns, emitted decoder equivalence, or complete M1.

Worker reported 3 focused Python tests passing. Final reviewer approved the bounded component, with the above limitation explicit. No new native or RTL execution occurred.

### M2 — three-bit route-tag transport

Private selective source copy: `m2/full-connectivity-v1/`. Existing three-bit patch applied privately to `Flit.scala`, `Types.scala`, `IngressUnit.scala`, `InputUnit.scala`. Tags 4–6 must not truncate to two bits. Shared external source remains outside this batch's write scope.

Initial Chisel test only tested a synthetic local Queue; reviewer correctly rejected that as production transport coverage. Fix added a production `InputBuffer` transport test under `src/src/test-m2/scala/constellation/RouteTagTransportSpec.scala`. Chisel test is **not compiled or executed**. Python tests pass as reported, but cannot establish Chisel correctness.

Remaining review note: copied `src/src/main/scala/CatalogRtlRouteTag.scala:6–36` still describes two-bit fields/unwired transport, contradicting widened private declarations. Correct these comments/history labels before treating the source set as coherent.

Prepared test interface:

```bash
# Requires COMPLETE private pinned Chipyard/source/build integration first.
# This is a test selector, not a validated standalone build environment:
sbt 'set Test / unmanagedSourceDirectories += baseDirectory.value / "src/test-m2/scala"' \
    'testOnly constellation.RouteTagTransportSpec'
```

Use the existing isolated JDK17/Chipyard runner, not an unpinned standalone sbt/toolchain reinvestigation.

### M3 — proof-to-emitted-decoder binding

Private code: `m3/decoder_binding.py`, reused `m3/rtl_binding.py`, tests and frozen ring/torus/GEC-MECS inputs. Added mask/link/port/terminal mapping checks and mutation tests. Follow-up added artifact hashes/identity/coverage checks. Worker reported 14 tests passing after fixes.

**Final reviewer still BLOCKS this gate:** `decoder_binding.py:51–52,119–120,142–143` accepts caller-declared `proof_status=certified` plus hash of arbitrary bytes as certification. The positive fixture accepts literal `b"proof"`. It does not parse/validate a recognized acyclic/progress certificate or bind certificate contents to the exact transition export.

Required fix: use a recognized proof schema/trusted existing verifier; independently validate success, source/export identity, exact transition digest, resource coverage and progress. Reject malformed/unrelated/transition-mutated certificates. Hash equality is not proof validity.

No complete real emitted-decoder map, physical binding or actual decoder execution passed the new gate. Existing structural binder remains `partial_unresolved`.

### M4 — actual family policy/datapath integration

SROTA dynamic D+T/FIU/telemetry remains incomplete. Existing SROTA allocation factoring preserves a base legal relation but does not implement those dynamic obligations; avoid duplicating its existing owners.

The parent reassigned M4 to **GEC-hybrid actual occupancy-selector integration**, authorizing coherent copies and modifications of the generic Constellation source tree inside `m4/`. Two supervisor replies explicitly allowed modifying PRIVATE copies of `InputUnit.scala`, `RouteComputer.scala`, parameter plumbing, selector and exporter. External writes were never authorized.

**The worker did not implement that integration even after clarification.** Current deliverable remains `m4/hybrid_selector.py`, five component tests, and an unchanged Chisel selector snapshot. Final review rejects it as model-only; the task is open implementation work, not a scope/authority blocker.

Actual integration target exists: `CatalogRtlHybridExport.CandidateNoCTop` instantiates `LazyModule(new NoC(params))`, whose generic Router uses InputUnit and RouteComputer. A separate family-specific Router class is unnecessary. `CatalogRtlHybridSelector` is defined but not instantiated. Needed seam:

1. Preserve physical link IDs and `(output, VC)` identity, including separate mesh/express parallel links.
2. Bind the certified legal mask and actual output occupancy to an opt-in hybrid selector in the real allocation path.
3. Match native `GetUsedCredit * remaining_hops`; mesh remaining distance, express H=1, ties choose MECS.
4. Hold committed route/head decisions under backpressure and maintain packet state.
5. Keep legacy profiles unchanged; force both parallel choices in actual production-path Chisel tests.

**Credit semantics require direct verification.** Do not trust the lane report's inference from variable names or the sentence about `credit_count := s.c`. Inspect OutputUnit update equations to determine whether each signal is free credits or used occupancy; derive native occupancy correctly. Egress count uses different queue semantics.

**Do not run the M4 RESULT's proposed command unchanged:** it targets external `full-connectivity-v1/src` and `/tmp/opencode/m5-rtl/gec_hybrid`, violates this workflow's private-output rule, and does not test any new selector wiring. Prepare a pinned PRIVATE build/output command after actual code exists.

### M5 — full-size inventory/lint/packets

No code assigned: reuse existing frozen packet fixes and run a genuine ring cell independently of unrelated incomplete milestones when the heavy slot is genuinely free.

Earlier historical progress reports a ring run of 16,385 accepted/delivered packets, 69,637 flits, exact drain, eject-only trace scope. It is historical evidence, not a fresh receipt for the current source/packet checkpoint. The corrected previous packet checkpoint reports 15 Python tests, with corrected RTL lint/build/simulation NOT_RUN.

Relevant frozen checkpoint:
`$LAB/verification-isolated-v1/reports/r6/sealed-packet-checkpoint/manifest.json`, reported SHA-256 `5816a5a5ad56bb51ab78d3e0098ef60ce7080e689a794862d5102e5935b887eb`.

Candidate command interface, to materialize in a coherently copied private execution workspace:

```bash
python3 tools/verilator/run_ring_verilator.py --out-dir runs/ring-verilator-m5-UNIQUE
```

This is a recipe, not a completed run or proof that every dependency is ready. Audit correct pinned executable/argv, assertion flags, top/helper/build/source hashes, raw exit/log, completion receipt, accepted vs attempted traffic, exact payload/flit/packet counters, stalled-beat checks, reset epochs and drain. Eject-only observations do not prove internal-hop/VC coverage.

### M6 — actual RTL replay and lineage

Private `m6/replay_provenance.py` now rejects duplicate capture content/paths, empty/failed build evidence and unsuccessful invocation fields; worker reported 10 unit tests passing after review fixes.

**Final reviewer still rejects acceptance:** `replay_provenance.py:102–139` trusts authored receipt JSON and arbitrary output bytes. It neither anchors input hashes to the approved accepted single/sequential captures nor validates actual RTL executable/build invocation, output replay schema, exact byte/packet lineage and causal sequencing. Unit fixtures fabricate the entire purported successful chain.

Required fix: consume approved capture manifests and actual runner-produced execution evidence; verify executable/build/top/helper identity and parse real outputs for exact byte/packet/causal checks. Keep this utility component-only until those facts exist. No actual Holoscan replay was performed or validated here.

### M7 — shared logical resources / Track B

Actual new RTL component now exists following parent correction:

- `m7/rtl/shared_channel_scheduler.sv`
- `m7/rtl/tb_shared_channel_scheduler.sv`
- `m7/shared_scheduler.py` (independent flit/packet model)
- `m7/tests/test_shared_scheduler.py` (reported 9 Python tests passing)

Generic scheduler has one accepted beat/cycle, round-robin eligible-tap selection, per-(tap,VC) credit gating/consume, head/tail, optional packet lock, and held grant/payload metadata under stalls. **SV has never been compiled or simulated.** Python tests do not establish RTL behavior.

Final reviewer notes the family profiles are only name/count records, not executable group/tap/resource bindings. Still needed: SROTA 224 groups/896 taps, GEC-MECS 32 groups/96 taps, hybrid those shared groups PLUS 48 distinct mesh P2P links; actual queues/locks/credit identities, shared-resource CDG/progress/fairness, reference-enabled sidebuffers and full-fabric replay. Sidebuffer is explicitly `not_modeled`, not qualified by disabling it.

Prepared COMPONENT test, only when heavy ownership permits (execute from a new private run dir rather than overwriting evidence):

```bash
iverilog -g2012 -s tb_shared_channel_scheduler -o /PRIVATE/FRESH-RUN/tb.vvp \
  m7/rtl/shared_channel_scheduler.sv m7/rtl/tb_shared_channel_scheduler.sv
vvp /PRIVATE/FRESH-RUN/tb.vvp
```

Use finite timeouts and the established resource isolation. A generic scheduler unit test can run as a deliberately bounded component check even while complete profile binding remains open; it cannot qualify all Track B families. The previous execution worker over-gated this component check on full profile completion; distinguish scoped test readiness from full milestone readiness.

### M8 — final pinned-snapshot reproducibility audit

Private `m8/fresh_reproducibility.py` compares fresh/current/sealed transition and inventory bytes and added run/source/tool/command field checks; worker reported 6 tests passing after fixes. It keeps 13 Track A rows and three Track B profiles separate.

**Final reviewer still rejects fresh-reproduction acceptance:** `fresh_reproducibility.py:107–125` accepts caller-authored receipt strings plus copied artifacts; fabricated receipt can bless a stale copy. A matching hash comparison is not evidence the exporter actually executed on the pinned snapshot.

Required fix: execution owner must actually run the pinned exporter into fresh private output and preserve command/tool/source/profile/run/output/log/exit evidence; verifier must bind that genuine run to files. Do not add a whole signing infrastructure merely to substitute for performing the actual execution. Until then label output byte-comparison/component evidence, not fresh reproduction or M8 PASS.

## Execution blocker and audit deficiencies

Serial execution child `f2ca3eb2-a961-4098-a88a-b0cb8671aaeb` ran a one-time process inspection and launched NO hardware/build/sim commands. At its snapshot (local 18:11:31, UTC approximately12:41:31), foreign heavy jobs were alive:

- SROTA per-router phaseA: wrapper PID289107, Java289108, parent289096.
- CMesh per-router phaseA: wrapper289983, Java289984, parent289972.
- Hybrid per-router phaseA: wrapper290276, Java290277, parent290265.
- Fat-tree per-router phaseA: wrapper289473, Java289474; reported parent2228 for wrapper.

These are historical snapshot PIDs, NOT proof of current activity. Original batch PID253958 was gone at that inspection; checking only that old PID is insufficient. Never mistake gaps between JVMs for whole-queue completion. Inspect the complete ownership/process tree at the next real execution barrier. No foreign process was signaled.

Original caps remain: systemd MemoryMax4G, MemorySwapMax512M, JVM-Xmx3g, one active processor/sbt task, native/Verilator -j1, finite1800s generation cap. Do not increase caps or weaken topology/config to get a pass.

The execution worker returned a runtime-bound report but did NOT create requested `execution/RESULT.md`/`result.json`; runtime auditor confirmed these absent. Auditor also could not independently verify reported unit logs/hashes from actual raw artifacts. Both actual reports are safely copied in `handoff-evidence/serial-execution.md` and `runtime-audit.md`. The execution worker's missing CURRENT-STATUS path is a path-resolution issue to investigate, not proof the external source/status vanished.

## Exact resume priorities

1. Read this file, original approved plan, and actual final integrator output if now present. Consume current workflow terminal result before launching more work. Preserve outstanding reviewer findings even if workflow says its bounded batch is complete.
2. Read copied final reviews `handoff-evidence/review-{0,1,2,3}-1.md`. Approval is only bounded M1/M2; M3/M4/M6/M7/M8 have open conditions. No all-milestone acceptance.
3. Reuse existing source/proof/packet work. Fix M3 proof-content validation; implement real M4 datapath wiring rather than another model; anchor M6 to actual accepted replay; bind M7 physical profiles; make M8 consume a genuine fresh execution. Do not spend another batch producing placeholders around missing work.
4. Freshly check global heavy queue ownership. When free, execute one reviewed, frozen real ring RTL cell in a private immutable output with original caps. Correct any concrete harness/tool errors rather than rerunning scaffolding. Audit raw artifacts independently.
5. Run the M7 SV component test as a separate bounded check when safe, then compile/execute the actual M2 production transport regression through the private pinned integration. These component checks do not require all twelve families ready.
6. Expand actual full-size inventory, packet/credit/stall/reset/drain, native decoder/CDG/progress and capture replay across ALL original12 families. Additional dragonflynew is separate; do not let it replace a required row.
7. Only after genuine full chain exists, run pinned-snapshot fresh reproduction and final audit. Never infer simulation from generation, proof validity from a digest/status field, or complete acceptance from agent task counts.

## Repository/source safety

The interactive repo is `/home/datavex/bruh/veritx-research`, branch `integration/studio-reconciliation`, heavily pre-dirty (620 status entries at checkpoint, mostly unrelated UI/backend and prior work). No broad reset/stash/clean/commit. Its `PROGRESS.md` concerns another effort; it was not overwritten. This handoff is a NEW file under docs/research.

Actual external Constellation source Git root is `$LAB/full-connectivity-v1/src`, branch `master`, observed HEAD `c1b42cd0c7c7d6e4fc1ed9bf1f86fbd3b31ac510`, already extensively dirty. This workflow authorizes writes only under `$ROOT` plus this newly requested handoff. Read/copy external inputs, modify PRIVATE copies only; never overwrite historical evidence or external OpenCode outputs. Other sessions own their work.

### Suggested next-session prompt

> Continue the RTL M1–M8 goal using Luna agents. First read docs/research/RTL-M1-M8-HANDOFF-20261108.md and consume workflow9cac9f69-c32b-402a-b810-9f005f90737d if terminal. Preserve all existing changes. Do not repeat broad scouting or checker-only placeholders. Focus on unresolved final-review findings, real GEC-hybrid datapath integration, actual shared-channel RTL/profile bindings, and one genuinely executed/audited frozen ring cell after global heavy-slot clearance. Keep original12-family gates, private ownership and resource caps. Zero complete qualifications are established by this handoff.
