# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
import os
import sys
import sysconfig
from PyInstaller.utils.hooks import collect_submodules

prototype = Path(SPECPATH).parent
repo = prototype.parents[2]
# Native packaging stages OS-specific simulator binaries outside the developer
# repository. Its tree mirrors repository-relative paths exactly.
RESOURCES = Path(os.environ.get("SROTA_DESKTOP_RESOURCES", repo)).resolve()
dse = RESOURCES / "tracks/t3-topology/dse"
datas = []
binaries = []


def add_tree(relative, suffixes=None):
    root = RESOURCES / relative
    if not root.is_dir():
        raise SystemExit(f"Missing runtime resources: {root}")
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in {"__pycache__", ".pytest_cache", ".git", "node_modules"} for part in path.parts):
            continue
        if suffixes is None or path.suffix in suffixes:
            datas.append((str(path), str(path.parent.relative_to(RESOURCES))))


# Real .py files preserve existing __file__-based registries and worker launches.
add_tree("tracks/t3-topology/dse/veritx_dse", {".py", ".yaml", ".json"})
for relative in (
    "docs/product", "contracts", "validation/experiments",
    "tracks/t3-topology/examples",
    # The on-disk workload registry: without it load_registry() silently
    # falls back to BUILTIN_WORKLOADS only, so the packaged app hides every
    # registered customer workload while the source tree lists them.
    "tracks/t3-topology/workloads",
    "tracks/t3-topology/dse/inputs", "tracks/t3-topology/dse/models",
    "tracks/t3-topology/dse/qualification",
    # Qualification refuses claims when their durable evidence files are absent.
    "tracks/t3-topology/dse/docs", "tracks/t3-topology/dse/tests",
    # These back the validation and qualification panels; without them the
    # packaged endpoints fail with an internal error.
    "validation/reports",
    "docs/production",
    # The ablation runner resolves its catalog, workload YAMLs and traces
    # against REPO, which is the bundle root when frozen. Without them
    # POST /api/v1/ablations answers 400 "ablation catalog is missing" while
    # the ablation table still renders from the frontend's own copy of the
    # catalog — a feature that looks present and silently refuses to run.
    "third_party/booksim2/src/examples/ai_workloads",
):
    add_tree(relative)

# The frontend bundles public/data itself; the gateway only reads the ablation catalog.
ablation_catalog = RESOURCES / "apps/studio/prototype/public/data/workload_ablation.json"
if not ablation_catalog.is_file():
    raise SystemExit(f"Missing desktop ablation catalog: {ablation_catalog}")
datas.append((str(ablation_catalog), str(ablation_catalog.parent.relative_to(RESOURCES))))

# The ablation runner is a stdlib-only subprocess the gateway launches by path.
_ablation_script = "tracks/t3-topology/scripts/ablate_workloads.py"
if not (RESOURCES / _ablation_script).is_file():
    raise SystemExit(f"Missing ablation runner: {RESOURCES / _ablation_script}")
datas.append((str(RESOURCES / _ablation_script),
              str(Path(_ablation_script).parent)))

# Ship the actual simulator binaries AND their identity manifests, never fake readiness.
for relative in (
    "third_party/booksim2/src/booksim",
    "third_party/astra-sim/astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2",
):
    path = RESOURCES / (relative + (".exe" if sys.platform == "win32" else ""))
    manifest = Path(str(path) + ".build-manifest.json")
    if not path.is_file() or not manifest.is_file():
        raise SystemExit(f"Build the simulator and its manifest first: {path}")
    binaries.append((str(path), str(path.parent.relative_to(RESOURCES))))
    datas.append((str(manifest), str(manifest.parent.relative_to(RESOURCES))))

# Ramulator must match the interpreter used to freeze the gateway.
ramulator = RESOURCES / "third_party/ramulator2/python/ramulator"
extension = ramulator / ("_ramulator" + sysconfig.get_config_var("EXT_SUFFIX"))
if not extension.is_file():
    raise SystemExit(f"Build Ramulator with this Python interpreter first: {extension}")
add_tree("third_party/ramulator2/python/ramulator", {".py", ".json", ".dll", ".pyd"})
binaries.append((str(extension), str(ramulator.relative_to(RESOURCES))))
# The Windows binding links a separate Windows Ramulator DLL; Linux uses one .so.
windows_dll = ramulator / "libramulator.dll"
if windows_dll.is_file():
    binaries.append((str(windows_dll), str(ramulator.relative_to(RESOURCES))))
manifest = Path(str(extension) + ".build-manifest.json")
if not manifest.is_file():
    raise SystemExit(f"Missing Ramulator build provenance: {manifest}")
datas.append((str(manifest), str(manifest.parent.relative_to(RESOURCES))))

# Chakra protobuf schema ships as real files so trace tooling and the native
# binding check can import it from a frozen build.
chakra_root = os.environ.get("SROTA_CHAKRA_ROOT")
if chakra_root:
    package = Path(chakra_root).resolve()
    for path in sorted(package.rglob("*.py")):
        datas.append((str(path), str(Path("chakra") / path.parent.relative_to(package))))

# The ASTRA machine refuses a fabric config it cannot check against the parser
# that will read it. That surface is the vendored parser source, so the frozen
# app must ship it alongside the binary.
for relative in (
    "third_party/booksim2/src/booksim_config.cpp",
    "third_party/booksim2/src/networks/gec.cpp",
    "third_party/booksim2/src/networks/srota.cpp",
):
    path = RESOURCES / relative
    if not path.is_file():
        raise SystemExit(f"Missing runtime parser surface: {path}")
    datas.append((str(path), str(Path(relative).parent)))

analysis = Analysis(
    [str(prototype / "desktop/gateway.py")],
    pathex=[str(dse)] + ([str(Path(chakra_root).resolve().parent)] if chakra_root else []),
    binaries=binaries,
    datas=datas,
    # The numeric stack is NOT shipped. numpy/scipy/scikit-learn/scikit-optimize
    # only ever served four topology-synthesis engines, and those engines (a)
    # have no Studio surface, (b) are undocumented in PRODUCT-API.md, (c) are
    # scheduled for removal by PRODUCT-FLOWS.md PF-D15, and (d) refused every
    # problem above 9 nodes in measurement while never beating the numpy-only
    # engine on objective. They cost ~32 MiB of a 116 MiB package, so the build
    # excludes them and product.vnext.require_engine() refuses those engines with
    # a typed ENGINE_UNAVAILABLE instead of dying on a missing import. Source and
    # CLI installs keep the stack, so local synthesis is unchanged.
    hiddenimports=collect_submodules(
        "veritx_dse",
        filter=lambda name: not any(
            name.endswith(suffix) for suffix in (
                "synthesis.milp_topology_v2", "synthesis.bo_synthesizer",
                "synthesis.iterative_synthesizer", "synthesis.event_objective",
                "tools.deadlock_routing")),
    ) + [
        "uvicorn.logging", "uvicorn.loops.asyncio", "uvicorn.protocols.http.h11_impl",
        "uvicorn.lifespan.on",
    ],
    # Source files are loaded from the preserved repository tree at runtime.
    excludes=[
        "tkinter", "pytest", "IPython", "matplotlib",
        # Optional ML/plotting packages on a developer machine are not gateway dependencies.
        "torch", "transformers", "datasets", "tokenizers", "av", "plotly",
        # The synthesis numeric stack: deliberately absent, see hiddenimports.
        "numpy", "scipy", "sklearn", "skopt",
    ],
)
# One-dir, not one-file: a one-file archive re-extracts this whole tree
# (~250 MB) into a temp directory on every launch, which dominated cold start.
# A one-dir tree is installed as-is and the launcher resolves its own
# _internal directory next to itself, so launch does no extraction at all.
pyz = PYZ(analysis.pure)
exe = EXE(
    pyz, analysis.scripts, [],
    exclude_binaries=True,
    name="srota-gateway", console=True, upx=False,
)
coll = COLLECT(
    exe, analysis.binaries, analysis.datas,
    strip=False, upx=False, name="srota-gateway",
)
