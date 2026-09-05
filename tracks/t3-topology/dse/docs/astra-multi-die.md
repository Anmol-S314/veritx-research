## 11. ASTRA-sim Multi-Die Simulation

### 11.1 What ASTRA-sim Does

ASTRA-sim models **multi-die** (chiplet) systems:
- Multiple dies connected via UCIe bridges
- Each die has its own NoC (can be BookSim2)
- Die-to-die communication via bridge models
- Support for different topologies per die

### 11.2 Build

```bash
# 1. Sync BookSim2 source
python3 scripts/tools.py booksim2 sync

# 2. Build ASTRA-sim
cd third_party/astra-sim/build/astra_booksim2
./build.sh

# 3. Verify
ls -la ../../astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2
```

### 11.3 Configuration

ASTRA-sim needs four JSON configs:

| Config | Purpose | Example |
|--------|---------|---------|
| Network | Topology, link bandwidth | `examples/network/ns3/sample_16nodes_2D.json` |
| System | Compute collectives | `examples/system/native_collectives/Ring_4chunks.json` |
| Workload | Application workload | `examples/workload/microbenchmarks/` |
| Remote Memory | Memory hierarchy | `examples/remote_memory/analytical/` |

### 11.4 Run

```bash
third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2 \
    --workload-configuration=<workload.json> \
    --network-configuration=<network.json> \
    --system-configuration=<system.json> \
    --remote-memory-configuration=<memory.json>
```

### 11.5 Common Errors

| Error | Fix |
|-------|-----|
| `veritx_embed.hpp: No such file` | Run `python3 scripts/tools.py booksim2 sync` |
| `PER_NODE_MEMORY_EXPANSION` abort | Set `num-devices` in memory config |
| Binary hangs at stdin | ASTRA-sim waits for `exit` command |
| `yaml-cpp` not found | `sudo apt install libyaml-cpp-dev` |
| `cmake version too old` | Need cmake 3.22+: `pip install cmake` |

---

<a name="full-stack-llm-serving-simulation-veritx-serve"></a>
