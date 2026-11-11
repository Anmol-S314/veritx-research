"""The backend knob surface, derived from the source and the profile audit.

The design surface must not carry its own copy of what the backend accepts:
a second list drifts, and a knob the UI forgets is a capability the product
hides. This module joins the two authorities we already have:

* the fork's own registration (``third_party/booksim2/src/booksim_config.cpp``)
  answers "what does the binary accept, and what is its default";
* the closure audit (``backend/booksim_profile.py``) answers "who owns this
  value, where is it read, and may a profile override it".

Neither is restated here. A knob that is registered but never read by any
audited profile is reported as ``UNAUDITED`` rather than hidden, because
"the binary accepts it" is true and worth showing; it is just not yet
product-relevant.

SCOPE: this reports the BACKEND knob surface alongside the intent surface
``knob_inventory`` already derives. It does not itself make a knob
authorable: "listed" and "safe to override" are different claims, and the
audit's owner is what separates them.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Where a knob is read, classified for rendering. Derived from the source
# location the audit records, so a new row lands in a real bucket instead of
# "other" by default.
_CATEGORY_BY_FILE: dict[str, str] = {
    "trafficmanager.cpp": "traffic",
    "iq_router.cpp": "router",
    "router.cpp": "router",
    "chaos_router.cpp": "router",
    "event_router.cpp": "router",
    "allocator.cpp": "allocator",
    "srota_arb.cpp": "arbiter",
    "arbiter.cpp": "arbiter",
    "buffer.cpp": "buffer",
    "buffer_state.cpp": "buffer",
    "main.cpp": "runtime",
    "power_module.cpp": "power",
}

_MEASUREMENT_SUFFIXES = ("_out", "_output", "_observation_file")
_MEASUREMENT_PREFIXES = ("watch_", "stats_")

# Name-based buckets for knobs registered in the fork's config file, where
# the audit records no read site to classify from. Ordered: the first rule
# that matches wins, so the specific spellings come before the general ones.
_POWER_RE = re.compile(
    r"^(H_|W_|Ioff|Cg|Cd|Cw_)|(_pwr$)|^(R|Rw|Vdd|LAMBDA|MetalPitch|tech_file|"
    r"power_output_file|wire_length)$")
_TOPOLOGY_NAMES = frozenset({
    "k", "n", "c", "o", "d", "mesh", "hybrid", "x", "y", "xr", "yr",
    "use_noc_latency"})
_PROVENANCE_RE = re.compile(
    r"^(run_|sample_period_cycles$|link_capacity_flits_per_cycle$|"
    r"perm_seed$|fail_seed$|trace_packet_log$)")
_CLASS_VCS = frozenset({
    "classes", "class_subnet", "priority", "vc_priority_donation"})
_CLASS_VC_RE = re.compile(r"(^mesh_class_vc_)|(_begin_vc$)|(_end_vc$)")
_TRAFFIC_RE = re.compile(
    r"^(batch_(count|size)$|burst_|in_ports$|out_ports$|output_delay$|"
    r"max_outstanding_requests$|reorder$|split_packets$|vct$)")

# Registration forms in booksim_config.cpp. The fork registers strings with
# the helper and numbers by direct map assignment; both are the authority.
_STR_RE = re.compile(r'AddStrField\(\s*"([A-Za-z_0-9]+)"\s*,\s*"([^"]*)"')
_INT_RE = re.compile(r'_int_map\[\s*"([A-Za-z_0-9]+)"\s*\]\s*=\s*(-?\d+)')
_FLOAT_RE = re.compile(
    r'_float_map\[\s*"([A-Za-z_0-9]+)"\s*\]\s*=\s*(-?[0-9.]+)')


def _registered_knobs(source: Path) -> dict[str, dict[str, Any]]:
    """Every knob the binary registers, with its default and transport type.

    A name may be registered twice when the fork needs a vector spelling
    (``class_subnet``, ``srota_isl_rate``): the scalar registration is the
    typed authority and the string registration is recorded as the
    workaround it says it is.
    """
    text = source.read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict[str, Any]] = {}
    for name, default in _STR_RE.findall(text):
        out.setdefault(name, {})["str_default"] = default
    for name, default in _INT_RE.findall(text):
        entry = out.setdefault(name, {})
        entry["value_default"] = int(default)
        entry["type"] = "integer"
    for name, default in _FLOAT_RE.findall(text):
        entry = out.setdefault(name, {})
        entry["value_default"] = float(default)
        entry["type"] = "number"
    for entry in out.values():
        entry.setdefault("type", "string")
        # A string default equal to "" is how the fork spells "disabled";
        # reporting it as absent would hide an opt-in default.
        entry.setdefault(
            "value_default",
            "" if entry.get("str_default") == "" else entry.get("str_default"))
        entry.setdefault("vector_spelling", "str_default" in entry
                         and entry["type"] != "string")
    return out


def _category(name: str, source: str) -> str:
    if name.startswith("srota_"):
        return "srota"
    # Power/tech constants are checked before the measurement suffixes: a
    # `*_file` spelling says where a value comes from, not what it measures.
    if _POWER_RE.search(name):
        return "power"
    if name.startswith(_MEASUREMENT_PREFIXES) \
            or name.endswith(_MEASUREMENT_SUFFIXES):
        return "measurement"
    file_name = Path(source.split(":", 1)[0]).name
    if file_name in _CATEGORY_BY_FILE:
        return _CATEGORY_BY_FILE[file_name]
    if file_name.startswith("network") or file_name in (
            "srota.cpp", "torus.cpp", "mesh.cpp", "flatfly.cpp", "anynet.cpp"):
        return "topology"
    if name in _TOPOLOGY_NAMES:
        return "topology"
    if _PROVENANCE_RE.search(name):
        return "provenance"
    if name in _CLASS_VCS or _CLASS_VC_RE.search(name):
        return "class_vc"
    if _TRAFFIC_RE.search(name):
        return "traffic"
    if name.endswith("_file") or name.endswith("_log"):
        return "io"
    return "other"


def _audit_rows() -> dict[str, Any]:
    """Every audited field across the shipped profiles, first row wins.

    Rows disagree between profiles only in the pin a profile fixes; the
    owner and the source location are properties of the field, so the first
    declaration is the right one to report.
    """
    from veritx_dse.backend.booksim_profile import (
        BOOKSIM_CERTIFIED_CONFIG_AUDIT,
    )
    out: dict[str, Any] = {}
    for row in BOOKSIM_CERTIFIED_CONFIG_AUDIT:
        out.setdefault(row.name, row)
    return out


def _controllable_names() -> dict[str, str]:
    """backend knob -> the authored control that already drives it."""
    try:
        from veritx_dse.backend.router_controls import NATIVE_FIELDS
    except Exception:  # pragma: no cover - backend optional at import time
        return {}
    return {key: field for field, (key, _src) in NATIVE_FIELDS.items()}


def backend_knob_catalog(source: Path | None = None) -> list[dict[str, Any]]:
    """Every backend knob, classified, in a stable order."""
    from veritx_dse.core.paths import BOOKSIM_DIR
    path = source or (BOOKSIM_DIR / "booksim_config.cpp")
    if not path.is_file():
        return []
    registered = _registered_knobs(path)
    audit = _audit_rows()
    controllable = _controllable_names()

    rows: list[dict[str, Any]] = []
    for name in sorted(set(registered) | set(audit)):
        entry = registered.get(name, {})
        row = audit.get(name)
        if row is None:
            owner = "UNAUDITED"
            source_location = "booksim_config.cpp"
            note = ("registered by the fork but read by no audited profile; "
                    "listed so a hidden knob is visible, not because the "
                    "product owns it")
            pinned = None
            optional = False
        else:
            owner = row.owner.value
            source_location = row.source
            note = row.note
            pinned = row.pin
            optional = bool(getattr(row, "optional", False))
        rows.append({
            "name": name,
            "type": entry.get("type", "string"),
            "category": _category(name, source_location),
            "owner": owner,
            "source": source_location,
            "default": entry.get("value_default"),
            "registered": name in registered,
            "audited": row is not None,
            # A BACKEND_PROFILE value is a pinned profile constant: that is
            # the set a controlled profile legitimately replaces. Other
            # owners are derived from the compiled design, and an unaudited
            # knob cannot be overridden at all until it has an audit row.
            "overridable": owner == "BACKEND_PROFILE",
            "derived": owner in ("DERIVED", "FABRIC_DERIVED",
                                 "WORKLOAD_DERIVED", "EXECUTION_POLICY"),
            "inactive": owner == "INACTIVE_FOR_PROFILE",
            "control": controllable.get(name),
            "optional": optional,
            "pinned": pinned,
            "vector_spelling": bool(entry.get("vector_spelling")),
            "note": note,
        })
    return rows


_DOCUMENT_CACHE: dict[tuple[str, float], dict[str, Any]] = {}


def backend_knob_catalog_document(source: Path | None = None
                                  ) -> dict[str, Any]:
    """The catalog plus the counts a client renders without re-deriving.

    Cached per source mtime: the gateway serves this on a page load, and
    re-parsing a 433-line C++ file per request is pure waste. A moved mtime
    (an edited fork) invalidates it.
    """
    from veritx_dse.core.paths import BOOKSIM_DIR
    path = source or (BOOKSIM_DIR / "booksim_config.cpp")
    if not path.is_file():
        return {
            "type": "veritx/BackendKnobCatalog/v1",
            "source": str(path),
            "total": 0, "audited": 0, "overridable": 0, "controllable": 0,
            "by_category": {}, "by_owner": {}, "knobs": [],
            "note": "the fork's config source is not present in this tree",
        }
    key = (str(path), path.stat().st_mtime)
    cached = _DOCUMENT_CACHE.get(key)
    if cached is not None:
        return cached
    rows = backend_knob_catalog(path)
    by_category: dict[str, int] = {}
    by_owner: dict[str, int] = {}
    for row in rows:
        by_category[row["category"]] = by_category.get(row["category"], 0) + 1
        by_owner[row["owner"]] = by_owner.get(row["owner"], 0) + 1
    document = {
        "type": "veritx/BackendKnobCatalog/v1",
        "source": "third_party/booksim2/src/booksim_config.cpp",
        "total": len(rows),
        "audited": sum(1 for r in rows if r["audited"]),
        "overridable": sum(1 for r in rows if r["overridable"]),
        "controllable": sum(1 for r in rows if r["control"]),
        "by_category": dict(sorted(by_category.items())),
        "by_owner": dict(sorted(by_owner.items())),
        "knobs": rows,
    }
    _DOCUMENT_CACHE.clear()
    _DOCUMENT_CACHE[key] = document
    return document
