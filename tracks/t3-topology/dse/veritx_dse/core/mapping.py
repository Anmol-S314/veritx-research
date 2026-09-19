"""veritx_dse.core.mapping — placement provenance (Wave B, audit #11/#25).

A workload's TP/EP/DP/PP counts do not say where ranks live. Two runs
with swapped per-rank workloads share a workload multiset but execute
different placements — on an asymmetric fabric these are not equivalent.
MappingArtifact binds each rank to its artifact, instance, node, and
parallelism groups, content-addressed. The comparison fingerprint
carries the mapping hash: swapped placements refuse unless declared.
"""
from __future__ import annotations

import copy as _copy
import hashlib
import json as _json
import re as _re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .spec import canonical_json

_INSTANCE_RE = _re.compile(r"instance(\d+)")


class MappingError(ValueError):
    """Unmappable workload index (fail-closed, never guessed)."""


@dataclass(frozen=True)
class MappingArtifact:
    entries: tuple[dict[str, Any], ...]
    mapping_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"entries": [dict(e) for e in self.entries],
                "mapping_hash": self.mapping_hash}


def _resolve_instances(cluster: dict[str, Any], helpers: Any,
                       cluster_id: str) -> list[dict[str, Any]]:
    from .spec import SpecError
    nodes = cluster.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise SpecError(f"cluster {cluster_id!r} has no nodes list")
    instances: list[dict[str, Any]] = []
    for ni, node in enumerate(nodes):
        for inst in node.get("instances") or []:
            work = _copy.deepcopy(inst)
            try:
                model_config = helpers.get_config(work["model_name"])
            except (FileNotFoundError, KeyError) as e:
                raise SpecError(
                    f"cluster {cluster_id!r} model "
                    f"{work.get('model_name')!r} unresolvable: {e}") from e
            try:
                helpers.resolve_parallelism(work, model_config)
            except ValueError as e:
                raise SpecError(
                    f"cluster {cluster_id!r} parallelism invalid: {e}") from e
            work["node_id"] = ni
            instances.append(work)
    try:
        helpers.resolve_dp_groups(instances)
    except ValueError as e:
        raise SpecError(
            f"cluster {cluster_id!r} dp groups invalid: {e}") from e
    return instances


def mapping_from_workload_index(index: dict[str, Any], cluster_id: str,
                                helpers: Any = None) -> MappingArtifact:
    """Bind each workload artifact to its rank/instance/node/groups.

    Rank comes from the trace filename (instance<N>_...); the instance
    position is its order in the resolved cluster. Anything unparseable
    refuses — a guessed placement is worse than none.
    """
    from .paths import serving_fixture
    artifacts = index.get("artifacts") or []
    if not artifacts:
        raise MappingError("workload index lists no artifacts")
    if helpers is None:
        from .serving import _load_serving_helpers
        from .paths import LLMSIM_DIR
        helpers = _load_serving_helpers(LLMSIM_DIR)
    cluster_path = serving_fixture("cluster", cluster_id)
    try:
        cluster = _json.loads(cluster_path.read_text())
    except (OSError, ValueError) as e:
        raise MappingError(f"cluster {cluster_id!r} unreadable: {e}") from e
    instances = _resolve_instances(cluster, helpers, cluster_id)
    entries = []
    for art in artifacts:
        m = _INSTANCE_RE.search(str(art.get("trace", "")))
        if not m:
            raise MappingError(
                f"artifact {art.get('name')!r} carries no instance rank "
                "in its trace path — placement unprovable")
        rank = int(m.group(1))
        if rank >= len(instances):
            raise MappingError(
                f"rank {rank} outside cluster's {len(instances)} "
                "instances")
        inst = instances[rank]
        entries.append({
            "rank": rank,
            "artifact_hash": art["artifact_hash"],
            "trace": str(art.get("trace", "")),
            "instance": rank,
            "node": inst.get("node_id"),
            "tp_size": inst.get("tp_size"),
            "dp_group": inst.get("dp_group"),
            "ep_size": inst.get("ep_size"),
        })
    entries.sort(key=lambda e: e["rank"])
    if len({e["rank"] for e in entries}) != len(entries):
        raise MappingError("duplicate ranks in workload index")
    h = hashlib.sha256(canonical_json({"entries": entries}).encode())
    return MappingArtifact(entries=tuple(entries),
                           mapping_hash="sha256:" + h.hexdigest())
