"""The knob inventory must be DERIVED, never a hand-written list.

If a field exists in the model and not in the inventory, the UI hides a
capability. If a value exists in the inventory and not in the model, the UI
offers something the parser refuses. Both are drift, and this gate closes
them by walking the same objects the inventory walks.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.knob_inventory import (  # noqa: E402
    control_knobs, knob_inventory, topology_knobs,
)
from veritx_dse.model import topology_intent as ti  # noqa: E402
from veritx_dse.model.noc_controls import NocControls  # noqa: E402


def test_every_intent_kind_appears_with_every_authorable_field():
    inv = topology_knobs()
    reported = {f["kind"]: {f["name"] for f in f["fields"]} for f in inv}
    for kind, cls in ti._KIND_TO_CLASS.items():
        declared = {f.name for f in dataclasses.fields(cls) if f.name != "kind"}
        if kind == "structured":
            # Free params mapping: reported as an object, not field-by-field.
            assert reported[kind] == {"family", "params"}
            continue
        assert reported.get(kind) == declared, (
            f"{kind}: inventory {reported.get(kind)} != model {declared}")


def test_every_control_field_appears_exactly_once():
    inv = control_knobs()
    names = [c["name"] for c in inv]
    assert len(names) == len(set(names))
    assert set(names) == {f.name for f in dataclasses.fields(NocControls)}


def test_router_controls_are_flagged_as_router_group():
    from veritx_dse.model.noc_controls import ROUTER_CONTROL_FIELDS
    router = {c["name"] for c in control_knobs() if c.get("group") == "router"}
    assert router == set(ROUTER_CONTROL_FIELDS)


def test_enum_fields_report_every_legal_value():
    """The list the UI renders comes from here, so it cannot fall behind."""
    inv = topology_knobs()
    srota = next(f for f in inv if f["kind"] == "srota")
    policy = next(f for f in srota["fields"] if f["name"] == "vc_policy")
    assert policy["type"] == "enum"
    # The engine accepts four policies; a hand-written UI list had three.
    assert set(policy["values"]) >= {"none", "shape", "rank", "oneshape"}
    gec = next(f for f in inv if f["kind"] == "gec")
    mode = next(f for f in gec["fields"] if f["name"] == "mode")
    assert set(mode["values"]) == {m.value for m in ti.GecMode}


def test_router_controls_carry_their_backend_binding():
    bound = {c["name"]: c["binds"] for c in control_knobs() if c.get("binds")}
    from veritx_dse.backend.router_controls import NATIVE_FIELDS
    assert set(bound) == set(NATIVE_FIELDS)


def test_inventory_states_shape_not_legality():
    """Bounds and cross-field rules must NOT be duplicated client-side."""
    doc = knob_inventory()
    assert "constraints" not in doc
    assert doc["type"] == "veritx/KnobInventory/v1"
    for family in doc["topology"]:
        for field in family["fields"]:
            assert "min" not in field and "max" not in field
    for control in doc["controls"]:
        assert "min" not in control and "max" not in control

def test_unc_covered_blocks_are_declared_not_guessed():
    """Blocks this module does not derive must be named, not half-derived.

    `physical` holds `default_clock_freq_mhz` while the request serializes
    `clock_freq_mhz`; guessing the name would write a key the strict parser
    refuses. The gap is declared so the UI can say so instead of silently
    offering controls that would not save.
    """
    doc = knob_inventory()
    assert "request_blocks" not in doc
    assert set(doc["not_covered"]) == {
        "agents", "physical", "requirements", "address_map", "workload",
        "dependencies"}
