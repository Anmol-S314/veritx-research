"""Native Tree4 projection: exact geometry, leaf terminals, NCA choice union.

Tree4 is a *choice-valued* fabric: a root picks one of the two middles that
serve the destination's group, a middle picks one of the four roots, and a
leaf picks one of its two parents. The fork draws those with a real
``RandomInt``, so a single-row first-hop table cannot describe the fabric.
Two evidence sets prove it instead:

* the static legal-choice UNION (``routing_dump_choice_probes > 0``) proves
  the set of hops the router may take for every (router, terminal) pair;
* the runtime route-compute dump proves which hops the simulator actually
  executed, that they are inside that union, and that every flow follows
  the climb-then-descend discipline the law implies.
"""
from veritx_dse.core.route_artifact import TREE4_NCA, TREE4_NCA_DEFINITION
from veritx_dse.model.topology_intent import Tree4Intent
from veritx_dse.model.tree4_net import (
    TERMINALS, materialize_tree4, router_level_position,
    tree4_legal_ports, tree4_next_router, tree4_native_router_id,
    tree4_terminal_location, tree4_terminal_of_seat,
)
from veritx_dse.model.topology_artifact import MaterializedFamily
from .booksim_projection import (
    BookSimProfile, ConfigRead, ParameterOwner as Owner, SemanticLoss,
    _AUDIT, _multi_class_audit, _qualify_point_to_point,
)

PROFILE_ID = "CERTIFIED_BOOKSIM_TREE4_NCA_V1"
#: A root has a two-face coin, a middle has FOUR (`RandomInt(gK-1)` is
#: inclusive in this fork) and a leaf has two. Eight probes leave a four-face
#: coin uncovered on real pairs, so this profile pins the count that reaches
#: the full union instead of pretending a sample is a table.
CHOICE_PROBES = 64
OBSERVATION_FILE = "native_route_observations.txt"
LOWERER_VERSION = "TREE4NCA/1"


def _tree4_audit() -> tuple[ConfigRead, ...]:
    """The shared audit re-pathed for the native Tree4.

    `tree4` is its own BookSim network (four roots, redundant upward links),
    so the routed knobs come from that source rather than from the anynet
    replica; the two evidence knobs are declared because this fabric cannot
    be certified from a single-row table.
    """
    rows: list[ConfigRead] = []
    for row in _AUDIT:
        if row.name == "network_file":
            continue
        if row.name == "topology":
            rows.append(ConfigRead(
                "topology", Owner.CANONICAL, "networks/network.cpp", "tree4",
                note="native Tree4 render: the four-root redundant tree, "
                     "not the balanced k-ary `tree4` preset graph"))
            continue
        rows.append(row)
    for name in ("k", "n"):
        rows.append(ConfigRead(
            name, Owner.DERIVED, "networks/tree4.cpp", 4 if name == "k" else 3,
            note="PINNED by the native construction: radix 4 over three "
                 "levels (4 roots, 8 middles, 16 leaves)"))
    rows.append(ConfigRead(
        "routing_dump_choice_probes", Owner.BACKEND_PROFILE,
        "networks/network.cpp", CHOICE_PROBES,
        note="PINNED probes per (router,dst): the middle level picks among "
             "FOUR roots, so a small probe count samples the union instead "
             "of reaching it; more than 8 distinct outcomes is still "
             "refused as adaptive"))
    rows.append(ConfigRead(
        "native_route_observation_file", Owner.DERIVED, "routefunc.cpp",
        note="mandatory executed route-compute evidence: a first-hop union "
             "cannot show which parent the run actually took"))
    return tuple(rows)


PROFILE = BookSimProfile(
    PROFILE_ID,
    "booksim2-fork+tree4-nca-upward-choice/v1+multi-class/v1",
    _multi_class_audit(_tree4_audit()))
SEMANTICS_VERSION = PROFILE.semantics_version


def qualify(parents, *, multi_class=False):
    """Prove every prerequisite of the native Tree4 envelope, or refuse."""
    topology = parents.topology
    if topology.family is not MaterializedFamily.TREE4_NATIVE:
        raise SemanticLoss(
            "the Tree4 envelope is certified for tree4_native only, got "
            f"{topology.family.value}")
    controls = {channel.width_bits for channel in topology.channels}
    if len(controls) != 1:
        raise SemanticLoss("native Tree4 requires uniform channel widths")
    expected = materialize_tree4(Tree4Intent(4, 3),
                                 width_bits=next(iter(controls)))
    if topology.canonical_dict() != expected.canonical_dict():
        raise SemanticLoss(
            "native Tree4 geometry/ports/seats differ from its construction "
            "(four roots, 8 middles, 16 leaves with 4 seats each)")
    if len(parents.attachment.endpoints) != TERMINALS:
        raise SemanticLoss(
            f"native Tree4 requires the complete {TERMINALS}-terminal "
            f"attachment, got {len(parents.attachment.endpoints)}")
    for endpoint in parents.attachment.endpoints:
        if (endpoint.router_id, endpoint.port_id) != tree4_terminal_location(
                endpoint.endpoint_id):
            raise SemanticLoss(
                "native Tree4 terminal attachment differs from its leaf seat "
                "law")
    if parents.route.routing_classes != (TREE4_NCA_DEFINITION,):
        raise SemanticLoss(
            "Tree4 requires the sealed TREE4_NCA algorithm and parameters "
            "(a choice union, not a single-parent NCA)")
    _qualify_point_to_point(
        parents, routing_class=TREE4_NCA, multi_class=multi_class)
    if parents.vc_resource.vc_count < 1:
        raise SemanticLoss("Tree4 NCA needs at least one VC")
    channels = {channel.channel_id: channel for channel in topology.channels}
    for router in range(len(topology.routers)):
        for terminal in range(TERMINALS):
            first, port = legal_hops(topology, router, terminal)[0]
            if first is None:
                if tree4_terminal_location(terminal)[0] != router:
                    raise SemanticLoss(
                        "canonical route ejects at a leaf that does not own "
                        "the terminal")
                continue
            channel = channels[parents.route.entries[(TREE4_NCA, router,
                                                     first)]]
            if (channel.src_router, channel.dst_router) != (router, first):
                raise SemanticLoss(
                    "canonical route is not a legal native Tree4 hop")
            if channel.src_port != port:
                raise SemanticLoss(
                    "canonical route uses a port outside the native port law")
    return topology


def model_topology():
    """The pinned native Tree4 construction the certification is about."""
    return materialize_tree4(Tree4Intent(4, 3))


def pinned_geometry(config_values) -> None:
    """Refuse a prepared config that is not the certified Tree4 geometry."""
    from .booksim_execution import BookSimExecutionError
    for name, want in (("k", 4), ("n", 3)):
        got = config_values.get(name)
        try:
            got = int(got)
        except (TypeError, ValueError):
            pass
        if got != want:
            raise BookSimExecutionError(
                f"native Tree4 is certified for {name}={want}, prepared "
                f"config says {name}={got!r}")


def legal_hops(topology, router, terminal):
    """Every (next router or None, native output port) NCA can choose."""
    return tuple((tree4_next_router(router, port), port)
                 for port in tree4_legal_ports(router, terminal))


def expected_rows(topology):
    """(deterministic hop rows, deterministic port rows, choice pairs).

    Only flows the hardware has no freedom over go into the strict
    single-row comparison; a pair with a real coin is returned separately,
    because its obligation is membership in a legal set, which one row
    cannot state.
    """
    rows, ports, choices = [], [], []
    for router in range(len(topology.routers)):
        for terminal in range(TERMINALS):
            options = legal_hops(topology, router, terminal)
            if len(options) > 1:
                choices.append((router, terminal, options))
                continue
            following, port = options[0]
            native_next = (router if following is None else
                           tree4_native_router_id(topology, following))
            rows.append((router, terminal, native_next))
            ports.append((router, terminal, port))
    return tuple(rows), tuple(ports), tuple(choices)


def verify_union_table(*, union, topology) -> dict:
    """Compare the producer's legal-choice union with the model's law.

    Both directions are claims, so both are checked:

    * soundness — the producer never names a port the law does not offer
      for that (router, terminal), and it covers every pair;
    * completeness — where the law is deterministic the producer must report
      exactly that hop, so no undeclared nondeterminism exists; and across
      the fabric every legal face must be observed at least once, so the
      model cannot claim a face the producer never shows.

    One coin is not required to land on every face inside a single dump: the
    deadlock proof covers all faces, so the union is evidence of legality,
    not a demand that a finite sample be exhaustive per pair. The profile
    still pins `CHOICE_PROBES` high enough that the four-face middle choice
    is reached on every pair in practice.
    """
    from .booksim_execution import BookSimExecutionError
    deterministic = choice_pairs = 0
    missing = []
    observed_ports: dict[int, set] = {}
    for router in range(len(topology.routers)):
        for terminal in range(TERMINALS):
            observed = union.get((router, terminal))
            if observed is None:
                missing.append((router, terminal))
                continue
            # The dump's next_router column is BookSim's internal id, and an
            # ejection port names the traffic manager rather than a router,
            # so the law is compared through the PORT (one numbering in both)
            # and the next-id only where a router exists.
            allowed = {}
            for following, port in legal_hops(topology, router, terminal):
                allowed[port] = (None if following is None else
                                 tree4_native_router_id(topology, following))
            for native_next, port in observed:
                if port not in allowed:
                    raise BookSimExecutionError(
                        f"producer realised first hop (next={native_next}, "
                        f"port={port}) for (router,dst)=({router},"
                        f"{terminal}), which the Tree4 NCA law does not "
                        f"permit (ports {sorted(allowed)})")
                if allowed[port] is not None and native_next != allowed[port]:
                    raise BookSimExecutionError(
                        f"producer realised port {port} toward router "
                        f"{native_next} for (router,dst)=({router},"
                        f"{terminal}), but the port law leads to "
                        f"{allowed[port]}")
            ports_seen = {port for _native, port in observed}
            observed_ports.setdefault(router, set()).update(ports_seen)
            if len(allowed) == 1:
                if ports_seen != set(allowed):
                    raise BookSimExecutionError(
                        f"(router,dst)=({router},{terminal}) is "
                        f"deterministic under the law but the producer's "
                        f"union names ports {sorted(ports_seen)}, not "
                        f"{sorted(allowed)}: nondeterminism the class does "
                        "not declare")
                deterministic += 1
            else:
                if len(ports_seen) > len(allowed):
                    raise BookSimExecutionError(
                        f"(router,dst)=({router},{terminal}) produced "
                        f"{len(ports_seen)} distinct first hops but the law "
                        f"offers {len(allowed)}")
                choice_pairs += 1
    if missing:
        raise BookSimExecutionError(
            f"union dump is missing {len(missing)} router/destination "
            f"pairs, starting {missing[:3]}: the table is incomplete")
    uncovered = []
    for router in range(len(topology.routers)):
        faces = observed_ports.get(router, set())
        for terminal in range(TERMINALS):
            options = legal_hops(topology, router, terminal)
            if len(options) < 2:
                continue
            unseen = [option for option in options if option[1] not in faces]
            if unseen:
                uncovered.append((router, terminal, unseen, sorted(faces)))
    if uncovered:
        raise BookSimExecutionError(
            f"{len(uncovered)} legal Tree4 choice(s) were never realised "
            f"anywhere in the union dump, starting {uncovered[:2]}: the "
            "model would otherwise claim a face the producer never shows")
    return {"pairs": deterministic + choice_pairs,
            "deterministic_pairs": deterministic,
            "choice_pairs": choice_pairs,
            "terminals": TERMINALS,
            "routers": len(topology.routers),
            "choice_probes": CHOICE_PROBES}


def verify_runtime(text: str, *, topology, vc_count: int) -> dict:
    """Prove the executed hops, injection seats, VCs and discipline.

    Every executed decision must be legal for its flow, a flit's first
    decision must enter through the seat port of its source terminal, every
    hop must use the full VC range the fork assigns to ANY_TYPE, and a
    flow's level sequence may only climb (toward the roots) before it
    descends: a climb after a descent is not a Tree4 traversal. Ejection is
    only legal at the seat that owns the destination terminal.
    """
    from .booksim_execution import BookSimExecutionError
    if vc_count < 1:
        raise BookSimExecutionError("Tree4 needs at least one VC to verify")
    native_to_canonical = {tree4_native_router_id(topology, router): router
                           for router in range(len(topology.routers))}
    levels: dict[int, list[int]] = {}
    last_output: dict[int, int] = {}
    flows: dict[int, tuple[int, int]] = {}
    rows = ejections = 0
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
            flit, src, dest, native, inp, _invc, out, vc_begin, vc_end, _ph = (
                int(value) for value in fields)
        except ValueError:
            raise BookSimExecutionError(
                f"native route observation row is not integral: {line!r}"
            ) from None
        if not 0 <= src < TERMINALS or not 0 <= dest < TERMINALS:
            raise BookSimExecutionError(
                f"native route observation names terminal {src}->{dest} "
                f"outside the attached {TERMINALS}")
        router = native_to_canonical.get(native)
        if router is None:
            raise BookSimExecutionError(
                f"native route observation names router {native}, which is "
                "not a native Tree4 router id")
        level, _position = router_level_position(router)
        options = legal_hops(topology, router, dest)
        ports = {port for _next, port in options}
        if out not in ports:
            raise BookSimExecutionError(
                f"executed Tree4 hop at router {router} toward {dest} used "
                f"port {out}, which no legal choice provides {sorted(ports)}")
        if (vc_begin, vc_end) != (0, vc_count - 1):
            raise BookSimExecutionError(
                f"executed Tree4 hop at router {router} used VC range "
                f"{vc_begin}..{vc_end}, not the full range "
                f"{0}..{vc_count - 1} the fork assigns to ANY_TYPE")
        established = flows.get(flit)
        if established is None:
            flows[flit] = (src, dest)
            if inp != src % 4:
                raise BookSimExecutionError(
                    f"flit {flit}'s first decision at router {router} "
                    f"entered on port {inp}, not the seat port {src % 4} of "
                    f"its source terminal {src}")
        elif established != (src, dest):
            raise BookSimExecutionError(
                f"flit {flit} is observed on two flows {established} and "
                f"{(src, dest)}")
        sequence = levels.setdefault(flit, [level])
        if len(sequence) > 1 and sequence[-1] != level:
            sequence.append(level)
        following = tree4_next_router(router, out)
        if following is None:
            ejections += 1
            terminal = tree4_terminal_of_seat(router, out)
            if terminal != dest:
                raise BookSimExecutionError(
                    f"flit {flit} ejected terminal {terminal} at router "
                    f"{router} port {out}, but its destination is {dest}")
        last_output[flit] = out
        rows += 1
    if rows == 0:
        raise BookSimExecutionError(
            "native route observation dump carries no executed rows")
    violations = 0
    for flit, sequence in levels.items():
        turned = False
        for before, after in zip(sequence, sequence[1:]):
            if after < before:
                if turned:
                    violations += 1
            elif after > before:
                turned = True
    if violations:
        raise BookSimExecutionError(
            f"{violations} flow(s) climbed toward the roots after descending:"
            " the Tree4 law only permits climb-then-descend")
    return {"rows": rows, "flits": len(levels), "ejections": ejections,
            "vc_range": [0, vc_count - 1], "terminals": TERMINALS}
