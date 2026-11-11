# Prototype backend completion — current status

## Delivered and tested

1. **Disposable live backend loop:** create a test project, select workload, validate/save a canonical draft, compile, edit/save/compile through the UI, evaluate, inspect metrics, recover selection after reload, download a real evidence JSON document, run a two-configuration optimization, and delete the disposable project **through the UI typed-id confirmation**. Existing project IDs are preserved.
2. **Live backend surfaces:** Explore submits bounded grid studies and reads job/results records. Verify reads the capability registry and tagged capability gaps plus a dedicated project-obligations register (`GET /api/v1/projects/{id}/obligations`, derived server-side from the draft, latest active run, and declared product limits — distinct from capability gaps). Deliver downloads real revision artifact-chain manifests and evidence indexes. These are reference/JSON exports, not RTL or physical implementation.
3. **Structured draft editing:** address ranges (canonical `size`/`target_agent_idx`, hex or decimal base), workload collectives, requirements, dependencies, and explicit `TopologyIR` graphs (`custom`/`anynet`, undirected `src dst` pairs, mandatory global link spec) are editable via structured controls. Advanced JSON is restricted to a `compute` object only. Gateway canonicalization precedes save. Any edit invalidates the preview. Saves use the canonical document, and the atomic server-side compare-and-swap (`expected_draft_design_hash` checked under the store lock; stale writes get 409 `STALE_REVIEW`) blocks conflicting writes.
4. **Evidence inspection:** filter/select the JSON documents returned by the evidence endpoint, inspect contents, download JSON, and download **original artifact bytes** with whole-file digest verification (manifest vs `x-content-sha256`). Decoders cover verified injection schedules (`workload.trace`) and executed first-hop realization tables (`routing.dump`, never a full packet path). Producer identity, original artifact sizes, and recorded digests remain distinguishable.
5. **State hardening:** generation guards reject stale project/run/job responses; job polling is sequential; cancellation refreshes job status; selection recovers from session IDs; active evaluation jobs are rediscovered. Completed jobs select their published run. Unknown job status blocks duplicate study launches. Project failures no longer silently show sample data. Covered: refused save (409 reason shown, editor stays open), client-timeout reads, mid-job reload recovery, typed-id UI deletion, and late-response race rejection.
6. **Backend comparison authority:** the comparison panel renders `GET /api/v1/compare` verdicts only — no browser gating arithmetic. Deltas require shared workload identity, backend, backend **configuration hash**, **measurement window**, **product metric definitions** (`product/metric_contracts.py`; unknown keys are explicitly not comparable), and a QUALIFIED evidence chain. The frontend `comparisonGaps` module was removed.
7. **Job logs:** in-process jobs (evaluation, optimization) now append state transitions to `job-work/{id}/worker.log`; process jobs log worker pid and exit state. Served via bounded `GET /api/v1/jobs/{id}/log` (offset/max_bytes, `eof` semantics) and an SSE tail (`/log/events`), rendered in `JobEvents` beside the state stream. Logs are operator diagnosis, never evidence.
8. **AI runtime against a local mock:** a loopback OpenAI-compatible stub verifies the real HTTP path — connection, model identity, consent gating (no consent, no transmission), workload translation, and hash-pinned adoption — plus invalid-envelope refusal (`tests/test_ai_provider_mock.py`). No credentials are read or changed in the browser. A real external model remains unverified: it needs owner-supplied `VERITX_AI_BASE_URL`/`VERITX_AI_MODEL` and explicit policy approval before confidential designs are sent.
9. **Deterministic optimization adoption:** `use_candidate` requires the pinned draft hash under the store lock and records draft history; adoption of uncompiled/unknown candidates is refused.

A real failure discovered during testing was fixed: HTTP 200 does not imply compilation success. `UNSUPPORTED` compilation results now show the refusal instead of appearing successful. The real workload requires 72 endpoint seats; a 4×4 mesh was correctly refused, and the successful test used a 9×9 mesh.

## Runtime closure update

10. **Optional general agent runtime:** `/agents/capabilities` reports an OpenAI-compatible server transport or owner-approved ACP-v1 stdio transport. Chat is memory-only and tool-free; draft context is opt-in and hash-pinned. Workload translation returns a schema-validated, non-executed proposal; only workload/compute sections can be changed, while source references and all other design intent are preserved. Adoption is explicit, hash-pinned, revalidated under the store lock, and archives the displaced draft. Tests cover consent, stale hashes, denied ACP tool/permission requests, timeout/termination, private-thought exclusion, invalid proposals, and adoption. The ACP subprocess is **not OS-sandboxed**; enabling it requires explicit owner trust and must only use a suitably isolated local runtime.
11. **Job events and artifact bytes:** bounded job-state SSE and log SSE endpoints exist; these are records/logs, not backend console capture. Original artifact downloads validate manifest path/size/digest and the browser verifies returned bytes against digest metadata. Injection trace decoding is limited to the supported recorded formats.
12. **Restart and store preservation:** gateway was restarted after confirming no active jobs. All 26 project IDs present after the browser suite were preserved; no disposable `prototype-smoke-*` project remains. The restarted gateway reports `stale=false`.

## Remaining — not represented as complete

- **Real-model verification:** blocked on owner configuration and policy approval. The currently configured runtime is unconfigured; no confidential project data was sent externally. ACP requires explicit process trust and does not itself provide an OS sandbox.
- **Hardware outputs:** RTL generation, ASIC/FPGA implementation, target qualification, and physical signoff remain separate engineering capabilities, not implied by manifest export.

## Reproducible checks

```sh
npm --prefix apps/studio/prototype run build
npm --prefix apps/studio/prototype test
npm --prefix apps/studio/prototype run test:e2e
# Explicit opt-in; creates/deletes its own project and runs real backends:
VERITX_LIVE_TEST=1 npm --prefix apps/studio/prototype run test:e2e -- tests/live-backend.spec.ts
```

```sh
cd tracks/t3-topology/dse && python -m pytest tests/test_prototype_backend_closure.py tests/test_agent_runtime_closure.py tests/test_ai_provider_mock.py -q
```

Latest verification: frontend build passed; **134 unit tests passed**. The broad browser suite had **62 passed, 2 failed, and 12 skipped**. The failures are stale expectations in `tests/intent-workspace.spec.ts` (expects an old `Engineering decision loop` navigation) and `tests/prototype.spec.ts` (catalog addition persistence assertion); these are not ACP/runtime tests. The explicit live-backend browser suite was attempted twice; its UI phase still expects the removed `clock_freq_mhz` editor control and failed before evaluation. Its `finally` cleanup passed, and no disposable smoke project remains. Backend checks: the latest focused closure/evidence rerun passed **44 tests**; product regressions passed **39, with 1 skipped**. The initial product regression command exceeded its timeout; rerunning with a longer deadline passed. The Vite >500 kB chunk advisory remains.

Tests live in `tests/backend-hardening.spec.ts`, `tests/live-backend.spec.ts`, `src/artifacts.test.ts`, and `src/model.test.ts`, alongside the backend suites. The Vite >500 kB chunk advisory remains.
