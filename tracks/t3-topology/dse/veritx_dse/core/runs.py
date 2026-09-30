"""veritx_dse.core.runs — immutable run skeleton (redesign PR 2).

Rationale: docs/decisions/modules/core.md
"""
from __future__ import annotations

import datetime as _dt
import fcntl
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
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .paths import VERITX_RUNS_DIR
from .recovery import atomic_write

@contextmanager
def _exclusive_lock(path: Path) -> Iterator[None]:
    """Interprocess exclusive lock for a run's read-modify-write authority.

    ``flock`` on a dedicated lock file (POSIX, as the product targets
    Linux containers). Two concurrent ``add_result`` writers are
    serialized, so neither can observe a stale manifest and drop the
    other's result. The lock file is created but never contains data.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

STATES = ("CREATED", "VALIDATED", "PLANNED", "RUNNING",
          "SUCCEEDED", "FAILED", "CANCELLED", "INTERRUPTED")
_TERMINAL = ("SUCCEEDED", "FAILED", "CANCELLED")
_TRANSITIONS: dict[str, tuple[str, ...]] = {
    "CREATED": ("VALIDATED", "CANCELLED"),
    "VALIDATED": ("PLANNED", "CANCELLED"),
    "PLANNED": ("RUNNING", "CANCELLED"),
    "RUNNING": ("SUCCEEDED", "FAILED", "INTERRUPTED"),
    "INTERRUPTED": ("RUNNING", "CANCELLED"),
}

class RunError(Exception):
    """Illegal run operation (bad transition, immutable-file write)."""

def _uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7 from stdlib only.

Rationale: docs/decisions/modules/core.md
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

_LOCK_PATH = Path(__file__).resolve().parents[2] / "requirements.lock"

def _dependency_lock_identity() -> dict[str, Any]:
    try:
        return {"requirements.lock.sha256": _file_sha256(_LOCK_PATH)}
    except Exception:
        return {"requirements.lock.sha256": None}

_RUNTIME_FLOOR = (3, 10)

def _declared_floor() -> tuple[int, int]:
    """The floor declared by pyproject, so the two cannot silently drift."""
    import re
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return _RUNTIME_FLOOR
    match = re.search(r'requires-python\s*=\s*">=\s*(\d+)\.(\d+)"', text)
    if match is None:
        return _RUNTIME_FLOOR
    return (int(match.group(1)), int(match.group(2)))

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
        return {"commit": None, "dirty": None}

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

    The enforced floor is ``_RUNTIME_FLOOR``; ``test_run_core`` pins it to
    the pyproject ``requires-python`` floor so the declared and enforced
    contracts cannot drift. Verified-PRD §0.4: silent incompatibility is
    how the uuid7 defect survived.
    """
    if sys.version_info[:2] < _RUNTIME_FLOOR:
        raise RunError(
            f"veritx requires Python >= {_RUNTIME_FLOOR[0]}.{_RUNTIME_FLOOR[1]}"
            f" (running {sys.version.split()[0]})")

def _utcnow() -> str:
    return _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")

FIDELITY_CATEGORIES = (
    "ANALYTICAL_ESTIMATE",
    "NETWORK_SIMULATION",
    "SYSTEM_SERVING_SIMULATION",
    "TRACE_REPLAY",
    "RTL_SIMULATION",
    "FORMAL_PROOF",
    "SYNTHESIS_STA_PHYSICAL",
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

def _write_json_atomic(path: Path, obj: Any) -> None:
    """Publish a JSON file atomically (temp file + rename, ADR 0003)."""
    with atomic_write(path) as tmp:
        tmp.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")

class Run:
    """One realized execution's directory + state (ADR 0001).

Rationale: docs/decisions/modules/core.md
    """

    def __init__(self, root: Path):
        self.root = root
        self._state_path = root / "state.json"

    @classmethod
    def create(cls, repo: Path, resolved_spec: dict[str, Any],
               argv: list[str] | None = None,
               study_hash: str | None = None) -> "Run":
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

        _write_json_atomic(root / "spec.resolved.json", resolved_spec)
        _write_json_atomic(root / "provenance.json", prov)
        manifest = {
            "schema_version": 1,
            "run_id": run_id,
            "experiment_hash": ehash,
            "study": study_hash,
            "status": "CREATED",
            "created_at": _utcnow(),
            "spec": "spec.resolved.json",
            "provenance": "provenance.json",
            "results": [],
        }
        _write_json_atomic(root / "manifest.json", manifest)
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
        payload = {"schema_version": 1, "state": state,
                   "updated_at": _utcnow(), **extra}
        with atomic_write(self._state_path) as tmp:
            tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")

    def add_result(self, task_id: str, result: dict[str, Any]) -> None:
        """Record one task result into manifest.results, atomically.

        The manifest read-modify-write runs under an interprocess lock, so
        two concurrent writers cannot both read the same list and drop one
        result. Appending to a terminal-state run is refused (immutability).
        """
        if self.state in _TERMINAL:
            raise RunError(
                f"run {self.run_id} is {self.state}; results are immutable")
        with _exclusive_lock(self.root / "manifest.lock"):
            manifest = json.loads((self.root / "manifest.json").read_text())
            manifest["results"].append({"task_id": task_id,
                                        "recorded_at": _utcnow(), **result})
            _write_json_atomic(self.root / "manifest.json", manifest)

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

    def record_plan(self, plan: dict[str, Any]) -> None:
        """Persist the executable plan and advance to RUNNING via PLANNED.

        One implementation of the plan-file contract (layout, key order,
        transition order) so slices cannot drift apart."""
        with atomic_write(self.root / "plan.json") as tmp:
            tmp.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n")
        self.transition("PLANNED", note=f"{len(plan['tasks'])} task(s)")
        self.transition("RUNNING")

    def cancel(self, reason: str) -> None:
        """Record the rejection INSIDE the run dir, then close it out —
        a refused experiment leaves evidence, not a silent no-op."""
        self.add_result("validate", {"error": reason})
        self.transition("CANCELLED", note=reason)
