# BookSim Performance Optimization Plan

## The Problem

BookSim trace mode is slow with large traces (7.9M packets, 127M flits).
Native patterns (uniform, transpose) are fast because they generate traffic on-the-fly.

**Root cause:** BookSim evaluates ALL 64 routers EVERY cycle, even when most are idle.

```
782K cycles × 64 routers × 3 phases = 150M router evaluations
But only ~10% of routers are active at any cycle
→ 135M wasted evaluations (90% overhead)
```

## Solution: Active Router Mechanism

**Don't replace BookSim's router model. Replace the amount of unnecessary work surrounding it.**

### Stage 1: Profile (find actual hot path)

```bash
# Compile with debug symbols
cd third_party/booksim2/src
make clean && make OPTIMIZE="-g -O2"

# Profile
perf record -g ./booksim /tmp/test.cfg
perf report
```

Find whether time is spent in:
- Router::Evaluate()
- Allocator::Allocate()
- Buffer operations
- TrafficManager
- Flit allocation
- Statistics
- Trace injection

### Stage 2: Low-Risk Optimizations (no semantic change)

**2a. Compact binary trace format**

Current: text file, 7.9M lines, parsed with std::istringstream
Better: binary file, 7.9M × 12 bytes = 95MB, mmap'd

```cpp
struct TracePacket {
    uint32_t cycle;
    uint16_t src;
    uint16_t dst;
    uint16_t cl;
    uint16_t size;
};  // 12 bytes per packet
```

**2b. Lazy packet/flit creation**

Current: pre-allocate all 127M flit objects at startup
Better: create flits only when packets are injected

```
Before: 7.9M trace records + 127M flit objects + metadata
After:  7.9M compact trace records + only active flits
```

**2c. Flit memory pool**

Current: `new Flit(...)` for each flit (heap allocation)
Better: pre-allocated arena/pool

```cpp
class FlitPool {
    std::vector<Flit> pool;
    size_t next;
public:
    Flit* Allocate() { return &pool[next++]; }
    void Reset() { next = 0; }
};
```

**2d. O(1) trace lookup**

Current: scan entire trace every cycle
Better: sorted trace + offset table

```cpp
// Build at load time:
std::vector<size_t> cycle_offsets(max_cycle + 2);
for (auto &p : trace) cycle_offsets[p.cycle + 1]++;

// At injection time:
size_t start = cycle_offsets[_time];
size_t end = cycle_offsets[_time + 1];
for (size_t i = start; i < end; i++)
    Inject(trace[i]);
```

### Stage 3: Router Fast Paths (requires correctness testing)

**3a. Active router skip**

```cpp
// Instead of:
for (int r = 0; r < _size; r++)
    _routers[r]->Evaluate();

// Do:
for (Router *r : active_routers)
    r->Evaluate();
```

Set `_active = true` when:
- Flit arrives
- Credit arrives
- Packet injected
- VC state changes

Set `_active = false` when:
- No flits in buffers
- No pending credits
- No injection pending

**3b. Uncontended fast path**

```cpp
if (input_count == 1 &&
    output_count == 1 &&
    credit_available) {
    FastForwardFlit();  // Skip full pipeline
} else {
    GeneralBookSimPipeline();  // Full arbitration
}
```

### Stage 4: Event-Driven Execution (if still too slow)

```cpp
priority_queue<Event> events;

while (!events.empty()) {
    Event e = events.top();
    events.pop();
    _time = e.cycle;
    ProcessEvent(e);
}
```

This is what Noxim does. But it's a larger rewrite with correctness risk.

## Expected Speedup

| Optimization | Risk | Expected Speedup |
|-------------|------|------------------|
| Binary trace format | None | 2-3× |
| Lazy flit creation | None | 2-4× |
| Flit memory pool | None | 1.5-2× |
| O(1) trace lookup | None | 2-3× |
| Active router skip | Low | 3-10× |
| Uncontended fast path | Medium | 2-5× |
| Event-driven | High | 10-100× |

**Combined (Stage 1-3): 20-50× speedup** → 7.9M packets in 2-5 seconds

## Implementation Order

1. Profile BookSim (find actual hot path)
2. Binary trace format + O(1) lookup (no semantic change)
3. Lazy flit creation + memory pool (no semantic change)
4. Active router skip (requires correctness testing)
5. Event-driven execution (only if still too slow)

## Correctness Verification

After each optimization:
1. Run small traces (1K, 10K packets) and compare results
2. Verify bit-for-bit identical packet latency
3. Verify cycle-for-cycle identical timing
4. Run regression test suite

## Key Insight

**Native patterns are fast because they generate traffic on-the-fly.**
**Trace mode is slow because it replays pre-recorded traffic.**

The optimization path is to make trace mode behave more like native patterns:
- Generate traffic on-the-fly (lazy creation)
- Only simulate active routers (skip idle work)
- Use event-driven execution (skip idle cycles)

This preserves BookSim's cycle-accurate semantics while eliminating wasted work.
