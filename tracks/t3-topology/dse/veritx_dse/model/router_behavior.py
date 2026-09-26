"""veritx_dse.model.router_behavior — canonical router microarchitecture.

``RouterBehaviorArtifact`` is the sole authority for **how a router behaves**
independent of any routing algorithm, RTL or simulator implementation: what
it buffers, how credits are interpreted, how output VCs are selected and
reused, how the switch is arbitrated, and what pipeline latency the
architecture has.

Its sole semantic parent is ``VCResourceArtifact``: the concrete VC universe
with traffic eligibility and the legal ``vc_in -> vc_out`` transition
relation. Router behavior knows how to handle whatever VC structure it is
given, without knowing a topology, wire format, route table, routing class,
routing role or backend. The same behavior may therefore be reused by
deterministic and adaptive routing systems that share the same concrete VC
resources.

It does NOT own:

    route tables or routing classes      (RouteArtifact)
    resolved endpoints                   (ResolvedRouteArtifact)
    VC ids or legal transitions          (VCResourceArtifact)
    packet bit positions                 (PacketFormatArtifact)
    routing candidate/priority semantics (RoutingPolicyDefinition,
                                          RoutingRelationArtifact)
    routing role->resource binding       (RoutingResourceBindingArtifact)
    channel/link latency                 (TopologyArtifact)
    backend sampling/seed knobs          (backend layer)

Hash domain is ``srota/RouterBehaviorArtifact/v3``. The version is
intentionally new: historical schema v1 conflated switch arbitration with
input-VC packet context (``packet_hold_policy``), and historical schema v2
was parented to the routing-specific ``VCAssignmentArtifact``. Canonical v3
binds the routing-independent ``VCResourceArtifact``. Historical
router-behavior hashes are deliberately not reproduced.

Three independent packet/switch semantics:

    hold_switch_for_packet = False
        the physical switch/crossbar is arbitrated per flit; a packet does
        not reserve the crossbar path until TAIL. It does NOT say anything
        about whether two packets may share one input VC's packet context.

    input_vc_packet_policy = ONE_PACKET_AT_A_TIME
        WITHIN one input VC, HEAD/SINGLE opens a packet context and
        BODY/TAIL belong to it; no second HEAD/SINGLE may begin there until
        the first packet closes. Packets in DIFFERENT VCs may still make
        interleaved progress through the switch.

    vc_allocation_scope = PACKET
        HEAD/SINGLE selects the output VC at this hop; BODY/TAIL reuse that
        same output VC, and every outgoing flit of the packet at this hop
        carries it in its hop-local ``vc_id`` field. BODY/TAIL never
        re-arbitrate a different output VC (that would let one packet split
        across VCs or routing classes mid-hop). This complements the
        hop-local ``vc_id`` of the canonical packet format.

These three are separate semantics and must not be conflated.

``VCResourceArtifact.allowed_transitions`` is the sole concrete authority
for legal ``vc_in -> vc_out`` transitions. This artifact contains no second
transition table and invents no transitions through timers, congestion,
escape designation, role membership or automatic demotion.

Explicitly absent: escape/adaptive priority, routing-action priority,
congestion thresholds, MinAdapt/UGAL arbitration, hidden QoS priority, and
multicast. ``RoutingRelationArtifact`` / ``RoutingPolicyDefinition`` own
routing candidate semantics; future backend qualification proves how a
concrete router implementation consumes them. This artifact owns generic
router microarchitecture only.

Convenience baseline defaults live only in ``derive_router_behavior``.
The persisted artifact contains every resolved value explicitly, and no
consumer may assume omitted defaults from serialized data.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

from dataclasses import dataclass
from enum import Enum
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.model.vc_resource import VCResourceArtifact

ROUTER_BEHAVIOR_SCHEMA_VERSION = 3
_HASH_TYPE_TAG = "srota/RouterBehaviorArtifact"

DEFAULT_INPUT_BUFFER_DEPTH_FLITS = 8
DEFAULT_OUTPUT_STAGE_DEPTH_FLITS = 1
DEFAULT_ALLOCATOR_ITERATIONS = 1
DEFAULT_CREDIT_RETURN_LATENCY_CYCLES = 1
DEFAULT_ROUTE_COMPUTE_CYCLES = 0
DEFAULT_VC_ALLOC_CYCLES = 1
DEFAULT_SWITCH_ALLOC_CYCLES = 1
DEFAULT_SWITCH_TRAVERSAL_CYCLES = 1
DEFAULT_OUTPUT_DELAY_CYCLES = 0


class RouterBehaviorError(ValueError, SemanticError):
    """The router behavior is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise RouterBehaviorError(
            f"{name} must be an exact int, got {type(value).__name__}")
    return value


def _as_positive_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 1:
        raise RouterBehaviorError(f"{name} must be >= 1, got {value}")
    return value


def _as_non_negative_int(name: str, value: Any) -> int:
    value = _as_int(name, value)
    if value < 0:
        raise RouterBehaviorError(f"{name} must be >= 0, got {value}")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise RouterBehaviorError(
            f"{name} must be an exact bool, got {type(value).__name__}")
    return value


def _as_hash(name: str, value: Any) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(c not in "0123456789abcdef" for c in value):
        raise RouterBehaviorError(
            f"{name} must be a 64-character lowercase hex digest")
    return value


def _require_enum(name: str, enum_cls: type[Enum], value: Any) -> None:
    if not isinstance(value, enum_cls):
        raise RouterBehaviorError(
            f"{name} must be a {enum_cls.__name__}, got "
            f"{type(value).__name__}")


def _strict_keys(d: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise RouterBehaviorError(
            f"{where} must be an object, got {type(d).__name__}")
    unknown = set(d) - allowed
    if unknown:
        raise RouterBehaviorError(
            f"{where} has unknown fields: {sorted(unknown)}")


def _need(d: dict[str, Any], key: str, where: str) -> Any:
    if key not in d:
        raise RouterBehaviorError(
            f"{where} is missing required field {key!r}")
    return d[key]


def _enum(name: str, enum_cls: type[Enum], value: Any) -> Enum:
    if not isinstance(value, str):
        raise RouterBehaviorError(
            f"{name} must be a string enum value, got "
            f"{type(value).__name__}")
    try:
        return enum_cls(value)
    except ValueError:
        raise RouterBehaviorError(
            f"unknown {name} {value!r}; known: "
            f"{[member.value for member in enum_cls]}") from None


# ── behavior vocabulary ──────────────────────────────────────────────────

class BufferOrganization(Enum):
    PER_INPUT_PORT_PER_VC = "per_input_port_per_vc"


class FlowControlProtocol(Enum):
    CREDIT = "credit"


class AllocatorPolicy(Enum):
    ISLIP = "islip"
    ROUND_ROBIN = "round_robin"


class InputVCPacketPolicy(Enum):
    """May flits of two packets share one input VC's packet context?"""

    ONE_PACKET_AT_A_TIME = "one_packet_at_a_time"


class VCAllocationScope(Enum):
    """How long an output-VC choice is held by a packet."""

    PACKET = "packet"


class VCReusePolicy(Enum):
    WAIT_FOR_TAIL_CREDIT = "wait_for_tail_credit"
    RELEASE_ON_TAIL_SEND = "release_on_tail_send"


_ARBITRATION_ALIASES = {
    "islip": AllocatorPolicy.ISLIP,
    "round_robin": AllocatorPolicy.ROUND_ROBIN,
    "round-robin": AllocatorPolicy.ROUND_ROBIN,
    "rr": AllocatorPolicy.ROUND_ROBIN,
}


def canonical_allocator(arbitration: str | None) -> AllocatorPolicy:
    """Canonicalize a guided arbitration label; unknown values fail closed.

    Raw spelling is not part of semantic identity: ``None``, ``"islip"`` and
    ``" iSLIP "`` all mean the same iSLIP policy, and ``"round_robin"``,
    ``"round-robin"``, ``"rr"`` and ``"RR"`` all mean round-robin.
    """
    if arbitration is None:
        return AllocatorPolicy.ISLIP
    if not isinstance(arbitration, str):
        raise RouterBehaviorError(
            f"arbitration must be a string or None, got "
            f"{type(arbitration).__name__}")
    key = arbitration.strip().lower()
    policy = _ARBITRATION_ALIASES.get(key)
    if policy is None:
        raise RouterBehaviorError(
            f"UNSUPPORTED arbitration {arbitration!r}; known: "
            f"{sorted(_ARBITRATION_ALIASES)}")
    return policy


def canonical_arbitration_token(arbitration: str | None) -> str | None:
    """Identity-stable arbitration token — the spelling that design_hash sees.

    Two designs that name the same policy with different spellings must have
    the same design identity, so ``"islip"``, ``"ISLIP"`` and ``" iSLIP "``
    all collapse to the canonical policy value. This is the normalization the
    product identity is computed through; it is deliberately *not* applied to
    lossless serialization (``to_dict``), which preserves what the user
    wrote.

    A value outside the alias table is returned verbatim rather than folded
    into a known policy or refused: it is not a policy this compiler knows,
    so it must keep its own identity. ``canonical_allocator`` still refuses it
    at compile time — identity is not the place to decide validity.

    ``None`` is deliberately NOT folded into the iSLIP default, even though
    ``canonical_allocator`` resolves it that way. ``None`` is a *declaration
    state* (unset; ``SEMANTIC_DEFAULT`` in the exposure registry), not a
    spelling of a chosen policy: "the user did not decide" and "the user
    chose iSLIP" are different requests, and ``design_hash`` answers what was
    requested, not what the compiler resolved it to.
    """
    if arbitration is None:
        return None
    try:
        return canonical_allocator(arbitration).value
    except RouterBehaviorError:
        return arbitration


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RouterBehaviorArtifact:
    """Architectural router behavior bound to one concrete VC resource."""

    vc_resource_hash: str

    buffer_organization: BufferOrganization
    input_buffer_depth_flits_per_vc: int
    output_stage_depth_flits_per_vc: int

    flow_control: FlowControlProtocol
    credit_return_latency_cycles: int
    vc_reuse_policy: VCReusePolicy

    vc_allocator: AllocatorPolicy
    switch_allocator: AllocatorPolicy
    allocator_iterations: int

    hold_switch_for_packet: bool
    input_vc_packet_policy: InputVCPacketPolicy
    vc_allocation_scope: VCAllocationScope

    input_speedup: int
    output_speedup: int
    internal_speedup: int

    route_compute_cycles: int
    vc_alloc_cycles: int
    switch_alloc_cycles: int
    switch_traversal_cycles: int
    output_delay_cycles: int

    schema_version: int = ROUTER_BEHAVIOR_SCHEMA_VERSION
    router_behavior_hash: str = ""

    def __post_init__(self):
        self._validate_structure()
        expected = self._compute_hash()
        if self.router_behavior_hash:
            _as_hash("router_behavior_hash", self.router_behavior_hash)
            if self.router_behavior_hash != expected:
                raise RouterBehaviorError(
                    "router_behavior_hash does not match content")
        else:
            object.__setattr__(self, "router_behavior_hash", expected)

    def _validate_structure(self) -> None:
        """All structural router invariants; fail closed, never coerce."""
        _as_hash("vc_resource_hash", self.vc_resource_hash)
        _require_enum("buffer_organization", BufferOrganization,
                      self.buffer_organization)
        if self.buffer_organization is not \
                BufferOrganization.PER_INPUT_PORT_PER_VC:
            raise RouterBehaviorError(
                f"UNSUPPORTED buffer organization "
                f"{self.buffer_organization.value!r} in v3")
        _as_positive_int("input_buffer_depth_flits_per_vc",
                         self.input_buffer_depth_flits_per_vc)
        _as_positive_int("output_stage_depth_flits_per_vc",
                         self.output_stage_depth_flits_per_vc)
        _require_enum("flow_control", FlowControlProtocol,
                      self.flow_control)
        if self.flow_control is not FlowControlProtocol.CREDIT:
            raise RouterBehaviorError(
                f"UNSUPPORTED flow control {self.flow_control.value!r} "
                "in v3")
        _as_non_negative_int("credit_return_latency_cycles",
                             self.credit_return_latency_cycles)
        _require_enum("vc_reuse_policy", VCReusePolicy,
                      self.vc_reuse_policy)
        _require_enum("vc_allocator", AllocatorPolicy, self.vc_allocator)
        _require_enum("switch_allocator", AllocatorPolicy,
                      self.switch_allocator)
        _as_positive_int("allocator_iterations", self.allocator_iterations)
        _as_bool("hold_switch_for_packet", self.hold_switch_for_packet)
        _require_enum("input_vc_packet_policy", InputVCPacketPolicy,
                      self.input_vc_packet_policy)
        if self.input_vc_packet_policy is not \
                InputVCPacketPolicy.ONE_PACKET_AT_A_TIME:
            raise RouterBehaviorError(
                f"UNSUPPORTED input VC packet policy "
                f"{self.input_vc_packet_policy.value!r} in v3")
        _require_enum("vc_allocation_scope", VCAllocationScope,
                      self.vc_allocation_scope)
        if self.vc_allocation_scope is not VCAllocationScope.PACKET:
            raise RouterBehaviorError(
                f"UNSUPPORTED VC allocation scope "
                f"{self.vc_allocation_scope.value!r} in v3")
        for name in ("input_speedup", "output_speedup", "internal_speedup"):
            _as_positive_int(name, getattr(self, name))
        for name in ("route_compute_cycles", "vc_alloc_cycles",
                     "switch_alloc_cycles", "switch_traversal_cycles",
                     "output_delay_cycles"):
            _as_non_negative_int(name, getattr(self, name))
        if type(self.schema_version) is not int or \
                self.schema_version != ROUTER_BEHAVIOR_SCHEMA_VERSION:
            raise RouterBehaviorError(
                f"unsupported router-behavior schema_version "
                f"{self.schema_version!r} (expected "
                f"{ROUTER_BEHAVIOR_SCHEMA_VERSION})")

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        """Semantic identity; every resolved semantic field participates."""
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "vc_resource_hash": self.vc_resource_hash,
            "buffer_organization": self.buffer_organization.value,
            "input_buffer_depth_flits_per_vc":
                self.input_buffer_depth_flits_per_vc,
            "output_stage_depth_flits_per_vc":
                self.output_stage_depth_flits_per_vc,
            "flow_control": self.flow_control.value,
            "credit_return_latency_cycles":
                self.credit_return_latency_cycles,
            "vc_reuse_policy": self.vc_reuse_policy.value,
            "vc_allocator": self.vc_allocator.value,
            "switch_allocator": self.switch_allocator.value,
            "allocator_iterations": self.allocator_iterations,
            "hold_switch_for_packet": self.hold_switch_for_packet,
            "input_vc_packet_policy": self.input_vc_packet_policy.value,
            "vc_allocation_scope": self.vc_allocation_scope.value,
            "input_speedup": self.input_speedup,
            "output_speedup": self.output_speedup,
            "internal_speedup": self.internal_speedup,
            "route_compute_cycles": self.route_compute_cycles,
            "vc_alloc_cycles": self.vc_alloc_cycles,
            "switch_alloc_cycles": self.switch_alloc_cycles,
            "switch_traversal_cycles": self.switch_traversal_cycles,
            "output_delay_cycles": self.output_delay_cycles,
        }

    def _compute_hash(self) -> str:
        return content_id(f"{_HASH_TYPE_TAG}/v{self.schema_version}",
                          self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        """Every semantic field is persisted explicitly; none omitted."""
        d = self.identity_dict()
        d["router_behavior_hash"] = self._compute_hash()
        return d

    # ── persisted parsing (validate, never repair) ─────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "RouterBehaviorArtifact":
        if isinstance(d, dict):
            version = d.get("schema_version")
            if type(version) is int and version == 1:
                raise RouterBehaviorError(
                    "RouterBehaviorArtifact schema v1 is refused: its "
                    "packet_hold_policy conflated switch arbitration with "
                    "input-VC packet context. Rebuild with v3 "
                    "(hold_switch_for_packet + input_vc_packet_policy + "
                    "vc_allocation_scope) — no silent migration")
            if type(version) is int and version == 2:
                raise RouterBehaviorError(
                    "RouterBehaviorArtifact schema v2 is refused: v2 was "
                    "parented to the routing-specific VCAssignmentArtifact. "
                    "Canonical v3 binds the routing-independent "
                    "VCResourceArtifact. Rebuild with v3 — no silent "
                    "migration")
        allowed = frozenset({
            "type", "schema_version", "vc_resource_hash",
            "buffer_organization", "input_buffer_depth_flits_per_vc",
            "output_stage_depth_flits_per_vc", "flow_control",
            "credit_return_latency_cycles", "vc_reuse_policy",
            "vc_allocator", "switch_allocator", "allocator_iterations",
            "hold_switch_for_packet", "input_vc_packet_policy",
            "vc_allocation_scope",
            "input_speedup", "output_speedup", "internal_speedup",
            "route_compute_cycles", "vc_alloc_cycles",
            "switch_alloc_cycles", "switch_traversal_cycles",
            "output_delay_cycles", "router_behavior_hash",
        })
        _strict_keys(d, allowed, "router_behavior")
        if _need(d, "type", "router_behavior") != _HASH_TYPE_TAG:
            raise RouterBehaviorError(
                f"router behavior type must be {_HASH_TYPE_TAG!r}, got "
                f"{d.get('type')!r}")
        artifact = cls(
            vc_resource_hash=_need(d, "vc_resource_hash", "router_behavior"),
            buffer_organization=_enum(
                "buffer organization", BufferOrganization,
                _need(d, "buffer_organization", "router_behavior")),
            input_buffer_depth_flits_per_vc=_need(
                d, "input_buffer_depth_flits_per_vc", "router_behavior"),
            output_stage_depth_flits_per_vc=_need(
                d, "output_stage_depth_flits_per_vc", "router_behavior"),
            flow_control=_enum(
                "flow control", FlowControlProtocol,
                _need(d, "flow_control", "router_behavior")),
            credit_return_latency_cycles=_need(
                d, "credit_return_latency_cycles", "router_behavior"),
            vc_reuse_policy=_enum(
                "VC reuse policy", VCReusePolicy,
                _need(d, "vc_reuse_policy", "router_behavior")),
            vc_allocator=_enum(
                "VC allocator", AllocatorPolicy,
                _need(d, "vc_allocator", "router_behavior")),
            switch_allocator=_enum(
                "switch allocator", AllocatorPolicy,
                _need(d, "switch_allocator", "router_behavior")),
            allocator_iterations=_need(
                d, "allocator_iterations", "router_behavior"),
            hold_switch_for_packet=_need(
                d, "hold_switch_for_packet", "router_behavior"),
            input_vc_packet_policy=_enum(
                "input VC packet policy", InputVCPacketPolicy,
                _need(d, "input_vc_packet_policy", "router_behavior")),
            vc_allocation_scope=_enum(
                "VC allocation scope", VCAllocationScope,
                _need(d, "vc_allocation_scope", "router_behavior")),
            input_speedup=_need(d, "input_speedup", "router_behavior"),
            output_speedup=_need(d, "output_speedup", "router_behavior"),
            internal_speedup=_need(d, "internal_speedup", "router_behavior"),
            route_compute_cycles=_need(
                d, "route_compute_cycles", "router_behavior"),
            vc_alloc_cycles=_need(d, "vc_alloc_cycles", "router_behavior"),
            switch_alloc_cycles=_need(
                d, "switch_alloc_cycles", "router_behavior"),
            switch_traversal_cycles=_need(
                d, "switch_traversal_cycles", "router_behavior"),
            output_delay_cycles=_need(
                d, "output_delay_cycles", "router_behavior"),
            schema_version=_need(d, "schema_version", "router_behavior"),
            router_behavior_hash=_need(
                d, "router_behavior_hash", "router_behavior"),
        )
        return artifact

    # ── parent validation ──────────────────────────────────────────────
    def validate_against(self, vc_resource: VCResourceArtifact) -> None:
        """Prove this behavior can instantiate the given VC resources.

        Requires only concrete VC resources: no routing algorithm, no
        identity transitions, no traffic injectability, no escape
        designation and no routing roles. Both one-VC and multi-VC
        resources are valid parents.
        """
        if not isinstance(vc_resource, VCResourceArtifact):
            raise RouterBehaviorError(
                f"vc_resource must be a VCResourceArtifact, got "
                f"{type(vc_resource).__name__}")
        if vc_resource.artifact_hash != vc_resource._compute_hash():
            raise RouterBehaviorError(
                "vc_resource_hash parent is internally inconsistent")
        if self.vc_resource_hash != vc_resource.artifact_hash:
            raise RouterBehaviorError(
                "vc_resource_hash does not match the VC resource")
        if vc_resource.vc_count < 1:
            raise RouterBehaviorError("vc_count must be >= 1")
        self._validate_structure()
        if self.router_behavior_hash != self._compute_hash():
            raise RouterBehaviorError(
                "router_behavior_hash does not match content")


def derive_router_behavior(
        *,
        vc_resource: VCResourceArtifact,
        arbitration: str | None = None,
        buffer_depth_flits: int = DEFAULT_INPUT_BUFFER_DEPTH_FLITS,
        output_stage_depth_flits: int = DEFAULT_OUTPUT_STAGE_DEPTH_FLITS,
) -> RouterBehaviorArtifact:
    """Canonical builder: VCResourceArtifact -> v3 router behavior.

    The historical baseline is:

        per-input-port/per-VC buffering, 8 flits deep
        one output staging slot per VC
        credit flow control, one-cycle return latency
        WAIT_FOR_TAIL_CREDIT reuse
        iSLIP VC and switch allocators, one iteration
        flit-granularity switch (no packet hold)
        one packet context per input VC, packet-scoped VC allocation
        input/output/internal speedup 1
        route 0, VC-alloc 1, switch-alloc 1, traversal 1, output 0 cycles

    These defaults belong only to this convenience builder. The persisted
    artifact always carries every resolved value explicitly.

    ``arbitration`` is a guided label canonicalized to an AllocatorPolicy;
    the raw string is not part of artifact identity.
    """
    if not isinstance(vc_resource, VCResourceArtifact):
        raise RouterBehaviorError(
            f"vc_resource must be a VCResourceArtifact, got "
            f"{type(vc_resource).__name__}")
    allocator = canonical_allocator(arbitration)
    artifact = RouterBehaviorArtifact(
        vc_resource_hash=vc_resource.artifact_hash,
        buffer_organization=BufferOrganization.PER_INPUT_PORT_PER_VC,
        input_buffer_depth_flits_per_vc=_as_positive_int(
            "buffer_depth_flits", buffer_depth_flits),
        output_stage_depth_flits_per_vc=_as_positive_int(
            "output_stage_depth_flits", output_stage_depth_flits),
        flow_control=FlowControlProtocol.CREDIT,
        credit_return_latency_cycles=DEFAULT_CREDIT_RETURN_LATENCY_CYCLES,
        vc_reuse_policy=VCReusePolicy.WAIT_FOR_TAIL_CREDIT,
        vc_allocator=allocator,
        switch_allocator=allocator,
        allocator_iterations=DEFAULT_ALLOCATOR_ITERATIONS,
        hold_switch_for_packet=False,
        input_vc_packet_policy=InputVCPacketPolicy.ONE_PACKET_AT_A_TIME,
        vc_allocation_scope=VCAllocationScope.PACKET,
        input_speedup=1,
        output_speedup=1,
        internal_speedup=1,
        route_compute_cycles=DEFAULT_ROUTE_COMPUTE_CYCLES,
        vc_alloc_cycles=DEFAULT_VC_ALLOC_CYCLES,
        switch_alloc_cycles=DEFAULT_SWITCH_ALLOC_CYCLES,
        switch_traversal_cycles=DEFAULT_SWITCH_TRAVERSAL_CYCLES,
        output_delay_cycles=DEFAULT_OUTPUT_DELAY_CYCLES,
    )
    artifact.validate_against(vc_resource)
    return artifact
