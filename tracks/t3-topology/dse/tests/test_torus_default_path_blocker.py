"""Torus default-path E2E blocker (§7).

Two torus truths coexist and must never be confused:

- The DEFAULT one-VC torus derivation stops at verification: INVALID with
  exactly {DEADLOCK_FREE}, because one VC cannot express the dateline
  partition.
- The 2-VC + X<->Y blocking-dependency configuration passes end to end and
  is product-reachable through the explicit `torus25` preset. Those declared
  dependencies are part of the preset identity, not silently inferred.

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
from veritx_dse.model.compile_model import DependencyGraph  # noqa: E402


def _one_vc_torus_request():
    from dataclasses import replace
    request = _probe_request("torus")
    return replace(request, dependencies=DependencyGraph(()))


def test_default_torus_stops_at_deadlock_free():
    compilation = FabricCompiler().compile(_one_vc_torus_request())
    assert compilation.status == "INVALID", compilation.status
    error = str(getattr(compilation, "error", ""))
    assert "DEADLOCK_FREE" in error, error


def test_default_torus_failure_names_only_deadlock_free():
    """The break is precise: routing and everything before it hold."""
    compilation = FabricCompiler().compile(_one_vc_torus_request())
    error = str(getattr(compilation, "error", ""))
    assert "DEADLOCK_FREE" in error
    # Routing completed — the failure is the proof, not the path.
    assert "ROUTING" not in error and "TOPOLOGY" not in error, error


def test_capability_truth_uses_the_shipped_torus_profile():
    truth = derive_family_stages("torus")
    assert all(truth.stages[stage] == "YES" for stage in truth.stages)
    assert truth.profile_id == "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"
