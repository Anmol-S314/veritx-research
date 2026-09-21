import hashlib
from dataclasses import dataclass

import pytest

from veritx_dse.application.results import EvaluationResult
from veritx_dse.application.service import VeriTXService
from veritx_dse.backend.evidence import EvidenceArtifact
from veritx_dse.core.errors import BackendFailure, EvidenceInvalid, InvalidInput
from veritx_dse.model.fabric import FabricSpec
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.model.parallelism import ParallelismArtifact
from veritx_dse.workload.graph import (OperationKind, OperationNode, WorkloadGraph,
                                      WorkloadSemantics)

INPUT=b"0 1 64 1 0\n1 2 64 1 1\n"
RAW=b"delivered_packets 2\n"


def evidence(**overrides):
    kwargs=dict(backend="TEST_BACKEND",backend_input_id="traffic-a",
                input_bytes=INPUT,raw_evidence=RAW,counters={"delivered_packets":2})
    kwargs.update(overrides)
    return EvidenceArtifact.build(**kwargs)


def graph(payload):
    p=ParallelismArtifact(1,1,1,2)
    op=OperationNode.create("x",OperationKind.P2P,
        detail={"role":"TRANSFER","src_rank":0,"dst_rank":1,"payload_bytes":payload})
    return WorkloadGraph.create(parallelism=p,participant_count=2,
                                semantics=WorkloadSemantics.create(),operations=(op,))


@dataclass
class RecordingBackend:
    name:str="TEST_BACKEND"
    raw:bytes=RAW
    def evaluate(self,*,input_id,payload):
        return self.raw
    def parse(self,raw):
        return (("delivered_packets",int(raw.split()[1])),),"test/parser/v1"


def compiled(payload=64):
    fabric=FabricSpec(2,"MESH",128,64); mapping=MappingArtifact(2,(0,1),fabric.fabric_id())
    return VeriTXService().compile(graph(payload),fabric=fabric,mapping=mapping)


# --- byte authentication -------------------------------------------------

def test_digests_are_of_the_actual_bytes():
    ev=evidence()
    assert ev.backend_input_sha256==hashlib.sha256(INPUT).hexdigest()
    assert ev.raw_evidence_sha256==hashlib.sha256(RAW).hexdigest()
    assert ev.authenticates(input_bytes=INPUT,raw_evidence=RAW)
    assert not ev.authenticates(input_bytes=INPUT+b"x",raw_evidence=RAW)
    assert not ev.authenticates(input_bytes=INPUT,raw_evidence=RAW+b"x")


def test_no_counters_without_raw_evidence():
    with pytest.raises(BackendFailure):
        evidence(raw_evidence=b"")


def test_backend_input_change_moves_identity_only():
    a,b=evidence(),evidence(input_bytes=INPUT+b"0 1 64 1 2\n")
    assert a.counters==b.counters
    assert a.backend_input_sha256!=b.backend_input_sha256
    assert a.evidence_id()!=b.evidence_id()


def test_raw_evidence_change_moves_identity_with_same_counters():
    a,b=evidence(),evidence(raw_evidence=b"delivered_packets 2\n# extra\n")
    assert a.counters==b.counters
    assert a.raw_evidence_sha256!=b.raw_evidence_sha256
    assert a.evidence_id()!=b.evidence_id()


def test_stats_digest_authenticates_counters():
    ev=evidence()
    with pytest.raises(EvidenceInvalid):
        EvidenceArtifact(ev.backend,ev.backend_input_id,ev.backend_input_sha256,
                         ev.raw_evidence_sha256,ev.parser_version,
                         (("delivered_packets",999),),ev.stats_sha256)


def test_counters_are_canonically_ordered_and_order_independent():
    a,b=evidence(counters=(("z",1),("a",2))),evidence(counters={"a":2,"z":1})
    assert a.counters==(("a",2),("z",1))
    assert a.evidence_id()==b.evidence_id()


@pytest.mark.parametrize("counters",[{"x":-1},{"x":"2"},[("x",1),("x",2)],
                                     {"":1},{"x":1.0},[("x",)]])
def test_invalid_counters_refuse(counters):
    with pytest.raises(InvalidInput):
        EvidenceArtifact.build(backend="B",backend_input_id="t",input_bytes=INPUT,
                               raw_evidence=RAW,counters=counters)


def test_parser_version_is_identity_bearing():
    a,b=evidence(parser_version="p/1"),evidence(parser_version="p/2")
    assert a.evidence_id()!=b.evidence_id()


# --- persistence ---------------------------------------------------------

def test_round_trip_is_tamper_closed():
    ev=evidence()
    assert EvidenceArtifact.from_dict(ev.to_dict())==ev
    doc=ev.to_dict(); doc["counters"]={"delivered_packets":999}
    with pytest.raises(EvidenceInvalid):
        EvidenceArtifact.from_dict(doc)
    doc=ev.to_dict(); doc["raw_evidence_sha256"]="0"*64
    with pytest.raises(EvidenceInvalid):
        EvidenceArtifact.from_dict(doc)
    doc=ev.to_dict(); doc["stats_sha256"]="deadbeef"
    with pytest.raises(EvidenceInvalid):
        EvidenceArtifact.from_dict(doc)
    doc=ev.to_dict(); doc["unexpected"]=1
    with pytest.raises(InvalidInput):
        EvidenceArtifact.from_dict(doc)


# --- ancestry ------------------------------------------------------------

def test_result_identity_includes_evidence_ancestry():
    a=compiled(64); backend=RecordingBackend()
    ra=VeriTXService().evaluate(a,backend=backend)
    rb=VeriTXService().evaluate(a,backend=RecordingBackend(raw=b"delivered_packets 2\n# t\n"))
    assert ra.evidence.counters==rb.evidence.counters
    assert ra.result_id()!=rb.result_id()


def test_evidence_for_another_traffic_cannot_be_transplanted():
    service=VeriTXService(); a,b=compiled(64),compiled(128)
    ra=service.evaluate(a,backend=RecordingBackend())
    with pytest.raises(EvidenceInvalid):
        EvaluationResult(b.graph.workload_id(),b.messages.message_artifact_id(),
                         b.traffic.traffic_id(),ra.evidence)


def test_result_identity_is_deterministic_across_runs():
    a=compiled(64)
    first=VeriTXService().evaluate(a,backend=RecordingBackend())
    second=VeriTXService().evaluate(a,backend=RecordingBackend())
    assert first.result_id()==second.result_id()
