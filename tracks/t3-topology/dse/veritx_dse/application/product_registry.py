"""veritx_dse.application.product_registry — the backend owner of the
frozen product registries (Gate 4 / Gate 6).

Two planning authorities live as data, not as Python:

  * ``docs/product/capability-registry.yaml`` — what SROTA can represent,
    derive, verify, project, execute, qualify, evidence and wire, plus the
    certified envelopes and their conditions;
  * ``docs/product/exposure-registry.yaml`` — which Design intent fields
    the product may render, at which disclosure depth, with which
    source-of-value.

Nothing here re-states them. This module loads them, exposes the single
``capability_semantics_version`` every claim surface binds to, and
projects per-field and per-capability facts. The frontend may map exposure
classes to presentation; it never owns the classification (Gate 8 §12/§13).

Fail-closed (Gate 8 §137/§138): if the registries are absent, unreadable or
disagree about the semantics version, a typed error is raised and the
claim surface withholds claims rather than guessing.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

CAPABILITY_FILE = "capability-registry.yaml"
EXPOSURE_FILE = "exposure-registry.yaml"

CAPABILITY_SCHEMA = "srota/capability-registry/v1"
EXPOSURE_SCHEMA = "srota/exposure-registry/v1"

#: Stages, in pipeline order (Gate 4).
STAGES = (
    "DECLARABLE", "DERIVABLE", "VERIFIABLE", "PROJECTABLE", "EXECUTABLE",
    "QUALIFIED", "EVIDENCE_CAPABLE", "PRODUCT_WIRED",
)

#: Exposure classes the user sees as Design intent.
RENDERED_CLASSES = frozenset({"G1", "G2", "E1", "E2"})
#: Exposure classes that mean "never rendered as Design intent".
HIDDEN_CLASSES = frozenset({"NOT_RENDERED", "LEGACY_ONLY"})
#: A structural row, satisfied by its child class.
CONTAINER_CLASS = "container"


class ProductRegistryError(RuntimeError):
    """The product registries are unavailable or mutually inconsistent.

    A claim surface that raises this must withhold claims — it must never
    substitute a guess (Gate 8 §137/§138).
    """


def registry_dir() -> Path:
    """Locate ``docs/product``.

    ``VERITX_PRODUCT_REGISTRY_DIR`` wins (a deployed gateway may ship the
    registries beside the app); otherwise walk up from this module looking
    for the directory, so an installed package still finds the repo copy.
    """
    override = os.environ.get("VERITX_PRODUCT_REGISTRY_DIR")
    if override:
        path = Path(override)
        if not path.is_dir():
            raise ProductRegistryError(
                f"VERITX_PRODUCT_REGISTRY_DIR {override!r} is not a directory")
        return path
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "docs" / "product"
        if (candidate / CAPABILITY_FILE).is_file():
            return candidate
    raise ProductRegistryError(
        "docs/product is not reachable from the installed package; set "
        "VERITX_PRODUCT_REGISTRY_DIR")


def _load(name: str) -> dict[str, Any]:
    path = registry_dir() / name
    try:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProductRegistryError(f"{path} is missing") from exc
    except yaml.YAMLError as exc:
        raise ProductRegistryError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(document, dict):
        raise ProductRegistryError(f"{path} is not a mapping")
    return document


@lru_cache(maxsize=1)
def capability_document() -> dict[str, Any]:
    document = _load(CAPABILITY_FILE)
    if document.get("schema") != CAPABILITY_SCHEMA:
        raise ProductRegistryError(
            f"{CAPABILITY_FILE} schema {document.get('schema')!r} != "
            f"{CAPABILITY_SCHEMA!r}")
    return document


@lru_cache(maxsize=1)
def exposure_document() -> dict[str, Any]:
    document = _load(EXPOSURE_FILE)
    if document.get("schema") != EXPOSURE_SCHEMA:
        raise ProductRegistryError(
            f"{EXPOSURE_FILE} schema {document.get('schema')!r} != "
            f"{EXPOSURE_SCHEMA!r}")
    return document


@lru_cache(maxsize=1)
def capability_semantics_version() -> str:
    """The ONE version every product claim surface binds to (Gate 4, §7).

    Both registries must agree; a disagreement is a build error, not
    something a caller may paper over.
    """
    capability = capability_document().get("capability_semantics_version")
    exposure = exposure_document().get("capability_semantics_version")
    if not capability:
        raise ProductRegistryError(
            f"{CAPABILITY_FILE} has no capability_semantics_version")
    if capability != exposure:
        raise ProductRegistryError(
            "registries disagree on capability_semantics_version: "
            f"{CAPABILITY_FILE}={capability!r} {EXPOSURE_FILE}={exposure!r}")
    return capability


def registry_versions() -> dict[str, Any]:
    """The version envelope a claim surface echoes back to a client."""
    return {
        "capability_semantics_version": capability_semantics_version(),
        "capability_registry_version": capability_document().get("version"),
        "exposure_registry_version": exposure_document().get("version"),
    }


# ── capabilities ───────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def capability_by_id() -> dict[str, dict[str, Any]]:
    return {row["id"]: row
            for row in capability_document().get("capabilities") or []
            if row.get("id")}


def capability_rows() -> list[dict[str, Any]]:
    return list(capability_document().get("capabilities") or [])


def envelopes() -> dict[str, dict[str, Any]]:
    return dict(capability_document().get("envelopes") or {})


def conditions() -> dict[str, str]:
    return dict(capability_document().get("conditions") or {})


def capability_stage(capability_id: str, stage: str) -> str | None:
    row = capability_by_id().get(capability_id)
    if row is None:
        return None
    return (row.get("stages") or {}).get(stage)


def capability_consequence(capability_id: str) -> dict[str, Any] | None:
    """The staged truth about one capability, in product terms.

    This is what a Design capability consequence is built from: the eight
    stages, the wiring class, the reason, the limitation and the claim
    scope. Never a single support boolean.
    """
    row = capability_by_id().get(capability_id)
    if row is None:
        return None
    stages = row.get("stages") or {}
    return {
        "capability_id": capability_id,
        "name": row.get("name"),
        "owner": row.get("owner"),
        "stages": {stage: stages.get(stage) for stage in STAGES},
        "wiring": row.get("wiring"),
        "reason": row.get("reason"),
        "limiting": row.get("limiting"),
        "claim_scope": row.get("claim_scope"),
        "conditions": list(row.get("conditions") or []),
        "capability_semantics_version": capability_semantics_version(),
    }


# ── exposure ───────────────────────────────────────────────────────────

def exposure_fields() -> dict[str, dict[str, Any]]:
    return dict(exposure_document().get("fields") or {})


def exposure_row(field_path: str) -> dict[str, Any] | None:
    return exposure_fields().get(field_path)


def exposure_class(field_path: str) -> str | None:
    row = exposure_row(field_path)
    return None if row is None else row.get("class")


def is_rendered(field_path: str) -> bool:
    """May this field appear as Design intent?"""
    row = exposure_row(field_path)
    if row is None:
        # Unknown field: fail closed. An unclassified active field is
        # never rendered (Gate 8 §138).
        return False
    if row.get("class") in HIDDEN_CLASSES or row.get("class") == CONTAINER_CLASS:
        return False
    if row.get("behaviour") == "DO_NOT_RENDER":
        return False
    return row.get("class") in RENDERED_CLASSES


def disclosure_depth(field_path: str) -> str | None:
    """GUIDED or EXPERT, from the class's ``rendered_at``."""
    row = exposure_row(field_path)
    if row is None:
        return None
    cls = exposure_document().get("classes", {}).get(row.get("class")) or {}
    return cls.get("rendered_at")


def product_label(field_path: str, depth: str = "GUIDED") -> str | None:
    """The product label for a field.

    ``NocConfig.radix`` is the implementation name; the scientific name is
    ``side_length`` and the product labels are "Grid size" (Guided) and
    "Mesh side length" (Expert). The label lives in the registry so no
    surface invents its own (Gate 3 CROSS-DOMAIN CORRECTION, §16).
    """
    row = exposure_row(field_path)
    if row is None:
        return None
    if depth == "EXPERT":
        return row.get("label_expert") or row.get("label_guided")
    return row.get("label_guided") or row.get("label_expert")


def scientific_name(field_path: str) -> str | None:
    row = exposure_row(field_path)
    if row is None:
        return None
    return row.get("scientific_name")


def source_of_value(field_path: str) -> str | None:
    row = exposure_row(field_path)
    return None if row is None else row.get("default")


def field_capability(field_path: str) -> str | None:
    row = exposure_row(field_path)
    return None if row is None else row.get("capability")


def preset_spec(preset_id: str) -> dict[str, Any] | None:
    return (exposure_document().get("presets") or {}).get(preset_id)


def guided_eligible_presets() -> list[str]:
    presets = exposure_document().get("presets") or {}
    return sorted(name for name, spec in presets.items()
                  if (spec or {}).get("guided_eligible"))


def safe_path() -> dict[str, Any]:
    return dict(exposure_document().get("safe_path") or {})


def clear_cache() -> None:
    """Drop the memoized documents (tests and hot reload only)."""
    capability_document.cache_clear()
    exposure_document.cache_clear()
    capability_semantics_version.cache_clear()
    capability_by_id.cache_clear()


__all__ = [
    "CAPABILITY_SCHEMA",
    "CONTAINER_CLASS",
    "EXPOSURE_SCHEMA",
    "HIDDEN_CLASSES",
    "ProductRegistryError",
    "RENDERED_CLASSES",
    "STAGES",
    "capability_by_id",
    "capability_consequence",
    "capability_document",
    "capability_rows",
    "capability_semantics_version",
    "capability_stage",
    "clear_cache",
    "conditions",
    "disclosure_depth",
    "envelopes",
    "exposure_class",
    "exposure_document",
    "exposure_fields",
    "exposure_row",
    "field_capability",
    "guided_eligible_presets",
    "is_rendered",
    "preset_spec",
    "product_label",
    "registry_dir",
    "registry_versions",
    "safe_path",
    "scientific_name",
    "source_of_value",
]
