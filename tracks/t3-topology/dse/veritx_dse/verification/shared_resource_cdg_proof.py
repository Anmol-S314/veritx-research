"""shared_resource_cdg_proof — a checkable certificate for shared-wire acyclicity.

Why this module exists
----------------------
``shared_resource_cdg`` builds the concrete ``(resource, vc)`` dependency graph
for a fabric with shared wires, and ``shared_resource_deadlock`` reports PASS
when ``find_cycle()`` returns None. That is a correct decision procedure, but
the verdict rests entirely on our own depth-first traversal: the claim "this
fabric is deadlock-free" is only as trustworthy as the ~40 lines that produced
it, and a reader has no way to check it short of re-reading the code.

The point-to-point families get a machine-checked proof instead: their channel
dependency graph is emitted as a SystemVerilog harness and discharged by
``sby prove`` as an unbounded induction. The shared-wire fabrics had no
equivalent, which is why both Scope B claim lists carry "formal deadlock ...
not established" as an open criterion.

This module gives the shared-wire graph the same class of artifact, in the form
the graph actually supports:

  * a RANK WITNESS — one integer per node such that every dependency edge goes
    from a strictly smaller rank to a strictly larger one. A DAG admits such a
    rank (a topological order); a graph with a cycle does not.

The witness is the certificate, and it is checkable in O(V+E) **without
trusting the producer and without a solver**: walk the edges and assert the
inequality. That matters more than speed. A PASS that carries a witness can be
audited by anyone with the edge list.

Three independent readers, which is the point:

  1. ``find_cycle`` (DFS) — decides, and names the cycle when there is one;
  2. ``topological_rank`` (Kahn) — produces the witness, or refuses;
  3. ``emit_smtlib`` + an SMT solver — re-derives the same question from the
     rank constraints alone, with no knowledge of the other two.

Disagreement is a bug and is refused, never averaged. ``check_with_solver``
reports the solver's answer, and the caller must compare it.

Limits, stated rather than implied (they are the same limits the CDG carries):
this proves routing-dependent resource cycles only. It does not model
arbitration fairness, buffer or credit availability, traffic-class injection
eligibility, or adaptive route sets without a supported dependency model. A
cycle-free dependency graph is a *necessary* condition for a deadlock-free
network, not a sufficient one for egress under every arbitration policy.

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

import heapq
import re
import shutil
import subprocess
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import SemanticError
from veritx_dse.model.shared_resource import ResourceVC
from veritx_dse.verification.shared_resource_cdg import (
    SharedResourceCDG,
    SharedResourceCDGError,
)

SHARED_RESOURCE_CDG_PROOF_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/SharedResourceAcyclicityProof"
PROOF_METHOD = "SHARED_RESOURCE_RANK_WITNESS"


class SharedResourceCDGProofError(ValueError, SemanticError):
    """The witness, the graph or the solver answer is not what it claims."""


@dataclass(frozen=True)
class AcyclicityProof:
    """A rank witness: every edge goes from a lower rank to a higher one."""

    graph_id: str
    ranks: tuple[tuple[ResourceVC, int], ...]
    node_count: int
    edge_count: int
    schema_version: int = SHARED_RESOURCE_CDG_PROOF_SCHEMA_VERSION

    def rank_map(self) -> dict[ResourceVC, int]:
        return dict(self.ranks)

    def canonical_dict(self) -> dict[str, Any]:
        return {
            "graph_id": self.graph_id,
            "ranks": [[resource.to_dict(), vc, rank] for (resource, vc), rank in self.ranks],
            "node_count": self.node_count,
            "edge_count": self.edge_count,
            "method": PROOF_METHOD,
        }

    def proof_id(self) -> str:
        return content_id(
            f"{_HASH_TYPE_TAG}/v{self.schema_version}", self.canonical_dict())

    def as_dict(self) -> dict[str, Any]:
        return {
            **self.canonical_dict(),
            "schema": "veritx/shared-resource-acyclicity-proof/1",
            "proof_method": PROOF_METHOD,
            "proof_id": self.proof_id(),
            "arbitration_fairness_modeled": False,
            "credit_or_buffer_availability_modeled": False,
            "sufficient_for_egress_under_any_arbitration": False,
        }


def _node_index(cdg: SharedResourceCDG) -> dict[ResourceVC, int]:
    """Deterministic index. The graph's own node tuple order is the authority."""
    return {node: index for index, node in enumerate(cdg.nodes)}


def _require_graph_matches_nodes(cdg: SharedResourceCDG) -> None:
    """Every edge endpoint must be a declared node.

    A graph whose edges reach undeclared nodes has no rank that covers it, and
    silently unioning the endpoints would hide a builder defect behind a
    proof. Refuse instead.
    """
    known = set(cdg.nodes)
    if len(known) != len(cdg.nodes):
        raise SharedResourceCDGProofError(
            "the graph lists the same node twice, so a rank cannot name it "
            "unambiguously")
    for src, dst in cdg.edges:
        for endpoint in (src, dst):
            if endpoint not in known:
                raise SharedResourceCDGProofError(
                    f"dependency edge names {endpoint!r}, which is not one of "
                    "the graph's declared nodes")


def topological_rank(cdg: SharedResourceCDG) -> dict[ResourceVC, int] | None:
    """Kahn's algorithm, deterministic. None means the graph has a cycle.

    Determinism is not cosmetic: the witness is hashed into the proof id, so a
    nondeterministic rank would give the same fabric two different proof ids
    and make the artifact undiffable across runs.
    """
    if not isinstance(cdg, SharedResourceCDG):
        raise SharedResourceCDGProofError(
            f"topological_rank needs a SharedResourceCDG, got "
            f"{type(cdg).__name__}")
    _require_graph_matches_nodes(cdg)
    index = _node_index(cdg)
    indegree = {node: 0 for node in cdg.nodes}
    outgoing: dict[ResourceVC, list[ResourceVC]] = {node: [] for node in cdg.nodes}
    for src, dst in cdg.edges:
        outgoing[src].append(dst)
        indegree[dst] += 1
    # Order the ready set by node index so the witness depends only on the
    # graph, never on dict or set iteration order.
    ready = [(_index_of(node, index), node)
             for node, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)
    ranks: dict[ResourceVC, int] = {}
    while ready:
        _, node = heapq.heappop(ready)
        ranks[node] = len(ranks)
        for nxt in outgoing[node]:
            indegree[nxt] -= 1
            if indegree[nxt] == 0:
                heapq.heappush(ready, (_index_of(nxt, index), nxt))
    if len(ranks) != len(cdg.nodes):
        return None
    return ranks


def _index_of(node: ResourceVC, index: dict[ResourceVC, int]) -> int:
    try:
        return index[node]
    except KeyError as exc:  # pragma: no cover - guarded by the caller
        raise SharedResourceCDGProofError(
            f"node {node!r} has no deterministic index") from exc


def verify_rank_witness(cdg: SharedResourceCDG,
                        ranks: dict[ResourceVC, int] | AcyclicityProof) -> None:
    """Check the witness against the graph, trusting nothing.

    This is the function an auditor runs. It needs no solver, no producer and
    no traversal state: ranks must cover exactly the declared nodes, and every
    single edge must strictly increase. Any violation raises.
    """
    observed = ranks.rank_map() if isinstance(ranks, AcyclicityProof) else dict(ranks)
    declared = set(cdg.nodes)
    missing = declared - set(observed)
    extra = set(observed) - declared
    if missing:
        raise SharedResourceCDGProofError(
            f"the witness omits {len(missing)} declared node(s), starting with "
            f"{sorted(missing, key=repr)[0]!r}; a partial rank proves nothing "
            "about the nodes it skips")
    if extra:
        raise SharedResourceCDGProofError(
            f"the witness ranks {len(extra)} node(s) the graph does not "
            f"declare, starting with {sorted(extra, key=repr)[0]!r}")
    for node, rank in observed.items():
        if type(rank) is not int:
            raise SharedResourceCDGProofError(
                f"rank for {node!r} must be an int, got {rank!r}")
    for src, dst in cdg.edges:
        if not observed[src] < observed[dst]:
            raise SharedResourceCDGProofError(
                f"edge {src!r} -> {dst!r} does not increase the rank "
                f"({observed[src]} !< {observed[dst]}); the witness does not "
                "certify acyclicity")


def prove_acyclic(cdg: SharedResourceCDG) -> AcyclicityProof | None:
    """Produce the witness, or None when the graph has a cycle.

    A witness that does not verify is a bug in this module, so it raises
    rather than returning something the caller would report as a pass.
    """
    ranks = topological_rank(cdg)
    if ranks is None:
        return None
    verify_rank_witness(cdg, ranks)
    ordered = tuple((node, ranks[node]) for node in cdg.nodes)
    return AcyclicityProof(
        graph_id=cdg.cdg_id(), ranks=ordered,
        node_count=cdg.node_count, edge_count=cdg.edge_count)


def emit_smtlib(cdg: SharedResourceCDG) -> str:
    """The same question as SMT-LIB, so a third party can re-decide it.

    Each node gets an integer rank bounded to ``[0, n-1]`` -- a topological
    order of a DAG always fits in that range, so the bound is lossless -- and
    every edge asserts ``(< rank_src rank_dst)``. ``sat`` means a rank exists
    (acyclic) and the model is a topological order; ``unsat`` means no rank
    exists (cyclic). Logic is QF_LIA: integers, no multiplication.
    """
    if not isinstance(cdg, SharedResourceCDG):
        raise SharedResourceCDGProofError(
            f"emit_smtlib needs a SharedResourceCDG, got {type(cdg).__name__}")
    _require_graph_matches_nodes(cdg)
    index = _node_index(cdg)
    count = cdg.node_count
    lines = [
        "; acyclicity of the shared-resource (resource, vc) dependency graph",
        f"; graph_id: {cdg.cdg_id()}",
        f"; nodes: {count}  edges: {cdg.edge_count}",
        f"; nodes rejected: the graph admits a rank iff it is acyclic",
        "(set-logic QF_LIA)",
    ]
    for node, position in sorted(index.items(), key=lambda item: item[1]):
        names = (f"; r{position} = (resource, vc) {node[0].to_dict()} @ {node[1]}")
        lines.append(names)
        lines.append(f"(declare-fun r{position} () Int)")
    for position in range(count):
        lines.append(f"(assert (>= r{position} 0))")
        lines.append(f"(assert (<= r{position} {max(count - 1, 0)}))")
    for src, dst in cdg.edges:
        lines.append(f"(assert (< r{index[src]} r{index[dst]}))")
    lines.append("(check-sat)")
    lines.append("(get-value (" + " ".join(
        f"r{position}" for position in range(count)) + "))")
    return "\n".join(lines) + "\n"


def solver_available() -> bool:
    return shutil.which("z3") is not None


def check_with_solver(cdg: SharedResourceCDG, *, timeout_s: int = 60
                      ) -> tuple[str, dict[int, int] | None]:
    """Re-decide acyclicity with z3, independently of this module's traversal.

    Returns ``("sat", model)`` when a rank exists, ``("unsat", None)`` when it
    does not, ``("unavailable", None)`` when z3 is absent, and ``("unknown",
    None)`` when the solver declines. A caller reporting PASS must compare this
    against the witness: ``sat`` agrees, ``unsat`` contradicts it and must be
    refused.
    """
    if not solver_available():
        return "unavailable", None
    script = emit_smtlib(cdg)
    try:
        run = subprocess.run(["z3", "-in", "-T:%d" % max(int(timeout_s), 1)],
                             input=script, capture_output=True, text=True,
                             timeout=timeout_s + 30)
    except subprocess.SubprocessError:
        return "unknown", None
    lines = [line.strip() for line in (run.stdout or "").splitlines() if line.strip()]
    if not lines:
        return "unknown", None
    verdict = lines[0]
    if verdict == "unsat":
        return "unsat", None
    if verdict != "sat":
        return "unknown", None
    # z3 prints the model across several lines as `((r0 0)\n (r1 1) ...)`, so
    # the pairs are found by pattern rather than by line shape.
    body = " ".join(lines[1:])
    model: dict[int, int] = {}
    for name, value in re.findall(r"\br(\d+)\s+(-?\d+)", body):
        model[int(name)] = int(value)
    return ("sat", model) if model else ("unknown", None)


def certificate(cdg: SharedResourceCDG, *, cross_check_solver: bool = True
                ) -> dict[str, Any]:
    """The full artifact: witness, SMT source, and the solver's independent word.

    ``acyclic`` is only true when the witness verifies AND (if a solver is
    present) the solver agrees. A contradiction is an error, not a downgrade.
    """
    proof = prove_acyclic(cdg)
    if proof is None:
        return {
            "acyclic": False,
            "proof": None,
            "smtlib": emit_smtlib(cdg),
            "solver": "not-asked",
            "reason": "no rank exists for this graph, so it has a cycle",
        }
    verified = True
    try:
        verify_rank_witness(cdg, proof)
    except SharedResourceCDGProofError:  # pragma: no cover - internal bug guard
        verified = False
    solver_state, model = ("not-asked", None)
    if cross_check_solver:
        solver_state, model = check_with_solver(cdg)
        if solver_state == "unsat":
            raise SharedResourceCDGProofError(
                "the solver proves no rank exists but this module produced one: "
                "refusing to report an acyclicity claim two checkers disagree on")
        if solver_state == "sat" and model is not None:
            reranked = {node: model[index]
                        for (node, index) in _node_index(cdg).items()
                        if index in model}
            if len(reranked) != cdg.node_count:
                raise SharedResourceCDGProofError(
                    "the solver returned a partial rank model; refusing it")
            verify_rank_witness(cdg, reranked)
    return {
        "acyclic": bool(verified),
        "proof": proof.as_dict(),
        "smtlib": emit_smtlib(cdg),
        "solver": solver_state,
        "reason": "every dependency edge strictly increases the rank",
    }


__all__ = [
    "AcyclicityProof", "PROOF_METHOD", "SharedResourceCDGProofError",
    "SHARED_RESOURCE_CDG_PROOF_SCHEMA_VERSION", "certificate",
    "check_with_solver", "emit_smtlib", "prove_acyclic", "solver_available",
    "topological_rank", "verify_rank_witness",
]
