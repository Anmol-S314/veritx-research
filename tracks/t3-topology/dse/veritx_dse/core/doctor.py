"""core/doctor.py — `veritx doctor`: self-check battery for the harness.

Why this exists: every session ends with the same ritual — run a smattering
of commands, eyeball numbers, hunt "funny results" by hand (phantom
0-injection traffic, timeout-as-failure, means over mismatched populations).
Doctor turns that ritual into one command with two levels:

    veritx doctor --level quick   # seams + binaries + calibration anchors. <5 s
    veritx doctor --level deep    # + tiny live runs of every command family
    veritx doctor --llm           # + LLM second opinion on the full log dump

Design (deep module at one seam):

    run_checks(level, checks=None) -> DoctorReport      # the interface
    review_with_llm(report) -> dict | None              # advisory adapter

Checks are pure-ish functions returning Observation(name, status, expected,
observed). "Funny" is computable locally where a calibrated anchor exists
(e.g. the 8-NPU all-gather must reproduce 119,080 BookSim cycles within
0.5%); the LLM layer is a *second opinion* appended to the report with the
harness log tail — it never gates the verdict, and its absence (no API key)
degrades to a plain report.

Contracts used here are verified against the live code, not invented:
- CLI:      `evaluate booksim --trace --topo`, `certify flow --model --topo`,
            `topology diff --ir --ets` (all timeout-flagged, VERITX_TIMEOUT-aware)
- seams:    paths.BOOKSIM_BIN/ASTRA_BS_BIN/REPO, booksim.BASE_PARAMS,
            topology_ir.BOOKSIM_DEFAULTS (equal-by-test), presets.lookup_topo
- anchors:  docs/CALIBRATION.md rows (119,080 / 106,949 / 56 pkts / 9-cycle wire)
- formats:  trace "cycle src class dst size" 5-col, anynet links
            "router N node M" + "router A router B w", TrafficModel
            network.flow_classes[{name,comm_type,invocations_per_batch,
            bytes_per_invocation,instances[{participants[]}]}]
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .paths import ASTRA_BS_BIN, ASTRA_DIR, BOOKSIM_BIN, DSE_DIR, REPO

# ── data model ────────────────────────────────────────────────────────────

STATUS_MARK = {"pass": "✓", "warn": "⚠", "fail": "✗", "skip": "-"}


@dataclass
class Observation:
    """One check's outcome. `expected` vs `observed` is the funny-detector."""
    name: str
    status: str                     # pass | warn | fail | skip
    expected: str = ""
    observed: str = ""
    seconds: float = 0.0

    def to_dict(self) -> dict:
        return {"name": self.name, "status": self.status,
                "expected": self.expected, "observed": self.observed,
                "seconds": round(self.seconds, 3)}


@dataclass
class DoctorReport:
    level: str
    started: str
    seconds: float
    checks: list[Observation]
    log_tail: list[str] = field(default_factory=list)   # for the LLM layer
    llm: dict | None = None

    @property
    def verdict(self) -> str:
        s = {c.status for c in self.checks}
        if "fail" in s:
            return "FAIL"
        if "warn" in s:
            return "WARN"
        return "PASS"

    def counts(self) -> dict:
        c = {"pass": 0, "warn": 0, "fail": 0, "skip": 0}
        for o in self.checks:
            c[o.status] = c.get(o.status, 0) + 1
        return c

    def summary(self) -> str:
        c = self.counts()
        return (f"verdict={self.verdict} pass={c['pass']} warn={c['warn']} "
                f"fail={c['fail']} skip={c['skip']} level={self.level} "
                f"({self.seconds:.1f}s)")

    def to_dict(self) -> dict:
        return {"level": self.level, "started": self.started,
                "seconds": round(self.seconds, 1), "verdict": self.verdict,
                "counts": self.counts(),
                "checks": [c.to_dict() for c in self.checks],
                "log_tail": self.log_tail, "llm": self.llm}


# ── calibrated anchors (docs/CALIBRATION.md, 2026-09-16) ─────────────────

ANCHOR_BOOKSIM_CYCLES = 119080     # mesh8 8×1 MB all-gather, BookSim leg
ANCHOR_ANALYTICAL_CYCLES = 106949  # same IR, analytical leg
ANCHOR_TOL_PCT = 0.5               # live determinism: drift >0.5% = warn

# ── fixed-size fixtures (every byte verified against the real parsers) ───

TINY_TRACE = "0 0 0 1 4\n10 1 0 2 4\n20 2 0 3 4\n30 3 0 0 4\n"

MESH8_IR = {
    "schema_version": "0",
    "name": "mesh8",
    "kind": "mesh",
    "nodes": 8,
    "params": {"k": 8, "n": 1},
    "dims": [{"topology": "Ring", "count": 8,
              "bandwidth_GBs": 64.0, "latency_ns": 9.0}],
    "link_attrs": {"bandwidth_GBs": 64.0, "latency_ns": 9.0},
    "rtl": {"layout": "grid", "rows": 8, "cols": 1},
}

RING4_LINKS = ("router 0 node 0 router 1 router 3\n"
               "router 1 node 1 router 0 router 2\n"
               "router 2 node 2 router 1 router 3\n"
               "router 3 node 3 router 2 router 0\n")

RING4_MODEL = {"network": {"flow_classes": [{
    "name": "allgather",
    "comm_type": "ALLGATHER",
    "invocations_per_batch": 1,
    "bytes_per_invocation": 512,
    "instances": [{"participants": [0, 1, 2, 3]}],
}]}}

# 16-rank ring allreduce — sized for the REAL configs/anynet16.links
# (the certify live check runs against that file, not a synthetic fixture).
RING4_MODEL_16 = {"network": {"flow_classes": [{
    "name": "allgather",
    "comm_type": "ALLGATHER",
    "invocations_per_batch": 1,
    "bytes_per_invocation": 512,
    "instances": [{"participants": list(range(16))}],
}]}}

# ── level: quick ──────────────────────────────────────────────────────────


def _check_bins(log: list[str]) -> list[Observation]:
    obs = []
    for name, path in (("booksim", BOOKSIM_BIN),
                       ("astra_booksim",
                        ASTRA_DIR / "astra-sim" / "network_frontend"
                        / "booksim2" / "bin" / "AstraSim_BookSim2")):
        obs.append(Observation(
            name=f"bin.{name}",
            status="pass" if path.exists() else "fail",
            expected=str(path),
            observed="exists" if path.exists() else "missing"))
    # analytical launcher (topology diff leg B); warn, not fail — its
    # absence only removes one diff leg.
    ana = ASTRA_DIR / "astra-sim" / "build" / "astra_analytical" / "build" \
        / "AnalyticalAstra" / "bin" / "AnalyticalAstra"
    obs.append(Observation(
        name="bin.analytical", status="pass" if ana.exists() else "warn",
        expected=str(ana),
        observed="exists" if ana.exists()
        else "missing (topology diff leg B unavailable)"))
    return obs


def _check_config_seams(log: list[str]) -> list[Observation]:
    """Re-verify live the equality that tests pin at rest: the two BookSim
    default dicts must never drift (they encode the calibrated protocol)."""
    from ..model import topology_ir as tir
    from ..simulation import booksim as bs
    drifted = {k: (tir.BOOKSIM_DEFAULTS.get(k), bs.BASE_PARAMS.get(k))
               for k in tir.BOOKSIM_DEFAULTS
               if tir.BOOKSIM_DEFAULTS.get(k) != bs.BASE_PARAMS.get(k)}
    return [Observation(
        name="seam.booksim_defaults_match",
        status="pass" if not drifted else "fail",
        expected="topology_ir.BOOKSIM_DEFAULTS == simulation.booksim.BASE_PARAMS",
        observed="equal" if not drifted else f"drifted: {drifted}")]


def _check_calibration_docs(log: list[str]) -> list[Observation]:
    cal = DSE_DIR.parent / "docs" / "CALIBRATION.md"
    if not cal.exists():
        return [Observation(name="docs.calibration", status="warn",
                            observed="docs/CALIBRATION.md not found")]
    text = cal.read_text()
    ok = ("119,080" in text) or ("119080" in text)
    return [Observation(
        name="docs.calibration", status="pass" if ok else "warn",
        expected="anchor row 119,080 cycles present",
        observed="anchor present" if ok else "anchor row missing")]


# ── level: deep (tiny live runs, every family) ────────────────────────────


def _cli(cwd: str | None = None) -> list[str]:
    """One CLI entry: python -m veritx_dse.cli, run from DSE_DIR so every
    REPO/DSE_DIR-relative default inside the CLI resolves."""
    return [sys.executable, "-m", "veritx_dse.cli"]


def _absorb(log: list[str], r: subprocess.CompletedProcess, tail: int = 8):
    log.extend((r.stdout or "").splitlines()[-tail:])
    log.extend((r.stderr or "").splitlines()[-tail:])


@dataclass
class _LiveRun:
    """Shared stack frame for one timed CLI live run (semantic compression:
    the three live checks repeated this scaffold; now it happens once)."""
    args: list[str]
    timeout: int
    log: list[str]
    r: subprocess.CompletedProcess | None = None
    timed_out: bool = False
    seconds: float = 0.0

    @property
    def out(self) -> str:
        if self.r is None:
            return ""
        return (self.r.stdout or "") + (self.r.stderr or "")


def _run_live(args: list[str], timeout: int, log: list[str],
              tail: int = 8) -> _LiveRun:
    """Timed subprocess run of one CLI command with log absorption."""
    t0 = time.time()
    run = _LiveRun(args=args, timeout=timeout, log=log)
    try:
        run.r = _run_cli(args, timeout)
        _absorb(log, run.r, tail=tail)
    except subprocess.TimeoutExpired:
        run.timed_out = True
    run.seconds = time.time() - t0
    return run


def _timeout_obs(name: str, run: _LiveRun, expected: str) -> Observation:
    return Observation(name=name, status="fail", expected=expected,
                       observed="timeout", seconds=run.seconds)


def _run_cli(cmd: list[str], timeout: int) -> subprocess.CompletedProcess:
    return subprocess.run(_cli() + cmd, cwd=str(DSE_DIR),
                          capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def _absorb(log: list[str], r: subprocess.CompletedProcess, tail: int = 8):
    log.extend((r.stdout or "").splitlines()[-tail:])
    log.extend((r.stderr or "").splitlines()[-tail:])


def _check_live_booksim(log: list[str]) -> list[Observation]:
    """Smallest honest replay: 4 packets on mesh. Funny-detectors:
    exit 0, no traceback, positive sane latency."""
    with tempfile.TemporaryDirectory(prefix="doctor_bs_") as td:
        trace = Path(td) / "tiny.trace"
        trace.write_text(TINY_TRACE)
        run = _run_live(["evaluate", "booksim", "--trace", str(trace),
                         "--topo", "mesh", "--timeout", "120"], 150, log)
    if run.timed_out:
        return [_timeout_obs("live.evaluate_booksim", run,
                             "exit 0 within 150s")]
    combined = run.out
    funny = None
    if run.r.returncode != 0:
        funny = f"exit {run.r.returncode}"
    elif "Traceback" in combined:
        funny = "traceback in output"
    # Real success line: "✓ Completion: 51c | p50: 13c | ..."
    lat = re.search(r"Completion:\s*([\d,]+(?:\.\d+)?)\s*c\b", combined)
    if not funny and not lat:
        funny = "exit 0 but no Completion metric (exit-0-no-metric class)"
    if not funny and lat:
        lat_v = float(lat.group(1).replace(",", ""))
        if lat_v <= 0 or lat_v < 1:
            funny = f"impossible completion {lat_v}c (≤0 or <1 cycle)"
    return [Observation(
        name="live.evaluate_booksim",
        status="fail" if funny else "pass",
        expected="exit 0, latency metric present, no traceback",
        observed=funny or f"completion≈{lat.group(1)}c",
        seconds=run.seconds)]


def _check_live_certify(log: list[str]) -> list[Observation]:
    """Ring allreduce model vs the REAL configs/anynet16.links must PASS.

    Uses the repo's canonical two-line links file, not a synthetic fixture
    — it exercises the exact path a user would (and did break: the parser
    once read this dialect as an empty graph).
    """
    links = DSE_DIR.parent / "configs" / "anynet16.links"
    if not links.exists():
        return [Observation(name="live.certify_flow", status="skip",
                            observed=f"{links.name} not found")]
    with tempfile.TemporaryDirectory(prefix="doctor_ct_") as td:
        td = Path(td)
        model = td / "tm.json"
        model.write_text(json.dumps(RING4_MODEL_16))
        run = _run_live(["certify", "flow", "--model", str(model),
                         "--topo", str(links), "--timeout", "120"], 150, log)
    if run.timed_out:
        return [_timeout_obs("live.certify_flow", run,
                             "PASS verdict within 150s")]
    out = run.out
    passed = "Verdict: PASS" in out
    failed = "Verdict: FAIL" in out
    # cmd_certify_flow exits 1 when the verdict is FAIL; both facts
    # must agree — exit 0 + FAIL verdict is itself a contract breach.
    consistent = (run.r.returncode == 0) == passed and (passed != failed)
    return [Observation(
        name="live.certify_flow",
        status="pass" if consistent and passed else "fail",
        expected="ring allreduce certifies against configs/anynet16.links "
                 "(exit 0 ⟺ Verdict: PASS)",
        observed=f"exit {run.r.returncode}, "
                 f"{'Verdict: PASS' if passed else 'Verdict: FAIL' if failed else 'no verdict'}"
                 + ("" if consistent else " [exit-code/verdict mismatch]"),
        seconds=run.seconds)]


def _check_live_topology_diff(log: list[str]) -> list[Observation]:
    """The calibrated anchor, reproduced live: mesh8 diff must land within
    0.5% of 119,080 BookSim cycles. This is the deepest funny-detector:
    any drift here means every other number is suspect."""
    ets = (ASTRA_DIR / "examples" / "workload" / "microbenchmarks"
           / "all_gather" / "8npus_1MB" / "all_gather")
    if not Path(f"{ets}.0.et").exists():
        return [Observation(name="live.topology_diff", status="skip",
                            observed=f"all-gather ETs not found: {ets}")]
    with tempfile.TemporaryDirectory(prefix="doctor_ir_") as td:
        ir = Path(td) / "mesh8.topo.json"
        ir.write_text(json.dumps(MESH8_IR))
        run = _run_live(["topology", "diff", "--ir", str(ir),
                         "--ets", str(ets), "--timeout", "300"], 360, log,
                        tail=12)
    if run.timed_out:
        return [_timeout_obs("live.topology_diff", run, "both legs within 360s")]
    combined = run.out
    # Real success line: "✓ topology diff mesh8: booksim=119,080c
    # analytical=106,949c divergence=10.19% (close)"
    m = re.search(r"booksim=([\d,]+)c\s+analytical=([\d,]+)c", combined)
    if run.r.returncode != 0 or not m:
        last = (combined.splitlines() or ["<no output>"])[-1]
        return [Observation(name="live.topology_diff", status="fail",
                            expected=f"booksim≈{ANCHOR_BOOKSIM_CYCLES}c",
                            observed=f"exit {run.r.returncode}: {last[-120:]}",
                            seconds=run.seconds)]
    bs_c = int(m.group(1).replace(",", ""))
    drift = abs(bs_c - ANCHOR_BOOKSIM_CYCLES) / ANCHOR_BOOKSIM_CYCLES * 100
    return [Observation(
        name="live.topology_diff",
        status="pass" if drift <= ANCHOR_TOL_PCT else "warn",
        expected=f"booksim={ANCHOR_BOOKSIM_CYCLES}c "
                 f"(analytical≈{ANCHOR_ANALYTICAL_CYCLES}c)",
        observed=f"booksim={bs_c}c, drift {drift:.2f}%",
        seconds=run.seconds)]


def _check_live_astra(log: list[str]) -> list[Observation]:
    """Live ASTRA leg: the 16-rank one-coll fixture through evaluate astra.

    Mirrors tests/test_evaluate_astra.py::TestLiveAstra (the certified
    recipe). Paths MUST be absolute: the embedded frontend resolves
    config paths against the process cwd (cwd-relative --network-config
    fails with 'cannot open config' — discovered live by this check).
    Funny-detectors: exit 0, status ok, cycles > 0, [plat] packets > 0.
    """
    fix = DSE_DIR / "tests" / "fixtures" / "astra_tiny"
    ets = fix / "one-coll.et"
    if not (ASTRA_BS_BIN.exists() and ets.exists()):
        return [Observation(name="live.evaluate_astra", status="skip",
                            observed="binary or astra_tiny fixture missing")]
    with tempfile.TemporaryDirectory(prefix="doctor_as_") as td:
        run = _run_live(
            ["evaluate", "astra", "--ets", str(ets.resolve()),
             "--system-config", str((fix / "system.json").resolve()),
             "--network-config", str((fix / "network.json").resolve()),
             "--memory-config", str((fix / "memory.json").resolve()),
             "--timeout", "240"], 300, log, tail=10)
    if run.timed_out:
        return [_timeout_obs("live.evaluate_astra", run,
                             "exit 0 within 300s")]
    combined = run.out
    if run.r.returncode != 0:
        last = (combined.splitlines() or ["<no output>"])[-1]
        return [Observation(name="live.evaluate_astra", status="fail",
                            expected="exit 0, status ok, plat packets > 0",
                            observed=f"exit {run.r.returncode}: {last[-120:]}",
                            seconds=run.seconds)]
    if "Traceback" in combined:
        return [Observation(name="live.evaluate_astra", status="fail",
                            expected="exit 0, status ok, plat packets > 0",
                            observed="traceback in output",
                            seconds=run.seconds)]
    # Parse the artifact JSON (status/cycles/plat_stats), not stdout —
    # the artifact is the contract; the "Saved:" line locates it.
    saved = re.search(r"Saved:\s*(\S+eval_[\w.-]+\.json)", combined)
    if not saved or not Path(saved.group(1)).exists():
        return [Observation(name="live.evaluate_astra", status="fail",
                            expected="Saved: <run>/eval_*.json artifact",
                            observed="no saved artifact found "
                                     "(exit-0-no-metric class)",
                            seconds=run.seconds)]
    try:
        doc = json.loads(Path(saved.group(1)).read_text())
    except (OSError, ValueError) as e:
        return [Observation(name="live.evaluate_astra", status="fail",
                            expected="parseable eval JSON",
                            observed=f"unreadable artifact: {e}",
                            seconds=run.seconds)]
    plat = doc.get("plat_stats") or {}
    ok = (doc.get("status") == "ok" and doc.get("cycles", 0) > 0
          and int(plat.get("packets", 0)) > 0)
    return [Observation(
        name="live.evaluate_astra", status="pass" if ok else "fail",
        expected="status ok, cycles > 0, [plat] packets > 0",
        observed=(f"cycles={doc.get('cycles')}, "
                  f"packets={plat.get('packets')}, "
                  f"hops_avg={plat.get('hops_avg')}"),
        seconds=run.seconds)]


# ── the interface ─────────────────────────────────────────────────────────

CHECKS: dict[str, list] = {
    "quick": [_check_bins, _check_config_seams, _check_calibration_docs],
    "deep": [_check_bins, _check_config_seams, _check_calibration_docs,
             _check_live_booksim, _check_live_certify,
             _check_live_astra, _check_live_topology_diff],
}


def run_checks(level: str = "quick",
               checks: list | None = None) -> DoctorReport:
    """Run the battery for `level` and assemble the report.

    `checks` lets tests inject tiny fake check functions — the seam for
    testing report assembly without running any real command. LLM review
    is *not* run here: callers opt in via review_with_llm() so the pure
    seam stays offline and deterministic.
    """
    if level not in CHECKS:
        raise ValueError(f"unknown doctor level {level!r}; "
                         f"have {sorted(CHECKS)}")
    t0 = time.time()
    log: list[str] = []
    all_obs: list[Observation] = []
    for fn in (checks if checks is not None else CHECKS[level]):
        try:
            all_obs.extend(fn(log))
        except Exception as e:  # a crashed check is itself a finding
            all_obs.append(Observation(
                name=f"crash.{getattr(fn, '__name__', '?')}", status="fail",
                expected="check completes", observed=repr(e)))
    return DoctorReport(level=level,
                        started=time.strftime("%Y-%m-%d %H:%M:%S"),
                        seconds=time.time() - t0,
                        checks=all_obs, log_tail=log[-200:])


# ── LLM second-opinion adapter (advisory, never gates) ────────────────────

LLM_REVIEW_SYSTEM = (
    "You are auditing the output of a network-topology simulation harness "
    "(VeritX DSE). You receive a doctor report (JSON) and the tail of the "
    "harness log. Look for: impossible numbers (negative or zero latency, "
    "cycles too small for the packet count), suspicious patterns (runs "
    "timing out at identical wall-clock, identical scores for different "
    "workloads, means averaged over different populations), contract "
    "violations (traceback fragments, exit-code masking), and anything "
    "else 'funny'. Cite the check name or log line. If everything is "
    "consistent, say so plainly. Max 250 words."
)


def llm_configured() -> bool:
    return bool(_llm_creds()[0] and _llm_creds()[1])


def build_paste_prompt(report: DoctorReport) -> str:
    """The manual-review flow: when no LLM endpoint is configured, --llm
    emits THIS text instead — paste it into any chat LLM by hand (the
    economical path: no API key, no spend). Same system prompt and same
    payload the automated adapter would send, so answers are comparable."""
    user_payload = json.dumps({
        "doctor_report": report.to_dict(),
        "log_tail": report.log_tail[-150:],
    })
    return (f"{LLM_REVIEW_SYSTEM}\n\n--- BEGIN PAYLOAD ---\n"
            f"{user_payload}\n--- END PAYLOAD ---")


def _llm_creds() -> tuple[str | None, str | None, str]:
    """(base_url, api_key, model) with a two-tier env chain.

    VERITX_LLM_* is the primary contract; OPENAI_* is the ubiquitous
    fallback (many users already export it). Model default follows the
    same chain: VERITX_LLM_MODEL > OPENAI_MODEL > gpt-4o-mini.
    """
    base = (os.environ.get("VERITX_LLM_BASE_URL")
            or os.environ.get("OPENAI_BASE_URL")
            or ("https://api.openai.com/v1"
                if os.environ.get("OPENAI_API_KEY") else None))
    key = os.environ.get("VERITX_LLM_API_KEY") or os.environ.get("OPENAI_API_KEY")
    model = (os.environ.get("VERITX_LLM_MODEL")
             or os.environ.get("OPENAI_MODEL") or "gpt-4o-mini")
    return base, key, model


def review_with_llm(report: DoctorReport) -> dict | None:
    """Second opinion via an OpenAI-compatible chat endpoint.

    Env chain (first hit wins):
      VERITX_LLM_BASE_URL / VERITX_LLM_API_KEY / VERITX_LLM_MODEL
      OPENAI_BASE_URL / OPENAI_API_KEY / OPENAI_MODEL (ubiquitous fallback)

    Returns {"model","review","latency_s"} or {"model","error",...} on
    failure, or None when unconfigured. Advisory only: no exception ever
    escapes, and a failed review never changes the verdict.
    """
    base, key, model = _llm_creds()
    if not (base and key):
        return None
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": LLM_REVIEW_SYSTEM},
            {"role": "user", "content": json.dumps({
                "doctor_report": report.to_dict(),
                "log_tail": report.log_tail[-150:],
            })},
        ],
        "temperature": 0.2,
    }
    req = urllib.request.Request(
        f"{base}/chat/completions",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
        method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
        return {"model": model,
                "review": body["choices"][0]["message"]["content"],
                "latency_s": round(time.time() - t0, 1)}
    except (urllib.error.URLError, KeyError, OSError, TimeoutError,
            ValueError) as e:
        return {"model": model, "review": None, "error": repr(e),
                "latency_s": round(time.time() - t0, 1)}


# ── rendering (presentation only; kept out of the seam) ──────────────────


def render(report: DoctorReport) -> str:
    lines = [f"veritx doctor — level {report.level}", ""]
    for c in report.checks:
        mark = STATUS_MARK.get(c.status, "?")
        line = f"  {mark} {c.name:<28} {c.status.upper():<5}"
        if c.observed:
            line += f"  {c.observed}"
        if c.seconds >= 0.05:
            line += f"  ({c.seconds:.1f}s)"
        lines.append(line)
    lines.append("")
    lines.append(report.summary())
    if report.llm:
        lines.append("")
        lines.append("=== LLM second opinion ===")
        if report.llm.get("review"):
            lines.extend(f"  {ln}"
                         for ln in report.llm["review"].splitlines())
        elif report.llm.get("paste_prompt"):
            lines.append("  no endpoint configured — paste the prompt below "
                         "into any chat LLM (also in --json-out)")
        else:
            lines.append(f"  unavailable: {report.llm.get('error')}")
    return "\n".join(lines)
