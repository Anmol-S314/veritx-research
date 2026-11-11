# Stitch correction prompt — Analysis, Workloads & Requirements, Optional Agents

Apply per screen. Send with the target screen attached; do not send more than one screen's
corrections at a time.

---

## Shared, every screen in this batch

1. Remove the fabricated global status strip. Delete "1 Active Job (Sim #403: Bert_Large 18%)",
   "Local Daemon v2.4.1" / "Daemon v2.4.1", and any DRC/LVS verdict in the top bar. Replace the
   entire strip with one line: `No backend connected · authored illustrative fixture · v1.0.0`.
2. Never show a filename, hash, byte offset, or CSV/JSON/trace name unless the screen also offers
   the file. When no file exists, write `Evidence shape only — no artifact supplied`.
3. One run = one set of numbers. Choose a single aggregate delivered throughput for SIM-402 and
   use it in the summary, metrics, matrix, topology overlay, and comparison screens.
4. Keep `Zero ≠ Missing`. A recorded zero renders `0`; an unrecorded value renders
   `Not recorded`, never `0`, never `—` as if it were a measurement.
5. Do not label a preview outcome `QUALIFIED`, `PASSED`, `PROVEN`, or `VERIFIED` unless an
   executable backend produced it. Use `Preview only`, `Not evaluated`, `Unavailable`.

---

## analysis_summary_sim_402

- `REQ-THR-01 Sustained Ingress Throughput ≥ 40.0 GB/s` currently reads `43.8 GB/s (+3.8 GB/s
  margin) MET`. Replace with the single aggregate value used everywhere (see item 3); if that
  value is below 40.0 GB/s the criterion is `Violated`, and the screen must say so.
- `OBS-01` mixes two different quantities: "Raw link capacity: 22.4 GB/s; observed flit transfer
  rate: 20.6 GB/s" is per-link, while the throughput criterion is aggregate. Label the observation
  `Per directed link (101% = 22.4 GB/s capacity)` and state that it is a derived proxy from
  canonical routes, not a recorded link counter.
- Remove `sim_402_txn_latency_hist.json 100k pts` and `sim_402_router_stat_summary.json 16 RTs`
  or mark them `Evidence shape only — no artifact supplied`.
- Requirement tallies: state `5 criteria: 2 Met · 1 Violated · 2 Not evaluated` and use the same
  5-criterion denominator on the matrix and requirements screens.
- One latency statistic per label. Do not show `P99 Tail Latency 34.8 ns` next to a criterion
  bound of 25.0 ns unless the screen says which P99 (packet vs transaction) and states that the
  transaction P95 is `Not evaluated`.

## analysis_traffic_matrix_sim_402

- Make the grid actually 8×8 with 8 target headers and 8 values per row, or change the caption to
  match 10 targets. The current caption, header count, and cell count disagree.
- Regenerate cell values so the row sum equals the aggregate flit total quoted on the summary
  screen. Current cells sum to 56.665 M while the header says `Total Flits: 2.41M`, and the
  heatmap scale `0–4.2M` is smaller than the largest single cell (3.88M).
- Enforce a physical ceiling: no cell may exceed the 450,000-cycle window, and no column total may
  exceed 1 flit/cycle/link × window.
- Replace the inspector route `R_1_2 → R_0_2 → R_0_0 — 2 Hops via DOR-XY` with a valid path whose
  hop count matches the drawn path and that terminates at the selected target's local router.
- Keep the "Evaluated Artifact Mismatch: d7a4e9b vs d7a4e9b-mod1*" banner. That is correct and
  should stay.

## analysis_traffic_matrix_sim_402_missing_artifact_corrected

- Keep the refusal to substitute requested demand. Add an explicit line: `This is an alternate
  fixture scenario, not a mutation of SIM-402's recorded artifact manifest.`
- Remove the invented `Required filename / hash` placeholder if no name is known; write
  `Not supplied` instead of a plausible-looking file name.

## analysis_topology_overlay_sim_402

- State the denominator next to every percentage: `busy-cycle proxy = routed flits ÷ 450,000
  cycles`. Do not present utilization as a recorded counter.
- Use the same aggregate throughput as the summary screen; `20.70 GB/s` here and `43.8 GB/s` there
  must become one figure with one definition.
- Label the canvas `logical topology · no physical coordinate frame` and keep the "not proof of
  causality" note.

## analysis_metrics_sim_402

- `43.8 GB/s` must match the reconciliation in item 3.
- Remove the "Latency distribution" affordance unless a distribution is supplied; if kept, it must
  open an explicit `Not supplied` state rather than an empty chart.
- Keep the definitions column. It is the best part of this screen.

## analysis_trace_viewer_sim_402

- Either supply a trace or label the whole screen `Illustrative example — not captured by SIM-402`.
  Do not present an example packet as "Recorded Hardware State".
- Fix flit accounting: `ResNet50_Burst [w12]` = 128 B payload on 128-bit links = 8 data flits.
  Show `HEAD, BODY×6, TAIL` (8 flits) instead of `Flit 0/4 [TAIL]`.
- `BUFFER_STALL 114,818 – 114,834` labelled `16 Cycles` is 17 cycles inclusive. Change to
  `114,818–114,833 (16 cycles)` or `17 cycles`.
- Remove `sim402_burst_phase2.trace.bin:offset_0x028A14` and the "Artifact Provenance &
  Verification Note" unless a real file backs them.
- Rename `Disciplinary Observation` to `Interpretation` and mark it a hypothesis, not a finding.

## analysis_run_comparison_sim_402_vs_sim_401

- Keep the refusal to compare mismatched workloads. Add the same refusal for
  `182.4 GB/s` vs `148.6 GB/s` rows: a whole-mesh aggregate cannot exceed
  16 endpoints × per-link capacity; either the metric is per-link, or the numbers are wrong.
- Show the metric definition (`network packet P99`, not transaction P95) in the table header, and
  mark `REQ-LAT-04 transaction P95 = Not evaluated` on both sides.
- Remove `Transaction SLA guarantee` wording where the SLA criterion is not evaluated.

## workloads_requirements_workload_library / structured_workload_editor / assumptions_model_inputs

- Keep these almost as-is. The `Unspecified` memory-service duration, the "override must not be
  silently rewritten" note, and the declared-vs-derived distinction are correct.
- In the editor, show flit math explicitly for each operation (`bytes ÷ 16 = minimum data flits`)
  and label it `minimum data flits; excludes header, adapter, and packetization overhead`.
- Remove `DRC: Clean` and `1 Active Job` from the chrome (see shared item 1).

## workloads_requirements_requirements_editor

- Keep the revision-policy paragraph and the "Still Fails Target" treatment verbatim.
- Use one identifier for the pending change. `r5-draft*`, `r6-draft`, and "Review & Commit r6"
  currently describe one diff three ways.
- Add `Not evaluated` explicitly to the tally so `3 Met / 1 Violated / 1 Not Eval` is stated as
  `5 criteria` everywhere.
- Keep `28.6 ns [VIOLATED by +3.6 ns]`.

## workloads_requirements_endpoint_bindings

- Remove `verified DRC/LVS: Clean` from the top bar. It contradicts the body text that binding
  "does not constitute … sign-off DRC/LVS".
- Remove `Problems: 0 / Errors: 0` counters that no checker produced.
- Keep the role checks (initiator/target) and the "does not allocate addresses, grant permission,
  create routes, or prove delivery" boundary.

## workloads_requirements_validation_lowering_preview

- Delete `Stage 5: Question Coverage — QUALIFIED (LAT-04, THR-02)` and `Stage 3 PASSED`. Use
  `Preview only — not evaluated` and keep the existing "Inconclusive: Coherence Sched." line.
- Delete `Adapter coverage: 82.4% native fidelity`. If a coverage number is unavoidable, define
  numerator and denominator in the same sentence.
- Delete `Srota Native … Status: Available (Requires Full License)` and
  `SystemC TLM-2.0 Adapter … Staged for Q3 Release`. Replace with
  `Not available in this build`.
- Fix the lowering math: `OP-101 Read 512 KiB → size=4 flits` is 32,768 flits at 16 B/flit. Show
  correct minimum flits per operation, or show bytes and say `flit count not derived`.
- Keep the "Lowering Scope Boundaries" paragraph; it is the only accurate status text here.

## optional_agents_contextual_assistant

- Keep the manual-equivalent links and the "no model response available" boundary.
- Add a visible `0 bytes transmitted` indicator and require explicit per-document context
  attachment; never imply the assistant already sees the whole project.

## optional_agents_runtime_connection_permissions

- Delete everything asserting a live channel: `PROTOCOL VERIFIED`, `SANDBOX COMPLIANCE:
  ENFORCED`, `CYCLE: 14,290,112`, `ENGINE: VERITX-RTL v2.4.9`, `DRC: 0 VIOLATIONS`,
  `LOCAL RPC: 127.0.0.1:9042`, `MEM: 4.12 GB / 32.0 GB`, the timestamped handshake frames,
  `Frame validator: Zero framing errors`, and the buffer-capacity counters.
- Delete `Export Raw PCAP Frame Trace`. A connection that does not exist cannot produce a capture,
  and a capture of local agent traffic would expose prompt and artifact contents.
- Remove `FPGA XC7V2000T … radix` from protocol frame fields.
- Keep the permission matrix and make `NEVER_ALLOWED · RELAX_REQUIREMENTS` prominent: an agent may
  not loosen `REQ-LAT-04 (25 ns)` or the throughput target.
- Replace the credential field with an environment-reference name only, add
  `Never paste a token value`, and state that no credential is read or stored.
- Rename the primary action `Save connection intent locally` and keep
  `Test handshake unavailable` disabled.

## optional_agents_approvals_scope_changes_activity

- Keep the local-preview framing and the absence of private reasoning in the log.
- Add the consequence of revocation in the dialog: cancels nothing running, preserves drafts,
  candidates, fixtures, and prepared artifacts.
- Remove any `Verify` affordance that implies an independent audit of activity the product did
  not record.
