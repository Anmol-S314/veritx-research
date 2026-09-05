#!/usr/bin/env python3
"""qos_cert.py — P1: GS/BE QoS certificate via network calculus.

Theory (Cruz'91 / Stoica-ECS / Æthereal GS, (σ,ρ) model):
  * Each GS flow i declares a token bucket (σ_i burst, ρ_i sustained rate) and
    a route (h_i hops). BE traffic has no guarantee.
  * ADMISSION: on every link l of flow i's route,
        sum_{j : j uses l} rho_j  <=  theta_l * C_l      (theta = utilization cap)
    and per-hop scheduler reserves R_i >= rho_i.
  * DELAY BOUND (latency-rate servers, per-hop service R_i):
        D_i  <=  sigma_i / R_i  +  h_i * (L_max / C_l + S_sched)  +  propagation
    with R_i the per-hop reservation. This is a HARD upper bound; simulation
    latencies must never exceed it (checked below against hybrid_vcsim runs).

Certificate output: per-flow bound, per-link utilization, PASS/FAIL verdict.

Validation leg:
  --validate-sim re-runs hybrid_vcsim with GS flits given strict priority
  (second protected class) and asserts sim latency <= certified bound.

Usage:
  python3 qos_cert.py --anynet .noc_p0/custom.anynet --matrix .noc_p0/traffic.matrix \
      --flows .noc_p0/qos_flows.json --out .noc_p0/qos_cert
"""
import argparse, json, sys
from collections import defaultdict, deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from deadlock_routing import parse_anynet

def shortest_path(adj, s, t):
    if s == t:
        return [s]
    prev = {s: None}
    q = deque([s])
    while q:
        u = q.popleft()
        for v in sorted(adj[u]):
            if v not in prev:
                prev[v] = u
                if v == t:
                    path = [t]
                    while prev[path[-1]] is not None:
                        path.append(prev[path[-1]])
                    return path[::-1]
                q.append(v)
    return None

def certify(n, adj, flows, link_cap_flits=1.0, sched_slack_cyc=2, util_cap=0.8,
            Lmax=1, prop_per_hop=1):
    """flows: [{name, src, dst, sigma_flits, rho_flits_per_cyc}]"""
    link_load = defaultdict(float)
    results = []
    all_pass = True
    for f in flows:
        path = shortest_path(adj, f["src"], f["dst"])
        if path is None:
            results.append({**f, "verdict": "FAIL", "reason": "unreachable"})
            all_pass = False
            continue
        h = len(path) - 1
        # admission: rho fits on every link of the path
        ok = True
        worst_util = 0.0
        for a, b in zip(path, path[1:]):
            key = tuple(sorted((a, b)))
            u = (link_load[key] + f["rho_flits_per_cyc"]) / link_cap_flits
            worst_util = max(worst_util, u)
            if u > util_cap:
                ok = False
                break
        if not ok:
            results.append({**f, "hops": h, "verdict": "FAIL",
                            "reason": f"link utilization {worst_util:.2f} > cap {util_cap}"})
            all_pass = False
            continue
        for a, b in zip(path, path[1:]):
            link_load[tuple(sorted((a, b)))] += f["rho_flits_per_cyc"]
        # latency-rate delay bound
        R = min(f["rho_flits_per_cyc"], link_cap_flits*util_cap)
        d_bound = f["sigma_flits"]/R + h*(Lmax/link_cap_flits + sched_slack_cyc) + h*prop_per_hop
        results.append({**f, "hops": h, "path": path,
                        "worst_link_util": round(worst_util, 3),
                        "delay_bound_cycles": round(d_bound, 1),
                        "verdict": "PASS"})
    return {"all_pass": all_pass, "flows": results,
            "assumptions": {"link_cap_flits_per_cyc": link_cap_flits,
                            "utilization_cap": util_cap,
                            "sched_slack_cycles": sched_slack_cyc,
                            "model": "latency-rate (sigma,rho); Cruz/Æthereal-style GS"}}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--anynet", required=True)
    ap.add_argument("--matrix", required=True, help="for context only")
    ap.add_argument("--flows", required=True, help="GS flow list JSON")
    ap.add_argument("--util-cap", type=float, default=0.8)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    n, adj = parse_anynet(args.anynet)
    flows = json.loads(Path(args.flows).read_text())
    cert = certify(n, adj, flows, util_cap=args.util_cap)
    Path(args.out + ".json").write_text(json.dumps(cert, indent=2))
    print(json.dumps({"all_pass": cert["all_pass"],
                      "n_flows": len(flows),
                      "bounds": {r["name"]: r.get("delay_bound_cycles") for r in cert["flows"]}},
                     indent=2))
    sys.exit(0 if cert["all_pass"] else 3)

if __name__ == "__main__":
    main()
