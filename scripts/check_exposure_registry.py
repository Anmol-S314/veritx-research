#!/usr/bin/env python3
"""Fail-closed gate for the exposure registry (Gate 6).

`docs/product/exposure-registry.yaml` is the single authority for which
Design intent fields the product may render, at which disclosure depth,
with which source-of-value. The frontend may map exposure classes to
presentation; it may not own the classification.

It checks:

  1. HEADER     schema id, version, and a capability semantics version
                equal to the capability registry's (one authority for the
                version every claim surface binds to);
  2. SHAPE      every field row states owner, source and class; class,
                behaviour, default and target_class come from declared
                vocabularies;
  3. REMOVED    a REMOVED_V4 source or a NOT_RENDERED / LEGACY_ONLY class
                is DO_NOT_RENDER — no removed-v4 field can be rendered;
  4. RENDERED   a rendered class (G1/G2/E1/E2) states a source-of-value
                and is not DO_NOT_RENDER;
  5. INTENT     every rendered field maps to a declared intent class, and
                no row names a field the intent model does not have;
  6. COVERAGE   every declared intent field has a row — the registry has
                no unclassified active field;
  7. AUTHORITY  no field name is both a rendered Design field and an
                evaluation-only / optimization-only entry (no duplicate
                field authority);
  8. FUTURE     no rendered field binds to a FUTURE_CONTRACT or
                LEGACY_ONLY capability — a future contract is never
                exposed as editable intent;
  9. REFS       every capability reference resolves; every preset's
                envelope resolves; a Guided-eligible preset names an
                envelope; the safe-path envelope resolves.

Exit codes:

  0  registry valid
  1  registry invalid

Usage:
    python3 scripts/check_exposure_registry.py
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
DSE = REPO_ROOT / "tracks" / "t3-topology" / "dse"
EXPOSURE = REPO_ROOT / "docs" / "product" / "exposure-registry.yaml"
CAPABILITY = REPO_ROOT / "docs" / "product" / "capability-registry.yaml"

SCHEMA = "srota/exposure-registry/v1"

#: Intent classes the Design surface may render. A rendered field must
#: belong to one of these — the registry cannot invent a field.
DECLARED_CLASSES = (
    "CompileRequestV3", "WorkloadV3", "RequirementV3", "Agent", "NocConfig",
    "AddressMap", "AddressRange", "PhysicalContext", "DependencyGraph",
    "Dependency", "CollectiveIntent", "WorkloadSourceRef",
)
PRODUCT_CLASSES = ("CompileIntent",)

#: Classes that mean "the user sees this as Design intent".
RENDERED = frozenset({"G1", "G2", "E1", "E2"})
#: Classes that mean "the user must not see this as Design intent".
HIDDEN = frozenset({"NOT_RENDERED", "LEGACY_ONLY"})
#: `container` is a structural row, satisfied by its child class.
CONTAINER = "container"


def _load_declared_fields() -> dict[str, list[str]]:
    """Follow the compiler, never a hand-kept list."""
    sys.path.insert(0, str(DSE))
    from veritx_dse.application.compile_intent import (  # noqa: PLC0415
        CompileIntent,
    )
    from veritx_dse.model import compile_model as cm  # noqa: PLC0415

    out: dict[str, list[str]] = {}
    for name in DECLARED_CLASSES:
        cls = getattr(cm, name)
        out[name] = [f.name for f in dataclasses.fields(cls)]
    for name in PRODUCT_CLASSES:
        out[name] = [f.name for f in dataclasses.fields(CompileIntent)]
    return out


def check(doc: dict, cap: dict,
          declared: dict[str, list[str]]) -> list[str]:
    errors: list[str] = []

    # ── 1. header ──────────────────────────────────────────────────────
    if doc.get("schema") != SCHEMA:
        errors.append(f"schema {doc.get('schema')!r} != {SCHEMA!r}")
    if not isinstance(doc.get("version"), int):
        errors.append("version must be an integer")
    exposure_csv = doc.get("capability_semantics_version")
    capability_csv = cap.get("capability_semantics_version")
    if exposure_csv != capability_csv:
        errors.append(
            f"capability_semantics_version {exposure_csv!r} != capability "
            f"registry {capability_csv!r} (one authority)")

    classes = set(doc.get("classes") or {}) | {CONTAINER}
    behaviours = set(doc.get("behaviours") or [])
    defaults = set(doc.get("default_classes") or {})
    fields = doc.get("fields") or {}
    envelopes = set(cap.get("envelopes") or {})
    caps_by_id = {c.get("id"): c for c in cap.get("capabilities") or []}

    # ── 2–4. per field row ─────────────────────────────────────────────
    for key, row in fields.items():
        row = row or {}
        for prop in ("owner", "src", "class"):
            if not row.get(prop):
                errors.append(f"{key}: missing {prop!r}")
        cls = row.get("class")
        if cls not in classes:
            errors.append(f"{key}: class {cls!r} is not declared")
        behaviour = row.get("behaviour")
        if behaviour is not None and behaviour not in behaviours:
            errors.append(f"{key}: behaviour {behaviour!r} is not declared")
        default = row.get("default")
        if default is not None and default not in defaults:
            errors.append(f"{key}: default {default!r} is not declared")
        target = row.get("target_class")
        if target is not None and target not in classes:
            errors.append(f"{key}: target_class {target!r} is not declared")

        # ── 3. removed-v4 is never rendered ────────────────────────────
        if row.get("src") == "REMOVED_V4" and behaviour != "DO_NOT_RENDER":
            errors.append(
                f"{key}: REMOVED_V4 must be DO_NOT_RENDER, got {behaviour!r}")
        if cls in HIDDEN and behaviour != "DO_NOT_RENDER":
            errors.append(
                f"{key}: class {cls} must be DO_NOT_RENDER, got {behaviour!r}")
        if behaviour == "DO_NOT_RENDER" and cls not in HIDDEN and cls != CONTAINER:
            errors.append(
                f"{key}: DO_NOT_RENDER but class {cls!r} is not a hidden class")

        # ── 4. rendered rows state their source of value ───────────────
        if cls in RENDERED:
            if default is None:
                errors.append(f"{key}: rendered class {cls} must state a default")
            if behaviour == "DO_NOT_RENDER":
                errors.append(f"{key}: rendered class {cls} cannot be DO_NOT_RENDER")

        # ── 9. capability reference ────────────────────────────────────
        ref = row.get("capability")
        ref_known = ref is None or ref in caps_by_id
        if not ref_known:
            errors.append(f"{key}: capability {ref!r} is not declared")

        # ── 5/8. rendered fields bind to available capabilities ────────
        if cls in RENDERED and ref_known and ref is not None:
            cap_row = caps_by_id[ref]
            stage = (cap_row.get("stages") or {}).get("DECLARABLE")
            if stage in ("FUTURE_CONTRACT", "LEGACY_ONLY"):
                errors.append(
                    f"{key}: rendered but capability {ref} is DECLARABLE "
                    f"{stage} — a future contract is never editable intent")

    # ── 5/6. intent mapping and coverage ───────────────────────────────
    known_paths: set[str] = set()
    for cls_name, names in declared.items():
        for field_name in names:
            known_paths.add(f"{cls_name}.{field_name}")

    for key in fields:
        if "." not in key:
            errors.append(f"{key}: field key is not Class.field")
            continue
        cls_name = key.split(".", 1)[0]
        if cls_name not in declared:
            errors.append(f"{key}: class {cls_name!r} is not a declared intent class")
        elif key not in known_paths:
            errors.append(f"{key}: the intent model has no such field")

    for path in sorted(known_paths):
        if path not in fields:
            errors.append(f"coverage: declared intent field {path} has no row")

    # ── 7. no duplicate field authority ────────────────────────────────
    rendered_names = {k.split(".", 1)[-1] for k, v in fields.items()
                      if (v or {}).get("class") in RENDERED}
    for group in ("evaluation_only", "optimization_only"):
        for entry in doc.get(group) or []:
            name = entry.get("field")
            if not name:
                errors.append(f"{group}: entry without a field")
                continue
            leaf = name.split(".")[-1]
            if leaf in rendered_names:
                errors.append(
                    f"{group}: {name!r} is also a rendered Design field "
                    "(duplicate field authority)")

    # ── 9. presets and safe path ───────────────────────────────────────
    for preset, spec in (doc.get("presets") or {}).items():
        spec = spec or {}
        env = spec.get("envelope")
        if spec.get("guided_eligible") and not env:
            errors.append(f"preset {preset}: Guided-eligible but names no envelope")
        if env is not None and env not in envelopes:
            errors.append(f"preset {preset}: envelope {env!r} is not declared")
    safe = doc.get("safe_path") or {}
    if safe.get("envelope") not in envelopes:
        errors.append(
            f"safe_path: envelope {safe.get('envelope')!r} is not declared")

    return errors


def main(argv: list[str]) -> int:
    doc = yaml.safe_load(EXPOSURE.read_text(encoding="utf-8"))
    cap = yaml.safe_load(CAPABILITY.read_text(encoding="utf-8"))
    declared = _load_declared_fields()
    errors = check(doc, cap, declared)
    if errors:
        print(f"EXPOSURE REGISTRY INVALID — {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
        return 1
    fields = doc.get("fields") or {}
    rendered = sum(1 for v in fields.values()
                   if (v or {}).get("class") in RENDERED)
    hidden = sum(1 for v in fields.values()
                 if (v or {}).get("behaviour") == "DO_NOT_RENDER")
    print(
        f"exposure registry valid: {len(fields)} field rows "
        f"({rendered} rendered, {hidden} never rendered), "
        f"{len(doc.get('classes') or {})} classes, "
        f"{len(doc.get('presets') or {})} presets, "
        f"capability_semantics_version={doc['capability_semantics_version']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
