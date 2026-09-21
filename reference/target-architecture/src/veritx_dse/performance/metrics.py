from fractions import Fraction
from veritx_dse.core.errors import InvalidInput


def request_latencies(workload,schedule):
    by=schedule.by_id(); out={}
    for req in workload.requests:
        completion=by[req.completion_event_id].end
        if completion<req.arrival: raise InvalidInput("request completes before arrival")
        out[req.request_id]=completion.q-req.arrival.q
    return out


def utilization(schedule):
    makespan=schedule.makespan().q
    if makespan==0: return {}
    busy={}
    for e in schedule.events: busy[e.resource]=busy.get(e.resource,Fraction())+(e.end.q-e.start.q)
    return {k:v/makespan for k,v in busy.items()}
