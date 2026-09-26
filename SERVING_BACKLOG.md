# Serving: backend capability vs Studio exposure

Method: inspected the live gateway and the real evidence document from a
completed run (`sv-17412227dec2`, 8 requests, 507 rounds, COMPLETED), fetched
from `GET /api/v1/serving/sv-17412227dec2`.

Source of truth: `/tmp/sv-evidence.json` (79 KB). Reproduce with:

```bash
curl -s http://127.0.0.1:8123/api/v1/serving/<serving_id> | python3 -m json.tool
```

## 1. The shape of the problem

`ServingView.evidence` in `apps/studio/src/api/types.ts` is a **hand-picked
subset of seven fields**. Everything else the backend produces is buried in
`document: Record<string, unknown>` — untyped, and rendered only as a raw JSON
dump inside `<details>`.

`apps/studio/src/pages/serving.tsx` renders:

- requests retired / expected
- rounds (a count)
- `machine_id` and `namespace_id` as raw `<code>`
- `evidence_ids` (which is empty — see bug 1)
- a per-request table: `request | TTFT (cycles) | completion (cycles)`
- a raw JSON `<details>` dump

That is the entire serving product surface today.

## 2. What the backend actually returns

`CanonicalServingEvidence` (`type: srota/CanonicalServingEvidence`, 28 fields
plus four 507-element arrays):

| Field | Exposed in UI |
|---|---|
| `request_count`, `rounds` | yes (counts) |
| `request_metrics` (8 rows: id, ttft, completion) | yes |
| `machine_id`, `namespace_id` | yes (raw) |
| `evidence_ids` | yes — 507 of them, rendered as a raw list of `Hash` components |
| `execution_mode` = `LIVE_CANONICAL_EXECUTION` | no |
| `network_evidence_tier` = `ASTRA_OWNED_COLLECTIVE_EXECUTION` | no |
| `expansion_authority` = `astra_comm_coll` | no |
| `every_instance_served` = true | no |
| `instance_count` = 4 | no |
| `served_instances` (4) | no |
| `instances_with_completions` (4) | no |
| `endpoint_completions` (8 rows: instance, completion cycles) | no |
| `autonomous_injection_packets` (507) | no — and all 507 values are `null` (bug 1) |
| `backend_evidence_ids` (507 sha256) | no |
| `evidence_id` | no |
| `reusable` = true | no (also in `ServingSummary`, not rendered) |
| `astra_source_revision` | no |
| `astra_binary_sha256`, `astra_binary_size` | no |
| `standalone_config_sha256`, `serving_config_id` | no |
| `embedded_fabric_abi_version` | no |
| `backend_id`, `serving_binding_id`, `participant_mapping_id` | no |
| `workload_id`, `type`, `schema_version` | no |

## 3. Bugs to fix before features

**Bug 1 — `autonomous_injection_packets` is 507 × `null`.**
Confirmed: 507 entries, 507 `None`, 0 non-null. The per-round network injection
payload is not carried. The IDs exist (`backend_evidence_ids`, also 507), the
packets do not. Any per-round network view is blocked until the canonical path
actually writes these, or the field is removed and the omission is stated.

**Bug 2 — identity leaks into primary UI.**
`machine_id` and `namespace_id` are rendered as full `<code>` values. Same
hash-first problem already fixed in the prototype artifact.

**Bug 3 — `reusable` is modelled but never shown.**
`ServingSummary.reusable` and the document's `reusable` both exist (both
`true`). It gates replay/regression eligibility and is invisible.

**Bug 4 — 507 hashes rendered as a wall.**
`evidence_ids` is exposed as a flat list of 507 `Hash` components with no
grouping, producer attribution, or pagination. The data is there; the
presentation is machine-oriented. This is the same evidence-UX problem already
solved in the prototype.

## 3a. Corrected note

An earlier draft of this document claimed `ServingView.evidence.evidence_ids`
was empty. That was wrong — it was a mistake in the audit script querying
`document.evidence_ids`, which does not exist. `evidence_ids` has 507 entries.

## 4. Feature backlog, ordered by value per unit of work

Everything below is already in the payload unless marked CONTRACT.

### P0 — expose what already exists

1. **Run summary card**: `execution_mode`, `network_evidence_tier`,
   `expansion_authority`, `instance_count`, `every_instance_served`,
   `reusable`. This is the observation-scope and qualification story the
   closure brief asked for, and it is already returned.
2. **Per-instance view**: `served_instances`, `instances_with_completions`,
   `endpoint_completions`. Shows whether every instance and endpoint actually
   served. Pure data, no new contract.
3. **Liveness / participation panel**: `every_instance_served` plus
   `instances_with_completions` gives a real "did the fabric participate"
   answer instead of a hard-coded PASS.
4. **Per-request detail**: add p50/p95/p99 over `request_metrics`, and a
   histogram. Presentation-only, declared population is 8/8 retired so
   completeness is known.
5. **Provenance / reproduce**: `astra_source_revision`, `astra_binary_sha256`,
   `astra_binary_size`, `embedded_fabric_abi_version`, `standalone_config_sha256`,
   `serving_config_id`. This makes the manifest real instead of fixture.
6. **Identity demotion**: short suffix + copy control for `machine_id`,
   `namespace_id`, `backend_id`, `serving_binding_id`, `participant_mapping_id`,
   `evidence_id`.
7. **Reusable badge** in the experiments list and detail, gating replay actions.

### P1 — needs small backend work, no new science

8. **Round-level view** (507 rounds). Requires the canonical path to emit
   per-round records. `rounds` is currently only a count. CONTRACT + writer.
9. **Evidence browser** over the 507 `backend_evidence_ids` with producer
   attribution and grouping. Hash list already exists; needs meaning.
   Per-packet detail is blocked on bug 1.
10. **Experiment comparison** (`GET /api/v1/compare` exists and is unused by
    serving): compare two serving runs on TTFT/completion/rounds.
11. **Regression gate**: `reusable` + a baseline picker. `POST
    /api/v1/runs/{run_id}/reproduce` and `/verify` exist and are unused here.

### P2 — genuinely missing contracts

12. Time-domain authority. `request_metrics` are cycles but there is no
    `time_domain` field, no conversion identity between
    `MODEL_SERVICE_CYCLE`, `SERVING_LOGICAL_CYCLE`, `NETWORK_BOOKSIM_CYCLE`.
    Cross-domain comparison must stay UNAVAILABLE until this exists.
13. Causal attribution, critical path, overlap, resource series, fairness
    thresholds, structured logs. Not in this payload. The closure brief's
    "MISSING" verdict stands for these.
14. Preflight for serving specifically. `GET
    /api/v1/revisions/{revision_id}/preflight` exists but is revision-scoped,
    not experiment-scoped.

## 5. Routes the Studio does not use for serving

Available on the gateway, currently unused by the serving page:

```
GET  /api/v1/runs/{run_id}/evidence
GET  /api/v1/runs/{run_id}/integrity
GET  /api/v1/runs/{run_id}/artifacts
POST /api/v1/runs/{run_id}/verify
POST /api/v1/runs/{run_id}/reproduce
GET  /api/v1/qualification
GET  /api/v1/validation
GET  /api/v1/capabilities
GET  /api/v1/compare
GET  /api/v1/catalog/workloads
POST /api/v1/projects/{project_id}/workload
GET  /api/v1/workloads/{workload_id}/lowering
```

`servingSubmit` accepts `{ num_reqs, workload_id }` but the UI only ever sends
`num_reqs`. Workload selection and lowering are never surfaced, even though the
project has `llama-dense-8b-64tiles` and `serve-single_node_4_instance_2TP`
available.

## 6. Recommended sequencing

1. Fix bugs 1–4 (small; bug 1 is backend-side).
2. Widen `ServingView.evidence` to a typed contract instead of seven fields
   plus an untyped `document`. This is the single highest-leverage change: it
   turns every P0 item into a typed render.
3. Ship P0 items 1–4. That alone moves serving from "a table and a JSON dump"
   to a qualified run with instance, endpoint, and provenance views.
4. Then P1, then argue about P2 contracts.

---

## 7. Update — config, trace, timeout, profile overrides (shipped)

**`GET /api/v1/catalog/serving-configs`** added. Returns 20 cluster configs and
6 request traces with `config_id`, `display_name`, `source`, `content_digest`,
a `geometry` block (nodes, instances, tp/ep/pp sizes, pd_types, models,
hardware, link bw/latency), and `default_config` / `default_trace`. Mirrors
`workload_catalog`; the product layer lists and does not interpret.

**`ServingBody`** now carries six fields, all reachable from the Studio form:

```
num_reqs, workload_id, cluster_config, dataset, timeout_s, profile_overrides
```

Before this, the Studio sent only `num_reqs` while the API already accepted
`cluster_config` and `dataset`, and the client type did not declare them.

**`profile_overrides`** is validated at submit time against the certified
`CertifiedServiceProfile` field set (18 fields; `model` and `schema_version`
excluded as engine-owned). Unknown keys, non-integer values, and out-of-range
`timeout_s` produce a typed `UNSUPPORTED_SEMANTICS` refusal (HTTP 422) before
the job starts, instead of a FAILED job. Both are stored on the experiment
record and returned by `GET /api/v1/serving/{id}`.

### Finding — the declared profile does not reach the evidence

Reproduced with two runs on `p-4168adf8057c`:

| | baseline | override |
|---|---|---|
| profile | certified defaults | `routing_policy=LOAD`, `max_num_seqs=16`, `timeout_s=300` |
| rounds | 507 | 507 |
| TTFT cycles | 22030…14030 | 22030…14030 |
| `evidence_id` | — | **identical** |
| `standalone_config_sha256` | — | **identical** |
| `backend_evidence_ids` | — | **identical** |

`grep -r profile` over the override run directory returns **nothing**, and
`profile_id` does not appear in `serving-evidence.json`, even though
`CertifiedServiceProfile.profile_id()` exists and is passed to
`run_request_driven_service(profile_id=...)`.

Consequences:

1. The declared service profile is a reproduction input that is absent from
   `CanonicalServingEvidence`. Two runs with different declared profiles are
   indistinguishable from the evidence alone.
2. The identical metrics are plausible — at 8 requests, `max_num_seqs` 8 -> 16
   never binds, and RR vs LOAD can order the same. The problem is not the
   result, it is that the evidence cannot say which profile produced it.

Recommended fix: add `profile_id` and the declared profile body to
`CanonicalServingEvidence`, and include them in the evidence digest.

### Operational note

Three Vite servers were running against `apps/studio` simultaneously, sharing
`node_modules/.vite`. That corrupts the module graph and produces
`does not provide an export named 'Serving'` with a blank page, even though
`tsc --noEmit` and `npm run build` both pass. One dev server per project
directory. The working instance is on port 5175.

---

## 8. Update — refusal classification, profile identity, stale links

### Fixed: a typed refusal was reported as an internal error

`UnsupportedSemantics` (from `core.errors`) subclasses `Refusal`, which is
**not** a `ControlPlaneError`. The job worker only caught `ControlPlaneError`, so
a semantic refusal fell through to the generic `except Exception` branch and was
recorded as `FAILED` / `INTERNAL_ERROR`.

Observed on `p-51c35e10deb9-r06` (workload `moe-8x7b-64tiles`):

```
before  state=FAILED   error_code=INTERNAL_ERROR
        "UnsupportedSemantics: intent lowering supports
         model_family=dense_transformer, got mixture_of_experts"
after   state=REFUSED  error_code=UNSUPPORTED_SEMANTICS
```

`"UNSUPPORTED_SEMANTICS"` was already present in `_REFUSAL_CODES`; the branch
ever ran. Added a `Refusal` handler to `JobManager._run` in
`product/jobs.py`, mirroring the `ControlPlaneError` mapping.

### Still open: no compatibility check before submit
The workload catalog offers `moe-8x7b-64tiles` (`model_family=mixture_of_experts`)
while `intent_lowering.py` supports only `dense_transformer`. Nothing warns the
operator before the run. The refusal is now correctly typed, but it is still
discovered after submission. Recommended: report a `lowering_supported` flag per
catalog workload, or check it in the Run Simulation preflight.

### Fixed: declared profile identity now binds into the evidence

`CertifiedServiceProfile.profile_id()` existed and was passed to
`run_request_driven_service`, but `CanonicalServingEvidence` did not carry it.
Two runs with different declared profiles produced identical evidence.

Changes:

- `CanonicalServingEvidence.service_profile_id` added.
- Included in `identity_dict()` and in the live-evidence completeness guard.
- `evidence_id()` identity version bumped `1` -> `2`, because the identity
  shape changed. v1 and v2 digests are deliberately not comparable.
- `build_serving_evidence(service_profile_id=...)` is a required keyword; the
  serving loop passes `profile.profile_id()`.

Verified on two runs with byte-identical metrics:

| field | defaults | `routing_policy=LOAD, max_num_seqs=16` | |
|---|---|---|---|
| `service_profile_id` | `b3dbac04…` | `a3096a2b…` | DIFFERENT |
| `evidence_id` | `c0a5b3ff…` | `6ec6eb2e…` | DIFFERENT |
| `rounds` / `request_metrics` | 507 / identical | 507 / identical | SAME |
| `standalone_config_sha256` | `cbb2f416…` | `cbb2f416…` | SAME |

The runs are now distinguishable and reproducible from evidence alone.
241 tests pass (4 skipped).

### Fixed: a stale project link dead-ended

`App.tsx` guarded `activeProjectId` against ids that no longer exist, but a
project id in the URL was trusted unconditionally, so a link to a deleted
project showed `NOT_FOUND ... Retry` forever. Deleted-project links now render
the project picker once the project list has loaded. A project id is treated as
unknown only after the list loads, so a valid deep link is not briefly rejected.


