from dataclasses import dataclass
from veritx_dse.core.errors import UnsupportedSchedule


@dataclass(frozen=True)
class ScheduledTransfer:
    src:int
    dst:int
    bytes:int
    step:int


def collective_schedule(kind, participants, payload_bytes, *, source=None):
    participants=tuple(participants); k=len(participants)
    if k<2: raise UnsupportedSchedule("collective requires >=2 participants")
    if payload_bytes<0: raise UnsupportedSchedule("negative payload")
    if kind=="BROADCAST":
        if source is None or source not in participants: raise UnsupportedSchedule("broadcast source required")
        return tuple(ScheduledTransfer(source,d,payload_bytes,0) for d in participants if d!=source)
    if kind in {"ALLREDUCE","REDUCESCATTER","ALLGATHER","ALLTOALL"} and payload_bytes % k:
        raise UnsupportedSchedule(f"{kind} exact schedule requires divisible payload")
    chunk=payload_bytes//k; out=[]
    if kind=="ALLREDUCE":
        for phase in range(2):
            for step in range(k-1):
                for i,src in enumerate(participants):
                    out.append(ScheduledTransfer(src,participants[(i+1)%k],chunk,phase*(k-1)+step))
    elif kind in {"REDUCESCATTER","ALLGATHER"}:
        for step in range(k-1):
            for i,src in enumerate(participants):
                out.append(ScheduledTransfer(src,participants[(i+1)%k],chunk,step))
    elif kind=="ALLTOALL":
        for i,src in enumerate(participants):
            for j,dst in enumerate(participants):
                if i!=j: out.append(ScheduledTransfer(src,dst,chunk,j))
    else:
        raise UnsupportedSchedule(f"unsupported collective {kind}")
    return tuple(out)
