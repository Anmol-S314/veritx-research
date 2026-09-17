"""veritx_dse.core.serving — serving-result identity (PR6 Slice B seam).

One concept: *how* a serving result was produced. A run that replays
trace durations exits 0 with plausible TTFT/TPOT but simulated no
network — so the execution mode rides with every serving result as
data, and the golden gate is a pure predicate over it.

Deliberately concrete: no Runner/Backend classes, no analytical
generalization (that is PR7's slice). Shared mechanics get extracted
only after slices B and C expose what actually repeats.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

# PR6 §17.4: the only two execution modes a serving result may claim.
# REAL_SIMULATION = packets/flits contended in a network backend.
# TRACE_REPLAY   = recorded durations replayed, fabric untouched
#                  (downstream `--booksim-replay-only`, the default).
NETWORK_MODES = ("REAL_SIMULATION", "TRACE_REPLAY")


def serving_provenance(*, engine: str, network_backend: str,
                       network_mode: str,
                       semantic_losses: list[str]) -> dict[str, Any]:
    """Build the identity block for one serving result.

    Raises ValueError on an unknown mode and TypeError when
    semantic_losses is not a list — a loss must be declared to be
    visible, never smuggled in as a bare string or None.
    """
    if network_mode not in NETWORK_MODES:
        raise ValueError(
            f"unknown network_mode {network_mode!r} — must be one of "
            f"{NETWORK_MODES}. Execution mode is data, not prose.")
    if not isinstance(semantic_losses, list) or not all(
            isinstance(s, str) for s in semantic_losses):
        raise TypeError(
            "semantic_losses must be a list of strings "
            f"(got {semantic_losses!r})")
    return {
        "engine": engine,
        "network_backend": network_backend,
        "network_mode": network_mode,
        "semantic_losses": list(semantic_losses),
    }


def passes_serving_golden_gate(provenance: dict[str, Any]) -> bool:
    """PR6 golden gate (§17.8): real simulation AND zero semantic loss.

    Pure predicate so tests — not eyeballs — enforce it. A replay-only
    run fails here even with perfect metrics; so does a real run that
    discarded load-bearing semantics (e.g. pp_stage_boundaries).
    """
    return (provenance.get("network_mode") == "REAL_SIMULATION"
            and provenance.get("semantic_losses") == [])


# ── Execution-mode / fidelity identity (Phase 1 T3) ───────────────────
# Closed vocabulary: a serving result is either real simulation or
# trace replay — never an unlabeled "booksim". Fidelity follows the
# existing runs.py categories (source wins over the program text's
# SYSTEM_SIMULATION shorthand until Phase 5 settles metric semantics).

def mode_for_backend(network_backend: str, cycle_accurate: bool) -> str:
    """Execution mode for a requested backend+flags combination."""
    if network_backend == "booksim":
        return "REAL_SIMULATION" if cycle_accurate else "TRACE_REPLAY"
    if network_backend in ("analytical", "ns3"):
        # Neither replays trace durations: analytical integrates its own
        # model, ns-3 simulates packets. (ns-3 is unreachable without its
        # binary — preflight refuses first.)
        return "REAL_SIMULATION"
    raise ValueError(
        f"unknown network_mode for backend {network_backend!r} — must be "
        f"one of booksim/analytical/ns3")


def fidelity_for_mode(network_backend: str, network_mode: str) -> str:
    """Metric fidelity for a backend+mode combination (runs.py vocabulary)."""
    table = {
        ("booksim", "REAL_SIMULATION"): "SYSTEM_SERVING_SIMULATION",
        ("booksim", "TRACE_REPLAY"): "TRACE_REPLAY",
        ("analytical", "REAL_SIMULATION"): "ANALYTICAL_ESTIMATE",
        ("ns3", "REAL_SIMULATION"): "SYSTEM_SERVING_SIMULATION",
    }
    try:
        return table[(network_backend, network_mode)]
    except KeyError:
        raise ValueError(
            f"unknown fidelity for {(network_backend, network_mode)!r} — "
            "fidelity is data, not prose") from None


# ── Analytical engine identity (PR7) ─────────────────────────────
# The congestion-aware analytical engine is 1-dim-only; N-dim clusters
# (DP/PP/MoE shapes) run on the congestion-unaware engine (optimistic
# lower bound). Selection happens once, in preflight binary resolution;
# this maps the resolved binaries back to a machine-readable name so a
# result can never misstate which engine produced it.

def engine_identity_from_binaries(serve_binaries: list[Any]) -> dict[str, str]:
    """Which analytical engine ran, from the binaries preflight resolved.

    Pure observation of the resolved paths — identity follows the binary
    that executed (same principle as binary_identity's sha256), never a
    re-derivation that could drift from it.
    """
    names = [Path(str(b)).name for b in serve_binaries]
    if any("AnalyticalAstraUnaware" in n for n in names):
        return {"network_engine": "congestion_unaware",
                "engine_selected_by": "topology_dims"}
    if any(n.startswith("AnalyticalAstra") for n in names):
        return {"network_engine": "congestion_aware",
                "engine_selected_by": "topology_dims"}
    raise ValueError(
        f"no analytical binary in resolved set {names} — engine identity "
        "is only defined for analytical runs")


def retired_from_csv(csv_path: Any) -> int:
    """Retired-request count from serving's per-request CSV (one row each)."""
    from pathlib import Path as _P

    path = _P(csv_path)
    if not path.is_file():
        raise FileNotFoundError(f"per-request CSV missing: {path}")
    with open(path) as f:
        lines = [ln for ln in f if ln.strip()]
    return max(len(lines) - 1, 0)  # header row is not a request


# ── Serve argv assembly (single implementation; CLI delegates here) ───
# Defaults mirror the `serve` parser exactly — the parser remains the
# human surface, this table is the reusable source for control-plane
# callers. Any default change lands here AND in build_parser together
# (pinned by test_serve_contract arg-forwarding tests).

SERVE_DEFAULTS: dict[str, Any] = {
    "num_reqs": 1,
    "network_backend": "booksim",
    "output": None,
    "timeout": None,
    "log_level": "WARNING",
    "no_cleanup": False,
    "no_prefix_caching": False,
    "cycle_accurate": False,
    "max_num_seqs": None,
    "max_num_batched_tokens": None,
    "long_prefill_token_threshold": None,
    "block_size": None,
    "npu_memory_utilization": None,
    "log_interval": None,
    "dtype": None,
    "kv_cache_dtype": None,
    "request_routing_policy": None,
    "expert_routing_policy": None,
    "prefix_storage": None,
    "skip_prefill": False,
    "save_trace_text": False,
    "enable_prefix_sharing": False,
    "enable_local_offloading": False,
    "enable_attn_offloading": False,
    "enable_sub_batch_interleaving": False,
    "no_chunked_prefill": False,
    "no_block_copy": False,
    "no_reserve_full_isl": False,
}


def serve_args(**overrides: Any) -> SimpleNamespace:
    """Argv namespace for serving assembly: defaults + spec overrides."""
    unknown = set(overrides) - set(SERVE_DEFAULTS)
    if unknown:
        raise ValueError(f"unknown serve args: {sorted(unknown)}")
    return SimpleNamespace(**{**SERVE_DEFAULTS, **overrides})


def locate_serve_path(p: str, *, llmsim_dir: Path, repo_dir: Path,
                      dse_dir: Path) -> str:
    """Resolve a config/dataset path for the serving sim.

    The serving module runs with cwd=llmsim_dir, chdir's into astra-sim/,
    and then blindly prepends "../" to every config/dataset path — so the
    string handed over is interpreted as llmsim_dir/<path>. Absolute paths
    would break unless the file lives inside llmsim_dir. Therefore: always
    return a path relative to llmsim_dir ("walk_up" style ../../x/y for
    files elsewhere in the repo), looking the input up against llmsim_dir,
    repo, dse, then CWD.
    """
    llmserving_root = llmsim_dir.resolve()

    def _rel(cand: Path) -> str:
        cand = cand.resolve()
        try:
            return str(cand.relative_to(llmserving_root))
        except ValueError:
            return str(cand.relative_to(llmserving_root, walk_up=True))

    r = Path(p)
    if r.is_absolute():
        if r.exists():
            return _rel(r)
        # Absolute path that doesn't exist: keep the old absolute behavior so
        # the module's own error message names the path the user gave.
        return str(r)
    for base in (llmserving_root, repo_dir, dse_dir, Path.cwd()):
        cand = base / p
        if cand.exists():
            return _rel(cand)
    # Not found anywhere: return an LLMSIM-relative guess so the downstream
    # "../" prepend resolves inside the vendored tree (module fails there
    # with an accurate "file not found" naming a resolvable location).
    return _rel(Path.cwd() / p)


def build_serve_cmd(args: Any, cluster_config: str, dataset: str) -> list:
    """Assemble the `python -m serving` command line.

    Single source of truth for the CLI→module flag contract: every VeritX
    rename/inversion wrinkle (upstream --no-cleanup-inputs → --keep-inputs,
    --cycle-accurate → --no-booksim-replay-only) is applied exactly once,
    here.
    """
    cmd = [
        sys.executable, "-m", "serving",
        "--cluster-config", cluster_config,
        "--dataset", dataset,
        "--num-reqs", str(args.num_reqs),
        "--network-backend", args.network_backend,
        "--log-level", args.log_level,
    ]

    if args.output:
        cmd.extend(["--output", str(Path(args.output).resolve())])

    if args.no_cleanup:
        # VeritX: upstream renamed --no-cleanup-inputs to --keep-inputs.
        cmd.append("--keep-inputs")

    if args.no_prefix_caching:
        cmd.append("--no-enable-prefix-caching")

    if args.cycle_accurate:
        # Downstream flag is inverted (replay-only defaults True).
        cmd.append("--no-booksim-replay-only")

    # Valued flags: forward only when explicitly set (None = upstream default).
    for _flag, _val in (
        ("--max-num-seqs", args.max_num_seqs),
        ("--max-num-batched-tokens", args.max_num_batched_tokens),
        ("--long-prefill-token-threshold", args.long_prefill_token_threshold),
        ("--block-size", args.block_size),
        ("--npu-memory-utilization", args.npu_memory_utilization),
        ("--log-interval", args.log_interval),
        ("--dtype", args.dtype),
        ("--kv-cache-dtype", args.kv_cache_dtype),
        ("--request-routing-policy", args.request_routing_policy),
        ("--expert-routing-policy", args.expert_routing_policy),
        ("--prefix-storage", args.prefix_storage),
    ):
        if _val is not None:
            cmd.extend([_flag, str(_val)])

    # Toggles.
    for _attr, _dflag in (
        ("skip_prefill", "--skip-prefill"),
        ("save_trace_text", "--save-trace-text"),
        ("enable_prefix_sharing", "--enable-prefix-sharing"),
        ("enable_local_offloading", "--enable-local-offloading"),
        ("enable_attn_offloading", "--enable-attn-offloading"),
        ("enable_sub_batch_interleaving", "--enable-sub-batch-interleaving"),
    ):
        if getattr(args, _attr, False):
            cmd.append(_dflag)
    # VeritX --no-* renames for upstream BooleanOptional defaults-True.
    for _attr, _dflag in (
        ("no_chunked_prefill", "--no-enable-chunked-prefill"),
        ("no_block_copy", "--no-enable-block-copy"),
        ("no_reserve_full_isl", "--no-reserve-full-isl"),
    ):
        if getattr(args, _attr, False):
            cmd.append(_dflag)

    return cmd


# ── Serving preflight (Phase 1 T1) ────────────────────────────────────
# Refuse invalid serving executions BEFORE LLMServingSim is spawned.
# Mirrors downstream rules (cited per check); the downstream checks stay
# as the second line of defense. Never spawns a subprocess.

# Closed refusal vocabulary (program Phase 1 T1).
_PREFLIGHT_REASONS = (
    "BACKEND_UNAVAILABLE",
    "BACKEND_BINARY_MISSING",
    "BACKEND_BINARY_NOT_EXECUTABLE",
    "DATASET_MISSING",
    "CLUSTER_INVALID",
    "MODEL_DOES_NOT_FIT",
    "UNSUPPORTED_PARALLELISM",
    "UNSUPPORTED_WORKLOAD_SEMANTIC",
    "UNSUPPORTED_EXECUTION_MODE",
)

# Mirror of serving/__main__.py:651.
_DTYPE_TO_BITS = {'float16': 16, 'bfloat16': 16, 'float32': 32,
                  'fp8': 8, 'int8': 8}

_GB_TO_BYTE = 1024 * 1024 * 1024


def _refuse(reason: str, **fields: Any) -> "ServingPreflightError":
    """Build the structured refusal block (program §5 T1 format)."""
    from .errors import ServingPreflightError
    assert reason in _PREFLIGHT_REASONS, reason
    lines = ["SERVING_PREFLIGHT_FAILED", "", f"reason: {reason}"]
    lines.extend(f"{k}: {v}" for k, v in fields.items())
    return ServingPreflightError(reason, "\n".join(lines))


def _load_serving_helpers(llmsim_dir: Any) -> Any:
    """Import the pure downstream helpers (no spawn, no CWD dependence).

    serving/core resolves model configs from its own __file__
    (utils.py:get_config), so only sys.path needs the LLMSIM root.
    Restored on return — never leaks into the caller.
    """
    import sys as _sys
    from types import SimpleNamespace as _NS

    saved = list(_sys.path)
    _sys.path.insert(0, str(llmsim_dir))
    try:
        from serving.core.config_builder import (  # noqa: PLC0415
            _compute_network_dims, _resolve_dp_groups,
            _resolve_parallelism)
        from serving.core.memory_model import (  # noqa: PLC0415
            calculate_sizes)
        from serving.core.utils import get_config  # noqa: PLC0415
        return _NS(resolve_parallelism=_resolve_parallelism,
                   resolve_dp_groups=_resolve_dp_groups,
                   network_dims=_compute_network_dims,
                   calculate_sizes=calculate_sizes,
                   get_config=get_config)
    finally:
        _sys.path[:] = saved


def _weight_bytes(model_name: str, tp: int, pp: int, ep: int, fp: int,
                  helpers: Any) -> int:
    """Mirror of MemoryModel.get_weight (memory_model.py:157-205).

    Per-rank weight bytes, conservative across PP ranks (heaviest rank).
    """
    calc = helpers.calculate_sizes
    cfg = helpers.get_config(model_name)
    n_layer = cfg['num_hidden_layers']
    is_moe = ('num_local_experts' in cfg or 'num_experts' in cfg)
    weight = 0
    _, embedding, _ = calc(model_name, 'embedding', 1, parallel=tp, fp=fp)
    weight += embedding
    block = 0
    _, ln_w, _ = calc(model_name, 'layernorm', 1, parallel=tp, fp=fp)
    block += 2 * ln_w
    _, qkv_w, _ = calc(model_name, 'qkv_proj', 1, parallel=tp, fp=fp)
    block += qkv_w
    _, o_w, _ = calc(model_name, 'o_proj', 1, parallel=tp, fp=fp)
    block += o_w
    if is_moe:
        _, moe_w, _ = calc(model_name, 'moe', 1, parallel=ep, fp=fp)
        block += moe_w
    else:
        _, ffn1_w, _ = calc(model_name, 'gate_up_proj', 1,
                            parallel=tp, fp=fp)
        block += ffn1_w
        _, ffn2_w, _ = calc(model_name, 'down_proj', 1, parallel=tp, fp=fp)
        block += ffn2_w
    weight += block * (n_layer // max(pp, 1))
    _, ln_f, _ = calc(model_name, 'final_layernorm', 1, parallel=tp, fp=fp)
    weight += ln_f
    _, lm_head, _ = calc(model_name, 'lm_head', 1, parallel=tp, fp=fp)
    weight += lm_head
    return weight


def _backend_binaries(llmsim_dir: Any, network_backend: str,
                      network_dims: list[int] | None) -> list[Any]:
    """Mirror the binary selection in serving/__main__.py:694-741."""
    from pathlib import Path as _P
    astra_sim = _P(llmsim_dir) / "astra-sim"
    if network_backend == "booksim":
        return [astra_sim / "network_frontend" / "booksim2" / "bin"
                / "AstraSim_BookSim2"]
    if network_backend == "ns3":
        return [astra_sim / "extern" / "network_backend" / "ns-3" / "build"
                / "scratch" / "ns3.42-AstraSimNetwork-default"]
    if network_backend == "analytical":
        aware = (astra_sim / "astra-sim" / "build" / "astra_analytical"
                 / "build" / "AnalyticalAstra" / "bin" / "AnalyticalAstra")
        if network_dims is not None and len(network_dims) > 1:
            # N-dim falls back to the congestion-unaware engine
            # (__main__.py:705-721) — both identities are required.
            unaware = (astra_sim / "build" / "astra_analytical_unaware"
                       / "build" / "bin" / "AnalyticalAstraUnaware")
            return [aware, unaware]
        return [aware]
    raise _refuse("BACKEND_UNAVAILABLE", backend=network_backend,
                  supported="booksim, analytical, ns3")


def preflight_serve(*, llmsim_dir: Any, cluster_path: Any,
                    dataset_path: Any, network_backend: str,
                    cycle_accurate: bool,
                    cli_dtype: Any = None) -> None:
    """Refuse an invalid serving execution before spawning (Phase 1 T1).

    Checks run in fixed order so the first refusal is deterministic:
    backend → execution mode → binaries → dataset → cluster →
    parallelism → model fit → converter capability. Returns the resolved
    backend binary paths when the execution may proceed (one resolution,
    reused for provenance identity). Raises ServingPreflightError
    otherwise. Never spawns a subprocess.
    """
    import copy as _copy
    import json as _json
    import os as _os
    from pathlib import Path as _P

    # ── backend + execution mode (request shape, no files needed) ─────
    if network_backend not in ("booksim", "analytical", "ns3"):
        raise _refuse("BACKEND_UNAVAILABLE", backend=network_backend,
                      supported="booksim, analytical, ns3")
    if cycle_accurate and network_backend != "booksim":
        # The flag only clears downstream --booksim-replay-only; anywhere
        # else it is silently meaningless — fail closed instead.
        raise _refuse("UNSUPPORTED_EXECUTION_MODE",
                      backend=network_backend, flag="--cycle-accurate",
                      detail="cycle-accurate simulation exists only for "
                             "the booksim backend")

    # ── binaries (mirror of __main__.py:694-741; dims resolved below) ─
    # The analytical N-dim rule needs resolved instances first, so binary
    # paths are collected after the cluster parses (same order downstream:
    # build_cluster_config precedes Popen).
    binaries: list[Any] | None = None
    if network_backend in ("booksim", "ns3"):
        binaries = _backend_binaries(llmsim_dir, network_backend, None)

    # ── dataset + cluster files ───────────────────────────────────────
    dataset_path = _P(dataset_path)
    if not dataset_path.is_file():
        raise _refuse("DATASET_MISSING", dataset=str(dataset_path))
    cluster_path = _P(cluster_path)
    try:
        cluster = _json.loads(cluster_path.read_text())
    except (OSError, ValueError) as e:
        raise _refuse("CLUSTER_INVALID", cluster=str(cluster_path),
                      detail=str(e)[:200]) from e
    nodes = cluster.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        raise _refuse("CLUSTER_INVALID", cluster=str(cluster_path),
                      detail="missing non-empty 'nodes' list")
    raw_instances: list[dict[str, Any]] = []
    raw_nodes: list[int] = []
    for ni, node in enumerate(nodes):
        insts = node.get("instances")
        if not isinstance(insts, list) or not insts:
            raise _refuse("CLUSTER_INVALID", cluster=str(cluster_path),
                          detail=f"node {ni} has no instances")
        for inst in insts:
            if not isinstance(inst, dict) or "model_name" not in inst \
                    or "npu_mem" not in inst:
                raise _refuse(
                    "CLUSTER_INVALID", cluster=str(cluster_path),
                    detail=f"node {ni} instance missing "
                           "model_name/npu_mem")
            raw_instances.append(inst)
            raw_nodes.append(ni)

    # ── downstream helpers (pure imports; no spawn) ───────────────────
    helpers = _load_serving_helpers(llmsim_dir)

    # ── parallelism + DP groups (exact downstream rules, deep copies) ─
    instances: list[dict[str, Any]] = []
    for ni, inst in zip(raw_nodes, raw_instances):
        work = _copy.deepcopy(inst)
        try:
            model_config = helpers.get_config(work["model_name"])
        except (FileNotFoundError, KeyError) as e:
            raise _refuse("CLUSTER_INVALID",
                          cluster=str(cluster_path),
                          detail=f"node {ni} model "
                                 f"{work.get('model_name')!r} unresolvable: "
                                 f"{e}"[:200]) from e
        try:
            helpers.resolve_parallelism(work, model_config)
        except ValueError as e:
            raise _refuse("UNSUPPORTED_PARALLELISM",
                          cluster=str(cluster_path),
                          detail=str(e)[:300]) from e
        instances.append(work)
    try:
        helpers.resolve_dp_groups(instances)
    except ValueError as e:
        raise _refuse("UNSUPPORTED_PARALLELISM",
                      cluster=str(cluster_path),
                      detail=str(e)[:300]) from e

    # ── analytical binaries need resolved dims ────────────────────────
    if binaries is None:
        dims = helpers.network_dims(instances)
        binaries = _backend_binaries(llmsim_dir, network_backend, dims)
    for binary in binaries:
        binary = _P(binary)
        if not binary.is_file():
            raise _refuse("BACKEND_BINARY_MISSING", backend=network_backend,
                          availability="UNAVAILABLE",
                          expected=str(binary),
                          hint="build the backend or pick an available one "
                               "(ns3 does not block PR6)")
        if not _os.access(binary, _os.X_OK):
            raise _refuse("BACKEND_BINARY_NOT_EXECUTABLE",
                          backend=network_backend, path=str(binary))

    # ── model fit (mirror of MemoryModel weight check) ────────────────
    for idx, (ni, inst) in enumerate(zip(raw_nodes, instances)):
        dtype = inst.get("dtype", cli_dtype)
        if dtype is None:
            torch_dtype = helpers.get_config(
                inst["model_name"]).get("torch_dtype")
            dtype = (torch_dtype if isinstance(torch_dtype, str)
                     and torch_dtype in _DTYPE_TO_BITS else "bfloat16")
        if dtype not in _DTYPE_TO_BITS:
            raise _refuse("CLUSTER_INVALID", cluster=str(cluster_path),
                          detail=f"instance {idx} unsupported dtype "
                                 f"{dtype!r}")
        fp = _DTYPE_TO_BITS[dtype] // 8
        weight = _weight_bytes(inst["model_name"], inst["tp_size"],
                               inst["pp_size"], inst["ep_total"], fp,
                               helpers)
        mem_size = inst["npu_mem"].get("mem_size")
        try:
            npu_mem = int(mem_size) * _GB_TO_BYTE
        except (TypeError, ValueError):
            raise _refuse("CLUSTER_INVALID", cluster=str(cluster_path),
                          detail=f"instance {idx} bad npu_mem.mem_size "
                                 f"{mem_size!r}") from None
        if weight > npu_mem:
            raise _refuse(
                "MODEL_DOES_NOT_FIT",
                cluster=_P(cluster_path).name, node=ni, instance=idx,
                required_weight_memory_gib=weight // _GB_TO_BYTE,
                available_npu_memory_gib=npu_mem // _GB_TO_BYTE)

    # ── converter capability ──────────────────────────────────────────
    for idx, inst in enumerate(instances):
        if inst["pp_size"] > 1:
            # convert_rows predates PP support: boundaries would be dropped
            # and the run would succeed with wrong communication semantics.
            raise _refuse("UNSUPPORTED_WORKLOAD_SEMANTIC",
                          field="pp_stage_boundaries",
                          instance=idx, pp_size=inst["pp_size"],
                          converter="convert_rows",
                          detail="converter has no pipeline-parallel "
                                 "semantics")
    return [str(b) for b in binaries]
