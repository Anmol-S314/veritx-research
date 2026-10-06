# Track SPEC — Simulation utilization overlay (derived + measured)

Status: SPEC (not started). UI implementation belongs to the Studio
owner; this document defines the DSE-side artifacts, the API contract,
and acceptance. No Studio files are touched by this track.

Mission anchor: the utilization-overlay Simulation view (mesh grid +
link coloring, telemetry cards, top-N congested links, selected-link
panel, latency-breakdown bar, cycle scrubber, trace-source
attribution). Every number carries its source label; derived and
measured render side by side with a source toggle.

## Non-goals

- No new simulator. No alternate BookSim. One fork, extended.
- No per-cycle animation beyond sampled snapshots (see Phase 2 for why
  exact per-cycle replay is refused).
- No physical numbers (LEVEL 0+ physical is the OpenROAD track).
- No Studio implementation in this track (contract only, §5 below).

## Phase 0 — Counter-availability spike (half day, read-only)

Confirm in the vendored fork + `channel_measurements.py` reader which
of these exist as real counters versus derivable quantities:

1. Per-channel flit counts — KNOWN (T6 `channel_activity`, typed).
2. Stall cycles per channel — VERIFY against fork stats output.
3. Arbitration-wait vs active-Tx split — VERIFY; if BookSim exposes only
   aggregate wait, the breakdown bar renders two segments (wait / Tx)
   with the third EXPLICITLY absent, never interpolated.

Spike output: a note in this file (append §6) recording
AVAILABLE / DERIVABLE / ABSENT per counter, with the exact stat names.
ABSENT counters stay absent in every phase below.

## Phase 1 — Fork: sampled snapshots (1–2 days)

Extend the T6 hook with periodic counter dumps:

- `sample_period_cycles`: authorable, default recorded in artifact.
- Output: `channel_timeseries` — per-channel flit counts per window
  (+ stall samples iff Phase 0 says AVAILABLE).
- Conservation test (mandatory, mirrors T6): sum over windows equals
  the cumulative counter exactly. A windowed series that disagrees with
  its own totals is refused, not rescaled.
- Sampling is lossy by declaration: windows are aggregates, not
  replayable traces. The scrubber scrubs window aggregates. Any UI copy
  claiming "cycle-accurate replay" is a spec violation.

New tests: conservation, empty-run refusal (zero windows → typed
refusal, not an empty chart), period-mismatch refusal (artifact period
≠ requested period → refuse, never resample silently).

## Phase 2 — Backend: typed series artifact (2–3 days)

New reader beside
`tracks/t3-topology/dse/veritx_dse/backend/channel_measurements.py`:

```text
ChannelLoadSeriesArtifact
{
  schema_version,          # 1
  run_hash,                # input design + config hash (reproducibility)
  sample_period_cycles,
  num_windows,
  capacity_formula,        # "flits_per_window / (window_cycles * link_capacity_flits_per_cycle)"
  link_capacity_flits_per_cycle,  # from width/flit-size, stated not measured
  channels: [
    { logical_channel_id, flits_per_window: [...], stalls_per_window: [...] | null }
  ],
  provenance: { backend, version, binary_hash, input_hashes }
}
```

Utilization % is DEFINED by `capacity_formula`, displayed with it.
Stall series is `null` (not zeros) when Phase 0 says ABSENT.

## Phase 3 — Product API contract (1 day, DSE side)

Extend the loom API surface (gateway, beside capabilities/provenance):

- `GET /api/v1/loom/simulation/load?run=<hash>&source=derived|measured`
  → per-channel utilization table (top-N sortable server-side).
- `GET /api/v1/loom/simulation/series?run=<hash>`
  → `ChannelLoadSeriesArtifact` (measured only; derived has no time
  axis — requesting `source=derived` here returns typed refusal
  `NO_TIME_AXIS`, not a flat line).
- `GET /api/v1/loom/simulation/link?run=<hash>&channel=<id>`
  → selected-link detail (util, flits, stalls|null, breakdown|null).

Refusal vocabulary (fail closed, same pattern as the rest of Loom):
`NO_RUN` (unknown hash), `NO_MEASURED` (run predates counters),
`NO_TIME_AXIS`, `PERIOD_MISMATCH`, `STALE_FIXTURE` (never serve
fixture bytes on the live path — T9 rule applies unchanged).

## Phase 4 — Studio contract (owner's lane; specified here, built there)

The Studio owner implements against §3 only. Conformance checklist:

- [ ] Source toggle Derived | Measured on every load-colored element.
- [ ] Every number shows its source label; capacity formula visible.
- [ ] Absent data renders as an explicit gap panel (named refusal),
      never as zero/placeholder.
- [ ] Scrubber labeled "window aggregates, N-cycle windows", not
      "cycle-accurate replay".
- [ ] Trace-source attribution from provenance (digest + coverage),
      not free text.

## Acceptance

- Phase 0 note recorded (§6 below); no Phase 1 work on ABSENT counters.
- Conservation test green; all four refusals tested with fixtures.
- Product-gates green; full DSE suite green; Studio tsc+vitest green
  on the combined tree.
- Demo: 8×8 mesh run → overlay with both sources, top-5 table,
  selected-link panel, scrubber — against a recorded `run_hash`
  reproducible from the committed inputs.

## §6 — Spike findings (append, do not pre-fill)

(record AVAILABLE / DERIVABLE / ABSENT with stat names)
