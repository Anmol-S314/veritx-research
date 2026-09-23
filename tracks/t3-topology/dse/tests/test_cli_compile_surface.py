"""Canonical ``veritx compile`` surface tests.

The public compile command is a thin adapter over ``SrotaControlPlane``:
CLI declaration -> CompileIntent -> service -> committed CompileOutcome.
These tests pin the grammar, the vocabulary sources, override parsing, the
goldens, failure chains, and the reachability/import sentinels that prove
no legacy compile authority is reachable.
"""
from __future__ import annotations

import argparse
import ast
import inspect
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from veritx_dse.application.compile_intent import (
    CompileIntent, preset_names,
)
from veritx_dse.application.service import (
    CompileServiceError, CompileServiceStage, SrotaControlPlane,
)
from veritx_dse.application.store import ResourceStore
from veritx_dse.cli import cli as cli_module
from veritx_dse.cli import commands_compile
from veritx_dse.cli.cli import DISPATCH, build_parser
from veritx_dse.cli.commands_compile import (
    CompileCommandError, _parse_override,
)
from veritx_dse.compiler.candidate_policy import CandidatePolicy
from veritx_dse.compiler.canonical import CanonicalCompileError, CompileStage
from veritx_dse.core.logging import Ctx

DSE_DIR = Path(__file__).resolve().parent.parent
POLICY = CandidatePolicy.BASELINE_DETERMINISTIC_V2.value

GOLDEN_MESH4_DESIGN = \
    "f13b8d7d61776d863f3f554c32f7d8dab2a622dbf62bdfe697afc6b95ee4547f"
GOLDEN_MESH4_FABRIC = \
    "d7fde891d47c7a6ffb1e0746429a784f95bd20a0014324b8757fdc2841716094"
GOLDEN_MESH4_RESOLVED = \
    "c05d4c19bf3bdd955da97f33fd665d2325441966906b1bb23290d0dcc3296fa1"
GOLDEN_WIDE128_RESOLVED = \
    "47d8cb6c386b22cbc6b4bbf152f40d3c1c72dd1900a48d099afd2bda8fbc9c7f"

SUMMARY_FIELDS = {
    "status", "intent_id", "design_hash", "fabric_hash",
    "resolved_fabric_hash", "topology_hash", "mapping_hash", "vc_count",
}


# ── helpers ────────────────────────────────────────────────────────────────

def _compile_parser() -> argparse.ArgumentParser:
    parser = build_parser()
    sub = next(action for action in parser._actions
               if isinstance(action, argparse._SubParsersAction))
    return sub.choices["compile"]


def _option(parser: argparse.ArgumentParser, name: str):
    return next(action for action in parser._actions
                if name in action.option_strings)


def _parse(argv: list[str]):
    return build_parser().parse_args(argv)


def _run(argv: list[str], tmp_path, *, json_mode: bool = True,
         verbosity: int = 0, output_file: str | None = None) -> None:
    args = _parse(argv)
    ctx = Ctx(verbosity=verbosity, json_mode=json_mode,
              output_file=output_file,
              log_file=str(tmp_path / "cli.log"))
    try:
        commands_compile.cmd_compile(ctx, args)
    finally:
        ctx.close()


def _run_json(argv: list[str], tmp_path, capsys, **kwargs) -> dict:
    _run(argv, tmp_path, json_mode=True, **kwargs)
    return json.loads(capsys.readouterr().out)


def _preset_argv(store: Path, preset: str = "mesh4", extra=()) -> list[str]:
    return ["compile", "--preset", preset, "--policy", POLICY,
            "--store", str(store), *extra]


def _cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "PYTHONPATH": str(DSE_DIR)}
    return subprocess.run(
        [sys.executable, "-m", "veritx_dse.cli", *args],
        capture_output=True, text=True, timeout=180,
        cwd=str(cwd or DSE_DIR), env=env)


# ── grammar ────────────────────────────────────────────────────────────────

def test_store_is_required(tmp_path):
    with pytest.raises(SystemExit):
        _parse(["compile", "--preset", "mesh4", "--policy", POLICY])
    with pytest.raises(SystemExit):
        _parse(["compile", "--intent", "i.json", "--policy", POLICY])


def test_exactly_one_of_preset_or_intent(tmp_path):
    for argv in (["compile", "--store", str(tmp_path)],
                 ["compile", "--preset", "mesh4", "--intent", "i.json",
                  "--policy", POLICY, "--store", str(tmp_path)]):
        with pytest.raises(SystemExit):
            _parse(argv)


def test_preset_vocabulary_comes_from_preset_names():
    choices = _option(_compile_parser(), "--preset").choices
    assert tuple(choices) == preset_names()


def test_policy_vocabulary_comes_from_candidate_policy():
    choices = _option(_compile_parser(), "--policy").choices
    assert list(choices) == [p.value for p in CandidatePolicy]


def test_preset_mode_requires_explicit_policy(tmp_path):
    args = _parse(["compile", "--preset", "mesh4",
                   "--store", str(tmp_path)])
    ctx = Ctx(verbosity=0, json_mode=True,
              log_file=str(tmp_path / "cli.log"))
    try:
        with pytest.raises(CompileCommandError, match="--policy is required"):
            commands_compile.cmd_compile(ctx, args)
    finally:
        ctx.close()


def test_no_backend_or_execution_options_exist():
    parser = _compile_parser()
    options = {opt for action in parser._actions
               for opt in action.option_strings}
    for forbidden in ("--timeout", "--backend", "--seed", "--trace",
                      "--booksim", "--verify", "--generate", "--routing",
                      "--vcs", "--topology"):
        assert forbidden not in options, forbidden


# ── override parsing ───────────────────────────────────────────────────────

def test_scalar_overrides_parse_with_exact_types():
    assert _parse_override("noc_config.link_width=128") \
        == ("noc_config.link_width", 128)
    assert _parse_override('noc_config.arbitration="rr"') \
        == ("noc_config.arbitration", "rr")
    assert _parse_override("noc_config.rcu_enabled=true") \
        == ("noc_config.rcu_enabled", True)
    assert _parse_override("workload.pp=null") == ("workload.pp", None)
    assert _parse_override("physical.process_node_nm=5.5") \
        == ("physical.process_node_nm", 5.5)


@pytest.mark.parametrize("text,match", [
    ("noc_config.arbitration=rr", "JSON scalar"),
    ("noc_config.link_width", "PATH=JSON_SCALAR"),
    ("=1", "non-empty dotted path"),
    ("noc_config..link_width=1", "empty segment"),
    ("noc_config.link_width=[1,2]", "JSON scalar"),
    ("noc_config.arbitration={\"a\":1}", "JSON scalar"),
    ("physical.clock_freq_mhz=NaN", "JSON scalar"),
    ("physical.clock_freq_mhz=Infinity", "JSON scalar"),
    ("noc_config.link_width='128'", "JSON scalar"),
])
def test_malformed_overrides_are_refused(text, match):
    with pytest.raises(CompileCommandError, match=match):
        _parse_override(text)


def test_duplicate_override_reaches_compile_intent_refusal(tmp_path):
    argv = _preset_argv(tmp_path / "store", extra=[
        "--set", "noc_config.link_width=128",
        "--set", "noc_config.link_width=64"])
    with pytest.raises(Exception) as excinfo:
        _run(argv, tmp_path)
    assert "duplicate override" in str(excinfo.value)
    assert not (tmp_path / "store" / "resolutions").exists() or \
        list((tmp_path / "store" / "resolutions").glob("*.json")) == []


# ── goldens through the CLI ────────────────────────────────────────────────

def test_mesh4_golden_through_the_cli(tmp_path, capsys):
    store = tmp_path / "store"
    summary = _run_json(_preset_argv(store), tmp_path, capsys)
    assert summary["status"] == "RESOLVED"
    assert summary["design_hash"] == GOLDEN_MESH4_DESIGN
    assert summary["fabric_hash"] == GOLDEN_MESH4_FABRIC
    assert summary["resolved_fabric_hash"] == GOLDEN_MESH4_RESOLVED
    committed = ResourceStore(store).load_committed(summary["intent_id"])
    assert committed.resolution.resolved_fabric_hash \
        == GOLDEN_MESH4_RESOLVED


def test_summary_fields_are_exactly_the_resolved_structural_set(tmp_path,
                                                                capsys):
    summary = _run_json(_preset_argv(tmp_path / "store"), tmp_path, capsys)
    assert set(summary) == SUMMARY_FIELDS
    blob = json.dumps(summary).lower()
    for token in ("verified", "qualified", "executable", "latency", "area",
                  "power", "certif", "booksim"):
        assert token not in blob, token


def test_wide128_override_converges_with_preset(tmp_path, capsys):
    override_summary = _run_json(
        _preset_argv(tmp_path / "s1", extra=[
            "--set", "noc_config.link_width=128"]), tmp_path, capsys)
    preset_summary = _run_json(
        _preset_argv(tmp_path / "s2", preset="mesh4_wide128"),
        tmp_path, capsys)
    assert override_summary["resolved_fabric_hash"] \
        == preset_summary["resolved_fabric_hash"] == GOLDEN_WIDE128_RESOLVED
    assert override_summary["design_hash"] == preset_summary["design_hash"]
    # declarations remain distinct
    assert override_summary["intent_id"] != preset_summary["intent_id"]


def test_name_is_presentation_only(tmp_path, capsys):
    alpha = _run_json(_preset_argv(tmp_path / "s1", extra=["--name", "alpha"]),
                      tmp_path, capsys)
    beta = _run_json(_preset_argv(tmp_path / "s2", extra=["--name", "beta"]),
                     tmp_path, capsys)
    assert alpha["intent_id"] == beta["intent_id"]
    assert alpha["design_hash"] == beta["design_hash"]


# ── intent file mode ───────────────────────────────────────────────────────

def _write_intent(tmp_path, name="file-intent") -> tuple[Path, CompileIntent]:
    intent = CompileIntent(name=name, fabric_preset="mesh4",
                           fabric_overrides=(), candidate_policy=
                           CandidatePolicy.BASELINE_DETERMINISTIC_V2)
    path = tmp_path / "intent.json"
    path.write_text(json.dumps(intent.to_dict()))
    return path, intent


def test_intent_file_mode_reproduces_service_identities(tmp_path, capsys):
    path, intent = _write_intent(tmp_path)
    summary = _run_json(["compile", "--intent", str(path),
                         "--store", str(tmp_path / "store")],
                        tmp_path, capsys)
    direct_store = ResourceStore(tmp_path / "direct")
    direct = SrotaControlPlane(store=direct_store).compile(intent)
    assert summary["intent_id"] == direct.intent_id
    assert summary["design_hash"] == direct.design_hash
    assert summary["resolved_fabric_hash"] == direct.resolved_fabric_hash
    assert summary["intent_id"] == intent.intent_id()


def test_intent_file_mode_refuses_preset_only_options(tmp_path):
    path, _ = _write_intent(tmp_path)
    for extra in (["--set", "noc_config.link_width=128"],
                  ["--name", "x"],
                  ["--policy", POLICY]):
        with pytest.raises(CompileCommandError, match="cannot be combined"):
            _run(["compile", "--intent", str(path), "--store",
                  str(tmp_path / "store"), *extra], tmp_path)


@pytest.mark.parametrize("field,value", [
    ("intent_id", "0" * 64),
    ("preset_design_hash", "0" * 64),
    ("compiler_semantics_version", 1),
])
def test_tampered_intent_file_is_refused_without_repair(tmp_path, field, value):
    path, _ = _write_intent(tmp_path)
    document = json.loads(path.read_text())
    document[field] = value
    path.write_text(json.dumps(document))
    with pytest.raises(Exception):
        _run(["compile", "--intent", str(path), "--store",
              str(tmp_path / "store")], tmp_path)
    assert list((tmp_path / "store" / "resolutions").glob("*.json")) == []


def test_missing_intent_file_is_refused(tmp_path):
    with pytest.raises(CompileCommandError, match="not found"):
        _run(["compile", "--intent", str(tmp_path / "nope.json"),
              "--store", str(tmp_path / "store")], tmp_path)


# ── failure chains ─────────────────────────────────────────────────────────

def test_torus_failure_chain_through_the_cli(tmp_path):
    store = tmp_path / "store"
    argv = _preset_argv(store, extra=[
        "--set", 'noc_config.topology_family="torus"'])
    with pytest.raises(CompileServiceError) as excinfo:
        _run(argv, tmp_path)
    error = excinfo.value
    assert error.stage is CompileServiceStage.COMPILE
    assert isinstance(error.__cause__, CanonicalCompileError)
    assert error.__cause__.stage is CompileStage.ROUTING
    assert list((store / "resolutions").glob("*.json")) == []


def test_store_failure_is_clean_domain_error(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("not a directory")
    with pytest.raises(Exception):
        _run(_preset_argv(blocker / "store"), tmp_path)


# ── presentation invariance ────────────────────────────────────────────────

def test_presentation_does_not_move_identities(tmp_path, capsys):
    quiet = _run_json(_preset_argv(tmp_path / "s1"), tmp_path, capsys,
                      verbosity=0)
    verbose = _run_json(_preset_argv(tmp_path / "s2"), tmp_path, capsys,
                        verbosity=2)
    out_file = tmp_path / "summary.json"
    saved = _run_json(_preset_argv(tmp_path / "s3"), tmp_path, capsys,
                      output_file=str(out_file))
    for summary in (verbose, saved):
        assert {k: summary[k] for k in ("intent_id", "design_hash",
                                        "fabric_hash",
                                        "resolved_fabric_hash")} \
            == {k: quiet[k] for k in ("intent_id", "design_hash",
                                      "fabric_hash",
                                      "resolved_fabric_hash")}
    assert json.loads(out_file.read_text()) == saved


def test_human_output_does_not_imply_execution(tmp_path, capsys):
    _run(_preset_argv(tmp_path / "store"), tmp_path, json_mode=False)
    out = capsys.readouterr().out.lower()
    assert "resolved" in out
    assert "backend execution" in out and "not performed" in out
    assert "verification" in out
    for token in ("verified", "qualified", "executable", "latency",
                  "area:", "power:", "certif"):
        assert token not in out, token


# ── no BookSim / no legacy reachability ────────────────────────────────────

def test_no_booksim_binary_needed_for_canonical_compile(tmp_path):
    booksim_paths = [
        DSE_DIR.parent.parent.parent / "third_party" / "booksim2" / "src"
        / "booksim",
        DSE_DIR.parent.parent.parent / "third_party" / "booksim2" / "build"
        / "booksim",
    ]
    assert not any(path.exists() for path in booksim_paths), \
        "this proof assumes the BookSim binary is absent"
    result = _cli(["compile", "--preset", "mesh4", "--policy", POLICY,
                   "--store", str(tmp_path / "store")], cwd=tmp_path)
    assert result.returncode == 0, result.stderr[-800:]
    assert "RESOLVED" in result.stdout


def test_raw_compile_request_positional_is_rejected(tmp_path):
    example = DSE_DIR / "examples" / "_template.json"
    result = _cli(["compile", str(example)], cwd=tmp_path)
    assert result.returncode != 0
    assert "Traceback" not in result.stderr


def test_dispatch_points_at_the_new_handler():
    assert DISPATCH["compile"] is commands_compile.cmd_compile
    assert "cmd_compile" not in vars(cli_module)


def test_legacy_compile_body_is_gone():
    source = inspect.getsource(cli_module)
    assert "def cmd_compile(" not in source
    for token in ("derive_topology_spec", "verify_design",
                  "generate_artifacts"):
        assert token not in source, token
    assert "def cmd_compile_legacy" not in source


# ── import / source authority sentinels ────────────────────────────────────

def _imported_modules(module) -> set[str]:
    tree = ast.parse(inspect.getsource(module))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            modules.add(node.module or "")
        elif isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
    return modules


def _stripped_source(module) -> str:
    source = inspect.getsource(module)
    tree = ast.parse(source)
    ranges = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)) \
                and node.body \
                and isinstance(node.body[0], ast.Expr) \
                and isinstance(node.body[0].value, ast.Constant) \
                and isinstance(node.body[0].value.value, str):
            ranges.append((node.body[0].lineno, node.body[0].end_lineno))
    return "".join(
        line for number, line in enumerate(source.splitlines(keepends=True),
                                           start=1)
        if not any(low <= number <= high for low, high in ranges))


def test_adapter_imports_only_transport_authorities():
    modules = _imported_modules(commands_compile)
    local = {name for name in modules if name.startswith("veritx_dse")}
    assert local == {
        "veritx_dse.application.compile_intent",
        "veritx_dse.application.service",
        "veritx_dse.application.store",
        "veritx_dse.core.logging",
        "veritx_dse.compiler.candidate_policy",
    }
    for forbidden in ("compile_model", "topology_artifact", "routing",
                      "vc_assignment", "vc_resource", "canonical",
                      "verification", "simulation", "booksim", "astra",
                      "reports", "uvm"):
        assert not any(forbidden in name for name in local), forbidden


def test_adapter_source_has_no_compiler_or_backend_calls():
    source = _stripped_source(commands_compile)
    for token in ("compile_deterministic_candidate",
                  "generate_baseline_candidate",
                  "derive_vc_assignment", "derive_vc_count",
                  "derive_topology_spec", "run_booksim", "build_config",
                  "verify_design", "generate_artifacts", "generate_uvm",
                  "generate_report", "DesignManifest", "validate",
                  "subprocess", "booksim", "CompileRequest"):
        assert token not in source, token
    assert "SrotaControlPlane(store=store).compile(intent)" in source
    assert ".compile(intent)" in source


def test_no_http_or_second_api_surface():
    tree = ast.parse(inspect.getsource(commands_compile))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert "http" not in (node.module or "")
            assert "server" not in (node.module or "")
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert "http" not in alias.name
                assert "flask" not in alias.name
                assert "fastapi" not in alias.name
