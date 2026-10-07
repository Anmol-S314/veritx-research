"""Canonical agent transaction intent (contract §4).

Architectural intent only: every valid combination describes an issue policy
this spec admits; every invalid combination refuses with a typed error.

Two properties are load-bearing and are tested directly:

* ``max_outstanding`` is an AGENT TRANSACTION CREDIT. This suite proves it
  actually gates issue, and proves the module emits no network/BookSim knob.
* ``split_transactions`` MATERIALIZES children (parent identity, 0-based
  sequence, exclusive end, ordering domain, traffic class) rather than merely
  recording that splitting is enabled.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DSE))

from veritx_dse.model.transaction_intent import (  # noqa: E402
    ChildTransaction,
    OrderingMode,
    OrderingPolicy,
    OutstandingLimit,
    OutstandingTracker,
    ReorderingPolicy,
    SplittingPolicy,
    TransactionIntentError,
    TransactionKind,
    TransactionPolicy,
    split_transactions,
)


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------

def _full_policy(**over):
    base = {
        "outstanding": {"reads": 4, "writes": 4, "total": 8},
        "ordering": {"mode": "STRONG", "enforce_raw": True,
                     "enforce_war": True, "enforce_waw": True,
                     "ordering_domain": "io"},
        "splitting": {"max_payload_bytes": 512, "boundary_bytes": 128},
        "reordering": {"enabled": True, "max_window": 3},
    }
    base.update(over)
    return base


def _split(**over):
    base = {"max_payload_bytes": 512, "boundary_bytes": 128}
    base.update(over)
    return SplittingPolicy(**base)


# ==========================================================================
# roundtrip
# ==========================================================================

def test_transaction_policy_roundtrips_fully_populated():
    policy = TransactionPolicy.from_dict(_full_policy())
    assert TransactionPolicy.from_dict(policy.to_dict()) == policy
    assert policy.is_neutral is False


def test_outstanding_limit_roundtrip():
    limit = OutstandingLimit(reads=2, writes=3, total=6)
    assert OutstandingLimit.from_dict(limit.to_dict()) == limit


def test_ordering_policy_roundtrip():
    ordering = OrderingPolicy(mode=OrderingMode.CUSTOM, enforce_raw=True,
                              enforce_waw=True, ordering_domain="mem")
    assert OrderingPolicy.from_dict(ordering.to_dict()) == ordering


def test_splitting_and_reordering_roundtrip():
    splitting = _split()
    assert SplittingPolicy.from_dict(splitting.to_dict()) == splitting
    reordering = ReorderingPolicy(enabled=False, max_window=0)
    assert ReorderingPolicy.from_dict(reordering.to_dict()) == reordering


def test_child_transaction_roundtrip():
    child = ChildTransaction(sequence=2, address_start=1024,
                             address_end=1152, byte_length=128,
                             parent_id="T0", ordering_domain="io",
                             traffic_class="blocking", is_last=False)
    assert ChildTransaction.from_dict(child.to_dict()) == child


# ==========================================================================
# unknown keys refuse — every from_dict
# ==========================================================================

@pytest.mark.parametrize("factory,bad", [
    (OutstandingLimit.from_dict, {"reads": 2, "buffer_depth": 4}),
    (OrderingPolicy.from_dict, {"mode": "STRONG", "vc": 3}),
    (SplittingPolicy.from_dict, {"max_payload_bytes": 512,
                                 "boundary_bytes": 128, "k": 4}),
    (ReorderingPolicy.from_dict, {"enabled": True, "flits": 8}),
    (TransactionPolicy.from_dict, {"outstanding": None, "topology": "mesh"}),
    (ChildTransaction.from_dict, {"sequence": 0, "address_start": 0,
                                  "address_end": 1, "byte_length": 1,
                                  "parent_id": "T", "ordering_domain": None,
                                  "traffic_class": "t", "is_last": True,
                                  "srota": 1}),
])
def test_unknown_keys_refuse(factory, bad):
    with pytest.raises(TransactionIntentError, match="unknown fields"):
        factory(bad)


@pytest.mark.parametrize("factory", [OutstandingLimit.from_dict,
                                     OrderingPolicy.from_dict,
                                     SplittingPolicy.from_dict,
                                     ReorderingPolicy.from_dict,
                                     TransactionPolicy.from_dict,
                                     ChildTransaction.from_dict])
def test_non_object_refuses(factory):
    with pytest.raises(TransactionIntentError, match="must be an object"):
        factory(["not", "an", "object"])


def test_missing_required_field_refuses():
    with pytest.raises(TransactionIntentError, match="missing required field"):
        OrderingPolicy.from_dict({"enforce_raw": True})


# ==========================================================================
# neutral / default equivalence — a v4 design migrates unchanged
# ==========================================================================

def test_empty_transaction_policy_is_the_v4_equivalent():
    neutral = TransactionPolicy.from_dict({})
    assert neutral == TransactionPolicy()
    assert neutral.is_neutral is True
    # every component stays None; nothing coerces to 0, False or ""
    assert neutral.to_dict() == {"outstanding": None, "ordering": None,
                                 "splitting": None, "reordering": None}


def test_none_is_never_coerced_to_zero():
    limit = OutstandingLimit(reads=2)
    d = limit.to_dict()
    assert d["writes"] is None and d["total"] is None
    assert "writes" in d, "None must be carried, not dropped"
    assert OutstandingLimit.from_dict(d) == limit


def test_absent_limit_is_none_not_zero():
    policy = TransactionPolicy()
    assert policy.outstanding is None
    assert policy.to_dict()["outstanding"] is None


# ==========================================================================
# OutstandingLimit laws
# ==========================================================================

def test_all_absent_limit_is_vacuous_and_refuses():
    with pytest.raises(TransactionIntentError, match="vacuous"):
        OutstandingLimit()


@pytest.mark.parametrize("kw", [{"reads": 0}, {"writes": -1},
                                {"total": -5}, {"reads": 1, "writes": 0}])
def test_non_positive_bound_refuses(kw):
    with pytest.raises(TransactionIntentError, match=">= 1"):
        OutstandingLimit(**kw)


def test_total_below_per_kind_bound_refuses():
    with pytest.raises(TransactionIntentError, match="total"):
        OutstandingLimit(reads=4, total=2)


def test_total_equal_to_per_kind_bound_is_legal():
    assert OutstandingLimit(reads=4, total=4, writes=4) is not None


# ==========================================================================
# OrderingPolicy laws
# ==========================================================================

def test_strong_with_disabled_hazard_refuses():
    with pytest.raises(TransactionIntentError, match="STRONG"):
        OrderingPolicy(mode=OrderingMode.STRONG, enforce_raw=True,
                       enforce_war=False, enforce_waw=True)


def test_strong_requires_all_three_hazards():
    # none enabled at all is the same refusal, not a different one
    with pytest.raises(TransactionIntentError, match="STRONG"):
        OrderingPolicy(mode=OrderingMode.STRONG)


def test_strong_with_all_hazards_is_legal():
    policy = OrderingPolicy(mode=OrderingMode.STRONG, enforce_raw=True,
                            enforce_war=True, enforce_waw=True)
    assert policy.enforced_hazards == ("RAW", "WAR", "WAW")


def test_custom_with_no_hazard_is_vacuous_and_refuses():
    with pytest.raises(TransactionIntentError, match="CUSTOM"):
        OrderingPolicy(mode=OrderingMode.CUSTOM)


def test_custom_with_one_hazard_is_legal():
    policy = OrderingPolicy(mode=OrderingMode.CUSTOM, enforce_raw=True)
    assert policy.enforced_hazards == ("RAW",)


def test_relaxed_with_no_hazard_is_legal_and_progresses_independently():
    policy = OrderingPolicy(mode=OrderingMode.RELAXED)
    assert policy.enforced_hazards == ()


def test_ordering_mode_names_are_exactly_the_contract_vocabulary():
    assert {m.value for m in OrderingMode} == {"STRONG", "RELAXED", "CUSTOM"}


def test_unknown_ordering_mode_refuses_with_known_list():
    with pytest.raises(TransactionIntentError, match="known"):
        OrderingPolicy.from_dict({"mode": "AXI"})


def test_non_bool_hazard_refuses():
    with pytest.raises(TransactionIntentError, match="bool"):
        OrderingPolicy(mode=OrderingMode.RELAXED, enforce_raw="yes")


def test_empty_ordering_domain_refuses():
    with pytest.raises(TransactionIntentError, match="non-empty"):
        OrderingPolicy(mode=OrderingMode.RELAXED, ordering_domain="")


def test_ordering_domain_may_be_absent():
    assert OrderingPolicy(mode=OrderingMode.RELAXED).ordering_domain is None


# ==========================================================================
# SplittingPolicy laws
# ==========================================================================

def test_non_power_of_two_boundary_refuses():
    with pytest.raises(TransactionIntentError, match="power of two"):
        SplittingPolicy(max_payload_bytes=1000, boundary_bytes=100)


def test_power_of_two_that_does_not_divide_refuses():
    with pytest.raises(TransactionIntentError, match="evenly divide"):
        SplittingPolicy(max_payload_bytes=192, boundary_bytes=128)


def test_boundary_above_payload_refuses():
    with pytest.raises(TransactionIntentError):
        SplittingPolicy(max_payload_bytes=64, boundary_bytes=128)


@pytest.mark.parametrize("boundary", [64, 128, 256, 512])
def test_legal_boundaries_under_512_are_accepted(boundary):
    assert SplittingPolicy(max_payload_bytes=512,
                           boundary_bytes=boundary).boundary_bytes == boundary


def test_splitting_child_count_is_derived():
    assert _split().child_count_per_max_payload == 4


# ==========================================================================
# split_transactions materializes children
# ==========================================================================

def test_split_512_at_128_yields_exactly_four_children():
    kids = split_transactions(parent_id="T0", address_base=0, payload_bytes=512,
                              splitting=_split(), ordering_domain="io",
                              traffic_class="blocking")
    assert len(kids) == 4
    assert [(c.address_start, c.address_end) for c in kids] == [
        (0, 128), (128, 256), (256, 384), (384, 512)]
    assert [c.sequence for c in kids] == [0, 1, 2, 3]
    assert [c.byte_length for c in kids] == [128, 128, 128, 128]


def test_children_carry_parent_identity_domain_and_traffic_class():
    kids = split_transactions(parent_id="T7", address_base=4096,
                              payload_bytes=512, splitting=_split(),
                              ordering_domain="io", traffic_class="blocking")
    for child in kids:
        assert child.parent_id == "T7"
        assert child.ordering_domain == "io"
        assert child.traffic_class == "blocking"


def test_only_the_last_child_is_marked_last():
    kids = split_transactions(parent_id="T0", address_base=0, payload_bytes=512,
                              splitting=_split(), ordering_domain="io",
                              traffic_class="blocking")
    assert [c.is_last for c in kids] == [False, False, False, True]


@pytest.mark.parametrize("base,payload,boundary", [
    (0, 512, 128), (0x1000, 512, 64), (0x8000_0000, 4096, 256),
    (1, 64, 64), (0, 1, 1),
])
def test_split_invariants_hold(base, payload, boundary):
    splitting = SplittingPolicy(max_payload_bytes=payload,
                                boundary_bytes=boundary)
    kids = split_transactions(parent_id="T", address_base=base,
                              payload_bytes=payload, splitting=splitting,
                              ordering_domain=None, traffic_class="t")
    # conservation
    assert sum(c.byte_length for c in kids) == payload
    # contiguity
    for left, right in zip(kids, kids[1:]):
        assert left.address_end == right.address_start
    # endpoints
    assert kids[0].address_start == base
    assert kids[-1].address_end == base + payload
    # 0-based contiguous sequence, exactly one last child
    assert [c.sequence for c in kids] == list(range(len(kids)))
    assert sum(1 for c in kids if c.is_last) == 1
    # each child is exactly one boundary long
    assert all(c.byte_length == boundary for c in kids)


def test_split_payload_larger_than_policy_max_refuses():
    with pytest.raises(TransactionIntentError, match="exceeds"):
        split_transactions(parent_id="T", address_base=0, payload_bytes=1024,
                           splitting=_split(), ordering_domain=None,
                           traffic_class="t")


def test_split_payload_not_a_multiple_of_boundary_refuses():
    with pytest.raises(TransactionIntentError, match="multiple"):
        split_transactions(parent_id="T", address_base=0, payload_bytes=300,
                           splitting=_split(), ordering_domain=None,
                           traffic_class="t")


def test_split_requires_real_splitting_policy_type():
    with pytest.raises(TransactionIntentError, match="SplittingPolicy"):
        split_transactions(parent_id="T", address_base=0, payload_bytes=128,
                           splitting={"boundary_bytes": 128},
                           ordering_domain=None, traffic_class="t")


def test_child_byte_length_must_match_address_span():
    with pytest.raises(TransactionIntentError, match="byte_length"):
        ChildTransaction(sequence=0, address_start=0, address_end=128,
                         byte_length=64, parent_id="T", ordering_domain=None,
                         traffic_class="t", is_last=True)


def test_child_end_must_exceed_start():
    with pytest.raises(TransactionIntentError, match="strictly greater"):
        ChildTransaction(sequence=0, address_start=128, address_end=128,
                         byte_length=128, parent_id="T", ordering_domain=None,
                         traffic_class="t", is_last=True)


# ==========================================================================
# ReorderingPolicy laws
# ==========================================================================

def test_enabled_reordering_with_zero_window_refuses():
    with pytest.raises(TransactionIntentError, match="window of 0"):
        ReorderingPolicy(enabled=True, max_window=0)


def test_disabled_reordering_with_nonzero_window_refuses():
    with pytest.raises(TransactionIntentError, match="disagree"):
        ReorderingPolicy(enabled=False, max_window=4)


def test_disabled_reordering_with_zero_window_is_legal():
    assert ReorderingPolicy(enabled=False).max_window == 0


def test_negative_window_refuses():
    with pytest.raises(TransactionIntentError, match=">= 0"):
        ReorderingPolicy(enabled=True, max_window=-1)


# ==========================================================================
# TransactionPolicy composition laws
# ==========================================================================

@pytest.mark.parametrize("field,bad", [
    ("outstanding", 5), ("ordering", "STRONG"),
    ("splitting", {"max_payload_bytes": 512, "boundary_bytes": 128}),
    ("reordering", True),
])
def test_transaction_policy_component_must_be_the_declared_type(field, bad):
    with pytest.raises(TransactionIntentError, match="must be a"):
        TransactionPolicy(**{field: bad})


def test_components_may_be_mixed_with_neutral():
    policy = TransactionPolicy(outstanding=OutstandingLimit(reads=2))
    assert policy.outstanding.reads == 2
    assert policy.ordering is None and policy.splitting is None
    assert policy.reordering is None
    assert policy.is_neutral is False


# ==========================================================================
# OutstandingTracker — proves max_outstanding is real
# ==========================================================================

def test_limit_two_blocks_third_until_completion():
    """The contract's exact scenario: T0, T1 issue; T2 blocked; T0 completes;
    T2 may issue."""
    tracker = OutstandingTracker(OutstandingLimit(total=2))

    assert tracker.try_issue(TransactionKind.READ) is True      # T0 issue
    assert tracker.try_issue(TransactionKind.READ) is True      # T1 issue
    assert tracker.live_total == 2
    tracker.assert_invariants()

    assert tracker.try_issue(TransactionKind.READ) is False     # T2 blocked
    assert tracker.live_total == 2
    tracker.assert_invariants()

    tracker.complete(TransactionKind.READ)                      # T0 completes
    assert tracker.live_total == 1
    tracker.assert_invariants()

    assert tracker.try_issue(TransactionKind.READ) is True      # T2 may issue
    assert tracker.live_total == 2
    tracker.assert_invariants()
    assert tracker.blocked_attempts == 1


def test_blocked_issue_changes_no_count():
    tracker = OutstandingTracker(OutstandingLimit(total=1))
    assert tracker.try_issue(TransactionKind.WRITE)
    reads, writes, total = (tracker.live_reads, tracker.live_writes,
                            tracker.live_total)
    assert tracker.try_issue(TransactionKind.READ) is False
    assert (tracker.live_reads, tracker.live_writes, tracker.live_total) == \
        (reads, writes, total)
    assert tracker.blocked_attempts == 1


def test_per_kind_limits_bound_independently_of_total():
    tracker = OutstandingTracker(OutstandingLimit(reads=2, writes=1, total=4))
    assert tracker.try_issue(TransactionKind.READ) is True
    assert tracker.try_issue(TransactionKind.READ) is True
    assert tracker.try_issue(TransactionKind.READ) is False      # reads == 2
    assert tracker.try_issue(TransactionKind.WRITE) is True
    assert tracker.try_issue(TransactionKind.WRITE) is False     # writes == 1
    # total (4) was never the binding constraint
    assert tracker.live_total == 3
    tracker.assert_invariants()


def test_live_count_never_exceeds_the_declared_limit():
    limit = OutstandingLimit(reads=1, writes=1, total=2)
    tracker = OutstandingTracker(limit)
    for _ in range(100):
        tracker.try_issue(TransactionKind.READ)
        tracker.assert_invariants()
        tracker.try_issue(TransactionKind.WRITE)
        tracker.assert_invariants()
        if tracker.live_total:
            kind = (TransactionKind.READ if tracker.live_reads
                    else TransactionKind.WRITE)
            tracker.complete(kind)
            tracker.assert_invariants()
    while tracker.live_reads:
        tracker.complete(TransactionKind.READ)
    while tracker.live_writes:
        tracker.complete(TransactionKind.WRITE)
    assert tracker.live_total == 0
    tracker.assert_invariants()


def test_completion_frees_exactly_one_credit():
    tracker = OutstandingTracker(OutstandingLimit(total=2))
    tracker.try_issue(TransactionKind.READ)
    tracker.try_issue(TransactionKind.READ)
    assert tracker.try_issue(TransactionKind.READ) is False
    tracker.complete(TransactionKind.READ)
    assert tracker.try_issue(TransactionKind.READ) is True


def test_completing_a_transaction_that_never_issued_refuses():
    tracker = OutstandingTracker(OutstandingLimit(total=2))
    with pytest.raises(TransactionIntentError, match="no live read"):
        tracker.complete(TransactionKind.READ)
    tracker.try_issue(TransactionKind.WRITE)
    with pytest.raises(TransactionIntentError, match="no live read"):
        tracker.complete(TransactionKind.READ)


def test_unbounded_kind_is_not_clamped_to_zero():
    """reads unconstrained (None) must not become a limit of 0."""
    tracker = OutstandingTracker(OutstandingLimit(writes=1))
    for _ in range(10):
        assert tracker.try_issue(TransactionKind.READ) is True
    assert tracker.live_reads == 10
    assert tracker.try_issue(TransactionKind.WRITE) is True
    assert tracker.try_issue(TransactionKind.WRITE) is False
    tracker.assert_invariants()


def test_tracker_requires_an_outstanding_limit_object():
    with pytest.raises(TransactionIntentError, match="must be an OutstandingLimit"):
        OutstandingTracker(limit=2)


def test_tracker_rejects_a_non_transaction_kind():
    tracker = OutstandingTracker(OutstandingLimit(total=2))
    with pytest.raises(TransactionIntentError, match="TransactionKind"):
        tracker.try_issue("read")


# ==========================================================================
# vocabulary + no-network-knob guard
# ==========================================================================

def test_ordering_is_canonical_not_protocol_specific():
    """Semantics must stay protocol-neutral until an adapter proves a mapping."""
    from veritx_dse.model import transaction_intent as mod
    source = Path(mod.__file__).read_text()
    assert "AXI ordering" not in source.replace('not "AXI ordering"', "")


def test_module_declares_the_transaction_credit_distinction():
    from veritx_dse.model import transaction_intent as mod
    source = Path(mod.__file__).read_text()
    assert "AGENT TRANSACTION CREDIT" in source
    assert "NOT a BookSim router buffer credit" in source


def test_emitted_schema_keys_are_only_transaction_concepts():
    """Guard: this layer must never grow a network/BookSim knob."""
    allowed = {
        "outstanding", "ordering", "splitting", "reordering",
        "reads", "writes", "total", "mode", "enforce_raw", "enforce_war",
        "enforce_waw", "ordering_domain", "max_payload_bytes",
        "boundary_bytes", "enabled", "max_window", "sequence",
        "address_start", "address_end", "byte_length", "parent_id",
        "traffic_class", "is_last",
    }
    emitted = set()
    for value in (TransactionPolicy.from_dict(_full_policy()),
                  OutstandingLimit(reads=1, writes=2, total=3),
                  SplittingPolicy(max_payload_bytes=512, boundary_bytes=64),
                  ReorderingPolicy(enabled=True, max_window=2),
                  OrderingPolicy(mode=OrderingMode.RELAXED),
                  ChildTransaction(sequence=0, address_start=0, address_end=8,
                                   byte_length=8, parent_id="T",
                                   ordering_domain=None, traffic_class="t",
                                   is_last=True)):
        emitted |= set(value.to_dict())
    assert emitted == allowed, emitted ^ allowed


def test_module_does_not_reference_booksim_config_fields():
    """The module may *discuss* BookSim to keep the distinction explicit; it
    must not import a simulator or carry a network config identifier."""
    import re
    from veritx_dse.model import transaction_intent as mod
    source = Path(mod.__file__).read_text()
    assert not re.search(r"^\s*(from|import)\s+\S*booksim", source,
                         re.IGNORECASE | re.MULTILINE)
    for banned in ("buffer_depth", "num_vcs", "flit_depth", "inject",
                   "topology_family", "link_width", "arbitration"):
        assert banned not in source, banned
