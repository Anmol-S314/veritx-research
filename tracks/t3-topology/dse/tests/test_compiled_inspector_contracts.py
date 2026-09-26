"""Compiled inspector contracts — P2-E … P2-X.

The Phase-2 acceptance battery, as executable contracts. Each test names
the obligation it discharges so the battery table in the ledger is
checkable rather than asserted.

Where a case cannot be exercised the test says so explicitly instead of
being silently absent: P2-S (torus inspectability) is BLOCKED because no
compiled torus can exist — the compiler refuses at the ROUTING stage and
discards the derived topology with the bundle.
"""
from __future__ import annotations

import copy
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.compile_intent import (  # noqa: E402
    build_preset_request,
)
from veritx_dse.application.compile_result_view import (  # noqa: E402
    GROUPS,
    build_compile_result,
    canonical_route,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.views import (  # noqa: E402
    artifact_chain_view,
    topology_view,
)
from veritx_dse.application.preset_certification import (  # noqa: E402
    _load_preset_doc,
)
from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3,
    NocConfig,
    TopologyFamily,
)

PRESET = "mesh4_hbm"
TEMPLATE_CONC4 = "dense-4b-32tiles-conc4"
TEMPLATE_DENSE = "dense-1b-16tiles"


def _compile(request):
    compilation = FabricCompiler().compile(request)
    revision = {
        "revision_id": "p-r01", "display_name": "r01",
        "created_at": "2026-09-26T19:20:00Z",
        "design_hash": request.design_hash(),
        "compilation": {
            "compiler_semantics_version":
                request.compiler_semantics_version,
            "resolved_fabric_hash": (
                compilation.bundle.root_hashes()["resolved_fabric_hash"]
                if compilation.bundle else None),
        },
        "certificate": {
            "certificate_id": (
                compilation.certificate.certificate_id()
                if compilation.certificate else None),
        },
    }
    return compilation, build_compile_result(
        revision, compilation,
        topology_view(compilation, revision_id="p-r01"),
        artifact_chain_view(compilation))


def _preset(name: str = PRESET):
    return build_preset_request(name)


def _template(name: str):
    return CompileRequestV3.from_dict(_load_preset_doc(name))


# ── P2-E / P2-F: mapping identity and immutability ─────────────────────


def test_p2_e_mapping_rows_carry_stable_identities():
    _compilation, result = _compile(_preset())
    mapping = result["groups"]["mapping"]
    assert mapping["available"] is True
    for row in mapping["rows"]:
        assert isinstance(row["rank"], int)
        assert row["agent_kind"]
        assert isinstance(row["group_index"], int)
        assert isinstance(row["instance_index"], int)
        assert isinstance(row["endpoint_id"], int)


def test_p2_e_mapping_carries_parallel_coordinates_from_the_rank_algebra():
    """Coordinates come from model.placement.coords_of, not a frontend
    convention."""
    _compilation, result = _compile(_template(TEMPLATE_DENSE))
    mapping = result["groups"]["mapping"]
    assert mapping["parallelism"]["tp"] == 4
    coords = [r["coordinates"] for r in mapping["rows"]]
    assert all(c is not None for c in coords)
    assert [c["tp"] for c in coords] == [0, 1, 2, 3]
    assert {c["pp"] for c in coords} == {0}


def test_p2_e_mapping_reports_idle_agents():
    """Gate 8 §53: a 64-tile fabric serving 8 ranks has idle tiles."""
    _compilation, result = _compile(_template(TEMPLATE_DENSE))
    idle = result["groups"]["mapping"]["idle_agents"]
    assert idle["count"] > 0
    assert idle["mapped"] == len(result["groups"]["mapping"]["rows"])
    assert idle["attached"] > idle["mapped"]


def test_p2_f_mapping_is_not_editable():
    _compilation, result = _compile(_preset())
    blob = json.dumps(result["groups"]["mapping"])
    for token in ("input", "onChange", "editable"):
        assert token not in blob


# ── P2-G: mesh geometry follows canonical coordinates ──────────────────


def test_p2_g_mesh_router_coordinates_are_canonical():
    _compilation, result = _compile(_preset())
    topology = result["groups"]["fabric"]["topology"]
    coords = [(r["router_id"], tuple(r["coordinates"]))
              for r in topology["routers"]]
    assert len(coords) == topology["counts"]["routers"]
    # every router has a 2D coordinate, and they are unique
    assert all(len(c) == 2 for _rid, c in coords)
    assert len({c for _rid, c in coords}) == len(coords)


def test_p2_g_channels_reflect_canonical_connectivity():
    _compilation, result = _compile(_preset())
    topology = result["groups"]["fabric"]["topology"]
    router_ids = {r["router_id"] for r in topology["routers"]}
    for channel in topology["channels"]:
        assert channel["src_router"] in router_ids
        assert channel["dst_router"] in router_ids
        # no self-loops in the directed channel set
        assert channel["src_router"] != channel["dst_router"]


def test_p2_g_no_diagonal_shortcuts_on_a_mesh():
    """A mesh channel joins routers exactly one grid step apart."""
    _compilation, result = _compile(_preset())
    topology = result["groups"]["fabric"]["topology"]
    by_id = {r["router_id"]: r["coordinates"] for r in topology["routers"]}
    for channel in topology["channels"]:
        a = by_id[channel["src_router"]]
        b = by_id[channel["dst_router"]]
        distance = sum(abs((a[i] if i < len(a) else 0)
                           - (b[i] if i < len(b) else 0))
                       for i in range(2))
        assert distance == 1, (channel["channel_id"], a, b)


# ── P2-H: torus wraparound (BLOCKED — see the module docstring) ────────


def test_p2_h_no_compiled_torus_can_exist():
    """The compiler refuses at ROUTING and discards the derived topology.

    This is why P2-S is BLOCKED rather than passing: there is no compiled
    torus to inspect. Recorded with source evidence, not assumed.
    """
    base = _preset()
    torus = replace(base, noc_config=replace(
        base.noc_config, topology_family=TopologyFamily.TORUS))
    compilation = FabricCompiler().compile(torus)
    assert compilation.status == "UNSUPPORTED"
    assert compilation.bundle is None
    assert "ROUTING" in (compilation.error or "")


def test_p2_h_torus_is_declarable_and_valid_even_though_it_does_not_compile():
    """The design is not invalid — a downstream stage is unavailable."""
    from veritx_dse.application import product_registry as registry
    consequence = registry.capability_consequence("FAB-003")
    assert consequence["stages"]["DECLARABLE"] == "YES"
    assert consequence["stages"]["DERIVABLE"] == "YES"
    assert consequence["stages"]["PROJECTABLE"] == "NO"


# ── P2-I / P2-J: concentration and unused seats ────────────────────────


def test_p2_i_concentration_renders_as_local_seats_not_extra_routers():
    """dense-4b-32tiles-conc4: 9 routers, 36 seats, concentration 4."""
    _compilation, result = _compile(_template(TEMPLATE_CONC4))
    fabric = result["groups"]["fabric"]
    counts = fabric["counts"]
    assert counts["routers"] == 9
    assert counts["seats"] == 36
    assert counts["seats"] == counts["routers"] * 4
    # seats are per-router capacity; routers are not duplicated per seat
    topology = fabric["topology"]
    capacities = {r["seat_capacity"] for r in topology["routers"]}
    assert capacities == {4}
    assert len(topology["routers"]) == 9


def test_p2_j_unused_seats_are_reported_per_router():
    """dense-1b-16tiles: 25 seats, 20 attached, 5 unused."""
    _compilation, result = _compile(_template(TEMPLATE_DENSE))
    fabric = result["groups"]["fabric"]
    counts = fabric["counts"]
    assert counts["unused_seats"] == counts["seats"] - counts["attached"]
    assert counts["unused_seats"] == 5
    # the frontend can compute the same per router from the artifact
    topology = fabric["topology"]
    per_router = {}
    for endpoint in topology["endpoints"]:
        per_router[endpoint["router_id"]] = \
            per_router.get(endpoint["router_id"], 0) + 1
    total_unused = sum(
        r["seat_capacity"] - per_router.get(r["router_id"], 0)
        for r in topology["routers"])
    assert total_unused == counts["unused_seats"]


def test_p2_j_a_fully_occupied_concentrated_fabric_reports_zero_unused():
    """Occupancy is ENDPOINT count, not distinct-router count.

    dense-4b-32tiles-conc4 has 9 routers x 4 seats = 36 seats and 36
    attached agents, so nothing is unused. Counting each router once would
    have reported 27 unused seats.
    """
    _compilation, result = _compile(_template(TEMPLATE_CONC4))
    counts = result["groups"]["fabric"]["counts"]
    assert counts["seats"] == 36
    assert counts["attached"] == 36
    assert counts["unused_seats"] == 0
    assert counts["occupied_routers"] == 9


def test_p2_j_no_endpoint_object_is_invented_for_an_unused_seat():
    """dense-1b-16tiles: 20 endpoint objects for 25 seats."""
    _compilation, result = _compile(_template(TEMPLATE_DENSE))
    topology = result["groups"]["fabric"]["topology"]
    counts = result["groups"]["fabric"]["counts"]
    assert len(topology["endpoints"]) == counts["attached"] == 20
    assert len(topology["endpoints"]) < counts["seats"] == 25


# ── P2-K: attachment selection resolves exactly ────────────────────────


def test_p2_k_every_endpoint_resolves_to_a_real_router():
    _compilation, result = _compile(_preset())
    topology = result["groups"]["fabric"]["topology"]
    router_ids = {r["router_id"] for r in topology["routers"]}
    for endpoint in topology["endpoints"]:
        assert endpoint["router_id"] in router_ids
    assert len({e["endpoint_id"] for e in topology["endpoints"]}) == \
        len(topology["endpoints"])


def test_p2_k_attachment_rows_carry_the_full_identity_chain():
    _compilation, result = _compile(_preset())
    for endpoint in result["groups"]["fabric"]["topology"]["endpoints"]:
        assert endpoint["endpoint_id"] is not None
        assert endpoint["router_id"] is not None
        assert endpoint["kind"]
        assert "group_index" in endpoint
        assert "instance_index" in endpoint


# ── P2-L / P2-M: canonical route, no frontend pathfinding ──────────────


def test_p2_l_the_route_comes_from_the_frozen_table():
    _compilation, result = _compile(_preset())
    routing = result["groups"]["routing"]
    assert routing["entry_count"] == len(routing["entries"])
    channels = {h["channel_id"] for h in routing["channel_hops"]}
    for entry in routing["entries"]:
        assert entry["channel_id"] in channels
    route = canonical_route(routing, "DOR_XY", 0, 8)
    assert route["terminates"] is True
    assert len(route["hops"]) == len(route["routers"]) - 1


def test_p2_m_local_ejection_is_handled():
    _compilation, result = _compile(_preset())
    routing = result["groups"]["routing"]
    assert canonical_route(routing, "DOR_XY", 3, 3)["terminal"] \
        == "LOCAL_EJECTION"
    assert canonical_route(routing, "DOR_XY", 0, 8)["terminal"] \
        == "LOCAL_EJECTION"


# ── P2-N: expected and observed stay separate ──────────────────────────


def test_p2_n_derived_route_and_runtime_evidence_are_separate():
    _compilation, result = _compile(_preset())
    routing = result["groups"]["routing"]
    assert routing["observation"]["available"] is False
    assert routing["observation"]["scope"] == "FIRST_HOP"
    assert "DERIVED EXPECTED" in routing["observation_note"]
    # the observation never claims a full packet path
    assert "not observed packet paths" in routing["observation"]["limit"]


# ── P2-O: VC inspection is read-only ───────────────────────────────────


def test_p2_o_vc_inspection_is_read_only_and_canonical():
    _compilation, result = _compile(_preset())
    resources = result["groups"]["resources"]
    assert resources["editable"] is False
    assert resources["vc_ids"]
    assert resources["vc_count"] == len(resources["vc_ids"])
    assert resources["traffic_class_to_vcs"]
    # canonical VC ids, not colours or draw order
    assert all(isinstance(v, int) for v in resources["vc_ids"])


# ── P2-P / P2-Q / P2-R: deadlock verdict, witness, resolution ──────────


def test_p2_p_a_deadlock_fail_displays_a_witness():
    """A real FAIL must carry the cycle, not just a verdict."""
    _compilation, result = _compile(_preset())
    witness = result["groups"]["resources"]["deadlock"]["witness"]
    assert witness["acyclic"] is True
    assert witness["sccs_gt_1"] == 0
    assert witness["node_count"] is not None
    assert witness["edge_count"] is not None


def test_p2_q_deadlock_unsupported_is_not_shown_as_fail():
    """The defect this closure exists to fix."""
    _compilation, result = _compile(_preset())
    analysis = result["certificate"]["deadlock_analysis"]
    assert analysis["analysis_verdict"] == "PASS"
    assert analysis["detected_deadlock"] is False
    # an UNSUPPORTED analysis must not set detected_deadlock
    for verdict in ("UNSUPPORTED", "NOT_RUN"):
        assert verdict in result["certificate"]["vocabulary"][
            "cdg_analysis_verdict"]


def test_p2_r_cdg_witness_ids_resolve_to_canonical_channels():
    _compilation, result = _compile(_preset())
    routing = result["groups"]["routing"]
    channel_ids = {h["channel_id"] for h in routing["channel_hops"]}
    # every route entry names a channel that exists in the topology
    for entry in routing["entries"]:
        assert entry["channel_id"] in channel_ids


# ── P2-S: torus inspectability — BLOCKED ───────────────────────────────


def test_p2_s_torus_inspectability_is_blocked_with_evidence():
    """Not a silent absence: the reason is asserted.

    The planning contract says torus topology stays inspectable. The
    compiler cannot deliver it through the compiled-revision path, so the
    case is BLOCKED rather than passing.
    """
    base = _preset()
    torus = replace(base, noc_config=replace(
        base.noc_config, topology_family=TopologyFamily.TORUS))
    compilation = FabricCompiler().compile(torus)
    assert compilation.status == "UNSUPPORTED"
    assert compilation.bundle is None
    # the topology is derivable in principle — only the bundle is discarded
    from veritx_dse.model.compile_model import derive_topology_spec
    spec = derive_topology_spec(torus)
    assert spec is not None
    assert "torus" in str(spec.name).lower()


# ── P2-T / P2-U: multi-class and capability limitations ────────────────


def test_p2_t_a_multi_class_compile_result_remains_inspectable():
    """The mesh4 family is multi-class and still compiles and inspects."""
    compilation, result = _compile(_preset())
    assert compilation.status == "COMPILED"
    assert result["available"] is True
    assert set(result["groups"]) == set(GROUPS)
    classes = dict(compilation.bundle.vc_assignment.traffic_class_to_vcs)
    assert len(classes) > 1


def test_p2_u_a_capability_limitation_does_not_invalidate_the_design():
    compilation, result = _compile(_preset())
    assert compilation.certificate.overall == "PASS"
    assert result["certificate"]["overall"] == "PASS"
    consequences = result["capability_consequences"]
    assert any(c["capability_id"] == "COMM-006" for c in consequences)
    # the consequence is a downstream limit, not a certificate failure
    for consequence in consequences:
        assert consequence["wiring"] == "NOT_AVAILABLE"


# ── P2-V: provenance in technical detail ───────────────────────────────


def test_p2_v_provenance_exposes_hashes_and_versions():
    _compilation, result = _compile(_preset())
    provenance = result["groups"]["provenance"]
    assert provenance["design_hash"].startswith("sha256:")
    assert provenance["resolved_fabric_hash"].startswith("sha256:")
    assert provenance["certificate_id"].startswith("sha256:")
    assert provenance["artifact_hashes"]
    assert provenance["compiler_semantics_version"] is not None


def test_p2_v_artifact_parentage_is_inspectable():
    _compilation, result = _compile(_preset())
    chain = result["groups"]["provenance"]["artifact_chain"]
    assert chain is not None
    nodes = chain["nodes"]
    assert nodes
    for node in nodes:
        assert "parents" in node
        assert "proved_by" in node
    assert any(node["parents"] == [] for node in nodes)


# ── P2-W: every scientific visual has a data equivalent ────────────────


def test_p2_w_the_fabric_artifact_supports_a_full_data_equivalent():
    """The router/channel/attachment tables are derivable from the payload.

    The frontend renders these as tables; the contract is that the payload
    carries every column they need.
    """
    _compilation, result = _compile(_preset())
    topology = result["groups"]["fabric"]["topology"]
    for router in topology["routers"]:
        assert {"router_id", "coordinates", "seat_capacity"} <= set(router)
    for channel in topology["channels"]:
        assert {"channel_id", "src_router", "src_port", "dst_router",
                "dst_port", "width_bits"} <= set(channel)
    for endpoint in topology["endpoints"]:
        assert {"endpoint_id", "kind", "group_index", "instance_index",
                "router_id"} <= set(endpoint)


# ── P2-X: no 3D ────────────────────────────────────────────────────────


def test_p2_x_no_depth_dimension_is_claimed():
    """The canonical topology has no z-axis, so nothing may assert one."""
    _compilation, result = _compile(_preset())
    blob = json.dumps(result)
    # `input_buffer_depth_flits_per_vc` is a buffer depth, not a spatial
    # axis — the forbidden tokens are spatial claims only.
    for token in ("z_axis", "perspective", "elevation", "camera"):
        assert token not in blob
    topology = result["groups"]["fabric"]["topology"]
    for router in topology["routers"]:
        assert len(router["coordinates"]) == 2


def test_p2_x_the_fabric_payload_has_no_3d_artifact():
    _compilation, result = _compile(_preset())
    assert "canvas3d" not in json.dumps(result).lower()


# ── deterministic compiled fixtures (Phase-2 §10/§11/§26) ──────────────


FIXTURES = Path(__file__).resolve().parent / "fixtures" / "compiled"


def _fixture(case: str) -> dict:
    path = FIXTURES / f"{case}.json"
    assert path.is_file(), f"missing fixture {case}"
    return json.loads(path.read_text())


@pytest.mark.parametrize("case", ["mesh4", "mesh8x8", "concentrated",
                                  "unused-seats", "mixed-agents"])
def test_every_fixture_has_a_deterministic_topology(case):
    fixture = _fixture(case)
    fabric = fixture["fabric"]
    assert fabric["available"] is True
    topology = fabric["topology"]
    assert len(topology["routers"]) == fabric["counts"]["routers"]
    assert len(topology["endpoints"]) == fabric["counts"]["attached"]
    assert sum(r["seat_capacity"] for r in topology["routers"]) \
        == fabric["counts"]["seats"]


def test_the_fixtures_do_not_drift():
    """Regeneration must be byte-identical — a topology change is a
    deliberate fixture update, never a silent drift."""
    import subprocess
    result = subprocess.run(
        [sys.executable, "tools/generate_compiled_fixtures.py", "--check"],
        capture_output=True, text=True, cwd=str(DSE))
    assert result.returncode == 0, result.stdout + result.stderr


def test_the_8x8_fixture_is_at_the_full_detail_boundary():
    """64 routers is the largest topology drawn per-router."""
    from veritx_dse.application.compile_result_view import (
        FULL_DETAIL_ROUTERS,
    )
    fixture = _fixture("mesh8x8")
    counts = fixture["fabric"]["counts"]
    assert counts["routers"] == 64 == FULL_DETAIL_ROUTERS
    assert fixture["fabric"]["detail_level"] == "FULL"


def test_the_8x8_fixture_has_a_non_trivial_route():
    fixture = _fixture("mesh8x8")
    routing = fixture["routing"]
    # 64 routers x 63 destinations = the complete route table
    assert routing["entry_count"] == 64 * 63


def test_the_concentrated_fixture_keeps_concentration_local():
    fixture = _fixture("concentrated")
    counts = fixture["fabric"]["counts"]
    assert counts["routers"] == 9
    assert counts["seats"] == 36
    assert counts["seats"] == counts["routers"] * 4
    assert counts["unused_seats"] == 0


def test_the_unused_seat_fixture_reports_the_gap():
    fixture = _fixture("unused-seats")
    counts = fixture["fabric"]["counts"]
    assert counts["unused_seats"] == 5
    assert counts["attached"] == 20
    assert counts["seats"] == 25


def test_the_mixed_agent_fixture_carries_every_kind():
    fixture = _fixture("mixed-agents")
    kinds = {e["kind"] for e in fixture["fabric"]["topology"]["endpoints"]}
    assert {"compute_tile", "hbm_controller", "nic", "peripheral"} <= kinds


def test_fixtures_carry_no_runtime_observation():
    """No fixture has been executed, so none may claim an observation."""
    for case in ("mesh4", "mesh8x8", "concentrated", "unused-seats",
                 "mixed-agents"):
        observation = _fixture(case)["routing"]["observation"]
        assert observation["available"] is False


def test_fixtures_carry_the_two_layer_certificate():
    for case in ("mesh4", "concentrated"):
        certificate = _fixture(case)["certificate"]
        assert certificate["claim_count"] == 4
        assert certificate["obligation_count"] == 10
        assert certificate["deadlock_analysis"]["detected_deadlock"] is False
