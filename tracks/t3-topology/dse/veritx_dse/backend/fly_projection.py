"""Native k-ary n-fly projection: stage law, ingress/egress split, dest-tag.

The fly executes the fork's ``fly`` network with ``dest_tag_fly``: three
stages of 16 routers, terminals injecting at stage 0 and ejecting at stage 2,
and a destination-digit port rule with NO adaptive choice. Three facts are
therefore checked here and nowhere else:

* the STATIC first-hop table is the literal output of ``dest_tag_fly`` for
  every (router, destination node) pair -- including the pairs no real flow
  can occupy, because the function answers them too and the producer dumps
  them;
* the EXECUTED route-compute stream only ever advances one stage per hop,
  starts at the flow's own injection router and ejects exactly at the
  flow's own stage-2 router, so a static table cannot be mistaken for a
  reachable path;
* the attachment is ASYMMETRIC: a terminal's ingress and egress locations
  are different routers. A symmetric attachment would let the renderer
  accept a fabric whose ejection points were never proven.
"""
from veritx_dse.core.route_artifact import FLY_DEST_TAG
from veritx_dse.model.fly_net import (
    EGRESS_ROUTERS, K, LEVELS, ROUTER_COUNT, TERMINALS, egress_port,
    materialize_fly, next_router, router_stage, terminal_egress_location,
    terminal_ingress_location,
)
from veritx_dse.model.topology_artifact import MaterializedFamily
from .booksim_projection import (
    BookSimProfile, ConfigRead, ParameterOwner as Owner, SemanticLoss,
    _AUDIT, _multi_class_audit, _qualify_point_to_point,
)

PROFILE_ID = "CERTIFIED_BOOKSIM_FLY_DEST_TAG_V1"
SEMANTICS_VERSION = (
    "booksim2-fork+fly-dest-tag+ingress0-egress2/v1+multi-class/v1")
LOWERER_VERSION = "FLYDESTTAG/1"
OBSERVATION_FILE = "native_route_observations.txt"
#: (routers, terminals) the executed first-hop obligations must cover.
QUALIFIED_HOP_OBLIGATIONS = (ROUTER_COUNT, TERMINALS)


def _fly_audit() -> tuple[ConfigRead, ...]:
    """The shared audit re-pathed for the native fly.

    `fly` is its own BookSim network (three stages of k^(n-1) routers with the
    terminal side wired to stage 0 and stage n-1), so the routed knobs come
    from that source rather than from the anynet replica, and the executed
    route-compute evidence is declared because a static table cannot show the
    stage a flow actually reached.
    """
    rows: list[ConfigRead] = []
    for row in _AUDIT:
        if row.name == "network_file":
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", Owner.CANONICAL, "networks/network.cpp", "fly",
                note="native k-ary n-fly render: the multi-stage butterfly, "
                     "not an AnyNet description of one"))
            continue
        if row.name == "routing_function":
            rows.append(ConfigRead(
                "routing_function", Owner.CANONICAL, "routers/iq_router.cpp",
                "dest_tag",
                note="dest_tag_fly: one port per (router, destination), so "
                     "this fabric needs no legal-choice union"))
            continue
        rows.append(row)
    rows.append(ConfigRead(
        "k", Owner.DERIVED, "networks/fly.cpp", 4,
        note="PINNED by the native construction: radix 4 fixes the routers "
             "per stage (k^(n-1) = 16) and the destination-digit port rule"))
    rows.append(ConfigRead(
        "n", Owner.DERIVED, "networks/fly.cpp", 3,
        note="PINNED by the native construction: three stages, which IS the "
             "terminal injection/ejection split"))
    rows.append(ConfigRead(
        "use_noc_latency", Owner.DERIVED, "networks/fly.cpp", 0,
        note="inter-stage channels carry the 1-cycle latency the builder "
             "pins (SetLatency(1)); no per-hop latency file is read"))
    rows.append(ConfigRead(
        "native_route_observation_file", Owner.DERIVED, "routefunc.cpp",
        note="mandatory executed route-compute evidence: the static table "
             "cannot show one-stage-per-hop advance or which stage-2 router "
             "a flow ejected at"))
    return tuple(rows)


PROFILE = BookSimProfile(
    profile_id=PROFILE_ID,
    semantics_version=SEMANTICS_VERSION,
    audit=_multi_class_audit(_fly_audit()))


def qualify(parents, *, multi_class=False) -> int:
    """Prove every prerequisite of the fly envelope, or refuse. Returns k^n."""
    topology = parents.topology
    if topology.family is not MaterializedFamily.FLY_NATIVE:
        raise SemanticLoss(
            "the destination-tag envelope is certified for fly_native only, "
            f"got {topology.family.value}")
    controls = {channel.width_bits for channel in topology.channels}
    if len(controls) != 1:
        raise SemanticLoss("native fly requires uniform channel widths")
    expected = materialize_fly(width_bits=next(iter(controls)))
    if topology.canonical_dict() != expected.canonical_dict():
        raise SemanticLoss(
            "native fly geometry/ports/slots differ from its construction "
            "(3 stages of 16 routers, 128 inter-stage channels, terminals "
            "injecting at stage 0 and ejecting at stage 2)")
    endpoints = parents.attachment.endpoints
    if len(endpoints) != TERMINALS:
        raise SemanticLoss(
            f"native fly requires the complete {TERMINALS}-terminal "
            f"attachment, got {len(endpoints)}")
    for endpoint in endpoints:
        terminal = endpoint.endpoint_id
        if not 0 <= terminal < TERMINALS:
            raise SemanticLoss(
                f"endpoint {terminal} is outside the {TERMINALS}-terminal "
                "fly fabric")
        if (endpoint.router_id, endpoint.port_id) != \
                terminal_ingress_location(terminal):
            raise SemanticLoss(
                f"native fly endpoint {terminal} does not inject at its "
                "stage-0 router/port")
        if endpoint.symmetric:
            raise SemanticLoss(
                f"native fly endpoint {terminal} declares no egress "
                "location; its ejection router is a different stage, so a "
                "symmetric seat would claim an ejection point never proven")
        if endpoint.egress_location() != terminal_egress_location(terminal):
            raise SemanticLoss(
                f"native fly endpoint {terminal} does not eject at its "
                "stage-2 router/port")
    if parents.route.routing_classes != (
            parents.route.routing_classes[0],) \
            or parents.route.routing_classes[0].id != FLY_DEST_TAG:
        raise SemanticLoss(
            "fly requires the sealed FLY_DEST_TAG algorithm alone")
    _qualify_point_to_point(
        parents, routing_class=FLY_DEST_TAG, multi_class=multi_class)
    channels = {channel.channel_id: channel for channel in topology.channels}
    for (cls, src, dest), channel_id in parents.route.entries.items():
        if dest not in EGRESS_ROUTERS:
            raise SemanticLoss(
                f"FLY_DEST_TAG entry ({src},{dest}) names a router that is "
                "not a stage-2 ejection point")
        port = egress_port(src, dest)
        if port is None:
            raise SemanticLoss(
                f"FLY_DEST_TAG entry ({src},{dest}) has no legal hop")
        following = next_router(src, port)
        channel = channels[channel_id]
        if channel.src_router != src or channel.dst_router != following:
            raise SemanticLoss(
                f"canonical fly route ({src},{dest}) is not the destination-"
                "tag hop")
    return TERMINALS


def static_port(router: int, terminal: int) -> int:
    """The literal output of ``dest_tag_fly`` at ``router`` for ``terminal``.

    Transcribed, not idealized: the function divides the destination by k
    until the flit is one stage from the end and takes ``dest % k``, so it
    answers EVERY (router, destination) pair -- including pairs no real flow
    can occupy (a stage-2 router answering for a terminal that ejects
    elsewhere). The static dump records that answer for every pair, so the
    comparison is exact rather than "reachable rows only".
    """
    stage = router_stage(router)
    dest = terminal
    for _ in range(LEVELS - 1 - stage):
        dest //= K
    return dest % K


def expected_rows(topology) -> tuple[tuple, tuple]:
    """(hop rows, port rows) for the deterministic static differential.

    Row shape matches the producer's dump ABI: (router, destination node,
    next router), where a port that leaves the fabric through an ejection
    channel names the router itself -- exactly what
    ``Network::DumpRoutingRealization`` writes when the sink is not a router.
    """
    hops, ports = [], []
    for router in range(len(topology.routers)):
        for terminal in range(TERMINALS):
            port = static_port(router, terminal)
            following = next_router(router, port)
            hops.append((router, terminal,
                         router if following is None else following))
            ports.append((router, terminal, port))
    return tuple(hops), tuple(ports)


def legal_hops(router: int, terminal: int) -> tuple[tuple[int, int], ...]:
    """The hop the executed flow may take at ``router``, or a refusal.

    Unlike the static law this is flow-aware: a flit can only be at a router
    its own path reaches, so a middle-stage router on the wrong digit class
    and a stage-2 router that is not the flow's ejection point are refused
    rather than answered.
    """
    stage = router_stage(router)
    egress_router, egress_port_ = terminal_egress_location(terminal)
    if stage == LEVELS - 1:
        if router != egress_router:
            raise SemanticLoss(
                f"a flit destined for terminal {terminal} cannot be at "
                f"stage-2 router {router}; it ejects at {egress_router}")
        return ((router, egress_port_),)
    port = egress_port(router, egress_router)
    if port is None:
        raise SemanticLoss(
            f"a flit at stage-1 router {router} cannot reach terminal "
            f"{terminal}; dest_tag_fly only forwards a flow whose "
            "destination digit matches")
    following = next_router(router, port)
    return ((following, port),)


def verify_runtime(text: str, *, num_vcs: int) -> dict:
    """Prove the executed stage advance, first hop and ejection point.

    Every observed row must be the destination-tag port, run in the full VC
    range (``dest_tag_fly`` sets ``0..gNumVCs-1`` and nothing narrower), and
    follow the previous hop of the SAME flit by exactly one stage. The first
    row of a flit must be its own injection router, and the last must eject
    it at its own stage-2 router: a flit that appears at a middle stage it
    could not have been reached through, or that ejects anywhere but its
    destination's ejection router, is not a fly traversal.
    """
    from .booksim_execution import BookSimExecutionError
    rows = 0
    last_router: dict[int, int] = {}
    flow: dict[int, tuple[int, int]] = {}
    stages = [0] * LEVELS
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 10:
            raise BookSimExecutionError(
                f"native route observation row {line_no} is not the 10-field "
                f"ABI: {line!r}")
        try:
            flit, src, dest, router, inp, _invc, out, vc_begin, vc_end, _ph = (
                int(value) for value in fields)
        except ValueError:
            raise BookSimExecutionError(
                f"native route observation row {line_no} is not integral: "
                f"{line!r}") from None
        if not (0 <= src < TERMINALS and 0 <= dest < TERMINALS):
            raise BookSimExecutionError(
                f"native route observation names terminal {src}->{dest} "
                f"outside the attached {TERMINALS}")
        if not 0 <= router < ROUTER_COUNT:
            raise BookSimExecutionError(
                f"native route observation names router {router}, which is "
                "outside the 3-stage fabric")
        seen_flow = flow.setdefault(flit, (src, dest))
        if seen_flow != (src, dest):
            raise BookSimExecutionError(
                f"flit {flit} is observed toward two flows {seen_flow} and "
                f"{(src, dest)}")
        if out != static_port(router, dest):
            raise BookSimExecutionError(
                f"executed fly hop at router {router} toward terminal {dest} "
                f"used port {out}, but dest_tag_fly computes "
                f"{static_port(router, dest)}")
        if (vc_begin, vc_end) != (0, num_vcs - 1):
            raise BookSimExecutionError(
                f"executed fly hop at router {router} ran in VC range "
                f"{vc_begin}..{vc_end}, but dest_tag_fly allocates the whole "
                f"range 0..{num_vcs - 1}")
        try:
            legal_hops(router, dest)   # refuses a hop no flow can take
        except SemanticLoss as exc:
            raise BookSimExecutionError(
                f"executed fly hop at router {router} toward terminal {dest} "
                f"is not a flow the fabric can carry: {exc}") from None
        stage = router_stage(router)
        previous = last_router.get(flit)
        if previous is None:
            ingress, _ = terminal_ingress_location(src)
            if router != ingress:
                raise BookSimExecutionError(
                    f"flit {flit} was first observed at router {router}, but "
                    f"terminal {src} injects at stage-0 router {ingress}")
            if stage != 0:
                raise BookSimExecutionError(
                    f"flit {flit} was first observed at stage {stage}, not "
                    "at its injection stage")
        else:
            expected_next, _ = legal_hops(previous, dest)[0]
            if router != expected_next:
                raise BookSimExecutionError(
                    f"flit {flit} was observed at router {router} after "
                    f"router {previous}, but the destination-tag hop from "
                    f"{previous} toward terminal {dest} lands at "
                    f"{expected_next}")
            if stage != router_stage(previous) + 1:
                raise BookSimExecutionError(
                    f"flit {flit} moved from stage {router_stage(previous)} "
                    f"to stage {stage}: a fly hop advances exactly one stage")
        egress_router, _ = terminal_egress_location(dest)
        if stage == LEVELS - 1 and router != egress_router:
            raise BookSimExecutionError(
                f"flit {flit} reached stage-2 router {router}, but terminal "
                f"{dest} ejects at {egress_router}")
        if not 0 <= inp < K:
            raise BookSimExecutionError(
                f"flit {flit} was observed entering router {router} on port "
                f"{inp}, which no fly router has")
        stages[stage] += 1
        last_router[flit] = router
        rows += 1
    if rows == 0:
        raise BookSimExecutionError(
            "native route observation dump carries no executed rows")
    return {"rows": rows, "flits": len(last_router), "stages": stages,
            "endpoints": TERMINALS}
