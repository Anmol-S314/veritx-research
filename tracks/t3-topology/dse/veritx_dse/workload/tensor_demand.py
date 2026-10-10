"""V5-bound explicit demand generator. Authored order is not an issue schedule."""
from bisect import bisect_right
from dataclasses import dataclass, asdict

from veritx_dse.core.artifact import FrozenMap, content_id, canonical_bytes, thaw
from veritx_dse.core.errors import InvalidInput, EvidenceInvalid, UnsupportedSemantics
from veritx_dse.core.memory import byte_transaction_span
from veritx_dse.model.access_policy import AddressSpace
from veritx_dse.model.compile_request_v5 import CompileRequestV5
from veritx_dse.model.tensor_demand import TensorDemandWorkload, MAX_REQUESTS


@dataclass(frozen=True)
class DemandRequest:
    request_id: str
    access_id: str
    tensor_id: str
    shard_id: str
    block_index: int
    tensor_offset_bytes: int
    issuer: int
    target: int
    address_space: str
    kind: str
    transaction_address: int
    transaction_bytes: int
    payload_address: int
    payload_bytes: int
    front_padding_bytes: int
    back_padding_bytes: int
    deps: tuple[str, ...]
    cache_policy: str

    def to_dict(self):
        return {**asdict(self), "deps": list(self.deps)}


@dataclass(frozen=True)
class LoweredTensorDemand:
    design_hash: str
    system_hash: str
    workload_id: str
    requests: tuple[DemandRequest, ...]
    audit: FrozenMap

    def identity_dict(self):
        return {"type": "veritx/LoweredTensorDemand", "schema_version": 1,
                "design_hash": self.design_hash, "system_hash": self.system_hash,
                "workload_id": self.workload_id, "requests": [r.to_dict() for r in self.requests],
                "audit": thaw(self.audit),
                "scope": {"cache": "EXPLICIT_BYPASS_ONLY" if all(r.cache_policy == "BYPASS" for r in self.requests) else "OWNER_CACHE_POLICY_PRESERVED_NO_CACHE_EFFECTS", "memory_contents_modeled": False,
                          "timing_modeled": False, "elapsed_clock_units": None,
                          "ordering": "SERIALIZATION_ONLY_HONOR_ACCESS_COMPLETION_DEPS",
                          "padding": "ACCOUNTING_ONLY_NOT_ACCESSED_OR_AUTHORIZED"}}

    def artifact_id(self):
        return content_id("veritx/LoweredTensorDemand/v1", self.identity_dict())

    def to_dict(self):
        return {**self.identity_dict(), "artifact_id": self.artifact_id()}

    def revalidate(self, *, compilation, workload):
        if self != lower_tensor_demand(compilation, workload):
            raise EvidenceInvalid("tensor demand differs from parent-recomputed lowering")

    @classmethod
    def from_dict(cls, doc, *, compilation, workload):
        expected = lower_tensor_demand(compilation, workload)
        if canonical_bytes(doc) != canonical_bytes(expected.to_dict()):
            raise EvidenceInvalid("stored tensor demand differs from parent-recomputed lowering")
        return expected


def _decode_shard(decode, shard):
    # Compiled decode is GLOBAL IDENTITY only. LOCAL must not borrow it.
    if shard.address_space is not AddressSpace.GLOBAL:
        raise UnsupportedSemantics("LOCAL tensor placement has no compiled address decode")
    start, end = shard.base_address, shard.base_address + shard.size_bytes
    cursor = start
    for entry in sorted(decode.entries, key=lambda e: e.base):
        if entry.base + entry.size <= cursor:
            continue
        if entry.base >= end:
            break
        if entry.base > cursor:
            raise InvalidInput("tensor shard spans an unmapped address gap")
        if entry.target_endpoint_id != shard.target:
            raise InvalidInput("tensor shard decode target differs from declared owner endpoint")
        cursor = min(end, entry.base + entry.size)
        if cursor == end:
            return
    raise InvalidInput("tensor shard is not fully covered by compiled address decode")


def _access_fragments(tensor, access):
    """Stream exact logical block/shard intersections without request allocation."""
    shards = sorted(tensor.shards, key=lambda s: s.offset_bytes)
    shard_starts = [shard.offset_bytes for shard in shards]
    for block_index in range(access.count):
        block_start = access.offset_bytes + block_index * access.stride_bytes
        block_end = block_start + access.block_bytes
        # Tensor validation guarantees contiguous, ordered logical shards. Skip
        # all earlier shards with a binary search, then visit only intersections.
        index = max(0, bisect_right(shard_starts, block_start) - 1)
        for shard_index in range(index, len(shards)):
            shard = shards[shard_index]
            if shard.offset_bytes >= block_end:
                break
            lo = max(block_start, shard.offset_bytes)
            hi = min(block_end, shard.offset_bytes + shard.size_bytes)
            if lo < hi:
                yield block_index, shard, lo, hi


def lower_tensor_demand(compilation, workload: TensorDemandWorkload, *, allow_owner_cache=False) -> LoweredTensorDemand:
    """Generate <=65536 exact byte slices; validate all layout, even unused shards.

    A dependency names an access, whose completion means ALL its requests have
    returned. Requests are not injected here; no time/duration/cache hits exist.
    """
    from veritx_dse.application.fabric_compiler import Compilation
    if not isinstance(compilation, Compilation) or compilation.status != "COMPILED":
        raise InvalidInput("tensor demand requires successful Compilation")
    if not isinstance(workload, TensorDemandWorkload):
        raise InvalidInput("explicit TensorDemandWorkload is required")
    if not allow_owner_cache and any(a.cache_policy == "OWNER_CACHE" for a in workload.accesses):
        raise UnsupportedSemantics("OWNER_CACHE requires the coupled owner-cache reference executor")
    root = compilation.compiled_system
    root.revalidate()
    if not isinstance(root.request, CompileRequestV5):
        raise UnsupportedSemantics("tensor demand requires V5 parent")
    if workload.design_hash != root.request.design_hash() or workload.system_hash != root.system_hash():
        raise EvidenceInvalid("tensor demand does not bind to exact design/system parents")
    attachment, decode = root.fabric.attachment, root.fabric.address_decode
    decode.validate_against(root.request.base_v4.address_map, attachment)
    endpoints = {e.endpoint_id: e for e in attachment.endpoints}
    tensors = {t.tensor_id: t for t in workload.tensors}
    for tensor in workload.tensors:
        for shard in tensor.shards:
            if shard.target not in endpoints:
                raise InvalidInput("tensor owner target endpoint is not attached")
            if shard.base_address + shard.size_bytes > 1 << endpoints[shard.target].interface.address_width_bits:
                raise InvalidInput("tensor shard exceeds target address width")
            _decode_shard(decode, shard)
    for access in workload.accesses:
        if access.issuer not in endpoints:
            raise InvalidInput("tensor access issuer endpoint is not attached")
    # Refuse total expansion before materializing ANY request objects.
    request_count = 0
    for access in workload.accesses:
        for _, shard, lo, hi in _access_fragments(tensors[access.tensor_id], access):
            start = shard.base_address + lo - shard.offset_bytes
            first, last, _, _ = byte_transaction_span(start, hi - lo, shard.transaction_bytes)
            request_count += last - first + 1
            if request_count > MAX_REQUESTS:
                raise UnsupportedSemantics("tensor demand exceeds generated request bound")
    requests, access_audits = [], []
    for access in workload.accesses:
        tensor = tensors[access.tensor_id]
        fragment_bytes = fragment_count = 0
        first_request = len(requests)
        for block_index, shard, lo, hi in _access_fragments(tensor, access):
            fragment_count += 1
            fragment_bytes += hi - lo
            start = shard.base_address + lo - shard.offset_bytes
            end = start + hi - lo
            first, last, _, _ = byte_transaction_span(start, hi - lo, shard.transaction_bytes)
            for tx_index in range(first, last + 1):
                tx_address = tx_index * shard.transaction_bytes
                payload_start = max(start, tx_address)
                payload_end = min(end, tx_address + shard.transaction_bytes)
                request_id = content_id("veritx/TensorDemandRequest/v1",
                                        [access.access_id, block_index, shard.shard_id, tx_address])
                requests.append(DemandRequest(
                    request_id, access.access_id, tensor.tensor_id, shard.shard_id,
                    block_index, lo + payload_start - start, access.issuer, shard.target,
                    shard.address_space.value, access.kind.value, tx_address, shard.transaction_bytes,
                    payload_start, payload_end - payload_start, payload_start - tx_address,
                    tx_address + shard.transaction_bytes - payload_end, access.deps, access.cache_policy))
        payload_bytes = sum(r.payload_bytes for r in requests[first_request:])
        declared = access.count * access.block_bytes
        if declared != fragment_bytes or declared != payload_bytes:
            raise EvidenceInvalid("tensor payload conservation failure")
        access_audits.append({"access_id": access.access_id, "declared_payload_bytes": declared,
                             "shard_fragment_bytes": fragment_bytes, "fragment_count": fragment_count,
                             "request_payload_bytes": payload_bytes,
                             "request_count": len(requests) - first_request})
    payload = sum(r.payload_bytes for r in requests)
    tx_bytes = sum(r.transaction_bytes for r in requests)
    padding = sum(r.front_padding_bytes + r.back_padding_bytes for r in requests)
    if (tx_bytes != payload + padding or len(requests) != request_count
            or len({r.request_id for r in requests}) != len(requests)):
        raise EvidenceInvalid("tensor transaction conservation/identity failure")
    return LoweredTensorDemand(workload.design_hash, workload.system_hash, workload.workload_id(),
        tuple(requests), FrozenMap({"storage_bytes": sum(t.size_bytes for t in workload.tensors),
            "declared_payload_bytes": sum(a.count * a.block_bytes for a in workload.accesses),
            "request_payload_bytes": payload, "transaction_bytes": tx_bytes, "padding_bytes": padding,
            "read_bytes": sum(r.payload_bytes for r in requests if r.kind == "READ"),
            "write_bytes": sum(r.payload_bytes for r in requests if r.kind == "WRITE"),
            "request_count": len(requests), "accesses": access_audits}))
