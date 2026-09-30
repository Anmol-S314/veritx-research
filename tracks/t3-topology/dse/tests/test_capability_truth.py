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

def test_there_is_no_second_shape_table():
    assert not hasattr(ct, "_PROBE_SHAPE")
    assert not hasattr(ct, "GATED_FAMILIES")
    for kind, intent in ct.PROBE_INTENTS.items():
        assert ct._probe_endpoints(intent) >= 1, kind

def test_probe_endpoint_law_follows_the_declared_structure():
    from veritx_dse.model.topology_intent import FatTreeIntent, MeshIntent
    assert ct._probe_endpoints(MeshIntent(side_length=4,
                                          concentration=1)) == 16
    assert ct._probe_endpoints(FatTreeIntent(switch_radix=4,
                                             level_count=2)) == 16

def test_no_regex_stage_recovery_for_v4():
    """The regex fallback is confined to the HISTORICAL v2 path, which has no
    structured record to read."""
    src = (DSE / "veritx_dse/application/capability_truth.py").read_text()
    idx = src.index("re.search")
    window = src[max(0, idx - 500):idx]
    assert "schema_version" in window and "== 2" in window, (
        "the regex stage fallback must be gated to the v2 path")

def test_stages_come_from_the_structured_derivation():
    """Torus materializes and routes (DOR_TORUS_XY) but its certificate is
    INVALID on DEADLOCK_FREE — the dateline-partition proof method is the
    open bridge. The INVALID path drops the staged record, so derivation
    probes the canonical seams directly (same intent, same functions)."""
    t = ct.derive_family_stages("torus")
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["ROUTABLE"] == "YES"
    assert "DEADLOCK_FREE" in t.refusal

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
    assert execution_handler_for(synthetic) is not None

def test_projection_and_execution_and_qualification_are_independent():
    """The stage questions stay independent for a family with a certified
    profile: mesh derives everywhere, torus materializes and routes but has
    no COMPILED bundle (deadlock-proof pending) so end-to-end projection is
    unit-level only, and concentrated_mesh progresses through all three
    (Phase 2 acceptance), each stage still carrying its own authority
    rather than one observation reported three times."""
    t = ct.derive_family_stages("torus")
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["ROUTABLE"] == "YES"
    assert t.stages["PROJECTABLE"] == "NO"
    assert t.stages["EXECUTABLE"] == "NO"
    assert t.authority["PROJECTABLE"] != t.authority["EXECUTABLE"]
    tc = ct.derive_family_stages("concentrated_mesh")
    assert tc.stages["MATERIALIZABLE"] == "YES"
    assert tc.stages["PROJECTABLE"] == "YES"
    assert tc.stages["EXECUTABLE"] == "YES"
    assert tc.stages["QUALIFIED"] == "YES"

def test_projectable_is_proven_by_the_real_preparer_not_by_selection():
    """mesh's PROJECTABLE authority names the preparer and the prepared id,
    not merely the selected profile."""
    t = ct.derive_family_stages("mesh")
    assert t.stages["PROJECTABLE"] == "YES"
    assert "prepare_booksim_input" in t.authority["PROJECTABLE"]

def test_the_two_sealed_profiles_are_qualified_with_resolvable_evidence():
    for profile_id in ("CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
                       "CERTIFIED_BOOKSIM_ANYNET_V1"):
        record = QUALIFICATION[profile_id]
        assert record.is_qualified
        assert record.scope
        assert callable(record.qualifier_callable())
        assert record.unresolved_evidence() == ()

def test_a_qualification_without_resolvable_evidence_is_refused():
    with pytest.raises(QualificationRegistryError, match="durable evidence"):
        QualificationRecord(profile_id="X", state="QUALIFIED",
                            projection_semantics_version="s",
                            lowerer_version=None, qualifier="m:f",
                            evidence_paths=(), scope="none")
    with pytest.raises(QualificationRegistryError, match="module:function"):
        QualificationRecord(profile_id="X", state="QUALIFIED",
                            projection_semantics_version="s",
                            lowerer_version=None, qualifier="just prose",
                            evidence_paths=("README.md",), scope="none")

def test_prose_cannot_make_a_profile_qualified():
    """Previously `evidence=("trust me",)` satisfied the constructor, which
    is exactly the hole this registry exists to close. The constructor is
    STRUCTURAL (a qualifier and at least one evidence path are required); the
    RESOLUTION of both is enforced by `validate_registry()` and by every
    `evaluate_qualification()` call."""
    from veritx_dse.application.booksim_qualification_registry import (
        evaluate_qualification,
    )
    prose = QualificationRecord(
        profile_id="X", state="QUALIFIED",
        projection_semantics_version="s", lowerer_version=None,
        qualifier="trust:me", evidence_paths=("trust me",), scope="none")
    assert prose.unresolved_evidence() == ("trust me",)
    ok, why = evaluate_qualification(
        type("P", (), {"profile_id": "X", "semantics_version": "s",
                       "lowerer_version": None})(), object())
    assert ok is False

def test_an_unregistered_profile_is_not_qualified_by_omission():
    assert qualification_of("NO_SUCH_PROFILE").state == "NOT_QUALIFIED"

def test_execution_handlers_resolve_to_real_implementations():
    """A registry entry cannot be a typo that silently means 'executable'."""
    for profile_id in EXECUTION_HANDLERS:
        assert callable(resolve_handler(EXECUTION_HANDLERS[profile_id]))
    with pytest.raises(QualificationRegistryError):
        resolve_handler("veritx_dse.backend.booksim_execution:no_such_fn")

def test_product_wired_is_independent_of_authorability():
    """torus is AUTHORABLE and MATERIALIZABLE but NOT product-wired: it
    stops at VERIFIABLE, so no executable preset can exist for it."""
    t = ct.derive_family_stages("torus")
    assert t.stages["AUTHORABLE"] == "YES"
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["PRODUCT_WIRED"] == "NO"

def test_every_executable_family_is_now_product_wired():
    """The typed-topology presets surface every executable family."""
    for kind in ("mesh", "concentrated_mesh", "flatfly", "explicit",
                 "gec_express"):
        t = ct.derive_family_stages(kind)
        assert t.stages["EXECUTABLE"] == "YES", kind
        assert t.stages["QUALIFIED"] == "YES", kind
        assert t.stages["PRODUCT_WIRED"] == "YES", (
            kind, t.authority["PRODUCT_WIRED"])

def test_gec_modes_are_authorable_and_stop_at_materialization():
    """The central law: the intent can express the physical design even when
    no materializer exists. Fat-tree LEFT this set when it gained a
    materializer — a graph-backed family executes through the generic seam."""
    for kind in ("gec_mesh", "gec_multidrop", "gec_hybrid"):
        t = ct.derive_family_stages(kind)
        assert t.stages["AUTHORABLE"] == "YES", kind
        assert t.stages["MATERIALIZABLE"] == "NO", kind
        assert t.stopped_at_stage == "TOPOLOGY", kind


def test_fattree_now_materializes():
    t = ct.derive_family_stages("fattree")
    assert t.stages["AUTHORABLE"] == "YES"
    assert t.stages["MATERIALIZABLE"] == "YES"

def test_gec_express_materializes_as_pure_p2p():
    """GEC-Express split: point-to-point express channels materialize and
    route via ANYNET_MIN_HOPS (no new route class needed); MULTIDROP/
    HYBRID/MESH still refuse rather than flatten."""
    t = ct.derive_family_stages("gec_express")
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["ROUTABLE"] == "YES"
    assert t.stages["VERIFIABLE"] == "YES"

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
    # Was {mesh, concentrated_mesh, explicit, gec_express, flatfly}. The
    # graph-backed families (fattree, flattened_butterfly, dragonfly,
    # qtree, tree4, fat_tree) joined once they took the generic
    # materialize-IR seam; they need no native BookSim profile to EXECUTE.
    assert fully == {"mesh", "concentrated_mesh", "explicit", "gec_express",
                     "flatfly", "fattree", "fat_tree", "flattened_butterfly",
                     "dragonfly", "qtree", "tree4"}

def test_qualification_is_NOT_bound_to_request_generation():
    """The qualified interface is the CANONICAL ARTIFACTS downstream of
    request generation. The qualifiers never inspect whether the root request
    began as v2, v3 or v4, and they must not: a v2, a v3 and a v4 request that
    lower to the same canonical parents produce the same prepared bytes and
    are therefore the same qualification question."""
    from veritx_dse.application.booksim_qualification_registry import (
        QUALIFICATION,
    )
    for record in QUALIFICATION.values():
        assert not hasattr(record, "semantics_version"), (
            "the compiler-semantics-version field was the WRONG boundary")
        assert not hasattr(record, "compiler_semantics_version")
    from veritx_dse.backend.booksim_projection import (
        ANYNET_PROFILE, MESH_DOR_PROFILE,
    )
    assert (QUALIFICATION[MESH_DOR_PROFILE.profile_id]
            .projection_semantics_version == MESH_DOR_PROFILE.semantics_version)
    assert (QUALIFICATION[ANYNET_PROFILE.profile_id]
            .projection_semantics_version
            == ANYNET_PROFILE.semantics_version)

def test_a_changed_projection_semantics_version_is_not_qualified():
    """Changing a profile's semantics string invalidates its qualification
    automatically — the exact-match check is what makes that true."""
    import dataclasses
    from veritx_dse.application.booksim_qualification_registry import (
        QUALIFICATION, evaluate_qualification,
    )
    from veritx_dse.backend.booksim_projection import MESH_DOR_PROFILE
    changed = dataclasses.replace(MESH_DOR_PROFILE,
                                  semantics_version="booksim2-fork+NEW+v3")
    ok, why = evaluate_qualification(changed, object())
    assert ok is False
    assert "does not carry across a semantics change" in why

def test_a_nonexistent_qualifier_is_refused():
    from veritx_dse.application.booksim_qualification_registry import (
        QualificationRegistryError, resolve_handler,
    )
    with pytest.raises(QualificationRegistryError, match="not 'module"):
        resolve_handler("noseparator")
    with pytest.raises(QualificationRegistryError, match="does not exist"):
        resolve_handler("veritx_dse.backend.booksim_projection:no_such_fn")
    with pytest.raises(QualificationRegistryError, match="does not import"):
        resolve_handler("no.such.module:fn")

def test_a_nonexistent_evidence_path_is_refused():
    from veritx_dse.application.booksim_qualification_registry import (
        QualificationRecord,
    )
    record = QualificationRecord(
        profile_id="X", state="QUALIFIED", projection_semantics_version="s",
        lowerer_version=None,
        qualifier="veritx_dse.backend.booksim_projection:qualify_anynet_min_hops",
        evidence_paths=("docs/DOES-NOT-EXIST.md",), scope="none")
    assert record.unresolved_evidence() == ("docs/DOES-NOT-EXIST.md",)
    from veritx_dse.application.booksim_qualification_registry import (
        QUALIFICATION, evaluate_qualification,
    )
    QUALIFICATION["X"] = record
    try:
        ok, why = evaluate_qualification(
            type("P", (), {"profile_id": "X", "semantics_version": "s",
                           "lowerer_version": None})(), object())
        assert ok is False and "does not exist" in why
    finally:
        del QUALIFICATION["X"]

def test_the_registry_validates_its_own_bindings_at_import():
    from veritx_dse.application.booksim_qualification_registry import (
        validate_registry,
    )
    validate_registry()

def test_a_registered_but_unresolvable_handler_makes_executable_NO(
        monkeypatch):
    """A typo in the registry must not read as availability until a test
    happens to catch it: the LIVE derivation resolves the symbol."""
    monkeypatch.setitem(ct.EXECUTION_HANDLERS_VIEW,
                        "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
                        "veritx_dse.backend.booksim_execution:no_such_symbol")
    t = ct.derive_family_stages("mesh")
    assert t.stages["EXECUTABLE"] == "NO"
    assert "does not resolve" in t.authority["EXECUTABLE"]

def test_an_unimportable_handler_module_makes_executable_NO(monkeypatch):
    monkeypatch.setitem(ct.EXECUTION_HANDLERS_VIEW,
                        "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
                        "no.such.module:fn")
    t = ct.derive_family_stages("mesh")
    assert t.stages["EXECUTABLE"] == "NO"
    assert "does not resolve" in t.authority["EXECUTABLE"]

def test_resolve_execution_handler_reports_the_reason():
    from veritx_dse.application.booksim_qualification_registry import (
        resolve_execution_handler,
    )
    handler, err = resolve_execution_handler("NOT_A_PROFILE")
    assert handler is None and err and "no execution implementation" in err
    handler, err = resolve_execution_handler("CERTIFIED_BOOKSIM_ANYNET_V1")
    assert callable(handler) and err is None

def test_product_wired_uses_the_normalized_intent_not_a_family_string():
    """All four GEC modes share `.kind == "gec"`, so a family-string match
    would mark every mode wired from one generic GEC preset. The derivation
    compares normalized capability labels instead."""
    src = (DSE / "veritx_dse/application/capability_truth.py").read_text()
    body = src[src.index("def _product_wired("):
               src.index("def derive_family_stages(")]
    assert "capability_family_label" in body
    assert "fabric_intent_view" in body
    assert "noc_config" not in body, (
        "PRODUCT_WIRED must not read the legacy topology_family field")
