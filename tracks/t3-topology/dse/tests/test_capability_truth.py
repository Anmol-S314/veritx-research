"""Capability truth — derived, not declared (PHASE A + B.1 §18–§20, §28).

The load-bearing properties:

  * probe coverage is DERIVED from the topology-intent registry, so a newly
    registered kind cannot be silently ungated;
  * the probe's SHAPE lives with its probe (no second shape table);
  * stage recovery for the current generation is STRUCTURED, never parsed out
    of an error string;
  * PROJECTABLE / EXECUTABLE / QUALIFIED are three SEPARATE authorities, so
    selector success alone cannot make QUALIFIED YES.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application import capability_truth as ct  # noqa: E402
from veritx_dse.application.booksim_qualification_registry import (  # noqa: E402
    EXECUTION_HANDLERS, QUALIFICATION, QualificationRecord,
    QualificationRegistryError, execution_handler_for, qualification_of,
    resolve_handler,
)
from veritx_dse.model.topology_intent import (  # noqa: E402
    AUTHORABLE_INTENT_KINDS, GecMode,
)


# ══ §18.1 coverage is derived from the intent registry ════════════════

def test_every_registered_topology_kind_has_a_probe():
    """A registered authorable kind with no probe would be silently absent
    from capability truth — the exact failure the old hardcoded family list
    had (it came from the legacy enum and could not see FlatFly or FatTree)."""
    assert ct.missing_probe_kinds() == ()


def test_flatfly_and_fattree_appear_automatically():
    assert "flatfly" in ct.GATED_KINDS
    assert "fattree" in ct.GATED_KINDS


def test_every_gec_subfamily_appears_automatically():
    for mode in GecMode:
        assert f"gec_{mode.value}" in ct.GATED_KINDS


def test_gated_kinds_cover_every_registered_kind():
    covered = {ct.PROBE_INTENTS[k].kind for k in ct.GATED_KINDS}
    assert set(AUTHORABLE_INTENT_KINDS) <= covered


def test_a_missing_probe_is_detected(monkeypatch):
    """The gate must FAIL, not silently omit, when coverage is incomplete."""
    monkeypatch.setattr(ct, "PROBE_INTENTS",
                        {k: v for k, v in ct.PROBE_INTENTS.items()
                         if k != "flatfly"})
    assert "flatfly" in ct.missing_probe_kinds()


# ══ §18.2 the probe's shape lives with the probe ══════════════════════

def test_there_is_no_second_shape_table():
    assert not hasattr(ct, "_PROBE_SHAPE")
    assert not hasattr(ct, "GATED_FAMILIES")
    # The probe SIZE is derived from the intent it declares.
    for kind, intent in ct.PROBE_INTENTS.items():
        assert ct._probe_endpoints(intent) >= 1, kind


def test_probe_endpoint_law_follows_the_declared_structure():
    from veritx_dse.model.topology_intent import FatTreeIntent, MeshIntent
    assert ct._probe_endpoints(MeshIntent(side_length=4,
                                          concentration=1)) == 16
    assert ct._probe_endpoints(FatTreeIntent(switch_radix=4,
                                             level_count=2)) == 16


# ══ §18.3 structured stages for the current generation ════════════════

def test_no_regex_stage_recovery_for_v4():
    """The regex fallback is confined to the HISTORICAL v2 path, which has no
    structured record to read."""
    src = (DSE / "veritx_dse/application/capability_truth.py").read_text()
    idx = src.index("re.search")
    window = src[max(0, idx - 500):idx]
    assert "schema_version" in window and "== 2" in window, (
        "the regex stage fallback must be gated to the v2 path")


def test_stages_come_from_the_structured_derivation():
    """Torus materializes but stops at ROUTING — a fact only the structured
    `produced_stages`/`stopped_at_stage` can report."""
    t = ct.derive_family_stages("torus")
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["ROUTABLE"] == "NO"
    assert t.stopped_at_stage == "ROUTING"


# ══ §19 three separate authorities ════════════════════════════════════

def test_selector_success_alone_cannot_make_qualified_yes(monkeypatch):
    """A synthetic profile that selects and prepares perfectly but has no
    qualification record must stay NOT_QUALIFIED."""
    synthetic = "SYNTHETIC_PROFILE_THAT_NOBODY_QUALIFIED"
    monkeypatch.setitem(EXECUTION_HANDLERS, synthetic,
                        "veritx_dse.backend.booksim_execution:"
                        "execute_prepared_booksim")
    record = qualification_of(synthetic)
    assert record.state == "NOT_QUALIFIED"
    assert not record.is_qualified
    # ...while its EXECUTABLE authority is genuinely YES: the two questions
    # are independent.
    assert execution_handler_for(synthetic) is not None


def test_projection_and_execution_and_qualification_are_independent():
    """concentrated_mesh: the compiler derives the full bundle, but no
    certified profile exists, so all three are NO for three DIFFERENT
    reasons — not one observation reported three times."""
    t = ct.derive_family_stages("concentrated_mesh")
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["PROJECTABLE"] == "NO"
    assert t.stages["EXECUTABLE"] == "NO"
    assert t.stages["QUALIFIED"] == "NO"
    assert t.authority["PROJECTABLE"] != t.authority["EXECUTABLE"]


def test_projectable_is_proven_by_the_real_preparer_not_by_selection():
    """mesh's PROJECTABLE authority names the preparer and the prepared id,
    not merely the selected profile."""
    t = ct.derive_family_stages("mesh")
    assert t.stages["PROJECTABLE"] == "YES"
    assert "prepare_booksim_input" in t.authority["PROJECTABLE"]


def test_the_two_sealed_profiles_are_qualified_with_named_evidence():
    for profile_id in ("CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
                       "CERTIFIED_BOOKSIM_ANYNET_V1"):
        record = QUALIFICATION[profile_id]
        assert record.is_qualified
        assert record.evidence
        assert record.scope


def test_a_qualification_without_evidence_is_refused():
    with pytest.raises(QualificationRegistryError, match="no qualification"):
        QualificationRecord(profile_id="X", state="QUALIFIED",
                            semantics_version=1, evidence=(), scope="none")


def test_an_unregistered_profile_is_not_qualified_by_omission():
    assert qualification_of("NO_SUCH_PROFILE").state == "NOT_QUALIFIED"


def test_execution_handlers_resolve_to_real_implementations():
    """A registry entry cannot be a typo that silently means 'executable'."""
    for profile_id in EXECUTION_HANDLERS:
        assert callable(resolve_handler(EXECUTION_HANDLERS[profile_id]))
    with pytest.raises(QualificationRegistryError):
        resolve_handler("veritx_dse.backend.booksim_execution:no_such_fn")


# ══ §20 PRODUCT_WIRED is not schema authorability ═════════════════════

def test_product_wired_is_independent_of_authorability():
    """flatfly is AUTHORABLE and MATERIALIZABLE but NOT product-wired."""
    t = ct.derive_family_stages("flatfly")
    assert t.stages["AUTHORABLE"] == "YES"
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["PRODUCT_WIRED"] == "NO"


# ══ §22 the derived staged truth ══════════════════════════════════════

def test_gec_and_fattree_are_authorable_and_stop_at_materialization():
    """The central law: the intent can express the physical design even when
    no materializer exists."""
    for kind in ("gec_mesh", "gec_express", "gec_multidrop", "gec_hybrid",
                 "fattree"):
        t = ct.derive_family_stages(kind)
        assert t.stages["AUTHORABLE"] == "YES", kind
        assert t.stages["MATERIALIZABLE"] == "NO", kind
        assert t.stopped_at_stage == "TOPOLOGY", kind


def test_derive_all_stages_covers_every_gated_kind():
    truth = ct.derive_all_stages()
    assert set(truth) == set(ct.GATED_KINDS)
    for kind, row in truth.items():
        assert row.stages["AUTHORABLE"] == "YES", kind
        assert row.family == kind


def test_mesh_is_the_only_fully_progressing_family():
    truth = ct.derive_all_stages()
    fully = {k for k, v in truth.items()
             if all(v.stages[s] == "YES" for s in ("AUTHORABLE",
                                                   "MATERIALIZABLE",
                                                   "ROUTABLE", "VERIFIABLE",
                                                   "PROJECTABLE",
                                                   "EXECUTABLE", "QUALIFIED"))}
    assert fully == {"mesh", "explicit"}
