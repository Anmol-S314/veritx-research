"""Wave-C surface tests: cross-surface equivalence + bypass prevention.

One canonical request through Python/CLI/API/T3 must yield identical
semantic identities. Adapters must import the service only — never
backend execution internals (AST-enforced).
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError, ErrorCode,
)
from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.application.surfaces import (  # noqa: E402
    api_intent, cli_intent, python_intent, t3_intent,
)
from veritx_dse.core.paths import REPO  # noqa: E402


def _canonical_doc(**over):
    doc = {
        "schema_version": 1, "name": "cross-surface",
        "fabric_preset": "mesh4", "fabric_overrides": {},
        "workload": {"trace": "tiny2"},
        "backend_target": "BOOKSIM_STANDALONE", "seed": None,
        "metrics": ["sim.latency.avg_cycles", "sim.delivered.packets"],
    }
    doc.update(over)
    return doc


def _needs_binary():
    from veritx_dse.simulation.booksim import (  # noqa: PLC0415
        find_booksim_bin,
    )
    try:
        return Path(find_booksim_bin(REPO))
    except FileNotFoundError:
        pytest.skip("no runnable BookSim binary")


class TestIntentEquivalence:
    def test_four_surfaces_same_intent_id(self, tmp_path):
        doc = _canonical_doc()
        request_file = tmp_path / "req.json"
        request_file.write_text(json.dumps(doc))
        ids = {
            python_intent(dict(doc)).intent_id(),
            api_intent(json.loads(json.dumps(doc))).intent_id(),
            t3_intent(dict(doc)).intent_id(),
            cli_intent(request_file=str(request_file)).intent_id(),
        }
        assert len(ids) == 1

    def test_cli_key_order_irrelevant(self, tmp_path):
        doc = _canonical_doc()
        plain = tmp_path / "plain.json"
        plain.write_text(json.dumps(doc))
        shuffled = tmp_path / "shuffled.json"
        shuffled.write_text(json.dumps(doc, sort_keys=True))
        assert cli_intent(request_file=str(plain)).intent_id() == \
            cli_intent(request_file=str(shuffled)).intent_id()

    def test_t3_forwards_service_commands(self):
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--list-commands"],
            capture_output=True, text=True, timeout=120, cwd=DSE)
        assert proc.returncode == 0, proc.stderr[-500:]
        rows = {r["name"]: r.get("t3_mode") for r in json.loads(proc.stdout)}
        for name in ("service compile", "service validate", "service plan",
                     "service evaluate", "service study",
                     "service compare", "service inspect",
                     "service capabilities", "service diagnose",
                     "service list"):
            assert name in rows, f"{name} missing from CLI registry"
            assert rows[name] == "forward"


class TestEvaluationEquivalence:
    def test_python_api_cli_same_experiment(self, tmp_path, capsys=None):
        import subprocess
        git = tmp_path / "cleanrepo"
        git.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(git), *args],
                           capture_output=True, timeout=30)
        (git / "src.txt").write_text("v1")
        subprocess.run(["git", "-C", str(git), "add", "src.txt"],
                       capture_output=True, timeout=30)
        subprocess.run(["git", "-C", str(git), "commit", "-qm", "v1"],
                       capture_output=True, timeout=30)
        binary = _needs_binary()
        doc = _canonical_doc()
        store = tmp_path / "store"
        python_svc = SrotaControlPlane(store_root=store, repo_root=git,
                                       binary=binary)
        python_res = python_svc.evaluate(dict(doc))
        from veritx_dse import api as api_mod
        api_out = api_mod.service_evaluate(
            dict(doc), store_root=store, repo=git, binary=binary)
        assert api_out["status"] == "OK", api_out
        api_res = api_out["result"]
        assert api_res["experiment_id"] == python_res["experiment_id"]
        assert api_res["backend_input_hash"] == \
            python_res["backend_input_hash"]
        assert api_res["backend_config_hash"] == \
            python_res["backend_config_hash"]
        # Same store + same semantics: the API call reuses the Python
        # attempt rather than spawning a duplicate execution.
        assert api_res["reused"] is True
        assert api_res["attempt_id"] == python_res["attempt_id"]

    def test_cli_evaluate_matches_python(self, tmp_path):
        import subprocess
        binary = _needs_binary()
        git = tmp_path / "cleanrepo"
        git.mkdir()
        for args in (["init", "-q"], ["config", "user.email", "t@t"],
                     ["config", "user.name", "t"]):
            subprocess.run(["git", "-C", str(git), *args],
                           capture_output=True, timeout=30)
        (git / "src.txt").write_text("v1")
        subprocess.run(["git", "-C", str(git), "add", "src.txt"],
                       capture_output=True, timeout=30)
        subprocess.run(["git", "-C", str(git), "commit", "-qm", "v1"],
                       capture_output=True, timeout=30)
        doc = _canonical_doc()
        request_file = tmp_path / "req.json"
        request_file.write_text(json.dumps(doc))
        store = tmp_path / "store"
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "service",
             "evaluate", "--request", str(request_file),
             "--store", str(store), "--repo", str(git),
             "--binary", str(binary)],
            capture_output=True, text=True, timeout=300, cwd=DSE)
        assert proc.returncode == 0, proc.stderr[-2000:]
        cli_res = json.loads(proc.stdout)
        assert cli_res["status"] == "OK", cli_res
        cli_res = cli_res["result"]
        python_svc = SrotaControlPlane(store_root=store, repo_root=git,
                                       binary=binary)
        python_res = python_svc.evaluate(dict(doc))
        # Same store, same semantics: CLI result reuses the Python run.
        assert python_res["reused"] is True
        assert python_res["experiment_id"] == cli_res["experiment_id"]

    def test_cli_compile_no_spawn(self, tmp_path):
        import subprocess
        doc = _canonical_doc()
        request_file = tmp_path / "req.json"
        request_file.write_text(json.dumps(doc))
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "service",
             "compile", "--request", str(request_file),
             "--store", str(tmp_path / "store")],
            capture_output=True, text=True, timeout=120, cwd=DSE)
        assert proc.returncode == 0, proc.stderr[-2000:]
        out = json.loads(proc.stdout)
        assert out["status"] == "OK"
        assert out["result"]["design"]["resource_id"]

    def test_cli_error_envelope_and_exit_code(self, tmp_path):
        import subprocess
        bad = _canonical_doc(fabric_preset="nope")
        request_file = tmp_path / "bad.json"
        request_file.write_text(json.dumps(bad))
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "service",
             "compile", "--request", str(request_file),
             "--store", str(tmp_path / "store")],
            capture_output=True, text=True, timeout=120, cwd=DSE)
        assert proc.returncode == 1
        out = json.loads(proc.stdout)
        assert out["status"] == "ERROR"
        assert out["code"] == "INVALID_INTENT"


class TestArchitecturalBoundaries:
    @staticmethod
    def _imports(path: Path) -> set[str]:
        tree = ast.parse(path.read_text())
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.add(node.module)
        return found

    def test_cli_adapter_imports_service_only(self):
        imports = self._imports(
            DSE / "veritx_dse" / "cli" / "service_cli.py")
        assert not any(
            i.startswith("veritx_dse.backend") or
            i.startswith("veritx_dse.simulation") or
            i.startswith("veritx_dse.model")
            for i in imports), imports
        assert not any("booksim" in i or "seam" in i for i in imports)

    def test_surfaces_import_service_only(self):
        imports = self._imports(
            DSE / "veritx_dse" / "application" / "surfaces.py")
        assert not any(
            i.startswith("veritx_dse.backend") or
            i.startswith("veritx_dse.simulation") or
            i.startswith("veritx_dse.model")
            for i in imports), imports

    @staticmethod
    def _imported_names(path: Path) -> set[str]:
        tree = ast.parse(path.read_text())
        found: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    found.add(
                        f"{node.module or ''}.{alias.name}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    found.add(alias.name)
        return found

    def test_service_never_uses_legacy_execution(self):
        names = self._imported_names(
            DSE / "veritx_dse" / "application" / "service.py")
        modules = {n.split(".", 1)[0] if "." not in n else n.rsplit(
            ".", 1)[0] for n in names}
        assert "veritx_dse.backend.booksim" in modules
        text = (DSE / "veritx_dse" / "application" /
                "service.py").read_text()
        assert "_run_qualified_booksim_with_runner_for_test" not in text
        for banned in ("run_topology_eval", "run_booksim",
                       "build_config", "run_experiment"):
            assert banned not in text, banned
        # Only binary discovery may come from simulation.booksim.
        sim_names = {n for n in names
                     if n.startswith("veritx_dse.simulation.booksim")}
        assert sim_names <= \
            {"veritx_dse.simulation.booksim.find_booksim_bin"}, sim_names

    def test_test_seam_not_imported_by_product_code(self):
        offenders = []
        for path in (DSE / "veritx_dse").rglob("*.py"):
            if "tests" in path.parts or "__pycache__" in path.parts:
                continue
            if path.name == "booksim.py":
                continue  # definition site
            names = self._imported_names(path)
            if any(n.endswith(
                    "_run_qualified_booksim_with_runner_for_test")
                    for n in names):
                offenders.append(str(path))
        assert offenders == [], offenders

    def test_legacy_execution_paths_classified(self):
        text = (DSE / "veritx_dse" / "application" /
                "inventory.py").read_text()
        for marker in ("LEGACY_INTERNAL", "TEST_ONLY",
                       "run_topology_eval", "simulation.booksim"):
            assert marker in text


class TestPublicSurfaceClosure:
    """Legacy scientific paths must not be normal product operations."""

    LEGACY_TOP_LEVEL = ("run", "sweep", "compare", "pareto",
                        "compile", "evaluate", "synthesize",
                        "certify", "baseline", "diff", "serve")
    LEGACY_HANDLERS = ("cmd_run", "cmd_sweep", "cmd_compare",
                       "cmd_pareto", "cmd_compile", "cmd_baseline",
                       "cmd_diff", "cmd_serve", "cmd_synthesize_bo",
                       "cmd_synthesize_iterative",
                       "cmd_synthesize_compile",
                       "cmd_evaluate_booksim", "cmd_evaluate_anynet",
                       "cmd_evaluate_astra", "cmd_topology_diff",
                       "cmd_certify_flow", "cmd_certify_rtl",
                       "cmd_certify_full", "cmd_api_execute",
                       "cmd_api_compare", "cmd_api_compile",
                       "cmd_api_validate", "cmd_api_plan", "cmd_api_run",
                       "cmd_api_results", "cmd_api_diagnose",
                       "cmd_api_export", "cmd_api_capabilities",
                       "cmd_api_workloads", "cmd_api_topologies")

    def _commands(self):
        from veritx_dse.cli.cli import COMMANDS  # noqa: PLC0415
        return COMMANDS

    def test_no_legacy_top_level_commands(self):
        commands = self._commands()
        for name in self.LEGACY_TOP_LEVEL:
            assert name not in commands, name
        assert "legacy" in commands
        assert "service" in commands
        assert "api" in commands
        assert "certify" not in commands
        legacy = commands["legacy"]["subcommands"]
        assert len(legacy) == 30
        for sub, entry in legacy.items():
            assert entry["t3_mode"] == "blocked", sub
        from veritx_dse.cli import service_cli  # noqa: PLC0415
        api_handlers = {
            entry["handler"].__name__
            for entry in commands["api"]["subcommands"].values()}
        service_handlers = {
            entry["handler"].__name__
            for entry in commands["service"]["subcommands"].values()}
        assert api_handlers == service_handlers
        assert api_handlers <= set(service_cli.__all__)

    def test_no_product_handler_reaches_legacy(self):
        commands = self._commands()
        for top, entry in commands.items():
            if top in ("legacy",):
                continue
            handler = entry.get("handler")
            if handler is not None:
                assert handler.__name__ not in self.LEGACY_HANDLERS, \
                    (top, handler.__name__)
            for sub, subentry in \
                    (entry.get("subcommands") or {}).items():
                assert subentry["handler"].__name__ not in \
                    self.LEGACY_HANDLERS, (top, sub)

    def test_api_advertises_service_only(self):
        from veritx_dse import api as api_mod  # noqa: PLC0415
        advertised = set(api_mod.__all__)
        for name in ("service_validate", "service_compile",
                     "service_plan", "service_evaluate",
                     "service_study", "service_compare",
                     "service_inspect", "service_capabilities",
                     "service_diagnose", "service_list"):
            assert name in advertised, name
        for name in ("execute", "compare", "compile_fabric",
                     "get_run", "get_results", "validate", "plan"):
            assert name not in advertised, name

    def test_t3_registry_consistency(self):
        import re
        t3 = (REPO / "tracks" / "t3-topology" / "t3").read_text()
        fallback = re.search(
            r'_veritx_verbs_fallback\(\) \{[^}]*echo "([^"]*)"', t3)
        assert fallback is not None
        fallback_verbs = sorted(fallback.group(1).split())
        live = sorted({r["name"].split()[0]
                       for r in self._registry_rows()})
        assert fallback_verbs == live
        blocked = re.search(r'_T3_BLOCKED="([^"]*)"', t3)
        assert blocked is not None
        blocked_set = {b.replace("/", " ")
                       for b in blocked.group(1).split()}
        names = {r["name"] for r in self._registry_rows()}
        for entry in blocked_set:
            assert entry in names, entry
        for name in names:
            if name.split()[0] == "legacy" and " " in name:
                assert name in blocked_set, name

    @staticmethod
    def _registry_rows():
        import subprocess
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--list-commands"],
            capture_output=True, text=True, timeout=120, cwd=DSE)
        assert proc.returncode == 0, proc.stderr[-2000:]
        import json
        return json.loads(proc.stdout)

    def test_capability_authority_equality(self, tmp_path):
        from veritx_dse import api as api_mod  # noqa: PLC0415
        service_caps = SrotaControlPlane(
            store_root=tmp_path / "store").capabilities()
        api_out = api_mod.service_capabilities(
            store_root=tmp_path / "store")
        assert api_out["status"] == "OK"
        assert api_out["result"] == service_caps

    def test_api_service_authority_equivalence(self, tmp_path):
        import subprocess
        doc = _canonical_doc()
        request_file = tmp_path / "req.json"
        request_file.write_text(json.dumps(doc))
        store = tmp_path / "store"
        first = None
        for group in ("service", "api"):
            proc = subprocess.run(
                [sys.executable, "-m", "veritx_dse.cli", group,
                 "validate", "--request", str(request_file),
                 "--store", str(store)],
                capture_output=True, text=True, timeout=120, cwd=DSE)
            assert proc.returncode == 0, proc.stderr[-1000:]
            out = json.loads(proc.stdout)
            assert out["status"] == "OK", out
            assert out["result"]["valid"] is True
            if first is None:
                first = out["result"]["intent_id"]
            else:
                assert out["result"]["intent_id"] == first
