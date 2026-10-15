"""Compute-duration quantization contract (§4.5).

The whole-microsecond conversion helper refuses lossy conversion.
The qualified v1 replay path represents remainders with chained 1-ns compute
nodes, so its declared cycle floor remains in exact nanoseconds. The old
`max(1, ns // 1000)` invented up to 1000x compute time.

Boundary contract for compute_micros:
  None / negative -> refuse (no timing without a duration)
  1..999 ns      -> refuse (unrepresentable without inventing time)
  0 ns           -> 0 (exactly representable)
  1000 ns        -> 1 (exact)
  non-multiple of 1000 ns -> refuse (no lossy timing evidence)
"""
from __future__ import annotations

import pytest

from veritx_dse.backend.astra import AstraError, compute_micros


def test_one_nanosecond_refuses():
    with pytest.raises(AstraError, match="cannot represent"):
        compute_micros(1, "op-1")


def test_999_nanoseconds_refuses():
    with pytest.raises(AstraError, match="cannot represent"):
        compute_micros(999, "op-999")


def test_exact_microsecond_passes():
    assert compute_micros(1000, "op-exact") == 1


def test_1001_nanoseconds_refuses_lossy_quantization():
    with pytest.raises(AstraError, match="cannot represent exactly"):
        compute_micros(1001, "op-1001")


def test_missing_duration_refuses():
    with pytest.raises(AstraError, match="no duration"):
        compute_micros(None, "op-gap")


def test_negative_duration_refuses():
    with pytest.raises(AstraError, match="invalid duration"):
        compute_micros(-5, "op-neg")


def test_zero_is_exactly_representable():
    assert compute_micros(0, "op-zero") == 0


def test_non_integer_duration_refuses():
    with pytest.raises(AstraError, match="invalid duration"):
        compute_micros(1500.5, "op-float")


@pytest.mark.parametrize("duration_ns", [True, False])
def test_boolean_duration_refuses(duration_ns):
    with pytest.raises(AstraError, match="invalid duration"):
        compute_micros(duration_ns, "op-bool")


@pytest.mark.parametrize("duration_ns", [0, 1, 999, 1000, 1001, 61200])
def test_declared_compute_cycles_preserves_exact_nanoseconds(duration_ns):
    """The projected floor never quantizes the authored compute demand."""
    from test_astra_projection import _logical, _ops, COUNT  # noqa: E402
    from veritx_dse.backend import astra  # noqa: E402
    from veritx_dse.workload.graph import (  # noqa: E402
        KIND_COMPUTE, OperationNode, compute_detail,
    )
    ops = (OperationNode(
        operation_id="tiny", kind=KIND_COMPUTE,
        detail=compute_detail(duration_ns=duration_ns, participant_count=COUNT)),)
    compiled, logical = _logical(ops)
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    assert projection.declared_compute_cycles() == duration_ns


def test_declared_compute_cycles_sums_whole_microseconds():
    from test_astra_projection import _projection  # noqa: E402
    projection = _projection()
    assert projection.declared_compute_cycles() == 10000
