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
from veritx_dse.model.compile_model import DepKind

GOLDEN_MESH4_RESOLVED = (
    "3b472dc759e3ac25423ec58de338253b43620eb7a5d9e264e73c1c2687af23ca")
GOLDEN_WIDE128_RESOLVED = (
    "e1862d0e97d9864b9e7e77d7d18c50ddd531e0dc01230fee5200f76765d7cbc9")
GOLDEN_MESH4_DESIGN = (
    "306dc86a9d7e63aa58d0ca594edc9a81e13593e956394dac02e91d1652ada4b5")
GOLDEN_HBM_DESIGN = (
    "c5bac8e54fe1be3f28dc6ea2db4558c48561b45392267fbd4562299efb4894b8")
GOLDEN_WIDE128_DESIGN = (
    "02ad4c724441abf6de311a63540f9be8293a792bd740711d8bf521e0f171ac3b")
GOLDEN_HBM_ADDRESS_DECODE = (
    "b498a6f0a7dfd3ca3261998f3239bb4178150f7fa6f4ff4c69184b853051ebef")
GOLDEN_HBM_FABRIC = (
    "264a857c1978fa44c0f17f150c929a2aff18691189405e5b7754c7fef42a79f1")
GOLDEN_HBM_RESOLVED = (
    "9d38b0d6cdbcde34106e795cd8d88cf1dd9c6e8270fd3d139fb3345467845abf")
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
        candidate_policy=CandidatePolicy.BASELINE_DETERMINISTIC_V1)


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
        "type", "schema_version", "fabric_preset", "fabric_overrides",
        "candidate_policy"}
    assert set(intent.to_dict()) == {
        "schema_version", "name", "fabric_preset", "fabric_overrides",
        "candidate_policy", "intent_id"}
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
        CandidatePolicy.BASELINE_DETERMINISTIC_V1
    assert intent.to_dict()["candidate_policy"] == "baseline_deterministic_v1"
    assert [p.value for p in CandidatePolicy] == ["baseline_deterministic_v1"]


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


def test_null_leaf_defers_to_canonical_parser():
    with pytest.raises(ValueError, match="link_width") as excinfo:
        derive_compile_request(
            _intent("mesh4", (("noc_config.link_width", "128"),)))
    assert not isinstance(excinfo.value, CompileIntentError)


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
                  "fabric_overrides", "candidate_policy", "intent_id"):
        incomplete = dict(persisted)
        del incomplete[field]
        with pytest.raises(CompileIntentError):
            CompileIntent.from_dict(incomplete)


@pytest.mark.parametrize("bad", [0, 2, True, "1"])
def test_schema_version_is_strict(bad):
    persisted = _intent("mesh4").to_dict()
    persisted["schema_version"] = bad
    with pytest.raises(CompileIntentError, match="schema_version"):
        CompileIntent.from_dict(persisted)


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
