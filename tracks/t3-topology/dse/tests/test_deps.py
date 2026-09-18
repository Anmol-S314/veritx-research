"""Contract tests for the runtime dependency self-check (core.deps).

Seam: declared metadata (dse/pyproject.toml) vs the interpreter. The CLI
fails fast at startup when a declared third-party dist is missing, before
any simulation burns time — this pins that contract without running sims.
"""
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.deps import (
    _naive_project_dependencies,
    declared_dependencies,
    missing_distributions,
)


class TestDeclaredDependencies:
    def test_parses_real_pyproject(self):
        deps = declared_dependencies()
        assert isinstance(deps, list) and len(deps) >= 1
        assert any(d.startswith("pydantic") for d in deps)

    def test_naive_parser_agrees_with_tomllib(self):
        text = (DSE / "pyproject.toml").read_text()
        assert _naive_project_dependencies(text) == declared_dependencies()

    def test_missing_file_is_noop_not_crash(self, tmp_path):
        assert declared_dependencies(tmp_path / "nope.toml") == []

    def test_naive_parser_ignores_comments_and_sections(self):
        text = (
            "[project]\n"
            'name = "x"  # trailing comment\n'
            "dependencies = [\n"
            '    "a>=1",  # pinned\n'
            '    "b",\n'
            "]\n"
            "[other]\n"
            'dependencies = ["not-this"]\n'
        )
        assert _naive_project_dependencies(text) == ["a>=1", "b"]


class TestMissingDistributions:
    def test_satisfied_dist_not_reported(self):
        assert missing_distributions(["pip>=1"]) == []

    def test_bogus_dist_reported_verbatim(self):
        assert missing_distributions(["no-such-dist-xyz>=1.0"]) == [
            "no-such-dist-xyz>=1.0"]

    def test_mixed_list_reports_only_missing(self):
        out = missing_distributions(["pip>=1", "no-such-dist-xyz>=1.0"])
        assert out == ["no-such-dist-xyz>=1.0"]

    def test_false_marker_skipped(self):
        out = missing_distributions(
            ['no-such-dist-xyz>=1.0; sys_platform == "win32-only"'])
        assert out == []

    def test_declared_metadata_satisfied_here(self):
        # In the dev/CI interpreter every declared dep is installed; the
        # startup check must be silent (no false alarm on a healthy env).
        assert missing_distributions() == []


class TestCliFailsFast:
    def test_missing_dep_exits_nonzero_before_work(self, monkeypatch,
                                                   capsys):
        """A missing dist aborts main() with nonzero exit, running nothing."""
        import veritx_dse.cli.cli as cli_mod
        import veritx_dse.core.deps as deps_mod
        # main() imports the check lazily from core.deps: patch the source.
        monkeypatch.setattr(deps_mod, "missing_distributions",
                            lambda: ["no-such-dist-xyz>=1.0"])
        monkeypatch.setattr(sys, "argv", ["veritx", "--list-commands"])
        with pytest.raises(SystemExit) as exc:
            cli_mod.main()
        assert exc.value.code != 0
        out = capsys.readouterr()
        assert "no-such-dist-xyz" in (out.out + out.err)

    def test_healthy_env_reaches_list_commands(self, monkeypatch, capsys):
        """With deps satisfied, --list-commands still exits 0 (no regression)."""
        import veritx_dse.cli.cli as cli_mod
        monkeypatch.setattr(sys, "argv", ["veritx", "--list-commands"])
        cli_mod.main()  # returns normally; raises nothing
        import json
        out = capsys.readouterr()
        assert json.loads(out.out)[0]["name"] == "trace" or "trace" in out.out
