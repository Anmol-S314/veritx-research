"""Compiled endpoint transaction/clock intent. Structural, not execution proof.

Group indices refer to the immutable V5 hardware base; endpoint identities come
only from its canonical attachment. No clock, policy, or crossing is inferred.
"""
from dataclasses import dataclass

from veritx_dse.core.artifact import FrozenMap, content_id, thaw
from veritx_dse.core.errors import UnsupportedSemantics


@dataclass(frozen=True)
class ExecutionContract:
    design_hash: str
    attachment_hash: str
    endpoints: tuple[FrozenMap, ...]
    crossings: tuple

    def to_dict(self):
        return {"type": "veritx/ExecutionContract", "schema_version": 1,
                "design_hash": self.design_hash, "attachment_hash": self.attachment_hash,
                "endpoints": [thaw(e) for e in self.endpoints],
                "crossings": [c.to_dict() for c in self.crossings],
                "scope": "DECLARED_ENDPOINT_TRANSACTION_CLOCK_STRUCTURE_ONLY"}

    def artifact_id(self):
        return content_id("veritx/ExecutionContract/v1", self.to_dict())


def materialize_execution_contract(request, bundle):
    if not request.agent_intents and not request.crossings:
        return None
    if any(i.interface_role is not None for i in request.agent_intents):
        raise UnsupportedSemantics("agent interface roles have no attachment materializer")
    policies = {i.agent_group_index: i.transaction_policy for i in request.agent_intents}
    transaction_clocks = {i.agent_group_index: i.transaction_clock_domain for i in request.agent_intents}
    rows = tuple(FrozenMap({
        "endpoint_id": e.endpoint_id, "agent": e.agent.to_dict(),
        "router_id": e.router_id, "fabric_clock_domain": e.interface.clock_domain,
        "transaction_clock_domain": transaction_clocks.get(e.agent.group_index),
        "transaction_policy": policies[e.agent.group_index].to_dict()
        if policies.get(e.agent.group_index) is not None else None,
    }) for e in bundle.attachment.endpoints)
    return ExecutionContract(request.design_hash(), bundle.attachment.attachment_hash(),
                             rows, request.crossings)
