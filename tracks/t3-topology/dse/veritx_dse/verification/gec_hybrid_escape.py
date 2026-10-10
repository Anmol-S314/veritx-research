"""NEW four-VC reference escape policy, not the native GEC VC allocation.

Concrete nodes identify a whole shared wire, never an individual tap. The
certificate proves structural accessibility/closure/termination only; eventual
escape selection, fair arbitration and available ejection credits are external
progress assumptions. No canonical or simulator policy is changed.
"""
from dataclasses import dataclass
from types import MappingProxyType
from collections import deque
from typing import Mapping

from veritx_dse.core.artifact import content_id
from veritx_dse.model.gec_hybrid_route import GecHybridParams, bound_gec_hybrid_candidates
from veritx_dse.model.shared_resource import RouteDecision
from veritx_dse.verification.shared_resource_cdg import SharedResourceCDG

PROFILE = "REFERENCE_GEC_SHARED_ESCAPE_V1"
PARTITION = (("ADAPTIVE_X", (0,)), ("ADAPTIVE_Y", (1,)),
             ("ESCAPE_X", (2,)), ("ESCAPE_Y", (3,)))
TRANSITIONS = ((0, 0), (0, 1), (1, 1), (0, 2), (0, 3),
               (1, 3), (2, 2), (2, 3), (3, 3))


def _relation(params, topology):
    candidates = bound_gec_hybrid_candidates(params, topology)
    # Injection from EVERY router to EVERY terminal, then concrete ingress
    # contexts reached by ANY adaptive or escape action (not a chosen trace).
    pending = deque((s, d, -1) for s in range(params.router_count)
                    for d in range(params.node_count))
    relation = {}
    while pending:
        key = pending.popleft()
        if key in relation:
            continue
        s, d, ingress = key
        hops = candidates[s, d]
        if not hops:
            relation[key] = ()  # explicit local ejection, no resource
            continue
        phase = hops[0].phase
        actions = []
        if ingress < 2:
            for hop in hops:
                vc = phase
                if ingress == -1 or (ingress, vc) in TRANSITIONS:
                    actions.append(RouteDecision(hop.resource, hop.next_router, vc, hop.tap))
        jump = next(h for h in hops if not h.is_mesh)
        vc = 2 + phase
        if ingress == -1 or (ingress, vc) in TRANSITIONS:
            actions.append(RouteDecision(jump.resource, jump.next_router, vc, jump.tap))
        if not actions:
            raise ValueError("reachable context has no legal escape action")
        relation[key] = tuple(actions)
        pending.extend((a.next_router, d, a.vc_partition) for a in actions)
    return relation


@dataclass(frozen=True)
class GecSharedEscape:
    params: GecHybridParams
    topology_hash: str
    partition: tuple[tuple[str, tuple[int, ...]], ...]
    transitions: tuple[tuple[int, int], ...]
    contexts: Mapping[tuple[int, int, int], tuple[RouteDecision, ...]]

    def __post_init__(self):
        if not isinstance(self.params, GecHybridParams) or not isinstance(self.topology_hash, str):
            raise ValueError("escape profile requires exact parent params/hash")
        if (type(self.partition) is not tuple or type(self.transitions) is not tuple or
                any(type(row) is not tuple or len(row) != 2 or type(row[0]) is not str or
                    type(row[1]) is not tuple or any(type(vc) is not int for vc in row[1])
                    for row in self.partition) or
                any(type(row) is not tuple or len(row) != 2 or any(type(vc) is not int for vc in row)
                    for row in self.transitions)):
            raise ValueError("escape partition/transitions require immutable exact integer domains")
        for key, actions in self.contexts.items():
            if (type(key) is not tuple or len(key) != 3 or any(type(v) is not int for v in key) or
                    type(actions) is not tuple or any(not isinstance(a, RouteDecision) for a in actions)):
                raise ValueError("escape contexts require exact immutable keys/actions")
        object.__setattr__(self, "contexts", MappingProxyType(dict(self.contexts)))

    def to_dict(self):
        return {"profile": PROFILE, "params": self.params.to_dict(),
                "topology_hash": self.topology_hash,
                "partition": [[name, list(vcs)] for name, vcs in self.partition],
                "transitions": [list(x) for x in self.transitions],
                "contexts": [[*key, [a.to_dict() for a in actions]]
                             for key, actions in sorted(self.contexts.items())]}

    def identity(self):
        return content_id(PROFILE, self.to_dict())

    def validate(self, topology):
        if self.topology_hash != topology.topology_hash():
            raise ValueError("escape topology hash mismatch")
        if self.partition != PARTITION or self.transitions != TRANSITIONS:
            raise ValueError("explicit disjoint role partition/transition mismatch")
        if self.contexts != _relation(self.params, topology):
            raise ValueError("escape contexts/actions differ from exhaustive concrete relation")


def build_gec_shared_escape(params, topology, *, partition, transitions):
    """Caller MUST explicitly declare the new resource partition/transitions.

    params.num_vcs describes the parent candidate geometry/tap allocation,
    NOT this separately declared four-VC resource universe.
    """
    profile = GecSharedEscape(params, topology.topology_hash(), partition,
                             transitions, _relation(params, topology))
    profile.validate(topology)
    return profile


def load_gec_shared_escape(value, params, topology):
    expected = build_gec_shared_escape(params, topology, partition=PARTITION,
                                      transitions=TRANSITIONS)
    # Exact canonical JSON comparison also rejects bool/int aliasing, unknown
    # keys, missing actions and self-consistently rehashed wrong tap records.
    import json
    if json.dumps(value, sort_keys=True) != json.dumps(expected.to_dict(), sort_keys=True):
        raise ValueError("serialized escape profile differs from actual parents")
    return expected


def verify_gec_shared_escape(profile, topology):
    profile.validate(topology)
    nodes, edges = set(), set()
    adaptive_contexts = 0
    for (s, d, ingress), actions in profile.contexts.items():
        if s == d // profile.params.c:
            if actions:
                raise ValueError("local ejection has outgoing actions")
            continue
        escape = [a for a in actions if a.vc_partition in (2, 3)]
        if len(escape) != 1:
            raise ValueError("every reachable context needs exactly one escape action")
        if ingress < 2:
            adaptive_contexts += 1
        elif len(actions) != 1:
            raise ValueError("escape role is not closed")
        if ingress != -1 and (ingress, escape[0].vc_partition) not in profile.transitions:
            raise ValueError("concrete ingress cannot enter escape")
        # Follow from this context, not just from injection. Limit/cycle checks
        # remain explicit even though this profile has at most two jumps.
        seen, path = set(), []
        key = (s, d, ingress)
        while key[0] != d // profile.params.c:
            if key in seen:
                raise ValueError("escape path loops")
            seen.add(key)
            action, = (a for a in profile.contexts[key] if a.vc_partition in (2, 3))
            node = (action.resource, action.vc_partition)
            nodes.add(node)
            if path:
                edges.add((path[-1], node))
            path.append(node)
            key = (action.next_router, d, action.vc_partition)
        if len(path) > 2:
            raise ValueError("escape path exceeds two shared jumps")
    graph = SharedResourceCDG(tuple(sorted(nodes)), tuple(sorted(edges)), {2: (2,), 3: (3,)})
    if graph.find_cycle() is not None:
        raise ValueError("escape concrete resource/VC union contains cycle")
    certificate = {"profile": PROFILE, "profile_id": profile.identity(),
                   "topology_hash": topology.topology_hash(), "verdict": "PASS",
                   "contexts": len(profile.contexts), "adaptive_contexts": adaptive_contexts,
                   "nodes": graph.node_count, "edges": graph.edge_count,
                   "scope": "NEW_REFERENCE_POLICY_ONLY_NOT_NATIVE_OR_QUALIFIED",
                   "progress_assumptions": ["eventual escape selection", "fair arbitration",
                                            "eventual sink credit availability"]}
    certificate["certificate_id"] = content_id(PROFILE + "/certificate", certificate)
    return certificate
