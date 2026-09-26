#!/usr/bin/env python3
"""Fail-closed gate for shipped-preset certification (Gate 6 §86/§87).

A preset may only advertise a capability envelope whose own conditions it
satisfies. The exposure registry states the *claim*; this gate proves it
against the canonical compilation, so a claim that its own envelope refutes
cannot ship.

It refuses:

  * a preset whose ``guided_eligible: true`` claim has a FAILING required
    condition of its advertised envelope (INVALID);
  * a Guided claim resting on a condition only an execution can decide
    (UNCERTIFIED — fail closed, never assumed);
  * a Guided claim that names no envelope;
  * no proven Guided-safe preset at all (GUIDED SAFE PATH BLOCKED).

Exit codes:

  0  every Guided claim is proven and the safe path exists
  1  a claim is unproven, refuted, or the safe path is missing

Usage:
    python3 scripts/check_preset_certification.py
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DSE = REPO_ROOT / "tracks" / "t3-topology" / "dse"
sys.path.insert(0, str(DSE))


def main(argv: list[str]) -> int:
    from veritx_dse.application import preset_certification as pc  # noqa: PLC0415
    from veritx_dse.application import product_registry as registry  # noqa: PLC0415
    from veritx_dse.application.fabric_compiler import (  # noqa: PLC0415
        FabricCompiler,
    )
    from veritx_dse.model.compile_model import (  # noqa: PLC0415
        CompileRequest, CompileRequestV3,
    )

    registry.clear_cache()
    preset_ids = sorted(registry.exposure_document().get("presets") or {})
    errors: list[str] = []
    rows: list[dict] = []

    for preset_id in preset_ids:
        doc = pc._load_preset_doc(preset_id)
        compilation = None
        if doc:
            request = (CompileRequestV3.from_dict(doc)
                       if doc.get("schema_version") == 3
                       else CompileRequest.from_dict(doc))
            compilation = FabricCompiler().compile(request)
        row = pc.certify(preset_id, doc, compilation)
        rows.append(row)
        if row["state"] == pc.INVALID:
            errors.append(f"{preset_id}: {row['reason']}")
        elif row["state"] == pc.UNCERTIFIED and row["claimed_guided_eligible"]:
            errors.append(f"{preset_id}: {row['reason']}")

    guided = [r["preset_id"] for r in rows if r["state"] == pc.GUIDED_SAFE]
    if not guided:
        errors.append(
            "GUIDED SAFE PATH BLOCKED - no shipped preset is proven to reach "
            "its advertised envelope")

    if errors:
        print(f"PRESET CERTIFICATION INVALID — {len(errors)} problem(s):")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(f"preset certification valid: {len(rows)} shipped presets")
    for row in rows:
        marker = "PROVEN" if row["state"] == pc.GUIDED_SAFE else row["state"]
        print(f"  {row['preset_id']:26s} {marker:10s} "
              f"{row['envelope'] or '(no static envelope)'}")
    print(f"guided safe path: {', '.join(guided)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
