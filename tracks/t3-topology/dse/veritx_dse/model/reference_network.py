"""Strict support for standalone reference envelopes, never canonical hardware."""
from __future__ import annotations

import json
from veritx_dse.core.artifact import content_id
from veritx_dse.model.attachment import AgentAttachmentArtifact
from veritx_dse.model.topology_artifact import TopologyArtifact


class ReferenceNetworkError(ValueError):
    """Invalid reference input or replay evidence."""


def integer(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise ReferenceNetworkError(f"{name} must be an exact integer >= {minimum}")
    return value


def text(value, name):
    if type(value) is not str or not value:
        raise ReferenceNetworkError(f"{name} must be a nonempty string")
    return value


def keys(value, names, name):
    if type(value) is not dict or set(value) != set(names):
        raise ReferenceNetworkError(f"{name} requires exactly fields {sorted(names)}")


def rows(value, name):
    if type(value) is not list:
        raise ReferenceNetworkError(f"{name} must be a JSON list")
    return value


def pairs(value, name):
    result = rows(value, name)
    if any(type(row) is not list or len(row) != 2 for row in result):
        raise ReferenceNetworkError(f"{name} must contain pairs")
    return result


def exact(actual, expected, name):
    # JSON comparison avoids Python's True == 1 equivalence in evidence.
    if json.dumps(actual, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ReferenceNetworkError(f"{name} differs from parent-recomputed content")


def sealed(domain, payload):
    return {**payload, "artifact_hash": content_id(domain, payload)}


def parents(topology, attachment):
    if not isinstance(topology, TopologyArtifact) or not isinstance(attachment, AgentAttachmentArtifact):
        raise ReferenceNetworkError("actual topology and attachment artifacts required")
    integer(topology.schema_version, "topology schema_version", 1)
    integer(attachment.schema_version, "attachment schema_version", 1)
    attachment.validate_against_topology(topology)
    if topology.shared_links:
        raise ReferenceNetworkError("reference v1 supports CHANNEL only, not SHARED_LINK/MECS")
    if topology.planes != ("d",):
        raise ReferenceNetworkError("reference v1 requires a single explicit Plane D")
    return {e.endpoint_id: e.router_id for e in attachment.endpoints}


def path(topology, channels, source, destination):
    if type(channels) is not tuple:
        raise ReferenceNetworkError("path must be an immutable channel tuple")
    by_id = {c.channel_id: c for c in topology.channels}
    current = source
    visited = {source}
    for cid in channels:
        integer(cid, "channel id")
        channel = by_id.get(cid)
        if channel is None or channel.src_router != current:
            raise ReferenceNetworkError("absent or discontinuous directed CHANNEL path")
        current = channel.dst_router
        if current in visited:
            raise ReferenceNetworkError("cyclic path")
        visited.add(current)
    if current != destination or (source == destination and channels):
        raise ReferenceNetworkError("path terminal differs from bound endpoint/router")
