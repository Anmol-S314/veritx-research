# HANDOFF — Cross-session review package (Phases 1→10, Phase-13 precursor)

**Date:** 2026-09-18 · **Branch:** `epic/booksim-forward-port` (remote: `Anmol-S314/veritx-research`)
**Purpose:** a single document for an independent reviewer (human or model) to
audit everything the agent sessions did, know what is deliberately deferred,
and resume Phase 13 without re-deriving context.
**Per-phase detail lives in the per-phase handoffs listed in §3 — this file is
the index and the honest-incident record, not a replacement.**

---

## 1. Program frame (read these first)

- Authority: `docs/VERITX_SROTA_IMPLEMENTATION_PLAN.md` (phase sections; Phase
  13 = §17, Phase 14 = §18). Sequencing: `docs/NEXT_ENGINEERING_SEQUENCE_2026-09-17.md`.
- Vocabulary (code-cited): `tracks/t3-topology/CONTEXT.md`. Invariants: ADRs
  `tracks/t3-topology/docs/adr/0001..0006` (immutable runs, run_id vs
  experiment_hash, fingerprint resume, trusted config vs scientific intent,
  no-shell boundary).
- Working rules: repo-root `AGENTS.md` (semantic compression, one
  implementation per concept, fail-fast command pattern = `cmd_serve`,
  no `| tail` exit-code trust, embedded ASTRA needs
  `--booksim2-extra=injection_rate=0.0`).
- Program discipline observed all sessions: one phase per arc, TDD red→green,
  tests at seams (no internal mocking), full suite + lint gate before commit,
  STOP before the next phase, commit + push each gate.

## 2. Current state (verify, don't trust)

```bash
python3 -m pytest tracks/t3-topology/dse/tests -q   # expected: 1180 passed, 1 skipped
make -C tracks/t3-topology lint                     # expected: PASS
python3 -m veritx_dse.cli doctor --level quick      # expected: all green
```

Head: `c06f3968` (phase13 precursor handoff). Everything below is committed and
pushed except local working files (`AGENTS.md`, `comm/`, `VERITX_CURRENT_STATE_AUDIT.md`,
`scorpio-demo/` are untracked host-side state; binaries under `third_party/` are
untracked build artifacts by design — `3086f629` stopped tracking them).

## 3. Timeline — one arc per session

| Phase | Commit(s) | Gate | Per-phase handoff (canonical detail) |
|---|---|---|---|
| 1 — serving preflight, PP fail-closed, fidelity identity | `0b82aa42`, `831c35d2`, `6b8cf56f` | suite green | (summarized in phase3/4 handoffs) |
| 2 — liveness command recording + baselines | `65cf7c3d` | suite green | `HANDOFF-2026-09-17-phase2-liveness-baseline.md` |
| 3 — real serving-BookSim fabric evidence | `b817f616`, `33dc37e0` | suite green | `HANDOFF-2026-09-17-phase3-real-booksim.md` |
| 4 — PR6 serving slice (spec, registry, goldens A+B, tripwire) | `33dc37e0` | suite green | `HANDOFF-2026-09-17-phase4-pr6-slice.md` |
| 5 — canonical serving metric vocabulary (schema v1) | `de4fcc02` | 1038 passed, 1 skipped | `HANDOFF-2026-09-17-phase5-metrics.md` |
| 6 — PR7 analytical slice (aware + unaware, engine identity as data) | `2ed6b623` | 1048 passed, 1 skipped | `HANDOFF-2026-09-17-phase6-pr7-analytical.md` |
| 7 — semantic-compression review (Run.record_plan/cancel extraction) | `0e91a612` | no behavior change | `HANDOFF-2026-09-17-phase7-compression-review.md` |
| 8 — ComparisonSpec enforcement | `1110bc71`, `dfce7046` | suite green (+428-line integrity tests) | `HANDOFF-2026-09-18-phase8-comparison-integrity.md` |
| 9 — canonical WorkloadArtifact + lowering + sufficiency gate | `c64d442c`, `711b51f1` | 1135 passed, 1 skipped (+48) | `HANDOFF-2026-09-18-phase9-canonical-workload.md` |
| 10 — RouteArtifact (content-addressed routing truth, F6 upgrade) | `08ad0bc6`, `eedd547c` | 1158 passed, 1 skipped (+23) | `HANDOFF-2026-09-18-phase10-route-artifact.md` |
| 13-precursor — F2/F3/F8 evidence plumbing + fork delta | `ad992a26`, `c06f3968` | 1180 passed, 1 skipped (+22) | `HANDOFF-2026-09-18-phase13-precursor-evidence-plumbing.md` |

User explicitly deferred **Phase 11 (RTL)** and **Phase 12 (formal — SVA proofs
run against RTL)**; program order then permitted the Phase-13 precursor, then
Phase 13 proper.

## 4. The load-bearing design rulings — scrutinize these first

Each of these was a judgment call with a "wrong version" that would have been
easier. If you refute one, the blast radius is the named phase's tests.

1. **Workload sufficiency gate (Phase 9, user-imposed test).** Both backend
   inputs (BookSim/ASTRA ET and analytical) must be *regenerable from the
   WorkloadArtifact alone* and byte-match what the child actually executed.
   This gate caught two real semantic gaps during development: dropped
   mem-location semantics (`REMOTE:<dev>` → ASTRA `issue_remote_mem`) and the
   label sidecar (transport vs identity). Verify the gate is not
   self-referential (it compares against the child's *executed* ET bytes, not
   the lowering's own claims) — `workload/lowering.py`, `workload/serve.py`,
   `tests/test_workload_canonical.py`.
2. **BROADCAST ruling (Phase 9, Case B).** The old `participants[0] = source`
   convention was provisional; the artifact now carries explicit
   `source` / `destinations`. Do not let any lowering reintroduce the
   positional assumption.
3. **Dimensional scope (Phase 9).** Scope is either an explicit dim list or the
   `ALL_DIMENSIONS` sentinel; "absent" is *unrepresentable* by construction —
   the backend fallback that fabricates all dimensions can no longer be
   reached silently. PP is representable in the artifact but every lowering
   refuses (`UNSUPPORTED_LOWERING_TARGET`) — capability ≠ lowering support.
4. **F3 has no derived `dropped` counter (Phase-13 precursor).**
   `dropped = injected − accepted` fed back into
   `injected == completed + dropped` is an arithmetic identity that verifies
   nothing. F3 uses complete-delivery semantics: any injected-vs-ejected gap is
   visible loss. A stock binary that prints no totals yields *absent* keys →
   F3 stays NOT_RUN — never a fabricated zero.
5. **Fork delta capture point (Phase-13 precursor).** Flit totals are
   increment-on-event at the two exact injection/ejection points
   (`trafficmanager.cpp`, `VeritX:`-marked, mirrored to both booksim2 copies
   per sync protocol; `doctor.seam.booksim_fork_mirror` guards drift). The
   obvious alternative (Overall stats block) provably reads *cleared* counters
   in trace mode — it prints `-nan`/0 while `DisplayStats` had the real values.
   That quirk is pre-existing upstream behavior, documented in the handoff;
   a live run verified 96 injected == 96 accepted.
6. **F8's bound comes only from declared E2 requirements.** No default bound
   exists; without a declared ceiling F8 stays NOT_RUN. A default would
   manufacture a pass.
7. **F6 (Phase 10).** RouteArtifact is certifier-side truth today: the
   deadlock certificate embeds it, `from_dict` re-verifies both hashes, F6
   upgrades NOT_RUN → PASS/FAIL on evidence. **Honest residual: BookSim does
   not yet *consume* the artifact** (no fork changes). The class/VC axis is
   reserved for schema v2.
8. **Phase 8 two-tier verdict.** Comparison-wide incoherence →
   `INVALID_COMPARISON`; candidate-specific defects → visible exclusions with
   pinned reasons; Pareto scope always states requested vs comparable counts.
   Unaware-analytical `exposed_communication` can never masquerade as a
   measured zero (`METRIC_NOT_COMPARABLE`). Legacy rows are `certified: false`.

Standing reviewer notes from the user (keep enforcing):
- `certified: false` must be a *transition* state — the immutable-run path
  should eventually produce certifiable comparison evidence, not inherit
  legacy false as permanent default.
- Seed policy being fingerprinted ≠ statistical confidence existing. For n=1,
  output must say exactly that.

## 5. Incident log (things that went wrong, honestly)

1. **ENOSPC disk exhaustion (early session).** In-tree run outputs filled the
   disk. Fixed: run dirs gitignored at all three accumulation points; `t3`
   entry lint-guarded. Do not regress.
2. **Tool-argument validation failures.** Several `write_file`/`str_replace`/
   `read_files` calls were rejected mid-session for malformed parameters
   (missing `instructions`, string-typed booleans, string-typed numbers).
   Transient agent tooling issues; no repo impact, retried successfully.
3. **Container breakage — DIAGNOSED, FIX DEFERRED BY USER (open).**
   Symptom: every `t3 veritx compare` run fails twice over:
   - `booksim: ... libstdc++.so.6: version 'GLIBCXX_3.4.32' not found`
   - `No module named 'pydantic'`
   Root cause: the Phase-13 precursor rebuilt the booksim binary with **host**
   `make` (host: libstdc++ ≥ 3.4.32, Python 3.14). `t3` executes inside
   `ghcr.io/anmol-s314/veritx-tools-base` (Ubuntu 22.04: libstdc++ 6.0.30 →
   GLIBCXX_3.4.30 max, Python 3.10, no pydantic). The host pytest suite cannot
   see either failure by construction — it runs on the host and never enters
   the container. Fix path (not executed): rebuild both binaries *inside* the
   container (`t3 exec` / `podman run ... make`), and provision the container
   python from `tracks/t3-topology/dse/requirements.lock` (pydantic==2.13.4 et
   al.; image has pip 22). Scope: **local workstation only** — binaries are
   untracked artifacts, so fresh clones are unaffected; repo content is sound.
   Why tests missed it: see §6.
4. **Piped-grep exit codes.** Repeatedly caught myself trusting `| grep`/`| tail`
   pipelines that mask real exit codes (AGENTS.md warning #2). The fork-delta
   debugging (wrong capture point, twice) is the cautionary example: verify
   against the real binary's output, not derived expectations.

## 6. What the test suite can and cannot catch (for the reviewer)

The 1180-test suite runs **on the host** and tests **seams** (parsers, spec
enforcement, hashing, evidence contracts) — deliberately, per the program's
tests-at-seams rule. Structurally invisible to it:

- **Container-only failures** (ABI, image python deps). Mitigation that does
  not exist yet: run `t3 veritx doctor` (or a smoke target) *inside* the
  container after any binary rebuild or dependency change. The doctor's
  `seam.booksim_fork_mirror` check already exists and caught a real drift once.
- **Byte-level tool behavior changes** (e.g. BookSim stats output format).
  Parsed seams have fixtures, but the live-binary contract is only exercised
  by goldens (Golden-A/B) — run them after any fork edit.
- Environment coupling of any kind. The honest rule: after touching
  `third_party/` or dependencies, run one real end-to-end (`t3 veritx compare`
  at the smallest config) before believing the gate.

## 7. Deferred ledger (explicitly not done — do not "discover" these)

| Item | Owner/when | Note |
|---|---|---|
| Phase 11 RTL credibility | user-deferred | automated 4×4/8×8 regression, correlation contracts first |
| Phase 12 formal (SVA) | deferred with RTL | proofs run against RTL |
| Container env repair (§5.3) | user-deferred 2026-09-18 | rebuild binaries in-container + pydantic provisioning |
| BookSim *consuming* RouteArtifact | Phase 10 residual | certifier-side only today; no fork changes |
| RouteArtifact class/VC axis | schema v2 | after routing truth is stable |
| Slice-A (standalone BookSim) workload canonicalization | deferred with its owner slice | Phase 9 covers the serving path |
| Phase 8 `certified: false` → certifiable immutable-run evidence | future phase | user standing note |
| Studio, NS-3 build, distributed anything | gated | never until the program opens them |

## 8. Phase 13 starting state (resume here)

Spec: plan §17 (Requirements-driven Fabric Compiler). Requirements
(`latency_ceiling_cycles`, etc.) already exist as data on E2 requirements —
they must now *actively constrain* synthesis. Required contract:

- Verdicts: `FEASIBLE` (candidate set + evaluated metrics + constraint
  verdicts + Pareto evidence) or `NO_FEASIBLE_DESIGN` (violated constraints +
  evidence + search scope + relaxation information). **Never silently relax a
  hard requirement.**
- Candidate records must preserve: identity, generation method, search budget,
  objective values, constraint verdicts, failed evaluations, pruning reason,
  fidelity, seed policy. Store the record set, not a winner.
- Audit already done (P13a, no code written): `veritx_dse/synthesis/` holds
  `evaluator.py` (869 ln), `bo_synthesizer.py` (690), `milp_topology_v2.py`
  (582), `iterative_synthesizer.py` (508), `results.py` (153),
  `event_objective.py` (166); the only consumer is `cli/cli.py`. Phase-8
  machinery (`core/comparison.py`) is the Pareto gate to reuse; the Phase-13
  precursor made F2/F3/F8 evidence real, which was the agreed prerequisite.
- Planned steps (TDD): b) derive compiler contract → c) constraint evaluation
  (fail closed, relaxation info on infeasible) → d) search integration
  (candidate records, Pareto via Phase-8) → e) CLI wiring + end-to-end
  feasible/infeasible examples → f) gate, commit, push,
  `docs/HANDOFF-2026-09-18-phase13-fabric-compiler.md`, STOP before Phase 14.

## 9. Reviewer checklist

```text
[ ] Re-run §2 gates; numbers match
[ ] Spot-audit §4 rulings against the per-phase handoffs (esp. #1 sufficiency
    gate and #5 fork capture point — both had plausible-but-wrong alternatives)
[ ] Confirm Phase 9 goldens still byte-match (tests test_workload_canonical.py)
[ ] Confirm F6 evidence path cannot PASS on a tampered artifact
[ ] Decide container repair (§5.3) before any t3 container work
[ ] Resume Phase 13 from §8; no other phase may start first
```
