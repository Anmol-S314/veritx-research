"""CompileResultView (Gate 5 §97, Gate 8 §50–§63).

Seven inspector groups under one Compile Result, materialized at
certification time and frozen with the revision. The tests below are the
contracts the inspectors must not break:

  * the seven groups exist, in order, and none is editable;
  * the certificate exposes the four product claims **and** every
    obligation the verifier issued — the four are a subset, so hiding the
    other six would hide proof the certificate relied on;
  * expected and observed are never merged: a compiled revision has no
    runtime execution, so it has no observation;
  * the canonical route is a query over frozen data that terminates in
    LOCAL_EJECTION;
  * semantic zoom thresholds are declared, not implicit.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.application.compile_intent import (  # noqa: E402
    build_preset_request,
)
from veritx_dse.application.compile_result_view import (  # noqa: E402
    FULL_DETAIL_ROUTERS,
    GROUPS,
    MAX_DETAIL_ROUTERS,
    OBSERVATION_CLAIM,
    OBSERVATION_LIMIT,
    OBSERVATION_SCOPE,
    PRODUCT_CLAIMS,
    build_compile_result,
    canonical_route,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.views import (  # noqa: E402
    artifact_chain_view,
    topology_view,
)
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

PRESET = "mesh4_hbm"


@pytest.fixture()
def compiled():
    compilation = FabricCompiler().compile(build_preset_request(PRESET))
    revision = {
        "revision_id": "p-r01",
        "display_name": "r01",
        "created_at": "2026-09-26T19:20:00Z",
        "design_hash": compilation.request.design_hash(),
        "compilation": {
            "compiler_semantics_version":
                compilation.request.compiler_semantics_version,
        },
        "certificate": {
            "certificate_id": compilation.certificate.certificate_id(),
        },
    }
    return build_compile_result(
        revision, compilation,
        topology_view(compilation, revision_id="p-r01"),
        artifact_chain_view(compilation))


@pytest.fixture()
def client(tmp_path):
    config = GatewayConfig(store_root=tmp_path / "store",
                           runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(config), raise_server_exceptions=False)


@pytest.fixture()
def revision_id(client):
    created = client.post("/api/v1/projects", json={"name": "p2"}).json()
    pid = created["project"]["project_id"]
    request = build_preset_request(PRESET).to_dict()
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
    snapshot = client.get(f"/api/v1/projects/{pid}/design",
                          params={"presentation": "review"}).json()
    compiled = client.post(
        f"/api/v1/projects/{pid}/compile",
        json={"expected_draft_design_hash":
              snapshot["draft_identity"]["draft_design_hash"]})
    assert compiled.status_code == 200, compiled.text
    return compiled.json()["revision_id"]


# ── shape ──────────────────────────────────────────────────────────────


def test_the_seven_groups_exist_in_order(compiled):
    assert tuple(compiled["groups"]) == GROUPS or \
        set(compiled["groups"]) == set(GROUPS)
    assert compiled["group_order"] == list(GROUPS)
    assert len(GROUPS) == 7


def test_no_group_is_editable(compiled):
    """Inspectors reveal canonical properties. There is no edit control."""
    for name, group in compiled["groups"].items():
        assert group.get("editable") is not True, name
    blob = json.dumps(compiled)
    for token in ("onChange", "editableFields", "canEdit"):
        assert token not in blob


def test_the_payload_is_pure_data(compiled):
    """The revision is persisted as JSON, so it can hold no callable."""
    json.dumps(compiled)


def test_a_refused_revision_has_no_compile_result(client, tmp_path):
    """A failed proof is not a fabric: no inspectors exist."""
    created = client.post("/api/v1/projects", json={"name": "p"}).json()
    pid = created["project"]["project_id"]
    request = build_preset_request(PRESET).to_dict()
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    # An address range targeting a compute-tile group is infeasible.
    request["address_map"]["ranges"][0]["target_agent_idx"] = 0
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
    client.post(f"/api/v1/projects/{pid}/compile", json={})
    project = client.get(f"/api/v1/projects/{pid}").json()
    attempt = project["latest_attempt"]
    assert attempt is not None
    assert attempt["compilation_status"] != "COMPILED"
    payload = client.get(
        f"/api/v1/revisions/{attempt['revision_id']}/compile-result").json()
    assert payload["available"] is False
    assert payload["reason"]


# ── the certificate: four claims over ten obligations ──────────────────


def test_the_certificate_exposes_the_four_product_claims(compiled):
    claims = compiled["certificate"]["claims"]
    assert [c["claim"] for c in claims] == [n for n, _ in PRODUCT_CLAIMS]
    for claim in claims:
        assert claim["status"] in ("PASS", "FAIL", "UNSUPPORTED")
        assert claim["scope"]


def test_the_four_claims_carry_the_planning_scope_sentences(compiled):
    scopes = {c["claim"]: c["scope"] for c in compiled["certificate"]["claims"]}
    assert scopes["ATTACHMENT_COMPLETE"] == "every declared agent is attached"
    assert scopes["DEADLOCK_FREE"] == "the channel-VC CDG is acyclic"


def test_every_obligation_is_exposed_not_only_the_named_claims(compiled):
    """The four claims are a subset; the proof is all ten."""
    certificate = compiled["certificate"]
    assert certificate["obligation_count"] == len(certificate["obligations"])
    assert certificate["obligation_count"] > certificate["claim_count"]
    named = {n for n, _ in PRODUCT_CLAIMS}
    additional = {o["obligation"]
                  for o in certificate["additional_obligations"]}
    assert named | additional == {
        o["obligation"] for o in certificate["obligations"]}
    assert not (named & additional)


def test_no_obligation_is_hidden(compiled):
    obligations = {o["obligation"] for o in compiled["certificate"]["obligations"]}
    assert obligations == {
        "TOPOLOGY_CONNECTED", "ATTACHMENT_COMPLETE", "ADDRESS_DECODE_VALID",
        "ROUTE_COMPLETE", "ROUTE_LEGAL", "VC_ASSIGNMENT_VALID",
        "DEADLOCK_FREE", "MAPPING_VALID", "PACKET_FORMAT_VALID",
        "FABRIC_DAG_VALID"}


# ── expected vs observed (Gate 8 §58/§59) ──────────────────────────────


def test_a_compiled_revision_reports_no_runtime_observation(compiled):
    """There is no runtime execution, so there is no observation.

    The certificate's `route_realization` is the artifact's encoding scheme
    (`v2_channel_id`), not an observation — presenting it as one would
    claim a runtime fact that does not exist.
    """
    observation = compiled["groups"]["routing"]["observation"]
    assert observation["available"] is False
    assert observation["reason"]
    assert "evaluation run" in observation["source"]


def test_the_observation_carries_the_exact_gate4_wording(compiled):
    observation = compiled["groups"]["routing"]["observation"]
    assert observation["scope"] == OBSERVATION_SCOPE == "FIRST_HOP"
    assert observation["claim"] == OBSERVATION_CLAIM
    assert observation["limit"] == OBSERVATION_LIMIT
    assert "not observed packet paths" in observation["limit"]


def test_expected_and_observed_are_separate_facts(compiled):
    routing = compiled["groups"]["routing"]
    assert "observation" in routing
    assert "observation_note" in routing
    assert "DERIVED EXPECTED" in routing["observation_note"]


# ── the canonical route walk (Gate 8 §58) ──────────────────────────────


def test_the_route_walk_produces_a_real_path(compiled):
    routing = compiled["groups"]["routing"]
    route = canonical_route(routing, "DOR_XY", 0, 8)
    assert route["terminates"] is True
    assert route["terminal"] == "LOCAL_EJECTION"
    assert route["routers"][0] == 0
    assert route["routers"][-1] == 8
    assert len(route["routers"]) > 1
    assert len(route["hops"]) == len(route["routers"]) - 1


def test_the_route_walk_shows_local_ejection_for_a_self_route(compiled):
    route = canonical_route(compiled["groups"]["routing"], "DOR_XY", 3, 3)
    assert route["routers"] == [3]
    assert route["terminal"] == "LOCAL_EJECTION"


def test_the_route_walk_is_reversible_on_a_mesh(compiled):
    routing = compiled["groups"]["routing"]
    forward = canonical_route(routing, "DOR_XY", 0, 8)["routers"]
    backward = canonical_route(routing, "DOR_XY", 8, 0)["routers"]
    assert forward[0] == backward[-1] and forward[-1] == backward[0]


def test_the_route_walk_reports_an_unknown_class_instead_of_guessing(compiled):
    route = canonical_route(compiled["groups"]["routing"], "NOPE", 0, 8)
    assert route["terminates"] is False
    assert "no entry" in route["reason"]


def test_every_route_entry_resolves_to_a_real_channel(compiled):
    routing = compiled["groups"]["routing"]
    channels = {row["channel_id"] for row in routing["channel_hops"]}
    assert all(row["channel_id"] in channels for row in routing["entries"])


# ── semantic zoom (Gate 8 §57) ─────────────────────────────────────────


def test_the_fabric_group_declares_its_zoom_thresholds(compiled):
    fabric = compiled["groups"]["fabric"]
    assert fabric["detail_thresholds"] == {
        "full_detail_max": FULL_DETAIL_ROUTERS,
        "router_detail_max": MAX_DETAIL_ROUTERS,
    }
    assert FULL_DETAIL_ROUTERS == 64
    assert MAX_DETAIL_ROUTERS == 256


def test_a_small_fabric_gets_full_detail(compiled):
    fabric = compiled["groups"]["fabric"]
    assert fabric["counts"]["routers"] <= FULL_DETAIL_ROUTERS
    assert fabric["detail_level"] == "FULL"


def test_the_fabric_group_reports_occupancy(compiled):
    counts = compiled["groups"]["fabric"]["counts"]
    assert counts["routers"] > 0
    assert counts["channels"] > 0
    assert counts["seats"] >= counts["attached"]
    assert counts["unused_seats"] == counts["seats"] - counts["attached"]


def test_the_fabric_group_carries_the_compiled_topology(compiled):
    """Gate 8 §35: the inspector draws the COMPILED artifact, not a preview."""
    fabric = compiled["groups"]["fabric"]
    assert fabric["topology"] is not None
    assert fabric["topology"]["topology_hash"]


# ── mapping (Gate 8 §53/§54) ───────────────────────────────────────────


def test_mapping_is_table_first_with_stable_identity(compiled):
    mapping = compiled["groups"]["mapping"]
    assert mapping["available"] is True
    assert mapping["rows"]
    for row in mapping["rows"]:
        assert isinstance(row["rank"], int)
        assert row["agent_kind"]
        assert "endpoint_id" in row


def test_mapping_rows_are_never_edited(compiled):
    blob = json.dumps(compiled["groups"]["mapping"])
    assert "input" not in blob


# ── resources (Gate 8 §60/§61) ─────────────────────────────────────────


def test_the_vc_inspector_reports_bindings_and_transitions(compiled):
    resources = compiled["groups"]["resources"]
    assert resources["vc_count"] >= 1
    assert resources["traffic_class_to_vcs"]
    assert resources["vc_to_routing_class"]
    assert isinstance(resources["transitions_are_identity"], bool)
    assert resources["editable"] is False


def test_the_deadlock_inspector_carries_the_cdg_witness(compiled):
    deadlock = compiled["groups"]["resources"]["deadlock"]
    assert deadlock["status"] in ("PASS", "FAIL", "UNSUPPORTED")
    witness = deadlock["witness"]
    assert witness["acyclic"] is not None
    assert witness["node_count"] is not None
    assert witness["edge_count"] is not None
    assert witness["sccs_gt_1"] is not None
    assert witness["route_realization_scheme"]


def test_arbitration_is_one_canonical_policy_not_two(compiled):
    """One field — never a VC allocator + a switch allocator as separate
    user concepts."""
    arbitration = compiled["groups"]["resources"]["arbitration"]
    assert arbitration["vc_allocator"] == arbitration["switch_allocator"]
    assert arbitration["vc_allocator"] == "islip"


def test_enums_are_projected_as_values_not_python_reprs(compiled):
    blob = json.dumps(compiled["groups"]["resources"])
    assert "AllocatorPolicy" not in blob
    assert "FlowControlProtocol" not in blob


# ── address decode (Gate 7 §23) ────────────────────────────────────────


def test_address_decode_presents_the_stable_target_identity(compiled):
    rows = compiled["groups"]["address_decode"]["rows"]
    assert rows
    for row in rows:
        assert row["name"]
        assert row["target_agent_kind"]
        assert row["target_endpoint_id"] is not None
        # The legacy positional index is technical detail, never the label.
        assert "legacy_target_agent_group" in row


def test_address_decode_targets_a_memory_agent(compiled):
    rows = compiled["groups"]["address_decode"]["rows"]
    assert any(row["target_agent_kind"] == "hbm_controller" for row in rows)


# ── summary (Gate 8 §52) ───────────────────────────────────────────────


def test_the_summary_separates_declared_derived_and_verified(compiled):
    summary = compiled["groups"]["summary"]
    assert set(summary) >= {"declared", "derived", "verified"}
    assert summary["derived"]["routers"] > 0
    assert summary["derived"]["channels"] > 0
    assert [c["claim"] for c in summary["verified"]] == \
        [n for n, _ in PRODUCT_CLAIMS]


def test_the_summary_uses_the_product_name_for_side_length(compiled):
    """§16: `radix` is the implementation field; the product says side
    length."""
    declared = compiled["groups"]["summary"]["declared"]
    assert "side_length" in declared
    assert "radix" not in declared


def test_the_summary_does_not_duplicate_design_review(compiled):
    """Gate 8 §52: the summary is derived facts, not the review."""
    blob = json.dumps(compiled["groups"]["summary"])
    for token in ("sections", "completeness", "scientific_diff",
                  "review_freshness"):
        assert token not in blob


# ── provenance (Gate 8 §115/§116) ──────────────────────────────────────


def test_provenance_carries_every_artifact_hash(compiled):
    provenance = compiled["groups"]["provenance"]
    hashes = provenance["artifact_hashes"]
    for expected in ("design_hash", "topology_hash", "fabric_hash",
                     "resolved_fabric_hash", "vc_assignment_hash"):
        assert expected in hashes, expected
        assert hashes[expected].startswith("sha256:")


def test_provenance_links_the_artifact_chain(compiled):
    assert compiled["groups"]["provenance"]["artifact_chain"] is not None


# ── over HTTP ──────────────────────────────────────────────────────────


def test_the_compile_result_is_served_for_a_compiled_revision(client,
                                                              revision_id):
    payload = client.get(
        f"/api/v1/revisions/{revision_id}/compile-result").json()
    assert payload["available"] is True
    assert payload["certificate"]["claim_count"] == 4
    assert payload["certificate"]["obligation_count"] == 10


def test_the_route_endpoint_walks_the_frozen_table(client, revision_id):
    response = client.get(f"/api/v1/revisions/{revision_id}/route",
                          params={"src": 0, "dst": 8})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["routers"][0] == 0
    assert body["routers"][-1] == 8
    assert body["terminal"] == "LOCAL_EJECTION"


def test_the_route_endpoint_defaults_to_a_real_route(client, revision_id):
    body = client.get(f"/api/v1/revisions/{revision_id}/route").json()
    assert body["routing_class"]
    assert body["routers"]
    assert body["terminates"] is True


def test_the_route_endpoint_refuses_an_unknown_class(client, revision_id):
    response = client.get(f"/api/v1/revisions/{revision_id}/route",
                          params={"routing_class": "NOPE"})
    assert response.status_code == 400
    assert response.json()["code"] == "INVALID_INTENT"


def test_the_compile_result_payload_is_json_over_the_wire(client,
                                                          revision_id):
    response = client.get(f"/api/v1/revisions/{revision_id}/compile-result")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
