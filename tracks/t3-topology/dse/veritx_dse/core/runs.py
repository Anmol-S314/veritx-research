"""veritx_dse.core.runs — immutable run skeleton (redesign PR 2).

Implements ADR 0001 (runs immutable once started), 0002 (run_id vs
experiment_hash), 0003 (filesystem authoritative, atomic writes), and 0006
(automatic provenance) for the standalone BookSim slice (PR 3) and beyond.

Deliberately NOT a Runner/Manager class hierarchy (redesign §0): a handful
of functions over a run directory.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import platform
import re
import secrets
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .paths import VERITX_RUNS_DIR
from .recovery import atomic_write

# State machine (redesign §11). States are added only when behavior needs
# them; RUNNING -> SUCCEEDED requires finalized results, never just exit 0.
STATES = ("CREATED", "VALIDATED", "PLANNED", "RUNNING",
          "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED")
_TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED")
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "CREATED": ("VALIDATED", "CANCELLED"),
    "VALIDATED": ("PLANNED", "CANCELLED"),
    "PLANNED": ("RUNNING", "CANCELLED"),
    "RUNNING": ("SUCCEEDED", "FAILED", "INTERRUPTED"),
    "INTERRUPTED": ("RUNNING", "CANCELLED"),  # explicit resume/retry only
}


class RunError(Exception):
    """Illegal run operation (bad transition, immutable-file write)."""


def _uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7 from stdlib only.

    uuid.uuid7() exists only on Python >= 3.14, but this package declares
    >=3.12 (verified-PRD Integrity PR A) — so the sortable-time identity
    (ADR 0002) is implemented here rather than imported. Layout:
    unix_ts_ms[48] | ver 0111 | rand_a[12] | var 10 | rand_b[62].
    74 fresh random bits per millisecond make collision odds negligible
    at run-creation scale; monotonic sorting falls out of the timestamp.
    """
    ms = time.time_ns() // 1_000_000
    rand = int.from_bytes(secrets.token_bytes(10), "big")
    rand_a = (rand >> 62) & 0x0FFF
    rand_b = rand & ((1 << 62) - 1)
    value = (ms << 80) | (0x7 << 76) | (rand_a << 64) | (0b10 << 62) | rand_b
    return uuid.UUID(int=value)


def new_run_id() -> str:
    """Sortable unique execution identity (ADR 0002): lowercase uuid7."""
    return str(_uuid7())


# Environment/lock identity (verified-PRD Integrity PR A / §11.3): a run's
# provenance must identify the installed dependency set, not assume the
# developer's machine. The lockfile is generated from the declared metadata
# (see dse/requirements.lock header) and fingerprinted here.
_LOCK_PATH = Path(__file__).resolve().parents[2] / "requirements.lock"


def _dependency_lock_identity() -> dict[str, Any]:
    try:
        return {"requirements.lock.sha256": _file_sha256(_LOCK_PATH)}
    except Exception:
        return {"requirements.lock.sha256": None}  # say so, never invent


_RUNTIME_FLOOR = (3, 12)  # must match pyproject requires-python (PR A gate)


# ── Provenance (ADR 0006: automatic, allowlisted env) ───────────────────────

def _git_identity(repo: Path) -> dict[str, Any]:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True,
            text=True, timeout=10, check=True,
        ).stdout.strip()
        return {"commit": commit, "dirty": bool(dirty)}
    except Exception:
        return {"commit": None, "dirty": None}  # not a git checkout; say so


def _file_sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


ENV_ALLOWLIST = ("PATH", "PYTHONPATH", "VIRTUAL_ENV", "CONDA_DEFAULT_ENV",
                 "VERITX_BOOKSIM_BIN", "VERITX_ASTRA_BIN")


def capture_provenance(repo: Path, argv: list[str]) -> dict[str, Any]:
    """Provenance every run gets, whether or not the author remembered.

    Never dumps the environment — allowlisted keys only (credential safety).
    """
    return {
        "git": _git_identity(repo),
        "python": sys.version.split()[0],
        "python_dependency_lock": _dependency_lock_identity(),
        "platform": platform.platform(),
        "argv": argv,
        "env": {k: os.environ[k] for k in ENV_ALLOWLIST if k in os.environ},
        "captured_at": _utcnow(),
    }


def assert_runtime_compatible() -> None:
    """Fail loudly on an unsupported interpreter (PR A gate).

    pyproject declares requires-python >=3.12; enforced at run creation so
    a mismatched environment cannot quietly produce runs with unknown
    semantics. Verified-PRD §0.4: silent incompatibility is how the
    uuid7 defect survived.
    """
    if sys.version_info[:2] < _RUNTIME_FLOOR:
        raise RunError(
            f"veritx requires Python >= {_RUNTIME_FLOOR[0]}.{_RUNTIME_FLOOR[1]}"
            f" (running {sys.version.split()[0]})")


def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")


# ── Typed metrics (verified-PRD Integrity PR E, §4/§6.9) ────────────────────

FIDELITY_CATEGORIES = (
    "ANALYTICAL_ESTIMATE",           # derived from a model, not simulated
    "NETWORK_SIMULATION",            # BookSim-style cycle simulation
    "SYSTEM_SERVING_SIMULATION",     # LLMServingSim over a real network backend
    "TRACE_REPLAY",                  # PR6 §17.5: trace durations replayed, no
                                     # network simulated — never comparable
                                     # against SYSTEM_SERVING_SIMULATION
    "RTL_SIMULATION",                # Verilator-class RTL execution
    "FORMAL_PROOF",                  # model-checker result
    "SYNTHESIS_STA_PHYSICAL",        # implementation-tool derived
)


def metric(name: str, value, unit: str, *, producer: str,
           fidelity: str, scope: str = "per_packet",
           derivation: str | None = None) -> dict[str, Any]:
    """A naked scientific number is not a result (PR E / verified-PRD §6.9).

    Every persisted metric carries its unit, the tool/model that produced
    it, and its evidence fidelity — so cycles are never compared against
    clocks and estimates are never mistaken for simulation. ``derivation``
    records any conversion applied (e.g. "bytes/64B per flit").
    """
    if fidelity not in FIDELITY_CATEGORIES:
        raise ValueError(
            f"unknown fidelity {fidelity!r} — must be one of "
            f"{FIDELITY_CATEGORIES}. Fidelity is data, not prose.")
    return {
        "name": name,
        "value": value,
        "unit": unit,
        "producer": producer,
        "fidelity": fidelity,
        "aggregation_scope": scope,
        "derivation": derivation,
    }


def binary_identity(path) -> dict[str, Any]:
    """Executable identity for provenance (PR E / §10.4): SHA256 of the
    binary actually executed, or a truthful None if unavailable.

    "A run must identify the code that produced it" — the executable is
    part of the experiment no less than the spec.
    """
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return {"sha256": h.hexdigest(), "path": str(path)}
    except OSError:
        return {"sha256": None, "path": str(path)}


# ── Run directory lifecycle ─────────────────────────────────────────────────

class Run:
    """One realized execution's directory + state (ADR 0001).

    Mutable files: state.json, stdout.log, stderr.log. Everything else
    (spec.resolved.json, manifest.json, provenance.json) is written once
    during initialization and frozen.
    """

    def __init__(self, root: Path):
        self.root = root
        self._state_path = root / "state.json"

    # -- construction ------------------------------------------------------

    @classmethod
    def create(cls, repo: Path, resolved_spec: dict[str, Any],
               argv: list[str] | None = None) -> "Run":
        """Allocate + initialize a run directory. Fails loudly if the run
        directory already exists (collision = bug, never overwrite)."""
        assert_runtime_compatible()
        run_id = new_run_id()
        root = VERITX_RUNS_DIR / run_id
        root.mkdir(parents=True)
        (root / "artifacts").mkdir()
        r = cls(root)
        r.run_id = run_id

        from .spec import canonical_json, experiment_hash
        ehash = experiment_hash(resolved_spec)
        prov = capture_provenance(repo, argv or [])

        # Frozen files — written once, never updated (ADR 0001).
        (root / "spec.resolved.json").write_text(
            json.dumps(resolved_spec, indent=2, sort_keys=True) + "\n")
        (root / "provenance.json").write_text(
            json.dumps(prov, indent=2, sort_keys=True) + "\n")
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "experiment_hash": ehash,
            "status": "CREATED",
            "created_at": _utcnow(),
            "spec": "spec.resolved.json",
            "provenance": "provenance.json",
            "results": [],
        }
        (root / "manifest.json").write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        r._write_state("CREATED", note="initialized")
        return r

    @classmethod
    def load(cls, run_id: str) -> "Run":
        root = VERITX_RUNS_DIR / run_id
        if not (root / "manifest.json").is_file():
            raise RunError(f"no such run: {run_id} (under {VERITX_RUNS_DIR})")
        r = cls(root)
        r.run_id = run_id
        return r

    # -- state machine -----------------------------------------------------

    @property
    def state(self) -> str:
        return json.loads(self._state_path.read_text())["state"]

    def transition(self, to: str, note: str = "") -> None:
        if to not in STATES:
            raise RunError(f"unknown state: {to}")
        cur = self.state
        if to not in _TRANSITIONS.get(cur, ()):
            raise RunError(f"illegal transition {cur} -> {to}")
        self._write_state(to, note=note, previous=cur)

    def _write_state(self, state: str, **extra: Any) -> None:
        # Atomic always: a Ctrl-C mid-write must never half-write the only
        # mutable authority in the run dir (ADR 0003).
        payload = {"schema_version": 1, "state": state,
                   "updated_at": _utcnow(), **extra}
        with atomic_write(self._state_path) as tmp:
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    # -- results -----------------------------------------------------------

    def add_result(self, task_id: str, result: dict[str, Any]) -> None:
        """Record one task result into manifest.results, atomically.
        Appending to a terminal-state run is refused (immutability)."""
        if self.state in _TERMINAL:
            raise RunError(
                f"run {self.run_id} is {self.state}; results are immutable")
        manifest = json.loads((self.root / "manifest.json").read_text())
        manifest["results"].append({"task_id": task_id,
                                    "recorded_at": _utcnow(), **result})
        with atomic_write(self.root / "manifest.json") as tmp:
            tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    def finalize(self, status: str, note: str = "") -> None:
        """Close the run. SUCCEEDED only after results are recorded —
        exit-code-0 alone never implies success (redesign §11)."""
        if status not in _TERMINAL:
            raise RunError(f"finalize requires a terminal state, got {status}")
        if status == "SUCCEEDED":
            manifest = json.loads((self.root / "manifest.json").read_text())
            if not manifest["results"]:
                raise RunError("cannot SUCCEED with zero recorded results")
        self.transition(status, note=note)
