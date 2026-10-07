"""GEC nearest-neighbor mode lowers through the qualified mesh path."""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.presets import build_typed_preset_request  # noqa: E402


def test_gec_mesh_compiles_as_canonical_mesh_and_executes():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import (
        MESH_DOR_PROFILE, prepare_booksim_input, select_booksim_profile,
    )
    from veritx_dse.gateway.app import resolve_booksim_bin
    from veritx_dse.model.topology_artifact import MaterializedFamily

    request = build_typed_preset_request("gec_mesh64")
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.certificate.overall == "PASS"
    assert compilation.bundle.topology.family == MaterializedFamily.MESH
    assert compilation.bundle.topology.router_count == 64
    assert compilation.bundle.topology.channel_count == 224

    parents = _parents_from_bundle(compilation.bundle, request)
    profile = select_booksim_profile(parents)
    assert profile.profile_id == MESH_DOR_PROFILE.profile_id
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
