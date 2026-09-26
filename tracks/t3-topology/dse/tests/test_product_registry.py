"""veritx_dse.application.product_registry — the backend registry owner.

Gate 4 / Gate 6: the registries are data, and exactly one backend module
owns reading them. Claim surfaces bind to ``capability_semantics_version``
from here; they never hardcode it (Gate 8 §7).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application import product_registry as pr  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache():
    pr.clear_cache()
    yield
    pr.clear_cache()


# ── version: one authority ─────────────────────────────────────────────


def test_capability_semantics_version_is_exposed():
    assert pr.capability_semantics_version() == "cap-v1"


def test_registry_versions_reports_both_documents():
    versions = pr.registry_versions()
    assert versions["capability_semantics_version"] == "cap-v1"
    assert versions["capability_registry_version"] == 1
    assert versions["exposure_registry_version"] == 1


def test_registry_dir_resolves_from_the_package():
    assert (pr.registry_dir() / "capability-registry.yaml").is_file()


def test_missing_registry_dir_fails_closed(monkeypatch):
    monkeypatch.setenv("VERITX_PRODUCT_REGISTRY_DIR", "/nonexistent/registry")
    with pytest.raises(pr.ProductRegistryError):
        pr.registry_dir()


def test_disagreeing_semantics_versions_fail_closed(monkeypatch):
    """Two registries, one version. A disagreement is a build error."""
    capability = pr.capability_document()
    exposure = pr.exposure_document()
    pr.clear_cache()

    import copy
    cap_doc = copy.deepcopy(capability)
    exp_doc = copy.deepcopy(exposure)
    exp_doc["capability_semantics_version"] = "cap-v2"

    monkeypatch.setattr(pr, "capability_document", lambda: cap_doc)
    monkeypatch.setattr(pr, "exposure_document", lambda: exp_doc)
    pr.capability_semantics_version.cache_clear()
    with pytest.raises(pr.ProductRegistryError, match="disagree"):
        pr.capability_semantics_version()


# ── exposure projection ────────────────────────────────────────────────


def test_removed_v4_fields_are_never_rendered():
    """Gate 4/6: a removed-v4 field is not Design intent."""
    for path in ("NocConfig.rcu_enabled", "NocConfig.mcast_groups",
                 "NocConfig.mcast_setup_cycles",
                 "RequirementV3.bandwidth_floor_gbps"):
        assert not pr.is_rendered(path), path


def test_unknown_field_fails_closed():
    """An unclassified active field is never rendered (Gate 8 §138)."""
    assert not pr.is_rendered("NocConfig.not_a_field")
    assert pr.exposure_class("NocConfig.not_a_field") is None
    assert pr.product_label("NocConfig.not_a_field") is None


def test_accepted_intent_fields_are_rendered():
    for path in ("NocConfig.radix", "NocConfig.topology_family",
                 "NocConfig.concentration", "NocConfig.link_width",
                 "WorkloadV3.model_family", "RequirementV3.qos_class"):
        assert pr.is_rendered(path), path


def test_container_rows_are_not_directly_rendered():
    assert not pr.is_rendered("CompileRequestV3.noc_config")
    assert pr.exposure_class("CompileRequestV3.noc_config") == "container"


def test_radix_carries_the_product_label_not_the_implementation_name():
    """Gate 3 CROSS-DOMAIN CORRECTION / §16.

    ``radix`` is the implementation field; ``side_length`` is the
    scientific name; the product labels come from the registry so no
    surface invents its own.
    """
    assert pr.product_label("NocConfig.radix") == "Grid size"
    assert pr.product_label("NocConfig.radix", "EXPERT") == "Mesh side length"
    assert pr.scientific_name("NocConfig.radix") == "side_length"


def test_disclosure_depth_comes_from_the_class():
    assert pr.disclosure_depth("NocConfig.radix") == "GUIDED"
    assert pr.disclosure_depth("NocConfig.arbitration") == "GUIDED"
    assert pr.disclosure_depth("NocConfig.output_formats") == "EXPERT"


def test_source_of_value_is_registry_owned():
    assert pr.source_of_value("NocConfig.radix") == "RECOMMENDATION"
    assert pr.source_of_value("NocConfig.rcu_enabled") == "NONE"


def test_guided_eligible_presets_match_the_registry():
    """Uncertified presets are never presented as Guided-safe (§32)."""
    guided = pr.guided_eligible_presets()
    assert "mesh4" in guided
    assert "mesh4_hbm" in guided
    assert "mesh4_wide128" in guided
    assert "dense-1b-16tiles" in guided
    assert "dense-4b-32tiles-conc4" not in guided
    assert "moe-8x7b-64tiles" not in guided


def test_uncertified_preset_names_its_reason():
    spec = pr.preset_spec("dense-4b-32tiles-conc4")
    assert spec["guided_eligible"] is False
    assert spec.get("reason")


# ── capability projection ──────────────────────────────────────────────


def test_capability_consequence_answers_all_eight_stages():
    consequence = pr.capability_consequence("FAB-003")
    assert set(consequence["stages"]) == set(pr.STAGES)
    assert consequence["wiring"] == "INSPECT_ONLY"
    assert consequence["reason"] == "NO_BACKEND_PROJECTION"


def test_torus_is_inspect_only_not_unavailable():
    """Gate 8 §36/§154: torus compiles; routed execution is what is absent."""
    stages = pr.capability_consequence("FAB-003")["stages"]
    assert stages["DECLARABLE"] == "YES"
    assert stages["DERIVABLE"] == "YES"
    assert stages["EXECUTABLE"] == "NO"


def test_rcu_is_a_future_contract_not_a_product_control():
    """Gate 5 correction / PF-D16: no RCU realization exists."""
    consequence = pr.capability_consequence("ROUTE-011")
    assert consequence["stages"]["DECLARABLE"] == "FUTURE_CONTRACT"
    assert consequence["wiring"] == "NOT_AVAILABLE"
    assert all(consequence["stages"][s] == "NO"
               for s in pr.STAGES if s != "DECLARABLE")


def test_unknown_capability_returns_none():
    assert pr.capability_consequence("NOPE-999") is None
    assert pr.capability_stage("NOPE-999", "DECLARABLE") is None


def test_every_consequence_carries_the_semantics_version():
    for row in pr.capability_rows():
        consequence = pr.capability_consequence(row["id"])
        assert consequence["capability_semantics_version"] == "cap-v1"


def test_envelopes_and_conditions_are_exposed():
    envelopes = pr.envelopes()
    assert "CAP-ENV-BOOKSIM-MESH-DOR-XY-V1" in envelopes
    assert envelopes["CAP-ENV-BOOKSIM-MESH-DOR-XY-V1"]["profile_id"] \
        == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert "COND-TOPOLOGY-MESH" in pr.conditions()


def test_no_surface_hardcodes_a_support_boolean():
    """A capability has stages and a wiring class, never a support flag."""
    consequence = pr.capability_consequence("SYS-001")
    assert "supported" not in consequence
    assert "wiring" in consequence
