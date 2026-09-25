"""R1.2 — independent serving scheduling oracle.

The certified serving loop (``simulation/serving_loop.run_request_driven_service``)
is exercised elsewhere by invariant assertions (TTFT > 0, arrival gating,
``clock == sum(round cycles)``). Invariants are not an oracle: they cannot
falsify a wrong schedule. This module adds one.

``reference_schedule`` is a first-principles model of the certified profile's
declared, non-chunked semantics:

    one round  ->  route arrivals  ->  one batch per instance  ->  advance the
    clock by the backend's declared per-round cost  ->  retire what the batch
    produced

It is written from the documented contract only. It never imports or calls
``serving_loop``, the vendored ``Scheduler``/``Router``, or any veritx code
under test. The loop is then run with a fake runtime whose per-round cycle
cost is a declared constant, so every clock in the model is exact.

Two human-checkable tables are asserted literally first (so the model itself
is falsifiable), then the model is compared field-by-field against the real
loop for the same traces.
"""
from __future__ import annotations

import dataclasses

import pytest

from test_serving_loop import _run


# ── the independent reference model ───────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class ReferenceOutcome:
    request_id: str
    instance_id: int
    arrival: int
    prefill_start: int
    prefill_end: int
    first_token: int
    decode_rounds: int
    completion: int
    ttft: int
    latency: int


def reference_schedule(
    rows: list[dict],
    *,
    instance_count: int,
    cycle_cost: int,
    max_num_seqs: int = 8,
    max_num_batched_tokens: int = 1024,
) -> list[ReferenceOutcome]:
    """Closed-form schedule for the certified non-chunked serving semantics.

    ``rows`` are ``{"input_toks", "output_toks", "arrival_time_ns"}``. A round
    serves each instance at most one batch; a batch is the arrived, queued
    requests up to ``max_num_seqs`` and the token budget; a request's prefill
    completes in the round it is first batched; each later round decodes one
    token; the request retires when ``input + output_toks`` tokens have been
    produced (the prefill round already produces the first one).
    """
    n = len(rows)
    inputs = [int(r["input_toks"]) for r in rows]
    totals = [int(r["input_toks"]) + int(r["output_toks"]) for r in rows]
    arrivals = [int(r["arrival_time_ns"]) for r in rows]

    num_computed = [0] * n
    ttft = [None] * n
    recent_end = [0] * n
    itl: list[list[int]] = [[] for _ in range(n)]
    end = [None] * n
    instance = [None] * n
    prefill_start = [None] * n
    prefill_end = [None] * n

    pending = sorted(range(n), key=lambda i: (arrivals[i], i))
    queues: list[list[int]] = [[] for _ in range(instance_count)]
    rr = 0
    clock = 0

    for _ in range(1_000_000):
        # route every arrived request, round-robin in (arrival, id) order
        while pending and arrivals[pending[0]] <= clock:
            i = pending.pop(0)
            inst = rr % instance_count
            rr += 1
            instance[i] = inst
            queues[inst].append(i)

        batches: dict[int, list[int]] = {}
        for inst in range(instance_count):
            queue = queues[inst]
            selected: list[int] = []
            total = 0
            for i in queue:
                scheduled = inputs[i] if num_computed[i] < inputs[i] else 1
                if selected and total + scheduled > max_num_batched_tokens:
                    break
                selected.append(i)
                total += scheduled
                if len(selected) >= max_num_seqs:
                    break
            if selected:
                queues[inst] = queue[len(selected):]
                batches[inst] = selected
                for i in selected:
                    if num_computed[i] < inputs[i] and prefill_start[i] is None:
                        prefill_start[i] = clock

        if not batches:
            if not pending and all(not q for q in queues):
                break
            future = [arrivals[i] for i in pending]
            future += [arrivals[i] for q in queues for i in q]
            future = [t for t in future if t > clock]
            if not future:  # pragma: no cover - a trace that cannot progress
                break
            clock = min(future)
            continue

        clock += cycle_cost
        for inst, selected in batches.items():
            for i in selected:
                if num_computed[i] < inputs[i]:
                    num_computed[i] = inputs[i]
                    if ttft[i] is None:
                        ttft[i] = clock - arrivals[i]
                        recent_end[i] = clock
                        prefill_end[i] = clock
                else:
                    itl[i].append(clock - recent_end[i])
                    recent_end[i] = clock
                    num_computed[i] += 1
                if totals[i] <= num_computed[i] + 1:
                    end[i] = clock
                else:
                    queues[inst].append(i)

    return [
        ReferenceOutcome(
            request_id=str(i), instance_id=instance[i] or 0,
            arrival=arrivals[i], prefill_start=prefill_start[i] or 0,
            prefill_end=prefill_end[i] or 0, first_token=prefill_end[i] or 0,
            decode_rounds=len(itl[i]), completion=end[i] or 0,
            ttft=ttft[i] or 0, latency=(end[i] or 0) - arrivals[i],
        )
        for i in range(n)
    ]


CYCLE = 1000


def _observed(result, cycle_cost=CYCLE) -> list[ReferenceOutcome]:
    out = []
    for req in sorted(result.requests, key=lambda r: int(r.request_id)):
        first_token = req.arrival_ns + req.ttft_ns
        # In the certified non-chunked profile prefill completes in the round
        # it is first batched, so the batch was scheduled exactly one round
        # cost before the first token.
        out.append(ReferenceOutcome(
            request_id=req.request_id, instance_id=req.instance_id,
            arrival=req.arrival_ns, prefill_start=first_token - cycle_cost,
            prefill_end=first_token,
            first_token=first_token,
            decode_rounds=len(req.itl_ns), completion=req.end_ns,
            ttft=req.ttft_ns, latency=req.latency_ns))
    return out


CYCLE = 1000


# ── human-checkable tables (falsify the model itself) ─────────────────────

def test_hand_table_single_instance_prefill_then_decode():
    rows = [{"input_toks": 8, "output_toks": 2, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]
    got = reference_schedule(rows, instance_count=1, cycle_cost=CYCLE)
    expected = [
        # all requests are batchable at t=0 -> prefill ends at the first
        # round boundary (1000). req0 needs one more decode round (2000);
        # req1 retires from the prefill round (output_toks == 1).
        ReferenceOutcome("0", 0, 0, 0, 1000, 1000, 1, 2000, 1000, 2000),
        ReferenceOutcome("1", 0, 0, 0, 1000, 1000, 0, 1000, 1000, 1000),
    ]
    assert got == expected


def test_hand_table_two_instances_round_robin():
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 2, "arrival_time_ns": 0}]
    got = reference_schedule(rows, instance_count=2, cycle_cost=CYCLE)
    expected = [
        ReferenceOutcome("0", 0, 0, 0, 1000, 1000, 0, 1000, 1000, 1000),
        ReferenceOutcome("1", 1, 0, 0, 1000, 1000, 0, 1000, 1000, 1000),
        ReferenceOutcome("2", 0, 0, 0, 1000, 1000, 1, 2000, 1000, 2000),
    ]
    assert got == expected


def test_hand_table_late_arrival_gates_service():
    rows = [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
            {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 3000}]
    got = reference_schedule(rows, instance_count=1, cycle_cost=CYCLE)
    # req0 retires at 1000; the clock then jumps to the 3000 arrival, so req1
    # is batched at 3000 and first-tokens at 4000 (TTFT is measured from its
    # own arrival, 1000).
    assert got[1] == ReferenceOutcome("1", 0, 3000, 3000, 4000, 4000, 0,
                                       4000, 1000, 1000)


# ── the model vs the real loop ────────────────────────────────────────────

@pytest.mark.parametrize("instance_count,rows", [
    (1, [{"input_toks": 8, "output_toks": 2, "arrival_time_ns": 0},
         {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0}]),
    (2, [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
         {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
         {"input_toks": 8, "output_toks": 2, "arrival_time_ns": 0}]),
    (1, [{"input_toks": 8, "output_toks": 1, "arrival_time_ns": 0},
         {"input_toks": 8, "output_toks": 1, "arrival_time_ns": 3000}]),
    (1, [{"input_toks": 4, "output_toks": 3, "arrival_time_ns": 0},
         {"input_toks": 5, "output_toks": 4, "arrival_time_ns": 0},
         {"input_toks": 6, "output_toks": 2, "arrival_time_ns": 0}]),
])
def test_reference_model_matches_the_real_loop(tmp_path, instance_count, rows):
    result, _, _ = _run(tmp_path, rows, instance_count=instance_count,
                        session={"cycles": CYCLE})
    expected = reference_schedule(rows, instance_count=instance_count,
                                  cycle_cost=CYCLE)
    assert _observed(result) == expected
    # the service clock is exactly the model's finishes, and never leaves the
    # declared cycle domain
    assert result.clock == max(o.completion for o in expected)
