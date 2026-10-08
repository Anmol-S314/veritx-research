"""SROTA QoS islands: PLACEMENT carried, routing rule proved (P5, islands).

The fork wraps every router in an island column in a rate regulator. The
canonical model does NOT simulate that regulator's timing, so it carries
only the PLACEMENT (``TopologyArtifact.island_columns``) and the routing
rule the placement induces: island-bound flows take column-first
(``srota_isl_route=colfirst``, the rule that makes TOPO-003's I-ISL
invariant hold). The shape union already covers column-first, so adding
islands does not add a route the proof has not seen.

Conservation is a property of the fabric, not of the regulator (the
regulator defers flits, it does not drop them), which is what the live test
below checks.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))


def _compile(preset: str = "srota32_islands"):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import build_typed_preset_request
    request = build_typed_preset_request(preset)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    return compilation, request


def _values(prepared):
    return {line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
            for line in prepared.config_text.splitlines() if " = " in line}


def test_islands_are_carried_as_placement():
    from veritx_dse.model.topology_artifact import materialize_srota
    art = materialize_srota(k=4, concentration=2, mecs_row=True,
                            mecs_col=True, island_columns=(1,))
    assert art.island_columns == (1,)
    # The placement is part of identity, so two fabrics differing only in
    # island columns must not hash the same.
    plain = materialize_srota(k=4, concentration=2, mecs_row=True,
                              mecs_col=True)
    assert art.topology_hash() != plain.topology_hash()
    assert plain.island_columns == ()


def test_islands_need_the_full_express_layer():
    from veritx_dse.model.topology_artifact import (
        TopologyError, materialize_srota,
    )
    with pytest.raises(TopologyError, match="express"):
        materialize_srota(k=4, concentration=2, mecs_row=False,
                          mecs_col=True, island_columns=(1,))


def test_island_design_renders_the_colfirst_rule():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    compilation, request = _compile()
    assert compilation.bundle.topology.island_columns == (1,)
    prepared = prepare_booksim_input(
        _parents_from_bundle(compilation.bundle, request), seed=0)
    values = _values(prepared)
    assert values["srota_island_col_map"] == str(1 << 1)
    assert values["srota_isl_route"] == "colfirst"
    # Islands are proved with the two-shape union, not a new route.
    assert values["srota_path_en"] == "3"
    assert values["srota_vc_policy"] == "shape"


def test_row_first_only_route_cannot_carry_island_flows():
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.topology_intent import topology_intent_from_dict
    intent = topology_intent_from_dict({
        "kind": "srota", "side_length": 4, "concentration": 2,
        "mecs_row": True, "mecs_col": True, "drop_latency": 1,
        "planes": ["d", "t"], "island_columns": [1],
        "path_shapes": ["row"], "vc_policy": "none",
        "sidebuf_enable": True, "sidebuf_watermark": 6,
        "tel_period": 4, "tel_latency": 8,
    })
    compilation = FabricCompiler().compile(CompileRequestV4(
        workload=_typed_workload(32, payload_bytes=32 * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=32, protocol="AXI",
                      data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls()))
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "ROUTING"
    assert "colfirst" in (compilation.error or "")


def test_island_run_conserves_every_flit():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    binary = REPO / "third_party" / "booksim2" / "src" / "booksim"
    if not binary.is_file():
        found = shutil.which("booksim")
        binary = Path(found) if found else None
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    import tempfile
    compilation, request = _compile()
    prepared = prepare_booksim_input(
        _parents_from_bundle(compilation.bundle, request), seed=0)
    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=600)
    stats = (record.evidence.to_dict()
             if hasattr(record.evidence, "to_dict") else {}).get("stats", {})
    assert stats.get("completion_cycles", 0) > 0, stats
    assert stats.get("flits_injected") == stats.get("flits_accepted"), stats
    assert stats.get("flits_injected") == prepared.expected_flits
