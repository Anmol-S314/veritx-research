"""bridge.py — synthesizer-spec candidates ↔ fabric-compiler seam.

Phase 13 (plan §17) wires the compiler to real evaluation. This bridge is
the ONLY place that knows both dialects:

  compiler candidate   = plain dict {name, topology, seed, ...}
  synthesis evaluation = evaluator.evaluate_spec on
                         (name, topo, extra, routing) → SynthResult

Round-trip guarantees (tested): a candidate produced by ``candidate_from_
synth_result`` evaluates bit-identically through ``_evaluate_candidate``
to what the same spec produces via ``evaluate_spec`` directly — the
bridge translates, never re-interprets (the Phase-10 "hope we agree" smell
is banned here too).

Failure handling stays honest: evaluator failures are SynthResult.fail
records (never exceptions), so a timed-out BookSim becomes an
EVALUATION_FAILED candidate with its reason, exactly as the compiler
contract requires. Import errors (missing binary resolver etc.) raise —
an environment that cannot evaluate anything must fail loudly, not
silently emit a NO_FEASIBLE_DESIGN that would read as scientific truth.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from veritx_dse.core.errors import VeritXError


def candidate_from_synth_result(sr_dict: dict[str, Any]) -> dict[str, Any]:
    """SynthResult.to_dict() → compiler candidate entry.

    Carries identity (name, topology/backend, nodes, edges, seed) plus the
    full record under ``synth_result`` so the compiler's evidence trail
    references real evaluation provenance. ``pruned`` entries are
    constructed by callers that did the pruning, not by this translator.
    """
    return {
        "name": sr_dict.get("name", ""),
        "topology": sr_dict.get("topology", "") or sr_dict.get("backend", ""),
        "nodes": sr_dict.get("nodes", 0),
        "edges": sr_dict.get("edges", 0),
        "seed": sr_dict.get("seed"),
        "synth_result": dict(sr_dict),
    }


def results_to_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A loaded synthesis-results file (list of SynthResult dicts) →
    compiler candidate list. Failed records become PRUNED candidates with
    their error as the reason — they stay visible without being evaluated
    again."""
    out: list[dict[str, Any]] = []
    for sr in results:
        if sr.get("status") == "ok":
            out.append(candidate_from_synth_result(sr))
        else:
            out.append({
                "name": sr.get("name", ""),
                "topology": sr.get("topology", "") or sr.get("backend", ""),
                "pruned": True,
                "pruning_reason": f"prior evaluation failed: {sr.get('error')}",
                "synth_result": dict(sr),
            })
    return out


def _evaluate_candidate(cand: dict[str, Any], *, seed: int,
                        timeout: int, trace_path: str):
    """Candidate → SynthResult via the one real evaluation path.

    The candidate's ``synth_result`` (when present) carries the exact
    (topology, extra, routing) spec that produced it originally; this
    re-evaluates THAT spec — the compiler scores what the synthesizer
    generated, never a re-interpretation of it.
    """
    from veritx_dse.synthesis.evaluator import evaluate_spec

    sr = cand.get("synth_result") or {}
    topo = sr.get("topology") or sr.get("backend") or cand.get("topology") or "anynet"
    extra = dict(sr.get("extra") or {})
    routing = extra.pop("routing", "min")
    name = cand.get("name") or sr.get("name") or "cand"
    # BookSim resolves the anynet file against the process cwd (the
    # evaluator's scratch dir) — a relative path from the results file's
    # era would silently vanish. Resolve NOW, against the caller's cwd,
    # and record the absolute path (AGENTS.md #7 class of bug).
    if topo == "anynet" and extra.get("network_file"):
        nf = Path(extra["network_file"])
        if not nf.is_absolute():
            nf = Path.cwd() / nf
        if not nf.exists():
            raise VeritXError(
                f"candidate {name}: network_file not found: {nf}")
        extra["network_file"] = str(nf)
    if topo == "anynet" and not extra.get("network_file"):
        raise VeritXError(
            f"candidate {name}: anynet candidate without network_file — "
            "cannot evaluate; carry the synth_result provenance")
    return evaluate_spec(
        trace_path=trace_path,
        topo_spec=(name, topo, extra, routing),
        seed=seed,
        timeout=timeout,
    )


def _spec_evaluator(*, trace_path: str, seed: int, timeout: int
                    ) -> Callable[[dict], dict]:
    """Compiler ``evaluate`` callable: candidate dict → result dict.

    SynthResult.to_dict() is already the compiler's expected shape
    (status ok/error, latency, seed, provenance, extra); the only
    additions are fidelity (real BookSim execution) and routing evidence.
    """
    def evaluate(cand: dict) -> dict:
        r = _evaluate_candidate(cand, seed=seed, timeout=timeout,
                                trace_path=trace_path).to_dict()
        r["fidelity"] = "NETWORK_SIMULATION"
        return r
    return evaluate


def compile_from_results_file(results_path: str | Path, request_kwargs: dict,
                              *, trace_path: str, seed: int, timeout: int,
                              out_path: str | Path) -> dict[str, Any]:
    """End-to-end: a synthesis results file + declared requirements →
    compiler verdict dict, written to ``out_path`` as evidence.

    Raises the file-not-found OSError loudly (missing input is an
    environment failure, not a design verdict).
    """
    import json

    from veritx_dse.synthesis.compiler import CandidateEvaluationRequest, evaluate_candidates

    data = json.loads(Path(results_path).read_text())
    results = data.get("results", data) if isinstance(data, dict) else data
    candidates = results_to_candidates(list(results))
    request = CandidateEvaluationRequest(candidates=candidates,
                              **{k: v for k, v in request_kwargs.items()
                                 if k != "candidates"})
    out = evaluate_candidates(request, _spec_evaluator(
        trace_path=str(Path(trace_path).resolve()), seed=seed, timeout=timeout))
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    out["output"] = str(out_path)
    return out
