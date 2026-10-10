"""Explicit ABSTRACT_LOCAL_ISLAND_V1 contract, not native SROTA semantics.

This new model owns only a single island router's local attach queues. Rates
are exact flits/model-cycle, not physical clocks. Buckets are shared by class
across the declared endpoints on that router. Empty queues start with capacity
credits. Each offer is one flit; no packet, side buffer or fabric is modeled.
All timing/capacity inputs are mandatory; placement never supplies defaults.
"""
from dataclasses import dataclass
from fractions import Fraction

from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.model.resource_graph import exact_int
from veritx_dse.model.topology_artifact import TopologyArtifact, MaterializedFamily
from veritx_dse.model.attachment import AgentAttachmentArtifact

PROFILE = "ABSTRACT_LOCAL_ISLAND_V1"
SEMANTICS = {
    "unit": "FLITS_PER_ABSTRACT_MODEL_CYCLE",
    "bucket_scope": "ROUTER_TRAFFIC_CLASS",
    "initial_state": "EMPTY_QUEUES_FULL_CAPACITY_CREDITS",
    "edge_order": "RETURNS_REFILL_SERVICE_ADMIT_SNAPSHOT",
    "refill": "NO_REFILL_AT_CYCLE_ZERO_CAP_AT_BURST",
    "service": "FIFO_EXISTING_QUEUE_PERIODIC_ENDPOINT_SLOTS",
    "admission": "ENDPOINT_ID_ORDER_FIFO_ARRIVAL_THEN_OFFER_ID",
    "debit": "ONE_TOKEN_AND_CREDIT_ONLY_ON_ADMISSION_NO_RESERVATION",
    "credit": "SERVICE_CYCLE_PLUS_LATENCY_ZERO_BEFORE_ADMIT_NO_REPEAT_SERVICE",
    "horizon": "CYCLES_ZERO_INCLUSIVE_HORIZON_EXCLUSIVE_NO_IMPLICIT_DRAIN",
}


def record(doc, fields, name):
    if type(doc) is not dict or set(doc) != set(fields):
        raise InvalidInput(f"{name} requires exactly {sorted(fields)}")


def name(value, label):
    if type(value) is not str or not value:
        raise InvalidInput(f"{label} must be a nonempty string")


def ratio(value):
    return {"numerator": value.numerator, "denominator": value.denominator}


def fraction(doc):
    record(doc, {"numerator", "denominator"}, "exact fraction")
    exact_int("numerator", doc["numerator"])
    exact_int("denominator", doc["denominator"], 1)
    value = Fraction(doc["numerator"], doc["denominator"])
    if ratio(value) != doc:
        raise InvalidInput("fraction must be reduced")
    return value


@dataclass(frozen=True)
class IslandBucket:
    traffic_class: str
    rate: Fraction
    burst: Fraction
    initial_tokens: Fraction

    def __post_init__(self):
        name(self.traffic_class, "traffic_class")
        for field in ("rate", "burst", "initial_tokens"):
            value = getattr(self, field)
            if type(value) is not Fraction or value < 0:
                raise InvalidInput(f"{field} must be a nonnegative exact Fraction")
        if self.burst < 1 or self.initial_tokens > self.burst:
            raise InvalidInput("burst must hold a flit and initial tokens must fit burst")

    def to_dict(self):
        return {"traffic_class": self.traffic_class, "rate": ratio(self.rate),
                "burst": ratio(self.burst), "initial_tokens": ratio(self.initial_tokens)}

    @classmethod
    def from_dict(cls, doc):
        record(doc, {"traffic_class", "rate", "burst", "initial_tokens"}, "bucket")
        return cls(doc["traffic_class"], fraction(doc["rate"]), fraction(doc["burst"]),
                   fraction(doc["initial_tokens"]))


@dataclass(frozen=True)
class IslandAttachQueue:
    endpoint_id: int
    capacity_flits: int
    service_slots: tuple[int, ...]
    credit_latency_cycles: int

    def __post_init__(self):
        exact_int("endpoint_id", self.endpoint_id)
        exact_int("capacity_flits", self.capacity_flits, 1)
        exact_int("credit_latency_cycles", self.credit_latency_cycles)
        if type(self.service_slots) is not tuple or not self.service_slots:
            raise InvalidInput("service_slots must be a nonempty periodic tuple")
        for slots in self.service_slots:
            exact_int("service slot", slots)

    def to_dict(self):
        return {"endpoint_id": self.endpoint_id, "capacity_flits": self.capacity_flits,
                "service_slots": list(self.service_slots),
                "credit_latency_cycles": self.credit_latency_cycles}

    @classmethod
    def from_dict(cls, doc):
        record(doc, {"endpoint_id", "capacity_flits", "service_slots", "credit_latency_cycles"}, "queue")
        if type(doc["service_slots"]) is not list:
            raise InvalidInput("service_slots must be a list")
        return cls(doc["endpoint_id"], doc["capacity_flits"], tuple(doc["service_slots"]),
                   doc["credit_latency_cycles"])


@dataclass(frozen=True)
class LocalIslandContract:
    topology_hash: str
    attachment_hash: str
    router_id: int
    buckets: tuple[IslandBucket, ...]
    queues: tuple[IslandAttachQueue, ...]

    def __post_init__(self):
        name(self.topology_hash, "topology_hash")
        name(self.attachment_hash, "attachment_hash")
        exact_int("router_id", self.router_id)
        for values, typ, key in ((self.buckets, IslandBucket, "traffic_class"),
                                 (self.queues, IslandAttachQueue, "endpoint_id")):
            if type(values) is not tuple or not values or any(type(v) is not typ for v in values):
                raise InvalidInput("contract requires nonempty typed bucket and queue tuples")
            keys = [getattr(v, key) for v in values]
            if keys != sorted(set(keys)):
                raise InvalidInput(f"{key} records must be sorted and unique")

    def validate_against(self, topology, attachment, traffic_classes):
        if not isinstance(topology, TopologyArtifact) or not isinstance(attachment, AgentAttachmentArtifact):
            raise InvalidInput("canonical topology and attachment are required")
        if (topology.topology_hash() != self.topology_hash
                or attachment.attachment_hash() != self.attachment_hash
                or attachment.topology_hash != self.topology_hash):
            raise EvidenceInvalid("local island contract parent identity mismatch")
        if topology.family is not MaterializedFamily.SROTA:
            raise UnsupportedSemantics("local island model requires SROTA placement")
        routers = {r.router_id: r for r in topology.routers}
        router = routers.get(self.router_id)
        if router is None or len(router.coordinates) != 2 or router.coordinates[0] not in topology.island_columns:
            raise InvalidInput("router must be in a declared island column")
        endpoints = {e.endpoint_id: e for e in attachment.endpoints}
        for queue in self.queues:
            endpoint = endpoints.get(queue.endpoint_id)
            if endpoint is None or endpoint.router_id != self.router_id:
                raise InvalidInput("queue endpoint must attach to the declared local router")
            if endpoint.port_id >= router.seat_capacity:
                raise InvalidInput("endpoint is not a real local seat")
        if any(b.traffic_class not in traffic_classes for b in self.buckets):
            raise InvalidInput("bucket traffic class is not declared by the compiled fabric")

    def to_dict(self):
        return {"profile": PROFILE, "semantics": dict(SEMANTICS),
                "topology_hash": self.topology_hash, "attachment_hash": self.attachment_hash,
                "router_id": self.router_id, "buckets": [b.to_dict() for b in self.buckets],
                "queues": [q.to_dict() for q in self.queues]}

    def artifact_id(self):
        return content_id("veritx/LocalIslandContract/v1", self.to_dict())

    @classmethod
    def from_dict(cls, doc):
        record(doc, {"profile", "semantics", "topology_hash", "attachment_hash", "router_id", "buckets", "queues"}, "contract")
        if doc["profile"] != PROFILE or doc["semantics"] != SEMANTICS:
            raise UnsupportedSemantics("unsupported abstract local island semantics")
        if type(doc["buckets"]) is not list or type(doc["queues"]) is not list:
            raise InvalidInput("buckets and queues must be lists")
        return cls(doc["topology_hash"], doc["attachment_hash"], doc["router_id"],
                   tuple(IslandBucket.from_dict(b) for b in doc["buckets"]),
                   tuple(IslandAttachQueue.from_dict(q) for q in doc["queues"]))


@dataclass(frozen=True)
class IslandOffer:
    offer_id: str
    arrival_cycle: int
    endpoint_id: int
    traffic_class: str

    def __post_init__(self):
        name(self.offer_id, "offer_id")
        name(self.traffic_class, "traffic_class")
        exact_int("arrival_cycle", self.arrival_cycle)
        exact_int("endpoint_id", self.endpoint_id)

    def to_dict(self):
        return {"offer_id": self.offer_id, "arrival_cycle": self.arrival_cycle,
                "endpoint_id": self.endpoint_id, "traffic_class": self.traffic_class}

    @classmethod
    def from_dict(cls, doc):
        record(doc, {"offer_id", "arrival_cycle", "endpoint_id", "traffic_class"}, "offer")
        return cls(**doc)
