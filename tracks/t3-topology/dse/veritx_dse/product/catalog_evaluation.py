"""One frozen workload evaluated on every catalog fabric by real backends.

The compiler and backend adapters own mapping, trace generation, execution
and evidence. A catalog run changes no project draft or revision.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import VeritXError
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import topology_intent_from_dict
from veritx_dse.optimization.definition import Objective
from veritx_dse.optimization.real_evaluator import RealCandidateEvaluator
from veritx_dse.optimization.topology_search import TopologyProposal, evaluate_candidate
from veritx_dse.workload.intent_lowering import lower_compile_workload

# Stable catalog identities, not a scalar topology_family search domain.
CATALOG = (
    ('mesh', 'Mesh'), ('concentrated_mesh', 'Concentrated mesh'),
    ('torus', 'Torus'), ('fattree', 'Fat-tree'), ('flatfly', 'Flatfly'),
    ('srota', 'Srota'), ('gec_mecs', 'GEC MECS'), ('gec_hybrid', 'GEC hybrid'),
    ('qtree_native', 'QTree'), ('tree4_native', 'Tree4'),
    ('ring_native', 'Ring'), ('fly_native', 'Fly'),
)
QUESTIONS = (EvaluationQuestion.NETWORK_COMPLETION, EvaluationQuestion.SYSTEM_MAKESPAN)
MAX_ENDPOINTS = 256
BACKEND_TIMEOUT_S = 60


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: Any) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(document, indent=2))
    temporary.replace(path)


def catalog_for(request: CompileRequestV4) -> list[dict[str, Any]]:
    """Complete typed intents, sized to seat the unchanged agent inventory."""
    count = sum(agent.count for agent in request.agents)
    if not 1 <= count <= MAX_ENDPOINTS:
        raise ValueError(f'Catalog evaluation supports 1–{MAX_ENDPOINTS} endpoint agents; no inventory is resized.')
    side = max(2, math.ceil(math.sqrt(count)))
    concentrated = max(2, math.ceil(math.sqrt(math.ceil(count / 4))))
    odd_side = side if side % 2 else side + 1
    radix = 2
    while radix * radix < count:
        radix *= 2
    gec_side = max(3, side)
    intents = {
        'mesh': dict(kind='mesh', side_length=side, concentration=1),
        'concentrated_mesh': dict(kind='concentrated_mesh', side_length=concentrated, concentration=4),
        'torus': dict(kind='torus', side_length=odd_side, concentration=1),
        'fattree': dict(kind='fattree', switch_radix=radix, level_count=2),
        'flatfly': dict(kind='flatfly', radix_per_dimension=side, dimension_count=2, concentration=1),
        'srota': dict(kind='srota', side_length=side, concentration=1, mecs_row=True, mecs_col=True,
                      drop_latency=1, planes=['d'], island_columns=[], path_shapes=['row', 'column'],
                      vc_policy='rank', sidebuf_enable=True, sidebuf_watermark=6, tel_period=4, tel_latency=8),
        'gec_mecs': dict(kind='gec', mode='multidrop', grid_side_length=gec_side, concentration=1,
                         express_channel_groups_per_dimension=1, destinations_per_express_channel=gec_side - 1),
        'gec_hybrid': dict(kind='gec', mode='hybrid', grid_side_length=gec_side, concentration=1,
                           express_channel_groups_per_dimension=1, destinations_per_express_channel=gec_side - 1),
        'qtree_native': dict(kind='qtree_native', radix=4, levels=3),
        'tree4_native': dict(kind='tree4_native', radix=4, levels=3),
        'ring_native': dict(kind='ring_native', router_count=max(3, count)),
        'fly_native': dict(kind='fly_native', radix=4, levels=3),
    }
    rows = []
    for key, label in CATALOG:
        reason = None
        if key in ('qtree_native', 'tree4_native', 'fly_native') and count > 64:
            reason = 'The native 4-ary, 3-level implementation has 64 terminal seats; this workload needs more.'
        # Parse even unavailable intents: malformed catalog definitions are a
        # programming error, never a misleading backend capability verdict.
        intent = topology_intent_from_dict(intents[key])
        rows.append({'topology_id': key, 'label': label, 'topology': intent.to_dict(), 'reason': reason})
    return rows


def workload_fingerprint(request: CompileRequestV4) -> str:
    document = request.to_dict()
    return content_id('veritx/catalog-workload-intent/v1', {
        key: document.get(key) for key in ('workload', 'compute', 'agents', 'requirements', 'dependencies', 'address_map')
    })


def candidate_for(base: CompileRequestV4, row: dict[str, Any]) -> TopologyProposal:
    request = replace(base, topology=topology_intent_from_dict(row['topology']))
    cid = 'catalog_' + content_id('veritx/catalog-candidate/v1', {
        'base_design_hash': base.design_hash(), 'design_hash': request.design_hash(),
    })
    return TopologyProposal(cid, base.design_hash(), request, f"Catalog fabric: {row['label']}")


# --- RTL finalization support ---------------------------------------------
#
# The catalog measures 12 topology families, but the product path has ONE RTL
# emitter: ``scripts/rtlgen/gen_rtl.py`` over ``rtl/mot_htree/gen_rtl_htree.py``.
# It is a 64-bit, 2-VC free/escape router over a connected, reciprocal,
# point-to-point graph. A fabric the catalog measured with a different VC/class
# scheme (GEC MECS, GEC hybrid, SROTA shared-wire, ...) has no matching emitter.
#
# This predicate is the ONE place that decides whether a selected fabric is
# inside the emitter's slice, so the product can name the reason instead of
# failing with a generic emitter error — or, worse, emitting 2-VC RTL for a
# fabric measured with a different scheme.

#: VCs the certified emitter implements: VC0 free, VC1 escape.
RTL_EMITTER_VC_COUNT = 2
#: The stage that owns the capability a refusal names.
RTL_OWNING_STAGE = 'RTL generation'

RTL_SUPPORTED_CERTIFIED = 'SUPPORTED_CERTIFIED_2VC'
RTL_SUPPORTED_SINGLE_CLASS = 'SUPPORTED_SINGLE_CLASS'
RTL_UNSUPPORTED_VC_SCHEME = 'UNSUPPORTED_VC_SCHEME'
RTL_UNSUPPORTED_SHARED_WIRE = 'UNSUPPORTED_SHARED_WIRE'
RTL_UNSUPPORTED_TOPOLOGY = 'UNSUPPORTED_TOPOLOGY'
RTL_UNSUPPORTED_VC_DERIVATION = 'UNSUPPORTED_VC_DERIVATION'
#: STAGE 1 fields whose RTL is not realized by the preview emitter.
#: M1 permission windows ARE realized in addr_decode.sv, M2 ordering /
#: traffic-class VC desires ARE realized in ordering_fsm.sv (OrderingFSM
#: + VC reassignment within the 2-VC slice), M3 crossings ARE realized
#: by emitted CdcCells, and all four M4 adapters (axi5 / chi / tilelink /
#: custom) ARE realized by the AdapterFactory shims. What remains refused:
#:   * any M2 policy outside the slice (VC>=2, shared wire, relaxed
#:     without a window, disagreeing per-group knobs → OrderingFSM).
#: A bare ``protocol="custom"`` without a burst/ordering param is
#: compile INVALID upstream (``PACKET_FORMAT``), never an RTL refusal.
#: Fail closed: refusing emission beats emitting RTL that drops the intent.
RTL_UNSUPPORTED_STAGE1_REALIZATION = 'UNSUPPORTED_STAGE1_REALIZATION'
#: The badge is a prediction from a topology-only compile; it failed loudly
#: rather than defaulting to "supported" or hiding the row.
RTL_PREDICTION_FAILED = 'PREDICTION_FAILED'


def _stage1_realization_demands(request: Any) -> list[str]:
    """STAGE 1 intents the preview emitter cannot realize (M4 only).

    Realized (deliberately not listed): M1 permission windows
    (``addr_decode.sv``), M2 ordering / traffic-class VC desires
    (``ordering_fsm.sv`` — slice boundary in :func:`_m2_ordering_issue`),
    M3 crossings (emitted CdcCells), all four M4 adapters (AdapterFactory
    axi5 burst-split/credit, chi SIZE-alignment/channel-map,
    tilelink UL framing, custom declared burst/ordering), and the M2
    credit/split knobs without a protocol (``ordering_fsm.sv``
    outstanding/split alignment). No M4 family demand remains: a bare
    custom without params is compile INVALID (``PACKET_FORMAT``), not
    an RTL-generation refusal, so it never reaches this gate.
    """
    # All closed-vocabulary families have a wrapper; every declared
    # protocol is realizable. The function is kept so rtl_support keeps
    # one M4 gate — future families would reappear here as
    # ADAPTER_UNSUPPORTED:<family> blockers, never a stub.
    return []


def _m2_ordering_issue(request: Any, shared_links: int) -> str | None:
    """Why an M2 policy is outside the OrderingFSM preview slice, else None.

    Delegates to the OrderingFSM deep module so the gate and the emitter
    share one definition of the slice (2 VCs, point-to-point, one agreed
    policy, relaxed needs a window). The reason names OrderingFSM.
    """
    from veritx_dse.product.ordering_fsm_rtl import (
        build_ordering_fsm, policy_from_request,
    )
    policy = policy_from_request(request)
    emission = build_ordering_fsm(
        policy, emitted_vcs=RTL_EMITTER_VC_COUNT, shared_wires=shared_links)
    if emission.verdict.ok:
        return None
    return emission.verdict.reason


@dataclass(frozen=True)
class RtlSupport:
    """Whether the product RTL emitter can serve a selected fabric, and why.

    ``vc_count`` is the VC count the catalog measured that fabric with.
    ``matches_certified_vc_count`` is True only for the exact 2-VC slice; a
    1-VC fabric is still served (by the emitter's free class, with the escape
    class unused), which is why support is ``vc_count <= RTL_EMITTER_VC_COUNT``
    rather than equality.
    """
    supported: bool
    code: str
    reason: str | None
    topology_kind: str | None
    topology_family: str | None
    vc_count: int | None
    emitted_vcs: int
    matches_certified_vc_count: bool
    shared_wire_links: int
    connected: bool | None
    reciprocal: bool | None
    router_count: int | None

    def to_dict(self) -> dict[str, Any]:
        return {
            'supported': self.supported,
            'code': self.code,
            'reason': self.reason,
            'topology_kind': self.topology_kind,
            'topology_family': self.topology_family,
            'vc_count': self.vc_count,
            'emitted_vcs': self.emitted_vcs,
            'matches_certified_vc_count': self.matches_certified_vc_count,
            'shared_wire_links': self.shared_wire_links,
            'connected': self.connected,
            'reciprocal': self.reciprocal,
            'router_count': self.router_count,
            'owner_stage': RTL_OWNING_STAGE,
        }


def _endpoint(channel: Any) -> tuple[int, int]:
    if isinstance(channel, dict):
        return channel['src_router'], channel['dst_router']
    return channel.src_router, channel.dst_router


def _topology_facts(topology: Any) -> tuple[str | None, int, list[int], list[tuple[int, int]]]:
    """Read (family, shared-wire count, router ids, directed edges) from
    either the persisted TopologyView dict or a TopologyArtifact."""
    if topology is None:
        return None, 0, [], []
    if isinstance(topology, dict):
        family = topology.get('family')
        shared = topology.get('shared_links') or ()
        counts = topology.get('counts') or {}
        shared_links = max(len(shared), int(counts.get('shared_links') or 0))
        routers = [r['router_id'] if isinstance(r, dict) else r.router_id
                   for r in (topology.get('routers') or ())]
        edges = [_endpoint(c) for c in (topology.get('channels') or ())]
        return family, shared_links, routers, edges
    family = getattr(topology, 'family', None)
    family = getattr(family, 'value', family)
    shared_links = len(getattr(topology, 'shared_links', ()) or ())
    routers = [r.router_id for r in getattr(topology, 'routers', ()) or ()]
    edges = [_endpoint(c) for c in getattr(topology, 'channels', ()) or ()]
    return family, shared_links, routers, edges


def _is_connected(router_ids: list[int], edges: list[tuple[int, int]]) -> bool:
    if not router_ids:
        return False
    adjacency: dict[int, set[int]] = {rid: set() for rid in router_ids}
    for src, dst in edges:
        if src in adjacency and dst in adjacency:
            adjacency[src].add(dst)
            adjacency[dst].add(src)
    seen = {router_ids[0]}
    stack = [router_ids[0]]
    while stack:
        for neighbour in adjacency[stack.pop()]:
            if neighbour not in seen:
                seen.add(neighbour)
                stack.append(neighbour)
    return len(seen) == len(set(router_ids))


def _is_reciprocal(edges: list[tuple[int, int]]) -> bool:
    edge_set = set(edges)
    return all((dst, src) in edge_set for src, dst in edge_set)


def _selected_vc_count(request: CompileRequestV4) -> int:
    """The VC count the catalog measured this request's fabric with.

    ``derive_vc_assignment_v3`` is the same derivation the compiled bundle
    carries (and therefore the same count the backend runs), so the seam can
    name it without compiling again.
    """
    from veritx_dse.model.compile_model import derive_vc_assignment_v3
    return derive_vc_assignment_v3(request).vc_count


def _intent_label(kind: str | None, intent: Any) -> str | None:
    """The selected fabric's intent label, with the GEC mode when it has one."""
    if kind is None:
        return None
    mode = getattr(getattr(intent, 'mode', None), 'value',
                   getattr(intent, 'mode', None))
    return f"{kind}:{mode}" if kind == 'gec' and mode else kind


def rtl_support(request: CompileRequestV4, topology: Any = None,
                vc_assignment: Any = None) -> RtlSupport:
    """Can the product RTL emitter serve this selected fabric?

    ``topology`` is the persisted TopologyView (or the TopologyArtifact) the
    selection compiled to. ``None`` means "not compiled yet" and is reported
    as unsupported rather than assumed servable. The VC-scheme check runs
    first because it is a property of the selected intent, so it can name the
    real mismatch before a compile has ever run.
    """
    intent = getattr(request, 'topology', None)
    kind = getattr(intent, 'kind', None)
    family, shared_links, routers, edges = _topology_facts(topology)
    try:
        vc_count = _selected_vc_count(request)
    except Exception as exc:  # fail closed: an underivable scheme is not servable
        return RtlSupport(
            False, RTL_UNSUPPORTED_VC_DERIVATION,
            f"The selected {family or kind or 'unknown'} fabric's VC scheme "
            f"cannot be derived ({type(exc).__name__}: {exc}); the only "
            f"product RTL emitter implements the certified "
            f"{RTL_EMITTER_VC_COUNT}-VC free/escape scheme, so no matching "
            f"RTL emitter exists (owner stage = {RTL_OWNING_STAGE}).",
            topology_kind=kind, topology_family=family, vc_count=None,
            emitted_vcs=RTL_EMITTER_VC_COUNT, matches_certified_vc_count=False,
            shared_wire_links=shared_links, connected=None, reciprocal=None,
            router_count=len(routers) if topology is not None else None)
    label = family or _intent_label(kind, intent) or 'selected'
    connected = _is_connected(routers, edges) if topology is not None else None
    reciprocal = _is_reciprocal(edges) if topology is not None else None
    common = dict(topology_kind=kind, topology_family=family, vc_count=vc_count,
                  emitted_vcs=RTL_EMITTER_VC_COUNT,
                  matches_certified_vc_count=(vc_count == RTL_EMITTER_VC_COUNT),
                  shared_wire_links=shared_links, connected=connected,
                  reciprocal=reciprocal,
                  router_count=len(routers) if topology is not None else None)
    if vc_assignment is not None:
        try:
            class_vcs = tuple(vc_assignment.traffic_class_to_vcs)
            vc_ids = tuple(vc_assignment.vc_ids)
        except AttributeError:
            class_vcs = ()
            vc_ids = ()
        if class_vcs:
            def _realizable(vcs: tuple) -> bool:
                if tuple(vcs) == vc_ids:
                    return True   # full-set default class: no isolation
                return (len(vcs) == 1 and vcs[0] in (0, 1)
                        and (not vc_ids or vcs[0] in vc_ids))
            bad = [(cls, tuple(vcs)) for cls, vcs in class_vcs
                   if not _realizable(tuple(vcs))]
            if bad:
                return RtlSupport(
                    False, RTL_UNSUPPORTED_VC_SCHEME,
                    f"The selected {label} fabric assigns traffic classes to "
                    f"VC subsets {bad}; the only product RTL emitter implements "
                    f"one free/escape VC scheme, not per-class VC isolation "
                    f"(only a class pinned to exactly one VC in "
                    f"{{0, 1}} — the OrderingFSM class->VC reassignment — or "
                    f"to the full VC set is realizable), so no matching RTL "
                    f"emitter exists (owner stage = {RTL_OWNING_STAGE}).",
                    **common)
    m2_issue = _m2_ordering_issue(request, shared_links)
    if m2_issue:
        return RtlSupport(
            False, RTL_UNSUPPORTED_STAGE1_REALIZATION, m2_issue, **common)
    demands = _stage1_realization_demands(request)
    if demands:
        return RtlSupport(
            False, RTL_UNSUPPORTED_STAGE1_REALIZATION,
            f"The selected {label} fabric declares STAGE 1 intent(s) this "
            f"preview cannot realize: {'; '.join(demands)}. The only "
            f"product RTL emitter is a fixed 2-VC free/escape design; "
            f"no matching RTL emitter exists for these fields (owner "
            f"stage = {RTL_OWNING_STAGE}). Permission windows (M1) ARE "
            f"realized in addr_decode.sv, M2 ordering/VC desires ARE "
            f"realized in ordering_fsm.sv, M3 crossings ARE realized by "
            f"emitted CdcCells, and axi5/chi/tilelink/custom adapters "
            f"(M4) ARE realized by the AdapterFactory shims; none of "
            f"those are refused here.",
            **common)
    if vc_count > RTL_EMITTER_VC_COUNT:
        shared = (f" and {shared_links} shared (multi-drop) wires"
                  if shared_links else "")
        return RtlSupport(
            False, RTL_UNSUPPORTED_VC_SCHEME,
            f"The selected {label} fabric needs {vc_count} VCs{shared}; the "
            f"only product RTL emitter implements the certified "
            f"{RTL_EMITTER_VC_COUNT}-VC free/escape scheme, so no matching "
            f"RTL emitter exists (owner stage = {RTL_OWNING_STAGE}).", **common)
    if topology is None:
        return RtlSupport(
            False, RTL_UNSUPPORTED_TOPOLOGY,
            f"The selected {label} fabric has no compiled topology; the "
            f"product RTL emitter needs a connected, reciprocal, "
            f"point-to-point topology with 2–64 routers (owner stage = "
            f"{RTL_OWNING_STAGE}).", **common)
    if shared_links:
        return RtlSupport(
            False, RTL_UNSUPPORTED_SHARED_WIRE,
            f"The selected {label} fabric has {shared_links} shared "
            f"(multi-drop) wire(s); the only product RTL emitter is a "
            f"point-to-point {RTL_EMITTER_VC_COUNT}-VC free/escape router, so "
            f"no RTL emitter can preserve this fabric (owner stage = "
            f"{RTL_OWNING_STAGE}).", **common)
    if not connected:
        return RtlSupport(
            False, RTL_UNSUPPORTED_TOPOLOGY,
            f"The selected {label} fabric is disconnected; the product RTL "
            f"emitter needs a connected topology so its escape tree spans "
            f"every router (owner stage = {RTL_OWNING_STAGE}).", **common)
    if not reciprocal:
        return RtlSupport(
            False, RTL_UNSUPPORTED_TOPOLOGY,
            f"The selected {label} fabric carries non-reciprocal channels; "
            f"the product RTL emitter needs reciprocal point-to-point links "
            f"(owner stage = {RTL_OWNING_STAGE}).", **common)
    if not 2 <= len(routers) <= 64:
        return RtlSupport(
            False, RTL_UNSUPPORTED_TOPOLOGY,
            f"The selected {label} fabric has {len(routers)} routers; the "
            f"product RTL emitter supports 2–64 contiguously numbered routers "
            f"(owner stage = {RTL_OWNING_STAGE}).", **common)
    return RtlSupport(
        True,
        RTL_SUPPORTED_CERTIFIED if vc_count == RTL_EMITTER_VC_COUNT
        else RTL_SUPPORTED_SINGLE_CLASS,
        None, **common)


def rtl_support_reason(request: CompileRequestV4, topology: Any = None) -> str | None:
    """None inside the certified emitter's slice, else the typed sentence
    naming the family, VC count / shared-wire condition and the missing
    matching emitter."""
    return rtl_support(request, topology).reason


def configuration_of(base: CompileRequestV4) -> dict[str, Any]:
    """The NoC controls every catalog row is measured with.

    ``controls_id`` is the identity envelope of ``noc_controls``, so two rows
    can be compared only when this value matches. It is recorded rather than
    assumed because a future mixed-config catalog must expose the mismatch
    instead of silently ranking unlike measurements.
    """
    controls = base.noc_controls
    return {
        'controls_id': controls.controls_id(),
        'input_buffer_depth_flits_per_vc': controls.input_buffer_depth_flits_per_vc,
        'link_width': controls.link_width,
        'arbitration': controls.arbitration,
    }


def _routing_class(route: Any) -> str | None:
    """The route artifact's class id, for both the v2 and v3 dialects."""
    value = getattr(route, 'routing_class', None)
    if isinstance(value, str):
        return value
    classes = getattr(route, 'routing_classes', None) or ()
    if classes:
        first = classes[0]
        if isinstance(first, dict):
            return first.get('id')
        return getattr(first, 'id', None)
    return None


def compiled_facts(request: CompileRequestV4) -> dict[str, Any]:
    """Compile one catalog candidate and report what selection depends on.

    This is a topology-only compile: no backend runs, no revision is written.
    It answers three pre-selection questions the measured table could not:
    which routing law the row actually used, how the fabric is shaped, and
    whether the one product RTL emitter can serve it. The RTL verdict here is
    ``preview_support``; final simulation-equivalent RTL remains unavailable.
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.views import topology_view
    from veritx_dse.product.rtl_prototypes import prototype_for_family
    compilation = FabricCompiler().compile(request)
    stage1_verdicts = list(getattr(compilation, "stage1_verdicts", ()) or ())
    stage1_findings = list(getattr(compilation, "findings", ()) or ())
    if compilation.status != 'COMPILED' or compilation.bundle is None:
        support = rtl_support(request, None)
        intent = getattr(request, 'topology', None)
        research = prototype_for_family(
            None, kind=getattr(intent, 'kind', None))
        return {'fabric': None, 'rtl_support': support.to_dict(), 'research_rtl': research,
                'stage1_verdicts': stage1_verdicts, 'stage1_findings': stage1_findings}
    bundle = compilation.bundle
    view = topology_view(compilation)
    vc_assignment = getattr(bundle, 'vc_assignment', None)
    support = rtl_support(request, view, vc_assignment)
    intent = getattr(request, 'topology', None)
    research = prototype_for_family(
        view.get('family'), kind=getattr(intent, 'kind', None))
    return {
        'fabric': {
            'router_count': len(view['routers']),
            'shared_wire_links': len(view['shared_links']),
            'routing_class': _routing_class(getattr(bundle, 'router_route', None)),
            'vc_count': getattr(vc_assignment, 'vc_count', None),
        },
        'rtl_support': support.to_dict(),
        'research_rtl': research,
        'stage1_verdicts': stage1_verdicts,
        'stage1_findings': stage1_findings,
    }


def pending_analyses(reason: str | None = None) -> list[dict[str, Any]]:
    return [{'question': q.value, 'backend_id': backend,
             'status': 'UNSUPPORTED' if reason else 'QUEUED', 'reason': reason,
             'normalized_metrics': None}
            for q, backend in zip(QUESTIONS, ('BOOKSIM_STANDALONE', 'ASTRA2_EMBEDDED_BOOKSIM'))]


def run_catalog(request_doc: dict[str, Any], directory: Path, config: dict[str, Any],
                topology_ids: list[str] | None = None) -> dict[str, Any]:
    base = CompileRequestV4.from_dict(request_doc)
    lowered = lower_compile_workload(base)
    graph = lowered.graph
    rows = catalog_for(base)
    if topology_ids is not None:
        unknown = set(topology_ids) - {r['topology_id'] for r in rows}
        if unknown or not topology_ids or len(set(topology_ids)) != len(topology_ids):
            raise ValueError('Select distinct topology identifiers from the catalog.')
        rows = [r for r in rows if r['topology_id'] in topology_ids]
    directory.mkdir(parents=True, exist_ok=True)
    write_json(directory / 'workload.json', graph.to_dict())
    configuration = configuration_of(base)
    document = {
        'schema': 'veritx/catalog-evaluation/1', 'base_design_hash': base.design_hash(),
        'workload_id': graph.workload_id(), 'participant_count': graph.participant_count,
        'operation_count': len(graph.operations), 'compute_stages': len(base.compute.stages) if base.compute else 0,
        'state': 'RUNNING', 'rows': [], 'artifacts': [],
        'configuration': {**configuration, 'workload_id': graph.workload_id()},
        'scope': 'One canonical workload, mapped and lowered independently for each fabric. Network cycles and system cycles are distinct measurements.',
    }
    for index, row in enumerate(rows, 1):
        document['rows'].append({**row, 'attempt': index, 'status': 'QUEUED', 'objective_values': {},
                                 'config': {**configuration, 'matched': True},
                                 'fabric': None, 'rtl_support': None,
                                 'analyses': pending_analyses(row['reason'])})
    path = directory / 'catalog.json'
    write_json(path, document)
    objectives = (Objective('completion_cycles', 'MIN', question=QUESTIONS[0]),
                  Objective('system_makespan_cycles', 'MIN', question=QUESTIONS[1]))
    evaluator = RealCandidateEvaluator(
        binary=config.get('booksim_bin'), astra_binary=config.get('astra_bin'),
        repo_root=Path(config['repo_root']), run_root=directory / 'evidence',
        timeout_s=BACKEND_TIMEOUT_S, questions=QUESTIONS, objectives=objectives,
        network_clock_hz=(int(base.physical.default_clock_freq_mhz * 1_000_000)
                          if base.physical.default_clock_freq_mhz is not None
                          else None),
    )
    for row in document['rows']:
        if row['reason']:
            row['status'] = 'UNSUPPORTED'
            write_json(path, document)
            continue
        candidate = candidate_for(base, row)
        # The scientific workload identity must not drift with topology.
        if lower_compile_workload(candidate.request).graph.workload_id() != document['workload_id']:
            raise ValueError('A candidate changed the pinned workload identity.')
        row.update(candidate_id=candidate.candidate_id, design_hash=candidate.request.design_hash(), status='RUNNING')
        # A topology-only compile makes routing law, fabric shape and RTL
        # feasibility visible BEFORE selection, from the same intent the
        # backends will measure. It runs no simulator and writes no revision.
        try:
            row.update(compiled_facts(candidate.request))
        except (ValueError, TypeError, KeyError, VeritXError) as exc:
            fallback = replace(
                rtl_support(candidate.request, None), supported=False,
                code=RTL_PREDICTION_FAILED,
                reason=f"RTL feasibility could not be predicted for {row['label']} "
                       f"({type(exc).__name__}: {exc}); it is decided at finalization "
                       f"(owner stage = {RTL_OWNING_STAGE}).")
            row.update(fabric=None, rtl_support=fallback.to_dict())
        write_json(path, document)
        try:
            result = evaluate_candidate(candidate, evaluator, proof_path=directory / f"proof-{row['attempt']}.json")
            row.update(result)
            if not row.get('analyses'):
                row['analyses'] = pending_analyses(result.get('reason') or 'Compilation did not reach either backend.')
            row['trace_files'] = []
            evidence_dir = directory / 'evidence' / candidate.candidate_id
            if evidence_dir.is_dir():
                for file in sorted(evidence_dir.rglob('*')):
                    if file.is_file() and (file.name == 'workload.trace' or file.suffix == '.et'):
                        relative = str(file.relative_to(directory))
                        artifact = {'path': relative, 'sha256': sha256(file), 'bytes': file.stat().st_size}
                        document['artifacts'].append(artifact)
                        row['trace_files'].append(relative)
        except (ValueError, VeritXError) as exc:
            row.update(status='FAILED', reason=str(exc), objective_values={}, analyses=pending_analyses(str(exc)))
        write_json(path, document)
    document['artifacts'].append({'path': 'workload.json', 'sha256': sha256(directory / 'workload.json'),
                                  'bytes': (directory / 'workload.json').stat().st_size})
    document['state'] = 'COMPLETED'
    write_json(path, document)
    return {'catalog_sha256': sha256(path), 'workload_id': document['workload_id'], 'candidate_count': len(rows)}
