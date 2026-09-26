"""Shipped-preset certification (Gate 6 §86/§87).

A preset may only advertise a capability envelope whose own conditions it
satisfies. Gate 6 asserted that for four presets; nothing verified it, and
one assertion was false.

The audit that produced these tests found **two** independent reasons the
`mesh4` family could not be Guided-safe under
`CAP-ENV-BOOKSIM-MESH-DOR-XY-V1`:

1. it declared `model_family=mixture_of_experts` while the envelope's
   `COND-DENSE-STATIC-WORKLOAD` requires `dense_transformer` — corrected at
   the canonical preset source;
2. it ships a **multi-class** fabric (dependency classes A and B, two VCs),
   and every static envelope requires `COND-SINGLE-COMM-CLASS`, with
   `COMM-006` recording multi-class execution as unavailable — corrected in
   the certification metadata.

`dense-1b-16tiles` is the one shipped preset that provably reaches the
advertised envelope, so the Guided safe path is real rather than asserted.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application import preset_certification as pc  # noqa: E402
from veritx_dse.application import product_registry as registry  # noqa: E402
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    CompileRequest, CompileRequestV3,
)


@pytest.fixture(autouse=True)
def _fresh_registry():
    registry.clear_cache()
    yield
    registry.clear_cache()


def _compile(preset_id: str):
    doc = pc._load_preset_doc(preset_id)
    assert doc, f"{preset_id} does not expand to a canonical request"
    request = (CompileRequestV3.from_dict(doc)
               if doc.get("schema_version") == 3
               else CompileRequest.from_dict(doc))
    return doc, request, FabricCompiler().compile(request)


def _certify(preset_id: str) -> dict:
    doc, _request, compilation = _compile(preset_id)
    return pc.certify(preset_id, doc, compilation)


def _shipped() -> list[str]:
    return sorted(registry.exposure_document().get("presets") or {})


# ── the Guided safe path is proven, not asserted ───────────────────────


def test_at_least_one_shipped_preset_is_proven_guided_safe():
    """§6: the Guided safe path must exist for real, not by declaration."""
    guided = [p for p in _shipped() if _certify(p)["state"] == pc.GUIDED_SAFE]
    assert guided, "GUIDED SAFE PATH BLOCKED — no shipped preset is proven"


@pytest.mark.parametrize("preset_id", _shipped())
def test_every_shipped_preset_certifies_to_a_known_state(preset_id):
    assert _certify(preset_id)["state"] in pc.CERTIFICATION_STATES


@pytest.mark.parametrize("preset_id", _shipped())
def test_every_shipped_preset_canonicalizes_and_compiles(preset_id):
    """Compilable is necessary — and explicitly not sufficient."""
    _doc, request, compilation = _compile(preset_id)
    assert request is not None
    assert compilation.status == "COMPILED"
    assert compilation.certificate is not None
    assert compilation.certificate.overall == "PASS"


def test_guided_safe_presets_satisfy_every_required_condition():
    """The whole point: a Guided claim must actually reach its envelope."""
    for preset_id in _shipped():
        row = _certify(preset_id)
        if row["state"] != pc.GUIDED_SAFE:
            continue
        assert row["envelope"], preset_id
        assert row["failed_conditions"] == [], (preset_id,
                                                row["failed_conditions"])
        assert row["pending_conditions"] == [], (preset_id,
                                                 row["pending_conditions"])
        assert all(v == pc.HOLDS for v in row["conditions"].values())


def test_the_guided_safe_preset_is_dense_and_single_class():
    for preset_id in _shipped():
        row = _certify(preset_id)
        if row["state"] != pc.GUIDED_SAFE:
            continue
        doc = pc._load_preset_doc(preset_id)
        assert doc["workload"]["model_family"] == "dense_transformer"
        assert row["conditions"]["COND-SINGLE-COMM-CLASS"] == pc.HOLDS


# ── the two corrections ────────────────────────────────────────────────


def test_mesh4_family_is_not_guided_safe_and_says_why():
    """The corrected certification: multi-class, so no static envelope."""
    for preset_id in ("mesh4", "mesh4_hbm", "mesh4_wide128"):
        row = _certify(preset_id)
        assert row["state"] == pc.EXPERT_ONLY, preset_id
        assert row["claimed_guided_eligible"] is False
        assert registry.preset_spec(preset_id).get("reason")


def test_mesh4_family_is_multi_class_which_no_static_envelope_admits():
    """The decisive reason, independent of the model-family correction."""
    for preset_id in ("mesh4", "mesh4_hbm", "mesh4_wide128"):
        _doc, _request, compilation = _compile(preset_id)
        classes = compilation.bundle.vc_assignment.traffic_class_to_vcs
        assert len(classes) > 1, preset_id
        verdicts = pc.condition_verdicts(
            _doc, compilation, ("COND-SINGLE-COMM-CLASS",))
        assert verdicts["COND-SINGLE-COMM-CLASS"] == pc.FAILS


def test_multi_class_execution_is_unavailable_in_the_registry():
    """COMM-006 is why no envelope admits the mesh4 family."""
    consequence = registry.capability_consequence("COMM-006")
    assert consequence["wiring"] == "NOT_AVAILABLE"


def test_mesh4_family_declares_the_dense_carrier_workload():
    """Correction 1, at the canonical preset source.

    These are FABRIC presets: a 4-tile mesh carrying a synthetic trace with
    tp=ep=dp=1. Declaring MOE made them fail COND-DENSE-STATIC-WORKLOAD, a
    condition of the envelope they advertised.
    """
    for preset_id in ("mesh4", "mesh4_hbm", "mesh4_wide128"):
        doc = pc._load_preset_doc(preset_id)
        assert doc["workload"]["model_family"] == "dense_transformer"
        assert doc["workload"]["ep"] == 1
        assert doc["workload"]["tp"] == 1


def test_the_dense_correction_is_inert_for_every_fabric_artifact():
    """Only the identity moved; the physics did not.

    Proven, not assumed: every derived artifact hash is identical between
    the MOE and DENSE carrier, because `total_npus = tp × ep = 1` either way
    and the traffic is trace-driven rather than collective-driven.
    """
    from dataclasses import replace

    from veritx_dse.application.compile_intent import (  # noqa: PLC0415
        build_preset_request,
    )
    from veritx_dse.model.compile_model import ModelFamily  # noqa: PLC0415

    for preset_id in ("mesh4", "mesh4_hbm", "mesh4_wide128"):
        current = build_preset_request(preset_id)
        previous = replace(
            current,
            workload=replace(current.workload,
                             model_family=ModelFamily.MOE))
        assert current.workload.total_npus == previous.workload.total_npus
        now = FabricCompiler().compile(current).bundle.root_hashes()
        before = FabricCompiler().compile(previous).bundle.root_hashes()
        moved = sorted(k for k in now if now[k] != before.get(k))
        assert moved == ["design_hash", "resolved_fabric_hash"], (preset_id,
                                                                  moved)


def test_a_real_moe_preset_keeps_its_moe_family():
    """The correction must not have been a blanket MoE removal."""
    doc = pc._load_preset_doc("moe-8x7b-64tiles")
    assert doc["workload"]["model_family"] == "mixture_of_experts"
    assert doc["workload"]["ep"] == 8


# ── MoE cannot be static-evaluation-safe ───────────────────────────────


def test_a_moe_preset_is_never_guided_safe_for_static_evaluation():
    """Static MoE lowering is unavailable (WORK-002), so no MoE preset may
    be advertised as static-evaluation-safe."""
    consequence = registry.capability_consequence("WORK-002")
    assert consequence["stages"]["DERIVABLE"] == "NO"
    for preset_id in _shipped():
        doc = pc._load_preset_doc(preset_id)
        if (doc.get("workload") or {}).get("model_family") \
                != "mixture_of_experts":
            continue
        row = _certify(preset_id)
        assert row["state"] != pc.GUIDED_SAFE, preset_id


def test_the_static_moe_condition_fails_for_a_moe_workload():
    doc = pc._load_preset_doc("moe-8x7b-64tiles")
    verdicts = pc.condition_verdicts(
        doc, None, ("COND-DENSE-STATIC-WORKLOAD",))
    assert verdicts["COND-DENSE-STATIC-WORKLOAD"] == pc.FAILS


# ── fail-closed ────────────────────────────────────────────────────────


def test_an_unknown_preset_is_uncertified():
    row = pc.certify("not-a-preset", {"schema_version": 2})
    assert row["state"] == pc.UNCERTIFIED
    assert row["conditions"] == {}


def test_a_failing_condition_on_a_guided_claim_is_invalid():
    """A Guided claim its own envelope refutes must not ship."""
    doc = pc._load_preset_doc("dense-1b-16tiles")
    doc["workload"]["model_family"] = "mixture_of_experts"
    _request = CompileRequestV3.from_dict(doc)
    compilation = FabricCompiler().compile(_request)
    row = pc.certify("dense-1b-16tiles", doc, compilation)
    assert row["state"] == pc.INVALID
    assert "COND-DENSE-STATIC-WORKLOAD" in row["failed_conditions"]


def test_an_undecidable_condition_never_yields_guided_safe():
    """Fail closed: execution-only conditions cannot be assumed."""
    doc = pc._load_preset_doc("dense-1b-16tiles")
    verdicts = pc.condition_verdicts(
        doc, None, ("COND-SERVING-ROUND-QUALIFIED",))
    assert verdicts["COND-SERVING-ROUND-QUALIFIED"] == pc.PENDING_EXECUTION
    # and an envelope resting on it cannot certify Guided-safe
    assert pc.GUIDED_SAFE not in (pc.PENDING_EXECUTION,)


def test_an_unexpandable_preset_fails_every_condition():
    """A preset the product cannot expand is not certifiable."""
    assert pc._load_preset_doc("nope") == {}
    verdicts = pc.condition_verdicts({}, None, ("COND-TOPOLOGY-MESH",))
    assert verdicts["COND-TOPOLOGY-MESH"] == pc.FAILS


def test_an_unknown_condition_is_pending_not_passing():
    verdicts = pc.condition_verdicts({}, None, ("COND-INVENTED",))
    assert verdicts["COND-INVENTED"] == pc.PENDING_EXECUTION


# ── no silent drift ────────────────────────────────────────────────────


def test_certification_cannot_drift_when_preset_contents_change():
    """Changing a preset's science must change its certification.

    The claim lives in the registry and the evidence lives in the
    compilation; `certify` derives the state from the evidence, so a preset
    that stops satisfying its envelope stops being Guided-safe without
    anyone editing the registry.
    """
    doc = pc._load_preset_doc("dense-1b-16tiles")
    baseline = pc.certify(
        "dense-1b-16tiles", doc, FabricCompiler().compile(
            CompileRequestV3.from_dict(doc)))
    assert baseline["state"] == pc.GUIDED_SAFE

    # A second communication class is exactly the mesh4 failure mode: every
    # static envelope requires COND-SINGLE-COMM-CLASS.
    mutated = copy.deepcopy(doc)
    mutated["workload"]["collectives"].append(
        {"kind": "allgather", "dimension": "DP", "payload_bytes": 1024,
         "traffic_class": "bulk"})
    compilation = FabricCompiler().compile(CompileRequestV3.from_dict(mutated))
    drifted = pc.certify("dense-1b-16tiles", mutated, compilation)
    assert drifted["state"] != pc.GUIDED_SAFE
    assert drifted["state"] == pc.INVALID
    assert "COND-SINGLE-COMM-CLASS" in drifted["failed_conditions"]


def test_certification_follows_a_topology_change():
    """A second, independent drift probe: the envelope is mesh-only."""
    doc = pc._load_preset_doc("dense-1b-16tiles")
    mutated = copy.deepcopy(doc)
    mutated["noc_config"]["topology_family"] = "concentrated_mesh"
    compilation = FabricCompiler().compile(CompileRequestV3.from_dict(mutated))
    drifted = pc.certify("dense-1b-16tiles", mutated, compilation)
    assert drifted["state"] == pc.INVALID
    assert "COND-TOPOLOGY-MESH" in drifted["failed_conditions"]


def test_the_registry_claim_alone_never_produces_guided_safe():
    """With no compilation the static conditions are undecidable."""
    doc = pc._load_preset_doc("dense-1b-16tiles")
    row = pc.certify("dense-1b-16tiles", doc, None)
    assert row["state"] != pc.GUIDED_SAFE


def test_certify_all_covers_every_registry_preset():
    assert sorted(r["preset_id"] for r in pc.certify_all()) == _shipped()
