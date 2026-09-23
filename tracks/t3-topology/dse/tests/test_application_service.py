"""SrotaControlPlane tests — the canonical application compile surface.

Pins sequencing, stage attribution, closed candidate-policy dispatch,
no-cache recompilation, identity preservation (name invariance and
many-intents -> one-design), the current goldens, restart/idempotence, and
the scope sentinels that absorb the old 25D reachability proof.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
from pathlib import Path
from types import MappingProxyType

import pytest

from veritx_dse.application import service as service_module
from veritx_dse.application.compile_intent import CompileIntent
from veritx_dse.application.service import (
    CompileOutcome, CompileServiceError, CompileServiceStage,
    SrotaControlPlane,
)
from veritx_dse.application.store import (
    ResourceCorruptionError, ResourceNotFoundError, ResourceStore,
    ResourceStoreError,
)
from veritx_dse.compiler.candidate_policy import (
    CandidatePolicy, CandidatePolicyError,
)
from veritx_dse.compiler.canonical import CanonicalCompileError, CompileStage

POLICY = CandidatePolicy.BASELINE_DETERMINISTIC_V2

# Current canonical goldens (see 25A.1 / 25B).
GOLDEN_MESH4_DESIGN = \
    "f13b8d7d61776d863f3f554c32f7d8dab2a622dbf62bdfe697afc6b95ee4547f"
GOLDEN_MESH4_FABRIC = \
    "d7fde891d47c7a6ffb1e0746429a784f95bd20a0014324b8757fdc2841716094"
GOLDEN_MESH4_RESOLVED = \
    "c05d4c19bf3bdd955da97f33fd665d2325441966906b1bb23290d0dcc3296fa1"
GOLDEN_HBM_RESOLVED = \
    "2bf76043e6c653147842b341a04d2600b6201a13ea10d7fe2f0b3e18fad099e6"
GOLDEN_WIDE128_RESOLVED = \
    "47d8cb6c386b22cbc6b4bbf152f40d3c1c72dd1900a48d099afd2bda8fbc9c7f"


# ── helpers ────────────────────────────────────────────────────────────────

def _intent(preset: str = "mesh4", overrides=(), *,
            name: str = "alpha") -> CompileIntent:
    return CompileIntent(name=name, fabric_preset=preset,
                         fabric_overrides=tuple(overrides),
                         candidate_policy=POLICY)


def _control(tmp_path) -> tuple[ResourceStore, SrotaControlPlane]:
    store = ResourceStore(tmp_path / "store")
    return store, SrotaControlPlane(store=store)


def _json_names(root: Path, kind: str) -> list[str]:
    return sorted(p.name for p in (root / kind).glob("*.json"))


# ── public surface / outcome ───────────────────────────────────────────────

def test_constructor_requires_an_explicit_resource_store(tmp_path):
    store, _ = _control(tmp_path)
    assert SrotaControlPlane(store=store) is not None
    with pytest.raises(TypeError):
        SrotaControlPlane()
    with pytest.raises(CompileServiceError, match="must be a ResourceStore"):
        SrotaControlPlane(store=object())


def test_public_surface_is_only_compile():
    public = {name for name in dir(SrotaControlPlane)
              if not name.startswith("_")}
    assert public == {"compile"}
    for forbidden in ("compile_bundle", "compile_request", "compile_legacy",
                      "quick_compile", "compile_without_store", "evaluate",
                      "run", "lower", "verify", "synthesize", "compare"):
        assert forbidden not in public


def test_outcome_fields_properties_and_immutability(tmp_path):
    _, control = _control(tmp_path)
    outcome = control.compile(_intent())
    assert {f.name for f in dataclasses.fields(CompileOutcome)} == {
        "compiled", "committed"}
    assert outcome.intent_id == outcome.committed.resolution.intent_id
    assert outcome.design_hash == outcome.committed.resolution.design_hash
    assert outcome.resolved_fabric_hash \
        == outcome.committed.resolution.resolved_fabric_hash
    with pytest.raises(dataclasses.FrozenInstanceError):
        outcome.compiled = outcome.compiled
    assert not hasattr(outcome, "to_dict")
    for name in dir(outcome):
        assert not (name.endswith("_hash")
                    and callable(getattr(outcome, name)))
    with pytest.raises(TypeError):
        CompileOutcome(compiled=object(), committed=outcome.committed)
    with pytest.raises(TypeError):
        CompileOutcome(compiled=outcome.compiled, committed=object())


def test_stage_vocabulary_is_exactly_pinned():
    assert [stage.name for stage in CompileServiceStage] == [
        "INTENT", "CANDIDATE", "COMPILE", "PERSISTENCE"]
    error = CompileServiceError(CompileServiceStage.COMPILE, "detail")
    assert error.stage is CompileServiceStage.COMPILE
    assert error.detail == "detail"
    assert "COMPILE" in str(error)


# ── dispatch sentinel ──────────────────────────────────────────────────────

def test_dispatch_covers_every_candidate_policy_exactly():
    dispatch = service_module._POLICY_DISPATCH
    assert set(dispatch) == set(CandidatePolicy)
    assert isinstance(dispatch, MappingProxyType)
    for entry in dispatch.values():
        assert isinstance(entry, service_module._PolicyDispatch)
    with pytest.raises(TypeError):
        dispatch[CandidatePolicy.BASELINE_DETERMINISTIC_V2] = None


def test_dispatch_gap_fails_closed(tmp_path, monkeypatch):
    _, control = _control(tmp_path)
    monkeypatch.setattr(service_module, "_POLICY_DISPATCH",
                        MappingProxyType({}))
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(_intent())
    assert excinfo.value.stage is CompileServiceStage.INTENT
    assert "dispatch" in excinfo.value.detail
    assert _json_names(tmp_path / "store", "resolutions") == []


# ── goldens through the service ────────────────────────────────────────────

def test_mesh4_golden(tmp_path):
    _, control = _control(tmp_path)
    outcome = control.compile(_intent("mesh4"))
    assert outcome.design_hash == GOLDEN_MESH4_DESIGN
    assert outcome.compiled.fabric.fabric_hash == GOLDEN_MESH4_FABRIC
    assert outcome.resolved_fabric_hash == GOLDEN_MESH4_RESOLVED
    assert outcome.compiled.resolved_fabric.resolved_fabric_hash \
        == GOLDEN_MESH4_RESOLVED


def test_mesh4_hbm_golden(tmp_path):
    _, control = _control(tmp_path)
    outcome = control.compile(_intent("mesh4_hbm"))
    assert outcome.resolved_fabric_hash == GOLDEN_HBM_RESOLVED


def test_mesh4_wide128_golden(tmp_path):
    _, control = _control(tmp_path)
    outcome = control.compile(_intent("mesh4_wide128"))
    assert outcome.resolved_fabric_hash == GOLDEN_WIDE128_RESOLVED


# ── identity preservation through the service ──────────────────────────────

def test_name_invariance_through_the_service(tmp_path):
    store, control = _control(tmp_path)
    alpha = control.compile(_intent(name="alpha"))
    beta = control.compile(_intent(name="beta"))
    assert alpha.intent_id == beta.intent_id
    assert alpha.design_hash == beta.design_hash
    assert alpha.resolved_fabric_hash == beta.resolved_fabric_hash
    assert alpha.committed.resolution.to_dict() \
        == beta.committed.resolution.to_dict()
    root = tmp_path / "store"
    assert len(_json_names(root, "intents")) == 1
    assert len(_json_names(root, "resolutions")) == 1
    blob = (root / "intents" / f"{alpha.intent_id}.json").read_bytes()
    assert b"alpha" not in blob and b"beta" not in blob
    assert store.load_committed(alpha.intent_id).resolution == \
        alpha.committed.resolution


def test_many_intents_one_design_through_the_service(tmp_path):
    store, control = _control(tmp_path)
    override = control.compile(
        _intent("mesh4", (("noc_config.link_width", 128),), name="A"))
    preset = control.compile(_intent("mesh4_wide128", name="B"))
    assert override.intent_id != preset.intent_id
    assert override.design_hash == preset.design_hash
    assert override.resolved_fabric_hash == preset.resolved_fabric_hash
    root = tmp_path / "store"
    assert len(_json_names(root, "intents")) == 2
    assert len(_json_names(root, "designs")) == 1
    assert len(_json_names(root, "resolved")) == 1
    assert len(_json_names(root, "resolutions")) == 2


# ── recompilation policy (no cache) ────────────────────────────────────────

def test_recompile_always_invokes_the_canonical_compiler(tmp_path,
                                                          monkeypatch):
    calls = {"n": 0}
    real = service_module.compile_deterministic_candidate

    def counting(**kwargs):
        calls["n"] += 1
        return real(**kwargs)

    monkeypatch.setattr(service_module, "compile_deterministic_candidate",
                        counting)
    _, control = _control(tmp_path)
    intent = _intent()
    first = control.compile(intent)
    second = control.compile(intent)
    assert calls["n"] == 2
    assert first.resolved_fabric_hash == second.resolved_fabric_hash
    assert _json_names(tmp_path / "store", "resolutions") == [
        f"{intent.intent_id()}.json"]


def test_twenty_five_same_store_recompiles_are_identical(tmp_path,
                                                         monkeypatch):
    calls = {"n": 0}
    real = service_module.compile_deterministic_candidate

    def counting(**kwargs):
        calls["n"] += 1
        return real(**kwargs)

    monkeypatch.setattr(service_module, "compile_deterministic_candidate",
                        counting)
    _, control = _control(tmp_path)
    intent = _intent()
    seen = set()
    for _ in range(25):
        outcome = control.compile(intent)
        seen.add((outcome.intent_id, outcome.design_hash,
                  outcome.compiled.fabric.fabric_hash,
                  outcome.resolved_fabric_hash))
    assert calls["n"] == 25
    assert len(seen) == 1
    assert seen.pop() == (intent.intent_id(), GOLDEN_MESH4_DESIGN,
                          GOLDEN_MESH4_FABRIC, GOLDEN_MESH4_RESOLVED)
    assert len(_json_names(tmp_path / "store", "resolutions")) == 1


def test_twenty_five_fresh_stores_are_identical(tmp_path):
    intent = _intent()
    expected = (intent.intent_id(), GOLDEN_MESH4_DESIGN,
                GOLDEN_MESH4_FABRIC, GOLDEN_MESH4_RESOLVED)
    seen = set()
    for index in range(25):
        store = ResourceStore(tmp_path / f"store_{index}")
        outcome = SrotaControlPlane(store=store).compile(intent)
        seen.add((outcome.intent_id, outcome.design_hash,
                  outcome.compiled.fabric.fabric_hash,
                  outcome.resolved_fabric_hash))
    assert seen == {expected}


def test_restart_is_idempotent(tmp_path):
    store, control = _control(tmp_path)
    intent = _intent()
    first = control.compile(intent)
    del control
    del store
    fresh_store = ResourceStore(tmp_path / "store")
    fresh_control = SrotaControlPlane(store=fresh_store)
    second = fresh_control.compile(intent)
    assert first.intent_id == second.intent_id
    assert first.design_hash == second.design_hash
    assert first.resolved_fabric_hash == second.resolved_fabric_hash
    assert len(_json_names(tmp_path / "store", "resolutions")) == 1
    committed = fresh_store.load_committed(intent.intent_id())
    assert committed.resolved_fabric.resolved_fabric_hash \
        == first.resolved_fabric_hash


# ── error chains ───────────────────────────────────────────────────────────

def test_intent_stage_rejects_non_intent(tmp_path):
    _, control = _control(tmp_path)
    for bad in (object(), {"fabric_preset": "mesh4"}, None, "mesh4"):
        with pytest.raises(CompileServiceError) as excinfo:
            control.compile(bad)
        assert excinfo.value.stage is CompileServiceStage.INTENT


def test_torus_failure_chain(tmp_path):
    store, control = _control(tmp_path)
    intent = _intent("mesh4", (("noc_config.topology_family", "torus"),))
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(intent)
    error = excinfo.value
    assert error.stage is CompileServiceStage.COMPILE
    assert isinstance(error.__cause__, CanonicalCompileError)
    assert error.__cause__.stage is CompileStage.ROUTING
    with pytest.raises(ResourceNotFoundError):
        store.load_resolution(intent.intent_id())
    assert _json_names(tmp_path / "store", "resolutions") == []


def test_rcu_failure_chain(tmp_path):
    store, control = _control(tmp_path)
    intent = _intent("mesh4", (("noc_config.rcu_enabled", True),))
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(intent)
    error = excinfo.value
    assert error.stage is CompileServiceStage.COMPILE
    assert isinstance(error.__cause__, CanonicalCompileError)
    assert error.__cause__.stage is CompileStage.RESOLVED_FABRIC
    with pytest.raises(ResourceNotFoundError):
        store.load_resolution(intent.intent_id())


def test_candidate_failure_chain(tmp_path, monkeypatch):
    store, control = _control(tmp_path)

    def boom(*, design):
        raise CandidatePolicyError("UNSUPPORTED_POLICY_DOMAIN", "injected")

    monkeypatch.setattr(service_module, "generate_baseline_candidate", boom)
    intent = _intent()
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(intent)
    error = excinfo.value
    assert error.stage is CompileServiceStage.CANDIDATE
    assert isinstance(error.__cause__, CandidatePolicyError)
    assert error.__cause__.reason == "UNSUPPORTED_POLICY_DOMAIN"
    with pytest.raises(ResourceNotFoundError):
        store.load_resolution(intent.intent_id())


def test_persistence_failure_on_commit(tmp_path, monkeypatch):
    store, control = _control(tmp_path)

    def boom(**kwargs):
        raise ResourceStoreError("injected commit failure")

    monkeypatch.setattr(store, "commit_resolution", boom)
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(_intent())
    assert excinfo.value.stage is CompileServiceStage.PERSISTENCE
    assert isinstance(excinfo.value.__cause__, ResourceStoreError)


def test_persistence_failure_on_reload(tmp_path, monkeypatch):
    store, control = _control(tmp_path)

    def boom(intent_id):
        raise ResourceCorruptionError("injected reload failure")

    monkeypatch.setattr(store, "load_committed", boom)
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(_intent())
    assert excinfo.value.stage is CompileServiceStage.PERSISTENCE
    assert isinstance(excinfo.value.__cause__, ResourceCorruptionError)
    # the commit did happen; the service still refuses to report success
    assert len(_json_names(tmp_path / "store", "resolutions")) == 1


def test_commit_then_reload_order_is_proven(tmp_path, monkeypatch):
    store, control = _control(tmp_path)
    order: list[str] = []
    real_commit = store.commit_resolution
    real_load = store.load_committed

    def record_commit(**kwargs):
        order.append("commit")
        return real_commit(**kwargs)

    def record_load(intent_id):
        order.append("load")
        return real_load(intent_id)

    monkeypatch.setattr(store, "commit_resolution", record_commit)
    monkeypatch.setattr(store, "load_committed", record_load)
    control.compile(_intent())
    assert order == ["commit", "load"]


def test_post_commit_mismatch_fails_persistence(tmp_path, monkeypatch):
    store, control = _control(tmp_path)
    intent = _intent()
    # a real, valid, but different committed bundle
    other_store = ResourceStore(tmp_path / "other_store")
    other_intent = _intent("mesh4_hbm", name="other")
    SrotaControlPlane(store=other_store).compile(other_intent)
    other_bundle = other_store.load_committed(other_intent.intent_id())
    monkeypatch.setattr(store, "load_committed",
                        lambda intent_id: other_bundle)
    with pytest.raises(CompileServiceError) as excinfo:
        control.compile(intent)
    assert excinfo.value.stage is CompileServiceStage.PERSISTENCE


# ── scope sentinels ────────────────────────────────────────────────────────

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


def _imported_modules(module) -> tuple[set[str], set[str]]:
    tree = ast.parse(inspect.getsource(module))
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules, names


def test_service_imports_only_the_authority_groups():
    modules, _ = _imported_modules(service_module)
    local = {name for name in modules if name.startswith("veritx_dse")}
    assert local == {
        "veritx_dse.application.compile_intent",
        "veritx_dse.application.store",
        "veritx_dse.compiler.candidate_policy",
        "veritx_dse.compiler.canonical",
        "veritx_dse.model.compile_model",
    }
    stdlib = {name for name in modules if not name.startswith("veritx_dse")}
    assert stdlib == {"__future__", "collections.abc", "dataclasses",
                     "enum", "types"}
    for forbidden in ("topology_artifact", "attachment", "routing_materialize",
                      "vc_assignment", "vc_resource", "packet_format",
                      "router_behavior", "address_decode", "fabric_artifact",
                      "resolved_fabric", "verification", "backend",
                      "simulation", "reports", "cli"):
        assert not any(forbidden in name for name in local), forbidden


def test_service_source_has_no_backend_verification_or_filesystem_tokens():
    source = _docstring_stripped_source(service_module)
    for token in ("pathlib", "tempfile", "fcntl", "import json", "import os",
                  "os.", "booksim", "BookSim", "astra", "ramulator",
                  "llmservingsim", "simulation", "subprocess", "certif",
                  "formal", "latency_ceiling", "bandwidth_floor",
                  "requirement", "compile_bundle", "derive_vc_assignment",
                  "derive_vc_count", "p4/studio"):
        assert token not in source, token


def test_application_package_reaches_no_legacy_compiler():
    application_dir = Path(service_module.__file__).parent
    files = sorted(application_dir.glob("*.py"))
    assert files, "application package must not be empty"
    for path in files:
        text = path.read_text(encoding="utf-8")
        for token in ("compile_bundle", "derive_route", "derive_vc_assignment",
                      "derive_vc_count", "p4/studio",
                      "veritx_dse.application.compile import",
                      "from veritx_dse.application.compile ",
                      "FabricPreset"):
            assert token not in text, (path.name, token)
    modules, _ = _imported_modules(service_module)
    assert "veritx_dse.application.compile" not in modules
    # the canonical branch has exactly one application compile surface
    assert not (application_dir / "compile.py").exists()
