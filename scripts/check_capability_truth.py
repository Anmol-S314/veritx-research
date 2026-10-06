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

# The registry-to-truth mapping lives in the registry itself: every family
# row declares `truth: [...]` naming the probed truth keys it describes.
# There is deliberately no second list here. A truth key no registry family
# claims is UNGATED (the exact failure a hardcoded list hid); a `truth:`
# entry naming no probed kind, or two families claiming one key, is a
# declaration error. An empty `truth: []` is allowed only for non-product
# roles (TEST_FIXTURE / BACKEND_ONLY): a family no probe can address must
# not be product-reachable by construction.
NON_PRODUCT_ROLES = ("TEST_FIXTURE", "BACKEND_ONLY")

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

    claimed: dict[str, str] = {}
    mapping: dict[str, list[str]] = {}
    for key, row in families.items():
        truth_keys = row.get("truth")
        if truth_keys is None:
            failures.append(
                f"{key}: registry family declares no `truth:` mapping — "
                "the checker cannot verify a family it cannot map")
            continue
        if not isinstance(truth_keys, list) or not all(
                isinstance(k, str) for k in truth_keys):
            failures.append(
                f"{key}: `truth:` must be a list of probed kind names")
            continue
        mapping[key] = truth_keys
        for k in truth_keys:
            if k not in truth:
                failures.append(
                    f"{key}: `truth:` names {k!r}, which capability truth "
                    "never probed — a dangling mapping")
                continue
            if k in claimed:
                failures.append(
                    f"{k}: claimed by both {claimed[k]!r} and {key!r} — "
                    "ambiguous ownership")
                continue
            claimed[k] = key
    for k in sorted(truth):
        if k not in claimed:
            failures.append(
                f"{k}: probed by capability truth but claimed by no "
                "registry family — UNGATED")

    for key, truth_keys in mapping.items():
        row = families[key]
        declared = row.get("stages") or {}
        if not truth_keys:
            role = row.get("role")
            if role not in NON_PRODUCT_ROLES:
                failures.append(
                    f"{key}: empty `truth:` with product role {role!r} — "
                    "a family no probe can address must not be "
                    "product-reachable by construction")
            report[key] = {"stages": {}, "unprobed": True,
                           "role": role}
            continue
        rows = [truth[k] for k in truth_keys if k in truth]
        if not rows:
            continue
        derived = rows[0] if len(rows) == 1 else _Aggregate(rows)
        per_family: dict[str, dict] = {}
        for stage in STAGES:
            if stage == "PRODUCT_WIRED":
                continue
            reg_value = str(declared.get(stage, "NO")).upper()
            live_value = derived.stages[stage]
            per_family[stage] = {"registry": reg_value, "live": live_value,
                                 "authority": derived.authority[stage]}
            if reg_value in _YES and live_value != "YES":
                failures.append(
                    f"{key}.{stage}: registry says {reg_value} but the "
                    f"implementation derives {live_value} — "
                    f"{derived.authority[stage]}")
        # WIRED is the registry's name for PRODUCT_WIRED. A full YES needs a
        # preset behind it; a PARTIAL needs at least a materialized fabric to
        # inspect — the inspectability floor. PARTIAL on an unmaterializable
        # family fails, so the word cannot be used to launder an overclaim.
        reg_wired = str(declared.get("WIRED", "NO")).upper()
        live_wired = derived.stages["PRODUCT_WIRED"]
        live_mat = derived.stages["MATERIALIZABLE"]
        wired_ok = (reg_wired not in _YES
                    or live_wired == "YES"
                    or (reg_wired == "PARTIAL" and live_mat == "YES"))
        per_family["PRODUCT_WIRED"] = {
            "registry": f"WIRED={reg_wired}", "live": live_wired,
            "authority": derived.authority["PRODUCT_WIRED"]
            + ("; PARTIAL accepted on the materialized-inspectable floor"
               if reg_wired == "PARTIAL" and live_wired != "YES" else ""),
        }
        if not wired_ok:
            failures.append(
                f"{key}.WIRED: registry says {reg_wired} but the "
                f"implementation derives PRODUCT_WIRED={live_wired} "
                f"(MATERIALIZABLE={live_mat}) — "
                f"{derived.authority['PRODUCT_WIRED']}")
        report[key] = {"stages": per_family,
                       "stopped_at_stage": derived.stopped_at_stage,
                       "profile_id": derived.profile_id,
                       "subfamilies": (
                           {k: {"stages": truth[k].stages,
                                "stopped_at_stage":
                                    truth[k].stopped_at_stage}
                            for k in truth_keys if k in truth}
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
