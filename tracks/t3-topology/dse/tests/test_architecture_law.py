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
import hashlib
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
PKG = DSE / "veritx_dse"
REPO = DSE.parents[2]
REFERENCE = REPO / "reference" / "target-architecture"
REFERENCE_IMPORT_PREFIXES = ("veritx_target", "target_architecture",
                             "reference.target_architecture")
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
        """A reference implemented with production code is not a reference.

        AST, not text: only TRUE TOP-LEVEL import statements count. The
        previous version scanned source text before the first ``def`` and
        then discarded its own AST findings, so a module-level import
        placed after the first function would have bypassed it.
        Imports nested INSIDE a verifier function are allowed: the
        verifier inspects an artifact, and the artifact must never be able
        to import the reference back.
        """
        path = PKG / "verification/reference_semantics.py"
        tree = ast.parse(path.read_text())
        module_level: list[str] = []
        for node in tree.body:  # top level ONLY
            if isinstance(node, ast.Import):
                module_level.extend(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                module_level.append(node.module or "")
        assert module_level, "expected at least one module-level import"
        offenders = [
            m for m in module_level
            if m.startswith(("veritx_dse.model", "veritx_dse.workload",
                             "veritx_dse.backend", "veritx_dse.application"))
        ]
        assert offenders == [], offenders


class TestTargetArchitectureReferenceIsNotRuntime:
    """The frozen North Star is a specification, not a runtime dependency.

    ``reference/target-architecture`` carries a src-layout package that is
    ALSO named ``veritx_dse``: the destination has the same package name as
    the repository being cut over to it. If its ``src/`` ever reached
    ``sys.path`` it would shadow production silently, so the boundary is
    asserted here instead of trusted. See ``docs/VERITX-NORTH-STAR.md``.
    """

    def test_production_never_imports_the_reference_tree(self):
        bad = []
        for path in sorted(PKG.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            for mod in _imports(path):
                if any(mod == f or mod.startswith(f + ".")
                       for f in REFERENCE_IMPORT_PREFIXES):
                    bad.append(f"{path.relative_to(DSE)} imports {mod}")
            if "reference/target-architecture" in path.read_text():
                bad.append(f"{path.relative_to(DSE)} names the reference path")
        assert bad == [], bad

    def test_reference_src_is_not_on_sys_path(self):
        offenders = []
        for entry in sys.path:
            if not entry:
                continue
            resolved = Path(entry).resolve()
            if resolved == REFERENCE / "src" or REFERENCE in resolved.parents:
                offenders.append(str(resolved))
        assert offenders == [], offenders

    def test_importable_package_is_the_production_one(self):
        import veritx_dse
        resolved = Path(veritx_dse.__file__).resolve()
        assert PKG.resolve() in resolved.parents, (
            f"veritx_dse resolved to {resolved}, outside {PKG}; the "
            "reference tree may be shadowing production")

    def test_reference_manifest_verifies_when_present(self):
        manifest = REFERENCE / "MANIFEST.sha256"
        if not manifest.exists():
            pytest.skip("reference tree is not present on this branch")
        bad = []
        for line in manifest.read_text().splitlines():
            digest, _, rel = line.partition("  ")
            target = REFERENCE / rel.removeprefix("./")
            if not target.exists():
                bad.append(f"missing {rel}")
            elif hashlib.sha256(target.read_bytes()).hexdigest() != digest:
                bad.append(f"digest mismatch {rel}")
        assert bad == [], bad


class TestP1CompilerAuthority:
    """P1.1: one product CompileRequest, one resolved-topology authority.

    TopologyArtifact is the authoritative resolved hardware topology;
    TopologyIR is interchange only. The product orchestrator
    (application/compile.py) must not depend on the IR for resolved
    semantics, and the candidate-evaluation request must never again
    be namable as a CompileRequest.
    """

    def test_orchestrator_does_not_import_topology_ir(self):
        bad = []
        for mod in _imports(PKG / "application/compile.py"):
            if mod == "veritx_dse.model.topology_ir" or \
                    mod.startswith("veritx_dse.model.topology_ir."):
                bad.append(mod)
        assert bad == [], bad

    def test_no_second_compile_request_class(self):
        """Exactly one request class is NAMED CompileRequest, and it is
        the E1–E5 product request. (CompileRequestSchemaError is its
        error type, not a request.)"""
        found = []
        for path in sorted(PKG.rglob("*.py")):
            if "__pycache__" in str(path):
                continue
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and \
                        node.name == "CompileRequest":
                    found.append(
                        f"{path.relative_to(DSE)}:{node.name}")
        assert found == [
            "veritx_dse/model/compile_model.py:CompileRequest"], found

    def test_evaluator_seam_has_no_compile_names(self):
        import veritx_dse.synthesis.compiler as evaluator
        assert hasattr(evaluator, "CandidateEvaluationRequest")
        assert hasattr(evaluator, "evaluate_candidates")
        assert not hasattr(evaluator, "CompilerRequest")
        assert not hasattr(evaluator, "compile_fabric")
