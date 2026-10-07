"""The distinct ``fattree`` intent has a shipped, qualified product path."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.presets import build_typed_preset_request  # noqa: E402


def test_fattree_preset_compiles_and_executes_with_conservation():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import (
        ANYNET_PROFILE, prepare_booksim_input, select_booksim_profile,
    )
    from veritx_dse.gateway.app import resolve_booksim_bin

    request = build_typed_preset_request("fattree16")
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    parents = _parents_from_bundle(compilation.bundle, request)
    profile = select_booksim_profile(parents)
    assert profile.profile_id == ANYNET_PROFILE.profile_id
    prepared = prepare_booksim_input(parents)
    binary = resolve_booksim_bin()
    assert binary is not None, "no built BookSim binary in tree"

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
