"""The Chipyard bridge must bind route resources by tap, not array index."""
from dataclasses import replace
import hashlib
import json

import pytest

from veritx_dse.model.topology_intent import GecMode, GecTopologyIntent
from veritx_dse.product.chipyard_gec import export_contract
from test_topology_search import _base


def request(k=9):
    base = _base()
    return replace(base, noc_controls=replace(base.noc_controls, link_width=128),
                   topology=GecTopologyIntent(
                       mode=GecMode.MULTIDROP, grid_side_length=k, concentration=1,
                       express_channel_groups_per_dimension=1, destinations_per_express_channel=k-1))


def test_selected_size_exports_compiled_wires_routes_vcs_and_packet_fields(tmp_path):
    result = export_contract(request().to_dict(), tmp_path, revision_id="test-r02")
    assert (result["routers"], result["vcs"], result["shared_wires"]) == (81, 8, 162)
    doc = json.loads((tmp_path / "contract.json").read_text())
    wires = doc["topology"]["shared_links"]
    # Route resource 1 is router 0's row port, not topology wire 1 (column).
    assert doc["route_resource_to_shared_link"]["1"] == 0
    endpoint_routers = doc["endpoint_routers"]
    for r, row in enumerate(doc["route_table"]):
        assert len(row) == 81
        for dst, (wire, nxt, vc) in enumerate(row):
            if r == dst:
                assert wire == -1
            else:
                assert wires[wire]["src_router"] == r
                assert nxt in wires[wire]["taps"]
                assert 0 <= vc < 8
        for endpoint_router in endpoint_routers:
            wire, nxt, vc = row[endpoint_router]
            if r == endpoint_router:
                assert wire == -1 and nxt == r
            else:
                assert wires[wire]["src_router"] == r
                assert nxt in wires[wire]["taps"]
                assert 0 <= vc < 8
    assert doc["final_implementation"] is False
    assert doc["scope"] == "CHIPYARD_TOPOLOGY_PREVIEW"
    assert "credit" in " ".join(doc["limitations"]).lower()
    assert doc["packet_format"]["flit_width_bits"] == 128
    assert doc["router_behavior"]["credit_return_latency_cycles"] == 1
    assert {w["latency_cycles"] for w in wires} == {1}
    assert {w["width_bits"] for w in wires} == {128}
    assert len(result["contract_hash"]) == 64
    binary = tmp_path / "resources" / "selected-gec.bin"
    assert binary.is_file()
    assert hashlib.sha256(binary.read_bytes()).hexdigest() == result["binary_hash"]
    first = (tmp_path / "SelectedGec.scala").read_bytes()
    binary_first = binary.read_bytes()
    assert len(first) < 4096, "route graph must remain a data resource, not a JVM initializer"
    source = first.decode()
    for token in (
        "GecContractData.load(\"/selected-gec.bin\"",
        "val sourceLsb = 113", "val sourceWidth = 5",
        "val typeWidth = 2", "val creditReturnLatency = 1",
        "val routeComputeCycles = 0", "val vcAllocCycles = 1",
        "val switchAllocCycles = 1", "val switchTraversalCycles = 1",
        "val outputStageDepth = 1", "val wireWidths = data.wires.map(_.width)",
        "val wireLatencies = data.wires.map(_.latency)", "val routes = data.routes",
    ):
        assert token in source
    assert export_contract(request().to_dict(), tmp_path, revision_id="test-r02") == result
    assert (tmp_path / "SelectedGec.scala").read_bytes() == first
    assert binary.read_bytes() == binary_first


def test_selected_74_endpoint_scale_is_preserved_in_source_contract(tmp_path):
    doc = request().to_dict()
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["agents"] = [
        {"addr_width": 64, "clock_domain": None, "count": 64, "data_width": 256,
         "kind": "compute_tile", "power_domain": None, "protocol": "AXI"},
        {"addr_width": 64, "clock_domain": None, "count": 8, "data_width": 256,
         "kind": "hbm_controller", "power_domain": None, "protocol": "AXI"},
        {"addr_width": 64, "clock_domain": None, "count": 2, "data_width": 256,
         "kind": "nic", "power_domain": None, "protocol": "AXI"},
    ]
    result = export_contract(doc, tmp_path, revision_id="test-74-endpoints")
    contract = json.loads((tmp_path / "contract.json").read_text())
    source = (tmp_path / "SelectedGec.scala").read_text()
    assert result["endpoints"] == 74
    assert len(contract["endpoint_routers"]) == 74
    assert "val sourceWidth = 7" in source
    assert "val destWidth = 7" in source


def test_other_fabric_is_refused_before_writing(tmp_path):
    with pytest.raises(ValueError, match="multidrop GEC"):
        export_contract(_base().to_dict(), tmp_path / "out", revision_id="test")
    assert not (tmp_path / "out").exists()


def test_concentrated_profile_is_not_silently_misrouted(tmp_path):
    req = request(4)
    req = replace(req, topology=replace(req.topology, concentration=2))
    with pytest.raises(ValueError, match="concentration"):
        export_contract(req.to_dict(), tmp_path / "out", revision_id="test")
    assert not (tmp_path / "out").exists()
