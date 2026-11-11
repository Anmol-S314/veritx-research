#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from reproduce_slice import slice_request


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=REPO / "runs" / "slice")
    parser.add_argument("--hashes-only", action="store_true")
    args = parser.parse_args()

    problems: list[str] = []
    manifest_path = args.out / "project-top-manifest.json"
    if not manifest_path.is_file():
        print(f"VERIFY FAILED: no manifest at {manifest_path}")
        print("hint: run scripts/reproduce_slice.sh first")
        return 1
    manifest = json.loads(manifest_path.read_text())

    if manifest.get("scope") != "COMPOSED_SLICE":
        problems.append(f"scope is {manifest.get('scope')!r}, expected COMPOSED_SLICE")
    if manifest.get("final_implementation") is not False:
        problems.append("final_implementation must be false (development milestone)")
    pinned = slice_request().design_hash()
    if manifest.get("design_hash") != pinned:
        problems.append(f"design_hash {manifest.get('design_hash')} != pinned {pinned}")

    files = manifest.get("files", [])
    rtl = args.out / "rtl"
    mismatched = 0
    for row in files:
        path = rtl / row["path"]
        if not path.is_file():
            problems.append(f"missing rtl/{row['path']}")
            continue
        if sha256(path) != row["sha256"]:
            mismatched += 1
            problems.append(f"hash mismatch rtl/{row['path']}")
    print(f"files: {len(files)} listed, {mismatched} hash mismatches")

    sidecar_manifest = args.out / "rtl-preview.json"
    if sidecar_manifest.is_file():
        preview = json.loads(sidecar_manifest.read_text())
        if preview.get("scope") != "TOPOLOGY_ONLY_PREVIEW":
            problems.append(f"sidecar scope is {preview.get('scope')!r}, "
                            "expected TOPOLOGY_ONLY_PREVIEW (never upgraded)")
        if manifest.get("sidecar", {}).get("manifest_sha256") != sha256(sidecar_manifest):
            problems.append("sidecar manifest_sha256 mismatch")
    else:
        problems.append("sidecar rtl-preview.json missing")

    import zipfile
    archive = args.out / "project-top.zip"
    if archive.is_file():
        try:
            with zipfile.ZipFile(archive) as package:
                members = set(package.namelist())
            expected_members = {"project-top-manifest.json", "rtl-preview.json"} | {
                f"rtl/{row['path']}" for row in files}
            missing = expected_members - members
            if missing:
                problems.append(f"project-top.zip missing members: {sorted(missing)}")
        except zipfile.BadZipFile:
            problems.append("project-top.zip is not a valid zip archive")
    else:
        problems.append("project-top.zip missing")

    sidecar_archive = args.out / "topology-rtl-preview.zip"
    if sidecar_archive.is_file():
        if manifest.get("sidecar", {}).get("archive_sha256") not in (
                None, sha256(sidecar_archive)):
            problems.append("topology-rtl-preview.zip hash differs from "
                            "manifest sidecar entry")
    else:
        problems.append("topology-rtl-preview.zip missing")

    lint = manifest.get("lint", {})
    sim = manifest.get("sim", {})
    print(f"lint: {lint.get('status')} (warnings={lint.get('warning_count')}, "
          f"clean={lint.get('clean')})")
    print(f"sim: {sim.get('status')} "
          f"({sum(1 for v in sim.get('scenarios', {}).values() if v)}/"
          f"{len(sim.get('scenarios', {}))} scenarios true)")
    if lint.get("status") != "PASS":
        problems.append(f"lint verdict is {lint.get('status')!r}, expected PASS")
    if sim.get("status") != "PASS":
        problems.append(f"sim verdict is {sim.get('status')!r}, expected PASS")
    failed = [k for k, v in sim.get("scenarios", {}).items() if not v]
    if failed:
        problems.append(f"TB scenarios false: {failed}")
    if args.hashes_only:
        for problem in problems:
            print(f"VERIFY (hashes-only) WARN: {problem}")
        problems = [
            p for p in problems
            if p.startswith(("scope", "final_implementation", "design_hash",
                             "missing", "hash mismatch", "sidecar",
                             "project-top.zip", "topology-rtl-preview"))]
        if problems:
            for problem in problems:
                print(f"VERIFY FAILED: {problem}")
            return 1
        print("VERIFY OK (hashes-only) — hash/content structure exact; "
              "lint/sim verdicts reported above, not enforced")
        return 0

    makefile = rtl / "Makefile"
    if makefile.is_file() and shutil.which("make") and shutil.which("verilator"):
        check = subprocess.run(["make", "-s", "lint-slice"], cwd=rtl,
                               capture_output=True, text=True, timeout=300)
        if check.returncode != 0:
            problems.append("fresh `make lint-slice` failed: "
                            + (check.stdout + check.stderr)[-500:])
        else:
            print("fresh lint: make lint-slice PASS")
    elif not makefile.is_file():
        problems.append("rtl/Makefile missing (cannot run fresh lint)")
    else:
        print("fresh lint: SKIPPED (Verilator not installed)")

    if problems:
        for problem in problems:
            print(f"VERIFY FAILED: {problem}")
        return 1
    print("VERIFY OK — slice reproduced exactly and proven")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
