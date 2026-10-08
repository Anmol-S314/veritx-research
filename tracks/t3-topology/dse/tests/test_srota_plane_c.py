"""SROTA Plane C: a SECOND subnet, materialized and executed independently.

Plane C is the SR-C control plane: a plain VC-buffered mesh with REQ/RSP/SNP
on three independent VCs and plain XY. It is not a recolouring of Plane D,
so the compiler derives it separately from the Plane D fabric (same grid and
concentration), the fabric declares ``multi_plane``, and the render puts each
traffic class on its own subnet via ``class_subnet``.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))


def _compile(preset: str = "srota32_plane_c"):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import build_typed_preset_request
    request = build_typed_preset_request(preset)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    return compilation, request


def _values(prepared):
    return {line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
            for line in prepared.config_text.splitlines() if " = " in line}


def test_control_plane_is_derived_from_the_data_plane_fabric():
    from veritx_dse.model.control_plane import (
        ControlPlaneArtifact, ControlPlaneError, materialize_control_plane,
    )
    compilation, _request = _compile()
    assert "c" in compilation.bundle.topology.planes
    cp = compilation.control_plane
    assert isinstance(cp, ControlPlaneArtifact)
    assert (cp.k, cp.c) == (4, 2)
    assert cp.vcs == ("REQ", "RSP", "SNP")
    assert cp.routing == "xy"
    assert cp.subnet == 1
    assert cp.content_hash
    # It refuses a fabric that does not declare Plane C.
    from veritx_dse.model.topology_artifact import materialize_srota
    plain = materialize_srota(k=4, concentration=2, mecs_row=True,
                              mecs_col=True)
    with pytest.raises(ControlPlaneError, match="Plane C"):
        materialize_control_plane(plain)


def test_fabric_declares_multi_plane():
    from veritx_dse.model.fabric_artifact import PlaneComposition
    compilation, _request = _compile()
    assert compilation.bundle.fabric.plane_composition \
        is PlaneComposition.MULTI_PLANE
    # A single-plane SROTA fabric is unchanged.
    plain, _r = _compile("srota32")
    assert plain.bundle.fabric.plane_composition \
        is PlaneComposition.SINGLE_PLANE
    assert plain.control_plane is None


def test_multi_plane_render_puts_each_class_on_its_plane():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_projection import (
        prepare_booksim_input, trace_class_map,
    )
    compilation, request = _compile()
    parents = _parents_from_bundle(compilation.bundle, request)
    assert len(trace_class_map(parents.physical_traffic)) == 2
    values = _values(prepare_booksim_input(parents, seed=0))
    assert values["subnets"] == "2"
    # TOPO_PLANES: D=1, C=2, T=4.
    assert values["srota_planes"] == "7"
    assert values["srota_planec_vcs"] == "3"
    assert values["srota_planec_vc_buf"] == "4"
    assert values["class_subnet"] == "{0,1}"
    assert values["classes"] == "2"
    # num_vcs must cover Plane C's three VCs as well as Plane D's two.
    assert values["num_vcs"] == "3"
    assert values["srota_d_num_vcs"] == "2"


def test_a_single_class_workload_cannot_leave_plane_c_idle():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_projection import (
        BookSimProjectionError, prepare_booksim_input,
    )
    from veritx_dse.application.presets import build_typed_preset_request
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.model.srota_intent import SrotaIntent
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.application.presets import _typed_workload
    intent = SrotaIntent(
        side_length=4, concentration=2, mecs_row=True, mecs_col=True,
        drop_latency=1, planes=frozenset({"d", "c", "t"}), island_columns=(),
        path_shapes=frozenset({"row", "column"}), vc_policy="shape",
        sidebuf_enable=True, sidebuf_watermark=6, tel_period=4,
        tel_latency=8)
    request = CompileRequestV4(
        workload=_typed_workload(32, payload_bytes=32 * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=32, protocol="AXI",
                      data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls())
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    parents = _parents_from_bundle(compilation.bundle, request)
    with pytest.raises(BookSimProjectionError, match="BOTH planes"):
        prepare_booksim_input(parents, seed=0)


def test_multi_plane_run_conserves_every_flit():
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
    # The full two-class trace was injected: neither plane was dropped.
    assert stats.get("flits_injected") == prepared.expected_flits, stats
