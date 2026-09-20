"""veritx_dse.wavee — Wave E system-performance semantics (§9/§111).

Small, boring modules over exact rational time:

    time         canonical QTime (exact rational seconds) + clocks
    model        WaveEPerformanceModel (immutable, content-addressed)
    workload     temporal overlay: events, requests, graph laws
    scheduler    deterministic discrete-event schedule (the ONE scheduler)
    network      BookSim evidence → BARRIER network window (§36–§42)
    metrics      critical path / utilization / request latencies
    sensitivity  counterfactual bottleneck evidence (§48–§51)
    result       WaveEEventGraph + verified performance result (§65/§66)

Compute/memory calibration: UNCALIBRATED (no dataset in repo, §11 of
the contract). Analytical models stay labeled; no synthetic data.
"""
from veritx_dse.wavee.model import (
    ClockDef,
    COMPUTE_SOURCES,
    NETWORK_TIMING_BOOKSIM,
    ResourceDef,
    WaveEPerformanceModel,
    rate_duration,
)
from veritx_dse.wavee.result import (
    RESULT_FIELDS,
    ResultError,
    WaveEEventGraph,
    build_performance_result,
    reverify_result,
)
from veritx_dse.wavee.scheduler import (
    Schedule,
    SchedulerDeadlock,
    ScheduledEvent,
    schedule_workload,
)
from veritx_dse.wavee.time import QTime, TimeError
from veritx_dse.wavee.workload import (
    EVENT_KINDS,
    WaveERequest,
    WaveETemporalEvent,
    WaveETemporalWorkload,
)

__all__ = [
    "ClockDef", "COMPUTE_SOURCES", "EVENT_KINDS", "NETWORK_TIMING_BOOKSIM",
    "RESULT_FIELDS", "ResourceDef", "ResultError", "QTime", "Schedule",
    "SchedulerDeadlock", "ScheduledEvent", "TimeError", "WaveEEventGraph",
    "WaveEPerformanceModel", "WaveERequest", "WaveETemporalEvent",
    "WaveETemporalWorkload", "build_performance_result", "rate_duration",
    "reverify_result", "schedule_workload",
]
