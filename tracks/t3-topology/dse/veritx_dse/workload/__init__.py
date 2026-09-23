"""veritx_dse.workload — canonical workload semantics.

The workload authority layer of the canonical SROTA spine:

    CompileRequest (design identity)
          |
          v
    WorkloadGraph            graph.py      operation semantics + namespace
          |
          v
    collective schedules     collectives.py  pinned step/byte arithmetic
          |
          v
    logical messages         messages.py   expansion + per-class conservation
          |
          v
    participant -> endpoint  traffic.py    canonical mapping/attachment binding
          |
          v
    packets / flits          traffic.py    bit-exact packetization

Nothing here owns design identity, topology, routing, VC resources or any
backend configuration: those remain the current canonical authorities.
"""
from __future__ import annotations

from .collectives import collective_schedule
from .graph import (
    ALL_KINDS, COLLECTIVE_KINDS, DEFAULT_BATCH_TAG, DEFAULT_LOC, DETAIL_KEYS,
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_EXPERT_BEGIN, KIND_EXPERT_END,
    KIND_MULTICAST, KIND_P2P, KIND_PIM_CHANNEL, KIND_PIM_END, OperationNode,
    P2P_ROLES, REPLICATION_KINDS, SCOPE_ALL, WorkloadGraph, WorkloadSemantics,
    collective_detail, compute_detail, expert_detail, multicast_detail,
    p2p_detail, pim_detail, pim_end_detail,
)
from .messages import (
    CollectiveScheduleRecord, DEFAULT_TRAFFIC_CLASS, LOGICAL_MESSAGE_SCHEMA_VERSION_V2,
    LogicalMessage, LogicalMessageArtifactV2, REPLICATION_SOURCE, SCHEDULES,
)
from .traffic import (
    BindingRecord, MessageTraffic, OperationLedgerEntry,
    PARTICIPANT_MAPPING_SCHEMA_VERSION, PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2,
    PacketRecord, ParticipantEndpointMapping, PhysicalTrafficArtifactV2,
    bind_participants, flitize_packet, header_width_bits, packet_capacity_bits,
    packetize_message, payload_width_bits,
)

__all__ = [
    "ALL_KINDS", "BindingRecord", "COLLECTIVE_KINDS",
    "CollectiveScheduleRecord", "DEFAULT_BATCH_TAG", "DEFAULT_LOC",
    "DEFAULT_TRAFFIC_CLASS", "DETAIL_KEYS", "KIND_COLLECTIVE", "KIND_COMPUTE",
    "KIND_EXPERT_BEGIN", "KIND_EXPERT_END", "KIND_MULTICAST", "KIND_P2P",
    "KIND_PIM_CHANNEL", "KIND_PIM_END", "LOGICAL_MESSAGE_SCHEMA_VERSION_V2",
    "LogicalMessage", "LogicalMessageArtifactV2", "MessageTraffic",
    "OperationLedgerEntry", "OperationNode", "P2P_ROLES",
    "PARTICIPANT_MAPPING_SCHEMA_VERSION", "PHYSICAL_TRAFFIC_SCHEMA_VERSION_V2",
    "PacketRecord", "ParticipantEndpointMapping", "PhysicalTrafficArtifactV2",
    "REPLICATION_KINDS", "REPLICATION_SOURCE", "SCHEDULES", "SCOPE_ALL",
    "WorkloadGraph", "WorkloadSemantics", "bind_participants",
    "collective_detail", "collective_schedule", "compute_detail",
    "expert_detail", "flitize_packet", "header_width_bits",
    "multicast_detail", "p2p_detail", "packet_capacity_bits",
    "packetize_message", "payload_width_bits", "pim_detail",
    "pim_end_detail",
]
