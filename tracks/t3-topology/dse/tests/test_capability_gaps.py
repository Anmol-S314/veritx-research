"""Missing-capability gaps are tagged at the site, never inferred from prose.

Two invariants:
  - a tagged gap is discoverable from source, so it reaches the product
    without anyone registering it;
  - a gap-shaped refusal without a tag is visible as backlog, so it cannot
    hide.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.capability_gaps import (  # noqa: E402
    GAP_PHRASES, MissingCapability, classify, declared_gaps,
    require_capability, untagged_gap_sites,
)
from veritx_dse.core.errors import MissingCapability as CoreMissingCapability


def test_application_reexports_core_capability_refusal():
    assert MissingCapability is CoreMissingCapability
    try:
        require_capability("example_capability", "missing", stage="SEMANTIC_STAGE")
    except MissingCapability as error:
        assert error.capability == "example_capability"
        assert error.kind == "NO_ARTIFACT"
        assert error.stage == "SEMANTIC_STAGE"
    else:
        raise AssertionError("require_capability must refuse")


def test_tagged_gaps_are_discoverable_from_source():
    gaps = declared_gaps()
    assert gaps, "at least one gap site must be tagged"
    ids = {g["capability"] for g in gaps}
    # The four capabilities the sweep showed as NO_ARTIFACT gaps.
    assert {"rcu_hardware", "multicast_group_hardware",
            "multicast_setup_state", "power_isolation"} <= ids
    for gap in gaps:
        assert gap["source"].endswith(".py")
        assert gap["line"] > 0


def test_every_gap_id_is_unique_per_site():
    seen = [(g["source"], g["line"]) for g in declared_gaps()]
    assert len(seen) == len(set(seen))


def test_classify_separates_gaps_from_impossibilities():
    # A real sweep refusal of each kind.
    assert classify("design requests RCU (rcu_enabled=True) but no "
                    "canonical RCU hardware artifact exists") == "NO_ARTIFACT"
    assert classify("header (9 bits) consumes the whole link") == "IMPOSSIBLE"
    assert classify("required 14 VCs exceeds fabric maximum 8") == "IMPOSSIBLE"
    assert classify("address ranges 'a' and 'b' overlap") == "IMPOSSIBLE"
    assert classify(None) == "UNKNOWN"


def test_returned_classification_is_not_a_refusal_site():
    """`performance.fidelity_warning` RETURNS a value that names missing
    measurement data, not a refusal. The over-broad "no hardware" phrase
    indexed it as a gap; that phrase is gone. The scanner still reads every
    statement (including `return`), so a genuine returned refusal is not
    hidden — only this data-note phrasing stops matching."""
    assert "no hardware" not in GAP_PHRASES
    assert not any(entry["source"] == "performance/model.py"
                   for entry in untagged_gap_sites())


def test_scanner_does_not_index_itself():
    for entry in untagged_gap_sites() + [
            {"source": g["source"]} for g in declared_gaps()]:
        assert "capability_gaps.py" not in entry["source"]


def test_tagged_sites_never_appear_as_untagged_backlog():
    tagged_sources = {g["source"] for g in declared_gaps()}
    for entry in untagged_gap_sites():
        if entry["source"] in tagged_sources:
            # Same file is fine; the same refusal line is not.
            assert entry["text"], entry
    # The four tagged lines are absent from the backlog.
    tagged_lines = {(g["source"], g["line"]) for g in declared_gaps()}
    for entry in untagged_gap_sites():
        assert (entry["source"], entry["line"]) not in tagged_lines


def test_untagged_backlog_is_bounded_and_reported():
    """The backlog is reported, not silently dropped. A new untagged gap must
    be a deliberate decision, so the count cannot grow unnoticed."""
    backlog = untagged_gap_sites()
    for entry in backlog:
        assert entry["text"], "backlog entries must carry their text"
    # Current measured backlog. A change here is a reviewed decision: either
    # a new gap site appeared, or one got tagged. Both are worth a look.
    # 19: the "no hardware" phrase used to add the returned performance
    # fidelity note (a value, not a refusal); it is no longer indexed.
    assert len(backlog) == 19
