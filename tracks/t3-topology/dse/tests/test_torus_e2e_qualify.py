"""Torus end-to-end qualification: COMPILED -> TORUS profile -> execute -> qualify.

Acceptance proof for the torus bridge. The shipped odd-side 5x5, 2-VC
torus design (X<->Y blocking
dependencies drive the second VC for the dateline halves) compiles with a
PASS certificate via the dateline-restricted CDG expansion, prepares under
CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1, executes on the real fork binary, and
qualifies over the real parents. The 1-VC torus stays INVALID (named
X-ring cycle) — that pin lives in the staged tests, not here.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.presets import (  # noqa: E402
    build_typed_preset_request,
)


def _torus_2vc_request():
    return build_typed_preset_request("torus25")

def test_torus_2vc_compiles_with_pass_certificate():
    compilation = FabricCompiler().compile(_torus_2vc_request())
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    assert compilation.bundle is not None

def test_torus_prepares_under_its_profile():
    from veritx_dse.application.capability_truth import (  # noqa: E402
        _parents_from_bundle,
    )
    from veritx_dse.backend.booksim_projection import (  # noqa: E402
        prepare_booksim_input, select_booksim_profile,
    )

    req = _torus_2vc_request()
    compilation = FabricCompiler().compile(req)
    parents = _parents_from_bundle(compilation.bundle, req)
    profile = select_booksim_profile(parents)
    assert profile.profile_id == "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"
    prepared = prepare_booksim_input(parents)
    assert prepared is not None

def test_torus_live_executes_with_conservation():
    """LIVE binary: odd-side 2-VC torus executes with flit conservation."""
    from veritx_dse.application.capability_truth import (  # noqa: E402
        _parents_from_bundle,
    )
    from veritx_dse.backend.booksim_execution import (  # noqa: E402
        execute_prepared_booksim,
    )
    from veritx_dse.backend.booksim_projection import (  # noqa: E402
        prepare_booksim_input, select_booksim_profile,
    )
    from veritx_dse.gateway.app import (  # noqa: E402
        resolve_booksim_bin,
    )

    req = _torus_2vc_request()
    compilation = FabricCompiler().compile(req)
    parents = _parents_from_bundle(compilation.bundle, req)
    assert select_booksim_profile(parents).profile_id == \
        "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"
    prepared = prepare_booksim_input(parents)
    binary = resolve_booksim_bin()
    assert binary is not None, "no built BookSim binary in tree"
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=290)
    evidence = record.evidence
    doc = evidence.to_dict() if hasattr(evidence, "to_dict") else {}
    stats = doc.get("stats", doc)
    assert stats.get("completion_cycles", 0) > 0, stats
    injected = stats.get("flits_injected")
    accepted = stats.get("flits_accepted")
    assert injected is not None and injected == accepted, stats

def test_torus_qualifies_over_real_parents():
    from veritx_dse.application.booksim_qualification_registry import (  # noqa: E402
        evaluate_qualification,
    )
    from veritx_dse.application.capability_truth import (  # noqa: E402
        _parents_from_bundle,
    )
    from veritx_dse.backend.booksim_projection import (  # noqa: E402
        select_booksim_profile,
    )

    req = _torus_2vc_request()
    compilation = FabricCompiler().compile(req)
    parents = _parents_from_bundle(compilation.bundle, req)
    profile = select_booksim_profile(parents)
    qualified, authority = evaluate_qualification(profile, parents)
    assert qualified, authority
