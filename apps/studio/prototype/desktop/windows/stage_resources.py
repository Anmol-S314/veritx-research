"""Stage Windows runtime resources into a repo-relative layout for freezing.

Only files the frozen gateway reads are copied. Simulator binaries must already
carry adjacent build manifests; this refuses to invent or relabel provenance.
"""
from __future__ import annotations

import json
import re
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]
WINDOWS = REPO / "apps/studio/prototype/.desktop-build/windows"
STAGE = WINDOWS / "stage"

DATA_TREES = [
    "docs/product", "contracts", "validation/experiments",
    "tracks/t3-topology/examples",
    # The on-disk workload registry: gateway.spec requires it on Linux, and
    # without it load_registry() falls back to BUILTIN_WORKLOADS only, so the
    # installed app hides every registered customer workload.
    "tracks/t3-topology/workloads",
    "tracks/t3-topology/dse/inputs",
    "tracks/t3-topology/dse/models", "tracks/t3-topology/dse/qualification",
    "tracks/t3-topology/dse/docs", "tracks/t3-topology/dse/tests",
    "validation/reports", "docs/production",
    # The ablation runner resolves its catalog, workload YAMLs and traces
    # against the bundle root; without them POST /ablations answers 400 while
    # the table still renders, i.e. a feature that looks present and silently
    # refuses to run.
    "third_party/booksim2/src/examples",
    # Supported-topology sweep evidence: the frozen gateway reads it on the
    # Knowledge view and its build guard refuses a package without it.
    "tracks/t3-topology/runs/supported-sweep",
]
EXCLUDE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git",
                                "node_modules", "*.o", "*.d", "*.a", "*.so")


def copy_tree(relative: str, suffixes: set[str] | None = None) -> None:
    source = REPO / relative
    if not source.is_dir():
        raise SystemExit(f"missing runtime resource tree: {source}")
    for path in sorted(source.rglob("*")):
        if not path.is_file() or EXCLUDE(str(path.parent), [path.name]):
            continue
        if suffixes is not None and path.suffix not in suffixes:
            continue
        target = STAGE / path.relative_to(REPO)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)


def copy_source(relative: str) -> None:
    """Ship one runtime-read source file (the ASTRA config parser surface)."""
    source = REPO / relative
    if not source.is_file():
        raise SystemExit(f"missing runtime source file: {source}")
    target = STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_file(relative: str) -> None:
    """Ship one runtime file the gateway opens by repository-relative path."""
    source = REPO / relative
    if not source.is_file():
        raise SystemExit(f"missing runtime file: {source}")
    target = STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)


def copy_binary(built: Path, relative: str) -> None:
    if not built.is_file():
        raise SystemExit(f"build Windows simulator first: {built}")
    manifest = Path(str(built) + ".build-manifest.json")
    if not manifest.is_file():
        raise SystemExit(f"missing simulator build provenance: {manifest}")
    target = STAGE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(built, target)
    shutil.copy2(manifest, Path(str(target) + ".build-manifest.json"))


def main() -> int:
    if STAGE.exists():
        shutil.rmtree(STAGE)
    STAGE.mkdir(parents=True)
    copy_tree("tracks/t3-topology/dse/veritx_dse", {".py", ".yaml", ".json"})
    for relative in DATA_TREES:
        copy_tree(relative)
    # Linux's gateway.spec ships these two; the frozen Windows app opens both.
    copy_file("apps/studio/prototype/public/data/workload_ablation.json")
    copy_file("apps/studio/prototype/public/data/design_sensitivity.json")
    # Catalog topologies name their BookSim config, and they live in more than
    # one directory; ship every directory the catalog references.
    catalog = json.loads((REPO / "apps/studio/prototype/public/data/"
                          "workload_ablation.json").read_text())
    for config_dir in sorted({t["config"].rsplit("/", 1)[0]
                              for t in catalog["topologies"]}):
        copy_tree(config_dir)
    # The runner imports its siblings, so the whole directory ships: with only
    # ablate_workloads.py every fabric search failed with "the runner produced no
    # ablation.json" and a ModuleNotFoundError hidden inside the 500 body.
    copy_tree("tracks/t3-topology/scripts", {".py"})
    # Catalog workloads that replay a project trace: take exactly the traces the
    # runner names (runs/studio-store is 3.1 GB of user data and never ships).
    runner = (REPO / "tracks/t3-topology/scripts/ablate_workloads.py").read_text()
    for relative in sorted(set(re.findall(
            r'REPO / "(runs/studio-store/[^"]*workload\.trace)"', runner))):
        copy_file(relative)
    copy_source("third_party/booksim2/src/booksim_config.cpp")
    copy_source("third_party/booksim2/src/networks/gec.cpp")
    copy_source("third_party/booksim2/src/networks/srota.cpp")
    copy_binary(WINDOWS / "booksim/booksim.exe",
                "third_party/booksim2/src/booksim.exe")
    copy_binary(WINDOWS / "astra/AstraSim_BookSim2.exe",
                "third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2.exe")
    binding = WINDOWS / "ramulator-binding/ramulator"
    pyd = next(iter(sorted(binding.glob("_ramulator*.pyd"))), None)
    if pyd is None:
        raise SystemExit(f"build Windows Ramulator bindings first: {binding}")
    relative = "third_party/ramulator2/python/ramulator"
    destination = STAGE / relative
    destination.mkdir(parents=True, exist_ok=True)
    for path in sorted(binding.iterdir()):
        keep = path.is_dir() or (path.is_file() and path.suffix in {".py", ".json", ".pyd", ".dll"})
        if not keep:
            continue
        target = destination / path.name
        if path.is_dir():
            shutil.copytree(path, target, ignore=EXCLUDE)
        else:
            shutil.copy2(path, target)
    print(STAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
