"""The arbiter's starvation bound: proven, tight, and still bound to the RTL.

Four separate things are asserted, because a fairness proof is worth exactly
the weakest of them:

  * the bound HOLDS -- no reachable start state blocks the free class past
    ESC_YIELD_K;
  * the bound is TIGHT -- K-1 is defeatable, so the number is not merely
    satisfied by a proof that would also accept a weaker guard;
  * the model is the model -- a deliberately weaker guard must FAIL the same
    encoding, otherwise the encoding proves nothing about anything;
  * the state machine proven is still the router's -- the branch conditions are
    extracted verbatim from router_template.sv and drift is refused.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.verification.arbiter_starvation import (  # noqa: E402
    ArbiterStarvationError,
    bind_to_rtl,
    decide,
    emit_bound_smtlib,
    emit_reset_smtlib,
    emit_tightness_smtlib,
    prove_bounded_service,
    solver_available,
    verify,
)

pytestmark = pytest.mark.skipif(
    not solver_available(), reason="the service bound is decided by the z3 binary")


def test_the_bound_is_proven_for_the_rtl_value():
    proof = prove_bounded_service(4)
    assert proof["bounded_service_verdict"] == "unsat-no-counterexample"
    assert proof["bound_cycles"] == 4
    assert proof["reset_step_verdict"] == "unsat-no-counterexample"
    assert proof["solver"] == "z3"
    assert proof["solver_version"].startswith("Z3 version")


def test_the_bound_is_tight_so_the_number_is_not_loose():
    proof = prove_bounded_service(4)
    assert proof["tightness_verdict"] == "sat-counterexample"
    # The worst case is the freshly-reset counter: it needs the full dwell.
    assert proof["tightness_witness"] == {"start_starve": 0, "start_yield": False}
    assert proof["tightness_witness_verdict"] == "sat-counterexample"


@pytest.mark.parametrize("k", [1, 2, 4, 8])
def test_the_bound_generalises_over_the_dwell_constant(k):
    proof = prove_bounded_service(k)
    assert proof["bound_cycles"] == k
    assert proof["bounded_service_verdict"] == "unsat-no-counterexample"
    assert proof["reachable_start_states"] == 2 * k


@pytest.mark.parametrize("k", [0, -1, 1.5, "4", None])
def test_a_nonsense_dwell_constant_is_refused(k):
    with pytest.raises(ArbiterStarvationError):
        prove_bounded_service(k)


def test_the_encoding_names_the_question_it_asks():
    """A reader must be able to see it is the right question."""
    script = emit_bound_smtlib(4)
    assert "(set-logic QF_LIA)" in script
    assert "unsatisfiable means PROVEN" in script
    assert script.count("(assert (not y") == 5      # cycles 0..K
    # K+1 transitions for K+1 states.
    assert script.count("(assert (= y") == 5
    assert script.rstrip().endswith("(check-sat)")
    assert decide(script)[0] == "unsat"


def test_tightness_encoding_is_satisfiable_and_reset_is_not():
    assert decide(emit_tightness_smtlib(4))[0] == "sat"
    assert decide(emit_reset_smtlib(4))[0] == "unsat"


def test_a_weaker_guard_fails_the_same_encoding():
    """If a weaker guard also passed, the encoding would prove nothing.

    The router arms at ``starve >= K-1``. Here the arm condition is moved to
    ``starve >= K``, one cycle later, and the K-cycle obligation must become
    satisfiable-violated (sat), i.e. the bound must NOT hold.
    """
    k = 4
    horizon = k + 1
    lines = ["(set-logic QF_LIA)"]
    for i in range(horizon + 1):
        lines.append(f"(declare-fun s{i} () Int)")
        lines.append(f"(declare-fun y{i} () Bool)")
    lines.append("(assert (>= s0 0))")
    lines.append(f"(assert (<= s0 {k - 1}))")
    for i in range(horizon):
        # The WEAKER guard: arms only past K.
        lines.append(f"(assert (= s{i + 1} (ite y{i} 0 (ite (>= s{i} {k}) s{i} (+ s{i} 1)))))")
        lines.append(f"(assert (= y{i + 1} (and (not y{i}) (>= s{i} {k}))))")
    lines.extend(f"(assert (not y{i}))" for i in range(k + 1))
    lines.append("(check-sat)")
    assert decide("\n".join(lines) + "\n")[0] == "sat", (
        "a weaker guard must break the bound; if this is unsat the encoding is "
        "not sensitive to the guard it claims to prove")


def test_the_proof_is_bound_to_the_router_that_exists():
    binding = bind_to_rtl()
    assert binding.esc_yield_k == 4
    assert binding.sha256 and len(binding.sha256) == 64
    assert binding.path.endswith("router_template.sv")
    assert len(binding.anchors) >= 6


def test_asking_for_a_dwell_the_router_does_not_use_is_refused():
    with pytest.raises(ArbiterStarvationError, match="declares"):
        bind_to_rtl(8)


def test_drift_in_the_guard_breaks_the_proof_instead_of_hiding(tmp_path):
    """A proof about a state machine that moved is worthless; refuse it."""
    real = Path(__file__).resolve().parents[2] / "rtl" / "mot_htree" / "router_template.sv"
    text = real.read_text()
    drifted = tmp_path / "router_template.sv"
    drifted.write_text(text.replace(
        "if (esc_starve[po] >= 4'(ESC_YIELD_K - 1))",
        "if (esc_starve[po] > 4'(ESC_YIELD_K))", 1))
    with pytest.raises(ArbiterStarvationError, match="anchor"):
        bind_to_rtl(source=drifted, repo_root=tmp_path)


def test_a_removed_dwell_constant_is_refused(tmp_path):
    real = Path(__file__).resolve().parents[2] / "rtl" / "mot_htree" / "router_template.sv"
    text = real.read_text()
    stripped = tmp_path / "router_template.sv"
    stripped.write_text(text.replace("localparam int ESC_YIELD_K = 4;", "", 1))
    with pytest.raises(ArbiterStarvationError, match="ESC_YIELD_K is not declared"):
        bind_to_rtl(source=stripped, repo_root=tmp_path)


def test_verify_carries_the_binding_a_digest_and_the_limits():
    proof = verify()
    assert proof["schema"] == "veritx/arbiter-starvation-proof/1"
    assert proof["rtl_binding"]["esc_yield_k"] == 4
    assert proof["proof_id"] and len(proof["proof_id"]) == 64
    assert "downstream acceptance fairness" in proof["not_modeled"]
    assert set(proof["smt_sha256"]) == {"bound", "tightness", "reset"}
