# Srota — closing the unimplemented features with the trace-replay methodology

Plan of record for the four features listed as *Not implemented* in
[`SROTA-EVALUATION.md`](SROTA-EVALUATION.md) §6.1 and
[`SROTA.md`](../../../third_party/booksim2/src/SROTA.md), executed on the
trace-replay traffic manager validated in
[`MR12-TRACE-VALIDATION.md`](MR12-TRACE-VALIDATION.md).

Written 2026-09-09, after `feat/srota-noc` was rebased onto `origin/main`
(`4be11e48`), which is the first tree where the Srota model and the trace
traffic manager coexist.

---

## 0. Why trace replay is the unlock, not just a nicer harness

The four gaps are not four unrelated features. Every one of them is a
**contention-regime claim** — it produces no number at all on an uncongested
fabric — and the statistical injector cannot express what any of them needs.

**1. Statistical injection carries no per-packet attributes.** M3 needs a
2-bit slack class per packet (PKT-008 §8.2), the STC level needs a batch
epoch tag, the golden level needs a golden window id. `traffic = matrix(f)`
plus `injection_rate` emits anonymous packets drawn from a distribution.
There is no place to put a slack class. The trace schema already carries
per-packet columns and is the natural home for three more.

**2. Saturation is where these features live, and rate sweeps measure it
badly.** BookSim's steady-state latency stats count only packets that
completed. SROTA-EVALUATION §3.1 had to exclude `cmesh16` from the MoE table
for exactly this reason — an unstable arm reads *lower* than a slower stable
one. A finite trace has a fixed, conserved population: every packet is
counted or the run is declared incomplete. That is what makes a
near-saturation comparison legitimate, and near-saturation is the only place
an arbiter, a side buffer, or a rate regulator does anything.

**3. The honest ruler matters precisely at the tails.** MR12 §5 showed
`arrival − trace_timestamp` and BookSim's `atime − ctime` diverge by up to
400× at ρ≈1.0, because the `_qtime` slot freezes while a source's injection
buffer is non-empty. An arbiter claim *is* a tail claim. Measuring it with a
ruler that is wrong in the tail would produce a number that looks like an
arbiter result and is actually a queueing artifact.

**4. Time structure is the thing being shaped.** A rate regulator shapes
bursts; a matrix has no bursts, only a stationary mean. `gen_trace.py`'s
`matrix` mode says so in its own docstring — it treats cells as relative
volume weights and spreads them uniformly. That is fine for a topology
comparison and useless for a regulator.

### What is *not* claimed here

The vanilla `plat_stats` path MR12 deliberately left untouched is **correct
for stationary synthetic injection**. The ruler bug is specific to finite
trace replay. So the existing Srota rate-sweep tables in SROTA-EVALUATION §2
are not retroactively wrong. The near-saturation rows are unsound for the
separate, older reason in point 2 above, which trace replay also fixes.

---

## Phase 0 — Merge hygiene and the trace-mode bring-up

Status: Phase 0 **done**, Phase 1 items 1.1 and 1.2 **done**, Phase 2a
**done** — results in [SROTA-M3-ARBITER.md](SROTA-M3-ARBITER.md).
Items 1.3 and 1.4 land with Phase 4, which is what needs them.

**0.1 `METADATA.json` was malformed (done).** The rebase concatenated the
MR12 `local_modifications` entries and the Srota entries without a separator,
leaving the file invalid JSON at line 25. The tool registry parses that file,
so `make tool-build TOOL=booksim2` failed with `unknown tool 'booksim2'`.
One missing comma; fixed.

**0.2 The merged tree builds (done).** `BUILD OK`.

**0.3 Srota's own checks still pass (done).** `srota_validate.py`: 19/19,
including the full F1/RT-R7 matrix, both TP-V2 cases, and the §14.3 config
validity refusals. The rebase did not disturb the model.

**0.4 Srota runs under `sim_type=trace` (done).** A 471-event 16-node probe
replayed end to end: 471 packets injected, 471 rows in the packet log,
p50/p95/p99 = 21/22/25, per-packet hops recorded. No code change was needed.
The trace destination override in `_GeneratePacket` lands *before* flit
creation, so Srota's FIU sees the true trace destination and its flow-hash
over (src, dest, class) keys correctly. This was the main integration risk
and it is retired.

**0.5 Two rulers, one physics on Srota** (MR12 §7 item 2). Feed the same
events through the CSV path and the veritx 5-column path; percentiles must
be bit-identical, as they were for mesh. Srota is the first topology with an
injection-time adaptive layer, so this is a real test, not a formality: the
FIU's epoch cache is keyed on flow identity and both injectors must produce
the same flow keys.

**0.6 Determinism.** Multiple seeds, bit-identical output. Srota adds two RNG
consumers the mesh path does not have — Valiant intermediate selection and
the epoch cache — so record `--seed` and confirm.

**0.7 Commit the bring-up.** A checked-in `srota_trace.config` and a
`workload16.yaml`, so the above is reproducible rather than a scratchpad
artifact.

---

## Phase 1 — Trace generation for the workloads Srota is designed around

**1.1 `moe_traffic.py --emit-trace`.** Today it emits a `matrix(file)`. Add a
packet-level emitter with real phase structure — dispatch, compute, combine —
rather than round-tripping through a matrix and re-sampling. The matrix path
destroys exactly the time structure Phases 2, 4 and 5 need to measure.
Keep the existing matrix output; this is an added mode, so the
SROTA-EVALUATION §2 tables stay reproducible.

**1.2 Schema extension: `slack`, `batch`, `golden_id`.** Optional trailing
columns, defaulted when absent, so every existing CSV keeps working.
Field widths follow PKT-008 §8.2: slack 2 bits (0 = critical, 1 = low-slack,
2 = bulk, 3 = background), batch 4 bits, golden_id sized by the golden epoch.

**1.3 Multicast rows.** A row whose destination is a group rather than a
single node. Needed by Phase 4 and by nothing else, so it can land with it.

**1.4 A broadcast workload that stays multicast.** `moe_traffic.py` currently
folds weight broadcast into per-destination unicast weights in the matrix.
That pre-flattening is exactly what makes the ~16× claim unmeasurable — the
saving being claimed is the difference between one channel transaction and N
unicasts, and flattening throws away the numerator.

---

## Phase 2 — The three-level arbiter (claim M3)

ROUTE-001 §16.4 names three ingredients for M3, and they map one-to-one onto
work items here.

### 2a. Allocator-only — answers M3 as specified

**Packet fields.** `Flit::pri` is a single int and already spoken for.
Add `slack`, `batch`, `golden_id` as distinct fields and plumb them
`TraceEvent → _GeneratePacket → Flit`. Prefer new fields over reusing
BookSim's traffic class: class carries VC-range and per-class-statistics side
effects that would confound the measurement.

**The allocator.** A `SrotaArbAllocator` registered as `srota_arb` in
`Allocator::NewAllocator`, implementing ROUTE-001 §11.2's cascade literally:

```
elig = req_vec & credit_avail & ~out_busy_mask
m0   = |(elig & golden_match) ? (elig & golden_match) : elig
m1   = m0 & (slack == min_over(m0, slack))
m2   = m1 & (batch == min_over(m1, batch))
gnt  = rr_select(m2, rr_ptr)
```

The `m0` fallback is a correctness requirement, not an optimisation: applied
unconditionally the golden mask would grant nobody in a cycle with no
golden-window request, idling the fabric on a schedule rather than on demand.
It deserves a directed test of its own.

**Config surface.** `srota_arb_l0_golden`, `srota_arb_l1_slack`,
`srota_arb_l2_stc` as enable masks, plus golden epoch length and batch
epoch length, matching the §13 register names the way the existing twelve
`srota_*` keys already do.

**The M3 experiment.** One trace, three arms: `islip` (the RR baseline),
`age` priority (the age baseline), and `srota_arb`. Report per-slack-class
p50/p95/p99. The claim is about critical-class latency, so the headline
number is class 0's tail against both baselines, with total throughput
alongside to show what it cost.

**Known departure to document up front.** BookSim's IQRouter drives one flat
allocator. TOPO-003 §7.3's two coupled 6-port stages, and the
`out_busy_mask` handshake rev 0.3 added as RT-R9, cannot be expressed
against it. Phase 2a therefore models the three *levels* exactly and the
two-*stage* coupling not at all. That is a real limit on quoting M3 against
the RTL, and it is what 2b exists to remove.

### 2b. The coupling — merged into Phase 3

`out_busy_mask` is router state, not allocator state, so it needs the custom
router below. Doing 2b and Phase 3 as one vehicle is less total work than
two separate patches against `IQRouter`.

---

## Phase 3 — Side buffer and staging latch (VC-R1)

A `SrotaRouterD : public Router`, alongside the existing `IQRouter`,
`EventRouter` and `ChaosRouter` subclasses. VC-002 §2.1–§2.3:

- 2-flit staging latch per input — a pipeline requirement, not a queue; not
  addressable as a VC, carries no VC id, cannot hold a flit indefinitely.
- One shared 8-flit side buffer per router, entered **only** by allocation
  losers, so it never sits on the common-case critical path.
- `srota_sidebuf_arb` to pick which buffered flit re-competes; each buffered
  flit carries its own port tag (VC-002 §11.2).
- Backpressure by credit withholding to the offending input's staging latch
  when the side buffer fills (§6.4) — graceful, bounded, not a fault.
- `VC_SIDEBUF_WATERMARK` defaulting to 6 of 8.

**What this unlocks beyond VC-R1 itself.** The watermark raises a
fabric-wide congestion hint on Plane T. Srota already models Plane T and the
injection-time overlay reads it. Today that loop is open — telemetry samples
router occupancy, but nothing raises the side-buffer hint, because there is
no side buffer. Closing it changes what the overlay sees, which means the
§4.5.3 / RT-R7 policy comparison and the M1 finding in SROTA.md §3 are both
measured against an incomplete telemetry signal until this lands.

**VC-R1 itself** is then a capacity sweep over side-buffer depth 4–16 flits
on a fixed trace, reporting the point where occupancy stops inflating and
the watermark stops firing spuriously — VC-002 §6 is explicit that a false
congestion hint is worse than none, because Plane T feeds the runtime layer.

This is the largest single item in the plan and it subsumes 2b.

---

## Phase 4 — Multicast over MECS (the ~16× broadcast claim)

`Flit::mcast` and `mcast_copies` already exist, added by the veritx_embed
work; `srota_o1turn` routes unicast only.

- Route a multicast as **one channel transaction** with per-drop accept
  filters, which is what makes a multidrop channel a broadcast medium
  (TOPO-003 §3.2, §9.3).
- Credit is an AND-reduction over the selected drops (§9.2): a channel
  transaction cannot be partially delivered, so **one congested drop blocks
  the whole broadcast**. That cost is the honest half of the claim and must
  be reported next to the saving.
- Counters `TOPO_CNT_MCAST_TXN`, `TOPO_CNT_MCAST_ACCEPT`,
  `TOPO_CNT_MCAST_BLOCK` (§13.5). Realised fan-out is
  `MCAST_ACCEPT / CH_TXN`, which §13.5 states is the direct measurement of
  the §14 claim — so the claim is read off a counter ratio, not inferred.
- Baseline arm: the identical broadcast expressed as N unicasts on the
  identical fabric and trace. The ratio between the arms is the claim; the
  16 in "~16×" is the full-fanout case at k=16, so a 4×4 probe fabric can at
  best show 4× and must not be quoted as a refutation.

---

## Phase 5 — Island rate regulators

Currently islands affect placement checking only. Add the `srota_island_wrap`
token-bucket regulator (TOPO-003 §7.5) driven by `ISL_RATE_CFG`, with the
counter for transactions deferred.

This turns the existing static I-ISL finding into a measured one. SROTA.md
already reports that row-first structurally violates I-ISL — 7,200 of 8,160
routes at the reference configuration pass through **two** island routers.
§4.1.2 says the consequence is that the composed rate is the product of the
two bounds rather than the intended bound, and that bandwidth is lost with
no error indication. With regulators modelled, that lost bandwidth becomes a
number, and the proposed rule — island-bound traffic must use column-first —
becomes a measurable A/B rather than an argument.

---

## Phase 6 — The SROTA-EVALUATION §8 items trace mode also serves

1. **A 1024-node comparison set** — matching `cmesh`, `flatfly` and `mesh`
   configs at k=16, c=4. The only size where MECS reach is exercised; §2.1
   showed a 16-node sweep cannot distinguish Srota from `flatfly16` even in
   principle.
2. **The N+1 node-count mismatch** — the spatial pipeline emits 73×73 while
   every config is 16, 64 or 72. Fold the DRAM node onto a tile, add a
   `--nodes N` mode, or add an `anynet` config that reads the graph.
3. **A real Accelergy technology model** — until then energy is
   `hops × 5 × 5.4` and carries no information the hop column does not.
4. **Retire or differentiate `ftree`**, which is byte-identical to
   `fattree16` and double-weights the fat tree in any cross-arm average; and
   correct `qtree16` / `tree4`, both of which are 64 nodes.

---

## Phase 7 — The trust harness

Encode MR12 §7's five checks as a script that every Srota result must pass
before it is quoted: conservation, two rulers, physical bounds, determinism,
ruler awareness. The value is that it turns the methodology from a document
into a gate.

---

## Decision points

| Decision | Recommendation |
|---|---|
| Slack as a new `Flit` field, or reuse the traffic class? | New field. Class carries VC-range and per-class-stats side effects that would confound M3. |
| Arbiter as allocator only, or wait for the custom router? | Allocator first. It answers M3 exactly as §16.4 words it, and the coupling departure is documentable. |
| Custom router now or later? | It gates VC-R1, the Plane-T hint loop, and the arbiter coupling. Largest item, highest fan-out. |
| Spec handling | The `SSM-UARCH-*` documents stay untracked and local. Section numbers and paraphrase in tracked docs, as `SROTA.md` already does. Nothing spec-derived gets published to an external service. |

## Suggested order

Phase 0 remainder → 1.1 and 1.2 → 2a (closes M3) → 3 (closes VC-R1 and the
telemetry loop) → 4 → 5, with Phase 6 items taken opportunistically and
Phase 7 landing alongside Phase 0.
