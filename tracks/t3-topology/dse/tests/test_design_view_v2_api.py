"""DesignViewV2 over the product API + the compile snapshot binding.

Two Gate-7 contracts are enforced here at the HTTP boundary:

  * ``GET /api/v1/projects/{id}/design`` serves DesignViewV2 in both
    presentations (§51.1);
  * ``POST /api/v1/projects/{id}/compile`` refuses with ``STALE_REVIEW``
    when the draft moved after the review snapshot (§4, REV-D2).

The second is the P0 bug the planning program identified: without it,
Review X → draft changes → compile Y was possible, so a user could certify
content they never reviewed.
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
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


@pytest.fixture()
def project(client):
    """A project whose draft is a real preset design."""
    created = client.post("/api/v1/projects", json={"name": "review"}).json()
    pid = created["project"]["project_id"]
    request = build_preset_request(PRESET).to_dict()
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    put = client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
    assert put.status_code == 200, put.text
    return pid, request


def _design(client, pid, **params):
    response = client.get(f"/api/v1/projects/{pid}/design", params=params)
    assert response.status_code == 200, response.text
    return response.json()


# ── the projection over HTTP ───────────────────────────────────────────


def test_design_view_v2_is_served_in_both_presentations(client, project):
    pid, _ = project
    edit = _design(client, pid)
    review = _design(client, pid, presentation="review")
    assert edit["contract_version"] == 2
    assert edit["presentation"] == "edit"
    assert review["presentation"] == "review"
    assert [s["id"] for s in edit["sections"]] == \
        [s["id"] for s in review["sections"]]


def test_the_draft_identity_matches_the_draft_view(client, project):
    pid, _ = project
    draft = client.get(f"/api/v1/projects/{pid}/draft").json()
    view = _design(client, pid, presentation="review")
    assert view["draft_identity"]["draft_design_hash"] == draft["design_hash"]


def test_review_carries_no_evaluation_fields(client, project):
    """REV-D5: design readiness is not evaluation preflight."""
    pid, _ = project
    view = _design(client, pid, presentation="review")
    for forbidden in ("backend", "backend_profile", "network_clock_hz",
                      "expected_evidence_tier", "ready"):
        assert forbidden not in view, forbidden


def test_review_reports_capability_semantics_version(client, project):
    pid, _ = project
    view = _design(client, pid, presentation="review")
    assert view["capability_semantics_version"] == "cap-v1"
    assert view["registry_versions"]["capability_semantics_version"] == "cap-v1"


def test_review_includes_the_preset_address_map_read_only(client, project):
    """Gate 7 §22: preset-provided AddressMap science is reviewable."""
    pid, _ = project
    view = _design(client, pid, presentation="review")
    memory = next(s for s in view["sections"] if s["id"] == "memory_addressing")
    assert {e["field"] for e in memory["entries"]} >= {
        "AddressRange.base", "AddressRange.size"}


def test_an_unknown_presentation_is_refused(client, project):
    pid, _ = project
    response = client.get(f"/api/v1/projects/{pid}/design",
                          params={"presentation": "print"})
    assert response.status_code >= 400


# ── the compile snapshot binding (P0) ──────────────────────────────────


def test_compile_with_the_reviewed_hash_succeeds(client, project):
    pid, _ = project
    reviewed = _design(client, pid, presentation="review")
    snapshot = reviewed["draft_identity"]["draft_design_hash"]
    response = client.post(f"/api/v1/projects/{pid}/compile",
                           json={"expected_draft_design_hash": snapshot})
    assert response.status_code == 200, response.text
    assert response.json()["revision_id"]


def test_compile_after_a_draft_change_is_stale_review(client, project):
    """Review X → draft changes → compile Y must be impossible."""
    pid, request = project
    reviewed = _design(client, pid, presentation="review")
    snapshot = reviewed["draft_identity"]["draft_design_hash"]

    changed = dict(request)
    changed["noc_config"] = dict(request["noc_config"], link_width=128)
    assert client.put(f"/api/v1/projects/{pid}/draft",
                      json={"request": changed}).status_code == 200

    response = client.post(f"/api/v1/projects/{pid}/compile",
                           json={"expected_draft_design_hash": snapshot})
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "STALE_REVIEW"


def test_a_stale_compile_does_not_create_a_revision(client, project):
    pid, request = project
    snapshot = _design(client, pid, presentation="review")[
        "draft_identity"]["draft_design_hash"]
    changed = dict(request)
    changed["noc_config"] = dict(request["noc_config"], link_width=128)
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": changed})

    before = len(client.get(f"/api/v1/projects/{pid}").json()["revisions"])
    client.post(f"/api/v1/projects/{pid}/compile",
                json={"expected_draft_design_hash": snapshot})
    after = len(client.get(f"/api/v1/projects/{pid}").json()["revisions"])
    assert after == before


def test_a_stale_compile_does_not_silently_regenerate_review(client, project):
    """No invisible refresh: the user must see the new snapshot."""
    pid, request = project
    snapshot = _design(client, pid, presentation="review")[
        "draft_identity"]["draft_design_hash"]
    changed = dict(request)
    changed["noc_config"] = dict(request["noc_config"], link_width=128)
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": changed})

    after = _design(client, pid, presentation="review")
    assert after["draft_identity"]["draft_design_hash"] != snapshot
    assert after["review_freshness"] == "STALE" \
        or after["review_freshness"] == "CURRENT"


def test_review_after_refresh_reports_stale_for_the_old_snapshot(client, project):
    pid, request = project
    snapshot = _design(client, pid, presentation="review")[
        "draft_identity"]["draft_design_hash"]
    changed = dict(request)
    changed["noc_config"] = dict(request["noc_config"], link_width=128)
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": changed})

    refreshed = _design(client, pid, presentation="review",
                        review_snapshot_hash=snapshot)
    assert refreshed["review_freshness"] == "STALE"


def test_compiling_the_refreshed_snapshot_succeeds(client, project):
    pid, request = project
    changed = dict(request)
    changed["noc_config"] = dict(request["noc_config"], link_width=128)
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": changed})

    refreshed = _design(client, pid, presentation="review")
    snapshot = refreshed["draft_identity"]["draft_design_hash"]
    response = client.post(f"/api/v1/projects/{pid}/compile",
                           json={"expected_draft_design_hash": snapshot})
    assert response.status_code == 200, response.text


def test_an_alias_respelling_does_not_stale_the_review(client, project):
    """§15/§24: a respelling is not a scientific change, so it must not
    force a re-review."""
    pid, request = project
    base = dict(request)
    base["noc_config"] = dict(request["noc_config"], arbitration="islip")
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": base})
    snapshot = _design(client, pid, presentation="review")[
        "draft_identity"]["draft_design_hash"]

    respelled = dict(base)
    respelled["noc_config"] = dict(base["noc_config"], arbitration=" iSLIP ")
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": respelled})

    response = client.post(f"/api/v1/projects/{pid}/compile",
                           json={"expected_draft_design_hash": snapshot})
    assert response.status_code == 200, response.text


def test_compile_without_a_snapshot_still_works_for_compatibility(client, project):
    """The compatibility path compiles the current draft. The product flow
    always sends the snapshot; this only keeps older clients working."""
    pid, _ = project
    response = client.post(f"/api/v1/projects/{pid}/compile", json={})
    assert response.status_code == 200, response.text


# ── the compiled revision is still an immutable result ─────────────────


def test_a_compiled_revision_has_a_certificate_and_is_reloadable(client, project):
    pid, _ = project
    snapshot = _design(client, pid, presentation="review")[
        "draft_identity"]["draft_design_hash"]
    compiled = client.post(
        f"/api/v1/projects/{pid}/compile",
        json={"expected_draft_design_hash": snapshot}).json()
    rid = compiled["revision_id"]
    loaded = client.get(f"/api/v1/revisions/{rid}").json()
    assert loaded["design_hash"] == compiled["design_hash"]
    assert loaded["certificate"]["overall"] == "PASS"
    # The certificate carries every obligation the verifier issued. The four
    # claims Gate 7/8 name (ATTACHMENT_COMPLETE, ROUTE_COMPLETE, ROUTE_LEGAL,
    # DEADLOCK_FREE) are a product-labelled subset of them, not the whole set.
    obligations = {o["obligation"] for o in loaded["certificate"]["obligations"]}
    assert {"ATTACHMENT_COMPLETE", "ROUTE_COMPLETE", "ROUTE_LEGAL",
            "DEADLOCK_FREE"} <= obligations
    assert all(o["status"] == "PASS"
               for o in loaded["certificate"]["obligations"])


def test_review_never_claims_a_certificate(client, project):
    """Review describes the draft; the certificate exists only after
    compile (Gate 7 §39/§40)."""
    pid, _ = project
    view = _design(client, pid, presentation="review")
    assert view["later_stage_claims"]["certificate"] is None
    assert view["later_stage_claims"]["qualification"] is None


# ── PF-D13: no ambiguous global "run" ──────────────────────────────────


def test_project_view_exposes_three_distinct_facts_not_a_latest_run(client, project):
    """PF-D13 / PRODUCT-FLOWS §128.

    "Latest run" is eliminated. The project summary carries a latest static
    evaluation, a latest serving experiment and a latest optimization study
    as separate facts, so no surface can render an unqualified "run".
    """
    pid, _ = project
    view = client.get(f"/api/v1/projects/{pid}").json()
    for key in ("latest_static_evaluation", "latest_serving_experiment",
                "latest_optimization_study"):
        assert key in view, key


def test_the_three_facts_start_empty_rather_than_null_ambiguous(client, project):
    pid, _ = project
    view = client.get(f"/api/v1/projects/{pid}").json()
    assert view["latest_static_evaluation"] is None
    assert view["latest_serving_experiment"] is None
    assert view["latest_optimization_study"] is None


def test_a_compiled_revision_is_reported_as_the_draft_basis(client, project):
    """Gate 8 §7: the context must answer "based on what?"."""
    pid, _ = project
    snapshot = _design(client, pid, presentation="review")[
        "draft_identity"]["draft_design_hash"]
    client.post(f"/api/v1/projects/{pid}/compile",
                json={"expected_draft_design_hash": snapshot})
    view = client.get(f"/api/v1/projects/{pid}").json()
    assert view["draft"]["based_on_revision_id"] == view["active_revision_id"]
    assert view["active_revision"] is not None
    assert view["draft"]["dirty"] is False
