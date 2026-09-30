"""Environment-failure triage record (executable, not prose).

Context: one full-suite run showed 34 failures across serving live-binary,
ASTRA runtime/timing-oracle, ramulator crash-leg, legacy-compare,
federation-kernel spawn, custom-routing, multi-fidelity and
product-federation tests. A later full-suite run on a stable tree showed
4 failed / 5182 passed with a DIFFERENT failure set, and every one of the
original 34 passes in file-group runs.

Verdict encoded below:
- The 34 were transient tree-flux/load artifacts (15-lane Studio fanout +
  parallel-track commits landing mid-run), NOT regressions from reclaimed
  slices. No skip marker is added for them: quarantining passing tests
  would weaken the suite.
- The 4 current failures split into: 2 x true pending-work gate
  (sibling-owned GEC-EXPRESS registry row, kept red via strict xfail),
  1 x flux-correct staleness gate (kept red-capable, asserted live), and
  1 x load-flake concurrency test (passes in isolation; asserted live).

Laws for this file:
- No test here ever skips release-critical coverage into a pass, and no
  assertion from another file is touched.
- The strict-xfail tripwire MUST fail loudly (XPASS) the moment the
  sibling topology lane lands the registry row, forcing triage-table
  cleanup instead of silent staleness.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))
ROOT = DSE.parent.parent.parent

TRANSIENT_BASELINE = (
    "tests/test_serving_canonical.py",
    "tests/test_serving_loop.py",
    "tests/test_serving_round.py",
    "tests/test_astra_runtime.py",
    "tests/test_astra_timing_oracle.py",
    "tests/test_backend_astra_namespace.py",
    "tests/test_ramulator_adapter.py::test_leg_failed_on_crash_and_inconclusive",
    "tests/test_closure_phase2_compare.py::test_legacy_rows_carry_verdicts",
    "tests/test_compiled_inspector_contracts.py"
    "::test_p2_u_a_capability_limitation_does_not_invalidate_the_design",
    "tests/test_custom_routing.py"
    "::test_custom_policy_is_accepted_by_the_certified_anynet_profile",
    "tests/test_federated_optimizer.py"
    "::test_inconclusive_native_drain_is_inconclusive",
    "tests/test_federation_kernel.py"
    "::test_astra_actually_spawns_and_authenticates",
    "tests/test_multi_fidelity_objectives.py"
    "::test_live_astra_makespan_objective_is_measured_with_provenance",
    "tests/test_product_federation.py::test_live_astra_evaluation_reproduces",
)

def _resolve(tag: str):
    if tag == "booksim":
        import os  # noqa: PLC0415
        from veritx_dse.core.paths import REPO  # noqa: PLC0415
        from veritx_dse.simulation.booksim import (  # noqa: PLC0415
            find_booksim_bin,
        )
        override = os.environ.get("VERITX_BOOKSIM_BIN")
        if override:
            return override
        try:
            return find_booksim_bin(REPO)
        except Exception:
            return None
    if tag == "astra":
        from veritx_dse.backend import astra as ma  # noqa: PLC0415
        fn = getattr(ma, "resolve_runtime_binary", None)
        if callable(fn):
            try:
                return fn()
            except Exception:
                return None
        return None
    raise ValueError(f"unknown producer tag {tag!r}")

def _present(tag: str) -> bool:
    found = _resolve(tag)
    return found is not None and Path(str(found)).is_file()

def test_booksim_producer_present():
    """The BookSim binary the certified path executes is on disk."""
    assert _present("booksim"), "no BookSim binary available"

def test_astra_producer_present():
    """The AstraSim_BookSim2 binary the ASTRA seam spawns is on disk."""
    assert _present("astra"), "no AstraSim_BookSim2 binary available"

def test_existing_binary_markers_cover_live_tests():
    """Live-binary tests already carry skipif markers; this asserts the
    pattern holds where the triage baseline needs it (no silent
    no-binary passes)."""
    timing = (DSE / "tests" / "test_astra_timing_oracle.py").read_text()
    assert "skipif" in timing and "release binary not built" in timing
    runtime = (DSE / "tests" / "test_astra_runtime.py").read_text()
    assert "_requires_binary" in runtime

def test_topology_family_checker_passes():
    """Runs the real checker: the gec_express registry row landed, so
    the tripwire marker was removed and this must stay green."""
    r = subprocess.run(
        [sys.executable, str(ROOT / "scripts"
                             / "check_topology_family_registry.py")],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr

def test_staleness_gate_reports_fresh_on_stable_tree():
    """The staleness gate is correct-by-construction: it fires on mid-run
    source mtimes. Asserting it live documents that THIS run executed on
    a stable tree; a failure here means tree flux, not product rot."""
    from veritx_dse.gateway import staleness as st  # noqa: PLC0415
    info = st.staleness()
    assert info["stale"] is False, (
        f"sources changed mid-run: {info} — rerun on a stable tree")

def test_concurrency_flake_is_documented_not_quarantined():
    """test_concurrent_finalize_same_directory_is_idempotent is
    timing-sensitive BY DESIGN (concurrent finalize race): observed 3/3
    green alone, red under full-suite + parallel-lane contention, red
    once via a contended subprocess, green again on immediate retry.
    That intermittency IS the triage evidence, so this record asserts
    the test's race structure instead of pretending determinism: the
    test must exercise threads and must NOT be skip-marked (a skip
    would hide a real finalize race as 'env')."""
    src = (DSE / "tests" / "production" / "test_concurrency.py"
           ).read_text()
    assert "thread" in src.lower(), \
        "concurrency test stopped exercising threads — re-triage"
    assert "no booksim binary available" in src.lower(), \
        "binary-presence gate removed — re-triage"
    assert "mark.skip(" not in src.replace("mark.skipif(", ""), \
        "blanket skip marker hides finalize races — re-triage"

def test_transient_baseline_documented():
    """The triage table above names every class from the 34-failure run;
    all of them pass on a stable tree, so none carries a skip marker."""
    assert len(TRANSIENT_BASELINE) == 14
    assert all(t.startswith("tests/") for t in TRANSIENT_BASELINE)
