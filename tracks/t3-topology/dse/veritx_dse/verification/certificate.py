"""veritx_dse.verification.certificate — resolved-fabric verification (P1.4).

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from typing import Any

from veritx_dse.core.errors import VeritXError
from veritx_dse.model.gec_hybrid_route import GecHybridRoute

CERTIFICATE_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/VerificationCertificate"

class CertificateError(ValueError, SemanticError):
    """A fabric failed certification, or a certificate is malformed."""

_SEMANTIC_ERRORS: tuple[type[BaseException], ...] = (VeritXError,)

OBLIGATIONS = (
    "TOPOLOGY_CONNECTED",
    "ATTACHMENT_COMPLETE",
    "ADDRESS_DECODE_VALID",
    "ROUTE_COMPLETE",
    "ROUTE_LEGAL",
    "VC_ASSIGNMENT_VALID",
    "DEADLOCK_FREE",
    "MAPPING_VALID",
    "PACKET_FORMAT_VALID",
    "FABRIC_DAG_VALID",
)

@dataclass(frozen=True)
class ObligationResult:
    obligation: str
    status: str
    method: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        from copy import deepcopy
        return {
            "obligation": self.obligation,
            "status": self.status,
            "method": self.method,
            "evidence": deepcopy(self.evidence),
        }

def _pass(obligation: str, method: str,
          evidence: dict[str, Any]) -> ObligationResult:
    return ObligationResult(obligation, "PASS", method, evidence)

def _fail(obligation: str, method: str, reason: str,
          evidence: dict[str, Any] | None = None) -> ObligationResult:
    ev = dict(evidence or {})
    ev["failure_reason"] = reason
    return ObligationResult(obligation, "FAIL", method, ev)

def _hash_of(obj: Any, name: str) -> str:
    """Read a child-artifact hash that may be a method (RT v1) or a
    stored attribute (canonical v2). Identity comes from the child;
    this shim only normalizes the accessor."""
    value = getattr(obj, name)
    return value() if callable(value) else value

def _topology_connected(bundle: Any) -> ObligationResult:
    topo = bundle.topology
    routers = [r.router_id for r in topo.routers]
    adj: dict[int, set[int]] = {r: set() for r in routers}
    for ch in topo.channels:
        adj[ch.src_router].add(ch.dst_router)
        adj[ch.dst_router].add(ch.src_router)
    # A shared wire connects its driver to every tap: it is one edge per tap,
    # not a direction, and it is the ONLY edge in an all-express fabric.
    # Ignoring it reported a fully connected fabric as 16 isolated routers.
    for link in getattr(topo, "shared_links", ()):
        for tap in link.taps:
            adj[link.src_router].add(tap)
            adj[tap].add(link.src_router)
    components = 0
    seen: set[int] = set()
    for r in routers:
        if r in seen:
            continue
        components += 1
        stack = [r]
        seen.add(r)
        while stack:
            u = stack.pop()
            for v in adj[u]:
                if v not in seen:
                    seen.add(v)
                    stack.append(v)
    ev = {"routers": len(routers),
          "directed_channels": len(topo.channels),
          "shared_wires": len(getattr(topo, "shared_links", ())),
          "components": components}
    if not routers or components != 1:
        return _fail("TOPOLOGY_CONNECTED", "undirected-bfs/v1",
                     "router graph is not one connected component", ev)
    isolated = [r for r in routers if not adj[r]]
    if isolated and len(routers) > 1:
        return _fail("TOPOLOGY_CONNECTED", "undirected-bfs/v1",
                     f"isolated routers {isolated}", ev)
    return _pass("TOPOLOGY_CONNECTED", "undirected-bfs/v1", ev)

def _attachment_complete(bundle: Any) -> ObligationResult:
    try:
        bundle.attachment.validate_against(
            bundle.design, bundle.inventory, bundle.topology)
    except _SEMANTIC_ERRORS as exc:
        return _fail("ATTACHMENT_COMPLETE",
                     "attachment.validate_against/v1", str(exc),
                     {"endpoints": len(bundle.attachment.endpoints)})
    return _pass("ATTACHMENT_COMPLETE", "attachment.validate_against/v1",
                 {"endpoints": len(bundle.attachment.endpoints)})

def _address_decode_valid(bundle: Any) -> ObligationResult:
    try:
        bundle.address_decode.validate_against(
            bundle.design.address_map, bundle.attachment)
    except _SEMANTIC_ERRORS as exc:
        return _fail("ADDRESS_DECODE_VALID",
                     "address_decode.validate_against/v1", str(exc),
                     {"entries": len(bundle.address_decode.entries)})
    return _pass("ADDRESS_DECODE_VALID",
                 "address_decode.validate_against/v1",
                 {"entries": len(bundle.address_decode.entries)})

def _is_shared_route(route: Any) -> bool:
    from veritx_dse.model.route_artifact_v3 import (
        RouteArtifactV3, ShapePolicyRoute,
    )
    from veritx_dse.model.srota_rank_route import RankPolicyRoute
    return isinstance(route, (RouteArtifactV3, ShapePolicyRoute,
                              RankPolicyRoute, GecHybridRoute))


def _shared_route_pairs(route: Any) -> Any:
    """The (src, dst) pairs a shared-wire route covers, either shape."""
    from veritx_dse.model.route_artifact_v3 import ShapePolicyRoute
    from veritx_dse.model.srota_rank_route import RankPolicyRoute
    if isinstance(route, (ShapePolicyRoute, RankPolicyRoute, GecHybridRoute)):
        return route.choices
    return route.decisions


def _route_classes(route: Any) -> list[str]:
    """The routing class ids of a route, whichever schema version it is.

    v2 carries a tuple of RoutingClassDefinition; v3 carries one id because a
    shared-resource realization is per class. The identity of the obligation
    evidence must not change shape between the two, so this returns the ids
    either way.
    """
    if _is_shared_route(route):
        return [route.routing_class]
    return [d.id for d in route.routing_classes]


def _route_complete(bundle: Any) -> ObligationResult:
    route = bundle.router_route
    classes = _route_classes(route)
    n = bundle.topology.router_count
    if _is_shared_route(route):
        # A v3 table is keyed by destination TERMINAL, not by router, so its
        # coverage is router x terminal. Counting router x router here would
        # demand a table the route never claimed to be.
        nodes = len(route.terminal_to_router)
        expected = len(classes) * n * nodes
    else:
        expected = len(classes) * n * (n - 1)
    got = len(_shared_route_pairs(route)) if _is_shared_route(route) \
        else len(route.entries)
    ev = {"routing_classes": classes, "routers": n,
          "expected_entries": expected, "entries": got}
    if got != expected:
        return _fail("ROUTE_COMPLETE", "entry-coverage/v1",
                     f"{got} entries != {expected} required", ev)
    return _pass("ROUTE_COMPLETE", "entry-coverage/v1", ev)

def _route_legal(bundle: Any) -> ObligationResult:
    try:
        bundle.router_route.validate_against(bundle.topology)
    except _SEMANTIC_ERRORS as exc:
        return _fail("ROUTE_LEGAL", "route.validate_against/v1",
                     str(exc), {})
    return _pass("ROUTE_LEGAL", "route.validate_against/v1",
                 {"routing_classes": _route_classes(bundle.router_route)})

def _vc_assignment_valid(bundle: Any) -> ObligationResult:
    try:
        bundle.vc_assignment.validate_against(bundle.resolved_route)
    except _SEMANTIC_ERRORS as exc:
        return _fail("VC_ASSIGNMENT_VALID",
                     "vc.validate_against/v1", str(exc),
                     {"vc_count": bundle.vc_assignment.vc_count})
    return _pass("VC_ASSIGNMENT_VALID", "vc.validate_against/v1",
                 {"vc_count": bundle.vc_assignment.vc_count,
                  "vc_to_routing_class": [
                      list(p) for p in
                      bundle.vc_assignment.vc_to_routing_class]})

def _scc_count(adj: dict[Any, list[Any]]) -> int:
    """Iterative Tarjan SCCs with >1 node (deterministic, no recursion)."""
    index_of: dict[Any, int] = {}
    low: dict[Any, int] = {}
    on_stack: set[Any] = set()
    stack: list[Any] = []
    counter = [0]
    big = [0]

    for root in sorted(adj, key=repr):
        if root in index_of:
            continue
        work: list[tuple[Any, int]] = [(root, 0)]
        while work:
            node, child_i = work[-1]
            if child_i == 0 and node not in index_of:
                index_of[node] = low[node] = counter[0]
                counter[0] += 1
                stack.append(node)
                on_stack.add(node)
            children = sorted(adj.get(node, []), key=repr)
            if child_i < len(children):
                work[-1] = (node, child_i + 1)
                child = children[child_i]
                if child not in index_of:
                    work.append((child, 0))
                elif child in on_stack:
                    low[node] = min(low[node], index_of[child])
            else:
                work.pop()
                if work:
                    parent = work[-1][0]
                    low[parent] = min(low[parent], low[node])
                if low[node] == index_of[node]:
                    size = 0
                    while True:
                        w = stack.pop()
                        on_stack.discard(w)
                        size += 1
                        if w == node:
                            break
                    if size > 1:
                        big[0] += 1
    return big[0]

def _deadlock_free_shared(bundle: Any) -> ObligationResult:
    """DEADLOCK_FREE for a fabric whose wires are shared (one driver, many taps).

    Evidence shape deliberately mirrors the point-to-point obligation
    (verdict + bound parent hashes + the cycle when there is one), because a
    reviewer should not have to learn two vocabularies to see that the same
    question was answered.
    """
    from veritx_dse.verification.shared_resource_deadlock import (
        verify_shared_resource_deadlock,
    )
    route = bundle.router_route
    rank_evidence = {}
    from veritx_dse.model.srota_rank_route import RankPolicyRoute
    if isinstance(route, RankPolicyRoute):
        try:
            from veritx_dse.model.compile_model import fabric_intent_view
            from veritx_dse.model.routing import derive_route
            expected = derive_route(request=fabric_intent_view(bundle.design),
                                    topology=bundle.topology)
            if (not isinstance(expected, RankPolicyRoute)
                    or route.canonical_dict() != expected.canonical_dict()):
                raise CertificateError("rank route differs from parent-recomputed admitted walks")
            route.validate_against(bundle.topology)
            va = bundle.vc_assignment
            # The route's allowed_transitions are the RANK policy's
            # (non-decreasing rank pairs); the VC ASSIGNMENT's are the
            # identity transitions it actually carries. Compare each to its
            # own vocabulary — conflating them fails every rank design.
            if (va.vc_count != sum(len(vcs) for vcs in expected.partition_to_vcs.values())
                    or va.allowed_transitions != tuple(
                        (vc, vc) for vc in range(va.vc_count))
                    or va.vc_ids != tuple(range(va.vc_count))
                    or va.escape_vcs):
                raise CertificateError("rank VC assignment differs from the declared envelope")
        except _SEMANTIC_ERRORS as exc:
            return _fail("DEADLOCK_FREE", "shared-resource-cdg/v1", str(exc))
    if isinstance(route, GecHybridRoute):
        from veritx_dse.verification.gec_hybrid_instance import prove_gec_hybrid_instance
        try:
            route.validate_against(bundle.topology)
            va = bundle.vc_assignment
            if (va.vc_count != route.params.num_vcs
                    or va.allowed_transitions != route.allowed_transitions
                    or va.escape_vcs
                    or any(vcs != tuple(range(va.vc_count))
                           for _cls, vcs in va.traffic_class_to_vcs)):
                raise CertificateError("hybrid VC assignment differs from the phase/tap envelope")
            proof = prove_gec_hybrid_instance(route.params, bundle.topology)
            graph = route.shared_resource_cdg()
            if graph.nodes != proof.graph.nodes or graph.edges != proof.graph.edges:
                raise CertificateError("hybrid route graph differs from the ranked candidate union")
            rank_evidence = {"rank_proof_id": proof.proof_id(),
                             "rank_proof_method": proof.to_dict()["proof_method"],
                             "scope": proof.to_dict()["scope"]}
        except _SEMANTIC_ERRORS as exc:
            return _fail("DEADLOCK_FREE", "gec-hybrid-ranked-union/v1", str(exc))
    verdict = verify_shared_resource_deadlock(route)
    ev = {
        "verdict": verdict.verdict,
        "proof_method": verdict.proof_method,
        "route_artifact_id": verdict.route_artifact_id,
        "routing_class": verdict.routing_class,
        "nodes": verdict.node_count,
        "edges": verdict.edge_count,
        "cycle": [[str(resource), vc] for resource, vc in verdict.cycle],
        "reason": verdict.reason,
        "topology_hash": bundle.topology.topology_hash(),
        "attachment_hash": bundle.attachment.attachment_hash(),
        "router_route_hash": route.route_artifact_id(),
        "resolved_route_hash": bundle.resolved_route.resolved_route_hash(),
        "vc_assignment_hash": bundle.vc_assignment.vc_assignment_hash(),
        "router_behavior_hash": _hash_of(
            getattr(bundle, "router_behavior", None),
            "router_behavior_hash"),
        **rank_evidence,
    }
    method = "gec-hybrid-ranked-union/v1" if rank_evidence else "shared-resource-cdg/v1"
    if verdict.verdict != "PASS":
        return _fail("DEADLOCK_FREE", method, verdict.reason, ev)
    return _pass("DEADLOCK_FREE", method, ev)


def _deadlock_free(bundle: Any) -> ObligationResult:
    from veritx_dse.verification.channel_vc_cdg import (
        certify_channel_vc_deadlock,
    )
    if _is_shared_route(bundle.router_route):
        # A shared wire has no channel id and no single destination, so the
        # (channel, vc) graph cannot describe it — the point-to-point
        # certifier refuses such a topology by design. The proof is the same
        # OBLIGATION over the shared-resource graph instead, recorded under
        # its own method name so the two are never confused.
        return _deadlock_free_shared(bundle)
    try:
        router_behavior = getattr(bundle, "router_behavior", None)
        behavior_hash = _hash_of(router_behavior, "router_behavior_hash")
        cert = certify_channel_vc_deadlock(
            topology=bundle.topology,
            resolved_route=bundle.resolved_route,
            router_route=bundle.router_route,
            vc_assignment=bundle.vc_assignment,
            router_behavior_hash=behavior_hash,
        )
        ev = dict(cert.evidence)
        ev["topology_hash"] = cert.topology_hash
        ev["attachment_hash"] = cert.attachment_hash
        ev["router_route_hash"] = cert.router_route_hash
        ev["resolved_route_hash"] = cert.resolved_route_hash
        ev["vc_assignment_hash"] = cert.vc_assignment_hash
        ev["router_behavior_hash"] = cert.router_behavior_hash
        if cert.verdict != "PASS":
            return _fail("DEADLOCK_FREE", "channel-vc-cdg/v2",
                         f"CDG verdict {cert.verdict}: "
                         f"{ev.get('unsupported_reason', ev.get('cycle', ''))}",
                         ev)
        from veritx_dse.verification.channel_vc_cdg import (
            build_channel_vc_cdg,
        )
        cdg = build_channel_vc_cdg(
            bundle.topology, bundle.router_route, bundle.vc_assignment)
        ev["sccs_gt_1"] = _scc_count(cdg.adjacency())
    except _SEMANTIC_ERRORS as exc:
        return _fail("DEADLOCK_FREE", "channel-vc-cdg/v2", str(exc), {})
    return _pass("DEADLOCK_FREE", "channel-vc-cdg/v2", ev)

def _mapping_valid(bundle: Any) -> ObligationResult:
    attached = {(e.agent.group_index, e.agent.instance_index,
                 e.agent.kind) for e in bundle.attachment.endpoints}
    placements = list(bundle.mapping.placements)
    ranks = sorted(p.rank for p in placements)
    ev = {"placements": len(placements)}
    if ranks != list(range(len(placements))):
        return _fail("MAPPING_VALID", "mapping-attachment-seam/v1",
                     f"ranks {ranks} are not contiguous from 0", ev)
    for p in placements:
        key = (p.agent.group_index, p.agent.instance_index,
               p.agent.kind)
        if key not in attached:
            return _fail(
                "MAPPING_VALID", "mapping-attachment-seam/v1",
                f"rank {p.rank} maps to unattached agent "
                f"{p.agent.instance_id}", ev)
    return _pass("MAPPING_VALID", "mapping-attachment-seam/v1", ev)

def _packet_format_valid(bundle: Any) -> ObligationResult:
    try:
        from veritx_dse.model.vc_resource import (
            vc_resources_from_assignment,
        )
        bundle.packet_format.validate_against(
            bundle.topology, bundle.attachment,
            vc_resources_from_assignment(bundle.vc_assignment))
    except _SEMANTIC_ERRORS as exc:
        return _fail("PACKET_FORMAT_VALID",
                     "packet_format.validate_against/v1", str(exc),
                     {"flit_width_bits":
                      bundle.packet_format.flit_width_bits})
    return _pass("PACKET_FORMAT_VALID",
                 "packet_format.validate_against/v1",
                 {"flit_width_bits": bundle.packet_format.flit_width_bits,
                  "vc_count": bundle.vc_assignment.vc_count})

def _fabric_dag_valid(bundle: Any) -> ObligationResult:
    try:
        bundle.revalidate()
    except _SEMANTIC_ERRORS as exc:
        return _fail("FABRIC_DAG_VALID", "bundle.revalidate/v1",
                     f"{type(exc).__name__}: {exc}", {})
    return _pass("FABRIC_DAG_VALID", "bundle.revalidate/v1",
                 bundle.root_hashes())

_OBLIGATION_RUNNERS = (
    _topology_connected,
    _attachment_complete,
    _address_decode_valid,
    _route_complete,
    _route_legal,
    _vc_assignment_valid,
    _deadlock_free,
    _mapping_valid,
    _packet_format_valid,
    _fabric_dag_valid,
)

@dataclass(frozen=True)
class VerificationCertificate:
    """One certified fabric: obligations with evidence, content-addressed."""

    resolved_fabric_hash: str
    compiler_semantics_version: int
    obligations: tuple[ObligationResult, ...]
    overall: str
    schema_version: int = CERTIFICATE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.overall not in ("PASS", "FAIL"):
            raise CertificateError(
                f"overall must be PASS or FAIL, got {self.overall!r}")
        got = [o.obligation for o in self.obligations]
        if sorted(got) != sorted(OBLIGATIONS):
            raise CertificateError(
                f"certificate must carry exactly {sorted(OBLIGATIONS)}, "
                f"got {sorted(got)}")
        if self.overall == "PASS" and \
                any(o.status != "PASS" for o in self.obligations):
            raise CertificateError(
                "overall PASS with a non-PASS obligation — refusing a "
                "contradictory certificate")
        for o in self.obligations:
            if o.status not in ("PASS", "FAIL"):
                raise CertificateError(
                    f"obligation {o.obligation} status {o.status!r} "
                    f"is not PASS/FAIL")

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "resolved_fabric_hash": self.resolved_fabric_hash,
            "compiler_semantics_version": self.compiler_semantics_version,
            "overall": self.overall,
            "obligations": [o.to_dict() for o in self.obligations],
        }

    @property
    def design_binding(self) -> dict[str, Any] | None:
        """Optional V5 structural binding; legacy certificate identity is unchanged."""
        from copy import deepcopy
        dag = next(o for o in self.obligations if o.obligation == "FABRIC_DAG_VALID")
        return deepcopy(dag.evidence.get("v5_design_binding"))

    def certificate_id(self) -> str:
        import hashlib
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return "sha256:" + hashlib.sha256(body.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {**self.identity_dict(),
                "certificate_id": self.certificate_id()}

    @classmethod
    def from_dict(cls, d: Any) -> "VerificationCertificate":
        allowed = {"type", "schema_version", "resolved_fabric_hash",
                   "compiler_semantics_version", "overall", "obligations",
                   "certificate_id"}
        unknown = set(d) - allowed
        if unknown:
            raise CertificateError(
                f"certificate has unknown fields {sorted(unknown)}")
        if d.get("type") != _HASH_TYPE_TAG:
            raise CertificateError(
                f"certificate type {d.get('type')!r} is not "
                f"{_HASH_TYPE_TAG!r}")
        if d.get("schema_version") != CERTIFICATE_SCHEMA_VERSION:
            raise CertificateError("unsupported certificate schema_version")
        obligations = tuple(
            ObligationResult(o["obligation"], o["status"], o["method"],
                             dict(o["evidence"]))
            for o in d.get("obligations", []))
        cert = cls(resolved_fabric_hash=d["resolved_fabric_hash"],
                   compiler_semantics_version=d[
                       "compiler_semantics_version"],
                   obligations=obligations, overall=d["overall"])
        if d.get("certificate_id") != cert.certificate_id():
            raise CertificateError(
                "certificate_id does not match content — refusing a "
                "re-signed certificate")
        return cert

def verify_compiled_fabric(bundle: Any) -> VerificationCertificate:
    """Run every LOCKED obligation over a resolved bundle."""
    from veritx_dse.model.compile_model import COMPILER_SEMANTICS_VERSION
    results = tuple(run(bundle) for run in _OBLIGATION_RUNNERS)
    overall = "PASS" if all(
        o.status == "PASS" for o in results) else "FAIL"
    return VerificationCertificate(
        resolved_fabric_hash=_hash_of(
            bundle.resolved_fabric, "resolved_fabric_hash"),
        compiler_semantics_version=COMPILER_SEMANTICS_VERSION,
        obligations=results, overall=overall)

def _v5_design_binding(request: Any, bundle: Any, *, clock_domains: Any,
                       sideband_set: Any, access_policy: Any) -> dict[str, Any]:
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    from veritx_dse.model.domain_intent import materialize_clock_domains
    from veritx_dse.model.sideband import materialize_sidebands
    if not isinstance(request, CompileRequestV5):
        raise CertificateError("V5 binding requires a CompileRequestV5")
    # Revalidate the complete root, including cross-references. Never rely on
    # an earlier constructor check over potentially mutated nested content.
    checked = CompileRequestV5.from_dict(request.to_dict())
    if checked.base_v4.design_hash() != bundle.design.design_hash():
        raise CertificateError("V5 base design does not match the compiled fabric")
    supported = {"sideband_interfaces", "sideband_connections", "access_policy",
                 "clock_sources", "clock_domains"}
    unbound = [name for name, value in checked.canonical_dict().items()
               if name != "base_v4" and name not in supported and value]
    if unbound:
        raise CertificateError(f"V5 extensions have no structural binding: {sorted(unbound)}")
    expected_clocks = (materialize_clock_domains(checked.clock_sources, checked.clock_domains)
                       if checked.clock_sources or checked.clock_domains else None)
    expected_sidebands = (materialize_sidebands(
        checked.sideband_interfaces, checked.sideband_connections,
        agent_universe=tuple(f"group:{i}" for i in range(len(checked.base_v4.agents))))
        if checked.sideband_interfaces or checked.sideband_connections else None)
    hashes = {}
    for name, actual, expected, hash_name in (
            ("clock_domains", clock_domains, expected_clocks, "content_hash"),
            ("sideband_set", sideband_set, expected_sidebands, "content_hash"),
            ("access_policy", access_policy, checked.access_policy, "policy_hash")):
        if expected is None:
            if actual is not None:
                raise CertificateError(f"undeclared V5 {name} output")
            hashes[name] = None
        else:
            if type(actual) is not type(expected) or actual.to_dict() != expected.to_dict():
                raise CertificateError(f"V5 {name} output differs from declared intent")
            hashes[name] = getattr(actual, hash_name)
    return {
        "design_hash": checked.design_hash(),
        "base_design_hash": checked.base_v4.design_hash(),
        "resolved_fabric_hash": _hash_of(bundle.resolved_fabric, "resolved_fabric_hash"),
        "extensions": hashes,
        "scope": "DECLARED_V5_EXTENSION_STRUCTURE_ONLY",
        "execution_semantics": "NOT_MODELED",
        "limitations": "No clock-to-agent assignment, CDC, multi-rate timing, sideband execution or access enforcement proof.",
    }


def verify_v5_compilation(request: Any, bundle: Any, *, clock_domains: Any = None,
                          sideband_set: Any = None, access_policy: Any = None
                          ) -> VerificationCertificate:
    """Bind a V5 root and its exact emitted records to the verified base DAG.

    The ten existing obligations remain. FABRIC_DAG_VALID additionally checks
    extension preservation/structure; its evidence is part of certificate ID.
    This does not promote declarative records into backend execution semantics.
    """
    from dataclasses import replace
    from veritx_dse.model.compile_request_v5 import CompileRequestV5
    if not isinstance(request, CompileRequestV5):
        raise CertificateError("V5 certification requires a CompileRequestV5")
    base = verify_compiled_fabric(bundle)
    results = []
    for result in base.obligations:
        if result.obligation == "FABRIC_DAG_VALID":
            evidence = dict(result.evidence)
            try:
                evidence["v5_design_binding"] = _v5_design_binding(
                    request, bundle, clock_domains=clock_domains,
                    sideband_set=sideband_set, access_policy=access_policy)
                result = replace(result, method="fabric-and-v5-intent-binding/v1",
                                 evidence=evidence)
            except _SEMANTIC_ERRORS as exc:
                result = _fail("FABRIC_DAG_VALID", "fabric-and-v5-intent-binding/v1",
                               str(exc), evidence)
        results.append(result)
    return VerificationCertificate(
        resolved_fabric_hash=base.resolved_fabric_hash,
        compiler_semantics_version=request.compiler_semantics_version,
        obligations=tuple(results),
        overall="PASS" if all(o.status == "PASS" for o in results) else "FAIL")


__all__ = [
    "CERTIFICATE_SCHEMA_VERSION", "OBLIGATIONS", "ObligationResult",
    "VerificationCertificate", "CertificateError",
    "verify_compiled_fabric", "verify_v5_compilation",
]
