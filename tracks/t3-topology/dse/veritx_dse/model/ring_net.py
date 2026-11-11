"""Native 1-D ring construction and dateline law, independent of execution.

A ring is one wraparound dimension with two neighbours per router. It is NOT
a square torus and not a line: the model's port law below is the one the
native router executes (port 0 leaves toward +1, port 1 toward -1, in that
fixed order on every router), and the dateline is the single wrap edge
between router n-1 and router 0.
"""
from .topology_artifact import MaterializedFamily, TopologyError, _artifact


def materialize_ring(intent, *, width_bits=64, latency_cycles=1):
    if intent.kind != "ring_native":
        raise TopologyError("ring construction requires the native ring intent")
    n = intent.router_count
    if n < 3:
        raise TopologyError("a native ring needs at least 3 routers")
    # Fixed port law: index 0 is the +1 (east) neighbour, index 1 the -1
    # (west) one. Sorting neighbours instead would flip the port order at
    # the wrap router only, so the port ids would stop being a direction.
    adjacency = {r: [(r + 1) % n, (r - 1) % n] for r in range(n)}
    coordinates = {r: (r,) for r in range(n)}
    return _artifact(MaterializedFamily.RING_NATIVE, adjacency, coordinates, 1,
                     width_bits, latency_cycles)


def ring_terminal_location(terminal, router_count):
    if type(terminal) is not int or not 0 <= terminal < router_count:
        raise TopologyError(
            f"ring terminal must be an integer in 0..{router_count - 1}")
    return terminal, 0


def ring_direction(source, destination, router_count):
    """Minimal wrap direction: 0 for +1, 1 for -1 (midpoint tie -> 0)."""
    forward = (destination - source) % router_count
    if forward == 0:
        raise TopologyError(
            f"router {source} has no ring hop to itself")
    return 0 if forward <= router_count // 2 else 1


def ring_next_router(source, destination, router_count):
    direction = ring_direction(source, destination, router_count)
    return (source + (1 if direction == 0 else -1)) % router_count, direction


def ring_dateline_partition(source, destination):
    """The VC half of a hop under the fixed dateline at n-1/0.

    Reducible from the fork's ``dor_next_torus`` (balance=false): both
    disjuncts of its partition test reduce to ``source > destination``, so
    the half is decided by position vs destination alone, whatever the
    midpoint tie resolves to.
    """
    return 1 if source > destination else 0


def ring_native_router_id(topology, router):
    """BookSim's k-ary n-cube ids are dense at n=1, so this is the id."""
    return topology.routers[router].coordinates[0]


def ring_native_ports(topology, router):
    """Model port ids are seat-offset by 1; the native router has no seats.

    Returns (east, west) native output port ids for the router.
    """
    seats = topology.routers[router].seat_capacity
    return seats, seats + 1
