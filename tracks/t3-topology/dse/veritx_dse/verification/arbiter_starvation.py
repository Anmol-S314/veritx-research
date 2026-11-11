"""arbiter_starvation — the wire arbiter's starvation bound, proven and bound to RTL.

The obligation this discharges
------------------------------
``router_template.sv`` gives the escape class priority on the output wire, with
an ``ESC_YIELD_K`` dwell counter as the anti-starvation guard: while both stage
classes are occupied on an output port the counter climbs; at ``ESC_YIELD_K``
the wire is handed to the free class for exactly one window. A7's named
residual was that this guard's *fairness* was asserted but never proven, only
the deadlock-freedom of a dependency graph was.

The theorem, stated so it can be falsified
------------------------------------------
    For one output port, from any state the guard can reach, if the free class
    holds a flit on that port and the escape class also holds it for
    ``ESC_YIELD_K`` consecutive cycles, and the downstream accepts whatever is
    shown, then the wire shows the free class at some cycle ``i <=
    ESC_YIELD_K`` (0-indexed). After that window the counter resets, so the
    bound re-applies and the free class is never blocked without end.

Three things make this a proof rather than a demonstration:

  * the unrolling is exactly ``ESC_YIELD_K`` steps, which is the *whole*
    question -- "is a K-cycle dwell enough" is finite, so nothing is being
    approximated. Tightness is checked separately (K-1 must FAIL), which is
    what stops the bound being satisfied by a proof that would also accept a
    weaker guard;
  * the obligation is discharged by the ``z3`` *binary* on SMT-LIB text this
    module emits, so the artifact can be re-decided by a third party and no
    Python dependency is added to the product. The solver version is recorded
    with the answer;
  * :func:`bind_to_rtl` refuses unless the RTL still contains the branch
    conditions the model was derived from, verbatim, and the declared
    ``ESC_YIELD_K`` still matches. A proof about a state machine that has
    quietly drifted from the router is worth nothing, and that is the standing
    failure mode of a hand-written formal harness.

What is NOT claimed: fairness of the *downstream* port (an input), arbitration
between the classes beyond this bound, progress for the escape class under a
permanently occupied free stage, injection-VC or allocator fairness, the
shared-wire fabric's arbiter, or end-to-end latency. This is one port's
wire-selection guard.

Rationale: docs/decisions/modules/verification.md
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.core.paths import REPO

TOOL = "veritx_dse.verification.arbiter_starvation"
PROOF_METHOD = "ARBITER_DWELL_BOUNDED_SERVICE"
CLAIM = (
    "from any reachable guard state, with both stage classes occupied on an "
    "output port and the downstream accepting what is shown, the wire shows "
    "the free class at some cycle i <= ESC_YIELD_K; the counter then resets, "
    "so the bound re-applies without end")
SCOPE = (
    "one output port's wire-selection guard: bounded service of the free class "
    "under continuous downstream readiness. Downstream fairness, class-vs-class "
    "arbitration beyond the bound, escape-class progress under a permanently "
    "occupied free stage, injection-VC/allocator fairness, the shared-wire "
    "fabric's arbiter and end-to-end latency are NOT modeled")

DEFAULT_RTL = Path("tracks/t3-topology/rtl/mot_htree/router_template.sv")

# The branch conditions the model below is derived from, extracted verbatim so
# drift in the RTL breaks the proof instead of silently invalidating it.
_RTL_ANCHORS = (
    "if (esc_yield_q[po]) begin",
    "end else if (out_valid_all[po][1] && out_valid_all[po][0]) begin",
    "if (esc_starve[po] >= 4'(ESC_YIELD_K - 1))",
    "esc_yield_q[po] <= 1'b1;",
    "esc_starve[po] <= esc_starve[po] + 4'd1;",
    "esc_starve[po]  <= 4'd0;",
)
_ESC_YIELD_K = re.compile(r"localparam\s+int\s+ESC_YIELD_K\s*=\s*(\d+)\s*;")


class ArbiterStarvationError(ValueError, SemanticError):
    """The model, the RTL binding or the solver answer is not what it claims."""


@dataclass(frozen=True)
class RtlBinding:
    """Evidence that the proven state machine is still the router's."""

    path: str
    sha256: str
    esc_yield_k: int
    anchors: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "sha256": self.sha256,
            "esc_yield_k": self.esc_yield_k,
            "anchors_present": list(self.anchors),
        }


def bind_to_rtl(k: int | None = None, *, source: Path | None = None,
                repo_root: Path | None = None) -> RtlBinding:
    """Read the router and refuse unless the guard is still the proven one."""
    root = Path(repo_root) if repo_root is not None else REPO
    path = Path(source) if source is not None else root / DEFAULT_RTL
    if not path.is_file():
        raise ArbiterStarvationError(
            f"the router source the proof is bound to is missing: {path}")
    text = path.read_text()
    match = _ESC_YIELD_K.search(text)
    if match is None:
        raise ArbiterStarvationError(
            f"ESC_YIELD_K is not declared in {path}; the guard this proof "
            "covers no longer exists in the form it was derived from")
    declared_k = int(match.group(1))
    if k is not None and declared_k != k:
        raise ArbiterStarvationError(
            f"the proof asked for ESC_YIELD_K={k} but {path} declares "
            f"{declared_k}; refusing to prove a bound the router does not use")
    missing = [anchor for anchor in _RTL_ANCHORS if anchor not in text]
    if missing:
        raise ArbiterStarvationError(
            f"the starvation guard in {path} no longer contains {len(missing)} "
            f"anchor(s) this proof was derived from, starting with "
            f"{missing[0]!r}; re-derive the model rather than trusting the old "
            "verdict")
    return RtlBinding(
        path=str(path.relative_to(root)) if root in path.parents else str(path),
        sha256=hashlib.sha256(text.encode()).hexdigest(),
        esc_yield_k=declared_k,
        anchors=_RTL_ANCHORS)


def solver_available() -> bool:
    return shutil.which("z3") is not None


def solver_version() -> str:
    try:
        run = subprocess.run(["z3", "--version"], capture_output=True, text=True,
                             timeout=30)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return (run.stdout or run.stderr or "").strip() or "unknown"


def _state_decls(k: int, horizon: int) -> list[str]:
    lines = ["(set-logic QF_LIA)"]
    for i in range(horizon + 1):
        lines.append(f"(declare-fun s{i} () Int)   ; esc_starve at cycle {i}")
        lines.append(f"(declare-fun y{i} () Bool)  ; esc_yield_q at cycle {i}")
    return lines


def _initial_box(k: int, index: int = 0) -> list[str]:
    """The reachable start set: starve in [0, K-1], yield free.

    ``starve`` saturates at K-1 when it arms and resets to 0 on a window, so
    that box is exactly what the guard can hold. Proving over the box is
    stronger than proving over whatever a simulation happened to visit.
    """
    return [f"(assert (>= s{index} 0))", f"(assert (<= s{index} {max(k - 1, 0)}))"]


def _step(k: int, i: int) -> list[str]:
    """The guard's next-state relation, with both stage classes occupied."""
    armed = f"(and (>= s{i} {k - 1}))"
    return [
        f"; cycle {i} -> {i + 1}: if yield then reset, else arm or count",
        f"(assert (= s{i + 1} (ite y{i} 0 (ite (>= s{i} {k - 1}) s{i} (+ s{i} 1)))))",
        f"(assert (= y{i + 1} (and (not y{i}) {armed})))",
    ]


def emit_bound_smtlib(k: int) -> str:
    """The bound obligation: no reachable start blocks the free class past K."""
    horizon = k + 1
    lines = [
        "; arbiter starvation bound -- unsatisfiable means PROVEN",
        f"; ESC_YIELD_K = {k}",
        "; claim: with both stage classes occupied on one output port and the",
        "; downstream accepting what is shown, y (the free window) is true at",
        f"; some cycle i <= {k}, from every reachable guard state.",
        *_state_decls(k, horizon),
        *_initial_box(k, 0),
    ]
    for i in range(horizon):
        lines.extend(_step(k, i))
    lines.append("; assume the free class is never shown inside the bound")
    lines.extend(f"(assert (not y{i}))" for i in range(k + 1))
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def emit_tightness_smtlib(k: int, *, start: tuple[int, bool] | None = None) -> str:
    """K-1 is defeatable, so the K bound is tight rather than merely satisfied."""
    horizon = max(k - 1, 0)
    lines = [
        "; tightness: K-1 must FAIL, else the proven bound is loose",
        f"; ESC_YIELD_K = {k}",
        *_state_decls(k, horizon),
    ]
    if start is None:
        lines.extend(_initial_box(k, 0))
    else:
        starve, yield_q = start
        lines.append(f"(assert (= s0 {int(starve)}))")
        lines.append(f"(assert (= y0 {'true' if yield_q else 'false'}))")
    for i in range(horizon):
        lines.extend(_step(k, i))
    lines.extend(f"(assert (not y{i}))" for i in range(horizon + 1))
    lines.append("(check-sat)")
    return "\n".join(lines) + "\n"


def emit_reset_smtlib(k: int) -> str:
    """After a window the guard returns to (0, false), so the bound re-applies."""
    lines = [
        "; reset step: an armed window must leave the guard at (s=0, y=false)",
        f"; ESC_YIELD_K = {k}",
        *_state_decls(k, 1),
        *_initial_box(k, 0),
        *_step(k, 0),
        "(assert y0)",
        "; a non-reset outcome would be a counterexample",
        "(assert (not (and (= s1 0) (not y1))))",
        "(check-sat)",
    ]
    return "\n".join(lines) + "\n"


def decide(smtlib: str, *, timeout_s: int = 60) -> tuple[str, str]:
    """Ask the z3 binary. Returns (verdict, solver version)."""
    if not solver_available():
        return "unavailable", "unavailable"
    try:
        run = subprocess.run(
            ["z3", "-in", "-T:%d" % max(int(timeout_s), 1)], input=smtlib,
            capture_output=True, text=True, timeout=timeout_s + 30)
    except (OSError, subprocess.SubprocessError):
        return "unknown", solver_version()
    verdict = ""
    for line in (run.stdout or "").splitlines():
        token = line.strip()
        if token in ("sat", "unsat", "unknown"):
            verdict = token
            break
    return (verdict or "unknown"), solver_version()


def prove_bounded_service(k: int) -> dict[str, Any]:
    """Prove the K-cycle bound, prove K-1 is not enough, prove the reset."""
    if type(k) is not int or k < 1:
        raise ArbiterStarvationError(f"ESC_YIELD_K must be a positive int, got {k!r}")
    version = solver_version() if solver_available() else "unavailable"
    bound, _ = decide(emit_bound_smtlib(k))
    if bound == "unavailable":
        raise ArbiterStarvationError(
            "the service bound is decided by the z3 binary; z3 is not on PATH")
    if bound != "unsat":
        raise ArbiterStarvationError(
            f"the {k}-cycle service bound does not hold: z3 returned {bound!r}, "
            "so the guard can block the free class longer than ESC_YIELD_K. Do "
            "not report this as proven")
    loose, _ = decide(emit_tightness_smtlib(k))
    if loose != "sat":
        raise ArbiterStarvationError(
            f"tightness check returned {loose!r}; K-1 should be defeatable. A "
            "tightness check that cannot produce a counterexample means the "
            "model is not the model, and the bound below proves nothing")
    worst, _ = decide(emit_tightness_smtlib(k, start=(0, False)))
    if worst != "sat":
        raise ArbiterStarvationError(
            "the freshly-reset guard should defeat K-1; it did not, so the "
            "model does not match the RTL counter")
    reset, _ = decide(emit_reset_smtlib(k))
    if reset != "unsat":
        raise ArbiterStarvationError(
            "the guard does not return to (starve=0, yield=0) after a window, "
            "so the bound does not re-apply and starvation is possible again")
    return {
        "claim": CLAIM,
        "scope": SCOPE,
        "proof_method": PROOF_METHOD,
        "esc_yield_k": k,
        "bound_cycles": k,
        "bounded_service_verdict": "unsat-no-counterexample",
        "tight_bound_cycles": k - 1,
        "tightness_verdict": "sat-counterexample",
        "tightness_witness": {"start_starve": 0, "start_yield": False},
        "tightness_witness_verdict": "sat-counterexample",
        "reset_step_verdict": "unsat-no-counterexample",
        "reachable_start_states": 2 * k,
        "solver": "z3",
        "solver_version": version,
        "eventually_often": (
            "the reset step makes the bound re-applicable, so with both classes "
            f"continuously occupied the free class is shown the wire at least "
            f"once every {k + 1} cycles, without end"),
        "modeled": ["bounded service of the free class", "guard reset"],
        "not_modeled": ["downstream acceptance fairness", "end-to-end latency",
                        "injection-VC and allocator fairness",
                        "the shared-wire fabric's arbiter"],
        "smt_sha256": {
            "bound": hashlib.sha256(emit_bound_smtlib(k).encode()).hexdigest(),
            "tightness": hashlib.sha256(
                emit_tightness_smtlib(k).encode()).hexdigest(),
            "reset": hashlib.sha256(emit_reset_smtlib(k).encode()).hexdigest(),
        },
    }


def verify(*, k: int | None = None, source: Path | None = None,
           repo_root: Path | None = None) -> dict[str, Any]:
    """The full artifact: RTL binding + proven bound, digested."""
    binding = bind_to_rtl(k, source=source, repo_root=repo_root)
    proof = prove_bounded_service(binding.esc_yield_k)
    payload = {
        "schema": "veritx/arbiter-starvation-proof/1",
        "tool": TOOL,
        "rtl_binding": binding.as_dict(),
        **proof,
    }
    payload["proof_id"] = hashlib.sha256(
        repr(sorted((key, repr(value)) for key, value in payload.items())
             ).encode()).hexdigest()
    return payload


__all__ = [
    "ArbiterStarvationError", "CLAIM", "PROOF_METHOD", "RtlBinding", "SCOPE",
    "TOOL", "bind_to_rtl", "decide", "emit_bound_smtlib", "emit_reset_smtlib",
    "emit_tightness_smtlib", "prove_bounded_service", "solver_available",
    "solver_version", "verify",
]
