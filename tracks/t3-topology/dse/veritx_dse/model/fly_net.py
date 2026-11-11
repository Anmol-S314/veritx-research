"""Native k-ary n-fly (butterfly) construction, k=4, n=3, 64 terminals.

This is BookSim's ``fly`` network, not any of the structured/AnyNet presets:
``KNFly::_ComputeSize``/``_BuildNet`` (``networks/fly.cpp``) build ``n``
stages of ``k**(n-1)`` routers and ``(n-1) * k**n`` directed channels, and
``dest_tag_fly`` (``routefunc.cpp``) routes by destination digit, with NO
adaptive choice. The port law below is a transcription of the builder's
``_InChannel`` arithmetic; it is not an invention of this module.

Two facts make the Fly structurally different from every fabric already
materialized here, and both are modelled explicitly rather than flattened:

1. A terminal injects at its STAGE-0 router and ejects at its STAGE-2
   router. Those are different routers in general, so an attachment is not
   one bidirectional seat; it is an ingress location plus an egress
   location.
2. A router's terminal-facing ports are the SAME port indices as its
   network-facing ports (there is no separate concentration block). Stage-0
   routers therefore own ingress-only slots, stage-2 routers egress-only
   slots, and the middle stage has neither.

Terminal numbering: BookSim injects terminal ``t`` on injection channel
``t``, which lands on stage-0 router ``t // k`` at port ``t % k``; it ejects
from stage-2 router ``t // k`` at port ``t % k``. Router ids are BookSim's
own: ``stage * k**(n-1) + addr``.
"""

from __future__ import annotations

from .topology_artifact import (
    DirectedChannel,
    MaterializedFamily,
    Router,
    TopologyArtifact,
    TopologyError,
    _DEFAULT_LINK_LATENCY_CYCLES,
    _DEFAULT_LINK_WIDTH_BITS,
    _as_int,
)

K = 4
LEVELS = 3
PER_STAGE = K ** (LEVELS - 1)          # 16 routers per stage
ROUTER_COUNT = LEVELS * PER_STAGE       # 48 routers
TERMINALS = K ** LEVELS                 # 64 terminals
STAGES = tuple(range(LEVELS))


def _check(k: int, n: int) -> None:
    _as_int("k", k, minimum=2)
    _as_int("n", n, minimum=1)
    if k != K or n != LEVELS:
        raise TopologyError(
            f"the native fly construction is pinned to k={K}, n={LEVELS} "
            f"(4-ary 3-stage butterfly); got k={k}, n={n}")


def router_id(stage: int, addr: int) -> int:
    """Dense router id used by the artifact AND by BookSim's node counter."""
    _as_int("stage", stage, minimum=0)
    _as_int("addr", addr, minimum=0)
    if not 0 <= stage < LEVELS or not 0 <= addr < PER_STAGE:
        raise TopologyError(f"no router at stage {stage}, addr {addr}")
    return stage * PER_STAGE + addr


def router_stage(r: int) -> int:
    _as_int("router", r, minimum=0)
    if not 0 <= r < ROUTER_COUNT:
        raise TopologyError(f"router {r} is outside the fabric")
    return r // PER_STAGE


def router_addr(r: int) -> int:
    return r % PER_STAGE


def _wiring() -> dict[tuple[int, int, int], tuple[int, int]]:
    """(stage, addr, out_port) -> (dst_router, dst_port), per fly.cpp.

    ``_InChannel(stage, addr, port)`` picks digit ``n-stage-1`` of ``addr``
    (``zero``), moves it to the port position and shifts ``port`` into that
    digit. Transcribing the inverse of that arithmetic gives the source of
    every inter-stage channel; the result was checked to be a perfect
    permutation over all ``(n-1) * k**n`` channels.
    """
    out: dict[tuple[int, int, int], tuple[int, int]] = {}
    for stage in range(1, LEVELS):
        shift = K ** (LEVELS - stage - 1)
        for addr in range(PER_STAGE):
            for port in range(K):
                zero = (addr // shift) % K
                in_addr = addr - zero * shift + port * shift
                in_port = zero
                src = (stage - 1, in_addr, in_port)
                if src in out:
                    raise TopologyError(
                        "fly wiring is not a permutation: two sources feed "
                        f"router {router_id(stage, addr)} port {port}")
                out[src] = (router_id(stage, addr), port)
    if len(out) != (LEVELS - 1) * TERMINALS:
        raise TopologyError("fly wiring does not cover every channel")
    return out


WIRING: dict[tuple[int, int, int], tuple[int, int]] = _wiring()


def next_router(r: int, port: int) -> int | None:
    """Router reached by output `port` of router `r`; None means "ejects"."""
    stage, addr = router_stage(r), router_addr(r)
    _as_int("port", port, minimum=0)
    if not 0 <= port < K:
        raise TopologyError(f"router {r} has no output port {port}")
    if stage == LEVELS - 1:
        return None
    dst, _ = WIRING[(stage, addr, port)]
    return dst


def next_port(r: int, port: int) -> int | None:
    stage, addr = router_stage(r), router_addr(r)
    if stage == LEVELS - 1:
        return None
    return WIRING[(stage, addr, port)][1]


def terminal_ingress_location(t: int) -> tuple[int, int]:
    """Stage-0 router and port a terminal injects through."""
    _as_int("terminal", t, minimum=0)
    if not 0 <= t < TERMINALS:
        raise TopologyError(f"terminal {t} is outside the fabric")
    return router_id(0, t // K), t % K


def terminal_egress_location(t: int) -> tuple[int, int]:
    """Stage-2 router and port a terminal ejects through."""
    _as_int("terminal", t, minimum=0)
    if not 0 <= t < TERMINALS:
        raise TopologyError(f"terminal {t} is outside the fabric")
    return router_id(LEVELS - 1, t // K), t % K


def terminal_of_ingress(r: int, port: int) -> int:
    if router_stage(r) != 0:
        raise TopologyError(
            f"router {r} is not a stage-0 router; terminals only inject there")
    return router_addr(r) * K + port


def terminal_of_egress(r: int, port: int) -> int:
    if router_stage(r) != LEVELS - 1:
        raise TopologyError(
            f"router {r} is not a stage-{LEVELS - 1} router; terminals only "
            "eject there")
    return router_addr(r) * K + port


EGRESS_ROUTERS: tuple[int, ...] = tuple(
    router_id(LEVELS - 1, addr) for addr in range(PER_STAGE))


def egress_port(r: int, egress_router: int) -> int | None:
    """Port a flit at router `r` uses to head toward an ejection router.

    Independent of WHICH terminal ejects there: ``dest_tag_fly`` only needs
    the destination's digit for the current stage, and every terminal sharing
    an egress router shares those digits. ``None`` means this router cannot
    make progress toward that ejection point (the last stage, or a middle
    stage that is not on the destination's digit class).
    """
    _as_int("egress_router", egress_router, minimum=0)
    if egress_router not in EGRESS_ROUTERS:
        raise TopologyError(
            f"router {egress_router} is not a stage-{LEVELS - 1} ejection "
            "router")
    stage = router_stage(r)
    target = router_addr(egress_router)
    if stage == LEVELS - 1:
        return None
    if stage == 1:
        if router_addr(r) // K != target // K:
            # dest_tag_fly only forwards flows whose destination digit for
            # this stage matches the one the router was reached through.
            return None
        return target % K
    return target // K


def legal_ports(r: int, terminal: int) -> tuple[int, ...]:
    """The single port a flit at router `r` must use, per ``dest_tag_fly``.

    ``dest_tag_fly`` divides the destination by ``gK`` until the flit is one
    stage from the end, then takes ``dest % gK``. That yields exactly one
    port per (router, destination) -- there is no adaptive face here, which
    is why this fabric needs no choice union.
    """
    stage = router_stage(r)
    _as_int("terminal", terminal, minimum=0)
    if not 0 <= terminal < TERMINALS:
        raise TopologyError(f"terminal {terminal} is outside the fabric")
    egress_router, egress_port_ = terminal_egress_location(terminal)
    if stage == LEVELS - 1:
        if r != egress_router:
            raise TopologyError(
                f"a flit destined for terminal {terminal} cannot be at "
                f"stage-2 router {r}; it ejects at {egress_router}")
        return (egress_port_,)
    port = egress_port(r, egress_router)
    if port is None:
        raise TopologyError(
            f"a flit at stage-1 router {r} cannot reach terminal {terminal}: "
            f"dest_tag_fly only forwards a flow whose destination digit "
            f"matches the one this router was reached through (its ejection "
            f"router is {egress_router})")
    return (port,)


def witness_path(source: int, terminal: int) -> tuple[int, ...]:
    """Router sequence a flit from `source` takes to eject at `terminal`."""
    _as_int("source", source, minimum=0)
    if not 0 <= source < ROUTER_COUNT:
        raise TopologyError(f"router {source} is outside the fabric")
    path = [source]
    r = source
    for _ in range(LEVELS):
        port = legal_ports(r, terminal)[0]
        nxt = next_router(r, port)
        if nxt is None:
            break
        path.append(nxt)
        r = nxt
    else:
        raise TopologyError(
            f"no terminating route from router {source} to terminal "
            f"{terminal}")
    egress_router, _ = terminal_egress_location(terminal)
    if r != egress_router:
        raise TopologyError(
            f"route from router {source} to terminal {terminal} ends at "
            f"router {r}, not the egress router {egress_router}")
    return tuple(path)


def native_router_id(r: int) -> int:
    """BookSim's own node id for this router.

    ``KNFly::_BuildNet`` numbers routers ``stage * k**(n-1) + addr``, which is
    already the dense id used here -- but the mapping is asserted through a
    function so a future construction cannot silently assume identity.
    """
    router_stage(r)
    return r


def materialize_fly(*, k: int = K, n: int = LEVELS,
                    width_bits: int = _DEFAULT_LINK_WIDTH_BITS,
                    latency_cycles: int = _DEFAULT_LINK_LATENCY_CYCLES
                    ) -> TopologyArtifact:
    """Materialize the 48-router, 128-channel, 64-terminal butterfly.

    Slot law: stage-0 routers own the ``k`` ingress slots (they are the only
    place a terminal can inject), stage-2 routers own the ``k`` egress slots,
    and the middle stage owns none. Channels use BookSim's own channel ids
    (``stage * k**n + addr * k + port``) and its port numbering (an
    inter-stage channel leaves port ``p`` and enters port ``zero``).
    """
    _check(k, n)
    _as_int("width_bits", width_bits, minimum=1)
    _as_int("latency_cycles", latency_cycles, minimum=0)
    routers = tuple(
        Router(
            router_id=r,
            coordinates=(router_stage(r), router_addr(r)),
            seat_capacity=(K if router_stage(r) == 0 else 0),
            egress_seat_capacity=(K if router_stage(r) == LEVELS - 1 else 0),
        )
        for r in range(ROUTER_COUNT)
    )
    channels = tuple(
        DirectedChannel(
            channel_id=stage * TERMINALS + addr * K + port,
            src_router=router_id(stage, addr),
            src_port=port,
            dst_router=dst,
            dst_port=dst_port,
            width_bits=width_bits,
            latency_cycles=latency_cycles,
        )
        for (stage, addr, port), (dst, dst_port) in sorted(WIRING.items())
    )
    return TopologyArtifact(family=MaterializedFamily.FLY_NATIVE,
                            routers=routers, channels=channels)
