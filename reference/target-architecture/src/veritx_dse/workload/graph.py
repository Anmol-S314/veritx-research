from __future__ import annotations
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from veritx_dse.core.artifact import content_id
from veritx_dse.core.errors import InvalidInput
from veritx_dse.model.parallelism import ParallelismArtifact

DOMAIN = "veritx/workload-graph/v2"


class OperationKind(StrEnum):
    COMPUTE = "COMPUTE"
    COLLECTIVE = "COLLECTIVE"
    P2P = "P2P"
    MULTICAST = "MULTICAST"
    EXPERT_BEGIN = "EXPERT_BEGIN"
    EXPERT_END = "EXPERT_END"
    PIM_CHANNEL = "PIM_CHANNEL"
    PIM_END = "PIM_END"


COMM_KINDS = {"ALLREDUCE","REDUCESCATTER","ALLGATHER","ALLTOALL","BROADCAST"}
P2P_ROLES = {"TRANSFER","SEND","RECV"}


def _int(value, name, minimum=0):
    if type(value) is not int or value < minimum:
        raise InvalidInput(f"{name} must be int >= {minimum}")
    return value


def _freeze(value):
    if isinstance(value, list):
        return tuple(_freeze(v) for v in value)
    if isinstance(value, dict):
        return tuple((k,_freeze(v)) for k,v in sorted(value.items()))
    return value


def _thaw(value):
    if isinstance(value, tuple):
        if value and all(isinstance(x,tuple) and len(x)==2 and isinstance(x[0],str) for x in value):
            return {k:_thaw(v) for k,v in value}
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True)
class WorkloadSemantics:
    phase: str | None = None
    routing_policy: str | None = None
    shape: tuple[tuple[str,int], ...] | None = None
    model_descriptor_hash: str | None = None

    @classmethod
    def create(cls, *, phase=None, routing_policy=None, shape=None, model_descriptor_hash=None):
        fs = None
        if shape is not None:
            allowed={"num_layers","hidden_size","bytes_per_elem","decode_steps","num_experts","top_k"}
            if set(shape)-allowed:
                raise InvalidInput("unknown shape fields")
            for k,v in shape.items():
                _int(v,f"shape.{k}")
            fs=tuple(sorted(shape.items()))
        return cls(phase,routing_policy,fs,model_descriptor_hash)

    def to_dict(self):
        return {
            "phase": self.phase,
            "routing_policy": self.routing_policy,
            "shape": None if self.shape is None else dict(self.shape),
            "model_descriptor_hash": self.model_descriptor_hash
        }


@dataclass(frozen=True)
class OperationNode:
    operation_id: str
    kind: OperationKind
    deps: tuple[str,...] = ()
    owner: int | None = None
    phase: str | None = None
    step: int | None = None
    label: str | None = None
    detail: tuple[tuple[str,Any], ...] = ()

    @classmethod
    def create(cls, operation_id, kind, *, deps=(), owner=None, phase=None, step=None, label=None, detail=None):
        if not operation_id:
            raise InvalidInput("operation_id required")
        k=OperationKind(kind)
        if owner is not None: _int(owner,"owner")
        if step is not None: _int(step,"step")
        d=dict(detail or {})
        cls._validate_local(k,d)
        return cls(operation_id,k,tuple(deps),owner,phase,step,label,
                   tuple((key,_freeze(value)) for key,value in sorted(d.items())))

    @staticmethod
    def _validate_local(kind, d):
        expected = {
            OperationKind.COMPUTE: {"duration_ns","input_bytes","weight_bytes","output_bytes","input_loc","weight_loc","output_loc","batch_tag"},
            OperationKind.COLLECTIVE: {"collective_kind","participants","payload_bytes","scope","source"},
            OperationKind.P2P: {"role","src_rank","dst_rank","payload_bytes"},
            OperationKind.MULTICAST: {"source_rank","destinations","payload_bytes","replication"},
            OperationKind.EXPERT_BEGIN: {"expert_num","collective_kind","participants","payload_bytes","scope"},
            OperationKind.EXPERT_END: {"expert_num","collective_kind","participants","payload_bytes","scope"},
            OperationKind.PIM_CHANNEL: {"channel"},
            OperationKind.PIM_END: set(),
        }[kind]
        if set(d) != expected:
            raise InvalidInput(f"{kind.value} detail mismatch")
        if kind == OperationKind.COMPUTE:
            _int(d["duration_ns"],"duration_ns")
            for k in ("input_bytes","weight_bytes","output_bytes"): _int(d[k],k)
            for k in ("input_loc","weight_loc","output_loc","batch_tag"):
                if not isinstance(d[k],str) or not d[k]: raise InvalidInput(f"{k} required")
        elif kind == OperationKind.COLLECTIVE:
            if d["collective_kind"] not in COMM_KINDS: raise InvalidInput("unknown collective")
            if not isinstance(d["participants"],(list,tuple)) or len(d["participants"])<2: raise InvalidInput("collective requires >=2 participants")
            _int(d["payload_bytes"],"payload_bytes")
            if d["collective_kind"]=="BROADCAST":
                _int(d["source"],"source")
                if d["source"] not in d["participants"]: raise InvalidInput("broadcast source not participant")
            elif d["source"] is not None:
                raise InvalidInput("non-broadcast source forbidden")
        elif kind == OperationKind.P2P:
            if d["role"] not in P2P_ROLES: raise InvalidInput("unknown P2P role")
            _int(d["src_rank"],"src_rank"); _int(d["dst_rank"],"dst_rank"); _int(d["payload_bytes"],"payload_bytes")
        elif kind == OperationKind.MULTICAST:
            _int(d["source_rank"],"source_rank"); _int(d["payload_bytes"],"payload_bytes")
            if not isinstance(d["destinations"],(list,tuple)) or not d["destinations"]: raise InvalidInput("destinations required")
            if d["replication"]!="SOURCE_REPLICATION": raise InvalidInput("unsupported multicast replication")
        elif kind in {OperationKind.EXPERT_BEGIN,OperationKind.EXPERT_END}:
            if d["expert_num"] is not None: _int(d["expert_num"],"expert_num")
            if d["collective_kind"] is None:
                if any(d[x] is not None for x in ("participants","payload_bytes","scope")):
                    raise InvalidInput("bare expert marker has payload")
            else:
                if d["collective_kind"] not in COMM_KINDS-{"BROADCAST"}: raise InvalidInput("unsupported expert collective")
                if not isinstance(d["participants"],(list,tuple)) or len(d["participants"])<2: raise InvalidInput("expert participants invalid")
                _int(d["payload_bytes"],"payload_bytes")
        elif kind == OperationKind.PIM_CHANNEL:
            _int(d["channel"],"channel")

    def detail_dict(self):
        return {k:_thaw(v) for k,v in self.detail}

    def identity_dict(self):
        return {
            "operation_id":self.operation_id,"kind":self.kind.value,"deps":list(self.deps),
            "owner":self.owner,"phase":self.phase,"step":self.step,"detail":self.detail_dict()
        }

    def to_dict(self):
        return {**self.identity_dict(),"label":self.label}


@dataclass(frozen=True)
class WorkloadGraph:
    parallelism: ParallelismArtifact
    participant_count: int
    semantics: WorkloadSemantics
    operations: tuple[OperationNode,...]
    provenance: tuple[tuple[str,Any], ...] = field(default_factory=tuple)

    def __post_init__(self):
        _int(self.participant_count,"participant_count",1)
        if not self.operations: raise InvalidInput("empty workload")
        ids=[o.operation_id for o in self.operations]
        if len(ids)!=len(set(ids)): raise InvalidInput("duplicate operation ids")
        idset=set(ids)
        for op in self.operations:
            if op.owner is not None and op.owner>=self.participant_count: raise InvalidInput("owner outside participant namespace")
            if any(dep not in idset for dep in op.deps): raise InvalidInput("unknown dependency")
            self._validate_namespace(op)
            if self.semantics.phase is not None and op.phase is not None and op.phase!=self.semantics.phase:
                raise InvalidInput("global/per-op phase disagreement")
        self.ordered_operations()
        self._validate_markers()

    @classmethod
    def create(cls, *, parallelism, participant_count, semantics, operations, provenance=None):
        return cls(parallelism,participant_count,semantics,tuple(operations),tuple(sorted((provenance or {}).items())))

    def _validate_namespace(self,op):
        d=op.detail_dict(); ranks=[]
        if op.kind==OperationKind.COLLECTIVE:
            ranks+=list(d["participants"])
            if d["source"] is not None: ranks.append(d["source"])
        elif op.kind==OperationKind.P2P: ranks += [d["src_rank"],d["dst_rank"]]
        elif op.kind==OperationKind.MULTICAST: ranks += [d["source_rank"],*d["destinations"]]
        elif op.kind in {OperationKind.EXPERT_BEGIN,OperationKind.EXPERT_END}: ranks += list(d["participants"] or [])
        for r in ranks:
            _int(r,"rank")
            if r>=self.participant_count: raise InvalidInput("rank outside participant namespace")

    def ordered_operations(self):
        by={o.operation_id:o for o in self.operations}
        indeg={o.operation_id:len(o.deps) for o in self.operations}
        children={o.operation_id:[] for o in self.operations}
        for o in self.operations:
            for d in o.deps: children[d].append(o.operation_id)
        ready=sorted(k for k,v in indeg.items() if v==0); out=[]
        while ready:
            oid=ready.pop(0); out.append(by[oid])
            for ch in sorted(children[oid]):
                indeg[ch]-=1
                if indeg[ch]==0:
                    ready.append(ch); ready.sort()
        if len(out)!=len(self.operations): raise InvalidInput("cycle in workload")
        return tuple(out)

    def require_total_order(self):
        ordered=self.ordered_operations()
        for prev,cur in zip(ordered,ordered[1:]):
            if prev.operation_id not in cur.deps: raise InvalidInput("consumer requires total dependency order")
        return ordered

    def _validate_markers(self):
        ordered=self.ordered_operations()
        if any(o.kind in {OperationKind.EXPERT_BEGIN,OperationKind.EXPERT_END,OperationKind.PIM_CHANNEL,OperationKind.PIM_END} for o in ordered):
            self.require_total_order()
        expert=False; pim=False
        for op in ordered:
            if op.kind==OperationKind.EXPERT_BEGIN:
                if expert: raise InvalidInput("nested expert regions unsupported")
                expert=True
            elif op.kind==OperationKind.EXPERT_END:
                if not expert: raise InvalidInput("stray EXPERT_END")
                expert=False
            elif op.kind==OperationKind.PIM_CHANNEL:
                pim=True
            elif op.kind==OperationKind.PIM_END:
                if not pim: raise InvalidInput("stray PIM_END")
                pim=False
        if expert: raise InvalidInput("unclosed EXPERT_BEGIN")
        if pim: raise InvalidInput("unclosed PIM interval")

    def identity_dict(self):
        return {
            "schema_version":2,
            "parallelism_id":self.parallelism.parallelism_id(),
            "participant_count":self.participant_count,
            "semantics":self.semantics.to_dict(),
            "operations":[o.identity_dict() for o in self.ordered_operations()]
        }

    def workload_id(self):
        return content_id(DOMAIN,self.identity_dict())

    def to_dict(self):
        return {
            **self.identity_dict(),
            "parallelism":self.parallelism.to_dict(),
            "operations":[o.to_dict() for o in self.operations],
            "provenance":dict(self.provenance),
            "workload_id":self.workload_id()
        }

    def by_id(self,oid):
        for op in self.operations:
            if op.operation_id==oid: return op
        raise KeyError(oid)
