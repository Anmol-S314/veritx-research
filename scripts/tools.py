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
DISCOVERY_DIRS = [THIRD_PARTY]


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
    """Find all METADATA.json under third_party/ and return {name: metadata}."""
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
        print("No tools found under third_party/")
        return

    print(f"{'Tool':<16} {'Location':<12} {'Commit':<12} {'Binary':<8} {'Sync'}")
    print("-" * 76)

    for name, meta in sorted(tools.items()):
        commit = meta.get("commit", "?")[:10]
        install = meta.get("install_location", "")
        tool_dir = meta["_dir"]

        # Show relative location
        try:
            loc = tool_dir.relative_to(REPO_ROOT).parent.name  # third_party
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
        ["bash", "-c", build_cmd], cwd=tool_dir,
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
                ["bash", "-c", post_sync], cwd=REPO_ROOT,
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
    cmd = [str(bin_path)] + (args.run_args or [])
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

    # Get current version
    current_tag = subprocess.run(
        ["git", "describe", "--tags", "--exact-match"],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    current = current_tag.stdout.strip() if current_tag.returncode == 0 else "(dirty)"
    print(f"\nCurrent: {current}")

    # Interactive selection
    try:
        choice = input(f"\nPick version (1-{len(tags)}) or 'q' to quit: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\nAborted.")
        return

    if choice == "q" or not choice:
        return

    try:
        idx = int(choice) - 1
        if idx < 0 or idx >= len(tags):
            print(f"Invalid choice: {choice}")
            return
    except ValueError:
        print(f"Invalid choice: {choice}")
        return

    tag = tags[idx]
    ver = tag.split("/")[-1]

    print(f"\nSwitching {args.tool} to v{ver}...")

    # Checkout the tag into the tool directory
    result = subprocess.run(
        ["git", "checkout", tag, "--", str(tool_dir.relative_to(REPO_ROOT))],
        capture_output=True, text=True, cwd=REPO_ROOT
    )
    if result.returncode != 0:
        print(f"Checkout failed: {result.stderr}", file=sys.stderr)
        return

    print(f"Switched to {tag}")

    # Auto-rebuild if build_command exists
    if meta.get("build_command"):
        print(f"Rebuilding {args.tool}...")
        build_args = argparse.Namespace(tool=args.tool)
        cmd_build(build_args)


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
        ["bash", "-c", clean_cmd], cwd=tool_dir,
        capture_output=True, text=True
    )

    if result.returncode != 0:
        print(f"CLEAN FAILED (exit {result.returncode})", file=sys.stderr)
        if result.stderr:
            print(result.stderr, file=sys.stderr)
    else:
        print("CLEAN OK")


def cmd_update(args: argparse.Namespace) -> None:
    """Update a tool from its upstream repository."""
    meta = get_tool(args.tool)
    tool_dir = meta["_dir"]
    upstream = meta.get("upstream")

    if not upstream:
        print(f"ERROR: {args.tool} has no upstream URL in METADATA.json", file=sys.stderr)
        sys.exit(1)

    # Check if tool directory is a git repo
    if not (tool_dir / ".git").exists() and not (tool_dir / ".git" / "HEAD").exists():
        # Try to initialize git repo from upstream
        print(f"Initializing git repo in {tool_dir}...")
        result = subprocess.run(
            ["git", "init"], cwd=tool_dir, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"ERROR: Could not initialize git repo: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        # Add upstream remote
        subprocess.run(
            ["git", "remote", "add", "upstream", upstream],
            cwd=tool_dir, capture_output=True, text=True
        )
    else:
        # Check if 'upstream' remote exists, if not add it
        result = subprocess.run(
            ["git", "remote", "get-url", "upstream"],
            cwd=tool_dir, capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"Adding 'upstream' remote: {upstream}")
            subprocess.run(
                ["git", "remote", "add", "upstream", upstream],
                cwd=tool_dir, capture_output=True, text=True
            )

    # Fetch upstream changes
    print(f"Fetching upstream changes from {upstream}...")
    result = subprocess.run(
        ["git", "fetch", "upstream"], cwd=tool_dir,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"FETCH FAILED: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    # Show what changed
    result = subprocess.run(
        ["git", "log", "HEAD..upstream/main", "--oneline"],
        cwd=tool_dir, capture_output=True, text=True
    )
    if result.returncode != 0:
        # Try master branch
        result = subprocess.run(
            ["git", "log", "HEAD..upstream/master", "--oneline"],
            cwd=tool_dir, capture_output=True, text=True
        )

    if result.stdout.strip():
        print(f"\nUpstream changes:")
        print(result.stdout)
    else:
        print("No upstream changes.")
        return

    # Merge upstream changes
    print("Merging upstream changes...")
    result = subprocess.run(
        ["git", "merge", "upstream/main"], cwd=tool_dir,
        capture_output=True, text=True
    )
    if result.returncode != 0:
        # Try master branch
        result = subprocess.run(
            ["git", "merge", "upstream/master"], cwd=tool_dir,
            capture_output=True, text=True
        )

    if result.returncode != 0:
        print(f"MERGE CONFLICTS detected:", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print("\nResolve conflicts manually, then run:")
        print(f"  python3 scripts/tools.py {args.tool} build")
        print(f"  python3 scripts/tools.py {args.tool} tag <new-version>")
        sys.exit(1)

    # Get new commit hash
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=tool_dir,
        capture_output=True, text=True
    )
    new_commit = result.stdout.strip()

    # Update METADATA.json
    import datetime
    meta["commit"] = new_commit
    meta["date_vendored"] = datetime.date.today().isoformat()
    meta_path = tool_dir / "METADATA.json"
    with open(meta_path, 'w') as f:
        json.dump({k: v for k, v in meta.items() if not k.startswith("_")}, f, indent=2)

    print(f"\nUpdated METADATA.json:")
    print(f"  commit: {new_commit}")
    print(f"  date: {meta['date_vendored']}")
    print(f"\nNext steps:")
    print(f"  1. Review changes: git -C {tool_dir} diff HEAD~1")
    print(f"  2. Build: python3 scripts/tools.py {args.tool} build")
    print(f"  3. Test: python3 scripts/tools.py {args.tool} run <config>")
    print(f"  4. Tag: python3 scripts/tools.py {args.tool} tag <new-version>")


def cmd_add(args: argparse.Namespace) -> None:
    """Clone a tool from a URL and auto-generate METADATA.json."""
    url = args.url
    if not url:
        print("ERROR: URL required (e.g., tools.py add https://github.com/user/repo)", file=sys.stderr)
        sys.exit(1)

    # Extract tool name from URL (strip query params, fragments, .git)
    from urllib.parse import urlparse
    parsed = urlparse(url)
    tool_name = parsed.path.rstrip('/').split('/')[-1]
    if tool_name.endswith('.git'):
        tool_name = tool_name[:-4]
    if not tool_name:
        print(f"ERROR: Cannot extract tool name from {url}", file=sys.stderr)
        sys.exit(1)

    tool_dir = THIRD_PARTY / tool_name
    if tool_dir.exists():
        print(f"ERROR: {tool_dir} already exists", file=sys.stderr)
        sys.exit(1)

    # Clone
    print(f"Cloning {url} -> {tool_dir}")
    result = subprocess.run(
        ["git", "clone", url, str(tool_dir)],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        # Clean up partial clone
        if tool_dir.exists():
            import shutil
            shutil.rmtree(tool_dir)
        print(f"CLONE FAILED: {result.stderr.strip()}", file=sys.stderr)
        sys.exit(1)

    # Get commit hash
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True, text=True, cwd=tool_dir
    )
    commit = result.stdout.strip()

    # Auto-detect build system
    build_cmd = "make"
    install_loc = "build/"
    if (tool_dir / "CMakeLists.txt").exists():
        build_cmd = "mkdir -p build && cd build && cmake .. && make -j$(nproc)"
        install_loc = "build/"
    elif (tool_dir / "wscript").exists() or (tool_dir / "ns3").exists():
        build_cmd = "./ns3 configure --enable-examples && ./ns3 build"
        install_loc = "build/scratch/"
    elif (tool_dir / "meson.build").exists():
        build_cmd = "meson setup build && ninja -C build"
        install_loc = "build/"
    elif (tool_dir / "configure.ac").exists() or (tool_dir / "configure").exists():
        build_cmd = "./configure && make -j$(nproc)"
        install_loc = ""
    else:
        build_cmd = "make -j$(nproc)"
        install_loc = ""

    # Generate METADATA.json
    metadata = {
        "name": tool_name,
        "description": f"{tool_name} (auto-added from {url})",
        "upstream": url,
        "commit": commit,
        "date_vendored": __import__('datetime').date.today().isoformat(),
        "build_command": build_cmd,
        "install_location": install_loc,
        "clean_command": "make clean" if "make" in build_cmd else "",
    }

    meta_path = tool_dir / "METADATA.json"
    with open(meta_path, 'w') as f:
        json.dump(metadata, f, indent=2)

    print(f"Created: {meta_path}")

    # Check for container runtime
    container = subprocess.run(
        ["bash", "-c", "command -v podman || command -v docker || echo none"],
        capture_output=True, text=True
    ).stdout.strip()

    # Add to Dockerfile
    dockerfile = REPO_ROOT / "Dockerfile"
    if dockerfile.exists():
        df_content = dockerfile.read_text()
        # Find where booksim COPY ends and add after it
        marker = "COPY --from=builder /opt/booksim2 /opt/booksim2"
        if marker in df_content and f"COPY third_party/{tool_name}/" not in df_content:
            insert_line = f"\n# {tool_name} — COPY from third_party/\nCOPY third_party/{tool_name}/ /opt/{tool_name}/"
            df_content = df_content.replace(marker, marker + insert_line)
            dockerfile.write_text(df_content)
            print(f"Updated: {dockerfile} (added COPY for {tool_name})")

    print(f"\nDone! Next steps:")
    print(f"  1. Edit {meta_path} (adjust build_command, install_location)")
    print(f"  2. python3 scripts/tools.py {tool_name} build")
    print(f"  3. python3 scripts/tools.py {tool_name} tag v1.0")
    if container != "none":
        print(f"  4. make tool-image  (rebuild container with {container})")
    else:
        print(f"  4. Install podman/docker for container support")


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
  python3 scripts/tools.py add https://github.com/user/repo  # add new tool
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
                        choices=["list", "info", "build", "run", "sync", "tag", "pick", "clean", "add", "update"],
                        default="list",
                        help="Command to run (default: list)")
    parser.add_argument("--url", help="URL for add command")
    parser.add_argument("--check", dest="check_only", action="store_true",
                        help="Dry run for sync command")
    parser.add_argument("--tag", dest="tag_version",
                        help="Version for tag command (e.g. --tag v2.1)")
    parser.add_argument("remaining", nargs="*",
                        help="Version for tag, or args for run command")

    args = parser.parse_args()

    # Normalize: 'remaining' is ambiguous — figure out what it means
    # For 'tag': first remaining arg is the version
    # For 'run': all remaining args are passed to the binary
    # For others: ignore
    args.version = None
    args.run_args = []
    if args.command == "tag":
        if args.tag_version:
            args.version = args.tag_version
        elif args.remaining:
            args.version = args.remaining[0]
            args.run_args = args.remaining[1:]
        else:
            args.version = None
    elif args.command == "run":
        if args.tag_version:
            args.run_args = [args.tag_version] + args.remaining
        else:
            args.run_args = args.remaining
    else:
        if args.tag_version:
            args.run_args = [args.tag_version] + args.remaining
        else:
            args.run_args = args.remaining

    # 'add' command uses --url flag
    if args.command == "add" or args.tool == "add":
        if not args.url:
            print("ERROR: --url required for add command", file=sys.stderr)
            print("Usage: tools.py add --url https://github.com/user/repo", file=sys.stderr)
            sys.exit(1)
        cmd_add(args)
        return

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
        "add": cmd_add,
        "update": cmd_update,
    }

    func = commands.get(args.command)
    if func:
        func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
