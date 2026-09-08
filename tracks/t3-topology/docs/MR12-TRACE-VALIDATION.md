# MR12 Trace Replay — Merge Resolution + Validation Audit

**MR:** shouryadip, "Booksim custom trace simulation extension" + "Config changes for
running traces" (`047703e2`, `6e9bd38a`) → `main`
**Resolution branch:** `resolve/mr12` (staged in `/tmp/mrtest`, scope: merge + validation only)
**Date:** 2026-09-08 · **Validator:** Qwen session (cross-checked against veritx-cli path)

## 1. What the MR adds

CSV-driven trace replay for BookSim2: `tracetrafficmanager.{cpp,hpp}` (new
`sim_type=trace` manager reading `timestamp,src,dst,type,packet_size[,transaction_id]`,
injecting at absolute timestamps, writing per-packet CSV logs), `trace_file` /
`trace_packet_log` config fields, 2 example workload YAMLs, 8 example configs
converted to trace mode, `gen_trace.py` (synthetic CSV generator:
uniform/hotspot/burst/explicit), `visualize_trace.py` (offline plotly report).

Workflow (verified end-to-end, see §6):
```
make tool-build TOOL=booksim2
python tracks/t3-topology/scripts/gen_trace.py third_party/booksim2/src/examples/workload2.yaml third_party/booksim2/src/examples/workload64_trace.csv
make tool-run TOOL=booksim2 ARGS="src/examples/mesh88_lat" [× 8 configs] > booksim_output.txt
python tracks/t3-topology/scripts/visualize_trace.py --run "Name:trace.csv:packets_out.csv" [...] --out report.html --offline
```

## 2. Merge conflicts (2 files) + resolutions

**`trafficmanager.cpp` :: `_GeneratePacket`** — main inserts the VeritX trace-dst
override + self-loop early-return; MR12 inserts `_OnPacketGenerated(...)` hook at the
same anchor. **Resolution: keep both, hook AFTER the VeritX block.** Ordering is
load-bearing, not cosmetic: MR12's override (`tracetrafficmanager.cpp:171`) consumes
`_pending_valid[source]` into `_pid_to_event[pid]` — firing before the early-return
would bookkeep phantom skipped packets. Hook args (`pid, source, cl, time`) are
unaffected by the VeritX edits.

**`mesh88_lat`** — main created it as a transpose/20-flit demo; MR12 rewrote the same
stanzas as a trace demo, and its documented commands address it by name
(`ARGS="src/examples/mesh88_lat"`). **Resolution: MR12's content keeps the name;
main's transpose demo moved to `mesh88_lat_transpose`.** Nothing references the
filename except those commands, so no other updates needed. (All 8 example configs
are intentionally converted to trace mode by this MR; pre-trace latency demos are
recoverable from git history.)

## 3. Extra bugs found during validation (fixed in `resolve/mr12`)

1. **Class-name collision** — MR12's `TraceTrafficPattern`
   (`tracetrafficmanager.hpp:80`) vs VeritX's `veritx_ext.hpp:20`. Each compiles
   alone; merged TU fails with redefinition. Renamed MR12's to
   `TraceFileTrafficPattern` (5 occurrences, all inside its own two files; direct
   `new`, no factory-string or script references). Both TUs `g++ -fsyntax-only` clean.
2. **Inverted exit code (pre-existing on main!)** — `main.cpp: return result ? -1 : 0`
   made EVERY clean run exit 255 (proved via transpose baseline). Fixed to
   `result ? 0 : -1`. Without this, any `set -e` driver aborts despite valid output.
3. **Missing dragonfly input** — `dragonflyconfig` needs 72-node `workload72_trace.csv`
   (72 = DragonFlyNew p=2: a=4, g=9, N=72 — verified against `_ComputeSize`), but the
   documented steps only generate the 64-node file. Added committed
   `examples/workload72.yaml` (`nodes: 72` variant of `workload2.yaml`); CSVs stay
   generated artifacts (reproduced: 630 events).

## 4. Cross-validation: MR12 path vs veritx-cli path (same workload, same fabric)

Method: convert his CSV → veritx `{cyc src cl dst sz}` (self-loops dropped both sides —
see §5.1), run both binaries, compare populations, horizons, distributions.

| Workload | His p50/p95/max | veritx (pre-fix) p50/p95 | Horizon |
|---|---|---|---|
| Synthetic 627pkts mesh8 (variable sizes 8/16/32) | 63 / 293 / 493 | 60 / 403 / 525 | identical |
| Qwen3-serve slice 4000pkts 2×2mesh (real serving-derived) | 77 / 78 / 78 | 31573 / 59923 / — | 64023 = 64023 |
| Qwen mid 3125 / late 12311 | 73/73, 74/78 | 98479 / 29876 | match to cycle |
| Micro-case (2 pkts) | 58.5 avg | 58.5 avg | identical |

Determinism: both sides bit-identical across seeds (his: 0 vs 7065408; ours: 4 seeds).
Seed is NOT a factor (no per-cycle RNG draws on either path). Configs field-matched
(VCs/buffers/delays/classes/speedups verified line-by-line; `dor_mesh` ≡
`dim_order_mesh`, same function pointer).

## 5. The ruler finding (the important one)

**Ejection-equality proof:** all 627 synthetic packets eject at bit-identical cycles
in both implementations (max abs diff 0, joined on source+order); Qwen horizons match
to the cycle on all 3 slices. **Same physics.** The reported-number gap is 100%
measurement baseline:

- His: `arrival − trace_timestamp` (honest; every term post-dates the packet).
- Ours (pre-fix): `atime − head->ctime`, where `ctime` is BookSim's `_qtime` slot —
  which **freezes while a source's injection buffer is non-empty**. At saturation the
  slot predates the packet itself by 10^4 cycles (measured: median lag 31.5K on the
  Qwen slice; per-packet `ours − his == request − ctime` exactly, mean 9.8 = 9.8,
  max 602 = 602 on synthetic).
- This is **vanilla BookSim semantics** (`_include_queuing==1 ? _qtime : _time`,
  untouched by us) — correct for stationary synthetic traffic, wrong for finite
  trace replay. p50 matches when load is light (slots fresh); tails explode with
  saturation (400× on Qwen: 31K vs 78).

**Fix applied (this branch, ~25 lines):** pid→request_time map (`_trace_reqtime`,
same pattern as his `_pid_to_event`): filled at the VeritX consume block in
`_GeneratePacket`, consumed+erased at the `_all_latencies` retire site with fallback
to ctime for non-trace traffic, cleared per `Run()`, self-loop-skip erases its entry.
`plat_stats` deliberately left vanilla (standard path untouched).

**Post-fix convergence (zero-diff acceptance):**
synthetic → ours **58 / 320 / 472** vs his 58 / 320 / 472 (**exact**);
Qwen slice → ours **77 / 78 / 78** vs his 77 / 78 / 78 (**exact**).
His-path regression: bit-identical (63/293 — map only fills via `g_trace_active`).
Interim mitigation (no code): `include_queuing = 0` collapses p95 403→320 but
undercounts honest admission wait by ~2 cycles — bandage only, superseded by this fix.

**Consequence for historical numbers:** every veritx `evaluate booksim` p95/p99 on
saturated bursty traces is inflated (means too, up to 400× at ρ≈1.0); medians/means
on light traffic are fine. Flag for recompute.

## 6. Audit nits (his MR — minor, documented not fixed)

- `gen_trace.py` can emit `src==dst` pairs (3/630 observed) — silently dropped
  post-merge by our self-loop skip; filter at generation or document.
- `injection_rate = 0.2` is dead in trace mode (timestamp-driven; no rate gate in
  `_Inject` for this path) — misleading to readers.
- Default `latency_thres` (500) nearly aborted his own run (max 493 observed);
  recommend `-1.0` as veritx does.
- Author's own `NEEDS TESTING` comments on the pending-handshake hold up under
  single-class use; multi-class use would need `_last_issue_source` keyed by class.
- His `type` column (READ/WRITE) is log-label only; `transaction_id` passthrough only.

## 7. Trust methodology (adopted for all future numbers)

1. Conservation: packets in == out; mean injected size == input mean (catches parse bugs free).
2. Two rulers, one physics: same workload both injectors; horizons + distributions must match.
3. Physical bounds: latency ≥ hops+serialization; completion ≈ span+drain.
4. Determinism: same seed → bit-identical; record `--seed` always.
5. Ruler awareness: after this fix both rulers agree; until binaries are refreshed everywhere, label pre-fix tails suspect.

## 8. Convergence: one injector family, one ruler (follow-up try, validated)

Per discussion, the veritx `traffic=trace()` path was converged onto the
pending-event design instead of extending the globals handshake:

- Pending state moved from manager arrays + `_last_issue_source` into the
  per-class `TraceFileTrafficPattern` object (`SetPending/HasPending/Pending/
  ClearPending`); `dest()` is self-contained, `friend` + `PendingDestination`
  deleted. This also removes both of the author's own `NEEDS TESTING` worries
  (size attribution is structural now, not temporal).
- `_LoadTraceFile` content-sniffs CSV vs veritx 5-col `{cyc src cl dst sz}`
  (comma test on first data line; `#`/`%` comments skipped); `TraceEvent` gains
  a `cl` field. Proven: same events via CSV and via veritx file give
  bit-identical percentiles (63/355/462 both).
- His `_RetireFlit` feeds veritx's `_all_latencies` vector with
  `arrival − request_time`, so `evaluate` reporting works unchanged.
- **Double-count trap found by the differential test:** first attempt pushed in
  both his override and base `_RetireFlit` (p95 417 vs CSV 410). Fix: single
  push site — base `_RetireFlit` reads the shared `_trace_reqtime` map (fed by
  both injectors: veritx path in `_GeneratePacket`, his path in
  `_OnPacketGenerated`); his override only writes CSV. Post-fix: vector == CSV
  exactly on every run (newmatch 57/410/642; Qwen 80/81).
- veritx legacy `traffic=trace()` path untouched and still guarded by the
  differential test; deletion is a separate decision. Serving/ASTRA loop
  untouched (collective-aware driver stays; CSV is packet-level only).

## 9. Files changed (in `resolve/mr12`)

Merge resolutions: `trafficmanager.cpp` (hook order), `mesh88_lat` (his content),
`mesh88_lat_transpose` (new, main's demo), `tracetrafficmanager.{cpp,hpp}` (rename),
`main.cpp` (exit code), `trafficmanager.hpp` (hook decl — auto-merged). Validation
enablers: `workload72.yaml` (new). veritx fix: `veritx_ext.{hpp,cpp}`,
`injection.cpp`, `trafficmanager.{cpp,hpp}` (reqtime map). This doc.
Excluded (regenerable): `*_trace.csv`, `*packets_out.csv`, `report.html`,
`qwen_report.html`, `booksim_output.txt`, build artifacts, `/tmp` scratch.
