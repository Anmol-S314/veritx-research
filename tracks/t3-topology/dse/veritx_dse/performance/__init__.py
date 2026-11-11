"""veritx_dse.performance — system-performance semantics (§9/§111).

Rationale: docs/decisions/modules/performance.md
"""
from veritx_dse.performance.model import (
    ClockDef,
    COMPUTE_SOURCES,
    NETWORK_TIMING_BOOKSIM,
    ResourceDef,
    PerformanceModel,
    rate_duration,
)
from veritx_dse.performance.result import (
    OPTIONAL_RESULT_FIELDS,
    RESULT_FIELDS,
    ResultError,
    PerformanceEventGraph,
    build_performance_result,
    reverify_result,
)
from veritx_dse.performance.traffic_class import (
    ClassMeasurement,
    TRAFFIC_CLASS_LATENCY_FIELDS,
    TRAFFIC_CLASS_METRICS_SCHEMA_VERSION,
    TrafficClassMetricsError,
    build_traffic_class_metrics,
    parse_traffic_class_metrics,
    validate_traffic_class_metrics,
)
from veritx_dse.performance.scheduler import (
    Schedule,
    SchedulerDeadlock,
    ScheduledEvent,
    schedule_workload,
)
from veritx_dse.core.time import QTime, TimeError
from veritx_dse.performance.workload import (
    EVENT_KINDS,
    PerformanceRequest,
    TemporalEvent,
    TemporalWorkload,
)

__all__ = [
    "ClockDef", "COMPUTE_SOURCES", "EVENT_KINDS", "NETWORK_TIMING_BOOKSIM",
    "OPTIONAL_RESULT_FIELDS", "RESULT_FIELDS", "ResourceDef", "ResultError",
    "QTime", "Schedule",
    "SchedulerDeadlock", "ScheduledEvent", "TimeError", "PerformanceEventGraph",
    "PerformanceModel", "PerformanceRequest", "TemporalEvent",
    "TemporalWorkload", "build_performance_result", "rate_duration",
    "reverify_result", "schedule_workload",
    "ClassMeasurement", "TRAFFIC_CLASS_LATENCY_FIELDS",
    "TRAFFIC_CLASS_METRICS_SCHEMA_VERSION", "TrafficClassMetricsError",
    "build_traffic_class_metrics", "parse_traffic_class_metrics",
    "validate_traffic_class_metrics",
]
