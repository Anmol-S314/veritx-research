from fractions import Fraction
from veritx_dse.core.time import QTime
from veritx_dse.performance.model import PerformanceModel,ResourceDef
from veritx_dse.performance.scheduler import TemporalEvent,TemporalWorkload,Request,schedule_workload
from veritx_dse.performance.metrics import request_latencies


def test_arrivals_and_resource_serialization_compose():
    model=PerformanceModel((ResourceDef("gpu","EXCLUSIVE"),))
    workload=TemporalWorkload(
        events=(
            TemporalEvent("a",(),"gpu",QTime.nanoseconds(10),request_id="r1"),
            TemporalEvent("b",(),"gpu",QTime.nanoseconds(10),request_id="r2"),
        ),
        requests=(
            Request("r1",QTime.nanoseconds(0),"a"),
            Request("r2",QTime.nanoseconds(5),"b"),
        )
    )
    s=schedule_workload(workload,model); lat=request_latencies(workload,s)
    assert lat["r1"]==Fraction(10,1_000_000_000)
    assert lat["r2"]==Fraction(15,1_000_000_000)
