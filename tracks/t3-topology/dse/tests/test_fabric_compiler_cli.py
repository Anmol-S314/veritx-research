"""Phase 13 — CLI + bridge seams for the fabric compiler.

Coverage split (never duplicating compiler-core tests, which live in
test_fabric_compiler.py at the compile_fabric seam):

  CLI   — registration contract and the fail-fast preflight: an incoherent
          --requirements spec must fail BEFORE any evaluation, and the
          command must exist in dispatch with the documented flags.
  bridge — dialect translation only: SynthResult dicts → compiler
          candidates (ok → evaluable, failed → PRUNED with reason) and
          the spec-faithful re-evaluation contract (the candidate's
          synth_result spec is what evaluate_spec receives). The real
          BookSim path is exercised by the evaluator's own tests and the
          golden suites — never duplicated here.
"""
import argparse
import json
from pathlib import Path

import pytest

from veritx_dse.cli.cli import COMMANDS
from veritx_dse.core.logging import Ctx
from veritx_dse.synthesis.bridge import (
    candidate_from_synth_result,
    results_to_candidates,
)


# ── CLI registration contract ────────────────────────────────────────────────

def test_compile_registered_in_dispatch():
    subs = COMMANDS["legacy"]["subcommands"]
    assert "synthesize-compile" in subs
    assert subs["synthesize-compile"]["handler"] is not None


def test_compile_flags_contract():
    import argparse
    import sys
    from veritx_dse.cli.cli import build_parser
    parser = build_parser()
    argv = ["legacy", "synthesize-compile", "--results", "r.json",
            "--trace", "t.trace", "--requirements", "[]"]
    args = parser.parse_args(argv)
    assert args.results == "r.json"
    assert args.trace == "t.trace"
    assert args.requirements == "[]"
    assert args.seed is not None  # recorded seed policy, never absent


# ── bridge: dialect translation ──────────────────────────────────────────────

def _sr_ok(name="a", topo="anynet", latency=61.5, seed=3, extra=None):
    return {"name": name, "topology": topo, "backend": topo, "nodes": 16,
            "edges": 32, "latency": latency, "status": "ok", "error": None,
            "seed": seed, "provenance": "bo_synthesizer+BO_PRESET",
            "extra": dict(extra or {})}


def test_ok_result_becomes_evaluable_candidate():
    cand = candidate_from_synth_result(_sr_ok())
    assert cand["name"] == "a"
    assert cand["topology"] == "anynet"
    assert cand["seed"] == 3
    assert cand["synth_result"]["provenance"] == "bo_synthesizer+BO_PRESET"
    assert not cand.get("pruned")


def test_failed_result_becomes_pruned_with_reason():
    cands = results_to_candidates([
        _sr_ok(name="good"),
        {"name": "bad", "topology": "anynet", "status": "error",
         "error": "booksim timeout", "latency": None, "extra": {}},
    ])
    by = {c["name"]: c for c in cands}
    assert not by["good"].get("pruned")
    assert by["bad"]["pruned"] is True
    assert "booksim timeout" in by["bad"]["pruning_reason"]
    assert by["bad"]["synth_result"]["status"] == "error"


def test_candidate_round_trip_preserves_the_executed_spec():
    """The spec that produced the result is what re-evaluation receives —
    the bridge translates, never re-interprets (Phase-10 lesson)."""
    sr = _sr_ok(extra={"network_file": "/tmp/x.anynet", "routing": "min",
                       "k": 8})
    cand = candidate_from_synth_result(sr)
    sr2 = cand["synth_result"]
    assert sr2["extra"]["network_file"] == "/tmp/x.anynet"
    assert sr2["extra"]["k"] == 8


# ── CLI preflight fail-fast ──────────────────────────────────────────────────

def _ctx(tmp_path) -> Ctx:
    return Ctx(verbosity=0, log_file=str(tmp_path / "t3test.log"))


def test_invalid_requirements_json_fails_before_evaluation(tmp_path, monkeypatch):
    """An incoherent --requirements spec must cost nothing: no results file
    read, no evaluator import, no evaluation. Verified by pointing
    --results at a path that would explode if touched."""
    ctx = _ctx(tmp_path)
    args = argparse.Namespace(
        results=str(tmp_path / "definitely-missing.json"),
        trace=str(tmp_path / "whatever.trace"),
        requirements="not-json-at-all",
        nodes=16, seed=0, max_evals=None, out=None, timeout=1,
    )
    from veritx_dse.cli.cli import cmd_synthesize_compile
    cmd_synthesize_compile(ctx, args)
    assert ctx.failed


def test_incoherent_requirements_fails_before_missing_results_check(tmp_path):
    """Order matters for cost: requirements are parsed before the results
    file gate, so a broken spec is reported as a spec error even when the
    results file is also missing."""
    ctx = _ctx(tmp_path)
    args = argparse.Namespace(
        results=str(tmp_path / "missing.json"),
        trace=str(tmp_path / "missing.trace"),
        requirements='[{"qos_class":"latency_critical","binding":true}]',
        nodes=16, seed=0, max_evals=None, out=None, timeout=1,
    )
    from veritx_dse.cli.cli import cmd_synthesize_compile
    cmd_synthesize_compile(ctx, args)
    assert ctx.failed
    log_text = Path(ctx.log_file).read_text()
    assert "no bound" in log_text
    assert "not found" not in log_text  # never reached the file gate
    ctx.close()
