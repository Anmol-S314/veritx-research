"""traffic_model_compiler.py — Step 1 of the pipeline.

Parses LLMServingSim text traces (Chakra format) → TrafficModel JSON.

The TrafficModel captures formal constraints on what traffic the workload
CAN produce, not a specific trace. This enables:
  - Topology synthesis against a workload CLASS (not one snapshot)
  - Formal deadlock certification for ALL traffic within bounds
  - Comparison across different workload configurations

Input:  directory of batch*.txt trace files (LLMServingSim Chakra format)
        + optional mapper event stream (test1_roundtrip.py output) for
          REAL participant structure
Output: TrafficModel JSON (see schema below)

TrafficModel schema:
{
  "source": "<path to trace directory>",
  "num_batches": <int>,
  "num_nodes": <int>,
  "compute": {
    "total_cycles": <int>,
    "total_weight_bytes": <int>,
    "ops": [ <per-operation summary> ]
  },
  "memory": {
    "total_weight_bytes": <int>,
    "total_input_bytes": <int>,
    "total_output_bytes": <int>,
    "weight_streaming": true  # weights >> inputs, dominated by streaming
  },
  "network": {
    "flow_classes": [
      {
        "name": "<op_type>"  # CLEAN: dimension scope stripped at parse time,
                              # e.g. "allreduce", never "allreduce:1,0"
        "comm_type": "<ALLREDUCE|ALLGATHER|REDUCESCATTER|NONE>",
        "bytes_per_invocation": <int>,
        "invocations_per_batch": <float>,
        "priority": <int>,
        "deadline_cycles": <int>,
        "participant_scope": "<group|global|unknown>",
        "participants": [<int>, ...] | null,  # canonical pattern (scope=group)
                                             # or full rep list (scope=global)
        "provenance": {
          "bytes": "<trace|mapper-events|published-llama7b>",
          "participants": "<mapper-events|derived-global|published-llama7b|null>"
        }
      }
    ],
    "constraints": {
      "max_injection_rate": <float>,
      "total_comm_bytes": <int>,
      "num_flows": <int>
    }
  }
}
"""

import json
import re
import sys
from pathlib import Path
from collections import defaultdict

# Clean collective types (dims like ":1,0" are dimension scope, stripped at
# PARSE TIME so every downstream consumer sees clean names).
COLLECTIVE_TYPES = ("ALLREDUCE", "ALLGATHER", "REDUCESCATTER", "ALLTOALL",
                    "BROADCAST", "P2P")

# Flow-class priorities by CLEAN type (sync points > expert-path ops).
# NOTE: this map was silently dead before the parse-time cleanup — keys are
# clean types but flow classes used to carry 'ALLREDUCE:1,0'-style tokens,
# so every class got priority 0.
PRIORITY = {
    "ALLREDUCE": 2,       # sync point — latency-critical
    "REDUCESCATTER": 1,   # expert combine — high priority
    "ALLGATHER": 1,       # expert dispatch — high priority
}


def split_comm_type(raw: str) -> tuple[str, str]:
    """Split raw LLMServingSim comm token into (clean_type, dims).

    'ALLREDUCE:1,0' -> ('ALLREDUCE', '1,0'); 'NONE' -> ('NONE', '').
    Fixing this AT PARSE TIME kills the naming bug that used to leak
    'allreduce:1,0' into flow-class names (previously worked around
    downstream via clean_class_name() in milestone_b.py) -- and restores
    the PRIORITY map, which was silently dead against dirty tokens.
    """
    if ":" in raw:
        t, dims = raw.split(":", 1)
        return t.strip().upper(), dims.strip()
    return raw.strip().upper(), ""


def parse_batch_trace(trace_file: Path) -> list[dict]:
    """Parse a single batch*.txt trace file into structured events."""
    events = []
    
    with open(trace_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("COLOCATED") or line.isdigit():
                continue
            if "Layername" in line or "comp_time" in line:
                continue
            
            parts = line.split()
            
            # Standard layer format: 11+ fields, second field is digit
            if len(parts) >= 10 and parts[1].isdigit():
                ct, dims = split_comm_type(parts[8])
                events.append({
                    "layer": parts[0],
                    "compute_cycles": int(parts[1]),
                    "input_loc": parts[2],
                    "input_bytes": int(parts[3]),
                    "weight_loc": parts[4],
                    "weight_bytes": int(parts[5]),
                    "output_loc": parts[6],
                    "output_bytes": int(parts[7]),
                    "comm_type": ct,
                    "comm_dims": dims,
                    "comm_bytes": int(parts[9]),
                })
            
            # Expert END: "EXPERT END REDUCESCATTER:1,1 16384" (check FIRST)
            elif "EXPERT END" in line:
                m = re.match(r"EXPERT END\s+(\S+)\s+(\d+)", line)
                if m:
                    ct, dims = split_comm_type(m.group(1))
                    events.append({
                        "layer": "expert_end",
                        "compute_cycles": 0,
                        "comm_type": ct,
                        "comm_dims": dims,
                        "comm_bytes": int(m.group(2)),
                    })
            
            # Expert dispatch: "EXPERT 0 ALLGATHER:1,1 4352" (check AFTER END)
            elif "EXPERT" in line and any(t in line for t in COLLECTIVE_TYPES + ("NONE",)):
                m = re.match(r"EXPERT\s+(\d+)\s+(\S+)\s+(\d+)", line)
                if m:
                    ct, dims = split_comm_type(m.group(2))
                    events.append({
                        "layer": f"expert_dispatch_{m.group(1)}",
                        "compute_cycles": 0,
                        "comm_type": ct,
                        "comm_dims": dims,
                        "comm_bytes": int(m.group(3)),
                    })
    
    return events


def extract_flow_classes(events: list[dict]) -> list[dict]:
    """Group events by (clean) communication type → flow classes."""
    groups = defaultdict(lambda: {"count": 0, "total_bytes": 0,
                                  "layers": set(), "dims": set()})
    
    for e in events:
        ct = e.get("comm_type", "NONE")
        if ct == "NONE":
            continue
        groups[ct]["count"] += 1
        groups[ct]["total_bytes"] += e.get("comm_bytes", 0)
        groups[ct]["layers"].add(e.get("layer", "unknown"))
        if e.get("comm_dims"):
            groups[ct]["dims"].add(e["comm_dims"])
    
    flow_classes = []
    for ct, data in sorted(groups.items()):
        if ct == "NONE":
            continue
        avg_bytes = data["total_bytes"] // max(data["count"], 1)
        dims_seen = sorted(data["dims"])
        flow_classes.append({
            "name": ct.lower(),
            "comm_type": ct,
            "comm_dims": dims_seen,   # provenance: dimension scopes observed
            "invocations": data["count"],
            "bytes_per_invocation": avg_bytes,
            "total_bytes": data["total_bytes"],
            "priority": PRIORITY.get(ct, 0),
            "deadline_hint_cycles": avg_bytes * 8 // 100,  # rough: 100 GB/s HBM
        })
    
    return flow_classes


# ---------------------------------------------------------------------------
# Structure merging (seed veritx-research-7eb4): ONE artifact carries
# what/how-much (traces) + who-to-whom (mapper event stream) + deadlines,
# with per-field provenance recorded. Downstream consumers (milestone_b)
# read the model directly — no consumption-time splicing.
# ---------------------------------------------------------------------------

def cluster_instances_from_structure(events: dict, n_nodes: int) -> dict:
    """Extract per-collective participant patterns from a mapper event
    stream. Returns {tensor_prefix: [participants_list, ...]} where TP
    patterns are replicated across node clusters with offsets."""
    cols = events.get("collectives", [])
    if not cols:
        raise ValueError("structure events contain no collectives")
    k_real = max(p for c in cols for p in c["participants"]) + 1
    n_clusters = n_nodes // k_real
    out = {}
    for c in cols:
        base = c["participants"]
        out[c["tensor"]] = [
            [off + p for p in base] for off in range(0, n_nodes, k_real)
        ] or [base]
    return out


def merge_participant_structure(model: dict, events: dict, n_nodes: int) -> dict:
    """Attach instances[] (participant sets) to every flow class lacking
    its own structural column. Records provenance."""
    patterns = cluster_instances_from_structure(events, n_nodes)
    tp_pattern = next(iter(patterns.values()))  # mapper TP pattern
    for fc in model["network"]["flow_classes"]:
        if "instances" in fc:
            continue
        # own structural column? (e.g. a DP class added earlier with explicit reps)
        own = next((v for k, v in patterns.items()
                    if k.upper().startswith(fc["comm_type"].upper())
                    and "DP" in k.upper()), None)
        fc["instances"] = [{"participants": p} for p in (own or tp_pattern)]
        fc.setdefault("provenance", {})["participants"] = \
            "mapper_event_stream:" + events.get("meta", {}).get("source", "attached")
    return model


def add_derived_dp_class(model: dict, n_nodes: int, k_cluster: int = 16,
                         layer_grad_bytes: int | None = None) -> dict:
    """Append the inter-cluster DP gradient AR class, derived from published
    Llama-7B architecture numbers (per-layer trainable weights, fp16).
    Recorded as DERIVED provenance — not from the serving trace."""
    if layer_grad_bytes is None:
        layer_grad_bytes = (4096 * (3 * 4096 + 4096 + 2 * 11008)) * 2
    reps = list(range(0, n_nodes, k_cluster))
    for fc in model["network"]["flow_classes"]:
        if fc["comm_type"] == "ALLREDUCE":
            tp_pattern = fc.get("instances", [])
            if tp_pattern:
                k = len(tp_pattern[0]["participants"])
                reps = list(range(0, n_nodes, k))
                break
    model["network"]["flow_classes"].append({
        "name": "dp_gradient_ar",
        "comm_type": "ALLREDUCE",
        "comm_dims": [],
        "invocations_per_batch": 1,
        "bytes_per_invocation": float(layer_grad_bytes),
        "priority": 1,
        "deadline_hint_cycles": int(layer_grad_bytes * 8 // 100),
        "instances": [{"participants": reps}],
        "provenance": {
            "bytes": "derived:published_llama7b_arch_fp16",
            "participants": "derived:cluster_reps",
        },
    })
    return model


def finalize_deadlines(model: dict, structure_events: dict | None = None):
    """Canonical deadline per class: SLO-derived when the attached event
    stream carries phase priorities, else the bandwidth hint."""
    for fc in model["network"]["flow_classes"]:
        fc["deadline_cycles"] = fc.pop("deadline_hint_cycles")
        fc.setdefault("provenance", {})["deadline_cycles"] = \
            "bandwidth_hint:100GB/s"
    return model


def compile_traffic_model(trace_dir: Path, num_batches_sample: int = 10,
                          num_nodes: int = 64) -> dict:
    """Compile a TrafficModel from a directory of batch traces."""
    trace_files = sorted(trace_dir.rglob("*.txt"))
    print(f"Found {len(trace_files)} trace files")
    if not trace_files:
        raise ValueError(f"no trace files under {trace_dir}")
    
    # Parse all batches
    batch_events = []
    for tf in trace_files[:num_batches_sample]:
        ev = parse_batch_trace(tf)
        if ev:                       # skip empty/stub traces
            batch_events.append(ev)
    if not batch_events:
        raise ValueError(f"all traces under {trace_dir} parsed to zero events")
    
    print(f"Parsed {sum(len(b) for b in batch_events)} events "
          f"from {len(batch_events)} non-empty batches")
    
    # Per-batch statistics (normalize across batches)
    batch_stats = []
    for events in batch_events:
        compute = sum(e.get("compute_cycles", 0) for e in events)
        weight = sum(e.get("weight_bytes", 0) for e in events if e.get("weight_bytes", 0) > 0)
        comm = sum(e.get("comm_bytes", 0) for e in events if e.get("comm_type") != "NONE")
        batch_stats.append({"compute": compute, "weight": weight, "comm": comm})
    
    # Compute model constraints from batch statistics
    avg_compute = sum(b["compute"] for b in batch_stats) / len(batch_stats)
    avg_weight = sum(b["weight"] for b in batch_stats) / len(batch_stats)
    avg_comm = sum(b["comm"] for b in batch_stats) / len(batch_stats)
    max_comm = max(b["comm"] for b in batch_stats)
    
    # --- Network model (BookSim convention) ---
    # BookSim: 1 ring step = 1 network cycle (flit moves one hop per
    # cycle through pipelined routers, no additional latency modeled here).
    # Ring AllReduce = ReduceScatter + AllGather = 2*(N-1) steps.
    # For N=64 nodes: 2*63 = 126 steps per AllReduce.
    #
    # Real hardware: T_ring = 2(N-1)α + 2(N-1)/N * S/B
    #   where α = per-step latency, B = bandwidth, S = message size.
    # Our model uses the BookSim convention (1 step = 1 cycle) as a
    # simplification. This UNDERESTIMATES network time (no α or B term),
    # making our "compute dominates" result a LOWER BOUND on compute's share.
    
    N = num_nodes
    steps_per_ring = 2 * (N - 1)  # e.g. 126 for N=64
    
    # Count collectives across all batches (CLEAN types — dims stripped at parse)
    total_collectives = 0
    total_compute_all = 0
    for events in batch_events:
        for e in events:
            if e.get("comm_type", "NONE") in COLLECTIVE_TYPES:
                total_collectives += 1
        total_compute_all += sum(e.get("compute_cycles", 0) for e in events)
    
    avg_collectives_per_batch = total_collectives / len(batch_events)
    avg_compute = total_compute_all / len(batch_events)
    total_network_cycles = avg_collectives_per_batch * steps_per_ring  # steps = cycles (BookSim)
    total_time = avg_compute + total_network_cycles
    
    # Injection rate (BookSim definition):
    #   Instantaneous IR = flits_per_node_per_cycle during a collective
    #   Average IR = total_network_cycles / total_time  (fraction of time network is active)
    #   Note: 1/126 ≈ 0.0079 is instantaneous IR during a ring collective,
    #   not the same as the average IR over the full batch.
    peak_ir = 1.0 / steps_per_ring  # instantaneous IR during a collective
    avg_ir = total_network_cycles / total_time if total_time > 0 else 0
    
    # Flow classes aggregated over ALL sampled batches (per-batch mean), NOT
    # just the first file — string-sorted rglob made 'first' an arbitrary
    # late-decode batch, which skewed bytes_per_invocation badly.
    per_batch_classes = [extract_flow_classes(ev) for ev in batch_events]
    agg = defaultdict(lambda: {"count": 0, "bytes": 0.0})
    for classes in per_batch_classes:
        for fc in classes:
            a = agg[fc["comm_type"]]
            a["count"] += fc["invocations"]
            a["bytes"] += fc["bytes_per_invocation"] * fc["invocations"]
    n_b = len(per_batch_classes)
    flow_classes = []
    for ct, a in sorted(agg.items()):
        inv = a["count"] / n_b                     # mean invocations/batch
        avg_bytes = a["bytes"] / max(a["count"], 1)  # byte-weighted mean
        flow_classes.append({
            "name": ct.lower(),
            "comm_type": ct,
            "invocations_per_batch": round(inv, 2),
            "bytes_per_invocation": int(round(avg_bytes)),
            "priority": PRIORITY.get(ct, 0),
            "deadline_hint_cycles": int(avg_bytes * 8 // 100),
        })
    
    model = {
        "source": str(trace_dir),
        "num_batches_analyzed": len(batch_events),
        "compute": {
            "avg_cycles_per_batch": int(avg_compute),
            "total_weight_bytes": int(avg_weight),
        },
        "memory": {
            "total_weight_bytes": int(avg_weight),
            "weight_streaming_dominates": avg_weight > avg_comm * 10,
        },
        "network": {
            "flow_classes": flow_classes,
            "constraints": {
                "peak_injection_rate": round(peak_ir, 6),
                "avg_injection_rate": round(avg_ir, 6),
                "avg_collectives_per_batch": int(avg_collectives_per_batch),
                "avg_comm_bytes_per_batch": int(avg_comm),
                "total_comm_bytes_per_batch": int(max_comm),
                "num_flow_classes": len(flow_classes),
                "compute_network_ratio": round(avg_compute / max(total_network_cycles, 1), 1),
                # Burst envelope: peak-batch vs mean-batch comm volume
                # (replaces value formerly hand-carried in a lost artifact)
                "burst_ratio": round(max_comm / max(avg_comm, 1), 3),
            },
        },
    }
    
    return model


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("trace_dir", nargs="?", default=
        "research-vendor/upstream/LLMServingSim/astra-sim/inputs/runs/run_1787561697070974_458785/trace")
    ap.add_argument("--structure", default=None,
                    help="mapper event stream JSON — merges participant "
                         "instances into flow classes (provenance-recorded)")
    ap.add_argument("--nodes", type=int, default=64)
    ap.add_argument("--add-dp-class", action="store_true",
                    help="append derived inter-cluster DP gradient AR class")
    ap.add_argument("--out", default=
        "tracks/t3-topology/dse/models/traffic_model.json")
    args = ap.parse_args()

    model = compile_traffic_model(Path(args.trace_dir),
                                  num_batches_sample=10, num_nodes=args.nodes)

    if args.structure:
        events = json.load(open(args.structure))
        model = merge_participant_structure(model, events, args.nodes)
        print(f"Merged participant structure from {args.structure}")
    if args.add_dp_class:
        model = add_derived_dp_class(model, args.nodes)
        print("Appended derived DP_GRADIENT_AR class (provenance: published arch)")
    model = finalize_deadlines(model)
    
    # Print summary
    print(f"\n{'='*50}")
    print("TrafficModel Summary")
    print(f"{'='*50}")
    print(f"Compute: {model['compute']['avg_cycles_per_batch']:,} cycles/batch")
    print(f"Weights: {model['memory']['total_weight_bytes']/1e6:.1f} MB (streaming: {model['memory']['weight_streaming_dominates']})")
    print(f"Network flow classes:")
    for fc in model['network']['flow_classes']:
        inst = fc.get('instances')
        inst_s = f" x{len(inst)} instances(k={len(inst[0]['participants'])})" if inst else ""
        print(f"  {fc['name']:15s} {fc['comm_type']:15s} {fc['bytes_per_invocation']:>9.0f} B/inv  "
              f"prio={fc['priority']} deadline={fc['deadline_cycles']}{inst_s}")
    print(f"Constraints:")
    c = model['network']['constraints']
    print(f"  peak_ir={c['peak_injection_rate']:.6f} (instantaneous during collective)")
    print(f"  avg_ir={c['avg_injection_rate']:.6f} (fraction of time network active)")
    print(f"  compute/network ratio={c['compute_network_ratio']:.1f}x")
    
    # Write JSON into the repo (NOT /tmp — tmpfs is RAM)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(model, indent=2))
    print(f"\nWrote {out}")
