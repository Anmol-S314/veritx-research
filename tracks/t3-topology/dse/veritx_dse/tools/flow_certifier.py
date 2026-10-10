#!/usr/bin/env python3
"""flow_certifier.py — Flow-Class-Aware Certification Engine.

Rationale: docs/decisions/modules/tools.md
"""
import argparse
import hashlib
import json
import math
import sys
import time
from collections import deque
from pathlib import Path

# Layout: <track>/dse/veritx_dse/tools/flow_certifier.py
_HERE = Path(__file__).resolve().parent              # .../dse/veritx_dse/tools
_TRACK_ROOT = _HERE.parents[2]                       # .../tracks/t3-topology
_SEAM_DIR = _TRACK_ROOT / "scripts" / "rtlgen"       # gen_rtl.py (the seam)
_EMITTER_DIR = _TRACK_ROOT / "rtl" / "mot_htree"     # router_template*.sv (the emitter's copy)

sys.path.insert(0, str(_HERE))
from deadlock_routing import parse_anynet

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

def algo_hops_ring(k):
    """Ring allreduce/allgather/reducescatter: (k-1) logical hops."""
    return k - 1 if k >= 2 else 0

def algo_hops_binary_tree(k):
    """Binary-tree reduce-scatter + allgather: 2*ceil(log2(k))."""
    if k <= 1:
        return 0
    return 2 * math.ceil(math.log2(k))

HBM_BW_BYTES_PER_CYCLE = 100_000_000_000 / 2_000_000_000

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

    chunk = bytes_per_invocation / k if bytes_per_invocation > 0 else 0
    ser_cycles = chunk / HBM_BW_BYTES_PER_CYCLE if HBM_BW_BYTES_PER_CYCLE > 0 else 0
    total = traversal + ser_cycles

    formula = (f"ring:{algo}steps × {ring_step_max}hop_max × {pipeline_cost}cyc = {traversal:.0f} + "
               f"ser:{chunk:.0f}B ÷ {HBM_BW_BYTES_PER_CYCLE:.0f}B/cyc = {ser_cycles:.0f} → {total:.0f}")
    return (total, ring_step_max, algo, formula)

def injection_ceiling_check(constraints):
    """Check peak injection rate is within fabric limits.

    Typical mesh: saturation ~0.35-0.50 (measured in Test 5).
    The TrafficModel's peak_injection_rate is per-node fractional.
    """
    peak_ir = constraints.get("peak_injection_rate", 0)
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

def check_cdg_acyclic(adj, n):
    """Channel-dependency-graph cycle detector (Dally-Seitz).

    Returns (acyclic: bool, n_cycles: int).
    """
    rtl_dir = Path(__file__).resolve().parent.parent.parent.parent / "scripts" / "rtlgen"
    sys.path.insert(0, str(rtl_dir))
    try:
        from gen_rtl import cdg_has_cycle, dim_order_tables, up_down_tables, dijkstra_tables
        tbl = dim_order_tables(n, adj)
        if tbl is not None and not cdg_has_cycle(n, adj, tbl):
            return True, 0, "dim_order"
        from gen_rtl import _best_escape_root
        root = _best_escape_root(n, adj)
        tbl = up_down_tables(n, adj, root)
        if tbl is not None and not cdg_has_cycle(n, adj, tbl):
            return True, 0, f"up_down(root={root})"
        tbl = dijkstra_tables(n, adj)
        if not cdg_has_cycle(n, adj, tbl):
            return True, 0, "dijkstra"
        return False, 1, "all_routing_methods_cyclic"
    except ImportError:
        return None, 0, "import_unavailable"

def build_certificate(traffic_model, adj, n_nodes, meta=None, pipeline_cost=1.0):
    """Build the full certificate from TrafficModel + topology.

    Returns certificate dict.
    """
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

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

    cdg_result, cdg_cycles, routing_method = check_cdg_acyclic(adj, n_nodes)

    constraints = traffic_model.get("network", {}).get("constraints", {})
    inj_check = injection_ceiling_check(constraints)

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

            reachable = all_reachable(adj, participants)

            lat, phys_hops, algo_steps, formula = latency_bound(
                comm_type, participants, bytes_per_inv, adj, pipeline_cost
            )

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

        total_bytes = invocations * bytes_per_inv * len(instances)
        class_ir = total_bytes / (n_nodes * 1e9) if n_nodes > 0 else 0

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

def verify_guardrail_hash(cert, meta, adj, n_nodes, emitter_dir=None):
    """Recompute ``meta["guardrail_hash"]`` from the ACTUAL emitter template.

    The emitter (``<track>/rtl/mot_htree/gen_rtl_htree.py``) hashes the router
    template it copies into the build, so this check must hash the emitter's
    own copy -- not a file under the seam dir, where no template exists.

    Fails closed: a missing template (or any inability to recompute) forces
    ``cert["verdict"] = "FAIL"`` and records the miss, instead of degrading to
    a warning a reader could mistake for a verified hash.  A successful run
    never raises the verdict; it only lowers it on mismatch.

    Returns True iff the recomputed hash matches ``meta["guardrail_hash"]``.
    """
    if emitter_dir is None:
        emitter_dir = _EMITTER_DIR
    arch = meta.get("arch")
    tmpl = meta.get("router_template")
    templates = {
        "legacy-vc": "router_template.sv",
        "plane-v2": "router_template_v2.sv",
    }
    valid_templates = {"router_template.sv", "router_template_v2.sv",
                       "router_htree.sv"}
    if (arch not in templates or tmpl not in valid_templates or
            (tmpl != "router_htree.sv" and templates[arch] != tmpl)):
        error = ("missing or unsupported arch/router_template metadata: "
                 f"arch={arch!r}, router_template={tmpl!r}")
        cert["verdict"] = "FAIL"
        cert["guardrail_hash_verification"] = {
            "stored_hash": meta.get("guardrail_hash"),
            "recomputed_hash": None,
            "match": None,
            "error": error,
            "note": "guardrail hash NOT verified — fail-closed verdict",
        }
        print(f"FAIL: guardrail hash not verified: {error}")
        return False
    tmpl_path = Path(emitter_dir) / tmpl
    if not tmpl_path.is_file():
        cert["verdict"] = "FAIL"
        cert["guardrail_hash_verification"] = {
            "stored_hash": meta.get("guardrail_hash"),
            "recomputed_hash": None,
            "match": None,
            "error": f"router template missing: {tmpl_path}",
            "note": "guardrail hash NOT verified — emitter template absent; "
                    "fail-closed verdict",
        }
        print(f"FAIL: guardrail hash not verified — emitter template missing: {tmpl_path}")
        return False

    try:
        sys.path.insert(0, str(_SEAM_DIR))
        from gen_rtl import (
            dim_order_tables, up_down_tables, dijkstra_tables,
            tree_tables, _best_escape_root, cdg_has_cycle
        )
        n = n_nodes
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
        h = hashlib.sha256()
        h.update(b"srota-engine-v6|")
        h.update(f"arch={meta.get('arch', 'legacy-vc')}|".encode())
        h.update(f"n={n}|deg={max(len(adj[i]) for i in range(n))}|edges={sum(len(v) for v in adj.values())//2}|".encode())
        h.update(f"vcs={meta.get('vcs', 2)}|buf={meta.get('buf', 8)}|blk={meta.get('block_k', 8)}|".encode())
        h.update(f"esc_root={esc_root}|tables={table_mode}|".encode())
        for (a, b) in sorted(tbl_min.items()):
            h.update(f"min:{a}:{b};".encode())
        for (a, b) in sorted(tbl_esc.items()):
            h.update(f"esc:{a}:{b};".encode())
        h.update(hashlib.sha256(tmpl_path.read_bytes()).hexdigest().encode())
        recomputed_hash = h.hexdigest()
    except Exception as e:
        cert["verdict"] = "FAIL"
        cert["guardrail_hash_verification"] = {
            "stored_hash": meta.get("guardrail_hash"),
            "recomputed_hash": None,
            "match": None,
            "error": str(e),
            "note": "guardrail hash NOT verified — fail-closed verdict",
        }
        print(f"FAIL: guardrail hash not verified: {e}")
        return False

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
    return hash_match


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

    with open(args.traffic_model) as f:
        traffic_model = json.load(f)

    n_nodes, adj = parse_anynet(args.topology)

    meta = None
    if args.meta and Path(args.meta).exists():
        with open(args.meta) as f:
            meta = json.load(f)

    cert = build_certificate(traffic_model, adj, n_nodes, meta, args.pipeline_cost)

    if meta and "guardrail_hash" in meta and meta["guardrail_hash"] != "not_generated_by_gen_rtl":
        verify_guardrail_hash(cert, meta, adj, n_nodes)

    out_path = Path(args.out) if args.out else Path(args.topology).parent / "certificate.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(cert, indent=2))
    print(f"Certificate written: {out_path}")

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

    dod = cert["definition_of_done"]
    print(f"\nDefinition of done:")
    for k, v in dod.items():
        print(f"  {k}: {'✓' if v else '✗'}")

    return 0 if cert["verdict"] == "PASS" else 1

if __name__ == "__main__":
    sys.exit(main())
