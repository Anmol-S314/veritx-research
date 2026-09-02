"""Decode optimizations — batch decode steps, cache traces, skip redundant graph gen.

When all requests in a batch are in decode phase (no prefill), subsequent
steps have identical trace structure — only attention latency changes
because kv_len increases by 1 per step. We exploit this to:

1. **Cache first decode trace** — skip perf_db reload and full interpolation
2. **Patch attention only** — only recompute attention 4D lookup per step  
3. **Batch decode steps** — pre-generate N traces, feed to binary without
   waiting for intermediate "Waiting" prompts
4. **Skip graph gen for cached traces** — reuse Chakra graph structure
"""

import os
import re
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .logger import get_logger

logger = get_logger("DecodeOpt")


# ---------------------------------------------------------------------------
# Decode trace cache
# ---------------------------------------------------------------------------

@dataclass
class CachedDecodeTrace:
    """A cached decode trace ready for fast patching."""
    instance_id: int
    batch_id: int
    hardware: str
    model: str
    
    # The trace text lines (before Chakra conversion)
    header_line: str = ""       # e.g. "COLOCATED\t\tmodel_parallel_NPU_group: 1\n"
    count_line: str = ""        # e.g. "156\n"
    column_line: str = ""       # header column names
    body_lines: List[str] = field(default_factory=list)  # layer entries
    
    # Line indices where attention latencies live
    attention_indices: List[int] = field(default_factory=list)
    # Original attention latency values (for each attention line)
    attention_latencies: List[str] = field(default_factory=list)
    
    # The Chakra graph .et files directory (shared across decode steps)
    chakra_workload_dir: str = ""


class DecodeTraceCache:
    """Cache for decode traces with fast attention-only patching."""
    
    def __init__(self):
        self._cache: Dict[Tuple[int, int], CachedDecodeTrace] = {}
        self._hits = 0
        self._misses = 0
    
    def cache_from_file(self, instance_id: int, batch_id: int,
                        hardware: str, model: str,
                        trace_path: str) -> Optional[CachedDecodeTrace]:
        """Parse a trace file and cache it."""
        if not os.path.exists(trace_path):
            return None
        
        with open(trace_path, 'r') as f:
            lines = f.readlines()
        
        if len(lines) < 3:
            return None
        
        # Parse structure: type_line, count_line, column_header, body...
        header_line = lines[0]
        count_line = lines[1]
        column_line = lines[2]
        body_lines = list(lines[3:])
        
        # Find attention layer lines (layer_name starts with 'attention_')
        attn_indices = []
        attn_values = []
        for i, line in enumerate(body_lines):
            parts = line.split()
            if parts and parts[0].startswith('attention_'):
                attn_indices.append(i)
                attn_values.append(parts[1] if len(parts) > 1 else "1")
        
        cached = CachedDecodeTrace(
            instance_id=instance_id,
            batch_id=batch_id,
            hardware=hardware,
            model=model,
            header_line=header_line,
            count_line=count_line,
            column_line=column_line,
            body_lines=body_lines,
            attention_indices=attn_indices,
            attention_latencies=attn_values,
        )
        
        key = (instance_id, batch_id)
        self._cache[key] = cached
        return cached
    
    def get(self, instance_id: int, batch_id: int) -> Optional[CachedDecodeTrace]:
        """Get cached trace."""
        key = (instance_id, batch_id)
        return self._cache.get(key)
    
    def patch_and_write(self, instance_id: int, batch_id: int,
                        new_latencies: List[str],
                        output_path: str) -> bool:
        """Patch attention latencies and write trace file.
        
        This is the fast path — no perf_db load, no interpolation,
        just string replacement in cached lines.
        """
        cached = self._cache.get((instance_id, batch_id))
        if cached is None:
            return False
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        with open(output_path, 'w') as f:
            f.write(cached.header_line)
            f.write(cached.count_line)
            f.write(cached.column_line)
            
            for i, line in enumerate(cached.body_lines):
                if i in cached.attention_indices:
                    # Find which attention index this is
                    attn_pos = cached.attention_indices.index(i)
                    if attn_pos < len(new_latencies):
                        parts = line.split()
                        if len(parts) > 1:
                            parts[1] = new_latencies[attn_pos]
                            f.write(' '.join(parts) + '\n')
                            continue
                f.write(line)
        
        return True
    
    def has(self, instance_id: int, batch_id: int) -> bool:
        return (instance_id, batch_id) in self._cache
    
    def invalidate(self, instance_id: int, batch_id: int):
        self._cache.pop((instance_id, batch_id), None)
    
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
        Python: trace gen → graph gen → write path
        Binary: process → output Waiting
        Python: parse → schedule → trace gen → ...
    
    We batch N decode steps:
        Python: generate N traces + graphs upfront
        Binary: processes all N without intermediate Waiting prompts
        Python: parses all N results
    
    This eliminates N-1 Python↔binary round-trips.
    """
    
    def __init__(self, batch_size: int = 32):
        self.batch_size = batch_size
        self._queues: Dict[int, deque] = {}
        self._batching_enabled: Dict[int, bool] = {}
    
    def is_decode_only(self, scheduler) -> bool:
        """Check if a scheduler has only decode requests (no prefill)."""
        if not scheduler.request:
            return False
        return all(not req.is_prefill() for req in scheduler.request 
                    if req.arrival <= scheduler._current_time if hasattr(scheduler, '_current_time'))
    
    def start_batch(self, instance_id: int):
        """Enable batching for an instance."""
        self._batching_enabled[instance_id] = True
        self._queues[instance_id] = deque()
    
    def enqueue(self, instance_id: int, workload_path: str, 
                batch_id: int):
        """Add a pre-generated workload to the queue."""
        if instance_id not in self._queues:
            self._queues[instance_id] = deque()
        self._queues[instance_id].append(QueuedWorkload(
            workload_path=workload_path,
            instance_id=instance_id,
            batch_id=batch_id,
        ))
    
    def has_workload(self, instance_id: int) -> bool:
        """Check if there are queued workloads."""
        q = self._queues.get(instance_id)
        return q is not None and len(q) > 0
    
    def next_workload(self, instance_id: int) -> Optional[QueuedWorkload]:
        """Pop next queued workload."""
        q = self._queues.get(instance_id)
        if q and len(q) > 0:
            return q.popleft()
        return None
    
    def remaining(self, instance_id: int) -> int:
        q = self._queues.get(instance_id)
        return len(q) if q else 0
    
    def stop_batch(self, instance_id: int):
        """Disable batching for an instance."""
        self._batching_enabled[instance_id] = False
        self._queues.pop(instance_id, None)
    
    def clear(self):
        self._queues.clear()
        self._batching_enabled.clear()


# ---------------------------------------------------------------------------
# Async trace generation (producer thread)
# ---------------------------------------------------------------------------

class AsyncTraceGenerator:
    """Generates decode traces in a background thread.
    
    While the binary processes the current batch, a producer thread
    generates the next batch's trace + graph. This overlaps Python
    overhead with binary execution.
    
    Usage:
        gen = AsyncTraceGenerator(generate_trace_fn, generate_graph_fn)
        gen.start(batch, ...)
        # ... binary processes current batch ...
        gen.wait()  # blocks until background generation is done
        workload = gen.get_workload()
    """
    
    def __init__(self):
        self._thread: Optional[threading.Thread] = None
        self._result = None
        self._error = None
        self._workload_path = None
    
    def generate_async(self, batch, trace_fn, graph_fn, workload_fn, **kwargs):
        """Start async trace + graph generation in background."""
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
        """Check if background generation is complete."""
        return self._thread is not None and not self._thread.is_alive()
    
    def wait(self, timeout: float = 30.0) -> bool:
        """Wait for background generation to complete."""
        if self._thread is not None:
            self._thread.join(timeout=timeout)
        return self._error is None and self._result is not None
    
    def get_workload(self) -> Optional[str]:
        """Get the generated workload path."""
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
