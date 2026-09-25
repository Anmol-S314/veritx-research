# VERITX Compiler Authority (C2.1)

One canonical artifact-derivation implementation. This document records
which input shapes exist, which one compiler sequences the sealed Wave-B
derivation, and how both request generations funnel through it.

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

## Remaining duplication (CLOSED — C2.1)

`build_resolved_bundle_v3` previously re-implemented the sequencer that
`compile_deterministic_candidate` already is, and carried its own
`_MAX_PACKET_FLITS`/`_INPUT_BUFFER_DEPTH_FLITS`/`_OUTPUT_STAGE_DEPTH_FLITS`
literals. Both are now gone:

- `canonical.compose_deterministic_candidate` is the ONE deterministic
  derivation engine. It takes explicit candidate semantics (route,
  resolved route, VC assignment) and produces every downstream artifact
  and the terminal `ResolvedFabric`.
- `compile_deterministic_candidate` derives those semantics from a policy
  and calls the composer.
- `build_resolved_bundle_v3` derives those semantics from the v3 intent and
  calls the same composer.
- `orchestration` no longer defines `_derive_canonical_fabric`,
  `_bind_resolved` or `_make_bundle`; the baseline hardware settings live
  only in `candidate_policy.BASELINE_FABRIC_SETTINGS`.

Tests:
`test_both_compile_paths_funnel_through_one_composer` (both entry points
call the composer) and
`test_v3_orchestration_uses_the_single_baseline_settings` (no private
sequencer/constants).

### Why not a V2↔V3 identity parity test

Equivalence between a V2 request and a V3 request is **not defined** by the
current request types: a v3 request derives VC structure from declared
traffic classes, so a design with no requirement/collective is
unrepresentable in v3 (it refuses), whereas the v2 baseline synthesizes a
`default` class. The generation-independent children (topology, mapping,
attachment, address decode) are shared by construction once the composer is
single. A request-equivalence definition (V3→candidate semantics
translation) remains the next step if the two inputs must be asserted
equal; recorded as a non-blocking limitation.
