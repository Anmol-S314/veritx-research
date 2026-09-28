"""Structural registry-truth test: COMM-006 may not contradict the MC profile.

Derives from live authorities, not prose:
  - MESH_DOR_MC_PROFILE / qualify_native_mesh_dor_mc in booksim_projection
  - LogicalMessageArtifactV3 / PhysicalTrafficArtifactV3 / VCResource
  - capability-registry.yaml COMM-006 row + MC envelope

Fails on the exact contradiction the reconciliation fixes: Studio rendering
READY / CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1 alongside multi-class
NOT_AVAILABLE.
"""
from __future__ import annotations

import sys
from pathlib import Path

import yaml

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

REPO = Path(__file__).resolve().parent.parent.parent.parent.parent
REGISTRY = REPO / "docs" / "product" / "capability-registry.yaml"

MC_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1"
MC_ENVELOPE = "CAP-ENV-BOOKSIM-MESH-DOR-MC-V1"


def _registry_row():
    doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    caps = {c.get("id"): c for c in doc.get("capabilities") or []}
    return doc, caps["COMM-006"]


def test_mc_profile_authority_exists():
    import veritx_dse.backend.booksim_projection as bp

    assert getattr(bp, "MESH_DOR_MC_PROFILE", None) is not None
    assert bp.MESH_DOR_MC_PROFILE.profile_id == MC_PROFILE_ID
    assert callable(bp.qualify_native_mesh_dor_mc)


def test_v3_class_aware_artifacts_exist():
    from veritx_dse.model.vc_resource import VCResourceArtifact
    from veritx_dse.workload.messages import LogicalMessageArtifactV3
    from veritx_dse.workload.traffic import PhysicalTrafficArtifactV3

    assert LogicalMessageArtifactV3.__name__
    assert PhysicalTrafficArtifactV3.__name__
    assert VCResourceArtifact.__name__


def test_selector_can_return_mc_profile():
    import inspect

    import veritx_dse.backend.booksim_projection as bp

    src = inspect.getsource(bp.select_booksim_profile)
    assert "MESH_DOR_MC_PROFILE" in src or MC_PROFILE_ID in src


def test_comm006_not_stale_no():
    _doc, row = _registry_row()
    stages = row["stages"]
    for stage in ("PROJECTABLE", "EXECUTABLE", "QUALIFIED", "EVIDENCE_CAPABLE"):
        assert stages[stage] != "NO", (
            f"COMM-006 {stage} is NO while {MC_PROFILE_ID} is live"
        )
    assert row["wiring"] != "NOT_AVAILABLE"


def test_comm006_bound_to_mc_envelope():
    doc, row = _registry_row()
    assert MC_ENVELOPE in list(row.get("conditions") or [])
    assert (doc["envelopes"][MC_ENVELOPE] or {})["profile_id"] == MC_PROFILE_ID
