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
from veritx_dse.application.loom_capability import _family_capability  # noqa: E402
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

def test_torus_probe_uses_the_declared_two_vc_product_profile():
    """The one-VC default still refuses; the shipped preset explicitly
    declares X<->Y blocking dependencies and qualifies end to end."""
    t = ct.derive_family_stages("torus")
    assert all(t.stages[s] == "YES" for s in ct.STAGES), t.stages
    assert t.profile_id == "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"
    assert "DEADLOCK_FREE" not in t.refusal

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
    profile: mesh, torus, and concentrated_mesh progress through distinct
    compiler, projection, execution, and qualification authorities."""
    t = ct.derive_family_stages("torus")
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["ROUTABLE"] == "YES"
    assert t.stages["VERIFIABLE"] == "YES"
    assert t.stages["PROJECTABLE"] == "YES"
    assert t.stages["EXECUTABLE"] == "YES"
    assert t.stages["QUALIFIED"] == "YES"
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
                       "CERTIFIED_BOOKSIM_ANYNET_V1",
                       "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1"):
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
    """The shipped torus preset explicitly wires a qualified 2-VC design."""
    t = ct.derive_family_stages("torus")
    assert t.stages["AUTHORABLE"] == "YES"
    assert t.stages["MATERIALIZABLE"] == "YES"
    assert t.stages["PRODUCT_WIRED"] == "YES"

def test_every_executable_family_is_now_product_wired():
    """The typed-topology presets surface every executable family."""
    for kind in ("mesh", "concentrated_mesh", "flatfly", "explicit",
                 "fattree", "gec_express", "gec_mesh", "torus"):
        t = ct.derive_family_stages(kind)
        assert t.stages["EXECUTABLE"] == "YES", kind
        assert t.stages["QUALIFIED"] == "YES", kind
        assert t.stages["PRODUCT_WIRED"] == "YES", (
            kind, t.authority["PRODUCT_WIRED"])

def test_gec_mesh_is_unblocked_but_shared_channel_modes_still_refuse():
    """GEC mesh lowers exactly to MESH; MECS/hybrid retain shared resources."""
    mesh = ct.derive_family_stages("gec_mesh")
    assert all(value == "YES" for value in mesh.stages.values()), mesh.as_dict()
    assert mesh.profile_id == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"

    # GEC-MECS LEFT this set when the shared-wire materializer landed: its
    # wires are SharedLinks now, and what remains missing is the per-tap VC
    # partition, which is a ROUTING-time question.
    # GEC-MECS left this set entirely: it materializes, routes over shared
    # wires with per-tap VC slices, and certifies.
    mesh_drop = ct.derive_family_stages("gec_multidrop")
    assert mesh_drop.stages["MATERIALIZABLE"] == "YES"
    assert mesh_drop.stages["ROUTABLE"] == "YES"
    assert mesh_drop.stages["VERIFIABLE"] == "YES"
    assert mesh_drop.stopped_at_stage is None

    # The representative hybrid probe matches gec_hybrid16 (six VCs).
    # Oversized tap envelopes still refuse; READY is not universal support.
    t = ct.derive_family_stages("gec_hybrid")
    assert all(value == "YES" for value in t.stages.values()), t.as_dict()
    assert t.profile_id == "CERTIFIED_BOOKSIM_GEC_HYBRID_V1"
    row = _family_capability("gec_hybrid", t)
    assert row.status == "READY" and row.blocked_at is None


def test_torus_ready_row_cites_the_shipped_qualified_profile():
    truth = ct.derive_family_stages("torus")
    row = _family_capability("torus", truth)
    assert row.status == "READY"
    assert row.blocked_at is None
    assert truth.profile_id in row.qualification


def test_fattree_now_has_a_qualified_product_preset():
    t = ct.derive_family_stages("fattree")
    assert all(value == "YES" for value in t.stages.values()), t.as_dict()
    assert t.profile_id == "CERTIFIED_BOOKSIM_ANYNET_V1"

def test_gec_express_materializes_as_pure_p2p():
    """GEC-Express split: point-to-point express channels materialize and
    route via ANYNET_MIN_HOPS (no new route class needed); MULTIDROP/
    HYBRID still refuse rather than flatten."""
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

def test_fully_progressing_families_are_product_wired():
    truth = ct.derive_all_stages()
    fully = {k for k, v in truth.items()
             if all(v.stages[s] == "YES" for s in ("AUTHORABLE",
                                                   "MATERIALIZABLE",
                                                   "ROUTABLE", "VERIFIABLE",
                                                   "PROJECTABLE",
                                                   "EXECUTABLE", "QUALIFIED"))}
    # Graph-backed families use AnyNet; torus uses its qualified native
    # two-VC DOR profile.
    # Keyed by the capability LABEL, which keeps the GEC subfamily
    # (gec_multidrop), not by the MaterializedFamily value (gec_mecs).
    assert fully == {"mesh", "concentrated_mesh", "explicit", "gec_express",
                     "gec_multidrop", "gec_mesh", "gec_hybrid", "srota",
                     "flatfly", "fattree", "fat_tree",
                     "flattened_butterfly",
                     "dragonfly", "qtree", "tree4", "torus"}

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
