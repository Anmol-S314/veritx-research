"""Wave-E metric projection tests (PERF-1..PERF-5).

AMEND-5: Wave-E metrics were computed but unprojected. They are registered
through the EXISTING CertifiedMetricRegistry (a new version, not a
replacement — one authority per metric).

The critical discipline: these are ANALYTICAL/MODEL-DERIVED facts. Nothing
here may let one render as a backend measurement.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.optimization.metric_registry import (
    CERTIFIED_METRIC_REGISTRY,
    CERTIFIED_METRIC_REGISTRY_V1,
    WAVE_E_NOT_SCALAR,
    WAVE_E_SCALAR_METRICS,
    wave_e_honesty_metadata,
)


def _doc(**kw) -> dict:
    base = {
        "makespan": {"numerator": 100, "denominator": 1},
        "dependency_critical_path_duration": {"numerator": 60, "denominator": 1},
        "latency_summary": {"mean": {"numerator": 25, "denominator": 2}},
        "utilization": {"r0": {"utilization": 0.5},
                        "r1": {"utilization": 0.75}},
        "metrics_warning": "ANALYTICAL: not a measurement",
    }
    base.update(kw)
    return base


# ── PERF-1: every metric comes from the certified registry ──────────────

def test_perf_1_metrics_come_from_the_certified_registry():
    got = CERTIFIED_METRIC_REGISTRY.extract_all(_doc())
    assert got["makespan"] == 100.0
    assert got["critical_path"] == 60.0
    assert got["request_latency_mean"] == 12.5
    assert got["resource_utilization_max"] == 0.75
    for name in ("makespan", "critical_path", "request_latency_mean",
                 "resource_utilization_max"):
        assert CERTIFIED_METRIC_REGISTRY.has_metric(name)
        auth = CERTIFIED_METRIC_REGISTRY.authorities[name]
        assert auth.producer_id == f"wave-e-model/{name}"


def test_perf_1b_v2_is_a_new_version_not_a_replacement():
    """One authority per metric: the builder refuses duplicates, so v2
    extends v1 rather than silently replacing a producer."""
    assert CERTIFIED_METRIC_REGISTRY_V1.version == "certified-builtin-v1"
    assert CERTIFIED_METRIC_REGISTRY.version == "certified-builtin-v2"
    v1 = set(CERTIFIED_METRIC_REGISTRY_V1.metric_names())
    v2 = set(CERTIFIED_METRIC_REGISTRY.metric_names())
    assert v1 < v2, "v2 must be a strict superset of v1"
    assert v2 - v1 == {n for n, _ in WAVE_E_SCALAR_METRICS}
    # v1's authenticated metrics are untouched.
    for m in v1:
        assert (CERTIFIED_METRIC_REGISTRY.authorities[m].producer_id
                == CERTIFIED_METRIC_REGISTRY_V1.authorities[m].producer_id)


def test_perf_1c_exact_rational_not_rounded():
    got = CERTIFIED_METRIC_REGISTRY.extract_all(_doc())
    # 25/2 must be exact, and 1/3 must not be silently truncated.
    assert got["request_latency_mean"] == 12.5
    third = CERTIFIED_METRIC_REGISTRY.extract_all(
        _doc(makespan={"numerator": 1, "denominator": 3}))
    assert abs(third["makespan"] - (1 / 3)) < 1e-15


# ── PERF-2: unsupported metric is ABSENT, never zero ────────────────────

def test_perf_2_absent_metric_is_absent_not_zero():
    got = CERTIFIED_METRIC_REGISTRY.extract_all({})
    assert got == {}, "a metric with no value must be ABSENT, never 0"
    for name in ("makespan", "critical_path", "request_latency_mean",
                 "resource_utilization_max"):
        assert CERTIFIED_METRIC_REGISTRY.extract(name, {}) is None


def test_perf_2b_malformed_value_is_absent_not_zero():
    assert CERTIFIED_METRIC_REGISTRY.extract(
        "makespan", {"makespan": {"numerator": 1, "denominator": 0}}) is None
    assert CERTIFIED_METRIC_REGISTRY.extract(
        "makespan", {"makespan": "100"}) is None
    assert CERTIFIED_METRIC_REGISTRY.extract(
        "resource_utilization_max", {"utilization": {}}) is None


def test_perf_2c_declared_but_uncomputed_metrics_are_not_registered():
    """ttft and decode_step_latency are DECLARED in the Wave-E capability
    set but not computed in the performance result. Registering them would
    fabricate a metric, so they are explicitly recorded as not-scalar."""
    names = set(CERTIFIED_METRIC_REGISTRY.metric_names())
    assert "ttft" not in names
    assert "decode_step_latency" not in names
    assert "ttft" in WAVE_E_NOT_SCALAR
    assert "decode_step_latency" in WAVE_E_NOT_SCALAR


def test_perf_2d_every_unregistered_wave_e_fact_has_a_reason():
    for fact, reason in WAVE_E_NOT_SCALAR.items():
        assert isinstance(reason, str) and len(reason) > 20, fact


# ── PERF-3: fidelity warning propagates ────────────────────────────────

def test_perf_3_fidelity_warning_propagates():
    meta = wave_e_honesty_metadata(_doc())
    assert meta["fidelity_warning"] == "ANALYTICAL: not a measurement"


def test_perf_3b_warning_absent_is_none_not_a_default_string():
    meta = wave_e_honesty_metadata({"makespan": {"numerator": 1,
                                                 "denominator": 1}})
    assert meta["fidelity_warning"] is None


# ── PERF-4: predictive_validation NOT_ESTABLISHED stays explicit ────────

def test_perf_4_predictive_validation_is_exact():
    meta = wave_e_honesty_metadata(_doc())
    assert meta["predictive_validation"] == "NOT_ESTABLISHED"


def test_perf_4b_analytical_output_never_claims_to_be_measured():
    meta = wave_e_honesty_metadata(_doc())
    assert meta["authority"] == "ANALYTICAL_MODEL"
    assert meta["measured"] is False


def test_perf_4c_unsupported_facts_travel_with_the_metrics():
    meta = wave_e_honesty_metadata(_doc())
    for fact in ("throughput", "continuous_batching",
                 "per_operation_network_causality",
                 "analytical_compute_roofline", "memory_capacity"):
        assert fact in meta["unsupported"], fact


# ── PERF-5: no frontend-derived metric ─────────────────────────────────

def test_perf_5_metric_set_is_closed_and_server_owned():
    """The metric names are a frozen tuple on the registry; a consumer
    cannot add one. This is what stops Studio inferring metric validity."""
    names = CERTIFIED_METRIC_REGISTRY.metric_names()
    assert isinstance(names, tuple)
    with pytest.raises(Exception):
        CERTIFIED_METRIC_REGISTRY.authorities["invented"] = None


def test_perf_5b_experimental_registry_cannot_yield_certified_claims():
    """Registration does not make a metric valid: eligibility stays
    backend/registry driven, and a plugin registry is structurally
    distinct."""
    from veritx_dse.optimization.metric_registry import (
        ExperimentalMetricRegistry,
    )
    exp = ExperimentalMetricRegistry()
    exp.register("makespan", lambda v: 1.0)
    assert not isinstance(exp, type(CERTIFIED_METRIC_REGISTRY))
    assert getattr(exp, "certified", None) is False
