"""A stored capability refusal must not outlive the capability state.

A revision stores the assessment its compile produced. When a withdrawn
capability is requalified, replaying that stored refusal blocked work the
current state allows while the evaluation plan (derived live) reported READY.
These tests pin the resolution rule for both directions.
"""
from veritx_dse.product.service import supersede_recorded_refusal


def test_a_refusal_the_live_state_allows_is_superseded_not_replayed():
    resolved = supersede_recorded_refusal(
        {"support": "UNSUPPORTED",
         "reason": "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1 is a WITHDRAWN capability"},
        {"support": "SUPPORTED", "readiness": "READY", "reason": None})
    assert resolved["support"] == "SUPPORTED"
    assert resolved["readiness"] == "READY"
    superseded = resolved["superseded_refusal"]
    assert superseded["recorded_support"] == "UNSUPPORTED"
    assert "WITHDRAWN" in superseded["recorded_reason"]
    assert superseded["re_derived_at"]
    assert "superseded, not withdrawn" in superseded["meaning"]


def test_a_refusal_the_live_state_reproduces_is_kept_without_a_history_note():
    """Re-deriving must never launder a refusal that still applies."""
    resolved = supersede_recorded_refusal(
        {"support": "UNSUPPORTED", "reason": "old wording"},
        {"support": "UNSUPPORTED",
         "reason": "UNSUPPORTED: certified mesh-DOR covers seat_capacity 1 only"})
    assert resolved["support"] == "UNSUPPORTED"
    assert "seat_capacity" in resolved["reason"]
    assert "superseded_refusal" not in resolved


def test_a_previously_supported_verdict_is_not_downgraded_by_a_stale_store():
    """The stored positive verdict stays authoritative; only refusals re-derive."""
    stored = {"support": "SUPPORTED", "readiness": "READY", "qualification": {}}
    assert supersede_recorded_refusal(stored, {"support": "SUPPORTED"}) is not None
