# P0 Foundation Seal — consolidation campaign closed

Mode change: we stop behaving like a migration project and start
behaving like a compiler project. P0 is sealed; do not reopen
migration architecture. The next campaign is P1 Fabric Compiler
Productization (promotion and unification of existing compiler
capability — not a greenfield compiler).

## Seal

```text
base                    1412ab50  (M1 through the M1.5 dispatch proof)
final                   ddaafa67  (M6 persistence vocabulary + battery record)
full battery            3716 passed, 40 skipped, 9 xfailed
known failures          5 (all QUALIFIED_BACKEND_UNAVAILABLE, see below)
failed-node delta       0 (name-identical to the M0.5 baseline set)
new tests               +32 vs M1.5 (+79 vs M0.5d clean baseline mapping)
canonical writer        yes (workloadgraph / messages v2 / traffic v2)
legacy readers          historical only (frozen, no production writers)
performance package     promoted (wavee/ deleted)
```

Battery command: `cd tracks/t3-topology/dse && python3 -m pytest tests
-q --tb=no -p no:cacheprovider` — 145s in the provisioned worktree.

The 5 known failures (unchanged since M0.5c; missing unbuilt
backend binaries, correct fail-closed refusals):

```text
test_astrasim_spine_contract::test_dangling_astrasim_bin_warns_and_falls_back
test_doctor::test_real_quick_battery_runs_offline_and_fast
test_pipeline_preflight::TestTimeloopBinPreference::test_real_repo_vendored_binary_exists
test_serve_contract::test_serve_end_to_end_analytical
test_serve_fidelity::test_serve_emits_structured_result
```

## Vocabulary law (wire/history vs live product)

Sealed identities are NEVER renamed cosmetically — renaming them
would fork content hashes or invalidate historical verification,
which is vandalism disguised as tidying:

```text
sealed hash tag "srota/wavee/..."        REMAINS (content identity)
historical persisted key "wave_d"        REMAINS (result/plan identity)
historical persisted key "wave_e"        REMAINS (result/plan identity)
historical store kinds waved*/opgraph    REMAIN READABLE (frozen readers)
```

Live product vocabulary (new writes, class names, packages) uses the
canonical names — these MUST NOT carry Wave-D/E naming:

```text
public class WaveEPerformanceModel       GONE (-> PerformanceModel)
new API parameter wave_d                 GONE (none remains)
new runtime package wavee/               GONE (-> performance/, core/time)
new store kinds waved*/opgraph           GONE (writers deleted in M4)
temporal workload store kind             performance (was waveeworkload)
```

Recorded deviations (each in its milestone commit): the old workload
authority classes stay frozen (authoring + history need them);
`canonical_graph.py -> graph.py` waits on P1 CompileRequest
authoring; inline block keys stay sealed.

## Known non-blocking defect (does NOT reopen P0)

`make lint` fails on missing `tracks/t3-topology/scripts/compare_bars.py`
(pre-existing, unrelated to P0 files). If `make lint` is an official
gate, file one small repair issue. Do not touch P0 for it.

## P1 entry

Next deliverable: `docs/FABRIC-COMPILER-AUTHORITY.md` (P1.0 audit) —
classify every existing compiler type as AUTHORITATIVE / IR / POLICY /
BACKEND PROJECTION / RESEARCH / DUPLICATE / LEGACY /
BROKEN-INCOMPLETE, and answer: which exact object owns each resolved
fabric semantic. Then promote E1–E5 `CompileRequest` as the sole
product request; resolve TopologyIR vs TopologyArtifact; build one
deterministic mesh pipeline.
