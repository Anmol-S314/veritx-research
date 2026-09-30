"""veritx_dse.performance.profile_ingest — customer-supplied measured profiles.

A ``ModelProfile`` normally comes from repo-shipped profiler CSVs
(``model_profile.derive_profile``). A customer brings their OWN measured
numbers, so this module turns a documented document into the same
first-class ``ModelProfile`` the evaluators already consume.

Schema ``veritx.model-profile/1``::

    {
      "schema": "veritx.model-profile/1",
      "model": "astr-llm-70b",          # customer model id (free text)
      "hardware": "ASTRA-AC-1",          # the silicon it was measured on
      "variant": "bf16",
      "tp": 4, "ep": 1,
      "source": "customer run 2026-03-14, n=512 tokens",
      "layers": [
        {"index": 0, "kind": "attention", "duration_ns": 45632,
         "input_bytes": 8192, "weight_bytes": 41943040, "output_bytes": 8192},
        {"index": 0, "kind": "dense_ffn", "duration_ns": null,
         "missing": "not measured at tp4"}
      ]
    }

Contract (fail-closed, same law as the rest of the product):

  * unknown keys refuse — never silently ignored;
  * ``duration_ns`` is REQUIRED on every layer and must be an explicit
    integer or an explicit ``null``;
  * an explicit ``null`` MUST carry a non-empty ``missing`` reason — an
    absence is a statement, not a blank;
  * a layer missing ``duration_ns`` entirely refuses (no invented numbers);
  * byte fields must be non-negative integers.

See docs/decisions/compute-memory-intent.md and
docs/product/profile-ingestion.md.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from veritx_dse.core.errors import SemanticError
from veritx_dse.model.compute_intent import ComputeSource
from veritx_dse.performance.model_profile import (
    LayerProfile,
    ModelProfile,
)

SCHEMA = "veritx.model-profile/1"

_TOP_KEYS = frozenset({
    "schema", "model", "hardware", "variant", "tp", "ep", "source",
    "provenance", "layers",
})
_LAYER_KEYS = frozenset({
    "index", "kind", "duration_ns", "missing", "input_bytes",
    "weight_bytes", "output_bytes",
})
_BYTE_KEYS = ("input_bytes", "weight_bytes", "output_bytes")
CONVENTIONAL_KINDS = frozenset({"attention", "moe", "dense_ffn"})

class ProfileIngestError(ValueError, SemanticError):
    """The customer profile document is not a valid veritx.model-profile/1."""

def _keys(doc: Any, allowed: frozenset[str], where: str) -> None:
    if not isinstance(doc, dict):
        raise ProfileIngestError(f"{where} must be a JSON object, got "
                                 f"{type(doc).__name__}")
    extra = set(doc) - allowed
    if extra:
        raise ProfileIngestError(
            f"{where} has unknown fields {sorted(extra)}; allowed "
            f"{sorted(allowed)}")

def _text(doc: dict[str, Any], key: str, where: str) -> str:
    v = doc.get(key)
    if not isinstance(v, str) or not v.strip():
        raise ProfileIngestError(
            f"{where}.{key} must be a non-empty string, got {v!r}")
    return v

def _count(doc: dict[str, Any], key: str, where: str, *, minimum: int = 0,
           required: bool = True) -> int | None:
    if key not in doc or doc[key] is None:
        if required:
            raise ProfileIngestError(f"{where}.{key} is required")
        return None
    v = doc[key]
    if isinstance(v, bool) or not isinstance(v, int) or v < minimum:
        raise ProfileIngestError(
            f"{where}.{key} must be an integer >= {minimum}, got {v!r}")
    return v

def _layer(doc: Any, where: str) -> LayerProfile:
    _keys(doc, _LAYER_KEYS, where)
    index = _count(doc, "index", where)
    kind = _text(doc, "kind", where)

    if "duration_ns" not in doc:
        raise ProfileIngestError(
            f"{where}.duration_ns is required — a layer is either measured "
            "(integer) or an explicit null with a `missing` reason; it is "
            "never absent (that would let a missing measurement pass as "
            "zero)")
    duration = doc["duration_ns"]
    missing = doc.get("missing")
    if duration is None:
        if not isinstance(missing, str) or not missing.strip():
            raise ProfileIngestError(
                f"{where}.duration_ns is null — an explicit absence MUST "
                "carry a non-empty `missing` reason")
    else:
        if isinstance(duration, bool) or not isinstance(duration, int) \
                or duration < 0:
            raise ProfileIngestError(
                f"{where}.duration_ns must be a non-negative integer or "
                f"explicit null, got {duration!r}")
        if missing is not None:
            raise ProfileIngestError(
                f"{where} declares both duration_ns and a `missing` reason "
                "— a measured layer has no absence to explain")

    byte_values = {k: (_count(doc, k, where, required=False) or 0)
                   for k in _BYTE_KEYS}
    components = ((kind, duration),)
    return LayerProfile(
        layer_index=index if index is not None else 0,
        kind=kind,
        duration_ns=duration,
        duration_components=components,
        missing=() if duration is not None else (missing,),
        input_bytes=byte_values["input_bytes"],
        weight_bytes=byte_values["weight_bytes"],
        output_bytes=byte_values["output_bytes"],
        weight_source="customer-supplied profile",
    )

def profile_from_document(doc: Any, *, origin: str = "<document>",
                          ) -> ModelProfile:
    """Build a first-class ``ModelProfile`` from a customer document."""
    _keys(doc, _TOP_KEYS, origin)
    schema = doc.get("schema")
    if schema != SCHEMA:
        raise ProfileIngestError(
            f"{origin}.schema must be {SCHEMA!r}, got {schema!r}")
    model = _text(doc, "model", origin)
    hardware = _text(doc, "hardware", origin)
    variant = _text(doc, "variant", origin)
    tp = _count(doc, "tp", origin, minimum=1)
    ep = _count(doc, "ep", origin, minimum=1, required=False) or 1
    source = doc.get("source")
    if source is not None and (not isinstance(source, str)
                               or not source.strip()):
        raise ProfileIngestError(
            f"{origin}.source must be a non-empty string when present")

    if "provenance" in doc:
        try:
            provenance = ComputeSource.from_dict(doc["provenance"])
        except Exception as exc:
            raise ProfileIngestError(
                f"{origin}.provenance: {exc}") from exc
        if not provenance.specified:
            raise ProfileIngestError(
                f"{origin}.provenance is present but `unspecified` — omit "
                "the block to claim a measurement, or name the kind")
    else:
        provenance = ComputeSource(
            kind="measured",
            detail="per-layer durations supplied by the measurer",
            reference=source or origin)

    raw_layers = doc.get("layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise ProfileIngestError(
            f"{origin}.layers must be a non-empty array")
    layers = tuple(_layer(l, f"{origin}.layers[{i}]")
                   for i, l in enumerate(raw_layers))

    indexes = sorted({l.layer_index for l in layers})
    if indexes != list(range(len(indexes))):
        raise ProfileIngestError(
            f"{origin}.layers: layer indexes must be 0..N-1 without gaps, "
            f"got {indexes}")

    return ModelProfile(
        model=model, hardware=hardware, variant=variant, tp=tp, ep=ep,
        layers=layers,
        weight_source=f"customer profile: {source or origin}",
        source=provenance)

def load_profile(path: str | Path) -> ModelProfile:
    """Read a customer profile document from disk (JSON)."""
    p = Path(path)
    if not p.is_file():
        raise ProfileIngestError(f"profile document not found: {p}")
    try:
        doc = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise ProfileIngestError(f"{p}: invalid JSON: {exc}") from exc
    return profile_from_document(doc, origin=str(p))

__all__ = [
    "ProfileIngestError",
    "SCHEMA",
    "load_profile",
    "profile_from_document",
]
