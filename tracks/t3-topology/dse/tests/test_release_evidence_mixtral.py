import hashlib
import json
from pathlib import Path

import pytest

EVIDENCE_DIR = Path(__file__).resolve().parents[4] / "docs" / "product" / "evidence" / "mixtral-74-81-8-162"
REVISION_PATH = EVIDENCE_DIR / "revision-p-fd7e5e31be77-r02.json"
TOPOLOGY_PATH = EVIDENCE_DIR / "topology-p-fd7e5e31be77-r02.json"

PINNED = {
    REVISION_PATH.name: "51ebbc5429011b5f394cd216554d2cfc4022b3d5ae884facbdc4ca52380fef4a",
    TOPOLOGY_PATH.name: "4315ad69bab4035251ca1bb3fec6c2219fcc6ad0132452c4684269298d5d9a82",
}
DESIGN_HASH = "sha256:ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0"


def _load(path):
    return json.loads(path.read_text())


@pytest.mark.parametrize("name,digest", sorted(PINNED.items()))
def test_pinned_artifact_bytes(name, digest):
    assert hashlib.sha256((EVIDENCE_DIR / name).read_bytes()).hexdigest() == digest


def test_selected_revision_keeps_74_agents():
    design = _load(REVISION_PATH)["design"]
    counts = {agent["kind"]: agent["count"] for agent in design["agents"]}
    assert counts == {"compute_tile": 64, "hbm_controller": 8, "nic": 2}
    assert sum(counts.values()) == 74


def test_selected_revision_keeps_eight_vcs():
    design = _load(REVISION_PATH)["design"]
    assert design["locked_derived"]["vc_count"] == 8
    assert design["locked_derived"]["routing"] == "DOR_GEC_MECS"


def test_selected_revision_keeps_81_routers_and_162_shared_links():
    topology = _load(TOPOLOGY_PATH)
    assert topology["family"] == "gec_mecs"
    assert topology["counts"] == {
        "channels": 0,
        "endpoints": 74,
        "routers": 81,
        "seats": 81,
        "shared_links": 162,
    }


def test_selected_revision_hashes_agree():
    revision = _load(REVISION_PATH)
    topology = _load(TOPOLOGY_PATH)
    assert revision["design_hash"] == DESIGN_HASH
    assert topology["design_hash"] == DESIGN_HASH
    assert revision["revision_id"] == topology["revision_id"] == "p-fd7e5e31be77-r02"
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["compilation"]["certificate_overall"] == "PASS"


def test_selected_revision_endpoints_cover_every_agent_instance():
    topology = _load(TOPOLOGY_PATH)
    revision = _load(REVISION_PATH)
    declared = sum(agent["count"] for agent in revision["design"]["agents"])
    endpoints = topology["endpoints"]
    assert len(endpoints) == declared
    seen = {(endpoint["group_index"], endpoint["instance_index"]) for endpoint in endpoints}
    assert len(seen) == declared
    assert sorted(endpoint["endpoint_id"] for endpoint in endpoints) == list(range(declared))
