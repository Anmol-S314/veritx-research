#!/usr/bin/env python3
"""Validate docs/product/topology-family-registry.yaml against the code.

This checker exists to stop enum drift. The tree carries two enums that
disagree (TopologyFamily vs MaterializedFamily); the registry is the stage
authority and this script fails closed if they diverge.

Invariants enforced (TAX-1..TAX-6 in the registry):

  TAX-1  RECOGNIZED does not imply AUTHORABLE
  TAX-2  AUTHORABLE does not imply MATERIALIZABLE
  TAX-3  MATERIALIZABLE does not imply AUTHORABLE
  TAX-4  MATERIALIZABLE does not imply ROUTABLE
  TAX-5  canonical_id is not a backend spelling
  TAX-6  no enum-set comparison is used as capability authority

Exit 0 = valid. Exit 1 = drift.
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
REGISTRY = REPO / "docs/product/topology-family-registry.yaml"
DSE = REPO / "tracks/t3-topology/dse"

sys.path.insert(0, str(DSE))


def _load() -> dict:
    try:
        import yaml
    except ImportError:
        print("FAIL: pyyaml is required")
        raise SystemExit(1)
    return yaml.safe_load(REGISTRY.read_text())


def main() -> int:
    doc = _load()
    families = doc["families"]
    stage_names = doc["stages"]
    stage_values = set(doc["stage_values"])
    errors: list[str] = []

    # ── shape ───────────────────────────────────────────────────────────
    for name, row in families.items():
        stages = row.get("stages", {})
        missing = [s for s in stage_names if s not in stages]
        if missing:
            errors.append(f"{name}: missing stages {missing}")
        unknown = [s for s in stages if s not in stage_names]
        if unknown:
            errors.append(f"{name}: unknown stages {unknown}")
        bad = {s: v for s, v in stages.items() if v not in stage_values}
        if bad:
            errors.append(f"{name}: invalid stage values {bad}")
        if not row.get("role"):
            errors.append(f"{name}: missing role")
        if row.get("role") not in doc["roles"]:
            errors.append(f"{name}: unknown role {row['role']!r}")

    # ── enum reconciliation (TAX-6) ─────────────────────────────────────
    try:
        from veritx_dse.model.compile_model import TopologyFamily
        from veritx_dse.model.topology_artifact import MaterializedFamily
    except Exception as e:  # pragma: no cover
        print(f"FAIL: cannot import the enums: {e}")
        return 1

    decl = {f.value for f in TopologyFamily}
    mat = {f.value for f in MaterializedFamily}

    # Every declarable family must have a registry row that says AUTHORABLE=YES.
    for value in sorted(decl):
        row = families.get(value)
        if row is None:
            errors.append(
                f"TopologyFamily.{value} has no registry row — enum drift")
            continue
        if row["stages"]["AUTHORABLE"] != "YES":
            errors.append(
                f"TopologyFamily.{value} is declarable in code but the "
                f"registry says AUTHORABLE={row['stages']['AUTHORABLE']}")

    # Every materializable family must have a row that says MATERIALIZABLE=YES.
    for value in sorted(mat):
        row = families.get(value)
        if row is None:
            errors.append(
                f"MaterializedFamily.{value} has no registry row — enum drift")
            continue
        if row["stages"]["MATERIALIZABLE"] != "YES":
            errors.append(
                f"MaterializedFamily.{value} is materializable in code but "
                f"the registry says MATERIALIZABLE="
                f"{row['stages']['MATERIALIZABLE']}")

    # And the converse: nothing may claim a stage the code cannot honour.
    for name, row in families.items():
        if row["stages"]["AUTHORABLE"] == "YES" and name not in decl:
            errors.append(
                f"{name}: registry says AUTHORABLE=YES but the family is not "
                f"in TopologyFamily (declaration authority)")
        if row["stages"]["MATERIALIZABLE"] == "YES" and name not in mat:
            errors.append(
                f"{name}: registry says MATERIALIZABLE=YES but the family is "
                f"not in MaterializedFamily (materialization authority)")

    # ── TAX-1..TAX-4: the independence witnesses must actually hold ─────
    witnesses = {
        "TAX-1": ("RECOGNIZED", "AUTHORABLE"),
        "TAX-2": ("AUTHORABLE", "MATERIALIZABLE"),
        "TAX-3": ("MATERIALIZABLE", "AUTHORABLE"),
        "TAX-4": ("MATERIALIZABLE", "ROUTABLE"),
    }
    for tax, (a, b) in witnesses.items():
        found = any(
            row["stages"][a] == "YES" and row["stages"][b] != "YES"
            for row in families.values())
        if not found:
            errors.append(
                f"{tax} FAILS: no family has {a}=YES and {b}!=YES, so the "
                f"independence of {a} and {b} is unproven")

    # ── TAX-5: canonical id must not be a backend spelling ─────────────
    boundary = doc.get("backend_spelling_boundary", {})
    if not boundary.get("examples"):
        errors.append("TAX-5: backend_spelling_boundary.examples is empty")
    else:
        diff = [e for e in boundary["examples"]
                if e["canonical"] != e["booksim"]]
        if not diff:
            errors.append(
                "TAX-5: every example has canonical == booksim, so the "
                "boundary is not demonstrated")

    # ── materializer references must resolve ───────────────────────────
    import inspect
    import veritx_dse.model.topology_artifact as ta
    for name, row in families.items():
        ref = row.get("materializer")
        if not ref:
            continue
        fn = ref.split("(")[0].split(".")[-1]
        if not hasattr(ta, fn):
            errors.append(
                f"{name}: materializer {ref!r} does not resolve in "
                f"topology_artifact ({fn} missing)")

    # ── report ──────────────────────────────────────────────────────────
    if errors:
        print("topology-family registry INVALID:")
        for e in errors:
            print(f"  - {e}")
        return 1

    declared = sorted(decl)
    materialized = sorted(mat)
    print(
        f"topology-family registry valid: {len(families)} families, "
        f"{len(stage_names)} stages, registry_version="
        f"{doc['registry_version']}")
    print(f"  TopologyFamily      ({len(declared)}): {', '.join(declared)}")
    print(f"  MaterializedFamily  ({len(materialized)}): "
          f"{', '.join(materialized)}")
    unrec = sorted(set(declared) - set(materialized))
    extra = sorted(set(materialized) - set(declared))
    print(f"  declarable-not-materializable: {', '.join(unrec) or '(none)'}")
    print(f"  materializable-not-declarable: {', '.join(extra) or '(none)'}")
    print("  TAX-1..TAX-6: independence witnesses hold")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
