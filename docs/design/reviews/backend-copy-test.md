# Backend-connected prototype: testing and copy cleanup

## Changes

- Shortened 37 repetitive notices across Design, Workloads, Analysis, Explore, Verify/Deliver, and Agents. Kept requirement-relaxation, missing-evidence, revision-scope, disconnected-agent, and destructive-action warnings.
- Header distinguishes **Gateway project** from **Sample project** instead of labelling live data illustrative.
- Live projects no longer display the sample draft's address-overlap count: **Address checks not run**.
- Jobs drawer uses a live-job-aware heading instead of always claiming there are no backend jobs.
- Removed the obsolete Environment claim that the prototype cannot connect to the gateway.

## Proof

- Production build passes. Vite reports the existing >500 kB chunk advisory.
- 18 unit tests pass.
- 21 Playwright tests pass, including mocked backend draft validation/save, evaluation plan gating, job tracking, published-run selection, and offline behavior.
- Read-only real-gateway browser smoke: loaded an existing project, traversed 21 Design, Workload, Analysis, Verify, and Jobs routes at 1440×900. No page errors, failed gateway responses, horizontal overflow, or mutation requests observed. Run selection uses the existing project's default historical run.
- Existing route checks also cover 1440×900 and 1280×800.

## Boundaries

Real-gateway writes, compilation, evaluation launch, deletion, and cancellation were not executed against existing projects. Those operations were exercised with mocked responses in the browser suite. This is not proof that every backend configuration or solver is correct.

Existing backend integration and unrelated working-tree changes were preserved.
