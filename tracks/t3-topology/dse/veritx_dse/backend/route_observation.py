"""veritx_dse.backend.route_observation — executed route realization (P0.10).

The canonical route is proven STATICALLY (RouteArtifact + ResolvedRoute).
This module proves the runtime routing realization: the vendored fork's
``routing_dump_file`` writes the routing function/table actually built at
network construction, and we compare it destination-by-destination against
the canonical route.

Precise claim:

    The runtime routing-function/table first-hop realization is exactly
    equivalent to the canonical route over the complete source x
    destination domain.

This is stronger than static configuration checking but narrower than
per-packet instrumentation: for mesh-DOR the dump calls the active
registered routing function for every router/destination pair after
network construction; for AnyNet it dumps the routing table AnyNet itself
uses. It does not record head flits as packets traverse the router, so it
proves deterministic first-hop routing equivalence, not observed packet
paths.

Id mapping (why this is exact, not assumed):
  * mesh-DOR: the profile qualification proves endpoint ids are dense
    0..E-1 and endpoint i attaches to router i, and the native mesh node n
    maps 1:1 to router n — so the dump's ``src_router``/``dst_node`` ARE
    the canonical router/endpoint ids;
  * AnyNet: ``render_anynet_topology`` emits ``router <id>`` / ``node <id>``
    with the canonical ids verbatim, so the same identity holds.

OWNERSHIP (Tranche 5 PHASE 2). This module is a SIMULATOR ADAPTER: it owns
(a) parsing the fork's dump format and (b) building the expected table from
the sealed canonical artifacts plus the execution node->router map. It does
NOT own route-set comparison semantics — ``core.route_artifact.
compare_first_hop_tables`` does, and this module delegates to it. Two
independent comparisons of the same science is exactly the drift this
reclamation exists to remove.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Mapping

from veritx_dse.core.artifact import canonical_bytes
from veritx_dse.core.errors import SemanticError


class RouteObservationError(ValueError, SemanticError):
    """The executed route dump is missing, malformed or divergent."""


#: the fork's first-hop dump line (networks/network.cpp, networks/anynet.cpp)
_DUMP_RE = re.compile(
    r"^src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)$")


@dataclass(frozen=True)
class RouteObservationResult:
    routing_class: str
    pairs_compared: int
    expected_sha256: str
    executed_sha256: str


def parse_route_dump(text: str) -> dict[tuple[int, int], int]:
    """Parse the fork's first-hop table; refuse malformed/duplicate rows."""
    executed: dict[tuple[int, int], int] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _DUMP_RE.match(line)
        if match is None:
            raise RouteObservationError(
                f"route dump line {line_no} is malformed: {line!r}")
        src, dst, nxt, _port = (int(g) for g in match.groups())
        key = (src, dst)
        if key in executed:
            raise RouteObservationError(
                f"route dump repeats (src_router={src}, dst_node={dst})")
        executed[key] = nxt
    if not executed:
        raise RouteObservationError("route dump is empty")
    return executed


def expected_route_rows(
        *, routing_class: str, topology: Any, route: Any,
        node_to_router: Mapping[int, int]) -> tuple[tuple[int, int, int], ...]:
    """Canonical expected first-hop table: (src_router, node, next_router).

    ``node_to_router`` is the execution node universe: mesh-DOR addresses
    every router as a node (node n -> router n); AnyNet addresses the
    attached endpoint nodes (node e -> its router). Derived only from the
    sealed canonical artifacts, never from a simulator. Refuses if the
    route artifact does not cover a required (class, src, dst) pair — a
    route proof that does not cover the fabric must not silently become an
    observation expectation.
    """
    channels = {c.channel_id: c for c in topology.channels}
    entries = route.entries
    rows: list[tuple[int, int, int]] = []
    for src in range(topology.router_count):
        for node in sorted(node_to_router):
            dst_router = node_to_router[node]
            if src == dst_router:
                next_router = src
            else:
                key = (routing_class, src, dst_router)
                channel_id = entries.get(key)
                if channel_id is None:
                    raise RouteObservationError(
                        f"RouteArtifact has no entry for "
                        f"({routing_class}, {src}, {dst_router})")
                channel = channels.get(channel_id)
                if channel is None:
                    raise RouteObservationError(
                        f"RouteArtifact entry {key} names unknown channel "
                        f"{channel_id}")
                if channel.src_router != src:
                    raise RouteObservationError(
                        f"RouteArtifact entry {key} leaves router "
                        f"{channel.src_router}, not {src}")
                next_router = channel.dst_router
            rows.append((src, node, next_router))
    return tuple(rows)


def compare_route_realization(
        *, expected_rows: tuple[tuple[int, int, int], ...],
        dump_text: str, routing_class: str = "") -> RouteObservationResult:
    """Exact destination-aware comparison of the executed first-hop table.

    Legal next-hop adjacency is already proven when ``expected_route_rows``
    is derived: every non-local expected hop is looked up as a real channel
    leaving that src router. Exact executed == expected therefore implies
    adjacency-legal hops; a divergent dump refuses.

    The VERDICT is delegated to
    ``core.route_artifact.compare_first_hop_tables`` — the one comparison
    authority. This function contributes the dump parsing, the id mapping
    and the evidence digests, and converts a DIVERGENT verdict into the
    typed refusal this adapter's callers expect.
    """
    from veritx_dse.core.route_artifact import compare_first_hop_tables

    executed = parse_route_dump(dump_text)
    expected = {(src, dst): next_router
                for src, dst, next_router in expected_rows}

    report = compare_first_hop_tables(expected, executed)
    if report["status"] != "COMPARABLE":
        mismatched = report["mismatched"]
        if mismatched:
            shown = [((m["src"], m["dst"]), m["artifact_next_hop"],
                      m["executed_next_hop"]) for m in mismatched[:3]]
            raise RouteObservationError(
                "executed route realization diverges from the RouteArtifact "
                f"in {len(mismatched)} entries, e.g. {shown} — the fabric "
                "is NOT executed as declared")
        raise RouteObservationError(
            "executed route dump coverage differs from the canonical route "
            f"(missing {[(m['src'], m['dst']) for m in report['missing_in_executed']][:3]}, "
            f"extra {[(m['src'], m['dst']) for m in report['extra_in_executed']][:3]})")

    def _digest(rows: Mapping[tuple[int, int], int]) -> str:
        return hashlib.sha256(canonical_bytes(
            [[r, e, rows[(r, e)]] for r, e in sorted(rows)]).decode()
            .encode()).hexdigest()

    return RouteObservationResult(
        routing_class=routing_class,
        pairs_compared=len(expected),
        expected_sha256=_digest(expected),
        executed_sha256=_digest(executed))


__all__ = [
    "RouteObservationError", "RouteObservationResult",
    "compare_route_realization", "expected_route_rows", "parse_route_dump",
]
