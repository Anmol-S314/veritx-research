"""API boundary pins — consolidation freeze (reviewer's FINAL FREEZE PATCH).

Two contracts, pinned at the public seam:

  1. NO PYTHON CALLABLES cross the external API boundary — structurally:
     ``api.compile_fabric`` has no ``evaluate`` parameter; the evaluator
     is selected by registered ID. Dependency injection exists only on
     the private seam (``api._compile_fabric_with_evaluator``), used by
     host embeddings and tests (synthesis.bridge does exactly that).

  2. Budgets are real MAXIMA: over-budget ``timeout`` (compile) and
     over-budget ``timeout_s`` / spec ``simulation.timeout_s`` (execute)
     are REJECTED with status INVALID — never clamped.

Compile verdicts here use the private seam with a stub evaluator: this
file pins the boundary, not the compiler (test_fabric_compiler.py owns
that seam). No BookSim binary is required.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse import api


# ── Contract 1: the boundary is structural ─────────────────────────────────

def test_public_compile_fabric_has_no_evaluate_parameter():
    """The public signature must not accept ``evaluate`` — callables are
    structurally impossible, not merely discouraged."""
    import inspect
    params = inspect.signature(api.compile_fabric).parameters
    assert "evaluate" not in params, (
        "api.compile_fabric must not expose an evaluate callable — the "
        "agent-safe boundary takes registered evaluator IDs only")
    assert "evaluator_id" in params
    assert "trace_path" in params


def test_public_compile_fabric_requires_evaluator_id():
    out = api.compile_fabric([], [])
    assert out["status"] == "INVALID" and out["valid"] is False
    assert "evaluator_id" in out["reasons"][0]


def test_public_compile_fabric_rejects_unknown_evaluator_id():
    out = api.compile_fabric([], [], evaluator_id="mystery")
    assert out["status"] == "UNSUPPORTED" and out["valid"] is False


def test_public_compile_fabric_declares_analytical_unsupported():
    out = api.compile_fabric([], [], evaluator_id="analytical")
    assert out["status"] == "UNSUPPORTED" and out["valid"] is False
    assert "UNSUPPORTED" in out["reasons"][0]


def test_public_compile_fabric_booksim_requires_trace_path():
    out = api.compile_fabric([], [], evaluator_id="booksim")
    assert out["status"] == "INVALID" and out["valid"] is False
    assert "trace_path" in out["reasons"][0]


def test_di_seam_is_private_and_not_exported():
    """The injection seam exists for embeddings/tests but is private and
    outside ``__all__`` — not part of the advertised surface."""
    assert callable(api._compile_fabric_with_evaluator)
    assert not hasattr(api, "compile_fabric_with_evaluator") or \
        api.compile_fabric_with_evaluator is api._compile_fabric_with_evaluator
    assert "_compile_fabric_with_evaluator" not in api.__all__
    assert "compile_fabric" in api.__all__


def test_di_seam_works_with_stub_evaluator():
    """The private seam still drives the real compiler (host-embedding path)."""

    def _stub_eval(cand: dict) -> dict:
        return {"name": cand["name"], "topology": "anynet", "backend": "anynet",
                "nodes": 16, "edges": 32, "latency": 61.5, "status": "ok",
                "error": None, "seed": 0, "provenance": "stub", "extra": {}}

    out = api._compile_fabric_with_evaluator(
        [{"qos_class": "latency_critical", "latency_ceiling_cycles": 100.0,
          "binding": True}],
        [{"name": "a", "topology": "anynet", "seed": 0,
          "fidelity": "NETWORK_SIMULATION"}],
        evaluate=_stub_eval)
    assert out["status"] == "OK"
    assert out["result"]["verdict"] == "FEASIBLE"


# ── Contract 2: budgets are maxima, never clamped ──────────────────────────

def test_compile_rejects_timeout_over_budget():
    out = api.compile_fabric([], [], evaluator_id="booksim",
                             trace_path="/tmp/unused.jsonl",
                             timeout=api.BUDGETS["max_execution_seconds"] + 1)
    assert out["status"] == "INVALID" and out["valid"] is False
    assert "timeout" in out["reasons"][0]
    assert str(api.BUDGETS["max_execution_seconds"]) in out["reasons"][0]


def test_compile_rejects_nonpositive_timeout():
    out = api.compile_fabric([], [], evaluator_id="booksim",
                             trace_path="/tmp/unused.jsonl", timeout=0)
    assert out["status"] == "INVALID" and out["valid"] is False


def test_compile_rejects_over_budget_before_trace_path_check():
    """Budget refusal must not be laundered into a trace_path error."""
    out = api.compile_fabric([], [], evaluator_id="booksim",
                             trace_path=None, timeout=999_999)
    assert out["status"] == "INVALID"
    assert "timeout" in out["reasons"][0]


def test_execute_rejects_over_budget_explicit_timeout():
    out = api.execute({"name": "x", "topology": {"kind": "preset",
                                                 "name": "mesh4x4"}},
                      timeout_s=999_999)
    assert out["status"] == "INVALID" and out["valid"] is False
    assert "exceeds API maximum" in out["reasons"][0]


def test_execute_rejects_over_budget_spec_timeout():
    out = api.execute({"name": "x", "topology": {"kind": "preset",
                                                 "name": "mesh4x4"},
                       "simulation": {"timeout_s": 999_999}})
    assert out["status"] == "INVALID" and out["valid"] is False
    assert "exceeds API maximum" in out["reasons"][0]


@pytest.mark.parametrize("bad", [-5, 0])
def test_execute_rejects_nonpositive_timeout(bad):
    out = api.execute({"name": "x", "topology": {"kind": "preset",
                                                 "name": "mesh4x4"}},
                      timeout_s=bad)
    assert out["status"] == "INVALID" and out["valid"] is False
