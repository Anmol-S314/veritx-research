"""Slice 34 — canonical participant → ASTRA execution-namespace binding.

The canonical model keeps four namespaces apart::

    workload rank   --MappingArtifact-->      agent
    agent           --AgentAttachmentArtifact--> physical endpoint
    endpoint        -->  BookSim fabric node  ==  ASTRA ``Sys.id``

ASTRA operates in the **endpoint** namespace: ``Workload.cc`` resolves
``<base>.<Sys.id>.et``, ``CommunicatorGroup`` membership is endpoint ids, and
Chakra ``comm_src``/``comm_dst`` are endpoint ids.  Nothing may assume
``rank == endpoint``.

This module translates only that namespace.  It never re-lowers the fabric,
never renumbers canonical endpoints, and never regenerates the message
schedule: the canonical identities stay rank-based.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.artifact import content_hash
from veritx_dse.core.errors import MappingInvalid

ASTRA_NAMESPACE_SCHEMA_VERSION = 1
MESSAGE_TRANSLATION_VERSION = "srota/astra-et-namespace-translation/v1"
COMMUNICATOR_GROUP_VERSION = "srota/astra-communicator-groups/v1"

#: which mechanism actually selects a collective's topology at runtime
MECHANISM_GLOBAL_LOGICAL_TOPOLOGY = "GLOBAL_LOGICAL_TOPOLOGY"
MECHANISM_COMMUNICATOR_GROUP_RING = "COMMUNICATOR_GROUP_RING"

COMM_GROUP_FILE = "comm_group.json"
_GROUP_KEY = "comm-group-configuration"


class AstraNamespaceError(ValueError):
    """The execution namespace cannot be derived, or was tampered with."""


# ── communicator groups ───────────────────────────────────────────────────

@dataclass(frozen=True)
class CommunicatorGroups:
    """Canonical collective membership sets, in the endpoint namespace.

    Membership is semantic; the numeric id is transport representation and is
    assigned deterministically from sorted canonical membership, never from
    Python object iteration order.
    """

    memberships: tuple[tuple[int, tuple[int, ...]], ...]

    def __post_init__(self) -> None:
        ids = [gid for gid, _ in self.memberships]
        if sorted(ids) != list(range(1, len(ids) + 1)):
            raise AstraNamespaceError(
                f"communicator group ids must be 1..N, got {ids}")
        seen: set[tuple[int, ...]] = set()
        for _, members in self.memberships:
            if not members:
                raise AstraNamespaceError("a communicator group is empty")
            if tuple(sorted(members)) != members:
                raise AstraNamespaceError(
                    "communicator group membership must be sorted")
            if len(set(members)) != len(members):
                raise AstraNamespaceError(
                    "communicator group membership has duplicates")
            if members in seen:
                raise AstraNamespaceError(
                    "the same membership must reuse one group")
            seen.add(members)

    def id_for(self, endpoints: tuple[int, ...]) -> int:
        wanted = tuple(sorted(endpoints))
        for gid, members in self.memberships:
            if members == wanted:
                return gid
        raise AstraNamespaceError(
            f"no communicator group for membership {wanted}")

    def group_ids(self) -> tuple[int, ...]:
        return tuple(gid for gid, _ in self.memberships)

    def to_json(self) -> str:
        """The ASTRA communicator-group document (ids are JSON string keys)."""
        payload = {str(gid): list(members)
                   for gid, members in self.memberships}
        return json.dumps(payload, sort_keys=True, indent=2)

    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/AstraCommunicatorGroups",
            "schema_version": 1,
            "version": COMMUNICATOR_GROUP_VERSION,
            "memberships": [[gid, list(m)] for gid, m in self.memberships],
        }

    def groups_id(self) -> str:
        return content_hash("srota/AstraCommunicatorGroups", 1,
                            self.identity_dict())


# ── the execution namespace ───────────────────────────────────────────────

@dataclass(frozen=True)
class AstraExecutionNamespace:
    """rank → endpoint binding plus the endpoint-namespace collective groups."""

    machine_id: str
    workload_projection_id: str
    participant_count: int
    rank_to_endpoint: tuple[tuple[int, int], ...]
    participant_mapping_id: str
    #: ASTRA's ``Sys.id`` namespace ``[0, endpoint_count)`` == the BookSim
    #: NODE count (``_tm->NumNodes()``), not the attached-endpoint count and
    #: not "routers" in the AnyNet sense
    endpoint_count: int
    router_count: int
    attached_endpoint_count: int
    groups: CommunicatorGroups
    #: (operation_id, mechanism) per collective, from the runtime's own rule
    collective_mechanisms: tuple[tuple[str, str], ...]
    num_vcs: int
    flit_bytes: int
    schema_version: int = ASTRA_NAMESPACE_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.participant_count <= 0:
            raise AstraNamespaceError("participant_count must be positive")
        endpoints = [e for _, e in self.rank_to_endpoint]
        if len(self.rank_to_endpoint) != self.participant_count:
            raise AstraNamespaceError(
                "the rank→endpoint table must cover every participant")
        if len(set(endpoints)) != len(endpoints):
            raise AstraNamespaceError(
                "duplicate endpoint binding in the namespace projection")
        if self.num_vcs <= 0:
            raise AstraNamespaceError("num_vcs must be positive")
        if self.flit_bytes <= 0:
            raise AstraNamespaceError("flit_bytes must be positive")
        for gid, members in self.groups.memberships:
            for endpoint in members:
                if not 0 <= endpoint < self.endpoint_count:
                    raise AstraNamespaceError(
                        f"communicator group {gid} names endpoint "
                        f"{endpoint} outside [0, {self.endpoint_count})")
        for _, mechanism in self.collective_mechanisms:
            if mechanism not in (MECHANISM_GLOBAL_LOGICAL_TOPOLOGY,
                                 MECHANISM_COMMUNICATOR_GROUP_RING):
                raise AstraNamespaceError(
                    f"unknown collective topology mechanism {mechanism!r}")

    # -- namespace queries ------------------------------------------------
    def endpoint_for(self, rank: int) -> int:
        try:
            return dict(self.rank_to_endpoint)[rank]
        except KeyError:
            raise AstraNamespaceError(
                f"participant rank {rank} has no endpoint binding") from None

    def participant_endpoints(self) -> tuple[int, ...]:
        return tuple(sorted(e for _, e in self.rank_to_endpoint))

    def idle_endpoints(self) -> tuple[int, ...]:
        """Fabric endpoints that are not canonical participants."""
        return tuple(sorted(set(range(self.endpoint_count))
                            - set(self.participant_endpoints())))

    def mechanisms(self) -> tuple[str, ...]:
        return tuple(sorted({m for _, m in self.collective_mechanisms}))

    def endpoint_namespace(self) -> tuple[int, ...]:
        return tuple(range(self.endpoint_count))

    # -- identity ---------------------------------------------------------
    def identity_dict(self) -> dict[str, Any]:
        return {
            "type": "srota/AstraExecutionNamespace",
            "schema_version": self.schema_version,
            "translation_version": MESSAGE_TRANSLATION_VERSION,
            "communicator_group_version": COMMUNICATOR_GROUP_VERSION,
            "machine_id": self.machine_id,
            "workload_projection_id": self.workload_projection_id,
            "participant_mapping_id": self.participant_mapping_id,
            "participant_count": self.participant_count,
            "rank_to_endpoint": [[r, e] for r, e in self.rank_to_endpoint],
            "endpoint_count": self.endpoint_count,
            "router_count": self.router_count,
            "attached_endpoint_count": self.attached_endpoint_count,
            "idle_endpoints": list(self.idle_endpoints()),
            "communicator_groups_id": self.groups.groups_id(),
            "collective_mechanisms": [[op, mech]
                                      for op, mech in self.collective_mechanisms],
            "num_vcs": self.num_vcs,
            "flit_bytes": self.flit_bytes,
        }

    def namespace_id(self) -> str:
        return content_hash("srota/AstraExecutionNamespace", 1,
                            self.identity_dict())

    def to_dict(self) -> dict[str, Any]:
        payload = dict(self.identity_dict())
        payload["namespace_id"] = self.namespace_id()
        payload["communicator_groups"] = json.loads(self.groups.to_json())
        return payload


def build_namespace(*, machine: Any, workload: Any, binding: Any,
                    endpoint_count: int, router_count: int) -> AstraExecutionNamespace:
    """Bind participants to endpoints and derive the collective groups.

    ``binding`` is the Slice-29 ``ParticipantEndpointMapping``: the only
    authority for rank→endpoint.  ``endpoint_count`` is the canonical fabric
    **node** count (== the ASTRA ``Sys.id`` namespace), which for AnyNet is
    not the router count.
    """
    if binding is None or not hasattr(binding, "binding_id"):
        raise AstraNamespaceError(
            "a canonical ParticipantEndpointMapping is required")
    if binding.participant_count != workload.participant_count:
        raise MappingInvalid(
            f"the participant mapping covers {binding.participant_count} "
            f"ranks but the workload projects {workload.participant_count}")
    if endpoint_count <= 0:
        raise AstraNamespaceError("endpoint_count must be positive")
    rows = tuple(binding.rank_to_endpoint)
    for rank, endpoint in rows:
        if not 0 <= endpoint < endpoint_count:
            raise MappingInvalid(
                f"rank {rank} binds to endpoint {endpoint} outside the "
                f"fabric's [0, {endpoint_count}) endpoint namespace")

    # collective membership: ranks → endpoints, canonicalised and deduplicated
    memberships: dict[tuple[int, ...], None] = {}
    mechanisms: list[tuple[str, str]] = []
    for op_id, _kind, _payload, participants in workload.collective_operations:
        endpoints = tuple(sorted(binding.endpoint_for(rank)
                                 for rank in participants))
        if not endpoints:
            raise AstraNamespaceError(
                f"collective {op_id!r} has an empty participant set")
        memberships[endpoints] = None
        mechanisms.append((op_id, collective_mechanism(
            endpoints=endpoints, endpoint_count=endpoint_count)))
    ordered = sorted(memberships)
    groups = CommunicatorGroups(
        memberships=tuple((index + 1, members)
                          for index, members in enumerate(ordered)))
    return AstraExecutionNamespace(
        machine_id=machine.machine_id(),
        workload_projection_id=workload.projection_id(),
        participant_count=workload.participant_count,
        rank_to_endpoint=rows,
        participant_mapping_id=binding.binding_id(),
        endpoint_count=endpoint_count,
        router_count=router_count,
        attached_endpoint_count=getattr(machine, "endpoint_count",
                                        endpoint_count),
        groups=groups,
        collective_mechanisms=tuple(mechanisms),
        num_vcs=machine.num_vcs,
        flit_bytes=machine.flit_bytes,
    )


def collective_mechanism(*, endpoints: tuple[int, ...],
                         endpoint_count: int) -> str:
    """Which mechanism the runtime uses to pick this collective's topology.

    Source: ``CommunicatorGroup::get_collective_plan`` — when the group spans
    every node it uses the global logical topology; otherwise it builds a
    one-dimensional ``RingTopology`` over exactly the group's endpoints.
    """
    if len(endpoints) == endpoint_count:
        return MECHANISM_GLOBAL_LOGICAL_TOPOLOGY
    return MECHANISM_COMMUNICATOR_GROUP_RING


# ── endpoint-indexed Chakra staging ───────────────────────────────────────

@dataclass(frozen=True)
class StagedWorkload:
    base: Path
    endpoint_files: tuple[tuple[int, Path], ...]
    rank_to_endpoint: tuple[tuple[int, int], ...]
    translated_send_recv: int
    pg_name_nodes: int
    translation_id: str

    def endpoints(self) -> tuple[int, ...]:
        return tuple(sorted(e for e, _ in self.endpoint_files))


def stage_endpoint_workload(*, workload: Any, namespace: AstraExecutionNamespace,
                            source_directory: str | Path,
                            target_directory: str | Path,
                            stem: str = "workload") -> StagedWorkload:
    """Write ``<stem>.et.<endpoint>.et`` for participants only.

    Canonical ETs are generated per **rank** by the Slice-30 writer.  This
    adapter translates only the runtime namespace:

      * the filename index becomes the endpoint id (``Sys.id``);
      * ``COMM_SEND_NODE``/``COMM_RECV_NODE`` ``comm_src``/``comm_dst`` are
        rewritten rank → endpoint;
      * every ``COMM_COLL_NODE`` gains ``pg_name = "<group id>"``.

    Non-participant endpoints receive **no** file, so the current source
    treats them as idle (``Workload.cc``: missing rank file ⇒ empty
    workload).  Returns the staged mapping so the caller can assert it.
    """
    source = Path(source_directory)
    target = Path(target_directory)
    target.mkdir(parents=True, exist_ok=True)
    try:
        from chakra.schema.protobuf import et_def_pb2 as pb
        from chakra.src.third_party.utils import protolib
    except Exception as exc:  # pragma: no cover - environment dependent
        raise AstraNamespaceError(
            f"the Chakra protobuf bindings are required: {exc}") from exc

    mechanisms = dict(namespace.collective_mechanisms)
    staged: list[tuple[int, Path]] = []
    sends = pg_nodes = 0
    for rank in workload.ranks():
        endpoint = namespace.endpoint_for(rank)
        source_file = source / f"{stem}.et.{rank}.et"
        if not source_file.is_file():
            raise AstraNamespaceError(
                f"canonical rank file missing: {source_file}")
        destination = target / f"{stem}.et.{endpoint}.et"
        translated = _translate_et(
            source_file, destination, pb=pb, protolib=protolib,
            namespace=namespace, mechanisms=mechanisms)
        sends += translated["send_recv"]
        pg_nodes += translated["pg_name"]
        staged.append((endpoint, destination))
    if len({e for e, _ in staged}) != len(staged):
        raise AstraNamespaceError(
            "two participants staged the same endpoint file")
    base = target / f"{stem}.et"
    base.write_bytes(staged[0][1].read_bytes())
    return StagedWorkload(
        base=base,
        endpoint_files=tuple(sorted(staged)),
        rank_to_endpoint=namespace.rank_to_endpoint,
        translated_send_recv=sends,
        pg_name_nodes=pg_nodes,
        translation_id=content_hash(
            "srota/AstraStagedWorkload", 1,
            {"namespace_id": namespace.namespace_id(),
             "translation_version": MESSAGE_TRANSLATION_VERSION,
             "endpoints": [e for e, _ in sorted(staged)],
             "send_recv_translated": sends,
             "pg_name_nodes": pg_nodes}),
    )


def _translate_et(source: Path, destination: Path, *, pb: Any, protolib: Any,
                  namespace: AstraExecutionNamespace,
                  mechanisms: dict[str, str]) -> dict[str, int]:
    """Rewrite one rank ET into the endpoint namespace, in place-safe order."""
    counters = {"send_recv": 0, "pg_name": 0}
    with open(source, "rb") as handle:
        metadata = pb.GlobalMetadata()
        if not protolib.decodeMessage(handle, metadata):
            raise AstraNamespaceError(f"{source} carries no GlobalMetadata")
        with open(destination, "wb") as out:
            protolib.encodeMessage(out, metadata)
            while True:
                node = pb.Node()
                if not protolib.decodeMessage(handle, node):
                    break
                if node.type in (pb.COMM_SEND_NODE, pb.COMM_RECV_NODE):
                    for attr in node.attr:
                        if attr.name in ("comm_src", "comm_dst"):
                            rank = int(attr.int32_val)
                            endpoint = _endpoint_or_refuse(
                                namespace, rank, node, attr.name)
                            attr.int32_val = endpoint
                            counters["send_recv"] += 1
                elif node.type == pb.COMM_COLL_NODE:
                    endpoints = _collective_membership(node, namespace)
                    group_id = namespace.groups.id_for(endpoints)
                    expected = mechanisms.get(node.name)
                    actual = collective_mechanism(
                        endpoints=endpoints,
                        endpoint_count=namespace.endpoint_count)
                    if expected is not None and expected != actual:
                        raise AstraNamespaceError(
                            f"collective {node.name!r} would run under "
                            f"{actual} but the namespace recorded {expected}")
                    pg = node.attr.add()
                    pg.name = "pg_name"
                    pg.string_val = str(group_id)
                    counters["pg_name"] += 1
                protolib.encodeMessage(out, node)
    return counters


def _endpoint_or_refuse(namespace: AstraExecutionNamespace, rank: int,
                        node: Any, attr_name: str) -> int:
    if rank not in dict(namespace.rank_to_endpoint):
        raise AstraNamespaceError(
            f"ET node {node.name!r} {attr_name}={rank} is not a canonical "
            "participant rank; refusing to translate a non-rank value")
    return namespace.endpoint_for(rank)


def _collective_membership(node: Any,
                           namespace: AstraExecutionNamespace) -> tuple[int, ...]:
    """The endpoint membership a COMM_COLL node belongs to.

    A Chakra collective node names no participants itself — membership comes
    from the canonical workload.  The node's compact collective type plus the
    namespace's only group set make this unambiguous for single-group
    workloads, and ambiguous cases are refused rather than guessed.
    """
    if len(namespace.groups.memberships) == 1:
        return namespace.groups.memberships[0][1]
    participants = namespace.participant_endpoints()
    if len(namespace.groups.memberships) == 0:
        raise AstraNamespaceError("no communicator group for a collective")
    # multiple groups: only the full participant set is unambiguously inferred
    for _gid, members in namespace.groups.memberships:
        if members == participants:
            return members
    raise AstraNamespaceError(
        "collective membership is ambiguous across communicator groups; "
        "refusing to guess a group")


def write_communicator_groups(namespace: AstraExecutionNamespace,
                              directory: str | Path) -> Path:
    target = Path(directory)
    target.mkdir(parents=True, exist_ok=True)
    path = target / COMM_GROUP_FILE
    text = namespace.groups.to_json() + "\n"
    if path.exists() and path.read_text(encoding="utf-8") != text:
        raise AstraNamespaceError(
            f"{path} already holds a different communicator-group document")
    path.write_text(text, encoding="utf-8")
    return path


# ── runtime command surface ───────────────────────────────────────────────

def comm_group_argument() -> str:
    return _GROUP_KEY
