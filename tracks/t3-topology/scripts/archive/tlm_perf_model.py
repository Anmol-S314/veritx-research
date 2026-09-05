#!/usr/bin/env python3
"""tlm_perf_model.py — P2: TLM/SystemC performance model.

Cycle-approximate latency estimator from topology + traffic matrix.
No RTL simulation needed — useful for rapid DSE iteration.

Usage:
  python3 tlm_perf_model.py --anynet .noc_p0/custom_v2.anynet \
      --matrix .noc_p0/traffic.matrix --out .noc_p0/tlm_result.json
"""
import argparse, json, numpy as np
from collections import defaultdict, deque
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadlock_routing import parse_anynet


def bfs_hops(adj, n):
    D = []
    for s in range(n):
        d = [-1]*n; d[s]=0; q = deque([s])
        while q:
            u = q.popleft()
            for v in adj.get(u, []):
                if d[v] < 0: d[v] = d[u]+1; q.append(v)
        D.append(d)
    return D


def tlm_estimate(adj, n, matrix, router_lat=2, wire_lat=1, buf_depth=8):
    """TLM model: latency = (router+wire)*hops + queue_delay(traffic_intensity)."""
    D = bfs_hops(adj, n)
    results = {}
    total_weighted_lat = 0
    total_weight = 0
    max_lat = 0

    for src in range(n):
        for dst in range(n):
            if src == dst or matrix[src][dst] == 0:
                continue
            h = D[src][dst]
            if h < 0:
                continue
            # Base latency: per-hop router + wire delay
            base_lat = h * (router_lat + wire_lat)
            # Queue delay: M/D/1 approximation = rho / (1-rho) * service_time
            # rho = arrival_rate / service_rate; service_time = router_lat
            rho = min(0.95, matrix[src][dst] * 10)  # scale traffic to intensity
            queue_lat = (rho / max(1 - rho, 0.01)) * router_lat if rho > 0 else 0
            total_lat = base_lat + queue_lat
            weight = matrix[src][dst]

            results[f"{src}->{dst}"] = {
                "hops": h,
                "base_lat": round(base_lat, 1),
                "queue_lat": round(queue_lat, 1),
                "total_lat": round(total_lat, 1),
                "weight": round(weight, 4),
            }
            total_weighted_lat += total_lat * weight
            total_weight += weight
            max_lat = max(max_lat, total_lat)

    return {
        "avg_latency": round(total_weighted_lat / max(total_weight, 1e-12), 2),
        "max_latency": round(max_lat, 1),
        "total_weight": round(total_weight, 4),
        "n_flows": len(results),
        "flows": results,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--anynet', required=True)
    parser.add_argument('--matrix', required=True)
    parser.add_argument('--out', default=None)
    args = parser.parse_args()

    n, adj = parse_anynet(args.anynet)
    matrix = np.loadtxt(args.matrix)
    if matrix.shape[0] < n:
        pad = np.zeros((n, n))
        pad[:matrix.shape[0], :matrix.shape[1]] = matrix
        matrix = pad

    result = tlm_estimate(adj, n, matrix)
    print(f"TLM Estimation: {result['n_flows']} flows, avg={result['avg_latency']} cyc, max={result['max_latency']} cyc")

    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2))
        print(f"Saved to {args.out}")


if __name__ == '__main__':
    main()
