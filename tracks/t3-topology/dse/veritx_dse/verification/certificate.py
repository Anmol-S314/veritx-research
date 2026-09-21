"""veritx_dse.verification.certificate — resolved-fabric verification (P1.4).

Before a fabric is called "compiled", it is certified. A
VerificationCertificate binds the resolved fabric to one verdict per
LOCKED obligation, each with its method and evidence digests — never
a generic {"verified": true}.

Obligations (P1A slice):

    TOPOLOGY_CONNECTED   underlying router graph is one component
    ATTACHMENT_COMPLETE  every design agent is attached (seats proven)
    ADDRESS_DECODE_VALID decode realizes the design address map
    ROUTE_COMPLETE       route table covers every class×src×dst pair
    ROUTE_LEGAL          every route is channel-legal and terminates
    VC_ASSIGNMENT_VALID  VC structure binds the resolved route
    DEADLOCK_FREE        (channel,VC) CDG is acyclic (typed proof)
    MAPPING_VALID        every mapped rank lands on an attached agent
    PACKET_FORMAT_VALID  wire format fits topology/attachment/VC bounds
    FABRIC_DAG_VALID     full hardware + design/mapping seam revalidates

A LOCKED obligation that is not PASS means the fabric is not
presented as compile success: the FabricCompiler returns INVALID
with this certificate as evidence. No obligation may be skipped,
downgraded, or satisfied by assumption.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

CERTIFICATE_SCHEMA_VERSION = 1
_HASH_TYPE_TAG = "srota/VerificationCertificate"


class CertificateError(ValueError):
    """A fabric failed certification, or a certificate is malformed."""


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
    status: str  # PASS or FAIL only
    method: str
    evidence: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "obligation": self.obligation,
            "status": self.status,
            "method": self.method,
            "evidence": dict(self.evidence),
        }


def _pass(obligation: str, method: str,
          evidence: dict[str, Any]) -> ObligationResult:
    return ObligationResult(obligation, "PASS", method, evidence)


def _fail(obligation: str, method: str, reason: str,
          evidence: dict[str, Any] | None = None) -> ObligationResult:
    ev = dict(evidence or {})
    ev["failure_reason"] = reason
    return ObligationResult(obligation, "FAIL", method, ev)


def _topology_connected(bundle: Any) -> ObligationResult:
    topo = bundle.topology
    routers = [r.router_id for r in topo.routers]
    adj: dict[int, set[int]] = {r: set() for r in routers}
    for ch in topo.channels:
        adj[ch.src_router].add(ch.dst_router)
        adj[ch.dst_router].add(ch.src_router)
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
    except Exception as exc:
        return _fail("ATTACHMENT_COMPLETE",
                     "attachment.validate_against/v1", str(exc),
                     {"endpoints": len(bundle.attachment.endpoints)})
    return _pass("ATTACHMENT_COMPLETE", "attachment.validate_against/v1",
                 {"endpoints": len(bundle.attachment.endpoints)})


def _address_decode_valid(bundle: Any) -> ObligationResult:
    try:
        bundle.address_decode.validate_against(
            bundle.design.address_map, bundle.attachment)
    except Exception as exc:
        return _fail("ADDRESS_DECODE_VALID",
                     "address_decode.validate_against/v1", str(exc),
                     {"entries": len(bundle.address_decode.entries)})
    return _pass("ADDRESS_DECODE_VALID",
                 "address_decode.validate_against/v1",
                 {"entries": len(bundle.address_decode.entries)})


def _route_complete(bundle: Any) -> ObligationResult:
    route = bundle.router_route
    classes = [d.id for d in route.routing_classes]
    n = bundle.topology.router_count
    expected = len(classes) * n * (n - 1)
    got = len(route.entries)
    ev = {"routing_classes": classes, "routers": n,
          "expected_entries": expected, "entries": got}
    if got != expected:
        return _fail("ROUTE_COMPLETE", "entry-coverage/v1",
                     f"{got} entries != {expected} required", ev)
    return _pass("ROUTE_COMPLETE", "entry-coverage/v1", ev)


def _route_legal(bundle: Any) -> ObligationResult:
    try:
        bundle.router_route.validate_against(bundle.topology)
    except Exception as exc:
        return _fail("ROUTE_LEGAL", "route.validate_against/v1",
                     str(exc), {})
    return _pass("ROUTE_LEGAL", "route.validate_against/v1",
                 {"routing_classes": [d.id for d in
                                      bundle.router_route.routing_classes]})


def _vc_assignment_valid(bundle: Any) -> ObligationResult:
    try:
        bundle.vc_assignment.validate_against(bundle.resolved_route)
    except Exception as exc:
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


def _deadlock_free(bundle: Any) -> ObligationResult:
    from veritx_dse.verification.channel_vc_cdg import (
        certify_channel_vc_deadlock,
    )
    try:
        router_behavior = getattr(bundle, "router_behavior", None)
        behavior_hash = router_behavior.router_behavior_hash()
        cert = certify_channel_vc_deadlock(
            topology=bundle.topology,
            resolved_route=bundle.resolved_route,
            router_route=bundle.router_route,
            vc_assignment=bundle.vc_assignment,
            router_behavior_hash=behavior_hash,
        )
    except Exception as exc:
        return _fail("DEADLOCK_FREE", "channel-vc-cdg/v1", str(exc), {})
    ev = dict(cert.evidence)
    # Preserve the authenticated parent identities in the obligation
    # evidence itself: the DeadlockCertificate object is dropped after
    # this function returns, so without these the certificate would name
    # a deadlock verdict it cannot tie to the exact artifacts proven.
    ev["topology_hash"] = cert.topology_hash
    ev["attachment_hash"] = cert.attachment_hash
    ev["router_route_hash"] = cert.router_route_hash
    ev["resolved_route_hash"] = cert.resolved_route_hash
    ev["vc_assignment_hash"] = cert.vc_assignment_hash
    ev["router_behavior_hash"] = cert.router_behavior_hash
    if cert.verdict != "PASS":
        return _fail("DEADLOCK_FREE", "channel-vc-cdg/v1",
                     f"CDG verdict {cert.verdict}: "
                     f"{ev.get('unsupported_reason', ev.get('cycle', ''))}",
                     ev)
    try:
        from veritx_dse.verification.channel_vc_cdg import (
            build_channel_vc_cdg,
        )
        cdg = build_channel_vc_cdg(
            bundle.topology, bundle.router_route, bundle.vc_assignment)
        ev["sccs_gt_1"] = _scc_count(cdg.adjacency())
    except Exception:
        pass
    return _pass("DEADLOCK_FREE", "channel-vc-cdg/v1", ev)


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
        bundle.packet_format.validate_against(
            bundle.topology, bundle.attachment, bundle.vc_assignment)
    except Exception as exc:
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
    except Exception as exc:
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
    overall: str  # PASS or FAIL only
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
        resolved_fabric_hash=bundle.resolved_fabric.resolved_fabric_hash(),
        compiler_semantics_version=COMPILER_SEMANTICS_VERSION,
        obligations=results, overall=overall)


__all__ = [
    "CERTIFICATE_SCHEMA_VERSION", "OBLIGATIONS", "ObligationResult",
    "VerificationCertificate", "CertificateError",
    "verify_compiled_fabric",
]
