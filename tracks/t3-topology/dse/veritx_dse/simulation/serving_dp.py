"""Slice 39 — dense data-parallel quorum semantics.

**DP synchronization is not a network operation.**  For dense DP there is no
cross-instance collective: a synchronized round still contains exactly the
per-instance TP collectives Slice 38 creates.  What DP adds is *when* a batch
may be dispatched:

    every group member resolves (real batch OR explicit dummy)
        -> pad every member to the group's max_total_len
        -> mark the whole quorum sent together
        -> each member runs its OWN TP group

This module owns DP *synchronization state* and nothing else.  It never owns
topology, routing, endpoint mapping or network configuration, and it never
adds ranks.  The padding semantics are the historical
``_pad_batch_to_max`` from the hardened LLMServingSim loop: only the
high-level dense-forward counters move, so attention keeps seeing the real
sequences while the dense/CUDA-graph shape reflects the padded one.

Two rules are load-bearing and are enforced here rather than trusted:

``sum_total_len = max_total_len``
    NOT ``max_total_len * group_size``.  It is bound into the quorum record
    even though this slice does not consume it: it is the seam a later EP
    slice reads.

``a pending real batch stays unsent``
    until the entire quorum is ready, which is what keeps the historical
    anti-pass-echo invariant intact.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from veritx_dse.backend.serving_round import DpMemberRecord, DpQuorumRecord

#: the historical minimal dummy shape (one decode token, no user requests)
DP_DUMMY_TOTAL_LEN = 1


class ServingDpError(ValueError):
    """DP synchronization state is inconsistent, or a rule was violated."""


# ── the historical padding semantics ──────────────────────────────────────

def pad_batch_to_max(batch: Any, max_len: int) -> int:
    """Pad one DP member's batch up to ``max_len`` (returns the pad amount).

    Mirrors vLLM's CUDA-graph DP padding, exactly as the hardened
    LLMServingSim ``_pad_batch_to_max`` does:

        batch.total_len = max_len
        batch.kv_len    += pad
        batch.num_decode += pad

    and deliberately NOT ``decode_k_list`` / the prefill token lists / the
    request list: padding changes the dense forward shape without inventing
    real attention sequences.  Completion accounting reads ``batch.requests``
    and ``batch.end``, so it is unaffected by these mutations.
    """
    pad = int(max_len) - int(batch.total_len)
    if pad <= 0:
        return 0
    batch.total_len = int(max_len)
    batch.kv_len += pad
    batch.num_decode += pad
    return pad


def make_dp_dummy(*, scheduler: Any, clock: int, start_npu: int) -> Any:
    """A real vendored ``Batch`` that closes a DP quorum for an idle member.

    Not ``None``: the dummy must live in the real ``Scheduler`` lifecycle so
    ``Scheduler.add_done()`` can clear it.  It is appended to the scheduler's
    inflight list exactly as ``Scheduler.schedule()`` would, is unsent until
    the quorum dispatches, carries no user requests, and therefore retires
    nothing.
    """
    try:
        from serving.core.request import Batch
    except Exception as exc:  # pragma: no cover - environment dependent
        raise ServingDpError(
            "the vendored LLMServingSim package is required on sys.path: "
            f"{exc}") from exc
    dummy = Batch(scheduler.get_batch_id(), scheduler.model,
                  DP_DUMMY_TOTAL_LEN, 1, [1], [], 0, 1, [], [], [1],
                  clock, 0)
    dummy.fired.append(start_npu)
    scheduler.inflight.append(dummy)
    return dummy


# ── coordinator state ─────────────────────────────────────────────────────

@dataclass(frozen=True)
class CompletedQuorum:
    """A resolved DP quorum plus the batches to dispatch for it."""

    record: DpQuorumRecord
    batches: tuple[tuple[int, Any], ...]

    def batch_map(self) -> dict[int, Any]:
        return dict(self.batches)

    def dummy_instances(self) -> frozenset[int]:
        return frozenset(m.instance_id for m in self.record.members
                         if m.is_dummy)


@dataclass
class _Pending:
    instance_id: int
    batch: Any
    is_dummy: bool
    original_total_len: int


class DpQuorumCoordinator:
    """DP synchronization state for one service run.

    States a member's batch moves through::

        scheduled but UNSENT real batch   (batch.sent is False)
        DP dummy                          (explicit, unsent)
        quorum-ready                      (every member resolved)
        dispatched                        (padded and marked sent)
    """

    def __init__(self, *, groups: Any) -> None:
        self._groups = groups
        self._pending: dict[str, dict[int, _Pending]] = {
            group_id: {} for group_id in groups.group_ids()}

    # -- queries ----------------------------------------------------------
    @property
    def groups(self) -> Any:
        return self._groups

    def group_of(self, instance_id: int) -> Any:
        return self._groups.group_of(instance_id)

    def is_member(self, instance_id: int) -> bool:
        return self._groups.is_member(instance_id)

    def has_pending(self) -> bool:
        """True while any real unsent batch is held: the run is NOT quiescent."""
        return any(table for table in self._pending.values())

    def pending_instances(self, group_id: str) -> tuple[int, ...]:
        return tuple(sorted(self._pending[group_id]))

    def open_groups(self) -> tuple[str, ...]:
        """Groups holding at least one REAL batch (a dummy never opens one)."""
        return tuple(group_id for group_id in self._groups.group_ids()
                     if any(not p.is_dummy
                            for p in self._pending[group_id].values()))

    def ready_groups(self) -> tuple[str, ...]:
        """Groups where every member has resolved and one is real."""
        ready: list[str] = []
        for group_id in self._groups.group_ids():
            table = self._pending[group_id]
            if not table:
                continue
            members = self._groups.group(group_id).instance_ids
            if len(table) != len(members):
                continue
            if not any(not p.is_dummy for p in table.values()):
                continue
            ready.append(group_id)
        return tuple(ready)

    # -- mutation ---------------------------------------------------------
    def note_real_batch(self, instance_id: int, batch: Any) -> None:
        """Hold a real DP batch unsent until its quorum resolves."""
        group = self.group_of(instance_id)
        if group is None:
            raise ServingDpError(
                f"serving instance {instance_id} is not a DP group member")
        table = self._pending[group.group_id]
        if instance_id in table:
            held = table[instance_id]
            raise ServingDpError(
                f"serving instance {instance_id} already holds a pending "
                f"{'dummy' if held.is_dummy else 'real'} batch "
                f"{held.batch.batch_id}; refusing to overwrite it")
        if getattr(batch, "sent", False):
            raise ServingDpError(
                f"a DP batch for instance {instance_id} entered the quorum "
                "already marked sent; it must be held unsent until dispatch")
        table[instance_id] = _Pending(
            instance_id=instance_id, batch=batch, is_dummy=False,
            original_total_len=int(batch.total_len))

    def add_dummy(self, *, group_id: str, instance_id: int, dummy: Any) -> None:
        if group_id not in self._pending:
            raise ServingDpError(f"unknown DP group {group_id!r}")
        if instance_id not in self._groups.group(group_id).instance_ids:
            raise ServingDpError(
                f"serving instance {instance_id} is not a member of DP group "
                f"{group_id!r}")
        table = self._pending[group_id]
        if instance_id in table:
            raise ServingDpError(
                f"serving instance {instance_id} already holds a pending "
                f"batch; refusing to add a dummy over it")
        if getattr(dummy, "requests", ()):
            raise ServingDpError(
                "a DP dummy must carry no user requests; a real empty batch "
                "must not masquerade as DP participation")
        if getattr(dummy, "sent", False):
            raise ServingDpError(
                "a DP dummy entered the quorum already marked sent")
        table[instance_id] = _Pending(
            instance_id=instance_id, batch=dummy, is_dummy=True,
            original_total_len=DP_DUMMY_TOTAL_LEN)

    def complete_ready(self) -> tuple[CompletedQuorum, ...]:
        """Pad every ready quorum and mark the whole group sent together."""
        completed: list[CompletedQuorum] = []
        for group_id in self.ready_groups():
            table = self._pending[group_id]
            members = self._groups.group(group_id).instance_ids
            max_total_len = max(int(p.batch.total_len)
                                for p in table.values())
            for instance_id in members:
                pending = table[instance_id]
                pad_batch_to_max(pending.batch, max_total_len)
                if getattr(pending.batch, "sent", False):
                    raise ServingDpError(
                        f"DP member {instance_id} was already sent before its "
                        "quorum dispatched")
                pending.batch.sent = True
            record = DpQuorumRecord(
                group_id=group_id,
                members=tuple(DpMemberRecord(
                    instance_id=instance_id,
                    batch_id=int(table[instance_id].batch.batch_id),
                    is_dummy=table[instance_id].is_dummy,
                    original_total_len=table[instance_id].original_total_len,
                    padded_total_len=int(table[instance_id].batch.total_len))
                    for instance_id in members),
                max_total_len=max_total_len,
                # the historical rule, bound explicitly
                dp_sum_total_len=max_total_len)
            completed.append(CompletedQuorum(
                record=record,
                batches=tuple((instance_id, table[instance_id].batch)
                              for instance_id in members)))
            self._pending[group_id] = {}
        return tuple(completed)
