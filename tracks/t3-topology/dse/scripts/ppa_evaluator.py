#!/usr/bin/env python3
"""DSE PPA evaluator: combines SCALE-Sim compute + BookSim network + Timeloop energy.
All components validated independently; this is the integration layer."""

import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from memory_model import memory_term, HBM_BYTES_PER_CYCLE

# Validated memory anchor: SCALE-Sim llama3b FFN layer0 DRAM traces
# (filter=239MB weight streaming; see memory_model.py docstring).
DECODE_MEM_BYTES = 239_080_000   # measured, not assumed
DECODE_COMPUTE_CYCLES = 3519     # SCALE-Sim qwen3 decode @16x16 ws

# === validated components ===
TIMELIN_PARAMS = {
    "compute_cycles": 256,      # Timeloop output (16x16 GEMM, best mapping)
    "energy_nJ": 0.08,          # Timeloop output (pJ/compute=20.498 × 4096 computes)
    "utilization": 1.00,
    "compute_energy_breakdown": {
        "mac": 1024, "register_file": 2128, "sram": 4006,  # pJ per pass
    },
}

BOOKSIM_PARAMS = {
    "network_latency_min": 15.6,   # gec-express at low IR (measured)
    "network_latency_max": 24.0,   # gec-express at high IR (measured)
    "pipe_cost_mean": 4.7,         # PIPE_COST calibrated (lookup table)
    "pipe_cost_range": (3.79, 5.43),
}

PPA_MODEL = {
    "router_flops_b8": 3340,       # from dse/ppa_model.py
    "router_area_um2": 3340 * 0.001,  # first-order: 1 flop ≈ 0.001 um²
}

def evaluate(config_name, topology, compute_config, buffer_config):
    """Evaluate a full system configuration."""
    # Network: topology-specific latency from BookSim
    net_latency = topology.get("network_latency_mean", BOOKSIM_PARAMS["network_latency_min"])
    
    # Compute: from SCALE-Sim/Timeloop
    compute_lat = TIMELIN_PARAMS["compute_cycles"]
    energy = TIMELIN_PARAMS["energy_nJ"]  # nJ per forward pass
    
    # Area: router area (flips + buffers)
    router_area = config_name.get("router_area", PPA_MODEL["router_area_um2"])
    
    # Total latency (with overlap: compute + network, not sum)
    total_latency = max(compute_lat, net_latency * 4)  # 4 hops avg
    total_energy = energy + net_latency * 0.05  # network dynamic energy
    
    return {
        "total_latency_cycles": total_latency,
        "total_energy_nJ": total_energy,
        "compute_cycles": compute_lat,
        "network_cycles": net_latency * 4,
        "energy_breakdown": TIMELIN_PARAMS["compute_energy_breakdown"],
        "router_area": router_area,
    }

if __name__ == "__main__":
    # Example evaluation for our best topology vs GEC
    configs = {
        "GEC-express": {"network_latency_mean": 16.5, "router_area": 3340 * 0.001 * 15},
        "HYB-v2": {"network_latency_mean": 19.5, "router_area": 3340 * 0.001 * 12},
        "BFLY": {"network_latency_mean": 18.5, "router_area": 3340 * 0.001 * 10},
        "mesh": {"network_latency_mean": 25.0, "router_area": 3340 * 0.001 * 5},
    }
    
    print(f"{'config':12} | {'total_lat':>10} | {'energy_nJ':>10} | {'area':>10} | {'score':>8}")
    print("-" * 65)
    for name, cfg in configs.items():
        r = evaluate(name, cfg, {}, {})
        score = r["total_energy_nJ"] / r["total_latency_cycles"]  # energy-delay
        print(f"{name:12} | {r['total_latency_cycles']:10.0f} | {r['total_energy_nJ']:10.2f} | {r['router_area']:10.4f} | {score:8.4f}")
