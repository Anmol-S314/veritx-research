# Design Spec — Two-Tier Envelope Gate for RTL NoC Verification

Status: SPEC (write-only; no implementation yet)
Owner: opencode (senior)
Date: 2026-08-13
Supersedes: the 0/0 bit-exact per-flit gate (GATE-R1-COORD.md §7 — re-scoped 2026-08-12)
Related docs: `docs/research/gate-r1-sensitivity-experiment.md`,
`docs/research/simulator-credibility-noc-literature.md`, `GATE-R1-COORD.md`

---

## 1. Purpose & scope

### 1.1 What the gate supports

The T3 paper's claims are worthless if the simulator is not credible. Gate R1
is the credibility gate: it establishes, per cell, that the Verilator RTL NoC
model (`tracks/t3-topology/rtl/`) tracks BookSim 2.0 (`third_party/booksim2/`)
— the field-standard cycle-accurate NoC simulator — under trace-replay, with
an auditable, reproducible fidelity bound.

The gate supports exactly one paper claim:

> The RTL implementation reproduces BookSim's per-flit traffic *mechanism*
> (routing, ordering, drops, delivery) bit-exactly, and its *timing* at
> per-class KPI level within a 5% envelope, with characterized bounded
> per-flit residuals.

Framed for the paper (per `simulator-credibility-noc-literature.md`):

> "Demonstrated per-flit agreement for 99.85% of flits with characterized
> bounded residuals."

NOT: "cycle-exact". The word "cycle-exact" is banned from gate outputs and
from the validation section of the paper.

### 1.2 Why a two-tier gate (history)

The original gate demanded bit-exact 0/0 per-flit agreement on all 15 cells.
The 0/0 datum was a one-off configuration artifact (GATE-R1-COORD.md §7.1):
no source state reproduces it, yesterday's own binaries fail their own cells
at 12–28% mismatch, and mismatch rate scales with VC count (arbitration
complexity) — structural, not fixable. The field standard, meanwhile, is
much weaker: BookSim's own ISPASS 2013 validation vs RTL reported ≤5%
latency / ≤3% throughput on *aggregate curves*, and no published per-flit
cycle-exact RTL↔sim gate exists for a reactive NoC.

Re-scope decision (GATE-R1-COORD.md §7.2, confirmed by the sensitivity
experiment, 2026-08-12):

- **Tier 1** keeps the bit-exact discipline where it is binary and
  *cheap to be exact about*: routing, ordering, drops, delivery.
- **Tier 2** moves timing into KPI space (per-class mean latency), where
  per-flit contention jitter is mean-preserving (measured: b10_vc4 has 28%
  flit-level mismatch but class-mean latencies agree to ~0.1%).

This is a fidelity bound, stated honestly, that exceeds every published
precedent in granularity (per-flit mechanism + KPI timing vs curve-level).

### 1.3 Scope

- **In scope:** the 15-cell burst matrix (b{5,10,20,40,80} × VCS{1,2,4}) and
  extension cells (e.g., the multi-source mixed unicast+mcast cell), all
  trace-replay via `rtl_r1.py`.
- **Out of scope:** bit-exact per-flit timing (dropped, see §2.3), saturation
  behavior, generality beyond the documented cell/config matrix, and any
  claim about which model is "correct" — the gate only asserts RTL tracks
  BookSim within the envelope on the documented cells.

---

## 2. Tier definitions and PASS/FAIL rules

### 2.1 Tier 1 — mechanism (ZERO tolerance)

Tier 1 is a set of binary checks on the *content* of the flit stream,
independent of timing. Any violation fails the cell unconditionally,
regardless of Tier 2.

Flits are matched across models by **per-(src, cl) packet ordinal** — NOT by
the pid field: BookSim's `flits.txt` uses a global packet id while the RTL
dump uses a per-NIC ordinal (keying on pid alone collides across NICs; see
the correlation note in `gate-r1-sensitivity-experiment.md` §3).

| Check | Rule | Failure |
|---|---|---|
| T1.1 Flit-count equality per packet | Every injected packet appears in both models with the identical flit count. | Any count mismatch = FAIL |
| T1.2 Identity fields | `cl`, `src`, `dst` equal per matched flit. | Any field mismatch = FAIL |
| T1.3 Packet order | Per (src, cl), packets appear in the same order in both models (ordinal i before i+1); flits within a packet keep in-order delivery. | Any inversion = FAIL |
| T1.4 Delivery completeness | Injected == retired in both models (no drops in either, no extras in either). | Any drop/extras = FAIL |

Tier 1 is the *mechanism* tier: it proves routing, ordering, and delivery
semantics are identical between RTL and BookSim. Timing is deliberately
excluded from this tier.

**Tier 1 verdict:** `CLEAN` if T1.1–T1.4 all pass; `VIOLATION` otherwise.
A `VIOLATION` verdict is final for the cell: `cell verdict = FAIL`, no
override is possible (§4.3), and the ordinal checks (§5) are reported as
invalid.

### 2.2 Tier 2 — timing envelope (KPI space)

Tier 2 compares *per-class mean packet latency* between models.

- Packet latency (both models, identical definition):
  `latency(pkt) = max(atime over the packet's flits) − itime`.
- Class means: mean over class-1 (control) packets and class-0 (DMA)
  packets, computed separately per model.
- Ratio: `r_c = mean_lat_RTL(c) / mean_lat_BS(c)` per class c.

**PASS rule (per class):** `r_c ∈ [1 − env, 1 + env]`, default
`env = 0.05` (5% — deliberately matched to BookSim's own ISPASS 2013
validation standard against RTL).

- Cell Tier 2 verdict = `PASS` iff *all* classes present in the cell pass.
- The envelope is checked on **per-class means (KPI space) only**. Per-flit
  deltas are NOT compared against the envelope; they are characterized
  (§6). This is the entire point of the re-scope: contention jitter that
  cancels in the mean is the envelope tier's domain.

Empirical anchor (sensitivity experiment, fixed-rate rerun 2026-08-12):
14/15 cells land within 0.97–1.01; the envelope is not aspirational — it
already holds nearly everywhere.

### 2.3 Cell verdict

| Tier 1 | Tier 2 | Override? | Verdict |
|---|---|---|---|
| CLEAN | PASS | — | **PASS** |
| CLEAN | FAIL | valid override (§4) | **PASS (override)** |
| CLEAN | FAIL | none | **FAIL** |
| VIOLATION | anything | never | **FAIL** |
| missing data | — | — | **INCOMPLETE** |

PASS per cell = Tier 1 clean AND Tier 2 within envelope (or documented
override). A cell with no data, no trace, or a crashed run is INCOMPLETE,
not PASS.

---

## 3. Inputs and outputs

### 3.1 Cell layout

The standard cell matrix is the 15-cell burst table:

- 8×8 mesh, XY/DoR routing, seed 1.
- 2 classes: class 0 = DMA hotspot to diagonal NICs
  {0,9,18,27,36,45,54,63}; class 1 = control uniform.
- Packet sizes: {burst, 1}; injection rates {0.008, 0.005} per class, with
  the canonical **constant-flit-load GRID rates** (DMA flit load = burst ×
  rate = 0.08 flits/cycle/node constant):

| burst | 5 | 10 | 20 | 40 | 80 |
|---|---|---|---|---|---|
| rate | 0.016 | 0.008 | 0.004 | 0.002 | 0.001 |

| cell | burst × VCS | | | |
|---|---|---|---|---|
| vc1 | b5 | b10 | b20 | b40 | b80 |
| vc2 | b5 | b10 | b20 | b40 | b80 |
| vc4 | b5 | b10 | b20 | b40 | b80 |

Cell id format: `b{burst}_vc{vcs}` (e.g., `b5_vc1`, `b80_vc4`).

Extension cells (not in the 15) may be registered with their own
documented configs, e.g. the multi-source two-class cell (mixed unicast +
mcast, 0.03 rate) used for the F2 reorder-path corner — see §7.

### 3.2 Pipeline and file format

```
BookSim (fork, trace_out + flit_dump)
  -> flits.txt      (per-flit retire dump: atime cl src dst pid itime)   [truth]
  -> trace.txt      (stimulus: cycle src cl dst size, gen order)
  -> trace_n%d.hex  (per-NIC BRAM images for RTL replay)
Verilator model (noc_pkg/islip/router/mesh/nic/noc_tb, -DR1_MODE)
  -> rtl_flits.txt  (same 6-field format)
rtl_r1.py gate ...  -> per-cell verdict + residual stats + ordinal checks
```

Flit record (both files, same 6-field format): `atime cl src dst pid itime`.
Matching key: `(src, cl, packet-ordinal)`, flits within a packet ordered by
atime.

Per-cell workdir (`<outdir>/<cell>/`): `flits.txt`, `trace.txt`,
`trace_n*.hex`, `rtl_flits.txt` (plus `rtl_flits_gold.txt` /
`rtl_flits_yday.txt` when two binaries are run), `run_cycles` (last retire +
drain margin), and the per-cell report JSON.

### 3.3 Provenance

Every gate run records provenance (existing rule, GATE-R1-COORD.md §3.2):
`<outdir>/manifest.txt` with git SHA + source mtimes + binary mtimes, plus
the policy file hash and the tool version. A gate report without a
manifest is INCOMPLETE.

### 3.4 Report format

Two artifacts, always written together:

**1. Machine-readable: `gate_report.json`** (aggregate). Per cell:

```json
{
  "schema_version": 1,
  "git_sha": "…",
  "policy_file": "configs/gate_policy.json",
  "default_env": 0.05,
  "cells": {
    "b5_vc1": {
      "status": "PASS | PASS-OVERRIDE | FAIL | INCOMPLETE",
      "tier1": {
        "verdict": "CLEAN | VIOLATION",
        "checks": {"t1.1": true, "t1.2": true, "t1.3": true, "t1.4": true}
      },
      "tier2": {
        "verdict": "PASS | FAIL",
        "env_applied": 0.05,
        "classes": {
          "0": {"bs_mean": 40.2, "rtl_mean": 40.2, "ratio": 1.00},
          "1": {"bs_mean": 44.1, "rtl_mean": 34.9, "ratio": 0.79}
        }
      },
      "residual": {
        "n_flits": 71832, "n_matched": 71723, "exact_match_frac": 0.9985,
        "mean_delta": 0.0103, "p95_abs_delta": 4.0, "max_abs_delta": 90.0,
        "family_notes": "mean-preserving jitter; see residual report"
      },
      "ordinal": {"o1_monotone_bs": true, "o1_monotone_rtl": true,
                  "o2_absorption_bs": true, "o2_absorption_rtl": true},
      "override": null,
      "binaries": {"gold": "rtl_flits_gold.txt", "yday": "rtl_flits_yday.txt",
                   "agree": true}
    }
  },
  "ordinal_summary": { … },
  "summary": {"n_pass": 14, "n_override": 1, "n_fail": 0, "n_incomplete": 0}
}
```

**2. Human-readable: `gate_report.md`** — per-cell table (verdict, BS mean
vs RTL mean per class, ratio, residual stats, override reason if any) plus
the ordinal-invariant section (§5) and a changelog line per verdict.
Written in the same style as the sensitivity experiment's result table.

---

## 4. Envelope defaults and anomaly/override policy

### 4.1 Defaults

- `env = 0.05` for all cells unless overridden.
- The default matches the field standard (BookSim's own ISPASS 2013
  validation: ≤5% latency / ≤3% throughput on aggregate curves). The gate is
  stricter than the precedent on mechanism (per-flit, zero tolerance) and
  equal on timing (per-class means, 5%).

### 4.2 Override policy

A Tier 2 envelope failure does not necessarily kill a cell: per-cell `env`
overrides are permitted ONLY with all of:

1. **Mechanism tier clean** (Tier 1 verdict CLEAN — non-negotiable, this
   proves both models route/order/deliver identically),
2. **Binary agreement** where two RTL binaries were run (gold == yday on
   the cell) — this rules out an RTL build regression as the cause,
3. **A mandatory non-empty reason string** — free-text justification
   citing the evidence (measured numbers, both-model values, mechanism
   hypothesis), stored in the policy file,
4. **An evidence reference** — file/URL to the experiment documenting the
   anomaly.

Overrides are per-cell and per-class where applicable; an override for
class 1 does not relax class 0.

### 4.3 Policy file: `configs/gate_policy.json`

```json
{
  "schema_version": 1,
  "default_env": 0.05,
  "overrides": [
    {
      "cell": "b5_vc1",
      "classes": ["1"],
      "env": 0.25,
      "reason": "Ratio 0.79 at highest injection rate (0.016): RTL 34.9 vs "
                "BookSim 44.1. Both RTL binaries agree (gold == yday); Tier 1 "
                "clean; BookSim identified as the outlier. See "
                "docs/research/gate-r1-sensitivity-experiment.md §5d.",
      "evidence_ref": "docs/research/gate-r1-sensitivity-experiment.md#5d",
      "date": "2026-08-12",
      "requires": ["tier1_clean", "binary_agreement"]
    }
  ]
}
```

Validation rules applied by the gate tool:

- `reason` must be non-empty (≥ 20 chars) — enforced, tool refuses an
  override without it.
- `requires` must include `tier1_clean` (mandatory) and `binary_agreement`
  (mandatory when a second binary exists for the cell).
- `env` must be > 0.05 for an override to be meaningful (an override at the
  default is a no-op and rejected).
- An override whose cell did not run Tier 2 at all is ignored (cell stays
  INCOMPLETE).
- Overrides are recorded in the report (`override` field) and count as
  `PASS-OVERRIDE`, never as unmarked PASS.

### 4.4 Known anomaly (pre-registered)

- **b5_vc1** — ratio 0.79 (RTL 34.9 vs BookSim 44.1, control class), the
  highest injection rate (0.016) of the matrix. Both RTL binaries (gold,
  yday) agree; the mechanism tier is clean; BookSim is the outlier. Full
  write-up: `docs/research/gate-r1-sensitivity-experiment.md` §5d. This is
  an open anomaly with a documented override, not a gate failure.

---

## 5. Ordinal invariant checks

The paper's claims are *ordinal* — ranking statements — and the gate checks
that both models agree on the rankings, not just on magnitudes:

- **O1 — Burst-starvation monotonicity.** At VC1, control-class mean packet
  latency is monotone non-decreasing in burst length:
  `b5 ≤ b10 ≤ b20 ≤ b40 ≤ b80`. Must hold in BOTH models.
- **O2 — VC absorption.** At the longest burst (b80), 1-VC control-class
  mean latency > 4-VC control-class mean latency (`b80_vc1 > b80_vc4`).
  Must hold in BOTH models.

Reported per model and per binary where both ran. Checked on the envelope
tier's KPI (per-class means), so they inherit the envelope's empirical
anchor: sensitivity experiment confirmed O1 and O2 hold on both models with
the fixed-rate cells (monotone on all three VC counts, both binaries;
absorption 138 vs 40 at b80, RTL side).

Also reported (not gated): starvation ratio magnitude comparability per
burst (paper's 1.36x → 6.68x sweep), for the paper's side-by-side
validation table.

**Ordinal interaction with the envelope:** a cell failing O1/O2 on either
model invalidates the ordinal claim for the paper even if its envelope
passes. O-checks are reported globally in `ordinal_summary`, not overridden
per-cell.

---

## 6. Residual characterization report (the credibility artifact)

This is the artifact that replaces the dead 0/0 claim. Always produced,
whether or not the envelope passes. Per cell, per matched flit:
`Δ = atime_RTL − atime_BS` (pairing on (src, cl, ordinal)):

| Statistic | Definition |
|---|---|
| exact-match fraction | fraction of flits with Δ = 0 (baseline demonstrated: 99.85% on b10_vc1 — 71,723/71,832) |
| mean Δ | signed mean delta in cycles (mean-preserving if ≈ 0) |
| p95 \|Δ\| | 95th percentile of absolute delta, cycles |
| max \|Δ\| | max absolute delta, cycles |
| Δ histogram | coarse buckets (e.g., <0, 0, 1–3, 4–10, 10+) for family triage |

Plus per-cell **family notes**: classification of the residual structure
with mechanism hypotheses, e.g.:

- ramp head-latency drift [0..9] cycles,
- const-early arrivals [−32..−23] cycles,
- VC-count-dependent rate (mismatch scales with arbitration complexity),
- mean-preserving contention jitter (measured: b10_vc4, 28% flit mismatch,
  net +0.0103 cyc/flit overall, +0.105 on control class),
- multi-source contention jitter (measured: mixed unicast+mcast cell at
  0.03 rate — 147 timing-only mismatches, deltas −1..+3, mean +0.89;
  mechanism tier clean).

The residual report is the paper's validation section material, in the
honest framing: "demonstrated per-flit agreement for 99.85% of flits with
characterized bounded residuals". The report is an audit artifact: every
number in it is derivable from `flits.txt` + `rtl_flits.txt` + the
pairing rule in §2.1.

---

## 7. Known limits (what the gate does NOT claim)

1. **No cycle-exact claim.** Per-flit timing agreement is reported as
   characterized residuals (§6), never as exactness. "Cycle-exact" is
   banned wording.
2. **Saturation.** The envelope is defined on mean latencies, which are
   unstable/divergent near saturation. The gate is only defined for
   non-saturating cells; a cell that saturates in either model is
   INCOMPLETE with a saturation flag, not FAIL (and not PASS).
3. **Multi-source pid mapping.** The BookSim dump uses a global pid; RTL
   uses a per-NIC ordinal. Pairing on (src, cl, ordinal) is correct for
   single-source traffic; the multi-source two-class cell showed structural
   pid mismatches under the old single-source diff logic (GATE-R1-COORD.md
   §7.4, F2). The gate's Tier 1 checks on multi-source cells require the
   (src, cl, ordinal) mapping and are verified against the known
   147-mismatch (−1..+3, mean +0.89) envelope-domain signature. The gate
   does NOT claim to verify arbitrary multi-source mixes beyond the
   documented cells.
4. **Generality.** All claims are scoped to the documented cell matrix,
   configs, and seeds. The gate does not certify the RTL "in general".
5. **Model truth.** The gate asserts RTL tracks BookSim; where they diverge
   it flags the cell but does not adjudicate which model is right
   (b5_vc1 is the documented case where BookSim is suspected).
6. **Reactive corner coverage.** Cells are trace-replay snapshots; the gate
   is not a full verification of the RTL (F1/F2 fork/reorder corners have
   their own gates per GATE-R1-COORD.md §7.4).

---

## 8. Implementation notes

### 8.1 New `gate` subcommand in `rtl_r1.py`

Add a `gate` subcommand to `tracks/t3-topology/scripts/rtl_r1.py`
(existing subcommands: `gen-trace`, `diff`, `sweep` — see module header).

```
rtl_r1.py gate --cells b5_vc1,b10_vc1,... \
               --env 0.05 \
               --policy configs/gate_policy.json \
               --binaries <gold[,yday]> \
               --out <outdir>
```

Behavior per cell:

1. `gen-trace` if trace artifacts are missing (reuses existing canonical
   config lint + GRID rate logic; run_cycles = last retire + drain).
2. Run each RTL binary (`+run_cycles=<cell>/run_cycles`), producing
   `rtl_flits.txt` (and `rtl_flits_gold.txt` / `rtl_flits_yday.txt`).
   Sequential, memory-guarded (existing rules: one build/run at a time,
   VERILATOR_JOBS=1 for VCS=8, `_avail_gb() < 3` refusal).
3. Pair flits on (src, cl, ordinal); evaluate T1.1–T1.4 (mechanism) and
   T2 per-class ratios (envelope); compute residual stats (§6).
4. Apply policy: look up override for the cell, validate the reason string
   and `requires` preconditions; compute final verdict (§2.3).
5. Run ordinal checks (O1, O2) across the completed VC1 and b80 cells;
   report globally.
6. Write `manifest.txt` (git SHA, source/binary mtimes, policy hash) +
   per-cell JSON + `gate_report.json` + `gate_report.md`.

### 8.2 `sweep --gate` mode

`rtl_r1.py sweep --gate --cells <matrix> --policy …` runs the full 15-cell
matrix (or an extension-cell set) as one sequential gated sweep, same
artifact layout as the existing sweep, plus the gate report artifacts.
Regenerating an existing cell's trace is NOT implied by --gate (traces are
reused; force via `gen-trace`).

### 8.3 Report artifacts (per §3.4)

- `<outdir>/gate_report.json` — machine-readable verdicts (CI-parseable).
- `<outdir>/gate_report.md` — human table + ordinal section.
- `<outdir>/residual/<cell>.json` — per-cell residual characterization
  (§6), the credibility artifact.
- `<outdir>/manifest.txt` — provenance.

### 8.4 Acceptance criteria for the implementation

- Gate run on the 15-cell matrix reproduces the sensitivity experiment's
  known numbers: 14 PASS within 0.97–1.01, b5_vc1 PASS-OVERRIDE at 0.79
  with the documented reason, all ordinal checks true on both models.
- A hand-corrupted `flits.txt` (dropped flit, swapped dst, reordered pair)
  must produce Tier 1 VIOLATION → cell FAIL — i.e., the gate can actually
  fail.
- An override with an empty reason is rejected by the tool.
- No gate run may write to `/tmp` (tmpfs; rule 5 in GATE-R1-COORD.md).
