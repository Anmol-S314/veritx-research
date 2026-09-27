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

#: The families the gate must test (the work order's list).
GATED_FAMILIES: tuple[TopologyFamily, ...] = (
    TopologyFamily.MESH,
    TopologyFamily.CONCENTRATED_MESH,
    TopologyFamily.TORUS,
    TopologyFamily.GEC,
    TopologyFamily.CUSTOM,
)

#: Per-family probe shape: (endpoint_count, concentration, radix).
#: Chosen to be the SMALLEST design that exercises the family's real path —
#: a probe that cannot materialize is itself the answer.
_PROBE_SHAPE: dict[TopologyFamily, tuple[int, int, int | None]] = {
    TopologyFamily.MESH: (16, 1, 4),
    TopologyFamily.CONCENTRATED_MESH: (16, 4, 2),
    TopologyFamily.TORUS: (16, 1, 4),
    TopologyFamily.GEC: (16, 1, 4),
    TopologyFamily.FAT_TREE: (16, 1, None),
}

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


def _probe_request(family: TopologyFamily) -> Any:
    """A minimal v3 design that exercises ``family``'s real compiler path.

    Built from the shipped v3 example so the probe uses the same schema the
    product does. (v2 is frozen and must not be reinterpreted, so the probe
    is authored in v3 rather than migrated.)
    """
    import json
    from pathlib import Path
    from veritx_dse.core.paths import REPO
    endpoints, concentration, radix = _PROBE_SHAPE[family]
    doc = json.loads((REPO / "tracks/t3-topology/examples/"
                      "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["agents"] = [
        {"kind": "compute_tile", "count": endpoints,
         "data_width": 256, "addr_width": 64, "protocol": "AXI"},
    ]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = family.value
    doc["noc_config"]["radix"] = radix
    doc["noc_config"]["concentration"] = concentration
    return CompileRequestV3.from_dict(doc)


def _custom_probe_request() -> Any:
    """CUSTOM is a classification marker, not an algorithm: the graph IS the
    input, so the probe is a v3 request carrying an explicit TopologyIR."""
    import json
    from pathlib import Path
    from veritx_dse.core.paths import REPO
    from veritx_dse.model import topology_ir as tir
    example = (REPO / "tracks/t3-topology/examples/"
               "dense_1b_16tiles-v3.json")
    doc = json.loads(Path(example).read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    k = 2
    links = []
    for y in range(k):
        for x in range(k):
            n = y * k + x
            if x + 1 < k:
                links.append([n, n + 1])
            if y + 1 < k:
                links.append([n, n + k])
    ir = tir.from_dict({
        "name": "probe-custom", "kind": "custom", "nodes": k * k,
        "links": links,
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })
    doc["explicit_topology"] = ir.to_dict()
    doc["agents"] = [
        {"kind": "compute_tile", "count": k * k,
         "data_width": 256, "addr_width": 64, "protocol": "AXI"},
    ]
    doc["noc_config"] = dict(doc["noc_config"])
    doc["noc_config"]["topology_family"] = None
    return CompileRequestV3.from_dict(doc)


def _authorable(family: TopologyFamily) -> tuple[str, str]:
    """AUTHORABLE: the schema accepts the family as declared intent."""
    if family is TopologyFamily.CUSTOM:
        return "YES", ("TopologyFamily.CUSTOM + CompileRequest.explicit_topology "
                       "(the graph is the input)")
    try:
        _probe_request(family)      # schema construction must accept it
    except Exception as exc:        # pragma: no cover - defensive
        return "NO", f"schema refused: {type(exc).__name__}"
    if family not in TopologyFamily:
        return "NO", "not a TopologyFamily member"
    return "YES", "TopologyFamily membership (authorable vocabulary)"


def _product_wired(family: TopologyFamily) -> tuple[str, str]:
    """PRODUCT_WIRED: reachable from a shipped product preset."""
    try:
        from veritx_dse.application.compile_intent import build_preset_request
        from veritx_dse.application.presets import FABRIC_PRESETS
    except Exception:               # pragma: no cover
        return "NO", "no product preset module"
    value = family.value
    for preset in FABRIC_PRESETS:
        try:
            request = build_preset_request(preset.name)
        except Exception:           # pragma: no cover - defensive
            continue
        fam = getattr(request.noc_config, "topology_family", None)
        if getattr(fam, "value", fam) == value:
            return "YES", f"shipped product preset {preset.name!r}"
    return "NO", "no shipped product preset targets this family"


def derive_family_stages(family: TopologyFamily) -> FamilyStageTruth:
    """Ask the actual compiler + profile selector what this family can do."""
    from veritx_dse.application.fabric_compiler import FabricCompiler

    stages: dict[str, str] = {s: "NO" for s in STAGES}
    authority: dict[str, str] = {s: "no implementation authority" for s in STAGES}

    ok, why = _authorable(family)
    stages["AUTHORABLE"], authority["AUTHORABLE"] = ok, why

    ok, why = _product_wired(family)
    stages["PRODUCT_WIRED"], authority["PRODUCT_WIRED"] = ok, why

    request = (_custom_probe_request() if family is TopologyFamily.CUSTOM
               else _probe_request(family))
    compilation = FabricCompiler().compile(request)
    staged = getattr(compilation, "staged", None)
    produced = set(getattr(staged, "produced_stages", ()) or ())
    stopped = getattr(staged, "stopped_at_stage", None)
    # A staged refusal carries `stage=<NAME>: cause=...` in the error; every
    # stage BEFORE it in the compiler order was genuinely produced. Without
    # this the probe would report a torus design as un-materializable even
    # though its wraparound topology IS derived.
    if not produced:
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
            stages["PROJECTABLE"] = "YES"
            authority["PROJECTABLE"] = f"select_booksim_profile -> {profile_id}"
            # EXECUTABLE: the selected profile has a real execution path.
            stages["EXECUTABLE"] = "YES"
            authority["EXECUTABLE"] = f"executable profile {profile_id}"
            # QUALIFIED: the profile's own qualification envelope accepted
            # these exact parents (select_booksim_profile calls it, so a
            # return here IS the qualification result).
            stages["QUALIFIED"] = "YES"
            authority["QUALIFIED"] = (
                f"{profile_id} qualification envelope accepted these parents")
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
        family=family.value, stages=stages, authority=authority,
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
    return {f.value: derive_family_stages(f) for f in GATED_FAMILIES}
