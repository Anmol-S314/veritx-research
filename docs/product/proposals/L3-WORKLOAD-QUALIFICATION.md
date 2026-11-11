# L3 — Workload qualification of the composed RTL (proposal)

Status: **PROPOSED, NOT EXECUTED** — 2026-11-10. This document is analysis only. No build, sim, or code edit was
performed to produce it (operator constraint). Nothing here upgrades any gate in
`MILESTONE-14-PRODUCTION-RTL-20261110.md`; the L3 cell stays ✗ until the procedure in §3–§4 has actually been run
and its evidence pinned.

Authority and inputs (all read, not modified):

- Pin: `docs/product/evidence/release-workloads-20261110.json` (contract_version 1, approval_id `release-workloads-20261110`,
  approved 2026-11-10 by operator directive, selection rule: *"Only workloads already present in this checkout are approved.
  No workload is resized, sampled down or invented. The Mixtral selected revision is the full-size acceptance case; the
  small designs are debugging aids and never replace it."*)
- Completion plan: `docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md` (§P3, §P4, §P5), milestone table in
  `docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md` (L3 definition: *"Workload-driven RTL qualification with the
  pinned workloads (no synthetic-only traffic); conservation/credit/reset across packet sizes, all VC classes,
  in-order + escape"*), P0–P1 status in `docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md`, P2/P3 measured verdicts in
  `docs/product/P2-P3-EVIDENCE-20261110.md`, remaining work in `docs/product/REMAINING-WORK.md` (item 5, the
  **P3 finish line — multi-instance/multi-seat compose path**, and item 20, contention-qualification scope).
- Synthetic TB baseline: S1–S28 in `tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py` (locked 2×2 slice TB;
  S18/S19/S28 are `NOT_RUN` for missing primitive `SLICE_MULTI_DEST`; no credit tap/delay primitives `SLICE_CREDIT_TAP`,
  `SLICE_CREDIT_DELAY` exist; post-S24 refused-burst seq-accounting gap and out-of-window SLVERR B-response wedge are
  open per `INTENT-TO-PLACED-RTL-P0-P1-STATUS.md`).
- The two endpoint-loss regressions `test_composed_family_never_drops_agent_instances[0/1]`
  (`tracks/t3-topology/dse/tests/test_project_top_slice.py`) show the current state: a 4-instance compiled request is
  **refused** by `composed_family_params_from_request` ("one instance per agent group") — per-instance adapters do not exist yet.
- Environment facts (read-only probes, no build): Verilator 5.032 (2025-01-01) and iverilog are installed.

---

## 0. TL;DR

1. **None of the 17 approved entries is a packet/flit/credit/VC/reset capture.** Five are declared request JSONs
   (authored or model-derived fabric + traffic-class profiles), twelve are data captures (paper-reported collective
   counts, aggregate link counters, kernel-slowdown ratios, a robotics frame ledger, CPU model-stage traces, VLA-Perf
   analytical roofline tables). Direct TB playback of "approved packet streams" is **not possible** and must not be
   claimed.
2. The only honest L3 path is **traffic-class-constrained synthetic injection** whose payload bytes, traffic classes,
   collective shapes and binding requirements are taken verbatim from the pinned files (hash-verified at test time).
3. Minimal viable sequence: **M1 = mesh 2×2 composed slice with 2-instance agent groups (aligned with the P3
   multi-instance finish line), two workloads (gr00t-vla-robotics-v4, pi0-thor-modeled-v4), all-pass gates** — then
   mesh-4×4 (32/64/128, VC 1/2/4, multi-clock) with a third workload and the switch-gen6-class 170-profile envelope,
   then torus-3×3 / ring-16 family regression, then the full-size Mixtral r02 acceptance (not one of the 17 captures).
4. CI artifact: a new `tracks/t3-topology/dse/tests/test_workload_rtl_qualification.py` (fail-closed, verilator-gated,
   approval-hash gated, `NOT_RUN` never counts as pass). Evidence pinned into
   `docs/product/evidence/l3-workload-qualification-<run-date>/` with a sha256 manifest and a human REPORT.md.
5. What is impossible from the pinned data (exact cycle traces, calibrated latency, measured "workload performance")
   is listed in §5 with mandated RFC wording. No L3 result may use the words *measured*, *calibrated*, *traced*, or
   *validated* for the workload itself.

---

## 1. What the 17 approved entries actually are (inspected, hash-verified)

All 17 paths exist in this checkout and **all 17 sha256 digests match the pin** (verified 2026-11-10 at this tree
state; re-verification is gate G1 in §3 and must be re-run by the executing session). Classification:

### 1.1 Bucket A — request JSONs (5): authored/declared fabric + traffic profiles, NOT measurements

| id | kind | what it is | Injectable material |
|---|---|---|---|
| `gr00t-n16-h100-measured` | request | GR00T N1.6 stage split measured on H100 (data prep 4.72 ms / backbone 37.96 ms / action head 94.28 ms, E2E 148.62 ms, 20 iters); **8-rank mesh 3×3 fabric, rank roles and traffic profiles are authored** | 9 profiles: camera_ingest 196,608 B (0→1); vision_tokens 65,536 B (1→{2,3,4,5}); action_tokens 20,480 B ({2,3,4,5}→6). No collectives. No binding requirements. Mesh 3×3, 256-bit links, 1 GHz |
| `gr00t-vla-robotics` | request | GR00T N1.7 Thor model-card durations (data 8.21 ms / backbone 28.89 ms / action head 56.64 ms); fabric + 1 kHz control stage + deadlines **authored** | 10 profiles: same as above + **control_out 128 B (6→7)**, binding requirement `control_out` latency_critical ≤ 1,000,000 cycles, `camera_ingest` latency ≤ 33,000,000 cycles + ≥ 0.005 GB/s floor. Mesh 3×3 |
| `qwen3-moe-tp2-ep4-16tiles` | request | **Declared** (not modeled, not measured) compute: 96 stages (48 layers × attn/moe) = 4096 B activation in/out per stage, TP2/EP4, 16 compute tiles + 4 HBM controllers + 2 NICs, 5×5 mesh | collectives: **allreduce 4096 B** (`tp_collective`, binding latency_critical ≤ 50,000 cycles); **alltoall 2048 B** ×2 (`ep_dispatch`, `ep_combine`). `traffic_profiles` is empty — collectives only |
| `pi0-thor-modeled` | request | π0 stage times are **VLA-Perf modeled roofline** (Thor, 10 denoising steps × horizon 50): vision 6.062347 ms / VLM 20.303090 ms / action 26.199927 ms (10 × 2,619,993 ns); fabric authored; fabric 3×3 | 9 profiles: camera_ingest 150,528 B (0→1); vision_tokens 262,144 B (1→{2,3,4,5}); action_latents **800 B** ({2,3,4,5}→6). No requirements |
| `switch-gen6-class` | request | **Authored hypothetical** Gen6-class 16-port switch fabric (NOT any Switchtec product, NOT PCIe): ranks 0–7 host-port proxies, 8–15 SSD-port proxies; 16 compute_tile agents; mesh 4×4 | **170 profiles**: read_256k 56×262,144 B + read_4k 56×4,096 B + write_256k 24×262,144 B + write_4k 24×4,096 B + incast_ssd0 2×262,144 B + multicast_equiv (duplicate unicast fan-out) 8×65,536 B — see note¹. Byte mix exactly 70/30 read/write (verified: read 14,909,440 B, write 6,389,760 B). Requirements: `incast_ssd0` latency_critical ≤ 10,000,000 cycles; `multicast_equiv` bandwidth ≥ 0.001 GB/s |

¹ multicast_equiv payloads are 65,536 B each (8 × 65,536 = 524,288 B; the same byte total as incast_ssd0's
  2 × 262,144 B).
  The profile list encodes host→SSD issue direction only; read data-return direction is **not modeled** upstream.

### 1.2 Bucket B — captures with payload-shaped numerics (3): counts and sizes, zero packet events

| id | kind | what it is | Injectable material |
|---|---|---|---|
| `llama31-8b-tp4-collectives` | capture | Paper-reported collective counts/payloads (arXiv 2507.14392, Table III/IV; vLLM 0.8.5.post1, NCCL 2.21.5, H100×4 NVLink). **No timestamps, no rank-specific events, no NCCL algorithm, no packets.** Count interpretation supported only by the paper's TP-invariance statement; raw participant-rank events absent | 65 × 1,048,576 B prefill allreduce; 8255 × 8,192 B decode allreduce; gather 1 + 127 × 64,128 B (**Gather dtype assumed, not reported**). Totals: prefill 68,157,440 B; decode 67,624,960 B; gather 8,208,384 B |
| `cal26-qwen3-30b-ep4-kernel-slowdowns` | capture | Public DeepEP(20) EP=4 vLLM kernel slowdown ratios (o proj GEMM etc.); 469 rows; range **1.0141–1.5183** | **None** — no bytes, no ranks, no packets. Informs "collective schedule exposure" only |
| `cal26-qwen3-30b-ep4-nvlink-counters` | capture | Aggregate panel counters (panels 22–28), 350 rows, `t_ms` 0.000256 → 2.6318; `nvlink_GBps` values as printed are ~1e-7 (unit anomaly is upstream's, not ours to fix) | **None** — aggregate link counters, not topology-specific, not per-link, no bytes-per-hop. Informs "link counter samples" only |

### 1.3 Bucket C — media/robotics dataset events (1): media packet sizes, not NoC flits

| id | kind | what it is | Injectable material |
|---|---|---|---|
| `gr00t-g1-apple-to-plate-events` | capture | Dataset-derived frame ledger of a public GR00T-X-Embodiment sim episode (metadata + 683 frames, 50 fps, 13.64 s): H.264 demux packet sizes with PTS + raw state/action vectors (344 B each). Total H.264 payload 1,456,293 B | **None without authored fabrication.** PTS is media presentation time; packet sizes encode video packetization; there are no ranks, no NoC addresses, no classes. Any mapping to a fabric would be authored, not pinned, and must be labeled as such — see §2.4 |

### 1.4 Bucket D — model-level stage traces and analytical tables (8): no network events at all

| id | kind | what it is | Injectable material |
|---|---|---|---|
| `lerobot-smolvla-trace` | capture | Real CPU LeRobot run (SmolVLA base, 450 M params, 2 timed calls × 4 stages); 8 rows; stage durations µs–ms; payload 2,359,296 B | Payload size only, with authored mapping (not a network profile) |
| `lerobot-smolvla-vla-trace` | capture | Same, stage split vision_encoder / vlm_prefill / 10 denoise steps / totals; 15 rows | Same |
| `lerobot-act-pusht-trace` | capture | Real CPU ACT/PushT run; 2 timed calls; 110,592 B payload | Same |
| `vla-perf-network-latency-kvcache` | capture | VLA-Perf **analytical** WAN round-trip model (4G…400GbE) for image-up/KV-cache-down; 66 rows; includes max sync/async control Hz column | None — WAN link model, unrelated to an on-package NoC |
| `vla-perf-network-latency-images` | capture | Analytical image-upload latency; 88 rows | None |
| `vla-perf-validation` | capture | VLA-Perf's roofline-vs-real check (RTX 4090/5090; `roofline_pct`); 6 rows | None |
| `vla-perf-pi0-denoising` | capture | π0 denoising-steps × chunk-size sweep; 75 rows | None for RTL (byte sizes already present in `pi0-thor-modeled`; do not double-count) |
| `vla-perf-pi0-family` | capture | π0 family E2E roofline per hardware/chips/batch; 55 rows | None |

**Excluded entry** (from the pin): `tracks/t3-topology/runs/…/mixtral-8x7b-64tiles_n64.trace` — "run output, not a
checked-in input"; it also does not exist in this checkout (verified). It must not be used.

**Direct answer to question 1:** there are no real packet captures, no NoC traces, and no tensor-profile summaries
with routing-layer semantics anywhere in the 17. There are exactly **five request JSONs** whose `traffic_profiles` /
`collectives` / `requirements` blocks encode byte-exact, class-tagged injection envelopes, plus **one capture**
(`llama31-8b-tp4-collectives`) whose counts × payload shapes do the same for collective classes (with the caveats in
§1.2). Everything else is context/provenance for analysis questions, unusable as RTL stimulus without authored invention.

---

## 2. Strategy

### 2.1 (a) Direct TB playback of approved packet streams — NOT AVAILABLE

No approved entry contains per-flit or per-packet records addressed to NoC destinations. The closest things to "packets"
in the pin are: (i) H.264 demux packet sizes with presentation timestamps (Bucket C) — media packetization with no
fabric semantics; (ii) h264 PTS (Bucket C), CPU wall-clock timestamps (Bucket D traces), `t_ms` counter cadence
(Bucket B) — none are NoC cycles; (iii) collective-level counts and byte shapes with **no order, no rank
schedule, no algorithm, no inter-operation gaps** (`llama31-8b-tp4-collectives.json → not_observed_in_source` says this
itself). Replaying any of these as packets would require inventing addressing, VC assignment, packetization and timing —
which the pin's selection rule and this repo's honesty rules both forbid ("No workload is resized, sampled down or invented").

**Conclusion: L3 has no (a) path. Anyone claiming "the pinned workloads were played into the RTL" is wrong.**

### 2.2 (b) Traffic-class-constrained synthetic injection — the only viable path

Define a derived, pinned **injection envelope** (`L3-ENV`) per source entry. The envelope is *derived data*, produced by a
small documented derivation (the future `test_workload_rtl_qualification.py` fixture may compute it in-memory; if a
persisted copy is pinned as evidence it is labeled derived, never confused with the pin):

1. **Classes and bytes, verbatim.** Each `traffic_profiles[]` row contributes one class-tagged flow with exactly its
   `payload_bytes`. Each `collectives[]` row contributes a collective-class flow with exactly its
   `payload_bytes` per rank per call and its declared call count (for llama31; for qwen3, per-layer cadence from the
   declared 96-stage compute table).
2. **Byte-exactness, not rate fidelity.** Injection is constant-rate, back-to-back per flow, in the authored list order.
   No claim is made that this reproduces any production timing (no production timing exists in the pin).
3. **Flit mapping at the design's link width.** Every payload in Buckets A/B is a multiple of 8 B, 16 B and 32 B
   (checked: 196,608 / 150,528 / 262,144 / 65,536 / 20,480 / 128 / 800 / 4,096 / 2,048 / 1,048,576 / 8,192 / 64,128 all
   divisible by 32). At 256-bit fabric (32 B flit): camera_ingest 6,144 flits, vision_tokens 2,048/8,192 flits,
   action_tokens 640 flits, control_out 4 flits, action_latents 25 flits, qwen3 allreduce 128 / alltoall 64 flits,
   llama31 prefill 32,768 / decode 256 / gather 2,004 flits, switch-gen6 read_256k 8,192 / read_4k 128 / write_256k 8,192 /
   write_4k 128 flits. The split of each payload into packets follows the adapter burst cap (current locked slice:
   16 beats × 32 bit; composed widths 64/128/256 bit scale the beat math, not the byte totals).
4. **Slice folding (debug designs only).** Debug slices do not host 8 ranks. The envelope is folded onto the slice's
   seats by an **authored** fold map, recorded in the envelope (e.g. for the 2×2 slice: initiator0 ≈ camera/backbone-side
   classes of gr00t/pi0 — camera_ingest + vision_tokens; initiator1 ≈ action-head-side classes — action_tokens /
   action_latents + control_out; HBM0@router2 is the single legal destination, same legality envelope as the locked
   TB's S1–S28). The fold is test scaffolding, declared as authored data, exactly like the requests themselves author
   their fabrics. It never re-labels the debug run as a run of the original design.
5. **Requirements carried, not dropped.** Each binding requirement in the source file is copied into the envelope and
   must be either (i) exercised and observed (record the observed value), or (ii) explicitly marked `NOT_TESTED` with a
   reason. Silently dropping a binding requirement invalidates the run (gate G8).
6. **Collectives are class flows, not semantic collectives.** The RTL has no allreduce/alltoall primitive. A collective
   is injected as its payload-shaped, class-tagged flit stream. No claim is made about collective algorithm, ordering
   across ranks, or NCCL behavior.

**Injection envelopes per approved entry (summary; byte/flit math in Appendix B):**

| Entry | Debug-design fit | Envelope |
|---|---|---|
| gr00t-vla-robotics | 2×2 (M1), 4×4 (M2), torus-3×3/ring-16 (M3) | W-A below |
| pi0-thor-modeled | 2×2 (M1), 4×4 (M2), torus-3×3/ring-16 (M3) | W-B below |
| gr00t-n16-h100-measured | same | W-C (W-A minus control_out; measured compute durations irrelevant to the NoC) |
| switch-gen6-class | **mesh-4×4 exactly** (16 seats = 16 agents; 4×4=16 routers) | W-D: 170 flows, 22,347,776 B total |
| qwen3-moe-tp2-ep4-16tiles | **No approved debug design** (needs 22 seats; 5×5 mesh unavailable — see blockers §6) | W-E: collective-class streams only, full-acceptance path |
| llama31-8b-tp4-collectives | ring-16 or 4×4 with 4 active seats (M3+, operator decision) | W-F: 65×1 MiB + 8255×8 KiB + 128×64,128 B |
| cal26 kernel-slowdowns | — | not injectable (no bytes) |
| cal26 nvlink-counters | — | not injectable (no per-link/per-VC bytes) |
| gr00t-g1-apple-to-plate | — | not injectable without authored mapping (forbidden here) |
| lerobot ×3, vla-perf ×5 | — | not injectable without authored mapping (forbidden here) |

**W-A — gr00t-vla-robotics-v4** (`bb7cc4…`, sha256 verified): camera_ingest 1 × 196,608 B (6,144 flits);
vision_tokens 4 × 65,536 B (2,048 flits each); action_tokens 4 × 20,480 B (640 flits each); control_out 1 × 128 B
(4 flits). Payload total 540,800 B; 16,900 flits @32 B. Requirements: `control_out` latency_critical ≤ 1,000,000 cycles
(binding); `camera_ingest` latency ≤ 33,000,000 cycles + ≥ 0.005 GB/s (binding).

**W-B — pi0-thor-modeled-v4** (`4d1596…`, verified): camera_ingest 1 × 150,528 B (4,704 flits);
vision_tokens 4 × 262,144 B (8,192 flits each); action_latents 4 × 800 B (25 flits each). Payload total 1,202,304 B;
37,572 flits @32 B. No requirements (requirements array is empty). Tests short-payload handling (800 B) and larger
vision class.

**W-D — switch-gen6-class-v4** (`c2e765…`, verified): read_256k 56 × 262,144 B; read_4k 56 × 4,096 B;
write_256k 24 × 262,144 B; write_4k 24 × 4,096 B; incast_ssd0 2 × 262,144 B (both target rank 8 / SSD-port-0 proxy);
multicast_equiv 8 × 65,536 B (the schema's multicast-equivalent duplicate-unicast fan-out — injected as 8 unicast
copies, never as a real multicast claim). 70/30 read/write byte mix (14,909,440 / 6,389,760 — verified exactly 0.7).
Total 22,347,776 B. Requirements: `incast_ssd0` latency_critical ≤ 10,000,000 cycles; `multicast_equiv` bandwidth
≥ 0.001 GB/s (both binding).

### 2.3 (c) The invariants (binding definitions for gates G3–G7)

All invariants are asserted per **VC**, per **class**, per **port**, per **reset epoch**, seeded. SINGLE-flit,
in-order (STRONG) and escape paths are treated distinctly (they are distinct in the RTL: `FT_SINGLE` vs
`FT_HEAD/BODY/TAIL`, per-initiator `STRONG` ordering FSMs, escape allocation after `AGE_K`):

- **I1 — Per-VC conservation.** For every VC `v` and class `c`: `injected(v,c) == ejected(v,c) + outstanding(v,c)` at
  all times; `outstanding(v,c) == 0` at drain (S23-style). No cross-VC credit/data leakage; an accepted packet is
  attributable to exactly one class. Conservation is checked per epoch and across the epoch boundary.
- **I2 — Credit capacity match.** For every (port, VC): `free_credits + queued + in_flight == BUF_DEPTH` at every
  observation point; delayed returns honor `CREDIT_RETURN_LATENCY`; `VC_REUSE_TAIL_CREDIT` releases are accounted;
  no credit is ever aliased across VCs or taps. **Observability caveat:** the locked slice TB exposes
  `dbg_inj/dbg_ej/dbg_dreq/dbg_drsp/outstanding` but has **no credit tap** (`SLICE_CREDIT_TAP` missing). Until that
  primitive lands, I2 can only be checked indirectly (queue drain + outstanding zero — necessary, not sufficient) and
  must be recorded as `CREDIT_UNVERIFIED`, not PASS. **An all-pass M1 claim requires `SLICE_CREDIT_TAP` (or an
  equivalent grant-point check proven equivalent).**
- **I3 — Reset epochs.** An epoch = one full envelope pass. Between epochs the design is reset (`rst_n` negedge pulse);
  after reset every state element covered by the reset block is zero (q_cnt, rt_alloc, esc_mode, locks, side buffers,
  credits = BUF_DEPTH, histories cleared). Epoch N+1 must reproduce epoch N bit-for-bit at the eject boundary; any
  leakage fails the run. Pre-S7 counters must restart at 0/2 (immediate deny+miss accounting unchanged).
- **I4 — Ordering classes.** (O0) STRONG in-order per initiator per class: `seq` completion order never violates
  (zero `order_violation`). (O1) Cross-initiator SINGLE-flit interleaving with distinct awid/arid is legal and lossless
  (S25 semantics) — note the workload envelopes contain no ≤1-flit payloads (smallest is 4 flits), so O1 coverage
  remains synthetic (S25) and is **not** claimed from workloads. (O2) HEAD/BODY/TAIL atomicity: a body/tail never
  overtakes its head on the same (initiator, class); switch lock held for the packet under `HOLD_SWITCH`. (O3) Escape:
  bandwidth-class packets aged past `AGE_K` are grantable on the escape VC; escape coverage is only claimed if a
  sink-hold scenario (S21-style) is included in the run — otherwise recorded as not exercised. (O4) Latency-critical
  class isolation (e.g. control_out on VC1 in the 2-VC configuration) is observed, not assumed; when
  `SUPPORTED_VC_COUNTS` collapses to 1 VC, class isolation is impossible and the report must say so.
- **I5 — Burst/boundary legality.** Every injected burst obeys the adapter cap and address-decode legality (all
  targets HBM0 in debug slices); no SLVERR/DECERR path is silently accepted (currently blocked by the open
  post-S24 refused-burst seq-accounting gap and the out-of-window SLVERR B-response wedge — see §3 M0).
- **I6 — Drain/quiescence.** At end of epoch: all VCs empty, `outstanding == 0`, no switch locks held, `dbg_dreq ==
  dbg_drsp`, no `imm` leakage beyond the pre-S7 accounting.
- **I7 — Requirement observability.** Each binding requirement from the source pin is exercised and its observed value
  recorded, or marked `NOT_TESTED` with a reason. Never silently dropped (G8).
- **I8 — No unapproved substitution.** The envelope is derived only from the pinned file, whose sha256 is asserted at
  test time. Any mismatch fails before any sim runs.

### 2.4 Why not the other buckets

Buckets B–D cannot define an injection envelope without inventing fabrication: Bucket B has sizes and counts but no
fabric mapping (and its byte totals are MoE-collective-shaped, already represented by W-E if a 5×5 or full-size path is
approved); Bucket C has media packet sizes with no addresses (and its own `evidence_boundary` string says no
endpoints/packetization/timing are claimed — quoting it verbatim in any report is mandatory); Bucket D is compute-stage
or WAN-link analysis. Using any of them as "RTL workload stimulus" would be authoring a new workload and calling it
pinned — exactly what the selection rule forbids. They remain legitimate **context** (e.g. Bucket B slowdowns
1.014–1.52 bound the urgency of EP dispatch classes; Bucket D bounds stage-time hypotheses) and must be cited as such.

---

## 3. Minimal viable sequence

### M0 — Prerequisites (nothing here runs without these)

1. Approval gate green: `tests/test_release_workload_approval.py` (4 tests: pinned Mixtral revision identity, all 17
   sha256s, debug designs never replace full-size, excluded entry carries a reason). This is G1.
2. **P3 multi-instance finish line** landed far enough for 2-instance agent groups on a mesh debug slice: per-instance
   adapter emission in the composed family builder, shared-router arbitration at the adapter→injection seam, and a
   conformance TB proving every compiled endpoint instance is present and routes (the conformance TB is the success-
   condition counterpart of `test_composed_family_never_drops_agent_instances`, which today asserts refusal).
   Until this lands, M1's composed top does not exist and any L3 run on multi-instance groups is blocked.
3. Credit observability: `SLICE_CREDIT_TAP` (or an integration-level check of I2). Until then M1 may pass G3/G5/G6 but
   G4 records `CREDIT_UNVERIFIED` and M1 is **not** "all-pass".
4. Close (or route around) the two locked-TB defects that envelopes can hit: the post-S24 refused-burst seq-accounting
   gap and the out-of-window SLVERR B-response wedge. Routing around is legitimate for M1 (envelopes target legal
   destinations only and never issue refused bursts) but the gaps stay on the books; closing them is required before M2.
5. `SLICE_MULTI_DEST` (S18/S19/S28) is **not** required for M1 (single destination HBM0) and not required for W-D as a
   retargeted burst-mix stress; it **is** required for W-D with real SSD-proxy destinations (incast/multicast-equivalent),
   and its absence keeps S18/S19/S28 `NOT_RUN` — see M2 and R5.

### M1 — mesh 2×2, 2-instance agent groups, two workloads (the ask)

- **Design:** the locked 2×2 composed slice (4 routers, mesh 2×2, concentrations 1, width 32, `SUPPORTED_VC_COUNTS=2`
  → VC0 bandwidth / VC1 latency-critical, `SUPPORTED_BUF_DEPTHS` default as per the slice default) **with 2-instance
  agent groups** per the P3 finish line: e.g. compute_tile group = 2 instances (initiator seat ≙ rank r and rank r+1),
  plus the HBM0 destination group (1 instance — the debug design's single legal destination). This is the smallest
  configuration that exercises per-instance adapter emission and the adapter→injection seam arbitration.
  An equivalent formulation: 2×2 mesh, 2 initiator groups × 2 instances = 4 injectors folded onto initiator seats 0/1
  per the fold map (§2.2.4). Either formulation is acceptable; the envelope and gates are identical.
- **Workloads:** W-A (gr00t-vla-robotics-v4) and W-B (pi0-thor-modeled-v4). Rationale: both are pinned, both are
  byte-exact envelopes, together they cover 196,608/150,528/262,144/65,536/20,480/800/128 B payloads, one binding
  latency_critical class (control_out), one binding bandwidth-floor class (camera_ingest), and no collectives — so M1
  qualifies the injection/conservation/credit/reset machinery without conflating it with collective semantics.
  `gr00t-n16-h100-measured` (W-C) is the drop-in third case; it adds no new class and is optional for M1.
- **Epochs:** ≥ 2 consecutive envelope epochs separated by reset, fixed seeds (1/7/42, matching the TB's seed set).
- **Sizing (32-bit datapath, 16-beat adapter cap):** W-A ≈ 540,800 B / 64 B per burst ≈ 8,450 bursts; W-B ≈
  1,202,304 B / 64 B ≈ 18,800 bursts (its 800 B payloads split 12×16 + 1×8 beats). At untimed Verilator this is
  minutes, not days; the TB is the same shape as S15–S27 (thousands of transactions, counters, drain asserts).
- **Gates G1–G9 (Appendix C) — all must pass, or the verdict says exactly which did not.** In particular:
  - G3 conservation per VC/class/epoch (I1) — asserted on per-class counters, not just aggregate `dbg_inj/dbg_ej`.
  - G4 credit capacity (I2) — PASS only with the credit tap; otherwise `CREDIT_UNVERIFIED` and M1 is not all-pass.
  - G5 reset epochs (I3): epoch 2 reproduces epoch 1; zero counter leakage across the boundary.
  - G6 ordering (I4): zero `order_violation`; per-initiator-per-class in-order seq completion; HEAD/BODY/TAIL atomicity;
    control_out observed on VC1 with its ceiling recorded (≤ 1,000,000 cycles — a loose ceiling; pass barring wedges,
    and the report records the actual number, never rounds it to a claim).
  - G7 burst legality (I5); G8 requirement observability (W-A: both bindings, observed values recorded; W-B: none —
    report states "no binding requirements in source", not silence); G9 machine-readable report emitted.
- **All-pass definition for M1:** G1, G2, G3, G5, G6, G7, G8, G9 = PASS; G4 = PASS (requires M0.3) or explicitly
  `CREDIT_UNVERIFIED` with M1 downgraded to "conservation/ordering/reset pass; credit NOT verified". No other outcome
  may be reported as M1 done.
- **What M1 proves / does not prove:** proves the composed multi-instance top carries the two pinned VLA envelopes
  through the fabric with conservation, credit, reset and ordering invariants intact across two epochs. Proves **nothing**
  about GR00T/π0 inference performance, QoS beyond the observed ceiling, or any other family/topology.

### M2 — mesh-4×4 (16 routers), width 32/64/128, VC 1/2/4, multi-clock (approved debug design)

Same envelopes W-A/W-B/W-C replayed at 64 and 128-bit datapaths and at VC ∈ {1,2,4}; envelope byte totals unchanged
(beat math scales). VC=1 collapses class isolation (report says so). Multi-clock per the approval's debug-design row.
Add **W-D (switch-gen6-class)** here — the only approved workload that fits mesh-4×4 exactly:
- fold (authored): ranks 0–7 → the 8 initiator-side seats; ranks 8–15 → SSD-proxy seats; on the single-destination
  slice constraint this means W-D runs **only after** `SLICE_MULTI_DEST` lands (or with all flows retargeted to HBM0,
  which changes nothing byte-wise but reduces W-D to a burst-mix stress — if so, say exactly that, never "incast/
  multicast qualified").
- `incast_ssd0` (2 flows, latency_critical ≤ 10,000,000 cycles) and `multicast_equiv` (8 duplicate-unicast flows) are
  exercised only in the SLICE_MULTI_DEST configuration.
- 70/30 read/write byte ratio is preserved by construction; the report records observed per-class byte counts as a
  consistency check — it is **not** a performance gate.

### M3 — family routing-law regression: torus-3×3 and ring-16 (approved debug designs)

W-A/W-B envelopes replayed to exercise wrap/seam/escape paths (the approval's stated purpose for these slices:
"wrap, seam and escape checks"). Escape-path coverage (I4/O3) becomes claimable here if a sink-hold augmentation is
included. Optionally **W-F (llama31-8b-tp4-collectives)** as collective-class envelopes on ring-16 with 4 active seats
(fold authored, labeled authored): 65 × 1,048,576 B (prefill) + 8255 × 8,192 B (decode) + 128 × 64,128 B (gather,
dtype assumed per source — the assumption string is carried verbatim). This qualifies small-payload collective-shaped
streams; it is **not** "Llama-3.1-8B ran on the ring".

### M4 — full-size acceptance (not one of the 17 captures; the approval's full_size_acceptance)

Mixtral revision `p-fd7e5e31be77-r02` (74 agents / 81 routers / 8 VCs / 128-bit links / 162 shared wires,
GEC-MECS `DOR_GEC_MECS`, deadlock-free CDG PASS at certificate level; declared workload moe-8x7b, TP8/EP8/DP1,
requirements: `tp_collective` latency_critical ≤ 100,000 cycles binding; `ep_dispatch` bandwidth ≥ 25 GB/s
non-binding). Important: the revision pin carries **no** `traffic_profiles` and **no** payload byte counts — the
certificate obligations prove topology/routes/VCs/deadlock, not traffic shape. An M4 envelope must be enumerated
from the compiled bundle's workload contract if it carries one, or fixed by the operator; it must **not** borrow the
qwen3-moe 4096/2048 B numbers by substitution. Until that enumeration is pinned, M4 is undefined and stays blocked.
L3 here means: the revision's declared collective-class streams (once enumerated) replayed through the composed GEC-MECS
top with the same I1–I8 invariants at 8 VCs. **Requires: P3 multi-instance exact on the full-size contract + all 13
L2 binding guards + a composed top that today refuses to emit (74 agents, >1 instance per group) + a pinned M4
envelope.** This is the L3 row for MILESTONE-14. The 17 pinned captures are not inputs to M4 — the Mixtral case is
governed by its own revision pin.

### M5 — explicitly out of scope

L4 physical (route/DRC/signoff), L5 release eligibility (`final_implementation` stays `false`), qwen3-moe-tp2-ep4-16tiles
as a runnable design (needs a 5×5 composed mesh with 22 seats — **not an approved debug design**; see §6 decisions),
any timing/performance/calibration claim, any use of the excluded Mixtral trace.

### Sequencing summary

```
M0 (approval gate + P3 multi-instance + credit tap + TB gap plan)
 └─ M1 mesh-2×2 (2-instance groups)  W-A, W-B      ← the ask; all-pass gates
     └─ M2 mesh-4×4 (32/64/128, VC 1/2/4, multi-clock)  W-A/B/C (+W-D with SLICE_MULTI_DEST)
         └─ M3 torus-3×3 / ring-16                W-A/B (+W-F optional)
             └─ M4 full-size Mixtral r02          revision-pin declared workload (not the 17)
```

---

## 4. CI/test artifact and evidence pinning

### 4.1 Test artifact (proposal — do not implement under this document's constraint)

New file (future execution PR only): `tracks/t3-topology/dse/tests/test_workload_rtl_qualification.py`.
Conventions copied from `test_project_top_slice.py` and `test_release_workload_approval.py`:

- Module-scope `ROOT = Path(__file__).resolve().parents[4]`; load the pin; **assert every workload's sha256 before any
  fixture builds anything** (import or replicate the four approval tests' assertions; do not weaken them).
- `pytest.skip("verilator not installed; cannot lint/sim the composed top")` when Verilator is absent — a skip is
  reported as NOT_RUN, and the workload-matrix CI job must treat NOT_RUN as not-qualified (fail-closed), never green.
- Pure-function envelope builder `derive_envelope(source: dict) -> Envelope` with `derivation_id =
  "VERITX_L3_ENVELOPE_V1"`; unit-tested against the pinned files (byte totals, flit counts, class lists — all asserted
  against literal constants so any drift in the source files fails loudly).
- Parametrized cases: `(design, workload, seed)` × M1/M2/M3 rows; M4 behind a separate opt-in marker
  (`@pytest.mark.full_size`) requiring the P3/L2 prerequisites and an explicit env flag.
- Gate assertions map 1:1 to `report.json` keys (G1–G9); the report is written into the pytest tmp dir and the test
  fails if any gate is red or missing. A `NOT_TESTED` entry (G8) is only legal with a reason string.
- The test does **not** auto-pin anything into `docs/product/evidence/`. Evidence pinning is a separate, explicit,
  human-reviewed step (4.2), mirroring how the Mixtral revision was pinned (deliberate copies + sha256, not CI side effects).

### 4.2 Evidence to pin into `docs/product/evidence/` after the run

Target directory: `docs/product/evidence/l3-workload-qualification-<YYYYMMDD>/` where `<YYYYMMDD>` is the **actual run
date** (never backdated; if the run is on 2026-11-10, use that; a later re-run gets a new directory).

| Artifact | Producer | Purpose |
|---|---|---|
| `REPORT.md` | executing session | Verdicts per (design × workload × seed); gate table; `CREDIT_UNVERIFIED`/`NOT_RUN` register; reproduction commands; honest scope sentence (§5 wording) |
| `MANIFEST.json` | executing session | sha256 of every file in the directory + the pin's sha256 + approval-contract sha256; self-check script runs in the pinning PR |
| `envelopes/<id>-envelope.json` | envelope builder | Derivation id, source path + sha256, fold map (authored), per-class bytes/packets/VC/epoch count, seed list — derived data, labeled as such |
| Per case: `<design>-<workload>-<seed>/project-top-manifest.json` (+ `project-top.zip` sha256) | `run_rtl_slice` / `run_composed_family` | Emitted top identity: `slice_sha256`/`archive_sha256`, `development_milestone: true`, `final_implementation: false` |
| Per case: `logs/verilator-lint.log`, `logs/verilator-build.log`, `logs/verilator-sim.log` | same | `--lint-only -Wall -Wno-fatal` result, build output tail, sim log with the S-series-style PASS lines and per-class conservation counters |
| Per case: `report.json` | test artifact | Machine-readable gates G1–G9 (verdicts + observed counters: injected/ejected/outstanding per VC/class, credit-tap readings if present, epoch-2-vs-epoch-1 digest, order violations = 0, requirement observations) |
| `release-workloads-20261110.json` (verbatim copy or hash reference) | pin | Self-containment of the evidence bundle; canonical copy remains at its original path |
| `environment.md` | executing session | Verilator/iverilog versions, git SHA, **dirty-tree state disclosed**, host, date |

After pinning, the **only** documents updated in the same PR are: the L3 row/cell in `MILESTONE-14-PRODUCTION-RTL-20261110.md`
(✗ → qualified/partial with evidence path), the L3 paragraph in `P2-P3-EVIDENCE-20261110.md` (append, never rewrite history),
and the L3 line in `INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md` / `REMAINING-WORK.md` (mark done with evidence pointer).
`final_implementation` stays `false` everywhere; L4/L5 are untouched.

### 4.3 What CI looks like after this lands

`dse` pytest lane runs `test_workload_rtl_qualification.py` alongside the existing RTL sim tests (all
verilator-gated). A dedicated slow job (or nightly) runs M2/M3; M1 runs in the default lane. The matrix fails if:
approval hash drift; any gate red; any `NOT_RUN` in the M1 set; any evidence pin missing from MANIFEST.json.

---

## 5. What is NOT possible from the pinned data — and how RFCs must speak

### 5.1 Hard impossibilities (with the pin's own words as evidence)

1. **No exact cycle traces exist.** No entry contains NoC-cycle-level events, flit times, credit returns, VC occupancy
   or reset epochs. The pin's `limits` fields say so per entry ("measured host capture; not an end-to-end application
   runtime"; "modeled request; no fabricated measured score"; "public capture; not a topology-specific measurement";
   "paper_reported_inference_collective_counts_and_payload_shapes"; "Dataset-derived source ledger only… No endpoints,
   packetization, network timing, or hardware performance are claimed"; "Analytical…"; "This is a transcription of
   paper-reported collective counts and payloads, not an inspected raw trace").
2. **No calibration is possible.** NoC latency/throughput of any composed top cannot be calibrated against the 17
   entries: the captures describe GPUs/hosts/WAN links/model stages, not the fabric; the requests are authored fabrics
   with at best model-derived stage times; there is no shared clock or cycle domain to calibrate against.
3. **No playback fidelity.** Any "replay" is injection of byte-exact envelopes at invented (constant) rates with an
   authored fold. The word *replay* may be used only qualified ("envelope-constrained injection"), never for timing.
4. **No semantic collectives.** allreduce/alltoall counts replay as payload-class streams; algorithm, rank schedule,
   and inter-op gaps are absent (llama31's own `simulation_boundary` field). Qwen3's EP/TP classes likewise.
5. **No per-link attribution.** nvlink counter samples are aggregate panel counters (and their printed units are
   anomalous as published); they cannot bind to a link of any composed top.
6. **No packet-size distributions for NoC.** h264 demux sizes describe a video stream; lerobot/vla-perf payloads are
   model tensors/images; using them as NoC packet-size distributions would be fabrication.
7. **Requirements are loose ceilings, not performance targets.** control_out ≤ 1,000,000 cycles and friends are orders
   of magnitude above any plausible NoC latency; meeting them demonstrates liveness, never competitiveness. RFCs must
   not present ceiling compliance as a performance result.

### 5.2 Mandated RFC/report wording

Allowed:
- "Traffic-class envelopes **derived from** `<pin id>` (sha256 `<sha>`) were injected into `<design>`; conservation,
  credit-capacity (or: credit accounting NOT VERIFIED — `SLICE_CREDIT_TAP` missing), reset-epoch and ordering
  invariants held in seeds 1/7/42 across 2 epochs."
- "No hardware-measured latency, throughput, or application-runtime claim is made or possible from the pinned data."
- "This qualifies the composed-top mechanism, not the workload's real hardware behavior."
- Verbatim `limits` strings carried next to every citation of a pinned entry (e.g. gr00t-g1's `evidence_boundary`).

Banned (any occurrence blocks the RFC/release):
- "the pinned workloads were **measured/validated/calibrated** on RTL"; "the capture **passes through** the fabric";
  "**cycle-accurate** replay of …"; "**end-to-end performance** of … on the fabric"; "requirement **met at** N cycles"
  (report the observed value; the ceiling is trivially loose); "**production-qualified**" before L4/L5; using
  `run_*`-output hashes or `final_implementation: true` anywhere in L3 text; citing the excluded Mixtral trace.

Consequence: every L3 artifact is labeled `development_milestone`, `final_implementation: false`; RFCs may claim
**mechanism qualification under pinned-derived envelopes** and **nothing else**.

### 5.3 What would close the gap (and is not in the pin)

A placed-and-routed design with on-fabric instrumentation (P9), or an operator-approved real NoC trace capture
(does not exist in this checkout), or approval of a *model* projection (BookSim/ASTRA-Sim) explicitly labeled a model —
the last is already legitimate for analysis and must keep its label. Until then, L3 language is fixed as in §5.2.

---

## 6. Risks and decisions needed from the operator

| # | Item | Needed from |
|---|---|---|
| R1 | P3 multi-instance per-instance adapters + seam arbitration do not exist; composed top refuses 2-instance groups today | Engineering (P3 finish line); blocks M1 entirely |
| R2 | `SLICE_CREDIT_TAP` (and ideally `SLICE_CREDIT_DELAY`) missing; I2 only partially observable | Engineering (P8/P4); without it no all-pass M1, ever |
| R3 | Post-S24 refused-burst seq-accounting gap + out-of-window SLVERR B-response wedge | Engineering; M1 routes around, M2 requires closure |
| R4 | qwen3-moe-tp2-ep4-16tiles fits **no** approved debug design (needs 5×5, 22 seats) | Operator: either approve a 5×5 debug-design addition (approval-contract amendment — selection rule currently pins only 2×2/4×4/torus-3×3/ring-16) or accept M4/full-stack path for it; until then it stays W-E-on-paper |
| R5 | `SLICE_MULTI_DEST` for W-D incast/multicast-equivalent and S18/S19/S28 | Engineering (P8); without it W-D is burst-mix stress only, and S18/19/28 stay NOT_RUN |
| R6 | llama31 W-F folding onto ring-16/4×4 with 4 active seats (authored fold; gather dtype assumed upstream) | Operator sign-off that collective-class envelope on a debug design is acceptable for M3 |
| R7 | Evidence-date honesty: REPORT.md must carry the true run date; a stale dir cannot be passed off as fresh | Executing session discipline; reviewer checks `environment.md` |
| R8 | nvlink-counter unit anomaly (`nvlink_GBps` ~1e-7 as published): pin as-is, never "correct" it | None — rule, not a task |
| R9 | M1's "two workloads" choice (W-A/W-B) — gr00t-n16-h100-measured is the drop-in alternative if the operator prefers the measured-H100 entry over the Thor-model-card entry | Operator preference only; neither changes any gate |

## 7. Execution checklist for the implementing session

1. Re-verify G1 at HEAD (all 17 hashes + approval contract). If any mismatch: stop, report, do not proceed.
2. Land/verify M0.2 (P3 multi-instance, 2-instance groups on the 2×2 mesh) with its conformance TB (success-condition
   twin of `test_composed_family_never_drops_agent_instances`).
3. Land/verify M0.3 (credit tap) or accept and record `CREDIT_UNVERIFIED`.
4. Implement `test_workload_rtl_qualification.py` (§4.1) with the W-A/W-B envelopes hard-coded from the pinned files
   (byte totals asserted literally), seeds 1/7/42, two epochs.
5. Run M1; collect G1–G9 into `report.json`; any red gate → fix → re-run (verify-and-stop, not scope creep).
6. Pin evidence per §4.2 (new dated directory; MANIFEST.json; environment.md with dirty-tree disclosure).
7. Update only the L3 cells named in §4.2's last paragraph, in the same PR.
8. Report: verdict per gate, `NOT_RUN` register, and the §5.2-compliant one-paragraph summary. Nothing else is claimed.

---

## Appendix A — The pin, verified (sha256, checked 2026-11-10 at this tree state)

Approval contract: `docs/product/evidence/release-workloads-20261110.json` — v1, approved 2026-11-10, selection rule
quoted in §0; full_size_acceptance = Mixtral `p-fd7e5e31be77-r02` (sha256:ab7bce8f…, 74/81/8/162; evidence in
`docs/product/evidence/mixtral-74-81-8-162/`); debug designs: mesh-2×2 (4 routers, 2 initiators, 1 destination —
transaction/ordering/backpressure/conservation/burst regression), mesh-4×4 (16 routers, width 32/64/128, VC 1/2/4,
multi-clock), torus-3×3 and ring-16 (routing-law regression).

| id | kind | sha256 (verified OK) |
|---|---|---|
| gr00t-n16-h100-measured | request | 18eeaed2d18ea857b7db5b353f1301b6abd390ee90c2fb13bda3c5c38506654f |
| gr00t-vla-robotics | request | bb7cc4078689d5433f79be0c5626e0b09b12a4b69bf17ee3e300de57640ac7f6 |
| qwen3-moe-tp2-ep4-16tiles | request | f7df8bc5a210cd2b63d844ab3d955ea21450a61e7a541e80bac8621f7f24ec05 |
| pi0-thor-modeled | request | 4d15960793ecbd85c97d51f6ad557c04335ef56bde7b61c1eab0951787dbdf70 |
| switch-gen6-class | request | c2e7658187f6a48457ee3c6a05c69090dfaea13ae821437591451250cd3a92fd |
| cal26-qwen3-30b-ep4-kernel-slowdowns | capture | cf34869fb9cc26364c1821c35e30f2510d7120994fc84c4c9ffabb8126975960 |
| cal26-qwen3-30b-ep4-nvlink-counters | capture | be275dec0c90b98c68a73e147dce2d1fad467254abd75ec5a62b3bb3030b7810 |
| llama31-8b-tp4-collectives | capture | 761dc54d764c360dcadccbc80c8a8c7624b1addeb140008bb177fc498446cef0 |
| gr00t-g1-apple-to-plate-events | capture | 0e4001d4554ae9d0519b336e5bdf2085b571ce5a6f4039c66daa7c2b4c7d8a96 |
| lerobot-smolvla-trace | capture | 5d91310c6fd84de191bb33ef7ca4cccf1b06d232033dd9733d88804af60052fa |
| lerobot-smolvla-vla-trace | capture | eea4d4f59fbe6d63d3a508df2b31059c611ac790e0f88b50227f2b48de444a94 |
| lerobot-act-pusht-trace | capture | eb3f58a144796079b7d49f9613f816819b5935a3c9b64a81399bdee71bafb7ed |
| vla-perf-network-latency-kvcache | capture | 8c90e5c478235943b980d2b524b7250d1ed66f7c8a577e56b6807be2cca40a8f |
| vla-perf-network-latency-images | capture | 96ac194c1627de6541f342ad01d0e4379ecb4d18b2c5c25b0978b3588cafbf74 |
| vla-perf-validation | capture | f807142651a81bea49b7fbb06fcf0fd3d6a9549b4fe9252b3dc02c6a6128f2d9 |
| vla-perf-pi0-denoising | capture | 6addcecbbd4b88303fdede36ded833b4d0aaa8472c7b12c10ceb4ec2d6cdfb63 |
| vla-perf-pi0-family | capture | 68e70df3ca4c7f1b8a5cb62acaa6e4d9f1b85a48c2ab1cd47b823561e2286206 |

Excluded (not used, path absent): `…/mixtral-8x7b-64tiles_n64.trace`.

## Appendix B — Byte/flit totals used above (256-bit link = 32 B flit)

| Envelope | Classes (flows × bytes) | Total bytes | Flits |
|---|---|---|---|
| W-A gr00t-vla-robotics | camera_ingest 1×196,608; vision_tokens 4×65,536; action_tokens 4×20,480; control_out 1×128 | 540,800 | 16,900 |
| W-C gr00t-n16-h100 | as W-A minus control_out | 540,672 | 16,896 |
| W-B pi0-thor-modeled | camera_ingest 1×150,528; vision_tokens 4×262,144; action_latents 4×800 | 1,202,304 | 37,572 |
| W-D switch-gen6-class | read_256k 56×262,144; read_4k 56×4,096; write_256k 24×262,144; write_4k 24×4,096; incast_ssd0 2×262,144; multicast_equiv 8×65,536 | 22,347,776 (read 14,909,440 = exactly 70.0 %, verified) | 698,368 |
| W-E qwen3-moe (collectives only) | allreduce 4096 B ×(96-layer cadence); alltoall 2048 B ×2 ×(96-layer cadence) | per-layer 8,192 B collectives | 128 + 2×64 per layer |
| W-F llama31-8b-tp4 | 65×1,048,576 prefill AR; 8255×8,192 decode AR; 128×64,128 gather | 143,990,784 | 4,499,712 |

All envelopes divisible at 32/16/8 B flit widths (checked programmatically). 64/128-bit datapaths only halve/quarter the
beat counts; byte totals and class tags are identical.

## Appendix C — Gate definitions

| Gate | Assertion | Source of truth |
|---|---|---|
| G1 | Pin sha256 match for every entry used; approval contract intact | `test_release_workload_approval.py` logic |
| G2 | Emitted composed top parses; Verilator `--lint-only -Wall -Wno-fatal` clean (zero LATCH/MODDUP/SELRANGE); hierarchy present (project_top, u_noc); log pinned | TB build step |
| G3 | Per VC/class/epoch: inj == ej + outstanding; outstanding == 0 at drain | extended S23-style counters, per class |
| G4 | Per (port, VC): free credits + queued + in-flight == BUF_DEPTH; delayed returns honored; no cross-VC alias | **requires `SLICE_CREDIT_TAP`**; else `CREDIT_UNVERIFIED` |
| G5 | Two epochs; post-reset counters == 0; epoch 2 eject digest == epoch 1; no locks/esc state leakage | I3 + pre-S7 counter checks |
| G6 | Zero `order_violation`; per-initiator-per-class seq in-order completion; HEAD/BODY/TAIL atomicity; control_out on VC1 (2-VC config), ceiling recorded | I4 + existing TB order FSMs |
| G7 | All injected bursts ≤ adapter cap; zero SLVERR/DECERR acceptance; address decode legal (HBM0) | I5 + decoder behavior |
| G8 | Every binding requirement exercised+observed (value recorded) or `NOT_TESTED`+reason; W-A: control_out ceiling, camera_ingest floor; W-B: explicit "none in source" | I7 |
| G9 | `report.json` emitted with all gates; test fails on any red/missing; pin step (§4.2) completeness (MANIFEST sha256 closure) | §4.1–4.2 |

## Appendix D — References (all in-repo)

- Pin & full-size pins: `docs/product/evidence/release-workloads-20261110.json`,
  `docs/product/evidence/mixtral-74-81-8-162/{revision-p-fd7e5e31be77-r02.json,topology-p-fd7e5e31be77-r02.json}`
- L3 definition & milestone table: `docs/product/MILESTONE-14-PRODUCTION-RTL-20261110.md`
- Plan/status: `docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md` (§P3–P5), `docs/product/INTENT-TO-PLACED-RTL-P0-P1-STATUS.md`,
  `docs/product/P2-P3-EVIDENCE-20261110.md`, `docs/product/REMAINING-WORK.md` (items 5, 20), `docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md`
- Locked TB & composed builder: `tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py` (S1–S28; `SUPPORTED_VC_COUNTS=(1,2,4)`,
  `SUPPORTED_BUF_DEPTHS=(4,8,16)`; `composed_family_params_from_request` refusal)
- Test conventions: `tracks/t3-topology/dse/tests/test_project_top_slice.py`, `tests/test_release_workload_approval.py`,
  `tests/test_acceptance_qwen_fullstack.py` (gateway-acceptance sibling, not RTL)
- Workload data: `tracks/t3-topology/examples/*-v4.json`, `tracks/t3-topology/data/{public-inference,public-robotics,lerobot,vla-perf}/…` (+ adjacent READMEs/SMOLVLA*.md, `LICENSE-vla-perf`)
- Calibration honesty pattern: `docs/product/calibration.md`, `docs/product/P2-P3-EVIDENCE-20261110.md` (P2.5: no hardware-coupled
  timing evidence exists anywhere in this repo)
