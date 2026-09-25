# VERITX Compiler Authority (C2.1)

One canonical artifact-derivation implementation. This document records
which input shapes exist, which one compiler sequences the sealed Wave-B
derivation, and the one remaining duplicate sequencer.

## Inputs

| input | type | interpreter | notes |
|-------|------|-------------|-------|
| V2 | `model/compile_model.CompileRequest` | `application/compile_intent.derive_compile_request` | candidate semantics explicit (inventory/mapping/routing_policy/vc_spec/settings) |
| V3 | `model/compile_model.CompileRequestV3` | `fabric_intent_view` | declared traffic classes; VC structure from `derive_vc_assignment_artifact_v3` |

V2 and V3 may interpret intent differently. Once a candidate's semantics
are explicit, both must funnel through one derivation engine.

## The one compiler

`compiler/canonical.compile_deterministic_candidate` is the single
orchestration path. It takes an exact `CompileRequest`, an exact placement
(`NodeInventory` + `MappingArtifact`) and an explicit candidate recipe
(`RoutingPolicyDefinition` + `DeterministicVCSpec` +
`FabricCompileSettings`), and derives:

```text
inventory ── materialize_topology ──> topology
           ├ derive_attachment ─────> attachment
           ├ materialize_route_artifact ──> route
           ├ derive_resolved_route ──> resolved_route
           ├ make_vc_assignment_artifact ──> vc_assignment
           │                             └─ vc_resources_from_assignment ──> vc_resource
           ├ make_deterministic_routing_realization ──> routing_realization
           ├ derive_packet_format / derive_router_behavior / derive_address_decode
           ├ make_deterministic_fabric ──> fabric
           └ make_resolved_deterministic_fabric ──> resolved_fabric  (terminal identity)
```

Terminal identity is `ResolvedFabric.resolved_fabric_hash`. The
`CompiledFabric` bundle is transport only.

### Candidate policy

`compiler/candidate_policy.generate_baseline_candidate` produces the
declared `BASELINE_DETERMINISTIC_V2` plan (inventory, mapping, routing
policy, VC spec, `FabricCompileSettings(8, 8, 1)`). Search/selection lives
above the compiler; every candidate funnels through
`compile_deterministic_candidate`.

## Paths

| path | entry | sequencing |
|------|-------|------------|
| service | `application.service.SrotaControlPlane` | candidate plan → `compile_deterministic_candidate` |
| V2 orchestration | `compiler.orchestration.build_resolved_bundle` | `generate_baseline_candidate` → `compile_deterministic_candidate` → bundle — **one v2 compiler** |
| V3 orchestration | `compiler.orchestration.build_resolved_bundle_v3` | derives the candidate semantics, then `_derive_canonical_fabric` + `_bind_resolved` + `_make_bundle` |

## Parity evidence

`tests/test_compiler_path_parity.py` runs the same intent through the
service and the V2 orchestration entry and asserts all 12 semantic child
identities are equal (topology, mapping, attachment, route, resolved route,
VC assignment, VC resource, routing realization, packet format, router
behavior, address decode, fabric, resolved fabric).

## Remaining duplication (OPEN — A8)

`build_resolved_bundle_v3` **re-implements the sequencer** that
`compile_deterministic_candidate` already is. The primitive `derive_*`
functions are shared, but:

- the sequence topology→…→resolved_fabric is written twice (once in
  `canonical.py`, once as `_derive_canonical_fabric`/`_bind_resolved`);
- the hardware constants are duplicated: `_MAX_PACKET_FLITS = 8`,
  `_INPUT_BUFFER_DEPTH_FLITS = 8`, `_OUTPUT_STAGE_DEPTH_FLITS = 1` in
  `orchestration.py` vs `BASELINE_* = 8/8/1` in `candidate_policy.py`.
  They agree today, which is exactly the F-0006 precondition — agreement by
  coincidence, not construction.

No cross-path (V2↔V3) identity parity test exists yet, so the two paths
could drift silently.

### Collapse plan

1. Extract `compose_deterministic_fabric(*, design, inventory, mapping,
   topology, attachment, route, resolved_route, vc_assignment, settings)`
   from `compile_deterministic_candidate`; have that function call it.
2. Define the V3→candidate-semantics translation explicitly (what VC spec
   the V3 declared classes correspond to) so equivalence is *defined*, not
   assumed.
3. Have `build_resolved_bundle_v3` build those semantics and call the same
   composer; delete `_derive_canonical_fabric`/`_bind_resolved` and the
   duplicated constants.
4. Add a V2↔V3 parity test asserting the 12 child identities for a fabric
   the two inputs intentionally represent identically.

Until (1)–(4) land, C2.1 is IN_PROGRESS and the ledger records it OPEN.
