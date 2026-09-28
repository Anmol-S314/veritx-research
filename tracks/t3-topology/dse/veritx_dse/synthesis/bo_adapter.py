"""BO synthesis adapter — parameterized-generator search as candidate producer.

Bayesian optimization over the historical 5-D topology-generator space
(cluster_size, express_length, radix, intra_weight, inter_weight).
The surrogate is pluggable and defaults to honestly-labelled
seeded-random: no scikit-optimize GP is vendored or claimed. A GP
returns only with a vendored, qualified surrogate whose name is recorded
on the proposal; until then the search reports BUDGETED completeness,
never exhaustive or optimal.

Same laws as the RHO/GRPO adapter: seeded determinism, connectivity +
radix invariants, sentinel ban, no uniform fallback, no BookSim
authority, candidate-identical proposal identity, vocabulary gate.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from veritx_dse.synthesis.rho_grpo_adapter import (
    AdapterError,
    AdapterVocabularyPending,
    CandidateRejected,
    check_objective_honest,
    is_connected,
    traffic_weighted_hops,
)

BO_ALGORITHM = "bo_gp"
NEEDED_VOCABULARY = (BO_ALGORITHM,)

CLUSTER_SIZES = (4, 8, 16)
EXPRESS_LENGTHS = (1, 2, 3)
RADICES = (3, 4, 5)


@dataclass(frozen=True)
class GeneratorParams:
    cluster_size: int = 4
    express_length: int = 1
    radix: int = 4
    intra_weight: float = 1.0
    inter_weight: float = 0.3

    def __post_init__(self):
        if self.cluster_size not in CLUSTER_SIZES:
            raise CandidateRejected(
                f"cluster_size {self.cluster_size!r} not in "
                f"{list(CLUSTER_SIZES)}"
            )
        if self.express_length not in EXPRESS_LENGTHS:
            raise CandidateRejected(
                f"express_length {self.express_length!r} not in "
                f"{list(EXPRESS_LENGTHS)}"
            )
        if self.radix not in RADICES:
            raise CandidateRejected(
                f"radix {self.radix!r} not in {list(RADICES)}"
            )
        for name in ("intra_weight", "inter_weight"):
            v = getattr(self, name)
            if not isinstance(v, (int, float)) or not math.isfinite(v):
                raise CandidateRejected(f"{name} must be finite, got {v!r}")
        if not 0.5 <= self.intra_weight <= 1.0:
            raise CandidateRejected("intra_weight must be in [0.5, 1.0]")
        if not 0.1 <= self.inter_weight <= 0.5:
            raise CandidateRejected("inter_weight must be in [0.1, 0.5]")


@dataclass(frozen=True)
class BoProposal:
    algorithm: str = BO_ALGORITHM
    definition_id: str = ""
    traffic_id: str = ""
    nodes: int = 0
    links: frozenset[tuple[int, int]] = frozenset()
    params: GeneratorParams = GeneratorParams()
    surrogate: str = "seeded-random"
    objective_name: str = "traffic_weighted_hops"
    objective_value: float = 0.0
    seed: int = 0
    engine_semantics_version: str = "bo-adapter/v1"

    def proposal_id(self) -> str:
        from veritx_dse.core.artifact import content_id

        return content_id(
            "veritx/bo-proposal/v1",
            {
                "algorithm": self.algorithm,
                "definition_id": self.definition_id,
                "traffic_id": self.traffic_id,
                "nodes": self.nodes,
                "links": sorted([list(e) for e in self.links]),
                "params": [
                    self.params.cluster_size,
                    self.params.express_length,
                    self.params.radix,
                    self.params.intra_weight,
                    self.params.inter_weight,
                ],
                "surrogate": self.surrogate,
                "seed": self.seed,
            },
        )


def generate_topology(
    nodes: int, params: GeneratorParams, seed: int
) -> frozenset[tuple[int, int]]:
    """Deterministic generator: mesh base + express edges + radix cap."""
    rng = random.Random((seed * 100003 + params.cluster_size * 101
                         + params.express_length * 11 + params.radix) % (2 ** 31))
    k = int(math.isqrt(nodes))
    if k * k != nodes:
        raise CandidateRejected("BO generator requires square nodes == k*k")
    links: set[tuple[int, int]] = set()
    for r in range(k):
        for c in range(k):
            u = r * k + c
            if c + 1 < k:
                links.add((min(u, u + 1), max(u, u + 1)))
            if r + 1 < k:
                links.add((min(u, u + k), max(u, u + k)))
    reach = params.express_length
    for r in range(k):
        for c in range(k):
            u = r * k + c
            if c + reach < k:
                v = r * k + c + reach
                links.add((min(u, v), max(u, v)))
            if r + reach < k:
                v = (r + reach) * k + c
                links.add((min(u, v), max(u, v)))
    degree = [0] * nodes
    for u, v in links:
        degree[u] += 1
        degree[v] += 1
    by_len = sorted(links, key=lambda e: (abs(e[0] - e[1]), e))
    kept: set[tuple[int, int]] = set()
    deg = [0] * nodes
    for e in by_len:
        u, v = e
        if deg[u] < params.radix and deg[v] < params.radix:
            kept.add(e)
            deg[u] += 1
            deg[v] += 1
    if not is_connected(nodes, frozenset(kept)):
        raise CandidateRejected("BO generator produced disconnected graph")
    _ = rng
    return frozenset(kept)


def run_bo(
    *,
    definition_id: str,
    traffic_id: str,
    nodes: int,
    demands: list[list[float]],
    seed: int,
    iters: int = 10,
    surrogate: str = "seeded-random",
) -> BoProposal:
    """Seeded-random search over the 5-D generator space (honestly labelled)."""
    if surrogate != "seeded-random":
        raise AdapterError(
            f"surrogate {surrogate!r} not vendored — only 'seeded-random' "
            "is available; a GP returns with a qualified surrogate"
        )
    rng = random.Random(seed)
    best: BoProposal | None = None
    for _ in range(max(iters, 1)):
        params = GeneratorParams(
            cluster_size=rng.choice(list(CLUSTER_SIZES)),
            express_length=rng.choice(list(EXPRESS_LENGTHS)),
            radix=rng.choice(list(RADICES)),
            intra_weight=rng.uniform(0.5, 1.0),
            inter_weight=rng.uniform(0.1, 0.5),
        )
        try:
            links = generate_topology(nodes, params, rng.randrange(2**31))
            obj = traffic_weighted_hops(nodes, links, demands)
        except CandidateRejected:
            continue
        prop = BoProposal(
            definition_id=definition_id,
            traffic_id=traffic_id,
            nodes=nodes,
            links=links,
            params=params,
            surrogate=surrogate,
            objective_value=obj,
            seed=seed,
        )
        if best is None or obj < best.objective_value:
            best = prop
    if best is None:
        raise CandidateRejected("BO search produced no connected proposal")
    return best


def to_topology_candidate(proposal: BoProposal, **kwargs):
    from veritx_dse.synthesis import candidate as cand

    if proposal.algorithm not in cand.ALGORITHMS:
        raise AdapterVocabularyPending(proposal.algorithm, NEEDED_VOCABULARY)
    raise AdapterError(
        "widened vocabulary path not yet wired to promotion in this slice"
    )


__all__ = [
    "BO_ALGORITHM",
    "GeneratorParams",
    "BoProposal",
    "generate_topology",
    "run_bo",
    "to_topology_candidate",
    "CandidateRejected",
]
