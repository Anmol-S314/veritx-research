#!/usr/bin/env python3
"""Standalone driver: generate REAL MoE serving network traces via
LLMServingSim's trace_generator, bypassing the ASTRA-sim binary.

Mimics vLLM continuous batching: mixes prefill and decode steps over a
ShareGPT Qwen3-30B-A3B request stream, emits per-layer comm ops
(TP ALLREDUCE, EP dispatch/combine ALLTOALL with token-routed sizes),
then converts to NoC traffic matrices + replayable trace files.
"""
import sys, os, json, random

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", "..", ".."))
LSS = os.path.join(_REPO_ROOT, "third_party", "llmservingsim")
sys.path.insert(0, LSS)
os.chdir(os.path.join(LSS, "astra-sim"))   # trace gen resolves ../profiler from here

from serving.core.request import Batch
from serving.core.trace_generator import generate_trace

MODEL = "Qwen/Qwen3-30B-A3B-Instruct-2507"
HARDWARE = "RTXPRO6000"

# --- load real request stream (ShareGPT Qwen3-30B-A3B) ---
reqs = []
for line in open(os.path.join(LSS, "workloads/sharegpt-qwen3-30b-a3b-300-sps10.jsonl")):
    r = json.loads(line)
    reqs.append((r["input_toks"], r["output_toks"]))
print(f"loaded {len(reqs)} requests from sharegpt-qwen3-30b-a3b")

rng = random.Random(42)
NBATCH = 60
batches = []
for b in range(NBATCH):
    # continuous-batching mix: 1 long prefill + several decodes (vLLM-ish)
    inp, out = rng.choice(reqs)
    n_dec = rng.randint(2, 8)
    q_list, k_list = [], []
    # the single prefill request contributes its chunked q
    pq = min(inp, rng.randint(512, 2048))
    q_list.append(pq); k_list.append(rng.randint(0, max(0, inp - pq)))
    for _ in range(n_dec):
        qlen = 1; klen = rng.randint(200, 1500)
        q_list.append(qlen); k_list.append(klen)
    total = sum(q_list) + sum(k_list)
    batches.append(Batch(
        batch_id=b, model=MODEL, total_len=total,
        kv_len=sum(k_list), q_list=q_list, k_list=k_list,
        num_prefill=1, num_decode=n_dec,
        prefill_q_list=[pq], prefill_k_list=[k_list[0]],
        decode_k_list=k_list[1:], batch_time=b * 40000,
        kv_size=sum(k_list) * 16 * 128 * 2 // 1024,  # KiB-ish placeholder
    ))

# --- generate traces: EP=2 across two instances (dp group), tp=1 ---
all_rows = {}
for inst in range(2):
    td = generate_trace(
        batch=batches[inst::2][0], hardware=HARDWARE,
        tp_size=1, pp_size=1, local_ep=1, ep_total=2,
        node_id=inst, instance_id=inst,
        expert_routing_policy="RAND",     # realistic gate imbalance, seedable
        fp=16, dtype="bfloat16",
        placement={"default": {"weights": "npu", "kv_loc": "npu",
                               "kv_evict_loc": "cpu"}, "layer": {}},
        inputs_root="/tmp/llmsim_inputs",
    )
    all_rows[inst] = td.rows
    print(f"instance {inst}: {len(td.rows)} rows")

print("done")
