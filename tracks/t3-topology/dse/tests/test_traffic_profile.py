"""Tests for the strict single-class traffic-profile front end.

No BookSim binary is required: generation is pure Python and validation uses
the shared strict scanner in ``veritx_dse.backend.booksim``.
"""
from __future__ import annotations

from fractions import Fraction

import pytest

from veritx_dse.core.errors import SemanticError
from veritx_dse.workload import traffic_profile as tp


SCHEMA = "veritx/traffic-profile/1"


def _profile(**overrides):
    """A valid profile document; overrides replace individual fields."""
    base = {
        "name": "cpu0",
        "src": 0,
        "targets": [1],
        "traffic_class": "compute",
        "payload_bytes": 8,
        "flit_width_bits": 64,
        "rate_flits_per_cycle": "1",
        "burst_flits": 8,
        "outstanding": 4,
        "read_write_ratio": "1:0",
        "response_latency_cycles": 10,
        "start_cycle": 0,
        "requests": 4,
        "protocol": "AXI",
        "qos_class": "best_effort",
        "latency_target_cycles": None,
    }
    base.update(overrides)
    return base


def _spec(**overrides):
    """A valid spec document; overrides replace individual fields."""
    base = {
        "schema": SCHEMA,
        "endpoint_count": 4,
        "max_packet_flits": 16,
        "cycles": 100,
        "seed": 7,
        "profiles": [_profile()],
    }
    base.update(overrides)
    return base


def _profile_obj(**overrides):
    """A directly constructed valid profile object."""
    base = {
        "name": "p",
        "src": 0,
        "targets": (1,),
        "traffic_class": "compute",
        "payload_bytes": 8,
        "rate_flits_per_cycle": Fraction(1),
        "burst_flits": 1,
        "outstanding": 1,
        "read_write_ratio": (1, 0),
        "response_latency_cycles": 0,
        "start_cycle": 0,
        "requests": 1,
    }
    base.update(overrides)
    return tp.InitiatorProfile(**base)


def _spec_obj(**overrides):
    """A directly constructed valid spec object."""
    base = {
        "profiles": (_profile_obj(),),
        "endpoint_count": 4,
        "max_packet_flits": 16,
        "cycles": 100,
        "seed": 0,
    }
    base.update(overrides)
    return tp.TrafficProfileSpec(**base)


def _rows(data):
    rows = []
    for line in data.decode("ascii").splitlines():
        parts = line.split()
        assert len(parts) == 5, f"not five columns: {line!r}"
        rows.append(tuple(int(part) for part in parts))
    return rows


def _peak_in_flight(rows, *, src, latency):
    """Peak requests whose [issue, issue+latency) interval covers a cycle."""
    issues = [cycle for cycle, row_src, _cls, _dst, _flits in rows
              if row_src == src]
    if not issues:
        return 0
    return max(
        sum(1 for issue in issues if issue <= cycle < issue + latency)
        for cycle in range(0, max(issues) + latency + 1)
    )


def test_error_is_value_and_semantic_error():
    err = tp.TrafficProfileError("nope")
    assert isinstance(err, ValueError)
    assert isinstance(err, SemanticError)
    assert err.code == "TRAFFIC_PROFILE_REFUSED"


def test_valid_spec_generates_deterministic_scannable_trace():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(
            name="cpu0",
            src=0,
            targets=[1, 2],
            burst_flits=1,
            outstanding=6,
            requests=6,
            response_latency_cycles=10,
        ),
    ]))
    data = tp.generate_trace(spec)
    assert data == tp.generate_trace(spec)

    summary = tp.scan_trace(
        data, endpoint_count=spec.endpoint_count,
        max_packet_flits=spec.max_packet_flits)
    assert summary == tp.TraceSummary(
        dialect="whitespace",
        num_packets=12,
        max_timestamp=15,
        endpoint_count=4,
    )

    rows = _rows(data)
    assert rows == sorted(rows, key=lambda r: (r[0], r[1], r[3], r[4]))
    for cycle, src, class_index, dst, flits in rows:
        assert cycle >= 0
        assert 0 <= src < spec.endpoint_count
        assert 0 <= dst < spec.endpoint_count
        assert class_index == 0
        assert 1 <= flits <= spec.max_packet_flits

    requests = [row for row in rows if row[1] == 0]
    responses = [row for row in rows if row[3] == 0]
    assert [row[0] for row in requests] == [0, 1, 2, 3, 4, 5]
    assert [row[3] for row in requests] == [1, 2, 1, 2, 1, 2]
    assert [row[0] for row in responses] == [10, 11, 12, 13, 14, 15]
    assert all(row[4] == 1 for row in rows)


def test_multiple_profiles_generate_independently_and_sort_canonically():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(
            name="a",
            src=0,
            targets=[2],
            burst_flits=1,
            outstanding=2,
            requests=2,
            response_latency_cycles=5,
        ),
        _profile(
            name="b",
            src=1,
            targets=[3],
            burst_flits=1,
            outstanding=2,
            requests=2,
            response_latency_cycles=5,
            start_cycle=1,
        ),
    ]))
    data = tp.generate_trace(spec)
    rows = _rows(data)
    assert rows == sorted(rows, key=lambda r: (r[0], r[1], r[3], r[4]))
    assert [row[0] for row in rows if row[1] == 0 and row[3] == 2] == [0, 1]
    assert [row[0] for row in rows if row[1] == 1 and row[3] == 3] == [1, 2]
    assert [row[0] for row in rows if row[1] == 2 and row[3] == 0] == [5, 6]
    assert [row[0] for row in rows if row[1] == 3 and row[3] == 1] == [6, 7]
    summary = tp.scan_trace(
        data, endpoint_count=4, max_packet_flits=16)
    assert summary.num_packets == 8
    assert summary.max_timestamp == 7


def test_from_dict_applies_optional_profile_defaults():
    d = _spec(profiles=[_profile()])
    for key in ("flit_width_bits", "protocol", "qos_class",
                "latency_target_cycles"):
        del d["profiles"][0][key]
    profile = tp.TrafficProfileSpec.from_dict(d).profiles[0]
    assert profile.flit_width_bits == 64
    assert profile.protocol == "AXI"
    assert profile.qos_class == "best_effort"
    assert profile.latency_target_cycles is None


def test_generated_row_format_is_exact():
    spec = tp.TrafficProfileSpec.from_dict(_spec(
        cycles=1,
        profiles=[_profile(
            payload_bytes=16,
            burst_flits=2,
            outstanding=1,
            requests=1,
            response_latency_cycles=3,
        )],
    ))
    assert tp.generate_trace(spec) == b"0 0 0 1 2\n3 1 0 0 2\n"


def test_token_bucket_rate_and_burst_schedule():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(
            rate_flits_per_cycle="1/4",
            burst_flits=8,
            outstanding=12,
            requests=12,
            response_latency_cycles=10,
            read_write_ratio="1:0",
        ),
    ]))
    rows = _rows(tp.generate_trace(spec))
    request_cycles = [cycle for cycle, src, _cls, _dst, _flits in rows
                      if src == 0]
    assert request_cycles == [0] * 8 + [4, 8, 12, 16]
    assert len(request_cycles) == 12


def test_outstanding_bounds_in_flight_against_declared_latency():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(
            rate_flits_per_cycle="1",
            burst_flits=8,
            outstanding=2,
            requests=20,
            response_latency_cycles=10,
            read_write_ratio="1:0",
        ),
    ]))
    rows = _rows(tp.generate_trace(spec))
    issues = [cycle for cycle, src, _cls, _dst, _flits in rows
              if src == 0]
    assert len(issues) == 20
    assert issues[:4] == [0, 0, 10, 10]
    assert issues == [cycle for pair in range(10)
                      for cycle in (pair * 10, pair * 10)]
    assert _peak_in_flight(rows, src=0, latency=10) == 2


def test_read_write_ratio_is_exact_over_full_periods():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(
            payload_bytes=16,
            burst_flits=32,
            outstanding=16,
            requests=9,
            read_write_ratio="2:1",
            response_latency_cycles=5,
        ),
    ]))
    rows = _rows(tp.generate_trace(spec))
    requests = [row for row in rows if row[1] == 0]
    responses = [row for row in rows if row[1] == 1 and row[3] == 0]
    assert len(requests) == 9
    assert all(row[4] == 2 for row in requests)
    assert len(responses) == 9
    # Read responses carry the payload; write acks are one flit.
    assert sum(1 for row in responses if row[4] == 2) == 6
    assert sum(1 for row in responses if row[4] == 1) == 3


def test_target_selection_is_round_robin_in_issue_order():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(
            targets=[1, 2, 3],
            burst_flits=1,
            outstanding=1,
            requests=7,
            response_latency_cycles=0,
        ),
    ]))
    rows = _rows(tp.generate_trace(spec))
    requests = [row for row in rows if row[1] == 0]
    assert [row[0] for row in requests] == [0, 1, 2, 3, 4, 5, 6]
    assert [row[3] for row in requests] == [1, 2, 3, 1, 2, 3, 1]


def test_requests_none_issues_until_window_ends():
    spec = tp.TrafficProfileSpec.from_dict(_spec(
        cycles=5,
        profiles=[_profile(
            requests=None,
            burst_flits=4,
            outstanding=10,
            response_latency_cycles=10,
        )],
    ))
    rows = _rows(tp.generate_trace(spec))
    request_cycles = [cycle for cycle, src, _cls, _dst, _flits in rows
                      if src == 0]
    assert request_cycles == [0, 0, 0, 0, 1, 2, 3, 4]
    summary = tp.scan_trace(
        tp.generate_trace(spec), endpoint_count=4, max_packet_flits=16)
    assert summary.num_packets == 16
    assert summary.max_timestamp == 14


def test_pending_responses_beyond_window_are_emitted():
    spec = tp.TrafficProfileSpec.from_dict(_spec(
        cycles=1,
        profiles=[_profile(
            burst_flits=1,
            outstanding=1,
            requests=1,
            response_latency_cycles=10,
        )],
    ))
    data = tp.generate_trace(spec)
    assert data == b"0 0 0 1 1\n10 1 0 0 1\n"
    summary = tp.scan_trace(
        data, endpoint_count=4, max_packet_flits=16)
    assert summary.max_timestamp == 10


def test_packet_flits_uses_ceiling_division():
    cases = [
        (8, 64, 1),
        (9, 64, 2),
        (64, 64, 8),
        (65, 64, 9),
        (8, 32, 2),
    ]
    for payload_bytes, flit_width_bits, expected in cases:
        profile = _profile_obj(
            payload_bytes=payload_bytes,
            flit_width_bits=flit_width_bits,
            burst_flits=expected,
        )
        assert profile.packet_flits == expected


def test_from_dict_parses_rate_and_ratio_forms():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(rate_flits_per_cycle="1/4", read_write_ratio="3:1"),
    ]))
    assert spec.profiles[0].rate_flits_per_cycle == Fraction(1, 4)
    assert spec.profiles[0].read_write_ratio == (3, 1)

    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(rate_flits_per_cycle="0.25", read_write_ratio=[3, 1]),
    ]))
    assert spec.profiles[0].rate_flits_per_cycle == Fraction(1, 4)
    assert spec.profiles[0].read_write_ratio == (3, 1)

    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(rate_flits_per_cycle=1, read_write_ratio=(3, 1)),
    ]))
    assert spec.profiles[0].rate_flits_per_cycle == Fraction(1, 1)
    assert spec.profiles[0].read_write_ratio == (3, 1)

    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(rate_flits_per_cycle=0.25, read_write_ratio=[3, 1]),
    ]))
    assert spec.profiles[0].rate_flits_per_cycle == Fraction(1, 4)
    assert spec.profiles[0].read_write_ratio == (3, 1)


def test_float_rate_must_be_exactly_representable():
    spec = tp.TrafficProfileSpec.from_dict(_spec(profiles=[
        _profile(rate_flits_per_cycle=0.25),
    ]))
    assert spec.profiles[0].rate_flits_per_cycle == Fraction(1, 4)
    with pytest.raises(tp.TrafficProfileError, match="exactly representable"):
        tp.TrafficProfileSpec.from_dict(_spec(profiles=[
            _profile(rate_flits_per_cycle=0.1),
        ]))


def test_seed_and_metadata_do_not_change_trace():
    first = tp.TrafficProfileSpec.from_dict(_spec(
        seed=1,
        profiles=[_profile(
            protocol="AXI",
            qos_class="best_effort",
            latency_target_cycles=None,
        )],
    ))
    second = tp.TrafficProfileSpec.from_dict(_spec(
        seed=999,
        profiles=[_profile(
            protocol="CHI",
            qos_class="low_latency",
            latency_target_cycles=5,
        )],
    ))
    assert tp.generate_trace(first) == tp.generate_trace(second)


def test_spec_refuses_multiple_traffic_classes():
    d = _spec(profiles=[
        _profile(name="a", src=0, targets=[1], traffic_class="compute"),
        _profile(name="b", src=1, targets=[0], traffic_class="memory"),
    ])
    with pytest.raises(tp.TrafficProfileError, match="single-class"):
        tp.TrafficProfileSpec.from_dict(d)

    first = _profile_obj(
        name="a", src=0, targets=(1,), traffic_class="compute")
    second = _profile_obj(
        name="b", src=1, targets=(0,), traffic_class="memory")
    with pytest.raises(tp.TrafficProfileError, match="single-class"):
        tp.TrafficProfileSpec(
            profiles=(first, second),
            endpoint_count=4,
            max_packet_flits=16,
            cycles=10,
            seed=0,
        )


@pytest.mark.parametrize("overrides", [{"src": 4}, {"targets": [4]}])
def test_spec_refuses_out_of_range_ranks(overrides):
    with pytest.raises(tp.TrafficProfileError, match="outside"):
        tp.TrafficProfileSpec.from_dict(_spec(profiles=[
            _profile(**overrides),
        ]))


def test_spec_refuses_duplicate_src():
    d = _spec(profiles=[
        _profile(name="a", src=0, targets=[1]),
        _profile(name="b", src=0, targets=[2]),
    ])
    with pytest.raises(tp.TrafficProfileError, match="duplicate src"):
        tp.TrafficProfileSpec.from_dict(d)


def test_spec_refuses_duplicate_name():
    d = _spec(profiles=[
        _profile(name="a", src=0, targets=[1]),
        _profile(name="a", src=1, targets=[0]),
    ])
    with pytest.raises(tp.TrafficProfileError, match="duplicate profile name"):
        tp.TrafficProfileSpec.from_dict(d)


def test_spec_refuses_payload_over_max_packet_flits():
    d = _spec(
        max_packet_flits=8,
        profiles=[_profile(payload_bytes=128, burst_flits=16)],
    )
    with pytest.raises(tp.TrafficProfileError, match="max_packet_flits"):
        tp.TrafficProfileSpec.from_dict(d)


def test_refuses_zero_rate():
    with pytest.raises(tp.TrafficProfileError, match="rate_flits_per_cycle"):
        tp.TrafficProfileSpec.from_dict(_spec(profiles=[
            _profile(rate_flits_per_cycle="0"),
        ]))


def test_refuses_burst_below_packet_flits():
    with pytest.raises(tp.TrafficProfileError, match="burst_flits"):
        tp.TrafficProfileSpec.from_dict(_spec(profiles=[
            _profile(payload_bytes=16, burst_flits=1),
        ]))


@pytest.mark.parametrize("ratio", [
    "0:0",
    "-1:2",
    "3:1:2",
    "a:b",
    "3",
    [3],
    [3, -1],
    [3, True],
    (3,),
])
def test_refuses_bad_ratio(ratio):
    with pytest.raises(tp.TrafficProfileError):
        tp.TrafficProfileSpec.from_dict(_spec(profiles=[
            _profile(read_write_ratio=ratio),
        ]))


def test_generate_refuses_zero_packets(monkeypatch):
    spec = tp.TrafficProfileSpec.from_dict(_spec())
    monkeypatch.setattr(tp, "_profile_rows", lambda spec, profile: [])
    with pytest.raises(tp.TrafficProfileError, match="zero packets"):
        tp.generate_trace(spec)


def test_refuses_unknown_top_level_key():
    d = _spec()
    d["bogus"] = 1
    with pytest.raises(tp.TrafficProfileError, match="bogus"):
        tp.TrafficProfileSpec.from_dict(d)


def test_refuses_unknown_profile_key():
    d = _spec(profiles=[_profile(bogus=1)])
    with pytest.raises(tp.TrafficProfileError, match="bogus"):
        tp.TrafficProfileSpec.from_dict(d)


def test_refuses_missing_top_level_key():
    d = _spec()
    del d["seed"]
    with pytest.raises(tp.TrafficProfileError, match="missing"):
        tp.TrafficProfileSpec.from_dict(d)


def test_refuses_missing_profile_key():
    d = _spec(profiles=[_profile()])
    del d["profiles"][0]["requests"]
    with pytest.raises(tp.TrafficProfileError, match="missing"):
        tp.TrafficProfileSpec.from_dict(d)


def test_refuses_bad_schema():
    with pytest.raises(tp.TrafficProfileError, match="schema"):
        tp.TrafficProfileSpec.from_dict(
            _spec(schema="veritx/traffic-profile/2"))


@pytest.mark.parametrize("rate", ["", "abc", "1/0", "1.2.3", True, None])
def test_refuses_malformed_rate(rate):
    with pytest.raises(tp.TrafficProfileError):
        tp.TrafficProfileSpec.from_dict(_spec(profiles=[
            _profile(rate_flits_per_cycle=rate),
        ]))


@pytest.mark.parametrize("overrides, match", [
    ({"name": ""}, "name"),
    ({"src": -1}, "src"),
    ({"src": True}, "int"),
    ({"targets": ()}, "targets"),
    ({"targets": [1]}, "tuple"),
    ({"targets": (1, 1)}, "unique"),
    ({"targets": (0,)}, "src"),
    ({"traffic_class": ""}, "traffic_class"),
    ({"payload_bytes": 0}, "payload_bytes"),
    ({"flit_width_bits": 0}, "flit_width_bits"),
    ({"rate_flits_per_cycle": Fraction(0)}, "rate_flits_per_cycle"),
    ({"rate_flits_per_cycle": 0.5}, "Fraction"),
    ({"burst_flits": 0}, "burst_flits"),
    ({"outstanding": 0}, "outstanding"),
    ({"read_write_ratio": (0, 0)}, "read_write_ratio"),
    ({"read_write_ratio": (-1, 1)}, "read_write_ratio"),
    ({"read_write_ratio": (1, 0, 0)}, "read_write_ratio"),
    ({"read_write_ratio": [1, 0]}, "tuple"),
    ({"response_latency_cycles": -1}, "response_latency_cycles"),
    ({"start_cycle": -1}, "start_cycle"),
    ({"requests": 0}, "requests"),
    ({"protocol": ""}, "protocol"),
    ({"qos_class": ""}, "qos_class"),
    ({"latency_target_cycles": -1}, "latency_target_cycles"),
])
def test_initiator_profile_refuses_bad_fields(overrides, match):
    with pytest.raises(tp.TrafficProfileError, match=match):
        _profile_obj(**overrides)


@pytest.mark.parametrize("overrides, match", [
    ({"profiles": ()}, "profiles"),
    ({"profiles": [_profile_obj()]}, "tuple"),
    ({"profiles": (object(),)}, "InitiatorProfile"),
    ({"endpoint_count": 0}, "endpoint_count"),
    ({"max_packet_flits": 0}, "max_packet_flits"),
    ({"cycles": 0}, "cycles"),
    ({"seed": -1}, "seed"),
])
def test_spec_refuses_bad_fields(overrides, match):
    with pytest.raises(tp.TrafficProfileError, match=match):
        _spec_obj(**overrides)


def test_scan_trace_returns_summary():
    summary = tp.scan_trace(
        b"0 0 0 1 1\n5 1 0 0 2\n",
        endpoint_count=2,
        max_packet_flits=2,
    )
    assert summary == tp.TraceSummary(
        dialect="whitespace",
        num_packets=2,
        max_timestamp=5,
        endpoint_count=2,
    )


@pytest.mark.parametrize("data", [
    b"",
    b"# only comments\n",
    b"0 0 0 1\n",
    b"0 0 0 1 0\n",
    b"0 0 0 1 9\n",
    b"0 0 0 2 1\n",
    b"0 2 0 1 1\n",
    b"-1 0 0 1 1\n",
    b"0 0 0 1 1\n0 0 0 5 1\n",
    b"nonsense\n",
    b"0 0 1 1 1\n",
])
def test_scan_trace_refuses_invalid_traces(data):
    with pytest.raises(tp.TrafficProfileError):
        tp.scan_trace(data, endpoint_count=2, max_packet_flits=8)


def test_scan_trace_refuses_nonzero_class():
    with pytest.raises(tp.TrafficProfileError, match="class index 1"):
        tp.scan_trace(
            b"0 0 1 1 1\n", endpoint_count=2, max_packet_flits=2)


def test_scan_trace_refuses_bad_bounds():
    with pytest.raises(tp.TrafficProfileError):
        tp.scan_trace("0 0 0 1 1\n", endpoint_count=2,
                      max_packet_flits=2)
    with pytest.raises(tp.TrafficProfileError):
        tp.scan_trace(b"0 0 0 1 1\n", endpoint_count=0,
                      max_packet_flits=2)
    with pytest.raises(tp.TrafficProfileError):
        tp.scan_trace(b"0 0 0 1 1\n", endpoint_count=2,
                      max_packet_flits=0)
