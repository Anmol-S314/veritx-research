# Review — Analysis, Workloads & Requirements, Optional Agents (13 exports)

Scope: the 13 Stitch exports added after the Design/Explore batch, rendered from their
`code.html` sources. Reviewed against the shared contract in `docs/design/stitch-prompts/`
and against the repository's actual capability envelope.

| Group | Exports |
| --- | --- |
| Analysis | `analysis_summary_sim_402`, `analysis_traffic_matrix_sim_402`, `analysis_traffic_matrix_sim_402_missing_artifact_corrected`, `analysis_topology_overlay_sim_402`, `analysis_metrics_sim_402`, `analysis_trace_viewer_sim_402`, `analysis_run_comparison_sim_402_vs_sim_401` |
| Workloads & Requirements | `workloads_requirements_workload_library`, `workloads_requirements_structured_workload_editor`, `workloads_requirements_requirements_editor`, `workloads_requirements_endpoint_bindings`, `workloads_requirements_assumptions_model_inputs`, `workloads_requirements_validation_lowering_preview` |
| Optional agents | `optional_agents_contextual_assistant`, `optional_agents_runtime_connection_permissions`, `optional_agents_approvals_scope_changes_activity` |

Verdicts:

- **Workloads & Requirements: strong.** The requirement-revision policy text is exactly right
  ("Relaxing an acceptance threshold is an explicit requirements change … NOT an architectural
  repair"), and `r5-draft*` correctly shows SIM-402 still failing. Keep this voice.
- **Analysis: usable structure, unusable numbers.** Screen layout and evidence-boundary text are
  good; the measurement set is internally contradictory and physically impossible.
- **Optional agents: mostly fabricated.** The assistant screen is honest; the runtime screen
  invents a transport, engine, and audit trail.

---

## Blocking defects

### A. One run, four mutually exclusive throughputs

With 1 flit/cycle/link at 1.4 GHz and 128-bit links, one directed link carries
**22.4 GB/s**, and a 16-endpoint mesh injects at most **358 GB/s** in total.

| Screen | Claim for SIM-402 |
| --- | --- |
| `analysis_summary_sim_402` REQ-THR-01 | **43.8 GB/s** "aggregate to HBM", MET vs ≥ 40.0 GB/s |
| `analysis_metrics_sim_402` | **43.8 GB/s** |
| `analysis_run_comparison_sim_402_vs_sim_401` | **22.4 GB/s** aggregate |
| `analysis_topology_overlay_sim_402` | **22.4 GB/s** capacity, **20.70 GB/s** observed |
| `analysis_summary_sim_402` OBS-01 | 20.6 GB/s on one link = 92% of 22.4 |

Two of these cannot both be the whole network. Either the aggregate is ~22.4 GB/s (one link's
worth for 16 endpoints, which is implausible but at least self-consistent) or ~43.8 GB/s; pick
one, derive it from the pair matrix, and make every screen quote that one number.

### B. The traffic matrix cannot be true

`analysis_traffic_matrix_sim_402`:

- Caption says **"8 Initiators × 8 Targets (64 pairs)"**; the grid has **10 target columns**
  and rows containing **8 values**.
- Row sum total is **56.665 M flits**. Stated "Total Flits: **2.41M**". Heatmap scale says
  **0–4.2M** while single cells read up to **3.88M** — a cell larger than the claimed total.
- 56.665 M flits over the declared 450,000-cycle window is **125.9 flits/cycle**, i.e. ~4×
  the maximum aggregate injection of a 4×4 mesh at 1 flit/cycle/port. The matrix is
  arithmetically impossible for the stated topology.

Fix: choose a loopback-free 8×8 pair set, generate counts that sum to the aggregate flit total
quoted elsewhere, cap each cell at the window length, and re-derive the throughput from the sum.

### C. Fabricated artifacts presented as recorded evidence

Named as if produced by a completed run:

- `sim_402_txn_latency_hist.json` "100k pts" (summary) — a histogram that also appears as
  unavailable in the metrics screen.
- `sim_402_flit_delivery_matrix.csv`, `sim_402_router_stat_summary.json`,
  `sim402_burst_phase2.trace.bin:offset_0x028A14` (trace viewer) — including a byte offset into
  a binary trace.
- "Recorded Hardware State", "Artifact Provenance & Verification Note".

Nothing in this repository produces those files. Either label the block
"illustrative artifact shape — no file supplied" or remove the filenames and hashes.

### D. Trace viewer contradicts itself and the flit model

- Packet `Pkt_0x4F19` has flits `0..3 [TAIL]` = **4 flits**. For `ResNet50_Burst [w12]`
  (128 B payload) on 128-bit links the minimum is **8 data flits**; 4 flits is 64 B.
- Inspector shows "Flit 0/4 (HEAD, 128-bit)" while the row list shows 4 rows total.
- `BUFFER_STALL 114,818 – 114,834` is labelled **16 Cycles**; inclusive that span is 17 cycles.
- Cycle→time conversion is correct (114,810 / 1.4 GHz = 82.007 µs) — keep that.
- Credit starvation is asserted as fact ("Downstream Credits 0/8") from an "example trace",
  while the same screen elsewhere admits no trace was captured.

### E. Invalid route still present

`analysis_traffic_matrix_sim_402` inspector: "Static Route: R_1_2 → R_0_2 → R_0_0 (**2 Hops**
via DOR-XY)". That path is 3 hops (R_1_2→R_0_2, R_0_2→R_0_1, R_0_1→R_0_0) and does not reach
`EP_NPU_CORE_0` unless its local port is R_0_0. The trace viewer instead ejects at `Tgt_0` from
`R_0_2`, so the two screens disagree about where the packet goes.

### F. Lowering preview claims qualification it cannot have

`workloads_requirements_validation_lowering_preview`:

- "Stage 5: Question Coverage — **QUALIFIED** (LAT-04, THR-02)" and "Stage 3 PASSED"
  alongside "5. Question Coverage … Inconclusive: Coherence Sched." on the same screen.
- "Adapter coverage: **82.4% native fidelity**" — an invented metric with no definition,
  denominator, or method.
- "Srota Native Cycle-Accurate … Status: **Available (Requires Full License)**" — contradictory,
  and asserts coherence-directory and register-slice timing models this repository does not
  establish. `test_rtl_generation_is_partial_not_product_integrated` still pins generation as
  PARTIAL.
- "SystemC TLM-2.0 Adapter … **Staged for Q3 Release**" — a roadmap claim invented by a mock.
- Flit math: `OP-101` "Read **512 KiB** from HBM3_0" lowered to "**size=4 flits**". 512 KiB at
  16 B/flit is **32,768 flits** — off by 8,192×. `OP-201` 128 B stream should be ≥ 8 flits.

The honesty paragraph at the bottom ("confirms mathematical parameter validity only … does not
certify physical timing, routing DRC/LVS, or synthesize an RTL datapath") is correct and should
be the *only* status language on this screen.

### G. Global chrome fabricates a running backend

Every one of the 13 screens carries a status strip claiming:

- "**1 Active Job (Sim #403: Bert_Large 18%)**" — no job exists.
- "**Local Daemon v2.4.1**" / "Daemon v2.4.1" — no daemon exists.
- "DRC: **Clean**" (workloads, validation preview) and "**verified DRC/LVS: Clean**"
  (`workloads_requirements_endpoint_bindings`) — while the same bindings screen says binding
  "does not constitute physical timing closure, sign-off DRC/LVS". Header and body contradict.
- "Policy: Strict Verification · Zero != Missing; No Silent Fallbacks" — good, keep.
- Analysis screens say "DRC: Not Evaluated", so the strip is also inconsistent across groups.

### H. Optional agents runtime screen is fiction

`optional_agents_runtime_connection_permissions` presents, as live state:

- "**PROTOCOL VERIFIED** | SANDBOX COMPLIANCE: **ENFORCED**", "CYCLE: 14,290,112",
  "ENGINE: **VERITX-RTL v2.4.9**", "DRC: **0 VIOLATIONS**",
  "LOCAL RPC: 127.0.0.1:9042 | MEM: 4.12 GB / 32.0 GB".
- A "Protocol Handshake Frame Inspector" with `[00:01.403]` timestamped frames, "Frame validator:
  Zero framing errors", and "**Export Raw PCAP Frame Trace**".
- "FPGA XC7V2000T … radix" fragments inside a handshake frame — not a protocol field.

No transport, credential store, engine, or PCAP capture exists. `Export Raw PCAP Frame Trace` is
actively harmful: it promises a network capture artifact the product cannot produce, and a PCAP
of a local IPC stream would leak prompt/context data if it ever did.

The *permission matrix* portion (allowed/denied operations, "NEVER_ALLOWED RELAX_REQUIREMENTS …
Requirements r5 are immutable") is good and should survive; only the live-telemetry theatre must go.

---

## Keep (these are better than the Design batch)

- Requirement-revision discipline in `requirements_editor`: base vs draft delta, "+3.0 ns
  (+4.2 cyc)", "Still Fails Target", and the explicit statement that historical SIM-402 stays
  Violated under r5. This is exactly the behaviour the prototype now implements.
- `assumptions_model_inputs`: "Unspecified" instead of a guessed memory-service duration, and the
  note that an operation-specific duration override must not be silently rewritten.
- Analysis summary/metrics boundary text: "Complete transaction P95: Not recorded", "Power / cell
  area / achieved timing: unavailable, not inferred from network statistics".
- `analysis_traffic_matrix_sim_402_missing_artifact_corrected` refusing to substitute requested
  demand for observed traffic.
- Comparison screen's refusal to compute deltas across mismatched workloads.
- `optional_agents_approvals_scope_changes_activity` framing approvals/revocation as local
  previews, and the absence of private model reasoning in the activity log.

## Consistency items (minor)

- "8 Initiators × 8 Targets" vs a 10-column grid (see B).
- Two identifiers for one pending requirements change: `r5-draft*` and `r6-draft` / "Review &
  Commit r6".
- "Requirement Violated (1 of 4 failed)" (matrix/summary) vs "5 criteria 3 Met 1 Violated 1 Not
  Eval" (requirements) — the 4 vs 5 denominator must match, and "1 of 4" omits the Not-Evaluated
  criterion entirely.
- Simulator identity drifts: "BookSim-v2.1 (Cycle-accurate NoC, non-signoff)" in the strip vs
  "ENGINE: VERITX-RTL v2.4.9" in the agents screen.
- `analysis_summary_sim_402` gives "P99 Tail Latency 34.8 ns, Max 41.2 ns" while the headline
  criterion is 28.6 ns; both are P99 in one place and packet vs transaction in another. State one
  definable statistic per label.

---

## What the prototype did with this batch

Implemented as fixtures that keep the *intent* and drop the fiction
(`apps/studio/prototype/src/AnalysisViews.tsx`, `WorkloadViews.tsx`, `AgentViews.tsx`):

- One run set (`SIM-402`, `SIM-451`, `SIM-401`) whose numbers are reconciled: pair fixture sums to
  **329,464 delivered flits**, which is **16.4 GB/s** over 450,000 cycles at 1.4 GHz — the same
  figure the matrix, metrics, summary, and comparison screens quote.
- Requested / injected / delivered are separate bases; a recorded zero stays `0` and is never
  filled from another basis.
- Link utilization is labelled a **canonical-route proxy**, not a recorded link counter, and is
  bounded by the window length.
- No histogram, per-packet trace, or transaction P95 is synthesized; the trace screen ships an
  explicitly separate `DEMO-TRACE-A` example that cannot be attributed to SIM-402.
- The lowering preview exports generic intent correspondence and refuses to emit BookSim flags;
  data amounts produce minimum 128-bit data flits (128 B → 8) with no invented header overhead.
- Working requirement revisions (e.g. 25 → 40 ns) are reviewed, stored separately, and never
  rewrite the captured r5 fixture's `Not evaluated` outcomes.
- Agent runtime configuration validates scheme/host/credential-reference shape, saves **intent
  only**, asserts no transport, and its browser test asserts **zero outbound requests**.
