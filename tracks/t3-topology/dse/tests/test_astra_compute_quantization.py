"""Compute-duration quantization contract (§4.5).

Chakra ET carries whole microseconds, so a nanosecond compute duration
reaches the backend only when it survives the conversion without inventing
time. The old `max(1, ns // 1000)` silently mapped 1ns (and 999ns, and a
missing duration) to a full microsecond — up to 1000x invented compute.

Boundary contract for compute_micros:
  None / negative -> refuse (no timing without a duration)
  1..999 ns      -> refuse (unrepresentable without inventing time)
  0 ns           -> 0 (exactly representable)
  1000 ns        -> 1 (exact)
  >= 1000 ns     -> floor(ns / 1000), remainder dropped and documented
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


def test_1001_nanoseconds_truncates_with_documented_boundary():
    # Representable with <0.1% loss; the remainder is dropped, never rounded
    # up, per the fidelity boundary in compute_micros.
    assert compute_micros(1001, "op-1001") == 1


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


def test_declared_compute_cycles_refuses_sub_microsecond_op():
    """The floor guard inherits the refusal: a 1ns op cannot set a floor."""
    from test_astra_projection import _logical, _ops, COUNT  # noqa: E402
    from veritx_dse.backend import astra  # noqa: E402
    from veritx_dse.workload.graph import (  # noqa: E402
        KIND_COMPUTE, OperationNode, compute_detail,
    )
    ops = (OperationNode(
        operation_id="tiny", kind=KIND_COMPUTE,
        detail=compute_detail(duration_ns=1, participant_count=COUNT)),)
    compiled, logical = _logical(ops)
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    with pytest.raises(AstraError, match="cannot represent"):
        projection.declared_compute_cycles()


def test_declared_compute_cycles_sums_whole_microseconds():
    from test_astra_projection import _projection  # noqa: E402
    projection = _projection()
    assert projection.declared_compute_cycles() == 10000
