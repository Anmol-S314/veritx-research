#!/usr/bin/env python3
"""Capability truth gate — the descriptive registry may not outrun the code.

`docs/product/topology-family-registry.yaml` claims stages. This gate derives
the SAME stages by asking the actual compiler and backend profile selector
(`veritx_dse.application.capability_truth`) and FAILS if the registry claims a
stage the implementation cannot produce.

Why it exists: the registry marked CONCENTRATED_MESH PROJECTABLE/EXECUTABLE/
QUALIFIED = YES while `select_booksim_profile()` has exactly two profiles — a
native mesh-DOR profile guarded on `family is MaterializedFamily.MESH`, and
the AnyNet profile, which requires ANYNET_MIN_HOPS. Concentrated mesh is
CONCENTRATED_MESH and routes DOR_XY, so it satisfies NEITHER. The registry was
describing an intention, not a fact.

    python3 scripts/check_capability_truth.py [--json]

A registry YES with no implementation authority is a FAILURE, not a warning.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSE = REPO / "tracks" / "t3-topology" / "dse"
REGISTRY = REPO / "docs" / "product" / "topology-family-registry.yaml"

sys.path.insert(0, str(DSE))

_FAMILY_KEY: dict[str, tuple[str, ...]] = {
    "mesh": ("mesh",),
    "concentrated_mesh": ("concentrated_mesh",),
    "torus": ("torus",),
    "flatfly": ("flatfly",),
    "fat_tree": ("fattree",),
    "gec": ("gec_mesh", "gec_express", "gec_multidrop", "gec_hybrid"),
    "custom": ("explicit",),
}

class _Aggregate:
    """A conservative view over several truth rows (see _FAMILY_KEY)."""

    def __init__(self, rows: list) -> None:
        self.rows = rows
        self.stages = {
            stage: ("YES" if all(r.stages[stage] == "YES" for r in rows)
                    else "NO")
            for stage in STAGES
        }
        self.authority = {
            stage: self._why(stage) for stage in STAGES
        }
        self.stopped_at_stage = next(
            (r.stopped_at_stage for r in rows if r.stopped_at_stage), None)
        self.profile_id = next((r.profile_id for r in rows if r.profile_id),
                               None)

    def _why(self, stage: str) -> str:
        if self.stages[stage] == "YES":
            return ("all subfamilies derive YES: " + "; ".join(
                f"{r.family}={r.stages[stage]}" for r in self.rows))
        bad = [f"{r.family}={r.stages[stage]}" for r in self.rows
               if r.stages[stage] != "YES"]
        return ("CONSERVATIVE NO — not every subfamily derives YES: "
                + "; ".join(bad))

STAGES = ("AUTHORABLE", "MATERIALIZABLE", "ROUTABLE", "VERIFIABLE",
          "PROJECTABLE", "EXECUTABLE", "QUALIFIED", "PRODUCT_WIRED")

_YES = {"YES", "PARTIAL"}

def load_registry() -> dict:
    import yaml
    return yaml.safe_load(REGISTRY.read_text())

def check() -> tuple[list[str], dict]:
    """Return (failures, report)."""
    from veritx_dse.application.capability_truth import derive_all_stages

    truth = derive_all_stages()
    registry = load_registry()
    families = registry.get("families") or {}
    failures: list[str] = []
    report: dict[str, dict] = {}

    for key, truth_keys in _FAMILY_KEY.items():
        row = families.get(key)
        if row is None:
            failures.append(f"registry has no family {key!r}")
            continue
        missing = [k for k in truth_keys if k not in truth]
        if missing:
            failures.append(
                f"{key}: capability truth has no row for {missing} — a "
                "topology kind without a derived row is UNGATED")
            continue
        declared = row.get("stages") or {}
        rows = [truth[k] for k in truth_keys]
        derived = rows[0] if len(rows) == 1 else _Aggregate(rows)
        per_family: dict[str, dict] = {}
        for stage in STAGES:
            reg_value = str(declared.get(stage, "NO")).upper()
            live_value = derived.stages[stage]
            per_family[stage] = {"registry": reg_value, "live": live_value,
                                 "authority": derived.authority[stage]}
            if reg_value in _YES and live_value != "YES":
                failures.append(
                    f"{key}.{stage}: registry says {reg_value} but the "
                    f"implementation derives {live_value} — "
                    f"{derived.authority[stage]}")
        report[key] = {"stages": per_family,
                       "stopped_at_stage": derived.stopped_at_stage,
                       "profile_id": derived.profile_id,
                       "subfamilies": (
                           {k: {"stages": truth[k].stages,
                                "stopped_at_stage":
                                    truth[k].stopped_at_stage}
                            for k in truth_keys}
                           if len(truth_keys) > 1 else None)}
    return failures, report

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", action="store_true",
                    help="emit the derived truth as JSON")
    args = ap.parse_args()

    failures, report = check()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    if failures:
        print("CAPABILITY TRUTH VIOLATIONS — the registry claims stages the "
              "implementation cannot produce:", file=sys.stderr)
        for f in failures:
            print(f"  - {f}", file=sys.stderr)
        return 1
    print(f"capability truth: {len(report)} families, registry matches the "
          "implementation")
    return 0

if __name__ == "__main__":
    sys.exit(main())
