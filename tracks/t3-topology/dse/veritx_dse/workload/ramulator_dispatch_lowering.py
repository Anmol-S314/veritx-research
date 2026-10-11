"""Pool-aware Ramulator manifest and address lowering."""
from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from veritx_dse.core.memory import MemoryArtifact, byte_transaction_span
from veritx_dse.workload.lowering import LoweringError
from veritx_dse.workload.memory_lowering import (
    ADDR_VEC_ORDERS, CHANNEL_INTERLEAVED, HBM3_INTERNAL_PREFETCH_BITS,
    MAPPING_ALGORITHM, NATIVE_ADDR_BIT_ORDER, RAMULATOR_BACKPRESSURE_POLICY,
    RAMULATOR_DISPATCHER_V1, RAMULATOR_DISPATCHER_VERSION,
    RAMULATOR_DISPATCH_LOWERER, RAMULATOR_DISPATCH_MAX_OUTSTANDING,
    RAMULATOR_READ_BUFFER_SIZE, RAMULATOR_WRITE_BUFFER_SIZE,
    MemoryTraceCost, RamulatorGeometry, _native_controller_count,
    _sha256, access_tx_range, addr_vec_for_tx,
)


def native_level_bits(geometry: RamulatorGeometry) -> dict[str, int]:
    """Address bits Ramulator's RoBaRaCoCh spends per mapped level.

    Mirrors AddrMapperBase::init(), including its power-of-two requirement:
    a non-power-of-two level count refuses here exactly as it refuses
    natively, rather than silently deriving the wrong bit count.
    """
    counts = geometry.level_counts()
    bits: dict[str, int] = {}
    for dim in NATIVE_ADDR_BIT_ORDER:
        count = counts[dim]
        if count < 1 or count & (count - 1):
            raise LoweringError(
                f"native HBM3 level {dim!r} count {count} is not a positive "
                "power of two — Ramulator's RoBaRaCoCh refuses it too")
        bits[dim] = count.bit_length() - 1
    if counts["column"] % (1 << HBM3_INTERNAL_PREFETCH_BITS):
        raise LoweringError(
            f"native HBM3 column count {counts['column']} is not a multiple "
            "of the 8x internal prefetch")
    bits["column"] -= HBM3_INTERNAL_PREFETCH_BITS
    if bits["column"] < 1:
        raise LoweringError(
            "native HBM3 column count collapses to zero address bits")
    return bits


def estimate_dispatch_cost(artifact: MemoryArtifact,
                           geometry: RamulatorGeometry, *,
                           device_ids: tuple[int, ...]
                           ) -> MemoryTraceCost:
    """Transaction count the multi-pool dispatcher would issue.

    Same span authority and same shape as ``estimate_trace_cost``, but
    every access must resolve onto a declared pool; capacity is the sum
    over the declared pools, since each owns a disjoint channel group.
    """
    declared = tuple(sorted(device_ids))
    if not declared:
        raise LoweringError("dispatch cost needs at least one declared pool")
    by_region = {r.region_id: r for r in artifact.regions}
    n_tx = n_rd = n_wr = 0
    for access in artifact.accesses:
        region = by_region.get(access.region_id)
        if region is None:
            raise LoweringError(
                f"access {access.access_id!r}: unknown region "
                f"{access.region_id!r}")
        if region.placement.device not in declared:
            raise LoweringError(
                f"region {region.region_id!r} selects undeclared device "
                f"{region.placement.device}; declared: {list(declared)}")
        first, last, _fp, _bp = access_tx_range(access, region.base_address,
                                                geometry)
        span = last - first + 1
        n_tx += span
        if access.kind == "WRITE":
            n_wr += span
        else:
            n_rd += span
    return MemoryTraceCost(
        transactions=n_tx, read_transactions=n_rd,
        write_transactions=n_wr,
        generated_bytes=n_tx * geometry.transaction_bytes,
        capacity_bytes=geometry.capacity_bytes() * len(declared))


def ramulator_dispatch_config_payload(
        geometry: RamulatorGeometry, device_ids: tuple[int, ...],
        native_transaction_bytes: int, mapping: str, *,
        dispatcher_version: str = RAMULATOR_DISPATCHER_VERSION,
        backpressure_retry_policy: str | None = RAMULATOR_BACKPRESSURE_POLICY,
        ) -> bytes:
    """Versioned native controller-group and event-engine identity."""
    devices = tuple(sorted(device_ids))
    if not devices or len(set(devices)) != len(devices):
        raise LoweringError("dispatch device IDs must be nonempty and unique")
    c = geometry.channels
    active_channels = len(devices) * c
    if dispatcher_version not in (RAMULATOR_DISPATCHER_V1,
                                   RAMULATOR_DISPATCHER_VERSION):
        raise LoweringError(f"unsupported dispatch engine {dispatcher_version!r}")
    if dispatcher_version == RAMULATOR_DISPATCHER_V1:
        if backpressure_retry_policy is not None:
            raise LoweringError("V1 dispatch config cannot declare a retry policy")
    elif backpressure_retry_policy != RAMULATOR_BACKPRESSURE_POLICY:
        raise LoweringError("V2 dispatch config needs its retry policy")
    payload = {
        "schema_version": 1,
        "dispatcher": dispatcher_version,
        "dependency_policy": "access_dependencies_callback_complete",
        "pool_profile_contract": "one logical HBM pool per declared HBM_CONTROLLER; profile channels per pool",
        "native_channel_mapper": "Gem5PortInterleave",
        "native_addr_mapper": "RoBaRaCoCh",
        "channel_address_encoding": "controller_local_address_expanded_by_total_channel_bits_v1",
        "native_transaction_bytes": native_transaction_bytes,
        "dispatcher_max_outstanding": RAMULATOR_DISPATCH_MAX_OUTSTANDING,
        "native_read_buffer_size": RAMULATOR_READ_BUFFER_SIZE,
        "native_write_buffer_size": RAMULATOR_WRITE_BUFFER_SIZE,
        "mapping_algorithm": mapping,
        "geometry_per_pool": replace(
            geometry, transaction_bytes=native_transaction_bytes).to_dict(),
        "device_channel_groups": {
            str(device): {"first_channel": ordinal * c,
                          "channel_count": c}
            for ordinal, device in enumerate(devices)},
    }
    if backpressure_retry_policy is not None:
        payload["backpressure_retry_policy"] = backpressure_retry_policy
    native_channels = _native_controller_count(active_channels)
    if dispatcher_version == RAMULATOR_DISPATCHER_V1 and \
            native_channels != active_channels:
        raise LoweringError(
            "ordered_callback_dispatch_v1 requires a power-of-two active "
            f"controller count, got {active_channels}")
    if native_channels != active_channels:
        payload["controller_padding"] = {
            "policy": "inactive_power_of_two_tail_v1",
            "active_channels": active_channels,
            "native_controller_count": native_channels,
        }
    return json.dumps(payload, sort_keys=True,
                      separators=(",", ":")).encode()


def lower_to_ramulator_dispatch(
        artifact: MemoryArtifact, geometry: RamulatorGeometry, *,
        device_ids: tuple[int, ...], native_transaction_bytes: int,
        backend_config_hash: str,
        mapping: str = MAPPING_ALGORITHM,
        dispatcher_version: str = RAMULATOR_DISPATCHER_VERSION,
        backpressure_retry_policy: str | None = RAMULATOR_BACKPRESSURE_POLICY,
        ) -> dict[str, Any]:
    """Build authenticated native requests with per-pool local addresses.

    Native Ramulator channels are assigned by sorted declared device ID;
    device identity remains separate from the channel ordinal. Each semantic
    access stays one dependency unit, expanded into backend-sized requests.
    """
    devices = tuple(sorted(device_ids))
    if not devices or len(set(devices)) != len(devices):
        raise LoweringError("dispatch device IDs must be nonempty and unique")
    if dispatcher_version == RAMULATOR_DISPATCHER_V1:
        if backpressure_retry_policy is not None:
            raise LoweringError("V1 dispatch cannot declare a retry policy")
    elif dispatcher_version != RAMULATOR_DISPATCHER_VERSION or \
            backpressure_retry_policy != RAMULATOR_BACKPRESSURE_POLICY:
        raise LoweringError("unsupported dispatch engine/retry policy")
    if native_transaction_bytes < 1:
        raise LoweringError("native transaction size must be positive")
    if mapping not in ADDR_VEC_ORDERS:
        raise LoweringError(f"unsupported dispatch mapping {mapping!r}")
    if geometry.channels > 1 and mapping != CHANNEL_INTERLEAVED:
        raise LoweringError(
            "native multi-channel dispatch requires channel_interleaved_v1")
    geo = replace(geometry, transaction_bytes=native_transaction_bytes)
    channels_per_pool = geo.channels
    total_channels = len(devices) * channels_per_pool
    native_controller_count = _native_controller_count(total_channels)
    if dispatcher_version == RAMULATOR_DISPATCHER_V1 and \
            native_controller_count != total_channels:
        raise LoweringError(
            "ordered_callback_dispatch_v1 requires a power-of-two active "
            f"controller count, got {total_channels}")
    channel_bit_width = native_controller_count.bit_length() - 1
    tx_shift = native_transaction_bytes.bit_length() - 1
    if native_transaction_bytes & (native_transaction_bytes - 1):
        raise LoweringError("native transaction size must be a power of two")
    groups = {device: {"first_channel": ordinal * channels_per_pool,
                       "channel_count": channels_per_pool}
              for ordinal, device in enumerate(devices)}
    level_bits = native_level_bits(geo)
    by_region = {r.region_id: r for r in artifact.regions}
    access_by_id = {a.access_id: a for a in artifact.accesses}
    records: list[dict[str, Any]] = []
    per_device: dict[int, dict[str, Any]] = {
        d: {"read_transactions": 0, "write_transactions": 0,
            "logical_read_bytes": 0, "logical_write_bytes": 0,
            "generated_bytes": 0, "padding_bytes": 0,
            "front_padding_bytes": 0, "back_padding_bytes": 0,
            "access_ids": []} for d in devices}
    for access in artifact.accesses:
        region = by_region.get(access.region_id)
        if region is None:
            raise LoweringError(
                f"access {access.access_id!r}: unknown region "
                f"{access.region_id!r}")
        device = region.placement.device
        if device not in groups:
            raise LoweringError(
                f"region {region.region_id!r} selects undeclared device "
                f"{device}; declared: {list(devices)}")
        if any(dep not in access_by_id for dep in access.dependencies):
            raise LoweringError(
                f"access {access.access_id!r} has unknown dependency")
        start = region.base_address + access.offset_bytes
        first, last, front_pad, back_pad = byte_transaction_span(
            start, access.size_bytes, native_transaction_bytes)
        device_stats = per_device[device]
        device_stats["access_ids"].append(access.access_id)
        device_stats["front_padding_bytes"] += front_pad
        device_stats["back_padding_bytes"] += back_pad
        kind = "WRITE" if access.kind == "WRITE" else "READ"
        logical_key = "logical_write_bytes" if kind == "WRITE" else \
            "logical_read_bytes"
        tx_key = "write_transactions" if kind == "WRITE" else \
            "read_transactions"
        device_stats[logical_key] += access.size_bytes
        for tx_index in range(first, last + 1):
            local_address = tx_index * native_transaction_bytes
            local_vector = addr_vec_for_tx(tx_index, geo, mapping=mapping)
            local_channel = local_vector[0]
            native_channel = groups[device]["first_channel"] + local_channel
            local_channel_tx = tx_index // channels_per_pool
            controller_local_address = (
                local_channel_tx * native_transaction_bytes)
            low_mask = (1 << tx_shift) - 1
            native_address = (
                (controller_local_address >> tx_shift) <<
                (tx_shift + channel_bit_width)) | \
                (controller_local_address & low_mask)
            fields: dict[str, int] = {}
            rem = controller_local_address >> tx_shift
            for dim in NATIVE_ADDR_BIT_ORDER:
                fields[dim] = rem & ((1 << level_bits[dim]) - 1)
                rem >>= level_bits[dim]
            if rem:
                raise LoweringError(
                    f"native address {controller_local_address} exceeds "
                    "the selected HBM3 geometry")
            native_vec = [native_channel, fields["pseudochannel"],
                          fields["sid"], fields["bankgroup"], fields["bank"],
                          fields["row"], fields["column"]]
            tx_start = local_address
            covered = max(0, min(start + access.size_bytes,
                                 tx_start + native_transaction_bytes) -
                          max(start, tx_start))
            records.append({
                "transaction_id": f"{access.access_id}:{tx_index-first}",
                "access_id": access.access_id,
                "source_op_id": access.source_op_id,
                "dependencies": list(access.dependencies),
                "device_id": device, "operation": kind,
                "source_address": max(start, tx_start),
                "source_access_start_address": start,
                "local_pool_address": local_address,
                "controller_local_address": controller_local_address,
                "native_address": native_address,
                "transaction_index": tx_index,
                "native_channel": native_channel,
                "native_addr_vec": native_vec,
                "pool_local_addr_vec": list(local_vector),
                "native_transaction_bytes": native_transaction_bytes,
                "logical_bytes": covered,
                "padding_bytes": native_transaction_bytes - covered,
            })
            device_stats[tx_key] += 1
            device_stats["generated_bytes"] += native_transaction_bytes
            device_stats["padding_bytes"] += native_transaction_bytes - covered
    total_logical = artifact.access_bytes_total("READ") + \
        artifact.access_bytes_total("WRITE")
    total_generated = sum(row["generated_bytes"] for row in per_device.values())
    total_padding = sum(row["padding_bytes"] for row in per_device.values())
    if total_generated != total_logical + total_padding:
        raise LoweringError(
            f"dispatch byte conservation failed: logical {total_logical} + "
            f"padding {total_padding} != generated {total_generated}")
    payload: dict[str, Any] = {
        "schema_version": 2,
        "lowerer": RAMULATOR_DISPATCH_LOWERER,
        "dispatcher": dispatcher_version,
        "device_group_assignment": "sorted_declared_device_id_order_v1",
        "dispatcher_max_outstanding": RAMULATOR_DISPATCH_MAX_OUTSTANDING,
        "native_queue_sizes": {
            "read": RAMULATOR_READ_BUFFER_SIZE,
            "write": RAMULATOR_WRITE_BUFFER_SIZE},
        "pool_profile_contract": "one logical HBM pool per declared HBM_CONTROLLER; selected profile channels per pool; not physical package equivalence",
        "native_channel_mapper": "Gem5PortInterleave",
        "native_addr_mapper": "RoBaRaCoCh",
        "dependency_policy": "all predecessor access transactions callback-complete",
        "mapping_algorithm": mapping,
        "ordering": "stable-round-robin-ready-accesses; independent ready accesses may overlap",
        "source_memory_artifact_hash": artifact.artifact_hash,
        "access_stream_hash": artifact.access_stream_hash,
        "backend_config_hash": backend_config_hash,
        "geometry_per_pool": geo.to_dict(),
        "device_channel_groups": {str(d): groups[d] for d in devices},
        "device_ledger": {str(d): per_device[d] for d in devices},
        "access_dependencies": {a.access_id: list(a.dependencies)
                                 for a in artifact.accesses},
        "counts": {
            "semantic_accesses": len(artifact.accesses),
            "transactions": len(records),
            "read_transactions": sum(r["operation"] == "READ"
                                      for r in records),
            "write_transactions": sum(r["operation"] == "WRITE"
                                       for r in records)},
        "bytes": {"logical_bytes": total_logical,
                  "generated_bytes": total_generated,
                  "padding_bytes": total_padding},
        "transactions": records,
    }
    if backpressure_retry_policy is not None:
        payload["backpressure_retry_policy"] = backpressure_retry_policy
    if native_controller_count != total_channels:
        payload["controller_padding"] = {
            "policy": "inactive_power_of_two_tail_v1",
            "active_channels": total_channels,
            "native_controller_count": native_controller_count,
            "inactive_channels": list(range(total_channels,
                                             native_controller_count)),
        }
    payload["dispatch_input_hash"] = _sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode())
    return payload
