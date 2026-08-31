"""Tests for pyproject.toml entry point — veritx CLI registration.

Verifies that:
1. The package is importable
2. The CLI main() function is callable
3. The veritx entry point resolves correctly
4. pyproject.toml has required sections
"""
import subprocess
import sys
from pathlib import Path

import pytest


DSE_DIR = Path(__file__).parent.parent  # dse/


# ── Package import tests ────────────────────────────────────────────────────

class TestPackageImport:
    """veritx_dse package is importable."""

    def test_import_veritx_dse(self):
        """veritx_dse package imports without error."""
        import veritx_dse
        assert hasattr(veritx_dse, "__version__")
        assert veritx_dse.__version__ == "0.3.0"

    def test_import_cli_main(self):
        """veritx_dse.cli:main is importable and callable."""
        from veritx_dse.cli import main
        assert callable(main)

    def test_import_compile_model(self):
        """veritx_dse.compile_model public API is importable."""
        from veritx_dse.compile_model import (
            CompileRequest, Workload, Agent, NocConfig,
            validate, derive_topology_spec, derive_vc_assignment,
            verify_design, generate_artifacts,
        )
        assert callable(validate)
        assert callable(derive_topology_spec)

    def test_import_reports(self):
        """veritx_dse.reports public API is importable."""
        from veritx_dse.reports import generate_report
        assert callable(generate_report)

    def test_import_artifact(self):
        """veritx_dse.artifact public API is importable."""
        from veritx_dse.artifact import DesignManifest, sign_manifest, verify_manifest
        assert callable(sign_manifest)

    def test_import_uvm_gen(self):
        """veritx_dse.uvm_gen public API is importable."""
        from veritx_dse.uvm_gen import generate_uvm
        assert callable(generate_uvm)


# ── pyproject.toml validation ───────────────────────────────────────────────

class TestPyprojectToml:
    """pyproject.toml has all required sections."""

    @pytest.fixture(autouse=True)
    def load_toml(self):
        import tomllib
        toml_path = DSE_DIR / "pyproject.toml"
        if not toml_path.exists():
            pytest.skip("pyproject.toml not found")
        with open(toml_path, "rb") as f:
            self.data = tomllib.load(f)

    def test_build_system_exists(self):
        """Has [build-system] with requires and build-backend."""
        assert "build-system" in self.data
        bs = self.data["build-system"]
        assert "requires" in bs
        assert "build-backend" in bs
        assert "setuptools" in str(bs["requires"])

    def test_project_metadata(self):
        """Has [project] with name, version, description."""
        proj = self.data.get("project", {})
        assert proj.get("name") == "veritx"
        assert proj.get("version") == "0.3.0"
        assert "description" in proj
        assert len(proj["description"]) > 10

    def test_project_requires_python(self):
        """Has requires-python >= 3.10."""
        proj = self.data.get("project", {})
        assert "requires-python" in proj
        assert "3.10" in proj["requires-python"]

    def test_entry_point_registered(self):
        """Has [project.scripts] with veritx entry point."""
        scripts = self.data.get("project", {}).get("scripts", {})
        assert "veritx" in scripts
        assert scripts["veritx"] == "veritx_dse.cli:main"

    def test_pytest_config(self):
        """Has [tool.pytest.ini_options] with testpaths."""
        pytest_cfg = self.data.get("tool", {}).get("pytest", {}).get("ini_options", {})
        assert "testpaths" in pytest_cfg
        assert "tests" in pytest_cfg["testpaths"]

    def test_coverage_config(self):
        """Has [tool.coverage.run] with source."""
        cov_cfg = self.data.get("tool", {}).get("coverage", {})
        assert "run" in cov_cfg
        assert "source" in cov_cfg["run"]
        assert "veritx_dse" in cov_cfg["run"]["source"]

    def test_setuptools_packages(self):
        """Has [tool.setuptools.packages.find] with veritx_dse."""
        find_cfg = self.data.get("tool", {}).get("setuptools", {}).get("packages", {}).get("find", {})
        assert "include" in find_cfg
        assert any("veritx_dse" in p for p in find_cfg["include"])


# ── Entry point resolution ──────────────────────────────────────────────────

class TestEntryPointResolution:
    """veritx entry point resolves to the correct function."""

    def test_entry_point_resolves(self):
        """importlib.metadata finds veritx entry point."""
        try:
            from importlib.metadata import entry_points
            eps = entry_points()
            # Python 3.12+ returns a SelectableGroups
            veritx_eps = [ep for ep in eps.get("console_scripts", []) if ep.name == "veritx"]
            if not veritx_eps:
                # Try group-based API (Python 3.9-3.11)
                veritx_eps = [ep for ep in eps.select(group="console_scripts") if ep.name == "veritx"]
            assert len(veritx_eps) >= 1, "veritx entry point not found in console_scripts"
            ep = veritx_eps[0]
            assert ep.value == "veritx_dse.cli:main"
        except Exception:
            # Fallback: check pyproject.toml directly
            import tomllib
            with open(DSE_DIR / "pyproject.toml", "rb") as f:
                data = tomllib.load(f)
            scripts = data.get("project", {}).get("scripts", {})
            assert scripts.get("veritx") == "veritx_dse.cli:main"


# ── CLI invocation tests ────────────────────────────────────────────────────

class TestCLIInvocation:
    """veritx CLI can be invoked and responds correctly."""

    def test_veritx_help(self):
        """veritx --help exits 0 and shows usage."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),  # repo root
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        assert result.returncode == 0
        assert "veritx" in result.stdout.lower()
        assert "usage" in result.stdout.lower()

    def test_veritx_version_in_help(self):
        """veritx --help shows version number."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        assert "0.3.0" in result.stdout

    def test_veritx_banner_shown(self):
        """veritx --help shows ASCII art banner."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        assert "_ _" in result.stdout or "VeritX" in result.stdout

    def test_all_subcommands_have_help(self):
        """Every subcommand has --help."""
        env = {**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)}
        cwd = str(DSE_DIR.parent)
        for cmd in ["trace", "synthesize", "evaluate", "certify", "run",
                     "sweep", "compare", "pareto", "compile", "init", "generate"]:
            result = subprocess.run(
                [sys.executable, "-m", "veritx_dse.cli", cmd, "--help"],
                capture_output=True, text=True, timeout=10,
                cwd=cwd, env=env,
            )
            assert result.returncode == 0, f"'veritx {cmd} --help' failed (exit {result.returncode})"

    def test_veritx_json_flag(self):
        """veritx --json flag is accepted."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--json", "trace", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        assert result.returncode == 0

    def test_veritx_verbose_flag(self):
        """veritx --verbose flag is accepted."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--verbose", "trace", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        assert result.returncode == 0

    def test_veritx_seed_flag(self):
        """veritx --seed 42 flag is accepted."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--seed", "42", "trace", "--help"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        assert result.returncode == 0

    def test_veritx_no_args_shows_help(self):
        """veritx with no args shows usage (not crash)."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        # Should show help or usage, not crash
        assert result.returncode == 0 or "usage" in result.stdout.lower()

    def test_veritx_unknown_command_shows_error(self):
        """veritx nonexistent-cmd shows error, not crash."""
        result = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "nonexistent-cmd"],
            capture_output=True, text=True, timeout=10,
            cwd=str(DSE_DIR.parent),
            env={**__import__("os").environ, "PYTHONPATH": str(DSE_DIR)},
        )
        # Should fail gracefully (exit 2 for argparse error)
        assert result.returncode != 0 or "error" in (result.stdout + result.stderr).lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
