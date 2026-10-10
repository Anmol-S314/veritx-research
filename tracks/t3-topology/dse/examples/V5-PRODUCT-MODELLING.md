# V5 JSON product modelling

The product's canonical JSON draft/revision path accepts `CompileRequestV5`
without changing its root identity. Studio edits the nested base through a
root-preserving lens and exposes explicit declaration JSON fields. Generic
backend execution remains unsupported; the separate abstract experiment is
not a V4 simulation or native qualification.

From `tracks/t3-topology/dse`, with an existing project and a gateway at
`http://localhost:8000` (replace `PROJECT_ID`):

```bash
# Import the example's design, not its separately owned experiment inputs.
python3 -c 'import json; print(json.dumps(json.load(open("examples/addressed_memory_v5.json"))["design"]))' > /tmp/v5-design.json
python3 -c 'import json; print(json.dumps({"request":json.load(open("/tmp/v5-design.json"))}))' > /tmp/v5-draft.json
curl --fail-with-body -H 'Content-Type: application/json' -X PUT \
  --data-binary @/tmp/v5-draft.json \
  http://localhost:8000/api/v1/projects/PROJECT_ID/draft
curl --fail-with-body -X POST \
  http://localhost:8000/api/v1/projects/PROJECT_ID/compile
# Run the explicit abstract experiment separately, with its workload/placement.
python3 -m veritx_dse.application.data_movement examples/addressed_memory_v5.json
```

A supplied V5 `design_hash` must match the strict model's computed hash.
Unknown root fields, including `guardrail_hash`, are invalid. Editable draft
JSON returned by the product omits computed root hashes; edit that document
rather than resubmit a changed design with a stale hash. On an explicit edit,
Studio removes computed root/base hashes (and the edited access policy's hash)
only; strict imports still verify supplied identities. All untouched extensions
and read-only migration provenance survive edits. Group addition/removal/remapping
is unavailable for V5 base controls. Integers outside JavaScript's safe range
refuse Studio authoring; use the exact canonical JSON API instead. Legacy V2-V4
input compatibility is unchanged.

Neutral roots and supported clock, sideband, access-policy and endpoint
execution-contract records retain V5 identity through synchronous/process
compilation, immutable storage and reconstructed views. Hardware inspection
uses the explicit `base_v4`; it is not the revision's identity. The full
CompilationView certificate and CompileResultView retain the existing
structural design binding; no new proof is invented. Reset/power declarations
still refuse at COMPOSE; interface roles refuse at ATTACHMENT.

Successful structural compilation does **not** qualify a simulation. Generic
V5 execution readiness is `UNSUPPORTED` / `BLOCKED`; evaluation planning
refuses with the existing `ABSTRACT_DATA_MOVEMENT_V1` boundary. Studio review
binds the full V5 root, includes extension-only scientific changes and freshness,
and labels legacy hardware summaries `BASE_ONLY`. `VALIDATED_DECLARATION` and
`NOT_RUN` never mean structurally supported, executable or qualified. Reset/power
and interface-role refusals remain visible declarations. Migration provenance is
metadata, excluded from scientific diff and identity.

## Explicit synchronous product experiment

`POST /api/v1/projects/PROJECT_ID/revisions/REVISION_ID/abstract-experiments`
accepts exactly `profile`, `workload`, `placement`, never a new design or paths.
Replace both IDs with the immutable revision compiled from the example above:

```bash
python3 -c 'import json; x=json.load(open("examples/addressed_memory_v5.json")); print(json.dumps({"profile":"ABSTRACT_DATA_MOVEMENT_V1", "workload":x["workload"], "placement":x["placement"]}))' > /tmp/v5-explicit-inputs.json
curl --fail-with-body -H 'Content-Type: application/json' -X POST \
  --data-binary @/tmp/v5-explicit-inputs.json \
  http://localhost:8000/api/v1/projects/PROJECT_ID/revisions/REVISION_ID/abstract-experiments
```

Studio's Evaluate page offers the same explicit workload/placement JSON action
for a compiled V5 revision, including when generic planning is unsupported.
No runtime inputs are stored in the canonical root. The result is dedicated
`DIAGNOSTIC_ABSTRACT` evidence bound to project/revision/design/system/workload/
placement identities; the stored immutable root is recompiled and the existing
runner enforces all parent contracts. Repeating the same inputs recomputes the
same evidence. It creates no job/run, changes no active pointers and never
promotes generic backend readiness. Only `ABSTRACT_DATA_MOVEMENT_V1` is accepted.
Unknown fields, wrong project/revision or parents, invalid clocks/paths/policies,
unsupported declarations and noncompletion refuse without successful evidence.

Conservative synchronous limits are 256 KiB request body and root, 64 operations,
routers and endpoints, 65536 total payload/control bytes, 4096 children and 65536
flits. HTTP streaming checks the body bound before JSON parsing; full input
bounds are checked before execution. The runner is event-driven with finite
demand, not an elapsed-cycle simulation; no new timing horizon/default is
inferred. Duplicate JSON keys and nonfinite numbers refuse. These limits do not
expand the existing deterministic P2P/clock/crossing model envelope.

The addressed runner consumes the same recompiled, root-bound revision with
explicit workload and placement. See `../docs/DATA-MOVEMENT-EXECUTION.md` for
its supported policies, clocks, permission checks and bounded execution.
It is abstract modelling, not BookSim equivalence, hardware signoff or timing
qualification.

The standalone class-VC source diagnostics separately check exact canonical
class-to-VC mapping, table bounds, stock request-envelope intersection and
trace class ingress. Invalid classes cannot disappear through per-class
filtering. The copied dirty source build is only diagnostic. The class-VC
profile remains `NOT_QUALIFIED`; pinned binaries/manifests are untouched.
Distinct embedded ASTRA class ranges still require the existing explicit
traffic-class ABI extension and are refused today.

Focused checks: `test_v5_studio_experiment.py`, `v5-authoring.contract.test.tsx`,
`test_v5_product_boundary.py`,
`test_booksim_class_vc_withdrawal.py`, `test_support_expansion.py`.
