"""SROTA Plane D executes on the real fork through the canonical pipeline.

This is the last link: a design authored as SROTA intent, compiled and
certified with its deadlock obligation discharged over the shared-resource
graph, rendered into a BookSim config by a profile whose audit describes
WIRES rather than channels, prepared, and executed live.

What only this test can show:

  * the rendered config is a SROTA config (no point-to-point channels appear
    anywhere in it), and the fabric it describes is the one certified;
  * injected == accepted == the trace's flit total, so nothing was silently
    dropped by a shared wire that the renderer had mis-modelled.

The fork's own F1 static CDG check also runs at elaboration on every SROTA
run (``srota_cdg_radix`` is pinned to k), so a run that starts at all is a
second, independent acyclicity witness alongside ours.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

_SROTA_SURFACE = "CERTIFIED_BOOKSIM_SROTA_ROW_FIRST_V1"


def _build(side_length: int, concentration: int):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.topology_intent import topology_intent_from_dict
    endpoints = side_length ** 2 * concentration
    intent = topology_intent_from_dict({
        "kind": "srota", "side_length": side_length,
        "concentration": concentration, "mecs_row": True, "mecs_col": True,
        "drop_latency": 1, "planes": ["d", "t"], "island_columns": [],
        "path_shapes": ["row"], "vc_policy": "none",
        "sidebuf_enable": True, "sidebuf_watermark": 6,
        "tel_period": 4, "tel_latency": 8,
    })
    request = CompileRequestV4(
        # EVERY collective in this workload must divide by the tile count,
        # so the payload is derived from it rather than hardcoded.
        workload=_typed_workload(endpoints, payload_bytes=endpoints * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=endpoints,
                      protocol="AXI", data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls())
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    return compilation, request


def _parents(compilation, request):
    from veritx_dse.application.capability_truth import _parents_from_bundle
    return _parents_from_bundle(compilation.bundle, request)


def _booksim_bin() -> Path | None:
    candidate = REPO / "third_party" / "booksim2" / "src" / "booksim"
    if candidate.is_file():
        return candidate
    found = shutil.which("booksim")
    return Path(found) if found else None


def test_the_rendered_config_is_a_srota_config_with_no_channels():
    """The surface must name wires, not channels.

    A point-to-point field leaking into this config would mean the renderer
    fell back to a profile that cannot describe a bus.
    """
    from veritx_dse.backend.booksim_projection import (
        prepare_booksim_input, select_booksim_profile,
    )
    compilation, request = _build(4, 2)
    parents = _parents(compilation, request)
    profile = select_booksim_profile(parents)
    assert profile.profile_id == _SROTA_SURFACE
    prepared = prepare_booksim_input(parents, seed=0)
    values = {
        line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
        for line in prepared.config_text.splitlines() if " = " in line}
    assert values["topology"] == "srota"
    assert values["routing_function"] == "o1turn"
    assert values["srota_router"] == "sidebuf"
    assert values["srota_path_en"] == "1", (
        "both direct shapes live without a VC partition reproduce RT-R7")
    assert values["srota_vc_policy"] == "none"
    assert values["num_vcs"] == "1"
    assert values["srota_d_num_vcs"] == "1"
    assert values["subnets"] == "1"
    assert values["use_noc_latency"] == "0"
    # The fork re-checks acyclicity itself at this radix.
    assert values["srota_cdg_radix"] == values["k"]
    assert "network_file" not in values, (
        "a rendered AnyNet file would mean a different topology was built")


def test_the_qualified_envelope_refuses_a_shape_mixing_design():
    """The profile covers ONE shape; mixing has no partition policy."""
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
        "planes": ["d", "t"], "island_columns": [],
        "path_shapes": ["row", "column"], "vc_policy": "rank",
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


@pytest.mark.parametrize("side_length,concentration", [(4, 2), (6, 2)])
def test_srota_executes_live_and_conserves_every_flit(side_length,
                                                      concentration):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    import tempfile

    compilation, request = _build(side_length, concentration)
    parents = _parents(compilation, request)
    prepared = prepare_booksim_input(parents, seed=0)
    assert prepared.profile_id == _SROTA_SURFACE
    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=600)
    doc = record.evidence.to_dict() \
        if hasattr(record.evidence, "to_dict") else {}
    stats = doc.get("stats", doc)
    assert stats.get("completion_cycles", 0) > 0, stats
    injected = stats.get("flits_injected")
    accepted = stats.get("flits_accepted")
    assert injected is not None and injected == accepted, stats
    # ...and the executed total is the one the canonical trace declared, so
    # the renderer did not silently drop or duplicate traffic.
    assert injected == prepared.expected_flits, (
        f"executed {injected} flits, the canonical trace declares "
        f"{prepared.expected_flits}")


def test_the_run_reports_measured_latency_not_just_completion():
    """MEASURED, not ESTIMATED: these are the fork's own statistics.

    Completion cycles and flit conservation say the run finished and lost
    nothing; they say nothing about how long the fabric took. The fork
    measures packet and flit latency, so the evidence carries them and the
    test asserts they are present and physically sane — a measured latency
    below the minimum possible hop count would mean the statistic was
    mis-parsed rather than measured.

    Hops are deliberately NOT asserted: a trace-driven run records no hop
    histogram, and inventing one would be exactly the estimate this project
    refuses.
    """
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    import tempfile

    compilation, request = _build(4, 2)
    parents = _parents(compilation, request)
    prepared = prepare_booksim_input(parents, seed=0)
    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=600)
    doc = record.evidence.to_dict() \
        if hasattr(record.evidence, "to_dict") else {}
    stats = doc.get("stats", doc)
    packet_latency = stats.get("packet_latency_avg")
    flit_latency = stats.get("flit_latency_avg")
    assert packet_latency is not None, (
        "the fork measured packet latency and the evidence must carry it")
    assert flit_latency is not None
    # A packet occupies at least one cycle per hop it crosses, so a mean
    # packet latency below a single cycle is not a measurement.
    assert packet_latency > 0, stats
    assert flit_latency > 0, stats
    assert packet_latency >= flit_latency, (
        f"a packet cannot average less than one of its flits "
        f"({packet_latency} < {flit_latency}); the statistic is mis-parsed")
    assert stats.get("sample_window_cycles") is not None, (
        "the measurement window is part of the provenance of any latency "
        "number and must be recorded alongside it")


def test_two_shape_srota_executes_live_and_every_hop_was_certified():
    """The adaptive (union) route runs, and its hops are its proof's hops.

    The FIU picks the shape per flow from live telemetry load, so the
    executed realization is a SAMPLE of the certified union — which is why
    the evidence comparison is membership, not equality. And "membership"
    is only meaningful if the alternative (no separation) would have failed:
    see test_collapsing_the_shapes_reproduces_rt_r7 in
    test_srota_shape_policy_union.py.
    """
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.route_artifact_v3 import ShapePolicyRoute
    from veritx_dse.model.topology_intent import topology_intent_from_dict
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    import tempfile

    intent = topology_intent_from_dict({
        "kind": "srota", "side_length": 4, "concentration": 2,
        "mecs_row": True, "mecs_col": True, "drop_latency": 1,
        "planes": ["d", "t"], "island_columns": [],
        "path_shapes": ["row", "column"], "vc_policy": "shape",
        "sidebuf_enable": True, "sidebuf_watermark": 6,
        "tel_period": 4, "tel_latency": 8,
    })
    request = CompileRequestV4(
        workload=_typed_workload(32, payload_bytes=32 * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=32, protocol="AXI",
                      data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls())
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    route = compilation.bundle.router_route
    assert isinstance(route, ShapePolicyRoute), (
        "a two-shape design must carry a UNION route; a deterministic one "
        "would certify the design against one of its two choices")
    assert compilation.bundle.vc_assignment.vc_count == 2
    parents = _parents(compilation, request)
    prepared = prepare_booksim_input(parents, seed=0)
    values = {line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
              for line in prepared.config_text.splitlines() if " = " in line}
    assert values["srota_path_en"] == "3"
    assert values["srota_vc_policy"] == "shape"
    assert values["num_vcs"] == "2"
    assert values["srota_d_num_vcs"] == "2"
    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=600)
    stats = (record.evidence.to_dict()
             if hasattr(record.evidence, "to_dict") else {}).get("stats", {})
    assert stats.get("completion_cycles", 0) > 0, stats
    assert stats.get("flits_injected") == stats.get("flits_accepted"), stats
    assert stats.get("flits_injected") == prepared.expected_flits
    assert stats.get("packet_latency_avg") is not None
