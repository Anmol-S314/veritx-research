#!/usr/bin/env python3
"""workload_generators.py — P0: Synthetic workload family generators for ensemble testing.

Each generator produces an NxN traffic matrix representing a distinct workload family.
These are used by ensemble_robustness.py to test topology robustness across
structurally different traffic patterns, not just perturbations of one trace.

Families:
  1. moe_dispatch    — the nominal MoE expert dispatch (from trace)
  2. allreduce_ring  — ring allreduce: each node sends to next, receives from prev
  3. kv_cache_multicast — KV-cache reads: few hot nodes broadcast to many
  4. all_to_all      — every node sends equally to every other (worst-case)
  5. hotspot         — subset of nodes are heavy sources+sinks
  6. bursty_dispatch — top-k dispatch with temporal burstiness

Usage:
  from workload_generators import generate_all_families
  matrices = generate_all_families(n=64)
  # matrices = {"moe_dispatch": array, "allreduce_ring": array, ...}
"""
import numpy as np
from typing import Dict


def generate_allreduce_ring(n: int) -> np.ndarray:
    """Ring allreduce: each node sends to node (i+1)%n and receives from (i-1)%n.
    Total volume = 2*(n-1) per node (allreduce pattern)."""
    T = np.zeros((n, n))
    for i in range(n):
        dst = (i + 1) % n
        T[i][dst] = 1.0
    # Normalize rows
    row_sums = T.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    T = T / row_sums * T.sum(axis=1, keepdims=True)
    return T


def generate_kv_cache_multicast(n: int, n_hot: int = 4, fanout: int = 8, seed: int = 42) -> np.ndarray:
    """KV-cache reads: a few hot nodes (KV-cache servers) multicast to many.
    Hot nodes = KV cache holders; cold nodes = request generators."""
    rng = np.random.default_rng(seed)
    T = np.zeros((n, n))
    hot = rng.choice(n, size=n_hot, replace=False)
    for h in hot:
        # Hot node sends to random fanout nodes (but not itself)
        targets = rng.choice(n, size=min(fanout, n-1), replace=False)
        targets = targets[targets != h]
        T[h][targets] = 1.0
    # Cold nodes send small amounts to hot nodes (requests)
    cold = [i for i in range(n) if i not in hot]
    for c in cold:
        targets = rng.choice(hot, size=min(2, len(hot)), replace=False)
        T[c][targets] = 0.5
    row_sums = T.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    T = T / row_sums * T.sum(axis=1, keepdims=True)
    return T


def generate_all_to_all(n: int) -> np.ndarray:
    """Uniform all-to-all: every node sends equally to every other."""
    T = np.ones((n, n))
    np.fill_diagonal(T, 0)
    row_sums = T.sum(axis=1, keepdims=True)
    T = T / row_sums
    return T


def generate_hotspot(n: int, hot_fraction: float = 0.3, seed: int = 42) -> np.ndarray:
    """Hotspot pattern: subset of nodes are heavy sources and sinks."""
    rng = np.random.default_rng(seed)
    hot = set(rng.choice(n, size=int(n * hot_fraction), replace=False))
    T = np.zeros((n, n))
    for s in range(n):
        for d in range(n):
            if s == d: continue
            if s in hot and d in hot:
                T[s][d] = 3.0
            elif s in hot or d in hot:
                T[s][d] = 1.5
            else:
                T[s][d] = 0.5
    row_sums = T.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    T = T / row_sums * T.sum(axis=1, keepdims=True)
    return T


def generate_bursty_dispatch(n: int, k_experts: int = 8, seed: int = 42) -> np.ndarray:
    """Bursty top-k dispatch: tokens route to k expert groups with temporal burstiness.
    Models real LLM serving where dispatch is not smooth."""
    rng = np.random.default_rng(seed)
    T = np.zeros((n, n))
    # Assign expert groups: nodes 0..k-1 are experts, rest are dispatchers
    expert_nodes = list(range(min(k_experts, n)))
    dispatchers = [i for i in range(n) if i not in expert_nodes]
    for d in dispatchers:
        # Each dispatcher sends to all experts with bursty weights
        weights = rng.exponential(1.0, size=len(expert_nodes))
        weights = weights / weights.sum()
        for e, w in zip(expert_nodes, weights):
            T[d][e] = w
    # Experts communicate with each other (expert-parallel allreduce)
    for e1 in expert_nodes:
        for e2 in expert_nodes:
            if e1 != e2:
                T[e1][e2] = 0.3
    row_sums = T.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    T = T / row_sums * T.sum(axis=1, keepdims=True)
    return T


def generate_perturbed(T_base: np.ndarray, noise_frac: float = 0.15, seed: int = 42) -> np.ndarray:
    """Generate a perturbed variant of a base traffic matrix."""
    rng = np.random.default_rng(seed)
    n = T_base.shape[0]
    mask = T_base > 0
    noise = rng.uniform(-noise_frac, noise_frac, size=T_base.shape) * mask
    T2 = np.maximum(T_base + noise, 0)
    row_sums = T2.sum(axis=1, keepdims=True)
    row_sums = np.maximum(row_sums, 1e-12)
    T2 = T2 / row_sums * T_base.sum(axis=1, keepdims=True)
    return T2


def generate_all_families(n: int = 64, base_matrix: np.ndarray = None,
                          n_perturbations: int = 3) -> Dict[str, np.ndarray]:
    """Generate all workload families for ensemble testing.
    
    Returns dict of {family_name: NxN traffic matrix}.
    """
    matrices = {}
    
    # If base matrix provided, include it + perturbations
    if base_matrix is not None:
        matrices["nominal"] = base_matrix
        for i in range(n_perturbations):
            matrices[f"perturb_{i}"] = generate_perturbed(base_matrix, seed=42+i)
    
    # Distinct workload families
    matrices["allreduce_ring"] = generate_allreduce_ring(n)
    matrices["kv_cache_multicast"] = generate_kv_cache_multicast(n)
    matrices["all_to_all"] = generate_all_to_all(n)
    matrices["hotspot"] = generate_hotspot(n)
    matrices["bursty_dispatch"] = generate_bursty_dispatch(n)
    
    return matrices


if __name__ == "__main__":
    import json, sys
    
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 64
    matrices = generate_all_families(n=n)
    
    print(f"Generated {len(matrices)} workload families for n={n}:")
    for name, mat in matrices.items():
        total = mat.sum()
        nz = np.count_nonzero(mat)
        print(f"  {name:24s}: total={total:8.1f}, nonzero={nz:5d}/{n*n}")
    
    # Save matrices
    for name, mat in matrices.items():
        path = f".noc_p0/{name}_n{n}.matrix"
        np.savetxt(path, mat, fmt="%.6f")
        print(f"  saved -> {path}")
