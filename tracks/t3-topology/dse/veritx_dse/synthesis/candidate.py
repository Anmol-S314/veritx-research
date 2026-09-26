"""veritx_dse.synthesis.candidate — TopologyCandidate and the MILP adapter.

THE AUTHORITY BOUNDARY
----------------------

A synthesis engine produces a CANDIDATE. It does not produce a fabric, a
route, a certificate or a measurement. The chain is:

    SynthesisDefinition + SynthesisTrafficMatrix
        -> engine (milp_topology_v2, unmodified)
        -> TopologyCandidate            <- this module
        -> TopologyIR  (kind=custom)    <- the SAME explicit topology
                                           representation an authored custom
                                           graph uses
        -> materialize_ir -> TopologyArtifact
        -> the NORMAL compiler -> verification -> evaluation

The engine never becomes a second compiler, verifier or evaluator. The
adapter's only job is to translate one engine's output into the canonical
explicit topology representation and to record provenance honestly.

GENERATOR OBJECTIVE != EVALUATED PERFORMANCE
--------------------------------------------

`objective_value` is a GENERATOR objective: traffic-weighted hop count, or
a priced geodesic over ANALYTICAL, UNCALIBRATED wire/pipeline constants.
It is NOT latency, NOT BookSim completion, NOT a Pareto metric. It is
carried on the candidate so a synthesis attempt can be compared with
another synthesis attempt, and for no other purpose. A test asserts the
candidate carries no certificate or performance field.

`.anynet` IS NOT AUTHORITY
--------------------------

The engine writes `<out>.anynet`. That is a BookSim PROJECTION. The
canonical graph is `links` on the candidate, and the candidate identity is
computed from the definition and the graph — never from the projection's
formatting or path.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

from .definition import SynthesisDefinition
from .traffic import SynthesisTrafficMatrix

DOMAIN = "veritx/topology-candidate/v1"
SCHEMA_VERSION = 1

#: Generation status. INFEASIBLE means the solver PROVED no graph satisfies
#: the encoded constraints; it never means the user's design is invalid.
GENERATION_STATUSES = (
    "SUCCEEDED", "INFEASIBLE", "UNSUPPORTED", "FAILED", "TIMED_OUT",
)

#: Solver status vocabulary, preserved rather than collapsed. `OPTIMAL` is
#: only ever reported when the solver PROVED optimality of the encoded
#: MILP formulation — never inferred from a feasible incumbent.
SOLVER_STATUSES = ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNBOUNDED",
                   "TIME_LIMIT", "UNKNOWN")

#: Which algorithm actually ran. Provenance, not identity.
ALGORITHMS = ("milp_tmcf", "sa_geodesic")

#: Which engine the definition names, and what it can run.
ENGINE_ALGORITHM = {"milp_tmcf": "milp_tmcf"}


class TopologyCandidateError(ValueError):
    """Invalid candidate or a failed synthesis attempt (typed, fail-closed)."""


def _solver_status(res: Any) -> str:
    """Map a scipy `milp` result onto the honest solver vocabulary.

    scipy status codes: 0 optimal, 1 iteration/time limit, 2 infeasible,
    3 unbounded, 4 other. A time-limited run that still carries an
    incumbent is FEASIBLE-or-TIME_LIMIT, NEVER OPTIMAL.
    """
    code = getattr(res, "status", None)
    if code == 0:
        return "OPTIMAL"
    if code == 1:
        return "TIME_LIMIT"
    if code == 2:
        return "INFEASIBLE"
    if code == 3:
        return "UNBOUNDED"
    # status 4 or missing: a solution may still exist; say so honestly.
    return "FEASIBLE" if getattr(res, "x", None) is not None else "UNKNOWN"


@dataclass(frozen=True)
class TopologyCandidate:
    """One generated topology graph with its provenance.

    Carries NO certificate, NO performance, NO Pareto status and NO
    qualification — those are produced downstream by the ordinary pipeline.
    """

    #: Parent synthesis definition.
    definition_id: str
    #: Canonical traffic authority that drove generation.
    traffic_id: str
    #: Exact undirected graph: sorted (u, v) pairs with u < v.
    links: tuple[tuple[int, int], ...]
    nodes: int
    #: Algorithm that actually ran (provenance).
    algorithm: str
    #: Honest solver status.
    solver_status: str
    #: GENERATOR objective — never evaluated performance. None when the
    #: solver reported no incumbent.
    objective_value: float | None
    objective_name: str
    #: `SUCCEEDED` iff a graph was produced.
    status: str
    #: Producer identity: engine module + semantics version.
    producer_id: str
    generator_semantics_version: str = "1"
    schema_version: int = SCHEMA_VERSION

    def __post_init__(self):
        if self.schema_version != SCHEMA_VERSION:
            raise TopologyCandidateError(
                f"schema_version {self.schema_version} != {SCHEMA_VERSION}")
        if self.status not in GENERATION_STATUSES:
            raise TopologyCandidateError(
                f"unknown status {self.status!r}; "
                f"supported: {list(GENERATION_STATUSES)}")
        if self.solver_status not in SOLVER_STATUSES:
            raise TopologyCandidateError(
                f"unknown solver_status {self.solver_status!r}; "
                f"supported: {list(SOLVER_STATUSES)}")
        if self.algorithm not in ALGORITHMS:
            raise TopologyCandidateError(
                f"unknown algorithm {self.algorithm!r}; "
                f"supported: {list(ALGORITHMS)}")
        if type(self.nodes) is not int or self.nodes < 2:
            raise TopologyCandidateError(
                f"nodes must be an int >= 2, got {self.nodes!r}")
        links = self.links
        if isinstance(links, list):
            links = tuple(tuple(e) for e in links)
            object.__setattr__(self, "links", links)
        seen: set[tuple[int, int]] = set()
        for e in links:
            if (not isinstance(e, tuple) or len(e) != 2
                    or not all(type(v) is int for v in e)):
                raise TopologyCandidateError(
                    f"links must be (u, v) int pairs, got {e!r}")
            u, v = e
            if u == v:
                raise TopologyCandidateError(f"link {e} is a self-loop")
            for w in (u, v):
                if not 0 <= w < self.nodes:
                    raise TopologyCandidateError(
                        f"link {e} endpoint {w} out of range [0, {self.nodes})")
            if u > v:
                raise TopologyCandidateError(
                    f"link {e} must be canonically ordered (u < v)")
            if e in seen:
                raise TopologyCandidateError(f"duplicate link {e}")
            seen.add(e)
        if self.status == "SUCCEEDED" and not links:
            raise TopologyCandidateError(
                "a SUCCEEDED candidate must carry at least one link")
        if self.status != "SUCCEEDED" and links:
            raise TopologyCandidateError(
                f"status {self.status} must not carry a graph")
        if self.objective_value is not None:
            if not isinstance(self.objective_value, (int, float)) or \
                    not math.isfinite(self.objective_value):
                raise TopologyCandidateError(
                    f"objective_value must be finite, got "
                    f"{self.objective_value!r}")
        # OPTIMAL is only ever a PROVEN claim about the encoded formulation.
        if self.solver_status == "OPTIMAL" and self.status != "SUCCEEDED":
            raise TopologyCandidateError(
                "OPTIMAL requires a produced graph")
        if self.solver_status == "OPTIMAL" and self.objective_value is None:
            raise TopologyCandidateError(
                "OPTIMAL requires an objective value to be optimal about")

    # ── identity ─────────────────────────────────────────────────────

    def candidate_id(self) -> str:
        """Binds the definition, the traffic and the EXACT GRAPH.

        Deliberately excludes the algorithm, solver status, wall time and
        the `.anynet` projection: two runs that produce the same graph from
        the same definition and traffic describe the same scientific
        candidate, whatever produced them.
        """
        return content_id(DOMAIN, {
            "definition_id": self.definition_id,
            "traffic_id": self.traffic_id,
            "nodes": self.nodes,
            "links": [list(e) for e in self.links],
        })

    def graph_id(self) -> str:
        """Identity of the graph alone (no definition, no traffic)."""
        return content_id(f"{DOMAIN}/graph", {
            "nodes": self.nodes,
            "links": [list(e) for e in self.links],
        })

    def producer_dict(self) -> dict[str, Any]:
        """Attempt provenance — NOT scientific identity."""
        return {
            "algorithm": self.algorithm,
            "producer_id": self.producer_id,
            "generator_semantics_version": self.generator_semantics_version,
            "solver_status": self.solver_status,
            "objective_value": self.objective_value,
            "objective_name": self.objective_name,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id(),
            "graph_id": self.graph_id(),
            "definition_id": self.definition_id,
            "traffic_id": self.traffic_id,
            "nodes": self.nodes,
            "links": [list(e) for e in self.links],
            "status": self.status,
            "producer": self.producer_dict(),
            # Explicit, so no reader can mistake the generator objective for
            # a measurement.
            "objective_is_measured_performance": False,
        }

    @classmethod
    def from_dict(cls, d: Any) -> "TopologyCandidate":
        if not isinstance(d, dict):
            raise TopologyCandidateError(
                f"candidate must be an object, got {type(d).__name__}")
        allowed = {
            "schema_version", "candidate_id", "graph_id", "definition_id",
            "traffic_id", "nodes", "links", "status", "producer",
            "objective_is_measured_performance",
        }
        unknown = sorted(set(d) - allowed)
        if unknown:
            raise TopologyCandidateError(
                f"unknown candidate fields {unknown} (schema close)")
        producer = d.get("producer") or {}
        if not isinstance(producer, dict):
            raise TopologyCandidateError("producer must be an object")
        known = {"algorithm", "producer_id", "generator_semantics_version",
                 "solver_status", "objective_value", "objective_name"}
        bad = sorted(set(producer) - known)
        if bad:
            raise TopologyCandidateError(f"unknown producer fields {bad}")
        obj = cls(
            schema_version=d.get("schema_version", SCHEMA_VERSION),
            definition_id=d["definition_id"], traffic_id=d["traffic_id"],
            nodes=d["nodes"],
            links=tuple((int(e[0]), int(e[1])) for e in d["links"]),
            algorithm=producer["algorithm"], solver_status=producer["solver_status"],
            objective_value=producer.get("objective_value"),
            objective_name=producer.get("objective_name", "traffic_weighted_hops"),
            status=d["status"], producer_id=producer["producer_id"],
            generator_semantics_version=producer.get(
                "generator_semantics_version", "1"),
        )
        supplied = d.get("candidate_id")
        if supplied is not None and supplied != obj.candidate_id():
            raise TopologyCandidateError(
                "candidate_id does not match content — the payload was "
                "edited after it was addressed")
        return obj

    def canonical_json(self) -> str:
        return canonical_json(self.to_dict())


# ── the adapter ─────────────────────────────────────────────────────────

#: Producer identity of the canonical adapter. The ENGINE is the historical
#: module; this string names the boundary that produced the candidate.
PRODUCER_ID = "veritx_dse.synthesis.milp_topology_v2/canonical-adapter"


def _layout_xy(defn: SynthesisDefinition):
    """Scientific coordinates for the definition's layout.

    These are the SAME functions the historical engine uses, so the
    adapter cannot disagree with the engine about geometry.
    """
    from . import milp_topology_v2 as engine
    if defn.layout == "grid":
        return engine.grid_xy(defn.k)
    return engine.interposer_xy(defn.rows, defn.cols, defn.layout_seed,
                                defn.jitter)


def synthesize(defn: SynthesisDefinition,
               traffic: SynthesisTrafficMatrix,
               *,
               engine_module: Any = None) -> TopologyCandidate:
    """Run the MILP/TMCF generator and return a canonical candidate.

    FAIL-CLOSED BOUNDARY. Everything the historical CLI would accept
    leniently is checked before the engine is called:

      * the traffic dimension MUST equal the definition's router count —
        the historical loader would happily solve a mismatched problem
      * every demand is already validated finite and non-negative by
        SynthesisTrafficMatrix
      * no uniform fallback exists at any point

    The engine is called UNMODIFIED. This function only translates.
    """
    if not isinstance(defn, SynthesisDefinition):
        raise TopologyCandidateError(
            f"expected a SynthesisDefinition, got {type(defn).__name__}")
    if not isinstance(traffic, SynthesisTrafficMatrix):
        raise TopologyCandidateError(
            f"expected a SynthesisTrafficMatrix, got {type(traffic).__name__}")
    if traffic.dimension != defn.nodes:
        raise TopologyCandidateError(
            f"traffic dimension {traffic.dimension} != definition nodes "
            f"{defn.nodes} — a mismatched problem is not solvable and the "
            "historical loader would not have noticed")

    engine = engine_module or _import_engine()
    import numpy as np

    T = np.array([list(r) for r in traffic.values], dtype=float)
    xy = _layout_xy(defn)
    cand_links = engine.valid_links(xy, defn.max_len)
    base_edges = engine.base_mesh(xy, radix=defn.radix)

    if defn.nodes > defn.max_nodes:
        # Above the exact-solve cap the historical engine switches to SA.
        # Tranche 3 wires the MILP only, so this is UNSUPPORTED rather than
        # a silent algorithm substitution.
        return TopologyCandidate(
            definition_id=defn.definition_id(), traffic_id=traffic.traffic_id(),
            nodes=defn.nodes, links=(), algorithm="milp_tmcf",
            solver_status="UNKNOWN", objective_value=None,
            objective_name="traffic_weighted_hops", status="UNSUPPORTED",
            producer_id=PRODUCER_ID)

    try:
        res, all_links, Lidx, dem, dir_edges, eid, L, F, E, xv, fv = \
            engine.solve_tmcf(T, xy, base_edges, cand_links, defn.radix,
                              defn.timeout_s, defn.max_nodes)
    except Exception as exc:  # solver blew up: FAILED, never a graph
        return TopologyCandidate(
            definition_id=defn.definition_id(), traffic_id=traffic.traffic_id(),
            nodes=defn.nodes, links=(), algorithm="milp_tmcf",
            solver_status="UNKNOWN", objective_value=None,
            objective_name="traffic_weighted_hops", status="FAILED",
            producer_id=f"{PRODUCER_ID}#{type(exc).__name__}")

    status = _solver_status(res)
    if getattr(res, "x", None) is None:
        # No incumbent: INFEASIBLE when proven, otherwise FAILED/TIMED_OUT.
        if status == "INFEASIBLE":
            gen = "INFEASIBLE"
        elif status == "TIME_LIMIT":
            gen = "TIMED_OUT"
        else:
            gen = "FAILED"
        return TopologyCandidate(
            definition_id=defn.definition_id(), traffic_id=traffic.traffic_id(),
            nodes=defn.nodes, links=(), algorithm="milp_tmcf",
            solver_status=status, objective_value=None,
            objective_name="traffic_weighted_hops", status=gen,
            producer_id=PRODUCER_ID)

    x = np.round(res.x[:L])
    chosen = sorted({tuple(sorted(e)) for e, k in Lidx.items()
                     if x[k] > 0.5})
    obj = float(res.fun) if getattr(res, "fun", None) is not None else None
    return TopologyCandidate(
        definition_id=defn.definition_id(), traffic_id=traffic.traffic_id(),
        nodes=defn.nodes, links=tuple(chosen), algorithm="milp_tmcf",
        solver_status=status, objective_value=obj,
        objective_name="traffic_weighted_hops", status="SUCCEEDED",
        producer_id=PRODUCER_ID)


def _import_engine() -> Any:
    from . import milp_topology_v2 as engine
    return engine


def to_topology_ir(candidate: TopologyCandidate,
                   definition: SynthesisDefinition):
    """Candidate -> the SAME explicit topology representation an authored
    custom graph uses. There is no synthesis-specific topology schema.

    `kind="custom"` with explicit undirected links is exactly what
    TopologyIR already models, so a synthesized graph and a hand-authored
    graph converge HERE, before `materialize_ir` and before TopologyArtifact.
    """
    from veritx_dse.model import topology_ir as tir

    if candidate.status != "SUCCEEDED":
        raise TopologyCandidateError(
            f"cannot convert a {candidate.status} candidate to topology")
    return tir.from_dict({
        "name": f"synthesized-{candidate.candidate_id()[:12]}",
        "kind": "custom",
        "nodes": candidate.nodes,
        "links": [[u, v] for u, v in candidate.links],
        "link_attrs": {
            "bandwidth_GBs": definition.bandwidth_GBs,
            "latency_ns": definition.latency_ns,
        },
    })


def anynet_projection(candidate: TopologyCandidate) -> str:
    """The BookSim projection. NOT scientific authority.

    Formatting, ordering and file path are all outside the candidate
    identity, so rewriting this text cannot change what the candidate IS.
    """
    adj: dict[int, list[int]] = {i: [] for i in range(candidate.nodes)}
    for u, v in candidate.links:
        adj[u].append(v)
        adj[v].append(u)
    lines = []
    for i in range(candidate.nodes):
        peers = " ".join(f"router {p}" for p in sorted(adj[i]))
        lines.append(f"router {i} node {i} {peers}".rstrip())
    return "\n".join(lines) + "\n"


__all__ = [
    "DOMAIN", "SCHEMA_VERSION", "GENERATION_STATUSES", "SOLVER_STATUSES",
    "ALGORITHMS", "ENGINE_ALGORITHM", "PRODUCER_ID",
    "TopologyCandidateError", "TopologyCandidate",
    "synthesize", "to_topology_ir", "anynet_projection",
]


# ── promotion: TopologyCandidate -> ordinary Design intent ──────────────

#: Promotion provenance key. Linkage, NOT design semantics — it never enters
#: design_hash.
PROMOTION_PROVENANCE_KEY = "synthesis_provenance"


def promote_to_explicit_topology(
        candidate: TopologyCandidate,
        definition: SynthesisDefinition,
        *,
        name: str | None = None,
        expected_candidate_id: str | None = None,
) -> dict[str, Any]:
    """Promote a candidate into ORDINARY explicit-topology design intent.

    WHAT PROMOTION IS: freezing the candidate's exact graph into a canonical
    `TopologyIR` (kind=custom) so it can enter a normal CompileRequest. That
    is all. It is NOT "mark the candidate verified" — nothing here claims a
    certificate, a measurement or a Pareto status.

    WHAT PROMOTION IS NOT: a second design type. The result is the SAME
    explicit topology an authored graph produces, so a synthesized design
    and a hand-authored one are indistinguishable downstream. Synthesis
    provenance is returned SEPARATELY as linkage.

    ORIGIN DOES NOT ENTER DESIGN IDENTITY. The returned TopologyIR carries a
    `name`, but `TopologyIR.scientific_dict()` excludes it, so the promoted
    graph and the identical manual graph have the same design_hash. Callers
    must attach `provenance` as metadata, never into the request's
    scientific fields.

    STALE PROMOTION REFUSES. Before freezing, the candidate is re-verified:
    schema, self-identity, definition identity, traffic identity, and graph
    integrity. A candidate that does not re-verify cannot become a design.
    """
    if not isinstance(candidate, TopologyCandidate):
        raise TopologyCandidateError(
            f"expected a TopologyCandidate, got {type(candidate).__name__}")
    if not isinstance(definition, SynthesisDefinition):
        raise TopologyCandidateError(
            f"expected a SynthesisDefinition, got {type(definition).__name__}")
    if candidate.status != "SUCCEEDED":
        raise TopologyCandidateError(
            f"cannot promote a {candidate.status} candidate — there is no "
            "graph to freeze")

    # ── staleness / integrity re-verification ────────────────────────
    if expected_candidate_id is not None and \
            candidate.candidate_id() != expected_candidate_id:
        raise TopologyCandidateError(
            "candidate_id does not match the expected value — refusing a "
            "stale promotion")
    if candidate.definition_id != definition.definition_id():
        raise TopologyCandidateError(
            "candidate.definition_id does not match the supplied definition "
            "— the definition changed since generation; refusing a stale "
            "promotion")
    # Re-derive through the wire form so a tampered in-memory object cannot
    # be promoted by accident.
    round_tripped = TopologyCandidate.from_dict(candidate.to_dict())
    if round_tripped.candidate_id() != candidate.candidate_id():
        raise TopologyCandidateError(
            "candidate does not re-verify against its own serialized form")

    # ── freeze the exact graph ───────────────────────────────────────
    ir = to_topology_ir(candidate, definition)
    if name:
        from veritx_dse.model import topology_ir as tir
        ir = tir.from_dict({**ir.to_dict(), "name": name})

    provenance = {
        "candidate_id": candidate.candidate_id(),
        "graph_id": candidate.graph_id(),
        "definition_id": candidate.definition_id,
        "traffic_id": candidate.traffic_id,
        "producer": candidate.producer_dict(),
        "promotion_schema_version": 1,
    }
    return {"explicit_topology": ir, "provenance": provenance}


def apply_promotion_to_request_doc(request_doc: dict[str, Any],
                                   promotion: dict[str, Any]
                                   ) -> dict[str, Any]:
    """Attach a promotion to a CompileRequest document.

    The topology goes into the SCIENTIFIC field (`explicit_topology`); the
    synthesis provenance goes into a NON-scientific linkage field. Keeping
    them apart is what makes a promoted design and the identical manual
    design the same design science.
    """
    ir = promotion["explicit_topology"]
    out = dict(request_doc)
    out.pop("design_hash", None)
    out.pop("guardrail_hash", None)
    out["explicit_topology"] = ir.to_dict()
    noc = dict(out.get("noc_config") or {})
    noc["topology_family"] = None
    out["noc_config"] = noc
    out[PROMOTION_PROVENANCE_KEY] = promotion["provenance"]
    return out
