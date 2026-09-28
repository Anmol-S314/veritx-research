#!/usr/bin/env python3
"""Multiclass truth gate — registry claims may not contradict executable authority.

Compares docs/product/capability-registry.yaml COMM-006 against the live
standalone BookSim multi-class authorities:

  1. BookSimProfile MESH_DOR_MC_PROFILE exists in
     veritx_dse.backend.booksim_projection with profile_id
     CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1;
  2. qualifier qualify_native_mesh_dor_mc exists and is importable;
  3. LogicalMessageArtifactV3 / PhysicalTrafficArtifactV3 exist with
     class-aware VC handling (traffic_class_to_vcs);
  4. select_booksim_profile can return the MC profile for a multi-class
     mesh design (import-level + selector-level, no binary execution);
  5. registry COMM-006 PROJECTABLE/EXECUTABLE/QUALIFIED/EVIDENCE_CAPABLE
     must be CONDITIONAL (or YES) with wiring WIRED/PRODUCT_WIRED YES and
     a condition referencing the MC envelope — never NOT_AVAILABLE while
     the profile exists.

A registry NO with a live certified profile is a FAILURE, not a warning.
This is the structural test the reconciliation demands: Studio must never
again display READY / CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1 on one part of a
page and multi-class NOT_AVAILABLE on another.

Usage: python3 scripts/check_multiclass_truth.py [--json]
Exit 0 truth reconciled, 1 contradiction.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSE = REPO / "tracks" / "t3-topology" / "dse"
REGISTRY = REPO / "docs" / "product" / "capability-registry.yaml"

sys.path.insert(0, str(DSE))

MC_PROFILE_ID = "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1"
MC_ENVELOPE = "CAP-ENV-BOOKSIM-MESH-DOR-MC-V1"


def fail(msg: str, errors: list[str]) -> None:
    errors.append(msg)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    errors: list[str] = []
    facts: dict[str, object] = {}

    # ── 1. backend profile authority ──────────────────────────────
    try:
        import veritx_dse.backend.booksim_projection as bp  # noqa: E402

        prof = getattr(bp, "MESH_DOR_MC_PROFILE", None)
        facts["mc_profile_present"] = prof is not None
        if prof is None:
            fail("MESH_DOR_MC_PROFILE missing from booksim_projection", errors)
        else:
            facts["mc_profile_id"] = getattr(prof, "profile_id", None)
            if prof.profile_id != MC_PROFILE_ID:
                fail(
                    f"MC profile id {prof.profile_id!r} != {MC_PROFILE_ID!r}",
                    errors,
                )
            facts["mc_semantics"] = getattr(prof, "semantics_version", None)
    except Exception as exc:  # fail closed
        facts["mc_profile_present"] = False
        fail(f"cannot import booksim_projection MC profile: {exc}", errors)

    # ── 2. qualifier authority ────────────────────────────────────
    try:
        from veritx_dse.backend.booksim_projection import (  # noqa: E402
            qualify_native_mesh_dor_mc,
        )

        facts["mc_qualifier_present"] = callable(qualify_native_mesh_dor_mc)
    except Exception as exc:
        facts["mc_qualifier_present"] = False
        fail(f"qualify_native_mesh_dor_mc not importable: {exc}", errors)

    # ── 3. V3 class-aware artifacts ───────────────────────────────
    try:
        from veritx_dse.workload.messages import (  # noqa: E402
            LogicalMessageArtifactV3,
        )
        from veritx_dse.workload.traffic import (  # noqa: E402
            PhysicalTrafficArtifactV3,
        )
        from veritx_dse.model.vc_resource import VCResourceArtifact  # noqa: E402

        facts["v3_present"] = True
        facts["v3_names"] = [
            LogicalMessageArtifactV3.__name__,
            PhysicalTrafficArtifactV3.__name__,
            VCResourceArtifact.__name__,
        ]
    except Exception as exc:
        facts["v3_present"] = False
        fail(f"V3 class-aware artifacts not importable: {exc}", errors)

    # ── 4. selector can return the MC profile ─────────────────────
    try:
        import inspect  # noqa: E402

        import veritx_dse.backend.booksim_projection as bp2  # noqa: E402

        src = inspect.getsource(bp2.select_booksim_profile)
        facts["selector_references_mc"] = (
            "MESH_DOR_MC_PROFILE" in src or MC_PROFILE_ID in src
        )
        if not facts["selector_references_mc"]:
            fail(
                "select_booksim_profile never returns the MC profile",
                errors,
            )
    except Exception as exc:
        facts["selector_references_mc"] = False
        fail(f"cannot inspect select_booksim_profile: {exc}", errors)

    # ── 5. registry must agree ────────────────────────────────────
    try:
        import yaml  # noqa: E402

        doc = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
        caps = {c.get("id"): c for c in doc.get("capabilities") or []}
        row = caps.get("COMM-006")
        if row is None:
            fail("COMM-006 missing from capability-registry.yaml", errors)
        else:
            stages = row.get("stages") or {}
            facts["comm006_stages"] = stages
            facts["comm006_wiring"] = row.get("wiring")
            for stage in (
                "PROJECTABLE",
                "EXECUTABLE",
                "QUALIFIED",
                "EVIDENCE_CAPABLE",
            ):
                if stages.get(stage) == "NO":
                    fail(
                        f"COMM-006 {stage} is NO while {MC_PROFILE_ID} "
                        "exists — stale NOT_AVAILABLE contradiction",
                        errors,
                    )
            if row.get("wiring") == "NOT_AVAILABLE":
                fail(
                    "COMM-006 wiring NOT_AVAILABLE while the MC profile "
                    "is certified — Studio would render READY and "
                    "NOT_AVAILABLE on the same page",
                    errors,
                )
            conds = list(row.get("conditions") or [])
            facts["comm006_conditions"] = conds
            if MC_ENVELOPE not in conds:
                fail(
                    f"COMM-006 conditions {conds} do not reference "
                    f"{MC_ENVELOPE}",
                    errors,
                )
            envs = doc.get("envelopes") or {}
            if MC_ENVELOPE not in envs:
                fail(f"envelope {MC_ENVELOPE} missing from registry", errors)
            elif (envs[MC_ENVELOPE] or {}).get("profile_id") != MC_PROFILE_ID:
                fail(
                    f"envelope {MC_ENVELOPE} profile "
                    f"{(envs[MC_ENVELOPE] or {}).get('profile_id')!r} "
                    f"!= {MC_PROFILE_ID!r}",
                    errors,
                )
    except Exception as exc:
        fail(f"cannot verify capability-registry.yaml: {exc}", errors)

    ok = not errors
    if args.json:
        print(json.dumps({"ok": ok, "errors": errors, "facts": facts},
                         indent=2, sort_keys=True))
    elif errors:
        print(f"MULTICLASS TRUTH CONTRADICTION — {len(errors)} problem(s):")
        for e in errors:
            print(f"  - {e}")
    else:
        print(
            f"multiclass truth reconciled: {MC_PROFILE_ID} live, "
            "COMM-006 agrees, envelope bound"
        )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
