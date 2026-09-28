"""RevisionDiffView — DESIGN / DERIVED / CAPABILITY changes.

The diff is a stable projection over two FROZEN CompileResultView payloads:
it compares fields, never recompiles, never re-derives. Contracts:

  * the first revision of a project has no basis (has_basis False + reason,
    not an error);
  * an identical recompile diffs empty;
  * a changed declared field appears in DESIGN CHANGES;
  * cross-project `against` is refused;
  * preflight liveness never leaks into the diff (capability changes come
    from frozen capability consequences + certificate overall only).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.application.compile_intent import (  # noqa: E402
    build_preset_request,
)
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

PRESET = "mesh4_hbm"


@pytest.fixture()
def client(tmp_path):
    config = GatewayConfig(store_root=tmp_path / "store",
                           runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(config), raise_server_exceptions=False)


def _compile(client, pid, mutate=None):
    request = build_preset_request(PRESET).to_dict()
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    if mutate:
        mutate(request)
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
    snapshot = client.get(f"/api/v1/projects/{pid}/design",
                          params={"presentation": "review"}).json()
    compiled = client.post(
        f"/api/v1/projects/{pid}/compile",
        json={"expected_draft_design_hash":
              snapshot["draft_identity"]["draft_design_hash"]})
    assert compiled.status_code == 200, compiled.text
    return compiled.json()["revision_id"]


@pytest.fixture()
def two_revisions(client):
    pid = client.post("/api/v1/projects", json={"name": "p2"}).json(
    )["project"]["project_id"]
    r1 = _compile(client, pid)

    def wider(request):
        # The preset leaves link_width as a semantic default (None);
        # declaring it explicitly is a real intent change that compiles.
        request["noc_config"]["link_width"] = 128

    r2 = _compile(client, pid, mutate=wider)
    return pid, r1, r2


def test_first_revision_has_no_basis(client):
    pid = client.post("/api/v1/projects", json={"name": "p1"}).json(
    )["project"]["project_id"]
    r1 = _compile(client, pid)
    diff = client.get(f"/api/v1/revisions/{r1}/diff").json()
    assert diff["contract_version"] == 1
    assert diff["has_basis"] is False
    assert diff["against_revision_id"] is None
    assert diff["reason"]
    assert diff["design_changes"] == []
    assert diff["derived_changes"] == []
    assert diff["capability_changes"] == []


def test_changed_declared_field_appears_in_design_changes(client,
                                                         two_revisions):
    _, r1, r2 = two_revisions
    diff = client.get(f"/api/v1/revisions/{r2}/diff").json()
    assert diff["has_basis"] is True
    assert diff["against_revision_id"] == r1
    fields = [row["field"] for row in diff["design_changes"]]
    assert "link_width" in fields
    row = next(r for r in diff["design_changes"]
               if r["field"] == "link_width")
    assert row["kind"] in ("added", "changed")
    assert row["before"] != row["after"]
    assert row["after"] == 128


def test_explicit_against_selects_basis(client, two_revisions):
    _, r1, r2 = two_revisions
    diff = client.get(f"/api/v1/revisions/{r2}/diff",
                      params={"against": r1}).json()
    assert diff["against_revision_id"] == r1
    assert diff["against_display_name"]


def test_cross_project_against_is_refused(client, two_revisions):
    _, _, r2 = two_revisions
    other = client.post("/api/v1/projects", json={"name": "other"}).json(
    )["project"]["project_id"]
    ro = _compile(client, other)
    resp = client.get(f"/api/v1/revisions/{r2}/diff", params={"against": ro})
    assert resp.status_code in (400, 409, 422), resp.text


def test_unknown_revision_is_not_found(client, two_revisions):
    _, _, r2 = two_revisions
    resp = client.get(f"/api/v1/revisions/{r2}/diff",
                      params={"against": "r-does-not-exist"})
    assert resp.status_code == 404, resp.text
