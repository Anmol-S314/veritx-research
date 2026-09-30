"""Compute provenance — a measured number and a typed number must differ.

The fabric's QUALIFIED verdict is about the fabric. It says nothing about
whether the durations fed to it were measured, derived from a source, or
typed in by hand. `compute.source` is where that claim lives, and these
tests pin that the claim is explicit and fail-closed.
"""
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.paths import REPO
from veritx_dse.model.compute_intent import (
    COMPUTE_SOURCE_KINDS,
    ComputeIntent,
    ComputeIntentError,
    ComputeSource,
    ComputeStage,
)
from veritx_dse.product.service import parse_request_doc

def test_the_default_is_unspecified_and_says_so():
    src = ComputeSource()
    assert src.kind == "unspecified"
    assert not src.specified

def test_measured_requires_a_reference():
    with pytest.raises(ComputeIntentError, match="must name its reference"):
        ComputeSource(kind="measured")

def test_derived_requires_both_a_formula_and_a_reference():
    with pytest.raises(ComputeIntentError, match="state the formula"):
        ComputeSource(kind="derived", reference="arXiv:1")
    with pytest.raises(ComputeIntentError, match="cite the reference"):
        ComputeSource(kind="derived", detail="f = a*b")

def test_declared_requires_a_rationale():
    with pytest.raises(ComputeIntentError, match="rationale"):
        ComputeSource(kind="declared")

def test_unknown_kind_refuses():
    with pytest.raises(ComputeIntentError, match="kind must be one of"):
        ComputeSource(kind="guessed")
    assert set(COMPUTE_SOURCE_KINDS) == {
        "measured", "derived", "declared", "unspecified"}

def test_unspecified_is_omitted_from_the_document():
    """Existing workloads must not churn identity for a field they never set."""
    stage = ComputeStage(stage_id="s", duration_ns=1, input_bytes=0,
                         weight_bytes=0, output_bytes=0)
    assert "source" not in ComputeIntent(stages=(stage,)).to_dict()
    doc = ComputeIntent(stages=(stage,), source=ComputeSource(
        kind="declared", detail="chosen")).to_dict()
    assert doc["source"]["kind"] == "declared"

def test_round_trip_through_a_v4_document():
    doc = {
        "schema_version": 4, "compiler_semantics_version": 4,
        "workload": {"model_family": "custom", "model_name": "x",
                     "tp": 1, "pp": 1, "ep": 1, "dp": 1,
                     "serving_mode": "mixed",
                     "collectives": [{"kind": "alltoall",
                                      "dimension": "TP",
                                      "payload_bytes": 64,
                                      "source_rank": None,
                                      "traffic_class": "t"}]},
        "requirements": [{"traffic_class": "t", "qos_class": "latency_critical",
                          "latency_ceiling_cycles": 100.0,
                          "bandwidth_floor_gbps": None, "binding": True}],
        "agents": [{"kind": "compute_tile", "count": 1, "protocol": "AXI",
                    "data_width": 256, "addr_width": 64}],
        "dependencies": [],
        "topology": {"kind": "mesh", "side_length": 1, "concentration": 1},
        "noc_controls": {"link_width": 64, "output_formats": ["json"]},
        "address_map": {"ranges": []},
        "compute": {
            "stages": [{"stage_id": "s0", "duration_ns": 5,
                        "input_bytes": 1, "weight_bytes": 0,
                        "output_bytes": 1}],
            "source": {"kind": "derived", "detail": "d = a*b",
                       "reference": "arXiv:1501.05992"},
        },
    }
    req = parse_request_doc(doc)
    assert req.compute.source.kind == "derived"
    assert req.compute.source.reference == "arXiv:1501.05992"
    assert req.compute.source.specified

def test_a_bad_provenance_in_a_document_is_refused_by_the_parser():
    doc = {
        "schema_version": 4, "compiler_semantics_version": 4,
        "workload": {"model_family": "custom", "tp": 1, "pp": 1, "ep": 1,
                     "dp": 1, "serving_mode": "mixed", "collectives": []},
        "requirements": [],
        "agents": [{"kind": "compute_tile", "count": 1,
                    "protocol": "AXI", "data_width": 256,
                    "addr_width": 64}],
        "dependencies": [],
        "topology": {"kind": "mesh", "side_length": 1, "concentration": 1},
        "noc_controls": {"link_width": 64},
        "address_map": {"ranges": []},
        "compute": {"stages": [], "source": {"kind": "measured"}},
    }
    with pytest.raises(Exception, match="reference"):
        parse_request_doc(doc)

def test_the_mwa_profile_declares_a_derived_source_with_a_citation():
    from veritx_dse.product.workload_registry import materialize, resolve
    entry = resolve(REPO, "mwa-fx-correlator")
    doc = materialize(entry, REPO)
    src = doc["compute"]["source"]
    assert src["kind"] == "derived"
    assert "1501.05992" in src["reference"]
    assert "baselines" in src["detail"]

def test_the_placeholder_profile_is_honestly_labelled_declared():
    """The SKA-Low document is an illustrative shape, not SKA data.

    Its numbers were checked against the published correlator and match
    none of it: 512 stations (not 16), 384 station-level coarse channels
    (not 64), 1,835,008 samples per correlation (not 256), 4-bit samples
    (not 2-bit), and a rack-scale Perentie/Alveo fabric (not a 5x5 mesh).
    It stays on disk only as a lowering fixture, so its own provenance
    must admit that \u2014 and it must NOT reach the product catalog.
    """
    from veritx_dse.performance.profile_ingest import load_profile
    from veritx_dse.product.workload_registry import load_registry, resolve

    profile = load_profile(
        REPO / "tracks/t3-topology/examples/profiles/"
        "ska-low-correlator-profile.json")
    assert profile.source.kind == "declared"
    assert "SKA-LOW-CORR-1" not in profile.hardware
    assert "SKA-Low" in profile.source.detail

    assert resolve(REPO, "ska-low-fx-correlator") is None
    ids = {e.workload_id for e in load_registry(REPO)}
    assert "mwa-fx-correlator" in ids
    assert "ska-low-fx-correlator" not in ids
