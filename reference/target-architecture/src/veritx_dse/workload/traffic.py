from dataclasses import dataclass
from math import ceil
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import MappingInvalid, ConservationFailed

DOMAIN="veritx/physical-traffic/v2"


@dataclass(frozen=True)
class Packet:
    packet_id:str; message_id:str; src_endpoint:int; dst_endpoint:int; payload_bytes:int; flits:int
    def to_dict(self): return self.__dict__.copy()


@dataclass(frozen=True)
class PhysicalTrafficArtifact:
    message_artifact_id:str; mapping_id:str; fabric_id:str; packets:tuple[Packet,...]; schema_version:int=2
    def identity_dict(self):
        return {"schema_version":self.schema_version,"message_artifact_id":self.message_artifact_id,
                "mapping_id":self.mapping_id,"fabric_id":self.fabric_id,
                "packets":[p.to_dict() for p in self.packets]}
    def traffic_id(self): return content_id(DOMAIN,self.identity_dict())


def build_physical_traffic(graph,logical,*,mapping,fabric,packet_payload_bytes=256):
    if logical.workload_id!=graph.workload_id(): raise MappingInvalid("logical parent mismatch")
    if mapping.participant_count!=graph.participant_count: raise MappingInvalid("participant namespace mismatch")
    if mapping.fabric_id!=fabric.fabric_id(): raise MappingInvalid("mapping bound to another fabric")
    if any(ep>=fabric.endpoints for ep in mapping.rank_to_endpoint): raise MappingInvalid("endpoint outside fabric")
    packets=[]
    for msg in logical.messages:
        rem=msg.payload_bytes; part=0
        while rem:
            payload=min(packet_payload_bytes,rem)
            packets.append(Packet(f"{msg.message_id}/p{part}",msg.message_id,
                                  mapping.endpoint_for(msg.src_rank),mapping.endpoint_for(msg.dst_rank),
                                  payload,ceil(payload*8/fabric.flit_bits)))
            rem-=payload; part+=1
    art=PhysicalTrafficArtifact(logical.message_artifact_id(),mapping.mapping_id(),fabric.fabric_id(),tuple(packets))
    validate_traffic_conservation(logical,art)
    return art


def validate_traffic_conservation(logical,traffic):
    totals={}
    for p in traffic.packets: totals[p.message_id]=totals.get(p.message_id,0)+p.payload_bytes
    for m in logical.messages:
        if totals.get(m.message_id,0)!=m.payload_bytes: raise ConservationFailed(f"packetization failed for {m.message_id}")
