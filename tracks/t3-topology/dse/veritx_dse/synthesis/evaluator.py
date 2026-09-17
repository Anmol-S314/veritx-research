"""evaluator.py — ONE BookSim evaluation code path for synthesis (Phase 2a).

Unifies the three divergent BookSim harnesses:

* ``bo_synthesizer.evaluate_topology`` (bo_synthesizer.py ~L226-316 pre-2a)
* ``iterative_synthesizer.eval_bs`` (iterative_synthesizer.py ~L122-177)
* ``multi_workload_pareto.eval_once`` (veritx_dse/tools/multi_workload_pareto.py
  ~L138-206 + ``_parse_lat`` ~L43-52)

CODE is unified first; NUMBERS converged to pareto in Phase 4a
(sim-owner sign-off 2026-09-13): ITERATIVE_PRESET is now numerically
identical to PARETO_PRESET (max_samples 5, warmup 1, no wait_for_tail,
honest-first first-match parse; the span formula, sim_type, thres, bufs
already matched). BO_PRESET adopts the pareto measurement protocol
(span-derived sample_period, max_samples 5, warmup 1, honest-first
first-match) while keeping its throughput-mode identity (sim_type,
matrix branch, vc_buf_matrix 16, injection 0.04, no latency_thres line,
seed 42, no stdin, connectivity fast-fail, 1e9/1000.0 sentinels).

Deliberately NOT converged (no pareto equivalent exists):

* sim_type: BO ``throughput`` (+ ``injection_rate=0.04`` matrix-only,
  ``vc_buf_size=16`` matrix-only); ITERATIVE/PARETO ``latency``.
* matrix branch: BO-only (sample_period 100 fixed); pareto has no matrix mode.
* latency_thres: ``1000000.0`` for ITERATIVE/PARETO, ABSENT for BO (a
  latency cutoff has no defined meaning for throughput scoring).
* stdin: BO passes none; ITERATIVE/PARETO pass ``stdin=DEVNULL`` (no
  numeric effect; preserved per preset).
* cfg/anynet filenames: BO ``topo.anynet``+``run.cfg``; ITERATIVE
  ``topo.anynet``+``cfg``; PARETO ``cfg.cfg`` (ephemeral tempdirs;
  filenames preserved per preset, no numeric effect).
* failure sentinels (loops only): BO disconnect ``1e9``, runtime ``1000.0``;
  ITERATIVE ``1e9`` everywhere; PARETO ``None`` + ``error`` string.
  The shared path always returns canonical :class:`SynthResult`
  (``status``/``error``, ``latency=None`` on failure); wrappers map back to
  floats for their inner loops (see "Record boundaries" below).
* scratch bases: BO reuses the caller-provided workdir (under SYNTH_DIR);
  ITERATIVE/PARETO mkdtemp under ``<repo>/runs/booksim`` and rmtree after.
  Preserved via ``scratch_parent`` passthrough.
* pareto ``_detect_classes`` result was computed but UNUSED (dead); the
  shared path drops the call (no numeric effect).
* pareto non-anynet backends (gec/mesh/torus/flatfly/fly/cmesh) keep their
  backend-specific config branches verbatim inside :func:`evaluate_spec`;
  only span/run/parse/failure-encoding are shared.

Subprocess execution uses ``veritx_dse.simulation.booksim`` primitives
WHERE POSSIBLE without changing numbers: binary resolution prefers
``core.paths.BOOKSIM_BIN`` at call time (so existing monkeypatches keep
working) with ``simulation.booksim.find_booksim_bin`` as fallback and the
legacy ``<repo>/third_party/booksim2/src/booksim`` path last. Config
building and latency parsing are intentionally NOT delegated to
``simulation.booksim.build_config`` / ``parse_output`` because those use
different defaults (span+margin ``max(200, ...)`` vs ``max(50000, ...)``,
``latency_thres=1e15`` vs ``1e6``/absent, plat regex with exponents) and
would change numbers. Trace-span uses the original swallow-and-default
loop (partial span on garbage) rather than ``detect_trace_stats`` (which
raises ``TraceError`` on the same input).

Record boundaries (float sentinel -> canonical conversion points):

* BO: ``objective()`` and the RHO/GRPO-style inner loop keep floats for the
  GP (``1e9`` disconnect / ``1000.0`` runtime). ``main()`` converts the
  winner to :class:`SynthResult` when writing ``bo_results_N{n}.json``
  (``synth_result`` key, additive) and again for the ``booksim_latency``
  validation record.
* ITERATIVE: ``run_rho`` / ``run_grpo`` keep floats (``1e9``). ``main()``
  converts the winner to :class:`SynthResult` for the ``.json`` sidecar
  (``synth_result`` key, additive).
* PARETO: ``eval_once`` returns canonical-shaped dicts already
  (``latency=None`` + ``error``); the shared path adds ``status`` /
  ``provenance`` / ``extra`` flat, and ``main()`` dumps them unchanged
  into ``pareto.json`` ``results``.
* MILP (analytical, no BookSim): ``main()`` converts its hops stats to a
  :class:`SynthResult` (``synth_result`` key) at the ``.json`` write.

Script-mode safe: all veritx_dse imports are try/except with local
fallbacks, matching the pattern already used in these files.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Script-mode-safe imports ──────────────────────────────────────────
try:
    from veritx_dse.synthesis.results import SynthResult
except Exception:  # script mode: sibling sits next to this file
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from results import SynthResult  # type: ignore
    except Exception:
        SynthResult = None  # type: ignore

try:
    from veritx_dse.model.presets import topo_size as _topo_size
    from veritx_dse.model.presets import count_anynet_edges as _count_anynet_edges
    from veritx_dse.core.constants import BOOKSIM_SEED, DEFAULT_TIMEOUT, env_int
except Exception:
    try:
        from ..model.presets import topo_size as _topo_size, count_anynet_edges as _count_anynet_edges  # type: ignore
        from ..core.constants import BOOKSIM_SEED, DEFAULT_TIMEOUT, env_int  # type: ignore
    except Exception:
        _topo_size = None  # type: ignore
        _count_anynet_edges = None  # type: ignore
        BOOKSIM_SEED = 42  # type: ignore  # same value; canonical home is core.constants
        DEFAULT_TIMEOUT = 60  # type: ignore
        def env_int(name, default):  # type: ignore
            import os
            raw = os.environ.get(name)
            if raw is None:
                return default
            return int(raw)  # fail fast like core.constants.env_int


# ── EvaluationConfig + named presets ──────────────────────────────────

@dataclass
class EvaluationConfig:
    """BookSim knob set for one caller. See module docstring for divergence."""

    name: str = ""
    # trace-mode sampling: fixed int, or None => span-derived
    #   span-derived: sample_period = max(span_min, span + span_margin)
    sample_period: int | None = None
    span_min: int = 50000
    span_margin: int = 10000
    # BO matrix-only fixed period (None = N/A for trace-only callers)
    matrix_sample_period: int | None = None
    max_samples: int = 1
    sim_type: str = "latency"
    num_vcs: int = 4
    vc_buf_size: int = 8
    vc_buf_size_matrix: int | None = None  # BO matrix override
    packet_size: int = 8
    latency_thres: float | None = 1000000.0  # None => omit line (BO)
    warmup_periods: int | None = None  # PARETO-only
    wait_for_tail_credit: int | None = None  # ITERATIVE-only
    injection_rate: float | None = None  # BO matrix-only
    prefer_honest: bool = False
    use_last_match: bool = False  # BO-only (plat last of max_samples phases)
    check_connectivity: bool = False  # BO-only fast-fail
    disconnected_sentinel: float = 1e9
    failure_sentinel: float = 1e9
    use_stdin_devnull: bool = True
    provenance: str = ""


# BO_PRESET — pareto-converged (Phase 4a) except throughput-mode lines.
# Converged TO pareto: span-derived sample_period (was fixed 200; the old
# computed-but-unused max(200,max_cyc+1000) quirk is gone), max_samples 5
# (was 3), warmup_periods 1 (was absent), honest-first parse (was plat-only),
# FIRST match (was LAST). Kept throughput-mode: sim_type=throughput,
# matrix branch (sample_period 100, vc_buf 16, injection 0.04 — no pareto
# equivalent exists), no latency_thres line (a latency cutoff has no defined
# meaning for throughput scoring; pareto's 1e6 is latency-mode only),
# seed/stdin/connectivity/sentinels unchanged.
BO_PRESET = EvaluationConfig(
    name="bo",
    sample_period=None,  # span-derived, like pareto
    matrix_sample_period=100,
    max_samples=5,
    sim_type="throughput",
    num_vcs=4,
    vc_buf_size=8,
    vc_buf_size_matrix=16,
    packet_size=8,
    latency_thres=None,
    warmup_periods=1,
    wait_for_tail_credit=None,
    injection_rate=0.04,
    prefer_honest=True,
    use_last_match=False,
    check_connectivity=True,
    disconnected_sentinel=1e9,
    failure_sentinel=1000.0,
    use_stdin_devnull=False,
    provenance="bo_synthesizer+BO_PRESET",
)

# ITERATIVE_PRESET — pareto-converged (Phase 4a): max_samples 5 (was 1),
# warmup_periods 1 (was absent), wait_for_tail_credit dropped (was 1),
# honest-first parse (was plat-only). Sample formula, sim_type, thres,
# vcs/buf, stdin, sentinels were already pareto-identical.
ITERATIVE_PRESET = EvaluationConfig(
    name="iterative",
    sample_period=None,  # span-derived
    span_min=50000,
    span_margin=10000,
    matrix_sample_period=None,
    max_samples=5,
    sim_type="latency",
    num_vcs=4,
    vc_buf_size=8,
    vc_buf_size_matrix=None,
    packet_size=8,
    latency_thres=1000000.0,
    warmup_periods=1,
    wait_for_tail_credit=None,
    injection_rate=None,
    prefer_honest=True,
    use_last_match=False,
    check_connectivity=False,
    disconnected_sentinel=1e9,
    failure_sentinel=1e9,
    use_stdin_devnull=True,
    provenance="iterative_synthesizer+ITERATIVE_PRESET",
)

# PARETO_PRESET — verbatim from multi_workload_pareto.eval_once pre-2a:
#   span L152: _trace_span (max cycle, swallow OSError/ValueError -> 0);
#     sp=max(50000, span+10000) (L153). _detect_classes L151 computed but
#     UNUSED (dead; dropped here, no numeric effect).
#   replay_common L161-163: latency_thres=1000000.0, sim_type=latency,
#     sample_period={sp}, max_samples=5, warmup_periods=1.
#   anynet cfg L171: topology anynet, routing min, network_file, traffic
#     trace, num_vcs=4, vc_buf=8, packet=8 + replay_common + seed param.
#     (gec/mesh/torus/flatfly/fly/cmesh branches keep their verbatim lines
#     in evaluate_spec below.)
#   parse _parse_lat L43-52: honest_avg (\\thonest_avg [0-9.eE+-]+) FIRST,
#     then plat ([0-9.]+) FIRST; None when neither matches. First phase wins
#     over max_samples=5 phases.
#   failures: None+error string (exit code / timeout), never a float sentinel.
PARETO_PRESET = EvaluationConfig(
    name="pareto",
    sample_period=None,  # span-derived
    span_min=50000,
    span_margin=10000,
    matrix_sample_period=None,
    max_samples=5,
    sim_type="latency",
    num_vcs=4,
    vc_buf_size=8,
    vc_buf_size_matrix=None,
    packet_size=8,
    latency_thres=1000000.0,
    warmup_periods=1,
    wait_for_tail_credit=None,
    injection_rate=None,
    prefer_honest=True,
    use_last_match=False,
    check_connectivity=False,
    disconnected_sentinel=1e9,  # unused (no fast-fail; fit-check lives in main)
    failure_sentinel=1e9,  # unused (pareto encodes None+error, not floats)
    use_stdin_devnull=True,
    provenance="multi_workload_pareto+PARETO_PRESET",
)


# ── Shared primitives ─────────────────────────────────────────────────

def write_anynet(adj: dict, path) -> None:
    """Write BookSim .anynet (verbatim shared copy of the three writers).

    Format: ``router <i> node <i> router <peer> ...`` with sorted peers.
    """
    n = len(adj)
    with open(path, "w") as f:
        for i in range(n):
            peers = sorted(adj.get(i, set()))
            f.write(f"router {i} node {i} " + " ".join(f"router {p}" for p in peers) + "\n")


def is_connected(adj: dict) -> bool:
    """BFS connectivity check (unified copy of bo._is_connected /
    iterative.is_connected — functionally identical)."""
    n = len(adj)
    if n == 0:
        return False
    visited: set = set()
    queue = [0]
    while queue:
        node = queue.pop()
        if node in visited:
            continue
        visited.add(node)
        for nb in adj.get(node, set()):
            if nb not in visited:
                queue.append(nb)
    return len(visited) == n


def count_edges(adj: dict) -> int:
    """Undirected edge count."""
    return sum(len(v) for v in adj.values()) // 2


def trace_span(trace_path) -> int:
    """Max cycle in a trace (verbatim shared copy of iterative/pareto span).

    Skips ``#`` comments; swallows OSError/ValueError and returns the
    partial max (0 when unreadable) — the conservative default each caller
    relied on. (Deliberately NOT detect_trace_stats, which raises
    TraceError on the same garbage input.)
    """
    m = 0
    try:
        with open(trace_path) as f:
            for line in f:
                if line.startswith("#"):
                    continue
                p = line.split()
                if len(p) >= 5:
                    c = int(p[0])
                    if c > m:
                        m = c
    except (OSError, ValueError):
        pass  # unreadable/garbage trace -> span unknown (partial/0)
    return m


def sample_period_for_span(span: int, cfg: EvaluationConfig) -> int:
    """Resolve the trace-mode sample_period for a preset."""
    if cfg.sample_period is not None:
        return cfg.sample_period
    return max(cfg.span_min, span + cfg.span_margin)


_PLAT_RE = r"Packet latency average\s*=\s*((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"
_HONEST_RE = rf"\thonest_avg\s*=\s*((?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)"


def parse_latency(
    output: str,
    *,
    prefer_honest: bool = False,
    use_last_match: bool = False,
) -> float | None:
    """Parse BookSim stdout to latency.

    Honest-first semantics match multi_workload_pareto._parse_lat verbatim:
    ``\\thonest_avg`` (first match) wins, plat fallback (first match), else
    None. With ``prefer_honest=False`` only plat is tried. With
    ``use_last_match=True`` (BO) the plat search takes the LAST match over
    the ``max_samples`` phases instead of the first.
    """
    if prefer_honest:
        m = re.search(_HONEST_RE, output)
        if m:
            try:
                return float(m.group(1))
            except ValueError:
                pass
    if use_last_match:
        matches = re.findall(_PLAT_RE, output)
        if matches:
            try:
                return float(matches[-1])
            except ValueError:
                return None
        return None
    m = re.search(_PLAT_RE, output)
    if m:
        try:
            return float(m.group(1))
        except ValueError:
            return None
    return None


def _resolve_booksim_bin():
    """Binary location: core.paths at call time -> simulation helper -> legacy.

    Call-time lookup (not import-time) so tests monkeypatching
    ``veritx_dse.core.paths.BOOKSIM_BIN`` keep working (cf. BO
    missing-binary test expecting the finite 1000.0 penalty).
    """
    try:
        import veritx_dse.core.paths as _paths

        cand = getattr(_paths, "BOOKSIM_BIN", None)
        if cand is not None:
            return Path(cand)
    except Exception:
        pass
    try:
        from veritx_dse.simulation.booksim import find_booksim_bin as _find
        from veritx_dse.core.paths import REPO as _REPO

        try:
            return _find(Path(_REPO))
        except Exception:
            pass
    except Exception:
        pass
    # Legacy standalone layout (pareto/iterative fallback math).
    here = Path(__file__).resolve()
    for base in (here.parents[4] if len(here.parents) > 4 else here.parent,
                 here.parents[5] if len(here.parents) > 5 else here.parent):
        cand = base / "third_party" / "booksim2" / "src" / "booksim"
        if cand.exists():
            return cand
    try:
        import veritx_dse.core.paths as _paths2

        return Path(_paths2.BOOKSIM_BIN)
    except Exception:
        return Path("booksim")


def _run_booksim_cfg(
    cfg_text: str,
    cfg_name: str,
    workdir: Path,
    timeout: int,
    *,
    use_stdin_devnull: bool = True,
):
    """Write cfg_text and run BookSim; return (stdout, returncode, stderr).

    Raises TimeoutError / OSError (e.g. missing binary) for the caller to
    encode canonically. Uses the shared binary resolution above.
    """
    workdir.mkdir(parents=True, exist_ok=True)
    cfg_path = workdir / cfg_name
    cfg_path.write_text(cfg_text)
    booksim = _resolve_booksim_bin()
    kw: dict[str, Any] = dict(
        capture_output=True, text=True, timeout=timeout, cwd=str(workdir.resolve())
    )
    if use_stdin_devnull:
        kw["stdin"] = subprocess.DEVNULL
    # Absolute cfg path: subprocess cwd=workdir, so relative paths double.
    r = subprocess.run(
        [str(booksim), str(cfg_path.resolve())],
        **kw,
    )
    return r.stdout, r.returncode, r.stderr


def _synth_ok(name, backend, nodes, edges, latency, seed, provenance, extra):
    assert SynthResult is not None, "results.py failed to import"
    return SynthResult.ok(
        name=name, topology=backend, backend=backend, nodes=nodes, edges=edges,
        latency=float(latency), seed=seed, provenance=provenance,
        extra=dict(extra or {}),
    )


def _synth_fail(name, backend, nodes, edges, error, seed, provenance, extra):
    assert SynthResult is not None, "results.py failed to import"
    return SynthResult.fail(
        name=name, topology=backend, backend=backend, nodes=nodes, edges=edges,
        error=str(error), seed=seed, provenance=provenance,
        extra=dict(extra or {}),
    )


# ── Config builders (verbatim per-preset lines) ───────────────────────

def build_trace_config(
    anynet_path: Path,
    trace_abs: str,
    seed: int,
    cfg: EvaluationConfig,
) -> str:
    """Anynet+trace config text, driven by the preset (Phase 4a converged).

    Every measurement-protocol line comes from ``cfg`` — no per-caller
    hardcodes. Line order and non-protocol lines (topology/routing/network
    file/traffic/vcs/buf/packet/seed) are unchanged from the pre-2a originals.
    """
    sp = sample_period_for_span(trace_span(trace_abs), cfg) \
        if cfg.sample_period is None else cfg.sample_period
    net = Path(anynet_path).resolve()
    lines = [
        "topology = anynet;",
        "routing_function = min;",
        f"network_file = {net};",
        f"traffic = trace({trace_abs});",
        "num_vcs = 4;",
        f"vc_buf_size = {cfg.vc_buf_size};",
        "packet_size = 8;",
        f"sim_type = {cfg.sim_type};",
    ]
    if cfg.latency_thres is not None:
        lines.append(f"latency_thres = {cfg.latency_thres};")
    lines.append(f"sample_period = {sp};")
    lines.append(f"max_samples = {cfg.max_samples};")
    if cfg.warmup_periods is not None:
        lines.append(f"warmup_periods = {cfg.warmup_periods};")
    if cfg.wait_for_tail_credit is not None:
        lines.append(f"wait_for_tail_credit = {cfg.wait_for_tail_credit};")
    lines.append(f"seed = {seed};")
    return "\n".join(lines) + "\n"


def build_matrix_config(anynet_path: Path, matrix_path: Path, cfg: EvaluationConfig) -> str:
    """BO matrix-mode config (preset-driven; Phase 4a: max_samples + warmup)."""
    net = Path(anynet_path).resolve()
    mat = Path(matrix_path).resolve()
    vc = cfg.vc_buf_size_matrix if cfg.vc_buf_size_matrix is not None else cfg.vc_buf_size
    ir = cfg.injection_rate
    sp = cfg.matrix_sample_period if cfg.matrix_sample_period is not None else 100
    lines = [
        "topology = anynet;",
        "routing_function = min;",
        f"network_file = {net};",
        f"traffic = matrix({mat});",
        "num_vcs = 4;",
        f"vc_buf_size = {vc};",
        f"sample_period = {sp};",
        f"max_samples = {cfg.max_samples};",
    ]
    if cfg.warmup_periods is not None:
        lines.append(f"warmup_periods = {cfg.warmup_periods};")
    if ir is not None:
        lines.append(f"injection_rate = {ir};  # 9ce5 pre-knee: BookSim 0.08 saturates, use 0.04")
    lines += [f"seed = {BOOKSIM_SEED};", "sim_type = throughput;"]
    return "\n".join(lines) + "\n"


def write_traffic_matrix(T, matrix_path: Path) -> None:
    """Normalize + write BO traffic.matrix (bo_synthesizer L332-337 verbatim)."""
    max_val = T.max() if T is not None else 1
    T_norm = T / max_val if max_val > 0 else T
    with open(matrix_path, "w") as f:
        for row in T_norm:
            f.write(" ".join(f"{v:.6g}" for v in row) + "\n")


# ── Unified adj evaluation (BO + ITERATIVE) ───────────────────────────

def evaluate_adj(
    adj: dict,
    *,
    trace_path=None,
    traffic_matrix=None,
    workdir=None,
    seed: int = BOOKSIM_SEED,
    timeout: int | None = None,
    config: EvaluationConfig = BO_PRESET,
    name: str = "",
    scratch_parent=None,
    _cleanup_temp: bool = True,
):
    """Evaluate an adjacency dict; return canonical SynthResult.

    Trace mode when ``trace_path`` is given, else BO matrix mode with
    ``traffic_matrix``. Handles connectivity fast-fail (BO only),
    anynet writing, config building, subprocess run, latency parsing and
    canonical failure encoding in the ONE place.

    timeout=None resolves VERITX_TIMEOUT (default 60s) at call time, so
    converged (longer) evals can be budgeted without editing call sites.
    """
    if timeout is None:
        timeout = env_int("VERITX_TIMEOUT", DEFAULT_TIMEOUT)
    n = len(adj)
    edges = count_edges(adj)
    backend = "anynet"
    prov = config.provenance or config.name
    disp = name or f"{config.name}_N{n}"

    if config.check_connectivity and (edges < n - 1 or not is_connected(adj)):
        return _synth_fail(
            disp, backend, n, edges, "disconnected topology", seed, prov,
            {"failure_kind": "disconnected"},
        )

    owns_tmp = False
    if workdir is None:
        base = Path(scratch_parent) if scratch_parent is not None else Path(tempfile.gettempdir())
        base.mkdir(parents=True, exist_ok=True)
        workdir = Path(tempfile.mkdtemp(dir=str(base)))
        owns_tmp = True
    else:
        workdir = Path(workdir)
        workdir.mkdir(parents=True, exist_ok=True)
    try:
        anynet_path = workdir / "topo.anynet"
        write_anynet(adj, anynet_path)

        if trace_path is not None:
            trace_abs = str(Path(trace_path).resolve())
            if config.name == "bo":
                cfg_text = build_trace_config(anynet_path, trace_abs, BOOKSIM_SEED, config)
                cfg_name = "run.cfg"
                run_seed = BOOKSIM_SEED
            else:
                cfg_text = build_trace_config(anynet_path, trace_abs, seed, config)
                cfg_name = "cfg"
                run_seed = seed
            try:
                stdout, rc, _stderr = _run_booksim_cfg(
                    cfg_text, cfg_name, workdir, timeout,
                    use_stdin_devnull=config.use_stdin_devnull,
                )
            except subprocess.TimeoutExpired as e:
                return _synth_fail(
                    disp, backend, n, edges, f"timeout after {timeout}s: {e}",
                    run_seed, prov, {"failure_kind": "timeout"},
                )
            except Exception as e:
                return _synth_fail(
                    disp, backend, n, edges,
                    f"booksim run failed ({type(e).__name__}: {e})",
                    run_seed, prov, {"failure_kind": "booksim_error"},
                )
            lat = parse_latency(
                stdout, prefer_honest=config.prefer_honest,
                use_last_match=config.use_last_match,
            )
            if lat is None:
                return _synth_fail(
                    disp, backend, n, edges, f"no latency in output (exit {rc})",
                    run_seed, prov, {"failure_kind": "no_latency", "returncode": rc},
                )
            return _synth_ok(disp, backend, n, edges, lat, run_seed, prov, {})
        else:
            # BO matrix mode (traffic_matrix required; None propagates like
            # the original outside-try TypeError path).
            matrix_path = workdir / "traffic.matrix"
            write_traffic_matrix(traffic_matrix, matrix_path)
            cfg_text = build_matrix_config(anynet_path, matrix_path, config)
            try:
                stdout, rc, _stderr = _run_booksim_cfg(
                    cfg_text, "run.cfg", workdir, timeout,
                    use_stdin_devnull=config.use_stdin_devnull,
                )
            except subprocess.TimeoutExpired as e:
                return _synth_fail(
                    disp, backend, n, edges, f"timeout after {timeout}s: {e}",
                    42, prov, {"failure_kind": "timeout"},
                )
            except Exception as e:
                return _synth_fail(
                    disp, backend, n, edges,
                    f"booksim run failed ({type(e).__name__}: {e})",
                    42, prov, {"failure_kind": "booksim_error"},
                )
            lat = parse_latency(
                stdout, prefer_honest=config.prefer_honest,
                use_last_match=config.use_last_match,
            )
            if lat is None:
                return _synth_fail(
                    disp, backend, n, edges, f"no latency in output (exit {rc})",
                    42, prov, {"failure_kind": "no_latency", "returncode": rc},
                )
            return _synth_ok(disp, backend, n, edges, lat, 42, prov, {})
    finally:
        if owns_tmp and _cleanup_temp:
            shutil.rmtree(workdir, ignore_errors=True)


# ── Unified topo-spec evaluation (PARETO, all backends) ───────────────

def _pareto_canonical_size(name, topo, extra):
    """(nodes, edges) — verbatim copy of pareto._canonical_size logic."""
    if _topo_size is not None:
        try:
            if topo == "anynet":
                return _topo_size(topo, dict(extra))
            try:
                from veritx_dse.model.presets import lookup_topo as _lookup
            except Exception:
                try:
                    from ..model.presets import lookup_topo as _lookup  # type: ignore
                except Exception:
                    _lookup = None  # type: ignore
            if _lookup is not None:
                t = _lookup(name)
                if t is not None and t.backend == topo:
                    return _topo_size(t)
            return _topo_size(topo, dict(extra))
        except Exception:
            return None
    return None


def _pareto_count_anynet(filepath):
    """Verbatim copy of pareto._count_anynet (presets-first, legacy fallback)."""
    if _count_anynet_edges is not None:
        try:
            return _count_anynet_edges(filepath)
        except Exception:
            pass
    nodes: set = set()
    edges: set = set()
    try:
        for line in open(filepath):
            parts = line.strip().split()
            if len(parts) < 5 or parts[0] != "router":
                continue
            rid = int(parts[1])
            nodes.add(rid)
            i = 4
            while i < len(parts):
                if parts[i] == "router" and i + 1 < len(parts):
                    pid = int(parts[i + 1])
                    nodes.add(pid)
                    edges.add((min(rid, pid), max(rid, pid)))
                    i += 2
                else:
                    i += 1
    except (OSError, ValueError):
        pass
    return len(nodes), len(edges)


def evaluate_spec(
    trace_path,
    topo_spec,
    seed: int = BOOKSIM_SEED,
    timeout: int | None = None,
    config: EvaluationConfig = PARETO_PRESET,
    scratch_parent=None,
):
    """Evaluate a pareto ``(name, topo, extra, routing)`` spec; return SynthResult.

    Backend config branches are verbatim copies of eval_once pre-2a lines;
    only span derivation, subprocess run, latency parsing and failure
    encoding are shared. The returned SynthResult.to_dict() merges flat
    into eval_once's legacy dict (additive: existing keys untouched).
    """
    name, topo, extra, routing = topo_spec
    if timeout is None:
        timeout = env_int("VERITX_TIMEOUT", DEFAULT_TIMEOUT)
    trace = str(Path(trace_path).resolve())
    span = trace_span(trace_path)
    sp = sample_period_for_span(span, config)
    replay_common = [
        "latency_thres = 1000000.0;",
        "sim_type = latency;",
        f"sample_period = {sp};",
        f"max_samples = {config.max_samples};",
    ]
    if config.warmup_periods is not None:
        replay_common.append(f"warmup_periods = {config.warmup_periods};")
    _size = _pareto_canonical_size(name, topo, extra)
    if topo == "anynet":
        nf = extra["network_file"]
        if _size is not None:
            nodes, edges = _size
        else:
            nodes, edges = _pareto_count_anynet(nf)
        cfg_lines = [
            "topology = anynet;",
            "routing_function = min;",
            f"network_file = {nf};",
            f"traffic = trace({trace});",
            "num_vcs = 4;",
            "vc_buf_size = 8;",
            "packet_size = 8;",
        ] + replay_common + [f"seed = {seed};"]
    elif topo == "gec":
        k = extra.get("k", 8)
        c = extra.get("c", 1)
        o = extra.get("o", 7)
        d = extra.get("d", 1)
        vcs = extra.get("vcs", max(4, d))
        if _size is not None:
            nodes, edges = _size
        else:
            nodes = k * k * c
            if extra.get("mesh"):
                edges = 2 * k * (k - 1)
            elif o >= k - 1 and d == 1:
                edges = k * k * (k - 1)
            else:
                edges = nodes * o * 2
        cfg_lines = [
            "topology = gec;",
            f"k = {k};",
            "n = 2;",
            f"c = {c};",
            f"o = {o};",
            f"d = {d};",
            f"mesh = {int(bool(extra.get('mesh')))};",
            f"routing_function = {routing};",
            f"num_vcs = {vcs};",
            "vc_buf_size = 8;",
            "packet_size = 8;",
            f"traffic = trace({trace});",
        ] + replay_common + ["use_noc_latency = 0;", f"seed = {seed};"]
    else:
        if _size is not None:
            nodes, edges = _size
        elif topo == "mesh":
            k = extra.get("k", 8)
            nn = extra.get("n", 2)
            nodes = k ** nn
            edges = nn * (k - 1) * k ** (nn - 1) if k > 0 else 0
        elif topo == "torus":
            k = extra.get("k", 8)
            nn = extra.get("n", 2)
            nodes = k ** nn
            edges = nn * k ** nn
        elif topo == "flatfly":
            k = extra.get("k", 4)
            nn = extra.get("n", 2)
            c = extra.get("c", 4)
            nodes = (k ** nn) * c
            edges = nodes // c * (c + (k - 1) * nn - c) // 2
        elif topo == "fly":
            k = extra.get("k", 4)
            nn = extra.get("n", 3)
            nodes = k ** nn
            edges = (nn - 1) * nodes
        elif topo == "cmesh":
            k = extra.get("k", 4)
            nn = extra.get("n", 2)
            c = extra.get("c", 4)
            nodes = c * k ** nn
            edges = 2 * nn * k ** nn
        else:
            nodes = edges = 0
        params: dict[str, Any] = {
            "topology": topo,
            "routing_function": routing,
            "num_vcs": 4,
            "vc_buf_size": 8,
            "packet_size": 8,
            "traffic": f"trace({trace})",
            "seed": seed,
        }
        params.update({k2: v for k2, v in extra.items() if k2 != "network_file"})
        cfg_lines = [f"{k2} = {v};" for k2, v in params.items()] + replay_common

    prov = config.provenance or config.name
    base = Path(scratch_parent) if scratch_parent is not None else None
    if base is None:
        try:
            import veritx_dse.core.paths as _paths

            base = Path(getattr(_paths, "REPO", Path.cwd())) / "runs" / "booksim"
        except Exception:
            base = Path.cwd() / "runs" / "booksim"
    try:
        base.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    workdir = Path(tempfile.mkdtemp(dir=str(base)))
    try:
        try:
            stdout, rc, _stderr = _run_booksim_cfg(
                "\n".join(cfg_lines) + "\n", "cfg.cfg", workdir, timeout,
                use_stdin_devnull=config.use_stdin_devnull,
            )
        except subprocess.TimeoutExpired:
            return _synth_fail(
                name, topo, nodes, edges, "timeout", seed, prov,
                {"failure_kind": "timeout", "trace": str(trace_path),
                 "trace_name": Path(trace_path).stem, "routing": routing},
            )
        lat = parse_latency(
            stdout, prefer_honest=config.prefer_honest,
            use_last_match=config.use_last_match,
        )
        if lat is None:
            return _synth_fail(
                name, topo, nodes, edges, f"exit {rc}", seed, prov,
                {"failure_kind": "no_latency", "returncode": rc,
                 "trace": str(trace_path),
                 "trace_name": Path(trace_path).stem, "routing": routing},
            )
        ok = _synth_ok(name, topo, nodes, edges, lat, seed, prov, {
            "trace": str(trace_path), "trace_name": Path(trace_path).stem,
            "routing": routing,
        })
        return ok
    finally:
        shutil.rmtree(workdir, ignore_errors=True)
