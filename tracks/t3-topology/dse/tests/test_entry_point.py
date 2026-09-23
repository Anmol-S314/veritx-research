"""Entry-point qualification tests — veritx CLI registration and packaging.

These tests qualify the REAL configured metadata target, not a literal TOML
string: the configured ``module:callable`` is parsed, the module is imported
dynamically, the callable is resolved and asserted callable. The old broken
``veritx_dse.cli:main`` arrangement fails this test because
``veritx_dse.cli`` exposes no ``main``.

An isolated offline install (local wheel into a temporary virtual
environment, no network) additionally proves that the generated console
script actually runs ``veritx --help``.
"""
from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

DSE_DIR = Path(__file__).parent.parent  # dse/
_EXPECTED_ENTRY_POINT = "veritx_dse.cli.cli:main"


def _configured_entry_point() -> str:
    """The ``project.scripts.veritx`` target from the project metadata."""
    toml_path = DSE_DIR / "pyproject.toml"
    with open(toml_path, "rb") as handle:
        data = tomllib.load(handle)
    scripts = data["project"]["scripts"]
    assert "veritx" in scripts, "veritx console script is not registered"
    return scripts["veritx"]


def _split_entry_point(configured: str) -> tuple[str, str]:
    module_name, separator, callable_name = configured.partition(":")
    assert separator == ":", f"entry point {configured!r} is not module:callable"
    assert module_name and callable_name, \
        f"entry point {configured!r} is not module:callable"
    return module_name, callable_name


# ── package import tests ────────────────────────────────────────────────────

class TestPackageImport:
    """veritx_dse package is importable."""

    def test_import_veritx_dse(self):
        import veritx_dse
        assert hasattr(veritx_dse, "__version__")
        assert veritx_dse.__version__ == "0.3.0"

    def test_import_cli_main(self):
        """The real CLI main() function is importable and callable."""
        from veritx_dse.cli.cli import main
        assert callable(main)

    def test_import_compile_model(self):
        from veritx_dse.model.compile_model import (
            CompileRequest, Workload, Agent, NocConfig,
            validate, derive_topology_spec, derive_vc_assignment,
            verify_design, generate_artifacts,
        )
        assert callable(validate)
        assert callable(derive_topology_spec)

    def test_import_reports(self):
        from veritx_dse.reports.reports import generate_report
        assert callable(generate_report)

    def test_import_artifact(self):
        from veritx_dse.reports.artifact import (
            DesignManifest, sign_manifest, verify_manifest)
        assert callable(sign_manifest)

    def test_import_uvm_gen(self):
        from veritx_dse.verification.uvm_gen import generate_uvm
        assert callable(generate_uvm)


# ── pyproject.toml validation ───────────────────────────────────────────────

class TestPyprojectToml:
    """pyproject.toml has all required sections."""

    @pytest.fixture(autouse=True)
    def load_toml(self):
        with open(DSE_DIR / "pyproject.toml", "rb") as handle:
            self.data = tomllib.load(handle)

    def test_build_system_exists(self):
        bs = self.data["build-system"]
        assert "requires" in bs
        assert "build-backend" in bs
        assert "setuptools" in str(bs["requires"])

    def test_project_metadata(self):
        proj = self.data.get("project", {})
        assert proj.get("name") == "veritx"
        assert proj.get("version") == "0.3.0"
        assert len(proj.get("description", "")) > 10

    def test_project_requires_python(self):
        proj = self.data.get("project", {})
        assert "3.10" in proj["requires-python"]

    def test_entry_point_registered(self):
        scripts = self.data["project"]["scripts"]
        assert scripts["veritx"] == _EXPECTED_ENTRY_POINT

    def test_pytest_config(self):
        cfg = self.data["tool"]["pytest"]["ini_options"]
        assert "tests" in cfg["testpaths"]

    def test_coverage_config(self):
        assert "veritx_dse" in self.data["tool"]["coverage"]["run"]["source"]

    def test_setuptools_packages(self):
        find = self.data["tool"]["setuptools"]["packages"]["find"]
        assert any("veritx_dse" in p for p in find["include"])


# ── dynamic entry-point qualification ───────────────────────────────────────

class TestEntryPointQualification:
    """The configured metadata target must import and resolve to a callable."""

    def test_configured_entry_point_resolves_dynamically(self):
        """Resolve the configured target itself; the broken arrangement fails."""
        module_name, callable_name = _split_entry_point(
            _configured_entry_point())
        module = importlib.import_module(module_name)
        target = getattr(module, callable_name)
        assert callable(target)

    def test_configured_entry_point_is_not_the_broken_package_level_import(self):
        module_name, _callable_name = _split_entry_point(
            _configured_entry_point())
        assert module_name != "veritx_dse.cli"
        package = importlib.import_module("veritx_dse.cli")
        assert not hasattr(package, "main"), (
            "veritx_dse.cli must stay a lightweight package; the console "
            "script must target veritx_dse.cli.cli:main")


# ── CLI invocation tests (python -m) ───────────────────────────────────────

class TestCLIInvocation:
    """veritx CLI can be invoked and responds correctly."""

    @staticmethod
    def _run(*args):
        return subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", *args],
            capture_output=True, text=True, timeout=30,
            cwd=str(DSE_DIR.parent),
            env={**os.environ, "PYTHONPATH": str(DSE_DIR)},
        )

    def test_veritx_help(self):
        result = self._run("--help")
        assert result.returncode == 0
        assert "veritx" in result.stdout.lower()
        assert "usage" in result.stdout.lower()

    def test_veritx_version_in_help(self):
        result = self._run("--help")
        assert "0.3.0" in result.stdout

    def test_veritx_banner_shown(self):
        result = self._run("--help")
        assert "_ _" in result.stdout or "VeritX" in result.stdout

    def test_all_subcommands_have_help(self):
        for cmd in ["trace", "synthesize", "evaluate", "certify", "run",
                    "sweep", "compare", "pareto", "compile", "init",
                    "generate"]:
            result = self._run(cmd, "--help")
            assert result.returncode == 0, \
                f"'veritx {cmd} --help' failed (exit {result.returncode})"

    def test_veritx_json_flag(self):
        assert self._run("--json", "trace", "--help").returncode == 0

    def test_veritx_verbose_flag(self):
        assert self._run("--verbose", "trace", "--help").returncode == 0

    def test_veritx_seed_flag(self):
        assert self._run("--seed", "42", "trace", "--help").returncode == 0

    def test_veritx_no_args_shows_help(self):
        result = self._run()
        assert result.returncode == 0 or "usage" in result.stdout.lower()

    def test_veritx_unknown_command_shows_error(self):
        result = self._run("nonexistent-cmd")
        assert result.returncode != 0 \
            or "error" in (result.stdout + result.stderr).lower()


# ── installed console-script qualification (offline, isolated) ─────────────

class TestInstalledConsoleScript:
    """Build the local wheel and run the generated ``veritx`` console script.

    Everything is local: the wheel is built with the hermetic interpreter's
    setuptools (``--no-index --no-build-isolation``) and installed into a
    temporary virtual environment with no network access.
    """

    @pytest.fixture(scope="class")
    def installed_venv(self, tmp_path_factory) -> Path:
        tmp = tmp_path_factory.mktemp("veritx-console")
        # Build from a throwaway copy so test runs never write build
        # artifacts (``*.egg-info``) into the canonical source tree.
        project = tmp / "project"
        project.mkdir()
        shutil.copy2(DSE_DIR / "pyproject.toml", project / "pyproject.toml")
        shutil.copy2(DSE_DIR / "README.md", project / "README.md")
        shutil.copytree(
            DSE_DIR / "veritx_dse", project / "veritx_dse",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        wheels = tmp / "wheels"
        wheels.mkdir()
        build = subprocess.run(
            [sys.executable, "-m", "pip", "wheel", "--no-index",
             "--no-build-isolation", "--no-deps", "-w", str(wheels),
             str(project)],
            capture_output=True, text=True, timeout=600)
        assert build.returncode == 0, build.stderr
        wheel = next(wheels.glob("veritx-*.whl"))
        venv_dir = tmp / "venv"
        created = subprocess.run(
            [sys.executable, "-m", "venv", str(venv_dir)],
            capture_output=True, text=True, timeout=300)
        assert created.returncode == 0, created.stderr
        installed = subprocess.run(
            [sys.executable, "-m", "pip", "--python",
             str(venv_dir / "bin" / "python"), "install", "--no-index",
             "--no-deps", "--quiet", str(wheel)],
            capture_output=True, text=True, timeout=300)
        assert installed.returncode == 0, installed.stderr
        return venv_dir

    def test_generated_script_targets_the_configured_callable(
            self, installed_venv):
        script = (installed_venv / "bin" / "veritx").read_text()
        module_name, callable_name = _split_entry_point(
            _configured_entry_point())
        assert f"from {module_name} import {callable_name}" in script
        assert "from veritx_dse.cli import main" not in script

    def test_installed_veritx_help_exits_zero(self, installed_venv):
        result = subprocess.run(
            [str(installed_venv / "bin" / "veritx"), "--help"],
            capture_output=True, text=True, timeout=60)
        assert result.returncode == 0, result.stderr
        output = (result.stdout + result.stderr).lower()
        assert "veritx" in output
        assert "usage" in output
        assert "compile" in output  # a stable top-level command

    def test_installed_package_is_used_not_the_worktree(self, installed_venv):
        result = subprocess.run(
            [str(installed_venv / "bin" / "python"), "-c",
             "import veritx_dse, pathlib; "
             "print(pathlib.Path(veritx_dse.__file__).resolve())"],
            capture_output=True, text=True, timeout=60, cwd=str(installed_venv))
        assert result.returncode == 0, result.stderr
        assert str(installed_venv) in result.stdout
        assert str(DSE_DIR) not in result.stdout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
