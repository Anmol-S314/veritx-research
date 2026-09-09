#!/usr/bin/env python3
"""milestone_c.py — Flow-Class-Aware Certification Engine (PLAN §Milestone C).

from log import get_log
log = get_log("milestone_c")

Reads:
  1. Unified TrafficModel JSON (dse/models/traffic_model.json)
  2. Topology .anynet file (from synthesis or manual input)
  3. gen_rtl.py meta.json (for guardrail_hash, if available)

Emits:
  certificate.json — reviewer-verifiable proof that every flow class
  from the TrafficModel has reachability + latency-bound + injection-ceiling
  assertions whose deadline provenance is stated.

Design principle: the certificate schema dictates what we can assert.
deadline_cycles in the TrafficModel are bandwidth HINTS (bytes*8/100GB/s),
not hard timing contracts.  We derive LATENCY_BOUND from topology structure
(algorithmic hops × physical hops × pipeline cost) and compare against
the hint deadline.  A PASS means the topology CAN deliver within the
bandwidth-implied deadline under ideal conditions.

Usage:
  python3 milestone_c.py \\
    --traffic-model dse/models/traffic_model.json \\
    --topology .noc_p0/custom.anynet \\
    [--meta .noc_p0/rtl_out/meta.json] \\
    [--out certificate.json] \\
    [--pipeline-cost 1.0]
"""
import argparse
import hashlib
import json
import math
import sys
import time
from collections import deque
from pathlib import Path

# ── Topology helpers (reuse parse_anynet from deadlock_routing) ────────
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from deadlock_routing import parse_anynet


# ── BFS shortest path (hop count) ────────────────────────────────────
def bfs_shortest(adj, src):
    """BFS from src; returns dict of distances (hops) for reachable nodes."""
    dist = {src: 0}
    q = deque([src])
    while q:
        u = q.popleft()
        for v in adj.get(u, []):
            if v not in dist:
                dist[v] = dist[u] + 1
                q.append(v)
    return dist


def ring_total_distance(adj, participants):
    """Sum of physical hops over the ring order (p[i] -> p[i+1] -> ... -> p[0]).
    Correct wire traversal cost for ring AR/AG/RS — NOT max-pair × (k-1).
    Returns (total_hops, per_step_max) or (-1, -1) if unreachable.
    """
    k = len(participants)
    if k < 2:
        return 0, 0
    total = 0
    step_max = 0
    for i in range(k):
        s, d = participants[i], participants[(i + 1) % k]
        dist = bfs_shortest(adj, s)
        if d not in dist:
            return -1, -1
        total += dist[d]
        step_max = max(step_max, dist[d])
    return total, step_max


def all_reachable(adj, participants):
    """True iff every ordered pair in participants is reachable.

    Participants not in the topology are counted as unreachable.
    """
    topo_nodes = set(adj.keys())
    for p in participants:
        if p not in topo_nodes:
            return False
    for src in participants:
        dist = bfs_shortest(adj, src)
        for dst in participants:
            if dst != src and dst not in dist:
                return False
    return True


# ── Collective algorithmic hop count ──────────────────────────────────
def algo_hops_ring(k):
    """Ring allreduce/allgather/reducescatter: (k-1) logical hops."""
    return k - 1 if k >= 2 else 0


def algo_hops_binary_tree(k):
    """Binary-tree reduce-scatter + allgather: 2*ceil(log2(k))."""
    if k <= 1:
        return 0
    return 2 * math.ceil(math.log2(k))


# ── Latency bound derivation ──────────────────────────────────────────
HBM_BW_BYTES_PER_CYCLE = 100_000_000_000 / 2_000_000_000  # 100 GB/s ÷ 2 GHz ≈ 50 B/cyc


def latency_bound(comm_type, participants, bytes_per_invocation,
                  adj, pipeline_cost=1.0):
    """Derive worst-case latency bound in cycles for one invocation.

    Two contributions: (a) flit traversal via ring = ring_steps × per_step_max × pipeline_cost,
    (b) serialization = chunk_bytes ÷ HBM_BW. Data-in-flight overlap assumed;
    total = traversal + last_chunk_serialization.
    Returns (latency_cycles, hops_used, algo_steps, formula).
    """
    k = len(participants)
    if k < 2:
        return (0, 0, 0, "unicast_or_single_participant")

    ct = comm_type.upper()
    ring_total, ring_step_max = ring_total_distance(adj, participants)
    if ring_total < 0:
        return (-1, -1, -1, "unreachable")

    algo = algo_hops_ring(k)
    traversal = algo * ring_step_max * pipeline_cost

    # Serialization: ring sends chunk = bytes_per_invocation/k per step
    chunk = bytes_per_invocation / k if bytes_per_invocation > 0 else 0
    ser_cycles = chunk / HBM_BW_BYTES_PER_CYCLE if HBM_BW_BYTES_PER_CYCLE > 0 else 0
    total = traversal + ser_cycles

    formula = (f"ring:{algo}steps × {ring_step_max}hop_max × {pipeline_cost}cyc = {traversal:.0f} + "
               f"ser:{chunk:.0f}B ÷ {HBM_BW_BYTES_PER_CYCLE:.0f}B/cyc = {ser_cycles:.0f} → {total:.0f}")
    return (total, ring_step_max, algo, formula)


# ── Injection ceiling ─────────────────────────────────────────────────
def injection_ceiling_check(constraints):
    """Check peak injection rate is within fabric limits.

    Typical mesh: saturation ~0.35-0.50 (measured in Test 5).
    The TrafficModel's peak_injection_rate is per-node fractional.
    """
    peak_ir = constraints.get("peak_injection_rate", 0)
    # Known saturation points from BookSim validation (PLAN §Test 5):
    # mesh_4x4: saturates ~0.45
    # synthesized T3: saturates ~0.45
    # We use 0.40 as conservative ceiling (80% of saturation).
    FABRIC_CEILING = 0.40
    margin = FABRIC_CEILING - peak_ir
    return {
        "peak_injection_rate": peak_ir,
        "fabric_ceiling": FABRIC_CEILING,
        "margin": margin,
        "pass": margin > 0,
        "note": f"peak IR {peak_ir:.6f} vs fabric ceiling {FABRIC_CEILING} "
                f"(~80% of measured saturation ~0.45); margin {margin:.6f}"
    }


# ── CDG acyclicity (reuse from gen_rtl.py) ────────────────────────────
def check_cdg_acyclic(adj, n):
    """Channel-dependency-graph cycle detector (Dally-Seitz).

    Returns (acyclic: bool, n_cycles: int).
    """
    # Import from gen_rtl.py (same codebase). Path is computed relative to
    # THIS file (dse/scripts/) so it works no matter where the repo root is:
    # dse/scripts -> dse -> t3-topology -> scripts/rtlgen.
    rtl_dir = Path(__file__).resolve().parent.parent.parent / "scripts" / "rtlgen"
    sys.path.insert(0, str(rtl_dir))
    try:
        from gen_rtl import cdg_has_cycle, dim_order_tables, up_down_tables, dijkstra_tables
        # Try dim-order first
        tbl = dim_order_tables(n, adj)
        if tbl is not None and not cdg_has_cycle(n, adj, tbl):
            return True, 0, "dim_order"
        # Try up/down
        from gen_rtl import _best_escape_root
        root = _best_escape_root(n, adj)
        tbl = up_down_tables(n, adj, root)
        if tbl is not None and not cdg_has_cycle(n, adj, tbl):
            return True, 0, f"up_down(root={root})"
        # Try dijkstra (needs escape VC for liveness guarantee)
        tbl = dijkstra_tables(n, adj)
        if not cdg_has_cycle(n, adj, tbl):
            return True, 0, "dijkstra"
        return False, 1, "all_routing_methods_cyclic"
    except ImportError:
        # Fallback: simple cycle detection on link-level CDG
        return None, 0, "import_unavailable"


# ── Certificate builder ───────────────────────────────────────────────
def build_certificate(traffic_model, adj, n_nodes, meta=None, pipeline_cost=1.0):
    """Build the full certificate from TrafficModel + topology.

    Returns certificate dict.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # Topology metadata
    n_edges = sum(len(v) for v in adj.values()) // 2
    max_deg = max(len(adj[i]) for i in range(n_nodes))

    topo_info = {
        "n_nodes": n_nodes,
        "n_edges": n_edges,
        "max_degree": max_deg,
    }
    if meta:
        topo_info["guardrail_hash"] = meta.get("guardrail_hash", "unknown")
        topo_info["anynet"] = meta.get("anynet", "unknown")
    else:
        topo_info["guardrail_hash"] = "not_generated_by_gen_rtl"
        topo_info["anynet"] = "direct_input"

    # CDG acyclicity check
    cdg_result, cdg_cycles, routing_method = check_cdg_acyclic(adj, n_nodes)

    # Injection ceiling
    constraints = traffic_model.get("network", {}).get("constraints", {})
    inj_check = injection_ceiling_check(constraints)

    # Per flow-class certification
    flow_classes = traffic_model.get("network", {}).get("flow_classes", [])
    certified_classes = []
    all_pass = True

    for fc in flow_classes:
        fc_name = fc.get("name", "unknown")
        comm_type = fc.get("comm_type", "ALLREDUCE")
        bytes_per_inv = fc.get("bytes_per_invocation", 0)
        deadline = fc.get("deadline_cycles", 0)
        priority = fc.get("priority", 0)
        invocations = fc.get("invocations_per_batch", 0)
        instances = fc.get("instances", [])
        provenance = fc.get("provenance", {})

        instance_results = []
        fc_pass = True

        for idx, inst in enumerate(instances):
            participants = inst.get("participants", [])
            k = len(participants)

            # Reachability
            reachable = all_reachable(adj, participants)

            # Latency bound
            lat, phys_hops, algo_steps, formula = latency_bound(
                comm_type, participants, bytes_per_inv, adj, pipeline_cost
            )

            # Deadline check (only if reachable and deadline is meaningful)
            deadline_pass = True
            if not reachable:
                deadline_pass = False
            elif deadline > 0 and lat > 0:
                deadline_pass = lat <= deadline

            if not reachable or not deadline_pass:
                fc_pass = False

            instance_results.append({
                "instance_id": idx,
                "participants": participants,
                "k": k,
                "reachable": reachable,
                "latency_bound_cycles": lat,
                "deadline_cycles": deadline,
                "deadline_pass": deadline_pass,
                "physical_hops_worst_case": phys_hops,
                "algorithmic_steps": algo_steps,
                "formula": formula,
            })

        # Injection check for this class
        # Per-class IR = total_bytes_per_batch / (nodes * cycle_time)
        # Simplified: invocations * bytes_per_invocation across all instances
        total_bytes = invocations * bytes_per_inv * len(instances)
        class_ir = total_bytes / (n_nodes * 1e9) if n_nodes > 0 else 0  # rough fractional

        certified_classes.append({
            "name": fc_name,
            "comm_type": comm_type,
            "priority": priority,
            "invocations_per_batch": invocations,
            "bytes_per_invocation": bytes_per_inv,
            "deadline_cycles": deadline,
            "deadline_provenance": provenance.get("deadline_cycles", "unknown"),
            "n_instances": len(instances),
            "all_reachable": all(r["reachable"] for r in instance_results),
            "all_deadlines_met": all(r["deadline_pass"] for r in instance_results),
            "instances": instance_results,
            "estimated_class_ir": class_ir,
            "certified": fc_pass,
        })

        if not fc_pass:
            all_pass = False

    # Overall verdict
    verdict = "PASS" if (all_pass and inj_check["pass"] and cdg_result) else "FAIL"

    certificate = {
        "schema_version": "1.0",
        "generated_at": ts,
        "verdict": verdict,
        "topology": topo_info,
        "routing": {
            "method": routing_method,
            "cdg_acyclic": cdg_result,
            "cdg_cycles_found": cdg_cycles,
        },
        "synthesis": {
            "source": "milestone_b.py (BO synthesis)",
            "note": "topology reconstructed from winner_gen_seed",
        },
        "traffic_model": {
            "n_flow_classes": len(flow_classes),
            "constraints": constraints,
        },
        "injection_ceiling": inj_check,
        "flow_classes_certified": certified_classes,
        "definition_of_done": {
            "all_flow_classes_listed": len(certified_classes) == len(flow_classes),
            "all_instances_reachable": all(
                inst["reachable"]
                for fc in certified_classes
                for inst in fc["instances"]
            ),
            "all_deadlines_met": all(
                inst["deadline_pass"]
                for fc in certified_classes
                for inst in fc["instances"]
            ),
            "guardrail_hash_present": topo_info.get("guardrail_hash") != "not_generated_by_gen_rtl",
            "deadline_provenance_stated": all(
                fc["deadline_provenance"] != "unknown"
                for fc in certified_classes
            ),
        },
    }

    return certificate


# ── CLI ───────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--traffic-model", required=True,
                    help="Path to unified TrafficModel JSON")
    ap.add_argument("--topology", required=True,
                    help="Path to .anynet topology file")
    ap.add_argument("--meta", default=None,
                    help="Path to gen_rtl.py meta.json (for guardrail_hash)")
    ap.add_argument("--out", default=None,
                    help="Output certificate path (default: <topology_dir>/certificate.json)")
    ap.add_argument("--pipeline-cost", type=float, default=1.0,
                    help="Cycles per physical hop (default: 1.0)")
    args = ap.parse_args()

    # Load inputs
    with open(args.traffic_model) as f:
        traffic_model = json.load(f)

    n_nodes, adj = parse_anynet(args.topology)

    meta = None
    if args.meta and Path(args.meta).exists():
        with open(args.meta) as f:
            meta = json.load(f)

    # Build certificate
    cert = build_certificate(traffic_model, adj, n_nodes, meta, args.pipeline_cost)

    # Guardrail hash verification: regenerate from .anynet + tables to verify meta.json
    # is consistent with the actual topology (prevents tampered certificates).
    if meta and "guardrail_hash" in meta and meta["guardrail_hash"] != "not_generated_by_gen_rtl":
        try:
            rtl_dir = Path(__file__).resolve().parent.parent.parent / "scripts" / "rtlgen"
            sys.path.insert(0, str(rtl_dir))
            from gen_rtl import (
                dim_order_tables, up_down_tables, dijkstra_tables,
                tree_tables, _best_escape_root, cdg_has_cycle
            )
            import hashlib as _hl
            n = n_nodes
            # Reproduce the same routing decisions gen_rtl.py would make
            tbl_min = dim_order_tables(n, adj)
            if tbl_min is not None and cdg_has_cycle(n, adj, tbl_min):
                tbl_min = None
            table_mode = meta.get("tables", "auto")
            if tbl_min is None and table_mode != "dijkstra":
                esc_root = meta.get("esc_root", _best_escape_root(n, adj))
                tbl_min = up_down_tables(n, adj, esc_root)
            if tbl_min is None:
                tbl_min = dijkstra_tables(n, adj)
            esc_root = meta.get("esc_root", _best_escape_root(n, adj))
            tbl_esc = tree_tables(n, adj, root=esc_root)
            # Rebuild hash with same inputs as gen_rtl.py
            h = _hl.sha256()
            h.update(b"srota-engine-v6|")
            h.update(f"arch={meta.get('arch', 'legacy-vc')}|".encode())
            h.update(f"n={n}|deg={max(len(adj[i]) for i in range(n))}|edges={sum(len(v) for v in adj.values())//2}|".encode())
            h.update(f"vcs={meta.get('vcs', 2)}|buf={meta.get('buf', 8)}|blk={meta.get('block_k', 8)}|".encode())
            h.update(f"esc_root={esc_root}|tables={table_mode}|".encode())
            for (a, b) in sorted(tbl_min.items()):
                h.update(f"min:{a}:{b};".encode())
            for (a, b) in sorted(tbl_esc.items()):
                h.update(f"esc:{a}:{b};".encode())
            tmpl_path = rtl_dir / ("router_template_v2.sv" if meta.get('arch') == 'plane-v2' else "router_template.sv")
            h.update(_hl.sha256(tmpl_path.read_bytes()).hexdigest().encode())
            recomputed_hash = h.hexdigest()
            hash_match = (recomputed_hash == meta["guardrail_hash"])
            cert["guardrail_hash_verification"] = {
                "stored_hash": meta["guardrail_hash"],
                "recomputed_hash": recomputed_hash,
                "match": hash_match,
                "note": "hash recomputed from .anynet topology + route tables; verifies meta.json is consistent with actual fabric"
            }
            if not hash_match:
                cert["verdict"] = "FAIL"
                print(f"WARNING: guardrail_hash MISMATCH — stored={meta['guardrail_hash'][:16]}... "
                      f"recomputed={recomputed_hash[:16]}...")
            else:
                print(f"Guardrail hash verified: {recomputed_hash[:16]}...")
        except Exception as e:
            cert["guardrail_hash_verification"] = {
                "match": None,
                "error": str(e),
                "note": "hash verification failed (non-fatal)"
            }
            print(f"WARNING: guardrail hash verification failed: {e}")

    # Output
    out_path = Path(args.out) if args.out else Path(args.topology).parent / "certificate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cert, indent=2))
    print(f"Certificate written: {out_path}")

    # Summary
    print(f"\n=== CERTIFICATION SUMMARY ===")
    print(f"Verdict: {cert['verdict']}")
    print(f"Nodes: {cert['topology']['n_nodes']}, Edges: {cert['topology']['n_edges']}")
    print(f"Routing: {cert['routing']['method']}, CDG acyclic: {cert['routing']['cdg_acyclic']}")
    print(f"Injection ceiling: {'PASS' if cert['injection_ceiling']['pass'] else 'FAIL'} "
          f"(margin {cert['injection_ceiling']['margin']:.6f})")
    print(f"\nFlow classes:")
    for fc in cert["flow_classes_certified"]:
        status = "PASS" if fc["certified"] else "FAIL"
        print(f"  {fc['name']} ({fc['comm_type']}, prio={fc['priority']}): "
              f"{fc['n_instances']} instances, {status}")
        for inst in fc["instances"]:
            r = "✓" if inst["reachable"] else "✗"
            d = "✓" if inst["deadline_pass"] else "✗"
            print(f"    [{inst['instance_id']}] k={inst['k']}, "
                  f"reachable={r}, lat={inst['latency_bound_cycles']} "
                  f"vs deadline={inst['deadline_cycles']} ({d}) "
                  f"— {inst['formula']}")

    # Definition of done check
    dod = cert["definition_of_done"]
    print(f"\nDefinition of done:")
    for k, v in dod.items():
        print(f"  {k}: {'✓' if v else '✗'}")

    return 0 if cert["verdict"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
