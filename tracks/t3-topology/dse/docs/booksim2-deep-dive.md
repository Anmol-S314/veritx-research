## 10. BookSim2 Deep Dive

### 10.1 What BookSim2 Does

BookSim2 is a cycle-accurate network-on-chip simulator. It models:
- Routers (input buffers, VC allocation, switch allocation, crossbar)
- Links (credit-based flow control)
- Traffic patterns (uniform, transpose, hotspot, trace)
- Routing functions (dimension-order, adaptive, minimal)

### 10.2 Our Trace Replay Extension

BookSim2's original traffic patterns are synthetic (uniform random, transpose, etc.). Our extension (`veritx_ext.*`) adds:

1. **TraceTrafficPattern** — reads a trace file and injects packets at the correct cycles
2. **Sequential injection** — O(1) lookup: packets sorted by cycle, inject when `current_cycle >= packet.cycle`
3. **Lazy flit creation** — flits created on injection, not upfront (saves memory)

### 10.3 Embedding API (veritx_embed)

For ASTRA-sim integration, BookSim2 needs to be callable as a library:

```cpp
// Create an embedded traffic manager
EmbedTM* tm = CreateEmbeddedTM("config.cfg");

// Inject packets from external host
tm->InjectUnicast(src, dst, size, packet_id);

// Check if packets have completed
bool done = tm->HasRetired(node_id, packet_id);

// Step the simulation
tm->Tick();
```

### 10.4 Common BookSim Issues

| Issue | Cause | Fix |
|-------|-------|-----|
| `trace() not found` | Built from wrong directory | Build from `third_party/booksim2/src/` |
| `duplicate symbol` | veritx_embed.o linked with main.o | Use `make lib` instead of `make` for embedding |
| `segmentation fault` | Trace file missing or corrupt | Run `veritx trace validate` first |
| `timeout` | Simulation too long | Check trace time range, reduce `sample_period` |

---

<a name="astra-sim-multi-die-simulation"></a>
