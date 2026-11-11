"""The backend knob catalog must be DERIVED, never a hand-written list.

The fork's own registration answers "what does the binary accept"; the
profile audit answers "who owns it and may it be replaced". If a knob exists
in the source and not here, the UI hides a capability. If a classification
exists here and not in the audit, the UI offers something execution refuses.
Both are drift, and these gates close them by reading the same authorities.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.backend_knob_catalog import (  # noqa: E402
    _FLOAT_RE, _INT_RE, _STR_RE,
    backend_knob_catalog, backend_knob_catalog_document,
)
from veritx_dse.application.knob_inventory import knob_inventory  # noqa: E402
from veritx_dse.core.paths import BOOKSIM_DIR  # noqa: E402

SOURCE = BOOKSIM_DIR / "booksim_config.cpp"


def _registered_names() -> set[str]:
    text = SOURCE.read_text(encoding="utf-8", errors="replace")
    return ({n for n, _ in _STR_RE.findall(text)}
            | {n for n, _ in _INT_RE.findall(text)}
            | {n for n, _ in _FLOAT_RE.findall(text)})


def test_every_registered_knob_is_reported():
    reported = {r["name"] for r in backend_knob_catalog()}
    assert reported >= _registered_names()


def test_every_audited_field_is_reported():
    from veritx_dse.backend.booksim_profile import (
        BOOKSIM_CERTIFIED_CONFIG_AUDIT,
    )
    reported = {r["name"] for r in backend_knob_catalog()}
    assert reported >= {row.name for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT}


def test_overridable_is_exactly_the_backend_profile_set():
    from veritx_dse.backend.booksim_profile import (
        BOOKSIM_CERTIFIED_CONFIG_AUDIT,
    )
    # Compare on the value, not enum identity: the audit's ParameterOwner
    # lives in backend/contracts.py, and backend/booksim_projection.py
    # defines a second enum with the same values.
    expected = {row.name for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT
                if row.owner.value == "BACKEND_PROFILE"}
    reported = {r["name"] for r in backend_knob_catalog() if r["overridable"]}
    assert reported == expected


def test_control_column_reverse_maps_the_authored_controls():
    from veritx_dse.backend.router_controls import NATIVE_FIELDS
    expected = {key: field for field, (key, _src) in NATIVE_FIELDS.items()}
    reported = {r["name"]: r["control"] for r in backend_knob_catalog()
                if r["control"]}
    assert reported == expected


def test_unaudited_knobs_are_marked_not_offered_as_editable():
    for row in backend_knob_catalog():
        if not row["audited"]:
            assert row["owner"] == "UNAUDITED"
            assert row["overridable"] is False
            assert row["note"]


def test_derived_and_inactive_owners_are_flagged_not_editable():
    from veritx_dse.backend.booksim_profile import (
        BOOKSIM_CERTIFIED_CONFIG_AUDIT,
    )
    by_name = {r["name"]: r for r in backend_knob_catalog()}
    for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT:
        reported = by_name[row.name]
        owner = row.owner.value
        assert reported["derived"] is (owner in {
            "DERIVED", "FABRIC_DERIVED", "WORKLOAD_DERIVED",
            "EXECUTION_POLICY"})
        assert reported["inactive"] is (owner == "INACTIVE_FOR_PROFILE")
        # Nothing derived or inactive may read as an editable pinned value.
        if reported["derived"] or reported["inactive"]:
            assert reported["overridable"] is False


def test_classification_is_not_a_catch_all():
    """A power constant, a radix and a provenance key land in real buckets."""
    by_name = {r["name"]: r["category"] for r in backend_knob_catalog()}
    assert by_name["Vdd"] == "power"
    assert by_name["tech_file"] == "power"
    assert by_name["k"] == "topology"
    assert by_name["run_hash"] == "provenance"
    assert by_name["pair_stats"] == "traffic"
    # The catch-all must stay small: a bucket nobody can name is a bucket
    # the UI would render as a wall.
    other = sum(1 for c in by_name.values() if c == "other")
    assert other < 20, f"'other' swallowed {other} knobs"


def test_missing_source_degrades_to_an_empty_catalog(tmp_path):
    doc = backend_knob_catalog_document(tmp_path / "absent.cpp")
    assert doc["total"] == 0
    assert doc["knobs"] == []
    assert "note" in doc


def test_inventory_exposes_the_backend_section_additively():
    doc = knob_inventory()
    backend = doc["backend"]
    assert backend["type"] == "veritx/BackendKnobCatalog/v1"
    assert backend["total"] == len(backend["knobs"])
    # The intents contract is unchanged: this is an added section, not a
    # replacement for what the Design page already renders.
    assert doc["type"] == "veritx/KnobInventory/v1"
    assert "topology" in doc and "controls" in doc
    assert "constraints" not in doc


def test_counts_agree_with_the_rows():
    backend = backend_knob_catalog_document()
    rows = backend["knobs"]
    assert backend["total"] == len(rows)
    assert backend["audited"] == sum(1 for r in rows if r["audited"])
    assert backend["overridable"] == sum(1 for r in rows if r["overridable"])
    assert backend["controllable"] == sum(1 for r in rows if r["control"])
    assert sum(backend["by_category"].values()) == len(rows)
    assert sum(backend["by_owner"].values()) == len(rows)
