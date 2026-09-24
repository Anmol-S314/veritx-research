"""veritx_dse.workload.canonical_graph — retired compatibility shim.

The Slice-2c migration is complete: the ONE canonical workload authority
is ``veritx_dse.workload.graph`` (ParallelismShape geometry). This module
re-exports it so historical imports keep resolving to the single
authority — it defines nothing itself and must never diverge.
"""
from __future__ import annotations

from veritx_dse.workload.graph import (  # noqa: F401
    ALL_KINDS,
    COLLECTIVE_KINDS,
    DEFAULT_BATCH_TAG,
    DEFAULT_LOC,
    DETAIL_KEYS,
    KIND_COLLECTIVE,
    KIND_COMPUTE,
    KIND_EXPERT_BEGIN,
    KIND_EXPERT_END,
    KIND_MULTICAST,
    KIND_P2P,
    KIND_PIM_CHANNEL,
    KIND_PIM_END,
    OperationNode,
    P2P_ROLES,
    REPLICATION_KINDS,
    SCHEMA_VERSION,
    SCOPE_ALL,
    WorkloadGraph,
    WorkloadSemantics,
    collective_detail,
    compute_detail,
    expert_detail,
    multicast_detail,
    p2p_detail,
    pim_detail,
    pim_end_detail,
)

__all__ = [
    "ALL_KINDS", "COLLECTIVE_KINDS", "DEFAULT_BATCH_TAG", "DEFAULT_LOC",
    "DETAIL_KEYS", "KIND_COLLECTIVE", "KIND_COMPUTE", "KIND_EXPERT_BEGIN",
    "KIND_EXPERT_END", "KIND_MULTICAST", "KIND_P2P", "KIND_PIM_CHANNEL",
    "KIND_PIM_END", "OperationNode", "P2P_ROLES", "REPLICATION_KINDS",
    "SCHEMA_VERSION", "SCOPE_ALL", "WorkloadGraph", "WorkloadSemantics",
    "collective_detail", "compute_detail", "expert_detail",
    "multicast_detail", "p2p_detail", "pim_detail", "pim_end_detail",
]
