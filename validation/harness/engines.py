"""Independent engine gates.

Where the experiment layers compare VERITX against an authority on a
specific workload, these gates qualify the independent engines
themselves as available and self-consistent, as one machine-readable
verdict:

  * ``ramulator`` — the memory-backend acceptance battery (drain,
    wrapper-vs-direct equivalence, determinism, locality, bank
    parallelism, integrity, byte audit). Runs under the vendored Python
    the extension was built for.
  * ``rtl`` — the T3 2D mesh testbench R0 self-checks (zero-traffic
    sanity, single-packet calibration, burst cadence, LFSR drain).
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_CHECK = re.compile(r"^\s+([A-Za-z0-9_.+-]+)\s+(PASS|FAIL)\s*(.*)$")
_VERDICT = re.compile(r"VERDICT:\s*(PASS|FAIL)\s*\(([^)]*)\)")


@dataclass(frozen=True)
class EngineResult:
    name: str
    passed: bool
    detail: str
    checks: tuple[tuple[str, bool, str], ...] = field(default_factory=tuple)
    #: True when the engine's OUTPUT is scientifically meaningful, not just
    #: that it ran. A liveness pass with validated=False must never feed a
    #: scientific comparison.
    validated: bool = True


def find_python312() -> str | None:
    """Locate a Python 3.12 for the vendored Ramulator extension."""
    override = os.environ.get("VERITX_PYTHON312")
    if override and Path(override).is_file():
        return override
    found = shutil.which("python3.12")
    if found:
        return found
    uv_root = Path.home() / ".local" / "share" / "uv" / "python"
    if uv_root.is_dir():
        for candidate in sorted(uv_root.glob("cpython-3.12*/bin/python3.12")):
            return str(candidate)
    return None


def run_ramulator(repo_root: Path, *, timeout: int = 1200) -> EngineResult:
    script = (Path(repo_root) / "tracks" / "t3-topology" / "dse"
              / "qualification" / "ramulator.py")
    interpreter = find_python312()
    if interpreter is None:
        return EngineResult(
            "ramulator_battery", False,
            "no python3.12 found (the vendored extension is built for "
            "cpython-3.12); set VERITX_PYTHON312 or build for the running "
            "interpreter")
    proc = subprocess.run(
        [interpreter, str(script)], cwd=str(repo_root), capture_output=True,
        text=True, timeout=timeout)
    checks = tuple(
        (m.group(1), m.group(2) == "PASS", m.group(3).strip())
        for m in (_CHECK.match(line) for line in proc.stdout.splitlines())
        if m is not None)
    verdict = _VERDICT.search(proc.stdout)
    if verdict is None:
        return EngineResult(
            "ramulator_battery", False,
            f"battery produced no verdict (rc={proc.returncode}); "
            f"{(proc.stdout or proc.stderr)[-300:]}", checks)
    passed = verdict.group(1) == "PASS" and proc.returncode == 0
    return EngineResult(
        "ramulator_battery", passed,
        f"{verdict.group(2)}; {sum(1 for _, ok, _ in checks if ok)}"
        f"/{len(checks)} checks", checks)


def run_rtl_selfcheck(repo_root: Path, work_root: Path,
                      *, x_dim: int = 4, y_dim: int = 4, vcs: int = 4
                      ) -> EngineResult:
    from .rtl import RtlError, build
    try:
        binary = build(repo_root=Path(repo_root),
                       build_dir=Path(work_root) / "rtl-r0",
                       x_dim=x_dim, y_dim=y_dim, vcs=vcs, t_depth=16,
                       r1_mode=False)
    except (RtlError, OSError) as exc:
        return EngineResult("rtl_selfcheck", False, f"build failed: {exc}")
    run_dir = Path(work_root) / "rtl-r0-run"
    run_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run([str(binary)], cwd=str(run_dir),
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=600)
    out = proc.stdout or ""
    passed = "GATE R0: ALL CHECKS PASSED" in out and proc.returncode == 0
    checks = tuple(
        (m.group(1), True, "")
        for m in (re.match(r"^PASS (\S+)", line)
                  for line in out.splitlines()) if m is not None)
    detail = "GATE R0: ALL CHECKS PASSED" if passed else (
        f"self-check failed (rc={proc.returncode}); {out[-300:]}")
    return EngineResult("rtl_selfcheck", passed, detail, checks)


def run_astra(repo_root: Path, work_root: Path,
              *, timeout: int = 300) -> EngineResult:
    """Run the canonical ASTRA projection on the real AstraSim_BookSim2.

    This is an engine gate, not an independent-parity check: ASTRA's
    BookSim2 frontend shares the BookSim2 network engine, so it cannot
    independently falsify the network. It proves the ASTRA path executes
    the canonical projection and reports per-rank cycles for every rank.
    """
    from veritx_dse.backend import astra
    from .fabric import build as build_fabric
    from .spec import ExperimentSpec

    binary = astra.resolve_runtime_binary()
    if binary is None:
        return EngineResult(
            "astra_runtime", False,
            "no AstraSim_BookSim2 binary; build it with "
            "third_party/astra-sim/build/astra_booksim2/build.sh")
    spec = ExperimentSpec.load(
        Path(__file__).resolve().parents[1] / "experiments"
        / "V02-allreduce-4x4.json")
    built = build_fabric(spec)
    try:
        projection = astra.AstraWorkloadProjection.build(
            logical=built.logical,
            resolved_fabric=built.bundle.resolved_fabric,
            mapping=built.bundle.mapping, attachment=built.bundle.attachment,
            et_granularity="collectives")
        et_dir = Path(work_root) / "astra-et"
        projection.write_chakra(directory=et_dir, stem="canon")
        fixture = (Path(repo_root) / "tracks" / "t3-topology" / "dse"
                   / "tests" / "fixtures" / "astra_tiny")
        evidence = astra.run_astra(
            binary=binary, projection=projection,
            workload_configuration=et_dir / "canon.et",
            system_configuration=fixture / "system.json",
            network_configuration=fixture / "mesh4x4.cfg",
            memory_configuration=fixture / "memory.json",
            logging_folder=Path(work_root) / "astra-logs",
            timeout_s=timeout)
    except Exception as exc:  # noqa: BLE001
        return EngineResult("astra_runtime", False,
                            f"{type(exc).__name__}: {exc}")
    ranks = len(evidence.per_rank_cycles)
    comm = evidence.aggregate_cycles - projection.declared_compute_cycles()
    ok = evidence.status == "EXECUTED" and ranks == 16 and comm > 0
    return EngineResult(
        "astra_runtime", ok,
        f"ASTRA_RUNTIME_EXECUTES={'PASS' if ok else 'FAIL'}; "
        f"ASTRA_NUMERICAL_VALIDITY=NOT_ESTABLISHED (aggregate "
        f"{evidence.aggregate_cycles}c, exposed_comm {comm}c are unexplained "
        "and must not enter a scientific comparison)",
        validated=False)


def run_engines(repo_root: Path, work_root: Path) -> list[EngineResult]:
    return [run_ramulator(repo_root),
            run_rtl_selfcheck(repo_root, work_root),
            run_astra(repo_root, work_root)]
