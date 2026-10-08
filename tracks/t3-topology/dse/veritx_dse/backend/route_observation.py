"""veritx_dse.backend.route_observation — executed route realization (P0.10).

Rationale: docs/decisions/modules/backend.md
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

#: Route-dump ABI version implemented by this parser. The fork emits the
#: four fixed fields below; anything after them is a whitespace-separated
#: sequence of `key value` trailer pairs (today: `drop`, `lanes`). A future
#: fork may append trailer pairs without breaking this parser — unknown
#: keys are accepted and ignored for the first-hop table. A dangling key
#: (odd token count) is malformed: a truncated trailer is not a guessable
#: trailer. Bump the version when the fixed fields change, never for a
#: trailer addition.
ROUTE_DUMP_ABI_VERSION = 1
#: Trailer keys the fork emits today. Unknown keys are still accepted (see
#: above); this set documents what has been observed, not what is allowed.
#: ``drop`` names the tap on a multidrop port; ``vc_start``/``vc_end`` are
#: the VC range that tap's eligibility resolves to. Those three were added
#: for shared-wire fabrics and are emitted ONLY for the multidrop
#: topologies, so a point-to-point dump never grows a trailer and its
#: recorded identity cannot move.
ROUTE_DUMP_KNOWN_TRAILERS = frozenset({"drop", "lanes", "vc_start",
                                       "vc_end"})
_DUMP_RE = re.compile(
    r"^src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)"
    r"((?:\s+\S+)*)$")

@dataclass(frozen=True)
class RouteDumpRow:
    """One realized first hop, with any trailers the fork attached.

    A shared-wire hop is only described by all of port (the wire), drop (the
    tap on it) and the VC range that tap resolves to, so the trailers are
    modelled rather than discarded. ``drop`` is absent for a
    point-to-point row and for a shared row that was not emitted with
    trailers, so callers must not assume it exists.
    """

    src_router: int
    dst_node: int
    next_router: int
    port: int
    trailers: Mapping[str, int]

    @property
    def drop(self) -> int | None:
        return self.trailers.get("drop")

    @property
    def vc_start(self) -> int | None:
        return self.trailers.get("vc_start")

    @property
    def vc_end(self) -> int | None:
        return self.trailers.get("vc_end")

    def is_shared(self) -> bool:
        drop = self.drop
        return drop is not None and drop >= 0

_TRAILER_VALUE_RE = re.compile(r"^-?\d+$")

def parse_route_dump_rows(text: str) -> dict[tuple[int, int], RouteDumpRow]:
    """Parse the fork's first-hop table WITH its trailers, refusing junk.

    Trailer values must be integers: a trailer the fork emitted is a number,
    so a non-numeric one means the dump is not the dialect this parser
    understands. ``parse_route_dump`` is the trailers-ignored view over this
    same parse, so the two can never disagree about the first-hop table.
    """
    rows: dict[tuple[int, int], RouteDumpRow] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _DUMP_RE.match(line)
        if match is None:
            raise RouteObservationError(
                f"route dump line {line_no} is malformed: {line!r}")
        tokens = match.group(5).split()
        if len(tokens) % 2:
            raise RouteObservationError(
                f"route dump line {line_no} has a dangling trailer key: "
                f"{line!r}")
        trailers: dict[str, int] = {}
        for i in range(0, len(tokens), 2):
            key, value = tokens[i], tokens[i + 1]
            if not _TRAILER_VALUE_RE.match(value):
                raise RouteObservationError(
                    f"route dump line {line_no} trailer {key!r} has "
                    f"non-integer value {value!r}")
            trailers[key] = int(value)
        src, dst = int(match.group(1)), int(match.group(2))
        key = (src, dst)
        if key in rows:
            raise RouteObservationError(
                f"route dump repeats (src_router={src}, dst_node={dst})")
        rows[key] = RouteDumpRow(
            src_router=src, dst_node=dst, next_router=int(match.group(3)),
            port=int(match.group(4)), trailers=trailers)
    if not rows:
        raise RouteObservationError("route dump is empty")
    return rows

@dataclass(frozen=True)
class RouteObservationResult:
    routing_class: str
    pairs_compared: int
    expected_sha256: str
    executed_sha256: str

def parse_route_dump(text: str) -> dict[tuple[int, int], int]:
    """Parse the fork's first-hop table; refuse malformed/duplicate rows.

    Implements route-dump ABI v1 (ROUTE_DUMP_ABI_VERSION): four fixed
    fields plus extensible `key value` trailer pairs. Trailer content is
    validated as pairs but not interpreted — this table is the first-hop
    relation, and a dropped tap still records the next router it leaves
    by. Read fields by index so trailer additions cannot break the table.
    """
    # One parser, not two: the trailers-ignored view is derived from the
    # trailers-aware parse, so the first-hop table can never differ between
    # the two readings of the same dump.
    return {key: row.next_router
            for key, row in parse_route_dump_rows(text).items()}

def expected_route_rows(
        *, routing_class: str, topology: Any, route: Any,
        node_to_router: Mapping[int, int]) -> tuple[tuple[int, int, int], ...]:
    """Canonical expected first-hop table: (src_router, node, next_router).

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.model.route_artifact_v3 import (
        RouteArtifactV3, ShapePolicyRoute,
    )
    from veritx_dse.model.srota_rank_route import RankPolicyRoute
    from veritx_dse.model.gec_hybrid_route import GecHybridRoute
    if isinstance(route, (ShapePolicyRoute, RankPolicyRoute, GecHybridRoute)):
        # An ADAPTIVE route has several realizable first hops per pair, so
        # the expected table is the SET of them. Comparisons against it must
        # be membership, not equality: the run picks one.
        if route.routing_class != routing_class:
            raise RouteObservationError(
                f"route declares class {route.routing_class!r}, not the "
                f"expected {routing_class!r}")
        rows = {(src, node, decision.next_router)
                for (src, node), options in route.choices.items()
                for decision in options}
        return tuple(sorted(rows))
    if isinstance(route, RouteArtifactV3):
        # A v3 decision already names the landing router: `next_router` IS
        # the first-hop answer, because a shared wire does not determine
        # where a packet leaves it. There is nothing to derive from a
        # channel table, and a mismatch here would mean the executed
        # realization disagrees with the certified route.
        if route.routing_class != routing_class:
            raise RouteObservationError(
                f"route declares class {route.routing_class!r}, not the "
                f"expected {routing_class!r}")
        return tuple(
            (src, node, decision.next_router)
            for (src, node), decision in sorted(route.decisions.items()))
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

def compare_hybrid_runtime_choices(*, expected: tuple[tuple[Any, ...], ...],
                                   text: str) -> dict[str, Any]:
    """Check real route-compute observations, not a zero-credit static probe.

    These rows record selector inputs and eligible outputs before VC
    allocation. They are not an allocator/fairness or complete flit-path log.
    """
    from veritx_dse.model.gec_hybrid_route import select_gec_hybrid_candidate
    admitted = set(expected)
    if not admitted:
        raise RouteObservationError("hybrid expected candidate set is empty")
    count = 0
    modes: dict[str, int] = {"mesh": 0, "mecs": 0}
    nonzero = 0
    for line_no, line in enumerate(text.splitlines(), 1):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        fields = line.split()
        if len(fields) != 14:
            raise RouteObservationError(f"hybrid observation {line_no} needs 14 fields")
        try:
            src, dest, ingress, mesh_credit, mecs_credit, hops, mesh_cost, mecs_cost = map(int, fields[:8])
            port, tap, vc_start, vc_end, phase = map(int, fields[9:])
        except ValueError as exc:
            raise RouteObservationError(f"hybrid observation {line_no} has non-integer fields") from exc
        if min(src, dest, ingress, mesh_credit, mecs_credit) < 0 or hops < 1:
            raise RouteObservationError(f"hybrid observation {line_no} has invalid selector inputs")
        if mesh_cost != mesh_credit * hops or mecs_cost != mecs_credit:
            raise RouteObservationError(f"hybrid observation {line_no} has inconsistent costs")
        selected = select_gec_hybrid_candidate(
            mesh_used_credit=mesh_credit, mecs_used_credit=mecs_credit, mesh_hops=hops)
        if fields[8] != selected:
            raise RouteObservationError(f"hybrid observation {line_no} violates credit-cost selection")
        row = (src, dest, selected, port, tap, vc_start, vc_end, phase, hops)
        if row not in admitted:
            raise RouteObservationError(f"hybrid observation {line_no} is outside the certified candidates: {row}")
        count += 1
        modes[selected] += 1
        nonzero += int(mesh_credit > 0 or mecs_credit > 0)
    if not count:
        raise RouteObservationError("hybrid runtime observation dump is empty")
    return {"scope": "RUNTIME_ROUTE_COMPUTE_CHOICES", "observations": count,
            "selected_modes": modes, "nonzero_credit_observations": nonzero,
            "sha256": hashlib.sha256(text.encode()).hexdigest()}


def compare_route_realization(
        *, expected_rows: tuple[tuple[int, int, int], ...],
        dump_text: str, routing_class: str = "",
        adaptive: bool = False) -> RouteObservationResult:
    """Destination-aware comparison of the executed first-hop table.

    ``adaptive=False`` (the default) is an EXACT comparison: every expected
    pair must be executed with exactly the expected next hop, which is what a
    deterministic route claims.

    ``adaptive=True`` is a MEMBERSHIP comparison: the route offers several
    realizable first hops per pair (SROTA picks its shape from live telemetry
    load), so the run executes one of them and demanding equality would fail
    roughly half the time for a perfectly correct design. What must hold is
    that the executed hop is one the certified route ALLOWS — an extra hop
    would mean routing the proof never saw.

Rationale: docs/decisions/modules/backend.md
    """
    from veritx_dse.core.route_artifact import compare_first_hop_tables

    executed = parse_route_dump(dump_text)
    if adaptive:
        allowed: dict[tuple[int, int], set[int]] = {}
        for src, dst, next_router in expected_rows:
            allowed.setdefault((src, dst), set()).add(next_router)
        foreign = sorted(
            ((pair, hop) for pair, hop in executed.items()
             if pair not in allowed or hop not in allowed[pair]),
            key=lambda item: item[0])
        if foreign:
            shown = [(pair, allowed.get(pair), hop)
                     for pair, hop in foreign[:3]]
            raise RouteObservationError(
                f"the executed realization takes {len(foreign)} hop(s) the "
                f"certified adaptive route does not allow (pair, allowed, "
                f"executed): {shown}")
        return RouteObservationResult(
            routing_class=routing_class, pairs_compared=len(executed),
            expected_sha256=hashlib.sha256(
                repr(sorted(expected_rows)).encode()).hexdigest(),
            executed_sha256=hashlib.sha256(
                repr(sorted(executed.items())).encode()).hexdigest())
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

ADAPTIVE_OBSERVATION_SCOPE = (
    "adaptive runtime selection is allocator-observed over the canonical "
    "candidate set; no deterministic first-hop table exists and the "
    "backend writes no dump. Deterministic table equivalence must never "
    "be claimed for an adaptive policy.")

def refuse_deterministic_claim_for_adaptive(policy_algorithm: object) -> None:
    """Refuse deterministic-table equivalence for adaptive policies."""
    if not isinstance(policy_algorithm, str) or not policy_algorithm:
        raise RouteObservationError(
            "policy algorithm must be a non-empty string")
    if policy_algorithm == "per_hop_min_adaptive":
        raise RouteObservationError(
            "UNSUPPORTED scope: deterministic first-hop table equivalence "
            "cannot certify per_hop_min_adaptive execution — the "
            "candidate set has no single next hop and the backend "
            "refuses the dump (" + ADAPTIVE_OBSERVATION_SCOPE + ")")
    return None

def render_adaptive_candidate_table(
        relation: Any) -> tuple[tuple[int, int, str | None, tuple], ...]:
    """Render canonical candidate sets for inspection (never evidence)."""
    rows: list[tuple[int, int, str | None, tuple]] = []
    for decision in relation.decisions:
        context = decision.context
        actions = tuple(
            (action.channel_id, action.next_role_id, action.priority)
            for action in decision.actions)
        rows.append((context.router_id,
                     context.destination_router_id,
                     context.current_role_id, actions))
    return tuple(sorted(rows, key=lambda row: (
        row[0], row[1], row[2] or "")))

__all__ = [
    "RouteObservationError", "RouteObservationResult", "RouteDumpRow",
    "compare_route_realization", "expected_route_rows", "parse_route_dump",
    "parse_route_dump_rows",
    "refuse_deterministic_claim_for_adaptive",
    "render_adaptive_candidate_table",
    "ADAPTIVE_OBSERVATION_SCOPE",
]
