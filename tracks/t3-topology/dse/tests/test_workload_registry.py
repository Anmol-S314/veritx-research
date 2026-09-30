"""Workload registry — workloads as data (veritx.workload-registry/1)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.product.service import ProductConfig, ProductService
from veritx_dse.product.workload_registry import (
    BUILTIN_WORKLOADS,
    REGISTRY_REL,
    REGISTRY_SCHEMA,
    WorkloadRegistryError,
    load_registry,
    materialize,
    registry_path,
    resolve,
)

SHIPPED_ID = "astr-llm-70b-tp4"
V4_DOC = REPO / "tracks/t3-topology/examples/astr_llm_70b_tp4-v4.json"
PROFILE = REPO / "tracks/t3-topology/examples/profiles/astr-llm-70b-profile.json"

def _write_registry(repo: Path, workloads: list) -> None:
    path = repo / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": REGISTRY_SCHEMA,
                                "workloads": workloads}))

def _entry(**over):
    base = {
        "workload_id": "cust-1",
        "path": "tracks/t3-topology/examples/astr_llm_70b_tp4-v4.json",
        "display_name": "Customer 1",
        "description": "a customer workload",
    }
    base.update(over)
    return base

def test_builtins_load_when_no_registry_file_exists(tmp_path):
    entries = load_registry(tmp_path)
    assert [e.workload_id for e in entries] == [t[0] for t in BUILTIN_WORKLOADS]
    assert all(e.origin == "builtin" for e in entries)
    assert not registry_path(tmp_path).exists()

def test_an_empty_registry_is_valid_and_adds_nothing(tmp_path):
    _write_registry(tmp_path, [])
    assert len(load_registry(tmp_path)) == len(BUILTIN_WORKLOADS)

def test_shipped_registry_adds_the_customer_workload():
    entry = resolve(REPO, SHIPPED_ID)
    assert entry is not None and entry.origin == "registry"
    assert entry.profile is not None and entry.owners == 4

def test_shipped_customer_compute_is_derived_from_its_profile():
    entry = resolve(REPO, SHIPPED_ID)
    doc = materialize(entry, REPO)
    stages = doc["compute"]["stages"]
    assert len(stages) == 4
    assert sum(s["duration_ns"] for s in stages) == 553300
    assert {s["owner"] for s in stages} <= {0, 1, 2, 3}

def test_customer_workload_is_compilable_and_certifies(tmp_path):
    svc = ProductService(ProductConfig(projects_root=tmp_path / "p"))
    catalog = svc.workload_catalog()["workloads"]
    ids = [w["workload_id"] for w in catalog]
    assert SHIPPED_ID in ids
    entry = next(w for w in catalog if w["workload_id"] == SHIPPED_ID)
    assert entry["evaluation_support"] == "SUPPORTED"
    revision = svc.compile_draft(
        svc.create_project(name="cust", workload_id=SHIPPED_ID)
        ["project"]["project_id"])
    assert revision["compilation"]["status"] == "COMPILED"
    assert revision["compilation"]["certificate_overall"] == "PASS"

def test_duplicate_id_never_shadows_a_shipped_workload(tmp_path):
    _write_registry(tmp_path, [_entry(workload_id=BUILTIN_WORKLOADS[0][0])])
    with pytest.raises(WorkloadRegistryError, match="duplicate workload_id"):
        load_registry(tmp_path)

def test_unknown_keys_refuse(tmp_path):
    _write_registry(tmp_path, [_entry(surprise=1)])
    with pytest.raises(WorkloadRegistryError, match="unknown fields"):
        load_registry(tmp_path)
    path = tmp_path / REGISTRY_REL
    path.write_text(json.dumps({"schema": REGISTRY_SCHEMA, "workloads": [],
                                "extra": True}))
    with pytest.raises(WorkloadRegistryError, match="unknown fields"):
        load_registry(tmp_path)

def test_wrong_or_absent_schema_refuses(tmp_path):
    path = tmp_path / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"workloads": []}))
    with pytest.raises(WorkloadRegistryError, match="schema must be"):
        load_registry(tmp_path)

def test_entry_fields_are_validated(tmp_path):
    _write_registry(tmp_path, [_entry(display_name="")])
    with pytest.raises(WorkloadRegistryError, match="display_name"):
        load_registry(tmp_path)
    _write_registry(tmp_path, [_entry(owners=0)])
    with pytest.raises(WorkloadRegistryError, match="owners"):
        load_registry(tmp_path)

def test_invalid_json_refuses(tmp_path):
    path = tmp_path / REGISTRY_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{oops")
    with pytest.raises(WorkloadRegistryError, match="invalid JSON"):
        load_registry(tmp_path)

def test_profile_only_attaches_to_a_v4_request(tmp_path, monkeypatch):
    entry = resolve(REPO, SHIPPED_ID)
    v3 = REPO / "tracks/t3-topology/examples/qwen3_32b_tp2_16tiles-v3.json"
    import dataclasses
    broken = dataclasses.replace(entry, path=str(v3.relative_to(REPO)))
    with pytest.raises(WorkloadRegistryError, match="must be a v4 request"):
        materialize(broken, REPO)

def test_a_missing_workload_document_refuses(tmp_path):
    entry = resolve(REPO, SHIPPED_ID)
    import dataclasses
    broken = dataclasses.replace(entry, path="tracks/t3-topology/examples/nope.json")
    with pytest.raises(WorkloadRegistryError, match="missing"):
        materialize(broken, REPO)

def test_an_incomplete_profile_refuses_rather_than_emitting_blank_stages(tmp_path):
    entry = resolve(REPO, SHIPPED_ID)
    import dataclasses
    partial = dataclasses.replace(
        entry,
        profile=("tracks/t3-topology/examples/profiles/"
                 "astr-llm-70b-profile-partial.json"))
    from veritx_dse.performance.model_profile import ModelProfileError
    with pytest.raises(ModelProfileError, match="unavailable"):
        materialize(partial, REPO)

def test_plain_entries_return_the_document_verbatim():
    entry = resolve(REPO, BUILTIN_WORKLOADS[0][0])
    doc = materialize(entry, REPO)
    original = json.loads(
        (REPO / BUILTIN_WORKLOADS[0][1]).read_text())
    assert doc == original
