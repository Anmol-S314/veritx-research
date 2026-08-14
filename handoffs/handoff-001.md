# Handoff 001 — Fork-gate session state (2026-08-13 late evening)

Numbered handoff series. Next file: handoff-002.md. Each file = one session's
end-state; reference this file's sections by number in follow-ups.

---

## 1. Where the work stands (one paragraph)

The T3 topology track's KV-multicast arc is **complete and verified through the
standard gate pipeline** on committed trees: bridge-fork mechanism (g-fold law),
placement law (35-cycle penalty = die height), and the RTL fork gate
(g ∈ {4,8,16} + 2-die on/off-axis, all ZERO mismatches at tol=0). F1 (fork-copy
XT collision) and F2 (reorder-path mcast deadlock) are **fixed and committed**
(edec5c1, 4f951e1). The two-tier gate subcommand (T3-002) is **implemented and
validated on the fork cells**; the 15-cell acceptance run is blocked on
regenerating stale (Aug-12) RTL dumps with the current RTL. One build is in
flight (vc4/VCS=8).

## 2. Environment rules (non-negotiable, from GATE-R1-COORD.md)

- **RAM:** 14 GB box, ~5 GB free with browser open. ONE build at a time.
- **Workspace:** ALL builds/cells/artifacts under `/var/tmp/r1work/fork_gate/`
  (real disk). NEVER `/tmp` — RAM-backed tmpfs, gets wiped (lost 3 builds +
  2 cells already). GATE-R1-COORD.md rule 5.
- **Launch builds:** `setsid bash -c '...' < /dev/null & disown` — survives
  shell cleanup. Do NOT use plain `&` in the shell tool.
- **pgrep self-match trap:** `pgrep -f "pattern"` matches your own shell.
  Use `ls <binary>` or `pgrep -x <name>` for completion checks.
- **RTL edits: COMMIT FIRST** (rule 3). Uncommitted tree = results void.
  Commit convention: `fix(t3-rtl): ...` / `docs(t3-rtl): ...`.

## 3. Verified state (committed, artifact-backed — do NOT re-verify)

| Cell | Binary | Result | Commit |
|---|---|---|---|
| g=4 mesh | b_1die | 66/66 ZERO mismatches tol=0 | edec5c1 |
| g=8 mesh | b_1die | 154/154 ZERO mismatches | edec5c1 |
| g=16 (16×8 mesh) | gate16 | 330/330 ZERO mismatches | edec5c1 |
| 2-die on-axis (BRIDGE_ROW=0) | b_2die_on | 154/154 ZERO, first copy T52 | edec5c1 (tree) |
| 2-die off-axis (BRIDGE_ROW=7) | b_2die_off | 154/154 ZERO, first copy T87, +35 penalty | edec5c1 (tree) |
| Two-class cell (mcast+unicast) | b_1die | F2 deadlock FIXED: 928 injected, 2824 ejected exact | 4f951e1 |
| Two-class diff (fa99a9b fix) | — | 147 timing-only mismatches, Δ≤+3, mean +0.89 | fa99a9b |

Cells: `/var/tmp/r1work/fork_gate/cells/{gf_8,gf_bridge_on,gf_bridge_off,gf_2cls}/`
Binaries: `/var/tmp/r1work/fork_gate/builds/{b_1die,b_2die_on,b_2die_off,b_vc2}/`

## 4. In-flight: T3-002 two-tier gate implementation

**Status: code DONE, validated on gf_8 + gf_2cls. 15-cell acceptance pending.**

- Spec: `docs/research/two-tier-gate-spec.md` (472 lines — READ IT).
- Implementation: `tracks/t3-topology/scripts/rtl_r1.py` — `gate` subcommand,
  `_load_policy`, `_pair_packets` (pairing on (src, cl, pid), spec §2.1),
  `gate_cell` (Tier 1: T1.1-T1.4 zero-tolerance; Tier 2: per-class mean
  latency ratio, env 0.05), residual stats, `gate` driver + O1/O2 ordinal
  checks + reports (gate_report.json/.md).
- Policy: `tracks/t3-topology/configs/gate_policy.json` (b5_vc1 override
  env 0.25 — **may need removal**, see §6).
- **Validated:** `gf_8` → PASS (T1 CLEAN, T2 ratio 1.0, 100% exact).
  `gf_2cls` → PASS (T1 CLEAN, T2 cl0 1.003 / cl1 1.0, 95% exact, mean Δ
  +0.09, max Δ 4). Syntax + behavior verified.
- **NOT yet committed** (rule 3: commit the gate code + policy next).
- Fixes made during implementation: JSON policy reason-string bug (was
  Python-style string concat); `gate` funcs defined after main (moved main
  to EOF); mcast T1.1 size expectation (1+copies not injected size);
  RTL keying (src,cl,pid) to fix multi-class pid collisions.

## 5. Blocked: 15-cell acceptance run

- Corpus: `/var/tmp/r1work/cells/b{5,10,20,40,80}_vc{1,2,4}/` (15 cells).
- **PROBLEM:** the corpus `rtl_flits.txt` are STALE (Aug-12 RTL, mtime
  11:06). The old RTL dropped packets (b5_vc1: 20,301 flits vs 44,274 fresh).
- Fix: regenerate each cell's rtl_flits with the CURRENT RTL binaries:
  - vc1 cells → `builds/b_1die/Vnoc_tb` (VCS=2? NO — VCS param mapping:
    sweep uses `total_vcs = v*2`, so vc1→GVCS=2, vc2→GVCS=4, vc4→GVCS=8).
    **VERIFY the -GVCS mapping against the cell.cfg `num_vcs` before running.**
  - vc2 → `builds/b_vc2/Vnoc_tb` (GVCS=4) — DONE building (23:12).
  - vc4 → `builds/b_vc4/Vnoc_tb` (GVCS=8) — IN FLIGHT (launched ~23:20).
- Command per cell: `cd <cell> && <binary> +run_cycles=$(cat run_cycles)`
  (overwrites rtl_flits.txt).
- Then: `python3 scripts/rtl_r1.py gate <outdir> <policy> <cell_dirs...>`.

## 6. Key finding: b5_vc1 anomaly RESOLVED

- Spec §4.4 documented b5_vc1 ratio 0.79 (RTL 34.9 vs BookSim 44.1) as an
  open anomaly → override env 0.25.
- **Fresh RTL run: ratio 1.0** (cl0 56.61/56.62, cl1 44.10/44.08), Tier 1
  CLEAN, full delivery 44,274 flits. The current RTL (post-F1/F2) fixed the
  delivery shortfall the anomaly was measuring.
- **Action:** after the 15-cell acceptance, if b5_vc1 passes at default env,
  REMOVE the override from gate_policy.json and update spec §4.4 + the
  sensitivity experiment doc (the 0.79 was stale-RTL data).

## 7. Issue tracker

`.seeds/issues.jsonl` (git-native, JSONL):
- **T3-001** [done] multi-source diff pid correlation (fa99a9b)
- **T3-002** [open, high] two-tier gate — this handoff §4/§5
- **T3-003** [open, med] F8: phantom local-port credit (DBG5 audit noise)
- **T3-004** [open, med] contention experiment (needs T3-002)
- **T3-005** [open, low] seq-512 v4 rerun (FINDINGS caveat)
- **T3-006** [open, low] g-at-fixed-S sweep (placement law confound)
- **veritx-research-889f** [open] F9: DBG3/4/5 dead in TWO_DIE mode
- **veritx-research-e77a** [open] LLM trace pipeline (Chakra lane, other agent)

## 8. Suggested skills for the next session

- `research` — if validating the Chakra/serving lane or any new external claims.
- `diagnosing-bugs` — for the 15-cell acceptance if regenerated cells fail.
- `to-tickets` — to break the contention experiment (T3-004) into child issues.
- `code-review` — before committing the gate code (T3-002), have a fresh
  reviewer pass over `rtl_r1.py` gate changes vs the spec.

## 9. Next actions (in order)

1. Wait for b_vc4 build; verify `ls builds/b_vc4/Vnoc_tb`.
2. VERIFY the -GVCS↔num_vcs mapping on one cell (b5_vc1 used GVCS=2? b_1die
   was built with GVCS=2 — confirm against cell.cfg).
3. Regenerate all 15 cells' rtl_flits with the matching binaries.
4. Run the full gate over the 15 cells; record results.
5. If b5_vc1 passes at env 0.05: remove override from gate_policy.json,
   update spec §4.4 + sensitivity doc.
6. Commit: gate code + policy + updated spec + 15-cell report (rule 3).
7. Update T3-002 status in .seeds/issues.jsonl.
8. Next issue: T3-003 (F8) or T3-004 (contention) per priority.
