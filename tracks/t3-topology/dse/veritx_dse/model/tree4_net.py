"""Native Tree4 construction, terminal law and legal-choice union.

Tree4 is NOT the balanced k-ary tree: it has FOUR roots, eight middle
routers and sixteen leaf routers, every middle is wired to every root, and
upward routing picks a parent at random. Two facts therefore cannot be
inherited from the structured `tree4` preset:

* the port law (which index leaves which way, per level), and
* the legal next-hop UNION, because the fork's ``tree4_nca`` draws a real
  random parent with ``RandomInt``.

Canonical router indices here are dense (roots 0..3, middles 4..11, leaves
12..27). BookSim's internal ``Router::GetID`` is ``level*16 + position``,
which is a different, sparser numbering and is never a terminal id.
"""
from .topology_artifact import MaterializedFamily, TopologyError, _artifact

K = 4
LEVELS = 3
#: `(4 >> level) * k**level` routers per level, in BookSim's build order.
LEVEL_COUNTS = tuple((4 >> level) * K**level for level in range(LEVELS))
OFFSETS = tuple(sum(LEVEL_COUNTS[:level]) for level in range(LEVELS))
TERMINALS = K**LEVELS
#: `RandomInt(max)` in this fork is inclusive ([0, max]), so the middle
#: level's `gK + RandomInt(gK-1)` selects ANY of the four roots. Reading it
#: as exclusive would have claimed root 3 is unreachable; the producer's
#: union dump shows port 7 in use, so the inclusive reading is the true one.
UP_ROOTS = tuple(range(K))


def _require_native(intent) -> None:
    if getattr(intent, "kind", None) != "tree4_native" or (
            getattr(intent, "radix", None),
            getattr(intent, "levels", None)) != (K, LEVELS):
        raise TopologyError("Tree4 requires the explicit native Tree4 intent")


def router_level_position(router: int) -> tuple[int, int]:
    if type(router) is not int or not 0 <= router < sum(LEVEL_COUNTS):
        raise TopologyError(f"tree4 router must be an integer in 0..27, got {router!r}")
    for level in range(LEVELS - 1, -1, -1):
        if router >= OFFSETS[level]:
            return level, router - OFFSETS[level]
    raise TopologyError(f"tree4 router {router!r} has no level")


def router_id(level: int, position: int) -> int:
    if not 0 <= level < LEVELS or not 0 <= position < LEVEL_COUNTS[level]:
        raise TopologyError(f"no tree4 router at level {level}, position {position}")
    return OFFSETS[level] + position


def materialize_tree4(intent, *, width_bits=64, latency_cycles=1):
    _require_native(intent)
    coordinates, adjacency, seats = {}, {}, {}
    for level in range(LEVELS):
        for position in range(LEVEL_COUNTS[level]):
            router = OFFSETS[level] + position
            coordinates[router] = (level, position)
            if level == 0:
                # Ports 0..7 leave DOWN to every middle router.
                parents, seats[router] = [], 0
                children = [OFFSETS[1] + m for m in range(LEVEL_COUNTS[1])]
            elif level == 1:
                # Ports 0..3 leave DOWN to the four leaves of this group,
                # ports 4..7 leave UP to the four roots (port 7 = root 3 is
                # wired but never selected by NCA).
                children = [OFFSETS[2] + 4 * (position // 2) + i
                            for i in range(K)]
                parents = [OFFSETS[0] + r for r in range(K)]
                seats[router] = 0
            else:
                # Ports 0..3 are the terminal seats, 4..5 leave UP to the
                # two middles that serve this leaf's destination group.
                children = []
                parents = [OFFSETS[1] + 2 * (position // 4) + i
                           for i in range(2)]
                seats[router] = K
            adjacency[router] = children + parents
    return _artifact(MaterializedFamily.TREE4_NATIVE, adjacency, coordinates,
                     seats, width_bits, latency_cycles)


def tree4_terminal_location(terminal):
    if type(terminal) is not int or not 0 <= terminal < TERMINALS:
        raise TopologyError("tree4 terminal must be an integer in 0..63")
    return OFFSETS[2] + terminal // K, terminal % K


def tree4_terminal_of_seat(router, port):
    """The terminal ejected by (leaf router, seat port), or None."""
    level, position = router_level_position(router)
    if level != LEVELS - 1 or not 0 <= port < K:
        return None
    return K * position + port


def tree4_legal_ports(router, terminal):
    """Every port the fork's NCA can choose at `router` toward `terminal`.

    Verified against the producer's legal-choice union dump: roots pick one
    of the two middles of the destination's group, a middle whose group
    matches goes down to the exact leaf, any other middle picks one of the
    three up ports (root 3 is never chosen), and a leaf ejects locally or
    picks one of its two parents.
    """
    tree4_terminal_location(terminal)
    level, position = router_level_position(router)
    group = terminal // (K**2)
    if level == 0:
        return (2 * group, 2 * group + 1)
    if level == 1:
        if group == position // 2:
            return ((terminal % (K**2)) // K,)
        return tuple(K + r for r in UP_ROOTS)
    if terminal // K == position:
        return (terminal % K,)
    return (K, K + 1)


def tree4_next_router(router, port):
    """The router a port leads to, or None when the port ejects a terminal."""
    level, position = router_level_position(router)
    if not 0 <= port < (K + (2 if level == LEVELS - 1 else K if level == 1 else K)):
        raise TopologyError(
            f"tree4 router {router!r} has no output port {port!r}")
    if level == 0:
        return OFFSETS[1] + port
    if level == 1:
        if port < K:
            return OFFSETS[2] + K * (position // 2) + port
        return OFFSETS[0] + (port - K)
    if port < K:
        return None
    return OFFSETS[1] + 2 * (position // 4) + (port - K)


def tree4_router_next(topology, router, destination):
    """The canonical witness hop toward a ROUTER destination, or None.

    Execution never targets a router: a flit's destination is always a
    terminal, and `tree4_legal_ports` is the executed law. This witness
    exists for the canonical route table (one channel per pair), and it is
    the level-aware extension of the same law: descend when the port leads
    to the destination's level/group, otherwise climb. Every returned port
    is one the port law really has, and `tree4_witness_path` proves the
    witness terminates at every one of the 28x28 pairs instead of trusting
    that it does.
    """
    if router == destination:
        return None
    level, position = router_level_position(router)
    dlevel, dposition = router_level_position(destination)
    if level == 0:
        # A root reaches every middle directly, and every deeper router
        # through the middle that serves it.
        if dlevel == 1:
            return OFFSETS[1] + dposition
        if dlevel == 2:
            return OFFSETS[1] + 2 * (dposition // 4)
        # Another root: no root-root channel, so descend first.
        return OFFSETS[1]
    if level == 1:
        if dlevel == 0:
            return OFFSETS[0] + dposition
        if dlevel == 1:
            # Middles are never adjacent; the route is up to a root, which
            # connects to every middle. Port K + 0 is the minimum legal one.
            return OFFSETS[0]
        if dposition // 4 == position // 2:
            return OFFSETS[2] + dposition
        return OFFSETS[0]
    # A leaf only has its two parents, and the smallest legal one climbs.
    return OFFSETS[1] + 2 * (position // 4)


def tree4_witness_path(topology, router, destination, *, limit=8):
    """Follow the canonical witness to `destination` and prove termination."""
    path = [router]
    while path[-1] != destination:
        if len(path) > limit:
            raise TopologyError(
                f"the canonical Tree4 witness does not reach router "
                f"{destination} from {router} within {limit} hops: {path}")
        step = tree4_router_next(topology, path[-1], destination)
        if step is None or step in path:
            raise TopologyError(
                f"the canonical Tree4 witness loops or stalls on its way "
                f"to router {destination} from {router}: {path}")
        path.append(step)
    return tuple(path)


def tree4_native_router_id(topology, router):
    """BookSim's internal id: `level*16 + position` (never dense)."""
    level, position = router_level_position(router)
    return level * K**2 + position
