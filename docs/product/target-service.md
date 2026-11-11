# Target/memory service model

`simulation/target_service.py` is a deterministic, generic target model with
per-bank queues and service timing. It implements the same duck-typed contract
the native coupled adapter already uses:

```python
tick()
send(addr, is_write, size, src, dst, callback) -> bool
get_stats()
finalize()
memory_ticks
tCK_ps
tx_bytes
```

It is deliberately not a DRAM protocol model. There is no refresh, bank-group
timing, capacity enforcement, coherency, or request/response handshake. It is
the queue/service/bank layer that sits between a traffic source and a
network, not a replacement for Ramulator.

## Configuration

```python
TargetServiceConfig(
    tx_bytes=32, tCK_ps=625,
    channels=8, banks_per_channel=16,
    read_queue_depth=32, write_queue_depth=32,
    bytes_per_cycle=32,          # or service_cycles=N, not both
    read_latency_cycles=20, write_latency_cycles=10,
    row_hit_cycles=4, row_miss_cycles=20,
    arbitration="FIFO",          # or ROUND_ROBIN
)
```

- `tx_bytes` is the transaction granule; it must be a power of two.
- Exactly one of `service_cycles` and `bytes_per_cycle` is set.
- Addresses decode as `channel, bank, row, column`, low bits first.
- `row_hit_cycles` / `row_miss_cycles` are optional adjustments; row
  statistics are tracked even when timing adjustments are disabled.
- `config_id()` is a stable hash over the full config surface.

## Behavior

- `send()` enqueues into the per-bank read/write FIFO. A full queue returns
  `False` without enqueuing or firing the callback; the caller retries.
- `tick()` advances one memory clock and starts service on free banks.
- Service duration is fixed or `ceil(size / bytes_per_cycle)`, plus the
  read/write latency and optional row adjustment.
- Callbacks fire exactly once as `(addr, int(is_write), size)`.
- `finalize()` refuses while requests are outstanding; `drain()` completes
  them first.
- `get_stats()` returns flat counters and the nested `memory_system` dict the
  native adapter expects.

## Trace helper

`execute_read_write_trace(trace_text, service=..., max_ticks=...)` parses the
existing Ramulator-style `R|W <addr>` rows, issues one transaction per tick,
retries on backpressure, drains, and returns `status`, `metrics`, and `stats`.
It refuses malformed lines, non-power-of-two transaction sizes, a
`max_ticks` shortfall, and an undrained service.

## What it is not

- Not wired into `backend/native_coupled.py` or the federation adapter yet.
- Not a coherency or protocol model.
- Not a substitute for Ramulator's HBM timing. Ramulator remains the
  cycle-accurate DRAM evidence path for the profiles it covers.
- Not causally coupled to BookSim or ASTRA. A target result is a separate
  question; do not add its latency to a network result.

The next step is to run the decision-accuracy matrix with and without this
model. If the fabric ranking does not move when the target backpressures, the
model is a diagnostic, not a selection feature.
