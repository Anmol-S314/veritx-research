#!/usr/bin/env python3
from __future__ import annotations
import argparse
import hashlib
import json
import os
import subprocess
import sys
import shutil
import urllib.request
from dataclasses import replace
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DSE = REPO / "tracks" / "t3-topology" / "dse"
sys.path.insert(0, str(DSE))
os.environ["PYTHONPATH"] = f"{DSE}:{DSE / 'tests'}{os.pathsep}{os.environ.get('PYTHONPATH', '')}"

FAMILY_REQUESTS = {
    "mesh": ("mesh8x8", "MeshIntent", {"side_length": 8, "concentration": 1}),
    "torus": ("torus", "TorusIntent", {"side_length": 3, "concentration": 1}),
    "concentrated_mesh": ("cmesh", "ConcentratedMeshIntent", {"side_length": 4, "concentration": 4}),
    "ring": ("ring", "RingIntent", {"router_count": 64}),
    "fly": ("fly", "FlyIntent", {"radix": 4, "levels": 3}),
    "qtree": ("qtree", "QTreeIntent", {"radix": 4, "levels": 3}),
    "tree4": ("tree4", "Tree4Intent", {"radix": 4, "levels": 3}),
    "flatfly": ("flatfly", "FlatFlyIntent", {"radix_per_dimension": 4, "dimension_count": 2, "concentration": 1}),
    "fattree": ("fattree", "FatTreeIntent", {"switch_radix": 4, "level_count": 2}),
    "dragonflynew": ("dragonfly", "StructuredTopologyIntent", {"family": "dragonfly", "params": {"radix": 6, "group_count": 6}}),
    "gec_mecs": ("gec_mecs", "GecTopologyIntent", {"mode": "MULTIDROP", "grid_side_length": 4, "concentration": 1, "express_channel_groups_per_dimension": 1, "destinations_per_express_channel": 3}),
    "gec_hybrid": ("gec_hybrid", "GecTopologyIntent", {"mode": "HYBRID", "grid_side_length": 4, "concentration": 1, "express_channel_groups_per_dimension": 1, "destinations_per_express_channel": 3}),
    "kncube": ("kncube", "StructuredTopologyIntent", {"family": "kncube", "params": {"radix": 3, "dimensions": 2, "wrap": True}}),
}
FAMILIES14 = (
    "mesh", "torus", "concentrated_mesh", "ring", "gec_mecs", "fly", "qtree",
    "tree4", "flatfly", "srota", "gec_hybrid", "fattree", "dragonflynew", "kncube")

SROTA_KWARGS = dict(
    side_length=4, concentration=1, mecs_row=True, mecs_col=True,
    drop_latency=1, planes=frozenset({"d"}), island_columns=(1,),
    path_shapes=frozenset({"row", "column"}), vc_policy="shape",
    sidebuf_enable=False, sidebuf_watermark=None, tel_period=4, tel_latency=8)


def canonical_bytes(doc: object) -> bytes:
    return json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()


def sha_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def git_head() -> tuple[str | None, bool]:
    try:
        head = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10).stdout.strip()
        dirty = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"],
            capture_output=True, text=True, timeout=20).stdout.strip()
        return head or None, bool(dirty)
    except Exception:
        return None, True


# Paths that REMAINING-WORK.md records as an explicit non-goal: unreviewed
# scratch that is never committed and cannot reach a measured stage. They are
# listed in the source tree only because moving them is not authorised, so
# counting them as "dirty" made `tree_dirty` permanently true -- which is
# exactly what the two runs cited as clean-tree evidence record. That made the
# field useless: a reader could not tell a genuinely dirty source tree from a
# repo carrying screenshots. The scoping below keeps the whole-tree signal and
# adds a source-only signal that pinned evidence can actually key on.
NON_GOAL_UNTRACKED = (
    ".codex/",
    ".impeccable/",
    ".pi/",
    "audit/",
    "test-results/",
    ".playwright-mcp/",
    "calculator.html",
    "calculator.py",
    "test_calculator.py",
)
NON_GOAL_UNTRACKED_SUFFIXES = (".png",)


def _is_non_goal_path(path: str) -> bool:
    if path.startswith(NON_GOAL_UNTRACKED):
        return True
    return path.endswith(NON_GOAL_UNTRACKED_SUFFIXES)


def source_dirty() -> tuple[bool, list[str]]:
    """Dirt that can reach a measured stage: tracked edits, plus untracked
    files that are not a declared non-goal.

    A tracked modification is always dirty, whatever its path: it means the
    bytes measured are not the bytes committed. Untracked files are dirty
    unless the repository has explicitly recorded them as excluded scratch.
    """
    try:
        porcelain = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain", "-uall"],
            capture_output=True, text=True, timeout=30).stdout
    except Exception:
        return True, ["<git status failed>"]
    paths = []
    for line in porcelain.splitlines():
        if len(line) < 4:
            continue
        status, path = line[:2], line[3:]
        if status.strip() == "??" and _is_non_goal_path(path):
            continue
        paths.append(f"{status.strip() or '??'} {path}")
    return bool(paths), paths


def sha_file(path: Path) -> str | None:
    try:
        return sha_bytes(path.read_bytes())
    except Exception:
        return None


def log_artifacts(directory: Path, root: Path) -> list[dict]:
    artifacts = []
    for path in sorted(directory.rglob("*.log")):
        if path.is_file():
            artifacts.append({
                "path": str(path.relative_to(root)),
                "bytes": path.stat().st_size,
                "sha256": sha_file(path),
            })
    return artifacts


def new_manifest(args) -> dict:
    head, dirty = git_head()
    src_dirty, src_paths = source_dirty()
    return {
        "contract_version": 1,
        "runner": "scripts/complete_design.py",
        "git_head": head,
        "tree_dirty": dirty,
        "source_dirty": src_dirty,
        "source_dirty_paths": src_paths,
        "platform": args.platform,
        "release": bool(args.release),
        "stages": [],
        "blockers": [],
        "artifacts": {},
        "scope_note": "",
    }


def record_stage(manifest, out: Path, name: str, cmd, rc: int, status: str,
                 log: Path | None = None, extra: dict | None = None) -> bool:
    stage = {
        "stage": name,
        "command": " ".join(str(part) for part in cmd) if isinstance(cmd, (list, tuple)) else str(cmd),
        "exit_code": rc,
        "status": status,
    }
    if log is not None:
        stage["log"] = str(log)
        stage["log_sha256"] = sha_file(log)
    if extra:
        stage.update(extra)
    manifest["stages"].append(stage)
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return status == "PASS"


def load_live_request(project: str, gateway: str, revision: str | None) -> dict:
    route = (f"/api/v1/revisions/{revision}" if revision is not None
             else f"/api/v1/projects/{project}/draft")
    with urllib.request.urlopen(f"{gateway.rstrip('/')}{route}", timeout=30) as response:
        payload = json.load(response)
    if revision is not None:
        if payload.get("project_id") != project or payload.get("revision_id") != revision:
            raise SystemExit("gateway revision identity does not match requested project/revision")
        request = payload.get("design")
        if not isinstance(request, dict):
            raise SystemExit(f"gateway revision {revision} carries no design object")
        from veritx_dse.model.compile_request_v4 import CompileRequestV4
        try:
            actual_hash = CompileRequestV4.from_dict(request).design_hash()
        except Exception as exc:
            raise SystemExit(f"gateway revision {revision} has invalid design: {exc}") from exc
        if payload.get("design_hash") != actual_hash:
            raise SystemExit(f"gateway revision {revision} design hash does not match saved design")
    else:
        request = payload.get("request")
        if not isinstance(request, dict):
            raise SystemExit(f"gateway draft for project {project} carries no request object")
    return request


def make_family_request(family: str):
    from veritx_dse.model.compile_model import (
        AddressMap, AddressRange, Agent, AgentKind, CollectiveDimension,
        CollectiveIntent, CollectiveKind, DependencyGraph, ModelFamily,
        PhysicalContext, TrafficProfile, WorkloadV3,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model import topology_intent as ti
    from veritx_dse.model.srota_intent import SrotaIntent
    from veritx_dse.model.agent_intent_v4 import (
        AgentIntentV4, OrderingMode, PermissionWindow, ProtocolFamily,
    )

    if family == "srota":
        topology = SrotaIntent(**SROTA_KWARGS)
    else:
        _name, constructor, kwargs = FAMILY_REQUESTS[family]
        built = {}
        for key, value in kwargs.items():
            if family == "gec_mecs" or family == "gec_hybrid":
                built[key] = getattr(ti.GecMode, value) if key == "mode" else value
            else:
                built[key] = value
        topology = getattr(ti, constructor)(**built)
    workload = WorkloadV3(
        model_family=ModelFamily.DENSE_TRANSFORMER, tp=2, pp=1, ep=1, dp=1,
        collectives=(CollectiveIntent(
            kind=CollectiveKind.ALLREDUCE, dimension=CollectiveDimension.TP,
            payload_bytes=8192, traffic_class="tp_collective"),),
        traffic_profiles=(TrafficProfile(
            src_rank=0, dst_rank=1, traffic_class="tp_collective",
            payload_bytes=64),))
    agents = (
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI",
              clock_domain="noc_clk", power_domain="pd0"),
        Agent(kind=AgentKind.COMPUTE_TILE, count=1, data_width=32,
              addr_width=64, protocol="AXI",
              clock_domain="noc_clk", power_domain="pd0"),
        Agent(kind=AgentKind.HBM_CONTROLLER, count=1, data_width=32,
              addr_width=64, protocol="AXI",
              clock_domain="noc_clk", power_domain="pd0"))
    intents = (
        AgentIntentV4(0, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG,
                      max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=True, atomic=False),)),
        AgentIntentV4(1, protocol=ProtocolFamily.AXI5, ordering=OrderingMode.STRONG,
                      max_outstanding=4,
                      permission_windows=(PermissionWindow(
                          "HBM0", readable=True, writable=False, atomic=False),)),
        AgentIntentV4(2))
    return CompileRequestV4(
        workload=workload, agents=agents, dependencies=DependencyGraph(()),
        topology=topology,
        address_map=AddressMap(ranges=(AddressRange(
            name="HBM0", base=0x1000, size=0x1000, target_agent_idx=2),)),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
        agent_intents=intents)


def compile_request(doc: dict):
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.application.fabric_compiler import FabricCompiler
    request = CompileRequestV4.from_dict(doc)
    compilation = FabricCompiler().compile(request)
    return request, compilation


def hardware_family_for_request(request) -> str:
    from veritx_dse.product.project_top_rtl import _family_id_from_topology

    family = _family_id_from_topology(request.topology)
    if family is None:
        kind = getattr(request.topology, "kind", type(request.topology).__name__)
        raise ValueError(f"UNSUPPORTED_COMPLETION_FAMILY: no exact hardware family for {kind!r}")
    return family


def generate_hardware(request, family: str, out: Path) -> dict:
    actual_family = hardware_family_for_request(request)
    if family != actual_family:
        raise ValueError(
            f"hardware family mismatch: request resolves to {actual_family!r}, "
            f"runner supplied {family!r}")
    doc = request.to_dict()
    config = {"repo_root": str(REPO)}
    if family in ("gec_mecs", "gec_hybrid", "srota"):
        from veritx_dse.product import project_top_rtl
        runner = {"gec_mecs": project_top_rtl.run_composed_family,
                  "gec_hybrid": project_top_rtl.run_hybrid_shared,
                  "srota": project_top_rtl.run_srota_shared}[family]
        result = runner(doc, out, config)
        return result
    from veritx_dse.product import project_top_rtl
    try:
        return project_top_rtl.run_rtl_slice(doc, out, config)
    except Exception as exc:
        message = str(exc)
        if "UNSUPPORTED_SLICE_PROFILE" not in message:
            raise
        result = project_top_rtl.run_composed_family(doc, out, config)
        result["slice_refusal"] = message
        return result


def release_matrix(manifest, out: Path) -> None:
    from veritx_dse.product import project_top_rtl
    from veritx_dse.application.fabric_compiler import FabricCompiler
    failures = []
    for family in FAMILIES14:
        family_out = out / family
        family_out.mkdir(parents=True, exist_ok=True)
        try:
            request = make_family_request(family)
            compiled = FabricCompiler().compile(request)
            if compiled.status != "COMPILED":
                failures.append(family)
                manifest["stages"].append({
                    "stage": f"family:{family}", "status": "FAIL",
                    "exit_code": 1, "family": family,
                    "detail": compiled.error or "not COMPILED"})
                continue
            family_doc = request.to_dict()
            config = {"repo_root": str(REPO)}
            if family in ("gec_mecs", "gec_hybrid", "srota"):
                runner = {"gec_mecs": project_top_rtl.run_composed_family,
                          "gec_hybrid": project_top_rtl.run_hybrid_shared,
                          "srota": project_top_rtl.run_srota_shared}[family]
                result = runner(family_doc, family_out, config)
            else:
                result = project_top_rtl.run_composed_family(family_doc, family_out, config)
            family_status = hardware_evidence_status(result)
            manifest["stages"].append({
                "stage": f"family:{family}",
                "status": family_status,
                "exit_code": 0 if family_status == "PASS" else 1,
                "family": family,
                "lint": result.get("lint"),
                "sim": result.get("sim"),
                "scenarios": result.get("scenarios"),
                "logs": log_artifacts(family_out, out),
                "development_milestone": result.get("development_milestone", True),
            })
            if family == "kncube" and family_status == "PASS":
                manifest["blockers"].append({
                    "code": "KNCUBE_NATIVE_EQUIVALENCE_UNVERIFIED",
                    "detail": "composed RTL for a general KNCube request (radix/dimensions/wrap) "
                              "lints and simulates; equivalence against the external Constellation "
                              "KNCube source is UNVERIFIED because that source is operator-owned and "
                              "absent; no torus substitute is used"})
            if family_status != "PASS":
                failures.append(family)
        except Exception as exc:
            failures.append(family)
            error_log = family_out / "runner-error.log"
            error_log.write_text(f"{type(exc).__name__}: {exc}\n")
            manifest["stages"].append({
                "stage": f"family:{family}", "status": "FAIL",
                "exit_code": 1, "family": family,
                "detail": str(exc)[:600],
                "logs": log_artifacts(family_out, out)})
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if failures:
        manifest["blockers"].append({
            "code": "FAMILY_MATRIX_FAILED",
            "detail": ("families without passing lint, simulation, and nonempty "
                       f"all-true scenarios: {sorted(failures)}")})
    rows = []
    for stage in manifest["stages"]:
        if stage["stage"].startswith("family:"):
            family = stage["family"]
            status = stage["status"]
            scenarios = stage.get("scenarios") or {}
            rows.append((family, status, len(scenarios) if scenarios else 0))
    rows.sort(key=lambda row: (row[1] != "PASS", row[0]))
    width = max(len(row[0]) for row in rows) if rows else 1
    for family, status, count in rows:
        print(f"  {family:<{width}}  {status}" + (f"  ({count} scenarios)" if count else ""), flush=True)


def kncube_lint_and_sim(params, topology, out: Path) -> dict:
    from veritx_dse.product import project_top_rtl
    if (project_top_rtl._family_id_from_topology(topology) != "kncube"
            or getattr(params, "family", None) != "kncube"):
        raise ValueError(project_top_rtl.KNCUBE_BLOCKER + ": refusing a non-KNCube source topology")
    dut_files = ["noc_pkg.sv", "router.sv", "noc_top.sv",
                 "addr_decode.sv", "ordering_fsm.sv"]
    for initiator in params.initiators:
        dut_files.append(f"adapter_axi5_g{initiator.group_idx}.sv")
    dut_files += ["cdc_bypass.sv", "destination_adapter.sv", "project_top.sv"]
    out.mkdir(parents=True, exist_ok=True)
    preview_doc = None
    fab_files = project_top_rtl.build_family_router(params, topology)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "rtl"
    target.mkdir(parents=True, exist_ok=True)
    for name, content in fab_files.items():
        (target / name).write_text(content)
    (target / "cdc_bypass.sv").write_text(project_top_rtl.render_cdc_bypass())
    (target / "destination_adapter.sv").write_text(project_top_rtl.render_destination_adapter(params))
    (target / "project_top.sv").write_text(project_top_rtl.render_family_project_top(params))
    (target / "tb_project_top.sv").write_text(project_top_rtl.render_family_tb(params))
    tb_files = list(dict.fromkeys(dut_files)) + ["tb_project_top.sv"]
    lint, _ = project_top_rtl._run_logged(
        [shutil.which("verilator") or "verilator", "--lint-only", "-sv", "-Wall",
         "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "--top-module", "project_top", *list(dict.fromkeys(dut_files))],
        cwd=target, timeout=300, log_path=target / "logs" / "verilator-lint.log")
    build, _ = project_top_rtl._run_logged(
        [shutil.which("verilator") or "verilator", "--binary", "--timing", "-Wall",
         "-Wno-fatal", "-Wno-WIDTH", "-Wno-PINNOTFOUND", "-Wno-UNOPTFLAT",
         "-Wno-DECLFILENAME", "--top-module", "tb_project_top",
         "--Mdir", "obj_kncube", *tb_files],
        cwd=target, timeout=600, log_path=target / "logs" / "verilator-build.log")
    transcript = ""
    if build.returncode == 0:
        run, transcript = project_top_rtl._run_logged(
            ["./obj_kncube/Vtb_project_top"], cwd=target, timeout=180,
            log_path=target / "logs" / "verilator-sim.log")
    (target / "kncube-sim.log").write_text(transcript)
    return {
        "scope": "COMPOSED_FAMILY",
        "family": "kncube",
        "lint": "PASS" if lint.returncode == 0 else "FAIL",
        "sim": "PASS" if (build.returncode == 0 and "status: PASS" in transcript) else "FAIL",
        "development_milestone": True,
        "final_implementation": False,
    }


def evidence_status(value) -> str | None:
    if isinstance(value, str):
        return value.upper()
    if isinstance(value, dict) and isinstance(value.get("status"), str):
        return value["status"].upper()
    return None


def hardware_evidence_status(result: dict) -> str:
    verdicts = [evidence_status(result.get(key)) for key in ("lint", "sim")]
    if any(verdict == "FAIL" for verdict in verdicts):
        return "FAIL"
    if any(verdict != "PASS" for verdict in verdicts):
        return "BLOCKED"
    scenarios = result.get("scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        return "BLOCKED"
    if any(value is not True for value in scenarios.values()):
        return "FAIL"
    return "PASS"


def completion_result(stages: list[dict], blockers: list[dict]) -> str:
    statuses = [stage["status"] for stage in stages]
    if "FAIL" in statuses:
        return "FAIL"
    if "BLOCKED" in statuses:
        return "BLOCKED"
    if "NOT_RUN" in statuses:
        return "PASS_WITH_NOT_RUN"
    if blockers:
        return "PASS_WITH_BLOCKERS"
    return "PASS"


def completion_exit_code(result: str) -> int:
    return 0 if result == "PASS" else 1


def physical_stage(manifest, out: Path, platform: str, with_physical: bool) -> None:
    if not with_physical:
        record_stage(manifest, out, "physical", "physical not requested (--with-physical)", 0,
                     "NOT_RUN", extra={
                         "reason": "no design-bound physical run requested; the fixed diagnostic "
                                   "LibreLane spike is not a substitute for the generated design"})
        return
    manifest["blockers"].append({
        "code": "DESIGN_BOUND_PHYSICAL_RUNNER_NOT_WIRED",
        "detail": f"platform {platform!r}: available LibreLane spike uses a fixed diagnostic "
                  "design/config, not the generated hardware artifact; no physical run started"})
    record_stage(manifest, out, "physical", "design-bound physical runner unavailable", 1,
                 "BLOCKED")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default=None)
    ap.add_argument("--revision", default=None)
    ap.add_argument("--request", default=None)
    ap.add_argument("--gateway", default="http://127.0.0.1:8099")
    ap.add_argument("--platform", default="sky130A")
    ap.add_argument("--release", action="store_true")
    ap.add_argument("--with-physical", action="store_true")
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    out: Path = args.out.resolve()
    if out.exists() and any(out.iterdir()):
        print(f"output directory must be fresh: {out}", file=sys.stderr)
        return 2
    out.mkdir(parents=True, exist_ok=True)
    manifest = new_manifest(args)
    if args.release:
        manifest["scope_note"] = (
            "fourteen-family release matrix; single-project runs never publish a "
            "14/14 claim")
        release_matrix(manifest, out)
        physical_stage(manifest, out, args.platform, args.with_physical)
        manifest["result"] = completion_result(manifest["stages"], manifest["blockers"])
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return completion_exit_code(manifest["result"])
    if args.request:
        doc = json.loads(Path(args.request).read_text())
        source = {"mode": "request", "path": str(args.request)}
    elif args.project:
        doc = load_live_request(args.project, args.gateway, args.revision)
        source = {"mode": "gateway", "project": args.project,
                  "revision": args.revision, "gateway": args.gateway}
    else:
        print("single-project runs need --request FILE or --project PID", file=sys.stderr)
        return 2
    (out / "input-request.json").write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
    freeze = {
        "source": source,
        "request_sha256": sha_bytes(canonical_bytes(doc)),
    }
    record_stage(manifest, out, "freeze", json.dumps(source, sort_keys=True), 0, "PASS",
                 extra=freeze)
    try:
        request, compilation = compile_request(doc)
    except Exception as exc:
        manifest["blockers"].append({
            "code": "INTENT_REFUSED",
            "detail": f"request does not resolve: {exc}"})
        record_stage(manifest, out, "compile", "FabricCompiler().compile(request)", 1, "FAIL",
                     extra={"error": str(exc)[:600]})
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return 1
    manifest["artifacts"]["design_hash"] = request.design_hash()
    if compilation.status != "COMPILED":
        manifest["blockers"].append({
            "code": "COMPILE_REFUSED",
            "detail": compilation.error or compilation.status})
        record_stage(manifest, out, "compile", "FabricCompiler().compile(request)", 1, "FAIL",
                     extra={"error": compilation.error or compilation.status})
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return 1
    record_stage(manifest, out, "compile", "FabricCompiler().compile(request)", 0, "PASS",
                 extra={"design_hash": request.design_hash(),
                        "certificate": (compilation.certificate.overall
                                        if compilation.certificate is not None else None)})
    try:
        family = hardware_family_for_request(request)
    except ValueError as exc:
        manifest["blockers"].append({"code": "UNSUPPORTED_COMPLETION_FAMILY", "detail": str(exc)})
        record_stage(manifest, out, "hardware", "resolve exact request family", 1, "BLOCKED",
                     extra={"error": str(exc)[:600]})
        manifest["result"] = "BLOCKED"
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return 1
    hardware_out = out / "hardware"
    hardware_out.mkdir(parents=True, exist_ok=True)
    try:
        result = generate_hardware(request, family, hardware_out)
    except Exception as exc:
        manifest["blockers"].append({
            "code": "HARDWARE_REFUSED",
            "detail": str(exc)[:600]})
        error_log = hardware_out / "runner-error.log"
        error_log.write_text(f"{type(exc).__name__}: {exc}\n")
        record_stage(manifest, out, "hardware", "generate_hardware", 1, "FAIL",
                     log=error_log,
                     extra={"error": str(exc)[:600],
                            "logs": log_artifacts(hardware_out, out)})
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        return 1
    scenarios = result.get("scenarios")
    scenario_pass = (all(value is True for value in scenarios.values())
                     if isinstance(scenarios, dict) and scenarios else None)
    hardware_status = hardware_evidence_status(result)
    hardware_manifest = hardware_out / "project-top-manifest.json"
    record_stage(manifest, out, "hardware", "generate_hardware",
                 0 if hardware_status == "PASS" else 1, hardware_status,
                 log=hardware_manifest if hardware_manifest.is_file() else None,
                 extra={"logs": log_artifacts(hardware_out, out),
                        "family": family,
                        "lint": result.get("lint"),
                        "sim": result.get("sim"),
                        "scenario_pass": scenario_pass,
                        "scenario_count": len(scenarios or {}),
                        "scope": result.get("scope"),
                        "final_implementation": result.get("final_implementation", False)})
    if hardware_status != "PASS":
        manifest["blockers"].append({
            "code": "HARDWARE_EVIDENCE_INCOMPLETE",
            "detail": f"lint/simulation/scenario evidence did not pass (stage={hardware_status})"})
        manifest["result"] = hardware_status
        (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
        print(json.dumps({"result": manifest["result"],
                          "design_hash": manifest["artifacts"].get("design_hash")}, indent=2))
        return 1
    physical_stage(manifest, out, args.platform, args.with_physical)
    manifest["scope_note"] = (
        "single-project run; this manifest covers exactly the declared project "
        "revision and never a fourteen-family claim")
    manifest["result"] = completion_result(manifest["stages"], manifest["blockers"])
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"result": manifest["result"],
                      "design_hash": manifest["artifacts"].get("design_hash")},
                     indent=2, sort_keys=True))
    return completion_exit_code(manifest["result"])


if __name__ == "__main__":
    raise SystemExit(main())
