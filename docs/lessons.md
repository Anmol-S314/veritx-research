# VeritX — Lessons Learned

**Status: living document, self-pruning.** The active section contains only
lessons still OPEN. When a fix lands, the entry is moved to the Archive
(dated, with the fix named). If the same mistake recurs, the archived entry
is revived with a "RECURRED" mark and must get a harder fix this time.

**Prune rules (apply on every edit):**
1. An entry stays in ACTIVE only while its fix is NOT in place.
2. When the fix ships, move the entry to ARCHIVE with `resolved:` + date + mechanism.
3. A convention becomes a code check → the lesson is archived and the convention row marks itself `scripted`/`automated`.
4. A recurring incident (archive entry revived) is written in bold at the top of ACTIVE — repeated failure gets a structural fix, not a reminder.

---

## ACTIVE

### L1: Canonical config must come from one source of truth
The generated cells hardcoded a fixed injection rate `{0.008, 0.005}` for
all bursts instead of the canonical constant-flit-load grid
`(5,0.016),(10,0.008),(20,0.004),(40,0.002),(80,0.001)` from `rtl_r1.py
GRID`. 12 of 15 cells were wrong; only b10 was correct by accident.
- **Lesson:** any experiment that claims to reproduce a paper's numbers
  must read the config from the same place the paper's numbers came from.
- **Fix:** config-lint in `rtl_r1.py` (`lint` subcommand; runs inside
  gen-trace — a cell.cfg whose DMA rate isn't canonical for its burst
  size, or whose control rate isn't 0.005, aborts the run). Verified
  against all 15 regenerated cells.
- **resolved: 2026-08-12 (rtl_r1.py lint_cell in gen-trace + `lint` subcommand).**

### L2: Know the schema of each dump before writing comparisons
BookSim `flits.txt` uses a **global** packet id; the RTL dump uses a
**per-NIC ordinal**. `compare_latency.py` keyed RTL latency on `pid` alone,
which collided across the 64 NICs and produced fake ~50x divergences.
- **Lesson:** verify field semantics (pid scope, time base, ordering)
  before trusting any diff. One sample line per side is the cheapest check.
- **Fix pending:** pairing `(src, pid)` documented in script headers +
  an assert that sample dumps parse as expected.

### L3: Distrust suspicious exactness; investigate, don't report it
Two bugs produced two false conclusions in one day: "identical means to
0.000000" (wrong grouping) and "50x divergence" (pid collision). Both were
believed until a human asked "is that real?"
- **Lesson:** exact agreement and wild disagreement are both red flags.
  A real result has structure you can point to (histograms, per-class sums,
  packet traces).
- **Fix pending:** every headline number must name its source file; numbers
  without provenance are not reported.

### L4: Per-flit mismatch does not mean mean-level mismatch
b10_vc4 had 28% per-flit atime mismatches (12,429/44,442 flits), yet
class-mean latencies agreed to ~0.1%. Δatime deltas were genuine
(-62..+90) but symmetric (6,253 neg / 6,156 pos), net +0.01 cyc.
- **Lesson:** report residual *distributions*, not means or counts.
  Bounded symmetric residuals cancel; ordinal claims on means are robust.
- **Fix pending:** residual histogram + cancellation check as a standard
  step in the comparison script.

### L5: Capture binary stderr; a crash you can't see is a trap
`run_experiment.sh` ran binaries with `> /dev/null`, so the yday b20_vc1
SIGABRT (exit 134) left only an exit code. (Trace-specific: the regenerated
trace exits 0.)
- **Lesson:** a non-zero exit needs its message, not just its code.
- **Fix pending:** drivers must tee stderr to a per-run log.

### L6: Status markers lie until you read the files
"EXPERIMENT_DONE" appeared in conversation long before it existed in the
log; an early summary asserted a full 15-cell table that did not exist.
- **Lesson:** run status is confirmed by reading marker files, not memory.
- **Fix pending:** none scripted yet — standing convention only.

### L7: Staged artifacts must exist before they're promised
A `fix_cells.sh` was "written and staged" in conversation but did not exist
on disk when we went to run it.
- **Lesson:** verify referenced scripts exist and match current state
  before building on them.
- **Fix pending:** none scripted yet — standing convention only.

### L8: Shared tool-output display corrupts long dumps
The tool's display layer truncated and duplicated stdout for large outputs.
- **Lesson:** analysis output goes to files, then to the report.
- **Fix pending:** none scripted yet — standing convention only.

---

## CONVENTIONS (active rules, with enforcement status)

| # | convention | status |
|---|---|---|
| C1 | Cell configs linted against canonical GRID before runs are trusted | scripted (`rtl_r1.py lint`, in gen-trace) — L1 archived |
| C2 | Cross-model comparisons declare their packet-key schema | manual — OPEN (L2) |
| C3 | Reported numbers cite their source file | manual — OPEN (L3) |
| C4 | Residual analysis reports distributions, not just means | manual — OPEN (L4) |
| C5 | Experiment drivers never swallow stderr | manual — OPEN (L5) |
| C6 | Run status confirmed by reading marker files | manual — OPEN (L6) |
| C7 | Referenced files verified on disk before use | manual — OPEN (L7) |
| C8 | Analysis output written to files, not display | manual — OPEN (L8) |

Status meanings: `manual` = humans must remember; `scripted` = a check
exists; `automated` = impossible to do wrong. When a convention moves from
manual to scripted, its lesson is archived and the row is updated.

---

## ARCHIVE (resolved — kept for history, not for reading)

- `resolved: 2026-08-12 (L1 — config lint shipped in rtl_r1.py gen-trace)` —
  12/15 cells had a fixed wrong injection rate; gen-trace now refuses any
  cell.cfg whose DMA rate isn't the canonical constant-flit-load rate for
  its burst size (and control class must be 0.005).
