# Copy/paste agent briefs

Use these with the [master plan](../RTL-12-OF-12-EXECUTION-PLAN.md), [work packages](WORK-PACKAGES.md) and [acceptance specification](ACCEPTANCE.md). Assign only the relevant package sections to a leaf; do not paste the entire previous session into every agent.

## 1. Orchestrator kickoff — hand this to the lead coding agent

```text
Implement the RTL twelve-family program to genuine 12/12 Track A acceptance.
Planning alone is not the task. Read:

/home/datavex/bruh/veritx-research/docs/research/RTL-12-OF-12-EXECUTION-PLAN.md

Then read its linked WORK-PACKAGES.md, ACCEPTANCE.md,
EXTERNAL-ARTIFACT-INTAKE.md and previous-session handoff.

Use Luna agents for independent owned implementation and fresh reviews.
The original12 are mesh8x8,torus8x8,cmesh,fattree,flatfly,srota8x8,
gec_mecs,gec_hybrid,qtree,tree4,ring,fly64.
Optional dragonflynew is separate. TrackB shared profiles are separate;
finish them for the complete M1-M8 program without inflating TrackA.

Preserve historical source/evidence and other agents' mutable ownership.
Create a new private integration root under the existing Constellation lab.
One shared-core writer, isolated family writers, one integrator, fresh
read-only reviewers, and ONE globally owned heavy execution slot.
Use at most six active agents while that configured limit remains in force.
Follow the host harness's delegation/protocol rules; do not recursively
spawn from ordinary leaves or switch to CLI/provider fallbacks.

Start by coherently intaking existing generated artifacts and recovering
one ACTUAL capped private build/RTL ring test. Do not regenerate the whole
catalog or make every preparatory lane finish before a safe ready cell runs.
Reuse solved JDK17/Chipyard/Espresso and corrected packet work.

Crucial source corrections:
- hybrid future-hop budget appears to be an exporter exact-decrement artifact,
  not native per-hop behavior. WP03 must resolve that model/hardware mismatch
  using strict progress, not invent packet behavior or weaken the theorem.
- OutputUnit counters reset to capacity, decrement on allocation and increase
  on return: they are FREE credits. Native hybrid uses used occupancy with
  port/drop-specific aggregation; derive it, don't wire free count directly.
- generic RouteComputer excludes route_tag; transported metadata does not
  automatically enforce shape/state. Bind the actual state representation.

Assign concrete production edits using WP00-WP14. Missing implementation is
work, not an external blocker. In particular, GEC-hybrid must actually wire
live occupancy/physical legal masks into instantiated ingress/transit allocation;
SROTA must implement enabled FIU/telemetry, not only a union of base shapes.

For every target, prove reachable physical-resource safety/progress, compare
actual emitted decoder/net behavior, execute the packet/credit campaign and
both approved captures, then independently verify the same-source evidence.
Correct all known final-review false accepts in proof/replay/reproduction.

Keep original resources/caps:4G cgroup,512M swap,3G JVM,1CPU/sbt task,
-j1 native/Verilator and finite1800s generation. Other agents' mf7g/6G
artifacts are useful intake candidates but not proof that the capped gate
passed. Coordinate live ownership; never kill foreign work or start a
competing heavy run during gaps between its JVMs.

Continue implementation/test/fix cycles until all original12 genuinely pass
or a concrete external authority/infrastructure decision blocks progress.
A bounded task batch or quota checkpoint is NOT completion. Preserve exact
remaining tasks in a durable handoff if you must stop.

Every progress report: actual qualified-row count; newly executed hardware
commands/results; merged production changes; critical-path blocker/next job.
No passing percentages from child count, files generated or Python fixtures.
```

## 2. Initial dispatch and useful parallelism

Use ownership roles, not eight independent writers modifying the same files.

### Initial six slots

| Slot | Assignment | Immediate checkable product |
|---|---|---|
| 1 | Integrator/WP00 | Coherent intake and ownership; then ready job coordination |
| 2 | Build/execution/WP01 | Actual private runner load/build plus ready ring cell |
| 3 | Native/WP02 | Exact profile/choice/occupancy/control contract gaps |
| 4 | Core/WP03–WP04 | State/progress correction and real production seam/tests |
| 5 | Proof/WP05 | Arbitrary-proof rejection and independent certificate verification |
| 6 | Harness/WP07 | Reuse actual ring path; prepare real generalized traffic/observability |

These are task roles, not a mandatory synchronous barrier. The integrator can release its slot after baseline integration. As prerequisites stabilize, schedule family production work, correspondence and fresh review in freed slots. Heavy commands still go through one owner even when several leaves are active.

### Next independent production work

- GEC owner: WP11, especially actual hybrid datapath.
- SROTA owner: WP12, actual control/FIU and capped emission.
- Baseline/cyclic/multipath owners: WP08–WP10 in isolated scopes.
- Correspondence owner: WP06, actual generated decoder/net observations.
- Replay owner: WP13, actual accepted byte stream through the compiled harness.
- TrackB owner: WP15 with shared heavy queue; generic scheduler unit test can run before full profile binding is done.

Do not wait for every family before proving the first end-to-end row. Do not freeze the final release until required production changes have been integrated.

## 3. Leaf implementer assignment template

```text
You own [PACKAGE], exclusively in [PRIVATE WRITE SCOPE], from baseline
[SNAPSHOT ID]. Read the relevant sections of WORK-PACKAGES.md and
ACCEPTANCE.md plus the exact existing files listed in your package.

Goal: [one concrete production behavior and its acceptance condition].
Shared inputs/external generated artifacts are read-only. Copy necessary
source/build inputs coherently into your owned scope and record hashes.
Importing source privately is allowed; writing the original is not.
Do not spawn more agents or use an alternate agent/provider/CLI path.

Read the actual caller and instantiated production module before edits.
Choose the smallest connected edit that satisfies the goal. Reuse and deepen
existing modules. Put each concept, ordering rule, special case, validation
and derived value in its one owning module. Apply the deletion test: merge
trivial forwarding away; retain modules that keep real complexity out of callers.
Do not create a module per work package or hide a parameter bag behind a context.

Inventory every caller before shrinking the interface. Remove derived,
constant-across-callers and unread parameters/flags; keep genuine runtime inputs.
Move every in-scope caller/test to the one new shape and delete superseded
entrypoints, wrappers, fallback branches and duplicated caller logic completely.
Preserve supported behavior and historical evidence, not obsolete interfaces.
A disconnected model/adapter, new status file or future command is not the
requested implementation.

Add a regression that fails for the actual missing behavior and exercises
production types/path. Run lightweight checks yourself. Submit exact real
Scala/RTL/build/simulation commands to the execution owner; do not launch
competing heavy work. A compiler/test that has not run stays NOT_RUN.

Return: changed production files and bounded patch; baseline and profile;
actual focused check commands/exits/raw logs; negative regressions;
exact ready execution job and needed artifacts; remaining conditions.
Never claim the family passes from component/model tests alone.

If the edit appears broad, identify the smallest connected production seam
and implement it or request one specific architecture decision. Do not
silently downgrade the assignment to another Python-only model.
```

### Additional GEC-hybrid instructions

```text
The integration target is real and generic:
CatalogRtlHybridExport.CandidateNoCTop -> NoC -> Router ->
IngressUnit/InputUnit/RouteComputer -> VC allocator -> OutputUnit.
No separate existing GEC-hybrid Router class is required to modify this.

Modify PRIVATE copies of shared source through the shared-core owner or
its agreed extension seam. Bind actual legal physical output/VC masks and
native-equivalent USED occupancy, including port/drop aggregation. Reuse
or correct the existing selector, derive arithmetic widths, instantiate it,
and test actual allocation choices under live credit changes/stalls.

A model plus an unchanged CatalogRtlHybridSelector.scala snapshot does
not satisfy the assignment. Do not execute the old RESULT command writing
full-connectivity-v1/src or /tmp/opencode; use private build/output roots.
```

### Additional SROTA instructions

```text
Preserve configured64routers/896TrackAtaplinks/4VC/depth8/128payload,
actual enabled path/plane/router controls and rank semantics. Base arithmetic
mask factoring is useful but not the configured FIU/telemetry implementation.

Use native networks/srota.cpp, routers/srota_router_d.cpp and effective
config to implement real injection choice, epoch/telemetry/reset behavior,
then bind it to committed packet selection. Preserve all modes enabled by
the selected profile; do not silently replace it with a static forced shape.

Measure the actual failing compilation stage and apply proven factoring or
coherent per-router lowering. A live JVM, an inventory file or copied router
partitions does not prove a completed connected fabric.
```

## 4. Execution-owner job template

```text
Execute [ONE NAMED PHASE/TARGET/PROFILE] from immutable snapshot [ID].
Read WP01 and the relevant acceptance section. You own [FRESH RUN ROOT].
No write to shared/historical source/builds or another owner's outputs.

Inputs: [exact source/build/top/helper/harness/config/capture manifests].
Command: [actual argv and cwd, not a placeholder].
Expected products: [named files/observations and validation predicates].
Prior review: [concrete code/preflight results and unresolved limits].

Acquire cooperating heavy lock and inspect current FOREIGN whole-queue
ownership. If occupied, return exact scheduling blocker and ready job;
no polling/sleep loop, process signaling or competing execution.

Use original4G/512M/3G/1CPU/-j1/finite-time isolation. Use established
background execution with native terminal notifications. Record actual
tool result, argv/env/cwd/tool/input hashes, logs, exit/signal and products.

Reject OOM/exception/incomplete/stale evidence even exit0. Preserve failed
runs. Diagnose concrete root cause; repair only your authorized narrow
runner/harness scope or return to the production owner. Never raise caps,
reduce profile or suppress scientific checks to obtain success.

Publish RESULT.md and machine-readable terminal evidence in your OWNED
run root. Then request independent evidence review. The phase is complete
only when its actual expected products validate; it is not the entire row.
```

A diagnostic first ring run need not already have its final source-reproduction certificate; label the limitation. A final row must have it. Likewise the generic shared-scheduler SV unit test can be a useful scoped run before full TrackB bindings exist. Missing unrelated final gates are not reasons to prohibit the first controlled component execution.

## 5. Fresh code-review brief

```text
Review only; no edits, agents or heavy builds. Scope [FILES/PATCH] from
baseline [ID]. Goal [PACKAGE ACCEPTANCE]. Read caller/production context,
not only helper code or RESULT prose. Provided actual checks: [EVIDENCE].

Find concrete wrong behavior, uninstantiated code, false coverage/proof,
wrong source/profile binding and vacuous tests. Distinguish actual code
readiness from final hardware qualification. Do not require a previous
hardware PASS to authorize the first controlled execution; do identify
specific pre-execution defects. Preserve all original scientific gates.

Return APPROVE_BOUNDED or CHANGES, one precise finding per item with
file:line, failing behavior, minimum production fix and regression.
No open correctness issue may be silently converted to approval because
review-round limits were reached. Component approval is not row PASS.
```

## 6. Independent evidence-review brief

```text
Read only. Verify [TARGET/PROFILE/SOURCE] against ACCEPTANCE.md using actual
raw runner/tool evidence and artifacts. Recompute hashes and independently
validate certificate contents, native/physical coverage and exact output
semantics. Author-generated JSON success fields are not proof of execution.

Check the SAME snapshot/profile produced the actual top/helper/binary,
proof, decoder/net observation, packet/credit tests, both accepted captures
and fresh reproduction. Report precise PASS/FAIL/NOT_RUN per column.

Reject missing required rows/resources, partial aliases, egress-only
internal-coverage claims, synthetic fixtures as hardware, stale binaries,
wrong accepted capture, arbitrary proof bytes and copied fresh-run trees.

Return row qualification only if the full conjunction passes. Explain
which exact product/check blocks it otherwise. Preserve bounded useful
results without inflating them into all12/hardware/PPA claims.
```

## 7. Session/quota handoff template

```text
Goal: original12 genuinely pass; current count [N/12 with evidence].
Current integrated snapshot/profile identity: [...].
Actual newly executed commands/results: [...raw paths...].
Production patches merged/unmerged and owner scopes: [...].
Final review findings still open: [...].
Heavy ownership/queue state, observed timestamp and exact ready next job: [...].
Next three concrete actions, each with acceptance command: [...].
Artifacts that are historical/generated/component-only: [...].
No original source/evidence reset/stash/clean; no new cap or protocol authority.
```

Preserve the handoff and actual evidence locally before quota exhaustion. Completing a bounded batch does not end the original program; leave the next production/execution action explicit.
