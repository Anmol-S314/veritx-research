"""R1.4 — multi-instance liveness proof for the certified serving loop.

The existing liveness module classifies a *backend protocol* snapshot. This
module proves the property end-to-end on a real multi-instance run driven by
the certified loop: every active instance makes progress, the clock advances,
all requests retire exactly once, and no instance is starved (in particular,
not instance 0).

A per-instance table is built from the run's own round records:

    instance  queued  dispatched_rounds  completed  last_progress_time
"""
from __future__ import annotations

import dataclasses

from test_serving_loop import _run


CYCLE = 1000


@dataclasses.dataclass(frozen=True)
class InstanceProgress:
    instance: int
    queued: int
    dispatched_rounds: int
    completed: int
    last_progress_time: int


def _progress(result, instance_count: int) -> list[InstanceProgress]:
    queued = {i: 0 for i in range(instance_count)}
    completed = {i: 0 for i in range(instance_count)}
    dispatched = {i: 0 for i in range(instance_count)}
    last = {i: None for i in range(instance_count)}
    for request in result.requests:
        queued[request.instance_id] += 1
        completed[request.instance_id] += 1
    for record in result.rounds:
        for instance in record.dispatched_instances:
            dispatched[instance] += 1
            last[instance] = record.clock_after
    return [InstanceProgress(
        instance=i, queued=queued[i], dispatched_rounds=dispatched[i],
        completed=completed[i], last_progress_time=last[i] or 0,
    ) for i in range(instance_count)]


def test_every_instance_progresses_on_a_spread_trace(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 2, "arrival_time_ns": 0}
            for _ in range(8)]
    result, _, _ = _run(tmp_path, rows, instance_count=4,
                        session={"cycles": CYCLE})

    # every request retired exactly once, through its own instance
    assert len(result.requests) == 8
    assert sorted(int(r.request_id) for r in result.requests) == list(range(8))
    table = _progress(result, 4)
    assert all(row.queued == 2 for row in table), table
    assert all(row.completed == 2 for row in table), table
    # no permanent Waiting: every instance was dispatched and then progressed
    assert all(row.dispatched_rounds >= 2 for row in table), table
    assert all(row.last_progress_time > 0 for row in table), table
    # no instance-0 bias: all instances share the same progress
    assert len({row.dispatched_rounds for row in table}) == 1
    assert len({row.last_progress_time for row in table}) == 1

    # simulation time advances strictly round over round
    clocks = [r.clock_after for r in result.rounds]
    assert clocks == sorted(set(clocks))
    assert len(clocks) == len(set(clocks)) == len(result.rounds)
    # the service clock is exactly the sum of the fabric's own cycle counts
    assert result.clock == sum(r.backend_cycles for r in result.rounds)
    # ...and equals the model: 2 rounds (prefill + one decode) at 1000 each
    assert result.clock == 2 * CYCLE


def test_late_instance_does_not_block_the_early_ones(tmp_path):
    """An instance with no arrived request is idle, not a hang."""
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    result, _, _ = _run(tmp_path, rows, instance_count=4,
                        session={"cycles": CYCLE})
    # RR sends the two requests to instances 0 and 1; 2 and 3 stay idle
    table = _progress(result, 4)
    assert table[0].completed == 1 and table[1].completed == 1
    assert table[2].queued == 0 and table[3].queued == 0
    assert table[2].dispatched_rounds == 0 and table[3].dispatched_rounds == 0
    # the idle instances are named explicitly, never silently "served"
    assert result.rounds[0].idle_instances == (2, 3)
    assert result.evidence.instances_with_completions == (0, 1)
    assert not result.evidence.every_instance_served()


def test_no_request_retires_twice_or_before_its_arrival(tmp_path):
    rows = [{"input_toks": 8, "output_toks": 3, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 2, "arrival_time_ns": 2000}]
    result, _, _ = _run(tmp_path, rows, instance_count=2,
                        session={"cycles": CYCLE})
    retired = [rid for record in result.rounds
               for rid in record.retired_request_ids]
    assert len(retired) == len(set(retired)) == 2
    for request in result.requests:
        assert request.end_ns >= request.arrival_ns
        assert request.ttft_ns > 0
        # no round that completed before the arrival could have retired it
        for record in result.rounds:
            if record.clock_after <= request.arrival_ns:
                assert request.request_id not in record.retired_request_ids
