#!/usr/bin/env python3
"""VERITX production gate (P5 step 13): one command, fail-closed.

Stages (no continue-on-error for scientific gates — the first failure
aborts with a non-zero status):

  1. product registry gates (intent/capability/exposure/preset)
  2. focused federation contract tests
  3. product workflow + gateway tests
  4. full DSE suite
  5. Studio npm ci + typecheck/build (+ Studio contract tests)
  6. live backend gate (only what is built runs; a missing REQUIRED
     release backend is FAILURE, never a skip)
  7. live browser E2E (requires a runnable harness + pinned producer)
  8. release-manifest.json validation

Usage: make production-gate
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSE = REPO / "tracks" / "t3-topology" / "dse"
STUDIO = REPO / "apps" / "studio"

FAILURES: list[str] = []

def _run(stage: str, cmd: list[str], **kwargs) -> None:
    print(f"\n=== production-gate: {stage} ===", flush=True)
    print(f"$ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, **kwargs)
    if proc.returncode != 0:
        print(f"PRODUCTION-GATE FAILED at stage: {stage} "
              f"(exit {proc.returncode})", flush=True)
        sys.exit(proc.returncode)

def _dse_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DSE)
    if extra:
        env.update(extra)
    return env

def _booksim_bin() -> Path | None:
    override = os.environ.get("VERITX_BOOKSIM_BIN")
    if override and Path(override).is_file():
        return Path(override)
    candidate = REPO / "third_party" / "booksim2" / "src" / "booksim"
    return candidate if candidate.is_file() else None

def _astra_present() -> bool:
    sys.path.insert(0, str(DSE))
    try:
        from veritx_dse.backend.astra import resolve_runtime_binary
        return resolve_runtime_binary() is not None
    except Exception:  # noqa: BLE001
        return False
    finally:
        sys.path.remove(str(DSE))

def _ramulator_ready() -> bool:
    sys.path.insert(0, str(DSE))
    try:
        from veritx_dse.simulation.ramulator import discover
        return bool(discover().ready)
    except Exception:  # noqa: BLE001
        return False
    finally:
        sys.path.remove(str(DSE))

def main() -> int:
    _run("product-registry-gates",
         ["make", "-C", "tracks/t3-topology", "product-gates"], cwd=str(REPO))

    _run("federation-contract-tests",
         [sys.executable, "-m", "pytest",
          "tests/test_evaluation_plan.py",
          "tests/test_gateway_federation.py",
          "tests/test_backend_registry.py",
          "tests/test_federation_kernel_acceptance.py",
          "-q", "-p", "no:cacheprovider"], cwd=str(DSE))

    _run("product-workflow",
         [sys.executable, "-m", "pytest",
          "tests/test_product_workflow.py",
          "tests/test_gateway.py",
          "-q", "-p", "no:cacheprovider"], cwd=str(DSE))

    _run("full-dse",
         [sys.executable, "-m", "pytest", "tests",
          "-q", "-p", "no:cacheprovider"], cwd=str(DSE))

    _run("studio-install", ["npm", "ci"], cwd=str(STUDIO))
    _run("studio-build", ["npm", "run", "build"], cwd=str(STUDIO))
    _run("studio-contract-tests",
         [sys.executable, "-m", "pytest",
          "tests/test_studio_contract_v2.py",
          "-q", "-p", "no:cacheprovider"],
         cwd=str(REPO / "apps" / "studio"), env=_dse_env())

    booksim = _booksim_bin()
    astra = _astra_present()
    ramulator = _ramulator_ready()
    print(f"\nlive backend facts: booksim={booksim} astra={astra} "
          f"ramulator={ramulator}", flush=True)
    if booksim is None or not astra:
        missing = [name for name, ok in
                   (("BookSim", booksim is not None), ("ASTRA", astra))
                   if not ok]
        print(f"PRODUCTION-GATE FAILED at stage: live-backend-gate — "
              f"missing required release backend(s): {', '.join(missing)}",
              flush=True)
        return 1
    live_env = {"VERITX_LIVE_FEDERATION": "1",
                "VERITX_BOOKSIM_BIN": str(booksim)}
    if ramulator:
        live_env["VERITX_LIVE_RAMULATOR"] = "1"
    _run("live-federation-acceptance",
         [sys.executable, "-m", "pytest",
          "tests/test_federation_kernel_acceptance.py",
          "-q", "-p", "no:cacheprovider"], cwd=str(DSE),
         env=_dse_env(live_env))
    if ramulator:
        _run("live-ramulator",
             [sys.executable, "-m", "pytest",
              "tests/test_ramulator_adapter.py",
              "-q", "-p", "no:cacheprovider"], cwd=str(DSE),
             env=_dse_env(live_env))
    else:
        print("PRODUCTION-GATE FAILED at stage: live-ramulator — "
              "Ramulator extension absent on this tree; DRAM_TIMING has "
              "no live gate here", flush=True)
        return 1

    browser_env = {"VERITX_E2E": "1", "VERITX_E2E_REQUIRE_BACKEND": "1",
                   "VERITX_BOOKSIM_BIN": str(booksim)}
    _run("browser-e2e",
         [sys.executable, "-m", "pytest",
          "tests/test_live_browser_e2e.py",
          "-q", "-p", "no:cacheprovider"], cwd=str(STUDIO),
         env=_dse_env(browser_env))

    _run("release-manifest",
         ["make", "release-manifest-json"], cwd=str(REPO))
    _run("release-manifest-validate",
         [sys.executable, "scripts/validate_release_manifest.py"],
         cwd=str(REPO))

    print("\nPRODUCTION-GATE PASSED", flush=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
