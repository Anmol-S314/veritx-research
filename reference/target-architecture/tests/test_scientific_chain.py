from dataclasses import dataclass
from veritx_dse.application.service import VeriTXService
from veritx_dse.model.fabric import FabricSpec
from veritx_dse.model.mapping import MappingArtifact
from veritx_dse.verification.scenarios import broadcast_nonzero_root
from veritx_dse.verification.provenance import ScientificChain


@dataclass
class RecordingBackend:
    name:str="TEST_BACKEND"
    def evaluate(self,*,input_id,payload):
        assert payload
        return f"{len(payload.splitlines())}\n".encode()
    def parse(self,raw):
        return (("delivered_packets",int(raw)),),"test/parser/v1"


def test_full_scientific_chain():
    graph=broadcast_nonzero_root().graph
    fabric=FabricSpec(4,"MESH",128,64); mapping=MappingArtifact(4,(0,1,2,3),fabric.fabric_id())
    compiled=VeriTXService().compile(graph,fabric=fabric,mapping=mapping)
    result=VeriTXService().evaluate(compiled,backend=RecordingBackend())
    chain=ScientificChain(graph.workload_id(),compiled.messages.message_artifact_id(),
                          compiled.traffic.traffic_id(),fabric.fabric_id(),mapping.mapping_id(),
                          result.evidence.evidence_id(),result.evidence.stats_sha256)
    chain.verify(workload_id=result.workload_id,message_artifact_id=result.message_artifact_id,
                 traffic_id=result.traffic_id,fabric_id=fabric.fabric_id(),mapping_id=mapping.mapping_id(),
                 evidence_id=result.evidence.evidence_id(),stats_sha256=result.evidence.stats_sha256)
