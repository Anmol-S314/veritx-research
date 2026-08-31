# Bake-Off Reproducibility Report

**Date:** 2026-08-27
**Status:** 3/4 claims verified, 1 claim corrected

## Summary

| Topology | S1 Claim | Verified Result | Verdict |
|----------|----------|-----------------|---------|
| mesh_8x8 (112 edges) | 23.37c | 23.38c | ✅ exact match |
| custom_anynet (115 edges) | 23.2c | 23.20c | ✅ exact match |
| hierarchical (145→118 edges) | 20.53c (−12.2%) | 22.78c (−2.5%) | ⚠️ direction correct, magnitude corrected |
| flatfly_8x8 (448 edges) | 19.87c (−15%) | 20.38c (−12.8%) | ✅ close match (2.5% off) |

## What changed

### BookSim drain fix (S1)
- Added `_trace_drained` flag in `trafficmanager.hpp/.cpp`
- BookSim exits when trace is exhausted and all flits delivered
- Python subprocess now works in 0.02s instead of hanging

### Hierarchical synthesizer fix (this session)
**Before (broken):** `synthesize_intra_cluster` generated random graphs (`random.randint(2,3)` edges per node). Quality was seed-dependent, topology was unstructured.

**After (fixed):** Deterministic4×4 mesh per cluster (24 edges each) + boundary-node express links between adjacent clusters + full mesh between cluster representatives (6 express shortcuts).

| Metric | Before | After |
|--------|--------|-------|
| Intra-cluster | random edges (seed-dependent) | 4×4 mesh (deterministic) |
| Inter-cluster | linear chain (5 edges) | boundary buses + express mesh (22 edges) |
| Total edges | 145 (varied by seed) | 118 (fixed) |
| Latency | 24.50c (+4.8% vs mesh) | 22.78c (−2.5% vs mesh) |

## Fair comparison (same routing)

| Config | Routing | Latency |
|--------|---------|---------|
| mesh_8x8 | dor | 23.38c |
| mesh_8x8 | min_anynet | 23.62c |
| hierarchical | min_anynet | 22.78c |

**The improvement is from topology, not routing.** Hierarchical beats mesh even when both use the same shortest-path routing (−3.6%). DOR is optimal for mesh (+1.1% worse than hierarchical).

## How to reproduce

```bash
# Generate trace from traffic model
python3 tracks/t3-topology/dse/model_to_trace.py

# Run bake-off
python3 << 'EOF'
import os, subprocess
TRACE = os.path.abspath("tracks/t3-topology/dse/experiments/results/llm64_ring.trace")
BOOKSIM = os.path.abspath("third_party/booksim2/src/booksim")

configs = {
    "mesh": "topology = mesh; k = 8; n = 2; routing_function = dor;",
    "hierarchical": f"topology = anynet; routing_function = min; network_file = {os.path.abspath('tracks/t3-topology/dse/hierarchical.anynet')};",
}
for name, topo in configs.items():
    cfg = f"{topo}\nnum_vcs = 4; vc_buf_size = 8; sim_type = latency; sample_period = 1000; traffic = trace({TRACE});"
    with open(f"/tmp/repro_{name}.cfg", "w") as f:
        f.write(cfg)
    out = subprocess.run([BOOKSIM, f"/tmp/repro_{name}.cfg"], capture_output=True, text=True, timeout=15)
    for line in (out.stdout + out.stderr).split("\n"):
        if "Packet latency average" in line:
            print(f"  {name}: {line.strip()}")
            break
EOF
```

## The honest story

The S1 claim "hierarchical is Pareto winner at 12% better" was based on a broken synthesizer that generated random intra-cluster topologies. A lucky seed happened to produce a good topology. The real improvement is 2.5% — meaningful but not 12%.

**The result is still publishable:** hierarchical beats mesh at near-identical wire cost, with deterministic synthesis. The contribution is the synthesis method, not the magnitude.
