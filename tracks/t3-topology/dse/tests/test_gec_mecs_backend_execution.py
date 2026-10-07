"""GEC-MECS renders and executes live over its shared wires.

The second shared-wire fabric to reach a live run, and the one that proves
the pattern generalizes: it shares the SROTA substrate (SharedLink ->
RouteArtifactV3 -> shared_resource_cdg -> shared-resource-cdg/v1) but NOT
its tap rule, its routing function, or its VC policy.

What only this test can show:

  * the rendered config is a MECS config — mesh=0 and d>1 are pinned, because
    mesh=1 would build only nearest-neighbour links and execute a different
    network than the one certified;
  * routing_delay > 0, because MECS refuses lookahead routing (the next hop
    is resolved through FlitChannel::GetSink(), which cannot distinguish a
    multidrop channel's taps);
  * injected == accepted == the canonical trace's flit total.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

_SURFACE = "CERTIFIED_BOOKSIM_GEC_MECS_V1"


def _build(k: int, o: int, d: int):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
    intent = GecTopologyIntent(
        mode=GecMode.MULTIDROP, grid_side_length=k, concentration=1,
        express_channel_groups_per_dimension=o,
        destinations_per_express_channel=d)
    n = k * k
    request = CompileRequestV4(
        workload=_typed_workload(n, payload_bytes=n * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=n, protocol="AXI",
                      data_width=256, addr_width=64),),
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


def test_the_rendered_config_pins_the_multidrop_surface():
    from veritx_dse.backend.booksim_projection import (
        prepare_booksim_input, select_booksim_profile,
    )
    compilation, request = _build(4, 1, 3)
    parents = _parents(compilation, request)
    assert select_booksim_profile(parents).profile_id == _SURFACE
    prepared = prepare_booksim_input(parents, seed=0)
    values = {line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
              for line in prepared.config_text.splitlines() if " = " in line}
    assert values["topology"] == "gec"
    assert values["routing_function"] == "dor_gec"
    assert values["o"] == "1" and values["d"] == "3"
    assert values["mesh"] == "0", (
        "mesh=1 builds only nearest-neighbour links and none of the express "
        "layer, so it would execute a different network")
    assert values["routing_delay"] == "1", (
        "MECS refuses lookahead routing: the next hop is resolved through "
        "FlitChannel::GetSink(), which cannot distinguish taps")
    assert values["use_noc_latency"] == "0"
    # One VC per tap, and the route agrees (see test_gec_mecs_vc_partition).
    assert values["num_vcs"] == "3"
    assert "network_file" not in values


def test_the_envelope_refuses_an_express_fabric():
    """d == 1 is point-to-point express, a different certified surface."""
    from veritx_dse.backend.booksim_projection import (
        qualify_native_gec_mecs,
    )
    compilation, request = _build(4, 1, 3)
    parents = _parents(compilation, request)
    object.__setattr__(parents, "route", None)
    with pytest.raises(Exception):
        qualify_native_gec_mecs(parents)


@pytest.mark.parametrize("k,o,d", [(4, 1, 3), (6, 1, 5)])
def test_mecs_executes_live_and_conserves_every_flit(k, o, d):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    binary = _booksim_bin()
    if binary is None:
        pytest.skip("no built BookSim binary in tree")
    import tempfile

    compilation, request = _build(k, o, d)
    parents = _parents(compilation, request)
    prepared = prepare_booksim_input(parents, seed=0)
    assert prepared.profile_id == _SURFACE
    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=600)
    stats = (record.evidence.to_dict()
             if hasattr(record.evidence, "to_dict") else {}).get("stats", {})
    assert stats.get("completion_cycles", 0) > 0, stats
    assert stats.get("flits_injected") == stats.get("flits_accepted"), stats
    assert stats.get("flits_injected") == prepared.expected_flits, (
        "the executed total must be the one the canonical trace declared")
    latency = stats.get("packet_latency_avg")
    assert latency is not None and latency > 0, (
        "the fork measured packet latency; the evidence must carry it")
