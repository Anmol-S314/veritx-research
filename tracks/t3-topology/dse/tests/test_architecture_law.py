"""tests/test_architecture_law.py — the dependency DAG, enforced.

Slice 2b established ownership:

    core  <-  model  <-  workload
    verification -> core/model/workload
    backend      -> core/model/workload (+ verification gates)
    application  -> everything (orchestration)

These guards fail if future code reintroduces a backwards dependency or a
historical package path. They are AST-based, not grep-based: an import
mentioned in a docstring or a comment must not fail the build, and an
import inside a function must still be caught.
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
PKG = DSE / "veritx_dse"
sys.path.insert(0, str(DSE))


def _imports(path: Path) -> set[str]:
    """Every module named by an import in the file (AST, all scopes)."""
    tree = ast.parse(path.read_text())
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative: resolve against the package
                parts = list(path.relative_to(PKG).parts[:-1])
                base = parts[:len(parts) - (node.level - 1)] if node.level > 1 \
                    else parts
                found.add("veritx_dse." + ".".join(base + [node.module or ""]))
            elif node.module:
                found.add(node.module)
    return found


def _python_files(subdir: str) -> list[Path]:
    return sorted(p for p in (PKG / subdir).rglob("*.py")
                  if "__pycache__" not in str(p))


def _violations(subdir: str, forbidden: tuple[str, ...]) -> list[str]:
    bad = []
    for path in _python_files(subdir):
        for mod in _imports(path):
            if any(mod == f or mod.startswith(f + ".")
                   for f in forbidden):
                bad.append(f"{path.relative_to(DSE)} imports {mod}")
    return bad


class TestDependencyLaw:
    def test_model_does_not_import_upward(self):
        bad = _violations("model", ("veritx_dse.verification",
                                    "veritx_dse.backend",
                                    "veritx_dse.application",
                                    "veritx_dse.workload"))
        assert bad == [], bad

    def test_workload_does_not_import_upward(self):
        bad = _violations("workload", ("veritx_dse.verification",
                                       "veritx_dse.backend",
                                       "veritx_dse.application"))
        assert bad == [], bad

    def test_verification_does_not_import_backend_or_application(self):
        bad = _violations("verification", ("veritx_dse.backend",
                                           "veritx_dse.application"))
        assert bad == [], bad

    def test_core_imports_nothing_from_the_domain(self):
        """core is the bottom of the DAG.

        KNOWN_UPWARD below are pre-existing legacy edges (research stack,
        Phase 9-16), not products of slice 2b. They are listed rather than
        ignored: the assertion is set EQUALITY, so a new upward import
        fails AND a silently-fixed one fails too (the list must stay
        truthful). Resolving them is slice 5's job, because they follow
        from where MemoryArtifact/CanonicalWorkload/spec live today.
        """
        bad = set(_violations("core", ("veritx_dse.model",
                                       "veritx_dse.workload",
                                       "veritx_dse.verification",
                                       "veritx_dse.backend",
                                       "veritx_dse.application")))
        known = {
            "veritx_dse/core/comparison.py imports veritx_dse.workload.serve",
            "veritx_dse/core/doctor.py imports veritx_dse.model",
            "veritx_dse/core/experiment.py imports veritx_dse.model.presets",
            "veritx_dse/core/experiment_serving.py imports "
            "veritx_dse.workload.serve",
            "veritx_dse/core/spec.py imports veritx_dse.model.presets",
        }
        assert bad == known, {
            "new": sorted(bad - known), "fixed_but_still_listed":
            sorted(known - bad)}


class TestHistoricalPackageIsGone:
    def test_no_production_import_of_the_wave_package(self):
        bad = []
        for path in sorted(PKG.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for mod in _imports(path):
                if mod == "veritx_dse.waved" or \
                        mod.startswith("veritx_dse.waved."):
                    bad.append(f"{path.relative_to(DSE)} imports {mod}")
        assert bad == [], bad

    def test_the_package_directory_does_not_exist(self):
        assert not (PKG / "waved").exists(), \
            "veritx_dse/waved must not come back as a compatibility layer"

    def test_the_modules_landed_in_their_owners(self):
        for mod in ("veritx_dse.model.parallelism",
                    "veritx_dse.model.resolved_bundle",
                    "veritx_dse.workload.graph",
                    "veritx_dse.workload.semantics",
                    "veritx_dse.workload.operations",
                    "veritx_dse.workload.messages",
                    "veritx_dse.workload.traffic",
                    "veritx_dse.workload.collectives",
                    "veritx_dse.verification.reference_semantics",
                    "veritx_dse.verification.gates"):
            __import__(mod)


class TestOracleIndependence:
    """The F1 defect: production must not derive from the reference."""

    def test_production_never_imports_the_reference_module(self):
        bad = _violations("model", ("veritx_dse.verification",))
        bad += _violations("workload", ("veritx_dse.verification",))
        assert bad == [], bad

    def test_reference_module_does_not_import_production_artifacts(self):
        """A reference implemented with production code is not a reference."""
        offenders = [m for m in _imports(
            PKG / "verification/reference_semantics.py")
            if m.startswith(("veritx_dse.workload", "veritx_dse.model"))]
        # lazy imports inside verifier FUNCTIONS are allowed (the verifier
        # inspects an artifact); module-level production imports are not.
        src = (PKG / "verification/reference_semantics.py").read_text()
        head = src.split("def ", 1)[0]
        module_level = [line for line in head.splitlines()
                        if line.startswith(("import ", "from "))]
        assert not any("workload" in line or "model" in line
                       for line in module_level), module_level
        _ = offenders
