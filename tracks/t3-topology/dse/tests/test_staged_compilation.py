"""Staged compilation — a later stage refusal preserves upstream artifacts.

THE LAW (T-series, Phase-2 closure)

    A refusal at stage N leaves every artifact from stages < N
    authoritative and produces none from stages >= N. Nothing is
    synthesized to fill a gap.

Torus is the case that exposed it: `materialize_topology` produces a real
`TopologyArtifact` (with canonical wraparound channels), then `derive_route`
refuses because no certified routing derivation exists for that family.
Before this change the whole derivation raised and the topology was
discarded, so a valid, inspectable artifact became an "invalid design".
"""
from __future__ import annotations

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
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.application.preset_certification import (  # noqa: E402
    _load_preset_doc,
)
from veritx_dse.application.views import staged_topology_view  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequestV3,
    TopologyFamily,
)
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig,
    ProductService,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "compiled"


def _v3(name: str = "dense-1b-16tiles") -> CompileRequestV3:
    return CompileRequestV3.from_dict(_load_preset_doc(name))


def _torus() -> CompileRequestV3:
    base = _v3()
    return replace(base, noc_config=replace(
        base.noc_config, topology_family=TopologyFamily.TORUS))


def _mesh() -> CompileRequestV3:
    return _v3()


def _wraps(topology: dict) -> list[dict]:
    by_id = {r["router_id"]: r["coordinates"] for r in topology["routers"]}
    out = []
    for channel in topology["channels"]:
        a = by_id[channel["src_router"]]
        b = by_id[channel["dst_router"]]
        if max(abs((a[i] if i < len(a) else 0) - (b[i] if i < len(b) else 0))
               for i in range(2)) > 1:
            out.append(channel)
    return out


def _service(tmp_path) -> ProductService:
    return ProductService(ProductConfig(projects_root=tmp_path / "projects"))


def _compile_torus(tmp_path):
    service = _service(tmp_path)
    pid = service.create_project(name="torus")["project"]["project_id"]
    doc = _torus().to_dict()
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    service.put_draft(pid, doc)
    revision = service.compile_draft(pid)
    return service, pid, revision["revision_id"]


# ── T1 / T16: the complete path is unchanged ───────────────────────────


def test_t1_mesh_compilation_is_unchanged():
    compilation = FabricCompiler().compile(_mesh())
    assert compilation.status == "COMPILED"
    assert compilation.bundle is not None
    assert compilation.certificate.overall == "PASS"
    assert compilation.stopped_at_stage is None
    assert compilation.staged is None


def test_t16_ordinary_mesh_full_compile_unaffected():
    compilation = FabricCompiler().compile(build_preset_request("mesh4_hbm"))
    assert compilation.status == "COMPILED"
    assert compilation.staged is None
    assert compilation.bundle.root_hashes()["resolved_fabric_hash"]


# ── T2 / T3: torus derives and persists ────────────────────────────────


def test_t2_torus_produces_a_real_topology_artifact():
    compilation = FabricCompiler().compile(_torus())
    assert compilation.staged is not None
    topology = compilation.staged.topology
    assert topology is not None
    assert type(topology).__name__ == "TopologyArtifact"
    assert len(topology.routers) > 0
    assert len(topology.channels) > 0
    assert compilation.staged.has("TOPOLOGY")


def test_t3_torus_topology_persists_after_the_routing_refusal(tmp_path):
    service, _pid, revision_id = _compile_torus(tmp_path)
    stored = service.store.load_revision_global(revision_id)[1]
    assert "staged_topology" in stored
    assert stored["staged_topology"]["staged"] is True
    assert stored["staged_topology"]["family"] == "torus"


def test_t13_the_staged_result_survives_a_fresh_service(tmp_path):
    """A new ProductService over the same store still sees it."""
    service, pid, revision_id = _compile_torus(tmp_path)
    reopened = _service(tmp_path)
    payload = reopened.get_revision_compile_result(revision_id)
    assert payload["available"] is False
    assert payload["staged"] is True
    assert payload["staged_topology"]["counts"]["routers"] > 0
    assert reopened.project_view(pid)["latest_attempt_revision_id"] \
        == revision_id


# ── T4 / T5 / T6 / T7 / T8: nothing downstream is fabricated ───────────


def test_t4_no_route_artifact_is_produced():
    compilation = FabricCompiler().compile(_torus())
    assert compilation.bundle is None
    assert not compilation.staged.has("ROUTING")
    assert compilation.stopped_at_stage == "ROUTING"


def test_t5_no_resolved_route_is_produced():
    compilation = FabricCompiler().compile(_torus())
    assert not compilation.staged.has("ROUTING_REALIZATION")


def test_t6_no_vc_assignment_is_produced():
    compilation = FabricCompiler().compile(_torus())
    assert not compilation.staged.has("VC")


def test_t7_no_full_fabric_is_fabricated():
    compilation = FabricCompiler().compile(_torus())
    assert compilation.bundle is None
    assert not compilation.staged.has("FABRIC")
    assert not compilation.staged.has("RESOLVED_FABRIC")
    assert compilation.certificate is None


def test_t8_no_certificate_is_fabricated(tmp_path):
    _service_, _pid, revision_id = _compile_torus(tmp_path)
    payload = _service_.get_revision_compile_result(revision_id)
    assert payload["certificate"]["available"] is False
    assert "no certificate was issued" in payload["certificate"]["reason"]
    # the four product claims are never rendered as if evaluated
    assert "claims" not in payload["certificate"]


def test_t8_the_staged_topology_never_reads_as_certified():
    staged = staged_topology_view(FabricCompiler().compile(_torus()),
                                  revision_id="x")
    assert staged["staged"] is True
    assert staged["stopped_at_stage"] == "ROUTING"


# ── T9: a staged refusal is not an invalid design ──────────────────────


def test_t9_a_staged_torus_is_not_invalid():
    compilation = FabricCompiler().compile(_torus())
    assert compilation.status == "UNSUPPORTED"
    assert compilation.status != "INVALID"


def test_t9_the_produced_stages_are_the_expected_prefix():
    compilation = FabricCompiler().compile(_torus())
    assert compilation.staged.produced_stages == (
        "INPUT", "INPUT_MAPPING", "TOPOLOGY", "ATTACHMENT")


# ── T10 / T11: the inspector consumes the persisted artifact ───────────


def test_t10_the_inspector_payload_is_the_persisted_artifact(tmp_path):
    service, _pid, revision_id = _compile_torus(tmp_path)
    payload = service.get_revision_compile_result(revision_id)
    staged = payload["staged_topology"]
    stored = service.store.load_revision_global(revision_id)[1][
        "staged_topology"]
    assert staged["topology_hash"] == stored["topology_hash"]
    assert staged["counts"] == stored["counts"]


def test_t11_wraparound_channels_are_artifact_derived(tmp_path):
    service, _pid, revision_id = _compile_torus(tmp_path)
    topology = service.get_revision_compile_result(revision_id)[
        "staged_topology"]
    wraps = _wraps(topology)
    assert len(wraps) > 0
    # every wraparound is a real channel of the artifact
    channel_ids = {c["channel_id"] for c in topology["channels"]}
    assert all(w["channel_id"] in channel_ids for w in wraps)
    # and a mesh of the same shape has none
    mesh = FabricCompiler().compile(_mesh())
    mesh_topology = staged_topology_view(mesh, revision_id="x")
    assert mesh_topology is None  # it compiled, so it is not staged


def test_t11_the_torus_fixture_matches_its_artifact():
    fixture = json.loads((FIXTURES / "torus-staged.json").read_text())
    topology = fixture["staged_topology"]
    assert fixture["stopped_at_stage"] == "ROUTING"
    assert topology["family"] == "torus"
    assert topology["counts"]["routers"] == len(topology["routers"])
    assert topology["counts"]["channels"] == len(topology["channels"])
    assert len(_wraps(topology)) > 0


# ── T12: Evaluate is unavailable for the exact reason ──────────────────


def test_t12_evaluate_is_unavailable_with_the_routing_reason(tmp_path):
    service, _pid, revision_id = _compile_torus(tmp_path)
    payload = service.get_revision_compile_result(revision_id)
    assert payload["stopped_at_stage"] == "ROUTING"
    # the reason names the routing stage, in registry wording
    assert "ROUTING" in payload["reason"] or "routing" in payload["reason"]
    scopes = " ".join(c["claim_scope"] or ""
                      for c in payload["capability_consequences"])
    assert "routed execution" in scopes or "route" in scopes.lower()
    # and it is NOT presented as an invalid design
    assert payload["compilation_status"] == "UNSUPPORTED"
    assert payload["compilation_status"] != "INVALID"


# ── T14 / T15: identity and provenance ─────────────────────────────────


def test_t14_the_design_hash_is_unchanged_by_the_staged_stop():
    torus = _torus()
    compilation = FabricCompiler().compile(torus)
    assert compilation.request.design_hash() == torus.design_hash()
    assert compilation.staged.view.design_hash \
        == torus.design_hash().removeprefix("sha256:")


def test_t15_provenance_is_valid_for_the_produced_stages():
    compilation = FabricCompiler().compile(_torus())
    staged = compilation.staged
    assert staged.topology.topology_hash()
    assert staged.attachment.topology_hash \
        == staged.topology.topology_hash()
    assert staged.inventory is not None
    assert staged.mapping is not None


# ── T17: an internal fault is not a staged capability refusal ──────────


def test_t17_an_internal_fault_does_not_masquerade_as_a_stage_refusal(
        monkeypatch):
    """A programmer fault must propagate, not become a staged result."""
    from veritx_dse.compiler import orchestration

    def boom(*_args, **_kwargs):
        raise RuntimeError("programmer fault")

    monkeypatch.setattr(orchestration, "derive_staged_route", boom,
                        raising=False)
    # the stage runner catches only typed semantic refusals
    with pytest.raises(RuntimeError):
        from veritx_dse.model.topology_artifact import materialize_topology

        def explode(*_a, **_k):
            raise RuntimeError("programmer fault")

        monkeypatch.setattr(orchestration, "_v3_stages",
                            lambda _r: (("TOPOLOGY", explode),))
        orchestration.derive_stages_v3(_mesh())


# ── T18 / T19: the Phase-2 cases ───────────────────────────────────────


def test_t18_p2_h_passes_torus_wrap_links_come_from_the_artifact(tmp_path):
    service, _pid, revision_id = _compile_torus(tmp_path)
    topology = service.get_revision_compile_result(revision_id)[
        "staged_topology"]
    wraps = _wraps(topology)
    assert len(wraps) == 20
    # a wraparound joins routers that are more than one grid step apart,
    # and the coordinates that prove it come from the artifact
    by_id = {r["router_id"]: r["coordinates"] for r in topology["routers"]}
    for wrap in wraps:
        a, b = by_id[wrap["src_router"]], by_id[wrap["dst_router"]]
        assert max(abs(a[0] - b[0]), abs(a[1] - b[1])) > 1


def test_t19_p2_s_passes_torus_is_inspectable_despite_the_refusal(tmp_path):
    service, pid, revision_id = _compile_torus(tmp_path)
    payload = service.get_revision_compile_result(revision_id)
    # the staged state is reachable and inspectable
    assert payload["staged"] is True
    topology = payload["staged_topology"]
    assert topology["routers"] and topology["channels"]
    # and it did not displace a usable revision
    project = service.project_view(pid)
    assert project["latest_attempt_revision_id"] == revision_id
    assert project["active_revision_id"] != revision_id


# ── the law is generic, not Torus-specific ─────────────────────────────


def test_the_law_is_not_torus_specific():
    """A second, later refusal preserves MORE stages than the Torus case.

    An address range targeting a compute-tile group is infeasible; the
    refusal lands inside COMPOSE (ADDRESS_DECODE), so seven stages survive
    rather than four. That is the law holding at a different N, not a
    Torus special case.
    """
    from veritx_dse.compiler.orchestration import derive_stages_v3
    from veritx_dse.model.compile_model import AddressMap, AddressRange

    bad = replace(_mesh(), address_map=AddressMap(ranges=(
        AddressRange(name="BAD", base=0, size=4096, target_agent_idx=0),)))
    bundle, staged, refusal = derive_stages_v3(bad)
    assert bundle is None
    assert refusal is not None
    assert "ADDRESS_DECODE" in str(refusal)
    assert staged.stopped_at_stage == "FABRIC"
    assert staged.produced_stages == (
        "INPUT", "INPUT_MAPPING", "TOPOLOGY", "ATTACHMENT", "ROUTING",
        "ROUTING_REALIZATION", "VC")
    # this refusal happened LATER, so it preserved strictly more
    torus_stages = FabricCompiler().compile(_torus()).staged.produced_stages
    assert len(staged.produced_stages) > len(torus_stages)
    assert set(torus_stages) < set(staged.produced_stages)
