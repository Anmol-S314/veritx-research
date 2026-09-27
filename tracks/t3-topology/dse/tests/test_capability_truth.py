"""Live capability truth — the registry may not outrun the implementation.

PHASE A. The load-bearing case is CONCENTRATED_MESH: the descriptive registry
claimed PROJECTABLE/EXECUTABLE/QUALIFIED = YES while `select_booksim_profile()`
has exactly two profiles and accepts neither concentrated mesh (family guard
is `MaterializedFamily.MESH`) nor its routing class (the AnyNet profile
requires ANYNET_MIN_HOPS; concentrated mesh routes DOR_XY).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).parents[4]
DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.capability_truth import (  # noqa: E402
    GATED_FAMILIES, STAGES, derive_all_stages, derive_family_stages,
)
from veritx_dse.model.compile_model import TopologyFamily  # noqa: E402


@pytest.fixture(scope="module")
def truth():
    return derive_all_stages()


# ══ the derivation is complete and independent ═════════════════════════

def test_every_gated_family_answers_every_stage(truth):
    assert len(truth) == len(GATED_FAMILIES)
    for name, t in truth.items():
        assert set(t.stages) == set(STAGES), name
        for stage in STAGES:
            assert t.stages[stage] in ("YES", "NO"), (name, stage)
            assert t.authority[stage].strip(), (name, stage)


def test_one_stage_going_yes_never_implies_another(truth):
    """TORUS is materializable but not routable; GEC is authorable but not
    materializable. Neither collapses into a single flag."""
    assert truth["torus"].stages["MATERIALIZABLE"] == "YES"
    assert truth["torus"].stages["ROUTABLE"] == "NO"
    assert truth["gec"].stages["AUTHORABLE"] == "YES"
    assert truth["gec"].stages["MATERIALIZABLE"] == "NO"


# ══ the false positive ═════════════════════════════════════════════════

def test_concentrated_mesh_is_not_projectable(truth):
    """THE PHASE-A FINDING. The registry said YES; the implementation says no,
    and the refusal names the real reason."""
    cm = truth["concentrated_mesh"]
    for stage in ("PROJECTABLE", "EXECUTABLE", "QUALIFIED"):
        assert cm.stages[stage] == "NO", (
            f"concentrated_mesh.{stage} unexpectedly YES — if a profile was "
            "added, the registry note and PHASE C must be updated together")
    assert cm.stages["MATERIALIZABLE"] == "YES"
    assert cm.stages["ROUTABLE"] == "YES"
    why = cm.authority["PROJECTABLE"]
    assert "ANYNET_MIN_HOPS" in why and "DOR_XY" in why


def test_mesh_is_fully_qualified(truth):
    m = truth["mesh"]
    for stage in STAGES:
        assert m.stages[stage] == "YES", stage
    assert m.profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"


def test_custom_projects_through_the_anynet_profile(truth):
    c = truth["custom"]
    assert c.stages["PROJECTABLE"] == "YES"
    assert c.profile_id == "CERTIFIED_BOOKSIM_ANYNET_V1"
    # CUSTOM is a classification marker with no shipped preset.
    assert c.stages["PRODUCT_WIRED"] == "NO"


def test_torus_materializes_but_cannot_route(truth):
    t = truth["torus"]
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["ROUTABLE"] == "NO"
    assert t.stopped_at_stage == "ROUTING"
    # No route means no resolved route to verify.
    assert t.stages["VERIFIABLE"] == "NO"


# ══ the gate itself ════════════════════════════════════════════════════

def test_gate_passes_on_the_current_registry():
    import subprocess
    r = subprocess.run([sys.executable,
                        str(REPO / "scripts/check_capability_truth.py")],
                       cwd=str(REPO), capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_gate_fails_when_a_registry_claims_an_unimplemented_stage(tmp_path):
    """Prove the LAW, not just the current file: a registry YES with no
    implementation authority must fail."""
    import subprocess
    import yaml
    src = REPO / "docs/product/topology-family-registry.yaml"
    doc = yaml.safe_load(src.read_text())
    # Concentrated mesh cannot project; make the registry claim it can.
    doc["families"]["concentrated_mesh"]["stages"]["PROJECTABLE"] = "YES"
    bad = tmp_path / "topology-family-registry.yaml"
    bad.write_text(yaml.safe_dump(doc))

    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "gate", REPO / "scripts/check_capability_truth.py")
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    gate.REGISTRY = bad
    failures, _ = gate.check()
    assert any("concentrated_mesh.PROJECTABLE" in f for f in failures), failures


def test_registry_no_longer_claims_the_concentrated_mesh_false_positive():
    import yaml
    doc = yaml.safe_load(
        (REPO / "docs/product/topology-family-registry.yaml").read_text())
    stages = doc["families"]["concentrated_mesh"]["stages"]
    assert stages["PROJECTABLE"] == "NO"
    assert stages["EXECUTABLE"] == "NO"
    assert stages["QUALIFIED"] == "NO"
    assert "capability_truth" in doc["families"]["concentrated_mesh"]["evidence"]


def test_registry_evidence_cites_the_truth_gate_for_every_correction():
    import yaml
    doc = yaml.safe_load(
        (REPO / "docs/product/topology-family-registry.yaml").read_text())
    for fam in ("concentrated_mesh", "torus", "gec"):
        blob = " ".join(str(v) for v in doc["families"][fam].values())
        assert "PHASE A" in blob or "capability_truth" in blob, fam
