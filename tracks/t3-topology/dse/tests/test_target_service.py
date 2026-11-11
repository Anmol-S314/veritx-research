"""Tests for the standalone deterministic target/memory service model."""
from __future__ import annotations

import ast
import dataclasses
import inspect

import pytest

from veritx_dse.core.errors import SemanticError
from veritx_dse.simulation import target_service as ts
from veritx_dse.simulation.target_service import (
    ROWS_PER_BANK,
    TargetService,
    TargetServiceConfig,
    TargetServiceError,
    execute_read_write_trace,
)


def cfg(**overrides):
    """A small valid configuration; tests override only what they exercise."""
    base = dict(
        tx_bytes=64,
        tCK_ps=500,
        channels=1,
        banks_per_channel=1,
        read_queue_depth=8,
        write_queue_depth=8,
        service_cycles=1,
        bytes_per_cycle=None,
        read_latency_cycles=0,
        write_latency_cycles=0,
        row_hit_cycles=None,
        row_miss_cycles=None,
    )
    base.update(overrides)
    return TargetServiceConfig(**base)


class Recorder:
    def __init__(self):
        self.calls = []

    def __call__(self, addr, is_write, size):
        self.calls.append((addr, is_write, size))


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
def test_error_is_a_value_error_and_semantic_error():
    assert issubclass(TargetServiceError, ValueError)
    assert issubclass(TargetServiceError, SemanticError)


@pytest.mark.parametrize("kwargs", [
    dict(service_cycles=1, bytes_per_cycle=16),
    dict(service_cycles=None, bytes_per_cycle=None),
])
def test_config_requires_exactly_one_service_rate(kwargs):
    with pytest.raises(TargetServiceError, match="exactly one"):
        cfg(**kwargs)


@pytest.mark.parametrize("value", [0, -64, 3, 48, 100])
def test_config_rejects_bad_tx_bytes(value):
    with pytest.raises(TargetServiceError, match="tx_bytes"):
        cfg(tx_bytes=value)


def test_config_rejects_bool_for_integer_fields():
    with pytest.raises(TargetServiceError, match="tx_bytes"):
        cfg(tx_bytes=True)
    with pytest.raises(TargetServiceError, match="version"):
        cfg(version=True)
    with pytest.raises(TargetServiceError, match="tCK_ps"):
        cfg(tCK_ps=True)
    with pytest.raises(TargetServiceError, match="channels"):
        cfg(channels=True)


def test_config_rejects_bad_mapping_and_arbitration():
    with pytest.raises(TargetServiceError, match="mapping"):
        cfg(mapping="channel_bank_row_col_v2")
    with pytest.raises(TargetServiceError, match="arbitration"):
        cfg(arbitration="PRIORITY")
    with pytest.raises(TargetServiceError, match="arbitration"):
        cfg(arbitration="fifo")


@pytest.mark.parametrize("field,value", [
    ("model_id", ""),
    ("model_id", "   "),
    ("model_id", 7),
    ("version", 0),
    ("tCK_ps", 0),
    ("channels", 0),
    ("banks_per_channel", 0),
    ("read_queue_depth", 0),
    ("write_queue_depth", 0),
    ("service_cycles", 0),
    ("read_latency_cycles", -1),
    ("write_latency_cycles", -1),
    ("row_hit_cycles", -1),
    ("row_miss_cycles", -1),
])
def test_config_rejects_out_of_range_fields(field, value):
    with pytest.raises(TargetServiceError):
        cfg(**{field: value})


def test_config_rejects_zero_bytes_per_cycle():
    with pytest.raises(TargetServiceError, match="bytes_per_cycle"):
        cfg(service_cycles=None, bytes_per_cycle=0)


def test_config_is_frozen_and_has_stable_identity():
    a = cfg()
    b = cfg()
    assert a == b
    assert a.to_dict()["model_id"] == "TARGET_FIFO_BANK_V1"
    assert a.to_dict()["mapping"] == "channel_bank_row_col_v1"
    assert a.config_id() == b.config_id()
    assert len(a.config_id()) == 64
    assert a.config_id() != cfg(tx_bytes=32).config_id()
    assert a.config_id() != cfg(arbitration="ROUND_ROBIN").config_id()
    assert a.config_id() != cfg(service_cycles=2).config_id()
    assert TargetServiceConfig(**a.to_dict()) == a
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.tx_bytes = 128


# ----------------------------------------------------------------------
# Address decode
# ----------------------------------------------------------------------
def test_decode_address_is_deterministic_with_channel_then_bank_order():
    service = TargetService(cfg(channels=2, banks_per_channel=2))
    assert service.decode_address(0) == (0, 0, 0, 0)
    assert service.decode_address(64) == (1, 0, 0, 0)
    assert service.decode_address(128) == (0, 1, 0, 0)
    assert service.decode_address(192) == (1, 1, 0, 0)
    assert service.decode_address(256) == (0, 0, 1, 0)
    # Addresses inside one transaction granule share a location.
    assert service.decode_address(65) == service.decode_address(64)
    # Same row, next column group.
    stride = 64 * 2 * 2 * ROWS_PER_BANK
    assert service.decode_address(stride) == (0, 0, 0, 1)
    assert service.decode_address(2 * stride) == (0, 0, 0, 2)


def test_decode_address_refuses_bad_addresses():
    service = TargetService(cfg())
    with pytest.raises(TargetServiceError, match="addr"):
        service.decode_address(-1)
    with pytest.raises(TargetServiceError, match="addr"):
        service.decode_address(True)


# ----------------------------------------------------------------------
# Backpressure
# ----------------------------------------------------------------------
def test_send_backpressure_is_per_class_and_never_calls_callback():
    service = TargetService(cfg(
        read_queue_depth=2, write_queue_depth=1, service_cycles=5))
    rec = Recorder()

    assert service.send(0, False, 64, 0, 0, rec) is True
    assert service.send(64, False, 64, 0, 0, rec) is True
    assert service.send(128, False, 64, 0, 0, rec) is False
    assert rec.calls == []

    assert service.send(0, True, 64, 0, 0, rec) is True
    assert service.send(64, True, 64, 0, 0, rec) is False

    stats = service.get_stats()
    assert stats["total_num_read_requests"] == 2
    assert stats["total_num_write_requests"] == 1
    assert stats["num_read_reqs"] == 2
    assert stats["num_write_reqs"] == 1
    assert stats["num_read_reqs_outstanding"] == 2
    assert stats["num_write_reqs_outstanding"] == 1
    assert stats["backpressure_events"] == 2
    assert stats["read_backpressure_events"] == 1
    assert stats["write_backpressure_events"] == 1
    assert rec.calls == []


def test_backpressure_is_per_bank():
    service = TargetService(cfg(
        channels=1, banks_per_channel=2,
        read_queue_depth=1, write_queue_depth=1, service_cycles=5))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec) is True    # bank 0
    assert service.send(64, False, 64, 0, 0, rec) is True   # bank 1
    assert service.send(128, False, 64, 0, 0, rec) is False  # bank 0 full
    assert service.send(192, False, 64, 0, 0, rec) is False  # bank 1 full


def test_queue_slot_frees_when_service_starts():
    service = TargetService(cfg(service_cycles=3, read_queue_depth=1))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec) is True
    assert service.send(64, False, 64, 0, 0, rec) is False
    service.tick()  # starts the first request; the waiting FIFO is now empty
    assert service.send(128, False, 64, 0, 0, rec) is True
    service.drain()
    assert [call[0] for call in rec.calls] == [0, 128]


def test_send_accepts_native_integer_is_write_values():
    service = TargetService(cfg())
    rec = Recorder()
    assert service.send(0, 0, 64, 0, 0, rec) is True
    assert service.send(64, 1, 64, 0, 0, rec) is True
    service.drain()
    assert rec.calls == [(0, 0, 64), (64, 1, 64)]


def test_send_refuses_bad_arguments():
    service = TargetService(cfg())
    with pytest.raises(TargetServiceError, match="addr"):
        service.send(-1, False, 64, 0, 0, None)
    with pytest.raises(TargetServiceError, match="is_write"):
        service.send(0, 2, 64, 0, 0, None)
    with pytest.raises(TargetServiceError, match="size"):
        service.send(0, False, 0, 0, 0, None)
    with pytest.raises(TargetServiceError, match="callback"):
        service.send(0, False, 64, 0, 0, "not-callable")
    assert service.send(0, False, 64, 0, 0, None) is True
    service.drain()


# ----------------------------------------------------------------------
# Arbitration and service duration
# ----------------------------------------------------------------------
def test_fifo_order_within_a_bank_across_read_and_write():
    service = TargetService(cfg(service_cycles=2))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    assert service.send(64, True, 64, 0, 0, rec)
    assert service.send(128, False, 64, 0, 0, rec)
    assert service.drain() == 6
    assert rec.calls == [(0, 0, 64), (64, 1, 64), (128, 0, 64)]


def test_round_robin_alternates_read_and_write_classes():
    service = TargetService(cfg(
        arbitration="ROUND_ROBIN", service_cycles=1))
    rec = Recorder()
    for addr, is_write in [(0, False), (64, False), (128, True), (192, True)]:
        assert service.send(addr, is_write, 64, 0, 0, rec)
    assert service.drain() == 4
    assert [call[0] for call in rec.calls] == [0, 128, 64, 192]


def test_round_robin_first_contention_follows_arrival_order():
    service = TargetService(cfg(
        arbitration="ROUND_ROBIN", service_cycles=1))
    rec = Recorder()
    assert service.send(0, True, 64, 0, 0, rec)   # write arrives first
    assert service.send(64, False, 64, 0, 0, rec)  # read arrives second
    service.drain()
    assert [call[0] for call in rec.calls] == [0, 64]


def test_banks_service_concurrently_and_independently():
    service = TargetService(cfg(
        channels=1, banks_per_channel=2, service_cycles=2))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)   # bank 0
    assert service.send(64, False, 64, 0, 0, rec)  # bank 1
    service.tick()
    assert rec.calls == []
    service.tick()
    assert len(rec.calls) == 2
    assert service.get_stats()["num_read_reqs_served"] == 2


def test_fixed_cycle_service_duration_and_latency():
    service = TargetService(cfg(service_cycles=3))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    assert service.tick() is None
    assert rec.calls == []
    assert service.tick() is None
    assert rec.calls == []
    assert service.tick() is None
    assert rec.calls == [(0, 0, 64)]
    stats = service.get_stats()
    assert stats["cycles"] == 3
    assert stats["avg_read_latency"] == 3.0


def test_rate_form_service_duration_rounds_up():
    service = TargetService(cfg(service_cycles=None, bytes_per_cycle=16))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    for _ in range(3):
        service.tick()
    assert rec.calls == []
    service.tick()
    assert rec.calls == [(0, 0, 64)]
    assert service.get_stats()["avg_read_latency"] == 4.0

    other = TargetService(cfg(service_cycles=None, bytes_per_cycle=16))
    other_rec = Recorder()
    assert other.send(0, False, 17, 0, 0, other_rec)
    other.tick()
    assert other_rec.calls == []
    other.tick()
    assert other_rec.calls == [(0, 0, 17)]
    assert other.get_stats()["avg_read_latency"] == 2.0


def test_latency_is_added_to_service_duration():
    service = TargetService(cfg(
        service_cycles=2, read_latency_cycles=3, write_latency_cycles=1))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    service.drain()
    assert rec.calls == [(0, 0, 64)]
    assert service.get_stats()["avg_read_latency"] == 5.0

    assert service.send(64, True, 64, 0, 0, rec)
    service.drain()
    assert rec.calls[-1] == (64, 1, 64)
    assert service.get_stats()["avg_write_latency"] == 3.0


# ----------------------------------------------------------------------
# Row behavior
# ----------------------------------------------------------------------
def test_row_hit_miss_and_conflict_adjustment():
    service = TargetService(cfg(
        tx_bytes=1, service_cycles=1,
        row_hit_cycles=0, row_miss_cycles=4))
    rec = Recorder()

    # No row open: row miss, duration 1 + 4 = 5.
    assert service.send(0, False, 1, 0, 0, rec)
    service.drain()
    assert rec.calls == [(0, 0, 1)]
    assert service.get_stats()["avg_read_latency"] == 5.0
    assert service.get_stats()["row_misses"] == 1

    # Same row, next column group: row hit, duration 1 + 0 = 1.
    assert service.send(ROWS_PER_BANK, False, 1, 0, 0, rec)
    service.drain()
    assert service.get_stats()["row_hits"] == 1

    # Different row with row 0 still open: conflict, miss adjustment.
    assert service.send(1, False, 1, 0, 0, rec)
    service.drain()
    stats = service.get_stats()
    assert stats["row_misses"] == 1
    assert stats["row_hits"] == 1
    assert stats["row_conflicts"] == 1
    assert stats["avg_read_latency"] == 11 / 3


def test_row_statistics_are_tracked_without_row_timing():
    service = TargetService(cfg(service_cycles=1))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    service.drain()
    assert service.send(0, False, 64, 0, 0, rec)
    service.drain()
    stats = service.get_stats()
    assert stats["row_misses"] == 1
    assert stats["row_hits"] == 1
    assert stats["avg_read_latency"] == 1.0


# ----------------------------------------------------------------------
# Completion, finalize, drain
# ----------------------------------------------------------------------
def test_callbacks_fire_exactly_once_and_extra_ticks_do_not_refire():
    service = TargetService(cfg(service_cycles=2))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    service.drain()
    assert rec.calls == [(0, 0, 64)]
    for _ in range(10):
        service.tick()
    assert rec.calls == [(0, 0, 64)]
    assert service.get_stats()["num_read_reqs_served"] == 1


def test_finalize_refuses_outstanding_then_drain_completes():
    service = TargetService(cfg(service_cycles=4))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    with pytest.raises(TargetServiceError, match="outstanding"):
        service.finalize()
    assert service.closed is True
    assert service.outstanding == 1
    with pytest.raises(TargetServiceError, match="finalized"):
        service.send(64, False, 64, 0, 0, rec)

    assert service.drain() == 4
    assert rec.calls == [(0, 0, 64)]
    service.finalize()  # idempotent once drained
    assert service.get_stats()["num_read_reqs_served"] == 1


def test_drain_max_ticks_refuses_a_shortfall_then_finishes():
    service = TargetService(cfg(service_cycles=5))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    with pytest.raises(TargetServiceError, match="max_ticks"):
        service.drain(max_ticks=2)
    assert service.memory_ticks == 2
    assert service.outstanding == 1
    assert rec.calls == []
    assert service.drain() == 3
    assert rec.calls == [(0, 0, 64)]


def test_finalize_with_no_outstanding_is_idempotent():
    service = TargetService(cfg())
    service.finalize()
    service.finalize()
    assert service.closed is True


# ----------------------------------------------------------------------
# Stats
# ----------------------------------------------------------------------
def test_stats_reconcile_reads_and_writes_separately():
    service = TargetService(cfg(
        channels=2, banks_per_channel=2,
        read_queue_depth=16, write_queue_depth=16, service_cycles=3))
    rec = Recorder()
    accepted_reads = accepted_writes = 0
    for i in range(8):
        is_write = i % 3 == 0
        if service.send(i * 64, is_write, 64, 0, 0, rec):
            if is_write:
                accepted_writes += 1
            else:
                accepted_reads += 1

    assert accepted_reads == 5
    assert accepted_writes == 3
    service.tick()
    stats = service.get_stats()
    assert stats["total_num_read_requests"] == stats["num_read_reqs"] \
        == accepted_reads
    assert stats["total_num_write_requests"] == stats["num_write_reqs"] \
        == accepted_writes
    assert stats["num_read_reqs_served"] + \
        stats["num_read_reqs_outstanding"] == stats["num_read_reqs"]
    assert stats["num_write_reqs_served"] + \
        stats["num_write_reqs_outstanding"] == stats["num_write_reqs"]
    assert stats["accepted_requests"] == accepted_reads + accepted_writes
    assert stats["served_requests"] + stats["outstanding_requests"] == \
        stats["accepted_requests"]
    assert stats["num_write_reqs_coalesced"] == 0
    assert stats["cycles"] == stats["memory_ticks"] == \
        service.memory_ticks == 1
    assert stats["read_queue_len"] == 3
    assert stats["write_queue_len"] == 1
    assert stats["read_queue_len_avg"] == 3.0
    assert stats["write_queue_len_avg"] == 1.0
    assert rec.calls == []

    for key in ("total_num_read_requests", "total_num_write_requests",
                "num_read_reqs_served", "cycles"):
        assert stats[key] == stats["memory_system"][key]

    service.drain()
    stats = service.get_stats()
    assert stats["num_read_reqs_served"] == accepted_reads
    assert stats["num_write_reqs_served"] == accepted_writes
    assert stats["outstanding_requests"] == 0
    assert stats["read_queue_len"] == 0
    assert stats["write_queue_len"] == 0
    assert stats["read_queue_len_avg"] == 1.5
    assert stats["write_queue_len_avg"] == 0.5


def test_stats_are_deterministic_across_identical_runs():
    def run():
        service = TargetService(cfg(
            channels=2, banks_per_channel=2,
            read_queue_depth=4, write_queue_depth=4, service_cycles=2))
        rec = Recorder()
        for i in range(12):
            assert service.send(i * 64, i % 4 == 0, 64, 0, 0, rec)
        service.drain()
        return service.get_stats(), list(rec.calls)

    assert run() == run()


def test_native_contract_surface():
    service = TargetService(cfg())
    assert service.tCK_ps == 500
    assert service.tx_bytes == 64
    assert service.memory_ticks == 0
    assert callable(service.tick)
    assert callable(service.send)
    assert callable(service.get_stats)
    assert callable(service.finalize)
    stats = service.get_stats()
    assert stats["memory_system"]["total_num_read_requests"] == 0
    assert stats["total_num_write_requests"] == 0


# ----------------------------------------------------------------------
# Trace helper
# ----------------------------------------------------------------------
def test_trace_helper_small_trace_and_optional_address_vector():
    trace = "\n".join([
        "R 0",
        "W 64 0,0,0,0,0,0,0",
        "R 128",
        "",
    ])
    service = TargetService(cfg(service_cycles=1))
    result = execute_read_write_trace(trace, service=service)
    assert result["status"] == "COMPLETE"
    assert result["metrics"] == {
        "requests": 3,
        "reads": 2,
        "writes": 1,
        "transaction_bytes": 64,
        "bytes": 192,
        "read_bytes": 128,
        "write_bytes": 64,
        "ticks": 3,
        "cycles": 3,
        "max_ticks": None,
        "callbacks": 3,
    }
    stats = result["stats"]
    assert stats["total_num_read_requests"] == 2
    assert stats["total_num_write_requests"] == 1
    assert stats["num_read_reqs_served"] == 2
    assert stats["num_write_reqs_served"] == 1
    assert stats["outstanding_requests"] == 0


def test_trace_helper_two_runs_are_equal():
    trace = "R 0\nW 64\nR 128\nR 192\nW 256\n"

    def run():
        service = TargetService(cfg(service_cycles=2))
        return execute_read_write_trace(trace, service=service)

    assert run() == run()


@pytest.mark.parametrize("trace", [
    "R\n",
    "W\n",
    "X 0\n",
    "R not-an-int\n",
    "R -1\n",
    "R 0 0,0,oops\n",
    "R 0 0,,0\n",
])
def test_trace_helper_refuses_malformed_lines(trace):
    service = TargetService(cfg())
    with pytest.raises(TargetServiceError):
        execute_read_write_trace(trace, service=service)


def test_trace_helper_refuses_non_string_trace():
    service = TargetService(cfg())
    with pytest.raises(TargetServiceError, match="string"):
        execute_read_write_trace(b"R 0\n", service=service)


def test_trace_helper_max_ticks_refusal():
    service = TargetService(cfg(service_cycles=5, read_queue_depth=1))
    with pytest.raises(TargetServiceError, match="max_ticks"):
        execute_read_write_trace("R 0\nR 64\nR 128\n",
                                 service=service, max_ticks=1)
    assert service.memory_ticks == 1


def test_trace_helper_empty_trace_with_zero_budget():
    service = TargetService(cfg())
    result = execute_read_write_trace("", service=service, max_ticks=0)
    assert result["status"] == "COMPLETE"
    assert result["metrics"]["requests"] == 0
    assert result["metrics"]["ticks"] == 0
    assert result["stats"]["cycles"] == 0


def test_trace_helper_refuses_non_power_of_two_transaction_size():
    class Stub:
        tx_bytes = 3
        has_outstanding = False
        outstanding = 0
        memory_ticks = 0

        def send(self, *args):
            return True

        def tick(self):
            pass

        def get_stats(self):
            return {}

    with pytest.raises(TargetServiceError, match="power of two"):
        execute_read_write_trace("R 0\n", service=Stub())


def test_trace_helper_refuses_a_non_quiescent_service():
    service = TargetService(cfg(service_cycles=4))
    rec = Recorder()
    assert service.send(0, False, 64, 0, 0, rec)
    with pytest.raises(TargetServiceError, match="quiescent"):
        execute_read_write_trace("R 64\n", service=service)


def test_module_has_no_wall_clock_or_randomness_imports():
    tree = ast.parse(inspect.getsource(ts))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "time" not in imported
    assert "random" not in imported
