#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "tracks" / "t3-topology" / "dse"))

from veritx_dse.core.paths import REPO as CORE_REPO
from veritx_dse.model.agent_intent_v4 import (
    AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
)
from veritx_dse.model.compile_model import (
    AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
    CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
    WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.topology_intent import MeshIntent
from veritx_dse.product.project_top_rtl import run_rtl_slice


def slice_request() -> CompileRequestV4:
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),))
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI", clock_domain="noc_clk",
              power_domain="pd0"),
    )
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1, protocol=ProtocolFamily.AXI5,
                      ordering=OrderingMode.STRONG, max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=False, atomic=False),)),
        AgentIntentV4(2),
    )
    return CompileRequestV4(
        workload=workload, agents=agents,
        dependencies=DependencyGraph(()),
        topology=MeshIntent(side_length=2, concentration=1),
        address_map=AddressMap(ranges=(
            AddressRange(name="HBM0", base=0x1000, size=0x1000,
                         target_agent_idx=2),)),
        agent_intents=intents)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO / "runs" / "slice")
    parser.add_argument("--clean", action="store_true")
    args = parser.parse_args()

    if str(CORE_REPO.resolve()) != str(REPO.resolve()):
        print(f"WARNING: core REPO resolves to {CORE_REPO}, "
              f"script repo is {REPO}; proceeding with script repo")
    request = slice_request()
    expected_hash = request.design_hash()
    print(f"design_hash: {expected_hash}")

    if args.clean and args.out.exists():
        import shutil
        shutil.rmtree(args.out)
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        result = run_rtl_slice(request.to_dict(), args.out,
                               {"repo_root": str(REPO)})
    except Exception as exc:
        print(f"REPRODUCE FAILED: {type(exc).__name__}: {exc}")
        return 1

    manifest = json.loads((args.out / "project-top-manifest.json").read_text())
    problems = []
    if manifest.get("design_hash") != expected_hash:
        problems.append("design_hash mismatch vs pinned request")
    if manifest.get("scope") != "COMPOSED_SLICE":
        problems.append(f"scope is {manifest.get('scope')!r}, expected COMPOSED_SLICE")
    lint = manifest.get("lint", {})
    if lint.get("status") != "PASS":
        problems.append(f"lint status {lint.get('status')!r} (expected PASS; "
                        f"{lint.get('reason', lint.get('log', ''))[-200:]})")
    sim = manifest.get("sim", {})
    if sim.get("status") != "PASS":
        problems.append(f"sim status {sim.get('status')!r} (expected PASS)")
    if problems:
        for problem in problems:
            print(f"REPRODUCE FAILED: {problem}")
        return 1
    print(f"manifest: {args.out / 'project-top-manifest.json'}")
    print(f"lint: PASS (warnings={lint.get('warning_count')}, "
          f"clean={lint.get('clean')})")
    print(f"sim: PASS ({len(sim.get('scenarios', {}))} scenarios)")
    print(f"slice archive sha256: {result['archive_sha256']}")
    print("REPRODUCE OK — run scripts/verify_slice.sh to re-check hashes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
