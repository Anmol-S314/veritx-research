"""Native 1-D ring projection: exact geometry, dateline halves, midpoint tie.

The ring executes the fork's 1-D dimension-order function (``dim_order`` over
``torus`` with ``n = 1``), not a square torus and not the legacy line-shaped
ring artifact: the port law is fixed (+1 then -1 on every router), the
dateline is the single n-1/0 wrap, and the half a hop occupies is recomputed
from (position, destination) on every routing decision.

Two faces of the same coin are therefore verified separately:

* the STATIC route dump proves every (router, destination) hop and native
  output port, with the diametral tie admitting either minimal direction;
* the RUNTIME route-compute dump proves the executed hops, their ports and
  their VC halves, which is the only evidence that can show the half rule is
  the one actually executed (a static table cannot carry ``ph``).
"""
from veritx_dse.core.route_artifact import RING_DATELINE
from veritx_dse.model.ring_net import (
    materialize_ring, ring_dateline_partition, ring_next_router,
    ring_terminal_location,
)
from veritx_dse.model.topology_artifact import MaterializedFamily
from veritx_dse.model.topology_intent import RingIntent
from .booksim_projection import (
    BookSimProfile, ConfigRead, ParameterOwner as Owner, SemanticLoss,
    _multi_class_audit, _qualify_point_to_point, _torus_audit,
)

PROFILE_ID = "CERTIFIED_BOOKSIM_RING_DATELINE_V1"
SEMANTICS_VERSION = (
    "booksim2-fork+R1-ring-dateline+runtime-halves-v1+multi-class/v1")
LOWERER_VERSION = "RINGDATELINE/1"
OBSERVATION_FILE = "native_route_observations.txt"


def _ring_audit() -> tuple[ConfigRead, ...]:
    """The torus audit re-pathed for a one-dimensional wraparound ring."""
    rows: list[ConfigRead] = []
    for row in _torus_audit():
        if row.name in ("k", "n"):
            rows.append(ConfigRead(
                row.name, Owner.DERIVED, "networks/kncube.cpp",
                note=("ring router count (k) re-derived from the topology "
                      "artifact; the ring IS the k-1/0 dateline"
                      if row.name == "k" else
                      "PINNED 1: the certified ring is ONE wraparound "
                      "dimension; a second dimension is a torus")))
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", Owner.CANONICAL, "networks/network.cpp", "torus",
                note="native ring render: KNCube with n = 1 and wrap links, "
                     "which is a ring rather than a line"))
            continue
        rows.append(row)
    rows.append(ConfigRead(
        "routing_dump_choice_probes", Owner.BACKEND_PROFILE,
        "networks/network.cpp", 8,
        note="PINNED 8 probes per (router,dst): enough to see both faces of "
             "a midpoint tie, few enough that an adaptive function is "
             "refused instead of silently unioned"))
    rows.append(ConfigRead(
        "native_route_observation_file", Owner.DERIVED, "routefunc.cpp",
        note="mandatory executed route-compute evidence: the dateline half "
             "is a per-hop decision and cannot be read from the static table"))
    return tuple(rows)


PROFILE = BookSimProfile(
    profile_id=PROFILE_ID,
    semantics_version=SEMANTICS_VERSION,
    audit=_multi_class_audit(_ring_audit()))


def qualify(parents, *, multi_class=False) -> int:
    """Prove every prerequisite of the ring envelope, or refuse. Returns n."""
    topology = parents.topology
    if topology.family is not MaterializedFamily.RING_NATIVE:
        raise SemanticLoss(
            "the dateline envelope is certified for ring_native only, got "
            f"{topology.family.value}")
    controls = {channel.width_bits for channel in topology.channels}
    if len(controls) != 1:
        raise SemanticLoss("native ring requires uniform channel widths")
    n = len(topology.routers)
    expected = materialize_ring(RingIntent(n), width_bits=next(iter(controls)))
    if topology.canonical_dict() != expected.canonical_dict():
        raise SemanticLoss(
            "native ring geometry/ports/seats differ from its construction "
            "(+1 then -1 on every router, one seat each)")
    if n % 2:
        # A ring without an exact antipode has no coin flip to prove. Odd
        # rings are a different (simpler) domain and are not certified here.
        raise SemanticLoss(
            f"UNSUPPORTED: the certified ring domain is even k so the "
            f"midpoint tie exists and is proven; got k={n}")
    if len(parents.attachment.endpoints) != n:
        raise SemanticLoss(
            f"native ring requires the complete {n}-terminal attachment, got "
            f"{len(parents.attachment.endpoints)}")
    for endpoint in parents.attachment.endpoints:
        if (endpoint.router_id, endpoint.port_id) != ring_terminal_location(
                endpoint.endpoint_id, n):
            raise SemanticLoss(
                "native ring terminal attachment differs from its seat law")
    if parents.route.routing_classes != (
            parents.route.routing_classes[0],) \
            or parents.route.routing_classes[0].id != RING_DATELINE:
        raise SemanticLoss(
            "ring requires the sealed RING_DATELINE algorithm alone")
    if parents.vc_resource.vc_count != 2:
        raise SemanticLoss(
            "the ring dateline integer-halves the VC range: exactly 2 VCs")
    _qualify_point_to_point(
        parents, routing_class=RING_DATELINE, multi_class=multi_class)
    channels = {channel.channel_id: channel for channel in topology.channels}
    for router in range(n):
        for terminal in range(n):
            if router == terminal:
                continue
            following, _ = ring_next_router(router, terminal, n)
            channel = channels[parents.route.entries[
                (RING_DATELINE, router, terminal)]]
            if (channel.dst_router != following
                    or channel.src_router != router):
                raise SemanticLoss(
                    "canonical route is not the native ring minimal hop")
    return n


def dateline_half(source_router: int, destination: int) -> int:
    """The VC half a flow occupies, from its INJECTION router.

    The fork sets ``ph`` once, at the routing decision that turns into the
    ring dimension, and keeps it for every later hop (the in-dimension
    branch only flips the output port). The half is a flow property; using
    the current router here would invent a crossing on every wrapping flow.
    """
    return ring_dateline_partition(source_router, destination)


def legal_hops(router: int, terminal: int, n: int) -> tuple[tuple[int, int], ...]:
    """Every (next router, native output port) the tie may legally produce.

    Non-diametral flows have exactly one; a diametral flow has two, one per
    face of the fork's ``RandomInt(1)``.
    """
    following, direction = ring_next_router(router, terminal, n)
    hops = [(following, direction)]
    if n % 2 == 0 and (terminal - router) % n == n // 2:
        mirror = (router - 1) % n
        hops.append((mirror, 1))
    return tuple(hops)


def expected_rows(topology) -> tuple[tuple, tuple, tuple]:
    return expected_rows_for(len(topology.routers))


def expected_rows_for(n: int) -> tuple[tuple, tuple, tuple]:
    """(deterministic hop rows, deterministic port rows, diametral pairs).

    The deterministic tables carry only the flows the hardware has no
    freedom over, so the shared strict comparison keeps its full strength;
    the diametral pairs are returned separately because their obligation is
    membership in a two-element legal set, which a single row cannot state.
    """
    rows, ports, ties = [], [], []
    for router in range(n):
        for terminal in range(n):
            if router == terminal:
                continue
            options = legal_hops(router, terminal, n)
            if len(options) > 1:
                ties.append((router, terminal, options))
                continue
            (following, port), = options
            rows.append((router, terminal, following))
            ports.append((router, terminal, port))
    return tuple(rows), tuple(ports), tuple(ties)


def verify_union_table(*, union, n: int) -> dict:
    """Compare the producer's legal-choice union with the model's law.

    Two claims, both total over the fabric:

    * every router/destination pair is present, and the producer never names
      a hop outside the model's legal set (soundness);
    * a pair has MORE than one outcome only when the ring has an exact
      antipode — i.e. the midpoint tie is the only nondeterminism the
      hardware has, which is what makes the deterministic rows usable at
      full strength.

    A diametral pair that the probes happened to resolve one way is not a
    failure: the model declares both faces legal and the deadlock proof
    covers both, so the union is evidence of legality, not a demand that a
    coin land on both sides within a finite number of probes.
    """
    from .booksim_execution import BookSimExecutionError
    deterministic = 0
    ties = 0
    missing = []
    for router in range(n):
        for terminal in range(n):
            observed = union.get((router, terminal))
            if observed is None:
                missing.append((router, terminal))
                continue
            if router == terminal:
                continue
            options = legal_hops(router, terminal, n)
            allowed = set(options)
            for row in observed:
                if row not in allowed:
                    raise BookSimExecutionError(
                        f"producer executed first hop {row} for "
                        f"(router,dst)=({router},{terminal}), which the ring "
                        f"law does not permit {sorted(allowed)}")
            if len(options) == 1:
                if observed != options:
                    raise BookSimExecutionError(
                        f"(router,dst)=({router},{terminal}) is deterministic "
                        f"but the producer's union is {observed}, not "
                        f"{options}: the tie is not the only nondeterminism")
                deterministic += 1
            else:
                if len(observed) > 2:
                    raise BookSimExecutionError(
                        f"diametral pair ({router},{terminal}) produced "
                        f"{len(observed)} distinct first hops; a midpoint tie "
                        f"has two faces")
                ties += 1
    if missing:
        raise BookSimExecutionError(
            f"union dump is missing {len(missing)} router/destination pairs, "
            f"starting {missing[:3]}: the table is incomplete")
    return {"pairs": deterministic + ties, "deterministic_pairs": deterministic,
            "diametral_pairs": ties, "endpoints": n}


def verify_runtime_halves(text: str, *, endpoint_count: int) -> dict:
    """Prove the executed hops, direction, ports and VC halves from the dump.

    Every executed route computation must name a legal ring direction for its
    flow, enter through the injection port on its first hop and through the
    opposite port of the previous hop thereafter, and run in the single VC of
    the dateline half its flow occupies. The midpoint tie must resolve to one
    legal direction and stay there for the whole packet: a flit that changes
    direction is not a minimal ring traversal.
    """
    from .booksim_execution import BookSimExecutionError
    n = endpoint_count
    injection_port = 2  # kcube: 2 output ports per dimension, one dimension
    last_output: dict[int, int] = {}
    directions: dict[int, tuple[int, int]] = {}
    seen: dict[int, tuple[int, int]] = {}
    rows = ties = 0
    halves = [0, 0]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 10:
            raise BookSimExecutionError(
                f"native route observation row is not the 10-field ABI: "
                f"{line!r}")
        try:
            flit, src, dest, router, inp, _invc, out, vc_begin, vc_end, _ph = (
                int(value) for value in fields)
        except ValueError:
            raise BookSimExecutionError(
                f"native route observation row is not integral: {line!r}"
            ) from None
        if not (0 <= src < n and 0 <= dest < n):
            raise BookSimExecutionError(
                f"native route observation names terminal {src}->{dest} "
                f"outside the attached {n}")
        if router == dest:
            # Ejection is decided by the same function; it is not a hop, and
            # the data flit's terminal delivery is the completion gate.
            continue
        options = legal_hops(router, dest, n)
        ports = {port for _next_router, port in options}
        if out not in ports:
            raise BookSimExecutionError(
                f"executed ring hop at router {router} toward {dest} used "
                f"port {out}, which no legal direction provides {sorted(ports)}")
        if len(ports) == 2:
            ties += 1
        half = dateline_half(src, dest)
        if (vc_begin, vc_end) != (half, half):
            raise BookSimExecutionError(
                f"executed ring flow {src}->{dest} ran hop {router}->{out} "
                f"in VC range {vc_begin}..{vc_end}, not the dateline half "
                f"{half} of its flow")
        previous_output = last_output.get(flit)
        if previous_output is None:
            if inp != injection_port:
                raise BookSimExecutionError(
                    f"flit {flit}'s first observed routing decision at router "
                    f"{router} entered on port {inp}, not the injection port "
                    f"{injection_port}")
        elif inp != (previous_output ^ 1):
            raise BookSimExecutionError(
                f"flit {flit} entered router {router} on port {inp} after "
                f"leaving on port {previous_output}: the fork flips the port "
                f"within a dimension, so this is not one ring traversal")
        established = directions.get(flit)
        if established is None:
            directions[flit] = (out, router)
        elif established[0] != out:
            raise BookSimExecutionError(
                f"flit {flit} changed ring direction at router {router} "
                f"(port {out} after port {established[0]} at router "
                f"{established[1]}): a minimal ring traversal has one "
                f"direction")
        half_half = seen.setdefault(flit, (src, dest))
        if half_half != (src, dest):
            raise BookSimExecutionError(
                f"flit {flit} is observed toward two flows {half_half} and "
                f"{(src, dest)}")
        last_output[flit] = out
        halves[half] += 1
        rows += 1
    if rows == 0:
        raise BookSimExecutionError(
            "native route observation dump carries no executed rows")
    return {"rows": rows, "diametral_rows": ties, "flits": len(last_output),
            "halves": halves, "endpoints": endpoint_count}
