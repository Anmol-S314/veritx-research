"""Authorable knob inventory, derived from the model — never hand-listed.

The design surface must not carry its own copy of what is authorable: a
second list drifts, and a knob the UI forgets is a capability the product
hides. This module walks the real intent dataclasses and the real
``NocControls`` record and emits what a client needs to render the whole
writable surface, including fields nobody hand-picked.

SCOPE: topology intents and fabric/router controls. The remaining request
blocks (agents, physical, requirements, address_map, workload) are NOT
covered yet. They are deliberately absent rather than half-derived: a block
whose model field name differs from the key the request serializes would
otherwise be written under a name the strict parser refuses. The parser's
own key tables (``_AGENT_KEYS``, ``_PHYSICAL_KEYS``, ``_REQUIREMENT_KEYS``,
``_WORKLOAD_KEYS``, ``_ADDRESS_MAP_KEYS`` in ``model/compile_model.py``) are
the authority for those; nothing guesses at them here.
"""
from __future__ import annotations

import dataclasses
import enum
import typing
from typing import Any

from veritx_dse.model import topology_intent as ti
from veritx_dse.model.noc_controls import NocControls, ROUTER_CONTROL_FIELDS


def _type_of(annotation: Any) -> dict[str, Any]:
    """Describe one field's annotation in transport terms."""
    args = typing.get_args(annotation)
    target = args[0] if args else annotation
    if isinstance(target, type) and issubclass(target, enum.Enum):
        return {"type": "enum", "values": [m.value for m in target]}
    if target is bool:
        return {"type": "boolean"}
    if target is int:
        return {"type": "integer"}
    if target is float:
        return {"type": "number"}
    if target is str:
        return {"type": "string"}
    origin = typing.get_origin(target)
    if origin in (list, tuple, set):
        return {"type": "list"}
    if origin is dict or target is dict:
        return {"type": "object"}
    # Optional[...] keeps the inner type when one is present.
    return {"type": "json"}


def _resolved_hints(cls: type) -> dict[str, Any]:
    """Real types, not PEP-563 strings.

    These modules use `from __future__ import annotations`, so a field's
    `.type` is the STRING 'int' or 'GecMode'. Resolving through the owning
    class is what makes one generic walker serve every intent instead of a
    hand-written field list per family.
    """
    try:
        return typing.get_type_hints(cls)
    except Exception:
        return {f.name: f.type for f in dataclasses.fields(cls)}


def _field_doc(f: dataclasses.Field, hints: dict[str, Any]) -> dict[str, Any]:
    default = f.default if f.default is not dataclasses.MISSING else None
    if default is not dataclasses.MISSING and isinstance(default, enum.Enum):
        default = default.value
    required = (f.default is dataclasses.MISSING
                and f.default_factory is dataclasses.MISSING)
    return {
        "name": f.name,
        "required": required,
        "default": None if required else default,
        **_type_of(hints.get(f.name, f.type)),
    }


def topology_knobs() -> list[dict[str, Any]]:
    """Every authorable topology field, per intent kind."""
    out: list[dict[str, Any]] = []
    for kind, cls in sorted(ti._KIND_TO_CLASS.items()):
        if kind == "structured":
            # `structured` takes a free params mapping whose legal keys live in
            # the family registry, not in this dataclass. It is reported as an
            # object rather than guessed field-by-field.
            out.append({"kind": kind, "label": "Structured (family params)",
                        "fields": [{"name": "family", "type": "string",
                                    "required": True, "default": None},
                                   {"name": "params", "type": "object",
                                    "required": True, "default": None}]})
            continue
        hints = _resolved_hints(cls)
        out.append({
            "kind": kind,
            "label": cls.__name__.removesuffix("Intent"),
            "fields": [_field_doc(f, hints) for f in dataclasses.fields(cls)
                       if f.name != "kind"],
        })
    return out


def control_knobs() -> list[dict[str, Any]]:
    """Every authorable fabric control, flagged as router micro-architecture."""
    router = set(ROUTER_CONTROL_FIELDS)
    # The BookSim source each router control binds to, where the backend
    # declares one. Read from the backend, never restated here.
    try:
        from veritx_dse.backend.router_controls import NATIVE_FIELDS
    except Exception:  # pragma: no cover - backend optional at import time
        NATIVE_FIELDS = {}
    hints = _resolved_hints(NocControls)
    out = []
    for f in dataclasses.fields(NocControls):
        if f.name == "output_formats":
            from veritx_dse.model.compile_model import OutputFormat
            out.append({"name": f.name, "required": False, "default": [],
                        "type": "enum_list",
                        "values": [o.value for o in OutputFormat],
                        "group": "generation"})
            continue
        doc = _field_doc(f, hints)
        doc["group"] = "router" if f.name in router else "fabric"
        native = NATIVE_FIELDS.get(f.name)
        if native:
            doc["binds"] = {"field": native[0], "source": native[1]}
        out.append(doc)
    return out


def knob_inventory() -> dict[str, Any]:
    """The complete writable surface for the blocks this module covers."""
    return {
        "type": "veritx/KnobInventory/v1",
        "topology": topology_knobs(),
        "controls": control_knobs(),
        "not_covered": ["agents", "physical", "requirements", "address_map",
                        "workload", "dependencies"],
        "notes": (
            "Derived by introspection from the intent dataclasses and "
            "NocControls. Deliberately carries no bounds, no legal-value "
            "lists and no cross-field rules: those live in the parser and "
            "validator, which refuse. This file reports SHAPE, and the "
            "engine decides legality, so the two cannot disagree. Request "
            "blocks other than topology and controls are not yet covered; "
            "see the module docstring."
        ),
    }
