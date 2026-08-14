# Laura's RTL Bug-Hunting Playbook

Author: Laura (senior agent). Not part of the numbered handoff series —
a standing reference. Distilled from the 2026-08-13/14 fork-gate session
(12+ bugs found, 6 of them structural, all with clean repros).

---

## 0. The meta-rule

**Never trust a number until you can name the artifact that produced it.**
Every bug in this session was caught by asking "where did this datum come
from, and does it still mean what it claims?" — never by looking at the
code harder.

---

## 1. Process discipline (the ground rules)

1. **One build at a time.** RAM rule: builds need ≥3 GB available or they
   OOM-kill silently (0-byte logs). Two concurrent VCS=8 builds killed both
   this morning. Check `free -g` before launching; never launch on top of a
   live build.
2. **Everything on real disk.** `/tmp` is a RAM-backed tmpfs that gets
   wiped (lost 3 builds + 2 cells). All artifacts in `/var/tmp/r1work/`.
   Logs to `/var/tmp/r1work/`, not `/tmp`.
3. **Commit first (rule 3).** An uncommitted tree = void results. The
   manifest records git SHA; runs on dirty trees don't count. Commit RTL
   edits WITH attribution before building from them.
4. **pgrep self-match trap.** `pgrep -f "pattern"` matches your own command
   line (the pattern string is in argv). Kills your own shell, poll loops
   never terminate. Use `pgrep -x` for exact binary names, or kill by PID.
5. **Launch via tmux or setsid with input redirect**, never bare `&`.
   Shell-tool process-group cleanup kills backgrounded children.
   `setsid bash -c '...' < /dev/null & disown` or `tmux new-session -d`.

## 2. The verification ladder (fastest first)

When a gate/cell/run misbehaves, walk this ladder — each rung discriminates
a whole class of cause:

| Rung | Check | Catches |
|---|---|---|
| 1 | **Is the artifact fresh?** mtime vs the binary/commit. | Stale data misread as result (the 56-line rtl_flits.txt). |
| 2 | **Is the cell what I think?** source/dst distribution, packet count, VC config vs binary. | Misconfigured cells (128-src trace when 4 intended; num_vcs mismatch). |
| 3 | **Does the binary match the source?** git SHA, build log tail, generated .cpp. | Stale binaries (pre-fix build compiled the old RTL). |
| 4 | **Does the config match the model?** num_vcs vs -GVCS, classes, rates. | VC/buffer mismatches → phantom flit loss. |
| 5 | **Format-validate the output.** Field counts, column meanings. | Malformed dump lines (the `7742 0 2` truncated write). |
| 6 | **Separate mechanism from timing.** Are mismatches identity/order (real) or delta-only (envelope)? | Misdiagnosing contention jitter as structural loss. |
| 7 | **Classify, don't aggregate.** Per-src, per-direction, per-hop breakdown. | "All late in trace" when it was uniform across 128 sources. |

## 3. The five signature bugs (how they present, how to catch them)

### S1 — Crossed/self-looped signals (the credit-lane bug)
**Symptom:** hard threshold at exactly buffer size (8 of 22 streams
delivered, then permanent stall). **Catch:** trace the signal's *source*
not its name — a credit-in fed from its own credit-out is a self-loop even
when the comment says "crosses". Verify by drawing the direction: sender's
credit-in must come from the *receiver's* credit-out.

### S2 — Undersized arrays in a parameterized design (the ND*N bug)
**Symptom:** OOB reads return garbage that *happens* to work single-die.
**Catch:** every array indexed by node count must be `[ND*N]`-sized when
the design doubles. Grep all `[N]` declarations and check against every
access loop's bound.

### S3 — Shift/base mismatch between pump and replay (the replay_base bug)
**Symptom:** entries scheduled in the past → nothing ever fires.
**Catch:** compute the base from the *actual* pump duration, not the
single-config constant. Any `N*T_DEPTH`-style constant that doesn't scale
with the config is a suspect.

### S4 — Last-write-wins in an always_ff (the fork-XT collision)
**Symptom:** silent flit loss under contention, zero under single-stream.
**Catch:** two loops writing the same register in one always_ff with a
comment claiming "can never collide" — the comment only excludes the SAME
source, not a *different* (i',v') in the same cycle. Count writers per
register.

### S5 — Preprocessor guard not honored in full elaboration (the R1_DEBUG bug)
**Symptom:** `ifndef` block present in standalone preproc/lint but present
in the full build's generated .cpp. **Catch:** verify the GENERATED code,
not the source or lint. When a guard proves unreliable, **delete the debug
code** — git history preserves it. Don't chase the tool.

## 4. Diagnosis moves that pay off

1. **Run the same command twice, differing by one variable.** Dave's
   "install fails" was stale; my second run succeeded. Isolate by changing
   exactly one thing.
2. **Check the data before the code.** Parse the dumps, count, classify —
   the answer is usually in the distribution (uniform loss = config;
   threshold loss = credit; late loss = drain).
3. **Verify the generated artifact, not the source.** Verilator's .cpp,
   the makefile, the wheel — the bug lives where the source met the tool.
4. **The trace structure IS the test.** A matrix with zero rows produces
   self-send pollution; verify diagonal ≈ 0 and direction counts before
   trusting any loss number.
5. **Name the artifact in every claim.** "168 flits lost" is meaningless;
   "42/2927 cross-die pids missing, both directions, at num_vcs=1 on the
   pre-fix binary" is actionable.

## 5. Environment survival (the boring 80%)

- RAM: `free -g` before builds; 14 GB box, ~5 GB with browser open.
- tmux sessions die with the server; `tmux start-server` revives, but a
  dead server takes builds with it — use `setsid` for long builds.
- The build wall times: 2-die VCS=2 ~11-13 min; VCS=8 ~30-40 min at -j1;
  single-die faster. Add 2x for unknown designs.
- Multiple agents: coordinate builds in GATE-R1-COORD.md BEFORE launching.
  Two seniors + junior = three build queues = OOM. The seed tracker
  (`.seeds/`) is the coordination surface.

## 6. The credibility posture (why this works)

Every bug we found, a reviewer would have found. The gate's job is to be
*more* hostile than the reviewer. When a finding contradicts the paper's
narrative, that's the gate working — record it as a seed with the repro,
fix it, and let the paper change. Never soften a finding to protect a
claim; the placement-law RTL verification and the trace-pipeline
corrections both survived because we let the data correct us.

---

*"Installed ≠ working. Built ≠ correct. Delivered ≠ arrived. Verify the
artifact, name the source, classify the loss, commit the fix."*
