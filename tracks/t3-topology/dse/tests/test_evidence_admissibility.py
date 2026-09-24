"""Evidence admissibility (§5.4): authenticity is not admissibility.

A document can hash correctly and still describe a run that cannot exist
(an unknown fidelity token, or QUALIFIED over a test-injected transport).
These tests build such self-consistent documents, recompute the evidence
id with the canonical algorithm, and prove they are still refused.
"""
from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend import evidence as ev  # noqa: E402
from veritx_dse.core.artifact import content_hash  # noqa: E402


def _valid_doc() -> dict:
    return ev.ScientificBackendEvidence(
        prepared_id="a" * 64,
        profile_id="CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        projection_semantics_version="v1",
        config_sha256="b" * 64,
        trace_sha256="c" * 64,
        topology_sha256=None,
        resolved_fabric_hash="d" * 64,
        physical_traffic_id="e" * 64,
        message_artifact_id="f" * 64,
        binary_sha256="0" * 64,
        binary_size=123,
        producer_source_revision="1" * 40,
        producer_dirty=False,
        seed=0,
        parser_version=ev.PARSER_VERSION,
        execution_fidelity="QUALIFIED",
        route_observation="EXECUTED_ROUTE_OBSERVED",
        stats={"completion_cycles": 100, "loaded_trace_packets": 7},
        exit_status=0,
        transport=ev.EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
        build_manifest_sha256="9" * 64,
        build_recipe_version="booksim2-fork/v1",
        route_dump_sha256="7" * 64,
    ).to_dict()


def _rehash(doc: dict) -> dict:
    """Recompute evidence_id with the canonical domain algorithm."""
    out = dict(doc)
    payload = {k: v for k, v in out.items() if k != "evidence_id"}
    out["evidence_id"] = content_hash(
        ev._EVIDENCE_DOMAIN, out["schema_version"], payload)
    return out


@pytest.mark.parametrize("over", [
    {"transport": "MAGIC_TRANSPORT"},
    {"execution_fidelity": "MAGIC_FIDELITY"},
    {"route_observation": "MAGIC_OBSERVATION"},
    {"execution_fidelity": "QUALIFIED",
     "transport": ev.EXECUTION_TRANSPORT_TEST_INJECTED},
    {"execution_fidelity": "QUALIFIED", "producer_dirty": True},
    {"execution_fidelity": "QUALIFIED", "exit_status": 1},
    {"transport": ev.EXECUTION_TRANSPORT_TEST_INJECTED,
     "execution_fidelity": "QUALIFIED"},
    {"producer_dirty": "yes"},
])
def test_self_consistent_but_impossible_document_refuses(over):
    doc = _rehash({**_valid_doc(), **over})
    # the id recomputes to the same value the document claims
    assert doc["evidence_id"] == _rehash(doc)["evidence_id"]
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(doc)
    with pytest.raises(ev.BackendEvidenceError):
        ev.ScientificBackendEvidence.from_dict(doc)


def test_valid_document_still_admits():
    doc = _valid_doc()
    assert ev.validate_evidence_document(copy.deepcopy(doc))["evidence_id"] \
        == doc["evidence_id"]


# ── the single certified-product admission rule (P0.5) ───────────────────

def _evidence(**over) -> "ev.ScientificBackendEvidence":
    fields = {
        "prepared_id": "a" * 64,
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
        "route_observation": "EXECUTED_ROUTE_OBSERVED",
        "stats": {"completion_cycles": 100},
        "exit_status": 0,
        "transport": ev.EXECUTION_TRANSPORT_SUPERVISED_PROCESS,
        "build_manifest_sha256": "9" * 64,
        "build_recipe_version": "booksim2-fork/v1",
        "route_dump_sha256": "7" * 64,
    }
    fields.update(over)
    return ev.ScientificBackendEvidence(**fields)


def test_admission_accepts_a_qualified_pinned_record():
    ev.admit_for_certified_product(_evidence())


def test_qualified_requires_revision_at_construction():
    with pytest.raises(ev.BackendEvidenceError,
                       match="known producer source revision"):
        _evidence(producer_source_revision=None)


@pytest.mark.parametrize("over,match", [
    ({"execution_fidelity": "DIAGNOSTIC_UNPINNED_PRODUCER"},
     "not QUALIFIED"),
    ({"transport": ev.EXECUTION_TRANSPORT_TEST_INJECTED,
      "execution_fidelity": "TEST_INJECTED"}, "supervised production"),
    ({"build_manifest_sha256": None}, "binds no build manifest"),
    ({"build_recipe_version": None}, "binds no build recipe"),
])
def test_admission_refuses_unqualified_records(over, match):
    with pytest.raises(ev.BackendEvidenceError, match=match):
        ev.admit_for_certified_product(_evidence(**over))


def test_admission_is_the_only_rule_used_by_reuse():
    record = ev.ExecutionRecord(
        evidence=_evidence(build_manifest_sha256=None),
        attempt=ev.ExecutionAttempt(
            wall_time_s=0.0, run_dir="", binary_path="", command=(),
            host="", platform=""))
    with pytest.raises(ev.BackendEvidenceError,
                       match="binds no build manifest"):
        ev.verify_reusable_record(
            record, prepared_id="a" * 64, config_sha256="b" * 64,
            trace_sha256="c" * 64, binary_sha256="0" * 64)


# ── the certification theorem: certified BookSim requires observation and
#    the exact certified recipe (a rehashed document must not slip through)

def test_certified_profile_requires_executed_route_observation():
    unobserved = _evidence(
        route_observation="DOMAIN_QUALIFIED_ROUTE_NOT_OBSERVED",
        route_dump_sha256=None)
    with pytest.raises(ev.BackendEvidenceError, match="executed-route"):
        ev.admit_for_certified_product(unobserved)
    with pytest.raises(ev.BackendEvidenceError, match="executed-route"):
        ev.verify_reusable_record(
            ev.ExecutionRecord(evidence=unobserved,
                               attempt=ev.ExecutionAttempt(
                                   wall_time_s=0.0, run_dir="",
                                   binary_path="", command=(), host="",
                                   platform="")),
            prepared_id="a" * 64, config_sha256="b" * 64,
            trace_sha256="c" * 64, binary_sha256="0" * 64)


def test_certified_profile_requires_the_exact_build_recipe():
    with pytest.raises(ev.BackendEvidenceError, match="not the certified"):
        ev.admit_for_certified_product(
            _evidence(build_recipe_version="evil/v1"))


def test_observed_without_dump_digest_is_unconstructible():
    with pytest.raises(ev.BackendEvidenceError, match="route dump digest"):
        _evidence(route_dump_sha256=None)


def test_admission_uses_the_recipe_constant_by_profile():
    assert ev.required_build_recipe("CERTIFIED_BOOKSIM_ANYNET_V1") \
        == ev.BOOKSIM_BUILD_RECIPE_VERSION
    assert ev.required_build_recipe("SOME_FUTURE_BACKEND") is None


# ── restored legacy v1 reader (was an undefined-name crash) ──────────────

def test_unversioned_v1_document_reads_with_required_keys():
    doc = {"backend_input_hash": "a" * 64,
           "stats": {"completion_cycles": 1}}
    assert ev.validate_evidence_document(doc) == doc


@pytest.mark.parametrize("doc", [
    {"stats": {"completion_cycles": 1}},
    {"backend_input_hash": "a" * 64},
    {"backend_input_hash": "a" * 64, "stats": {}},
])
def test_unversioned_v1_document_missing_required_keys_refuses(doc):
    with pytest.raises(ev.BackendEvidenceError):
        ev.validate_evidence_document(doc)


def test_unknown_declared_schema_version_refuses():
    with pytest.raises(ev.BackendEvidenceError, match="unsupported"):
        ev.validate_evidence_document(
            {"schema_version": 99, "stats": {"completion_cycles": 1}})
