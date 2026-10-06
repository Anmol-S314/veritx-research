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
ROUTE_DUMP_KNOWN_TRAILERS = frozenset({"drop", "lanes"})
_DUMP_RE = re.compile(
    r"^src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)"
    r"((?:\s+\S+)*)$")

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
    executed: dict[tuple[int, int], int] = {}
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _DUMP_RE.match(line)
        if match is None:
            raise RouteObservationError(
                f"route dump line {line_no} is malformed: {line!r}")
        trailer = match.group(5).split()
        if len(trailer) % 2:
            raise RouteObservationError(
                f"route dump line {line_no} has a dangling trailer key: "
                f"{line!r}")
        src = int(match.group(1))
        dst = int(match.group(2))
        nxt = int(match.group(3))
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

Rationale: docs/decisions/modules/backend.md
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

Rationale: docs/decisions/modules/backend.md
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
    "RouteObservationError", "RouteObservationResult",
    "compare_route_realization", "expected_route_rows", "parse_route_dump",
    "refuse_deterministic_claim_for_adaptive",
    "render_adaptive_candidate_table",
    "ADAPTIVE_OBSERVATION_SCOPE",
]
