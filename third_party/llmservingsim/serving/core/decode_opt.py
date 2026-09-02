"""Decode optimizations — trace caching, batch decode, async trace generation.

When all requests in a batch are in decode phase (no prefill), subsequent
steps have identical trace structure — only attention latency changes
because kv_len increases by 1 per step. We exploit this to:

1. **Cache first decode trace** — skip perf_db reload and full interpolation
2. **Patch attention only** — only recompute attention 4D lookup per step
3. **Batch decode steps** — pre-generate N traces, feed to binary without
   waiting for intermediate "Waiting" prompts
4. **Async trace gen** — background thread overlaps trace gen with binary exec
"""

import os
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .logger import get_logger

logger = get_logger("DecodeOpt")


# ---------------------------------------------------------------------------
# Decode trace cache — keyed by (instance_id, num_prefill)
# ---------------------------------------------------------------------------

@dataclass
class CachedDecodeTrace:
    """A cached decode trace ready for fast patching."""
    instance_id: int
    num_prefill: int     # cache key — constant during decode phase (always 0)
    hardware: str
    model: str

    # The trace text lines (before Chakra conversion)
    header_line: str = ""
    count_line: str = ""
    column_line: str = ""
    body_lines: List[str] = field(default_factory=list)

    # Line indices where attention latencies live
    attention_indices: List[int] = field(default_factory=list)
    attention_latencies: List[str] = field(default_factory=list)


class DecodeTraceCache:
    """Cache for decode traces with fast attention-only patching.

    Keyed by (instance_id, num_prefill) which stays constant during
    a decode phase. When new prefill requests arrive (num_prefill > 0),
    the cache is invalidated.

    CRITICAL: num_decode changes every step (1, 2, 3...) so it CANNOT
    be used as a cache key. The batch STRUCTURE (which determines the
    trace layout) depends on num_prefill, not num_decode.
    """

    def __init__(self):
        self._cache: Dict[Tuple[int, int], CachedDecodeTrace] = {}
        self._hits = 0
        self._misses = 0

    def cache_from_file(self, instance_id: int, num_prefill: int,
                        hardware: str, model: str,
                        trace_path: str) -> Optional[CachedDecodeTrace]:
        """Parse a trace file and cache it for future patching."""
        if not os.path.exists(trace_path):
            return None

        with open(trace_path, 'r') as f:
            lines = f.readlines()

        if len(lines) < 3:
            return None

        header_line = lines[0]
        count_line = lines[1]
        column_line = lines[2]
        body_lines = list(lines[3:])

        # Find attention layer lines — these are the ones that change
        attn_indices = []
        attn_values = []
        for i, line in enumerate(body_lines):
            parts = line.split()
            if parts and 'attention' in parts[0].lower():
                attn_indices.append(i)
                attn_values.append(parts[1] if len(parts) > 1 else "1")

        cached = CachedDecodeTrace(
            instance_id=instance_id,
            num_prefill=num_prefill,
            hardware=hardware,
            model=model,
            header_line=header_line,
            count_line=count_line,
            column_line=column_line,
            body_lines=body_lines,
            attention_indices=attn_indices,
            attention_latencies=attn_values,
        )

        key = (instance_id, num_prefill)
        self._cache[key] = cached
        self._hits += 1

        logger.debug("Cached decode trace: inst=%d num_prefill=%d attn=%d lines=%d",
                     instance_id, num_prefill, len(attn_indices), len(body_lines))
        return cached

    def get(self, instance_id: int, num_prefill: int) -> Optional[CachedDecodeTrace]:
        """Get cached trace by (instance_id, num_prefill)."""
        return self._cache.get((instance_id, num_prefill))

    def patch_and_write(self, instance_id: int, num_prefill: int,
                        new_latencies: List[str],
                        output_path: str) -> bool:
        """Patch attention latencies and write trace file.

        Fast path: no perf_db load, no interpolation, just string replacement.
        """
        cached = self._cache.get((instance_id, num_prefill))
        if cached is None:
            return False

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        with open(output_path, 'w') as f:
            f.write(cached.header_line)
            f.write(cached.count_line)
            f.write(cached.column_line)

            for i, line in enumerate(cached.body_lines):
                if i in cached.attention_indices:
                    attn_pos = cached.attention_indices.index(i)
                    if attn_pos < len(new_latencies):
                        parts = line.split()
                        if len(parts) > 1:
                            parts[1] = new_latencies[attn_pos]
                            f.write('\t'.join(parts) + '\n')
                            continue
                f.write(line)

        return True

    def has(self, instance_id: int, num_prefill: int) -> bool:
        return (instance_id, num_prefill) in self._cache

    def invalidate(self, instance_id: int, num_prefill: int):
        self._cache.pop((instance_id, num_prefill), None)

    def invalidate_all_for_instance(self, instance_id: int):
        """Clear all cached traces for an instance."""
        keys = [k for k in self._cache if k[0] == instance_id]
        for k in keys:
            del self._cache[k]

    def clear(self):
        self._cache.clear()

    @property
    def stats(self) -> str:
        total = self._hits + self._misses
        rate = (self._hits / total * 100) if total > 0 else 0
        return f"DecodeTraceCache: {len(self._cache)} cached, {self._hits} hits ({rate:.0f}%)"


# ---------------------------------------------------------------------------
# Decode batch pre-generation
# ---------------------------------------------------------------------------

@dataclass
class QueuedWorkload:
    """A pre-generated workload path ready to submit to the binary."""
    workload_path: str
    instance_id: int
    batch_id: int


class DecodeBatcher:
    """Pre-generates N decode traces and queues them for the binary.

    Instead of the round-trip per decode step:
        Python: trace gen -> graph gen -> write path
        Binary: process -> output Waiting
        Python: parse -> schedule -> trace gen -> ...

    We batch N decode steps:
        Python: generate N traces + graphs upfront
        Binary: processes all N without intermediate Waiting prompts
        Python: parses all N results

    This eliminates N-1 Python<->binary round-trips.
    """

    def __init__(self, batch_size: int = 32):
        self.batch_size = batch_size
        self._queues: Dict[int, list] = {}  # instance_id -> list of QueuedWorkload
        self._active: Dict[int, bool] = {}

    def start_batch(self, instance_id: int):
        self._active[instance_id] = True
        self._queues[instance_id] = []

    def enqueue(self, instance_id: int, workload_path: str, batch_id: int):
        if instance_id not in self._queues:
            self._queues[instance_id] = []
        self._queues[instance_id].append(QueuedWorkload(
            workload_path=workload_path,
            instance_id=instance_id,
            batch_id=batch_id,
        ))

    def has_workload(self, instance_id: int) -> bool:
        q = self._queues.get(instance_id)
        return q is not None and len(q) > 0

    def next_workload(self, instance_id: int) -> Optional[QueuedWorkload]:
        q = self._queues.get(instance_id)
        if q and len(q) > 0:
            return q.pop(0)
        return None

    def remaining(self, instance_id: int) -> int:
        q = self._queues.get(instance_id)
        return len(q) if q else 0

    def stop_batch(self, instance_id: int):
        self._active[instance_id] = False
        self._queues.pop(instance_id, None)

    def clear(self):
        self._queues.clear()
        self._active.clear()


# ---------------------------------------------------------------------------
# Async trace generation (producer thread)
# ---------------------------------------------------------------------------

class AsyncTraceGenerator:
    """Generates decode traces in a background thread.

    While the binary processes the current batch, a producer thread
    generates the next batch's trace + graph. This overlaps Python
    overhead with binary execution.
    """

    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._result = None
        self._error = None
        self._workload_path = None

    def generate_async(self, batch, trace_fn, graph_fn, workload_fn, **kwargs):
        def _worker():
            try:
                trace_fn(batch, **kwargs)
                graph_fn(batch, **kwargs)
                self._workload_path = workload_fn(batch, **kwargs)
                self._result = True
            except Exception as e:
                self._error = e
                logger.error("Async trace gen failed: %s", e)

        self._thread = threading.Thread(target=_worker, daemon=True)
        self._thread.start()

    def is_ready(self) -> bool:
        return self._thread is not None and not self._thread.is_alive()

    def wait(self, timeout: float = 30.0) -> bool:
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self._error is None and self._result is not None

    def get_workload(self) -> Optional[str]:
        return self._workload_path

    def get_error(self):
        return self._error

    def reset(self):
        self._thread = None
        self._result = None
        self._error = None
        self._workload_path = None


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_trace_cache = DecodeTraceCache()
_decode_batcher = DecodeBatcher()
_async_gen = AsyncTraceGenerator()


def get_trace_cache() -> DecodeTraceCache:
    return _trace_cache

def get_decode_batcher() -> DecodeBatcher:
    return _decode_batcher

def get_async_gen() -> AsyncTraceGenerator:
    return _async_gen

def clear_all_decode_opts():
    _trace_cache.clear()
    _decode_batcher.clear()
    _async_gen.reset()
