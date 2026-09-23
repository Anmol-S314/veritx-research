"""CompileIntentRecord / CompileResolution persistence-envelope tests.

These pin the 25B resource projections: the intent record is the exact
SEMANTIC CompileIntent declaration (never the presentation name), and
CompileResolution is a linkage record with no new content hash.
"""
from __future__ import annotations

import dataclasses
import inspect
import json
from dataclasses import replace

import pytest

from veritx_dse.application import resources as res
from veritx_dse.application.compile_intent import (
    COMPILE_INTENT_SCHEMA_VERSION, CompileIntent, derive_compile_request,
)
from veritx_dse.application.resources import (
    COMPILE_INTENT_RECORD_SCHEMA_VERSION, COMPILE_RESOLUTION_SCHEMA_VERSION,
    CompileIntentRecord, CompileResolution, ResourceValidationError,
    make_compile_resolution,
)
from veritx_dse.compiler.candidate_policy import (
    CandidatePolicy, generate_baseline_candidate,
)
from veritx_dse.compiler.canonical import compile_deterministic_candidate
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, CompileRequest,
)

POLICY = CandidatePolicy.BASELINE_DETERMINISTIC_V2


# ── fixtures ───────────────────────────────────────────────────────────────

def _intent(preset: str = "mesh4", overrides=(), *,
            name: str = "product") -> CompileIntent:
    return CompileIntent(name=name, fabric_preset=preset,
                         fabric_overrides=tuple(overrides),
                         candidate_policy=POLICY)


def _compile(intent: CompileIntent):
    design = derive_compile_request(intent)
    plan = generate_baseline_candidate(design=design)
    compiled = compile_deterministic_candidate(
        design=design, inventory=plan.inventory, mapping=plan.mapping,
        routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
        settings=plan.compile_settings)
    return design, compiled.resolved_fabric


def _record(preset: str = "mesh4", overrides=()) -> CompileIntentRecord:
    return CompileIntentRecord.from_intent(_intent(preset, overrides))


# ── shape / immutability ───────────────────────────────────────────────────

def test_intent_record_fields_are_exactly_pinned():
    assert {f.name for f in dataclasses.fields(CompileIntentRecord)} == {
        "intent_schema_version", "compiler_semantics_version",
        "fabric_preset", "preset_design_hash", "fabric_overrides",
        "candidate_policy", "intent_id", "schema_version"}
    assert COMPILE_INTENT_RECORD_SCHEMA_VERSION == 1


def test_resolution_fields_are_exactly_pinned():
    assert {f.name for f in dataclasses.fields(CompileResolution)} == {
        "intent_id", "design_hash", "resolved_fabric_hash", "schema_version"}
    assert COMPILE_RESOLUTION_SCHEMA_VERSION == 1


def test_envelopes_are_frozen():
    record = _record()
    with pytest.raises(dataclasses.FrozenInstanceError):
        record.intent_id = "0" * 64
    resolution = CompileResolution(intent_id="a" * 64, design_hash="b" * 64,
                                   resolved_fabric_hash="c" * 64)
    with pytest.raises(dataclasses.FrozenInstanceError):
        resolution.design_hash = "d" * 64


def test_envelopes_carry_no_hash_method_and_no_new_identity():
    record = _record()
    resolution = CompileResolution(intent_id="a" * 64, design_hash="b" * 64,
                                   resolved_fabric_hash="c" * 64)
    for obj in (record, resolution):
        for name in dir(obj):
            assert not (name.endswith("_hash") and callable(getattr(obj, name)))
    for forbidden in ("record_hash", "resolution_hash", "compiled_design_hash",
                      "compile_intent_record_hash", "artifact_hash"):
        assert not hasattr(record, forbidden)
        assert not hasattr(resolution, forbidden)


def test_to_dict_returns_fresh_objects():
    record = _record("mesh4", (("noc_config.link_width", 128),))
    first = record.to_dict()
    first["intent_id"] = "0" * 64
    first["fabric_overrides"].append(["x", 1])
    second = record.to_dict()
    assert second["intent_id"] == record.intent_id
    assert second["fabric_overrides"] == [["noc_config.link_width", 128]]


# ── semantic projection of CompileIntent ───────────────────────────────────

def test_from_intent_excludes_presentation_name():
    alpha = _intent(name="alpha")
    beta = _intent(name="beta")
    assert alpha.intent_id() == beta.intent_id()
    record_a = CompileIntentRecord.from_intent(alpha)
    record_b = CompileIntentRecord.from_intent(beta)
    assert record_a == record_b
    assert alpha.to_dict() != beta.to_dict()  # names really do differ
    assert json.dumps(record_a.to_dict(), sort_keys=True) \
        == json.dumps(record_b.to_dict(), sort_keys=True)
    blob = json.dumps(record_a.to_dict())
    assert "alpha" not in blob and "beta" not in blob
    assert "name" not in record_a.to_dict()


def test_identity_payload_matches_compile_intent_identity_dict():
    intent = _intent("mesh4_hbm", (("noc_config.arbitration", "rr"),))
    record = CompileIntentRecord.from_intent(intent)
    assert record.identity_payload() == intent.identity_dict()
    assert set(record.identity_payload()) == {
        "type", "schema_version", "compiler_semantics_version",
        "fabric_preset", "preset_design_hash", "fabric_overrides",
        "candidate_policy"}


def test_from_intent_rejects_non_intent():
    for bad in (object(), None, "mesh4", {}):
        with pytest.raises(ResourceValidationError, match="CompileIntent"):
            CompileIntentRecord.from_intent(bad)


def test_record_round_trip_is_lossless():
    record = _record("mesh4_wide128")
    loaded = CompileIntentRecord.from_dict(record.to_dict())
    assert loaded == record
    assert loaded.to_dict() == record.to_dict()
    assert loaded.intent_id == record.intent_id


def test_record_recomputed_intent_id_equals_compile_intent():
    intent = _intent("mesh4", (("noc_config.link_width", 128),))
    record = CompileIntentRecord.from_intent(intent)
    assert record.intent_id == intent.intent_id()
    reconstructed = record.to_current_intent(name="anything")
    assert reconstructed.intent_id() == intent.intent_id()
    assert derive_compile_request(reconstructed).to_dict() \
        == derive_compile_request(intent).to_dict()


def test_validation_name_never_serialized():
    record = _record()
    intent = record.to_current_intent(name=res._VALIDATION_NAME)
    assert intent.name == res._VALIDATION_NAME  # caller-supplied, not stored
    assert res._VALIDATION_NAME not in json.dumps(record.to_dict())


# ── strict record parsing ──────────────────────────────────────────────────

def _record_doc(**overrides) -> dict:
    doc = _record().to_dict()
    doc.update(overrides)
    return doc


@pytest.mark.parametrize("mutate,match", [
    (lambda d: d.pop("intent_id"), "missing required fields"),
    (lambda d: d.update(extra=1), "unknown fields"),
    (lambda d: d.update(type="srota/CompileRequest"), "type must be"),
    (lambda d: d.update(schema_version=0), "schema_version"),
    (lambda d: d.update(schema_version=2), "schema_version"),
    (lambda d: d.update(schema_version=True), "exact int"),
    (lambda d: d.update(intent_schema_version=1), "intent_schema_version"),
    (lambda d: d.update(intent_schema_version=3), "intent_schema_version"),
    (lambda d: d.update(compiler_semantics_version=1),
     "compiler_semantics_version"),
    (lambda d: d.update(candidate_policy="magic_policy"), "recomputed"),
    (lambda d: d.update(preset_design_hash="0" * 64), "recomputed"),
    (lambda d: d.update(preset_design_hash="A" * 64), "lowercase hex"),
    (lambda d: d.update(intent_id="0" * 64), "recomputed"),
    (lambda d: d.update(intent_id="A" * 64), "lowercase hex"),
    (lambda d: d.update(intent_id="abc"), "lowercase hex"),
    (lambda d: d.update(fabric_preset=""), "non-empty string"),
    (lambda d: d.update(fabric_overrides=[["x", 1], ["x", 2]]),
     "duplicate override"),
    (lambda d: d.update(fabric_overrides=[["x", [1]]]), "JSON scalar"),
    (lambda d: d.update(fabric_overrides=[["a..b", 1]]), "empty segment"),
    (lambda d: d.update(fabric_overrides=[[7, 1]]), "non-empty string"),
    (lambda d: d.update(fabric_overrides=17), "mapping or a sequence"),
])
def test_record_parser_fails_closed(mutate, match):
    doc = _record_doc()
    mutate(doc)
    with pytest.raises(ResourceValidationError, match=match):
        CompileIntentRecord.from_dict(doc)


def test_record_parser_rejects_non_object():
    with pytest.raises(ResourceValidationError, match="JSON object"):
        CompileIntentRecord.from_dict(["not", "an", "object"])


def test_record_parser_accepts_transport_override_mapping():
    record = _record("mesh4", (("noc_config.link_width", 128),))
    doc = record.to_dict()
    doc["fabric_overrides"] = {"noc_config.link_width": 128}
    assert CompileIntentRecord.from_dict(doc) == record


def _rehash(doc: dict) -> dict:
    """Recompute intent_id so current-only checks are actually reached."""
    from veritx_dse.core.artifact import content_id
    payload = {
        "type": "srota/CompileIntent",
        "schema_version": doc["intent_schema_version"],
        "compiler_semantics_version": doc["compiler_semantics_version"],
        "fabric_preset": doc["fabric_preset"],
        "preset_design_hash": doc["preset_design_hash"],
        "fabric_overrides": [list(row) for row in doc["fabric_overrides"]],
        "candidate_policy": doc["candidate_policy"],
    }
    doc["intent_id"] = content_id(
        f"srota/CompileIntent/v{doc['intent_schema_version']}", payload)
    return doc


def test_unknown_candidate_policy_refused_when_id_is_consistent():
    doc = _rehash(_record_doc(candidate_policy="magic_policy"))
    with pytest.raises(ResourceValidationError, match="candidate_policy"):
        CompileIntentRecord.from_dict(doc)


def test_stale_preset_pin_refused_when_id_is_consistent():
    doc = _rehash(_record_doc(preset_design_hash="0" * 64))
    with pytest.raises(ResourceValidationError, match="preset_design_hash"):
        CompileIntentRecord.from_dict(doc)


# ── CompileResolution parsing / linkage ────────────────────────────────────

def _resolution(intent, design, resolved) -> CompileResolution:
    return make_compile_resolution(intent=intent, design=design,
                                   resolved_fabric=resolved)


def test_make_compile_resolution_links_exactly():
    intent = _intent("mesh4")
    design, resolved = _compile(intent)
    resolution = _resolution(intent, design, resolved)
    assert resolution.intent_id == intent.intent_id()
    assert resolution.design_hash == design.design_hash()
    assert resolution.resolved_fabric_hash == resolved.resolved_fabric_hash
    assert resolution.to_dict()["type"] == "srota/CompileResolution"
    record = CompileIntentRecord.from_intent(intent)
    resolution.validate_against(record, design, resolved)  # no raise


def test_resolution_round_trip_and_strict_parse():
    intent = _intent("mesh4")
    design, resolved = _compile(intent)
    resolution = _resolution(intent, design, resolved)
    assert CompileResolution.from_dict(resolution.to_dict()) == resolution
    doc = resolution.to_dict()
    doc["extra"] = 1
    with pytest.raises(ResourceValidationError, match="unknown fields"):
        CompileResolution.from_dict(doc)
    for field in ("intent_id", "design_hash", "resolved_fabric_hash",
                  "type", "schema_version"):
        doc = resolution.to_dict()
        del doc[field]
        with pytest.raises(ResourceValidationError, match="missing required"):
            CompileResolution.from_dict(doc)
    with pytest.raises(ResourceValidationError, match="schema_version"):
        CompileResolution.from_dict(dict(resolution.to_dict(),
                                         schema_version=2))
    with pytest.raises(ResourceValidationError, match="lowercase hex"):
        CompileResolution.from_dict(dict(resolution.to_dict(),
                                         design_hash="Z" * 64))


def test_make_compile_resolution_rejects_mismatched_inputs():
    intent = _intent("mesh4")
    design, resolved = _compile(intent)
    other_intent = _intent("mesh4_wide128")
    other_design, other_resolved = _compile(other_intent)
    with pytest.raises(ResourceValidationError, match="not exactly"):
        make_compile_resolution(intent=intent, design=other_design,
                                resolved_fabric=resolved)
    with pytest.raises(ResourceValidationError, match="design_hash"):
        make_compile_resolution(intent=intent, design=design,
                                resolved_fabric=other_resolved)
    v1_design = replace(design, compiler_semantics_version=1)
    with pytest.raises(ResourceValidationError, match="current compiler"):
        make_compile_resolution(intent=intent, design=v1_design,
                                resolved_fabric=resolved)
    for kwargs in (dict(intent=object(), design=design,
                        resolved_fabric=resolved),
                   dict(intent=intent, design=object(),
                        resolved_fabric=resolved),
                   dict(intent=intent, design=design,
                        resolved_fabric=object())):
        with pytest.raises(ResourceValidationError):
            make_compile_resolution(**kwargs)


def test_validate_against_link_matrix():
    intent = _intent("mesh4")
    design, resolved = _compile(intent)
    record = CompileIntentRecord.from_intent(intent)
    resolution = _resolution(intent, design, resolved)
    other_intent = _intent("mesh4_hbm")
    other_record = CompileIntentRecord.from_intent(other_intent)
    other_design, other_resolved = _compile(other_intent)

    with pytest.raises(ResourceValidationError, match="intent record"):
        resolution.validate_against(other_record, design, resolved)
    wrong_design = CompileResolution(
        intent_id=resolution.intent_id, design_hash="a" * 64,
        resolved_fabric_hash=resolution.resolved_fabric_hash)
    with pytest.raises(ResourceValidationError, match="does not match the design"):
        wrong_design.validate_against(record, design, resolved)
    wrong_resolved = CompileResolution(
        intent_id=resolution.intent_id, design_hash=resolution.design_hash,
        resolved_fabric_hash="b" * 64)
    with pytest.raises(ResourceValidationError, match="resolved_fabric_hash"):
        wrong_resolved.validate_against(record, design, resolved)
    # resolution references design A but the resolved root belongs to design B
    crossed = CompileResolution(
        intent_id=resolution.intent_id, design_hash=resolution.design_hash,
        resolved_fabric_hash=other_resolved.resolved_fabric_hash)
    with pytest.raises(ResourceValidationError,
                       match="resolved fabric design_hash"):
        crossed.validate_against(record, design, other_resolved)
    with pytest.raises(ResourceValidationError, match="CompileRequest"):
        resolution.validate_against(record, object(), resolved)
    with pytest.raises(ResourceValidationError, match="ResolvedFabric"):
        resolution.validate_against(record, design, object())


def test_validate_against_rejects_v1_design():
    intent = _intent("mesh4")
    design, resolved = _compile(intent)
    record = CompileIntentRecord.from_intent(intent)
    resolution = _resolution(intent, design, resolved)
    v1 = replace(design, compiler_semantics_version=1)
    with pytest.raises(ResourceValidationError,
                       match="current compiler semantics"):
        resolution.validate_against(record, v1, resolved)


# ── identity sentinels ─────────────────────────────────────────────────────

def _docstring_stripped_source(module) -> str:
    import ast
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


def test_resources_module_introduces_no_new_hash_identity():
    source = _docstring_stripped_source(res)
    # exactly one content_id call: the existing CompileIntent identity
    assert source.count("content_id(") == 1
    for forbidden in ("_compute_hash", "record_hash", "resolution_hash",
                      "compiled_design_hash", "mapping_hash"):
        assert forbidden not in source, forbidden
    assert "generate_baseline_candidate" not in source
    assert "compile_deterministic_candidate" not in source
    assert "compile_adaptive_candidate" not in source


def test_resources_module_imports_only_application_model_core():
    tree = __import__("ast").parse(inspect.getsource(res))
    imported: set[str] = set()
    for node in __import__("ast").walk(tree):
        if isinstance(node, __import__("ast").ImportFrom):
            imported.add(node.module or "")
        elif isinstance(node, __import__("ast").Import):
            imported.update(alias.name for alias in node.names)
    local = {name for name in imported if name.startswith("veritx_dse")}
    assert local == {
        "veritx_dse.application.compile_intent",
        "veritx_dse.core.artifact",
        "veritx_dse.model.compile_model",
        "veritx_dse.model.resolved_fabric",
    }
    for forbidden in ("veritx_dse.compiler", "verification", "backend",
                      "simulation", "reports", "cli"):
        assert not any(forbidden in name for name in local), forbidden


def test_resources_module_has_no_forbidden_mechanisms():
    source = _docstring_stripped_source(res)
    for forbidden in ("pickle", "shelve", "sqlite", "eval(", "exec(",
                      "os.environ", "uuid", "datetime", "time.time",
                      "getenv"):
        assert forbidden not in source, forbidden
