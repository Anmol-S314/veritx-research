"""Torus default-path E2E blocker (§7).

Two torus truths coexist and must never be confused:

- The DEFAULT torus derivation (plain intent, no workload structure
  establishing a second VC) stops at verification: INVALID with exactly
  {DEADLOCK_FREE}, because the static (channel, VC) CDG cannot express
  the dateline partition. Capability truth derives VERIFIABLE=NO.
- The 2-VC + X<->Y blocking-dependency configuration passes end to end
  (proven by test_torus_e2e_qualify.py) but is NOT product-reachable:
  no preset wires it, and wiring it would mean inventing workload
  dependencies the user never declared.

This file pins the first truth. If the default path ever flips to
COMPILED, that is either the proof-method bridge landing (celebrate,
then re-derive truth) or an unsound default (the dateline cycle the
1-VC pin in the staged tests names) — either way this test forces the
conversation. See also test_torus_e2e_qualify.py for the passing path.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.application.capability_truth import (  # noqa: E402
    _probe_request, derive_family_stages,
)
from veritx_dse.application.fabric_compiler import (  # noqa: E402
    FabricCompiler,
)


def test_default_torus_stops_at_deadlock_free():
    compilation = FabricCompiler().compile(_probe_request("torus"))
    assert compilation.status == "INVALID", compilation.status
    error = str(getattr(compilation, "error", ""))
    assert "DEADLOCK_FREE" in error, error


def test_default_torus_failure_names_only_deadlock_free():
    """The break is precise: routing and everything before it hold."""
    compilation = FabricCompiler().compile(_probe_request("torus"))
    error = str(getattr(compilation, "error", ""))
    assert "DEADLOCK_FREE" in error
    # Routing completed — the failure is the proof, not the path.
    assert "ROUTING" not in error and "TOPOLOGY" not in error, error


def test_capability_truth_derives_torus_verifiable_no():
    truth = derive_family_stages("torus")
    assert truth.stages["ROUTABLE"] == "YES"
    assert truth.stages["VERIFIABLE"] == "NO"
    assert truth.stopped_at_stage == "VERIFICATION"
