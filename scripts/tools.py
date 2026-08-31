#!/usr/bin/env python3
"""
scripts/tools.py -- Unified vendored tool management.

Auto-discovers tools from METADATA.json files under third_party/ and serving/.
Manages all vendored tools from a single interface.
Tools declare sync_targets in METADATA.json (no shell scripts needed).

Usage:
    python3 scripts/tools.py                        # list all tools
    python3 scripts/tools.py booksim2 info           # show details
    python3 scripts/tools.py booksim2 build          # build the tool
    python3 scripts/tools.py booksim2 sync           # sync to downstream copies
    python3 scripts/tools.py booksim2 sync --check   # dry run
    python3 scripts/tools.py booksim2 tag 2.1        # tag current state
    python3 scripts/tools.py booksim2 clean          # clean build artifacts

Makefile targets (equivalent):
    make tools                 list all tools
    make tool-info TOOL=X      show details
    make tool-build TOOL=X     build
    make tool-sync TOOL=X      sync downstream copies
    make tool-tag TOOL=X VER=Y tag
    make tool-clean TOOL=X     clean
"""

from __future__ import annotations

import argparse
import difflib
import fnmatch
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent
THIRD_PARTY = REPO_ROOT / "third_party"
SERVING = REPO_ROOT / "serving"
DISCOVERY_DIRS = [THIRD_PARTY, SERVING]


# ---------------------------------------------------------------------------
# METADATA.json schema
# ---------------------------------------------------------------------------

# Required fields:
#   name            str   tool name (matches directory name)
#   description     str   one-line description
#   upstream        str   upstream repo URL
#   commit          str   vendored commit hash
#   date_vendored   str   YYYY-MM-DD
#   build_command   str   shell command to build (relative to tool dir)
#   install_location str  path to built binary (relative to tool dir)
#
# Optional fields:
#   source_branch       str    upstream branch vendored from
#   patches             list   description of local patches
#   local_modifications list   files modified locally
#   known_gaps          list   known issues / TODOs
#   used_by             list   track directories that use this tool
#   clean_command       str    shell command to clean build artifacts
#   deps                list   other tool names this depends on
#   sync_targets        list   downstream copies to keep in sync
#
# sync_targets schema:
#   - dest          str    destination path (relative to REPO_ROOT)
#     patterns      list   glob patterns to sync (default: ["*.cpp","*.hpp","*.h","*.c","Makefile"])
#     skip          list   filenames to skip (default: [])
#     post_sync     str    optional shell command to run after sync


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_tools() -> dict[str, dict[str, Any]]:
    """Find all METADATA.json under third_party/ and serving/ and return {name: metadata}."""
    tools: dict[str, dict[str, Any]] = {}

    for discovery_dir in DISCOVERY_DIRS:
        if not discovery_dir.exists():
            continue
        for md_path in sorted(discovery_dir.rglob("METADATA.json")):
            try:
                with open(md_path) as f:
                    meta = json.load(f)
            except (json.JSONDecodeError, OSError) as e:
                print(f"  WARNING: skipping {md_path}: {e}", file=sys.stderr)
                continue

            name = meta.get("name")
            if not name:
                print(f"  WARNING: {md_path} has no 'name' field", file=sys.stderr)
                continue

            # Store the path to METADATA.json and the tool directory
            meta["_path"] = md_path
            meta["_dir"] = md_path.parent
            tools[name] = meta

    return tools


def get_tool(name: str) -> dict[str, Any]:
    """Get a single tool by name, or exit with error."""
    tools = discover_tools()
    if name not in tools:
        available = ", ".join(sorted(tools.keys())) or "(none)"
        print(f"ERROR: unknown tool '{name}'", file=sys.stderr)
        print(f"Available tools: {available}", file=sys.stderr)
        sys.exit(1)
    return tools[name]


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list(_args: argparse.Namespace) -> None:
    """List all discovered tools."""
    tools = discover_tools()
    if not tools:
        print("No tools found under third_party/ or serving/")
        return

    print(f"{'Tool':<16} {'Location':<12} {'Commit':<12} {'Binary':<8} {'Sync'}")
    print("-" * 76)

    for name, meta in sorted(tools.items()):
        commit = meta.get("commit", "?")[:10]
        install = meta.get("install_location", "")
        tool_dir = meta["_dir"]

        # Show relative location
        try:
            loc = tool_dir.relative_to(REPO_ROOT).parent.name  # third_party or serving
        except ValueError:
            loc = "?"

        # Check if binary exists
        if install:
            bin_path = tool_dir / install
            binary = "OK" if bin_path.exists() else "MISSING"
        else:
            binary = "--"

        # Check sync targets
        sync_targets = meta.get("sync_targets", [])
        if sync_targets:
            sync_status = f"{len(sync_targets)} target(s)"
        else:
            sync_status = "--"

        print(f"{name:<16} {loc:<12} {commit:<12} {binary:<8} {sync_status}")


def cmd_info(args: argparse.Namespace) -> None:
    """Show detailed information about a tool."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]

    print(f"Tool: {meta['name']}")
    print(f"  Description:     {meta.get('description', '?')}")
    print(f"  Upstream:        {meta.get('upstream', '?')}")
    print(f"  Commit:          {meta.get('commit', '?')}")
    print(f"  Date vendored:   {meta.get('date_vendored', '?')}")
    print(f"  Source branch:   {meta.get('source_branch', '?')}")
    print(f"  Directory:       {tool_dir}")

    # Binary status
    install = meta.get("install_location", "")
    if install:
        bin_path = tool_dir / install
        status = "BUILT" if bin_path.exists() else "NOT BUILT"
        print(f"  Binary:          {install} ({status})")
    else:
        print(f"  Binary:          (no install_location defined)")

    # Dependencies
    deps = meta.get("deps", [])
    if deps:
        print(f"  Dependencies:    {', '.join(deps)}")

    # Used by
    used_by = meta.get("used_by", [])
    if used_by:
        print(f"  Used by:         {', '.join(used_by)}")

    # Sync targets
    sync_targets = meta.get("sync_targets", [])
    if sync_targets:
        print(f"  Sync targets:")
        for st in sync_targets:
            dest = st.get("dest", "?")
            patterns = st.get("patterns", ["*.cpp", "*.hpp", "*.h", "*.c", "Makefile"])
            print(f"    {dest}")
            print(f"      patterns: {', '.join(patterns)}")
            skip = st.get("skip", [])
            if skip:
                print(f"      skip: {', '.join(skip)}")

    # Local modifications
    mods = meta.get("local_modifications", [])
    if mods:
        print(f"  Local modifications:")
        for m in mods:
            print(f"    - {m}")

    # Patches
    patches = meta.get("patches", [])
    if patches:
        print(f"  Patches:")
        for p in patches:
            print(f"    - {p}")

    # Known gaps
    gaps = meta.get("known_gaps", [])
    if gaps:
        print(f"  Known gaps:")
        for g in gaps:
            print(f"    - {g}")


def cmd_build(args: argparse.Namespace) -> None:
    """Build a tool using its build_command."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]
    build_cmd = meta.get("build_command")

    if not build_cmd:
        print(f"ERROR: {args.tool} has no build_command in METADATA.json", file=sys.stderr)
        sys.exit(1)

    # Check dependencies first
    deps = meta.get("deps", [])
    for dep in deps:
        dep_meta = get_tool(dep)
        dep_install = dep_meta.get("install_location", "")
        if dep_install and not (dep_meta["_dir"] / dep_install).exists():
            print(f"Dependency '{dep}' not built. Building it first...")
            dep_args = argparse.Namespace(tool=dep)
            cmd_build(dep_args)

    print(f"Building {args.tool}...")
    print(f"  Directory: {tool_dir}")
    print(f"  Command:   {build_cmd}")

    result = subprocess.run(
        build_cmd, shell=True, cwd=tool_dir,
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"BUILD FAILED (exit {result.returncode})", file=sys.stderr)
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
        sys.exit(result.returncode)

    # Verify binary
    install = meta.get("install_location", "")
    if install:
        bin_path = tool_dir / install
        if bin_path.exists():
            print(f"BUILD OK: {bin_path}")
        else:
            print(f"WARNING: build succeeded but {install} not found", file=sys.stderr)
    else:
        print("BUILD OK (no install_location to verify)")


def cmd_sync(args: argparse.Namespace) -> None:
    """Sync tool source to downstream copies declared in METADATA.json."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]
    sync_targets = meta.get("sync_targets", [])

    if not sync_targets:
        print(f"{args.tool} has no sync_targets defined in METADATA.json")
        return

    for target in sync_targets:
        dest_rel = target["dest"]
        patterns = target.get("patterns", ["*.cpp", "*.hpp", "*.h", "*.c", "Makefile"])
        skip = set(target.get("skip", []))
        post_sync = target.get("post_sync")

        src_dir = tool_dir / "src"
        dst_dir = REPO_ROOT / dest_rel / "src"

        if not src_dir.exists():
            print(f"  ERROR: source dir not found: {src_dir}", file=sys.stderr)
            continue
        if not dst_dir.exists():
            print(f"  ERROR: destination dir not found: {dst_dir}", file=sys.stderr)
            continue

        print(f"Syncing {args.tool} -> {dest_rel}")

        # Collect files to sync
        files_to_sync = []
        for pattern in patterns:
            for f in src_dir.rglob(pattern):
                rel = f.relative_to(src_dir)
                if rel.name in skip:
                    continue
                files_to_sync.append(rel)

        # Check for differences
        diffs = 0
        new_files = 0
        changed_files = 0

        for rel in files_to_sync:
            src_file = src_dir / rel
            dst_file = dst_dir / rel

            if not dst_file.exists():
                if not args.check_only:
                    print(f"  NEW:    {rel}")
                new_files += 1
                diffs += 1
            elif not filecmp(src_file, dst_file):
                if not args.check_only:
                    print(f"  CHANGED: {rel}")
                changed_files += 1
                diffs += 1

        # Info-only: files only in destination
        for rel in files_to_sync:
            src_file = src_dir / rel
            dst_file = dst_dir / rel
            if not src_file.exists() and dst_file.exists():
                if not args.check_only:
                    print(f"  DEST-ONLY: {rel} (not in source)")

        if diffs == 0:
            print(f"  All {len(files_to_sync)} files are in sync.")
            continue

        print(f"  Found {diffs} differences ({new_files} new, {changed_files} changed)")

        if args.check_only:
            print(f"  Dry run -- no files copied. Run without --check to sync.")
            continue

        # Actually sync
        copied = 0
        for rel in files_to_sync:
            src_file = src_dir / rel
            dst_file = dst_dir / rel

            dst_file.parent.mkdir(parents=True, exist_ok=True)

            if not dst_file.exists() or not filecmp(src_file, dst_file):
                shutil.copy2(src_file, dst_file)
                copied += 1

        print(f"  Synced {copied} files.")

        # Post-sync hook
        if post_sync:
            print(f"  Running post-sync: {post_sync}")
            result = subprocess.run(
                post_sync, shell=True, cwd=REPO_ROOT,
                capture_output=True, text=True
            )
            if result.returncode != 0:
                print(f"  WARNING: post-sync failed (exit {result.returncode})", file=sys.stderr)
                if result.stderr:
                    print(f"  {result.stderr.strip()}", file=sys.stderr)


def cmd_run(args: argparse.Namespace) -> None:
    """Run a tool's binary with optional arguments."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]
    install = meta.get("install_location", "")

    if not install:
        print(f"ERROR: {args.tool} has no install_location in METADATA.json", file=sys.stderr)
        sys.exit(1)

    bin_path = tool_dir / install
    if not bin_path.exists():
        print(f"ERROR: {args.tool} binary not found: {bin_path}", file=sys.stderr)
        print(f"Run: make tool-build TOOL={args.tool}", file=sys.stderr)
        sys.exit(1)

    # Build command line
    cmd = [str(bin_path)] + (args.args or [])
    print(f"Running: {' '.join(cmd)}")
    print(f"  CWD: {tool_dir}")

    result = subprocess.run(cmd, cwd=tool_dir)
    sys.exit(result.returncode)


def cmd_pick(args: argparse.Namespace) -> None:
    """Interactive version picker — list available tags, switch, auto-rebuild."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]

    # List available tags
    result = subprocess.run(
        ["git", "tag", "-l", f"vendor/{args.tool}/*"],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    tags = sorted(result.stdout.strip().split("\n")) if result.stdout.strip() else []

    if not tags:
        print(f"No version tags found for {args.tool}")
        print(f"Create one with: make tool-tag TOOL={args.tool} VER=1.0")
        return

    print(f"Available versions for {args.tool}:")
    for i, tag in enumerate(tags, 1):
        ver = tag.split("/")[-1]
        # Get tag date
        tag_result = subprocess.run(
            ["git", "log", "-1", "--format=%ci", tag],
            capture_output=True, text=True, cwd=REPO_ROOT
        )
        date = tag_result.stdout.strip()[:10] if tag_result.stdout.strip() else "?"
        print(f"  {i}. {ver} ({date})")

    print(f"\nCurrent: {meta.get('commit', '?')[:10]}")
    print(f"\nTo switch: git checkout vendor/{args.tool}/<version>")
    print(f"Then rebuild: make tool-build TOOL={args.tool}")


def cmd_tag(args: argparse.Namespace) -> None:
    """Tag the current state of a tool (creates a git tag)."""
    meta = get_tool(args.tool)
    ver = args.version

    if not ver:
        print("ERROR: version required (e.g., tools.py booksim2 tag 2.1)", file=sys.stderr)
        sys.exit(1)

    tag_name = f"vendor/{args.tool}/{ver}"

    # Check if tag already exists
    result = subprocess.run(
        ["git", "tag", "-l", tag_name],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.stdout.strip():
        print(f"Tag {tag_name} already exists.", file=sys.stderr)
        sys.exit(1)

    # Create tag
    subprocess.run(
        ["git", "tag", "-a", tag_name, "-m", f"Vendor {args.tool} v{ver}"],
        check=True, cwd=REPO_ROOT
    )
    print(f"Tagged: {tag_name}")


def cmd_clean(args: argparse.Namespace) -> None:
    """Clean build artifacts for a tool."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]
    clean_cmd = meta.get("clean_command")

    if not clean_cmd:
        # Try to infer from build_command
        build_cmd = meta.get("build_command", "")
        if "make" in build_cmd:
            clean_cmd = build_cmd.replace("make", "make clean", 1)
        else:
            print(f"{args.tool} has no clean_command. Nothing to clean.")
            return

    print(f"Cleaning {args.tool}...")
    result = subprocess.run(
        clean_cmd, shell=True, cwd=tool_dir,
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"CLEAN FAILED (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    else:
        print("CLEAN OK")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def filecmp(a: Path, b: Path) -> bool:
    """True if files are byte-identical."""
    if a.stat().st_size != b.stat().st_size:
        return False
    with open(a, "rb") as fa, open(b, "rb") as fb:
        while True:
            chunk_a = fa.read(8192)
            chunk_b = fb.read(8192)
            if chunk_a != chunk_b:
                return False
            if not chunk_a:
                return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Unified vendored tool management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 scripts/tools.py                         # list all tools
  python3 scripts/tools.py booksim2 info           # show details
  python3 scripts/tools.py booksim2 build          # build the tool
  python3 scripts/tools.py booksim2 sync           # sync to downstream copies
  python3 scripts/tools.py booksim2 sync --check   # dry run
  python3 scripts/tools.py booksim2 tag 2.1        # tag current state
  python3 scripts/tools.py booksim2 clean          # clean build artifacts
        """
    )
    parser.add_argument("tool", nargs="?", help="Tool name")
    parser.add_argument("command", nargs="?",
                        choices=["list", "info", "build", "run", "sync", "tag", "pick", "clean"],
                        default="list",
                        help="Command to run (default: list)")
    parser.add_argument("version", nargs="?", help="Version for tag command")
    parser.add_argument("--check", dest="check_only", action="store_true",
                        help="Dry run for sync command")
    parser.add_argument("args", nargs="*", help="Arguments for run command")

    args = parser.parse_args()

    if not args.tool or args.command == "list":
        cmd_list(args)
        return

    commands = {
        "info": cmd_info,
        "build": cmd_build,
        "run": cmd_run,
        "sync": cmd_sync,
        "tag": cmd_tag,
        "pick": cmd_pick,
        "clean": cmd_clean,
    }

    func = commands.get(args.command)
    if func:
        func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
