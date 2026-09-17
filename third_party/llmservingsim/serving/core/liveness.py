"""Serving-loop liveness observation (VeriTX review-directed, post-PR5).

PURE observation — this module never mutates simulator state, never
aborts, never converts a stall into success/failure, and adds no
round-count threshold. The serving loop calls ``observe()`` once per
round with values it has ALREADY computed (plus cheap counters); the
probe:

  * classifies the round into the review-mandated state vocabulary
    (BACKEND_NOT_RESPONDING, BACKEND_RESPONSIVE_NO_TIME_ADVANCE,
    SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS, SCHEDULER_NO_DISPATCH,
    INFLIGHT_NO_COMPLETION, USEFUL_PROGRESS);
  * counts consecutive rounds whose progress fingerprint
    ``(sim_time, retired, pending, deferred, inflight, backend_completions)``
    is unchanged;
  * renders the NO_USEFUL_PROGRESS report (human block + machine JSON)
    on demand — on an explicit request (VERITX_LIVENESS_DUMP=n) or when
    the caller reports a failure (the existing EOF / spin-abort paths
    attach the latest observation).

NO_USEFUL_PROGRESS is an OBSERVATION, never a diagnosis: it does not
claim deadlock and does not change control flow. The report exists so
the question "which state stopped changing first?" has a
deterministic, evidence-backed answer for the historical multi-instance
livelock.

Field sources (serving/__main__.py round body):
  sim_time           — ``current`` (frontend clock; last backend-reported
                       cycle, optionally jumped by pass <t>)
  backend_cycle      — reply burst's trailing completion cycle
  backend_completions— completion lines in the current reply burst
  retired_requests   — ``req_cnt`` (cumulative)
  pending_requests   — router._pending_idx / len(router._pending_requests)
  deferred_requests  — len(router._deferred_sessions)
  inflight_batches   — sum(len(schedulers[i].inflight))
  dispatched_this_round — a new batch/workload was handed to the backend
  per-instance       — waiting/running/inflight (+dp-queued) per instance
  last_command       — the command (logical) issued for the next round
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Optional

# Review-mandated states. Order matters only for documentation: the
# classification below is exclusive by construction.
BACKEND_NOT_RESPONDING = "BACKEND_NOT_RESPONDING"
BACKEND_RESPONSIVE_NO_TIME_ADVANCE = "BACKEND_RESPONSIVE_NO_TIME_ADVANCE"
SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS = "SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS"
SCHEDULER_NO_DISPATCH = "SCHEDULER_NO_DISPATCH"
INFLIGHT_NO_COMPLETION = "INFLIGHT_NO_COMPLETION"
USEFUL_PROGRESS = "USEFUL_PROGRESS"


@dataclass
class ProgressObservation:
    """One round's observational snapshot (all values, no interpretation)."""
    round: int
    sim_time: Optional[int]           # frontend ``current``
    backend_cycle: Optional[int]      # trailing cycle in the reply burst
    backend_completions: int          # completion lines in this reply
    retired_requests: int             # req_cnt (cumulative)
    pending_requests: int             # router pending not yet routed
    deferred_requests: int            # router deferred sessions
    inflight_batches: int             # total scheduler.inflight
    dispatched_this_round: bool       # new workload handed to backend
    last_command: str                 # logical command issued this round
    per_instance: dict[str, dict[str, int]] = field(default_factory=dict)
    backend_alive: Optional[bool] = None   # proc.poll() is None
    note: str = ""                    # free-form context (e.g. dp_pending)

    def fingerprint(self) -> tuple:
        """Scientifically meaningful progress state (NOT wall-clock)."""
        return (self.sim_time, self.retired_requests, self.pending_requests,
                self.deferred_requests, self.inflight_batches,
                self.backend_completions)


class LivenessProbe:
    """Accumulates observations; classifies; renders reports on demand.

    The fast path is one dataclass construction + one tuple compare per
    round. No I/O, no formatting, unless a report is requested.
    """

    def __init__(self) -> None:
        self.rounds = 0
        self.last: Optional[ProgressObservation] = None
        self._fp: Optional[tuple] = None
        self.rounds_unchanged = 0
        self.history_tail: list[ProgressObservation] = []  # bounded tail

    def observe(self, obs: ProgressObservation) -> None:
        self.rounds += 1
        obs.round = self.rounds
        fp = obs.fingerprint()
        if fp == self._fp:
            self.rounds_unchanged += 1
        else:
            self.rounds_unchanged = 0
        self._fp = fp
        self.last = obs
        self.history_tail.append(obs)
        if len(self.history_tail) > 20:
            del self.history_tail[:len(self.history_tail) - 20]

    # -- classification ----------------------------------------------------

    def classify(self, obs: Optional[ProgressObservation] = None) -> str:
        """Exactly one state per round. Rules, in order:

        1. backend process dead                          -> BACKEND_NOT_RESPONDING
        2. backend answered, zero completions, no clock
           move, NOTHING inflight (pure idle ping-pong)  -> BACKEND_RESPONSIVE_NO_TIME_ADVANCE
        3. work inflight but zero completions in this
           reply (and nothing dispatched this round)     -> INFLIGHT_NO_COMPLETION
        4. clock advancing but retired count frozen      -> SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS
        5. nothing inflight, nothing dispatched, work
           pending/deferred                              -> SCHEDULER_NO_DISPATCH
        6. otherwise                                     -> USEFUL_PROGRESS

        Precedence note: INFLIGHT_NO_COMPLETION outranks
        SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS because "work is stuck in
        the network" is the operationally sharper label; a pass <t> jump
        while a batch is inflight still reports inflight-no-completion —
        exactly what the historical livelock needs to show.
        """
        o = obs if obs is not None else self.last
        if o is None:
            return USEFUL_PROGRESS
        if o.backend_alive is False:
            return BACKEND_NOT_RESPONDING
        # "no time advance" = this reply reported the same (or no) clock
        # as the previous round, via the probe's memory of the previous
        # observation — never by mutating the obs.
        prev = self.history_tail[-2] if len(self.history_tail) >= 2 else None
        clock_moved = (o.backend_cycle is not None
                       and prev is not None
                       and prev.backend_cycle is not None
                       and o.backend_cycle > prev.backend_cycle)
        completions = o.backend_completions
        if (completions == 0 and not clock_moved
                and o.inflight_batches == 0):
            return BACKEND_RESPONSIVE_NO_TIME_ADVANCE
        if (o.inflight_batches > 0 and completions == 0
                and not o.dispatched_this_round):
            return INFLIGHT_NO_COMPLETION
        retired_moved = (prev is None
                         or o.retired_requests > prev.retired_requests)
        if clock_moved and not retired_moved:
            return SIM_TIME_ADVANCING_NO_REQUEST_PROGRESS
        has_work_waiting = (o.pending_requests > 0 or o.deferred_requests > 0)
        if (o.inflight_batches == 0 and not o.dispatched_this_round
                and has_work_waiting):
            return SCHEDULER_NO_DISPATCH
        return USEFUL_PROGRESS

    # -- reporting -----------------------------------------------------------

    def no_useful_progress_report(self, state: Optional[str] = None) -> dict[str, Any]:
        """Machine-readable report (future `veritx diagnose` input)."""
        o = self.last
        if o is None:
            return {"error": "no observations recorded"}
        prev = self.history_tail[-2] if len(self.history_tail) >= 2 else None
        return {
            "type": "NO_USEFUL_PROGRESS",
            "state": state or self.classify(o),
            "rounds_unchanged": self.rounds_unchanged,
            "round": o.round,
            "sim_time": o.sim_time,
            "backend_cycle": o.backend_cycle,
            "prev_backend_cycle": prev.backend_cycle if prev else None,
            "retired_requests": o.retired_requests,
            "pending_requests": o.pending_requests,
            "deferred_requests": o.deferred_requests,
            "inflight_batches": o.inflight_batches,
            "backend_completions": o.backend_completions,
            "dispatched_this_round": o.dispatched_this_round,
            "last_command": o.last_command,
            "backend_alive": o.backend_alive,
            "note": o.note,
            "per_instance": dict(o.per_instance),
            "fingerprint": list(o.fingerprint()),
        }

    def render(self, state: Optional[str] = None) -> str:
        """Compact human block — the review-mandated shape."""
        r = self.no_useful_progress_report(state)
        if "error" in r:
            return f"NO_USEFUL_PROGRESS unavailable: {r['error']}"
        lines = [
            "NO_USEFUL_PROGRESS",
            f"state: {r['state']}",
            f"rounds_unchanged: {r['rounds_unchanged']}",
            f"round: {r['round']}",
            f"sim_time: {r['sim_time']}",
            f"backend_cycle: {r['backend_cycle']} (prev {r['prev_backend_cycle']})",
            f"retired_requests: {r['retired_requests']}",
            f"pending_requests: {r['pending_requests']}",
            f"deferred_requests: {r['deferred_requests']}",
            f"inflight_batches: {r['inflight_batches']}",
            f"backend_completions: {r['backend_completions']}",
            f"dispatched_this_round: {r['dispatched_this_round']}",
            f"last_command: {r['last_command']}",
            f"backend_alive: {r['backend_alive']}",
        ]
        if r["note"]:
            lines.append(f"note: {r['note']}")
        lines.append("per_instance:")
        for name, st in sorted(r["per_instance"].items()):
            lines.append(f"  {name}: {json.dumps(st, sort_keys=True)}")
        return "\n".join(lines)

    # answers the review's eight questions directly
    def answers(self) -> dict[str, Any]:
        o = self.last
        prev = self.history_tail[-2] if len(self.history_tail) >= 2 else None
        if o is None:
            return {}
        return {
            "backend_alive": o.backend_alive,
            "backend_replying": o.backend_completions > 0 or o.last_command != "",
            "sim_time_changing": (prev is not None
                                  and o.backend_cycle is not None
                                  and prev.backend_cycle is not None
                                  and o.backend_cycle != prev.backend_cycle),
            "requests_retiring": (prev is not None
                                  and o.retired_requests > prev.retired_requests),
            "schedulers_dispatching": o.dispatched_this_round
                                      or o.inflight_batches > 0,
            "batches_inflight": o.inflight_batches,
            "stuck_instance": _stuck_instance(o, prev),
            "repeating_same_action": (prev is not None
                                      and o.last_command == prev.last_command
                                      and o.fingerprint() == prev.fingerprint()),
        }


def _stuck_instance(o: ProgressObservation,
                    prev: Optional[ProgressObservation]) -> Optional[str]:
    """The instance holding unresolved work that never drains.

    Signature per the review: "one instance progresses, another never
    receives work" — i.e. queued requests (waiting) with nothing inflight,
    whose state is unchanged from the previous round.
    """
    if not o.per_instance:
        return None
    for name in sorted(o.per_instance):
        st = o.per_instance[name]
        has_queued_work = (st.get("waiting", 0) + st.get("dp_queued", 0)) > 0
        nothing_inflight = st.get("inflight", 0) == 0
        unchanged = (prev is None or prev.per_instance.get(name) == st)
        if has_queued_work and nothing_inflight and unchanged:
            return name
    return None


def attach_to_failure(probe: LivenessProbe, message: str) -> str:
    """Render the latest observation for an existing failure path.

    Called by the serving loop when EOF-with-work or the spin abort
    fires. Returns the text to print; also available via
    no_useful_progress_report() for machine consumption.
    """
    if probe.last is None:
        return message
    return (f"{message}\n"
            f"liveness snapshot at failure:\n{probe.render()}")
