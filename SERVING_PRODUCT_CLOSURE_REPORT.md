# Serving Product Closure Report

Scope: `veritx-serving-workspace-hardened.html` (reference artifact) against the
29-phase refinement brief. Verdict at the end.

This report is written in normal prose because it is for humans and persists
outside the chat.

## 1. Final commit SHA

None. No commit was created. The artifact is **untracked** in git
(`git ls-files` does not know it), and the repository working tree is already
dirty on unrelated Studio files. Committing was out of scope for a single-file
fix and would have mixed unrelated changes.

## 2. Files changed

- `veritx-serving-workspace-hardened.html` (routing, authority, dead code)

## 3. Current branch

`integration/studio-reconciliation`

## 4. Browser/runtime defects found in the hardened prototype

Phase 0 was executed with real Chromium (Playwright 1.63, bundled browser), not
inferred from "HTML generated successfully".

Baseline result: **0 page exceptions, 0 console errors, all 31 rail routes
render**. The prototype is materially healthier than the brief assumes.

Defects that were real:

1. `go()` contained `if(state.page!==p||true)history.pushState(...)`. The
   `||true` forced a history push on every navigation, including during
   `popstate`, so back/forward produced duplicate entries.
2. `window.onpopstate = () => route()`, and `route()` called `go()`, which
   pushed again. Back/forward did not behave as history navigation.
3. Round selection used `history.replaceState(null,'','#rounds/'+round)`,
   bypassing the canonical route builder and writing a hash shape that does not
   survive refresh.
4. No `hashchange` handling; manual hash edits did not route.
5. `init()` called `route()` with no distinction between initial load and
   navigation, so the first load pushed instead of normalising the URL.

Fixed and verified (see §19).

## 5. Browser-derived scientific semantics removed

1. The round debugger computed "After" state and the round delta in the
   renderer: `r.tokens+18`, `Math.min(8,r.retired+1)`, `Math.max(0,r.active-1)`.
   That is browser-invented scientific state. It now comes from
   `gw.getRoundTransition(round)`, and renders `TRANSITION UNAVAILABLE` with a
   required-contract string when the gateway has no transition.
2. `const FIELD_CLASS = {...}` was a hard-coded browser field classification
   map. It was **dead code** (defined once, referenced zero times); rendering
   already used `gw.getFieldClassification()`. Removed.

## 6. Gateway contracts reused

Already present in the artifact as gateway-owned fixture views:

- `ResolvedFabricTopologyView.v1`
- `ServingCriticalPathView.v1` (`classification_status: 'DERIVED-BY-BACKEND'`)
- `ServingOverlapView.v1` (interval authority + overlap metric names)
- Preflight view shape: `check_id / status / blocking / authority /
  reason_code / explanation / recommended_action`
- A `gw` facade with `respond(view, binding)` that binds `experiment_id`

## 7. New contracts introduced

- `ServingRoundTransitionView.v1` (`before`, `after`, `delta`) — introduced
  only inside the artifact, as a gateway method. It does **not** exist as a
  backend contract.

## 8. Contract blockers left unresolved

Verified against the repository: `contracts/` contains only `srota` v1/v2
schemas, and `apps/studio/src/api/{index,types,client}.ts` exposes
`servingList`, `servingSubmit`, and `serving` only. The following are
**FIXTURE-ONLY** in the artifact and have no backend contract or Studio DTO:

causal attribution, critical-path classification, phase intervals, resource
time series, fairness thresholds, checkpoint metadata, structured logs,
regression policy, semantic field classification, preflight, experiment cost
estimate, expert attribution.

Per the brief's Phase 23, these should render truthful unavailable states plus a
documented contract blocker rather than be invented. In the artifact they are
labelled fixtures behind `gw`, which is the correct seam but not an authority.

## 9. Primary navigation after consolidation

**Not done.** The rail still exposes 31 destinations (the brief's core problem
#10). The existing rail already has five group headers (`Serving workspace`,
`Understand`, `Execution structure`, `Debug & reproduce`, `Record`), so the
consolidation is tractable, but it is a structural DOM change across a
minified single-line layout and was not attempted under this pass.

## 10. Canonical deep-link forms

Now used consistently for the objects that were broken:

```
#serving/{experimentId}                      page-level
#serving/{experimentId}/requests/{requestId}
#serving/{experimentId}/rounds/{roundId}
#serving/{experimentId}/collectives/{collectiveId}
#serving/{experimentId}/evidence/{evidenceId}
```

Verified: request and round clicks now produce these shapes, and refresh
restores `selectedRequest` / `selectedRound`. Invalid ids produce a typed
`NOT_FOUND` toast rather than an exception.

## 11. Experiment / run / attempt identity model

Partial. Experiments carry stable `sv-*` ids and the gateway binds
`experiment_id`. The explicit **experiment vs execution-attempt** separation
(Phase 13) is not modelled, and one fixture id (`sv-large1a2b3c4`) is clearly
synthetic.

## 12. Time-domain model

Present in fixtures: `SERVING_LOGICAL_CYCLE`, `MODEL_SERVICE_CYCLE`,
`NETWORK_BOOKSIM_CYCLE`, plus `ASTRA_TIME`/`WALL_TIME_DIAGNOSTIC` naming. No
cross-domain conversion identity, ratio, rounding law, or qualification is
supplied. Cross-domain comparison therefore has no conversion authority.

## 13. Large-run architecture

Not real. The large scenario is an `estimate` fixture (`estimated_requests:
10000`, `estimated_rounds: 812000`) plus a browser-generated round population
(`Array.from({length:150})`). There is no cursor-driven pagination over real
populations; `requestPageSel` shows a single page. Per Phase 8/22 this remains
the "browser holds the data" pattern.

## 14. Stale-binding guards

Partial. `gw.respond(view, binding)` attaches `experiment_id`. There is no
general identity-agreement check across `run_id`, `design_hash`, `fabric_hash`,
`machine_identity`, `request_trace_identity`, or `service_profile_identity`
before composing a view, and no `STALE / IDENTITY MISMATCH` render path.

## 15. Reproduction manifest fields

The reproduce page exposes source/vendor/seed/identity fields and
export/import/verify/reproduce actions. It has not been validated field-by-field
against the Phase 12 list, and byte-reproduction is not promised.

## 16. Replay / first-divergence authority

`gw.getDivergence(a,b)` returns `first_divergent_event` and
`divergence_class`, and the page distinguishes `INCOMPARABLE`. It is a fixture;
no backend diff contract exists.

## 17. Regression policy authority

`gw.getRegression(baseline,candidate)` returns a policy object with
`policy_id`, and the UI renders it as a backend policy object rather than
deciding thresholds. Fixture-only.

## 18. Adversarial scenarios exercised

Via the scenario switcher: default, incompatible-compare, EP-capacity refusal,
unknown-enum (`SOME_NEW_ENUM`), backend-unavailable (`BACKEND_UNREACHABLE`).
Confirmed present as fixtures.

## 19. Browser E2E results

Executed with Playwright + Chromium:

- baseline load: 0 page errors, 0 console errors
- all 31 rail routes: all render non-empty content, 0 errors
- theme toggle: light -> dark
- scenario switch: r05 -> r04
- request click -> `#serving/<exp>/requests/<id>` (canonical)
- round click -> `#serving/<exp>/rounds/<id>` (canonical)
- `history.back()` moved, `history.forward()` restored
- deep-link refresh `requests/6` -> `selectedRequest === 6`
- deep-link refresh `rounds/207` -> `selectedRound === 207`
- invalid round id -> typed `NOT_FOUND`, no exception

Post-fix regression run: 31 routes, 0 errors, no route with empty content.

## 20. Typecheck / build results

- Artifact: inline script passes `node --check` (syntax valid).
- Studio production build: **not run** in this pass.

## 21. Studio regression tests

**Not run.**

## 22. Confirmation on frontend semantics

No frontend simulator, compiler, scheduler, or routing algorithm was introduced.
One unresolved leak remains: the fabric topology fixture builds its **edges with
a browser function** (`edges:(()=>{const e=[]...`) rather than receiving a
resolved edge list. It sits behind `gw`, but per Phase 1 it is still a browser
computation of a scientific structure and should be replaced by a resolved
topology response.

---

## Remaining blockers

1. No backend contracts for the 12 surfaces listed in §8; Studio exposes only
   `servingList` / `servingSubmit` / `serving`.
2. No real `ServingStudioGateway` implemented in `apps/studio`.
3. Primary navigation not consolidated (31 destinations remain).
4. Large-run architecture is fixture-only; no cursor pagination.
5. No time-domain conversion authority.
6. No general identity-agreement guard / stale-binding render path.
7. Topology edge list still computed in browser code.
8. No committed browser E2E test suite or performance gate.

## Verdict

SERVING PRODUCT CLOSURE: FAIL

Blocked on backend contracts, the real Studio gateway, navigation
consolidation, and large-run architecture. Routing and the two confirmed
authority leaks in this artifact were fixed and verified.
