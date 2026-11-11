# Ablation correctness, product promotion, and prototype audit

## Scope and verdict

This is a scoped review and implementation of the workload-ablation surface,
its CLI/gateway runner, and candidate promotion paths. It is not a certification
of every prototype view, native graphics performance, or all topology sizes.
The incumbent industrial/engineering UI is preserved; no redesign was needed.

**Implementation integrity: major correctness issues were found and fixed.**
The surface now distinguishes executed traffic, experimental identity,
configuration support, and qualification. Existing historical data is not
rewritten to manufacture provenance. Exact nontrivial function-body comparison
across prototype TypeScript found no verbatim clones; semantic duplication and
repeated presentation were more important than textual duplication.

## Shipped changes

### Experiment identity and replay

- Gateway tuning replays the catalog's frozen trace, rather than regenerating a
  random workload from a similarly named YAML.
- New outputs record executed/source trace hashes, active endpoint IDs/count,
  trace packet sizes, simulator seed, binary hash and source-arm hash.
- Paired improvement claims require matching trace, arm, simulator binary and
  simulator seed. Missing historical evidence produces an explicit warning,
  not an assumed match. Workload variants remain viewable without being called
  hardware-only improvements.
- Cache reuse binds the executed config, trace, binary and packet-output digest.
  Changing knobs invalidates the old result. A failed rerun cannot reuse a stale
  packet file. Nonzero exits and incomplete packet delivery are not successes.
- Malformed packet measurements fail closed instead of partially counting rows.

### Workload controls and scope

- Active endpoints are distinct referenced IDs, not highest ID + 1. A trace on
  endpoints 0 and 63 has two active endpoints, not 64. Endpoint zero alone counts
  as one. Sparse activity is not expanded behind the user's back.
- Explicit trace variants can change packet flits, requested arrival-time scale,
  burst-window coalescing, or a bijective affine rank placement (stride/offset).
  Placement preserves the number of active ranks; it does not create traffic.
- The config packet-size default remains separate from observed packet sizes.
  The inspector reports effective sizes from packet output.
- Router resource inventory comes from BookSim's cost record. Declared buffering
  per input is labeled separately. Neither is measured area, power, or energy.
- Trace replay is labeled network-only: no model compute or DRAM timing is added
  or inferred. Existing modeled energy charts remain proxies.

### Prototype feedback and duplication

- A shared `ablationEvidence.ts` pairing rule is used by comparison summaries
  and the inspector; the two places cannot independently assume "same trace".
- Hiding the last candidate now shows zero selected candidates. Previously an
  empty selection was interpreted as "all", immediately undoing the user's
  action. Ranking selection and tuner run selection remain separate scopes.
- Failed cells with numeric partial output are excluded from heat coloring.
- Clipboard failures now have visible recovery guidance and success is announced.
- Stale gateway code is checked before a run; the client timeout leaves room for
  the gateway's own 600-second failure response.
- Duplicate knob-provenance summary/list rendering was removed; the detailed
  audit remains available in one disclosure.
- The sticky toolbar is opaque so scrolled table text does not bleed through.
- An empty model name now says "Unnamed workload", not "No workload declared"
  when traffic or compute may already exist.

## Product promotion

| Configuration | Outcome | Reason / remaining work |
|---|---|---|
| GEC MECS, 64 endpoints | Added `gec_mecs64` product preset | Canonical 4×4 routers, concentration 4; compiler-owned shared-resource routing and normal authenticated evaluation path |
| GEC hybrid, 64 endpoints | Added `gec_hybrid64` product preset | Same canonical geometry; ranked mesh/MECS union and normal evaluation path |
| SROTA 8×8, concentration 1 | Added `srota64` product preset | Canonical express fabric, row/column rank routing, two VC sets; compilation certificate, native route differential and authenticated execution pass. Historical research results are not relabeled |
| QTree64 | Added distinct `qtree_native64` preset | Exact 21-router geometry and leaf-only 64-terminal attachment; compiler-owned QTREE_NCA; native qtree/nca profile with all 1,344 hops and output ports authenticated. Historical balanced-tree identities and four-VC research results are not rewritten |
| Tree4-64 | Not promoted | Native 28-router graph and redundant upward NCA choices still require their own union proof and native evidence; existing `tree4_7` remains a different balanced-tree construction |
| 64-node Ring | Not promoted | Registry intentionally marks Ring as a test fixture, not authorable product intent. A 1-D torus spelling is not permission to silently change canonical identity |
| Fly64 | Not promoted | Native multi-stage butterfly must not be conflated with flattened butterfly/FlatFly. Canonical intent, graph, routing and execution evidence are still required |

The two new GEC presets are **canonical product alternatives**, not a retroactive
promotion of the raw research configs or their saved results. The old 16-endpoint
preset design hashes are regression-tested unchanged. Native tests compile and
execute each new preset with authenticated evidence and a realization digest.
This is bounded model execution proof, not hardware calibration or a claim that
every workload/parameter combination has been qualified. No family registry
stage was loosened.

The follow-up `srota64` preset extends unit-concentration support through intent
validation and BookSim projection. The existing materializer and rank-route
proof already support this geometry. Concentration below one is rejected;
concentration one without MECS remains a plain mesh and must use mesh intent.
The native differential checks the 8×8 fabric's nonlocal router/destination
choices against the certified union, while canonical evaluation authenticates
the realized route and requires injected/accepted flit conservation. This does
not establish equality with every buffer, timing or telemetry knob in a raw
research configuration, nor requalify historical traces.

Follow-up verification: **120 tests passed** across all `test_srota*.py`,
`test_product_srota64.py`, `test_product_gec64.py`,
`test_project_from_preset.py` and `test_structured_presets.py`. Pytest reported
one existing unknown-`timeout` configuration warning. No frontend change was
needed: the new preset is served by the existing catalog.

## Canonical workload-study follow-up

The existing bounded product optimization job now accepts canonical `tp`, `ep`,
`dp` and `pp` dimensions, individually or together. It rebuilds workload groups
through normal compiler/lowering/evaluation paths. The older multi-scenario
study path shares the same workload patch authority and supports typed V4
fabric patches instead of attempting to write its legacy `noc_config` view.
Imported source traces cannot be repartitioned by changing their metadata.

Explore exposes a TP/EP Cartesian grid capped at four configurations, explicit
network/system/DRAM objective questions, and independent memory timing. System
objectives require declared compute; memory controls require operand bytes and
an actual HBM controller. Dirty drafts must be compiled first. Approval resets
on changed inputs and nothing is adopted automatically. Backend availability
and per-candidate support remain authoritative; an absent objective cannot rank
as zero. Compute durations, owners and memory operands remain exactly as
authored, **not automatically resharded to imply equal model work**.

Live smoke evidence is frozen in
[`evidence/workload-study-native-smoke.json`](evidence/workload-study-native-smoke.json).
The declared synthetic input is 16 compute endpoints, one HBM controller, a
100 ns compute stage on rank 0, and 64/128/32 input/weight/output bytes. It is
not a real model profile. Both tested decompositions use eight ranks:

| Decomposition | BookSim network cycles | ASTRA system cycles | Ramulator average read-latency cycles |
|---|---:|---:|---:|
| TP2 / EP4 | 91 | 352 | 117 |
| TP4 / EP2 | 109 | 612 | 117 |

Every column has its own native evidence ID and producer/model provenance.
The independent cycle domains are never summed. A native regression also
increases authored compute duration and checks that system makespan rises
while standalone network completion stays unchanged; native scheduling may
overlap work, so an arithmetic compute+network formula is not asserted.

### Exact native topology boundaries

- Native QTree64 (`networks/qtree.cpp`) has 1+4+16 routers, 20 bidirectional
  inter-router connections and 64 terminals, four per leaf router. Existing
  canonical `qtree` radix=4/tiers=3 has 85 routers. They cannot share a claim.
- Native Tree4-64 (`networks/tree4.cpp`) has 4 roots, 8 middle routers and
  16 leaves; its redundant upward wiring is not a balanced k-ary tree.
  The existing canonical `tree4` spelling retains its historical graph/hash.
- Native Ring64 is a **one-dimensional**, even-side torus. Current product
  torus intent/profile is a square grid and qualified only for odd-side
  deterministic dumps; the separate materialized Ring remains a test fixture.
  Exact promotion needs its own intent and dateline-routing qualification.
- Native Fly64 (`networks/fly.cpp`) has three stages of 16 routers. Each
  terminal injects at the first stage and ejects at the last stage, whereas
  canonical attachment currently binds an endpoint to one router. It needs a
  directional ingress/egress attachment contract and native destination-tag
  routing, not a flattened-butterfly alias.

The existing seven-node canonical tree presets execute with authenticated
realization and flit conservation. Their stage rows now name the actual AnyNet
projection, and the registry checker derives structured declaration membership
from `STRUCTURED_FAMILIES` instead of maintaining a drifting second name list.
The subsequent native QTree compiler extension implements its own lossless
construction and NCA policy, rather than aliasing a balanced-tree preset; see
[`native-indirect-topologies.md`](../../decisions/native-indirect-topologies.md).
The new `qtree_native64` preset has native hop/port and authenticated execution
proof. No qualification gate was weakened and no existing project was migrated.
Tree4, Ring and Fly still require their own contracts and proof.

## Evidence and checks

Latest follow-up checks: **202 targeted backend tests, 72 frontend unit tests
and 19 browser tests passed**, including the real four-candidate product job
through BookSim, ASTRA and Ramulator. The frontend production build, registry
checker and `git diff --check` passed. The existing large-chunk build warning
and unknown pytest `timeout` option remain; neither is hidden or treated as
performance verification. Browser captures were inspected at 1280 and 1440 px.

Runnable checks:

```bash
python3 -m pytest -q tracks/t3-topology/dse/tests/test_workload_optimization.py tracks/t3-topology/dse/tests/test_workload_optimization_native.py tracks/t3-topology/dse/tests/test_research_promotion_boundaries.py
python3 scripts/check_topology_family_registry.py
npm --prefix apps/studio/prototype run test:e2e -- tests/backend-hardening.spec.ts
python3 tracks/t3-topology/dse/tests/test_ablation_evidence.py
python3 tracks/t3-topology/dse/tests/test_ablation_gateway.py
python3 tracks/t3-topology/dse/tests/test_product_gec64.py
python3 tracks/t3-topology/dse/tests/test_product_srota64.py
python3 -m pytest -q tracks/t3-topology/dse/tests/test_project_from_preset.py
npm --prefix apps/studio/prototype test
npm --prefix apps/studio/prototype run build
npm --prefix apps/studio/prototype run test:e2e -- tests/ablation-evidence.spec.ts tests/workload-analysis.spec.ts tests/desktop.spec.ts
```

A bounded real BookSim check replayed the Astr trace on mesh8x8 and srota8x8,
then replayed the exact baseline with deeper buffers, then explicitly changed
payload, arrival spacing, burst window and rank placement. Paired hashes matched;
variant hashes differed; eight active endpoints stayed eight; effective packet
sizes changed from 8 to 16 flits; identity-checked cache reuse passed.

A useful cost observation from that check: at depth 8, the simulator reports
5,120 storage flits for mesh8x8 versus 30,720 for the SROTA research arm. Equal
VC depth is demonstrably **not** equal fabric buffering. Do not interpret the
latency ranking as an equal-cost comparison.

Browser checks exercise sparse-coverage warnings, zero-selection behavior,
verified/blocked comparisons, explicit variant requests, stale-code refusal and
clipboard feedback. Screenshots were inspected at 1440×900 and 1280×900 in
Chromium. This does not constitute native WebKit performance or font verification.
The mechanical design detector returned no findings on the changed ablation
surface; that is not a whole-application accessibility guarantee.

## Remaining prioritized work

- **P1 — Product support authority:** replace the manually curated raw-arm support
  classifications with evidence tied to an exact canonical configuration. Do not
  inherit qualification from the family name. `$impeccable clarify` for the claim
  surface, backed by compiler/native qualification tests.
- **P1 — Representative model studies:** canonical TP/EP sweeps and authored
  compute/memory evaluation are implemented and live-smoke-tested above. Real
  model durations, sharding policy and memory demand still need authored or
  measured inputs before application-level conclusions. No automatic model
  profiling, arbitrary DAG editor or KV-cache model is implied.
- **P1 — Desktop distribution:** live ablation execution still depends on repository
  scripts/configs and trace sources. This pass does not silently bundle historical
  user project traces into a distributable installer. A release needs explicit
  asset selection, writable output routing, license review and packaged execution
  tests.
- **P2 — Long-run feedback:** the gateway ablation call is synchronous. The UI
  honestly displays running state, but per-cell progress/cancellation needs the
  existing job lifecycle rather than a fabricated percentage. `$impeccable harden`.
- **P2 — Prototype module structure:** `WorkloadAblations.tsx` still mixes data
  loading, controls, ranking and inspection; live/fixture view branches and form
  types repeat knowledge. Extract only tested shared behavior (as done for pairing),
  not a generic component framework. `$impeccable distill`.
- **P2 — Performance:** the main application chunk remains above Vite's warning
  threshold. A release-build/WebKit profile is needed before blaming a particular
  renderer or introducing memoization everywhere. `$impeccable optimize`.
- **P2 — Broader UI audit:** desktop-only dense controls are not a tested phone
  interface; contrast, keyboard actions, plot interaction, and zoom need a separate
  full-prototype pass. `$impeccable audit`, then `$impeccable polish`.

No full benchmark campaign was launched, no existing project was edited or
migrated, and no old result was relabeled as qualified.
