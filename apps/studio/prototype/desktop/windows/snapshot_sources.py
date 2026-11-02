"""Pin exact producer inputs in a separate local Git repo, never the worktree.

A dirty producer is deliberately not relabelled clean. Rebuild from this new,
committed input snapshot; record its own revision and retain origin facts. No
original repository branch, index or commit is changed by this operation.
"""
from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOTS = {
    "booksim": ("third_party/booksim2",),
    "astra": ("third_party/astra-sim", "third_party/booksim2"),
    "ramulator": ("third_party/ramulator2",),
}
EXCLUDE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", "*.o", "*.obj",
    "*.d", "*.a", "*.so", "*.pyd", "*.dll", "*.exe", "*.build-manifest.json",
    "node_modules", "results", "runs", "booksim", "AstraSim_BookSim2")


def snapshot(repo: Path, parent: Path, producer: str) -> Path:
    roots = ROOTS[producer]
    parent.mkdir(parents=True, exist_ok=True)
    target = Path(tempfile.mkdtemp(prefix=f"{producer}-sources-", dir=parent))
    for relative in roots:
        source = repo / relative

        def ignore(directory, names):
            ignored = set(EXCLUDE(directory, names))
            # ASTRA's root build/ contains the CMake recipe, not just outputs.
            if "build" in names and Path(directory) != repo / "third_party/astra-sim":
                ignored.add("build")
            return ignored

        shutil.copytree(source, target / relative, ignore=ignore)
    recipes = ["snapshot_sources.py", f"build_{producer}.sh"]
    if producer == "ramulator":
        recipes.append("build_ramulator_binding.sh")
    # Recipe scripts may live only in the caller's checkout when the producer
    # revision is pinned through an older worktree.
    import os
    recipe_repo = Path(os.environ.get("SNAPSHOT_RECIPE_REPO") or repo)
    for name in recipes:
        relative = Path("apps/studio/prototype/desktop/windows") / name
        (target / relative).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(recipe_repo / relative, target / relative)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    status = subprocess.check_output(["git", "status", "--porcelain", "--", *roots], cwd=repo, text=True)
    (target / "SOURCE_ORIGIN.json").write_text(json.dumps({
        "origin_revision": revision, "origin_producer_dirty": bool(status),
        "producer_paths": roots,
        "note": "Independent build input snapshot, not an upstream qualification claim",
    }, indent=2) + "\n", encoding="utf-8")
    # Stable timestamp: identical snapshot contents produce an identical commit.
    date = subprocess.check_output(["git", "show", "-s", "--format=%cI", "HEAD"], cwd=repo, text=True).strip()
    import os
    env = {key: value for key, value in os.environ.items() if key not in {
        "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"}}
    env.update(GIT_AUTHOR_DATE=date, GIT_COMMITTER_DATE=date)
    subprocess.run(["git", "init", "-q"], cwd=target, env=env, check=True)
    subprocess.run(["git", "add", "."], cwd=target, env=env, check=True)
    subprocess.run(["git", "-c", "user.name=Srota build snapshot", "-c",
                    "user.email=build@localhost", "-c", "commit.gpgsign=false",
                    "-c", "core.hooksPath=/dev/null", "commit", "-q", "-m",
                    f"build: pin {producer} Windows inputs"], cwd=target, env=env, check=True)
    if subprocess.check_output(["git", "status", "--porcelain"], cwd=target, env=env, text=True).strip():
        raise RuntimeError("producer snapshot is not clean")
    return target


if __name__ == "__main__":
    print(snapshot(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), sys.argv[3]))
