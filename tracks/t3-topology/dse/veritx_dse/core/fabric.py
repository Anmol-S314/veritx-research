"""veritx_dse.core.fabric — the one content-addressed fabric identity.

Wave B of the study-integrity program (post-freeze review items 1/4/13/26):
before this module, "which fabric executed" was described by ad-hoc dicts
in two places (standalone preset resolution, serving cluster resolution),
while comparison fingerprints and execution fingerprints re-derived their
own subsets. One concept, one implementation.

``FabricArtifact`` is the single authority for fabric identity:

* built FROM the two legitimate authorities — a registered preset
  (``fabric_from_preset``, consuming the same param resolution that
  ``build_config`` renders) or a serving cluster (``fabric_from_serving_cluster``,
  consuming the child's own config_builder arithmetic);
* content-addressed — ``artifact_hash`` covers every result-affecting
  fabric dimension; any change (VCs, buffers, packet/flit size, routing,
  dims) forks the hash, so reuse/compare decisions key on the hash, not
  on topology names;
* round-trip safe — ``from_dict`` re-verifies the hash like the
  route_artifact pattern: tampered dimensions fail closed.

``MappingArtifact`` pins rank→device placement (review item 25): high-level
parallelism does not identify WHERE ranks live, and two placements sharing
TP/EP/DP/PP can still behave differently. Content-addressed, order-canonical
by rank.

Both types are pure identity — they carry no I/O and never talk to a
backend. Slices lower backends FROM an artifact and record executed
evidence against its hash.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any

from .spec import canonical_json

__all__ = [
    "FabricError",
    "FabricArtifact",
    "fabric_from_preset",
    "fabric_from_serving_cluster",
    "MappingArtifact",
    "mapping_artifact",
]

AUTHORITIES = ("preset", "serving_cluster")


class FabricError(ValueError):
    """Unbuildable fabric/mapping identity — unknown dimensions refuse."""


def _sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode()).hexdigest()


def _req_str(name: str, v: Any) -> str:
    if not isinstance(v, str) or not v:
        raise FabricError(
            f"fabric dimension {name!r} must be a non-empty string, got {v!r}")
    return v


def _req_int(name: str, v: Any, *, minimum: int = 1) -> int:
    if not isinstance(v, int) or isinstance(v, bool) or v < minimum:
        raise FabricError(
            f"fabric dimension {name!r} must be an int >= {minimum}, got {v!r}")
    return v


@dataclass(frozen=True)
class FabricArtifact:
    """One exact fabric. Hash covers every result-affecting dimension."""
    authority: str                 # "preset" | "serving_cluster"
    topology_id: str               # registered preset id / serving fixture id
    backend: str                   # BookSim topology type (mesh, torus, anynet, ...)
    routing: str                   # BookSim routing function name
    node_count: int
    dimensions: tuple[int, ...]    # k/n-style dims; () when the backend takes params only
    vc_count: int
    buffer_flits: int
    packet_size_flits: int
    flit_size_bytes: int
    params: dict[str, Any]         # topology-specific overrides (k, n, c, ...), hash-sorted
    artifact_hash: str = ""

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "topology_id": self.topology_id,
            "backend": self.backend,
            "routing": self.routing,
            "node_count": self.node_count,
            "dimensions": list(self.dimensions),
            "vc_count": self.vc_count,
            "buffer_flits": self.buffer_flits,
            "packet_size_flits": self.packet_size_flits,
            "flit_size_bytes": self.flit_size_bytes,
            "params": dict(sorted(self.params.items())),
        }

    def to_dict(self) -> dict[str, Any]:
        d = self._identity_dict()
        d["artifact_hash"] = self.artifact_hash
        return d

    def execution_dims(self) -> dict[str, Any]:
        """Project onto study.ExecutionFingerprint's fabric dimensions.

        packet_bytes is derived honestly: BookSim's payload per packet is
        packet_size_flits × flit_size_bytes — never invented, never a
        separate recorded number that could disagree.
        """
        return {
            "fabric_topology": self.topology_id,
            "fabric_routing": self.routing,
            "vc_count": self.vc_count,
            "buffer_flits": self.buffer_flits,
            "packet_bytes": self.packet_size_flits * self.flit_size_bytes,
            "flit_bytes": self.flit_size_bytes,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "FabricArtifact":
        try:
            fa = FabricArtifact(
                authority=d["authority"], topology_id=d["topology_id"],
                backend=d["backend"], routing=d["routing"],
                node_count=d["node_count"], dimensions=d.get("dimensions", ()),
                vc_count=d["vc_count"], buffer_flits=d["buffer_flits"],
                packet_size_flits=d["packet_size_flits"],
                flit_size_bytes=d["flit_size_bytes"],
                params=d.get("params", {}),
            )
        except (KeyError, TypeError) as e:
            raise FabricError(f"malformed FabricArtifact: {e}") from e
        _validate_and_hash(fa)   # recompute + validate every dimension
        if fa.artifact_hash != d.get("artifact_hash"):
            raise FabricError(
                "artifact_hash mismatch — a fabric dimension was tampered "
                "with or corrupted")
        return fa


def _validate_and_hash(art: FabricArtifact) -> FabricArtifact:
    if art.authority not in AUTHORITIES:
        raise FabricError(
            f"fabric authority {art.authority!r} not in {AUTHORITIES} — an "
            "artifact must name which authority owns it")
    _req_str("topology_id", art.topology_id)
    _req_str("backend", art.backend)
    _req_str("routing", art.routing)
    _req_int("node_count", art.node_count)
    for i, dim in enumerate(art.dimensions):
        _req_int(f"dimensions[{i}]", dim)
    _req_int("vc_count", art.vc_count)
    _req_int("buffer_flits", art.buffer_flits)
    _req_int("packet_size_flits", art.packet_size_flits)
    _req_int("flit_size_bytes", art.flit_size_bytes)
    if not isinstance(art.params, dict):
        raise FabricError("fabric params must be a dict")
    object.__setattr__(art, "artifact_hash",
                       _sha256(canonical_json(art._identity_dict())))
    return art


def fabric_from_preset(topo: Any, *, sim_params: dict[str, Any],
                       node_count: int) -> FabricArtifact:
    """Build the fabric artifact for a registered standalone preset.

    ``sim_params`` MUST come from ``simulation.booksim.resolve_fabric_params``
    — the same resolution ``build_config`` renders from — so the artifact
    records exactly what the backend receives. A second param-resolution
    implementation here would be a second topology truth.
    """
    dims = topo.params.get("k"), topo.params.get("n")
    return _validate_and_hash(FabricArtifact(
        authority="preset",
        topology_id=topo.name,
        backend=topo.backend,
        routing=topo.routing,
        node_count=node_count,
        dimensions=tuple(int(d) for d in dims if isinstance(d, int)),
        vc_count=int(sim_params["num_vcs"]),
        buffer_flits=int(sim_params["vc_buf_size"]),
        packet_size_flits=int(sim_params["packet_size"]),
        flit_size_bytes=int(sim_params["flit_size"]),
        params=dict(topo.params),
    ))


def fabric_from_serving_cluster(expected: dict[str, Any]) -> FabricArtifact:
    """Build the fabric artifact from the serving cluster authority.

    ``expected`` is the dict produced by
    ``core.serving.resolve_serving_fabric_identity`` (the child's own
    config_builder arithmetic). For multi-entry topologies (per-instance
    fabrics) every entry must agree on routing/VC/packet config or the
    artifact refuses — a fabric with two different routing truths is not
    one fabric.
    """
    topologies = expected.get("topology") or expected.get("topologies")
    if isinstance(topologies, str):
        topologies = [topologies]
    if not isinstance(topologies, (list, tuple)) or not topologies:
        raise FabricError(
            "serving fabric needs a topology list from the cluster resolver")
    dims = tuple(int(d) for d in (expected.get("dimensions") or ()))
    nodes = expected.get("npu_count") or expected.get("node_count")
    backend = ("anynet" if len(topologies) > 1
               else str(topologies[0]).replace("FullyConnected", "anynet")
               .lower())
    # The child's lowering: single-entry mesh → dor; multi-entry anynet →
    # min (serving/__main__._prepare_booksim_config). Recorded as the
    # expected routing the executed config must show.
    routing = expected.get("routing") or ("dor" if backend == "mesh" else "min")
    vcs = expected.get("num_vcs") or expected.get("vc_count")
    if vcs is None:
        raise FabricError(
            "serving fabric identity lacks vc_count — the cluster resolver "
            "must record the executed VC config (review item 14: no hidden "
            "backend defaults)")
    buf = expected.get("vc_buf_size") or expected.get("buffer_flits")
    if buf is None:
        raise FabricError(
            "serving fabric identity lacks buffer_flits — unknown execution "
            "dimensions refuse")
    pkt = expected.get("packet_size") or expected.get("packet_size_flits")
    if pkt is None:
        raise FabricError(
            "serving fabric identity lacks packet_size — unknown execution "
            "dimensions refuse")
    flit_bytes = expected.get("flit_size")
    if flit_bytes is None:
        raise FabricError(
            "serving fabric identity lacks flit_size — unknown execution "
            "dimensions refuse")
    return _validate_and_hash(FabricArtifact(
        authority="serving_cluster",
        topology_id=_req_str(
            "topology_id",
            expected.get("fixture_id") or expected.get("cluster_id")
            or expected.get("cluster") or "serving_cluster"),
        backend=backend,
        routing=str(routing),
        node_count=int(nodes) if nodes is not None else 0,
        dimensions=dims,
        vc_count=int(vcs),
        buffer_flits=int(buf),
        packet_size_flits=int(pkt),
        flit_size_bytes=int(flit_bytes),
        params={k: v for k, v in expected.items()
                if k not in ("topology", "topologies", "dimensions",
                             "npu_count", "node_count", "routing",
                             "num_vcs", "vc_count", "vc_buf_size",
                             "buffer_flits", "packet_size",
                             "packet_size_flits", "flit_size",
                             "fixture_id", "cluster", "source")},
    ))


@dataclass(frozen=True)
class MappingArtifact:
    """Rank→device placement, content-addressed, order-canonical by rank."""
    authority: str
    entries: tuple[dict[str, Any], ...]   # [{"rank": 0, "device": "node0/npu0"}, ...]
    mapping_hash: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "authority": self.authority,
            "entries": [dict(e) for e in self.entries],
            "mapping_hash": self.mapping_hash,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MappingArtifact":
        try:
            ma = MappingArtifact(
                authority=d["authority"],
                entries=tuple(dict(e) for e in d["entries"]),
            )
        except (KeyError, TypeError) as e:
            raise FabricError(f"malformed MappingArtifact: {e}") from e
        object.__setattr__(
            ma, "mapping_hash", _sha256(canonical_json(ma.to_dict())))
        if ma.mapping_hash != d.get("mapping_hash"):
            raise FabricError(
                "mapping_hash mismatch — placement was tampered with or "
                "corrupted")
        return ma


def mapping_artifact(*, authority: str,
                     entries: list[dict[str, Any]] | tuple) -> MappingArtifact:
    """Build + hash a rank→device placement artifact.

    Entries are canonicalized by the rank key (stable sort — never by
    device identity, never by input order). Ranks must be exactly
    0..n-1 (gaps/duplicates hide placement semantics), every entry needs
    a non-empty device identity.
    """
    if not isinstance(entries, (list, tuple)) or not entries:
        raise FabricError(
            f"mapping entries must be a non-empty list, got {entries!r}")
    clean = []
    for i, e in enumerate(entries):
        if not isinstance(e, dict):
            raise FabricError(f"mapping[{i}] must be a dict, got {e!r}")
        rank = e.get("rank")
        if not isinstance(rank, int) or isinstance(rank, bool) or rank < 0:
            raise FabricError(f"mapping[{i}].rank must be an int >= 0")
        device = e.get("device") or e.get("artifact")
        if not isinstance(device, str) or not device:
            raise FabricError(
                f"mapping[{i}] needs a non-empty device identity")
        key = "device" if e.get("device") is not None else "artifact"
        clean.append({"rank": rank, key: device})
    clean.sort(key=lambda e: e["rank"])          # canonical by rank key
    ranks = [e["rank"] for e in clean]
    if ranks != list(range(len(ranks))):
        raise FabricError(
            f"mapping ranks must be exactly 0..{len(ranks) - 1}, got {ranks}")
    ma = MappingArtifact(
        authority=_req_str("authority", authority),
        entries=tuple(clean),
    )
    object.__setattr__(ma, "mapping_hash",
                       _sha256(canonical_json(ma.to_dict())))
    return ma
