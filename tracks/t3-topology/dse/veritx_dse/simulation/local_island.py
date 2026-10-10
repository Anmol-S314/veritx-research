"""Bounded deterministic local-island reference execution; no physical timing.

No speculative switch allocation is modeled: failed admission spends nothing.
Credits are independent of tokens. A served slot remains credit-in-flight until
its explicit return edge; zero latency returns before admission on that edge.
Admission never feeds the same edge's service, regardless of latency/slots.
"""
from collections import deque

from veritx_dse.core.artifact import FrozenMap
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.local_island import LocalIslandContract, IslandOffer, ratio


def simulate_local_island(contract, offers, horizon_cycles):
    if type(contract) is not LocalIslandContract:
        raise UnsupportedSemantics("explicit abstract local island contract is required; placement is not timing")
    exact_int("horizon_cycles", horizon_cycles, 1)
    if type(offers) is not tuple or any(type(o) is not IslandOffer for o in offers):
        raise InvalidInput("offers must be a tuple of IslandOffer")
    # Bound both emitted snapshots and straightforward FIFO admission work.
    if horizon_cycles * (len(offers) + len(contract.queues) + len(contract.buckets)) > 1_000_000:
        raise UnsupportedSemantics("abstract local island trace exceeds one million work units")
    if len({o.offer_id for o in offers}) != len(offers):
        raise InvalidInput("offer identities must be unique")
    configs = {q.endpoint_id: q for q in contract.queues}
    buckets = {b.traffic_class: b for b in contract.buckets}
    for offer in offers:
        if offer.endpoint_id not in configs or offer.traffic_class not in buckets:
            raise InvalidInput("offer references undeclared endpoint or traffic class")
    ordered = sorted(offers, key=lambda o: (o.arrival_cycle, o.offer_id))
    upstream = {eid: deque(o for o in ordered if o.endpoint_id == eid) for eid in configs}
    queues = {eid: deque() for eid in configs}
    credits = {eid: q.capacity_flits for eid, q in configs.items()}
    returns = {eid: deque() for eid in configs}
    tokens = {cls: b.initial_tokens for cls, b in buckets.items()}
    admitted, delivered, snapshots = [], [], []
    token_debits = {cls: 0 for cls in buckets}
    for cycle in range(horizon_cycles):
        for eid in configs:
            while returns[eid] and returns[eid][0] <= cycle:
                returns[eid].popleft()
                credits[eid] += 1
        if cycle:
            for cls, bucket in buckets.items():
                tokens[cls] = min(bucket.burst, tokens[cls] + bucket.rate)
        for eid, config in configs.items():
            slots = config.service_slots[cycle % len(config.service_slots)]
            for _ in range(min(slots, len(queues[eid]))):
                offer = queues[eid].popleft()
                delivered.append({"offer_id": offer.offer_id, "cycle": cycle})
                if config.credit_latency_cycles == 0:
                    credits[eid] += 1
                else:
                    returns[eid].append(cycle + config.credit_latency_cycles)
        blocked = []
        for eid in configs:  # Contract requires sorted endpoint IDs.
            while upstream[eid] and upstream[eid][0].arrival_cycle <= cycle:
                offer = upstream[eid][0]
                reasons = []
                if not credits[eid]:
                    reasons.append("NO_CREDIT")
                if tokens[offer.traffic_class] < 1:
                    reasons.append("NO_TOKEN")
                if reasons:
                    blocked.append({"offer_id": offer.offer_id, "reasons": reasons})
                    break  # Explicit head-of-line FIFO; no class bypass.
                upstream[eid].popleft()
                queues[eid].append(offer)
                credits[eid] -= 1
                tokens[offer.traffic_class] -= 1
                token_debits[offer.traffic_class] += 1
                admitted.append({"offer_id": offer.offer_id, "cycle": cycle})
        state = []
        for eid, config in configs.items():
            if (credits[eid] + len(queues[eid]) + len(returns[eid]) != config.capacity_flits
                    or credits[eid] < 0 or len(queues[eid]) > config.capacity_flits):
                raise EvidenceInvalid("local island credit/capacity conservation failed")
            state.append({"endpoint_id": eid, "occupancy": len(queues[eid]),
                          "credits": credits[eid], "credits_in_flight": len(returns[eid])})
        if (len(offers) != sum(map(len, upstream.values())) + sum(map(len, queues.values())) + len(delivered)
                or len(admitted) != sum(map(len, queues.values())) + len(delivered)):
            raise EvidenceInvalid("local island flit conservation failed")
        for cls, bucket in buckets.items():
            if not 0 <= tokens[cls] <= bucket.burst or token_debits[cls] > bucket.initial_tokens + cycle * bucket.rate:
                raise EvidenceInvalid("local island token bounds/envelope failed")
        snapshots.append({"cycle": cycle, "queues": state, "blocked_heads": blocked,
                          "tokens": {cls: ratio(t) for cls, t in tokens.items()}})
    pending = [{"offer_id": o.offer_id, "state": "NOT_YET_ARRIVED" if o.arrival_cycle >= horizon_cycles else "UPSTREAM_BACKPRESSURED"}
               for eid in configs for o in upstream[eid]]
    pending.extend({"offer_id": o.offer_id, "state": "ATTACH_QUEUE"} for eid in configs for o in queues[eid])
    in_flight = sum(map(len, returns.values()))
    return FrozenMap({"status": "COMPLETE" if not pending and not in_flight else "INCOMPLETE",
                      "horizon_cycles": horizon_cycles, "offered_flits": len(offers),
                      "admitted_flits": len(admitted), "delivered_flits": len(delivered),
                      "credits_in_flight": in_flight, "payload_completed": not pending,
                      "admissions": admitted, "deliveries": delivered, "pending": pending,
                      "token_debits": token_debits, "snapshots": snapshots})
