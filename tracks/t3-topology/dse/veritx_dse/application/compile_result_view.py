"""veritx_dse.application.compile_result_view — Compile Result inspectors.

One projection over a compiled revision, materialized **at certification
time** and frozen with the revision (Gate 5 §97, Gate 8 §50). The
inspectors are never re-derived from the request at view time: a drawn
graph that could drift from the proof it claims to show is worse than no
graph.

Seven groups under one Compile Result (Gate 8 §50) — not one page per
artifact:

    summary · mapping · fabric · routing · resources · address_decode ·
    provenance

Two rules shape what is projected:

* **Expected and observed are never merged** (Gate 8 §58/§59). The
  canonical route is a DERIVED EXPECTED state; runtime observation is a
  separate fact with its own scope. The observation is reported only when
  the certificate actually carries it, using the exact Gate-4 claim
  wording.
* **The certificate is four product claims over ten obligations** (Gate 7
  §9 PF-D9, Gate 8 §62). The verifier issues ten obligations; four of them
  are the named claims the product surfaces. Both are exposed — the four
  as the headline, all ten verbatim — so the projection cannot hide an
  obligation the proof relied on.

Everything here is read-only. No group carries an edit control.
"""
from __future__ import annotations

from typing import Any

CONTRACT_VERSION = 1

#: Shape version of the CERTIFICATE CLAIM rows inside a CompileResultView.
#:
#: WHY THIS EXISTS. The claim row shape changed while CONTRACT_VERSION stayed
#: 1: legacy rows are ``{claim, scope, status, method}`` and current rows add
#: ``certificate_status``, ``established``, ``contributing_obligations``,
#: ``contributing_statuses`` and ``aggregation``. A CompileResultView is
#: FROZEN at certification time and served back verbatim, so a revision
#: persisted before the change hands the frontend a payload its own type
#: says is impossible — ``claim.contributing_obligations.map`` throws and the
#: Compile Result white-screens.
#:
#: The version marker alone is not enough (nothing reads it on a legacy
#: payload), so ``claims_are_current()`` is the enforcement: a frozen payload
#: whose claims are not current is treated as ABSENT and re-derived through
#: the existing hash-checked path, never served stale and never silently
#: redrawn.
CLAIM_SHAPE_VERSION = 2

#: Fields every CURRENT claim row must carry. Presence, not truthiness: a
#: legitimate ``established: false`` must still pass.
REQUIRED_CLAIM_FIELDS = (
    "claim",
    "scope",
    "certificate_status",
    "established",
    "contributing_obligations",
    "contributing_statuses",
    "aggregation",
)


def claims_are_current(claims: Any) -> bool:
    """True when every claim row carries the current claim shape.

    An empty list is CURRENT (a certificate with no claims is a legitimate
    state). A non-list, or any row missing a required field, is NOT — that
    is a legacy or foreign payload and must not be served.
    """
    if not isinstance(claims, list):
        return False
    for row in claims:
        if not isinstance(row, dict):
            return False
        if any(field not in row for field in REQUIRED_CLAIM_FIELDS):
            return False
    return True


def compile_result_is_current(payload: Any) -> bool:
    """True when a FROZEN CompileResultView may be served as-is.

    Guards the certificate claim shape. A payload with no certificate block
    (``available: False``, or a staged stop) is current — there are no
    claims to render. Anything else must prove its claims are current.
    """
    if not isinstance(payload, dict):
        return False
    if payload.get("contract_version") != CONTRACT_VERSION:
        return False
    certificate = payload.get("certificate")
    if certificate is None:
        return True
    if not isinstance(certificate, dict):
        return False
    if certificate.get("claim_shape_version") == CLAIM_SHAPE_VERSION:
        return True
    # Legacy payloads carry no marker; fall back to a structural check so a
    # pre-marker revision is still classified correctly rather than
    # re-derived on every read.
    return claims_are_current(certificate.get("claims", []))

#: Gate 8 §50 — the seven groups, in order.
GROUPS = (
    "summary",
    "mapping",
    "fabric",
    "routing",
    "resources",
    "address_decode",
    "provenance",
)

#: Gate 7 §9 / Gate 8 §62 — the four named certificate claims, in the
#: product's order, with the exact scope sentence the planning corpus uses.
PRODUCT_CLAIMS: tuple[tuple[str, str], ...] = (
    ("ATTACHMENT_COMPLETE", "every declared agent is attached"),
    ("ROUTE_COMPLETE", "every required (class, src, dst) has a route"),
    ("ROUTE_LEGAL", "every route's channel sequence is legal"),
    ("DEADLOCK_FREE", "the channel-VC CDG is acyclic"),
)

#: Gate 8 §57 — semantic zoom thresholds for the fabric inspector. Above
#: MAX_DETAIL_ROUTERS a per-router DOM is not created.
FULL_DETAIL_ROUTERS = 64
MAX_DETAIL_ROUTERS = 256

#: Gate 8 §59 — the exact Gate-4 observation claim.
OBSERVATION_SCOPE = "FIRST_HOP"
OBSERVATION_CLAIM = (
    "runtime routing-function/table first-hop realization is exactly "
    "equivalent to the canonical route over the complete source x "
    "destination domain")
OBSERVATION_LIMIT = (
    "this proves deterministic first-hop routing equivalence, not observed "
    "packet paths")

#: The DEADLOCK_FREE obligation records the route-realization *scheme*
#: (`v2_channel_id`), which is a property of the artifact encoding, not a
#: runtime observation. It must never be presented as one.
_ROUTE_REALIZATION_IS_A_SCHEME = True


def _enum_value(value: Any) -> Any:
    """Enum -> its declared value; anything else passes through.

    The inspectors present canonical values, never Python reprs such as
    ``AllocatorPolicy.ISLIP``.
    """
    return getattr(value, "value", value)


def _h(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.startswith("sha256:") else f"sha256:{text}"


def _obligations(certificate: Any) -> list[dict[str, Any]]:
    if certificate is None:
        return []
    return [o.to_dict() for o in getattr(certificate, "obligations", ())]


def _claim_table(obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The four product claims, derived from the ten obligations.

    Delegates to CertificateProjectionV1: the claims are aggregated by an
    explicit contribution table, never by a same-name lookup, and the
    deadlock claim carries its underlying analysis verdict so a
    NOT-ESTABLISHED certificate state is never rendered as a detected
    deadlock.
    """
    projection = _projection_for_obligations(obligations)
    return projection.get("claims", [])


def _additional_obligations(
        obligations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projection = _projection_for_obligations(obligations)
    return projection.get("technical_only", [])


def _projection_for_obligations(
        obligations: list[dict[str, Any]]) -> dict[str, Any]:
    """Project a bare obligation list through the same authority.

    The Compile Result holds an already-serialized obligation list, so it
    re-wraps it in a minimal certificate-shaped object rather than
    duplicating the projection rules.
    """
    from veritx_dse.application.certificate_projection import (  # noqa: PLC0415
        project_certificate,
    )

    class _Row:
        def __init__(self, row: dict[str, Any]) -> None:
            self._row = row

        def to_dict(self) -> dict[str, Any]:
            return self._row

    class _Certificate:
        overall = None
        certificate_id = staticmethod(lambda: None)

        def __init__(self, rows: tuple) -> None:
            self.obligations = rows

    projection = project_certificate(
        _Certificate(tuple(_Row(o) for o in obligations)))
    projection["overall"] = next(
        (o.get("status") for o in obligations), None)
    return projection


# ── groups ─────────────────────────────────────────────────────────────

def _summary(request: Any, bundle: Any, certificate: Any,
             compilation: Any) -> dict[str, Any]:
    """Gate 8 §52 — declared / derived / verified. Not a Design Review."""
    noc = getattr(request, "noc_config", None)
    workload = getattr(request, "workload", None)
    topology = getattr(bundle, "topology", None)
    attachment = getattr(bundle, "attachment", None)
    vc = getattr(bundle, "vc_assignment", None)
    declared: dict[str, Any] = {}
    if noc is not None:
        family = getattr(noc, "topology_family", None)
        declared["topology_family"] = getattr(family, "value", family)
        # §16: the product name for the implementation field `radix`.
        declared["side_length"] = getattr(noc, "radix", None)
        declared["concentration"] = getattr(noc, "concentration", None)
        declared["link_width"] = getattr(noc, "link_width", None)
        declared["arbitration"] = getattr(noc, "arbitration", None)
    if workload is not None:
        declared["parallelism"] = {
            "tp": getattr(workload, "tp", None),
            "pp": getattr(workload, "pp", None),
            "ep": getattr(workload, "ep", None),
            "dp": getattr(workload, "dp", None),
        }
    declared["agents"] = [
        {"kind": getattr(getattr(a, "kind", None), "value",
                         getattr(a, "kind", None)),
         "count": getattr(a, "count", None)}
        for a in (getattr(request, "agents", ()) or ())]
    declared["requirements"] = len(getattr(request, "requirements", ()) or ())

    derived: dict[str, Any] = {}
    if topology is not None:
        derived["routers"] = len(getattr(topology, "routers", ()))
        derived["channels"] = len(getattr(topology, "channels", ()))
        derived["seats"] = sum(
            getattr(r, "seat_capacity", 0) or 0
            for r in getattr(topology, "routers", ()))
    if attachment is not None:
        derived["endpoints"] = len(getattr(attachment, "endpoints", ()))
    if vc is not None:
        derived["vc_count"] = getattr(vc, "vc_count", None)
    route = getattr(bundle, "router_route", None)
    if route is not None:
        derived["routing_classes"] = [
            c.id for c in getattr(route, "routing_classes", ())]

    return {
        "declared": declared,
        "derived": derived,
        "verified": _claim_table(_obligations(certificate)),
        "certificate_overall": getattr(certificate, "overall", None),
        "compilation_status": getattr(compilation, "status", None),
    }


def _mapping(bundle: Any, request: Any = None) -> dict[str, Any]:
    """Gate 8 §53/§54 — participant -> compute agent, table-first.

    Parallel coordinates come from the sealed Wave-B rank algebra
    (``model.placement.coords_of``), never from a frontend convention: a
    second copy of the rank law is a second answer to "which rank is
    (tp=1,dp=0)".
    """
    mapping = getattr(bundle, "mapping", None)
    attachment = getattr(bundle, "attachment", None)
    if mapping is None:
        return {"available": False, "rows": []}

    workload = getattr(request, "workload", None)
    dims = None
    if workload is not None:
        try:
            dims = {
                "tp": int(getattr(workload, "tp") or 1),
                "pp": int(getattr(workload, "pp") or 1),
                "ep": int(getattr(workload, "ep") or 1),
                "dp": int(getattr(workload, "dp") or 1),
            }
        except (TypeError, ValueError):
            dims = None
    coords_of = None
    if dims is not None:
        from veritx_dse.model.placement import (  # noqa: PLC0415
            coords_of as _coords_of,
        )
        coords_of = _coords_of
    endpoints_by_agent: dict[tuple[int, int], int] = {}
    if attachment is not None:
        for endpoint in getattr(attachment, "endpoints", ()):
            agent = getattr(endpoint, "agent", None)
            if agent is None:
                continue
            endpoints_by_agent[
                (getattr(agent, "group_index", -1),
                 getattr(agent, "instance_index", -1))
            ] = getattr(endpoint, "endpoint_id", None)
    rows: list[dict[str, Any]] = []
    for placement in getattr(mapping, "placements", ()):
        agent = getattr(placement, "agent", None)
        group_index = getattr(agent, "group_index", None)
        instance_index = getattr(agent, "instance_index", None)
        kind = getattr(agent, "kind", None)
        rank = getattr(placement, "rank", None)
        coordinates = None
        if coords_of is not None and rank is not None:
            try:
                coordinates = coords_of(rank, **dims)
            except (TypeError, ValueError):
                coordinates = None
        rows.append({
            "rank": rank,
            "agent_kind": getattr(kind, "value", kind),
            "group_index": group_index,
            "instance_index": instance_index,
            "endpoint_id": endpoints_by_agent.get(
                (group_index, instance_index)),
            "coordinates": coordinates,
        })
    return {
        "available": True,
        "rows": rows,
        "rank_count": getattr(mapping, "rank_count", len(rows)),
        "parallelism": dims,
        "idle_agents": _idle_agents(bundle, rows),
    }


def _idle_agents(bundle: Any, rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Attached compute agents no rank maps to.

    Gate 8 §53 requires idle compute to be visible: a 64-tile fabric
    serving 8 ranks has 56 idle tiles, and that is a design fact.
    """
    attachment = getattr(bundle, "attachment", None)
    if attachment is None:
        return {"count": 0, "by_kind": {}, "mapped": 0, "attached": 0}
    mapped = {(r["group_index"], r["instance_index"]) for r in rows}
    by_kind: dict[str, int] = {}
    attached = 0
    idle = 0
    for endpoint in getattr(attachment, "endpoints", ()):
        agent = getattr(endpoint, "agent", None)
        if agent is None:
            continue
        attached += 1
        kind = getattr(getattr(agent, "kind", None), "value",
                       getattr(agent, "kind", None))
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if (getattr(agent, "group_index", None),
                getattr(agent, "instance_index", None)) not in mapped:
            idle += 1
    return {"count": idle, "by_kind": by_kind, "mapped": len(rows),
            "attached": attached}


def _fabric(bundle: Any, topology_view: dict[str, Any] | None) -> dict[str, Any]:
    """Gate 8 §55/§57 — the compiled topology plus its zoom strategy."""
    topology = getattr(bundle, "topology", None)
    attachment = getattr(bundle, "attachment", None)
    if topology is None:
        return {"available": False, "rows": []}
    routers = list(getattr(topology, "routers", ()))
    endpoints = list(getattr(attachment, "endpoints", ())) \
        if attachment is not None else []
    # OCCUPANCY IS ENDPOINT COUNT, NOT DISTINCT-ROUTER COUNT. A router with
    # four seats hosting four agents occupies four seats; counting the
    # router once would under-report occupancy by a factor of the
    # concentration (dense-4b-32tiles-conc4 has 36 seats and 36 agents, so
    # zero unused — not 27).
    attached_count = len(endpoints)
    occupied_routers = {getattr(e, "router_id", None) for e in endpoints}
    seats = sum(getattr(r, "seat_capacity", 0) or 0 for r in routers)
    count = len(routers)
    if count <= FULL_DETAIL_ROUTERS:
        detail = "FULL"
    elif count <= MAX_DETAIL_ROUTERS:
        detail = "ROUTERS_AND_LINKS"
    else:
        detail = "AGGREGATE"
    return {
        "available": True,
        "counts": {
            "routers": count,
            "channels": len(getattr(topology, "channels", ())),
            "seats": seats,
            # occupied seats = attached endpoints
            "attached": attached_count,
            "unused_seats": max(0, seats - attached_count),
            # routers with at least one attached agent (distinct from seats)
            "occupied_routers": len([r for r in occupied_routers
                                     if r is not None]),
        },
        # Gate 8 §57: above MAX_DETAIL_ROUTERS no per-router DOM is created.
        "detail_level": detail,
        "detail_thresholds": {
            "full_detail_max": FULL_DETAIL_ROUTERS,
            "router_detail_max": MAX_DETAIL_ROUTERS,
        },
        "topology": topology_view,
    }


def _routing(bundle: Any, certificate: Any) -> dict[str, Any]:
    """Gate 8 §58/§59 — expected and observed, never merged."""
    route = getattr(bundle, "router_route", None)
    if route is None:
        return {"available": False}
    entries = dict(getattr(route, "entries", {}) or {})
    topology = getattr(bundle, "topology", None)
    classes = [c.id for c in getattr(route, "routing_classes", ())]

    # The route table and the channel table are stored as pure data: the
    # revision is persisted as JSON, so the payload can hold no callable.
    # `canonical_route(payload, ...)` walks them on request.
    route_entries = [
        {"routing_class": cls, "src": src, "dst": dst, "channel_id": channel}
        for (cls, src, dst), channel in sorted(
            entries.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2]))
    ]
    channel_hops = [
        {"channel_id": getattr(c, "channel_id", None),
         "src_router": getattr(c, "src_router", None),
         "src_port": getattr(c, "src_port", None),
         "dst_router": getattr(c, "dst_router", None),
         "dst_port": getattr(c, "dst_port", None)}
        for c in (getattr(topology, "channels", ()) or ())
    ]

    # Gate 8 §59: the observation is a separate fact with its own scope.
    #
    # A compiled revision has NO runtime execution, so there is no
    # observation to report. The DEADLOCK_FREE evidence carries
    # `route_realization: "v2_channel_id"`, which is the artifact's encoding
    # scheme — presenting it as an observation would claim a runtime fact
    # that does not exist. The observation belongs to an evaluation run,
    # where RunIntegrityView.route_realization reports
    # OBSERVED | NOT_OBSERVED with its own scope.
    observation: dict[str, Any] = {
        "available": False,
        "scope": OBSERVATION_SCOPE,
        "claim": OBSERVATION_CLAIM,
        "limit": OBSERVATION_LIMIT,
        "realized_digest": None,
        "reason": ("no runtime execution exists for a compiled revision; a "
                   "route observation is produced by an evaluation run"),
        "source": "evaluation run (RunIntegrityView.route_realization)",
    }

    return {
        "available": True,
        "routing_classes": classes,
        "default_class": classes[0] if classes else None,
        "entry_count": len(route_entries),
        "entries": route_entries,
        "channel_hops": channel_hops,
        "observation": observation,
        "observation_note": (
            "expected and observed are separate facts: the canonical route "
            "is DERIVED EXPECTED, the observation is a runtime realization "
            f"at scope {OBSERVATION_SCOPE}"),
    }


def _resources(bundle: Any, certificate: Any) -> dict[str, Any]:
    """Gate 8 §60/§61 — VC assignment, CDG, arbitration."""
    vc = getattr(bundle, "vc_assignment", None)
    behavior = getattr(bundle, "router_behavior", None)
    if vc is None:
        return {"available": False}
    transitions = list(getattr(vc, "allowed_transitions", ()) or ())
    pairs = [list(pair) for pair in transitions
             if isinstance(pair, (tuple, list)) and len(pair) == 2]
    identity = bool(pairs) and all(a == b for a, b in pairs)
    class_map = [list(pair) for pair in
                 (getattr(vc, "traffic_class_to_vcs", ()) or ())]
    vc_to_class = [list(pair) for pair in
                   (getattr(vc, "vc_to_routing_class", ()) or ())]

    deadlock: dict[str, Any] = {"status": "UNSUPPORTED", "evidence": {}}
    for obligation in _obligations(certificate):
        if obligation.get("obligation") == "DEADLOCK_FREE":
            evidence = obligation.get("evidence") or {}
            # Gate 8 §61: the channel dependency graph is the witness. When
            # the verdict is FAIL the cycle is named; when PASS the graph
            # properties are the proof. Both are the same fields.
            deadlock = {
                "status": obligation.get("status", "UNSUPPORTED"),
                "method": obligation.get("method"),
                "witness": {
                    "acyclic": evidence.get("acyclic"),
                    "sccs_gt_1": evidence.get("sccs_gt_1"),
                    "node_count": evidence.get("node_count"),
                    "edge_count": evidence.get("edge_count"),
                    "cdg_route_classes": evidence.get("cdg_route_classes"),
                    "escape_vcs": evidence.get("escape_vcs"),
                    "vc_count": evidence.get("vc_count"),
                    "route_realization_scheme": evidence.get(
                        "route_realization"),
                },
                "evidence": evidence,
            }
            break

    return {
        "available": True,
        "vc_count": getattr(vc, "vc_count", None),
        "vc_ids": list(getattr(vc, "vc_ids", ()) or ()),
        "traffic_class_to_vcs": class_map,
        "vc_to_routing_class": vc_to_class,
        "allowed_transitions": pairs,
        "transitions_are_identity": identity,
        "escape_vcs": list(getattr(vc, "escape_vcs", ()) or ()),
        "derivation": getattr(vc, "derivation", None),
        "arbitration": {
            "vc_allocator": _enum_value(
                getattr(behavior, "vc_allocator", None)),
            "switch_allocator": _enum_value(
                getattr(behavior, "switch_allocator", None)),
            "input_vc_packet_policy": _enum_value(
                getattr(behavior, "input_vc_packet_policy", None)),
            "flow_control": _enum_value(
                getattr(behavior, "flow_control", None)),
            "allocator_iterations": getattr(
                behavior, "allocator_iterations", None),
            "input_buffer_depth_flits_per_vc": getattr(
                behavior, "input_buffer_depth_flits_per_vc", None),
            "output_stage_depth_flits_per_vc": getattr(
                behavior, "output_stage_depth_flits_per_vc", None),
        },
        "deadlock": deadlock,
        "editable": False,
    }


def _address_decode(bundle: Any) -> dict[str, Any]:
    """Gate 8 §50 — ranges -> memory agent -> endpoint.

    Gate 7 §23: the resolved stable identity is presented; the legacy
    positional `target_agent_group` is carried as technical detail, never
    as the primary label.
    """
    decode = getattr(bundle, "address_decode", None)
    attachment = getattr(bundle, "attachment", None)
    if decode is None:
        return {"available": False, "rows": []}
    endpoints_by_id = {getattr(e, "endpoint_id", None): e
                       for e in getattr(attachment, "endpoints", ()) or ()}
    rows: list[dict[str, Any]] = []
    for entry in getattr(decode, "entries", ()):
        endpoint_id = getattr(entry, "target_endpoint_id", None)
        endpoint = endpoints_by_id.get(endpoint_id)
        agent = getattr(endpoint, "agent", None) if endpoint else None
        kind = getattr(agent, "kind", None) if agent else None
        rows.append({
            "name": getattr(entry, "name", None),
            "base": getattr(entry, "base", None),
            "size": getattr(entry, "size", None),
            # The stable semantic target, then the positional legacy index.
            "target_agent_kind": getattr(kind, "value", kind),
            "target_agent_instance": (
                getattr(agent, "instance_index", None) if agent else None),
            "target_endpoint_id": endpoint_id,
            "legacy_target_agent_group": getattr(
                entry, "target_agent_group", None),
        })
    transform = getattr(decode, "address_transform", None)
    policy = getattr(decode, "unmatched_address_policy", None)
    return {
        "available": True,
        "rows": rows,
        "address_transform": getattr(transform, "value", transform),
        "unmatched_address_policy": getattr(policy, "value", policy),
    }


def _provenance(revision: dict[str, Any], bundle: Any,
                chain_view: dict[str, Any] | None) -> dict[str, Any]:
    """Gate 8 §115/§116 — compiler semantics, artifact hashes, pins."""
    hashes: dict[str, Any] = {}
    if bundle is not None:
        try:
            hashes = {str(k): _h(v) for k, v in bundle.root_hashes().items()}
        except Exception:  # noqa: BLE001
            hashes = {}
    compilation = revision.get("compilation") or {}
    return {
        "revision_id": revision.get("revision_id"),
        "design_hash": _h(revision.get("design_hash")),
        "compiler_semantics_version": compilation.get(
            "compiler_semantics_version"),
        "resolved_fabric_hash": _h(compilation.get("resolved_fabric_hash")),
        "certificate_id": _h((revision.get("certificate") or {})
                             .get("certificate_id")),
        "artifact_hashes": hashes,
        "artifact_chain": chain_view,
    }


def canonical_route(routing_group: dict[str, Any], routing_class: str,
                    src: int, dst: int,
                    limit: int = 512) -> dict[str, Any]:
    """Walk the frozen route table — the DERIVED EXPECTED route (Gate 8 §58).

    ``entries[(class, src, dst)]`` is a **channel id**; the next router is
    that channel's destination. The walk terminates in ``LOCAL_EJECTION``.

    This is a query over the frozen payload, never a re-derivation: the
    table it walks is the one captured at certification time.
    """
    table = {(row["routing_class"], row["src"], row["dst"]):
             row["channel_id"] for row in routing_group.get("entries", ())}
    channels = {row["channel_id"]: row
                for row in routing_group.get("channel_hops", ())}
    if src == dst:
        return {"routing_class": routing_class, "src": src, "dst": dst,
                "routers": [src], "hops": [], "terminates": True,
                "terminal": "LOCAL_EJECTION", "reason": None}
    path = [src]
    hops: list[dict[str, Any]] = []
    current = src
    while current != dst and len(path) < limit:
        channel_id = table.get((routing_class, current, dst))
        if channel_id is None:
            return {"routing_class": routing_class, "src": src, "dst": dst,
                    "routers": path, "hops": hops, "terminates": False,
                    "terminal": None,
                    "reason": f"no entry ({routing_class},{current},{dst})"}
        channel = channels.get(channel_id)
        if channel is None:
            return {"routing_class": routing_class, "src": src, "dst": dst,
                    "routers": path, "hops": hops, "terminates": False,
                    "terminal": None,
                    "reason": f"channel {channel_id} is not in the topology"}
        hops.append(channel)
        nxt = channel.get("dst_router")
        if nxt is None or nxt == current:
            return {"routing_class": routing_class, "src": src, "dst": dst,
                    "routers": path, "hops": hops, "terminates": False,
                    "terminal": None, "reason": "route does not advance"}
        path.append(nxt)
        current = nxt
    terminates = current == dst
    return {"routing_class": routing_class, "src": src, "dst": dst,
            "routers": path, "hops": hops, "terminates": terminates,
            "terminal": "LOCAL_EJECTION" if terminates else None,
            "reason": None}


def _capability_consequences(request: Any,
                             compilation: Any = None) -> list[dict[str, Any]]:
    """Downstream capability state for the compiled design.

    Delegates to the DesignViewV2 consequence builder so the Compile Result
    and the Design surface can never disagree about what a choice costs.
    """
    from veritx_dse.application.design_view_v2 import (  # noqa: PLC0415
        _capability_consequences as build_consequences,
    )
    from veritx_dse.application.views import (  # noqa: PLC0415
        design_view,
    )

    if request is None:
        return []
    try:
        doc = design_view(request).get("__source_doc__")
    except Exception:  # noqa: BLE001
        doc = None
    if doc is None:
        # design_view projects rather than exposing the request doc, so
        # rebuild the minimal document the consequence builder reads.
        doc = {
            "workload": {
                "model_family": getattr(
                    getattr(request, "workload", None), "model_family", None),
                "ep": getattr(getattr(request, "workload", None), "ep", None),
                "collectives": [
                    {"kind": getattr(c, "kind", None),
                     "dimension": getattr(
                         getattr(c, "dimension", None), "value",
                         getattr(c, "dimension", None)),
                     "traffic_class": getattr(c, "traffic_class", None)}
                    for c in (getattr(
                        getattr(request, "workload", None),
                        "collectives", ()) or ())],
            },
            "noc_config": {
                "topology_family": getattr(
                    getattr(getattr(request, "noc_config", None),
                            "topology_family", None), "value",
                    getattr(getattr(request, "noc_config", None),
                            "topology_family", None)),
                "concentration": getattr(
                    getattr(request, "noc_config", None), "concentration", None),
            },
            "agents": [
                {"clock_domain": getattr(a, "clock_domain", None)}
                for a in (getattr(request, "agents", ()) or ())],
        }
    # The compilation is required to see the LOWERED traffic classes: a
    # fabric can be multi-class through its dependency graph without
    # declaring a single collective (the mesh4 family is exactly that).
    return build_consequences(doc, compilation)


# ── the projection ─────────────────────────────────────────────────────

def build_compile_result(revision: dict[str, Any],
                         compilation: Any,
                         topology_view: dict[str, Any] | None,
                         chain_view: dict[str, Any] | None) -> dict[str, Any]:
    """Materialize the seven inspector groups for one compiled revision.

    Called at compile time and frozen with the revision, so the inspectors
    can never drift from the proof they describe.
    """
    bundle = getattr(compilation, "bundle", None)
    certificate = getattr(compilation, "certificate", None)
    request = getattr(compilation, "request", None)
    obligations = _obligations(certificate)

    if bundle is None:
        return {
            "contract_version": CONTRACT_VERSION,
            "available": False,
            "reason": getattr(compilation, "error", None)
            or "no bundle exists for this revision",
            "groups": {name: {"available": False} for name in GROUPS},
            "certificate": None,
        }

    result = {
        "contract_version": CONTRACT_VERSION,
        "available": True,
        "revision_id": revision.get("revision_id"),
        "display_name": revision.get("display_name"),
        "compiled_at": revision.get("created_at"),
        "design_hash": _h(revision.get("design_hash")),
        "certificate": {
            **_projection_for_obligations(obligations),
            "claim_shape_version": CLAIM_SHAPE_VERSION,
            "overall": getattr(certificate, "overall", None),
            "certificate_id": _h(getattr(certificate, "certificate_id",
                                         lambda: None)()),
            "obligations": obligations,
            "additional_obligations": _additional_obligations(obligations),
            "claim_count": len(PRODUCT_CLAIMS),
            "obligation_count": len(obligations),
        },
        "groups": {
            "summary": _summary(request, bundle, certificate, compilation),
            "mapping": _mapping(bundle, request),
            "fabric": _fabric(bundle, topology_view),
            "routing": _routing(bundle, certificate),
            "resources": _resources(bundle, certificate),
            "address_decode": _address_decode(bundle),
            "provenance": _provenance(revision, bundle, chain_view),
        },
        "group_order": list(GROUPS),
        # Gate 8 §43/§46: downstream capability state, from the SAME
        # registry authority DesignViewV2 uses. One capability authority.
        "capability_consequences": _capability_consequences(
            request, compilation),
        "topology_hash": (topology_view or {}).get("topology_hash"),
    }
    return result


__all__ = [
    "CLAIM_SHAPE_VERSION",
    "REQUIRED_CLAIM_FIELDS",
    "CONTRACT_VERSION",
    "claims_are_current",
    "compile_result_is_current",
    "FULL_DETAIL_ROUTERS",
    "GROUPS",
    "MAX_DETAIL_ROUTERS",
    "OBSERVATION_CLAIM",
    "OBSERVATION_LIMIT",
    "OBSERVATION_SCOPE",
    "PRODUCT_CLAIMS",
    "build_compile_result",
    "canonical_route",
]
