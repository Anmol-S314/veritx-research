"""ResourceStore tests — typed, write-once, verified, atomic, concurrent.

Covers the 25B durability boundary: four resource kinds, canonical JSON,
unique-temp + fsync + os.replace, cross-process write lock, idempotence,
conflict refusal, corruption refusal, commit-point semantics, and restart.
"""
from __future__ import annotations

import ast
import dataclasses
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from veritx_dse.application import store as store_module
from veritx_dse.application.compile_intent import (
    CompileIntent, derive_compile_request,
)
from veritx_dse.application.resources import (
    CompileIntentRecord, CompileResolution, make_compile_resolution,
)
from veritx_dse.application.store import (
    ResourceConflictError, ResourceCorruptionError, ResourceNotFoundError,
    ResourceStore, ResourceStoreError, StoredCompileResolution,
)
from veritx_dse.compiler.candidate_policy import (
    CandidatePolicy, generate_baseline_candidate,
)
from veritx_dse.compiler.canonical import compile_deterministic_candidate
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, CompileRequest, migrate_design,
)
from veritx_dse.model.resolved_fabric import ResolvedFabric

DSE_DIR = Path(__file__).resolve().parent.parent
POLICY = CandidatePolicy.BASELINE_DETERMINISTIC_V2

_MESH4_OVERRIDE = (("noc_config.link_width", 128),)


# ── fixtures / helpers ─────────────────────────────────────────────────────

def _intent(preset: str = "mesh4", overrides=(), *,
            name: str = "alpha") -> CompileIntent:
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


def _bundle(preset: str = "mesh4", overrides=(), *, name: str = "alpha"):
    intent = _intent(preset, overrides, name=name)
    design, resolved = _compile(intent)
    return intent, design, resolved


def _store(tmp_path) -> ResourceStore:
    return ResourceStore(tmp_path / "store")


def _canonical_bytes(document) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8") \
        + b"\n"


def _json_files(root: Path, kind: str) -> list[str]:
    return sorted(p.name for p in (root / kind).glob("*.json"))


def _tmp_files(root: Path) -> list[str]:
    return sorted(str(p.relative_to(root)) for p in root.rglob("*.tmp"))


# ── construction / layout ──────────────────────────────────────────────────

def test_root_is_required_explicitly(tmp_path):
    with pytest.raises(TypeError):
        ResourceStore()
    with pytest.raises(ResourceStoreError, match="root is required"):
        ResourceStore(None)


def test_directory_layout_is_created(tmp_path):
    store = _store(tmp_path)
    root = tmp_path / "store"
    for name in ("intents", "designs", "resolved", "resolutions"):
        assert (root / name).is_dir()
    assert (root / ".store.lock").exists()
    assert store is not None


# ── commit / load / restart ────────────────────────────────────────────────

def test_commit_and_load_committed_round_trip(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    resolution = store.commit_resolution(
        intent=intent, design=design, resolved_fabric=resolved)
    assert resolution.intent_id == intent.intent_id()
    bundle = store.load_committed(intent.intent_id())
    assert isinstance(bundle, StoredCompileResolution)
    assert bundle.resolution == resolution
    assert bundle.intent_record.intent_id == intent.intent_id()
    assert bundle.design.to_dict() == design.to_dict()
    assert bundle.resolved_fabric.to_dict() == resolved.to_dict()


def test_exact_file_set_after_single_commit(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    root = tmp_path / "store"
    assert _json_files(root, "intents") == [f"{intent.intent_id()}.json"]
    assert _json_files(root, "designs") == [f"{design.design_hash()}.json"]
    assert _json_files(root, "resolved") == [
        f"{resolved.resolved_fabric_hash}.json"]
    assert _json_files(root, "resolutions") == [f"{intent.intent_id()}.json"]
    assert _tmp_files(root) == []
    assert sorted(p.name for p in root.iterdir()) == [
        ".store.lock", "designs", "intents", "resolutions", "resolved"]


def test_restart_from_disk_needs_no_memory(tmp_path):
    intent, design, resolved = _bundle()
    first = _store(tmp_path)
    first.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    del first
    second = ResourceStore(tmp_path / "store")
    bundle = second.load_committed(intent.intent_id())
    assert bundle.design.to_dict() == design.to_dict()
    assert bundle.resolved_fabric.to_dict() == resolved.to_dict()
    assert bundle.intent_record.to_dict() \
        == CompileIntentRecord.from_intent(intent).to_dict()


# ── intent record: name invariance ─────────────────────────────────────────

def test_put_intent_name_invariance_and_idempotence(tmp_path):
    alpha = _intent(name="alpha")
    beta = _intent(name="beta")
    assert alpha.intent_id() == beta.intent_id()
    store = _store(tmp_path)
    record_a = store.put_intent(alpha)
    assert record_a == CompileIntentRecord.from_intent(beta)
    path = tmp_path / "store" / "intents" / f"{alpha.intent_id()}.json"
    bytes_after_alpha = path.read_bytes()
    store.put_intent(beta)  # idempotent
    assert path.read_bytes() == bytes_after_alpha
    assert b"alpha" not in bytes_after_alpha
    assert b"beta" not in bytes_after_alpha
    assert b'"name"' not in bytes_after_alpha
    assert store.load_intent_record(alpha.intent_id()).intent_id \
        == alpha.intent_id()


# ── many intents -> one design ─────────────────────────────────────────────

def test_many_intents_one_design_file_counts(tmp_path):
    intent_a = _intent("mesh4", _MESH4_OVERRIDE, name="A")
    intent_b = _intent("mesh4_wide128", name="B")
    design_a, resolved_a = _compile(intent_a)
    design_b, resolved_b = _compile(intent_b)
    assert intent_a.intent_id() != intent_b.intent_id()
    assert design_a.design_hash() == design_b.design_hash()
    assert resolved_a.resolved_fabric_hash == resolved_b.resolved_fabric_hash

    store = _store(tmp_path)
    store.commit_resolution(intent=intent_a, design=design_a,
                            resolved_fabric=resolved_a)
    store.commit_resolution(intent=intent_b, design=design_b,
                            resolved_fabric=resolved_b)
    root = tmp_path / "store"
    assert len(_json_files(root, "intents")) == 2
    assert len(_json_files(root, "designs")) == 1
    assert len(_json_files(root, "resolved")) == 1
    assert len(_json_files(root, "resolutions")) == 2
    assert _json_files(root, "designs") \
        == [f"{design_a.design_hash()}.json"]
    assert store.load_committed(intent_a.intent_id()).design.design_hash() \
        == store.load_committed(intent_b.intent_id()).design.design_hash()


def test_declaration_forms_remain_distinct_over_one_design(tmp_path):
    preset = _intent("mesh4_wide128", name="preset")
    redundant = _intent("mesh4_wide128", _MESH4_OVERRIDE, name="redundant")
    override = _intent("mesh4", _MESH4_OVERRIDE, name="override")
    ids = {preset.intent_id(), redundant.intent_id(), override.intent_id()}
    assert len(ids) == 3  # declarations stay distinct
    designs = {_compile(i)[0].design_hash() for i in (preset, redundant, override)}
    assert len(designs) == 1  # ...while converging on one design
    store = _store(tmp_path)
    for intent in (preset, redundant, override):
        design, resolved = _compile(intent)
        store.commit_resolution(intent=intent, design=design,
                                resolved_fabric=resolved)
    root = tmp_path / "store"
    assert len(_json_files(root, "intents")) == 3
    assert len(_json_files(root, "designs")) == 1
    assert len(_json_files(root, "resolved")) == 1
    assert len(_json_files(root, "resolutions")) == 3


# ── current-only design policy ─────────────────────────────────────────────

def test_put_design_refuses_legacy_v1_then_migrated_succeeds(tmp_path):
    intent, design, resolved = _bundle()
    v1 = dataclasses.replace(design, compiler_semantics_version=1)
    store = _store(tmp_path)
    with pytest.raises(ResourceStoreError, match="current compiler semantics"):
        store.put_design(v1)
    assert _json_files(tmp_path / "store", "designs") == []
    # the raw migration input is untouched
    raw_before = v1.to_dict()
    migrated, provenance = migrate_design(v1)
    assert provenance["from_semantics"] == 1
    assert v1.to_dict() == raw_before
    store.put_design(migrated)
    assert store.load_design(migrated.design_hash()).to_dict() \
        == migrated.to_dict()
    assert migrated.compiler_semantics_version == COMPILER_SEMANTICS_VERSION


def test_load_design_refuses_legacy_v1_inserted_in_store(tmp_path):
    intent, design, _ = _bundle()
    v1 = dataclasses.replace(design, compiler_semantics_version=1)
    store = _store(tmp_path)
    path = tmp_path / "store" / "designs" / f"{v1.design_hash()}.json"
    path.write_bytes(_canonical_bytes(v1.to_dict()))
    with pytest.raises(ResourceStoreError, match="not current-semantics"):
        store.load_design(v1.design_hash())
    # deliberately not reported as merely missing
    with pytest.raises(ResourceStoreError) as excinfo:
        store.load_design(v1.design_hash())
    assert not isinstance(excinfo.value, ResourceNotFoundError)


# ── key validation / paths ─────────────────────────────────────────────────

@pytest.mark.parametrize("key", [
    "A" * 64, "a" * 63, "a" * 65, "g" * 64, "", "a" * 64 + "/x",
    "../" + "a" * 61, " " + "a" * 63, 7, None, "a" * 63 + " ",
])
def test_malformed_keys_are_rejected(tmp_path, key):
    store = _store(tmp_path)
    for loader in (store.load_intent_record, store.load_design,
                   store.load_resolved, store.load_resolution):
        with pytest.raises(ResourceStoreError):
            loader(key)


def test_key_validation_prevents_traversal_writes(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    escaped = list(tmp_path.glob("*.json"))
    assert escaped == []
    assert not (tmp_path / "store" / "designs").parent.parent.joinpath(
        "etc").exists()


def test_symlinked_resource_is_refused(tmp_path):
    intent, design, _ = _bundle()
    store = _store(tmp_path)
    real = tmp_path / "elsewhere.json"
    real.write_bytes(_canonical_bytes(design.to_dict()))
    link = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    link.symlink_to(real)
    with pytest.raises(ResourceCorruptionError, match="symlink"):
        store.load_design(design.design_hash())


# ── missing / corruption matrix ────────────────────────────────────────────

def test_missing_resource_is_not_found(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(ResourceNotFoundError):
        store.load_design("a" * 64)


@pytest.mark.parametrize("kind,key_of", [
    ("intents", "intent_id"),
    ("designs", "design_hash"),
    ("resolved", "resolved_fabric_hash"),
])
def test_invalid_json_is_corruption(tmp_path, kind, key_of):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    key = {"intent_id": intent.intent_id(),
           "design_hash": design.design_hash(),
           "resolved_fabric_hash": resolved.resolved_fabric_hash}[key_of]
    (tmp_path / "store" / kind / f"{key}.json").write_bytes(b"{not json")
    with pytest.raises(ResourceCorruptionError):
        store.load_committed(intent.intent_id()) if kind != "designs" \
            else store.load_design(key)


def test_wrong_resource_type_in_design_slot_is_corruption(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.put_resolved(resolved)
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    path.write_bytes(_canonical_bytes(resolved.to_dict()))
    with pytest.raises(ResourceCorruptionError):
        store.load_design(design.design_hash())


def test_missing_required_field_is_corruption(tmp_path):
    intent, design, _ = _bundle()
    store = _store(tmp_path)
    doc = design.to_dict()
    del doc["workload"]
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    path.write_bytes(_canonical_bytes(doc))
    with pytest.raises(ResourceCorruptionError):
        store.load_design(design.design_hash())


def test_tampered_internal_hash_is_corruption(tmp_path):
    intent, design, _ = _bundle()
    store = _store(tmp_path)
    doc = design.to_dict()
    doc["design_hash"] = "0" * 64
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    path.write_bytes(_canonical_bytes(doc))
    with pytest.raises(ResourceCorruptionError):
        store.load_design(design.design_hash())


def test_valid_design_under_wrong_filename_is_corruption(tmp_path):
    intent, design, _ = _bundle()
    store = _store(tmp_path)
    wrong_key = "a" * 64
    path = tmp_path / "store" / "designs" / f"{wrong_key}.json"
    path.write_bytes(_canonical_bytes(design.to_dict()))
    with pytest.raises(ResourceCorruptionError, match="does not match its key"):
        store.load_design(wrong_key)


def test_valid_resolved_under_wrong_filename_is_corruption(tmp_path):
    _, _, resolved = _bundle()
    store = _store(tmp_path)
    wrong_key = "b" * 64
    path = tmp_path / "store" / "resolved" / f"{wrong_key}.json"
    path.write_bytes(_canonical_bytes(resolved.to_dict()))
    with pytest.raises(ResourceCorruptionError, match="does not match its key"):
        store.load_resolved(wrong_key)


def test_tampered_intent_record_id_is_corruption(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    path = tmp_path / "store" / "intents" / f"{intent.intent_id()}.json"
    doc = json.loads(path.read_text())
    doc["intent_id"] = "c" * 64
    path.write_bytes(_canonical_bytes(doc))
    with pytest.raises(ResourceCorruptionError):
        store.load_intent_record(intent.intent_id())


def test_resolution_missing_design_parent(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    (tmp_path / "store" / "designs" / f"{design.design_hash()}.json").unlink()
    with pytest.raises(ResourceNotFoundError):
        store.load_committed(intent.intent_id())


def test_resolution_missing_resolved_parent(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    (tmp_path / "store" / "resolved"
     / f"{resolved.resolved_fabric_hash}.json").unlink()
    with pytest.raises(ResourceNotFoundError):
        store.load_committed(intent.intent_id())


def test_resolution_with_crossed_resolved_root_is_corruption(tmp_path):
    intent_a, design_a, _ = _bundle("mesh4")
    _, design_b, resolved_b = _bundle("mesh4_hbm", name="B")
    store = _store(tmp_path)
    store.put_intent(intent_a)
    store.put_design(design_a)
    store.put_resolved(resolved_b)
    store.put_resolution(CompileResolution(
        intent_id=intent_a.intent_id(), design_hash=design_a.design_hash(),
        resolved_fabric_hash=resolved_b.resolved_fabric_hash))
    with pytest.raises(ResourceCorruptionError, match="design_hash"):
        store.load_committed(intent_a.intent_id())


def test_resolution_whose_design_is_not_the_intent_design(tmp_path):
    """A committed resolution must link to the design its intent derives."""
    intent_a, design_a, resolved_a = _bundle("mesh4")
    _, design_b, resolved_b = _bundle("mesh4_hbm", name="B")
    store = _store(tmp_path)
    store.put_intent(intent_a)
    store.put_design(design_b)      # a valid design, but not intent A's
    store.put_resolved(resolved_b)
    store.put_resolution(CompileResolution(
        intent_id=intent_a.intent_id(), design_hash=design_b.design_hash(),
        resolved_fabric_hash=resolved_b.resolved_fabric_hash))
    with pytest.raises(ResourceCorruptionError, match="not exactly the request"):
        store.load_committed(intent_a.intent_id())


# ── conflict / no-overwrite ────────────────────────────────────────────────

def test_resolution_conflict_same_intent_different_links(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    path = tmp_path / "store" / "resolutions" / f"{intent.intent_id()}.json"
    before = path.read_bytes()
    conflicting = CompileResolution(
        intent_id=intent.intent_id(), design_hash="d" * 64,
        resolved_fabric_hash=resolved.resolved_fabric_hash)
    with pytest.raises(ResourceConflictError, match="different canonical"):
        store.put_resolution(conflicting)
    assert path.read_bytes() == before


def test_put_never_overwrites_corrupt_content(tmp_path):
    intent, design, _ = _bundle()
    store = _store(tmp_path)
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    path.write_bytes(b"CORRUPT")
    with pytest.raises(ResourceCorruptionError):
        store.put_design(design)
    assert path.read_bytes() == b"CORRUPT"


def test_put_never_overwrites_miskeyed_content(tmp_path):
    intent, design, _ = _bundle()
    other_design, _ = _compile(_intent("mesh4_hbm", name="B"))
    store = _store(tmp_path)
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    path.write_bytes(_canonical_bytes(other_design.to_dict()))
    before = path.read_bytes()
    with pytest.raises(ResourceCorruptionError):
        store.put_design(design)
    assert path.read_bytes() == before


def test_idempotent_put_is_a_noop(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    before = path.read_bytes()
    store.put_design(design)
    store.put_resolved(resolved)
    store.put_intent(intent)
    assert path.read_bytes() == before


# ── canonical bytes ────────────────────────────────────────────────────────

def test_canonical_bytes_ignore_dict_insertion_order():
    a = {"b": 1, "a": {"d": 2, "c": [1, 2]}}
    b = {"a": {"c": [1, 2], "d": 2}, "b": 1}
    assert store_module._canonical_bytes(a) == store_module._canonical_bytes(b)
    encoded = store_module._canonical_bytes(a)
    assert encoded.endswith(b"\n") and not encoded.endswith(b"\n\n")
    assert b": " not in encoded and b", " not in encoded
    with pytest.raises(ValueError):
        store_module._canonical_bytes({"x": float("nan")})


def test_stored_bytes_are_canonical_and_sorted(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    path = tmp_path / "store" / "designs" / f"{design.design_hash()}.json"
    raw = path.read_bytes()
    assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
    assert raw == _canonical_bytes(json.loads(raw.decode()))


# ── durability / failure paths ─────────────────────────────────────────────

def test_write_path_flushes_fsyncs_and_replaces(tmp_path, monkeypatch):
    _, design, _ = _bundle()
    store = _store(tmp_path)  # construct before recording: __init__ fsyncs root
    events: list[str] = []
    real_flush = store_module._flush_and_sync
    real_replace = store_module.os.replace
    real_sync_dir = store_module._sync_directory

    def record_flush(handle):
        events.append("flush+fsync_file")
        return real_flush(handle)

    def record_replace(src, dst):
        events.append("replace")
        return real_replace(src, dst)

    def record_sync_dir(directory):
        events.append("fsync_dir")
        return real_sync_dir(directory)

    monkeypatch.setattr(store_module, "_flush_and_sync", record_flush)
    monkeypatch.setattr(store_module.os, "replace", record_replace)
    monkeypatch.setattr(store_module, "_sync_directory", record_sync_dir)
    store.put_design(design)
    assert events == ["flush+fsync_file", "replace", "fsync_dir"]


def test_publish_failure_cleans_temp_and_preserves_existing(tmp_path,
                                                            monkeypatch):
    _, design_a, _ = _bundle("mesh4")
    _, design_b, _ = _bundle("mesh4_hbm", name="B")
    store = _store(tmp_path)
    store.put_design(design_a)
    path_a = tmp_path / "store" / "designs" / f"{design_a.design_hash()}.json"
    before = path_a.read_bytes()

    def boom(src, dst):
        raise OSError("injected publish failure")

    monkeypatch.setattr(store_module.os, "replace", boom)
    with pytest.raises(ResourceStoreError) as excinfo:
        store.put_design(design_b)
    assert isinstance(excinfo.value.__cause__, OSError)
    assert path_a.read_bytes() == before
    assert _tmp_files(tmp_path / "store") == []
    assert _json_files(tmp_path / "store", "designs") \
        == [f"{design_a.design_hash()}.json"]


def test_commit_point_failure_then_idempotent_retry(tmp_path, monkeypatch):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    root = tmp_path / "store"
    resolution_name = f"{intent.intent_id()}.json"
    real_replace = store_module.os.replace
    state = {"fail": True}

    def selective_replace(src, dst):
        target = Path(dst)
        if state["fail"] and target.parent.name == "resolutions" \
                and target.name == resolution_name:
            raise OSError("injected commit-point failure")
        return real_replace(src, dst)

    monkeypatch.setattr(store_module.os, "replace", selective_replace)
    with pytest.raises(ResourceStoreError):
        store.commit_resolution(intent=intent, design=design,
                                resolved_fabric=resolved)
    # parents may exist; the resolution commit marker does not
    assert _json_files(root, "intents") == [resolution_name]
    assert _json_files(root, "designs") == [f"{design.design_hash()}.json"]
    assert _json_files(root, "resolved") \
        == [f"{resolved.resolved_fabric_hash}.json"]
    assert _json_files(root, "resolutions") == []
    with pytest.raises(ResourceNotFoundError):
        store.load_committed(intent.intent_id())
    assert _tmp_files(root) == []

    state["fail"] = False
    resolution = store.commit_resolution(intent=intent, design=design,
                                         resolved_fabric=resolved)
    assert store.load_committed(intent.intent_id()).resolution == resolution
    assert _json_files(root, "resolutions") == [resolution_name]


# ── cross-process concurrency ──────────────────────────────────────────────

_CHILD = r'''
import os
import sys
import time
from veritx_dse.application.compile_intent import CompileIntent, derive_compile_request
from veritx_dse.application.store import ResourceStore
from veritx_dse.compiler.candidate_policy import CandidatePolicy, generate_baseline_candidate
from veritx_dse.compiler.canonical import compile_deterministic_candidate

root = sys.argv[1]
gate = sys.argv[2]
intent = CompileIntent(
    name="concurrent", fabric_preset="mesh4", fabric_overrides=(),
    candidate_policy=CandidatePolicy.BASELINE_DETERMINISTIC_V2)
design = derive_compile_request(intent)
plan = generate_baseline_candidate(design=design)
compiled = compile_deterministic_candidate(
    design=design, inventory=plan.inventory, mapping=plan.mapping,
    routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
    settings=plan.compile_settings)
store = ResourceStore(root)
# start-gate: all workers hit the store at the same moment
while not os.path.exists(gate):
    time.sleep(0.005)
store.commit_resolution(intent=intent, design=design,
                        resolved_fabric=compiled.resolved_fabric)
print("ok", intent.intent_id())
'''


def test_concurrent_process_writers_are_idempotent(tmp_path):
    root = tmp_path / "store"
    ResourceStore(root)  # create layout up front
    gate = tmp_path / "start.gate"
    env = {**os.environ, "PYTHONPATH": str(DSE_DIR)}
    workers = 6
    procs = [subprocess.Popen(
        [sys.executable, "-c", _CHILD, str(root), str(gate)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
        for _ in range(workers)]
    gate.write_text("go")
    results = [p.communicate(timeout=180) for p in procs]
    for proc, (out, err) in zip(procs, results):
        assert proc.returncode == 0, err[-2000:]
        assert out.startswith("ok ")
    intent = _intent(name="concurrent")
    bundle = ResourceStore(root).load_committed(intent.intent_id())
    assert bundle.resolution.intent_id == intent.intent_id()
    assert _tmp_files(root) == []
    assert _json_files(root, "resolutions") == [f"{intent.intent_id()}.json"]
    for kind in ("intents", "designs", "resolved", "resolutions"):
        for path in (root / kind).glob("*.json"):
            raw = path.read_bytes()
            assert raw.endswith(b"\n") and not raw.endswith(b"\n\n")
            json.loads(raw.decode())
            assert raw == _canonical_bytes(json.loads(raw.decode()))


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


def test_store_module_source_sentinels():
    source = _docstring_stripped_source(store_module)
    for forbidden in ("pickle", "shelve", "sqlite", "eval(", "exec(",
                      "os.environ", "uuid", "datetime", "time.time",
                      "getenv"):
        assert forbidden not in source, forbidden
    for expected in ("fcntl", "tempfile", "os.replace", "os.fsync",
                     "sort_keys=True"):
        assert expected in source, expected
    modules, _ = _imported_modules(store_module)
    local = {name for name in modules if name.startswith("veritx_dse")}
    assert local == {
        "veritx_dse.application.compile_intent",
        "veritx_dse.application.resources",
        "veritx_dse.model.compile_model",
        "veritx_dse.model.resolved_fabric",
    }
    for forbidden in ("veritx_dse.compiler", "verification", "backend",
                      "simulation", "reports", "cli"):
        assert not any(forbidden in name for name in local), forbidden
    assert "content_id" not in source
    assert "generate_baseline_candidate" not in source
    assert "compile_deterministic_candidate" not in source


def test_store_exposes_only_typed_operations():
    api = {name for name in dir(ResourceStore) if not name.startswith("_")}
    assert {"put_intent", "load_intent_record", "put_design", "load_design",
            "put_resolved", "load_resolved", "put_resolution",
            "load_resolution", "commit_resolution",
            "load_committed"} <= api
    for forbidden in ("put_json", "get_json", "write_path", "namespace",
                      "put_raw", "load_raw"):
        assert forbidden not in api


def test_no_full_compiled_dag_or_provenance_persisted(tmp_path):
    intent, design, resolved = _bundle()
    store = _store(tmp_path)
    store.commit_resolution(intent=intent, design=design,
                            resolved_fabric=resolved)
    root = tmp_path / "store"
    blob = b"".join(p.read_bytes() for p in root.rglob("*.json"))
    for token in (b"topology_hash", b"attachment_hash", b"routing_realization",
                  b"packet_format_hash", b"router_behavior", b"address_decode",
                  b"vc_resource", b"vc_assignment", b"fabric_artifact",
                  b"CompiledFabric", b"compiled_fabric", b"hostname",
                  b"timestamp", b"git_sha", b"run_id", b"git_commit",
                  b"environment", b"pickle"):
        assert token not in blob, token
    # transport wrapper carries only the four resources
    assert {f.name for f in dataclasses.fields(StoredCompileResolution)} == {
        "intent_record", "design", "resolved_fabric", "resolution"}
    assert not hasattr(StoredCompileResolution(intent_record=None,
                                               design=None,
                                               resolved_fabric=None,
                                               resolution=None),
                       "hash")
