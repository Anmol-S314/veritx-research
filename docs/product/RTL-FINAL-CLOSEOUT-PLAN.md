# RTL final closeout plan

## Goal and authority

Finish the release defined by `INTENT-TO-PLACED-RTL-COMPLETION-PLAN.md`: a saved request produces its exact connected, tested and legally placed network block; all fourteen required topology families qualify; the browser drives the real flow; a fresh environment reproduces the delivery.

This is an execution checklist for that plan, not a reduced replacement. Preserve unrelated dirty-tree changes. A refusal is correct behavior but does not close a required release feature. Small designs diagnose; they never replace full-size acceptance.

## Verified starting point

- Acceptance revision: `p-fd7e5e31be77-r02`, design hash `ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0`; retain 74 agents/endpoints, 81 routers, 8 VCs, 162 shared wires and 128-bit flits.
- Latest local checks: prototype units 325/325; focused prototype Playwright lifecycle/readiness tests 8/8; browser hardening 23/23 before the additional snapshot test; snapshot browser regression 1/1; TypeScript/prototype build clean; pinned release/workload/address/GEC contract tests 27/27. These are not RTL qualification.
- Exact high-address entry and legacy snapshot restoration now have regression coverage. Do not reopen these without a failing witness; complete live save/reload/export coverage in the final workflow gate.
- The 36-router credit baseline has a recorded simulation pass in `PROGRESS.md`. It is not evidence for the selected 81-router implementation.
- Selected 81-router emission attempts 1–3 were blocked before execution by other heavy builds. Bounded queued task `b28707ffb` was launched subsequently; consume its terminal receipt before any replacement run. Do not infer the scheduler succeeded.
- Historical reports disagree about family readiness, platform, counts and current failures. Treat them as discovery pointers; bind every closure below to current source and raw artifacts.

## Three decisions required once

1. **Platform:** approve the actual implementation platform, or provide an accessible platform/library set matching the requested technology and its license conditions. Sky130A may be a separately labeled diagnostic target; it cannot satisfy a 7-nm request. Availability must be checked, not assumed impossible or silently substituted.
2. **Physical constraints:** approve clock(s), corners, die/core limits, pins, placement restrictions and external macro assumptions. Reuse saved declarations where sufficient; ask only for genuinely absent inputs. Do not relax timing or shrink buffers to obtain a pass without approval.
3. **Exclusive build ownership:** arrange one heavy-build owner/queue used by every active hardware lane. Existing guards remain mandatory. Repeatedly attempting to catch a gap between independent build loops is not a reliable scheduling solution.

These decisions block physical completion, not safe source fixes and lightweight verification. Placement is the required finish line; routing/GDS/signoff are additional gates only if advertised. A router slice cannot replace the full delivered block.

## Execution order

### 1. Freeze the remaining obligations and capture evidence first — P0, P10.6, P11.1

**Action:** reconcile each P0–P11 acceptance ID into PASS / OPEN / BLOCKED / NOT_RUN against current code. Attach source/input/tool hashes and a raw result path to every PASS. Record ownership for source and output areas. Pin owned release inputs without sweeping other writers' changes into a commit.

Reuse the private runner, existing job artifacts and root manifests. Every execution records argv, cwd, start/end, exit/signal, useful stdout/stderr, resource limits, input/output hashes and the earliest failed gate. Record queued/blocked separately from compiler failure. Restore reliable pytest timeout enforcement or wrap stages with real process deadlines.

**Acceptance:** a deliberately failed job and an interrupted job retain usable logs and cannot publish successful artifacts; the frozen target and all fourteen named families appear once in the checklist; every required input/tool/license has an identity or precise blocker.

### 2. Close intent and workload trace-through — P1, P2

**Action:** finish the per-field owner/consumer inventory. Cover V5 hardware-base binding, stable named-agent-to-endpoint identity, protocol/version/features, widths/IDs/bursts/outstanding limits, permissions, clocks/resets/power, IP materialization and fixed/locality placement intent. Preserve explicit versus derived values and recheck overrides. Finish missing consumers; retain precise refusals until implementation exists.

Verify approved workload bytes, rank groups, dependencies, memory ownership/extents/repeats/completion, installed engine readiness, executable identity and stale-result rejection. Keep network cycles, schedule exposure and calibrated application runtime separate. No invented memory traffic, scores or physical estimates.

**Acceptance:** directed mutation tests show each offered input reaches its intended hardware/configuration/constraint consumer or refuses before expensive work. All required release fields have consumers, not just refusal tests. Browser/API save/reload preserves high addresses and policy/domain values. Candidate adoption creates a reviewed revision and invalidates affected evidence.

### 3. Finish the selected full-size vertical hardware path — P4–P6

**Action:** consume the queued emission result first. On a queue blocker, coordinate ownership; on a real elaboration/OOM/compiler error, use its receipt and first failing log. Preserve full-size dimensions, VC/buffer/packet semantics and shared-wire bandwidth. Stay within approved resource caps; no hidden workload reduction.

Connect actual ingress adapters → trusted requester/access decode → ordering/outstanding → crossings → packet/credit network → destination → response. Use the compiled GEC credit implementation, not an unrelated composed-family wrapper presented as the selected hardware. Reuse existing router/adapter owners.

**Acceptance:** selected 74-endpoint project emits a connected top with independently checked hierarchy counts and identities. Real requests/responses preserve payload, IDs, errors, partial beats and permissions under stalls; long packets, delayed credits and reset balance accepted/delivered/flushed/outstanding counts. Emission alone does not close this step.

### 4. Complete fourteen exact family bindings — P3, remaining P4/P6

**Action:** through the same builder, close independent injection/ejection at every concentrated or tree/fly/fat-tree seat; general saved-request KNCube selection; Dragonfly group/global-port/gateway binding; and any remaining family shape/VC/tap checks. Revalidate current implementations before assuming an old gap remains.

Exercise real native controls: torus/ring boundaries and direction commitments; flatfly orders; legal tree uplinks/ancestors; GEC ordered taps and tap-specific credit pools; hybrid real occupancy and express tie rule; SROTA direct/Valiant state, ranks/islands, flow cache, telemetry, enabled side buffers and separate planes. No spanning-tree or mesh substitution.

**Acceptance:** fourteen unique request→compiled-design→connected-hardware rows, each with endpoint maps, graph/resources, widths/buffers, requested controls and directed distinctive tests. A blocked required row leaves the step OPEN. Debug harness-only construction cannot satisfy saved-project support.

### 5. Prove routing/resource legality on emitted implementations — P7

**Action:** compare independently checked native relations with the actual instantiated decoder/policy state. Include incoming link/VC, destination, committed shape/leg/rank, locks, side buffers and per-tap pools. Close bad-design witnesses currently labeled NOT_COVERED. Validate certificate contents rather than trusting status/hash fields.

**Acceptance:** every reachable legal routing state/choice is covered; wrong wrap/turn/rank/tap/VC/seat/edge and tampered certificates fail with witnesses. A mutation of production routing logic makes the comparison fail. Topology legality is not mislabeled fairness or payload proof.

### 6. Run the full hardware traffic qualification — P8

**Action:** qualify every declared family profile plus the unchanged selected project. Run ordered endpoint pairs including local seats; packet lengths 1, 2, 5, B+1, 2B+3; all legal route choices; uniform/transpose/permutation/hotspot/same-output traffic at seeds 1/7/42; sink/credit/tail stalls; packet interleaving; reset during traffic; and approved real captures.

**Acceptance:** payload/byte/packet/flit reconstruction and causal order match; accepted = delivered + explicitly flushed + outstanding, with zero outstanding after drain; each physical credit pool balances. Byte/route/credit/executable/certificate corruptions fail the relevant checker. No unrun, skipped or refused required profile counts toward 14/14.

### 7. Synthesize and place that exact verified hardware — P9

**Action:** use the approved platform/constraints and complete production source list. Resolve queue-memory realization without changing requested usable capacities; add macros only with real timing/physical models. Fix latches/frontend issues, establish mapped equivalence or explicitly bounded gate-level behavior, then floorplan/place and measure timing/congestion/clock constraints.

Reuse `scripts/librelane-spike/` machinery where appropriate, but generate configuration from the verified project; an old static slice configuration is not the selected design. Repeat affected functional gates after hardware or memory changes.

**Acceptance:** source/top/netlist/constraint/platform hashes join the same manifest; no unconstrained relevant paths, unmapped cells, illegal placement, overlap or invented macro footprint; declared placement/timing limits pass. Export netlist, placement, SDC and raw reports. Do not claim routed timing, DRC/LVS or GDS unless those separate runs pass.

### 8. Wire the real completion runner and product lifecycle — P6.5, P10

**Action:** extend `scripts/complete_design.py` and existing service/job/UI owners; do not introduce another evidence system. Wire immutable revision inputs, exact family dispatch, real hardware/physical invocations, hash-checked resume, cancellation, failure recovery and invalidation.

Confirmed implementation gaps to fix: `physical_stage()` currently records NOT_RUN even with `--with-physical`; single-project family dispatch defaults non-mesh/torus requests to `mesh`; hardware stage PASS is recorded without deriving it from all lint/simulation/scenario outcomes; final success semantics must reject required BLOCKED/NOT_RUN results. Verify these against code before changing them.

**Acceptance:** a normal live-browser project reaches verified RTL and legal placement; readiness comes from backend artifacts. Duplicate submit, cancel, timeout, restart, stale revision and cross-project artifact tests pass. Failed/blocked/incomplete required stages return non-success and never publish hardware-ready. A clean-output rerun works without manual file edits.

### 9. Freeze, rerun, review and reproduce — P11

**Action:** stabilize owned changes; run backend, production UI, prototype unit/build/browser gates and the complete fourteen-family hardware campaign serially where heavy. Rebuild the selected project in a fresh output environment with declared prerequisites. Review code plus raw evidence; fix findings and invalidate/rerun affected dependents.

**Acceptance:** every original P0–P11 ID closes with evidence; no required skip/blocker; exact selected project and all fourteen families pass their required checks; fresh reproduction matches functional outputs and accepted physical results. Deliver one archive/root manifest containing intent, RTL, tests, constraints, netlist/placement, logs, hashes and reproduction instructions. Redistribute licensed files only when permitted.

## Work ownership and parallelism

- **Intent/workload owner:** step 2, with one writer for model/compiler changes.
- **Hardware owner:** steps 3–6; serialize shared router/top-builder edits. Finish selected-path proof before multiplying full campaigns.
- **Physical owner:** prepare platform/constraint validation independently; consume frozen verified hardware at step 7.
- **Product owner:** lightweight runner/job/UI work can proceed against explicit artifact contracts; live final acceptance waits for real hardware/physical outputs.
- **Evidence/release owner:** reconcile status, retain artifacts and maintain the dependency ledger.

These are ownership boundaries, not authorization to launch agents. Parallel source work requires isolated ownership; all heavy builds use one shared queue. Existing sources remain authoritative until reviewed migration passes.

## Invalidation and stop rules

- Router/policy/buffer/packet/graph changes invalidate affected P7/P8 and physical evidence.
- Adapter/access/order/CDC changes invalidate transaction, crossing and affected physical evidence.
- Platform/clock/constraints changes invalidate physical evidence; changed hardware repeats functional gates.
- Producer/tool/workload changes invalidate their downstream measurements; files existing on disk never imply success.
- After two failed variants, test the underlying assumption rather than repeat the build. Preserve the failed evidence.
- Report a genuine missing external input once, with exact required decision/file and safe resume point. Continue only work independent of that input.

## Plan critique incorporated

1. **Missing scheduling prerequisite:** three queue-blocked emissions are not RTL failures; exclusive heavy-build ownership precedes another expensive campaign.
2. **Unverified success assumption:** the existing completion script is not a complete physical runner. Its NOT_RUN/dispatch/verdict behavior must be repaired, not promoted by documentation.
3. **Scope trap:** small-router passes, source tests and correct refusals do not close the selected full network or all fourteen families.
4. **Simpler path:** finish one exact selected vertical path using existing owners, extend the same builder, then qualify the matrix; no second compiler, runner or evidence database.
5. **External blocker:** the physical target requires explicit inputs; do not promise a finish date or change technology to make the plan appear complete.
