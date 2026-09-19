"""veritx_dse.model.router_behavior — RouterBehaviorArtifact (Wave B3.4b).

RouterBehaviorArtifact is the sole authority for **how a router behaves**,
independent of any RTL or simulator implementation: what it buffers, how
credits are interpreted, how output VCs are selected and reused, how the
switch is arbitrated, and what pipeline latency the architecture has.

It does NOT own route tables, RoutingClass definitions, VC ids or legal
transitions (VCAssignmentArtifact), packet bit positions
(PacketFormatArtifact), channel/link latency (`DirectedChannel`), or any
backend sampling/seed knob.

Its only parent is ``vc_assignment_hash``: it defines how to handle
whatever VC structure it is given, without knowing a concrete topology or
wire format.

v1 baseline (see docs §14.4):

    per-input-port / per-VC buffering, 8 flits deep
    one output staging slot per VC
    credit flow control, one-flit granularity
    WAIT_FOR_TAIL_CREDIT reuse
    iSLIP VC and switch allocators, one iteration
    flit-granularity switch (no packet hold)
    input/output/internal speedup 1
    route 0, VC-alloc 1, switch-alloc 1, traversal 1, output 0 cycles

Two independent packet/switch semantics (B3.4c, schema v2):

    hold_switch_for_packet = False
        the physical switch is arbitrated per flit; a packet does not
        reserve the crossbar path until TAIL.

    input_vc_packet_policy = ONE_PACKET_AT_A_TIME
        WITHIN one input VC, HEAD opens a packet context and BODY/TAIL
        belong to it; no second HEAD/SINGLE may begin there until the
        first packet closes. Packets in DIFFERENT VCs may still make
        interleaved progress through the switch.

    vc_allocation_scope = PACKET
        HEAD/SINGLE selects vc_out for this packet at this hop;
        BODY/TAIL reuse that same vc_out, and every outgoing flit of the
        packet at this hop carries it in its hop-local vc_id field.
        BODY/TAIL never re-arbitrate a different vc_out (that would let
        one packet split across VCs or routing classes mid-hop).

Explicitly absent in v1: automatic VC demotion, hidden escape/QoS
priority, and multicast. A VC transition is legal only if
VCAssignmentArtifact.allowed_transitions contains it and the router's
output-VC allocator selects it; no timer or ``escape_vcs`` membership may
invent one.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Any

from .vc_assignment import VCAssignmentArtifact

ROUTER_BEHAVIOR_SCHEMA_VERSION = 2
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


class RouterBehaviorError(ValueError):
    """The router behavior is invalid or unsupported — fail closed."""


def _as_int(name: str, value: Any) -> int:
    if type(value) is not int:
        raise RouterBehaviorError(
            f"{name} must be an int, got {type(value).__name__}")
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


def _as_str(name: str, value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise RouterBehaviorError(f"{name} must be a non-empty string")
    return value


def _as_bool(name: str, value: Any) -> bool:
    if type(value) is not bool:
        raise RouterBehaviorError(
            f"{name} must be a bool, got {type(value).__name__}")
    return value


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
            f"{name} must be a string enum value, got {type(value).__name__}")
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
    """Canonicalize a GUIDED arbitration label; unknown values fail."""
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


# ── the artifact ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class RouterBehaviorArtifact:
    """Architectural router behavior bound to one VC assignment."""

    vc_assignment_hash: str

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

    input_vc_packet_policy: InputVCPacketPolicy = \
        InputVCPacketPolicy.ONE_PACKET_AT_A_TIME
    vc_allocation_scope: VCAllocationScope = VCAllocationScope.PACKET

    input_speedup: int = 1
    output_speedup: int = 1
    internal_speedup: int = 1

    route_compute_cycles: int = DEFAULT_ROUTE_COMPUTE_CYCLES
    vc_alloc_cycles: int = DEFAULT_VC_ALLOC_CYCLES
    switch_alloc_cycles: int = DEFAULT_SWITCH_ALLOC_CYCLES
    switch_traversal_cycles: int = DEFAULT_SWITCH_TRAVERSAL_CYCLES
    output_delay_cycles: int = DEFAULT_OUTPUT_DELAY_CYCLES

    schema_version: int = ROUTER_BEHAVIOR_SCHEMA_VERSION
    artifact_hash: str = ""

    def __post_init__(self):
        _as_str("vc_assignment_hash", self.vc_assignment_hash)
        if not isinstance(self.buffer_organization, BufferOrganization):
            raise RouterBehaviorError(
                "buffer_organization must be a BufferOrganization")
        if self.buffer_organization is not \
                BufferOrganization.PER_INPUT_PORT_PER_VC:
            raise RouterBehaviorError(
                f"UNSUPPORTED buffer organization "
                f"{self.buffer_organization.value!r} in v1")
        _as_positive_int("input_buffer_depth_flits_per_vc",
                         self.input_buffer_depth_flits_per_vc)
        _as_positive_int("output_stage_depth_flits_per_vc",
                         self.output_stage_depth_flits_per_vc)
        if not isinstance(self.flow_control, FlowControlProtocol):
            raise RouterBehaviorError(
                "flow_control must be a FlowControlProtocol")
        if self.flow_control is not FlowControlProtocol.CREDIT:
            raise RouterBehaviorError(
                f"UNSUPPORTED flow control {self.flow_control.value!r} "
                "in v1")
        _as_non_negative_int("credit_return_latency_cycles",
                             self.credit_return_latency_cycles)
        if not isinstance(self.vc_reuse_policy, VCReusePolicy):
            raise RouterBehaviorError(
                "vc_reuse_policy must be a VCReusePolicy")
        for name in ("vc_allocator", "switch_allocator"):
            if not isinstance(getattr(self, name), AllocatorPolicy):
                raise RouterBehaviorError(
                    f"{name} must be an AllocatorPolicy")
        _as_positive_int("allocator_iterations", self.allocator_iterations)
        _as_bool("hold_switch_for_packet", self.hold_switch_for_packet)
        if not isinstance(self.input_vc_packet_policy, InputVCPacketPolicy):
            raise RouterBehaviorError(
                "input_vc_packet_policy must be an InputVCPacketPolicy")
        if self.input_vc_packet_policy is not \
                InputVCPacketPolicy.ONE_PACKET_AT_A_TIME:
            raise RouterBehaviorError(
                f"UNSUPPORTED input VC packet policy "
                f"{self.input_vc_packet_policy.value!r} in v2")
        if not isinstance(self.vc_allocation_scope, VCAllocationScope):
            raise RouterBehaviorError(
                "vc_allocation_scope must be a VCAllocationScope")
        if self.vc_allocation_scope is not VCAllocationScope.PACKET:
            raise RouterBehaviorError(
                f"UNSUPPORTED VC allocation scope "
                f"{self.vc_allocation_scope.value!r} in v2")
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
        expected = self._compute_hash()
        if self.artifact_hash and self.artifact_hash != expected:
            raise RouterBehaviorError(
                "artifact_hash does not match content")
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash", expected)

    # ── identity ───────────────────────────────────────────────────────
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": _HASH_TYPE_TAG,
            "schema_version": self.schema_version,
            "vc_assignment_hash": self.vc_assignment_hash,
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
        from veritx_dse.core.spec import canonical_json
        body = (f"{_HASH_TYPE_TAG}/v{self.schema_version}\0"
                + canonical_json(self.identity_dict()))
        return hashlib.sha256(body.encode()).hexdigest()

    def router_behavior_hash(self) -> str:
        return self._compute_hash()

    def to_dict(self) -> dict[str, Any]:
        d = self.identity_dict()
        d["artifact_hash"] = self.router_behavior_hash()
        return d

    # ── persisted parsing (validate, never repair) ─────────────────────
    @classmethod
    def from_dict(cls, d: Any) -> "RouterBehaviorArtifact":
        allowed = frozenset({
            "type", "schema_version", "vc_assignment_hash",
            "buffer_organization", "input_buffer_depth_flits_per_vc",
            "output_stage_depth_flits_per_vc", "flow_control",
            "credit_return_latency_cycles", "vc_reuse_policy",
            "vc_allocator", "switch_allocator", "allocator_iterations",
            "hold_switch_for_packet", "input_vc_packet_policy",
            "vc_allocation_scope",
            "input_speedup", "output_speedup", "internal_speedup",
            "route_compute_cycles", "vc_alloc_cycles",
            "switch_alloc_cycles", "switch_traversal_cycles",
            "output_delay_cycles", "artifact_hash",
        })
        if isinstance(d, dict) and d.get("schema_version") == 1:
            raise RouterBehaviorError(
                "RouterBehaviorArtifact schema v1 is refused: its "
                "packet_hold_policy conflated switch arbitration with "
                "input-VC packet context. Rebuild with v2 "
                "(input_vc_packet_policy + vc_allocation_scope) — no "
                "silent migration")
        _strict_keys(d, allowed, "router_behavior")
        if _need(d, "type", "router_behavior") != _HASH_TYPE_TAG:
            raise RouterBehaviorError(
                f"unexpected artifact type {d.get('type')!r}")
        _as_str("vc_assignment_hash",
                _need(d, "vc_assignment_hash", "router_behavior"))
        return cls(
            vc_assignment_hash=d["vc_assignment_hash"],
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
            artifact_hash=_need(d, "artifact_hash", "router_behavior"),
        )

    # ── parent validation ──────────────────────────────────────────────
    def validate_against(self, vc_assignment: VCAssignmentArtifact) -> None:
        """Prove this behavior can instantiate the given VC structure."""
        if not isinstance(vc_assignment, VCAssignmentArtifact):
            raise RouterBehaviorError(
                "vc_assignment must be a VCAssignmentArtifact")
        if self.vc_assignment_hash != vc_assignment.vc_assignment_hash():
            raise RouterBehaviorError(
                "vc_assignment_hash does not match the VC assignment")
        if vc_assignment.vc_count < 1:
            raise RouterBehaviorError("vc_count must be >= 1")
        if self.buffer_organization is not \
                BufferOrganization.PER_INPUT_PORT_PER_VC:
            raise RouterBehaviorError(
                "v1 supports per-input-port/per-VC buffering only")
        if self.input_buffer_depth_flits_per_vc < 1:
            raise RouterBehaviorError(
                "every VC queue needs at least one flit of capacity")


def derive_router_behavior(
        *,
        vc_assignment: VCAssignmentArtifact,
        arbitration: str | None = None,
        buffer_depth_flits: int = DEFAULT_INPUT_BUFFER_DEPTH_FLITS,
        output_stage_depth_flits: int = DEFAULT_OUTPUT_STAGE_DEPTH_FLITS,
) -> RouterBehaviorArtifact:
    """Canonical builder: VCAssignmentArtifact -> v1 router behavior.

    ``arbitration`` is a GUIDED label canonicalized to an AllocatorPolicy;
    the raw string is not part of artifact identity.
    """
    if not isinstance(vc_assignment, VCAssignmentArtifact):
        raise RouterBehaviorError(
            f"vc_assignment must be a VCAssignmentArtifact, got "
            f"{type(vc_assignment).__name__}")
    allocator = canonical_allocator(arbitration)
    artifact = RouterBehaviorArtifact(
        vc_assignment_hash=vc_assignment.vc_assignment_hash(),
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
    artifact.validate_against(vc_assignment)
    return artifact
