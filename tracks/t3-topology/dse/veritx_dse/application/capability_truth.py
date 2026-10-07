"""capability_truth — live topology stage truth, derived from the compiler.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from veritx_dse.model.compile_model import CompileRequestV3, TopologyFamily
from veritx_dse.application.booksim_qualification_registry import (
    EXECUTION_HANDLERS as EXECUTION_HANDLERS_VIEW,
    QualificationRegistryError,
)
from veritx_dse.backend.booksim_projection import BookSimProjectionError
from veritx_dse.core.errors import Refusal

from veritx_dse.model.topology_intent import (  # noqa: E402
    AUTHORABLE_INTENT_KINDS, StructuredTopologyIntent, ConcentratedMeshIntent, ExplicitTopologyIntent,
    FatTreeIntent, FlatFlyIntent, GecMode, GecTopologyIntent, MeshIntent,
    SrotaIntent, TorusIntent, capability_family_label,
)
from veritx_dse.model.family_registry import spec_for
from veritx_dse.model.topology_artifact import STRUCTURED_FAMILIES

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
        "mesh": MeshIntent(side_length=4, concentration=1),        "concentrated_mesh": ConcentratedMeshIntent(side_length=2,
                                                    concentration=4),
        "torus": TorusIntent(side_length=5, concentration=1),
        "flatfly": FlatFlyIntent(radix_per_dimension=2, dimension_count=2,
                                 concentration=1),
        "fattree": FatTreeIntent(switch_radix=4, level_count=2),
        "explicit": ExplicitTopologyIntent(graph=graph),
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
        "srota": SrotaIntent.from_dict({
            "kind": "srota", "side_length": 4, "concentration": 2,
            "mecs_row": True, "mecs_col": True, "drop_latency": 1,
            "planes": ["d", "t"], "island_columns": [],
            "path_shapes": ["row"], "vc_policy": "none",
            "sidebuf_enable": True, "sidebuf_watermark": 6,
            "tel_period": 4, "tel_latency": 8,
        }),
    }
    for family, spec in STRUCTURED_FAMILIES.items():
        fields = spec["fields"]
        out[family] = StructuredTopologyIntent(
            family=family, params={f: 2 for f in fields})
    for label, intent in out.items():
        assert capability_family_label(intent) == label, (label, intent.kind)
    return out

PROBE_INTENTS: dict[str, Any] = _probe_intents()

GATED_KINDS: tuple[str, ...] = tuple(sorted(PROBE_INTENTS))

def missing_probe_kinds() -> tuple[str, ...]:
    """Registered authorable kinds with NO probe factory.

    MUST be empty. A new topology kind that is not gated would otherwise be
    silently absent from capability truth — the exact failure the previous
    hardcoded family list had.
    """
    covered = {capability_family_label(i) for i in PROBE_INTENTS.values()}
    required: set[str] = set()
    for kind in AUTHORABLE_INTENT_KINDS:
        # A kind with sub-labels is declarable once per sub-label:
        # gec -> gec_express/gec_mecs, structured -> its families.
        if kind == "structured":
            required |= set(STRUCTURED_FAMILIES)
            continue
        modes = spec_for(kind)["modes"]
        if modes:
            required |= {f"{kind}_{m}" for m in modes}
        else:
            required.add(kind)
    return tuple(sorted(required - covered))

STAGES: tuple[str, ...] = (
    "AUTHORABLE", "MATERIALIZABLE", "ROUTABLE", "VERIFIABLE",
    "PROJECTABLE", "EXECUTABLE", "QUALIFIED", "PRODUCT_WIRED",
)

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

Rationale: docs/decisions/modules/application.md
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
    request = migrate_v3_to_v4(v3, topology_intent=intent)
    if kind == "torus":
        # The supported torus profile requires X<->Y blocking dependencies
        # to derive its two dateline VCs. Reuse the shipped preset's explicit
        # dependency policy; keep the one-VC default refusal covered separately.
        from veritx_dse.application.presets import build_typed_preset_request
        torus_preset = build_typed_preset_request("torus25")
        request = replace(request, dependencies=torus_preset.dependencies)
    return request

def _probe_endpoints(intent: Any) -> int:
    """Endpoint count for a probe: enough to seat the declared structure.

    Derived from the INTENT, so a probe cannot silently test a different
    shape than the one it declares.
    """
    from veritx_dse.model.topology_intent import (
        ConcentratedMeshIntent, ExplicitTopologyIntent, FatTreeIntent,
        FlatFlyIntent, GecTopologyIntent, MeshIntent, SrotaIntent,
        TorusIntent,
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
    if isinstance(intent, SrotaIntent):
        return intent.side_length ** 2 * intent.concentration
    if isinstance(intent, FatTreeIntent):
        return intent.endpoint_capacity
    if getattr(intent, "kind", None) == "structured":
        # Correct by construction: seat exactly the graph the family builds.
        from veritx_dse.model.topology_artifact import structured_graph
        return structured_graph(intent.family, intent.params).nodes
    raise ValueError(f"no probe size law for {type(intent).__name__}")

def _authorable(kind: str) -> tuple[str, str]:
    """AUTHORABLE: the v4 schema accepts the declaration.

    This is a REAL observation (constructing the probe request), not a
    membership lookup: a kind can be registered and still be refused by the
    schema, and that difference matters.
    """
    try:
        _probe_request(kind)
    except (Refusal, ValueError) as exc:
        return "NO", f"schema refused: {type(exc).__name__}: {str(exc)[:120]}"
    return "YES", (f"CompileRequestV4 accepted topology kind "
                   f"{PROBE_INTENTS[kind].kind!r}")

def _product_wired(kind: str) -> tuple[str, str]:
    """PRODUCT_WIRED: reachable from a shipped product preset."""
    try:
        from veritx_dse.application.compile_intent import build_preset_request
        from veritx_dse.application.presets import (
            FABRIC_PRESETS, build_typed_preset_request, typed_preset_names,
        )
        from veritx_dse.model.compile_model import fabric_intent_view
    except ImportError:            # pragma: no cover
        return "NO", "no product preset module"
    want = capability_family_label(PROBE_INTENTS[kind])
    factories = [(p.name, build_preset_request) for p in FABRIC_PRESETS]
    factories += [(n, build_typed_preset_request) for n in typed_preset_names()]
    for name, factory in factories:
        try:
            request = factory(name)
            view = fabric_intent_view(request)
        except (Refusal, ValueError):  # pragma: no cover - defensive
            continue
        actual = capability_family_label(view.topology)
        if actual == want:
            return "YES", (
                f"shipped product preset {name!r} normalizes to "
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
    failed_stage = {
        "TOPOLOGY": "MATERIALIZABLE",
        "ROUTING": "ROUTABLE",
        "ROUTING_REALIZATION": "VERIFIABLE",
        "VERIFICATION": "VERIFIABLE",
        "VERIFICATION_BUNDLE": "VERIFIABLE",
        "PROJECTION": "PROJECTABLE",
        "EXECUTION": "EXECUTABLE",
        "QUALIFICATION": "QUALIFIED",
        "PRESET": "PRODUCT_WIRED",
    }.get(stopped)
    if (failed_stage
            and authority.get(failed_stage) == "no implementation authority"):
        authority[failed_stage] = (
            f"compiler stopped at {stopped}: {refusal or compilation.status}")

    for comp_stage, cap_stage in _STAGE_PROOF.items():
        if comp_stage in produced:
            stages[cap_stage] = "YES"
            authority[cap_stage] = f"compiler produced stage {comp_stage}"
    _direct_topo = None
    if stages["MATERIALIZABLE"] == "NO":
        try:
            from veritx_dse.compiler.orchestration import (
                probe_direct_materialize,
            )
            _direct_topo = probe_direct_materialize(
                request, PROBE_INTENTS[kind])
            _thash = _direct_topo.topology_hash()
            stages["MATERIALIZABLE"] = "YES"
            authority["MATERIALIZABLE"] = (
                "direct materialization probe produced TopologyArtifact "
                f"{str(_thash)[:18]}… (compiler dropped stages on the "
                f"{compilation.status} path)")
        except Exception as exc:
            authority["MATERIALIZABLE"] = (
                f"direct materialization probe refused: "
                f"{type(exc).__name__}: {str(exc)[:160]}")
    if _direct_topo is not None and stages["ROUTABLE"] == "NO":
        try:
            from veritx_dse.compiler.orchestration import (
                probe_direct_route,
            )
            _route = probe_direct_route(request, _direct_topo)
            _rclass = getattr(_route, 'routing_class', None) or getattr(
                _route, 'routing_classes', 'route')
            stages["ROUTABLE"] = "YES"
            authority["ROUTABLE"] = (
                "direct route-derivation probe produced "
                f"{_rclass} (compiler dropped stages on the "
                f"{compilation.status} path)")
        except Exception as exc:
            authority["ROUTABLE"] = (
                f"direct route probe refused: {type(exc).__name__}: "
                f"{str(exc)[:160]}")

    profile_id: str | None = None
    bundle = getattr(compilation, "bundle", None)
    if bundle is None:
        authority["PROJECTABLE"] = (
            f"no COMPILED bundle ({compilation.status}): the real "
            "preparation path is unreached")
        authority["EXECUTABLE"] = (
            f"no COMPILED bundle ({compilation.status}): no profile "
            "reached execution-handler resolution")
        authority["QUALIFIED"] = (
            f"no COMPILED bundle ({compilation.status}): no qualifying "
            "profile")
    if compilation.status == "COMPILED" and bundle is not None:
        stages["MATERIALIZABLE"] = "YES"
        authority["MATERIALIZABLE"] = (
            f"compiler produced TopologyArtifact family "
            f"{getattr(bundle.topology.family, 'value', bundle.topology.family)}")
        stages["ROUTABLE"] = "YES"
        from veritx_dse.model.routing_realization import (
            route_artifact_identity,
        )
        authority["ROUTABLE"] = (
            f"compiler derived RouteArtifact "
            f"{route_artifact_identity(bundle.router_route)[:18]}…")
        stages["VERIFIABLE"] = "YES"
        authority["VERIFIABLE"] = "compiler produced the full bundle"
        try:
            from veritx_dse.backend.booksim_projection import (
                select_booksim_profile,
            )
            parents = _parents_from_bundle(bundle, request)
            profile = select_booksim_profile(parents)
            profile_id = profile.profile_id
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
            except (Refusal, BookSimProjectionError
                    ) as prep_exc:
                stages["PROJECTABLE"] = "NO"
                authority["PROJECTABLE"] = (
                    f"select_booksim_profile -> {profile_id}, but the "
                    f"preparer refused: {type(prep_exc).__name__}: "
                    f"{str(prep_exc)[:140]}")
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
            qualified, qual_authority = evaluate_qualification(profile,
                                                               parents)
            stages["QUALIFIED"] = "YES" if qualified else "NO"
            authority["QUALIFIED"] = qual_authority
        except (Refusal, BookSimProjectionError,
                QualificationRegistryError) as exc:
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
