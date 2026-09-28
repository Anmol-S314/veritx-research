"""RHO/GRPO synthesis adapters — candidate producers, not evaluators.

Rolling-horizon (RHO) retains the useful historical idea (seed topology,
add/remove link mutations, connectivity + edge-budget invariants,
rolling-horizon evaluation) and GRPO retains group candidate evaluation
with relative selection — WITHOUT pretending GRPO is a trained RL policy.

Both emit HeuristicProposal objects whose identity binding is
candidate-identical (definition_id + traffic_id + nodes + sorted links),
so the lead integrator's vocabulary widening (candidate.ALGORITHMS +
definition ENGINES) changes nothing in this file. Conversion via
to_topology_candidate() raises AdapterVocabularyPending until that
widening lands — a typed gate, never a silent bypass.

Laws (fail-closed):
- Seeded random.Random only; no global random, no subprocess, no BookSim.
- Analytical traffic_weighted_hops objective (exact BFS shortest paths);
  disconnected graphs raise CandidateRejected, never a penalty number.
- Sentinel ban: 1000.0 / 1e9 / non-finite objectives are refused, never
  valid measurements (historical failure laundering ends here).
- No uniform-traffic fallback: traffic dims must equal definition nodes.
- Proposals carry NO certificate, qualified performance, routing proof,
  Pareto membership or recommendation — screening only.
"""
from __future__ import annotations

import math
import random
from collections import deque
from dataclasses import dataclass, field


class AdapterError(ValueError):
    """Typed adapter refusal."""


class CandidateRejected(AdapterError):
    """A proposal that may never become a candidate (disconnected, ...)."""


class AdapterVocabularyPending(AdapterError):
    """candidate.ALGORITHMS does not yet list this adapter's algorithm.

    Raised by to_topology_candidate() until the lead integrator widens
    the central vocabulary. The proposal identity is already
    candidate-identical, so widening changes nothing here.
    """

    def __init__(self, algorithm: str, needed: tuple[str, ...]):
        super().__init__(
            f"algorithm {algorithm!r} not in candidate.ALGORITHMS; "
            f"lead integrator must add {list(needed)}"
        )
        self.algorithm = algorithm
        self.needed = needed


RHO_ALGORITHM = "rho_iterative"
GRPO_ALGORITHM = "grpo_group"
NEEDED_VOCABULARY = (RHO_ALGORITHM, GRPO_ALGORITHM)

#: Historical failure-laundering sentinels — never valid objectives.
BANNED_OBJECTIVES = frozenset({1000.0, 1e9})


def check_objective_honest(value: float) -> float:
    if not isinstance(value, (int, float)) or not math.isfinite(value):
        raise CandidateRejected(f"non-finite generator objective {value!r}")
    if float(value) in BANNED_OBJECTIVES:
        raise CandidateRejected(
            f"banned sentinel objective {value!r} — failure is typed, "
            "never a large valid latency"
        )
    return float(value)


def _bfs_hops(nodes: int, adj: dict[int, set[int]], src: int) -> list[float]:
    dist = [math.inf] * nodes
    dist[src] = 0.0
    q: deque[int] = deque([src])
    while q:
        u = q.popleft()
        for v in adj.get(u, ()):
            if dist[v] == math.inf:
                dist[v] = dist[u] + 1.0
                q.append(v)
    return dist


def traffic_weighted_hops(
    nodes: int, links: frozenset[tuple[int, int]], demands: list[list[float]]
) -> float:
    """Analytical generator objective — exact BFS, never measured latency."""
    if len(demands) != nodes or any(len(r) != nodes for r in demands):
        raise CandidateRejected(
            f"traffic {len(demands)}x{len(demands[0]) if demands else 0} "
            f"!= nodes {nodes} — no uniform fallback"
        )
    adj: dict[int, set[int]] = {i: set() for i in range(nodes)}
    for u, v in links:
        adj[u].add(v)
        adj[v].add(u)
    total = 0.0
    for s in range(nodes):
        dist = _bfs_hops(nodes, adj, s)
        for t in range(nodes):
            d = demands[s][t]
            if d:
                if dist[t] == math.inf:
                    raise CandidateRejected(
                        f"disconnected candidate: {s}->{t} unreachable"
                    )
                total += d * dist[t]
    return check_objective_honest(total)


def is_connected(nodes: int, links: frozenset[tuple[int, int]]) -> bool:
    if nodes <= 1:
        return True
    adj: dict[int, set[int]] = {i: set() for i in range(nodes)}
    for u, v in links:
        adj[u].add(v)
        adj[v].add(u)
    seen = {0}
    q: deque[int] = deque([0])
    while q:
        u = q.popleft()
        for v in adj[u]:
            if v not in seen:
                seen.add(v)
                q.append(v)
    return len(seen) == nodes


def mesh_links(k: int) -> frozenset[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for r in range(k):
        for c in range(k):
            u = r * k + c
            if c + 1 < k:
                out.add((min(u, u + 1), max(u, u + 1)))
            if r + 1 < k:
                out.add((min(u, u + k), max(u, u + k)))
    return frozenset(out)


@dataclass(frozen=True)
class HeuristicProposal:
    """A screened graph proposal — not a TopologyCandidate until converted."""

    algorithm: str
    definition_id: str
    traffic_id: str
    nodes: int
    links: frozenset[tuple[int, int]]
    objective_name: str = "traffic_weighted_hops"
    objective_value: float = 0.0
    seed: int = 0
    engine_semantics_version: str = "rho-grpo-adapter/v1"

    def proposal_id(self) -> str:
        from veritx_dse.core.artifact import content_id

        return content_id(
            "veritx/heuristic-proposal/v1",
            {
                "algorithm": self.algorithm,
                "definition_id": self.definition_id,
                "traffic_id": self.traffic_id,
                "nodes": self.nodes,
                "links": sorted([list(e) for e in self.links]),
                "objective_name": self.objective_name,
                "seed": self.seed,
            },
        )


def _mutate(
    rng: random.Random,
    nodes: int,
    links: set[tuple[int, int]],
    max_edges: int,
    radix: int,
) -> set[tuple[int, int]] | None:
    degree = [0] * nodes
    for u, v in links:
        degree[u] += 1
        degree[v] += 1
    if rng.random() < 0.5 or not links:
        if len(links) >= max_edges:
            return None
        for _ in range(32):
            u, v = rng.randrange(nodes), rng.randrange(nodes)
            if u == v:
                continue
            e = (min(u, v), max(u, v))
            if e in links or degree[u] >= radix or degree[v] >= radix:
                continue
            return links | {e}
        return None
    e = rng.choice(sorted(links))
    trial = links - {e}
    if not is_connected(nodes, frozenset(trial)):
        return None
    return trial


def run_rho(
    *,
    definition_id: str,
    traffic_id: str,
    nodes: int,
    k: int,
    demands: list[list[float]],
    seed: int,
    steps: int = 20,
    horizon: int = 3,
    branch: int = 4,
    max_edges: int = 120,
    radix: int = 4,
) -> HeuristicProposal:
    """Rolling-horizon graph search — deterministic under seed."""
    rng = random.Random(seed)
    cur = set(mesh_links(k)) if k * k == nodes else set()
    if not cur or not is_connected(nodes, frozenset(cur)):
        raise CandidateRejected("RHO requires a connected seed mesh")
    best = frozenset(cur)
    best_obj = traffic_weighted_hops(nodes, best, demands)
    for _ in range(steps):
        cands: list[frozenset[tuple[int, int]]] = []
        for _ in range(branch * 2):
            trial = set(best)
            for _ in range(max(horizon - 1, 1)):
                m = _mutate(rng, nodes, trial, max_edges, radix)
                if m is not None:
                    trial = m
            if is_connected(nodes, frozenset(trial)):
                cands.append(frozenset(trial))
        for cand in cands:
            try:
                obj = traffic_weighted_hops(nodes, cand, demands)
            except CandidateRejected:
                continue
            if obj < best_obj:
                best, best_obj = cand, obj
    return HeuristicProposal(
        algorithm=RHO_ALGORITHM,
        definition_id=definition_id,
        traffic_id=traffic_id,
        nodes=nodes,
        links=best,
        objective_value=best_obj,
        seed=seed,
    )


def run_grpo(
    *,
    definition_id: str,
    traffic_id: str,
    nodes: int,
    k: int,
    demands: list[list[float]],
    seed: int,
    steps: int = 20,
    group: int = 4,
    max_edges: int = 120,
    radix: int = 4,
) -> HeuristicProposal:
    """Group-relative graph search — relative selection, no trained policy.

    No weights, no gradients, no policy network: per step, evaluate a
    group of mutants, baseline = mean reward, commit the best mutant only
    if it improves on the incumbent. The name records the selection
    discipline, not a learned model.
    """
    rng = random.Random(seed)
    cur = set(mesh_links(k)) if k * k == nodes else set()
    if not cur or not is_connected(nodes, frozenset(cur)):
        raise CandidateRejected("GRPO requires a connected seed mesh")
    best = frozenset(cur)
    best_obj = traffic_weighted_hops(nodes, best, demands)
    for _ in range(steps):
        scored: list[tuple[float, frozenset[tuple[int, int]]]] = []
        for _ in range(group):
            m = _mutate(rng, nodes, set(best), max_edges, radix)
            if m is None or not is_connected(nodes, frozenset(m)):
                continue
            try:
                obj = traffic_weighted_hops(nodes, frozenset(m), demands)
            except CandidateRejected:
                continue
            scored.append((obj, frozenset(m)))
        if not scored:
            continue
        rewards = [-o - 0.1 * len(c) for o, c in scored]
        baseline = sum(rewards) / len(rewards)
        top = max(range(len(scored)), key=lambda i: rewards[i] - baseline)
        if scored[top][0] < best_obj and len(scored[top][1]) <= max_edges:
            best, best_obj = scored[top][1], scored[top][0]
    return HeuristicProposal(
        algorithm=GRPO_ALGORITHM,
        definition_id=definition_id,
        traffic_id=traffic_id,
        nodes=nodes,
        links=best,
        objective_value=best_obj,
        seed=seed,
    )


def to_topology_candidate(proposal: HeuristicProposal, **kwargs):
    """Promote a screened proposal into a typed TopologyCandidate.

    Heuristic provenance: solver_status is FEASIBLE always (never OPTIMAL —
    only a solver proof earns OPTIMAL). Search completeness for RHO/GRPO is
    UNBOUNDED: product copy may only say 'best observed among evaluated
    candidates' (see optimization/completeness.py)."""
    from veritx_dse.synthesis import candidate as cand

    if proposal.algorithm not in cand.ALGORITHMS:
        raise AdapterVocabularyPending(proposal.algorithm, NEEDED_VOCABULARY)
    return cand.TopologyCandidate(
        definition_id=proposal.definition_id,
        traffic_id=proposal.traffic_id,
        links=tuple(sorted(proposal.links)),
        nodes=proposal.nodes,
        algorithm=proposal.algorithm,
        solver_status="FEASIBLE",
        objective_value=proposal.objective_value,
        objective_name=proposal.objective_name,
        status="SUCCEEDED",
        producer_id=f"veritx_dse.synthesis.rho_grpo_adapter/{proposal.engine_semantics_version}",
    )


__all__ = [
    "AdapterError",
    "CandidateRejected",
    "AdapterVocabularyPending",
    "RHO_ALGORITHM",
    "GRPO_ALGORITHM",
    "HeuristicProposal",
    "check_objective_honest",
    "traffic_weighted_hops",
    "is_connected",
    "run_rho",
    "run_grpo",
    "to_topology_candidate",
]
