"""Parent-recomputed dependency proofs for the canonical routing seam.

Whole-wire/VC nodes are a conservative quotient of tap-buffer instances:
all admitted transitions are retained, INCLUDING collapsed self-loops. This
is a routing/resource-cycle proof, not fairness, credits or buffer liveness.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from functools import cached_property
from typing import Callable

from veritx_dse.core.artifact import (
    content_id, require_fields, require_type_tag, require_schema_version, require_embedded_id,
)
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.shared_resource import ResourceRef, ResourceVC
from veritx_dse.verification.shared_resource_cdg import SharedResourceCDG


class ProofStrategy(str, Enum):
    ACYCLIC_DEPENDENCY_GRAPH = "ACYCLIC_DEPENDENCY_GRAPH"
    STRICT_RESOURCE_RANK = "STRICT_RESOURCE_RANK"
    ESCAPE_SUBNETWORK = "ESCAPE_SUBNETWORK"


@dataclass(frozen=True)
class DependencyGraph:
    resource_graph_id: str
    routing_policy_id: str
    allocation_id: str
    nodes: tuple[ResourceVC, ...]
    edges: tuple[tuple[ResourceVC, ResourceVC], ...]

    def __post_init__(self):
        for name in ("resource_graph_id", "routing_policy_id", "allocation_id"):
            if not isinstance(getattr(self, name), str) or not getattr(self, name):
                raise InvalidInput("dependency graph requires all parent identities")
        if not isinstance(self.nodes, tuple) or not isinstance(self.edges, tuple):
            raise InvalidInput("dependency nodes/edges must be immutable")
        for node in self.nodes:
            if not isinstance(node, tuple) or len(node) != 2 or not isinstance(node[0], ResourceRef):
                raise InvalidInput("dependency node must be (canonical resource, concrete VC)")
            exact_int("held VC", node[1])
        known = set(self.nodes)
        if len(known) != len(self.nodes):
            raise InvalidInput("duplicate dependency node")
        for edge in self.edges:
            if not isinstance(edge, tuple) or len(edge) != 2 or any(node not in known for node in edge):
                raise InvalidInput("dependency edge names a missing concrete held resource")
        if len(set(self.edges)) != len(self.edges):
            raise InvalidInput("duplicate dependency edge")
        object.__setattr__(self, "nodes", tuple(sorted(self.nodes)))
        object.__setattr__(self, "edges", tuple(sorted(self.edges)))

    def find_cycle(self):
        return SharedResourceCDG(self.nodes, self.edges, {}).find_cycle()

    def identity_dict(self):
        node = lambda n: [n[0].to_dict(), n[1]]
        return {"type": "veritx/DependencyGraph", "schema_version": 1,
                "resource_graph_id": self.resource_graph_id, "routing_policy_id": self.routing_policy_id,
                "allocation_id": self.allocation_id, "abstraction": "CONSERVATIVE_WHOLE_RESOURCE_VC",
                "nodes": [node(n) for n in self.nodes], "edges": [[node(a), node(b)] for a, b in self.edges]}

    @cached_property
    def _artifact_id(self):
        return content_id("veritx/DependencyGraph/v1", self.identity_dict())

    def artifact_id(self):
        return self._artifact_id

    def to_dict(self):
        return {**self.identity_dict(), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, d):
        fields = {"type", "schema_version", "resource_graph_id", "routing_policy_id", "allocation_id",
                  "abstraction", "nodes", "edges", "artifact_id"}
        require_fields(d, fields, "dependency graph")
        require_type_tag(d, "veritx/DependencyGraph", "dependency graph")
        if type(d.get("schema_version")) is not int:
            raise InvalidInput("dependency schema version must be an exact int")
        require_schema_version(d, 1, "dependency graph")
        if d.get("abstraction") != "CONSERVATIVE_WHOLE_RESOURCE_VC":
            raise UnsupportedSemantics("unsupported dependency resource abstraction")
        if type(d.get("nodes")) is not list or type(d.get("edges")) is not list:
            raise InvalidInput("dependency data must be JSON lists")
        def node(row):
            if type(row) is not list or len(row) != 2:
                raise InvalidInput("dependency node must be [resource, VC]")
            return ResourceRef.from_dict(row[0]), row[1]
        edges = []
        for edge in d["edges"]:
            if type(edge) is not list or len(edge) != 2:
                raise InvalidInput("dependency edge must contain two nodes")
            edges.append((node(edge[0]), node(edge[1])))
        graph = cls(d["resource_graph_id"], d["routing_policy_id"], d["allocation_id"],
                    tuple(node(n) for n in d["nodes"]), tuple(edges))
        require_embedded_id(d, "artifact_id", graph.artifact_id(), "dependency graph")
        return graph


def recompute_dependency_graph(resources, policy, allocation) -> DependencyGraph:
    policy.validate_against(resources, allocation)
    transitions = set(allocation.resources.allowed_transitions)
    nodes, edges = set(), set()
    for rule in policy.rules:
        for first in rule.actions:
            if first.eject:
                continue
            incoming = allocation.vcs(first.vc_partition)
            nodes.update((first.resource, vc) for vc in incoming)
            for second in policy.actions(first.continuation(rule.context)):
                if second.eject:
                    continue
                outgoing = allocation.vcs(second.vc_partition)
                nodes.update((second.resource, vc) for vc in outgoing)
                for vc_in in incoming:
                    targets = tuple(vc for vc in outgoing if (vc_in, vc) in transitions)
                    if not targets:
                        raise InvalidInput("allocation cannot realize an admitted routing continuation")
                    # Never drop self-loops, including tap-buffer quotient loops.
                    edges.update(((first.resource, vc_in), (second.resource, vc)) for vc in targets)
    return DependencyGraph(resources.artifact_id(), policy.artifact_id(), allocation.artifact_id(),
                           tuple(sorted(nodes)), tuple(sorted(edges)))


@dataclass(frozen=True)
class DependencyProof:
    strategy: ProofStrategy
    graph: DependencyGraph
    verdict: str
    ranks: tuple[tuple[ResourceVC, int], ...] = ()
    cycle: tuple[ResourceVC, ...] = ()

    def __post_init__(self):
        if not isinstance(self.strategy, ProofStrategy) or not isinstance(self.graph, DependencyGraph):
            raise InvalidInput("dependency proof needs a typed strategy and graph")
        if self.verdict not in ("PASS", "FAIL"):
            raise InvalidInput("dependency proof verdict must be PASS or FAIL")
        if not isinstance(self.ranks, tuple) or not isinstance(self.cycle, tuple):
            raise InvalidInput("proof data must be immutable")
        for node, rank in self.ranks:
            if node not in self.graph.nodes:
                raise InvalidInput("rank names a missing dependency node")
            exact_int("resource rank", rank)
        if len({n for n, _r in self.ranks}) != len(self.ranks):
            raise InvalidInput("duplicate resource rank")
        object.__setattr__(self, "ranks", tuple(sorted(self.ranks)))

    @cached_property
    def _artifact_id(self):
        return content_id("veritx/DependencyProof/v1", self.identity_dict())

    def artifact_id(self):
        return self._artifact_id

    def identity_dict(self):
        return {"type": "veritx/DependencyProof", "schema_version": 1,
                "strategy": self.strategy.value, "strategy_version": 1,
                "scope": "ROUTING_RESOURCE_VC_CYCLES_ONLY", "graph_id": self.graph.artifact_id(),
                "verdict": self.verdict,
                "ranks": [[n[0].to_dict(), n[1], rank] for n, rank in self.ranks],
                "cycle": [[n[0].to_dict(), n[1]] for n in self.cycle]}

    def to_dict(self):
        return {**self.identity_dict(), "graph": self.graph.to_dict(), "artifact_id": self.artifact_id()}

    @classmethod
    def from_dict(cls, d, *, resources, policy, allocation, rank_provider=None):
        fields = {"type", "schema_version", "strategy", "strategy_version", "scope", "graph_id",
                  "verdict", "ranks", "cycle", "graph", "artifact_id"}
        require_fields(d, fields, "dependency proof")
        require_type_tag(d, "veritx/DependencyProof", "dependency proof")
        if type(d.get("schema_version")) is not int or type(d.get("strategy_version")) is not int:
            raise InvalidInput("proof versions must be exact ints")
        require_schema_version(d, 1, "dependency proof")
        graph = DependencyGraph.from_dict(d["graph"])
        expected = prove_dependencies(resources, policy, allocation,
                                      rank_provider=rank_provider, stored_graph=graph)
        from veritx_dse.core.artifact import canonical_bytes
        if canonical_bytes({key: d.get(key) for key in expected.identity_dict()}) != canonical_bytes(expected.identity_dict()):
            raise EvidenceInvalid("stored proof strategy/rank/verdict differs from parent recomputation")
        require_embedded_id(d, "artifact_id", expected.artifact_id(), "dependency proof")
        return expected

    def revalidate(self, resources, policy, allocation, *, rank_provider=None):
        expected = prove_dependencies(resources, policy, allocation, rank_provider=rank_provider)
        if self != expected:
            raise EvidenceInvalid("stored dependency proof differs from parent-recomputed proof data")


def prove_dependencies(resources, policy, allocation, *, rank_provider: Callable | None = None,
                       stored_graph: DependencyGraph | None = None) -> DependencyProof:
    try:
        strategy = ProofStrategy(policy.proof_strategy)
    except ValueError:
        raise UnsupportedSemantics(f"unknown dependency proof strategy {policy.proof_strategy!r}") from None
    if strategy is ProofStrategy.ESCAPE_SUBNETWORK:
        raise UnsupportedSemantics("escape strategy requires an implemented accessibility/closure theorem")
    graph = recompute_dependency_graph(resources, policy, allocation)
    if stored_graph is not None and stored_graph != graph:
        raise EvidenceInvalid("stored dependency graph differs from parent-recomputed nodes/edges")
    cycle = tuple(graph.find_cycle() or ())
    ranks = ()
    rank_ok = True
    if strategy is ProofStrategy.STRICT_RESOURCE_RANK:
        if rank_provider is None:
            raise UnsupportedSemantics("strict resource rank requires a trusted parent-derived rank provider")
        derived = rank_provider(resources, policy, allocation, graph)
        if set(derived) != set(graph.nodes):
            raise InvalidInput("parent-derived rank does not cover every concrete held resource")
        for rank in derived.values():
            exact_int("resource rank", rank)
        ranks = tuple(sorted(derived.items()))
        rank_ok = all(derived[a] < derived[b] for a, b in graph.edges)
    return DependencyProof(strategy, graph, "FAIL" if cycle or not rank_ok else "PASS", ranks, cycle)
