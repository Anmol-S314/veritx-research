"""Indirect-tree construction and terminal law, independent of execution.

Dense canonical router indices differ from BookSim QTree's internal
Router::GetID (level*256+position). Neither is a terminal ID.
"""
from .topology_artifact import MaterializedFamily, TopologyError, _artifact


def materialize_qtree(intent, *, width_bits=64, latency_cycles=1):
    if intent.kind != "qtree_native" or (intent.radix, intent.levels) != (4, 3):
        raise TopologyError("QTree requires the explicit native QTree intent")
    k, levels = intent.radix, intent.levels
    offsets = tuple(sum(k**h for h in range(level)) for level in range(levels))
    coordinates = {offsets[level] + position: (level, position)
                   for level in range(levels) for position in range(k**level)}
    adjacency, seats = {}, {}
    for router, (level, position) in coordinates.items():
        # Native port order: children first, parent last. Leaf ports 0..3
        # are terminals; parent port is 4. Internal routers have NO seats.
        children = ([offsets[level + 1] + k * position + port for port in range(k)]
                    if level < levels - 1 else [])
        parent = [offsets[level - 1] + position // k] if level else []
        adjacency[router] = children + parent
        seats[router] = k if level == levels - 1 else 0
    return _artifact(MaterializedFamily.QTREE, adjacency, coordinates, seats,
                     width_bits, latency_cycles)


def qtree_terminal_location(terminal):
    if type(terminal) is not int or not 0 <= terminal < 64:
        raise TopologyError("QTree terminal must be an integer in 0..63")
    return 5 + terminal // 4, terminal % 4


def qtree_nca_next(topology, router, terminal):
    """NCA first hop and native output port, including local ejection."""
    qtree_terminal_location(terminal)
    level, position = topology.routers[router].coordinates
    destination = terminal // (4 ** (2 - level))
    if position == destination // 4:
        port = destination % 4
        next_router = (router if level == 2 else
                       sum(4**h for h in range(level + 1)) + 4*position + port)
        return next_router, port
    return sum(4**h for h in range(level - 1)) + position // 4, 4


def qtree_router_next(topology, router, destination):
    """NCA step for any router destination, used by the canonical route table."""
    if router == destination:
        return None
    level, position = topology.routers[router].coordinates
    target_level, target_position = topology.routers[destination].coordinates
    if target_level > level and target_position // 4**(target_level - level) == position:
        child_position = target_position // 4**(target_level - level - 1)
        return sum(4**h for h in range(level + 1)) + child_position
    return sum(4**h for h in range(level - 1)) + position // 4


def qtree_native_router_id(topology, router):
    level, position = topology.routers[router].coordinates
    return level * 256 + position
