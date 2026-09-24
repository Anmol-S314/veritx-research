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
| RT certified evidence | `backend.booksim.CertifiedBookSimEvidence` | — | RT | — | `to_dict` coerces | none | **legacy vocabulary** | not production-reachable (test-only readers in `application/results.py`) | legacy |
| performance result | `performance.result` | 1 | performance | `from_dict` | VERIFY | canonical JSON | RT readers in `application/results.py` (legacy, test-only) | yes | canonical production path |
| optimization definition | `optimization.definition` | VERIFY | optimizer | `from_dict` | `OptimizationDefinitionError` | canonical JSON | none | yes | canonical |
| optimization result | `optimization.result` | VERIFY | optimizer | `from_dict` | VERIFY | canonical JSON | none | yes | canonical |
| backend producer identity | `backend.producer.resolve_producer_identity` | — | producer | — | `ProducerIdentity` | in-memory + evidence fields | none | yes | canonical |
| build provenance | `core.build_manifest.BuildManifest` | 1 | build (`make release-manifest`) | `load_and_verify_manifest` | sha256/size + recipe | canonical JSON beside binary | none | yes | canonical |
| run bundle | `core.runs` (`new_run_dir`) | — | CLI | — | none | timestamped dir | — | yes | BLOCKER B5: not content-addressed/atomic |

## Known second-authority / legacy blockers

### B1 — second compile authority removed (CLOSED)

Resolved by `9eb7c2e6`: `application/compile.py` was deleted and its
orchestration moved to `veritx_dse/compiler/orchestration.py` as
`build_resolved_bundle` / `build_resolved_bundle_v3`; the three callers
now import from the compiler package. `FabricPreset` was renamed to
`Preset`. The canonical control plane remains
`application/service.py` (SrotaControlPlane).

### B2 — `application/results.py` RT vocabulary (CLOSED as option B)

The canonical design loader `load_verified_design` is authoritative and
production-used. The historical RT-vocabulary result/attempt/comparison/
study readers are marked LEGACY, are not production-reachable (no CLI or
service imports them), and the capability inventory was split accordingly
(`c78e54af`). A guard test enforces that no production module imports or
calls them. Migration of the Wave-D/E seal tests to canonical evidence is
the remaining cleanup.

### B3 — evidence admissibility and producer qualification (CLOSED)

Closed by `facf645b` (closed vocabularies + impossible-combination
refusal + restored legacy v1 reader) and `978a38ed` (one
`admit_for_certified_product` rule: supervised transport, QUALIFIED
fidelity, known revision, clean producer, exit 0).

### B4 — build provenance (CLOSED)

Closed by `43f55d94`: `core/build_manifest.py` binds the build-time source
revision + dirty state + binary sha/size + compiler + flags + recipe; the
binary is verified against the manifest at resolve time, so the A→B
counterexample is detected and a manifest-less binary is never pinned.
`make release-build` generates manifests.

### B5 — run bundles are timestamped temp directories (OPEN)

`core.paths.new_run_dir` and `core.runs` create timestamped directories.
They are not content-addressed, not atomic, and cannot be independently
re-verified. `veritx reproduce` / `veritx verify-run` do not exist.
This is the P2 phase.

### B6 — `CompileRequest`/`migrate_design` duplicate (CLOSED)

Resolved by `8c32ccc2`: the shadow copy from `a5b806fe` was removed and
the canonical (dependency-canonicalizing) definition is live.

### B7 — semantic-error taxonomy is ValueError-rooted (OPEN, residual)

The certificate and compiler boundaries catch `(ValueError, VeritXError)`
as the declared semantic taxonomy and abort on everything else, so the
mandate's injected faults (RuntimeError/AttributeError/NameError/TypeError)
propagate. A programmer fault raised as a bare `ValueError` would still be
laundered into a verdict. Closing this means introducing one
`SemanticError` base in `core.errors` and re-parenting the ~30
`*Error(ValueError)` classes so the boundaries catch the base only.

### B8 — executed route realization is not observed (OPEN, honest)

The vendored fork emits a first-hop route dump (`routing_dump_file`), but
the canonical execution does not yet render it and compare it against the
resolved route, so evidence honestly records
`DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED`. No profile claims observed route
equivalence. Implementing exact destination-aware observation (coverage,
first-hop equality, adjacency, routing class) is the remaining work.
