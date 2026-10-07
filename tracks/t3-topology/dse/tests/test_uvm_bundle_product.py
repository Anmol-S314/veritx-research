"""Canonical UVM generation from the compiled bundle (PRODUCT-CONVERGENCE-V1 item G).

The generator used to take a legacy v2 CompileRequest plus FREE size
parameters (n_nodes=64, k=8 defaults), so no product or gateway route
could call it without guessing the fabric. These tests pin the repaired
contract:

  * every fabric parameter (nodes, K, VC count, routing) is derived from
    the ResolvedFabricBundle — the exact numbers the compiler certified;
  * the output is stamped with the revision's frozen identity (revision,
    design hash, schema, generator version);
  * a revision with no compiled fabric is refused (CONFLICT), never
    approximated;
  * a fabric the testbench cannot describe (torus or concentrated mesh)
    refuses instead of instantiating the wrong DUT;
  * recompiled artifacts must match the revision's frozen artifact hashes;
  * the legacy v2 entry (test_compile_uvm.py) still behaves as pinned.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.application.compile_intent import (  # noqa: E402
    build_preset_request,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.verification.uvm_gen import (  # noqa: E402
    UVM_GENERATOR_VERSION,
    UvmGenerationError,
    _derive_k,
    generate_uvm_for_bundle,
)

PRESET = "mesh4_hbm"


@pytest.fixture()
def client(tmp_path):
    config = GatewayConfig(store_root=tmp_path / "store",
                           runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(config), raise_server_exceptions=False)


@pytest.fixture()
def revision_id(client):
    created = client.post("/api/v1/projects", json={"name": "p-uvm"}).json()
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


def _preset_bundle():
    return FabricCompiler().compile(build_preset_request(PRESET)).bundle


def test_collateral_derives_the_fabric_from_the_compiled_bundle(client,
                                                                revision_id):
    """The numbers in the SystemVerilog ARE the bundle's numbers —
    node count from the topology, K from the grid, VC count exactly
    (the legacy templates add +1; the projection must not drift)."""
    bundle = _preset_bundle()
    resp = client.post(f"/api/v1/revisions/{revision_id}/uvm")
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["files"] == ["tb_noc.sv", "seq_lib.sv",
                             "assertions.sv", "cov.sv"]
    tb = body["tb_top"]
    assert (f"localparam int NUM_NODES = "
            f"{bundle.topology.router_count};") in tb
    assert "localparam int K = 3;" in tb          # sqrt(9 routers), mesh grid
    assert (f"localparam int NUM_VCS = "
            f"{bundle.vc_assignment.vc_count};") in tb
    routing = bundle.router_route.routing_classes[0].id
    assert f'localparam int ROUTING = "{routing}";' in tb

    fabric = body["fabric"]
    assert fabric["n_nodes"] == bundle.topology.router_count
    assert fabric["vc_count"] == bundle.vc_assignment.vc_count
    assert fabric["routing_classes"] == [
        rc.id for rc in bundle.router_route.routing_classes]
    assert fabric["family"] == bundle.topology.family.value
    # Provenance: every parameter names the artifact it came from.
    assert "topology.router_count" in fabric["derived_from"]
    assert "vc_assignment.vc_count" in fabric["derived_from"]

    # Pure data end to end.
    json.dumps(body)


def test_identity_is_stamped_from_the_frozen_revision(client, revision_id):
    """Collateral without provenance is anonymous; the stamp must bind
    the generated files to the frozen revision the server serves."""
    revision = client.get(f"/api/v1/revisions/{revision_id}").json()
    body = client.post(f"/api/v1/revisions/{revision_id}/uvm").json()

    identity = body["identity"]
    assert identity["generator"] == "veritx-uvm"
    assert identity["generator_version"] == UVM_GENERATOR_VERSION
    assert identity["revision_id"] == revision_id
    assert identity["design_hash"] == revision["design_hash"]
    # mesh4_hbm is a v2 preset: the stamp names the design's generation.
    assert identity["design_schema_version"] == 2

    for source in (body["tb_top"], body["sequences"],
                   body["assertions"], body["coverage"]):
        assert f"// revision={revision_id}" in source
        assert f"design_hash={revision['design_hash']}" in source
        assert f"generator={UVM_GENERATOR_VERSION}" in source


def test_an_uncertified_revision_has_no_testbench(client):
    """No compiled fabric, no collateral — a CONFLICT, never a guess.

    A refused compile still freezes a revision record (the attempt),
    and that record has no fabric to describe.
    """
    created = client.post("/api/v1/projects", json={"name": "p-draft"}).json()
    pid = created["project"]["project_id"]
    request = build_preset_request(PRESET).to_dict()
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    request["address_map"]["ranges"][0]["target_agent_idx"] = 0
    client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
    client.post(f"/api/v1/projects/{pid}/compile", json={})
    project = client.get(f"/api/v1/projects/{pid}").json()
    attempt = project["latest_attempt"]
    assert attempt is not None
    assert attempt["compilation_status"] != "COMPILED"

    resp = client.post(
        f"/api/v1/revisions/{attempt['revision_id']}/uvm")
    assert resp.status_code == 409, resp.text
    assert "did not compile" in resp.text


def test_a_v4_declared_grid_derives_k_from_the_intent():
    """The shipped qwen v4 example: K comes from the MeshIntent's
    side_length, VC count is the bundle's exact (single-VC) count."""
    doc = json.loads((REPO / "tracks/t3-topology/examples/"
                      "qwen3_moe_tp2_ep4_16tiles-v4.json").read_text())
    bundle = FabricCompiler().compile(parse_request_doc(doc)).bundle
    result = generate_uvm_for_bundle(bundle, revision_id="q-r01")

    assert result["fabric"]["k"] == 5          # MeshIntent side_length=5
    assert result["fabric"]["n_nodes"] == 25   # 5x5 materialized grid
    assert result["fabric"]["vc_count"] == 1
    tb = result["tb_top"]
    assert "localparam int K = 5;" in tb
    assert "localparam int NUM_NODES = 25;" in tb
    assert "localparam int NUM_VCS = 1;" in tb
    assert "// revision=q-r01" in tb


def test_torus_refuses_instead_of_receiving_a_mesh_testbench():
    """A square torus is not a mesh; equal dimensions do not make the
    generated noc_mesh DUT an equivalent topology."""
    design = SimpleNamespace(topology=None, noc_config=None)
    topology = SimpleNamespace(router_count=16,
                               family=SimpleNamespace(value="torus"))
    with pytest.raises(UvmGenerationError, match="noc_mesh"):
        _derive_k(design, topology)


def test_concentrated_mesh_refuses_instead_of_losing_concentration():
    design = SimpleNamespace(
        topology=SimpleNamespace(side_length=3, concentration=2),
        noc_config=None)
    topology = SimpleNamespace(
        router_count=9, family=SimpleNamespace(value="mesh"))
    with pytest.raises(UvmGenerationError, match="concentration=2"):
        _derive_k(design, topology)


def test_recompilation_must_match_frozen_revision_artifact_hashes(
        client, revision_id, monkeypatch):
    from types import SimpleNamespace
    from veritx_dse.application.fabric_compiler import FabricCompiler

    monkeypatch.setattr(
        FabricCompiler, "compile",
        lambda self, request: SimpleNamespace(
            status="COMPILED",
            bundle=SimpleNamespace(root_hashes=lambda: {"changed": "sha256:x"})))
    response = client.post(f"/api/v1/revisions/{revision_id}/uvm")
    assert response.status_code != 200
    assert "artifact hashes differ from the frozen revision" in response.text


def test_a_radix_that_conflicts_with_compiled_router_count_refuses():
    design = SimpleNamespace(
        topology=None, noc_config=SimpleNamespace(radix=4))
    topology = SimpleNamespace(
        router_count=9, family=SimpleNamespace(value="mesh"))
    with pytest.raises(UvmGenerationError, match="radix=4.*compiled topology has 9"):
        _derive_k(design, topology)


def test_a_contradictory_grid_refuses_rather_than_describing_it():
    """side_length=4 with 9 materialized routers means the compiler did
    not produce the declared grid — an evidence refusal, not a render."""
    design = SimpleNamespace(
        topology=SimpleNamespace(side_length=4), noc_config=None)
    topology = SimpleNamespace(
        router_count=9, family=SimpleNamespace(value="mesh"))
    with pytest.raises(UvmGenerationError, match="did not produce"):
        _derive_k(design, topology)


def test_unknown_revision_is_refused_by_the_server(client):
    resp = client.post("/api/v1/revisions/no-such-revision/uvm")
    assert resp.status_code != 200
