"""FabricArtifact contracts (audit #1): one fabric authority.

Identity is content-addressed: same executed network → same hash, any
material mutation → different hash or explicit refusal. Both BookSim
paths share the config parser — never two readers of one grammar.
"""
import pytest

from veritx_dse.core.fabric import (
    check_serving_fabric,
    fabric_from_config_text,
    fabric_from_preset,
    fabric_hash,
    fabrics_match,
)
from veritx_dse.model.presets import lookup_topo

MESH_CFG = """k = 8;
n = 2;
num_vcs = 4;
vc_buf_size = 8;
packet_size = 8;
topology = mesh;
routing_function = min_adapt;
"""


def test_hash_stable():
    a = fabric_from_config_text(MESH_CFG)
    b = fabric_from_config_text(MESH_CFG)
    assert a.artifact_hash == b.artifact_hash


def test_mutation_changes_hash():
    a = fabric_from_config_text(MESH_CFG)
    b = fabric_from_config_text(MESH_CFG.replace("num_vcs = 4;", "num_vcs = 8;"))
    assert a.artifact_hash != b.artifact_hash
    assert a.num_vcs == 4 and b.num_vcs == 8


def test_fields_parsed():
    a = fabric_from_config_text(MESH_CFG)
    assert (a.topology, a.routing, a.node_count) == ("mesh", "min_adapt", 64)
    assert (a.vc_buf_size, a.packet_size) == (8, 8)
    assert a.config_sha256.startswith("sha256:")


def test_missing_topology_refused():
    with pytest.raises(ValueError, match="topology"):
        fabric_from_config_text("num_vcs = 4;\n")


def test_anynet_counts_routers_and_hashes():
    anynet = "router 0 node 0 router 1\nrouter 1 node 1 router 0\n"
    a = fabric_from_config_text(
        "topology = anynet;\nnetwork_file = /x/topo.anynet;\n"
        "routing_function = min;\nnum_vcs = 16;\n",
        anynet_text=anynet)
    assert a.node_count == 2
    assert a.anynet_sha256.startswith("sha256:")
    assert a.artifact_hash != fabric_from_config_text(
        "topology = anynet;\nnetwork_file = /x/topo.anynet;\n"
        "routing_function = min;\nnum_vcs = 16;\n").artifact_hash


def test_preset_constructor():
    topo = lookup_topo("mesh_8x8")
    a = fabric_from_preset(topo, 64)
    assert a.source == "preset:mesh_8x8"
    assert (a.topology, a.routing, a.node_count) == ("mesh", "min_adapt", 64)
    assert a.config_sha256 is None


def test_match_same_fabric():
    a = fabric_from_config_text(MESH_CFG)
    ok, reason = fabrics_match(a, fabric_from_config_text(MESH_CFG))
    assert ok and reason is None


def test_match_routing_mismatch():
    a = fabric_from_config_text(MESH_CFG)
    b = fabric_from_config_text(MESH_CFG.replace("min_adapt", "dim_order"))
    ok, reason = fabrics_match(a, b)
    assert not ok and "routing" in reason


def test_match_unrecorded_never_matches():
    a = fabric_from_config_text(MESH_CFG)
    b = fabric_from_config_text("topology = mesh;\nrouting_function = min_adapt;\n")
    ok, reason = fabrics_match(a, b)
    assert not ok and "unrecorded" in reason


EXP = {"source": "serving_cluster", "cluster": "single_tp2_ep2",
       "topology": ["FullyConnected"], "dimensions": [2], "npu_count": 2}
YML = {"topology": ["FullyConnected"], "npus_count": [2]}


def _exec(nodes=2):
    return fabric_from_config_text(
        f"k = {nodes};\nn = 1;\nnum_vcs = 16;\nrouting_function = dor;\n"
        f"topology = mesh;\n").to_dict()


def test_serving_check_accepts_matching():
    ok, reason = check_serving_fabric(EXP, _exec(2), YML)
    assert ok and reason is None


def test_serving_check_rejects_node_mismatch():
    ok, reason = check_serving_fabric(EXP, _exec(4), YML)
    assert not ok and "nodes" in reason


def test_serving_check_rejects_yml_dims_mismatch():
    ok, reason = check_serving_fabric(
        EXP, _exec(2), {"topology": ["FullyConnected"], "npus_count": [4]})
    assert not ok and "dims" in reason


def test_serving_check_rejects_missing_evidence():
    ok, _ = check_serving_fabric(EXP, {"unrecorded": True}, YML)
    assert not ok
    ok, _ = check_serving_fabric(EXP, _exec(2), None)
    assert not ok
    ok, _ = check_serving_fabric(None, _exec(2), YML)
    assert not ok
