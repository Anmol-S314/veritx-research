# runner-release-audit — the release-runner machinery, audited statically (2026-11-10)

Status: **audit; static inspection only**. No builds, sims, gates, or tests were run.
No file was edited except this one. Repo HEAD at inspection: `7b124cc5d0f9200d1ef730ee57ec046402e2c3ff`;
740 porcelain entries in `git status` at inspection time (was 732 at the 2026-11-10 morning audit).
All audited runner files are untracked (`scripts/complete_design.py`, `scripts/sequential-gates.sh`,
`scripts/reproduce_slice.sh`, `scripts/verify_slice.sh`) as are the audited docs
(`SEQUENTIAL-GATES.md`, `GATEWAY-RESTART.md`, `INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md`).
Nothing here is release evidence; only artifacts archived under `runs/` with sha256 pins are.

Scope: `scripts/complete_design.py` (in full), `scripts/sequential-gates.sh`,
`scripts/validate_release_manifest.py`, `scripts/write_release_manifest.py`,
`scripts/check_topology_family_registry.py`, `scripts/reproduce_slice.sh`, `scripts/verify_slice.sh`,
`tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py` (family constants and composed/shared
runner arms), `tracks/t3-topology/dse/tests/test_complete_design.py`,
`test_project_top_slice.py`, `test_family_bad_design.py`,
`docs/product/INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md` (§12 checkpoint 2026-11-10),
`docs/product/INTENT-TO-PLACED-RTL-20261110-AUDIT.md`, `docs/product/SEQUENTIAL-GATES.md`,
`docs/product/GATEWAY-RESTART.md`, `docs/product/REMAINING-WORK.md`.

---

## 0. Verdict summary (read first)

1. **The C-08 fix path is internally consistent in shape but is not the fix the docs describe.**
   The `kncube` row short-circuits **before** `make_family_request` and writes a `family:kncube`
   `BLOCKED` stage; every other row goes through the generic path; every branch writes a
   `family:<name>` stage. However, **`kncube_lint_and_sim` is never called by the runner** — it is
   dead code outside the tests. The landed behavior is an honest refusal
   (`KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING`), not "kncube harness routing",
   and not the fix `INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md:382`, `GATEWAY-RESTART.md:43`,
   `SEQUENTIAL-GATES.md:24,33`, `REMAINING-WORK.md:9`, and the audit's own C-08 remedy claim.
2. **The release matrix cannot exit 0 today, by construction.** `release_matrix` always appends
   `kncube` to `failures`, so the `FAMILY_MATRIX_FAILED` blocker always fires; `completion_result`
   ranks `BLOCKED` above `NOT_RUN`; the `--release` path returns exit 1 unless the result is
   `PASS`, which is unreachable while the kncube short-circuit and `physical NOT_RUN` both stand.
   Best achievable `--release` outcome today is `BLOCKED`; realistic outcome (given the five
   recorded typed refusals) is `FAIL`. **P11.3's pass condition — "no required row missing,
   duplicated, substituted, blocked or unrun" — is not meetable on 2026-11-10.**
3. **mesh 8×8 is not proven to emit from `--release` today.** Recorded evidence is negative (the
   300 s Verilator-arm FAIL); the one reported PASS exists only in a destroyed `/tmp` log; the
   composed build arm is now 900 s with `--build-jobs 1 -CFLAGS -O0`, which removes the known
   failure mode but creates no evidence. Do not state "mesh passes" until a pinned re-run exists.
4. **Nothing from any matrix run is pinned under `runs/`.** The 2026-11-09 "torus/ring/gec_mecs/
   flatfly/srota/gec_hybrid PASS" claim has no `runs/` artifact either; the 2026-11-10 matrix FAIL
   manifest lived only at `/tmp/opencode/complete-design-release/manifest.json` and was destroyed
   by the service restart (only the audit's transcription of its row results remains).
5. **`FAMILIES14` is the right fourteen-name set but three hand-maintained copies exist**; one of
   them (`test_family_bad_design.py:34`) spells the list with `"cmesh"`. There is no
   machine-checked acceptance list anywhere; `check_topology_family_registry.py` checks the YAML
   registry, not the release set.
6. **The acceptance revision cannot be smoked through `--revision` as wired:** the frozen revision
   carries no `topology` object, and `CompileRequestV4.from_dict` requires one
   (`compile_request_v4.py:326` — "a v4 request MUST carry 'topology'"). The `--project/--revision`
   live path therefore ends in `INTENT_REFUSED`, not in hardware evidence. The `--request` fixture
   REMAINING-WORK.md item 10 expects does not exist in the repo.
7. **The single-project smoke (C-07) has never run.** No `PASS_WITH_NOT_RUN` or complete_design
   manifest exists anywhere in `runs/`, `/tmp`, or the audit record.
8. **`sequential-gates.sh` and `SEQUENTIAL-GATES.md` disagree on gate order** (`frontend-tsc` runs
   last in the script's default, first in the doc's Rule 1), and two `manifest.json` formats
   co-exist (the script's stage→rc map vs. the runner's `contract_version: 1` manifest). Neither is
   chosen by any document as the P11.4/11.5 artifact.
9. **No script is wired into CI** (`.github/workflows/ci.yml`, `release.yml`, `studio-live-e2e.yml`,
   `windows-desktop-acceptance.yml`, `Makefile` — zero references to `complete_design.py` or the
   matrix). P11.1 "one stable source snapshot" has no machine enforcement.
10. **The backend DSE unit suite has never completed this cycle**
    (`runs/sequential-gates-20261110T091202Z/dse-pytest.log` ends at ~33% with one `F`).

What to do about it: §4 gives the exact P11 command list, §5 the honest expected rows, §6 the
artifacts to archive and the sha256 pin procedure, §7 the required order (gates first, then matrix,
then pin), §9 the doc corrections the operator must ratify.

---

## 1. Method

All conclusions come from reading files and `git` state. No process was started. Notably: the
compiled cache `scripts/__pycache__/complete_design.cpython-314.pyc` (mtime 2026-11-10 14:55) was
inspected read-only; its `release_matrix` code object names
`['FAMILIES14', 'mkdir', 'append', 'KNCUBE_BLOCKER', 'write_text', ..., 'make_family_request', ...]`
contain **no** `kncube_lint_and_sim` reference, confirming the on-disk kncube short-circuit was the
last compiled state, i.e. the docs describe a fix that is not in the tree. `git ls-files` was used
to classify tracked vs. untracked; `find runs/` showed no complete_design manifest under `runs/`
(timed out on breadth, but no `runner` / `--release` / `FAMILY_MATRIX_FAILED` hits anywhere in
`runs/`). The live gateway was not probed; the 2026-11-10 14:2x restart record in
`GATEWAY-RESTART.md` is taken as the last published state and treated as stale by its own rule.

---

## 2. Task 1 — is the C-08 fix path internally consistent?

Reference: `scripts/complete_design.py:250-329` (`release_matrix`).

### 2.1 Branch topology as it exists on disk

| Branch | Lines | Trigger | Path | Stage written |
|---|---|---|---|---|
| kncube short-circuit | 258-269 | `family == "kncube"` | **before** `make_family_request`; appends `KNCUBE_BLOCKER` detail blocker ("no general saved-request KNCube topology exists; refusing the old torus-backed substitute") | `family:kncube`, `status=BLOCKED`, `exit_code=1`, no lint/sim/scenarios keys |
| generic compiled path | 270-288 | all other 13 families | `make_family_request` → `FabricCompiler().compile` → if not `COMPILED`, typed FAIL stage + `continue` | `family:<name>` `FAIL` (compile refused) |
| generic hardware path | 282-288 | compiled | `gec_mecs`/`gec_hybrid`/`srota` → pinned shared runners; **all others** → `run_composed_family(family_doc, family_out, config)` directly | (flows to §2.3) |
| post-hardware | 289-300 | after `run_*` returns | `hardware_evidence_status(result)` → stage appended with lint/sim/scenarios/logs/`development_milestone` | `family:<name>` with full evidence |
| exception net | 303-311 | any exception | `runner-error.log` written under `family_out/` | `family:<name>` `FAIL`, `detail` truncated to 600 chars |

Every one of the 14 `FAMILIES14` entries produces exactly one `family:<name>` stage per matrix run;
the kncube branch additionally writes `manifest.json` inline (267-268) and the loop end writes it
again (312) — benign double write. `failures` aggregate feeds `FAMILY_MATRIX_FAILED` (313-317).
Non-PASS family statuses append `failures` (274, 302-303); the kncube branch appends `kncube` (266).

### 2.2 `hardware_evidence_status` semantics (`:389-400`)

`FAIL` if any of `lint`/`sim` is `FAIL`; else `BLOCKED` if either is missing/not `PASS`; else
`BLOCKED` if `scenarios` missing/empty; else `FAIL` if any scenario value is not literally `True`;
else `PASS`. Consequences for the matrix:

- A family whose runner raises (lint or build refused → `ValueError`) is caught by the exception
  net → `FAIL`, not `BLOCKED` — evidence is never silently upgraded.
- Scenarios is `dict[str, bool]` everywhere; a single `False` (or `1`) flips the row to `FAIL`.
- A row with lint+sim `PASS` but empty scenarios is `BLOCKED` — correct strictness.

### 2.3 `completion_result` / exit code (`:403-417`)

Precedence: `FAIL` > `BLOCKED` > `NOT_RUN` > `PASS_WITH_BLOCKERS` > `PASS`. `--release` returns
exit 0 **only** for `PASS` (`:458-460`). Today: kncube `BLOCKED` present + physical `NOT_RUN`
(default) ⇒ best case `BLOCKED` (exit 1); any family `FAIL` ⇒ `FAIL` (exit 1). `exit 0` is
unreachable without (a) a working kncube general-intent binding + native equivalence checker and
(b) a design-bound physical runner (`physical_stage :420-432` always records `NOT_RUN` without
`--with-physical`, and `BLOCKED`+`DESIGN_BOUND_PHYSICAL_RUNNER_NOT_WIRED` with it).

### 2.4 Consistency verdict per branch

- **kncube short-circuit is before `make_family_request`** — yes, exactly as intended by C-08's
  "must not raise inside the generic branch" requirement. It cannot escape as an exception; it
  writes its stage; `manifest.json` reflects it. **The shape requirement holds.**
- **Else generic path** — in the matrix, gec/srota go to shared pinned runners and everything else
  to `run_composed_family` **directly**; the single-project path's `run_rtl_slice` →
  `run_composed_family` fallback (`generate_hardware :223-247`) is *not* used by the matrix.
- **Each branch writes `family:<name>` statuses** — yes (kncube: BLOCKED shape without evidence
  keys; compiled-refused: FAIL; hardware: full evidence shape; exception: FAIL with truncated
  detail). Downstream summary table (`:318-328`) prints all rows sorted FAIL/BLOCKED first.

### 2.5 Deviations — where the on-disk fix diverges from the documented fix

| # | Claim in docs | Reality in tree |
|---|---|---|
| D-1 | `completed_design.py` "harness routes kncube directly to `kncube_lint_and_sim` before `make_family_request`" (PLAN `:382`; audit C-08 remedy; `SEQUENTIAL-GATES.md:24,33`; `GATEWAY-RESTART.md:43`; `REMAINING-WORK.md:9`) | kncube branch writes `BLOCKED` and **never calls** `kncube_lint_and_sim`. `kncube_lint_and_sim` (`:331-378`) has zero call sites in the runner; only `tests/test_complete_design.py:9,50` imports/calls it. pyc confirms. |
| D-2 | "its honest verdict comes from the next matrix re-run, not from the source change alone" (SEQUENTIAL-GATES L24) | The next re-run will print `BLOCKED` for kncube regardless of machine health; there is no "verdict" left for the row to surprise anyone with. Deterministic, construction-bound outcome. |
| D-3 | `kncube_lint_and_sim` is the harness path "kncube uses" (SEQUENTIAL-GATES L24; audit §D) | The harness requires `params.family == "kncube"` built from **torus** compile output (`test_project_top_slice.py:691-704`, `replace(torus_params, family="kncube")`) — the "old torus-backed substitute" that the landed short-circuit explicitly refuses and that `test_complete_design.py::test_kncube_runner_refuses_a_torus_source_instead_of_substituting` asserts must be refused. The documented route would reintroduce the substitute the tree rejects. |
| D-4 | kncube never passes before the fix; "fixed" (audit C-08, remediation table) | The fix removed the `TopologyIntentError` crash/FAIL-by-construction row; it did **not** make a PASS row reachable. `KNCUBE_BLOCKER` = `KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING` (`project_top_rtl.py:4121`). Building a general structured `kncube` intent would additionally require registering `kncube` in `STRUCTURED_FAMILIES` (`topology_artifact.py:1180-1210` — absent) and a native equivalence checker (absent). |
| D-5 | `FAMILY_REQUESTS["kncube"]` entry (`:32`) — harmless leftover | Any future edit that removes the short-circuit re-arms `TopologyIntentError: unknown structured family 'kncube'` (known: `dragonfly`, `fat_tree`, `flattened_butterfly`, `qtree`, `tree4`). The entry is a landmine, not an option. |
| D-6 | Recommendation in audit C-08 "Route `kncube` to `kncube_lint_and_sim` before `make_family_request`" | Not landed; do **not** "land" it without an explicit operator decision, because D-3. The honest current state is "BLOCKED by construction" — docs must say that, verbatim. |

Conclusion: internally consistent **as a refusal**, inconsistent **as the documented C-08 fix**.
The C-08 invariant "kncube must not reach `make_family_request`" is satisfied; the C-08 intended
outcome "kncube row executes the harness and reports lint/sim" is not, and cannot be without a
general kncube intent source and a non-substitute parameterization.

### 2.6 Smaller notes observed while verifying the branch (not defects)

- gec/srota shared runner arms build with `timeout=300` (`project_top_rtl.py:8796,8863,8926`)
  while the composed arm uses `timeout=900 --build-jobs 1 -CFLAGS -O0` (`:6500`) and lint 120 s
  (`:6489`), sim 120 s (`:6503`). Three timing regimes co-exist; none is documented as intentional
  in the runner.
- The kncube stage omits `lint`/`sim`/`scenarios`/`logs` keys entirely; consumers must not assume
  the full hardware-evidence shape for BLOCKED rows from non-`run_*` writers. They don't
  (`hardware_evidence_status` is never called on it).
- `family_out` is `mkdir`'d for every row including kncube; kncube leaves an empty
  `release-matrix/kncube/` directory — harmless, but it will fool a naive
  "every family produced RTL" file-existence check.
- `release_matrix` never sets `manifest["result"]` itself; `main()` does (`:458`). A future refactor
  calling `release_matrix` directly would leave the manifest without `result`. Cosmetic.
- The summary table's `width = max(len(row[0]) ...)` uses `rows` after all 14 rows — fine.

---

## 3. Task 2 — what else in `scripts/` is stale

Legend: **S-n** = finding; severity: **H** = invalidates a claim, **M** = must fix before release
evidence, **L** = hygiene.

1. **S-1 (H) `FAMILIES14` vs the acceptance list.** The acceptance plan (`INTENT-TO-PLACED-RTL-
   COMPLETION-PLAN.md:89` P0.3 "one checked-in acceptance list; no shifting finish line" and `:341`
   "extend the required release set to all fourteen without rewriting historical evidence") extends
   the 12 Track-A families in `docs/research/rtl-12of12-plan/ACCEPTANCE.md` §8 (mesh, CMesh, ring,
   torus, qtree, tree4, fat-tree, fly64, flatfly, gec-mecs, hybrid, srota) with `dragonflynew` +
   `kncube`. `scripts/complete_design.py:34-36` carries exactly that fourteen
   (`mesh, torus, concentrated_mesh, ring, gec_mecs, fly, qtree, tree4, flatfly, srota, gec_hybrid,
   fattree, dragonflynew, kncube`) — consistent with P0.3's intent. **But** the "acceptance list"
   is nowhere machine-checkable: (a) three hand-maintained copies of the set exist —
   `complete_design.py:34`, `project_top_rtl.py:4115` (identical order), and
   `tests/test_family_bad_design.py:34-36` which uses `"cmesh"` and a different order; (b) a third
   naming scheme lives beside them (`LEGACY_FAMILY_IDS`/`FAMILY_TOPOLOGY_IDS`,
   `project_top_rtl.py:4118-4120`: `mesh→mesh8x8`, `fly→fly64`, `torus→torus8x8`); `FAMILY_EXPECTED_
   ROUTERS` (`:4122-4124`) uses a fourth mapping internally. Nothing checks that the runner's fourteen
   == the acceptance fourteen == the registry's fourteen. `scripts/check_topology_family_registry.py`
   (modified today, +5 lines) derives intent-kinds from `STRUCTURED_FAMILIES` — the right fix for
   that file — but still checks the YAML registry, never the release set.
2. **S-2 (H) dragonflynew kwarg fix is present but never re-run.** `complete_design.py:29`:
   `StructuredTopologyIntent({"family": "dragonfly", "params": {"radix": 6, "group_count": 6}})` —
   matches `STRUCTURED_FAMILIES["dragonfly"]` fields `(radix, group_count)` with `_as_int(...,
   minimum=2)` ✓, and `_family_id_from_topology` maps `{family: dragonfly}` → `"dragonflynew"` ✓, so
   `hardware_family_for_request` returns `"dragonflynew"` == `family` ✓. The fix is real. But the
   last recorded matrix ran with this shape present (the audit's C-08 row) and still recorded
   `dragonflynew` FAIL; whether that FAIL predates or postdates the fix is unrecorded, and the
   `/tmp` manifest is destroyed. **Unverified — pending the §4 re-run; do not quote as PASS.**
3. **S-3 (H) Can `--release` emit mesh deterministically now? No — unproven, recorded evidence is
   negative.** Mechanism today: `run_composed_family` → `_require_single_endpoint_per_router`
   (`project_top_rtl.py:6372-6380`, refuses "multiple endpoint seats on one router" — mesh8×8 with
   3 endpoint groups seats on distinct routers, OK) → `run_rtl_preview` → `apply_ordering_frontend_
   fix`/widening → `build_family_router` → lint `-Wall` `timeout=120` → TB build `--binary --timing
   --build-jobs 1 -CFLAGS -O0` `timeout=900` → sim `timeout=120`, 13 scenarios expected
   (`status: PASS` + conservation/drain invariants). The 300 s arm that timed out is gone (now
   900 s, `-O0`), but: (a) no matrix re-run exists since the arm changed; (b) the only mesh PASS
   on record lived in `/tmp/opencode/mesh-rerun/` and was destroyed 2026-11-10 (SEQUENTIAL-GATES
   L29; audit §D); (c) `runs/` contains no mesh row of any kind — the only matrix manifest
   ever recorded was `/tmp/opencode/complete-design-release/manifest.json` (mesh FAIL at the
   300 s arm, now destroyed; only the audit's transcription survives), and the one `runs/`
   gate directory (`runs/sequential-gates-20261110T091202Z/dse-pytest.log`) shows the backend
   suite died ~33% into this cycle; (d) this host's swap was ~95% used with load > 9 at the time
   Deterministic emission requires a pinned re-run and a repeat; nothing about the current tree
   provides it. **Answer: not yet; treat mesh as the row most likely to FAIL or starve the box.**
4. **S-4 (H) The kncube machinery as documented does not exist.** `kncube_lint_and_sim`
   (`complete_design.py:331-378`) is reachable only from tests; in the runner it is dead code. Its
   own contract refuses non-kncube source topologies (`:333-335`) — i.e. it would demand the
   torus-substitute it exists to guard. The FAMILY_REQUESTS "kncube" row (`:32`) can never construct.
   `STRUCTURED_FAMILIES` has no kncube; the native equivalence checker does not exist;
   `KNCUBE_BLOCKER` is the honest state. Docs must stop saying "harness routes kncube".
5. **S-5 (M) `scripts/sequential-gates.sh` vs `docs/product/SEQUENTIAL-GATES.md` disagree.**
   Doc Rule 1 order: `frontend-tsc → dse-pytest → slice-family → parameterized → families-lint →
   release-matrix → playwright → reproduce → verify`. Script default (`sequential-gates.sh:48`):
   `dse-pytest slice-family parameterized families-lint release-matrix playwright reproduce verify
   frontend-tsc` — **frontend-tsc last, undocumented**. A bare invocation of the script therefore
   does not run the documented order and stops at the first failure with `failed.json` but never
   records the doc's intended frontend-first sequencing. Also: the script's success path writes a
   stage→exit-code `manifest.json` (`:64-72`) whose schema is unrelated to the runner's
   `contract_version: 1` manifest; P11 never names which one closes §11.4/§11.5; the script does
   not archive, does not sha256-pin, and does not record tool versions (REMAINING-WORK item 16);
   `families-lint` references the node id `test_composed_family_lints_and_sims` (exists,
   `test_project_top_slice.py:350`) but no count; the `release-matrix` stage writes
   `$OUT/release-matrix` into a timestamped fresh `$OUT` — correct and reproducible.
6. **S-6 (M) 2026-11-09 "PASS" rows are unpinned.** SEQUENTIAL-GATES L33 cites torus/ring/gec_mecs/
   flatfly/srota/gec_hybrid PASS (2026-11-09 run). No `runs/` artifact of that run exists (grep
   over `runs/` for the manifest marker finds nothing; the only matrix manifest ever recorded was
   `/tmp/opencode/complete-design-release/manifest.json` — FAIL, now destroyed). The six rows may
   well pass again; until re-run and pinned they are folklore, cited or not.
7. **S-7 (M) The single-project smoke cannot run against the acceptance revision as wired.**
   `--revision p-fd7e5e31be77-r02` (the acceptance revision, pinned in
   `docs/product/evidence/mixtral-74-81-8-162/`) yields a `design` object with keys `agents,
   workload, requirements, requirements, locked_derived, noc_guided, schema_version,
   compiler_semantics_version, contract_version, design_hash` — **no `topology`, no `physical`,
   no `address_map`, no `agent_intents`, no `dependencies`**. `CompileRequestV4.from_dict` refuses
   ("a v4 request MUST carry 'topology'", `compile_request_v4.py:326`) → the runner exits
   `INTENT_REFUSED` at the compile stage; no hardware stage runs. `--project <pid>` (draft) is the
   only other revision path and is equally dependent on the store's draft shape (not inspectable
   without a live GET — out of scope; do not assume). The `--request` fixture REMAINING-WORK item
   10 calls for does not exist; the audit cannot produce one (no code edits); §4 includes the
   exact one-off fixture-generation commands for the operator.
8. **S-8 (M) The acceptance revision would fail the hardware stage anyway.**
   `generate_hardware` dispatches `gec_mecs` → `run_gec_mecs_shared`, which pins k=4, c=1, o=1,
   d=3, **16 routers, 32 shared wires, VC 3** (`gec_mecs_shared_params_from_request`,
   `project_top_rtl.py:6679-6717`: any other shape raises `_refuse_shared`). The 81-router /
   162-shared-link / VC-8 acceptance design is not representable in the shared runner, and the
   matrix bypasses `generate_hardware` entirely. So the C-07 smoke, if aimed at the acceptance
   revision, fails at the hardware stage by typed refusal — this must be documented in the smoke
   report, not discovered as a "bug" mid-P11.
9. **S-9 (L/M) Release-manifest toolchain ≠ release runner.** `scripts/write_release_manifest.py`
   (schema_version 2; `release_sha`, cxx identity, backend build manifests, validation digests) and
   `scripts/validate_release_manifest.py` (fail-closed validator for the same) implement the
   **BookSim/backend-toolchain** sense of "release" — unchanged, tracked in git, not consulted by
   `complete_design.py`, not referenced by `sequential-gates.sh`, and not named in any P11 row.
   P11.4's "rebuild into a fresh output directory/environment" and P11.5's comparison have no
   bound to this manifest; the name collision will confuse two later auditors. Decide which
   manifest P11 consumes and say so in the P11 report; do not merge them silently.
10. **S-10 (L) Byte-compiled caches prove the on-disk state.**
    `scripts/__pycache__/complete_design.cpython-314.pyc` (2026-11-10 14:55) compiles the current
    BLOCKED short-circuit; `release_matrix`'s names omit `kncube_lint_and_sim`. Cache files should
    not be committed and are not evidence of behavior, but here they corroborate the source read.
11. **S-11 (L) Untracked state is not a release substrate.** `scripts/complete_design.py`,
    `scripts/sequential-gates.sh`, both gate docs, and the completion plan/audit are untracked;
    740 porcelain entries (vs. 732 at the morning audit). `git_head` recorded by any manifest
    today would be `7b124cc` with `tree_dirty: true` — honest, but not a "stable source
    snapshot" (P11.1). P11.1 must pin the owned subset (git add of the runner + docs, or an
    operator-approved snapshot tag) before any release claim can cite a manifest.
12. **S-12 (L) `scripts/reproduce_slice.sh` / `verify_slice.sh` are thin wrappers and untracked;**
    `reproduce_slice.sh:4` defaults `OUT=runs/slice` (shared, requires `--clean` to avoid
    contamination — the gate passes `--clean`, good). No staleness found beyond S-1/S-11; neither
    script is in the fourteen-family path.
13. **S-13 (L) date-stamped preflight.** `sequential-gates.sh:16` stamps `OUT` with UTC; re-runs
    accumulate `runs/sequential-gates-*` directories; only one exists (`…T091202Z`, dse-pytest
    died ~33%). No retention policy; harmless.
14. **S-14 (L) `check_topology_family_registry.py` fix works but is narrow.** The added
    `STRUCTURED_FAMILIES`-derived kinds close the qtree blind spot the comment describes; it does
    not (and cannot) validate the release set — that is S-1's unmet P0.3 item.
15. **S-15 (L) PLAN `:506` P11.2 note** — "the currently ignored pytest timeout setting":
    `pyproject.toml`/pytest ini carries an unknown `timeout` option (warning "Unknown config
    option: timeout" observed in the P0.6 re-run). P11.2's requirement to "enforce timeouts rather
    than rely on the ignored setting" is real; `sequential-gates.sh` relies on stage-level logs,
    not per-test timeouts; the Verilator arms carry `_run_logged(..., timeout=...)` (120/300/900 s)
    which *is* enforced. No script change mandated; noted so P11.2 does not quote GHA-style
    per-test enforcement into this repo.
16. **S-16 (H, doc-side) The doc set is stale relative to the tree.** Enumeration without re-editing:
    `INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md:382` (kncube "fixed by routing kncube directly to
    `kncube_lint_and_sim`" — false, D-1; also still says "mesh hit the 300 s Verilator timeout" as
    if current — the arm is now 900 s), `:384` ("mesh8x8 PASS … /tmp … must be pinned" — correct and
    unchanged), `:505` (P11.2 note, correct). `SEQUENTIAL-GATES.md:24` ("row harness-routes it since
    2026-11-10" — false), `:29-33` (mesh PASS "unsubstantiated until … lands under `runs/`" —
    correct and unchanged; the six recorded-PASS rows "torus/ring/gec_mecs/flatfly/srota/gec_hybrid"
    need the same unpinned treatment). `GATEWAY-RESTART.md:43` ("kncube harness routing" listed
    among the day's final edits — names an edit that did not land). `INTENT-TO-PLACED-RTL-20261110-
    AUDIT.md` (C-08 remediation row: "code fixed, matrix re-run pending" — true only in the narrow
    sense of "no longer crashes"; the prescribed fix is absent, and its "Needed to close" — re-run
    `--release`, archive under `runs/` — is undone). `REMAINING-WORK.md` items 9–16 match this
    audit; item 10 (fixture `--request`) additionally requires an authoring step nobody has done.
17. **S-17 (L) Three vocabularies for the same fourteen.** Manifest `family:` rows use runner
    spellings; `FAMILY_TOPOLOGY_IDS` emits `torus8x8`/`fly64`/`mesh8x8`-class ids in
    `family_profile`; the acceptance vocabulary (`fly64`, `CMesh`, `Fly64`…) in ACCEPTANCE.md §8.
    A downstream verifier keyed on the wrong spelling will fail loudly (good) or silently (bad, if
    it substring-matches `"mesh"`). Any P11 report must print the runner spellings, not the
    acceptance spellings, and say which spelling was used.

Net: S-1 through S-8 and S-16 are the stale set that matters for P11; S-9 decide-or-document;
S-10..S-15, S-17 hygiene.

---

## 4. Task 3/4 — exact command list to close P11 (frames incl. `--release`)

**Not to be run until the preconditions hold.** This audit ran none of these.

### 4.0 Preconditions (stop-and-report list)

- P9 lane notifies it releases the machine (SEQUENTIAL-GATES Rule 1); P8 lane notifies it releases
  the TB generators. No gate starts before both. Current P9 state: CTS/post-CTS STA recorded,
  stages ≥ 37 NOT_RUN — **the physical half of P11 is blocked regardless of what follows here.**
- Operator gives explicit direction to run the release lane (the 2026-11-10 gate runs were
  operator-owned; a fresh run inherits that ownership).
- `awk '/^MemAvailable:/{print int($2/1024)}' /proc/meminfo` ≥ 4096 and `awk '/^SwapFree:/{print
  int($2/1024)}' /proc/meminfo` ≥ 1024 (the script enforces this; check before the first stage).
- Nothing else heavy is running (`loadavg`, no concurrent Verilator/LibreLane).
- Tree state is pinned for release: owned release files committed or operator-approved snapshot;
  record `git rev-parse HEAD` and `git status --porcelain | wc -l` into the evidence root. Do not
  sweep unrelated files to make this clean — record the dirty count instead.

### 4.1 Choose and create the evidence root

```bash
cd /home/datavex/bruh/veritx-research
TS=$(date -u +%Y%m%dT%H%M%SZ)
export RUNS="runs/p11-release-$TS"
mkdir -p "$RUNS"
{ git rev-parse HEAD; git status --porcelain | wc -l; verilator --version; python3 --version;
  node --version 2>/dev/null; npx --version 2>/dev/null; uname -a; date -u; } | tee "$RUNS/TOOLCHAIN.txt"
```

### 4.2 Gates — documented order (SEQUENTIAL-GATES.md Rule 1), not the script's default

Run one at a time. If a stage fails, stop; record `failed.json`; fix the cause; resume from that
stage only (Rule 3). Never rerun to green (Rule 4).

1. `frontend-tsc`
   `npx --prefix apps/studio/prototype tsc --noEmit 2>&1 | tee "$RUNS/frontend-tsc.log"; echo "rc=$?" | tee "$RUNS/frontend-tsc.rc"`
2. `dse-pytest` (must run to completion; the 2026-11-10 attempt died ~33% in)
   `PYTHONPATH=$PWD/tracks/t3-topology/dse:$PWD/tracks/t3-topology/dse/tests python3 -m pytest tracks/t3-topology/dse/tests -q -p no:randomly 2>&1 | tee "$RUNS/dse-pytest.log"`
3. `slice-family`
   `PYTHONPATH=$PWD/tracks/t3-topology/dse:$PWD/tracks/t3-topology/dse/tests python3 -m pytest tracks/t3-topology/dse/tests/test_project_top_slice.py tracks/t3-topology/dse/tests/test_project_top_shared.py tracks/t3-topology/dse/tests/test_project_top_parameterized.py -q --tb=short 2>&1 | tee "$RUNS/slice-family.log"`
4. `parameterized`
   `PYTHONPATH=$PWD/tracks/t3-topology/dse:$PWD/tracks/t3-topology/dse/tests python3 -m pytest tracks/t3-topology/dse/tests/test_project_top_parameterized.py -q --tb=short 2>&1 | tee "$RUNS/parameterized.log"`
5. `families-lint`
   `PYTHONPATH=$PWD/tracks/t3-topology/dse:$PWD/tracks/t3-topology/dse/tests python3 -m pytest "tracks/t3-topology/dse/tests/test_project_top_slice.py::test_composed_family_lints_and_sims" tracks/t3-topology/dse/tests/test_project_top_shared.py -q --tb=short 2>&1 | tee "$RUNS/families-lint.log"`
6. `release-matrix` (the fourteen-family frame; §5 predicts the rows)
   `PYTHONPATH=$PWD/tracks/t3-topology/dse python3 scripts/complete_design.py --release --out "$RUNS/release-matrix" 2>&1 | tee "$RUNS/release-matrix.log"; echo "rc=$?" | tee "$RUNS/release-matrix.rc"`
   - Exit 0 is not achievable today (§0.2). Exit 1 is expected; **archive whatever it produced**;
     do not rerun hoping for green.
7. `playwright`
   `npm --prefix apps/studio/prototype run test:e2e 2>&1 | tee "$RUNS/playwright.log"`
8. `reproduce`
   `bash scripts/reproduce_slice.sh --out "$RUNS/slice" --clean 2>&1 | tee "$RUNS/reproduce.log"`
9. `verify`
   `bash scripts/verify_slice.sh 2>&1 | tee "$RUNS/verify.log"`

Equivalent via dispatcher: `scripts/sequential-gates.sh frontend-tsc dse-pytest slice-family
parameterized families-lint release-matrix playwright reproduce verify` — note this **overrides**
the script's default order (S-5); with no arguments the script runs its own order, not this one.

### 4.3 Single-project smoke (C-07 / REMAINING-WORK item 10)

The fixture does not exist; authoring it is part of the smoke, not a code edit:

```bash
cd /home/datavex/bruh/veritx-research
PYTHONPATH=$PWD/tracks/t3-topology/dse python3 -c '
from scripts.complete_design import make_family_request
import json
print(json.dumps(make_family_request("torus").to_dict(), sort_keys=True, indent=2))' \
  > /tmp/opencode/smoke-torus-request.json
python3 scripts/complete_design.py --request /tmp/opencode/smoke-torus-request.json \
  --out "$RUNS/single-project-smoke" 2>&1 | tee "$RUNS/smoke.log"
```

Expected honest result: `PASS_WITH_NOT_RUN` (hardware PASS if the torus row passes, physical
`NOT_RUN`). If hardware fails, record it — do not iterate the fixture to force green; the smoke
exists to expose the runner, not to flatter it. (Torus chosen: 9 routers, the known-smallest
composed family; matches the release matrix's torus row recipe.)

The acceptance revision must **not** be smoked as-is: it lacks `topology` in the pinned `design`
object (S-7) and, if migrated by hand, would still fail the hardware stage via the pinned shared
runner shape (S-8). Any "smoke the acceptance revision" attempt is out of scope until those are
addressed by design work, not by the audit.

### 4.4 Fresh-environment rebuild comparison (P11.4/P11.5)

Out of scope here; P11.4 requires a second clean machine or container and is blocked behind P9.
Recorded for completeness: no commands are prescribed until the operator approves the environment.

---

## 5. Honest expected fourteen-family FAIL rows today (static prediction; the re-run decides)

| # | family | code path today | expected row today | evidence |
|---|---|---|---|---|
| 1 | mesh | `run_composed_family` (64 routers, lint 120 s / build 900 s `-O0 --build-jobs 1` / sim 120 s) | **UNKNOWN — assume FAIL until proven** | recorded FAIL at the 300 s arm; `/tmp` PASS destroyed; never re-run; host swap pressure |
| 2 | torus | composed (9 routers) | PASS (recorded 2026-11-09) — **unpinned** | SEQUENTIAL-GATES L33; no `runs/` artifact |
| 3 | concentrated_mesh | composed | **FAIL** — typed `UNSUPPORTED_COMPOSED_FAMILY` (multi-seat, recorded) | audit C-08; `_require_single_endpoint_per_router` |
| 4 | ring | composed (64 routers) | PASS (recorded 2026-11-09) — **unpinned; memory risk like mesh** | SEQUENTIAL-GATES L33 |
| 5 | gec_mecs | shared pinned (k=4 c=1 o=1 d=3; 16 routers; 3 VCs; 32 shared wires) | PASS (recorded) — **unpinned** | shared-arm build timeout 300 s |
| 6 | fly | composed | **FAIL** — typed `UNSUPPORTED_COMPOSED_FAMILY` (recorded) | audit C-08 |
| 7 | qtree | composed | **FAIL** — typed refusal (recorded) | audit C-08 |
| 8 | tree4 | composed | **FAIL** — typed refusal (recorded) | audit C-08 |
| 9 | flatfly | composed (16 routers) | PASS (recorded) — **unpinned** | SEQUENTIAL-GATES L33 |
| 10 | srota | shared pinned (k=4 c=1, mecs row+col, island (1,), shapes {row,column}, vc=shape, 2 VCs, 48 shared wires) | PASS (recorded) — **unpinned** | SEQUENTIAL-GATES L33; pins match `SROTA_KWARGS` |
| 11 | gec_hybrid | shared pinned (same shape as mecs; HYBRID mode) | PASS (recorded) — **unpinned** | SEQUENTIAL-GATES L33 |
| 12 | fattree | composed (`FatTreeIntent(4,2)`) | **FAIL** — typed refusal (recorded) | audit C-08 |
| 13 | dragonflynew | composed, `StructuredTopologyIntent("dragonfly", 6, 6)` → 36 routers | **UNKNOWN — recorded FAIL; kwarg fix never re-run; seat-collision refusal possible** | audit C-08; fix present (S-2) |
| 14 | kncube | short-circuit | **BLOCKED by construction** (never PASS; always in `FAMILY_MATRIX_FAILED`) | §2 |

**Honest count today: 5 certain FAIL rows (concentrated_mesh, fly, qtree, tree4, fattree — typed
multi-seat refusals, P3 open), 1 certain BLOCKED row (kncube), 2 unproven rows (mesh, dragonflynew),
6 recorded-PASS-but-unpinned rows (torus, ring, gec_mecs, flatfly, srota, gec_hybrid).
Minimum certain non-PASS rows: 6. Predicted `manifest.json` result: `FAIL` (or `BLOCKED` in the
best case if every unproven row passes) — exit 1 either way; `scope_note` will read
"fourteen-family release matrix; single-project runs never publish a 14/14 claim" (correct);
`FAMILY_MATRIX_FAILED` will list at least `[concentrated_mesh, fly, kncube, qtree, tree4, fattree]`.

**P11.3 cannot close on this tree.** Either the multi-seat compose path lands (P3), the mesh row
passes and is pinned, the dragonflynew row is adjudicated by re-run, kncube gets a general
intent + native equivalence checker (or an operator-approved scope amendment), or P11.3 stays open.
Do not let any document quote "14/14" until all of those are true and pinned.

---

## 6. Artifacts to archive into `runs/` and the sha256 pin procedure

Archive everything below into `"$RUNS"` (from §4.1); nothing else counts as evidence; nothing in
`/tmp` may be cited.

| Artifact | Produced by | Archive as |
|---|---|---|
| `TOOLCHAIN.txt` (HEAD, dirty count, verilator/node/python versions, uname, date) | §4.1 | `$RUNS/TOOLCHAIN.txt` |
| Gate logs 1–9 (§4.2) | each command | `$RUNS/<stage>.log` (+ `frontend-tsc.rc`, `release-matrix.rc`) |
| Gate order record / `failed.json` if stopped | `sequential-gates.sh` if used | `$RUNS/failed.json` or per-stage `.rc` files |
| Release matrix manifest (fourteen rows, contract_version 1, git_head, tree_dirty, scope_note, stages, blockers, `result`) | §4.2 stage 6 | `$RUNS/release-matrix/manifest.json` |
| Per-family tops: `project-top-manifest.json`, `project-top.zip`, `rtl/**` (incl. `rtl/logs/*.log`), `runner-error.log` where present | stage 6 (`--out` dir) | `$RUNS/release-matrix/<family>/…` |
| Smoke manifest + input request copy + hardware dir | §4.3 | `$RUNS/single-project-smoke/…` (+ `smoke.log`) |
| Reproduce output | stage 8 | `$RUNS/slice/…` (only with `--clean`) |
| Verify output | stage 9 | `$RUNS/verify.log` (+ whatever `verify_slice.py` writes) |

Pin procedure (after the last artifact exists):

```bash
( cd "$RUNS" && find . -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum ) > "$RUNS/SHA256SUMS"
wc -l "$RUNS/SHA256SUMS"
( cd "$RUNS" && sha256sum -c SHA256SUMS )   # every line must print: OK
```

Then write `$RUNS/PINS.md` recording: git HEAD; `tree_dirty` boolean; date; the fourteen rows with
`status`, `lint`, `sim`, scenario count, and each row's `logs[].sha256` **as already embedded by
the runner** (`log_artifacts` hashes every `.log` into the manifest — verify they match the files);
the smoke `design_hash`; the `SHA256SUMS` digest itself. Commit these pins and the docs that quote
them; do not commit `rtl/` build trees unless the operator explicitly wants them (they are large and
reproducible-by-command).

Comparison rules for P11.5: **functional comparison only.** `project-top-manifest.json` semantic
fields (`design_hash`, `family_params`, `scenarios` map, `lint`/`sim` statuses, `scope`,
`final_implementation: false`) must match across the two builds; SV bytes and log tails contain
paths/timestamps/timing and are **not** byte-stable — pin their sha256 as provenance of what ran,
never as golden bytes. `release-matrix/manifest.json` across runs differs in `git_head` only when
the tree changed; flag any other semantic drift as a finding.

Minimal acceptance proof for the pin: `sha256sum -c` all-OK; `python3 -c 'import json;
m=json.load(open("…/manifest.json")); print(m["result"], m["git_head"])'`; and a one-line note of
what was **not** run (e.g. physical stages, `dse-pytest` if it died again).

---

## 7. Required order: gates first, then matrix, then pin — and why

1. **Pin the snapshot first** (§4.0): a manifest whose `git_head` is a moving target is not release
   evidence (P11.1). Commit or operator-snapshot the owned release files; record HEAD + dirty count.
2. **Cheap gates → heavy gates, documented order** (§4.2): `frontend-tsc` (fast, catches type
   regressions before anything else looks green) → `dse-pytest` (must *complete* — it has never
   finished this cycle) → `slice-family` → `parameterized` → `families-lint`. Each later stage
   presumes the earlier ones compiled the sources it will exercise; a red slice suite invalidates
   matrix rows attempted in the same window.
3. **`release-matrix` runs after `families-lint`** (§4.2 stage 6): same code path
   (`run_composed_family`), same host, same preflight; lint-level failures there would otherwise be
   rediscovered 30 minutes later inside the matrix.
4. **Archive before you evaluate** (§6): the matrix FAILs today; archive immediately anyway. The
   pin is what turns a FAIL into evidence of *which* rows failed and why; delay converts it into
   hearsay.
5. **Pin last, after everything exists** (`SHA256SUMS` + `PINS.md`): hashing an incomplete set
   invites silent omission.
6. **Only after the pin may any document quote rows** — and even then, not as "14/14", not as
   "mesh passes", only as the recorded per-row statuses.
7. What this order deliberately excludes: the physical half (P9 stages ≥ 37), fresh-environment
   rebuild (P11.4), functional diff across machines (P11.5), production review (P11.6), acceptance
   closure (P11.7). Those gate behind P9 notification and operator approval; this audit neither
   schedules nor certifies them.

---

## 8. What this audit did not verify

- No build, lint, sim, test, gate, or network call was executed; host memory/swap statements are
  quoted from docs, not re-measured; the live gateway was not probed (`GATEWAY-RESTART.md` is its
  last published state).
- Live store `design` shape vs. the frozen pin was assessed from the pinned file only.
- External receipts cited elsewhere (`/home/datavex/.cache/veritx-noc-lab/…/execution/runs/
  all14-native-rtl-20261110-v1-mesh8x8-xmx6g/receipt.json`) were not inspected; treating them as
  unusable P11 evidence stands regardless.
- `reproduce_slice.py` / `verify_slice.py` internals beyond the wrapper layer.
- Whether 740 porcelain entries include any operator-owned mid-edit files relevant to the runner —
  assumed yes; nothing was touched.

## 9. Recommended doc corrections — for operator decision, NOT applied

1. `INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md:382` — replace the kncube sentence with: "the kncube
   row is BLOCKED by construction (`KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING`);
   `kncube_lint_and_sim` is test-only; no general saved-request KNCube intent exists; the matrix
   cannot PASS until a kncube intent class + native equivalence checker land or the operator
   amends the fourteen-family requirement." Drop "fixed by routing kncube directly to
   `kncube_lint_and_sim`" and refresh "the 300 s Verilator timeout" to the current arm (§2.6).
2. `SEQUENTIAL-GATES.md:24` — replace "the release matrix row harness-routes it directly since
   2026-11-10" with the same BLOCKED-by-construction sentence; line 33 — the six recorded-PASS
   rows get the same "unsubstantiated until pinned under `runs/`" treatment the mesh row already
   carries.
3. `GATEWAY-RESTART.md:43` — drop "kncube harness routing" from the final-restart edit list (the
   edit did not land as described); keep the rest.
4. `INTENT-TO-PLACED-RTL-20261110-AUDIT.md` — C-08 remedy row: annotate rather than rewrite:
   "PARTIAL — the TopologyIntentError crash was removed by short-circuiting the row to BLOCKED;
   the prescribed `kncube_lint_and_sim` routing was never landed; what shipped refuses the
   torus-backed substitute; the remedy 'matrix re-run pending' remains undone."
5. `REMAINING-WORK.md` items 9–10 — item 9 stays valid with corrected framing ("re-run after the
   2026-11-10 fix" → "re-run to record the construction-bound BLOCKED row and the unproven mesh /
   dragonflynew rows"); item 10 additionally needs the fixture-authoring step (§4.3) before the
   smoke can claim to exist.
6. `complete_design.py:32` — remove or annotate `FAMILY_REQUESTS["kncube"]` (S-2/S-4); import
   `FAMILIES14` from `project_top_rtl` instead of re-declaring (S-1); add a test pinning the three
   copies equal — as a follow-up, not in this audit.
7. `SEQUENTIAL-GATES.md` vs `sequential-gates.sh` — either reorder the script to Rule 1 or move the
   doc; and name the P11 manifest (recommend: the runner's `contract_version: 1` manifest, archived
   per §6) so two formats stop coexisting silently.

## 10. Appendix — citations

`scripts/complete_design.py`: FAMILY_REQUESTS `:19-33`; kncube row `:32`; FAMILIES14 `:34-36`;
SROTA_KWARGS `:38-42`; `release_matrix` `:250-329`; kncube branch `:258-269`; `make_family_request`
`:144-202`; `generate_hardware` `:223-247`; `kncube_lint_and_sim` `:331-378`;
`hardware_evidence_status` `:389-400`; `completion_result` `:403-413`; `physical_stage` `:420-432`;
`--release` path `:452-460`; single-project `scope_note` `:552-554`.
`scripts/sequential-gates.sh`: preflight `:19-29`; stage table/default `:47-73`; release-matrix
stage `:56`; success manifest `:64-72`.
`project_top_rtl.py`: `FAMILIES14` `:4115`; `SUPPORTED_COMPOSED_FAMILIES` `:4116`;
`FAMILY_EXPECTED_ROUTERS` `:4122-4124` (mesh 64, torus 9, ring 64, gec_mecs 16, fly 48, qtree 21,
tree4 28, flatfly 16, srota 16, gec_hybrid 16, fattree 8, dragonflynew 36, kncube 9);
`KNCUBE_BLOCKER` `:4121`; `_require_single_endpoint_per_router` `:6372-6380`; lint 120 s `:6489`;
build 900 s `-O0` `:6500`; sim 120 s `:6503`; shared arms `:8788-8799, 8855-8866, 8922-8933`;
`run_gec_mecs_shared` `:8765`; `run_srota_shared` `:8832`; `run_hybrid_shared` `:8899`;
`gec_mecs_shared_params_from_request` `:6679`; `srota_shared_params_from_request` `:6719`.
`topology_artifact.py`: `STRUCTURED_FAMILIES` `:1180-1210` (kncube absent; dragonfly fields
`radix, group_count`).
`tests`: `test_complete_design.py:12-26,50`; `test_project_top_slice.py:350-401`
(`test_composed_family_lints_and_sims`), `:691-754` (kncube harness = torus-derived params);
`test_family_bad_design.py:34-36` (`cmesh` spelling).
`docs`: completion-plan checkpoint `:370-388` (esp. `:382, :384, :505`), §P11 `:272-281`, §6 `:284-307`;
SEQUENTIAL-GATES L1-50 (esp. L3, L12-17, L24-25, L29-33, L35-44); GATEWAY-RESTART L41-49;
REMAINING-WORK items 5, 6, 9-16; ACCEPTANCE.md §8 (Track-A 12) via completion-plan `:341`.
Binary corroboration: `scripts/__pycache__/complete_design.cpython-314.pyc` (2026-11-10 14:55).
