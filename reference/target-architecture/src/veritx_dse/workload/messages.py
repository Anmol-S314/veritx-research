from dataclasses import dataclass
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import ConservationFailed, UnsupportedSemantic
from .graph import OperationKind
from .collectives import collective_schedule

DOMAIN="veritx/logical-messages/v2"


@dataclass(frozen=True)
class LogicalMessage:
    message_id:str; operation_id:str; phase:str|None
    src_rank:int; dst_rank:int; payload_bytes:int; step:int
    def to_dict(self): return self.__dict__.copy()


@dataclass(frozen=True)
class OperationSchedule:
    operation_id:str; kind:str; algorithm:str
    payload_bytes:int; message_count:int; aggregate_bytes:int
    def to_dict(self): return self.__dict__.copy()


@dataclass(frozen=True)
class LogicalMessageArtifact:
    workload_id:str
    messages:tuple[LogicalMessage,...]
    schedules:tuple[OperationSchedule,...]
    schema_version:int=2
    def identity_dict(self):
        return {"schema_version":self.schema_version,"workload_id":self.workload_id,
                "messages":[m.to_dict() for m in self.messages],
                "schedules":[s.to_dict() for s in self.schedules]}
    def message_artifact_id(self): return content_id(DOMAIN,self.identity_dict())


def _embedded_collective(op):
    d=op.detail_dict()
    if op.kind==OperationKind.COLLECTIVE:
        return d["collective_kind"],tuple(d["participants"]),d["payload_bytes"],d["source"]
    if op.kind in {OperationKind.EXPERT_BEGIN,OperationKind.EXPERT_END} and d["collective_kind"] is not None:
        return d["collective_kind"],tuple(d["participants"]),d["payload_bytes"],None
    return None


def build_logical_messages(graph):
    rows=[]; schedules=[]; seq=0
    def add(op,src,dst,payload,step):
        nonlocal seq
        rows.append(LogicalMessage(f"{op.operation_id}#{seq}",op.operation_id,op.phase,src,dst,payload,step))
        seq+=1
    for op in graph.ordered_operations():
        coll=_embedded_collective(op)
        if coll:
            kind,participants,payload,source=coll
            transfers=collective_schedule(kind,participants,payload,source=source)
            for t in transfers: add(op,t.src,t.dst,t.bytes,t.step)
            schedules.append(OperationSchedule(op.operation_id,kind,"ROOT_FANOUT" if kind=="BROADCAST" else "RING",
                                               payload,len(transfers),sum(t.bytes for t in transfers)))
            continue
        d=op.detail_dict()
        if op.kind==OperationKind.P2P:
            if d["role"]!="TRANSFER": raise UnsupportedSemantic(f"{d['role']} has no proven complete-message lowering")
            add(op,d["src_rank"],d["dst_rank"],d["payload_bytes"],0)
        elif op.kind==OperationKind.MULTICAST:
            for dst in d["destinations"]: add(op,d["source_rank"],dst,d["payload_bytes"],0)
    art=LogicalMessageArtifact(graph.workload_id(),tuple(rows),tuple(schedules))
    validate_message_conservation(graph,art)
    return art


def validate_message_conservation(graph,art):
    if art.workload_id!=graph.workload_id(): raise ConservationFailed("message parent mismatch")
    by={}
    for m in art.messages: by.setdefault(m.operation_id,[]).append(m)
    for op in graph.operations:
        d=op.detail_dict(); rows=by.get(op.operation_id,[])
        if op.kind==OperationKind.P2P and d["role"]=="TRANSFER":
            if len(rows)!=1 or rows[0].payload_bytes!=d["payload_bytes"]: raise ConservationFailed("P2P conservation failed")
        elif op.kind==OperationKind.MULTICAST:
            if sum(m.payload_bytes for m in rows)!=len(d["destinations"])*d["payload_bytes"]:
                raise ConservationFailed("multicast conservation failed")
        elif op.kind in {OperationKind.COMPUTE,OperationKind.PIM_CHANNEL,OperationKind.PIM_END} and rows:
            raise ConservationFailed(f"{op.kind} generated network messages")
