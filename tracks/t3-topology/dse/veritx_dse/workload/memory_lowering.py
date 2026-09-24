"""memory_lowering.py — CanonicalWorkload → MemoryArtifact resolver (Phase 14b).

Resolves per-op memory demand (COMPUTE input/weight/output bytes + locations)
against an explicit single-HBM-pool design into placed regions and an ordered
semantic access stream. Returns the artifact plus a conservation report; the
artifact itself carries everything Phase 15 needs.

Deliberate v1 boundaries (each documented where enforced):

* Op-scoped regions: one region per (op, operand). The workload carries no
  tensor identity across ops, so cross-op persistence (one weights region
  shared by many layers) would be invented semantics. Recorded as an
  assumption, not modeled.
* Fixed operand mapping: input→ACTIVATION, weight→WEIGHT, output→OUTPUT.
  No inference (a KV input is still ACTIVATION — the source does not
  distinguish it, so neither do we).
* Strict locations: only LOCAL resolves (to the design's HBM pool).
  REMOTE/CXL/STORAGE refuse as UnsupportedSemantic — "eh, use HBM" would
  silently reroute off-package traffic through the evaluated memory.
* Single-HBM designs only: multi-device placement needs an explicit
  sharding policy (future). Refuse, don't spread.
* Execution attribution is explicit: COMPUTE ops carry no placement, so
  the caller supplies per-op issue nodes (or one node for all, recorded
  as an assumption). Absent and ambiguous → refuse.
* Order, not timing: accesses chain positionally (workload op order is
  execution order — the ET lowering precedent); each op reads then
  writes, the write depending on the op's reads. No ready cycles invented.
* Zero/None operand bytes emit nothing (no empty regions, no zero accesses
  — both refuse at the schema, so the resolver skips them).
* Comm ops and structural markers carry no memory operands → ignored.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.memory import (
    AddressMappingPolicy,
    MemoryAccess,
    MemoryArtifact,
    MemoryPlacement,
    allocate_regions,
    build_access,
    build_artifact,
)
from veritx_dse.workload.canonical import WorkloadArtifact
from veritx_dse.workload.lowering import LoweringError, UnsupportedSemantic

MEMORY_RESOLVER_VERSION = 1
RESOLVER_ID = f"veritx_dse.workload.memory_lowering/{MEMORY_RESOLVER_VERSION}"

DEFAULT_POLICY = AddressMappingPolicy(
    name="contiguous_aligned_v1", version=1, alignment_bytes=64,
    parameters={})

# Fixed operand→object mapping (no inference; documented above).
_OPERANDS: tuple[tuple[str, str, str, str], ...] = (
    ("input_bytes", "input_loc", "input", "ACTIVATION"),
    ("weight_bytes", "weight_loc", "weight", "WEIGHT"),
    ("output_bytes", "output_loc", "output", "OUTPUT"),
)


@dataclass(frozen=True)
class MemorySystemDesign:
    """The resolved-against memory design (v1: one HBM pool).

    hbm_devices: device ids exposing HBM. Exactly one in v1 — placement
                 below device granularity (stack/bank/row) belongs to the
                 Phase-15 lowerer, and spreading tensors across pools
                 without a sharding policy would invent placement.
    """
    hbm_devices: tuple[int, ...] = (0,)

    def __post_init__(self) -> None:
        devs = tuple(self.hbm_devices)
        object.__setattr__(self, "hbm_devices", devs)
        if not devs:
            raise LoweringError(
                "MemorySystemDesign needs at least one HBM device — "
                "memory demand with nowhere to live is not resolvable")
        for d in devs:
            if not isinstance(d, int) or isinstance(d, bool) or d < 0:
                raise LoweringError(
                    f"HBM device ids must be non-negative ints, got {d!r}")
        if len(set(devs)) != len(devs):
            raise LoweringError(
                f"duplicate HBM device ids: {sorted(devs)}")
        if len(devs) > 1:
            raise UnsupportedSemantic(
                f"multi-HBM design {sorted(devs)} needs an explicit "
                "tensor-sharding policy (which pool holds which tensor). "
                "v1 resolves single-pool designs only — spreading demand "
                "across pools without that policy would invent placement.")

    def placement_for_local(self) -> MemoryPlacement:
        """Where a LOCAL operand lives: the pool. (Only LOCAL resolves.)"""
        return MemoryPlacement(tier="HBM", device=self.hbm_devices[0],
                               stack=None)


@dataclass(frozen=True)
class ResolvedMemory:
    """Resolver output: the artifact plus its conservation audit."""
    artifact: MemoryArtifact
    workload_operand_bytes: int
    region_bytes: int
    read_bytes: int
    write_bytes: int

    def conserved(self) -> bool:
        return self.workload_operand_bytes == self.region_bytes == (
            self.read_bytes + self.write_bytes)


def _resolve_location(op_id: str, operand: str, loc: str,
                      design: MemorySystemDesign) -> MemoryPlacement:
    """Strict canonical-location → placement (only LOCAL resolves)."""
    if loc == "LOCAL" or loc.startswith("LOCAL:"):
        # LOCAL:<dev> suffix (canonical grammar allows it): the owning
        # device must BE the pool — a LOCAL claim on another device is a
        # remote access mislabeled, not local memory.
        if ":" in loc:
            tail = loc.split(":", 1)[1].split(".")[0]
            if not tail.isdigit() or int(tail) != design.hbm_devices[0]:
                raise UnsupportedSemantic(
                    f"op {op_id!r} operand {operand!r} location {loc!r}: "
                    "LOCAL device is not the HBM pool — cross-device "
                    "local claims need an explicit placement policy")
        return design.placement_for_local()
    base = loc.split(":", 1)[0]
    if base == "REMOTE":
        raise UnsupportedSemantic(
            f"op {op_id!r} operand {operand!r} location {loc!r}: REMOTE "
            "implies a fabric traversal to another device's memory — a "
            "different system path, not pool HBM. Refused (never "
            "silently remapped).")
    if base == "CXL":
        raise UnsupportedSemantic(
            f"op {op_id!r} operand {operand!r} location {loc!r}: CXL-"
            "attached memory is not the HBM pool. Refused.")
    if base == "STORAGE":
        raise UnsupportedSemantic(
            f"op {op_id!r} operand {operand!r} location {loc!r}: off-"
            "package storage is never HBM. Refused.")
    raise UnsupportedSemantic(
        f"op {op_id!r} operand {operand!r} location {loc!r}: "
        "unresolvable against the v1 memory design.")


def _issue_nodes(art: WorkloadArtifact,
                 issue_node: int | dict[str, int] | None
                 ) -> tuple[dict[str, int], tuple[str, ...]]:
    """Per-COMPUTE-op execution attribution + the assumption it records."""
    compute_ids = [op.op_id for op in art.ops if op.kind == "COMPUTE"]
    return _issue_nodes_for(compute_ids, art.num_participants, issue_node)


def _issue_nodes_for(compute_ids: list[str], num_participants: int,
                     issue_node: int | dict[str, int] | None
                     ) -> tuple[dict[str, int], tuple[str, ...]]:
    """Attribution core over explicit ids + namespace (one implementation)."""
    if issue_node is None:
        if num_participants == 1:
            return ({op_id: 0 for op_id in compute_ids}, ())
        raise LoweringError(
            f"workload has {num_participants} participants and COMPUTE "
            "ops carry no placement: pass issue_node (int for all ops, or "
            "an explicit {op_id: node} map). Execution attribution must "
            "not default silently.")
    if isinstance(issue_node, int):
        if isinstance(issue_node, bool) or \
                not (0 <= issue_node < num_participants):
            raise LoweringError(
                f"issue_node {issue_node!r} out of range "
                f"[0, {num_participants})")
        return ({op_id: issue_node for op_id in compute_ids},
                (f"issue-node-mapping: all COMPUTE memory accesses "
                 f"attributed to node {issue_node}",))
    mapping = dict(issue_node)
    missing = [i for i in compute_ids if i not in mapping]
    if missing:
        raise LoweringError(
            f"issue_node map misses COMPUTE op(s) {missing} — partial "
            "execution attribution refuses (typo guard)")
    extra = [i for i in mapping if i not in compute_ids]
    if extra:
        raise LoweringError(
            f"issue_node map names unknown op(s) {extra} — typo guard")
    for op_id, node in mapping.items():
        if not isinstance(node, int) or isinstance(node, bool) or \
                not (0 <= node < num_participants):
            raise LoweringError(
                f"issue_node[{op_id!r}] = {node!r} out of range "
                f"[0, {num_participants})")
    return (mapping,
            ("issue-node-mapping: explicit per-op execution attribution",))


def resolve_memory(art: WorkloadArtifact, design: MemorySystemDesign, *,
                   policy: AddressMappingPolicy = DEFAULT_POLICY,
                   issue_node: int | dict[str, int] | None = None,
                   name: str | None = None) -> ResolvedMemory:
    """Lower a CanonicalWorkload to a MemoryArtifact (Phase 14b).

    Raises UnsupportedSemantic for unresolvable locations/multi-HBM (never
    partial artifacts — refuse before building anything) and LoweringError
    for ambiguous attribution or empty memory demand.
    """
    views = [{"op_id": op.op_id,
              "input_bytes": op.input_bytes, "input_loc": op.input_loc,
              "weight_bytes": op.weight_bytes, "weight_loc": op.weight_loc,
              "output_bytes": op.output_bytes, "output_loc": op.output_loc}
             for op in art.ops if op.kind == "COMPUTE"]
    nodes, issue_assumption = _issue_nodes(art, issue_node)
    return _resolve_views(
        views, design, policy=policy, nodes=nodes,
        issue_assumption=issue_assumption,
        source_hash=art.artifact_hash, num_nodes=art.num_participants,
        name=name or f"mem-{art.workload_id}")


def resolve_memory_graph(graph: Any, design: MemorySystemDesign, *,
                         policy: AddressMappingPolicy = DEFAULT_POLICY,
                         issue_node: int | dict[str, int] | None = None,
                         name: str | None = None) -> ResolvedMemory:
    """Lower a canonical WorkloadGraph to a MemoryArtifact (M3).

    The ONLY runtime memory entry point going forward: COMPUTE operand
    bytes/locations come from the graph's closed COMPUTE detail, in the
    graph's total order (positional memory stream needs it — an
    unordered DAG refuses rather than invents an order). Comm ops and
    structural markers carry no memory operands and are ignored, exactly
    as in the artifact path. Allocation, access chaining and
    conservation are the shared core below — one implementation.
    """
    from veritx_dse.core.artifact import thaw
    from veritx_dse.workload.graph import KIND_COMPUTE
    ordered = graph.require_total_order()
    views = []
    for op in ordered:
        if op.kind != KIND_COMPUTE:
            continue
        d = thaw(op.detail)
        views.append({"op_id": op.operation_id,
                      "input_bytes": d.get("input_bytes"),
                      "input_loc": d.get("input_loc"),
                      "weight_bytes": d.get("weight_bytes"),
                      "weight_loc": d.get("weight_loc"),
                      "output_bytes": d.get("output_bytes"),
                      "output_loc": d.get("output_loc")})
    compute_ids = [v["op_id"] for v in views]
    nodes, issue_assumption = _issue_nodes_for(
        compute_ids, graph.participant_count, issue_node)
    return _resolve_views(
        views, design, policy=policy, nodes=nodes,
        issue_assumption=issue_assumption,
        source_hash=graph.workload_id(),
        num_nodes=graph.participant_count,
        name=name or f"mem-{graph.workload_id()}")


def _resolve_views(views: list[dict[str, Any]], design: MemorySystemDesign,
                   *, policy: AddressMappingPolicy,
                   nodes: dict[str, int],
                   issue_assumption: tuple[str, ...],
                   source_hash: str, num_nodes: int,
                   name: str) -> ResolvedMemory:
    """Shared resolver core over normalized COMPUTE operand views."""
    specs: list[dict[str, Any]] = []
    operand_bytes = 0
    for view in views:
        for bytes_f, loc_f, suffix, otype in _OPERANDS:
            nbytes = view[bytes_f]
            if not nbytes:
                continue  # None/0: no operand bytes declared → no region
            operand_bytes += nbytes
            placement = _resolve_location(view["op_id"], suffix,
                                          view[loc_f], design)
            specs.append({
                "region_id": f"{view['op_id']}.{suffix}",
                "object_type": otype, "size_bytes": nbytes,
                "placement": placement, "source_op_id": view["op_id"],
            })
    if not specs:
        raise LoweringError(
            "workload declares no COMPUTE memory-operand bytes — nothing "
            "to resolve (comm bytes are fabric traffic, not memory "
            "demand)")
    # Allocate per placement scope (separate physical memories must not
    # share one cursor — identical numeric addresses across scopes are
    # distinct locations, not collisions).
    by_scope: dict[tuple, list[dict[str, Any]]] = {}
    for s in specs:
        p = s["placement"]
        by_scope.setdefault((p.tier, p.device, p.stack), []).append(s)
    regions = []
    for scope in sorted(by_scope):
        regions.extend(allocate_regions(by_scope[scope], policy))
    by_id = {r.region_id: r for r in regions}
    # Access stream: workload order, reads before the op's write, the
    # write depending on the op's reads, each op chaining after the
    # previous op's last access (positional chaining — order, not timing).
    accesses = []
    prev_tail: str | None = None
    for view in views:
        op_acc: list[str] = []
        writes: list[str] = []
        for bytes_f, _loc_f, suffix, _otype in _OPERANDS:
            if not view[bytes_f]:
                continue
            reg = by_id[f"{view['op_id']}.{suffix}"]
            aid = f"acc.{reg.region_id}"
            kind = "WRITE" if suffix == "output" else "READ"
            deps: list[str] = []
            if prev_tail is not None and not op_acc:
                deps.append(prev_tail)
            if kind == "WRITE":
                deps.extend(op_acc)  # write after this op's reads
            accesses.append(build_access(
                aid, view["op_id"], reg.region_id, kind, 0,
                reg.size_bytes, nodes[view["op_id"]], tuple(deps)))
            op_acc.append(aid)
            if kind == "WRITE":
                writes.append(aid)
        if op_acc:
            prev_tail = writes[-1] if writes else op_acc[-1]
    artifact = build_artifact(
        name=name,
        source_workload_hash=source_hash,
        num_nodes=num_nodes,
        regions=regions, accesses=accesses, mapping_policy=policy,
        assumptions=(f"resolver:{RESOLVER_ID}",
                     "op-scoped regions: cross-op tensor persistence "
                     "(e.g. weights shared across layers) is NOT modeled "
                     "— one region per (op, operand) conserves bytes "
                     "without inventing tensor identity",
                     *issue_assumption))
    region_bytes = artifact.region_bytes_total()
    read_bytes = artifact.access_bytes_total("READ")
    write_bytes = artifact.access_bytes_total("WRITE")
    if region_bytes != operand_bytes or \
            read_bytes + write_bytes != operand_bytes:
        raise LoweringError(
            "resolver conservation failure: workload operands "
            f"{operand_bytes}B vs regions {region_bytes}B vs accesses "
            f"{read_bytes + write_bytes}B — refuse rather than emit a "
            "lossy artifact")
    return ResolvedMemory(artifact=artifact,
                          workload_operand_bytes=operand_bytes,
                          region_bytes=region_bytes, read_bytes=read_bytes,
                          write_bytes=write_bytes)


# ── Phase 15a: MemoryArtifact → Ramulator trace lowering ───────────────────
#
# Boundary (spike-proven): the ReadWriteTrace frontend consumes text lines
#   R|W ch,pc,sid,bg,bank,row,col
# i.e. BACKEND address vectors, not byte addresses, issuing one request per
# frontend tick. This lowering is a pure function of (artifact + explicit
# backend geometry): it never imports Ramulator, so it runs on any VeriTX
# interpreter (the bindings are interpreter-tagged). Geometry mismatch with
# the executing backend is a Phase-15b execution-time check against this
# manifest's backend_config_hash — not something lowering can see.

RAMULATOR_TRACE_LOWERER = (
    f"{RESOLVER_ID}/ramulator-trace/1")

# Bytes→addr_vec policy: sequential transactions fill column fastest, then
# bank, bankgroup, sid, pseudo-channel, channel, row slowest. Rationale:
# a sequential tensor stream stays row-local as long as possible (streaming
# behavior), spreading across banks/channels only as addresses grow — the
# locality-monotonic choice. Row slowest means crossing a row boundary is
# always visible as a deliberately large address step, never an accident
# of interleaving. Versioned: any order change is a new mapping version.
ADDR_VEC_ORDER = ("column", "bank", "bankgroup", "sid", "pseudochannel",
                  "channel", "row")
MAPPING_ALGORITHM = "sequential_bankstriped_v1"


def _sha256(payload: bytes) -> str:
    return "sha256:" + hashlib.sha256(payload).hexdigest()


@dataclass(frozen=True)
class RamulatorGeometry:
    """Explicit backend geometry the lowering maps into (v1: HBM-shaped).

    Level counts (>0 ints) in ReadWriteTrace addr_vec order plus the
    transaction size the backend serves per request. All caller-supplied:
    transcribing them here (instead of importing Ramulator) keeps the
    lowering pure and interpreter-independent; the manifest hashes them so
    15b execution can prove it ran the same geometry. Use
    hbm3_16gb_8hi_geometry() for the audited preset transcription.
    """
    dram_class: str
    org_preset: str
    timing_preset: str
    controller: str
    channels: int
    pseudo_channels: int
    sids: int
    bankgroups: int
    banks: int
    rows: int
    columns: int
    transaction_bytes: int

    def __post_init__(self) -> None:
        for name in ("dram_class", "org_preset", "timing_preset",
                     "controller"):
            if not isinstance(getattr(self, name), str) or \
                    not getattr(self, name):
                raise LoweringError(
                    f"geometry {name} must be a non-empty string")
        for name in ("channels", "pseudo_channels", "sids", "bankgroups",
                     "banks", "rows", "columns", "transaction_bytes"):
            v = getattr(self, name)
            if not isinstance(v, int) or isinstance(v, bool) or v < 1:
                raise LoweringError(
                    f"geometry {name} must be an int >= 1, got {v!r}")

    def level_counts(self) -> dict[str, int]:
        """ Counts keyed by ADDR_VEC_ORDER names (row slowest)."""
        return {"column": self.columns, "bank": self.banks,
                "bankgroup": self.bankgroups, "sid": self.sids,
                "pseudochannel": self.pseudo_channels,
                "channel": self.channels, "row": self.rows}

    def capacity_bytes(self) -> int:
        """Addressable bytes: product(counts) × transaction size."""
        n = 1
        for v in self.level_counts().values():
            n *= v
        return n * self.transaction_bytes

    def to_dict(self) -> dict[str, Any]:
        return {"dram_class": self.dram_class,
                "org_preset": self.org_preset,
                "timing_preset": self.timing_preset,
                "controller": self.controller,
                "levels": self.level_counts(),
                "transaction_bytes": self.transaction_bytes}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RamulatorGeometry":
        try:
            lv = d["levels"]
            return cls(
                dram_class=d["dram_class"], org_preset=d["org_preset"],
                timing_preset=d["timing_preset"],
                controller=d["controller"], channels=lv["channel"],
                pseudo_channels=lv["pseudochannel"], sids=lv["sid"],
                bankgroups=lv["bankgroup"], banks=lv["bank"],
                rows=lv["row"], columns=lv["column"],
                transaction_bytes=d["transaction_bytes"])
        except (KeyError, TypeError) as e:
            raise LoweringError(
                f"malformed RamulatorGeometry: {e}") from e


def hbm3_16gb_8hi_geometry(num_channels: int = 1,
                           transaction_bytes: int = 64) -> RamulatorGeometry:
    """Audited transcription of Ramulator's HBM3_16Gb_8hi preset.

    Level sizes transcribed from the vendored tree
    (third_party/ramulator2/python/ramulator/dram/hbm3.py,
    HBM3.org_presets["HBM3_16Gb_8hi"]; test_transcription_pin pins them):
    pseudochannel=2, sid=2, bankgroup=4, bank=4, row=16384, column=256.
    transaction_bytes=64 from dram_spec.h
    (internal_prefetch_size 8 × channel_width 64 / 8; HBM3.cpp sets
    internal_prefetch_size=8 and the preset carries no payload override).
    Channel COUNT is configuration (stacks × channels/stack), not preset —
    caller-supplied, defaulting to 1 for single-channel experiments.
    """
    return RamulatorGeometry(
        dram_class="HBM3", org_preset="HBM3_16Gb_8hi",
        timing_preset="HBM3_6400Mbps", controller="HBM34",
        channels=num_channels, pseudo_channels=2, sids=2, bankgroups=4,
        banks=4, rows=16384, columns=256,
        transaction_bytes=transaction_bytes)


def addr_vec_for_tx(tx_index: int, geometry: RamulatorGeometry,
                    ) -> tuple[int, ...]:
    """Flat transaction index → (ch,pc,sid,bg,bank,row,col) per
    MAPPING_ALGORITHM. Out-of-capacity indices refuse (Phase-16
    INFEASIBLE lives here later; v1 raises rather than wraps)."""
    counts = geometry.level_counts()
    vec: dict[str, int] = {}
    rem = tx_index
    for dim in ADDR_VEC_ORDER:
        vec[dim], rem = rem % counts[dim], rem // counts[dim]
    if rem:
        raise LoweringError(
            f"transaction {tx_index} exceeds backend capacity "
            f"({geometry.capacity_bytes()}B at "
            f"{geometry.transaction_bytes}B/tx) — logical addresses do "
            "not fit this geometry (refuse, never wrap)")
    return (vec["channel"], vec["pseudochannel"], vec["sid"],
            vec["bankgroup"], vec["bank"], vec["row"], vec["column"])


def expand_access(access: MemoryAccess, base_address: int,
                  geometry: RamulatorGeometry,
                  ) -> tuple[list[tuple[int, ...]], list[int], int, int]:
    """One semantic access → (backend request vectors, flat addresses,
    front_pad, back_pad).

    The backend serves whole transactions (req.size_bytes = tx, set by the
    frontend — a partial tail still occupies a full request). Padding is
    explicit: front_pad bytes before the access inside the first tx,
    back_pad after it inside the last tx. The flat byte address of each
    transaction (tx_index * transaction_bytes) rides beside its addr_vec:
    it is the equality key for controller write coalescing / read
    forwarding (the req.addr == -1 aliasing bug, fixed 2026-09-18 —
    without it, unrelated requests shared one coalescing key). Pure: no I/O.
    """
    tx = geometry.transaction_bytes
    start = base_address + access.offset_bytes
    end = start + access.size_bytes
    first, last = start // tx, (end - 1) // tx
    vecs: list[tuple[int, ...]] = []
    flats: list[int] = []
    for i in range(first, last + 1):
        vecs.append(addr_vec_for_tx(i, geometry))
        flats.append(i * tx)
    return vecs, flats, start - first * tx, (last + 1) * tx - end


@dataclass(frozen=True)
class MemoryLoweringManifest:
    """Every claim the Ramulator-trace lowering makes, in checkable form.

    Mirrors workload/lowering.py:LoweringManifest culture: semantic_losses
    is [] ONLY because the conservation asserts in lower_to_ramulator_trace
    ran (never claimed from completion), and coverage is total-or-refuse.
    """
    schema_version: int
    source_memory_artifact_hash: str
    access_stream_hash: str
    backend: str
    lowerer: str
    mapping_algorithm: str
    backend_config_hash: str
    geometry: dict
    transaction_bytes: int
    counts: dict
    bytes: dict
    coverage: dict
    transformations: list
    semantic_losses: list
    unsupported: list
    trace_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "source_memory_artifact_hash": self.source_memory_artifact_hash,
            "access_stream_hash": self.access_stream_hash,
            "backend": self.backend, "lowerer": self.lowerer,
            "mapping_algorithm": self.mapping_algorithm,
            "backend_config_hash": self.backend_config_hash,
            "geometry": self.geometry,
            "transaction_bytes": self.transaction_bytes,
            "counts": self.counts, "bytes": self.bytes,
            "coverage": self.coverage,
            "transformations": self.transformations,
            "semantic_losses": self.semantic_losses,
            "unsupported": self.unsupported,
            "trace_sha256": self.trace_sha256,
        }


def backend_config_payload(geometry: RamulatorGeometry, mapping: str,
                           ) -> bytes:
    """Canonical config payload whose sha256 is the manifest's
    backend_config_hash — ONE implementation; execute() recomputes it
    to verify the manifest's declared hash against the geometry that
    actually generates the driver (tamper-closed chain, 2026-09-18)."""
    return json.dumps({
        "geometry": geometry.to_dict(), "mapping": mapping,
        "transaction_bytes": geometry.transaction_bytes},
        sort_keys=True, separators=(",", ":")).encode()


def lower_to_ramulator_trace(artifact: MemoryArtifact,
                             geometry: RamulatorGeometry, *,
                             out_path: str | Path,
                             mapping: str = MAPPING_ALGORITHM,
                             ) -> MemoryLoweringManifest:
    """Expand an artifact's access stream to a ReadWriteTrace file + manifest.

    Stream order preserved (execution semantics). Conservation is asserted,
    not assumed: logical + padding == generated, per kind and in total;
    any violation refuses instead of emitting a lossy trace.
    """
    if mapping != MAPPING_ALGORITHM:
        raise LoweringError(
            f"addr_vec mapping {mapping!r} unsupported — implemented: "
            f"{MAPPING_ALGORITHM!r} (a new order is a new version, not a "
            "flag)")
    by_region = {r.region_id: r for r in artifact.regions}
    lines: list[str] = []
    n_tx = n_rd_tx = n_wr_tx = 0
    gen_rd = gen_wr = front_pad = back_pad = 0
    for access in artifact.accesses:
        region = by_region.get(access.region_id)
        if region is None:  # schema-validated, but refuse > KeyError
            raise LoweringError(
                f"access {access.access_id!r}: unknown region "
                f"{access.region_id!r}")
        vecs, flats, fp, bp = expand_access(access, region.base_address,
                                            geometry)
        op = "W" if access.kind == "WRITE" else "R"
        # VeriX extended trace form: <op> <flat_byte_addr> <addr_vec> —
        # the flat address is the controller's coalescing/forwarding key
        # (the lowerer KNOWS the logical byte address; never invent a
        # hash of the addr_vec for it).
        lines.extend(f"{op} {flat} {','.join(map(str, v))}"
                     for v, flat in zip(vecs, flats))
        n_tx += len(vecs)
        front_pad += fp
        back_pad += bp
        if access.kind == "WRITE":
            n_wr_tx += len(vecs)
            gen_wr += len(vecs) * geometry.transaction_bytes
        else:
            n_rd_tx += len(vecs)
            gen_rd += len(vecs) * geometry.transaction_bytes
    log_rd = artifact.access_bytes_total("READ")
    log_wr = artifact.access_bytes_total("WRITE")
    logical = log_rd + log_wr
    generated = gen_rd + gen_wr
    padding = front_pad + back_pad
    if generated != logical + padding:
        raise LoweringError(
            "trace-lowering conservation failure: logical "
            f"{logical}B + padding {padding}B != generated {generated}B")
    if n_tx != n_rd_tx + n_wr_tx or \
            gen_rd + gen_wr != (n_rd_tx + n_wr_tx) * \
            geometry.transaction_bytes:
        raise LoweringError(
            "trace-lowering kind-split failure: per-kind transaction "
            "accounting does not reconcile")
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    trace_hash = _sha256(out.read_bytes())
    backend_config_hash = _sha256(backend_config_payload(geometry, mapping))
    return MemoryLoweringManifest(
        schema_version=1,
        source_memory_artifact_hash=artifact.artifact_hash,
        access_stream_hash=artifact.access_stream_hash,
        backend="ramulator", lowerer=RAMULATOR_TRACE_LOWERER,
        mapping_algorithm=mapping,
        backend_config_hash=backend_config_hash,
        geometry=geometry.to_dict(),
        transaction_bytes=geometry.transaction_bytes,
        counts={"semantic_accesses": len(artifact.accesses),
                "transactions": n_tx, "read_transactions": n_rd_tx,
                "write_transactions": n_wr_tx},
        bytes={"logical_read_bytes": log_rd,
               "logical_write_bytes": log_wr,
               "generated_read_bytes": gen_rd,
               "generated_write_bytes": gen_wr,
               "front_padding_bytes": front_pad,
               "back_padding_bytes": back_pad},
        coverage={"lowered_accesses": len(artifact.accesses),
                  "total_accesses": len(artifact.accesses)},
        transformations=[
            "semantic access order → trace line order (positional, kept)",
            "logical byte range → ceil(size/tx) whole-tx requests "
            "(backend serves full transactions; tails become explicit "
            "back padding, unaligned heads explicit front padding)",
            "flat tx index → addr_vec via sequential_bankstriped_v1 "
            "(column, bank, bankgroup, sid, pseudochannel, channel, "
            "row — row slowest)",
            "flat tx byte address emitted per line (VeriX 3-token "
            "extended trace form) — req.addr correctness for controller "
            "coalescing/forwarding (2026-09-18)",
        ],
        semantic_losses=[],
        unsupported=[],
        trace_sha256=trace_hash,
    )
