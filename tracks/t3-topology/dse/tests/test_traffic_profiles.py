"""Canonical per-initiator traffic profiles (v4-only P2P volume/mix layer).

A profile is DECLARED volume/class intent for one initiator→target transfer.
It lowers to the existing KIND_P2P TRANSFER path. Schema 3 stays frozen: the
key is unknown to the v3 document reader. This layer states volume and mix
only — no rate, burst or outstanding-request schedule is claimed.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
REPO = DSE.parents[2]
sys.path.insert(0, str(DSE))

from veritx_dse.core.errors import InvalidInput  # noqa: E402
from veritx_dse.model.compile_model import (  # noqa: E402
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    CompileRequestV3,
    CompileRequestV3SchemaError,
    DependencyGraph,
    ModelFamily,
    PhysicalContext,
    TrafficProfile,
    WorkloadV3,
    derive_v3_traffic_classes,
)
from veritx_dse.model.compile_request_v4 import (  # noqa: E402
    CompileRequestV4,
    CompileRequestV4SchemaError,
)
from veritx_dse.model.compute_intent import ComputeIntent  # noqa: E402
from veritx_dse.model.noc_controls import NocControls  # noqa: E402
from veritx_dse.model.topology_intent import MeshIntent  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    LoweredWorkload,
    lower_compile_workload,
)

TP_ALLREDUCE = CollectiveIntent(
    kind=CollectiveKind.ALLREDUCE,
    dimension=CollectiveDimension.TP,
    payload_bytes=8192,
    traffic_class="tp_collective",
)


def _profile(**overrides):
    base = dict(src_rank=0, dst_rank=1, traffic_class="p2p_bulk",
                payload_bytes=4096)
    base.update(overrides)
    return TrafficProfile(**base)


def _request(*, profiles=(), collectives=(TP_ALLREDUCE,)):
    """A minimal valid v4 request: 4 ranks on a 2x2 mesh, one TP collective."""
    return CompileRequestV4(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            model_name="traffic-profile-probe",
            tp=2, pp=1, ep=1, dp=2,
            collectives=tuple(collectives),
            traffic_profiles=tuple(profiles),
        ),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4,
                      protocol="AXI", data_width=256, addr_width=64),),
        topology=MeshIntent(side_length=2, concentration=1),
        noc_controls=NocControls(link_width=64),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        compute=ComputeIntent(stages=()),
    )


def test_profile_only_workload_lowers_to_p2p_transfers():
    profiles = (
        _profile(src_rank=0, dst_rank=1, traffic_class="p2p_bulk"),
        _profile(src_rank=2, dst_rank=3, traffic_class="p2p_latency",
                 payload_bytes=512),
    )
    lowered = lower_compile_workload(
        _request(profiles=profiles, collectives=()))
    ops = lowered.graph.of_kind("P2P")
    assert [op.operation_id for op in ops] == ["t000_p2p", "t001_p2p"]
    assert [dict(op.detail) for op in ops] == [
        {"role": "TRANSFER", "src_rank": 0, "dst_rank": 1,
         "payload_bytes": 4096},
        {"role": "TRANSFER", "src_rank": 2, "dst_rank": 3,
         "payload_bytes": 512},
    ]
    assert lowered.graph.of_kind("COLLECTIVE") == ()
    assert lowered.classes == ("p2p_bulk", "p2p_latency")


def test_design_hash_commits_to_profiles_and_roundtrips():
    base = _request(profiles=(
        _profile(),
        _profile(src_rank=2, dst_rank=3, traffic_class="p2p_latency",
                 payload_bytes=512),
    ))
    changed = _request(profiles=(
        _profile(payload_bytes=8192),
        _profile(src_rank=2, dst_rank=3, traffic_class="p2p_latency",
                 payload_bytes=512),
    ))
    assert base.design_hash() != changed.design_hash()

    doc = base.to_dict()
    assert doc["workload"]["traffic_profiles"] == [
        p.to_dict() for p in base.workload.traffic_profiles]
    back = CompileRequestV4.from_dict(doc)
    assert back.workload.traffic_profiles == base.workload.traffic_profiles
    assert back.design_hash() == base.design_hash()
    assert back.to_dict() == doc


def test_v4_without_profiles_serializes_no_empty_key():
    doc = _request(profiles=()).to_dict()
    assert "traffic_profiles" not in doc["workload"]
    assert CompileRequestV4.from_dict(doc).to_dict() == doc


def test_v3_document_refuses_traffic_profiles_as_unknown_field():
    from veritx_dse.model.compile_model import _WORKLOAD_V3_KEYS
    assert "traffic_profiles" not in _WORKLOAD_V3_KEYS

    doc = json.loads(
        (REPO / "tracks/t3-topology/examples/"
         "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    doc["workload"]["traffic_profiles"] = [_profile().to_dict()]
    with pytest.raises(CompileRequestV3SchemaError,
                       match="traffic_profiles"):
        CompileRequestV3.from_dict(doc)


@pytest.mark.parametrize("overrides, match", [
    (dict(src_rank=1, dst_rank=1), "must differ"),
    (dict(traffic_class=""), "non-empty"),
    (dict(payload_bytes=0), "payload_bytes"),
])
def test_traffic_profile_refuses_invalid_rows(overrides, match):
    with pytest.raises(ValueError, match=match):
        _profile(**overrides)


def test_v3_request_refuses_profiles_its_identity_cannot_express():
    import dataclasses

    doc = json.loads(
        (REPO / "tracks/t3-topology/examples/"
         "dense_1b_16tiles-v3.json").read_text())
    doc.pop("design_hash", None)
    doc.pop("guardrail_hash", None)
    v3 = CompileRequestV3.from_dict(doc)
    with pytest.raises(ValueError, match="v4-only"):
        dataclasses.replace(
            v3, workload=dataclasses.replace(
                v3.workload, traffic_profiles=(_profile(),)))


def test_workload_refuses_a_rank_outside_world_size():
    with pytest.raises(ValueError, match="world_size"):
        WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER,
                   tp=2, dp=2,
                   traffic_profiles=(_profile(src_rank=4, dst_rank=0),))


def test_workload_refuses_a_duplicate_pair_and_class():
    duplicate = _profile()
    with pytest.raises(ValueError, match="duplicate"):
        WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER,
                   tp=2, dp=2,
                   traffic_profiles=(duplicate, duplicate))


def test_workload_allows_one_pair_in_distinct_classes():
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, dp=2,
        traffic_profiles=(_profile(traffic_class="bulk"),
                          _profile(traffic_class="latency")))
    assert len(workload.traffic_profiles) == 2


def test_workload_refuses_a_non_profile_row():
    with pytest.raises(ValueError, match="TrafficProfile"):
        WorkloadV3(model_family=ModelFamily.DENSE_TRANSFORMER,
                   tp=2, dp=2, traffic_profiles=(object(),))


def test_traffic_profile_from_dict_is_strict():
    row = _profile().to_dict()
    row["rate_flits_per_cycle"] = 1
    with pytest.raises(ValueError, match="unknown field"):
        TrafficProfile.from_dict(row)

    missing = _profile().to_dict()
    del missing["payload_bytes"]
    with pytest.raises(ValueError, match="missing required field"):
        TrafficProfile.from_dict(missing)


def test_v4_parse_refuses_a_malformed_profile_row():
    doc = _request(profiles=(_profile(),)).to_dict()
    doc["workload"]["traffic_profiles"][0]["src_rank"] = 1
    doc["workload"]["traffic_profiles"][0]["dst_rank"] = 1
    with pytest.raises(CompileRequestV4SchemaError,
                       match="traffic_profiles"):
        CompileRequestV4.from_dict(doc)


def test_v4_parse_refuses_a_profile_rank_outside_world_size():
    doc = _request(profiles=(_profile(),)).to_dict()
    doc["workload"]["traffic_profiles"][0]["src_rank"] = 4
    with pytest.raises(CompileRequestV4SchemaError,
                       match="traffic_profiles"):
        CompileRequestV4.from_dict(doc)


def test_v4_parse_refuses_duplicate_profile_rows():
    doc = _request(profiles=(_profile(),)).to_dict()
    doc["workload"]["traffic_profiles"].append(
        dict(doc["workload"]["traffic_profiles"][0]))
    with pytest.raises(CompileRequestV4SchemaError, match="duplicate"):
        CompileRequestV4.from_dict(doc)


def test_v4_parse_refuses_a_non_array_profile_list():
    doc = _request(profiles=(_profile(),)).to_dict()
    doc["workload"]["traffic_profiles"] = {"src_rank": 0}
    with pytest.raises(CompileRequestV4SchemaError,
                       match="must be a JSON array"):
        CompileRequestV4.from_dict(doc)


def test_derive_v3_traffic_classes_includes_profile_classes():
    request = _request(profiles=(
        _profile(traffic_class="p2p_bulk"),
        _profile(src_rank=2, dst_rank=3, traffic_class="p2p_latency"),
    ))
    assert derive_v3_traffic_classes(request) == (
        "p2p_bulk", "p2p_latency", "tp_collective")


def test_lowered_class_sidecar_names_every_p2p_transfer_exactly_once():
    lowered = lower_compile_workload(_request(profiles=(
        _profile(),
        _profile(src_rank=2, dst_rank=3, traffic_class="p2p_latency",
                 payload_bytes=512),
    )))
    ids = [op for op, _ in lowered.traffic_class_by_operation]
    p2p = lowered.graph.of_kind("P2P")
    assert len(p2p) == 2
    for op in p2p:
        assert op.detail["role"] == "TRANSFER"
        assert ids.count(op.operation_id) == 1
    classes = dict(lowered.traffic_class_by_operation)
    assert classes["t000_p2p"] == "p2p_bulk"
    assert classes["t001_p2p"] == "p2p_latency"


def test_lowered_workload_refuses_a_p2p_transfer_without_a_class():
    lowered = lower_compile_workload(
        _request(profiles=(_profile(),), collectives=()))
    with pytest.raises(InvalidInput, match="P2P TRANSFER"):
        LoweredWorkload(graph=lowered.graph,
                        traffic_class_by_operation=(),
                        design_hash=lowered.design_hash)
