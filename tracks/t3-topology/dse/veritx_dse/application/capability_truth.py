"""capability_truth — LIVE topology stage truth, derived from the compiler.

WHY THIS EXISTS
===============

We have repeatedly shipped documentation that claimed a capability the
compiler or evaluator could not actually execute. The worst instance:
`docs/product/topology-family-registry.yaml` marks CONCENTRATED_MESH
`PROJECTABLE: YES, EXECUTABLE: YES, QUALIFIED: YES`, while
`select_booksim_profile()` has exactly two profiles — a native mesh-DOR
profile whose guard is `TopologyArtifact.family is MaterializedFamily.MESH`,
and the AnyNet profile, which requires `ANYNET_MIN_HOPS`. Concentrated mesh
materializes as `MaterializedFamily.CONCENTRATED_MESH` and routes `DOR_XY`,
so it satisfies NEITHER. The registry was describing an intention, not a
fact.

THE LAW
=======

A descriptive registry may add prose and provenance. It may NOT claim a
stage that has no implementation authority. This module derives the stage
truth by ASKING THE ACTUAL IMPLEMENTATION — compiling a probe design and
running the real profile selector — and `scripts/check_capability_truth.py`
fails CI when the registry disagrees.

Stages are derived independently. One becoming YES never implies another.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from veritx_dse.model.compile_model import CompileRequestV3, TopologyFamily
from veritx_dse.application.booksim_qualification_registry import (
    EXECUTION_HANDLERS as EXECUTION_HANDLERS_VIEW,
)

#: §18.1 — PROBE COVERAGE IS DERIVED FROM THE TOPOLOGY-INTENT REGISTRY.
#:
#: A hand-maintained family list drifts: the previous one came from the
#: legacy `TopologyFamily` enum and therefore could not see FlatFly or
#: FatTree at all, even though both became authorable. Coverage is now
#: `AUTHORABLE_INTENT_KINDS` plus the GEC physical subfamilies (GEC is one
#: registered kind but four modes that progress differently, so reporting it
#: as one row would hide which subfamilies can advance).
#:
#: A registered kind with NO probe factory is a GATE FAILURE, not a silent
#: omission — see `missing_probe_kinds()`.
from veritx_dse.model.topology_intent import (  # noqa: E402
    AUTHORABLE_INTENT_KINDS, ConcentratedMeshIntent, ExplicitTopologyIntent,
    FatTreeIntent, FlatFlyIntent, GecMode, GecTopologyIntent, MeshIntent,
    TorusIntent, capability_family_label,
)

#: Capability-truth key -> the intent the probe declares. The probe SHAPE
#: lives with the probe (§18.2: no second shape table). Each is the SMALLEST
#: design that exercises the family's real path — a probe that cannot
#: materialize is itself the answer.
def _probe_intents() -> dict[str, Any]:
    from veritx_dse.model import topology_ir as tir
    k = 2
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                links.append([n, n + 1])
            if y + 1 < k:
                links.append([n, n + k])
    graph = tir.from_dict({
        "name": "probe-custom", "kind": "custom", "nodes": k * k,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })
    out: dict[str, Any] = {
        "mesh": MeshIntent(side_length=4, concentration=1),
        "concentrated_mesh": ConcentratedMeshIntent(side_length=2,
                                                    concentration=4),
        "torus": TorusIntent(side_length=4, concentration=1),
        "flatfly": FlatFlyIntent(radix_per_dimension=2, dimension_count=2,
                                 concentration=4),
        "fattree": FatTreeIntent(switch_radix=4, level_count=2),
        "explicit": ExplicitTopologyIntent(graph=graph),
        # GEC is one registered kind, four physical modes.
        "gec_mesh": GecTopologyIntent(mode=GecMode.MESH, grid_side_length=8,
                                      concentration=1),
        "gec_express": GecTopologyIntent(
            mode=GecMode.EXPRESS, grid_side_length=8, concentration=1,
            express_channel_groups_per_dimension=7,
            destinations_per_express_channel=1),
        "gec_multidrop": GecTopologyIntent(
            mode=GecMode.MULTIDROP, grid_side_length=8, concentration=1,
            express_channel_groups_per_dimension=1,
            destinations_per_express_channel=7),
        "gec_hybrid": GecTopologyIntent(
            mode=GecMode.HYBRID, grid_side_length=8, concentration=1,
            express_channel_groups_per_dimension=7,
            destinations_per_express_channel=1),
    }
    for label, intent in out.items():
        assert capability_family_label(intent) == label, (label, intent.kind)
    return out


PROBE_INTENTS: dict[str, Any] = _probe_intents()

#: The capability-truth rows the gate must produce.
GATED_KINDS: tuple[str, ...] = tuple(sorted(PROBE_INTENTS))


def missing_probe_kinds() -> tuple[str, ...]:
    """Registered authorable kinds with NO probe factory.

    MUST be empty. A new topology kind that is not gated would otherwise be
    silently absent from capability truth — the exact failure the previous
    hardcoded family list had.
    """
    covered = {capability_family_label(i) for i in PROBE_INTENTS.values()}
    # A registered kind is satisfied when EVERY subfamily label it expands to
    # is probed: GEC is one registered kind but four physical modes, and all
    # four must be gated.
    required: set[str] = set()
    for kind in AUTHORABLE_INTENT_KINDS:
        if kind == "gec":
            required |= {f"gec_{m.value}" for m in GecMode}
        else:
            required.add(kind)
    return tuple(sorted(required - covered))

STAGES: tuple[str, ...] = (
    "AUTHORABLE", "MATERIALIZABLE", "ROUTABLE", "VERIFIABLE",
    "PROJECTABLE", "EXECUTABLE", "QUALIFIED", "PRODUCT_WIRED",
)

#: Compiler stage -> the capability stage it proves.
_STAGE_PROOF: dict[str, str] = {
    "TOPOLOGY": "MATERIALIZABLE",
    "ROUTING": "ROUTABLE",
    "RESOLVED_ROUTE": "VERIFIABLE",
}


@dataclass(frozen=True)
class FamilyStageTruth:
    """One family's stage truth, with the authority that produced it."""
    family: str
    stages: dict[str, str]
    authority: dict[str, str]
    stopped_at_stage: str | None = None
    profile_id: str | None = None
    refusal: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "stages": dict(self.stages),
            "authority": dict(self.authority),
            "stopped_at_stage": self.stopped_at_stage,
            "profile_id": self.profile_id,
            "refusal": self.refusal,
        }


def _probe_request(kind: str) -> Any:
    """A minimal V4 design that exercises ``kind``'s real compiler path.

    Authored in v4 because v4 is where typed topology intent lives — and
    because the probe must exercise the SAME vocabulary a user declares.
    Built from the shipped v3 example's workload so the probe uses the same
    science the product does; the workload is migrated, the topology is
    declared.

    A kind whose probe cannot even be CONSTRUCTED is a gate failure: the
    intent registry and the probe registry must agree.
    """
    import json
    from pathlib import Path
    from veritx_dse.core.paths import REPO
    from veritx_dse.model.compile_model import CompileRequestV3
    from veritx_dse.model.compile_request_v4 import migrate_v3_to_v4

    intent = PROBE_INTENTS[kind]
    endpoints = _probe_endpoints(intent)
    doc = json.loads((REPO / "tracks/t3-topology/examples/"
                      "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["agents"] = [
        {"kind": "compute_tile", "count": endpoints,
         "data_width": 256, "addr_width": 64, "protocol": "AXI"},
    ]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = None
    doc["noc_config"]["radix"] = None
    doc["noc_config"]["concentration"] = None
    v3 = CompileRequestV3.from_dict(doc)
    return migrate_v3_to_v4(v3, topology_intent=intent)


def _probe_endpoints(intent: Any) -> int:
    """Endpoint count for a probe: enough to seat the declared structure.

    Derived from the INTENT, so a probe cannot silently test a different
    shape than the one it declares.
    """
    from veritx_dse.model.topology_intent import (
        ConcentratedMeshIntent, ExplicitTopologyIntent, FatTreeIntent,
        FlatFlyIntent, GecTopologyIntent, MeshIntent, TorusIntent,
    )
    if isinstance(intent, ExplicitTopologyIntent):
        return intent.graph.nodes
    if isinstance(intent, (MeshIntent, TorusIntent)):
        return intent.side_length ** 2 * intent.concentration
    if isinstance(intent, ConcentratedMeshIntent):
        return intent.side_length ** 2 * intent.concentration
    if isinstance(intent, FlatFlyIntent):
        return (intent.radix_per_dimension ** intent.dimension_count
                * intent.concentration)
    if isinstance(intent, GecTopologyIntent):
        return intent.grid_side_length ** 2 * intent.concentration
    if isinstance(intent, FatTreeIntent):
        return intent.endpoint_capacity
    raise ValueError(f"no probe size law for {type(intent).__name__}")


def _authorable(kind: str) -> tuple[str, str]:
    """AUTHORABLE: the v4 schema accepts the declaration.

    This is a REAL observation (constructing the probe request), not a
    membership lookup: a kind can be registered and still be refused by the
    schema, and that difference matters.
    """
    try:
        _probe_request(kind)
    except Exception as exc:                                # noqa: BLE001
        return "NO", f"schema refused: {type(exc).__name__}: {str(exc)[:120]}"
    return "YES", (f"CompileRequestV4 accepted topology kind "
                   f"{PROBE_INTENTS[kind].kind!r}")


def _product_wired(kind: str) -> tuple[str, str]:
    """PRODUCT_WIRED: reachable from a shipped product preset.

    PHASE B.2 §8 — NO FAMILY-NAME SHORTCUT. Comparing a legacy
    `topology_family` string against `intent.kind` conflates all four GEC
    physical modes, because `.kind == "gec"` for every one of them: a single
    future generic GEC preset would make gec_mesh, gec_express, gec_multidrop
    AND gec_hybrid all read PRODUCT_WIRED even if it declared only one mode.

    Instead the preset request is normalized through the REAL generation seam
    and the resulting intent's capability label is compared with the probed
    label. A legacy Mesh preset still normalizes to Mesh; a future v4 GEC
    preset keeps its exact mode.
    """
    try:
        from veritx_dse.application.compile_intent import build_preset_request
        from veritx_dse.application.presets import FABRIC_PRESETS
        from veritx_dse.model.compile_model import fabric_intent_view
    except Exception:               # pragma: no cover
        return "NO", "no product preset module"
    want = capability_family_label(PROBE_INTENTS[kind])
    for preset in FABRIC_PRESETS:
        try:
            request = build_preset_request(preset.name)
            view = fabric_intent_view(request)
        except Exception:           # pragma: no cover - defensive
            continue
        actual = capability_family_label(view.topology)
        if actual == want:
            return "YES", (
                f"shipped product preset {preset.name!r} normalizes to "
                f"topology {actual!r} (via the generation seam, not a "
                "family-name match)")
    return "NO", (f"no shipped product preset normalizes to topology "
                  f"{want!r}")


def derive_family_stages(kind: str) -> FamilyStageTruth:
    """Ask the actual compiler + profile selector what this family can do."""
    from veritx_dse.application.fabric_compiler import FabricCompiler

    stages: dict[str, str] = {s: "NO" for s in STAGES}
    authority: dict[str, str] = {s: "no implementation authority" for s in STAGES}

    ok, why = _authorable(kind)
    stages["AUTHORABLE"], authority["AUTHORABLE"] = ok, why

    ok, why = _product_wired(kind)
    stages["PRODUCT_WIRED"], authority["PRODUCT_WIRED"] = ok, why

    request = _probe_request(kind)
    compilation = FabricCompiler().compile(request)
    staged = getattr(compilation, "staged", None)
    produced = set(getattr(staged, "produced_stages", ()) or ())
    stopped = getattr(staged, "stopped_at_stage", None)
    # §18.3 — STRUCTURED stage recovery for the current generation.
    #
    # `StagedDerivation.produced_stages` / `.stopped_at_stage` are the
    # authority. The regex fallback is retained ONLY for the HISTORICAL v2
    # path, which is not decomposed into preserved stages and therefore has
    # no structured record to read; it is never consulted for a v3/v4 probe.
    if not produced and getattr(compilation, "request", None) is not None \
            and getattr(compilation.request, "schema_version", None) == 2:
        import re as _re
        m = _re.search(r"stage=([A-Z_]+)", str(getattr(compilation, "error", "")))
        if m:
            stopped = stopped or m.group(1)
            order = ("INVENTORY", "MAPPING", "TOPOLOGY", "ATTACHMENT",
                     "ROUTING", "RESOLVED_ROUTE", "VC_ASSIGNMENT",
                     "COMPOSE", "BUNDLE")
            if stopped in order:
                produced = set(order[:order.index(stopped)])
    refusal = str(getattr(compilation, "error", "") or "")

    for comp_stage, cap_stage in _STAGE_PROOF.items():
        if comp_stage in produced:
            stages[cap_stage] = "YES"
            authority[cap_stage] = f"compiler produced stage {comp_stage}"

    profile_id: str | None = None
    bundle = getattr(compilation, "bundle", None)
    if compilation.status == "COMPILED" and bundle is not None:
        stages["MATERIALIZABLE"] = "YES"
        authority["MATERIALIZABLE"] = (
            f"compiler produced TopologyArtifact family "
            f"{getattr(bundle.topology.family, 'value', bundle.topology.family)}")
        stages["ROUTABLE"] = "YES"
        authority["ROUTABLE"] = (
            f"compiler derived RouteArtifact "
            f"{bundle.router_route.route_table_hash[:18]}…")
        stages["VERIFIABLE"] = "YES"
        authority["VERIFIABLE"] = "compiler produced the full bundle"
        # PROJECTABLE / EXECUTABLE / QUALIFIED come from the REAL selector.
        try:
            from veritx_dse.backend.booksim_projection import (
                select_booksim_profile,
            )
            parents = _parents_from_bundle(bundle, request)
            profile = select_booksim_profile(parents)
            profile_id = profile.profile_id
            # PROJECTABLE is a SEPARATE question from selection: it is
            # answered by the REAL preparation path, which is what actually
            # produces backend input. Selecting a profile is necessary but
            # not sufficient, and the binary is NOT spawned to answer it.
            try:
                from veritx_dse.backend.booksim_projection import (
                    prepare_booksim_input,
                )
                prepared = prepare_booksim_input(parents)
                pid = getattr(prepared, "prepared_id", None)
                pid = pid() if callable(pid) else pid
                stages["PROJECTABLE"] = "YES"
                authority["PROJECTABLE"] = (
                    f"prepare_booksim_input produced {str(pid)[:18]}… under "
                    f"profile {profile_id}")
            except Exception as prep_exc:                   # noqa: BLE001
                stages["PROJECTABLE"] = "NO"
                authority["PROJECTABLE"] = (
                    f"select_booksim_profile -> {profile_id}, but the "
                    f"preparer refused: {type(prep_exc).__name__}: "
                    f"{str(prep_exc)[:140]}")
            # EXECUTABLE is IMPLEMENTATION AVAILABILITY — and it is
            # FAIL-CLOSED: the registered handler must RESOLVE to a callable.
            # Merely finding a registry string would let a typo read as
            # availability until a test happened to catch it, so the live
            # truth calls the same resolver the gate does.
            from veritx_dse.application.booksim_qualification_registry import (
                evaluate_qualification, resolve_execution_handler,
            )
            handler, handler_err = resolve_execution_handler(profile_id)
            stages["EXECUTABLE"] = "YES" if handler is not None else "NO"
            authority["EXECUTABLE"] = (
                f"execution implementation "
                f"{EXECUTION_HANDLERS_VIEW.get(profile_id)} resolves to a "
                f"callable" if handler is not None else handler_err or "no "
                "execution implementation")
            # QUALIFIED is SCIENTIFIC QUALIFICATION, from ONE registry, and
            # it is decided by the REAL qualifier over the REAL canonical
            # parents under an EXACT projection-semantics match. Selecting a
            # profile, or preparing it, never implies qualification.
            qualified, qual_authority = evaluate_qualification(profile,
                                                               parents)
            stages["QUALIFIED"] = "YES" if qualified else "NO"
            authority["QUALIFIED"] = qual_authority
        except Exception as exc:
            stages["PROJECTABLE"] = "NO"
            authority["PROJECTABLE"] = (
                f"select_booksim_profile refused: {type(exc).__name__}: "
                f"{str(exc)[:160]}")
            stages["EXECUTABLE"] = "NO"
            authority["EXECUTABLE"] = "no profile reached execution"
            stages["QUALIFIED"] = "NO"
            authority["QUALIFIED"] = "no qualifying profile"

    return FamilyStageTruth(
        family=kind, stages=stages, authority=authority,
        stopped_at_stage=stopped, profile_id=profile_id, refusal=refusal)


def _parents_from_bundle(bundle: Any, request: Any) -> Any:
    """Build BookSimProjectionParents exactly as the evaluator does.

    This is the SAME construction `FabricEvaluator.evaluate` performs before
    it calls `prepare_booksim_input`, so the probe asks the real projection
    rather than a parallel one.
    """
    from veritx_dse.backend.booksim_projection import BookSimProjectionParents
    from veritx_dse.model.vc_resource import vc_resources_from_assignment
    from veritx_dse.workload.intent_lowering import lower_compile_workload
    from veritx_dse.workload.messages import LogicalMessageArtifactV2
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV2
    from veritx_dse.workload.graph import WorkloadGraph

    lowered = lower_compile_workload(request)
    graph = lowered.graph
    if not isinstance(graph, WorkloadGraph):
        graph = WorkloadGraph(
            parallelism=bundle.design.workload.parallelism
            if hasattr(bundle.design.workload, "parallelism") else None,
            participant_count=getattr(lowered, "participant_count", 0),
            operations=tuple(getattr(lowered, "operations", ()) or ()),
        )
    logical = LogicalMessageArtifactV2(graph=graph)
    traffic = PhysicalTrafficArtifactV2(
        logical=logical, resolved_fabric=bundle.resolved_fabric,
        mapping=bundle.mapping, attachment=bundle.attachment,
        inventory=bundle.inventory, packet_format=bundle.packet_format)
    return BookSimProjectionParents(
        resolved_fabric=bundle.resolved_fabric,
        topology=bundle.topology,
        attachment=bundle.attachment,
        mapping=bundle.mapping,
        vc_resource=vc_resources_from_assignment(bundle.vc_assignment),
        vc_assignment=bundle.vc_assignment,
        packet_format=bundle.packet_format,
        route=bundle.router_route,
        physical_traffic=traffic,
    )


def derive_all_stages() -> dict[str, FamilyStageTruth]:
    return {k: derive_family_stages(k) for k in GATED_KINDS}
