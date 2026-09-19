"""Simulation entry point: ``python -m serving --cluster-config <...> [...]``.

Parses CLI args, generates ASTRA-Sim input files via ``serving.core.config_builder``,
spawns the ASTRA-Sim subprocess, and runs the iteration loop:
``router.route -> scheduler.schedule -> trace_generator -> graph -> ASTRA-Sim
-> scheduler.add_done`` until every request completes.
"""

import os
import subprocess
import argparse
import json
import shutil
from time import time
from collections import defaultdict, deque

from serving.core.scheduler import *
from serving.core.request import *
from serving.core.utils import *
from serving.core.controller import *
from serving.core.memory_model import *
from serving.core.graph_generator import *
from serving.core.trace_generator import *
from serving.core.pim_model import *
from serving.core.config_builder import *
from serving.core.router import *
from serving.core.power_model import *
from serving.core.logger import *
from serving.core.run_paths import build_run_paths, resolve_run_id
from serving.core.liveness import (
    LivenessProbe as _LivenessProbe,
    ProgressObservation as _ProgressObservation,
    attach_to_failure as _liveness_attach,
    USEFUL_PROGRESS as _LIVE_PROGRESS,
)
# VeritX B3.7c: certified backend consumer seam (no semantic inference).
from serving.veritx_certified import CERTIFIED_BACKEND_ENV, resolve_certified_backend
import sys as flush

# Optional profiling: the vendored pyinstrument ships a C extension built
# for one CPython version; on a newer interpreter the import fails and would
# otherwise kill the whole simulation at startup. All current uses are
# commented out (see main()), so degrade to Profiler=None instead.
try:
    from pyinstrument import Profiler
except ImportError:  # missing/incompatible compiled low_level extension
    Profiler = None


def _pad_batch_to_max(batch, max_len):
    """Pad a batch up to ``max_len`` for DP-sync.

    Mirrors vLLM's CUDA-graph DP padding: every DP rank's forward runs at
    ``max(num_tokens_across_dp)``. We bump the high-level counters so
    dense layers, lm_head, and the MoE compute path all reflect the
    padded shape — but we deliberately leave ``decode_k_list`` /
    prefill lists untouched so attention continues to see only the real
    decodes. FlashAttention's varlen kernel gives padded ``seq_len=0``
    entries zero compute in real vLLM, and extending ``decode_k_list``
    with ``kv=1`` dummies would instead collapse ``kv_decode_mean``
    toward 1 and push the attention lookup far outside the profiled
    sweep.

    MoE AG/RS comm size is anchored separately to ``max_total_len`` (no
    ``× group_size``) in the iteration loop — that calibrates the
    bandwidth model against the same ``link_bw`` AllReduce already uses.

    Request-completion accounting (`scheduler.add_done`) reads
    ``batch.requests`` and ``batch.end``, not these mutated token-list
    fields, so it is unaffected.
    """
    pad = max_len - batch.total_len
    if pad <= 0:
        return
    batch.total_len = max_len
    batch.kv_len += pad                  # each dummy contributes kv=1
    batch.num_decode += pad              # counted for lm_head / dense shape


def _sweep_completion(network_backend, num_instances, instance_id,
                      decode_instance, is_prefill_done, schedulers, router,
                      inst_dp_group, dp_groups, npu2inst_mapping, instances,
                      done_inst_npus, done_instance, round_done_npus):
    """Burst-wide completion accounting. Returns newly-done instance ids.

    Completion is a property of simulator state, not of which instance
    happened to be selected for scheduling: booksim/analytical replies are
    cluster-wide (bursts name many NPUs while sys points at one), so every
    instance represented by this round's evidence is evaluated. Other
    backends keep served-instance-only behaviour (their per-NPU polls visit
    everyone naturally). Mutates done_inst_npus / done_instance in place.
    """
    _prefill_done_before_sweep = is_prefill_done
    _newly_done = []
    if network_backend in ('booksim', 'analytical'):
        _candidates = range(num_instances)
    else:
        _candidates = (instance_id,)
    for _iid in _candidates:
        # Phase gate, snapshotted: completing the final prefill instance
        # must not also complete decode instances in the same iteration.
        if _iid in decode_instance and not _prefill_done_before_sweep:
            continue
        if _iid in done_instance:
            continue
        if not schedulers[_iid].is_request_empty():
            continue
        if router.has_pending_requests():
            continue
        if router.has_deferred_sessions():
            continue
        # DP-group all-members-empty check (candidate-skip, not
        # iteration-skip).
        _dg = inst_dp_group.get(_iid)
        if _dg is not None and not all(
                schedulers[i].is_request_empty()
                and len(schedulers[i].inflight) == 0
                for i in dp_groups[_dg]):
            continue
        # Credit only actual completion evidence for this instance.
        for _done_sys in round_done_npus:
            if npu2inst_mapping.get(_done_sys) != _iid:
                continue
            if _done_sys not in done_inst_npus[_iid]:
                done_inst_npus[_iid].append(_done_sys)
        _need = 1 if (
            instances[_iid]["num_npus"] == 1
            or network_backend in ('booksim', 'analytical')
        ) else 2
        # >= not ==: one burst can expose several NPUs of an instance at
        # once; exact equality would livelock 0->2 against a threshold of 1.
        # Dedup keeps the 2-distinct-NPU handshake exact for other backends.
        if len(done_inst_npus[_iid]) >= _need:
            done_instance.append(_iid)
            _newly_done.append(_iid)
    return _newly_done


def _pass_response(router, current, state_changed=False):
    """The "pass" answer, carrying the next known arrival when there is one.

    ASTRA-Sim stops re-asking an NPU that passed until either some NPU
    reports an iteration the frontend has not processed yet, or this
    deadline is reached. Those are the only two things that can change what
    ``schedule()`` returns, so suppressing the re-asks in between skips no
    decision. Without the deadline an idle instance would stay suppressed
    past an arrival it should have admitted, in the case where every other
    instance is still mid-batch and so no report is coming.

``state_changed=True`` sends ``pass -1``: this pass altered scheduler
    state, so it is not idempotent and re-asking is not a wasted question.
    The three DP-barrier passes do that -- joining a round with a dummy,
    joining it with a real batch, or handing a batch claim back -- and none
    of them is preceded by a report, so nothing else would lift the
    suppression. ASTRA-Sim treats it like a workload assignment: this NPU
    stays askable and every other one is re-opened too.
    """
    if state_changed:
        return "pass -1"
    nxt = router.get_next_pending_arrival()
    if nxt is None or nxt <= current:
        return "pass"
    return f"pass {int(nxt)}"


def _runtime_limit(value):
    return float('inf') if value == 0 else value


def _cluster_config_path(path):
    if os.path.isabs(path):
        return path
    return os.path.join("..", path)


def _load_cluster_config_for_overrides(path):
    with open(_cluster_config_path(path), "r") as f:
        return json.load(f)


def _resolve_output_file(path, run_id):
    if path is None:
        return None
    return path.replace("{run_id}", run_id)


def _cleanup_inputs_root(run_paths, logger):
    """Remove generated ASTRA-Sim inputs after a completed simulation."""
    runs_root = os.path.abspath(os.path.join("inputs", "runs"))
    inputs_root = os.path.abspath(run_paths.inputs_root)
    if inputs_root in (os.path.abspath("inputs"), runs_root):
        raise RuntimeError(f"Refusing to remove broad inputs root: {inputs_root}")
    if not inputs_root.startswith(runs_root + os.sep):
        logger.warning(
            "Skipping ASTRA-Sim inputs cleanup because inputs_root is outside %s: %s",
            runs_root, inputs_root,
        )
        return
    shutil.rmtree(inputs_root, ignore_errors=True)
    logger.info("Removed ASTRA-Sim inputs root: %s", inputs_root)


def _prepare_booksim_config(astra_sim, run_paths, num_nodes):
    # VeritX: forward-ported BookSim backend (upstream deleted theirs).
    """Prepare BookSim config for ASTRA-sim's BookSim2 backend.

    BookSim mesh only supports square k^n. For rectangular dims like 2x4 (8 NPUs)
    we emit an anynet mesh file instead. This keeps node_count correct and avoids
    dimension mismatch with ASTRA's network.yml (which is [2,4] for 4xTP2).

    Now reads the ACTUAL network.yml dims instead of inferring, so any LLM
    workload (any N, any parallelism) is correct.
    """
    import math, yaml
    booksim_src = os.path.join(astra_sim, "..", "..", "booksim2", "src")
    if not os.path.exists(booksim_src):
        booksim_src = os.path.join(os.path.dirname(astra_sim), "..", "..", "booksim2", "src")

    _certified = resolve_certified_backend()
    if _certified is not None:
        # VeritX B3.7c: certified consumption. The exact config is prepared
        # by the semantic lowerer; never synthesize a second fabric from
        # network.yml. CertifiedBackendError propagates (fail closed).
        return _certified["config_path"], booksim_src

    config_dir = os.path.join(run_paths.inputs_root, "booksim")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "config.cfg")

    # Read ACTUAL dims from network.yml (already written by build_cluster_config)
    network_yml = os.path.join(run_paths.inputs_root, "network", "network.yml")
    dims = None
    topologies = None
    if os.path.exists(network_yml):
        try:
            with open(network_yml) as f:
                y = yaml.safe_load(f)
                dims = y.get("npus_count")
                topologies = y.get("topology")
                if dims and all(isinstance(x, int) for x in dims) \
                        and topologies and len(topologies) == len(dims):
                    pass
                else:
                    dims = None
        except Exception:
            dims = None
    if dims is None:
        # VeritX: certified execution never invents a fabric. network.yml
        # is written by build_cluster_config in this same process — its
        # absence (or a missing topology axis) is an internal failure,
        # not a license to infer dimensions or assume FullyConnected.
        raise RuntimeError(
            f"refusing to invent serving fabric: {network_yml} missing or "
            "without matching npus_count/topology (certified runs derive "
            "dims from the resolved cluster only)")
    # Mesh k^n only works for square/1D line. FullyConnected with >2 nodes needs anynet clique.
    # e.g. dims [8] FullyConnected is 8-node clique, not 8-node line (k=8 mesh).
    has_fc_large = False
    for i, d in enumerate(dims):
        if topologies[i] == "FullyConnected" and d > 2:
            has_fc_large = True
    is_square_mesh = (len(dims) == 1 and dims[0] == 2) or (len(dims) == 2 and dims[0] == dims[1])
    if dims == [1]:
        is_square_mesh = True
    if has_fc_large:
        is_square_mesh = False

    # Rectangular dims -> anynet
    if not is_square_mesh and dims != [1]:
        anynet_path = os.path.join(config_dir, "topo.anynet")
        # Generate mesh anynet for dims
        def _gen_mesh_anynet(dims, out_path):
            N = math.prod(dims)
            # Precompute strides
            strides = []
            prod = 1
            for d in reversed(dims):
                strides.insert(0, prod)
                prod *= d
            # Decode id -> coords
            def coords(idx):
                c = []
                for i, d in enumerate(dims):
                    c.append((idx // strides[i]) % d)
                return c
            # Build adjacency: FullyConnected dims -> clique, else mesh (no wrap)
            with open(out_path, "w") as f:
                for r in range(N):
                    rc = coords(r)
                    line = f"router {r} node {r}"
                    for dim, d in enumerate(dims):
                        if topologies[dim] == "FullyConnected":
                            # Fully connect all routers sharing same coords in other dims
                            for other in range(N):
                                if other == r: continue
                                oc = coords(other)
                                # same in all dims except this dim
                                if all(oc[i] == rc[i] for i in range(len(dims)) if i != dim):
                                    line += f" router {other}"
                        else:
                            # Mesh: neighbors in each dim
                            for delta in (-1, 1):
                                nc = rc.copy()
                                nc[dim] += delta
                                if 0 <= nc[dim] < d:
                                    nid = sum(nc[i] * strides[i] for i in range(len(dims)))
                                    line += f" router {nid}"
                    f.write(line + "\n")
        _gen_mesh_anynet(dims, anynet_path)
        with open(config_path, "w") as f:
            f.write(f"""// BookSim anynet for {num_nodes} NPUs dims={dims}
topology = anynet;
network_file = {anynet_path};
routing_function = min;
num_vcs = 16;
vc_buf_size = 512;
packet_size = 64;
wait_for_tail_credit = 1;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = 1;
credit_delay = 2;
routing_delay = 0;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
input_speedup = 2;
output_speedup = 1;
internal_speedup = 1.0;
traffic = uniform;
injection_rate = 0.0;
""")
        # VeritX: main.cc now takes --physical-dims (logical dims), so
        # multi-dim collective_impl arrays are honored (no collapse needed).
        # Collapsing them to 1D would renumber dim>=1 (EP/DP) collectives
        # out of existence in Sys::generate_collective.
        return config_path, booksim_src

    # Square / 1D mesh path (original)
    k = int(math.sqrt(num_nodes))
    if k * k != num_nodes:
        k = num_nodes
        n = 1
    else:
        n = 2
    if k < 2:
        if num_nodes == 1:
            k = 1
            n = 1
        else:
            k = 2
            n = 1
    with open(config_path, "w") as f:
        f.write(f"""// BookSim config for ASTRA-sim backend
// Generated by LLMServingSim
topology = mesh;
k = {k};
n = {n};
routing_function = dor;
num_vcs = 16;
vc_buf_size = 512;
packet_size = 64;
wait_for_tail_credit = 1;
vc_allocator = islip;
sw_allocator = islip;
alloc_iters = 1;
credit_delay = 2;
routing_delay = 0;
vc_alloc_delay = 1;
sw_alloc_delay = 1;
input_speedup = 2;
output_speedup = 1;
internal_speedup = 1.0;
traffic = uniform;
// VeritX: embed mode must never synthesize demand traffic — every flit
// comes from sim_send. Without this, booksim's default injection floods
// the fabric (~2M background flits per 1M cycles) and the event loop
// spins forever draining flits that never end.
injection_rate = 0.0;
""")
    return config_path, booksim_src



def _prepare_ns3_config(astra_sim, run_paths):
    template = os.path.join(astra_sim, "extern/network_backend/ns-3/scratch/config/config.txt")
    output_dir = os.path.join(run_paths.inputs_root, "ns3", "output")
    config_path = os.path.join(run_paths.inputs_root, "ns3", "config.txt")
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(os.path.dirname(config_path), exist_ok=True)

    replacements = {
        "FLOW_FILE": os.path.join(output_dir, "flow.txt"),
        "TRACE_FILE": os.path.join(output_dir, "trace.txt"),
        "TRACE_OUTPUT_FILE": os.path.join(output_dir, "mix.tr"),
        "FCT_OUTPUT_FILE": os.path.join(output_dir, "fct.txt"),
        "PFC_OUTPUT_FILE": os.path.join(output_dir, "pfc.txt"),
        "QLEN_MON_FILE": os.path.join(output_dir, "qlen.txt"),
    }

    for path in (replacements["FLOW_FILE"], replacements["TRACE_FILE"]):
        open(path, "w").close()

    with open(template, "r", encoding="utf-8") as f:
        lines = f.readlines()

    with open(config_path, "w", encoding="utf-8") as f:
        for line in lines:
            parts = line.split(maxsplit=1)
            if parts and parts[0] in replacements:
                f.write(f"{parts[0]} {replacements[parts[0]]}\n")
            else:
                f.write(line)
    return config_path


def _iter_raw_instances(cluster_config):
    for node in cluster_config.get("nodes", []):
        for instance in node.get("instances", []):
            yield instance


def _resolve_instance_dtype(instance, cli_dtype, dtype_to_bits):
    dtype = instance.get("dtype", cli_dtype)
    if dtype is None:
        config = get_config(instance["model_name"])
        torch_dtype = config.get("torch_dtype")
        if isinstance(torch_dtype, str) and torch_dtype in dtype_to_bits:
            dtype = torch_dtype
        else:
            dtype = "bfloat16"
    if dtype not in dtype_to_bits:
        raise ValueError(f"Unsupported dtype '{dtype}' for instance {instance.get('instance_id')}")
    return dtype


def _resolve_mem_util(instance, cli_default):
    """Per-instance NPU memory utilization, from ``npu_mem.mem_util``.

    Lives inside ``npu_mem`` because its only job is to scale ``mem_size``, and
    it follows that block's ``mem_*`` naming. Falls back to the CLI default.
    """
    util = instance.get("npu_mem", {}).get("mem_util", cli_default)
    try:
        util = float(util)
    except (TypeError, ValueError):
        raise ValueError(
            f"npu_mem.mem_util for instance {instance.get('instance_id')} must be a "
            f"number in (0, 1]; got {util!r}"
        ) from None
    if not 0 < util <= 1:
        raise ValueError(
            f"npu_mem.mem_util for instance {instance.get('instance_id')} must be in "
            f"(0, 1]; got {util}. It is a fraction of npu_mem.mem_size, so 0.9 rather "
            f"than 90"
        )
    return util


def _build_instance_runtime_configs(instances, args, dtype_to_bits):
    runtime_configs = []
    for instance_id, instance in enumerate(instances):
        dtype = _resolve_instance_dtype(instance, args.dtype, dtype_to_bits)
        kv_cache_dtype = instance.get("kv_cache_dtype", args.kv_cache_dtype)
        if kv_cache_dtype not in ("auto", "fp8"):
            raise ValueError(f"Unsupported kv_cache_dtype '{kv_cache_dtype}' for instance {instance_id}")

        enable_attn_offloading = instance.get("enable_attn_offloading", args.enable_attn_offloading)
        enable_sub_batch_interleaving = instance.get(
            "enable_sub_batch_interleaving", args.enable_sub_batch_interleaving)
        if enable_sub_batch_interleaving and not enable_attn_offloading:
            raise RuntimeError(
                f"Instance {instance_id} enables sub-batch interleaving without attention offloading")
        if enable_sub_batch_interleaving and instance.get("pp_size", 1) > 1:
            raise RuntimeError(
                f"Instance {instance_id} enables sub-batch interleaving with pp_size "
                f"{instance['pp_size']}: an interleaved trace leaves both sub-batches "
                f"mid-block at every group edge, so a pipeline stage has no single "
                f"hidden state to pass on")

        runtime_configs.append({
            "max_num_seqs": _runtime_limit(instance.get("max_num_seqs", args.max_num_seqs)),
            "max_num_batched_tokens": _runtime_limit(
                instance.get("max_num_batched_tokens", args.max_num_batched_tokens)),
            "long_prefill_token_threshold": instance.get(
                "long_prefill_token_threshold", args.long_prefill_token_threshold),
            "block_size": instance.get("block_size", args.block_size),
            "dtype": dtype,
            "fp": dtype_to_bits[dtype],
            "kv_cache_dtype": kv_cache_dtype,
            "enable_chunked_prefill": instance.get(
                "enable_chunked_prefill", args.enable_chunked_prefill),
            "enable_prefix_caching": instance.get(
                "enable_prefix_caching", args.enable_prefix_caching),
            "npu_memory_utilization": _resolve_mem_util(
                instance, args.npu_memory_utilization),
            "reserve_full_isl": instance.get("reserve_full_isl", args.reserve_full_isl),
            "enable_local_offloading": instance.get(
                "enable_local_offloading", args.enable_local_offloading),
            "enable_attn_offloading": enable_attn_offloading,
            "enable_sub_batch_interleaving": enable_sub_batch_interleaving,
            "enable_block_copy": instance.get("enable_block_copy", args.enable_block_copy),
        })
    return runtime_configs


def main():
    # ----------------------------------------------------------------------------------------------
    # LLMServingSim runs in astra-sim directory for easy path configuration
    # your relative path should start from astra-sim directory
    cwd = os.getcwd()
    astra_sim = os.path.join(cwd, "astra-sim")
    os.chdir(astra_sim)

    # -------------------------------------- Argument parsing --------------------------------------
    parser = argparse.ArgumentParser(prog='python -m serving',
                                     description='LLMServingSim')

    parser.add_argument('--cluster-config', type=str, default='configs/cluster/single_node_single_instance.json',
                        help='path to cluster config JSON defining node topology, instance layout, hardware, and memory hierarchy')
    parser.add_argument('--max-num-seqs', type=int, default=128,
                        help='maximum number of sequences in a batch (0 = unlimited)')
    parser.add_argument('--max-num-batched-tokens', type=int, default=2048,
                        help='maximum number of tokens processed per iteration across all requests (the total token budget). '
                        'With chunked prefill, long inputs are split across iterations; '
                        'without chunked prefill, this effectively caps max input length')
    parser.add_argument('--long-prefill-token-threshold', type=int, default=0,
                        help='per-request token cap per step for chunked prefill (0 = disabled). '
                        'Limits how many tokens a single prefill request consumes per iteration, '
                        'preventing long prompts from monopolizing the token budget. '
                        'When 0, a single prefill can consume the entire budget')
    parser.add_argument('--dtype', type=str, choices=['float16', 'bfloat16', 'float32', 'fp8', 'int8'], default=None,
                        help='model weight data type (vLLM-style). When omitted, defaults to the model config\'s '
                        '``torch_dtype`` (falling back to bfloat16). Overrides only take effect if the profiler '
                        'produced matching data under perf/<hw>/<model>/<variant>/tp<N>/')
    parser.add_argument('--request-routing-policy', type=str, choices=['LOAD', 'RR', 'RAND', 'CUSTOM'], default='LOAD',
                        help='request routing policy across instances: LOAD (vLLM-style weighted least-loaded, default), '
                        'RR (round-robin), RAND (random), CUSTOM (user-defined)')
    parser.add_argument('--expert-routing-policy', type=str,
                        choices=['BALANCED', 'RR', 'RAND', 'CUSTOM'],
                        default='BALANCED',
                        help='expert token routing policy for MoE models: '
                        'BALANCED (default; analytical pigeonhole approximation of '
                        'a trained load-balanced learned gate), '
                        'RR (round-robin), RAND (uniform random per token), '
                        'CUSTOM (user-defined)')
    parser.add_argument('--enable-block-copy', action=argparse.BooleanOptionalAction,
                        default=True,
                        help='Replay one transformer block\'s trace across every '
                        'layer instead of re-computing the routing per layer — '
                        'cuts trace-generation time roughly num_hidden_layers× '
                        'on MoE models. Safe with BALANCED (deterministic); '
                        'RR/RAND get a small per-layer variance averaged out. '
                        'Disable only for CUSTOM policies that need faithful '
                        'per-layer variance.')
    parser.add_argument('--enable-prefix-caching', action=argparse.BooleanOptionalAction, default=True,
                        help='enable prefix caching to reuse KV cache blocks across requests '
                        'with shared prefixes (default: enabled). Use --no-enable-prefix-caching to disable')
    parser.add_argument('--enable-chunked-prefill', action=argparse.BooleanOptionalAction, default=True,
                        help='enable chunked prefill to split long prefill requests across multiple iterations, '
                        'matching vLLM v1 behavior (default: enabled). Use --no-enable-chunked-prefill to disable')
    parser.add_argument('--enable-prefix-sharing', action='store_true', default=False,
                        help='enable second-tier prefix cache pooling across instances within a node')
    parser.add_argument('--prefix-storage', type=str, choices=['None', 'CPU', 'CXL'], default='None',
                        help='storage medium for the second-tier prefix cache pool: None (NPU only), CPU, or CXL')
    parser.add_argument('--enable-local-offloading', action='store_true', default=False,
                        help='enable weight offloading to local (NPU) memory. '
                        'Recommended to disable unless weight memory access is not counted in profiling')
    parser.add_argument('--enable-attn-offloading', action='store_true', default=False,
                        help='enable attention computation offloading to PIM (Processing-In-Memory) devices')
    parser.add_argument('--enable-sub-batch-interleaving', action='store_true', default=False,
                        help='enable sub-batch interleaving to overlap XPU and PIM computation. '
                        'Requires --enable-attn-offloading')
    parser.add_argument('--reserve-full-isl', action=argparse.BooleanOptionalAction, default=True,
                        help='admit a request only if its whole sequence fits in the KV cache, '
                        'not merely its first chunk. Mirrors vLLM\'s scheduler_reserve_full_isl '
                        '(True there too); without it chunked prefill over-admits and thrashes '
                        'the KV cache. Override per instance with "reserve_full_isl"')
    parser.add_argument('--npu-memory-utilization', type=float, default=0.9,
                        help='fraction of NPU memory an instance may use for weights plus '
                        "KV cache. Corresponds to vLLM's --gpu-memory-utilization, renamed "
                        'because every other memory surface here is NPU-terminology; '
                        'override per instance with "npu_mem": {"mem_util": ...}. KV capacity is '
                        '(npu_mem * this - model weight); the activation peak and CUDA '
                        'context that vLLM also subtracts are not modelled, so the '
                        'resulting capacity is an upper bound on vLLM\'s at the same value')
    parser.add_argument('--block-size', type=int, default=16,
                        help='KV cache block size in tokens (number of tokens per block)')
    parser.add_argument('--dataset', type=str, default=None,
                        help='path to .jsonl dataset file with request traces. '
                        'If None, requests must be added manually in serving/__main__.py')
    parser.add_argument('--output', type=str, default=None,
                        help='path for per-request CSV output with latency metrics (TTFT, TPOT, ITL). '
                        'If None, results are printed to stdout only. Supports {run_id} placeholder')
    parser.add_argument('--run-id', type=str, default=None,
                        help='unique id for this simulation run. Intermediate ASTRA-Sim inputs are written under '
                        'astra-sim/inputs/runs/<run-id>. If omitted, a process-unique id is generated')
    parser.add_argument('--inputs-root', type=str, default=None,
                        help='override the root directory for generated ASTRA-Sim inputs. Defaults to '
                        'astra-sim/inputs/runs/<run-id>')
    parser.add_argument('--save-trace-text', action=argparse.BooleanOptionalAction, default=False,
                        help='write each batch\'s trace as text, for inspection (default: '
                        'disabled). Nothing in the pipeline reads it -- the Chakra converter takes '
                        'the trace rows directly -- so it is produced only on request, and it is '
                        'the only human-readable form of what the simulator emitted. Implies '
                        '--keep-inputs, since the text is written into the run directory. Can '
                        'leave gigabytes behind on a long run')
    parser.add_argument('--keep-inputs', action=argparse.BooleanOptionalAction, default=False,
                        help='keep the generated ASTRA-Sim inputs under '
                        'astra-sim/inputs/runs/<run-id> after a successful simulation (default: '
                        'disabled). Preserves the Chakra .et workloads and the generated network, '
                        'system and memory configs, so a run can be replayed through ASTRA-Sim by '
                        'hand. Replaces --cleanup-inputs, whose polarity was inverted')
    parser.add_argument('--skip-prefill', action='store_true', default=False,
                        help='skip the prefill phase, running decode only')
    parser.add_argument('--num-reqs', type=int, default=0,
                        help='number of entries (requests or sessions) to load from the dataset. '
                        'For agentic datasets, each entry is a session with multiple sub-requests. '
                        '0 = load all entries')
    parser.add_argument('--log-interval', type=float, default=1.0,
                        help='interval in seconds between throughput/memory usage log messages')
    parser.add_argument('--log-level', type=str, choices=['WARNING', 'INFO', 'DEBUG'], default='WARNING',
                        help='logging verbosity: WARNING (minimal), INFO (per-iteration details), DEBUG (per-layer memory)')
    parser.add_argument('--kv-cache-dtype', type=str, choices=['auto', 'fp8'], default='auto',
                        help='KV cache data type: auto (inherit --dtype) or fp8. Selects the profile '
                        'variant folder -- fp8 resolves to <dtype>-kvfp8, e.g. bf16-kvfp8 -- and '
                        'halves KV cache memory. Override per instance with "kv_cache_dtype"')
    parser.add_argument('--network-backend', type=str, choices=['analytical', 'ns3', 'booksim'], default='analytical',
                        help='network simulation backend: analytical (fast, default), ns3 (detailed, WIP), '
                        'or booksim (VeritX: cycle-accurate NoC via AstraSim_BookSim2)')
    # VeritX: forward-ported BookSim backend (upstream deleted theirs).
    parser.add_argument('--booksim-replay-only', action=argparse.BooleanOptionalAction, default=True,
                        help='(booksim backend only) replay trace durations without cycle-accurate network simulation '
                        '(default: enabled). Required when ASTRA-sim ring topology does not match BookSim mesh topology. '
                        'Use --no-booksim-replay-only for full cycle-accurate network simulation (requires matching topologies, ~10x slower).')

    args = parser.parse_args()

    args.run_id = resolve_run_id(args.run_id)
    run_paths = build_run_paths(astra_sim, args.run_id, args.inputs_root)
    args.inputs_root = run_paths.inputs_root
    args.output = _resolve_output_file(args.output, args.run_id)

    configure_logger(level=args.log_level)
    logger = get_logger("Main")
    print_banner()
    print_input_config(args=args)
    flush.stdout.flush()

    _dtype_to_bits = {'float16': 16, 'bfloat16': 16, 'float32': 32, 'fp8': 8, 'int8': 8}
    request_routing_policy=args.request_routing_policy
    expert_routing_policy=args.expert_routing_policy
    enable_prefix_sharing=args.enable_prefix_sharing
    prefix_storage=args.prefix_storage
    dataset=args.dataset
    output_file=args.output
    is_init = not args.skip_prefill
    num_req=args.num_reqs
    log_interval=args.log_interval
    network_backend = args.network_backend
    raw_cluster_config = _load_cluster_config_for_overrides(args.cluster_config)
    raw_instances = list(_iter_raw_instances(raw_cluster_config))
    build_enable_local_offloading = args.enable_local_offloading or any(
        inst.get("enable_local_offloading", False) for inst in raw_instances)
    build_enable_attn_offloading = args.enable_attn_offloading or any(
        inst.get("enable_attn_offloading", False) for inst in raw_instances)
    # ---------------------------------- Extract cluster config -----------------------------------
    cluster = build_cluster_config(
        astra_sim, args.cluster_config, build_enable_local_offloading, build_enable_attn_offloading,
        inputs_root=run_paths.inputs_root)
    num_nodes = cluster["num_nodes"]
    num_instances = cluster["num_instances"]
    instances = cluster["instances"]
    inst2node_mapping = cluster["inst2node_mapping"]
    inst2npu_mapping = cluster["inst2npu_mapping"]
    npu2inst_mapping = cluster["npu2inst_mapping"]
    prefill_instance = cluster["prefill_instance"]
    decode_instance = cluster["decode_instance"]
    start_npu_ids = cluster["start_npu_ids"]
    end_npu_ids = cluster["end_npu_ids"]
    placement = cluster["placement"]
    block_mode_on = cluster["block_mode_on"]
    total_npu = cluster["total_npu"]
    cpu_mem_size = cluster["cpu_mem_size"]
    power_modeling = cluster["power_modeling"]
    power_configs = cluster["power_configs"]
    pim_models = cluster["pim_models"]
    instance_runtime_configs = _build_instance_runtime_configs(instances, args, _dtype_to_bits)
    any_prefix_caching = any(cfg["enable_prefix_caching"] for cfg in instance_runtime_configs)
    # ----------------------------------------- Set config -----------------------------------------
    # Automatic network, memory configuration
    # If you want to set more specific information such as latency, look at config.py and each json file
    _analytical_unaware = False  # VeritX: True when N-dim falls back to unaware engine
    if network_backend == 'analytical':
        network=run_paths.network_config
        # VeritX: binary lives in the SOURCE tree build (astra-sim/astra-sim/build),
        # not the top-level third_party/astra-sim/build/ twin (stale, removed).
        # astra_sim/astra-sim -> third_party/astra-sim/astra-sim via symlink.
        binary=os.path.join(astra_sim, "astra-sim/build/astra_analytical/build/AnalyticalAstra/bin/AnalyticalAstra")
        # VeritX: the congestion-aware engine only supports flat 1-dim
        # topologies. For multi-dim (DP/PP/MoE) fall back to the
        # congestion-unaware engine (native N-dim, optimistic lower bound)
        # instead of failing. See build/astra_analytical_unaware/.
        _analytical_unaware = False
        try:
            import yaml as _yaml
            with open(network) as _nf:
                _ndims = (_yaml.safe_load(_nf) or {}).get("npus_count", [1])
            if isinstance(_ndims, list) and len(_ndims) > 1:
                # VeritX: this path is where build.sh's cmake actually emits
                # the binary (build/bin/...); the twin at
                # build/AnalyticalAstraUnaware/bin/ was the pre-reconfigure
                # layout and silently went stale on rebuilds.
                _unaware = os.path.join(astra_sim, "build/astra_analytical_unaware/build/bin/AnalyticalAstraUnaware")
                if os.path.exists(_unaware):
                    binary = _unaware
                    _analytical_unaware = True
                    print("[LLMServingSim] network dims "
                          f"{_ndims}: congestion-aware engine is 1-dim-only, "
                          f"using congestion-unaware estimates (lower bound).", flush=True)
                else:
                    raise SystemExit(
                        f"error: --network-backend analytical supports only 1-dim topologies, "
                        f"but this cluster yields network dims {_ndims} "
                        f"(and the unaware fallback binary is missing — build it via "
                        f"third_party/astra-sim/build/astra_analytical_unaware/build.sh). "
                        f"Use --network-backend booksim for multi-dim (DP/PP/MoE) configs.")
        except SystemExit:
            raise
        except Exception:
            pass
    elif network_backend == 'ns3':
        network=_prepare_ns3_config(astra_sim, run_paths)
        binary=os.path.join(astra_sim, "extern/network_backend/ns-3/build/scratch/ns3.42-AstraSimNetwork-default")
    elif network_backend == 'booksim':
        # VeritX: forward-ported (upstream deleted the booksim backend).
        network, booksim_src = _prepare_booksim_config(astra_sim, run_paths, total_npu)
        binary=os.path.join(astra_sim, "network_frontend/booksim2/bin/AstraSim_BookSim2")
    else:
        raise NotImplementedError("Only analytical, ns3, and booksim network backends are supported")
    memory=run_paths.memory_config
    system=run_paths.system_config
    # ------------------------------------- Prepare simulation -------------------------------------
    # Need to extract each instance's memory accessability
    node2inst_mapping = defaultdict(list)
    for inst_id, node_id in inst2node_mapping.items():
        node2inst_mapping[node_id].append(inst_id)
    node2inst_mapping = dict(node2inst_mapping)

    prefix_pool_inst_mapping = {}
    for i in range(num_instances):
        prefix_pool_inst_mapping[i] = None

    pool_device = None

    if prefix_storage == "CPU":
        pool_device = Device.CPU
    elif prefix_storage == "CXL":
        pool_device = Device.CXL

    if any_prefix_caching and enable_prefix_sharing and prefix_storage != 'None':
        num_prefix_pool = num_nodes
        # make prefix pool objects based on num_prefix_pool
        prefix_pools = []

        def _pool_kv_bytes_per_token(inst_ids):
            """KV bytes per token for a shared pool."""
            kv_shapes = {
                (
                    instances[i]["model_name"],
                    instance_runtime_configs[i]["fp"],
                    instance_runtime_configs[i]["kv_cache_dtype"],
                )
                for i in inst_ids
            }
            if len(kv_shapes) > 1:
                raise RuntimeError(
                    "Shared prefix pool requires instances to share model, "
                    f"dtype, and kv_cache_dtype; got {kv_shapes}"
                )
            model = instances[inst_ids[0]]['model_name']
            cfg = instance_runtime_configs[inst_ids[0]]
            return full_cluster_kv_bytes_per_token(model, cfg["fp"], cfg["kv_cache_dtype"])

        def _pool_block_size(inst_ids):
            sizes = {instance_runtime_configs[i]["block_size"] for i in inst_ids}
            if len(sizes) > 1:
                raise RuntimeError(
                    f"Shared prefix pool requires instances to share block_size; got {sizes}")
            return sizes.pop()

        if prefix_storage == 'CPU':
            for i in range(num_prefix_pool):
                if cpu_mem_size[i] <= 0:
                    raise RuntimeError(f"Memory size for prefix storage type {prefix_storage} is invalid")
                inst_ids = node2inst_mapping[i]
                prefix_pools.append(build_prefix_pool(
                    pool_device, cpu_mem_size[i] * GB_TO_BYTE,
                    _pool_block_size(inst_ids), _pool_kv_bytes_per_token(inst_ids),
                    node_id=i))
            # This means one node shares one prefix pool
            prefix_pool_inst_mapping = inst2node_mapping

        elif prefix_storage == 'CXL':
            if cluster["cxl_mem_size"] <= 0:
                raise RuntimeError(f"Memory size for prefix storage type {prefix_storage} is invalid")
            inst_ids = list(range(num_instances))
            prefix_pools.append(build_prefix_pool(
                pool_device, cluster["cxl_mem_size"] * GB_TO_BYTE,
                _pool_block_size(inst_ids), _pool_kv_bytes_per_token(inst_ids)))
            # This means every instance shares the same universal prefix pool (maybe fixed later)
            prefix_pool_inst_mapping = [0 for _ in range(num_instances)]
        else:
            raise NotImplementedError(f"Prefix storage type {prefix_storage} is not supported or memory size is invalid")

    schedulers = []
    for instance_id, instance in enumerate(instances):
        prefix_pool_index = prefix_pool_inst_mapping[instance_id]
        prefix_pool = None
        if prefix_pool_index != None:
            prefix_pool = prefix_pools[prefix_pool_index]
        cxl_mem = 0
        if cluster["cxl_mem_size"] > 0:
            cxl_mem = cluster["cxl_mem_size"]

        # Make scheduler for each instance

        inst_cfg = instance_runtime_configs[instance_id]

        schedulers.append(Scheduler(
            instance["model_name"], instance["node_id"], instance_id,
            inst_cfg["max_num_seqs"], inst_cfg["max_num_batched_tokens"],
            instance["num_npus"], instance["tp_size"], instance["pp_size"],
            instance["npu_mem"]["mem_size"], cpu_mem_size[instance["node_id"]],
            inst2npu_mapping[instance_id], instance["pd_type"],
            inst_cfg["fp"], inst_cfg["block_size"], num_req,
            inst_cfg["enable_prefix_caching"],
            enable_prefix_sharing, prefix_pool, pool_device, inst_cfg["enable_chunked_prefill"],
            inst_cfg["long_prefill_token_threshold"],
            cxl_mem,
            ep_size=instance.get("ep_total", 1),
            kv_cache_dtype=inst_cfg["kv_cache_dtype"],
            npu_memory_utilization=inst_cfg["npu_memory_utilization"],
            reserve_full_isl=inst_cfg["reserve_full_isl"],
        ))

    # The derived KV capacity, not the utilization fraction, is what decides
    # memory pressure. It is per instance and only known once the schedulers
    # exist, so it gets its own section rather than a row in the input-config
    # block, which is printed before any of this is resolved.
    print_heading("KV Cache Initialization")
    print_markup("")
    # Pad only as far as the widest label, so the line stays inside the rule.
    pad = max(len(f"Instance [{i}]") for i in range(len(schedulers)))
    for inst_id, sched in enumerate(schedulers):
        pool = sched.memory.npu_pool
        label = f"Instance \\[{inst_id}]"
        print_markup(
            f"  \u2022 [cyan]{label:<{pad + 1}}[/cyan] : "
            f"{pool.num_blocks * pool.block_size} tokens / {pool.num_blocks} blocks "
            f"({pool.num_blocks * pool.bytes_per_block / GB_TO_BYTE:.2f} GiB/rank "
            f"at util {sched.memory.npu_memory_utilization:.2f})"
        )
    print_rule()

    # Controller for astra-sim process communication
    controller = Controller(total_npu)
    # Global Request Router
    router = Router(num_instances, schedulers, num_req, request_routing_policy)
    # Power Modeling if enabled
    if power_modeling:
        power_model = PowerModel(power_configs)
    else:
        power_model = None
    # Load requests into router (routed in real-time during simulation)
    if dataset != None:
        router.load_requests(dataset, enable_prefix_caching=any_prefix_caching, is_init=is_init)
    else:
        # Manually adding request (legacy: route all upfront)
        for i in range(16):
            for sched in schedulers:
                sched.add_request([i, sched.model, 64, 128, 0, i % num_instances])

    # Simulator start
    current = 0 # current tick of the system
    sys = 0 # current system id (NPU id)
    id = 0 # id of the request
    is_prefill_done = False # flag to check if prefill is done
    done_instance = [] # list of done instances
    done_inst_npus = [[] for _ in range(num_instances)]
    start_time = time()
    last_end_time = [0 for _ in range(num_instances)]
    last_calc_time = [0 for _ in range(num_instances)]
    waiting_request = [False for _ in range(num_instances)]

    # Calculating Simulator's Throughput
    throughput = []
    prompt_th = 0    # Avg Prompt Throguhput per Sec
    gen_th = 0       # Avg Generation Throughput per Sec
    last_log = 0    # last logged time
    FREQ = 1000_000_000 # 1 GHz (1e9 Hz)
    INTERVAL = log_interval*FREQ
    # Per-interval token counts -> tokens/s, so 1/log_interval. Floor division
    # collapsed to 0 for any --log-interval > 1, which zeroed every logged
    # throughput and made the summary line divide by zero.
    RATIO = FREQ/INTERVAL
    total_prompt = 0
    total_gen = 0
    total_latency = 0
    req_cnt = 0

    # Set Event Handler that loop with INTERVAL time until first request arrive (for all instances)
    first_arival_time = router.get_first_arrival_time()
    if INTERVAL > first_arival_time:
        event_time = first_arival_time
    else:
        event_time = INTERVAL
    event_trace = generate_event(int(event_time), inputs_root=run_paths.inputs_root)
    # Make Chakra Grapth
    generate_graph(None, None, total_npu, event=True, inputs_root=run_paths.inputs_root,
                   save_trace_text=args.save_trace_text, trace=event_trace)
    # set first workload file
    workload = get_workload(None, None, event=True, inputs_root=run_paths.inputs_root)
    # run subprocess
    # VeritX: our analytical/BookSim binaries require --remote-memory-configuration
    # (upstream's newer binaries made it optional/renamed — revisit on backend swap).
    astra_args = [binary, "--workload-configuration="+workload, "--system-configuration="+system, "--network-configuration="+network, "--memory-configuration="+memory, "--remote-memory-configuration="+memory]
    if network_backend == 'booksim':
        _certified = resolve_certified_backend()
        if _certified is not None:
            # VeritX B3.7c: flit width comes from PacketFormatArtifact via
            # the exact bits->bytes conversion. 64 BITS must be 8 BYTES.
            astra_args.append(
                "--booksim2-flit-bytes=%d" % _certified["flit_bytes"])
            # Logical dims are an exact certified execution input; missing
            # or malformed data fails closed (no silent flat fallback).
            astra_args.append("--physical-dims=" + ",".join(
                str(x) for x in _certified["physical_dims"]))
        else:
            # Legacy path (non-certified): keep historical behavior.
            # VeritX forward-port: flit 64B reduces packet count 4x for large LLM
            # AllReduces (16MB -> 4K pkts -> 1K pkts).
            astra_args.append("--booksim2-flit-bytes=64")
            # VeritX: pass LOGICAL topology dims (trace dim numbering) so trace
            # collectives scoped to dim>=1 (EP/DP) map onto real Sys dims instead
            # of being silently dropped. network.yml stays physical/flat.
            try:
                _ldims_path = os.path.join(run_paths.inputs_root, "logical_dims.json")
                with open(_ldims_path) as _lf:
                    _ndims = json.load(_lf).get("dims")
                if _ndims and all(isinstance(x, int) and x >= 1 for x in _ndims):
                    astra_args.append("--physical-dims=" + ",".join(str(x) for x in _ndims))
            except Exception:
                pass
        # --- BookSim backend: optionally force replay-only mode ---
        # When replay-only=1, ASTRA-sim replays trace durations directly without
        # sending packets through BookSim. REQUIRED when the ASTRA-sim topology
        # (e.g. ring) does not match the BookSim topology (e.g. mesh), because
        # mismatched ring collectives over mesh cause deadlock. Disable with
        # --no-booksim-replay-only for full cycle-accurate network simulation
        # (requires matching topologies).
        if args.booksim_replay_only:
            if _certified is not None:
                # VeritX B3.7c: replay is not network execution. A certified
                # run must never masquerade as one.
                raise SystemExit(
                    "error: " + CERTIFIED_BACKEND_ENV + " refuses "
                    "--booksim-replay-only: replay is not network execution")
            try:
                with open(system, 'r') as _f:
                    _j = json.load(_f)
                _j["replay-only"] = 1
                _j["roofline-enabled"] = 0
                with open(system, 'w') as _f:
                    json.dump(_j, _f, indent=2)
            except Exception:
                pass
    if start_npu_ids != "":
        astra_args.append("--start-npu-ids="+start_npu_ids)
    if end_npu_ids != "":
        astra_args.append("--end-npu-ids="+end_npu_ids)
    if network_backend == 'ns3':
        astra_args.append("--logical-topology-configuration="+astra_sim+"/inputs/logical_topology/logical_8nodes_1D.json")
    import os as _os2
    _dbg_err = open(_os2.getenv("VERITX_BACKEND_STDERR", "/dev/null"), "w") if _os2.getenv("VERITX_BACKEND_STDERR") else subprocess.PIPE
    p = subprocess.Popen(astra_args, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=_dbg_err, universal_newlines=True)
    # VeritX forward-port: drain the binary's stderr in a background thread so
    # it can never fill the pipe and deadlock the binary mid-run (the backend
    # logs ~510B/round; the main loop only reads stdout, so without this the
    # pipe fills around round ~1500 and the run stalls with both sides idle).
    # Forwards the collective-execution ledger ([LEDGER] lines, gated by
    # VERITX_LEDGER in the binary) plus fail-loud error/panic lines; routine
    # chatter is discarded. NOTE: with the drain active, p.stderr is consumed
    # live, so the early-death diagnostic below gets little — the forwarded
    # lines already went to our stderr.
    if _dbg_err is subprocess.PIPE:
        import threading as _threading
        import re as _re
        _stderr_forward_re = _re.compile(r"panic|assert|error|DRAIN_STUCK", _re.IGNORECASE)
        def _drain_stderr():
            try:
                while True:
                    line = p.stderr.readline()
                    if not line:
                        break
                    if line.startswith("[LEDGER]") or _stderr_forward_re.search(line):
                        import sys as _s
                        _s.stderr.write(line)
            except Exception:
                pass
        _threading.Thread(target=_drain_stderr, daemon=True).start()

    # DP group synchronization: defer trace generation until all members have scheduled
    # dp_groups maps dp_group_name -> list of instance_ids
    dp_groups = {}
    for inst in instances:
        dg = inst.get("dp_group")
        if dg is not None:
            dp_groups.setdefault(dg, []).append(inst["instance_id"])
    # Reverse lookup: instance_id -> dp_group_name
    inst_dp_group = {}
    for dg, members in dp_groups.items():
        for inst_id in members:
            inst_dp_group[inst_id] = dg
    # Batches waiting at the DP barrier: per group, per member, a FIFO. With
    # pp_size > 1 a member can have up to pp_size batches awaiting their round,
    # and vLLM pairs the members' forwards in order -- rank A's j-th forward
    # joins the same collective as rank B's j-th. A single slot per member
    # silently dropped the earlier batch, which then never got a workload_name,
    # so the instance's other NPUs retried joining it forever.
    dp_pending = {dg: defaultdict(deque) for dg in dp_groups}  # dg -> {inst: deque[(batch, node_id)]}
    # Workloads pre-generated by a DP round, keyed by the NPU that opened that
    # member's batch. Retained as a no-op: a DP round's graph is one shared
    # folder for every member, so the round is dispatched on the poll that
    # completes the barrier and nothing is ever queued here anymore (queuing
    # the same shared path for each opener re-ran the whole round per write).
    dp_ready_workloads = defaultdict(deque)  # npu_id -> deque[workload_path]

    # ----------------------------------- Start simulation loop ------------------------------------
    print_markup("[sim.heading]▶ Starting simulation...[/]\n")
    flush.stdout.flush()

    # Starting simulation, one while loop processes one iteration
    _backend_died_early = False  # VeritX: fail loudly if backend EOFs
    _rr_next = 0  # VeritX (booksim): round-robin cursor across instances
    _veritx_last_served = None  # VeritX: instance served last round (fairness rotation)
    # VeritX: bare-pass livelock counter. Consecutive no-op "pass" rounds
    # (nothing retired, routed, or time-advanced) mean scheduler and backend
    # are ping-ponging with no progress — fail loudly instead of spinning
    # forever. Threshold overridable for testing (VERITX_SPIN_ABORT).
    _veritx_idle_rounds = 0
    _veritx_spin_abort = int(os.environ.get("VERITX_SPIN_ABORT", "100000"))
    # VeritX: per-iteration phase timing (VERITX_ROUND_TIMING=1). Splits each
    # serving<->backend round into backend_wait (blocked in read_wait) vs
    # sched (parse/route/rebind/retire) vs gen_dispatch (schedule + trace /
    # graph generation + write_flush). Plain stdout prints every 10 rounds
    # so timeout-killed runs still report. Zero overhead when unset.
    from time import perf_counter as _vperf
    _vround_timing = bool(os.environ.get("VERITX_ROUND_TIMING"))
    _vround_n = 0
    _vround_bw = 0.0
    _vround_sched = 0.0
    _vround_gen = 0.0
    _vround_s0 = 0.0
    _vround_lb = 0.0
    _vround_ls = 0.0
    _vbr = defaultdict(int)  # dispatch-arm histogram (same flag)
    # VeritX: livelock progress markers (always-on, ints only). The old reset zeroed the detector every lap:
    # pass-echo replies carry sys/cycle lines by construction, and the
    # increment required an exact "pass" shape while "pass {deadline}"/
    # "pass -1" skipped it. Progress is now: backend clock advanced,
    # a batch dispatched, requests routed/retired, or the deadline jump
    # moved time. Rounds with none of those count up whatever the message
    # shape; legitimate waiting always advances the clock, so it never
    # counts. Threshold still VERITX_SPIN_ABORT (default 100000).
    _vprog_round = 0
    _vprog_last = 0
    _vprog_last_current = None
    # VeritX: liveness observation (review-directed). PURE instrumentation:
    # one snapshot per round, no control-flow effect. Reports are emitted
    # only when explicitly requested (VERITX_LIVENESS_DUMP=n — every n
    # unchanged rounds) or when an existing failure path fires (EOF with
    # work, spin abort) — the observation never aborts anything itself.
    _lv_probe = _LivenessProbe()
    _lv_dump_every = int(os.environ.get("VERITX_LIVENESS_DUMP", "0"))
    _lv_last_cmd = "<startup>"  # logical command pending/issued last

    def _issue(cmd):
        """Single backend-send seam (VeritX liveness, behavior-neutral).

        EVERY command to the backend flows through here — workload
        paths, pass variants, done, exit — so the probe records the
        COMPLETE logical command, not a normalized category. Closure
        over this loop's state: same string, same order, same call.
        """
        nonlocal _lv_last_cmd
        _lv_last_cmd = cmd
        controller.write_flush(p, cmd)
    while True:
        if _vround_timing:
            _vround_now = _vperf()
            if _vround_n > 0:
                _vround_gen += (_vround_now - _vround_s0) - _vround_lb - _vround_ls
                if _vround_n % 10 == 0:
                    _vbr_other = _vround_n - sum(_vbr.values())
                    _vbr_top = sorted(_vbr.items(), key=lambda kv: -kv[1])[:5]
                    _vbr_txt = ", ".join(f"{k}={v}" for k, v in _vbr_top)
                    if _vbr_other:
                        _vbr_txt += f", other={_vbr_other}"
                    print(f"[VERITX_TIMING] rounds={_vround_n} "
                          f"backend_wait={_vround_bw:.1f}s sched={_vround_sched:.1f}s "
                          f"gen_dispatch={_vround_gen:.1f}s arms:[{_vbr_txt}]", flush=True)
            _vround_n += 1
            _vround_s0 = _vround_now
        _vprog_round += 1
        round_done_npus = set()  # backend completion evidence this round
        out = controller.read_wait(p)
        if len(out) <= 1 and out[0] == '':
            # VeritX: backend EOF — died or closed the pipe. Only a failure
            # if work remains (pending/deferred requests or in-flight
            # batches); a post-completion EOF is a clean shutdown.
            _work_remains = (
                router.has_pending_requests()
                or router.has_deferred_sessions()
                or any(len(sch.inflight) > 0 for sch in schedulers)
            )
            if _work_remains:
                _backend_died_early = True
                try:
                    if p.poll() is not None and p.stderr:
                        _serr = p.stderr.read()
                        if _serr:
                            print(f"[LLMServingSim] backend stderr:\n{_serr[-3000:]}", flush=True)
                except Exception:
                    pass
                print("[LLMServingSim] ERROR: backend pipe exhausted with work "
                      f"remaining ({req_cnt} requests retired) — results below "
                      f"are incomplete.", flush=True)
                # VeritX: attach the latest liveness observation so the
                # failure says WHICH state stopped changing first (§28).
                print(_liveness_attach(_lv_probe, "backend EOF"), flush=True)
            break
        if _vround_timing:
            _vround_s1 = _vperf()
            _vround_lb = _vround_s1 - _vround_s0
            _vround_bw += _vround_lb
        if network_backend in ('booksim', 'analytical'):
            # Both backends return a burst containing one completion per NPU.
            # Parse that burst once so analytical's iteration format and
            # BookSim's workload format share the same evidence path.
            _joined_out = "\n".join(out)
            out_dict = controller.parse_output(_joined_out)
            round_completions = controller.parse_all_completions(_joined_out)
        else:
            out_dict = controller.parse_output(out[-2])
            round_completions = controller.parse_all_completions(out[-2])

        if out_dict != None:
            reported_sys = out_dict['sys']
            sys = reported_sys
            id = out_dict['id']
            current = out_dict['cycle']
            # Preserve the backend-reported NPU before instance rebinding can
            # change `sys`; completion evidence must never be credited to the
            # scheduler-selected instance.
            # Progress marker: backend clock moved. NOTE: no counter reset
            # here — pass-echo replies parse too, and resetting on "any
            # reply" defeated the detector (reset won every lap by order).
            if _vprog_last_current is None or current != _vprog_last_current:
                _vprog_last_current = current
                _vprog_last = _vprog_round

        # Route newly arrived requests to instances based on current load
        round_done_npus.update(record['sys'] for record in round_completions)
        _routed_now = 0
        if dataset is not None:
            _routed_now = router.route_arrived_requests(current)

        instance_id = npu2inst_mapping[sys]  # get instance id from NPU id
        node_id = inst2node_mapping[instance_id] # get node id from instance id

        # VeritX (booksim/analytical backends): both report per-round
        # completion only, so the parse lands on a single NPU (sys 0 from the
        # joined output) and an idle instance's member may never be polled —
        # a DP quorum could never assemble. Fall back to another instance
        # when the reported one is fully empty OR its newest batch is still
        # waiting for DP quorum (unquorate — serving it again cannot
        # progress). DP partners are preferred (they unblock the quorum);
        # otherwise any instance with queued work. Served via its first NPU.
        if network_backend in ('booksim', 'analytical') and num_instances > 1:
            def _veritx_needs(_iid):
                if not schedulers[_iid].is_request_empty():
                    return True
                _dg = inst_dp_group.get(_iid)
                return bool(_dg is not None
                            and any(dp_pending[_dg][i] for i in dp_groups[_dg]))
            def _veritx_blocked(_iid):
                _inf = schedulers[_iid].inflight
                if not _inf:
                    return False
                _dg = inst_dp_group.get(_iid)
                if _dg is None:
                    return False
                _newest = _inf[-1]
                return any(_newest is _qb
                           for _dq in dp_pending[_dg].values()
                           for (_qb, _qn) in _dq)
            if not _veritx_needs(instance_id) or _veritx_blocked(instance_id):
                _dg0 = inst_dp_group.get(instance_id)
                _cands = []
                if _dg0 is not None:
                    _cands += [i for i in dp_groups[_dg0] if i != instance_id]
                _cands += [i for i in range(num_instances)
                           if i != instance_id
                           and i not in _cands and _veritx_needs(i)]
                for _cand in _cands:
                    instance_id = _cand
                    node_id = inst2node_mapping[_cand]
                    sys = inst2npu_mapping[_cand]
                    break
            # VeritX: fairness rotation. Reports pin `sys` to the NPU that
            # ran (usually sys 0), so with continuous work on one instance
            # the others starve: their queues fill but schedule() is never
            # called for them, and a premature per-instance "done" then
            # kills the shared binary with their work still queued (clean
            # EXIT:0 with missing requests). If we'd serve the same instance
            # twice in a row while another needs service, hand this round
            # to the other (DP partner states already handled above; this
            # only fires when the rebind left service unmoved).
            if instance_id == _veritx_last_served:
                _others = [i for i in range(num_instances)
                           if i != instance_id and _veritx_needs(i)]
                if _others:
                    _pick = _rr_next if _rr_next in _others else _others[0]
                    instance_id = _pick
                    node_id = inst2node_mapping[_pick]
                    sys = inst2npu_mapping[_pick]
            _veritx_last_served = instance_id
            _rr_next = (instance_id + 1) % num_instances

        # add stanby energy consumption for power modeling
        if power_modeling and sys == inst2npu_mapping[instance_id] and waiting_request[instance_id]:
            power_model.add_npu_standby_energy_consumption(instances[instance_id]["hardware"], node_id, current,
                        last_end_time[instance_id], last_calc_time[instance_id], num_npus=instances[instance_id]["num_npus"])
            last_calc_time[instance_id] = current

        # mark latest end time of the first NPU in the instance
        # An instance can span multiple NPUs. Only update end-time when sys is the first NPU of the instance.
        # waiting_request[instance_id] = True means the instance has no batch to run (idle).
        if sys == inst2npu_mapping[instance_id] and not waiting_request[instance_id]:
            last_end_time[instance_id] = current
            waiting_request[instance_id] = True

        # check request is done
        if network_backend in ('booksim', 'analytical'):
            # VeritX: the BookSim/analytical finish lines carry no batch
            # identity (just sys/cycle), so retire by scheduler state. A
            # batch still sitting
            # in a dp_pending quorum deque was never dispatched — retiring it
            # on a pass-echo requeues requests every round (DP livelock). Walk
            # back to the youngest dispatched one. batch_id+1 because new
            # add_done() decrements before matching.
            def _veritx_dispatched(_b, _iid):
                _dg = inst_dp_group.get(_iid)
                if _dg is None:
                    return True
                for _dq in dp_pending[_dg].values():
                    for (_qb, _qn) in _dq:
                        if _qb is _b:
                            return False
                return True
            _cand = None
            for _b in reversed(schedulers[instance_id].inflight):
                if _veritx_dispatched(_b, instance_id):
                    _cand = _b
                    break
            if _cand is not None:
                prompt_t, gen_t, finished_reqs = schedulers[instance_id].add_done(
                    _cand.batch_id + 1, sys, current)
            else:
                prompt_t, gen_t, finished_reqs = 0, 0, []
        else:
            prompt_t, gen_t, finished_reqs = schedulers[instance_id].add_done(id, sys, current)
        # add tokens in throughput
        prompt_th += prompt_t
        total_prompt += prompt_t
        gen_th += gen_t
        total_gen += gen_t
        # count only finished requests
        req_cnt += len(finished_reqs) if instances[instance_id]["pd_type"] != "prefill" else 0

        # Notify router of completed requests for dependency chain release
        if instances[instance_id]["pd_type"] != "prefill":
            for req in finished_reqs:
                router.notify_request_completed(req.id, current)

        # Add prefill ended requests to decode instance
        if instances[instance_id]["pd_type"] == "prefill" and len(finished_reqs) > 0:
            router.transfer_prefill_request(finished_reqs)

        # VeritX (booksim/analytical backends): both emit one finish line per
        # NPU per round but the main path above only retires the leading sys.
        # Feed every non-leading line through the same add_done + accounting
        # path (needed for TP>1: a batch retires only when all NPUs report).
        if network_backend in ('booksim', 'analytical'):
            for extra in round_completions:
                if extra['sys'] != reported_sys:
                    _e_inst = npu2inst_mapping.get(extra['sys'])
                    if _e_inst is None:
                        continue
                    round_done_npus.add(extra['sys'])
                    # VeritX: same dispatched-only rule as the main path.
                    _e_cand = None
                    for _b in reversed(schedulers[_e_inst].inflight):
                        _e_dg = inst_dp_group.get(_e_inst)
                        _e_queued = False
                        if _e_dg is not None:
                            for _dq in dp_pending[_e_dg].values():
                                for (_qb, _qn) in _dq:
                                    if _qb is _b:
                                        _e_queued = True
                                        break
                                if _e_queued:
                                    break
                        if not _e_queued:
                            _e_cand = _b
                            break
                    if _e_cand is not None:
                        _ep, _eg, _ef = schedulers[_e_inst].add_done(
                            _e_cand.batch_id + 1, extra['sys'], extra['cycle'])
                    else:
                        _ep, _eg, _ef = 0, 0, []
                    prompt_th += _ep
                    total_prompt += _ep
                    gen_th += _eg
                    total_gen += _eg
                    if instances[_e_inst]["pd_type"] != "prefill":
                        req_cnt += len(_ef)
                        for _r in _ef:
                            router.notify_request_completed(_r.id, extra['cycle'])
                    elif len(_ef) > 0:
                        router.transfer_prefill_request(_ef)

        # An NPU that opened a DP round owes ASTRA-Sim that round's graph, and it
        # has to be handed over before the scheduler may open anything new. vLLM
        # schedules and dispatches in one step (``schedule()`` then
        # ``execute_model()`` inside ``step_with_batch_queue``), so a scheduled
        # batch is never left un-dispatched. A DP batch has to break that up --
        # its graph cannot be emitted until every member has joined the barrier
        # and the padded ``max_total_len`` is known -- so the invariant to keep is
        # that the dispatch still lands before the next schedule for this NPU.
        # Without it, at pp_size > 1 the NPU built its next microbatch on the very
        # poll that should have handed over the previous one, and the round after
        # that overwrote the entry: the first graph never ran, and the other
        # pipeline stage blocked forever on a RECV that never came.
        if _vround_timing:
            _vround_s2 = _vperf()
            _vround_ls = _vround_s2 - _vround_s1
            _vround_sched += _vround_ls
        pending = dp_ready_workloads.get(sys)
        new_req = None if pending else schedulers[instance_id].schedule(current, sys, id)
        if new_req is not None:
            _vprog_last = _vprog_round  # dispatch = forward motion
        responded = False  # track whether we already sent a response to ASTRA-Sim

        # Hand over a workload pre-generated by a DP round this NPU opened.
        if pending:
            if _vround_timing:
                _vbr['pending_handover'] += 1
            _issue(pending.popleft())
            if not pending:
                del dp_ready_workloads[sys]
            responded = True
        # DP group: truly idle instance (no inflight batch) — create dummy batch so ALLTOALL syncs
        # An idle DP member has to keep pace with a busy one. vLLM requires every
        # rank of a DP group to run the same number of forwards, and with PP a
        # rank has pp_size microbatches in flight at once -- so the gate here is
        # schedule()'s own pipeline-depth rule, not "nothing in flight". Gating on
        # == 0 lets the member holding the real request run ahead by up to
        # pp_size batches, and the dp_pending barrier then waits for a round the
        # idle members can never join.
        #
        # Any NPU of the instance may open the round, not just its first. Which
        # NPU ASTRA-Sim asks about is not ours to choose, and an instance whose
        # start NPU is busy or starved would otherwise never contribute a dummy
        # -- the barrier then waits on a member that cannot answer. An empty
        # ``dp_pending[dg][instance_id]`` keeps it to one dummy per member per
        # round -- the member has nothing queued, so it has not yet joined the
        # round being assembled -- which is what the start-NPU test used to be
        # standing in for.
        elif (new_req is None and instance_id in inst_dp_group
              and not dp_pending[inst_dp_group[instance_id]][instance_id]
              and len(schedulers[instance_id].inflight) < schedulers[instance_id].pp_size):
            dg = inst_dp_group[instance_id]
            if any(dp_pending[dg][i] for i in dp_groups[dg]):
                # Emit a 1-token dummy; the uniform pad-to-max pass below
                # brings it (and any undersized real peers) up to the
                # group's max_total_len, matching vLLM's CUDA-graph DP padding.
                logger.debug(f"Instance {instance_id} is idle but DP group {dg} has pending batches. Creating dummy batch for synchronization.")
                dummy = Batch(schedulers[instance_id].get_batch_id(), instances[instance_id]["model_name"],
                              1, 1, [1], [], 0, 1, [], [], [1], current, 0)
                dummy.fired.append(sys)
                # Register it the way scheduler._build_batch registers a real
                # batch. Without this the instance's other NPUs get nothing:
                # schedule() routes them to _schedule_existing, which searches
                # inflight, finds no dummy, and they fall through to "pass" --
                # so their .et never runs and the group's EP collective blocks
                # forever. Invisible at tp=pp=1, where the start NPU is the only
                # NPU an instance owns.
                schedulers[instance_id].inflight.append(dummy)
                if _vround_timing:
                    _vbr['dummy_created'] += 1
                dp_pending[dg][instance_id].append((dummy, inst2node_mapping[instance_id]))

                if all(dp_pending[dg][i] for i in dp_groups[dg]):
                    # Every DP member has a batch queued — take one from each,
                    # oldest first, and pad them to the group's max (vLLM
                    # CUDA-graph DP padding) before generating.
                    round_batches = {i: dp_pending[dg][i].popleft() for i in dp_groups[dg]}
                    own_workload = None
                    config = get_config(instances[instance_id]["model_name"])
                    max_total_len = max(b.total_len for b, _ in round_batches.values())
                    for b, _ in round_batches.values():
                        _pad_batch_to_max(b, max_total_len)
                    # MoE AG/RS comm size is anchored to ``max_total_len``
                    # (not ``max × group_size``). The trace generator divides
                    # this by ep_total internally for the per-rank AG chunk
                    # and uses the same value for the RS pre-scatter buffer.
                    # Empirically this matches real NCCL AG/RS bandwidth on
                    # PCIe 5.0 at the same ``link_bw`` that already calibrates
                    # AllReduce — i.e. ASTRA-Sim's Ring half-duplex model
                    # ends up correct for AR but 2× over real AG/RS, and the
                    # "× group_size" we used previously stacked the two errors.
                    sum_total_len = max_total_len

                    # Shared workload folder for all DP members
                    first_inst_id = dp_groups[dg][0]
                    first_batch = round_batches[first_inst_id][0]
                    dp_workload_name = f'{instances[first_inst_id]["hardware"]}/{instances[first_inst_id]["model_name"]}/dp_{dg}_batch{first_batch.batch_id}'

                    for inst_id in dp_groups[dg]:
                        batch, nid = round_batches[inst_id]
                        batch.workload_name = dp_workload_name
                        inst = instances[inst_id]
                        inst_cfg = instance_runtime_configs[inst_id]
                        trace_data = generate_trace(batch, inst["hardware"], inst["tp_size"], inst["pp_size"],
                                       inst["local_ep"], inst["ep_total"], inst["pd_type"],
                                       nid, inst_id,
                                       inst_cfg["max_num_batched_tokens"], inst_cfg["max_num_seqs"],
                                       placement[inst_id], block_mode_on[inst_id],
                                       expert_routing_policy, inst_cfg["enable_prefix_caching"],
                                       inst_cfg["enable_attn_offloading"],
                                       power_model, pim_models[nid],
                                       inst_cfg["enable_sub_batch_interleaving"], inst_cfg["fp"],
                                       dtype=inst_cfg["dtype"], kv_cache_dtype=inst_cfg["kv_cache_dtype"],
                                       tp_dim=inst.get("tp_dim"), ep_dim=inst.get("ep_dim"),
                                       dp_sum_total_len=sum_total_len,
                                       enable_block_copy=inst_cfg["enable_block_copy"],
                                       inputs_root=run_paths.inputs_root)
                        generate_graph(batch, inst["hardware"], inst["num_npus"], nid,
                                       inst_id, inst2npu_mapping[inst_id],
                                       inst_cfg["enable_local_offloading"],
                                       workload_name=dp_workload_name,
                                       inputs_root=run_paths.inputs_root,
                                       save_trace_text=args.save_trace_text,
                                       trace=trace_data)
                        # ``fired[0]`` is the NPU that opened this member's
                        # round -- the one that owes ASTRA-Sim its graph. That is
                        # normally this very poll, and then it is answered
                        # directly. With pp_size > 1 the round can instead pop a
                        # batch that another NPU of the instance opened, or an
                        # older one this NPU opened, so queue it for that NPU.
                        ready = get_workload(batch, inst["hardware"], inst_id,
                                             workload_name=dp_workload_name,
                                             inputs_root=run_paths.inputs_root)
                        # The round's graph is ONE shared folder for every DP
                        # member (dp_workload_name), so a single bare-path
                        # write runs it for all ranks — the opener NPU of each
                        # member's batch is irrelevant. Hand the shared path
                        # out exactly once, right here (first member wins);
                        # deferring it to the opener's later poll would write
                        # the same path again and re-run the whole round.
                        own_workload = ready if own_workload is None else own_workload

                    if own_workload is not None:
                        _issue(own_workload)
                    else:
                        _issue(_pass_response(router, current, state_changed=True))
                    responded = True
                else:
                    # Joined the round with a dummy; the round is not complete.
                    _issue(_pass_response(router, current, state_changed=True))
                    responded = True
        # runnable batch exists
        elif new_req is not None:
            # ``_build_batch`` returns a batch fired only by the NPU that built
            # it, so a longer ``fired`` means this poll joined a batch through
            # ``_schedule_existing``. With DP groups any NPU of an instance may
            # open a round (the idle-member dummy in particular), so the start
            # NPU can arrive here holding a batch it did not build -- it has to
            # be served like any other joiner, not registered into the round a
            # second time.
            built_here = len(new_req.fired) == 1  # implies sys is the start NPU
            if built_here:  # first NPU of the instance, opening a new batch
                waiting_request[instance_id] = False
                instance = instances[instance_id]
                dg = inst_dp_group.get(instance_id)

                if dg is not None:
                    # DP group: defer trace generation until all members scheduled
                    dp_pending[dg][instance_id].append((new_req, node_id))

                    if all(dp_pending[dg][i] for i in dp_groups[dg]):
                        # Every DP member has a batch queued — take one from
                        # each, oldest first, and pad them to the group's max
                        # (vLLM CUDA-graph DP padding) so smaller batches gain
                        # dummy decodes that all layers still compute over.
                        round_batches = {i: dp_pending[dg][i].popleft() for i in dp_groups[dg]}
                        own_workload = None
                        config = get_config(instance["model_name"])
                        max_total_len = max(b.total_len for b, _ in round_batches.values())
                        for b, _ in round_batches.values():
                            _pad_batch_to_max(b, max_total_len)
                        # See twin block above: anchor MoE comm to max_total_len
                        # (no group-size multiplier).
                        sum_total_len = max_total_len

                        # Shared workload folder for all DP members
                        first_inst_id = dp_groups[dg][0]
                        first_batch = round_batches[first_inst_id][0]
                        dp_workload_name = f'{instances[first_inst_id]["hardware"]}/{instances[first_inst_id]["model_name"]}/dp_{dg}_batch{first_batch.batch_id}'

                        for inst_id in dp_groups[dg]:
                            batch, nid = round_batches[inst_id]
                            batch.workload_name = dp_workload_name
                            inst = instances[inst_id]
                            inst_cfg = instance_runtime_configs[inst_id]
                            trace_data = generate_trace(batch, inst["hardware"], inst["tp_size"], inst["pp_size"],
                                           inst["local_ep"], inst["ep_total"], inst["pd_type"],
                                           nid, inst_id,
                                           inst_cfg["max_num_batched_tokens"], inst_cfg["max_num_seqs"],
                                           placement[inst_id], block_mode_on[inst_id],
                                           expert_routing_policy, inst_cfg["enable_prefix_caching"],
                                           inst_cfg["enable_attn_offloading"],
                                           power_model, pim_models[nid],
                                           inst_cfg["enable_sub_batch_interleaving"], inst_cfg["fp"],
                                           dtype=inst_cfg["dtype"], kv_cache_dtype=inst_cfg["kv_cache_dtype"],
                                           tp_dim=inst.get("tp_dim"), ep_dim=inst.get("ep_dim"),
                                           dp_sum_total_len=sum_total_len,
                                           enable_block_copy=inst_cfg["enable_block_copy"],
                                           inputs_root=run_paths.inputs_root)
                            generate_graph(batch, inst["hardware"], inst["num_npus"], nid,
                                           inst_id, inst2npu_mapping[inst_id],
                                           inst_cfg["enable_local_offloading"],
                                           workload_name=dp_workload_name,
                                           inputs_root=run_paths.inputs_root,
                                           save_trace_text=args.save_trace_text,
                                           trace=trace_data)
                            # See the twin block above: the NPU that opened a
                            # member's round owes its graph, and that is normally
                            # this poll.
                            ready = get_workload(batch, inst["hardware"], inst_id,
                                                 workload_name=dp_workload_name,
                                                 inputs_root=run_paths.inputs_root)
                            # One shared folder per round (dp_workload_name);
                            # see the twin block above — dispatch it exactly
                            # once, here, not per opener NPU.
                            own_workload = ready if own_workload is None else own_workload

                        if own_workload is not None:
                            _issue(own_workload)
                        else:
                            _issue(_pass_response(router, current, state_changed=True))
                        responded = True
                    else:
                        # Waiting for other DP members — send pass
                        _issue(_pass_response(router, current, state_changed=True))
                        responded = True
                else:
                    # Independent instance: generate trace immediately
                    if _vround_timing:
                        _vbr['gen_new_req'] += 1
                    inst_cfg = instance_runtime_configs[instance_id]
                    trace_data = generate_trace(new_req, instance["hardware"], instance["tp_size"], instance["pp_size"],
                                   instance["local_ep"], instance["ep_total"],
                                   instance["pd_type"],
                                   node_id, instance_id,
                                   inst_cfg["max_num_batched_tokens"], inst_cfg["max_num_seqs"],
                                   placement[instance_id], block_mode_on[instance_id],
                                   expert_routing_policy, inst_cfg["enable_prefix_caching"],
                                   inst_cfg["enable_attn_offloading"], power_model, pim_models[node_id],
                                   inst_cfg["enable_sub_batch_interleaving"], inst_cfg["fp"],
                                   dtype=inst_cfg["dtype"], kv_cache_dtype=inst_cfg["kv_cache_dtype"],
                                   tp_dim=instance["tp_dim"], ep_dim=instance["ep_dim"],
                                   enable_block_copy=inst_cfg["enable_block_copy"],
                                   inputs_root=run_paths.inputs_root)
                    generate_graph(new_req, instance["hardware"], instance["num_npus"], node_id,
                                   instance_id, inst2npu_mapping[instance_id],
                                   inst_cfg["enable_local_offloading"],
                                   inputs_root=run_paths.inputs_root,
                                   save_trace_text=args.save_trace_text,
                                   trace=trace_data)
                    workload = get_workload(new_req, instance["hardware"], instance_id,
                                            inputs_root=run_paths.inputs_root)
                    _issue(workload)
            else:
                # Joined an existing batch: pick up its workload. workload_name
                # matters for a DP batch, whose graph lives in the group's shared
                # folder -- deriving the default instance<id>_batch<id> path here
                # points at a directory that was never written, and ASTRA-Sim
                # stalls on the missing .et instead of failing.
                #
                # A DP batch is in ``inflight`` from the moment its own instance
                # schedules it, but it is only stamped with the shared folder
                # when the *last* member of the group joins the barrier. In that
                # window ``_schedule_existing`` will hand it to this NPU with no
                # name yet, so wait instead of guessing a path: hand the claim
                # back and pass, and the batch is re-offered on a later poll once
                # the round is assembled. The batch is necessarily queued in
                # ``dp_pending`` already (it exists because an NPU of this
                # instance opened it), so passing here cannot stall the barrier.
                if sys == inst2npu_mapping[instance_id]:
                    waiting_request[instance_id] = False
                if instance_id in inst_dp_group and new_req.workload_name is None:
                    new_req.fired.remove(sys)
                    _issue(_pass_response(router, current, state_changed=True))
                    responded = True
                else:
                    workload = get_workload(new_req, instances[instance_id]["hardware"], instance_id,
                                            workload_name=new_req.workload_name,
                                            inputs_root=run_paths.inputs_root)
                    _issue(workload)

        # check time to store throughput (only print on start NPU to avoid transient states)
        if current > last_log + INTERVAL and sys == inst2npu_mapping[instance_id]:
            # store the prompt
            throughput.append((prompt_th*RATIO, gen_th*RATIO))
            last_log += INTERVAL
            log_time_str = f"[{last_log / FREQ:.1f}s]"
            log_time_len = len(log_time_str)
            log_indent = ' ' * log_time_len + '  '
            tree_indent = '├─'
            # Heartbeat timestamp stays in the terminal's default
            # colour — bright enough to scan, not so dim that it
            # disappears. (The per-log-record [HH:MM:SS.mmm] stays
            # dim via sim.time because it appears every other line.)
            print_markup(
                f"{log_time_str} "
                f"[blue]Avg prompt throughput: {prompt_th * RATIO:.1f} tokens/s,[/] "
                f"[blue]Avg generation throughput: {gen_th * RATIO:.1f} tokens/s[/]"
            )
            prompt_th = 0
            gen_th = 0

            ######### Per Instance Metrics #########

            for inst_id in range(num_instances):
                # len(running), not the size of the in-flight batch: the persistent
                # running set is the exact analogue of vLLM's num_running_reqs, which
                # is what bench compares this column against. The batch is only the
                # subset that fit in this step's token budget.
                running_reqs = len(schedulers[inst_id].running)
                waiting_reqs = len([req for req in schedulers[inst_id].waiting if req.arrival <= current])

                mem = schedulers[inst_id].memory
                npu_used_mb = mem.npu_used / MB_TO_BYTE
                npu_util = (mem.npu_used / mem.npu_mem * 100.0) if mem.npu_mem else 0.0

                line = (
                    f"{log_indent+tree_indent}Running Instance\\[{inst_id}]: "
                    f"{running_reqs} reqs, Waiting: {waiting_reqs} reqs, "
                    f"Total # {schedulers[inst_id].num_npus} NPUs, "
                    f"Each NPU Memory Usage {npu_used_mb:.2f} MB "
                    f"({npu_util:.3f} % Used)"
                )
                if schedulers[inst_id].enable_prefix_caching:
                    line += schedulers[inst_id].memory.format_prefix_info()
                print_markup(line)

            ######### Per Node Metrics #########
            if node2inst_mapping:
                num_nodes = len(node2inst_mapping)
                for i, (node_id, inst_ids) in enumerate(node2inst_mapping.items()):
                    node_cpu_usage = 0
                    inst_usage = []
                    if any_prefix_caching and enable_prefix_sharing and prefix_storage == "CPU":
                        node_cpu_usage = prefix_pools[node_id].used_bytes()
                    else:
                        for inst_id in inst_ids:
                            inst_cpu_usage = schedulers[inst_id].memory.cpu_used
                            node_cpu_usage += inst_cpu_usage
                            inst_usage.append(inst_cpu_usage)

                    cpu_util = (node_cpu_usage / (cpu_mem_size[node_id]*GB_TO_BYTE)) * 100
                    if prefix_storage != "CXL" and not power_modeling and i == num_nodes - 1:
                        tree_indent = '└─'
                    line = (
                        f"{log_indent+tree_indent}Node\\[{node_id}]: "
                        f"Total CPU Memory Usage {node_cpu_usage/MB_TO_BYTE:.2f} MB, "
                        f"{cpu_util:.3f} % Used "
                    )
                    if any_prefix_caching and enable_prefix_sharing and prefix_storage == "CPU":
                        line += prefix_pools[node_id].stats.format_prefix_info()

                    if (any_prefix_caching and enable_prefix_sharing and prefix_storage == "CPU") or (len(inst_ids) == 1):
                        print_markup(line)
                    else:
                        parts = []
                        for j, inst_cpu_usage in enumerate(inst_usage):
                            inst_cpu_util = (inst_cpu_usage / node_cpu_usage)*100 if node_cpu_usage else 0
                            parts.append(f"Instance\\[{inst_ids[j]}]: {inst_cpu_util:.2f} %")
                        print_markup(line + "(" + ", ".join(parts) + ")")

            ######### Per CXL Metrics #########
            if any_prefix_caching and prefix_storage == "CXL":
                if enable_prefix_sharing:
                    num_prefix_pool = len(prefix_pools)
                    for cxl_id, cxl_pool in enumerate(prefix_pools):
                        cxl_usage = cxl_pool.used_bytes()
                        cxl_util = cxl_pool.usage()
                        if not power_modeling and cxl_id == num_prefix_pool - 1:
                            tree_indent = '└─'
                        print_markup(
                            f"{log_indent+tree_indent}CXL\\[{cxl_id}]: "
                            f"Total CXL Device Memory Usage "
                            f"{cxl_usage/MB_TO_BYTE:.2f}MB, {cxl_util:.3f} % Used"
                        )
                else:
                    enabled_inst_ids = [
                        inst_id for inst_id, sched in enumerate(schedulers)
                        if sched.enable_prefix_caching
                    ]
                    for pos, inst_id in enumerate(enabled_inst_ids):
                        second_tier = schedulers[inst_id].memory.storage_pool
                        if second_tier is None:
                            continue
                        cxl_usage = second_tier.used_bytes()
                        cxl_util = second_tier.usage()
                        if not power_modeling and pos == len(enabled_inst_ids) - 1:
                            tree_indent = '└─'
                        print_markup(
                            f"{log_indent+tree_indent}CXL\\[0]/Instance\\[{inst_id}]: "
                            f"Total CXL Device Memory Usage {cxl_usage / MB_TO_BYTE:.2f} MB, "
                            f"{cxl_util:.3f} % Used"
                        )

            ######### Power Modeling #########
            if power_modeling:
                tree_indent = '└─'
                print_markup(
                    f"{log_indent+tree_indent}"
                    f"Avg power consumption: {power_model.get_current_power(current)} W"
                )
        # Completion is independent of scheduler visitation; sweep all
        # candidates using only backend evidence observed in this burst.
        _newly_done_instances = _sweep_completion(
            network_backend, num_instances, instance_id,
            decode_instance, is_prefill_done, schedulers, router,
            inst_dp_group, dp_groups, npu2inst_mapping, instances,
            done_inst_npus, done_instance, round_done_npus)

        # check if all prefill instances are done
        if len(done_instance) == len(prefill_instance):
            is_prefill_done = True

        # check if all instances are done
        if len(done_instance) == num_instances:
            for inst_idx in range(num_instances):
                schedulers[inst_idx].memory.free_prefix_cache()
                schedulers[inst_idx].memory.free_weight()

            # check memory leak before exit
            schedulers[inst_idx].memory.is_free()

            print_rule()
            print_markup("[sim.heading]▶ Exiting simulation...[/]\n")
            _issue("exit")
            break
        if _newly_done_instances:
            # The backend command is not instance-addressed: one ack per
            # round suffices even if several transitioned together.
            _issue("done") # make done instances to sleep
            responded = True
        if new_req is None and not responded:
            # If all instances are idle but deferred sessions have pending
            # requests with future arrival times (tool calls still running),
            # advance current time so the next iteration can pick them up.
            # Built before the jump below: _pass_response compares against
            # the clock ASTRA-Sim is actually at, not the one we skip to.
            pass_msg = _pass_response(router, current)
            if router.has_deferred_sessions() or router.has_pending_requests():
                next_arrival = router.get_next_pending_arrival()
                if next_arrival is not None and next_arrival > current:
                    current = next_arrival
                    _vprog_last = _vprog_round  # legitimate wait: clock moved
            # VeritX: no-progress spin detector. Counts rounds with no
            # retire, no route, no dispatch and no clock advance, whatever
            # the pass-message shape ("pass" / "pass {deadline}" /
            # "pass -1" all count). Thousands in a row mean scheduler and
            # backend are ping-ponging with no progress (e.g. a DP quorum
            # that can never assemble). Fail loudly with a state dump
            # instead of spinning forever.
            _is_bare_pass = (not finished_reqs
                             and not _routed_now
                             and _vprog_round > _vprog_last)
            if _is_bare_pass:
                # (last_command already holds pass_msg: every send,
                # including this round's upcoming _issue(pass_msg),
                # flows through the _issue seam.)
                _veritx_idle_rounds = _vprog_round - _vprog_last
                if _veritx_idle_rounds == 200:
                    print(f"[LLMServingSim] DEBUG first-stall round: "
                          f"out_tail={[ln[:100] for ln in out[-3:]]!r} "
                          f"out_dict={out_dict!r}", flush=True)
                if (_veritx_idle_rounds % 20000 == 0
                        or _veritx_idle_rounds >= _veritx_spin_abort):
                    _parts = []
                    for _iid in range(num_instances):
                        _sch = schedulers[_iid]
                        _dg = inst_dp_group.get(_iid)
                        _dplen = len(dp_pending[_dg][_iid]) if _dg is not None else 0
                        _parts.append(
                            f"i{_iid}:w={len(_sch.waiting)} r={len(_sch.running)} "
                            f"f={len(_sch.inflight)} q={_dplen}")
                    _r = router
                    print(f"[LLMServingSim] "
                          f"{'ERROR' if _veritx_idle_rounds >= _veritx_spin_abort else 'WARNING'}: "
                          f"{_veritx_idle_rounds} consecutive no-op pass rounds "
                          f"(current={current} retired={req_cnt} done={done_instance} "
                          f"pending={_r._pending_idx}/{len(_r._pending_requests)} "
                          f"deferred={len(_r._deferred_sessions)} "
                          f"svc_inst={instance_id} svc_sys={sys} "
                          f"new_req={'Y' if new_req is not None else 'N'} "
                          f"{' | '.join(_parts)})", flush=True)
                if _veritx_idle_rounds >= _veritx_spin_abort:
                    print("[LLMServingSim] ERROR: scheduler/backend livelock "
                          "(see state above) — aborting instead of spinning.",
                          flush=True)
                    # VeritX: liveness snapshot at abort — the observation
                    # distinguishes the stall class; it does not replace
                    # the abort (existing guardrail stays).
                    print(_liveness_attach(
                        _lv_probe, "spin abort"), flush=True)
                    try:
                        with open(os.environ.get(
                                "VERITX_LIVENESS_JSON", ""), "w") as _lf:
                            json.dump(_lv_probe.no_useful_progress_report(), _lf,
                                      indent=2, sort_keys=True)
                    except Exception:
                        pass
                    _backend_died_early = True  # non-zero exit + keep inputs
                    try:
                        _issue("exit")
                    except Exception:
                        pass
                    break
            else:
                _veritx_idle_rounds = 0
            _issue(pass_msg)
            if _vround_timing:
                _vbr['bare_pass'] += 1

        # VeritX: liveness observation — snapshot this round. Read-only;
        # every value here was already computed above. Cheap: one dataclass
        # + one tuple compare. Never aborts, never changes scheduling.
        try:
            _lv_disp = bool(finished_reqs) or _routed_now > 0 or new_req is not None
            _lv_probe.observe(_ProgressObservation(
                round=0,  # probe assigns the real round number
                sim_time=current,
                backend_cycle=(round_completions[-1]['cycle']
                               if round_completions else None),
                backend_completions=len(round_completions),
                retired_requests=req_cnt,
                pending_requests=(len(router._pending_requests)
                                  - router._pending_idx),
                deferred_requests=len(router._deferred_sessions),
                inflight_batches=sum(len(sch.inflight) for sch in schedulers),
                dispatched_this_round=_lv_disp,
                last_command=_lv_last_cmd,
                per_instance={
                    f"instance_{i}": {
                        "waiting": len(schedulers[i].waiting),
                        "running": len(schedulers[i].running),
                        "inflight": len(schedulers[i].inflight),
                        "dp_queued": (len(dp_pending[inst_dp_group[i]][i])
                                      if i in inst_dp_group else 0),
                    }
                    for i in range(num_instances)
                },
                backend_alive=(p.poll() is None),
                note=("dp_pending=" + str({dg: {i: len(q) for i, q in m.items()}
                                              for dg, m in dp_pending.items()}
                                         ) if dp_pending else ""),
            ))
            if (_lv_dump_every and _lv_probe.rounds_unchanged >= _lv_dump_every
                    and _lv_probe.rounds_unchanged % _lv_dump_every == 0
                    and _lv_probe.classify() != _LIVE_PROGRESS):
                print(f"[LIVENESS] {_lv_probe.render()}", flush=True)
        except Exception:  # instrumentation must never kill simulation
            pass

    # calculate simulation time
    end_time = time()
    total_time = end_time - start_time
    hours, remainder = divmod(total_time, 3600)
    minutes, seconds = divmod(remainder, 60)

    # VeritX: opt-in terminal liveness evidence (T5 baselines). Pure
    # observation print under an explicit env gate — never on by default,
    # never a behavioral change.
    if os.environ.get("VERITX_LIVENESS_DUMP"):
        try:
            print(f"[LIVENESS] final:\n{_lv_probe.render()}", flush=True)
        except Exception:
            pass

    # check all scheduled requests in astra-sim are well done
    controller.check_end(p)

    # calcuate prefix caching metrics
    total_requested_tokens = 0
    total_npu_hit_tokens = 0
    total_cpu_hit_tokens = 0
    if any_prefix_caching:
        for i in range(num_instances):
            if not schedulers[i].enable_prefix_caching:
                continue
            (temp_npu_a, temp_npu_b), (temp_cpu_a, temp_cpu_b) = schedulers[i].memory.return_prefix_info()
            if (not enable_prefix_sharing) and (prefix_storage != "None") and (temp_npu_a != temp_cpu_a):
                raise RuntimeError(f"Instance[{i}] prefix caching requested tokens mismatch between NPU ({temp_npu_a}) and CPU ({temp_cpu_a})")
            total_requested_tokens += temp_npu_a
            total_npu_hit_tokens += temp_npu_b
            if not enable_prefix_sharing:
                total_cpu_hit_tokens += temp_cpu_b

        if enable_prefix_sharing:
            for pool in prefix_pools:
                _, temp_cpu_b = pool.stats.return_prefix_info()
                total_cpu_hit_tokens += temp_cpu_b

    # This is total system's throughput
    total_latency = current/FREQ
    print_rule()
    print_markup("[sim.heading]▶ Simulation results...[/]\n")
    if _analytical_unaware:
        # VeritX: remind at the point of use — these clocks are optimistic.
        print_markup("[sim.tagline]Engine: congestion-UNaware analytical (N-dim lower bound, no congestion)[/]")
    if network_backend == 'booksim' and args.booksim_replay_only:
        # VeritX: replay-only replays recorded trace durations without
        # touching the fabric — cycle counts contain zero network simulation.
        print_markup("[sim.tagline]Engine: BookSim replay-only (trace durations replayed, no network simulation)[/]")
    print_markup(f"Total simulation time: {int(hours)}h {int(minutes)}m {seconds:.3f}s")
    print_rule("[sim.tagline]Throughput Results[/]")
    print_markup(f"Total requests:                                                     {req_cnt}")
    print_markup(f"Total clocks (ns):                                                  {current}")
    print_markup(f"Total latency (s):                                                  {total_latency:.3f}")
    # total_prompt is the vLLM prompt-throughput gauge: it counts every token
    # pushed through prefill, including prefix-cache hits and anything recomputed
    # after a preemption. Report the dataset input from the requests themselves
    # rather than by subtracting the recompute counter -- a request preempted
    # again mid-recompute is charged its full remaining work each time it is
    # re-admitted, so the two are not each other's complement.
    total_recompute = sum(s.recompute_tokens for s in schedulers)
    total_preempt = sum(s.num_preemptions for s in schedulers)
    total_input = sum(req.original_input for s in schedulers for req in s.done)
    print_markup(f"Total input tokens:                                                 {total_input}")
    if total_preempt:
        print_markup(f"Preemptions:                                                        {total_preempt}")
    if total_recompute:
        print_markup(f"Recomputed prompt tokens (preemption):                               {total_recompute}")
    print_markup(f"Total generated tokens:                                             {total_gen}")
    if total_latency > 0:
        print_markup(f"Request throughput (req/s):                                         {req_cnt/total_latency:.2f}")
        print_markup(f"Average prompt throughput (tok/s):                                  {total_prompt/total_latency:.2f}")
        print_markup(f"Average generation throughput (tok/s):                              {total_gen/total_latency:.2f}")
        print_markup(f"Total token throughput (tok/s):                                     {(total_prompt + total_gen)/total_latency:.2f}")
    else:
        # VeritX: early backend death reaches here with zero clocks —
        # report N/A instead of ZeroDivisionError after the ERROR above.
        print_markup(f"Request throughput (req/s):                                         N/A (no cycles)")
        print_markup(f"Average prompt throughput (tok/s):                                  N/A")
        print_markup(f"Average generation throughput (tok/s):                              N/A")
        print_markup(f"Total token throughput (tok/s):                                     N/A")
    print_markup(f"Throughput per {log_interval:g} sec (\\[prompt_throughput], \\[gen_throughput]): {throughput}")
    print_rule()
    if any_prefix_caching:
        print_rule("[sim.tagline]Prefix Caching Results[/]")
        print_markup(f"Total requested prompt tokens:                                      {total_requested_tokens}")
        print_markup(f"NPU prefix hit prompt tokens:                                       {total_npu_hit_tokens}")
        if total_requested_tokens > 0:
            print_markup(f"NPU prefix hit ratio (%):                                           {(total_npu_hit_tokens/total_requested_tokens)*100:.2f}")
            if prefix_storage != "None":
                print_markup(f"{prefix_storage} prefix hit prompt tokens:                                       {total_cpu_hit_tokens}")
                print_markup(f"{prefix_storage} prefix hit ratio (%):                                           {(total_cpu_hit_tokens/total_requested_tokens)*100:.2f}")
            print_markup(f"Total prefix hit ratio (%):                                         {((total_npu_hit_tokens+total_cpu_hit_tokens)/total_requested_tokens)*100:.2f}")
        else:
            print_markup("NPU prefix hit ratio (%):                                           N/A (no requests tracked)")
        print_rule()
    if power_modeling:
        print_rule("[sim.tagline]Power Modeling Results[/]")
        total_energy = power_model.get_final_energy(current)
        print_markup(f"Total energy consumption (kJ):                                      {total_energy/1000:.2f}")
        # Each node results
        power_model.print_power_summary()
        print_markup(f"Power per {log_interval:g} sec (W): {power_model.power_time_series}")
        print_rule()
    # Each instacne results
    for i in range(num_instances):
        print_rule(f"[sim.tagline]Instance \\[{i}][/]")
        schedulers[i].print_result()
        print_rule()

    # Important informations about metrics
    # The TTFT (Time to First Token) in our simulator differs from vllm.
    # While vllm measures TTFT as the time when the client receives the first token,
    # Our simulator measures it as the time when the computation of the first token is completed.
    # Therefore, vllm gets much more higher TTFT.
    # (Ref: https://docs.vllm.ai/en/latest/design/metrics.html?utm_source=chatgpt.com#interval-calculations-vs-preemptions)

    if output_file != None:
        print(f"Saving each request's information to output file: {output_file}")
        for i in range(num_instances):
            schedulers[i].save_output(output_file, is_append=False if i == 0 else True)

    # --save-trace-text writes the text into the run directory, so keeping it
    # is implied: producing the text and then deleting it would be pointless.
    # VeritX: never clean up after an early backend death — keep the evidence.
    if not (args.keep_inputs or args.save_trace_text or _backend_died_early):
        _cleanup_inputs_root(run_paths, logger)

    if _backend_died_early:
        # VeritX: non-zero exit so wrappers/CI notice.
        import sys as _sys
        _sys.exit(1)


if __name__ == "__main__":
    # For simulation time breakdown
    # profiler = Profiler()
    # profiler.start()
    main()
    # profiler.stop()
    # print(profiler.output_text(unicode=True, color=True))
