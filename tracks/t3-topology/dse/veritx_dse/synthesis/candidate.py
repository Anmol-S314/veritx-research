"""veritx_dse.synthesis.candidate — TopologyCandidate and the MILP adapter.

Rationale: docs/decisions/modules/synthesis.md
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

GENERATION_STATUSES = (
    "SUCCEEDED", "INFEASIBLE", "UNSUPPORTED", "FAILED", "TIMED_OUT",
)

SOLVER_STATUSES = ("OPTIMAL", "FEASIBLE", "INFEASIBLE", "UNBOUNDED",
                   "TIME_LIMIT", "UNKNOWN")

ALGORITHMS = ("milp_tmcf", "sa_geodesic", "rho_iterative", "grpo_group",
               "bo_gp")

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
    return "FEASIBLE" if getattr(res, "x", None) is not None else "UNKNOWN"

@dataclass(frozen=True)
class TopologyCandidate:
    """One generated topology graph with its provenance.

Rationale: docs/decisions/modules/synthesis.md
    """

    definition_id: str
    traffic_id: str
    links: tuple[tuple[int, int], ...]
    nodes: int
    algorithm: str
    solver_status: str
    objective_value: float | None
    objective_name: str
    status: str
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
        if self.solver_status == "OPTIMAL" and self.status != "SUCCEEDED":
            raise TopologyCandidateError(
                "OPTIMAL requires a produced graph")
        if self.solver_status == "OPTIMAL" and self.objective_value is None:
            raise TopologyCandidateError(
                "OPTIMAL requires an objective value to be optimal about")

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

def _assert_objective_is_honest(defn: SynthesisDefinition,
                                algorithm: str) -> None:
    """`priced_geodesic` must never be accepted by a path that cannot use it.

    The TMCF MILP minimizes traffic-weighted hops; it has no notion of pipe or
    wire price. Accepting `priced_geodesic` there hashed a distinct design
    identity while producing the byte-identical graph as `geodesic` — two
    designs, one artifact. Refusing is the honest behaviour.
    """
    if defn.objective == "priced_geodesic" and algorithm != "sa_geodesic":
        raise TopologyCandidateError(
            f"objective {defn.objective!r} requires the SA engine, but this "
            f"definition selects {algorithm!r} (nodes {defn.nodes} <= "
            f"max_nodes {defn.max_nodes}). Raise max_nodes=None/lower nodes "
            "to use SA, or use objective 'geodesic'.")

def synthesize(defn: SynthesisDefinition,
               traffic: SynthesisTrafficMatrix,
               *,
               engine_module: Any = None) -> TopologyCandidate:
    """Run the MILP/TMCF generator and return a canonical candidate.

Rationale: docs/decisions/modules/synthesis.md
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

    _assert_objective_is_honest(
        defn, "sa_geodesic" if defn.nodes > defn.max_nodes else "milp_tmcf")

    T = np.array([list(r) for r in traffic.values], dtype=float)
    xy = _layout_xy(defn)
    cand_links = engine.valid_links(xy, defn.max_len)
    base_edges = engine.base_mesh(xy, radix=defn.radix)

    if defn.nodes > defn.max_nodes:
        priced = defn.objective == "priced_geodesic"
        if priced:
            engine.set_costs(defn.pipe_cost, defn.wire_cost)
        try:
            adj, best = engine.sa_synthesize(
                T, xy, base_edges, cand_links, defn.radix,
                seed=defn.layout_seed, priced=priced)
        except Exception as exc:                            # noqa: BLE001
            return TopologyCandidate(
                definition_id=defn.definition_id(),
                traffic_id=traffic.traffic_id(), nodes=defn.nodes, links=(),
                algorithm="sa_geodesic", solver_status="UNKNOWN",
                objective_value=None, objective_name=defn.objective,
                status="FAILED",
                producer_id=f"{PRODUCER_ID}#{type(exc).__name__}")
        chosen_sa = tuple(sorted({(min(a, b), max(a, b))
                                  for a in adj for b in adj[a] if a < b}))
        if not chosen_sa:
            return TopologyCandidate(
                definition_id=defn.definition_id(),
                traffic_id=traffic.traffic_id(), nodes=defn.nodes, links=(),
                algorithm="sa_geodesic", solver_status="UNKNOWN",
                objective_value=None, objective_name=defn.objective,
                status="FAILED", producer_id=PRODUCER_ID)
        return TopologyCandidate(
            definition_id=defn.definition_id(),
            traffic_id=traffic.traffic_id(), nodes=defn.nodes,
            links=chosen_sa, algorithm="sa_geodesic",
            solver_status="FEASIBLE", objective_value=float(best),
            objective_name=defn.objective, status="SUCCEEDED",
            producer_id=PRODUCER_ID)

    try:
        res, all_links, Lidx, dem, dir_edges, eid, L, F, E, xv, fv = \
            engine.solve_tmcf(T, xy, base_edges, cand_links, defn.radix,
                              defn.timeout_s, defn.max_nodes)
    except Exception as exc:
        return TopologyCandidate(
            definition_id=defn.definition_id(), traffic_id=traffic.traffic_id(),
            nodes=defn.nodes, links=(), algorithm="milp_tmcf",
            solver_status="UNKNOWN", objective_value=None,
            objective_name="traffic_weighted_hops", status="FAILED",
            producer_id=f"{PRODUCER_ID}#{type(exc).__name__}")

    status = _solver_status(res)
    if getattr(res, "x", None) is None:
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

PROMOTION_PROVENANCE_KEY = "synthesis_provenance"

#: Recognition boundary: these families have exact edge-set generators, so a
#: candidate can be PROVEN equal to them. Every other shape stays an explicit
#: graph — never a heuristic "mesh-like" promotion.
RECOGNIZABLE_FAMILIES = (
    "mesh", "torus", "dragonfly", "fat_tree", "flattened_butterfly",
    "qtree", "tree4",
)

#: Routing policy an irregular promoted graph executes under. Verified: an
#: explicit graph materializes to MaterializedFamily.CUSTOM, whose policy is
#: ANYNET_MIN_HOPS (model.routing._POLICY_BY_FAMILY). Stated, not inferred.
IRREGULAR_ROUTING_POLICY = "ANYNET_MIN_HOPS"

def _family_intent(family: str, params: dict[str, Any]):
    """Build the canonical intent for an exactly-recognized family.

    Imports are local: synthesis must not become an import-time dependent
    of the model layer. Raises TopologyCandidateError for a family this
    promotion path cannot construct (a second mapping would be a second
    authority — the constructors below ARE the mapping)."""
    from veritx_dse.model import topology_intent as ti
    if family == "mesh":
        return ti.MeshIntent(**params)
    if family == "torus":
        return ti.TorusIntent(**params)
    return ti.StructuredTopologyIntent(family=family, params=dict(params))

def promote_to_explicit_topology(
        candidate: TopologyCandidate,
        definition: SynthesisDefinition,
        *,
        name: str | None = None,
        expected_candidate_id: str | None = None,
        concentration: int | None = None,
) -> dict[str, Any]:
    """Promote a candidate into ORDINARY design intent.

    Exact family recognition runs first: when the candidate graph is
    edge-set-equal to a canonical family, the promotion carries that
    family's intent (structure EXACT) so native routing, projection and
    qualification apply downstream. Anything else promotes as an explicit
    graph (structure IRREGULAR) executing under ANYNET_MIN_HOPS.

    `concentration` is REQUIRED for a mesh/torus family promotion: a
    candidate carries a router graph only, so the endpoints-per-router
    must be stated, never assumed. Without it a mesh-shaped candidate
    still promotes — as explicit topology, with the recognized family
    recorded alongside the reason family promotion was withheld.
    Structured families carry no concentration (their params are complete
    by construction), so they promote directly.

Rationale: docs/decisions/modules/synthesis.md
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
    if concentration is not None and (
            type(concentration) is not int or concentration < 1):
        raise TopologyCandidateError(
            f"concentration must be a positive int, got "
            f"{concentration!r}")

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
    round_tripped = TopologyCandidate.from_dict(candidate.to_dict())
    if round_tripped.candidate_id() != candidate.candidate_id():
        raise TopologyCandidateError(
            "candidate does not re-verify against its own serialized form")

    from veritx_dse.model.topology_artifact import recognize_family
    recognized = recognize_family(candidate.nodes, candidate.links)
    family_intent = None
    withheld_reason: str | None = None
    if recognized is not None:
        family, params = recognized
        assert family in RECOGNIZABLE_FAMILIES, family
        if family in ("mesh", "torus") and concentration is None:
            withheld_reason = (
                f"graph is exactly {family} {params}, but concentration "
                "was not stated: a candidate carries a router graph only, "
                "so family promotion would have to assume "
                "endpoints-per-router. Promoting as explicit topology.")
        else:
            if family in ("mesh", "torus"):
                assert concentration is not None
                params = {**params, "concentration": concentration}
            try:
                family_intent = _family_intent(family, params)
            except Exception as exc:
                # The graph IS the canonical family, but the intent type
                # rejects these parameters (e.g. degenerate tiers). The
                # promotion still proceeds as explicit topology — the exact
                # graph is preserved — with the recognition and the reason
                # recorded instead of silently dropping the match.
                withheld_reason = (
                    f"graph is exactly {family} {params}, but the family "
                    f"intent does not construct ({exc}); promoting as "
                    "explicit topology.")

    ir = to_topology_ir(candidate, definition)
    if name:
        from veritx_dse.model import topology_ir as tir
        ir = tir.from_dict({**ir.to_dict(), "name": name})

    # Structure is about the GRAPH (exact edge-set equality); the intent is
    # about what the compiler can declare. A degenerate exact match (tiers
    # too low for the intent type) is still exactly that family, routed as
    # explicit topology until the taxonomy admits it.
    structure = "EXACT" if recognized is not None else "IRREGULAR"
    provenance = {
        "candidate_id": candidate.candidate_id(),
        "graph_id": candidate.graph_id(),
        "definition_id": candidate.definition_id,
        "traffic_id": candidate.traffic_id,
        "producer": candidate.producer_dict(),
        "promotion_schema_version": 2,
        "structure": structure,
        "recognized_family": (
            {"family": recognized[0], "params": recognized[1]}
            if recognized is not None else None),
        "routing_policy": (
            None if family_intent is not None
            else IRREGULAR_ROUTING_POLICY),
        "withheld_reason": withheld_reason,
    }
    return {"explicit_topology": ir,
            "family_intent": family_intent,
            "provenance": provenance}

def apply_promotion_to_request_doc(request_doc: dict[str, Any],
                                   promotion: dict[str, Any]
                                   ) -> dict[str, Any]:
    """Attach a promotion to a CompileRequest document.

    The topology goes into the SCIENTIFIC field; the synthesis provenance
    goes into a NON-scientific linkage field. Keeping them apart is what
    makes a promoted design and the identical manual design the same
    design science.

    An exactly-recognized family promotes as the family intent: on a v4
    document the `topology` authority carries it and any explicit topology
    is cleared, so the design compiles under native routing instead of
    ANYNET_MIN_HOPS. Anything else promotes as explicit topology exactly
    as before. The input document is never mutated.
    """
    out = dict(request_doc)
    out.pop("design_hash", None)
    out.pop("guardrail_hash", None)
    family_intent = promotion.get("family_intent")
    if family_intent is not None:
        if "topology" not in out:
            raise TopologyCandidateError(
                "family promotion needs a v4 request document with a "
                "`topology` authority field — refusing to downgrade an "
                "exactly-recognized family into a document that cannot "
                "carry it")
        out["topology"] = family_intent.to_dict()
        out.pop("explicit_topology", None)
    else:
        ir = promotion["explicit_topology"]
        out["explicit_topology"] = ir.to_dict()
        noc = dict(out.get("noc_config") or {})
        noc["topology_family"] = None
        out["noc_config"] = noc
    out[PROMOTION_PROVENANCE_KEY] = promotion["provenance"]
    return out
