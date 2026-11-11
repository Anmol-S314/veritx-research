import hashlib
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[4]
APPROVAL = ROOT / "docs" / "product" / "evidence" / "release-workloads-20261110.json"


def _approval():
    return json.loads(APPROVAL.read_text())


def test_approval_names_the_pinned_mixtral_revision():
    approval = _approval()
    full = approval["full_size_acceptance"]
    assert full["revision_id"] == "p-fd7e5e31be77-r02"
    assert full["design_hash"] == "sha256:ab7bce8f71b5ed4fde4101ee80a60b6c69c16989d966f0f9096dd6d76ad392f0"
    assert (full["agents"], full["routers"], full["vcs"], full["shared_links"]) == (74, 81, 8, 162)


def test_every_approved_workload_exists_and_matches_its_hash():
    approval = _approval()
    assert approval["approved_workloads"]
    for workload in approval["approved_workloads"]:
        path = ROOT / workload["path"]
        assert path.is_file(), workload["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == workload["sha256"], workload["id"]


def test_debug_designs_never_replace_full_size_acceptance():
    approval = _approval()
    assert approval["full_size_acceptance"]["agents"] == 74
    for design in approval["debug_designs"]:
        assert "never" in approval["selection_rule"].lower()
        assert design["scope"]
        assert design["purpose"]


@pytest.mark.parametrize("excluded", _approval()["excluded"])
def test_excluded_inputs_name_a_reason(excluded):
    assert excluded["reason"].strip()
