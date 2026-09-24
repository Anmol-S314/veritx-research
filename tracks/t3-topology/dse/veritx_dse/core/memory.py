"""memory.py — canonical memory semantics, v1 (MEMORY-ROADMAP Phase 14a).

A content-addressed, backend-independent representation of RESOLVED memory
demand and placement: what the workload needs living where, as semantic
accesses over logical byte addresses. Follows the Phase-9/10 artifact
pattern (workload/canonical.py, core/route_artifact.py): frozen dataclasses,
eager validation at builders (the only sanctioned constructors),
_hash-of-canonical-JSON identity, tamper-evident from_dict.

What this artifact is NOT (deliberate v1 boundaries):

* Not a workload duplicate: COMPUTE operand sizes/locations live in
  CanonicalWorkload (input/weight/output_bytes + _loc). This artifact
  references that workload by hash and resolves placement here.
* Not a backend input: NO Ramulator address vectors (channel/bank/row/col),
  NO issue cycles. The Phase-15 lowerer maps logical byte addresses to
  backend coordinates; inventing them here would smuggle backend grammar
  into canonical semantics (spike: ReadWriteTrace consumes addr_vec and
  issues one request/tick, so ready-cycle timing would be fabricated).
* Not a cache model: SCRATCHPAD tier marks explicitly on-chip-resident
  data; no hit-rate/reuse claims. Ramulator starts after an access has
  become a DRAM/HBM transaction.

Identity (what the hashes cover):

  region_table_hash  hash over regions ONLY (sorted by region_id) — the
                     placement truth a lowerer verifies without trusting
                     the rest of the artifact
  access_stream_hash hash over accesses in ARTIFACT ORDER (order is
                     execution semantics, like workload op order) — the
                     hash a Ramulator lowerer quotes as "I lowered stream
                     sha256:..."
  artifact_hash      hash over the full identity dict (schema, workload
                     hash, node count, mapping policy, both table hashes,
                     assumptions)

Excluded from identity: display name, JSON formatting, file paths.
"""
from __future__ import annotations

from veritx_dse.core.errors import SemanticError

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

SCHEMA_VERSION = 1

# v1 object classes. OTHER is allowed only when the source semantics
# genuinely fit no known class — never inferred into a prettier category.
OBJECT_TYPES = frozenset({"WEIGHT", "ACTIVATION", "KV_CACHE", "OUTPUT",
                          "OTHER"})

# v1 access classes. Backend-independent: READ/WRITE over logical bytes.
ACCESS_KINDS = frozenset({"READ", "WRITE"})

# v1 placement tiers. HBM = off-chip traffic evaluated by the memory
# backend. SCRATCHPAD = explicitly on-chip-resident (never HBM traffic).
# DDR/CXL/STORAGE/REMOTE placements do not exist in v1: canonical locations
# implying them are UNSUPPORTED at the resolver (Phase 14b), never silently
# remapped to HBM.
PLACEMENT_TIERS = frozenset({"HBM", "SCRATCHPAD"})

# v1 address-allocation policies. Unknown names refuse (fail-closed): an
# unrecognized policy means unrecognized address semantics.
ADDRESS_POLICIES = frozenset({"contiguous_aligned_v1"})

# Architectural address-space bound for overflow checks (v1 has no capacity
# model — capacity constraints are Phase-16 requirements, not schema).
_ADDR_SPACE_BITS = 64


class MemoryArtifactError(ValueError, SemanticError):
    """Resolved memory semantics cannot be represented or trusted."""


def _sha256_of(obj: Any) -> str:
    payload = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                         ensure_ascii=True).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _is_pow2(v: int) -> bool:
    return v > 0 and (v & (v - 1)) == 0


# ── placement ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MemoryPlacement:
    """Typed placement: which physical memory, no finer (v1).

    tier:   HBM | SCRATCHPAD (nothing else exists in v1)
    device: owning device index (>= 0)
    stack:  HBM stack index, or None when the design does not place at
            stack granularity (normal: the lowerer owns stack/bank/row).
    """
    tier: str
    device: int
    stack: int | None = None

    def __post_init__(self) -> None:
        if self.tier not in PLACEMENT_TIERS:
            raise MemoryArtifactError(
                f"placement tier {self.tier!r} unsupported in v1 — "
                f"supported: {sorted(PLACEMENT_TIERS)}")
        for name, v in (("device", self.device), ("stack", self.stack)):
            if v is None:
                continue
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise MemoryArtifactError(
                    f"placement {name} must be a non-negative int, "
                    f"got {v!r}")

    def to_dict(self) -> dict[str, Any]:
        return {"tier": self.tier, "device": self.device,
                "stack": self.stack}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryPlacement":
        try:
            return cls(tier=d["tier"], device=d["device"],
                       stack=d.get("stack"))
        except (KeyError, TypeError) as e:
            raise MemoryArtifactError(
                f"malformed MemoryPlacement: {e}") from e


# ── address-mapping policy ────────────────────────────────────────────────

@dataclass(frozen=True)
class AddressMappingPolicy:
    """Versioned deterministic address-allocation policy (in identity).

    v1 supports contiguous_aligned_v1: regions sorted by stable semantic
    identity (region_id), cursor aligned up per region, bases assigned.
    parameters must be JSON-safe (checked at build).
    """
    name: str
    version: int
    alignment_bytes: int
    parameters: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.name not in ADDRESS_POLICIES:
            raise MemoryArtifactError(
                f"address policy {self.name!r} unsupported — supported: "
                f"{sorted(ADDRESS_POLICIES)} (fail-closed: unknown policy "
                "means unknown address semantics)")
        if not isinstance(self.version, int) or isinstance(self.version,
                                                            bool) \
                or self.version < 1:
            raise MemoryArtifactError(
                f"policy version must be an int >= 1, got "
                f"{self.version!r}")
        if not isinstance(self.alignment_bytes, int) or \
                not _is_pow2(self.alignment_bytes):
            raise MemoryArtifactError(
                f"alignment_bytes must be a positive power of two, got "
                f"{self.alignment_bytes!r}")
        try:
            json.dumps(self.parameters, sort_keys=True)
        except (TypeError, ValueError) as e:
            raise MemoryArtifactError(
                f"policy parameters must be JSON-safe, got "
                f"{self.parameters!r} ({e})") from e
        object.__setattr__(self, "parameters",
                           json.loads(json.dumps(self.parameters,
                                                 sort_keys=True)))

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "version": self.version,
                "alignment_bytes": self.alignment_bytes,
                "parameters": self.parameters}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AddressMappingPolicy":
        try:
            return cls(name=d["name"], version=d["version"],
                       alignment_bytes=d["alignment_bytes"],
                       parameters=d.get("parameters", {}))
        except (KeyError, TypeError) as e:
            raise MemoryArtifactError(
                f"malformed AddressMappingPolicy: {e}") from e


# ── region ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MemoryRegion:
    """One placed tensor/object: logical byte range in a typed memory."""
    region_id: str
    object_type: str
    size_bytes: int
    base_address: int
    placement: MemoryPlacement
    alignment_bytes: int
    source_op_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.region_id, str) or not self.region_id:
            raise MemoryArtifactError(
                f"region_id must be a non-empty string, got "
                f"{self.region_id!r}")
        if self.object_type not in OBJECT_TYPES:
            raise MemoryArtifactError(
                f"region {self.region_id!r}: object_type "
                f"{self.object_type!r} unknown — supported: "
                f"{sorted(OBJECT_TYPES)} (OTHER only when the source "
                "semantics genuinely fit no known class)")
        if not isinstance(self.size_bytes, int) or \
                isinstance(self.size_bytes, bool) or self.size_bytes <= 0:
            raise MemoryArtifactError(
                f"region {self.region_id!r}: size_bytes must be a positive "
                f"int of BYTES, got {self.size_bytes!r} (zero-byte operands "
                "carry no traffic — the resolver skips them, it does not "
                "mint empty regions)")
        if not isinstance(self.base_address, int) or \
                isinstance(self.base_address, bool) or \
                self.base_address < 0:
            raise MemoryArtifactError(
                f"region {self.region_id!r}: base_address must be a "
                f"non-negative int, got {self.base_address!r}")
        if self.base_address + self.size_bytes > (1 << _ADDR_SPACE_BITS):
            raise MemoryArtifactError(
                f"region {self.region_id!r}: address range overflows the "
                f"{_ADDR_SPACE_BITS}-bit address space")
        if not isinstance(self.alignment_bytes, int) or \
                not _is_pow2(self.alignment_bytes):
            raise MemoryArtifactError(
                f"region {self.region_id!r}: alignment_bytes must be a "
                f"positive power of two, got {self.alignment_bytes!r}")
        if self.base_address % self.alignment_bytes != 0:
            raise MemoryArtifactError(
                f"region {self.region_id!r}: base_address "
                f"{self.base_address} violates alignment "
                f"{self.alignment_bytes}")
        if not isinstance(self.source_op_id, str) or not self.source_op_id:
            raise MemoryArtifactError(
                f"region {self.region_id!r}: source_op_id must be a "
                "non-empty string (provenance — every region traces to "
                "the op whose demand created it)")
        if not isinstance(self.placement, MemoryPlacement):
            raise MemoryArtifactError(
                f"region {self.region_id!r}: placement must be a "
                "MemoryPlacement, never a free string")

    def end_address(self) -> int:
        """First byte past the region (half-open [base, end))."""
        return self.base_address + self.size_bytes

    def to_dict(self) -> dict[str, Any]:
        return {"region_id": self.region_id,
                "object_type": self.object_type,
                "size_bytes": self.size_bytes,
                "base_address": self.base_address,
                "alignment_bytes": self.alignment_bytes,
                "placement": self.placement.to_dict(),
                "source_op_id": self.source_op_id}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryRegion":
        try:
            return cls(
                region_id=d["region_id"], object_type=d["object_type"],
                size_bytes=d["size_bytes"], base_address=d["base_address"],
                placement=MemoryPlacement.from_dict(d["placement"]),
                alignment_bytes=d["alignment_bytes"],
                source_op_id=d["source_op_id"])
        except (KeyError, TypeError) as e:
            raise MemoryArtifactError(
                f"malformed MemoryRegion: {e}") from e


# ── access ────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MemoryAccess:
    """One backend-independent semantic access: logical bytes + order.

    Address = region.base_address + offset_bytes (logical byte address;
    the Phase-15 lowerer maps it to backend coordinates). dependencies =
    access_ids that must complete first (ordering, not cycles — v1 has no
    ready_cycle: the sources do not supply grounded issue timing).
    """
    access_id: str
    source_op_id: str
    region_id: str
    kind: str
    offset_bytes: int
    size_bytes: int
    source_node: int
    dependencies: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.access_id, str) or not self.access_id:
            raise MemoryArtifactError(
                f"access_id must be a non-empty string, got "
                f"{self.access_id!r}")
        if not isinstance(self.source_op_id, str) or not self.source_op_id:
            raise MemoryArtifactError(
                f"access {self.access_id!r}: source_op_id must be a "
                "non-empty string")
        if not isinstance(self.region_id, str) or not self.region_id:
            raise MemoryArtifactError(
                f"access {self.access_id!r}: region_id must be a "
                "non-empty string")
        if self.kind not in ACCESS_KINDS:
            raise MemoryArtifactError(
                f"access {self.access_id!r}: kind {self.kind!r} unknown — "
                f"supported: {sorted(ACCESS_KINDS)}")
        for name, v in (("offset_bytes", self.offset_bytes),
                        ("size_bytes", self.size_bytes),
                        ("source_node", self.source_node)):
            if not isinstance(v, int) or isinstance(v, bool) or v < 0:
                raise MemoryArtifactError(
                    f"access {self.access_id!r}: {name} must be a "
                    f"non-negative int, got {v!r}")
        if self.size_bytes == 0:
            raise MemoryArtifactError(
                f"access {self.access_id!r}: zero-byte accesses carry no "
                "traffic and cannot be conserved — refuse, don't record")
        if not isinstance(self.dependencies, tuple):
            object.__setattr__(self, "dependencies",
                               tuple(self.dependencies))
        for dep in self.dependencies:
            if not isinstance(dep, str) or not dep:
                raise MemoryArtifactError(
                    f"access {self.access_id!r}: dependency {dep!r} must "
                    "be a non-empty access_id string")
            if dep == self.access_id:
                raise MemoryArtifactError(
                    f"access {self.access_id!r}: self-dependency is a "
                    "cycle by construction")
        if len(set(self.dependencies)) != len(self.dependencies):
            raise MemoryArtifactError(
                f"access {self.access_id!r}: duplicate dependencies")

    def to_dict(self) -> dict[str, Any]:
        return {"access_id": self.access_id,
                "source_op_id": self.source_op_id,
                "region_id": self.region_id, "kind": self.kind,
                "offset_bytes": self.offset_bytes,
                "size_bytes": self.size_bytes,
                "source_node": self.source_node,
                "dependencies": list(self.dependencies)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryAccess":
        try:
            return cls(
                access_id=d["access_id"],
                source_op_id=d["source_op_id"], region_id=d["region_id"],
                kind=d["kind"], offset_bytes=d["offset_bytes"],
                size_bytes=d["size_bytes"], source_node=d["source_node"],
                dependencies=tuple(d.get("dependencies", ())))
        except (KeyError, TypeError) as e:
            raise MemoryArtifactError(
                f"malformed MemoryAccess: {e}") from e


# ── builders (validate eagerly; the only sanctioned constructors) ─────────

def build_region(region_id: str, object_type: str, size_bytes: int,
                 base_address: int, placement: MemoryPlacement,
                 alignment_bytes: int, source_op_id: str) -> MemoryRegion:
    """Eagerly-validated region constructor (MemoryRegion is frozen)."""
    return MemoryRegion(
        region_id=region_id, object_type=object_type,
        size_bytes=size_bytes, base_address=base_address,
        placement=placement, alignment_bytes=alignment_bytes,
        source_op_id=source_op_id)


def build_access(access_id: str, source_op_id: str, region_id: str,
                 kind: str, offset_bytes: int, size_bytes: int,
                 source_node: int,
                 dependencies: tuple[str, ...] = ()) -> MemoryAccess:
    """Eagerly-validated access constructor (cross-refs checked at the
    artifact builder: region existence, bounds, node range, dep closure)."""
    return MemoryAccess(
        access_id=access_id, source_op_id=source_op_id,
        region_id=region_id, kind=kind, offset_bytes=offset_bytes,
        size_bytes=size_bytes, source_node=source_node,
        dependencies=tuple(dependencies))


def allocate_regions(specs: list[dict[str, Any]],
                     policy: AddressMappingPolicy) -> list[MemoryRegion]:
    """Deterministic base-address allocation for ONE address space.

    Caller groups specs by placement scope ((tier, device, stack) share one
    address space — separate physical memories must be allocated in
    separate calls, or identical addresses across scopes would collide).
    Regions sort by stable semantic identity (region_id), the cursor aligns
    up per region, bases assign. Same specs in any input order → identical
    bases. Each spec: region_id, object_type, size_bytes, placement,
    source_op_id, optional alignment_bytes (default: policy alignment).
    """
    if policy.name != "contiguous_aligned_v1":
        raise MemoryArtifactError(
            f"allocate_regions implements contiguous_aligned_v1, not "
            f"{policy.name!r}")
    ordered = sorted(specs, key=lambda s: s["region_id"])
    seen: set[str] = set()
    out: list[MemoryRegion] = []
    cursor = 0
    for s in ordered:
        rid = s["region_id"]
        if rid in seen:
            raise MemoryArtifactError(
                f"duplicate region_id {rid!r} in allocation specs")
        seen.add(rid)
        align = s.get("alignment_bytes", policy.alignment_bytes)
        if not isinstance(align, int) or not _is_pow2(align):
            raise MemoryArtifactError(
                f"region {rid!r}: alignment_bytes must be a positive "
                f"power of two, got {align!r}")
        cursor = ((cursor + align - 1) // align) * align
        out.append(build_region(
            rid, s["object_type"], s["size_bytes"], cursor,
            s["placement"], align, s["source_op_id"]))
        cursor += s["size_bytes"]
    return out


# ── the artifact ──────────────────────────────────────────────────────────

@dataclass(frozen=True)
class MemoryArtifact:
    """Versioned, immutable, content-addressed resolved memory semantics."""
    name: str
    source_workload_hash: str
    num_nodes: int
    regions: tuple[MemoryRegion, ...]
    accesses: tuple[MemoryAccess, ...]
    mapping_policy: AddressMappingPolicy
    assumptions: tuple[str, ...] = ()
    schema_version: int = 1
    region_table_hash: str = field(default="", compare=True)
    access_stream_hash: str = field(default="", compare=True)
    artifact_hash: str = field(default="", compare=True)

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name:
            raise MemoryArtifactError("name must be a non-empty string")
        if not isinstance(self.source_workload_hash, str) or \
                not self.source_workload_hash.startswith("sha256:"):
            raise MemoryArtifactError(
                "source_workload_hash is mandatory and must be a workload "
                f"content hash (sha256:...), got "
                f"{self.source_workload_hash!r} — an artifact that cannot "
                "name its workload cannot be conserved against it")
        if not isinstance(self.num_nodes, int) or \
                isinstance(self.num_nodes, bool) or self.num_nodes < 1:
            raise MemoryArtifactError(
                f"num_nodes must be an int >= 1, got {self.num_nodes!r}")
        object.__setattr__(self, "regions", tuple(self.regions))
        object.__setattr__(self, "accesses", tuple(self.accesses))
        object.__setattr__(self, "assumptions", tuple(self.assumptions))
        if not self.regions:
            raise MemoryArtifactError(
                "artifact has no regions — memory demand with no placed "
                "object is not evaluatable")
        for a in self.assumptions:
            if not isinstance(a, str) or not a:
                raise MemoryArtifactError(
                    f"assumption {a!r} must be a non-empty string "
                    "(assumptions are identity — anonymous ones lie)")
        self._check_regions()
        self._check_accesses()
        if not self.region_table_hash:
            object.__setattr__(self, "region_table_hash",
                               _sha256_of({"regions":
                                           self._canon_regions()}))
        if not self.access_stream_hash:
            object.__setattr__(self, "access_stream_hash",
                               _sha256_of({"accesses":
                                           self._canon_accesses()}))
        if not self.artifact_hash:
            object.__setattr__(self, "artifact_hash",
                               _sha256_of(self._identity_dict()))

    # -- cross-reference validation --------------------------------------

    def _check_regions(self) -> None:
        ids = [r.region_id for r in self.regions]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise MemoryArtifactError(
                f"duplicate region_id(s): {dupes}")
        # Overlap is refused within one placement scope (v1 supports no
        # shared/aliased mode — overlapping claims on one memory would let
        # two tensors silently share bytes). Separate scopes (different
        # tier/device/stack = different physical memories) may reuse the
        # same numeric addresses.
        by_scope: dict[tuple, list[MemoryRegion]] = {}
        for r in self.regions:
            key = (r.placement.tier, r.placement.device,
                   r.placement.stack)
            by_scope.setdefault(key, []).append(r)
        for key, rs in by_scope.items():
            spans = sorted((r.base_address, r.end_address(), r.region_id)
                           for r in rs)
            for (s0, e0, id0), (s1, e1, id1) in zip(spans, spans[1:]):
                if s1 < e0:
                    raise MemoryArtifactError(
                        f"regions {id0!r} [{s0},{e0}) and {id1!r} "
                        f"[{s1},{e1}) overlap in placement scope {key} — "
                        "v1 supports no aliasing (fail-closed)")

    def _check_accesses(self) -> None:
        ids = [a.access_id for a in self.accesses]
        if len(ids) != len(set(ids)):
            dupes = sorted({i for i in ids if ids.count(i) > 1})
            raise MemoryArtifactError(
                f"duplicate access_id(s): {dupes}")
        by_region = {r.region_id: r for r in self.regions}
        idset = set(ids)
        for a in self.accesses:
            reg = by_region.get(a.region_id)
            if reg is None:
                raise MemoryArtifactError(
                    f"access {a.access_id!r}: unknown region "
                    f"{a.region_id!r} — accesses cannot dangle")
            if a.offset_bytes + a.size_bytes > reg.size_bytes:
                raise MemoryArtifactError(
                    f"access {a.access_id!r}: range "
                    f"[{a.offset_bytes},{a.offset_bytes + a.size_bytes}) "
                    f"exceeds region {reg.region_id!r} size "
                    f"{reg.size_bytes} — out-of-bounds accesses refuse, "
                    "never clamp")
            if not (0 <= a.source_node < self.num_nodes):
                raise MemoryArtifactError(
                    f"access {a.access_id!r}: source_node {a.source_node} "
                    f"out of range [0, {self.num_nodes})")
            for dep in a.dependencies:
                if dep not in idset:
                    raise MemoryArtifactError(
                        f"access {a.access_id!r}: unknown dependency "
                        f"{dep!r} — ordering cannot dangle")
        self._check_acyclic(ids)

    def _check_acyclic(self, ids: list[str]) -> None:
        deps = {a.access_id: set(a.dependencies) for a in self.accesses}
        visiting: set[str] = set()
        done: set[str] = set()

        def visit(n: str, chain: list[str]) -> None:
            if n in done:
                return
            if n in visiting:
                raise MemoryArtifactError(
                    "dependency cycle: " + " -> ".join(chain + [n]) +
                    " — execution order must be a DAG")
            visiting.add(n)
            for m in sorted(deps[n]):
                visit(m, chain + [n])
            visiting.discard(n)
            done.add(n)

        for i in ids:
            visit(i, [])

    # -- identity --------------------------------------------------------

    def _canon_regions(self) -> list[dict[str, Any]]:
        return [r.to_dict() for r in
                sorted(self.regions, key=lambda r: r.region_id)]

    def _canon_accesses(self) -> list[dict[str, Any]]:
        # Stream order is execution semantics — preserved, never sorted
        # (like workload op order in Phase 9).
        return [a.to_dict() for a in self.accesses]

    def _identity_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_workload_hash": self.source_workload_hash,
            "num_nodes": self.num_nodes,
            "mapping_policy": self.mapping_policy.to_dict(),
            "region_table_hash": self.region_table_hash,
            "access_stream_hash": self.access_stream_hash,
            "assumptions": list(self.assumptions),
        }

    # -- serialization ---------------------------------------------------

    def serialize(self) -> dict[str, Any]:
        d = self._identity_dict()
        d["name"] = self.name  # presentation sidecar: roundtrips, never
        # hashed (a rename must not change memory identity)
        d["regions"] = [r.to_dict() for r in self.regions]
        d["accesses"] = [a.to_dict() for a in self.accesses]
        d["artifact_hash"] = self.artifact_hash
        return d

    def to_dict(self) -> dict[str, Any]:
        return self.serialize()

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "MemoryArtifact":
        """Load serialized form; re-verifies every hash (tamper-evident)."""
        try:
            art = cls(
                name=d["name"],
                source_workload_hash=d["source_workload_hash"],
                num_nodes=d["num_nodes"],
                regions=tuple(MemoryRegion.from_dict(r)
                              for r in d["regions"]),
                accesses=tuple(MemoryAccess.from_dict(a)
                               for a in d["accesses"]),
                mapping_policy=AddressMappingPolicy.from_dict(
                    d["mapping_policy"]),
                assumptions=tuple(d.get("assumptions", ())),
                schema_version=int(d.get("schema_version",
                                         SCHEMA_VERSION)),
                region_table_hash=d["region_table_hash"],
                access_stream_hash=d["access_stream_hash"],
                artifact_hash=d["artifact_hash"],
            )
        except (KeyError, ValueError, TypeError) as e:
            raise MemoryArtifactError(
                f"malformed MemoryArtifact: {e}") from e
        if art.schema_version != SCHEMA_VERSION:
            raise MemoryArtifactError(
                f"schema_version {art.schema_version} unsupported "
                f"(expected {SCHEMA_VERSION})")
        if _sha256_of({"regions": art._canon_regions()}) != \
                art.region_table_hash:
            raise MemoryArtifactError(
                "region_table_hash mismatch — regions were tampered with "
                "or corrupted")
        if _sha256_of({"accesses": art._canon_accesses()}) != \
                art.access_stream_hash:
            raise MemoryArtifactError(
                "access_stream_hash mismatch — the access stream was "
                "tampered with or corrupted")
        if _sha256_of(art._identity_dict()) != art.artifact_hash:
            raise MemoryArtifactError(
                "artifact_hash mismatch — the artifact was tampered with")
        return art

    # -- aggregate facts used by conservation and manifests --------------

    def region_bytes_total(self) -> int:
        """Total placed bytes across all regions."""
        return sum(r.size_bytes for r in self.regions)

    def access_bytes_total(self, kind: str | None = None) -> int:
        """Total access bytes, optionally restricted to READ/WRITE."""
        if kind is not None and kind not in ACCESS_KINDS:
            raise MemoryArtifactError(
                f"unknown access kind {kind!r}")
        return sum(a.size_bytes for a in self.accesses
                   if kind is None or a.kind == kind)


def build_artifact(*, name: str, source_workload_hash: str,
                   num_nodes: int, regions: list[MemoryRegion],
                   accesses: list[MemoryAccess],
                   mapping_policy: AddressMappingPolicy,
                   assumptions: tuple[str, ...] = ()) -> MemoryArtifact:
    """Sanctioned artifact constructor (validates eagerly, hashes)."""
    return MemoryArtifact(
        name=name, source_workload_hash=source_workload_hash,
        num_nodes=num_nodes, regions=tuple(regions),
        accesses=tuple(accesses), mapping_policy=mapping_policy,
        assumptions=tuple(assumptions))
