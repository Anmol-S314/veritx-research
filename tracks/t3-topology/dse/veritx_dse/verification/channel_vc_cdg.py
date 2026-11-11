"""veritx_dse.verification.channel_vc_cdg — independent (channel, VC) CDG.

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

import math

from veritx_dse.core.errors import SemanticError

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from veritx_dse.core.artifact import freeze, thaw
from veritx_dse.core.route_artifact import RouteArtifact, RouteArtifactError
from veritx_dse.model.resolved_route import ResolvedRouteArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.vc_assignment import VCAssignmentArtifact, VCAssignmentError

CHANNEL_VC_DEPENDENCY_ACYCLIC = "CHANNEL_VC_DEPENDENCY_ACYCLIC"

DATELINE_RESTRICTED_EXPANSION = "dateline_restricted"
DATELINE_RESTRICTED_1D_EXPANSION = "dateline_restricted_1d"
TREE4_DESTINATION_EXPANSION = "tree4_destination_indexed"
FLY_DESTINATION_EXPANSION = "fly_destination_indexed"
GENERIC_EXPANSION = "generic"

DEADLOCK_PROOF_METHODS = (
    "DETERMINISTIC_DOR_THEOREM",
    CHANNEL_VC_DEPENDENCY_ACYCLIC,
    "ESCAPE_SUBNETWORK_THEOREM",
    "FORMAL_BOUNDED_CHECK",
)

DEADLOCK_CERTIFICATE_SCHEMA_VERSION = 1
VERDICTS = ("PASS", "FAIL", "UNSUPPORTED", "NOT_RUN")

CDG_TOOL = "veritx_dse.verification.channel_vc_cdg"
CDG_SCOPE = ("routing+VC dependency proof only (Dally-Seitz (channel,vc) "
             "dependencies); attachment completeness is not recertified "
             "here; buffering/credits not modeled")

Verdict = str

ChannelVC = tuple[int, int]

class CDGError(ValueError, SemanticError):
    """The CDG request is inconsistent or tampered with — fail closed."""

@dataclass(frozen=True)
class ChannelVCCDG:
    """The realized dependency graph, deterministic node/edge order."""

    nodes: tuple[ChannelVC, ...]
    edges: tuple[tuple[ChannelVC, ChannelVC], ...]
    cdg_route_classes: tuple[str, ...] = ()
    expansion: str = GENERIC_EXPANSION
    dateline_k: int = 0
    dateline_tie_mirrors: int = 0
    dateline_turn_crosses: int = 0

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def adjacency(self) -> dict[ChannelVC, list[ChannelVC]]:
        adj: dict[ChannelVC, list[ChannelVC]] = {n: [] for n in self.nodes}
        for src, dst in self.edges:
            adj[src].append(dst)
        return adj

    def find_cycle(self) -> list[ChannelVC] | None:
        """First cycle in deterministic DFS order, or None if acyclic."""
        adj = self.adjacency()
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {n: WHITE for n in self.nodes}
        parent: dict[ChannelVC, ChannelVC | None] = {}
        for root in self.nodes:
            if color[root] != WHITE:
                continue
            stack: list[tuple[ChannelVC, int]] = [(root, 0)]
            color[root] = GRAY
            parent[root] = None
            while stack:
                node, idx = stack[-1]
                if idx < len(adj[node]):
                    stack[-1] = (node, idx + 1)
                    nxt = adj[node][idx]
                    if color[nxt] == WHITE:
                        color[nxt] = GRAY
                        parent[nxt] = node
                        stack.append((nxt, 0))
                    elif color[nxt] == GRAY:
                        cycle = [nxt]
                        cur = node
                        while cur is not None and cur != nxt:
                            cycle.append(cur)
                            cur = parent[cur]
                        cycle.append(nxt)
                        cycle.reverse()
                        return cycle
                else:
                    color[node] = BLACK
                    stack.pop()
        return None

def _require_types(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> None:
    if not isinstance(topology, TopologyArtifact):
        raise CDGError("topology must be a TopologyArtifact")
    if not isinstance(router_route, RouteArtifact):
        raise CDGError("router_route must be a RouteArtifact")
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise CDGError("vc_assignment must be a VCAssignmentArtifact")

def _fork_partition(a: int, b: int, direction: int) -> int:
    """The fork's fixed-dateline rule, verbatim (``dor_next_torus`` with
    ``balance=false``): partition 1 iff ``(dir == 0 and cur > dest)`` or
    ``(dir == 1 and dest < cur)``. ``direction`` is 0 (Right/+x) or 1
    (Left/-x) and must be a minimal direction (either coin outcome on
    midpoint ties)."""
    if direction not in (0, 1):
        raise CDGError(
            f"dateline direction must be 0 or 1, got {direction!r}")
    if (direction == 0 and a > b) or (direction == 1 and b < a):
        return 1
    return 0

def dateline_partition(a: int, b: int) -> int:
    """The VC half for a 1D traversal from ``a`` to ``b``.

    Reducible from :func:`_fork_partition`: both disjuncts are ``a > b``,
    so the partition is 1 iff ``a > b`` REGARDLESS of the minimal
    direction — midpoint ties take the same half whichever way the fork
    resolves them. (Pinned by test over all coordinate pairs.)"""
    return 1 if a > b else 0

def _ring_dateline_request(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> tuple:
    """Whether the 1-D dateline expansion applies to this fabric."""
    from veritx_dse.core.route_artifact import RING_DATELINE
    from veritx_dse.model.topology_artifact import MaterializedFamily
    declared = {d.id for d in router_route.routing_classes}
    if declared != {RING_DATELINE}:
        return False, "routing classes are not exactly RING_DATELINE"
    if tuple(vc_assignment.vc_ids) != (0, 1):
        return False, "VC set is not exactly (0, 1)"
    if tuple(vc_assignment.allowed_transitions) != ((0, 0), (1, 1)):
        return False, "transitions are not identity"
    bound = set(dict(vc_assignment.vc_to_routing_class).values())
    if bound != {RING_DATELINE}:
        return False, "VCs are not all bound to RING_DATELINE"
    if getattr(topology, "family", None) is not MaterializedFamily.RING_NATIVE:
        return False, "topology family is not RING_NATIVE"
    return True, "RING_DATELINE dateline partition over exact 2 VCs"


def _ring_dateline_edges(
        topology: TopologyArtifact,
        table: dict,
        n: int,
        envelope: tuple,
) -> tuple:
    """Expand the TRUE executed (channel, VC) dependencies of a 1-D ring.

    A hop's half is ``dateline_partition(flow source, destination)``: the
    fork sets ``ph`` once, at the routing decision that turns into the ring
    dimension, and then keeps it for every later hop of that packet (the
    in-dimension branch only flips the output port). The half is therefore a
    property of the FLOW, not of the hop, and the transitions stay identity —
    verified against the fork's own executed dumps, not assumed.

    Both minimal directions are expanded when a flow is diametral: the
    midpoint tie is a coin the hardware may land either way, and a proof over
    one face of it would not cover the fabric.
    """
    channel_by_id = {c.channel_id: c for c in topology.channels}
    channel_by_pair: dict[tuple[int, int], int] = {}
    for ch in topology.channels:
        key = (ch.src_router, ch.dst_router)
        if key in channel_by_pair:
            raise CDGError(
                f"parallel ring channels {key} — a ring hop is not a bundle")
        channel_by_pair[key] = ch.channel_id
    edges: set[tuple[ChannelVC, ChannelVC]] = set()
    tie_mirrors = 0
    crossings = 0

    def _table_run(s: int, d: int) -> list[int]:
        channels: list[int] = []
        cur, seen = s, {s}
        while cur != d:
            ch_id = table.get((cur, d))
            if ch_id is None:
                raise CDGError(
                    f"RING_DATELINE route has no entry for ({cur},{d}) on "
                    f"flow ({s},{d}) — the table is incomplete")
            ch = channel_by_id.get(ch_id)
            if ch is None or ch.src_router != cur:
                raise CDGError(
                    f"RING_DATELINE route ({cur},{d}) names channel "
                    f"{ch_id!r}, which does not leave router {cur}")
            channels.append(ch_id)
            cur = ch.dst_router
            if cur in seen:
                raise CDGError(
                    f"RING_DATELINE route revisits router {cur} on flow "
                    f"({s},{d}) — not a minimal ring path")
            seen.add(cur)
        return channels

    def _add(channels: list[int], s: int, d: int) -> None:
        nonlocal crossings
        path = [s]
        for ch_id in channels:
            path.append(channel_by_id[ch_id].dst_router)
        if path[-1] != d:
            raise CDGError(
                f"flow ({s},{d}) run does not reach its destination")
        shortest = min((d - s) % n, (s - d) % n)
        if len(channels) != shortest:
            raise CDGError(
                f"flow ({s},{d}) run takes {len(channels)} hops, not the "
                f"{shortest} of a minimal ring traversal")
        halves = [dateline_partition(s, d)] * len(channels)
        for i in range(len(channels) - 1):
            transition = (halves[i], halves[i + 1])
            if transition not in envelope:
                raise CDGError(
                    f"flow ({s},{d}) hop {path[i]}->{path[i + 1]} crosses "
                    f"VC {transition[0]}->{transition[1]}, which the ring "
                    f"dateline envelope {list(envelope)} does not declare")
            if halves[i] != halves[i + 1]:
                crossings += 1
            edges.add(((channels[i], halves[i]),
                       (channels[i + 1], halves[i + 1])))

    for s in range(n):
        for d in range(n):
            if s == d:
                continue
            _add(_table_run(s, d), s, d)
            if n % 2 == 0 and (d - s) % n == n // 2:
                mirror_head = (s - 1) % n
                ch_id = channel_by_pair.get((s, mirror_head))
                if ch_id is None:
                    raise CDGError(
                        f"tie-mirror run for flow ({s},{d}) has no channel "
                        f"{s}->{mirror_head}")
                _add([ch_id] + _table_run(mirror_head, d), s, d)
                tie_mirrors += 1
    diag = {"tie_mirrors": tie_mirrors, "turn_crosses": crossings}
    return edges, diag


def _dateline_restricted_request(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> tuple:
    """Whether the dateline-partition expansion applies.

    ALL of: single routing class DOR_TORUS_XY; exactly VCs (0, 1);
    identity transitions; both VCs bound to DOR_TORUS_XY; square torus.
    Anything else takes the generic expansion (which FAILs on the X-ring
    witness — unproven, never wrongly passed)."""
    from veritx_dse.core.route_artifact import DOR_TORUS_XY
    from veritx_dse.model.topology_artifact import MaterializedFamily
    declared = {d.id for d in router_route.routing_classes}
    if declared != {DOR_TORUS_XY}:
        return False, "routing classes are not exactly DOR_TORUS_XY"
    if tuple(vc_assignment.vc_ids) != (0, 1):
        return False, "VC set is not exactly (0, 1)"
    if tuple(vc_assignment.allowed_transitions) != ((0, 0), (1, 1)):
        return False, "transitions are not identity"
    bound = set(dict(vc_assignment.vc_to_routing_class).values())
    if bound != {DOR_TORUS_XY}:
        return False, "VCs are not all bound to DOR_TORUS_XY"
    if getattr(topology, "family", None) is not MaterializedFamily.TORUS:
        return False, "topology family is not TORUS"
    return True, "DOR_TORUS_XY dateline partition over exact 2 VCs"

def _dateline_restricted_edges(
        topology: TopologyArtifact,
        table: dict,
        id_to_xy: dict,
        k: int,
) -> tuple:
    """Expand the TRUE executed dependencies under the ph-discipline.

Rationale: docs/decisions/modules/verification.md
    """
    channel_by_id = {c.channel_id: c for c in topology.channels}
    channel_by_pair = {}
    for ch in topology.channels:
        channel_by_pair.setdefault(
            (ch.src_router, ch.dst_router), ch.channel_id)
    xy_to_id = {xy: rid for rid, xy in id_to_xy.items()}
    edges = set()
    tie_mirrors = 0
    turn_crosses = 0

    def _geom_run(x0: int, y0: int, xd_: int, yd_: int,
                  x_dir: int, y_dir: int) -> list | None:
        """One geometric phase-pair run as channels, or None.

        Used ONLY for tie-mirror phases (minimal by construction: a
        diametral run spans exactly k/2 hops). Non-tie phases always
        ride the canonical table run — a geometric run there could take
        the long way around and invent dependencies the fork never
        takes, so it is never built."""
        nodes = [(x0, y0)]
        x, y = x0, y0
        while x != xd_:
            x = (x + x_dir) % k
            nodes.append((x, y))
            if len(nodes) > k + 1:
                return None
        while y != yd_:
            y = (y + y_dir) % k
            nodes.append((x, y))
            if len(nodes) > 2 * k + 1:
                return None
        ids = []
        for (ax, ay) in nodes:
            rid = xy_to_id.get((ax, ay))
            if rid is None:
                return None
            ids.append(rid)
        chs = []
        for i in range(len(ids) - 1):
            ch = channel_by_pair.get((ids[i], ids[i + 1]))
            if ch is None:
                return None
            chs.append(ch)
        return chs

    routers = sorted(id_to_xy)
    for s in routers:
        xs, ys = id_to_xy[s]
        for d in routers:
            if s == d:
                continue
            xd, yd = id_to_xy[d]
            x_tie = (k % 2 == 0 and xs != xd
                     and (xd - xs) % k == k // 2)
            y_tie = (k % 2 == 0 and ys != yd
                     and (yd - ys) % k == k // 2)
            px = dateline_partition(xs, xd) if xs != xd else None
            py = dateline_partition(ys, yd) if ys != yd else None
            canon: list = []
            cur = s
            seen = {s}
            while cur != d:
                ch_id = table.get((cur, d))
                if ch_id is None:
                    raise CDGError(
                        f"DOR_TORUS_XY route has no entry for ({cur},{d})"
                        f" on flow ({s},{d}) — the table is incomplete")
                ch = channel_by_id.get(ch_id)
                if ch is None or ch.src_router != cur:
                    raise CDGError(
                        f"DOR_TORUS_XY route ({cur},{d}) names channel "
                        f"{ch_id!r}, which does not leave router {cur}")
                canon.append(ch_id)
                cur = ch.dst_router
                if cur in seen:
                    raise CDGError(
                        f"DOR_TORUS_XY route revisits router {cur} on flow "
                        f"({s},{d}) — not a minimal DOR path")
                seen.add(cur)
            canon_nodes = [s]
            for ch_id in canon:
                canon_nodes.append(channel_by_id[ch_id].dst_router)
            xrun_canon: list = []
            yrun_canon: list = []
            in_y = False
            for idx, ch_id in enumerate(canon):
                if id_to_xy[canon_nodes[idx]][0] != xd and not in_y:
                    xrun_canon.append(ch_id)
                else:
                    in_y = True
                    yrun_canon.append(ch_id)
            xruns = [xrun_canon]
            yruns = [yrun_canon]
            if x_tie:
                mx = _geom_run(xs, ys, xd, ys, -1, 1)
                if mx is None or len(mx) != k // 2:
                    raise CDGError(
                        f"tie-mirror X-run for flow ({s},{d}) is not "
                        f"realizable on topology channels — refusing an "
                        f"unproven direction")
                xruns.append(mx)
                tie_mirrors += 1
            if y_tie:
                my = _geom_run(xd, ys, xd, yd, 1, -1)
                if my is None or len(my) != k // 2:
                    raise CDGError(
                        f"tie-mirror Y-run for flow ({s},{d}) is not "
                        f"realizable on topology channels — refusing an "
                        f"unproven direction")
                yruns.append(my)
                tie_mirrors += 1
            runs: list = []
            for xc in xruns:
                for yc in yruns:
                    if not xc and not yc:
                        continue
                    runs.append(xc + yc)
            for channels in runs:
                node_path = [s]
                for ch_id in channels:
                    node_path.append(channel_by_id[ch_id].dst_router)
                if node_path[-1] != d:
                    raise CDGError(
                        f"flow ({s},{d}) run does not reach its "
                        f"destination — refusing an unproven path")
                seen_y = False
                for i in range(len(channels) - 1):
                    u, v, w = (node_path[i], node_path[i + 1],
                               node_path[i + 2])
                    xu = id_to_xy[u][0]
                    xv = id_to_xy[v][0]
                    if seen_y and xu != xv:
                        raise CDGError(
                            f"flow ({s},{d}) returns to X after Y — not "
                            f"a DOR X-then-Y path")
                    if xu != xd:
                        hu = px
                    else:
                        hu = py
                        seen_y = True
                    if xv != xd:
                        hv = px
                    else:
                        hv = py
                        seen_y = True
                    if hu is None or hv is None:
                        raise CDGError(
                            f"flow ({s},{d}) hop {u}->{v}->{w} has no "
                            f"dateline half — phase detection failed")
                    cu = channels[i]
                    cv = channels[i + 1]
                    if hu == hv:
                        edges.add(((cu, hu), (cv, hu)))
                    else:
                        turn_crosses += 1
                        edges.add(((cu, hu), (cv, hv)))
    diag = {"tie_mirrors": tie_mirrors, "turn_crosses": turn_crosses}
    return edges, diag

def _tree4_request(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> tuple:
    """Whether the native Tree4 destination-indexed expansion applies."""
    from veritx_dse.core.route_artifact import TREE4_NCA
    from veritx_dse.model.topology_artifact import MaterializedFamily
    declared = {d.id for d in router_route.routing_classes}
    if declared != {TREE4_NCA}:
        return False, f"routing classes are {sorted(declared)}, not TREE4_NCA"
    if getattr(topology, "family", None) is not MaterializedFamily.TREE4_NATIVE:
        return False, "topology family is not TREE4_NATIVE"
    bound = set(dict(vc_assignment.vc_to_routing_class).values())
    if bound != {TREE4_NCA}:
        return False, "VCs are not all bound to TREE4_NCA"
    return True, "TREE4_NCA destination-indexed union"


def _fly_request(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> tuple:
    """Whether the native fly destination-indexed expansion applies."""
    from veritx_dse.core.route_artifact import FLY_DEST_TAG
    from veritx_dse.model.topology_artifact import MaterializedFamily
    declared = {d.id for d in router_route.routing_classes}
    if declared != {FLY_DEST_TAG}:
        return False, f"routing classes are {sorted(declared)}, not FLY_DEST_TAG"
    if getattr(topology, "family", None) is not MaterializedFamily.FLY_NATIVE:
        return False, "topology family is not FLY_NATIVE"
    bound = set(dict(vc_assignment.vc_to_routing_class).values())
    if bound != {FLY_DEST_TAG}:
        return False, "VCs are not all bound to FLY_DEST_TAG"
    return True, "FLY_DEST_TAG destination-indexed chain"


def _fly_edges(
        topology: TopologyArtifact,
        transitions: tuple,
        terminals: int,
) -> tuple[tuple[ChannelVC, ChannelVC], ...]:
    """Exact dependencies of the native fly's destination-tag law.

    Destinations are TERMINALS, and a terminal injects at one stage-0 router
    and ejects at one stage-2 router. The channel chain of a terminal is
    therefore a single deterministic path, and a channel may be followed by
    another only when they are consecutive links of that SAME terminal's
    path (which two terminals sharing an egress router also share, exactly as
    the hardware does). Every hop strictly advances the stage, so acyclicity
    is a property of the construction rather than an assumption about it.
    """
    from veritx_dse.model.fly_net import (
        LEVELS, egress_port, next_router, router_stage,
        terminal_egress_location, terminal_ingress_location,
    )
    channel_id = {(c.src_router, c.dst_router): c.channel_id
                  for c in topology.channels}
    if len(channel_id) != len(topology.channels):
        raise CDGError(
            "the native fly has parallel channels between one router pair; "
            "the destination-indexed expansion cannot name them")
    edges: set[tuple[ChannelVC, ChannelVC]] = set()
    for terminal in range(terminals):
        ingress, _ = terminal_ingress_location(terminal)
        egress, _ = terminal_egress_location(terminal)
        chain: list[int] = []
        router = ingress
        for _ in range(LEVELS - 1):
            port = egress_port(router, egress)
            if port is None:
                raise CDGError(
                    f"terminal {terminal} has no forward hop at router "
                    f"{router}")
            following = next_router(router, port)
            if following is None:
                raise CDGError(
                    f"terminal {terminal} ejects before its last stage")
            ch = channel_id.get((router, following))
            if ch is None:
                raise CDGError(
                    f"fly hop {router}->{following} for terminal {terminal} "
                    "names no directed channel")
            chain.append(ch)
            router = following
        if router != egress:
            raise CDGError(
                f"terminal {terminal} ends at router {router}, not its "
                f"ejection router {egress}")
        if [router_stage(channel_dst(topology, c)) for c in chain] != \
                sorted(router_stage(channel_dst(topology, c)) for c in chain):
            raise CDGError(
                f"terminal {terminal} hops do not advance stage")
        for a, b in zip(chain, chain[1:]):
            for vc_in, vc_out in transitions:
                edges.add(((a, vc_in), (b, vc_out)))
    return tuple(sorted(edges))


def channel_dst(topology: TopologyArtifact, channel_id: int) -> int:
    for channel in topology.channels:
        if channel.channel_id == channel_id:
            return channel.dst_router
    raise CDGError(f"channel {channel_id} is not in the topology")


def _tree4_edges(
        topology: TopologyArtifact,
        transitions: tuple,
        terminals: int,
) -> tuple[tuple[ChannelVC, ChannelVC], ...]:
    """Exact dependencies of the native Tree4's choice-valued NCA law.

    A coarse (channel -> any-next-channel) graph would report a cycle that
    no flit can take: `middle -> leaf` is only chosen when the leaf IS the
    destination, and a flit at its destination ejects. The graph is
    therefore built PER DESTINATION: channel `a` may be followed by channel
    `b` only when both carry the SAME terminal, which is exactly the routing
    the hardware executes. Upward links never follow a downward one, so the
    up*/down* discipline is a consequence of the law rather than an
    assumption about it.
    """
    from veritx_dse.model.tree4_net import (
        tree4_legal_ports, tree4_next_router,
    )
    channel_id = {(c.src_router, c.dst_router): c.channel_id
                  for c in topology.channels}
    if len(channel_id) != len(topology.channels):
        raise CDGError(
            "the native Tree4 has parallel channels between one router "
            "pair; the destination-indexed expansion cannot name them")
    edges: set[tuple[ChannelVC, ChannelVC]] = set()
    routers = range(len(topology.routers))
    for terminal in range(terminals):
        usable: list[int] = []
        for router in routers:
            for port in tree4_legal_ports(router, terminal):
                following = tree4_next_router(router, port)
                if following is None:
                    continue
                ch = channel_id.get((router, following))
                if ch is None:
                    raise CDGError(
                        f"TREE4_NCA hop {router}->{following} for terminal "
                        f"{terminal} names no directed channel")
                usable.append(ch)
        for a in usable:
            dst_router = None
            for channel in topology.channels:
                if channel.channel_id == a:
                    dst_router = channel.dst_router
                    break
            if dst_router is None:
                raise CDGError(f"channel {a} is not in the topology")
            for b in usable:
                src = None
                for channel in topology.channels:
                    if channel.channel_id == b:
                        src = channel.src_router
                        break
                if src != dst_router:
                    continue
                for vc_in, vc_out in transitions:
                    edges.add(((a, vc_in), (b, vc_out)))
    return tuple(sorted(edges))


def build_channel_vc_cdg(
        topology: TopologyArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> ChannelVCCDG:
    """Expand routing over the (channel, VC) resources.

    Raises CDGError if the VC assignment uses a routing class this
    certifier cannot interpret (the caller reports UNSUPPORTED).
    """
    _require_types(topology, router_route, vc_assignment)
    if router_route.schema_version != 2:
        raise CDGError(
            "router route is not schema v2 (class-aware channel "
            "realization) — cannot build the realized CDG")
    declared = {d.id for d in router_route.routing_classes}
    if not declared:
        raise CDGError(
            "router route does not declare routing classes (schema v2 "
            "required) — cannot build the realized CDG")
    class_of_vc = dict(vc_assignment.vc_to_routing_class)
    unknown = set(class_of_vc.values()) - declared
    if unknown:
        raise CDGError(
            f"VC routing classes {sorted(unknown)} are not defined by the "
            f"router route (has {sorted(declared)}) — cannot build the "
            f"realized CDG")

    per_class: dict[str, dict[tuple[int, int], int]] = {cid: {}
                                                        for cid in declared}
    for (cid, s, d), ch in router_route.entries.items():
        table = per_class.get(cid)
        if table is None:
            raise CDGError(
                f"router route entry {cid!r} is not a declared routing class")
        table[(s, d)] = ch
    channel_by_id = {c.channel_id: c for c in topology.channels}
    for cid in sorted(per_class):
        for (s, d), ch_id in sorted(per_class[cid].items()):
            if type(ch_id) is not int or ch_id not in channel_by_id:
                raise CDGError(
                    f"{cid} route ({s},{d}) names channel {ch_id!r}, which "
                    f"is not in the topology")

    ring, ring_why = _ring_dateline_request(
        topology, router_route, vc_assignment)
    if ring:
        from veritx_dse.core.route_artifact import RING_DATELINE
        n = len(topology.routers)
        redges, diag = _ring_dateline_edges(
            topology, per_class[RING_DATELINE], n,
            tuple(vc_assignment.allowed_transitions))
        nodes = tuple(
            (ch.channel_id, vc)
            for ch in topology.channels
            for vc in vc_assignment.vc_ids
        )
        return ChannelVCCDG(
            nodes=nodes, edges=tuple(sorted(redges)),
            cdg_route_classes=tuple(sorted(declared)),
            expansion=DATELINE_RESTRICTED_1D_EXPANSION,
            dateline_k=n,
            dateline_tie_mirrors=diag["tie_mirrors"],
            dateline_turn_crosses=diag["turn_crosses"])

    tree4, tree4_why = _tree4_request(
        topology, router_route, vc_assignment)
    if tree4:
        seats = sum(r.seat_capacity for r in topology.routers)
        edges = _tree4_edges(
            topology, tuple(vc_assignment.allowed_transitions), seats)
        nodes = tuple(
            (ch.channel_id, vc)
            for ch in topology.channels
            for vc in vc_assignment.vc_ids
        )
        return ChannelVCCDG(
            nodes=nodes, edges=edges,
            cdg_route_classes=tuple(sorted(declared)),
            expansion=TREE4_DESTINATION_EXPANSION)

    fly, fly_why = _fly_request(topology, router_route, vc_assignment)
    if fly:
        seats = sum(r.seat_capacity for r in topology.routers)
        edges = _fly_edges(
            topology, tuple(vc_assignment.allowed_transitions), seats)
        nodes = tuple(
            (ch.channel_id, vc)
            for ch in topology.channels
            for vc in vc_assignment.vc_ids
        )
        return ChannelVCCDG(
            nodes=nodes, edges=edges,
            cdg_route_classes=tuple(sorted(declared)),
            expansion=FLY_DESTINATION_EXPANSION)

    restricted, restricted_why = _dateline_restricted_request(
        topology, router_route, vc_assignment)
    if restricted:
        from veritx_dse.core.route_artifact import DOR_TORUS_XY
        id_to_xy = {}
        for r in topology.routers:
            coords = getattr(r, "coordinates", None)
            if coords is None:
                raise CDGError(
                    "dateline restriction needs router coordinates — "
                    "refusing an unproven geometry")
            id_to_xy[r.router_id] = (coords[0], coords[1])
        n = len(id_to_xy)
        k = math.isqrt(n)
        if k < 2 or k * k != n:
            raise CDGError(
                f"dateline restriction needs a square k x k torus, got "
                f"{n} routers")
        if set(id_to_xy.values()) != {(x, y) for x in range(k)
                                      for y in range(k)}:
            raise CDGError(
                "dateline restriction needs a full rectangular grid")
        redges, diag = _dateline_restricted_edges(
            topology, per_class[DOR_TORUS_XY], id_to_xy, k)
        nodes = tuple(
            (ch.channel_id, vc)
            for ch in topology.channels
            for vc in vc_assignment.vc_ids
        )
        return ChannelVCCDG(
            nodes=nodes, edges=tuple(sorted(redges)),
            cdg_route_classes=tuple(sorted(declared)),
            expansion=DATELINE_RESTRICTED_EXPANSION,
            dateline_k=k,
            dateline_tie_mirrors=diag["tie_mirrors"],
            dateline_turn_crosses=diag["turn_crosses"])

    nodes = tuple(
        (ch.channel_id, vc)
        for ch in topology.channels
        for vc in vc_assignment.vc_ids
    )
    unmapped = sorted({vc for pair in vc_assignment.allowed_transitions
                       for vc in pair} - set(class_of_vc))
    if unmapped:
        raise CDGError(
            f"VCs {unmapped} appear in allowed_transitions but name no "
            f"routing class — the (channel, VC) proof cannot cover them")
    edges: set[tuple[ChannelVC, ChannelVC]] = set()
    for vc_in, vc_out in vc_assignment.allowed_transitions:
        class_in = class_of_vc[vc_in]
        class_out = class_of_vc[vc_out]
        table_in = per_class[class_in]
        table_out = per_class[class_out]
        for (s, d), in_id in sorted(table_in.items()):
            v = channel_by_id[in_id].dst_router
            if v == d:
                continue
            out_id = table_out.get((v, d))
            if out_id is None:
                raise CDGError(
                    f"{class_in} route ({s},{d}) reaches router {v} but the "
                    f"{class_out} route has no entry for ({v},{d}) — the "
                    f"{class_in}->{class_out} transition is not realizable")
            out_ch = channel_by_id[out_id]
            if out_ch.src_router != v:
                raise CDGError(
                    f"{class_out} route ({v},{d}) names channel {out_id}, "
                    f"which does not leave router {v}")
            edges.add(((in_id, vc_in), (out_id, vc_out)))

    return ChannelVCCDG(nodes=nodes, edges=tuple(sorted(edges)),
                        cdg_route_classes=tuple(sorted(declared)))

@dataclass(frozen=True)
class DeadlockCertificate:
    """Immutable structured deadlock verdict with every bound artifact hash.

Rationale: docs/decisions/modules/verification.md
    """

    proof_method: str
    verdict: Verdict
    topology_hash: str
    attachment_hash: str
    router_route_hash: str
    resolved_route_hash: str
    vc_assignment_hash: str
    router_behavior_hash: str
    evidence: Mapping[str, Any] = field(default_factory=dict)
    tool: str = CDG_TOOL
    scope: str = CDG_SCOPE
    schema_version: int = DEADLOCK_CERTIFICATE_SCHEMA_VERSION

    def __post_init__(self):
        if self.proof_method not in DEADLOCK_PROOF_METHODS:
            raise CDGError(
                f"proof method {self.proof_method!r} is not in the closed "
                f"vocabulary {list(DEADLOCK_PROOF_METHODS)}")
        if self.verdict not in VERDICTS:
            raise CDGError(
                f"verdict {self.verdict!r} is not one of {list(VERDICTS)}")
        for name in ("topology_hash", "attachment_hash", "router_route_hash",
                     "resolved_route_hash", "vc_assignment_hash"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value:
                raise CDGError(f"{name} must be a non-empty string")
        if not isinstance(self.router_behavior_hash, str):
            raise CDGError("router_behavior_hash must be a string")
        if not isinstance(self.tool, str) or not self.tool:
            raise CDGError("tool must be a non-empty string")
        if not isinstance(self.scope, str) or not self.scope:
            raise CDGError("scope must be a non-empty string")
        if type(self.schema_version) is not int or \
                self.schema_version != DEADLOCK_CERTIFICATE_SCHEMA_VERSION:
            raise CDGError(
                f"unsupported deadlock-certificate schema_version "
                f"{self.schema_version!r}")
        if not isinstance(self.evidence, Mapping):
            raise CDGError("evidence must be a mapping")
        object.__setattr__(self, "evidence", freeze(self.evidence))

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/DeadlockCertificate",
            "schema_version": self.schema_version,
            "proof_method": self.proof_method,
            "verdict": self.verdict,
            "topology_hash": self.topology_hash,
            "attachment_hash": self.attachment_hash,
            "router_route_hash": self.router_route_hash,
            "resolved_route_hash": self.resolved_route_hash,
            "vc_assignment_hash": self.vc_assignment_hash,
            "router_behavior_hash": self.router_behavior_hash,
            "evidence": thaw(self.evidence),
            "tool": self.tool,
            "scope": self.scope,
        }

def _binding_hashes(
        topology: TopologyArtifact,
        resolved_route: ResolvedRouteArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
) -> tuple[str, str, str, str, str]:
    """Prove the parent chain this verifier actually relies on.

    Deliberately does NOT call ``resolved_route.validate_against(...)``:
    that also requires the real AgentAttachmentArtifact. Attachment
    completeness is not recertified here (see ``CDG_SCOPE``).
    """
    if not isinstance(topology, TopologyArtifact):
        raise CDGError("topology must be a TopologyArtifact")
    if not isinstance(resolved_route, ResolvedRouteArtifact):
        raise CDGError("resolved_route must be a ResolvedRouteArtifact")
    if not isinstance(router_route, RouteArtifact):
        raise CDGError("router_route must be a RouteArtifact")
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise CDGError("vc_assignment must be a VCAssignmentArtifact")
    if router_route.schema_version != 2:
        raise CDGError(
            "router route is not schema v2 (class-aware channel "
            "realization); v1 is refused on the certification path")
    if resolved_route.topology_hash != topology.topology_hash():
        raise CDGError("resolved route does not bind this topology")
    if resolved_route.router_route_hash != router_route.artifact_hash:
        raise CDGError("resolved route does not bind this router route")
    if vc_assignment.resolved_route_hash != resolved_route.resolved_route_hash():
        raise CDGError("VC assignment does not bind this resolved route")
    try:
        router_route.validate_against(topology)
    except RouteArtifactError as exc:
        raise CDGError(
            f"router route fails parent validation against the topology: "
            f"{exc}") from exc
    try:
        vc_assignment.validate_against(resolved_route)
    except VCAssignmentError as exc:
        raise CDGError(
            f"VC assignment fails parent validation against the resolved "
            f"route: {exc}") from exc
    return (topology.topology_hash(), resolved_route.attachment_hash,
            router_route.artifact_hash, resolved_route.resolved_route_hash(),
            vc_assignment.vc_assignment_hash())

def certify_channel_vc_deadlock(
        *,
        topology: TopologyArtifact,
        resolved_route: ResolvedRouteArtifact,
        router_route: RouteArtifact,
        vc_assignment: VCAssignmentArtifact,
        router_behavior_hash: str = "",
) -> DeadlockCertificate:
    """Prove or refute acyclicity of the realized (channel, VC) CDG.

    Verdicts: PASS (acyclic), FAIL (deterministic cycle witness),
    UNSUPPORTED (routing/VC semantics not interpretable exactly). A
    designated escape VC never changes the verdict by itself.
    """
    topo_hash, att_hash, router_hash, rr_hash, vc_hash = _binding_hashes(
        topology, resolved_route, router_route, vc_assignment)

    classes = sorted({rc for _vc, rc in vc_assignment.vc_to_routing_class})
    evidence: dict[str, Any] = {
        "vc_count": vc_assignment.vc_count,
        "routing_classes": classes,
        "escape_vcs": list(vc_assignment.escape_vcs),
    }

    try:
        cdg = build_channel_vc_cdg(topology, router_route, vc_assignment)
    except CDGError as exc:
        evidence["unsupported_reason"] = str(exc)
        return DeadlockCertificate(
            proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="UNSUPPORTED",
            topology_hash=topo_hash, attachment_hash=att_hash,
            router_route_hash=router_hash, resolved_route_hash=rr_hash,
            vc_assignment_hash=vc_hash,
            router_behavior_hash=router_behavior_hash, evidence=evidence)

    evidence["node_count"] = cdg.node_count
    evidence["edge_count"] = cdg.edge_count
    evidence["route_realization"] = "v2_channel_id"
    evidence["cdg_route_classes"] = list(cdg.cdg_route_classes)
    evidence["expansion"] = cdg.expansion
    if cdg.expansion in (DATELINE_RESTRICTED_EXPANSION,
                         DATELINE_RESTRICTED_1D_EXPANSION):
        evidence["dateline_k"] = cdg.dateline_k
        evidence["dateline_tie_mirrors"] = cdg.dateline_tie_mirrors
        evidence["dateline_turn_crosses"] = cdg.dateline_turn_crosses
    cycle = cdg.find_cycle()
    if cycle is None:
        evidence["acyclic"] = True
        return DeadlockCertificate(
            proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="PASS",
            topology_hash=topo_hash, attachment_hash=att_hash,
            router_route_hash=router_hash, resolved_route_hash=rr_hash,
            vc_assignment_hash=vc_hash,
            router_behavior_hash=router_behavior_hash, evidence=evidence)
    evidence["acyclic"] = False
    evidence["cycle"] = [list(node) for node in cycle]
    return DeadlockCertificate(
        proof_method=CHANNEL_VC_DEPENDENCY_ACYCLIC, verdict="FAIL",
        topology_hash=topo_hash, attachment_hash=att_hash,
        router_route_hash=router_hash, resolved_route_hash=rr_hash,
        vc_assignment_hash=vc_hash,
        router_behavior_hash=router_behavior_hash, evidence=evidence)
