"""CompileIntent / product preset boundary tests.

Compile-only product input: presets, strict overrides, intent identity, and
the seam reaching Slice-24 candidate generation and Slice-23 compilation.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import sys

import pytest

from veritx_dse.application import compile_intent as ci
from veritx_dse.application.compile_intent import (
    COMPUTED_IDENTITY_FIELDS, RESERVED_OVERRIDE_PATHS, CompileIntent,
    CompileIntentError, CompilePreset, build_preset_request,
    derive_compile_request, get_preset, preset_names,
)
from veritx_dse.compiler.canonical import (
    CanonicalCompileError, CompileStage, compile_deterministic_candidate,
)
from veritx_dse.compiler.candidate_policy import (
    CandidatePolicy, generate_baseline_candidate,
)
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, DepKind,
)

GOLDEN_MESH4_RESOLVED = (
    "c05d4c19bf3bdd955da97f33fd665d2325441966906b1bb23290d0dcc3296fa1")
GOLDEN_WIDE128_RESOLVED = (
    "47d8cb6c386b22cbc6b4bbf152f40d3c1c72dd1900a48d099afd2bda8fbc9c7f")
# Design hashes are identity-only movers under compiler semantics v2; the
# old semantics-v1 values were 306dc86a… (mesh4), c5bac8e5… (hbm),
# 02ad4c72… (wide128) and remain reproducible via
# replace(request, compiler_semantics_version=1).design_hash().
GOLDEN_MESH4_DESIGN = (
    "f13b8d7d61776d863f3f554c32f7d8dab2a622dbf62bdfe697afc6b95ee4547f")
GOLDEN_HBM_DESIGN = (
    "0fe2e62ae06c67c5dc781eafd69ff9138f505c62a16f29ad5ea16494abc2bc13")
GOLDEN_WIDE128_DESIGN = (
    "d94dde8d87bdac52316bcfd8c2f210a2598a564045f7e60f3da92650da2968b3")
# Hardware children: MUST NOT move (execution semantics unchanged).
GOLDEN_HBM_ADDRESS_DECODE = (
    "b498a6f0a7dfd3ca3261998f3239bb4178150f7fa6f4ff4c69184b853051ebef")
GOLDEN_HBM_FABRIC = (
    "264a857c1978fa44c0f17f150c929a2aff18691189405e5b7754c7fef42a79f1")
# ResolvedFabric moves only because its design_hash parent moved.
GOLDEN_HBM_RESOLVED = (
    "2bf76043e6c653147842b341a04d2600b6201a13ea10d7fe2f0b3e18fad099e6")
GOLDEN_DOR_POLICY = (
    "c451979bf68ac87535cf117adc1b9ff98cb45ea6a50ff42d22f7e312f68a2426")
PRESOLVED = {"mesh4": GOLDEN_MESH4_RESOLVED,
             "mesh4_hbm": GOLDEN_HBM_RESOLVED,
             "mesh4_wide128": GOLDEN_WIDE128_RESOLVED}


def _intent(preset: str, overrides=(), *,
            intent_name: str = "product") -> CompileIntent:
    return CompileIntent(
        name=intent_name, fabric_preset=preset,
        fabric_overrides=tuple(overrides),
        candidate_policy=CandidatePolicy.BASELINE_DETERMINISTIC_V2)


def _compile(intent: CompileIntent):
    """TEST-ONLY integration: intent -> request -> plan -> compiled."""
    design = derive_compile_request(intent)
    plan = generate_baseline_candidate(design=design)
    return compile_deterministic_candidate(
        design=design, inventory=plan.inventory, mapping=plan.mapping,
        routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
        settings=plan.compile_settings)


# ── preset registry ───────────────────────────────────────────────────────

def test_registry_is_exactly_the_three_product_presets():
    assert preset_names() == ("mesh4", "mesh4_hbm", "mesh4_wide128")
    preset = get_preset("mesh4")
    assert isinstance(preset, CompilePreset)
    assert {f.name for f in dataclasses.fields(CompilePreset)} == {
        "name", "description"}
    for forbidden in ("endpoint_count", "topology_hash", "mapping_hash",
                      "fabric_hash"):
        assert not hasattr(preset, forbidden)


def test_unknown_preset_is_a_product_boundary_error():
    with pytest.raises(CompileIntentError, match="unknown product preset"):
        get_preset("not_a_preset")
    with pytest.raises(CompileIntentError):
        _intent("not_a_preset")
    with pytest.raises(CompileIntentError, match="string"):
        get_preset(7)


# ── preset semantics ──────────────────────────────────────────────────────

def test_mesh4_preset_semantics():
    request = build_preset_request("mesh4")
    assert len(request.agents) == 1
    agent = request.agents[0]
    assert (agent.kind.value, agent.count, agent.protocol, agent.data_width,
            agent.addr_width) == ("compute_tile", 4, "AXI", 256, 64)
    assert [(d.source, d.target, d.kind)
            for d in request.dependencies.dependencies] == [
        ("A", "B", DepKind.BLOCKING), ("B", "A", DepKind.BLOCKING)]
    assert request.noc_config.topology_family.value == "mesh"
    assert request.noc_config.link_width is None
    assert request.address_map.ranges == ()
    assert (request.workload.tp, request.workload.pp, request.workload.ep,
            request.workload.dp) == (1, 1, 1, 1)
    assert request.workload.collectives == ()
    assert request.requirements == ()


def test_mesh4_hbm_preset_semantics():
    request = build_preset_request("mesh4_hbm")
    assert len(request.agents) == 2
    hbm = request.agents[1]
    assert (hbm.kind.value, hbm.count, hbm.addr_width) == (
        "hbm_controller", 1, 64)
    assert len(request.address_map.ranges) == 1
    rng = request.address_map.ranges[0]
    assert (rng.name, rng.base, rng.size, rng.target_agent_idx) == (
        "HBM0", 0x1000, 0x1000, 1)
    base = build_preset_request("mesh4")
    assert [(d.source, d.target, d.kind)
            for d in request.dependencies.dependencies] \
        == [(d.source, d.target, d.kind)
            for d in base.dependencies.dependencies]
    assert request.noc_config.topology_family.value == "mesh"


def test_mesh4_wide128_differs_only_in_link_width():
    wide = build_preset_request("mesh4_wide128").to_dict()
    plain = build_preset_request("mesh4").to_dict()
    # semantic comparison: computed identity is derived, not semantic shape
    for d in (wide, plain):
        for field in COMPUTED_IDENTITY_FIELDS:
            d.pop(field)
    wide["noc_config"]["link_width"] = plain["noc_config"]["link_width"]
    assert wide == plain
    assert build_preset_request("mesh4_wide128").noc_config.link_width == 128


def test_base_design_hashes_are_pinned_and_distinct():
    assert build_preset_request("mesh4").design_hash() == GOLDEN_MESH4_DESIGN
    assert build_preset_request("mesh4_hbm").design_hash() == GOLDEN_HBM_DESIGN
    assert build_preset_request("mesh4_wide128").design_hash() \
        == GOLDEN_WIDE128_DESIGN
    assert GOLDEN_MESH4_DESIGN != GOLDEN_WIDE128_DESIGN
    assert GOLDEN_MESH4_DESIGN != GOLDEN_HBM_DESIGN
    for name in preset_names():
        assert build_preset_request(name).design_hash() \
            == build_preset_request(name).design_hash()


def test_preset_requests_are_fresh_and_frozen():
    first = build_preset_request("mesh4")
    second = build_preset_request("mesh4")
    assert first is not second
    assert first.workload is not second.workload
    assert first.dependencies is not second.dependencies
    assert first.agents is not second.agents
    assert first.to_dict() == second.to_dict()
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.workload = second.workload
    with pytest.raises(dataclasses.FrozenInstanceError):
        first.dependencies = second.dependencies
    # a failed mutation attempt on one build cannot affect a later build
    assert second.design_hash() == GOLDEN_MESH4_DESIGN
    assert build_preset_request("mesh4").design_hash() \
        == GOLDEN_MESH4_DESIGN


# ── intent identity ───────────────────────────────────────────────────────

def test_identity_equation_is_exactly_pinned():
    intent = _intent("mesh4", (("noc_config.link_width", 128),))
    assert set(intent.identity_dict()) == {
        "type", "schema_version", "compiler_semantics_version",
        "fabric_preset", "preset_design_hash", "fabric_overrides",
        "candidate_policy"}
    assert set(intent.to_dict()) == {
        "schema_version", "name", "compiler_semantics_version",
        "fabric_preset", "preset_design_hash", "fabric_overrides",
        "candidate_policy", "intent_id"}
    # both pins are bound on construction, never caller-supplied
    assert intent.compiler_semantics_version == COMPILER_SEMANTICS_VERSION
    assert intent.preset_design_hash \
        == build_preset_request("mesh4").design_hash()
    assert COMPUTED_IDENTITY_FIELDS == frozenset(
        {"design_hash", "guardrail_hash"})
    assert RESERVED_OVERRIDE_PATHS == frozenset({
        "schema_version", "compiler_semantics_version", "type",
        "design_hash", "guardrail_hash"})


def test_name_is_invariance():
    alpha = _intent("mesh4", intent_name="alpha")
    beta = _intent("mesh4", intent_name="beta")
    assert alpha.intent_id() == beta.intent_id()
    assert derive_compile_request(alpha).to_dict() \
        == derive_compile_request(beta).to_dict()
    assert derive_compile_request(alpha).design_hash() \
        == derive_compile_request(beta).design_hash()


def test_candidate_policy_is_required_and_persisted_verbatim():
    with pytest.raises(TypeError):
        CompileIntent(name="p", fabric_preset="mesh4",
                      fabric_overrides=())
    intent = _intent("mesh4")
    assert intent.candidate_policy is \
        CandidatePolicy.BASELINE_DETERMINISTIC_V2
    assert intent.to_dict()["candidate_policy"] == "baseline_deterministic_v2"
    assert [p.value for p in CandidatePolicy] == ["baseline_deterministic_v2"]


def test_candidate_policy_v1_to_v2_changes_intent_identity():
    """The policy value participates in identity; a v1-carrying document
    is refused because V1 left the closed vocabulary."""
    from veritx_dse.core.artifact import content_id
    intent = _intent("mesh4")
    v1_identity = dict(intent.identity_dict())
    v1_identity["candidate_policy"] = "baseline_deterministic_v1"
    assert content_id(f"srota/CompileIntent/v{intent.schema_version}",
                      v1_identity) != intent.intent_id()
    persisted = intent.to_dict()
    persisted["candidate_policy"] = "baseline_deterministic_v1"
    persisted.pop("intent_id")
    with pytest.raises(CompileIntentError, match="candidate_policy"):
        CompileIntent.from_dict(dict(persisted,
                                     intent_id=intent.intent_id()))


def test_preset_change_moves_intent_and_design():
    base = _intent("mesh4")
    wide = _intent("mesh4_wide128")
    assert base.intent_id() != wide.intent_id()
    assert derive_compile_request(base).design_hash() \
        != derive_compile_request(wide).design_hash()
    assert base.candidate_policy is wide.candidate_policy


# ── override mechanics ────────────────────────────────────────────────────

def test_override_order_invariance():
    first = _intent("mesh4", (("noc_config.link_width", 128),
                              ("noc_config.arbitration", "rr")))
    second = _intent("mesh4", (("noc_config.arbitration", "rr"),
                               ("noc_config.link_width", 128)))
    assert first.intent_id() == second.intent_id()
    assert derive_compile_request(first).to_dict() \
        == derive_compile_request(second).to_dict()
    assert derive_compile_request(first).design_hash() \
        == derive_compile_request(second).design_hash()


def test_duplicate_override_is_refused():
    with pytest.raises(CompileIntentError, match="duplicate override"):
        _intent("mesh4", (("noc_config.link_width", 64),
                          ("noc_config.link_width", 128)))


def test_redundant_override_declaration_vs_resolved_design():
    declared = _intent("mesh4_wide128", (("noc_config.link_width", 128),))
    plain = _intent("mesh4_wide128")
    assert declared.intent_id() != plain.intent_id()  # declaration differs
    assert derive_compile_request(declared).design_hash() \
        == derive_compile_request(plain).design_hash()  # design does not


@pytest.mark.parametrize("overrides,match", [
    ((("noc_config.brand_new", 1),), "unknown field"),
    ((("", 1),), "non-empty string"),
    ((("agents.0.count", 2),), "non-dictionary"),
    ((("schema_version", 2),), "reserved"),
    ((("compiler_semantics_version", 9),), "reserved"),
    ((("design_hash", "a" * 64),), "reserved"),
    ((("workload.tp", True),), "semantic type"),
    ((("noc_config.arbitration", [1, 2]),), "JSON scalar"),
    ((("noc_config.arbitration", {"a": 1}),), "JSON scalar"),
    ((("noc_config.arbitration", float("nan")),), "JSON scalar"),
    ((("noc_config.arbitration", object()),), "JSON scalar"),
])
def test_illegal_overrides_are_refused(overrides, match):
    with pytest.raises(CompileIntentError, match=match):
        derive_compile_request(_intent("mesh4", overrides))


def test_type_mismatch_on_known_leaf_is_refused_by_intent_layer():
    with pytest.raises(CompileIntentError, match="semantic type"):
        derive_compile_request(
            _intent("mesh4_wide128", (("noc_config.link_width", "128"),)))


def test_null_leaf_defers_to_canonical_parser_at_the_boundary():
    # the canonical parser stays the type authority; the application
    # boundary wraps it as CompileIntentError with the cause preserved
    with pytest.raises(CompileIntentError, match="link_width") as excinfo:
        derive_compile_request(
            _intent("mesh4", (("noc_config.link_width", "128"),)))
    cause = excinfo.value.__cause__
    assert isinstance(cause, ValueError)
    assert not isinstance(cause, CompileIntentError)
    assert "link_width" in str(cause)


def test_legal_null_leaf_override_derives():
    design = derive_compile_request(
        _intent("mesh4", (("noc_config.link_width", 128),)))
    assert design.noc_config.link_width == 128


def test_reserved_override_paths():
    for path in RESERVED_OVERRIDE_PATHS:
        with pytest.raises(CompileIntentError, match="reserved"):
            derive_compile_request(_intent("mesh4", ((path, "x"),)))


# ── derive API ────────────────────────────────────────────────────────────

def test_derive_requires_an_intent_and_fresh_preset():
    with pytest.raises(CompileIntentError, match="CompileIntent"):
        derive_compile_request(object())
    preset = build_preset_request("mesh4")
    before = preset.to_dict()
    derived = derive_compile_request(_intent("mesh4"))
    assert derived.to_dict() == before
    assert derived.design_hash() == GOLDEN_MESH4_DESIGN
    assert preset.to_dict() == before  # preset object untouched


# ── end-to-end: every preset reaches ResolvedFabric ───────────────────────

def test_mesh4_reproduces_the_slice24_golden():
    assert _compile(_intent("mesh4")).resolved_fabric.resolved_fabric_hash \
        == GOLDEN_MESH4_RESOLVED


@pytest.mark.parametrize("preset", ["mesh4", "mesh4_hbm", "mesh4_wide128"])
def test_every_preset_reaches_resolved_fabric(preset):
    compiled = _compile(_intent(preset))
    assert compiled.resolved_fabric.resolved_fabric_hash \
        == PRESOLVED[preset]


def test_mesh4_wide128_preset_vs_override_equivalence():
    via_override = _intent("mesh4", (("noc_config.link_width", 128),))
    via_preset = _intent("mesh4_wide128")
    request_a = derive_compile_request(via_override)
    request_b = derive_compile_request(via_preset)
    assert request_a.design_hash() == request_b.design_hash() \
        == GOLDEN_WIDE128_DESIGN
    assert request_a.to_dict() == request_b.to_dict()
    plan_a = generate_baseline_candidate(design=request_a)
    plan_b = generate_baseline_candidate(design=request_b)
    assert plan_a.vc_spec == plan_b.vc_spec
    assert plan_a.mapping == plan_b.mapping
    assert plan_a.routing_policy == plan_b.routing_policy
    resolved_a = _compile(via_override).resolved_fabric.resolved_fabric_hash
    resolved_b = _compile(via_preset).resolved_fabric.resolved_fabric_hash
    assert resolved_a == resolved_b == GOLDEN_WIDE128_RESOLVED
    # declarations are still distinct product requests
    assert via_override.intent_id() != via_preset.intent_id()
    assert via_override.fabric_preset != via_preset.fabric_preset


def test_mesh4_hbm_pins_new_canonical_hashes():
    compiled = _compile(_intent("mesh4_hbm"))
    assert compiled.design.design_hash() == GOLDEN_HBM_DESIGN
    assert compiled.address_decode.address_decode_hash \
        == GOLDEN_HBM_ADDRESS_DECODE
    assert compiled.fabric.fabric_hash == GOLDEN_HBM_FABRIC
    assert compiled.resolved_fabric.resolved_fabric_hash \
        == GOLDEN_HBM_RESOLVED


# ── representability / authority separations ──────────────────────────────

def test_torus_is_legal_input_but_unrepresentable_candidate():
    intent = _intent("mesh4", (("noc_config.topology_family", "torus"),))
    # intent parses and derives; no torus rejection lives in this layer
    assert CompileIntent.from_dict(intent.to_dict()).intent_id() \
        == intent.intent_id()
    design = derive_compile_request(intent)
    plan = generate_baseline_candidate(design=design)
    assert plan.routing_policy.policy_hash == GOLDEN_DOR_POLICY
    with pytest.raises(CanonicalCompileError) as excinfo:
        compile_deterministic_candidate(
            design=design, inventory=plan.inventory, mapping=plan.mapping,
            routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
            settings=plan.compile_settings)
    assert excinfo.value.stage is CompileStage.ROUTING


def test_rcu_intent_derives_and_fails_downstream():
    intent = _intent("mesh4", (("noc_config.rcu_enabled", True),))
    design = derive_compile_request(intent)
    assert design.noc_config.rcu_enabled is True
    plan = generate_baseline_candidate(design=design)
    with pytest.raises(CanonicalCompileError) as excinfo:
        compile_deterministic_candidate(
            design=design, inventory=plan.inventory, mapping=plan.mapping,
            routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
            settings=plan.compile_settings)
    assert excinfo.value.stage is CompileStage.RESOLVED_FABRIC


def test_arbitration_override_moves_only_router_hardware():
    base = _compile(_intent("mesh4"))
    round_robin = _compile(
        _intent("mesh4", (("noc_config.arbitration", "rr"),)))
    base_design = derive_compile_request(_intent("mesh4"))
    rr_design = derive_compile_request(
        _intent("mesh4", (("noc_config.arbitration", "rr"),)))
    assert rr_design.design_hash() != base_design.design_hash()
    base_plan = generate_baseline_candidate(design=base_design)
    rr_plan = generate_baseline_candidate(design=rr_design)
    assert rr_plan.routing_policy.policy_hash \
        == base_plan.routing_policy.policy_hash == GOLDEN_DOR_POLICY
    assert rr_plan.vc_spec == base_plan.vc_spec
    assert rr_plan.compile_settings == base_plan.compile_settings
    assert round_robin.router_behavior.router_behavior_hash \
        != base.router_behavior.router_behavior_hash
    assert round_robin.fabric.fabric_hash != base.fabric.fabric_hash
    assert round_robin.resolved_fabric.resolved_fabric_hash \
        != base.resolved_fabric.resolved_fabric_hash


# ── strict serialization ──────────────────────────────────────────────────

def test_intent_roundtrip_is_lossless():
    intent = _intent("mesh4_hbm", (("noc_config.arbitration", "rr"),),
                     intent_name="rr-hbm")
    loaded = CompileIntent.from_dict(intent.to_dict())
    assert loaded == intent
    assert loaded.intent_id() == intent.intent_id()
    assert loaded.name == "rr-hbm"


def test_unknown_and_missing_fields_are_refused():
    persisted = _intent("mesh4").to_dict()
    with_extra = dict(persisted, extra=1)
    with pytest.raises(CompileIntentError, match="unknown fields"):
        CompileIntent.from_dict(with_extra)
    for field in ("schema_version", "name", "fabric_preset",
                  "fabric_overrides", "candidate_policy", "intent_id",
                  "compiler_semantics_version", "preset_design_hash"):
        incomplete = dict(persisted)
        del incomplete[field]
        with pytest.raises(CompileIntentError):
            CompileIntent.from_dict(incomplete)


@pytest.mark.parametrize("bad", [0, 3, True, "2"])
def test_schema_version_is_strict(bad):
    persisted = _intent("mesh4").to_dict()
    persisted["schema_version"] = bad
    with pytest.raises(CompileIntentError, match="schema_version"):
        CompileIntent.from_dict(persisted)


def test_schema_v1_documents_are_refused_explicitly():
    """v1 predates compiler-semantics and preset-revision pinning."""
    v1_document = {
        "schema_version": 1,
        "name": "old",
        "fabric_preset": "mesh4",
        "fabric_overrides": {},
        "candidate_policy": "baseline_deterministic_v1",
        "intent_id": "0" * 64,
    }
    with pytest.raises(CompileIntentError,
                       match="CompileIntent v1 predates compiler-semantics") as excinfo:
        CompileIntent.from_dict(v1_document)
    assert "rebuild the intent under schema v2" in str(excinfo.value)


def test_stale_preset_and_semantics_pins_are_refused():
    with pytest.raises(CompileIntentError, match="preset_design_hash"):
        CompileIntent(name="stale", fabric_preset="mesh4",
                      fabric_overrides=(),
                      candidate_policy=CandidatePolicy.BASELINE_DETERMINISTIC_V2,
                      preset_design_hash="0" * 64)
    with pytest.raises(CompileIntentError, match="compiler_semantics_version"):
        CompileIntent(name="stale", fabric_preset="mesh4",
                      fabric_overrides=(),
                      candidate_policy=CandidatePolicy.BASELINE_DETERMINISTIC_V2,
                      compiler_semantics_version=COMPILER_SEMANTICS_VERSION + 1)


def test_deserialized_pins_must_match_current_values():
    persisted = _intent("mesh4").to_dict()
    for field, bad in (("preset_design_hash", "0" * 64),
                       ("compiler_semantics_version",
                        COMPILER_SEMANTICS_VERSION + 1)):
        doc = dict(persisted)
        doc[field] = bad
        with pytest.raises(CompileIntentError, match=field):
            CompileIntent.from_dict(doc)


def test_preset_semantic_revision_changes_intent_id(monkeypatch):
    """A changed base-preset revision rebinds preset_design_hash, and the
    intent id changes mechanically with it."""
    from dataclasses import replace as dc_replace

    from veritx_dse.application import compile_intent as module
    baseline = _intent("mesh4")
    original_builders = dict(module._PRESET_BUILDERS)

    def revised_mesh4():
        request = original_builders["mesh4"]()
        return dc_replace(
            request,
            noc_config=dc_replace(request.noc_config, link_width=256))

    patched = dict(original_builders)
    patched["mesh4"] = revised_mesh4
    monkeypatch.setattr(module, "_PRESET_BUILDERS", patched)
    revised = _intent("mesh4")
    assert revised.preset_design_hash != baseline.preset_design_hash
    assert revised.intent_id() != baseline.intent_id()


def test_identity_binds_the_pins_themselves():
    """Forging a bound pin post-construction moves the id — the pins are
    identity-bearing, not decorative."""
    from veritx_dse.core.artifact import content_id
    intent = _intent("mesh4")
    forged_semantics = dict(intent.identity_dict())
    forged_semantics["compiler_semantics_version"] = \
        COMPILER_SEMANTICS_VERSION + 1
    assert content_id(f"srota/CompileIntent/v{intent.schema_version}",
                      forged_semantics) != intent.intent_id()
    forged_preset = dict(intent.identity_dict())
    forged_preset["preset_design_hash"] = "0" * 64
    assert content_id(f"srota/CompileIntent/v{intent.schema_version}",
                      forged_preset) != intent.intent_id()


def test_preset_registry_is_structurally_immutable():
    from veritx_dse.application import compile_intent as module
    for registry in (module._PRESETS, module._PRESET_BUILDERS):
        with pytest.raises(TypeError):
            registry["mesh4"] = "forged"
        with pytest.raises(TypeError):
            del registry["mesh4"]
        with pytest.raises(AttributeError):
            registry.clear()
    # preset->builder association cannot be re-pointed at runtime
    with pytest.raises(TypeError):
        module._PRESET_BUILDERS["mesh4"] = lambda: None
    assert set(module.preset_names()) == {"mesh4", "mesh4_hbm",
                                          "mesh4_wide128"}
    assert build_preset_request("mesh4").design_hash() \
        == GOLDEN_MESH4_DESIGN


def test_declaration_failures_keep_the_canonical_cause():
    # an unknown leaf path is an application-layer refusal (no cause)
    with pytest.raises(CompileIntentError, match="unknown field") as excinfo:
        derive_compile_request(
            _intent("mesh4", (("noc_config.brand_new", 1),)))
    assert excinfo.value.__cause__ is None
    # a canonical semantic refusal keeps the canonical exception as cause
    with pytest.raises(CompileIntentError, match="arbitration") as excinfo:
        derive_compile_request(
            _intent("mesh4", (("noc_config.arbitration", 7),)))
    assert isinstance(excinfo.value.__cause__, ValueError)
    assert not isinstance(excinfo.value.__cause__, CompileIntentError)
    assert "arbitration" in str(excinfo.value.__cause__)


def test_bad_intent_id_is_refused():
    persisted = _intent("mesh4").to_dict()
    persisted["intent_id"] = "0" * 64
    with pytest.raises(CompileIntentError, match="intent_id"):
        CompileIntent.from_dict(persisted)


def test_unknown_candidate_policy_is_refused():
    persisted = _intent("mesh4").to_dict()
    persisted["candidate_policy"] = "magic_policy"
    with pytest.raises(CompileIntentError, match="candidate_policy"):
        CompileIntent.from_dict(persisted)


def test_transport_overrides_must_be_an_object_of_scalars():
    persisted = _intent("mesh4").to_dict()
    persisted["fabric_overrides"] = [("noc_config.link_width", 128)]
    with pytest.raises(CompileIntentError, match="JSON object"):
        CompileIntent.from_dict(persisted)
    persisted = _intent("mesh4").to_dict()
    persisted["fabric_overrides"] = {"agents": [1, 2]}
    with pytest.raises(CompileIntentError, match="JSON scalar"):
        CompileIntent.from_dict(persisted)


@pytest.mark.parametrize("field,bad", [
    ("name", ""), ("name", 7), ("fabric_preset", 7),
    ("candidate_policy", 7), ("intent_id", 7),
])
def test_non_string_or_empty_required_fields_are_refused(field, bad):
    persisted = _intent("mesh4").to_dict()
    persisted[field] = bad
    with pytest.raises(CompileIntentError):
        CompileIntent.from_dict(persisted)


# ── determinism ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("preset", ["mesh4", "mesh4_hbm", "mesh4_wide128"])
def test_fifty_cycles_per_preset_are_identical(preset):
    first_id = _intent(preset).intent_id()
    first_dict = derive_compile_request(_intent(preset)).to_dict()
    first_design = derive_compile_request(_intent(preset)).design_hash()
    for _ in range(49):
        assert _intent(preset).intent_id() == first_id
        assert derive_compile_request(_intent(preset)).to_dict() == first_dict
        assert derive_compile_request(_intent(preset)).design_hash() \
            == first_design


def test_fifty_cycles_with_legal_overrides_are_identical():
    overrides = (("noc_config.link_width", 128),
                 ("noc_config.arbitration", "rr"))
    first_id = _intent("mesh4", overrides).intent_id()
    first_dict = derive_compile_request(
        _intent("mesh4", overrides)).to_dict()
    for _ in range(49):
        assert _intent("mesh4", overrides).intent_id() == first_id
        assert derive_compile_request(
            _intent("mesh4", overrides)).to_dict() == first_dict


# ── scope sentinels ───────────────────────────────────────────────────────

def test_production_imports_are_exactly_allowed():
    tree = ast.parse(inspect.getsource(ci))
    local: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "veritx_dse"):
            local.add(node.module)
            if node.module == "veritx_dse.compiler.candidate_policy":
                assert {a.name for a in node.names} == {"CandidatePolicy"}
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("veritx_dse"), alias.name
    assert local == {
        "veritx_dse.compiler.candidate_policy",
        "veritx_dse.core.artifact",
        "veritx_dse.model.compile_model",
    }
    called = {node.func.id for node in ast.walk(tree)
              if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    for forbidden in ("generate_baseline_candidate",
                      "compile_deterministic_candidate",
                      "compile_adaptive_candidate"):
        assert forbidden not in called


def test_no_old_application_or_compiler_module_references():
    tree = ast.parse(inspect.getsource(ci))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    # positive pin: the only application module this production file names
    application_modules = {m for m in imported
                           if m.startswith("veritx_dse.application")}
    assert application_modules == set()
    for exact_old in ("veritx_dse.application.compile",
                      "veritx_dse.application.presets",
                      "veritx_dse.application.requests",
                      "veritx_dse.application.service",
                      "veritx_dse.compiler.canonical"):
        assert exact_old not in imported


def _docstring_stripped_source(module) -> str:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) \
                and node.body \
                and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ranges.append((node.body[0].lineno, node.body[0].end_lineno))
    return "".join(
        line for number, line in enumerate(source.splitlines(keepends=True),
                                           start=1)
        if not any(low <= number <= high for low, high in ranges))


def test_production_source_has_no_evaluation_transport_or_io_tokens():
    source = _docstring_stripped_source(ci)
    tokens = ("os.environ", "os.getenv", "open(", "pathlib", "subprocess",
              "booksim", "astra", "compile" + "_bundle",
              "Srota" + "ControlPlane",
              "seed", "metric", "timeout", "verification", "store",
              "wave_d", "wave_e", "simulation", "backend_target")
    for token in tokens:
        assert token not in source, token


def test_test_module_imports_only_the_new_application_module():
    tree = ast.parse(inspect.getsource(sys.modules[__name__]))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    application_modules = {m for m in imported
                           if m.startswith("veritx_dse.application")}
    # package import (from ... import compile_intent) plus the module itself
    assert application_modules <= {"veritx_dse.application",
                                   "veritx_dse.application.compile_intent"}
    assert "veritx_dse.application.compile_intent" in application_modules
    for exact_old in ("veritx_dse.application.compile",
                      "veritx_dse.application.presets",
                      "veritx_dse.application.requests"):
        assert exact_old not in imported


def test_new_files_have_no_cross_worktree_dependency():
    tokens = ("/home/datavex/" + "bruh", "p4" + "/studio",
              "origin/" + "p4", "compile" + "_bundle",
              "Srota" + "ControlPlane")
    for path in (ci.__file__, __file__):
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for token in tokens:
            assert token not in source, (path, token)
