#!/usr/bin/env python3
"""LLM NoC Traffic Generator (llm_traffic.py).

Generates authentic LLM hardware communication traffic profiles:
  1. TP_ALLREDUCE : Tensor Parallel Ring/All-to-All communication (MHA QKV & FFN scatter-gather)
  2. MOE_DISPATCH : Mixture-of-Experts token routing permutations (Top-K expert dispatch)
  3. KV_CACHE     : Mixed Prefill (large burst B=40..80) & Decode (short packet B=1..5) streaming
"""

import sys, os, math, random

def generate_llm_pattern(pattern_type, num_nodes, num_packets=5000, seed=42):
    random.seed(seed)
    packets = []  # (cycle, src, cl, dst, size)
    
    # 8x8 mesh default assumptions (64 nodes)
    # Tile allocation: 8 TP groups of 8 tiles each
    tp_group_size = min(8, num_nodes)
    num_tp_groups = max(1, num_nodes // tp_group_size)
    
    cycle = 1
    
    if pattern_type == "tp_allreduce":
        # Ring All-Reduce within each TP group
        for p in range(num_packets):
            group_id = random.randint(0, num_tp_groups - 1)
            rank = random.randint(0, tp_group_size - 1)
            src = group_id * tp_group_size + rank
            # Next rank in ring (All-Reduce ring step)
            dst_rank = (rank + 1) % tp_group_size
            dst = group_id * tp_group_size + dst_rank
            
            cl = 0 if random.random() < 0.8 else 1
            sz = 20 if cl == 0 else 1  # 20 flits for DMA payload, 1 flit for control credit
            cycle += random.randint(1, 4)
            packets.append((cycle, src, cl, dst, sz))
            
    elif pattern_type == "moe_dispatch":
        # Top-K Dynamic Expert Dispatch (Permutations across Expert Tiles)
        num_experts = max(4, num_nodes // 2)
        for p in range(num_packets):
            src = random.randint(0, num_nodes - 1)
            # Route token to 2 random expert nodes
            dst = random.randint(0, num_experts - 1)
            if dst == src:
                dst = (dst + 1) % num_nodes
            
            cl = 0
            sz = 10  # Token feature payload
            cycle += random.randint(1, 3)
            packets.append((cycle, src, cl, dst, sz))
            
    elif pattern_type == "kv_cache":
        # Prefill (burst) + Decode (short latency)
        for p in range(num_packets):
            src = random.randint(0, num_nodes - 1)
            dst = random.randint(0, num_nodes - 1)
            while dst == src:
                dst = random.randint(0, num_nodes - 1)
            
            is_prefill = random.random() < 0.3
            if is_prefill:
                cl = 0
                sz = 40  # Prefill KV block payload
                cycle += random.randint(5, 15)
            else:
                cl = 1
                sz = 1   # Decode token ACK / control flit
                cycle += random.randint(1, 3)
                
            packets.append((cycle, src, cl, dst, sz))
            
    else:
        raise ValueError(f"Unknown LLM pattern: {pattern_type}")
        
    return packets

def write_trace_file(packets, out_path):
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "w") as f:
        for cyc, src, cl, dst, sz in packets:
            f.write(f"{cyc} {src} {cl} {dst} {sz}\n")
    print(f"Wrote LLM trace with {len(packets)} packets to {out_path}")

if __name__ == "__main__":
    pattern = sys.argv[1] if len(sys.argv) > 1 else "tp_allreduce"
    nodes = int(sys.argv[2]) if len(sys.argv) > 2 else 64
    out = sys.argv[3] if len(sys.argv) > 3 else "llm_trace.txt"
    
    pkts = generate_llm_pattern(pattern, nodes)
    write_trace_file(pkts, out)
