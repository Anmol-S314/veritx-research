# VERITX Authority Map

One authoritative representation per scientific concept. This is a
**first pass** built from the production tree at `190d04f1` plus the
three P0 closures. Rows marked `VERIFY` still need a full writer/reader
audit before the seal; rows marked `BLOCKER` have a known second current
authority or a legacy reader on a production path.

Rule enforced by this map:

> Any concept with two current writers is a blocker. Legacy code may READ
> old versions through an explicitly versioned migration adapter, but must
> never silently become a second current authority.

## Concepts

| concept | canonical type/module | schema | writer | reader | validator | persisted form | legacy readers | prod-reachable | status |
|---------|----------------------|--------|--------|--------|-----------|----------------|----------------|----------------|--------|
| design intent | `model.compile_model.CompileRequest` | 2 | compiler | `from_dict` | `__post_init__`, `design_hash` | canonical JSON | LEGACY_COMPILER_SEMANTICS_VERSIONS=(1,) via `migrate_design` | yes | canonical |
| design intent v3 | `model.compile_model.CompileRequestV3` | 3 | compiler | `from_dict` | `__post_init__` | canonical JSON | none | yes | canonical |
| topology | `model.topology_artifact.TopologyArtifact` | 1 | compiler | `from_dict` | `validate_*` | canonical JSON | none | yes | canonical |
| attachment | `model.attachment.AgentAttachmentArtifact` | 3 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| address decode | `model.address_decode.AddressDecodeArtifact` | 3 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| mapping | `model.mapping.MappingArtifact` | 1 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| routing (router level) | `core.route_artifact.RouteArtifact` | 2 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| resolved route | `model.resolved_route.ResolvedRouteArtifact` | 2 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| VC assignment | `model.vc_assignment.VCAssignmentArtifact` | 1 | compiler | `from_dict` | `__post_init__` + `validate_against` | canonical JSON | none | yes | closed (P0.a0b934b6) |
| VC resource | `model.vc_resource.VCResourceArtifact` | 1 | derived | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical (one-way projection) |
| packet format | `model.packet_format.PacketFormatArtifact` | 2 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| router behavior | `model.router_behavior.RouterBehaviorArtifact` | 3 | compiler | `from_dict` | `validate_against` | canonical JSON | none | yes | canonical |
| fabric | `model.fabric_artifact.FabricArtifact` | 1 | compiler | `from_dict` | `validate_against_deterministic` | canonical JSON | none | yes | canonical |
| resolved fabric | `model.resolved_fabric.ResolvedFabric` | 1 | compiler | `from_dict` | `validate_against_deterministic` | canonical JSON | none | yes | canonical |
| verification certificate | `verification.certificate.VerificationCertificate` | 1 | certificate | `from_dict` | `__post_init__` + id recompute | canonical JSON | none | yes | closed (P0.8d61da35) |
| logical workload | `workload.graph` / `workload.canonical` / `workload.operations` | 1 | workload | `from_dict` | `validate_conservation` | canonical JSON | VERIFY: three workload graph modules coexist | yes | VERIFY |
| logical messages | `workload.messages.LogicalMessage` | — | lowering | — | oracle checks | not persisted | — | yes | scope-limited: no chunk id (F-0004) |
| physical traffic | `workload.traffic.PhysicalTrafficArtifact` | 1 | lowering | `from_dict` | `validate_conservation` | canonical JSON | none | yes | canonical |
| participant mapping | `workload.traffic.ParticipantEndpointMapping` | 1 | lowering | `from_dict` | validate | canonical JSON | none | yes | canonical |
| prepared backend input | `backend.booksim_projection.PreparedBookSimInput` | 2 | projection | `from_dict` | id recompute | canonical JSON + config/trace | none | yes | canonical |
| backend evidence (scientific) | `backend.evidence.ScientificBackendEvidence` | 1 | execution | `ScientificBackendEvidence.from_dict` | closed fields + id recompute | canonical JSON | legacy unversioned v1 via `validate_evidence_document` | yes | canonical; admissibility incomplete (P0.4) |
| backend evidence (artifact) | `backend.evidence.EvidenceArtifact` | 1 | M1.4 | `from_dict` | id recompute | canonical JSON | v1 label ordering preserved | yes | VERIFY vs ScientificBackendEvidence |
| RT certified evidence | `backend.booksim.CertifiedBookSimEvidence` | — | RT | — | `to_dict` coerces | none | **legacy vocabulary** | BLOCKER: reachable via `application/results.py` | legacy |
| performance result | `performance.result` | 1 | performance | `from_dict` | VERIFY | canonical JSON | `application/results.py` (RT vocabulary) | yes | BLOCKER (§5.11) |
| optimization definition | `optimization.definition` | VERIFY | optimizer | `from_dict` | `OptimizationDefinitionError` | canonical JSON | none | yes | canonical |
| optimization result | `optimization.result` | VERIFY | optimizer | `from_dict` | VERIFY | canonical JSON | none | yes | canonical |
| backend producer identity | `backend.producer.resolve_producer_identity` | — | producer | — | `ProducerIdentity` | in-memory + evidence fields | none | yes | **no build manifest** (P0.6) |
| build provenance | — | — | — | — | — | none | — | yes | BLOCKER: ambient git HEAD only |
| run bundle | `core.runs` (`new_run_dir`) | — | CLI | — | none | timestamped dir | — | yes | BLOCKER: not content-addressed/atomic |

## Known second-authority / legacy blockers

### B1 — `application/compile.py` is a second compile authority (P0)

`application/compile.py` defines `compile_bundle` / `compile_bundle_v3`
and is imported by `application/fabric_compiler.py`,
`application/results.py` and `application/waved_resources.py`. The
canonical control plane is `application/service.py`
(`SrotaControlPlane`) built on `application/compile_intent.py`. The test
`test_application_service.py::test_application_package_reaches_no_legacy_compiler`
asserts `compile.py` does not exist and that no `application/*.py`
mentions `compile_bundle`, `derive_route`, `derive_vc_assignment`,
`derive_vc_count`, `FabricPreset` or `p4/studio`.

Resolution (planned P0.1): move the orchestration body into a
non-application module (`veritx_dse/compiler/`), delete
`application/compile.py`, and route the three callers through the
canonical service surface with a name that does not collide with the
forbidden tokens. Behavioural equivalence must be pinned by the existing
compile tests.

### B2 — `application/results.py` persists RT-vocabulary resources (P0, §5.11)

`load_verified_result` / `load_verified_design` read resources with
legacy field aliases (`backend_config_hash`, `qualification`,
`execution_transport`, `booksim_binary_sha256`). It is reachable from
`application/waved_resources.py` (production) and is exercised by
`test_wave_d_seal.py`. Resolution: either migrate to
`ScientificBackendEvidence` with versioned persistence and
write→reload→verify tests, or mark it legacy and remove it from
production reachability. Must not keep stale aliases in canonical code.

### B3 — `ScientificBackendEvidence` admissibility is content-only (P0, §5.4/§5.5)

The class enforces closed fields, `evidence_id` recompute, finite stats
and exact ints. It does NOT yet enforce closed vocabularies for
`execution_fidelity`, `transport`, `route_observation`, or family-specific
cross-field invariants on `producer_source_revision` / `producer_dirty` /
`profile_id` / `projection_semantics_version`. Producer qualification
(`transport == SUPERVISED_PROCESS`, `execution_fidelity == QUALIFIED`,
revision present, not dirty, exit 0) is split between the `reusable`
property and `verify_reusable_record`. One function must own it.

### B4 — build provenance is ambient (P0, §5.6)

`resolve_producer_identity` hashes the binary and reads live git HEAD.
The counterexample (build at A, checkout B, binary untouched, clean tree
→ binary attributed to B) is NOT detected. A build-time manifest binding
source revision + dirty state + binary sha + size + compiler + recipe
version is owed.

### B5 — run bundles are timestamped temp directories (P0, §7)

`core.paths.new_run_dir` and `core.runs` create timestamped directories.
They are not content-addressed, not atomic, and cannot be independently
re-verified. `veritx reproduce` / `veritx verify-run` do not exist.

### B6 — `CompileRequest`/`migrate_design` duplicate (CLOSED)

Resolved by `8c32ccc2`: the shadow copy from `a5b806fe` was removed and
the canonical (dependency-canonicalizing) definition is live.

### B7 — semantic-error taxonomy is ValueError-rooted (VERIFY, §5.1)

The certificate boundary now catches `(ValueError, VeritXError)` as the
declared semantic taxonomy and aborts on everything else. A programmer
fault raised as a bare `ValueError` would still be laundered into a
verdict. Eliminating that residual risk means introducing one
`SemanticError` base in `core.errors` and re-parenting the ~30
`*Error(ValueError)` classes. Recorded, not yet done.
