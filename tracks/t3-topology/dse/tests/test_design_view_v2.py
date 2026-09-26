"""DesignViewV2 (Gate 5 D1, Gate 6, Gate 7 §51.1).

One projection serves authoring and Review. The tests below are the
contracts that make the planning claims checkable rather than aspirational:

  * the completeness invariant (Gate 7 §5);
  * no later-stage claims (Gate 7 §39/§40);
  * readiness is five states, not a boolean, and carries no evaluation
    fields (REV-D5);
  * findings are structured, with an explicit blocking flag (Gate 7 §29);
  * capability consequences come from the registry (Gate 7 §30);
  * Review freshness is CURRENT/STALE and presentation state never
    invalidates it (Gate 7 §33);
  * the scientific diff is over normalized science (Gate 8 §24).
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application import product_registry as registry  # noqa: E402
from veritx_dse.application.compile_intent import (  # noqa: E402
    build_preset_request,
)
from veritx_dse.application.design_view_v2 import (  # noqa: E402
    CONTRACT_VERSION,
    FINDING_CLASSES,
    OWNER_SECTION,
    READINESS,
    SECTIONS,
    build_design_view_v2,
)

HASH_A = "sha256:" + "a" * 64
HASH_B = "sha256:" + "b" * 64


def _doc(name: str = "mesh4_hbm") -> dict:
    request = build_preset_request(name)
    doc = request.to_dict()
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    return doc


def _view(doc: dict, presentation: str = "review", **kw) -> dict:
    return build_design_view_v2(
        doc, project_id="p1", presentation=presentation,
        draft_design_hash=kw.pop("draft_design_hash", HASH_A), **kw)


# ── shape ──────────────────────────────────────────────────────────────


def test_contract_version_and_presentation():
    view = _view(_doc())
    assert view["contract_version"] == CONTRACT_VERSION == 2
    assert view["presentation"] == "review"
    assert _view(_doc(), presentation="edit")["presentation"] == "edit"


def test_unknown_presentation_is_refused():
    with pytest.raises(ValueError):
        _view(_doc(), presentation="print")


def test_nine_sections_in_the_gate7_order():
    view = _view(_doc())
    assert [s["id"] for s in view["sections"]] == [sid for sid, _ in SECTIONS]
    assert len(view["sections"]) == 9


def test_draft_identity_and_semantics_version():
    view = _view(_doc())
    assert view["draft_identity"] == {"project_id": "p1",
                                      "draft_design_hash": HASH_A}
    assert view["capability_semantics_version"] == "cap-v1"
    assert view["registry_versions"]["capability_semantics_version"] == "cap-v1"


def test_parent_revision_ref_is_carried():
    view = _view(_doc(), parent_revision={"revision_id": "p1-r07",
                                          "display_name": "r07"})
    assert view["parent_revision_ref"] == {"revision_id": "p1-r07",
                                           "label": "r07"}


def test_every_entry_has_a_semantic_class():
    """Gate 7 §52: no naked values."""
    for section in _view(_doc())["sections"]:
        for entry in section["entries"]:
            assert entry["semantic_class"] == "DECLARED"
            assert entry["exposure_class"]
            assert "ownership" in entry


def test_entry_labels_come_from_the_registry():
    """§16: the product label, not the implementation name."""
    fabric = next(s for s in _view(_doc())["sections"] if s["id"] == "fabric")
    radix = next(e for e in fabric["entries"] if e["field"] == "NocConfig.radix")
    # Guided depth is the default disclosure, so the Guided label applies.
    assert radix["label"] == "Grid size"
    assert radix["disclosure_depth"] == "GUIDED"
    assert radix["ownership"]["scientific_name"] == "side_length"
    assert registry.product_label("NocConfig.radix", "EXPERT") \
        == "Mesh side length"


# ── readiness (REV-D5) ─────────────────────────────────────────────────


def test_readiness_is_one_of_five_states():
    assert _view(_doc())["readiness"] in READINESS


def test_readiness_is_not_a_boolean():
    view = _view(_doc())
    assert not isinstance(view["readiness"], bool)
    assert "ready" not in view


def test_readiness_carries_no_evaluation_fields():
    """REV-D5: design readiness is not evaluation preflight."""
    view = _view(_doc())
    for forbidden in ("backend", "backend_profile", "network_clock_hz",
                      "expected_evidence_tier", "execution_attempt",
                      "qualification"):
        assert forbidden not in view, forbidden
    blob = json.dumps(view)
    assert "network_clock_hz" not in blob
    assert "expected_evidence_tier" not in blob


def test_a_preset_design_is_limited_not_blocked():
    """mesh4 declares MoE; static MoE lowering is unavailable (WORK-002).

    The design is still valid and compilable — this is a downstream
    limitation, never an invalid design (Gate 7 §28).
    """
    view = _view(_doc("mesh4"))
    assert view["readiness"] == "CAPABILITY_LIMITED_BUT_COMPILABLE"
    assert not any(f["blocking"] for f in view["validation_findings"])


def test_malformed_intent_is_invalid_and_blocking():
    doc = _doc()
    doc["noc_config"]["radix"] = "not-a-number"
    view = _view(doc)
    assert view["readiness"] == "INVALID"
    blocking = [f for f in view["validation_findings"] if f["blocking"]]
    assert blocking and blocking[0]["class"] == "BLOCKING_ERROR"


def test_an_infeasible_cross_domain_join_is_preflight_blocked():
    """Gate 7 §27: a canonical join provable before compile.

    An address range must target a memory agent; pointing it at a compute
    tile group is infeasible, and the compiler proves it before compiling.
    """
    doc = _doc("mesh4_hbm")
    doc["address_map"]["ranges"][0]["target_agent_idx"] = 0
    view = _view(doc)
    assert view["readiness"] == "PREFLIGHT_BLOCKED"
    blocking = [f for f in view["validation_findings"] if f["blocking"]]
    assert blocking and blocking[0]["class"] == "BLOCKING_ERROR"


def test_a_valid_address_map_is_not_blocked():
    doc = _doc("mesh4_hbm")
    view = _view(doc)
    assert view["readiness"] != "PREFLIGHT_BLOCKED"
    assert not any(f["blocking"] for f in view["validation_findings"])


# ── findings (Gate 7 §29) ──────────────────────────────────────────────


def test_findings_are_structured_with_an_explicit_blocking_flag():
    doc = _doc()
    doc["noc_config"]["rcu_enabled"] = True
    view = _view(doc)
    for finding in view["validation_findings"]:
        assert finding["class"] in FINDING_CLASSES
        assert isinstance(finding["blocking"], bool)
        assert finding["owner_domain"]
        assert finding["code"]
        assert finding["message"]
        assert "affected" in finding
        assert isinstance(finding["remediation_owners"], list)


def test_torus_is_a_non_blocking_downstream_limitation():
    """Gate 7 §28: torus routing unavailability must not block topology
    compilation."""
    doc = _doc()
    doc["noc_config"]["topology_family"] = "torus"
    view = _view(doc)
    torus = [f for f in view["validation_findings"]
             if f["class"] == "DOWNSTREAM_LIMITATION"]
    assert torus and not torus[0]["blocking"]
    assert torus[0]["owner_domain"] == "FABRIC"


def test_removed_v4_values_are_migration_notices_not_errors():
    doc = _doc()
    doc["noc_config"]["rcu_enabled"] = True
    doc["noc_config"]["mcast_groups"] = 4
    view = _view(doc)
    notices = [f for f in view["validation_findings"]
               if f["class"] == "LEGACY_MIGRATION_NOTICE"]
    assert {n["code"] for n in notices} == {"REMOVED_V4"}
    assert not any(n["blocking"] for n in notices)


def test_removed_v4_fields_are_never_section_entries():
    """A removed-v4 field is not Design intent."""
    doc = _doc()
    doc["noc_config"]["rcu_enabled"] = True
    fields = {e["field"] for s in _view(doc)["sections"]
              for e in s["entries"]}
    assert "NocConfig.rcu_enabled" not in fields
    assert "NocConfig.mcast_groups" not in fields
    assert "RequirementV3.bandwidth_floor_gbps" not in fields


# ── capability consequences (Gate 7 §30) ───────────────────────────────


def test_consequences_come_from_the_registry():
    doc = _doc()
    doc["noc_config"]["topology_family"] = "torus"
    view = _view(doc)
    assert view["capability_consequences"]
    for consequence in view["capability_consequences"]:
        row = registry.capability_by_id()[consequence["capability_id"]]
        assert consequence["registry_version"] == "cap-v1"
        assert consequence["wiring"] == row["wiring"]
        assert set(consequence["stages"]) == set(registry.STAGES)


def test_concentration_above_one_is_a_consequence_not_an_error():
    doc = _doc()
    doc["noc_config"]["concentration"] = 2
    view = _view(doc)
    assert any(c["capability_id"] == "FAB-002"
               for c in view["capability_consequences"])
    assert not any(f["blocking"] for f in view["validation_findings"])


def test_multiple_clock_domains_are_a_declared_consequence():
    doc = _doc()
    doc["agents"] = [
        {"kind": "compute_tile", "count": 4, "data_width": 256,
         "addr_width": 64, "protocol": "AXI", "clock_domain": "d0",
         "power_domain": None},
        {"kind": "hbm_controller", "count": 1, "data_width": 256,
         "addr_width": 64, "protocol": "AXI", "clock_domain": "d1",
         "power_domain": None},
    ]
    view = _view(doc)
    assert any(c["capability_id"] == "SYS-003"
               for c in view["capability_consequences"])


def test_the_full_matrix_is_not_dumped():
    """Gate 7 §30: consequences caused by the choices, not 73 rows."""
    view = _view(_doc())
    assert len(view["capability_consequences"]) < 10


# ── completeness (Gate 7 §5) ───────────────────────────────────────────


def test_completeness_invariant_holds_for_every_preset():
    for name in ("mesh4", "mesh4_hbm", "mesh4_wide128"):
        completeness = _view(_doc(name))["completeness"]
        assert completeness["invariant_holds"], (name, completeness)
        assert completeness["unrepresented_active_fields"] == []


def test_completeness_law_is_stated():
    completeness = _view(_doc())["completeness"]
    assert "metadata-only" in completeness["law"]
    assert "represented" in completeness["law"]


def test_an_active_address_map_is_represented():
    """Gate 7 §22: preset-provided AddressMap science cannot be invisible."""
    doc = _doc("mesh4_hbm")
    assert doc["address_map"]["ranges"]
    view = _view(doc)
    memory = next(s for s in view["sections"]
                  if s["id"] == "memory_addressing")
    fields = {e["field"] for e in memory["entries"]}
    assert "AddressRange.base" in fields
    assert "AddressRange.size" in fields
    assert "AddressRange.target_agent_idx" in fields


def test_metadata_fields_are_excluded_from_scientific_completeness():
    completeness = _view(_doc())["completeness"]
    for path in completeness["active_scientific_fields"]:
        row = registry.exposure_row(path) or {}
        assert row.get("class") != "METADATA"
        assert row.get("src") != "METADATA"


def test_completeness_reports_non_active_fields_with_a_reason():
    completeness = _view(_doc("mesh4"))["completeness"]
    assert completeness["non_active_fields"]
    for row in completeness["non_active_fields"]:
        assert row["reason"] == "NO_ACTIVE_VALUE"


# ── no later-stage claims (Gate 7 §39/§40) ─────────────────────────────


def test_review_claims_no_later_stage_fact():
    view = _view(_doc())
    claims = view["later_stage_claims"]
    assert claims["certificate"] is None
    assert claims["qualification"] is None
    assert claims["measurements"] is None
    assert claims["requirement_verdicts"] is None


@pytest.mark.parametrize("forbidden", [
    "DEADLOCK_FREE", "ROUTE_LEGAL", "QUALIFIED", "SATISFIED",
    "ATTACHMENT_COMPLETE", "ROUTE_COMPLETE",
])
def test_forbidden_later_stage_vocabulary_never_appears_as_a_fact(forbidden):
    """Review describes the draft; these do not exist before compile.

    The registry legitimately names QUALIFIED as a *stage key*, so the
    assertion is over the facts Review states — its findings, its section
    values and its derived summaries — not over registry vocabulary.
    """
    view = _view(_doc())
    facts = {
        "findings": view["validation_findings"],
        "derived": view["derived_summaries"],
        "entries": [e["value"] for s in view["sections"] for e in s["entries"]],
        "claims": view["later_stage_claims"],
    }
    for where, payload in facts.items():
        assert forbidden not in json.dumps(payload), (where, forbidden)


def test_edit_presentation_carries_no_review_only_keys():
    view = _view(_doc(), presentation="edit")
    assert "scientific_diff" not in view
    assert "review_freshness" not in view
    assert "later_stage_claims" not in view


# ── freshness (Gate 7 §33) ─────────────────────────────────────────────


def test_matching_snapshot_is_current():
    view = _view(_doc(), review_snapshot_hash=HASH_A)
    assert view["review_freshness"] == "CURRENT"


def test_a_different_snapshot_is_stale():
    view = _view(_doc(), review_snapshot_hash=HASH_B)
    assert view["review_freshness"] == "STALE"


def test_snapshot_is_bound_by_identity_not_a_second_hash():
    """Gate 7 §53: no separate Review hash."""
    snapshot = _view(_doc(), review_snapshot_hash=HASH_A)["review_snapshot"]
    assert snapshot["bound_by"] == [
        "project_id", "draft_design_hash", "capability_semantics_version"]


def test_a_canonical_change_makes_review_stale():
    """The precondition for the STALE_REVIEW compile refusal."""
    parent = _doc()
    changed = copy.deepcopy(parent)
    changed["noc_config"]["link_width"] = 128
    diff = _view(changed, parent_doc=parent)["scientific_diff"]
    assert [d["field"] for d in diff] == ["NocConfig.link_width"]


def test_presentation_state_is_not_part_of_the_projection():
    """Expanding a disclosure is frontend state; it cannot make Review
    stale because it is not in the document or the view at all."""
    view = _view(_doc())
    blob = json.dumps(view)
    for token in ("expanded", "collapsed", "disclosure_state", "advanced_open"):
        assert token not in blob


# ── scientific diff (Gate 8 §24) ───────────────────────────────────────


def test_no_parent_means_no_diff():
    assert _view(_doc())["scientific_diff"] == []


def test_alias_respelling_is_not_a_scientific_diff():
    """§15/§24: raw spelling is not semantic identity."""
    parent = _doc()
    parent["noc_config"]["arbitration"] = "islip"
    respelled = copy.deepcopy(parent)
    respelled["noc_config"]["arbitration"] = " iSLIP "
    assert _view(respelled, parent_doc=parent)["scientific_diff"] == []


def test_an_unset_field_is_a_different_request_from_a_chosen_one():
    """``None`` is a declaration state, not a spelling of iSLIP."""
    parent = _doc()
    parent["noc_config"]["arbitration"] = None
    chosen = copy.deepcopy(parent)
    chosen["noc_config"]["arbitration"] = "islip"
    diff = _view(chosen, parent_doc=parent)["scientific_diff"]
    assert [d["field"] for d in diff] == ["NocConfig.arbitration"]


def test_diff_reports_added_and_changed():
    parent = _doc("mesh4")
    changed = copy.deepcopy(parent)
    changed["noc_config"]["link_width"] = 128   # unset -> set
    changed["workload"]["tp"] = 2               # 1 -> 2
    diff = {d["field"]: d
            for d in _view(changed, parent_doc=parent)["scientific_diff"]}
    assert diff["NocConfig.link_width"]["kind"] == "added"
    assert diff["NocConfig.link_width"]["before"] is None
    assert diff["WorkloadV3.tp"]["kind"] == "changed"
    assert diff["WorkloadV3.tp"]["before"] == 1
    assert diff["WorkloadV3.tp"]["after"] == 2


def test_diff_ignores_metadata():
    parent = _doc()
    changed = copy.deepcopy(parent)
    changed["workload"]["model_name"] = "renamed"
    diff = _view(changed, parent_doc=parent)["scientific_diff"]
    assert all(d["field"] != "WorkloadV3.model_name" for d in diff)


# ── registry mismatch (Gate 7 §31) ─────────────────────────────────────


def test_a_stale_registry_withholds_claims():
    view = build_design_view_v2(
        _doc(), project_id="p1", presentation="review",
        draft_design_hash=HASH_A,
        expected_capability_semantics_version="cap-v2")
    assert view["sections"] == []
    assert view["capability_consequences"] == []
    assert view["readiness"] == "PREFLIGHT_BLOCKED"
    assert view["validation_findings"][0]["code"] \
        == "CAPABILITY_REGISTRY_MISMATCH"
    assert view["completeness"]["invariant_holds"] is False


# ── derived summaries (Gate 8 §42) ─────────────────────────────────────


def test_derived_summaries_come_from_the_compiler():
    view = _view(_doc("mesh4"))
    by_id = {d["id"]: d for d in view["derived_summaries"]}
    assert by_id["routers"]["value"] == 4
    assert by_id["channels"]["value"] == 8
    for summary in view["derived_summaries"]:
        assert summary["kind"] == "PRE_COMPILE_DERIVED_SUMMARY"
        assert summary["semantic_class"] == "DERIVED_PREVIEW"


def test_no_derived_summary_when_the_design_does_not_derive():
    doc = _doc()
    doc["noc_config"]["radix"] = "not-a-number"
    assert _view(doc)["derived_summaries"] == []


# ── section counters ───────────────────────────────────────────────────


def test_section_counters_are_present_and_integral():
    for section in _view(_doc())["sections"]:
        assert isinstance(section["advanced_active_count"], int)
        assert isinstance(section["blocking_count"], int)
        assert isinstance(section["limitation_count"], int)


def test_section_owner_mapping_covers_every_declared_domain():
    declared = {row.get("owner") for row in registry.exposure_fields().values()}
    for owner in declared:
        if owner in (None, "-"):
            continue
        assert owner in OWNER_SECTION, owner


def test_memory_addressing_is_review_only_until_pf_d1():
    """Authoring does not render AddressMap; Review shows it read-only."""
    doc = _doc("mesh4_hbm")
    review_fields = {e["field"] for s in _view(doc, presentation="review")["sections"]
                     for e in s["entries"]}
    edit_fields = {e["field"] for s in _view(doc, presentation="edit")["sections"]
                   for e in s["entries"]}
    assert "AddressRange.base" in review_fields
    assert "AddressRange.base" not in edit_fields
