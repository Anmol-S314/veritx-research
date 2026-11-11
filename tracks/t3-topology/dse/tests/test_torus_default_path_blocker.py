"""Torus default-path E2E floor (§7).

The default torus derivation now applies the same dateline VC floor the ring
already used: the fork integer-halves the VC range, so a cycle-free torus
request without explicit X<->Y dependencies derives TWO dateline VCs and
compiles with ``DEADLOCK_FREE`` PASS. The explicit ``torus25`` preset remains
product-reachable; its declared dependencies are part of the preset identity,
not silently inferred.

This file pins that floor. A one-VC torus is an unsound default: it cannot
express the dateline partition, so a regression to 1 VC must fail here and
in the certificate. See also ``test_torus_e2e_qualify.py`` for the shipped
preset path.
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


def _default_torus_request():
    from dataclasses import replace
    request = _probe_request("torus")
    return replace(request, dependencies=DependencyGraph(()))


def _deadlock_obligation(compilation):
    return next(
        obligation for obligation in compilation.certificate.obligations
        if obligation.obligation == "DEADLOCK_FREE")


def test_default_torus_derives_two_dateline_vcs():
    compilation = FabricCompiler().compile(_default_torus_request())
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.bundle.vc_assignment.vc_count == 2


def test_default_torus_certificate_is_deadlock_free():
    """The default is no longer an unsound one-VC path."""
    compilation = FabricCompiler().compile(_default_torus_request())
    assert compilation.certificate is not None
    assert compilation.certificate.overall == "PASS"
    obligation = _deadlock_obligation(compilation)
    assert obligation.status == "PASS", obligation.evidence
    assert obligation.evidence["vc_count"] == 2
    assert obligation.evidence["acyclic"] is True


def test_capability_truth_uses_the_shipped_torus_profile():
    truth = derive_family_stages("torus")
    assert all(truth.stages[stage] == "YES" for stage in truth.stages)
    assert truth.profile_id == "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"
