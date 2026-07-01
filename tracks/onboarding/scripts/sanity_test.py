#!/usr/bin/env python3
"""Onboarding — toolchain validation for all tracks."""
import subprocess, json, sys, os
from pathlib import Path

RESULTS = Path(__file__).parent.parent / "results"

TOOLS = [
    ("python3",   ["--version"]),
    ("make",      ["--version"]),
    ("booksim",   ["--version"]),
    ("yosys",     ["--version"]),
    ("cbmc",      ["--version"]),
    ("sby",       ["--version"]),
]

PYTHON_PACKAGES = ["numpy", "matplotlib", "pandas", "seaborn", "click", "pyyaml"]

def check_tool(name, args):
    try:
        result = subprocess.run([name] + args, capture_output=True, text=True, timeout=10)
        return {"name": name, "found": True, "version": result.stdout[:100].strip(), "error": None}
    except FileNotFoundError:
        return {"name": name, "found": False, "version": None, "error": "not installed"}
    except Exception as e:
        return {"name": name, "found": False, "version": None, "error": str(e)}

def check_py(name):
    try:
        import importlib.metadata
        v = importlib.metadata.version(name)
        return {"package": name, "found": True, "version": v}
    except importlib.metadata.PackageNotFoundError:
        return {"package": name, "found": False, "version": None}
    except Exception:
        return {"package": name, "found": True, "version": "installed"}

def main():
    RESULTS.mkdir(parents=True, exist_ok=True)
    tools = [check_tool(n, a) for n, a in TOOLS]
    pkgs = [check_py(n) for n in PYTHON_PACKAGES]

    missing_tools = [t for t in tools if not t["found"]]
    missing_pkgs = [p for p in pkgs if not p["found"]]

    data = {
        "track": "onboarding",
        "tools": tools,
        "python_packages": pkgs,
        "all_ok": len(missing_tools) == 0 and len(missing_pkgs) == 0,
        "missing_tools": [t["name"] for t in missing_tools],
        "missing_packages": [p["package"] for p in missing_pkgs],
    }

    report = RESULTS / "sanity_result.json"
    with open(report, "w") as f:
        json.dump(data, f, indent=2)

    for t in tools:
        icon = "✓" if t["found"] else "✗"
        print(f"  {icon} {t['name']}: {t['version'] or t['error']}")
    for p in pkgs:
        icon = "✓" if p["found"] else "✗"
        print(f"  {icon} {p['package']}: {p['version'] or 'missing'}")

    if data["all_ok"]:
        print("\n  All tools OK")
    else:
        print(f"\n  ⚠  Missing: tools={data['missing_tools']}  packages={data['missing_packages']}")
        sys.exit(1)

if __name__ == "__main__":
    main()
