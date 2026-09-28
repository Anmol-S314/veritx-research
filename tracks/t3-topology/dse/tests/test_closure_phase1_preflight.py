"""Phase-1 RC-01 regression: revision_preflight derives support and profile
from the federation planner without crashing, and reports support and
readiness as distinct verdicts.

A. The historical defect consumed ``profile_id``/``profile_reason`` before
   initialization, so preflight raised UnboundLocalError exactly when a
   backend WAS configured (the unconfigured path short-circuited). These
   tests configure the backend and demand a 200 with a derived profile.
B. The catalog exposes the support/readiness split for a representable
   workload independently of backend presence.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from veritx_dse.core.paths import REPO
from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.simulation.booksim import find_booksim_bin

WORKLOAD = "llama-dense-8b-64tiles"


def _client(tmp_path: Path, with_backend: bool) -> TestClient:
    if with_backend:
        try:
            binary = find_booksim_bin(REPO)
        except FileNotFoundError:
            pytest.skip("no BookSim binary in this environment")
    else:
        binary = os.environ.get("VERITX_BOOKSIM_BIN")
        binary = Path(binary) if binary else None
    cfg = GatewayConfig(
        store_root=tmp_path / "store", runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects",
        booksim_bin=Path(binary) if binary else None,
        timeout_s=600)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _certified_revision(client: TestClient) -> str:
    project = client.post(
        "/api/v1/projects",
        json={"name": "preflight", "workload_id": WORKLOAD}).json()
    pid = project["project"]["project_id"]
    assert client.post(f"/api/v1/projects/{pid}/compile").status_code == 200
    project = client.get(f"/api/v1/projects/{pid}").json()
    return project["active_revision_id"]


def test_preflight_with_configured_backend_does_not_crash(tmp_path):
    """RC-01: the configured-backend path used to die with
    UnboundLocalError before the gates were even built. It must return
    a full PreflightView with the adapter's own derived profile, and
    ready/reason must stay consistent whatever the producer state is."""
    client = _client(tmp_path, with_backend=True)
    rid = _certified_revision(client)
    resp = client.get(f"/api/v1/revisions/{rid}/preflight")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    gates = {g["gate"]: g for g in body["gates"]}
    assert set(gates) == {"compilation", "certificate", "backend",
                          "producer_qualification"}
    assert gates["compilation"]["state"] == "READY"
    assert gates["certificate"]["state"] == "READY"
    # The design is representable, so the backend gate names the real
    # derived profile instead of refusing or crashing.
    assert gates["backend"]["state"] == "READY", gates["backend"]
    assert body["backend_profile"], body
    # Producer truth, not presence: QUALIFIED only with a pinned
    # producer; anything else keeps ready False with the exact reason.
    assert gates["producer_qualification"]["state"] in (
        "QUALIFIED", "NOT_QUALIFIED")
    if gates["producer_qualification"]["state"] == "QUALIFIED":
        assert body["ready"] is True
        assert body["reason"] is None
    else:
        assert body["ready"] is False
        assert body["reason"], body
        assert "producer" in body["reason"].lower()


def test_catalog_splits_support_from_readiness(tmp_path):
    """RC-02: a representable workload reports SUPPORTED support even
    with no backend configured; readiness carries the execution truth
    separately, and the legacy boolean stays a pure representability
    derivation."""
    client = _client(tmp_path, with_backend=False)
    catalog = client.get("/api/v1/catalog/workloads").json()
    dense = next(w for w in catalog["workloads"]
                 if w["workload_id"] == WORKLOAD)
    assert dense["evaluation_support"] == "SUPPORTED"
    assert dense["evaluation_supported"] is True
    assert dense["evaluation_readiness"] in (
        "READY", "BLOCKED", "UNAVAILABLE")
