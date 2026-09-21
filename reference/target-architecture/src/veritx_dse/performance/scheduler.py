from dataclasses import dataclass
from veritx_dse.core.time import QTime
from veritx_dse.core.errors import InvalidInput


@dataclass(frozen=True)
class TemporalEvent:
    event_id:str
    deps:tuple[str,...]
    resource:str
    duration:QTime
    request_id:str|None=None


@dataclass(frozen=True)
class Request:
    request_id:str
    arrival:QTime
    completion_event_id:str
    first_token_event_id:str|None=None


@dataclass(frozen=True)
class TemporalWorkload:
    events:tuple[TemporalEvent,...]
    requests:tuple[Request,...]=()
    def __post_init__(self):
        if not self.events: raise InvalidInput("temporal workload cannot be empty")
        ids={e.event_id for e in self.events}
        if len(ids)!=len(self.events): raise InvalidInput("duplicate event ids")
        for e in self.events:
            if any(d not in ids for d in e.deps): raise InvalidInput("missing event dependency")
        rids=[r.request_id for r in self.requests]
        if len(rids)!=len(set(rids)): raise InvalidInput("duplicate request ids")
        for r in self.requests:
            if r.completion_event_id not in ids: raise InvalidInput("missing request completion event")
            if r.first_token_event_id is not None and r.first_token_event_id not in ids:
                raise InvalidInput("missing first-token event")


@dataclass(frozen=True)
class ScheduledEvent:
    event_id:str; start:QTime; end:QTime; resource:str


@dataclass(frozen=True)
class Schedule:
    events:tuple[ScheduledEvent,...]
    def by_id(self): return {e.event_id:e for e in self.events}
    def makespan(self): return max((e.end for e in self.events),default=QTime.seconds(0))


def schedule_workload(workload,model):
    resources={r.name:r for r in model.resources}
    by={e.event_id:e for e in workload.events}
    arrivals={r.request_id:r.arrival for r in workload.requests}
    done={}; free={name:QTime.seconds(0) for name in resources}; remaining=set(by)
    while remaining:
        ready=sorted(eid for eid in remaining if all(d in done for d in by[eid].deps))
        if not ready: raise InvalidInput("temporal DAG contains a cycle")
        eid=ready[0]; event=by[eid]
        if event.resource not in resources: raise InvalidInput("unknown resource")
        start=QTime.seconds(0)
        for dep in event.deps:
            if done[dep].end>start: start=done[dep].end
        if event.request_id in arrivals and arrivals[event.request_id]>start: start=arrivals[event.request_id]
        if free[event.resource]>start: start=free[event.resource]
        end=start+event.duration
        done[eid]=ScheduledEvent(eid,start,end,event.resource); free[event.resource]=end; remaining.remove(eid)
    return Schedule(tuple(done[e.event_id] for e in workload.events))
