#!/usr/bin/env python3
"""VeritX Tool Manager — auto-discovers tools from METADATA.json.

Usage:
    tools <tool>                     # show tool info + actions
    tools <tool> run [args]          # run the tool
    tools <tool> build               # build/rebuild
    tools <tool> clean               # clean build artifacts
    tools <tool> tag <ver>           # tag version
    tools <tool> pick                # pick version
    tools <tool> diff                # show changes from upstream
    tools list                       # list all tools
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Optional, Dict, Any

# ──────────────────────────────────────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).parent.parent
SEARCH_DIRS = [REPO_ROOT / "third_party", REPO_ROOT]

# ──────────────────────────────────────────────────────────────────────────────
# Auto-discovery
# ──────────────────────────────────────────────────────────────────────────────

def discover_tools() -> Dict[str, Dict[str, Any]]:
    """Auto-discover tools from METADATA.json files."""
    tools = {}
    
    for search_dir in SEARCH_DIRS:
        if not search_dir.exists():
            continue
        for meta_file in search_dir.rglob("METADATA.json"):
            if ".git" in str(meta_file) or "TEMPLATE" in str(meta_file):
                continue
            try:
                with open(meta_file) as f:
                    meta = json.load(f)
                name = meta["name"]
                tool_dir = meta_file.parent
                tools[name] = {
                    "path": tool_dir,
                    "metadata": meta,
                    "binary": _find_binary(tool_dir, meta),
                    "build_cmd": meta.get("build_command", "make"),
                    "clean_cmd": meta.get("clean_command", "make clean"),
                    "description": meta.get("description", ""),
                }
            except Exception as e:
                pass
    return tools

def _find_binary(tool_dir: Path, meta: dict) -> Optional[Path]:
    """Find the binary for a tool."""
    install_loc = meta.get("install_location", "")
    if install_loc:
        binary = tool_dir / install_loc
        if binary.exists():
            return binary
    # Try common locations
    for candidate in ["src/booksim", "bin/noxim", ".venv/bin/scalesim"]:
        binary = tool_dir / candidate
        if binary.exists():
            return binary
    return None

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def run(cmd: str, cwd: Optional[Path] = None) -> tuple:
    """Run shell command."""
    r = subprocess.run(cmd, shell=True, cwd=cwd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def get_version(path: Path) -> str:
    """Get version from git tags."""
    if not path.exists():
        return "unknown"
    rc, out, _ = run("git describe --tags --exact-match 2>/dev/null || git rev-parse --short HEAD", path)
    return out.strip() if rc == 0 else "unknown"

def get_changelog(path: Path) -> str:
    """Get changelog from git."""
    if not path.exists():
        return "No changelog"
    rc, tag, _ = run("git describe --tags --abbrev=0 2>/dev/null", path)
    if rc == 0 and tag.strip():
        rc2, diff, _ = run(f"git diff {tag.strip()}..HEAD --stat", path)
        if rc2 == 0 and diff.strip():
            return f"Changes since {tag.strip()}:\n{diff.strip()}"
    rc3, commits, _ = run("git log --oneline -5", path)
    return f"Recent:\n{commits.strip()}" if rc3 == 0 else "No changelog"

def check_dependencies() -> Dict[str, bool]:
    """Check if required tools are installed."""
    deps = {}
    for tool in ["gcc", "g++", "make", "git", "python3"]:
        rc, _, _ = run(f"which {tool}")
        deps[tool] = rc == 0
    return deps

def verify_binary(binary: Path) -> bool:
    """Verify binary works."""
    if not binary.exists():
        return False
    rc, _, _ = run(f"{binary} --help 2>/dev/null || {binary} --version 2>/dev/null")
    return rc == 0

# ──────────────────────────────────────────────────────────────────────────────
# Commands
# ──────────────────────────────────────────────────────────────────────────────

def cmd_list():
    """List all tools."""
    tools = discover_tools()
    
    print("\nVeritX Tools")
    print("=" * 65)
    print(f"  {'Tool':<15} {'Commit':<12} {'Status':<12} {'Description'}")
    print("-" * 65)
    
    for name, cfg in sorted(tools.items()):
        path = cfg["path"]
        meta = cfg["metadata"]
        ver = meta.get("version", get_version(path))
        desc = meta.get("description", "")[:30]
        status = "built" if cfg["binary"] else "missing"
        print(f"  {name:<15} {ver:<12} {status:<12} {desc}")
    
    print("\nUsage: tools <tool> [action]")

def cmd_info(name: str):
    """Show tool info and actions."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        print(f"Available: {', '.join(sorted(tools.keys()))}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    meta = cfg["metadata"]
    
    print(f"\n{'─' * 50}")
    print(f"  {name}")
    print(f"{'─' * 50}")
    print(f"  {meta.get('description', '')}")
    print(f"  Upstream: {meta.get('upstream', 'N/A')}")
    
    if path.exists():
        ver = get_version(path)
        print(f"  Version: {ver}")
        print(f"  Path: {path}")
        
        # Check dependencies
        deps = check_dependencies()
        missing = [d for d, ok in deps.items() if not ok]
        if missing:
            print(f"  Missing deps: {', '.join(missing)}")
        
        # Check binary
        if cfg["binary"]:
            status = "ready" if verify_binary(cfg["binary"]) else "needs build"
            print(f"  Binary: {status}")
        else:
            print(f"  Binary: none (library/tool)")
        
        # Surface known gaps / TODOs so they can't be missed
        for gap in meta.get("known_gaps", []):
            print(f"\n  KNOWN GAP: {gap}")
    else:
        print(f"  Status: not cloned")
    
    print(f"\n  Actions:")
    print(f"    tools {name} run [args]    # run the tool")
    print(f"    tools {name} build         # build/rebuild")
    print(f"    tools {name} clean         # clean build")
    print(f"    tools {name} tag <ver>     # tag version")
    print(f"    tools {name} pick          # pick version")
    print(f"    tools {name} diff          # show changes")
    print()

def cmd_build(name: str):
    """Build a tool with verification."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    
    if not path.exists():
        print(f"Tool not cloned: {path}")
        return
    
    # Check dependencies first
    deps = check_dependencies()
    missing = [d for d, ok in deps.items() if not ok]
    if missing:
        print(f"Missing dependencies: {', '.join(missing)}")
        print("Install them first:")
        for d in missing:
            print(f"  sudo apt install {d}")
        return
    
    print(f"\nBuilding {name}...")
    rc, out, err = run(cfg["build_cmd"], path)
    
    if rc == 0:
        print(f"Build complete")
        
        # Verify binary
        if cfg["binary"]:
            if verify_binary(cfg["binary"]):
                print(f"Binary verified: {cfg['binary']}")
            else:
                print(f"Warning: binary exists but failed verification")
    else:
        print(f"Build failed:")
        print(err)

def cmd_clean(name: str):
    """Clean build artifacts."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    
    if not path.exists():
        print(f"Tool not cloned: {path}")
        return
    
    print(f"\nCleaning {name}...")
    rc, out, err = run(cfg["clean_cmd"], path)
    
    if rc == 0:
        print(f"Clean complete")
    else:
        print(f"Clean failed:")
        print(err)

def cmd_run(name: str, args: str = ""):
    """Run a tool."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    
    if not path.exists():
        print(f"Tool not cloned: {path}")
        return
    
    if not cfg["binary"]:
        print(f"No binary for {name}")
        return
    
    if not cfg["binary"].exists():
        print(f"Binary not found. Building...")
        cmd_build(name)
    
    cmd = f"{cfg['binary']} {args}".strip()
    print(f"Running: {cmd}")
    rc, out, err = run(cmd, path)
    if out:
        print(out)
    if err:
        print(err)

def cmd_tag(name: str, version: str):
    """Tag current version."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    
    if not path.exists():
        print(f"Tool not cloned: {path}")
        return
    
    tag = f"{name}-v{version}"
    changelog = get_changelog(path)
    
    # Write changelog to temp file
    desc_file = Path("/tmp/tag_desc.txt")
    desc_file.write_text(f"Version {version}\n\n{changelog}")
    
    rc, out, err = run(f"git tag -a {tag} -F {desc_file}", path)
    if rc == 0:
        print(f"Tagged {name} as {tag}")
        print(f"\n{changelog}")
    else:
        print(f"Failed: {err}")

def cmd_pick(name: str):
    """Interactive version picker."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    
    if not path.exists():
        print(f"Tool not cloned: {path}")
        return
    
    current = get_version(path)
    print(f"\n{name} — current: {current}\n")
    
    rc, out, _ = run("git tag -l", path)
    if rc == 0 and out.strip():
        tags = sorted(out.strip().split("\n"))
        for i, tag in enumerate(tags, 1):
            marker = " * " if tag == current else "   "
            print(f"  {i}. {tag}{marker}")
        
        try:
            choice = input("\nVersion (number or 'q'): ").strip()
            if choice.lower() == 'q':
                return
            idx = int(choice) - 1
            if 0 <= idx < len(tags):
                print(f"\nSwitching to {tags[idx]}...")
                run(f"git checkout {tags[idx]}", path)
                cmd_build(name)
        except (ValueError, EOFError):
            pass
    else:
        print("No versions tagged yet")

def cmd_diff(name: str):
    """Show changes from upstream."""
    tools = discover_tools()
    
    if name not in tools:
        print(f"Unknown tool: {name}")
        return
    
    cfg = tools[name]
    path = cfg["path"]
    
    if not path.exists():
        print(f"Tool not cloned: {path}")
        return
    
    # Check for uncommitted changes
    rc, out, _ = run("git diff", path)
    if out.strip():
        print(f"\nUncommitted changes in {name}:")
        print(out)
    else:
        print(f"\nNo uncommitted changes in {name}")

# ──────────────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) < 2:
        cmd_list()
        return
    
    tool = sys.argv[1].lower()
    
    # Handle --help
    if tool in ("-h", "--help", "help"):
        print(__doc__)
        return
    
    # Handle list
    if tool == "list":
        cmd_list()
        return
    
    # Check if tool exists
    tools = discover_tools()
    if tool not in tools:
        print(f"Unknown tool: {tool}")
        print(f"Available: {', '.join(sorted(tools.keys()))}")
        return
    
    # Handle tool actions
    action = sys.argv[2].lower() if len(sys.argv) > 2 else "info"
    
    if action == "info" or len(sys.argv) == 2:
        cmd_info(tool)
    elif action == "build":
        cmd_build(tool)
    elif action == "clean":
        cmd_clean(tool)
    elif action == "run":
        args = " ".join(sys.argv[3:])
        cmd_run(tool, args)
    elif action == "tag" and len(sys.argv) > 3:
        cmd_tag(tool, sys.argv[3])
    elif action == "pick":
        cmd_pick(tool)
    elif action == "diff":
        cmd_diff(tool)
    else:
        print(f"Unknown action: {action}")
        cmd_info(tool)

if __name__ == "__main__":
    main()
