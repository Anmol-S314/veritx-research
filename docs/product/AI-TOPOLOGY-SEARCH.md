# Bounded AI-guided topology trial

The AI caller proposes a topology, reads real feedback, then proposes again.
The bridge makes **no LLM calls**; this first trial used the coding assistant
as the proposer. There is no unattended provider integration or Studio AI
button yet. Existing heuristic generators are not mislabeled as LLMs.

## Run one round

```sh
PYTHONPATH=tracks/t3-topology/dse python -m veritx_dse.optimization.topology_search \
  --base /path/to/canonical-v4-draft.json \
  --proposal /path/to/proposal.json \
  --run-root runs/ai-topology-search/my-study
```

The base may be a v4 request or a draft response containing `request`.
A proposal has exactly three keys:

```json
{
  "base_design_hash": "<canonical request.design_hash(), without sha256: prefix>",
  "topology": {"kind": "torus", "side_length": 7, "concentration": 1},
  "rationale": "Why this candidate follows from the previous feedback."
}
```

Read `feedback.json` before the next round. Reuse the same run directory:
refusals and duplicates consume slots; duplicates do not rerun simulation.
An interrupted round remains `SUBMITTED`, not evaluated. Remove a leftover
`.proposal.lock` only after confirming its process is no longer running.

## Boundaries

- Four proposals per study; backend timeout 30 seconds per execution.
- At most 64 routers/seats, 256 directed channels and network degree eight.
- Pilot kinds: mesh, concentrated mesh, torus, flatfly and explicit graphs.
  Other families are **not searched**, not declared unsupported globally.
- Workload, agents, requirements, dependencies, compute intent, physical
  context and NoC controls remain fixed. A stale base hash refuses. This
  pilot requires a declared network clock; it does not invent one.
- Explicit graph input contains only name, kind, nodes and links. Bandwidth
  and latency attributes are pinned to the declared link width and clock
  (one-cycle links); no invented physical layout, wire cost or power model.
- Canonical parsers/materializers check proposals. The existing real
  evaluator compiles, verifies, qualifies and executes. Unsupported cases
  carry no objective values. Successful metrics are extracted from
  consumption-time reverified authenticated evidence, not model predictions.
- The objective is simulated **network completion cycles**. This is not
  model runtime, hardware compute time, serving latency or physical signoff.
- No automatic adoption, optimality claim, multi-seed robustness claim or
  authoritative multi-objective frontier. Graph limits are not area estimates.

## First trial: pinned 32-agent Llama-8B / TP8 snapshot

Artifacts: `runs/ai-topology-search/p-9cd75d116fd4-20261008/`.

| Proposal | Outcome | Network cycles |
| --- | --- | ---: |
| 6×6 mesh, concentration 1 | Compiled; execution refused its VC subsets | unavailable |
| 6×6 torus, concentration 1 | Compiled; deterministic qualifier excludes even-side midpoint ties | unavailable |
| 7×7 torus, concentration 1 | Qualified, evaluated; requirements satisfied | 2,998 |
| Custom 32-node TP8 fanout tree | Compiled; execution refused its VC subsets | unavailable |

The original 1,057-node QTree was **not evaluated**. These results establish
an executable candidate, not an improvement over that QTree or global
optimality. The Studio draft changed during the trial; results remain bound
to the captured earlier request, not the newer draft.

The qualified candidate was copied to a separate Studio project for
inspection, never adopted into the source project:

- Project: `p-a845f3d63789` (32-agent snapshot)
- Revision: `p-a845f3d63789-r01`
- Published run: `01a11bdf-8476-71be-ab3c-5471aa3c73b6`
- Export: `qualified-torus-request.json` in the artifact directory

## Bounded Studio integration (assistant provider is server-owned)

`topology_search` remains the assistant-guided CLI. Studio now drives the same
pilot through a bounded background job, so a run is not tied to one shell:

- `GET /api/v1/ai-topology-search/capabilities` — provider readiness plus the
  frozen limits. A client MUST read this before offering a search.
- `POST /api/v1/projects/{pid}/ai-topology-search` with
  `expected_draft_design_hash` — pins the saved snapshot and starts the job.
- `GET /api/v1/projects/{pid}/ai-topology-search/{job_id}` — attempts with
  statuses, reasons, and consumption-time re-verified measurements.
- `POST /api/v1/projects/{pid}/ai-topology-search/{job_id}/candidates/{id}/adopt`
  — the only write path. It refuses when the job is not `COMPLETED`, when
  requirements were not satisfied, when the candidate is not evidence-backed,
  or when the draft moved after the search.

Configuration lives only on the server: `VERITX_AI_BASE_URL` (HTTPS, or
loopback HTTP), `VERITX_AI_MODEL`, and `VERITX_AI_API_KEY` when the endpoint is
not loopback. The key is never sent to the browser, never echoed in an error,
and never stored. Unconfigured, the capability answer is `configured: false`
with the reason, and the Studio button is disabled.

Measured evidence is never read from the search job's stored JSON. Every view
re-opens the evidence bytes, re-derives the result through
`verify_performance_result`, and re-proves the chain with
`verify_authenticated_backend_evaluation`; a tampered or transplanted proof
reports `EVIDENCE_INVALID` with no score and no adoption.

Compilation moved to the same owned-process seam:

- `POST /api/v1/projects/{pid}/compile-jobs` (202) — compiles the pinned draft
  in a separate process; only the parent publishes the revision, and only if
  the draft still matches the pinned hash and the revision identity agrees.
- `POST /api/v1/jobs/{job_id}/cancel` and `GET /api/v1/projects/{pid}/jobs?kind=COMPILE`
  — cancel a running attempt (process group killed) and recover active work
  after navigation. Cancelled, timed-out or stale attempts publish nothing;
  they do raise the project's revision sequence, so revision ids may skip.

The worker sets a 2 GiB address-space limit and is killed if its parent dies,
so an abandoned heavy compile cannot outlive the gateway. Cancellation and the
deadline are enforced by the parent, not by trusting the child.

### Live verification

Against the running gateway with a loopback fixture provider (32-agent QTree
base, revision sequence shared with the pinned earlier trial):

| # | proposal | outcome |
|---|---|---|
| 1 | torus 7×7 | **EVALUATED**, 2,998 cycles, `CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1`, requirements satisfied, adoptable |
| 2 | mesh 6×6 | UNSUPPORTED (trace execution) — no score |
| 3 | mesh 6×6 (repeat) | REFUSED — duplicate, not re-simulated |
| 4 | torus 6×6 | UNSUPPORTED — even-sided midpoint ties |

The draft stayed byte-identical through all four attempts and the adoption
step; no revision was created; the source project was untouched. A QTree
compile started as a job kept the health and Design endpoints responsive and
was cancelled without publishing a revision.

This establishes an executable, cancellable and explicitly adopted candidate.
It is not an improvement claim over the unevaluated QTree, not global
optimality, and not a model-runtime, area, power, or robustness result.
