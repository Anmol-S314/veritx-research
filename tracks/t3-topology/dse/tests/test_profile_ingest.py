"""Customer profile ingestion — veritx.model-profile/1."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from veritx_dse.core.paths import REPO
from veritx_dse.performance.model_profile import ModelProfileError
from veritx_dse.performance.profile_ingest import (
    SCHEMA,
    ProfileIngestError,
    load_profile,
    profile_from_document,
)

EXAMPLE = (REPO / "tracks/t3-topology/examples/profiles"
           / "astr-llm-70b-profile.json")
PARTIAL = (REPO / "tracks/t3-topology/examples/profiles"
           / "astr-llm-70b-profile-partial.json")

def _doc(**over):
    base = {
        "schema": SCHEMA,
        "model": "cust-model",
        "hardware": "CUST-HW",
        "variant": "bf16",
        "tp": 2,
        "layers": [
            {"index": 0, "kind": "attention", "duration_ns": 100,
             "input_bytes": 8, "weight_bytes": 16, "output_bytes": 8},
            {"index": 0, "kind": "dense_ffn", "duration_ns": 200},
        ],
    }
    base.update(over)
    return base

def test_loads_the_shipped_customer_example():
    prof = load_profile(EXAMPLE)
    assert prof.model == "astr-llm-70b"
    assert prof.hardware == "ASTRA-AC-1"
    assert prof.tp == 4 and prof.ep == 1
    assert len(prof.layers) == 4
    assert prof.complete
    assert sum(l.duration_ns for l in prof.layers) == 553300

def test_the_shipped_partial_example_carries_an_explicit_absence():
    prof = load_profile(PARTIAL)
    absent = prof.layers[2]
    assert absent.duration_ns is None
    assert absent.missing == (
        "not measurable at tp4 on this silicon revision",)
    assert not prof.complete

def test_measured_layers_become_stages_and_placement_is_balanced():
    prof = profile_from_document(_doc())
    assert prof.complete
    ci = prof.to_compute_intent(participants=2, stage_prefix="c")
    assert [s["stage_id"] for s in ci["stages"]] == ["c0_attention", "c0_dense_ffn"]
    assert ci["stages"][0]["duration_ns"] == 100
    assert [s["owner"] for s in ci["stages"]] == [1, 0]
    loads = {}
    for s in ci["stages"]:
        loads[s["owner"]] = loads.get(s["owner"], 0) + s["duration_ns"]
    assert loads == {0: 200, 1: 100}

def test_placement_balances_a_lopsided_workload():
    """The bug this replaces: 8 stages, 16 ranks, everything on 4 ranks."""
    layers = [{"index": 0, "kind": "correlate", "duration_ns": 89000},
              {"index": 0, "kind": "accumulate", "duration_ns": 12000},
              {"index": 1, "kind": "correlate", "duration_ns": 89000},
              {"index": 1, "kind": "accumulate", "duration_ns": 12000},
              {"index": 2, "kind": "correlate", "duration_ns": 89000},
              {"index": 2, "kind": "accumulate", "duration_ns": 12000},
              {"index": 3, "kind": "correlate", "duration_ns": 89000},
              {"index": 3, "kind": "accumulate", "duration_ns": 12000}]
    prof = profile_from_document(_doc(layers=layers))
    ci = prof.to_compute_intent(participants=16)
    owners = [s["owner"] for s in ci["stages"]]
    assert len(set(owners)) == 8, owners
    loads = {}
    for s in ci["stages"]:
        loads[s["owner"]] = loads.get(s["owner"], 0) + s["duration_ns"]
    assert max(loads.values()) - min(loads.values()) == 89000 - 12000

def test_incomplete_profile_refuses_to_emit_a_stage():
    prof = load_profile(PARTIAL)
    with pytest.raises(ModelProfileError, match="unavailable"):
        prof.to_compute_intent(participants=4)

def test_absent_duration_requires_an_explicit_reason():
    doc = _doc(layers=[{"index": 0, "kind": "attention", "duration_ns": None}])
    with pytest.raises(ProfileIngestError, match="non-empty `missing`"):
        profile_from_document(doc)

def test_missing_duration_key_refuses_rather_than_defaulting_to_zero():
    doc = _doc(layers=[{"index": 0, "kind": "attention"}])
    with pytest.raises(ProfileIngestError, match="duration_ns is required"):
        profile_from_document(doc)

def test_a_measured_layer_may_not_also_claim_to_be_missing():
    doc = _doc(layers=[{"index": 0, "kind": "attention", "duration_ns": 5,
                        "missing": "nope"}])
    with pytest.raises(ProfileIngestError, match="has no absence"):
        profile_from_document(doc)

def test_unknown_keys_refuse_at_both_levels():
    with pytest.raises(ProfileIngestError, match="unknown fields"):
        profile_from_document(_doc(surprise=1))
    doc = _doc(layers=[{"index": 0, "kind": "attention", "duration_ns": 1,
                        "sneaky": True}])
    with pytest.raises(ProfileIngestError, match="unknown fields"):
        profile_from_document(doc)

def test_wrong_schema_refuses():
    with pytest.raises(ProfileIngestError, match="schema must be"):
        profile_from_document(_doc(schema="veritx.model-profile/2"))
    with pytest.raises(ProfileIngestError, match="schema must be"):
        profile_from_document(_doc(schema=None))

def test_geometry_is_validated():
    with pytest.raises(ProfileIngestError, match="tp must be an integer >= 1"):
        profile_from_document(_doc(tp=0))

def test_non_llm_stage_kinds_are_accepted():
    """The compute grammar is domain-neutral; so is ingestion."""
    doc = _doc(layers=[
        {"index": 0, "kind": "correlate", "duration_ns": 89000},
        {"index": 0, "kind": "halo_exchange", "duration_ns": 1200}])
    prof = profile_from_document(doc)
    assert [l.kind for l in prof.layers] == ["correlate", "halo_exchange"]

def test_an_unnamed_stage_kind_refuses():
    with pytest.raises(ProfileIngestError, match="kind must be a non-empty"):
        profile_from_document(_doc(layers=[
            {"index": 0, "kind": "  ", "duration_ns": 1}]))

def test_negative_and_non_integer_bytes_refuse():
    with pytest.raises(ProfileIngestError, match="input_bytes"):
        profile_from_document(_doc(layers=[
            {"index": 0, "kind": "attention", "duration_ns": 1,
             "input_bytes": -1}]))
    with pytest.raises(ProfileIngestError, match="weight_bytes"):
        profile_from_document(_doc(layers=[
            {"index": 0, "kind": "attention", "duration_ns": 1,
             "weight_bytes": 1.5}]))

def test_layer_indexes_must_be_contiguous():
    doc = _doc(layers=[
        {"index": 0, "kind": "attention", "duration_ns": 1},
        {"index": 2, "kind": "dense_ffn", "duration_ns": 1}])
    with pytest.raises(ProfileIngestError, match="without gaps"):
        profile_from_document(doc)

def test_non_json_and_missing_file_refuse(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ProfileIngestError, match="invalid JSON"):
        load_profile(bad)
    with pytest.raises(ProfileIngestError, match="not found"):
        load_profile(tmp_path / "absent.json")

def test_round_trips_through_the_public_schema_key():
    doc = json.loads(Path(EXAMPLE).read_text())
    assert doc["schema"] == SCHEMA
    prof = profile_from_document(doc)
    assert prof.weight_source.startswith("customer profile: customer silicon")

def test_absent_provenance_is_unclaimed_origin_never_measured():
    """A profile without a provenance block must not silently become
    measured: unclaimed origin rides as `unspecified`, never as data."""
    prof = profile_from_document(_doc())
    assert prof.source.kind == "unspecified"
    assert not prof.source.specified


def test_explicit_provenance_kinds_survive_ingest():
    from veritx_dse.model.compute_intent import ComputeSource
    measured = _doc(provenance={
        "kind": "measured", "detail": "d",
        "reference": "silicon run 2026-03-14"})
    assert profile_from_document(measured).source.kind == "measured"
    declared = _doc(provenance={"kind": "declared", "detail": "chosen"})
    assert profile_from_document(declared).source.kind == "declared"
    assert isinstance(
        profile_from_document(_doc()).source, ComputeSource)
