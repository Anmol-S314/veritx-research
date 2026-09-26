#!/usr/bin/env python3
"""Generate the deterministic compiled-inspector fixtures.

These are the semantic render inputs the Fabric Inspector consumes —
routers, channels, attachments, seats, occupancy — not pixel snapshots.
A fixture that asserts a coordinate is a fixture that fails when the
canonical topology changes, which is the point.

    python3 -m veritx_dse.tools.generate_compiled_fixtures [--check]

``--check`` regenerates in memory and fails if the committed bytes differ,
so a topology change cannot silently drift from the fixtures.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import replace
from pathlib import Path

# Runnable both as a script and as a module: make the package importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from veritx_dse.application.compile_intent import build_preset_request
from veritx_dse.application.compile_result_view import build_compile_result
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.preset_certification import _load_preset_doc
from veritx_dse.application.views import artifact_chain_view, topology_view
from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequestV3, NocConfig, TopologyFamily,
)

OUT = REPO / "tracks" / "t3-topology" / "dse" / "tests" / "fixtures" / "compiled"


def _cases() -> dict:
    """One request per topology case the inspector must render."""
    mesh4 = build_preset_request("mesh4_hbm")

    # 8x8 mesh: 64 routers, the boundary of the full-detail band.
    mesh8 = replace(
        mesh4,
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=64,
                      data_width=256, addr_width=64, protocol="AXI"),),
        # mesh4_hbm's address map targets an HBM group this case does not
        # declare, so the map goes with it.
        address_map=type(mesh4.address_map)(),
        noc_config=replace(mesh4.noc_config,
                           topology_family=TopologyFamily.MESH,
                           radix=8, concentration=1, link_width=256),
    )

    # Concentrated mesh: many agents per router (concentration 4).
    conc = CompileRequestV3.from_dict(
        _load_preset_doc("dense-4b-32tiles-conc4"))

    # Unused seats: a fabric larger than the workload.
    unused = CompileRequestV3.from_dict(
        _load_preset_doc("dense-1b-16tiles"))

    # Multiple agent kinds on one fabric.
    mixed = replace(
        mesh4,
        agents=(
            Agent(kind=AgentKind.COMPUTE_TILE, count=4, data_width=256,
                  addr_width=64, protocol="AXI"),
            Agent(kind=AgentKind.HBM_CONTROLLER, count=1, addr_width=64),
            Agent(kind=AgentKind.NIC, count=1, addr_width=64),
            Agent(kind=AgentKind.PERIPHERAL, count=1, addr_width=64),
        ),
        noc_config=replace(mesh4.noc_config,
                           topology_family=TopologyFamily.MESH,
                           radix=3, concentration=1, link_width=256),
    )
    return {
        "mesh4": mesh4,
        "mesh8x8": mesh8,
        "concentrated": conc,
        "unused-seats": unused,
        "mixed-agents": mixed,
    }


def build(case: str, request) -> dict:
    compilation = FabricCompiler().compile(request)
    if compilation.status != "COMPILED":
        raise SystemExit(f"{case}: does not compile ({compilation.status}: "
                         f"{compilation.error})")
    revision = {
        "revision_id": f"fixture-{case}",
        "display_name": case,
        "created_at": "2026-09-26T00:00:00Z",
        "design_hash": request.design_hash(),
        "compilation": {
            "compiler_semantics_version": request.compiler_semantics_version,
            "resolved_fabric_hash":
                compilation.bundle.root_hashes()["resolved_fabric_hash"],
        },
        "certificate": {
            "certificate_id": compilation.certificate.certificate_id()},
    }
    result = build_compile_result(
        revision, compilation,
        topology_view(compilation, revision_id=revision["revision_id"]),
        artifact_chain_view(compilation))
    return {
        "case": case,
        "fabric": result["groups"]["fabric"],
        "mapping": result["groups"]["mapping"],
        "routing": {
            "routing_classes": result["groups"]["routing"]["routing_classes"],
            "default_class": result["groups"]["routing"]["default_class"],
            "entry_count": result["groups"]["routing"]["entry_count"],
            "observation": result["groups"]["routing"]["observation"],
        },
        "resources": result["groups"]["resources"],
        "certificate": result["certificate"],
    }


def main(argv) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="fail if the committed fixtures differ")
    args = parser.parse_args(argv)

    OUT.mkdir(parents=True, exist_ok=True)
    failures = []
    for case, request in _cases().items():
        payload = build(case, request)
        text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
        path = OUT / f"{case}.json"
        if args.check:
            if not path.is_file() or path.read_text() != text:
                failures.append(case)
            continue
        path.write_text(text)
        print(f"wrote {path.relative_to(REPO)}")
    if failures:
        print(f"COMPILED FIXTURES DRIFTED: {failures}", file=sys.stderr)
        return 1
    if args.check:
        print(f"compiled fixtures current ({len(_cases())} cases)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
