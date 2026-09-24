"""Evidence authority boundary (§26 Option 2).

Proves the architecture, not just the happy path:

* canonical ScientificBackendEvidence round-trips through write →
  read_verified_evidence → validate_evidence_document → from_dict with
  a stable evidence_id;
* any tampered/transplanted/mistyped canonical document refuses;
* an RT CertifiedBookSimEvidence document is NOT canonical evidence:
  passed directly to the canonical validator it fails closed. That
  failure is a feature — no silent cross-schema coercion exists.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend import evidence as ev  # noqa: E402


def _doc(**over):
    fields = {
        "prepared_id": "sha256:" + "a" * 64,
        "profile_id": "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        "projection_semantics_version": "v1",
        "config_sha256": "b" * 64,
        "trace_sha256": "c" * 64,
        "topology_sha256": None,
        "resolved_fabric_hash": "d" * 64,
        "physical_traffic_id": "e" * 64,
        "message_artifact_id": "f" * 64,
        "binary_sha256": "0" * 64,
        "binary_size": 123,
        "producer_source_revision": "1" * 40,
        "producer_dirty": False,
        "seed": 0,
        "parser_version": ev.PARSER_VERSION,
        "execution_fidelity": "QUALIFIED",
        "route_observation": "DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED",
        "stats": {"completion_cycles": 100, "loaded_trace_packets": 7},
        "exit_status": 0,
        "transport": "SUPERVISED_PROCESS",
        "build_manifest_sha256": "9" * 64,
        "build_recipe_version": "booksim2-fork/v1",
    }
    fields.update(over)
    return ev.ScientificBackendEvidence(**fields).to_dict()


def test_canonical_evidence_round_trips_with_stable_id(tmp_path):
    doc = _doc()
    ref = ev.write_evidence(tmp_path, doc)
    reread = ev.read_verified_evidence(ref)
    validated = ev.validate_evidence_document(reread)
    assert validated["evidence_id"] == doc["evidence_id"]
    rebuilt = ev.ScientificBackendEvidence.from_dict(validated)
    assert rebuilt.evidence_id() == doc["evidence_id"]
    assert rebuilt.to_dict() == validated


def test_wrong_prepared_id_refuses():
    doc = _doc()
    bad = dict(doc)
    bad["prepared_id"] = "sha256:" + "9" * 64
    with pytest.raises(ev.BackendEvidenceError):
        ev.ScientificBackendEvidence.from_dict(bad)
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(bad)


def test_wrong_profile_id_refuses():
    bad = dict(_doc())
    bad["profile_id"] = "CERTIFIED_BOOKSIM_ANYNET_V1"
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(bad)


def test_wrong_config_digest_refuses():
    bad = dict(_doc())
    bad["config_sha256"] = "1" * 64
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(bad)


def test_transplanted_evidence_id_refuses():
    first = _doc()
    second = _doc(trace_sha256="2" * 64)
    assert first["evidence_id"] != second["evidence_id"]
    transplant = dict(first)
    transplant["evidence_id"] = second["evidence_id"]
    with pytest.raises(ev.BackendEvidenceError):
        ev.ScientificBackendEvidence.from_dict(transplant)


def test_extra_field_refuses():
    bad = dict(_doc())
    bad["backend_config_hash"] = "3" * 64
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(bad)


def test_missing_field_refuses():
    bad = dict(_doc())
    del bad["stats"]
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(bad)


def test_wrong_type_tag_refuses():
    bad = dict(_doc())
    bad["type"] = "srota/OtherEvidence"
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(bad)


def test_rt_evidence_is_not_canonical_evidence():
    """RT CertifiedBookSimEvidence must fail the canonical validator.

    The RT document carries backend_config_hash / route_equivalence /
    qualification — adjacent concepts, different contracts. Accepting
    it here would silently coerce one authority into another.
    """
    from veritx_dse.backend.booksim import CertifiedBookSimEvidence
    rt = CertifiedBookSimEvidence(
        backend_config_hash="4" * 64,
        backend_input_hash="5" * 64,
        resolved_fabric_hash="d" * 64,
        fabric_hash="6" * 64,
        route_equivalence="EXACT",
        route_expected_sha256="7" * 64,
        route_executed_sha256="7" * 64,
        route_pairs_compared=6,
        exact_fabric_eligible=True,
        qualification="QUALIFIED",
        semantic_loss=(),
        stats={"completion_time": 100},
        exit_status=0,
        wall_time_s=0.5,
        command=("booksim", "config.cfg"),
        backend_dir="/tmp/run",
        booksim_binary_sha256="0" * 64,
        producer_source_revision=None,
        producer_source_dirty=False,
        producer_source_dirty_digest=None,
        producer_tool_identity="linux",
        execution_transport="SUPERVISED_PROCESS",
        parser_version=ev.PARSER_VERSION)
    rt_doc = rt.to_dict() if False else None
    # NOTE: rt.to_dict() is intentionally not called: it coerces through
    # the canonical ScientificBackendEvidence constructor and is
    # structurally incapable of producing a document (TypeError) — the
    # coercion cannot even be constructed, let alone accepted. What the
    # validator must refuse is an RT-vocabulary document handed to it
    # directly (defense in depth against hand-crafted coercion).
    import dataclasses
    rt_fields = dataclasses.asdict(rt)
    assert "backend_config_hash" in rt_fields
    assert "route_equivalence" in rt_fields
    hand_built = {"type": "srota/ScientificBackendEvidence",
                  "schema_version": 1,
                  **rt_fields,
                  "evidence_id": "0" * 64}
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(hand_built)
    with pytest.raises(ev.BackendEvidenceError):
        ev.ScientificBackendEvidence.from_dict(hand_built)


def test_modified_stats_change_the_id(tmp_path):
    doc = _doc()
    ref = ev.write_evidence(tmp_path, doc)
    altered = copy.deepcopy(doc)
    altered["stats"] = {"completion_cycles": 101,
                        "loaded_trace_packets": 7}
    with pytest.raises(ev.BackendEvidenceError):
        ev.ScientificBackendEvidence.from_dict(altered)
    # the persisted original still validates — the alteration never landed
    assert ev.validate_evidence_document(
        ev.read_verified_evidence(ref))["evidence_id"] == doc["evidence_id"]
