"""Source-snapshot reproducibility, honest provenance and native counterexamples.

Native checks reuse existing canonical parent fixtures, not a parallel lowerer.
No optional tool skip: these acceptance cases require an actual source build.
"""
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess

import pytest

REPO = Path(__file__).resolve().parents[4]
SCRIPT = REPO / "scripts/verify_booksim_source_build.py"
spec = importlib.util.spec_from_file_location("booksim_source_verification", SCRIPT)
verification = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verification)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / "repo" / "src"
    root.mkdir(parents=True)
    for name, content in {"Makefile": "all: booksim\n", "config.l": "lex", "config.y": "yacc",
                          "main.cpp": "int main() {}", "ignored-untracked.hpp": "// input"}.items():
        (root / name).write_text(content)
    (root / "booksim").write_bytes(b"old pinned binary")
    (root / "booksim.build-manifest.json").write_text("old pin")
    (root / "main.o").write_bytes(b"product")
    (root / "lex.yy.c").write_text("stale generated source")
    return root


def test_inventory_includes_actual_untracked_and_executable_inputs(source):
    (source / "ignored-untracked.hpp").chmod(0o755)
    value = verification.inventory(source)
    files = {row["path"]: row for row in value["files"]}
    assert files["ignored-untracked.hpp"]["executable"]
    assert files["ignored-untracked.hpp"]["sha256"] == verification.file_fact(source / "ignored-untracked.hpp")["sha256"]
    assert {"booksim", "booksim.build-manifest.json", "main.o", "lex.yy.c"} <= set(value["excluded"])
    assert value["content_sha256"] == verification.digest(value["files"])
    (source / "ignored-untracked.hpp").write_text("changed")
    assert verification.inventory(source)["content_sha256"] != value["content_sha256"]


@pytest.mark.parametrize("case", ["external_file", "internal_file", "external_directory", "fifo", "missing"])
def test_inventory_refuses_escaping_aliases_special_and_missing_inputs(source, case):
    if case == "external_file":
        (source / "alias.hpp").symlink_to("/etc/passwd")
    elif case == "internal_file":
        (source / "alias.hpp").symlink_to("main.cpp")
    elif case == "external_directory":
        (source / "alias").symlink_to("/tmp", target_is_directory=True)
    elif case == "fifo":
        os.mkfifo(source / "pipe")
    else:
        (source / "config.y").unlink()
    with pytest.raises(verification.VerificationError):
        verification.inventory(source)


def test_snapshot_copy_detects_drift(source, tmp_path, monkeypatch):
    before = verification.inventory(source)
    copy = verification.shutil.copy2
    def changing_copy(src, dst):
        result = copy(src, dst)
        if Path(src).name == "main.cpp":
            (source / "config.l").write_text("changed while copying")
        return result
    monkeypatch.setattr(verification.shutil, "copy2", changing_copy)
    with pytest.raises(verification.VerificationError, match="drift"):
        verification.copy_snapshot(source, tmp_path / "snapshot", before)


def test_dirty_git_facts_are_never_promoted(source, monkeypatch):
    def git(command, **kwargs):
        text = "a" * 40 if "rev-parse" in command else " M src/main.cpp\n"
        return subprocess.CompletedProcess(command, 0, stdout=text, stderr="")
    monkeypatch.setattr(verification.subprocess, "run", git)
    facts = verification.git_facts(source.parent, source)
    assert facts["revision"] and facts["source_dirty"] and facts["repository_dirty"]
    assert facts["source_status"] and not facts["pinned"] and not facts["qualification"]


def test_logged_compiler_failure_and_timeout_retained(tmp_path):
    import sys
    log = tmp_path / "failed.log"
    result = verification.run_logged([sys.executable, "-c", "print('failure'); exit(2)"], tmp_path, log, os.environ, 10)
    assert result["returncode"] == 2 and "failure" in log.read_text()
    timed = verification.run_logged([sys.executable, "-c", "import time; time.sleep(5)"], tmp_path, log, os.environ, .05)
    assert timed["returncode"] is None and timed["error"] and "VERIFICATION_FAILURE" in log.read_text()


def test_timeout_kills_compiler_descendants_not_only_wrapper(tmp_path):
    import sys
    import time
    marker = tmp_path / "orphan-output"
    ready = tmp_path / "child-started"
    child = f"from pathlib import Path; import time; Path({str(ready)!r}).write_text('ready'); time.sleep(1); Path({str(marker)!r}).write_text('orphan')"
    parent = f"import subprocess, time; subprocess.Popen([{sys.executable!r}, '-c', {child!r}]); time.sleep(5)"
    outcome = verification.run_logged([sys.executable, "-c", parent], tmp_path, tmp_path / "timeout.log", os.environ, .5)
    assert outcome["returncode"] is None and outcome["error"] and ready.is_file()
    time.sleep(1)
    assert not marker.exists()


def test_unknown_provenance_is_never_clean(source):
    facts = verification.git_facts(source.parent, source)
    assert facts["revision"] is None and facts["source_dirty"] is None
    assert facts["repository_dirty"] is None and not facts["pinned"] and not facts["qualification"]


def fake_builds(monkeypatch, tmp_path, *, mismatch=False, fail=False, drift=False):
    tool = tmp_path / "compiler"
    tool.write_text("tool executable")
    tool.chmod(0o755)
    monkeypatch.setattr(verification, "tool_fact", lambda command: {"path": str(tool), "version": command + " version", **verification.file_fact(tool)})
    count = 0
    def run(command, cwd, log, env, timeout):
        nonlocal count
        count += 1
        Path(log).write_text("compile log")
        (Path(cwd) / "booksim").write_bytes(b"binary" + (str(count).encode() if mismatch else b""))
        if drift:
            (Path(cwd) / "main.cpp").write_text("build altered source")
        return {"command": command, "returncode": 1 if fail else 0, "error": None,
                "log": Path(log).name, "log_fact": verification.file_fact(log)}
    monkeypatch.setattr(verification, "run_logged", run)


def build(source, tmp_path, **kwargs):
    return verification.verify_builds(repo_root=source.parent, source_root=source,
                                     output_root=tmp_path / "output", native_diagnostics=False, **kwargs)


def test_two_build_positive_report_and_old_pins_preserved(source, tmp_path, monkeypatch):
    pins = {name: (source / name).read_bytes() for name in ("booksim", "booksim.build-manifest.json")}
    fake_builds(monkeypatch, tmp_path)
    report = build(source, tmp_path)
    assert report["success"] and report["byte_identical"] and not report["qualification"]
    assert report["provenance"]["source_dirty"] is None
    assert verification.verify_report(tmp_path / "output/verification.json") == report
    assert all((source / name).read_bytes() == data for name, data in pins.items())
    for row in report["builds"]:
        assert "CC=" in " ".join(row["execution"]["command"])
        assert "-ffile-prefix-map=" in row["flags"]
        assert row["copied_inventory"]["content_sha256"] == report["input_inventory"]["content_sha256"]


@pytest.mark.parametrize("failure", ["compiler", "mismatch", "drift", "missing_tool"])
def test_failed_build_retains_failure_evidence(source, tmp_path, monkeypatch, failure):
    fake_builds(monkeypatch, tmp_path, fail=failure == "compiler", mismatch=failure == "mismatch", drift=failure == "drift")
    if failure == "missing_tool":
        def missing(command):
            raise verification.VerificationError("required tool absent")
        monkeypatch.setattr(verification, "tool_fact", missing)
    report = build(source, tmp_path)
    assert not report["success"] and report["failure"] and not report["qualification"]
    assert json.loads((tmp_path / "output/verification.json").read_text()) == report
    with pytest.raises(verification.VerificationError):
        verification.verify_report(tmp_path / "output/verification.json")


@pytest.mark.parametrize("missing_profile", [False, True])
def test_native_runner_creates_external_parent_and_requires_complete_coverage(source, tmp_path, monkeypatch, missing_profile):
    fake_builds(monkeypatch, tmp_path)
    build_run = verification.run_logged
    monkeypatch.setattr(verification, "verification_inputs", lambda repo: {})
    def run(command, cwd, log, env, timeout):
        if "pytest" not in command:
            return build_run(command, cwd, log, env, timeout)
        root = Path(env["VERITX_SOURCE_VERIFICATION_EVIDENCE"])
        assert root.is_dir()  # pytest --basetemp requires its parent to exist
        assert env["VERITX_SROTA_DIAGNOSTIC_BINARY"] == env["VERITX_SOURCE_VERIFICATION_BINARY"]
        for name in ("cmesh-2", "class-vc") if missing_profile else ("cmesh-2", "cmesh-4", "class-vc"):
            (root / name).mkdir()
            (root / name / "summary.json").write_text(json.dumps({"binary_sha256": env["VERITX_SOURCE_VERIFICATION_SHA256"], "qualification": False}))
        Path(log).write_text("4 passed")
        return {"command": command, "returncode": 0, "error": None, "log": Path(log).name, "log_fact": verification.file_fact(log)}
    monkeypatch.setattr(verification, "run_logged", run)
    report = verification.verify_builds(repo_root=source.parent, source_root=source,
                                       output_root=tmp_path / "output", native_diagnostics=True)
    assert report["success"] is (not missing_profile)
    if not missing_profile:
        verification.verify_report(tmp_path / "output/verification.json")
    else:
        assert "coverage incomplete" in report["failure"]


def test_byte_mismatch_can_be_reported_but_never_relabelled(source, tmp_path, monkeypatch):
    fake_builds(monkeypatch, tmp_path, mismatch=True)
    report = build(source, tmp_path, require_byte_identical=False)
    assert report["success"] and not report["byte_identical"] and not report["pinned"]
    verification.verify_report(tmp_path / "output/verification.json")


@pytest.mark.parametrize("case", ["binary", "source", "copied_source", "log", "report", "qualified", "escaping_artifact", "tool", "false_equality", "unknown_field", "false_clean", "missing_artifacts", "bool_alias", "wrong_recipe"])
def test_report_reverification_refuses_tampering(source, tmp_path, monkeypatch, case):
    fake_builds(monkeypatch, tmp_path)
    doc = build(source, tmp_path)
    out = tmp_path / "output"
    path = out / "verification.json"
    if case == "binary":
        (out / "build-1/booksim").write_bytes(b"replacement")
    elif case == "source":
        (source / "new-untracked.cpp").write_text("input")
    elif case == "copied_source":
        (out / "build-2/main.cpp").write_text("different input")
    elif case == "log":
        (out / "build-1.log").write_text("tamper")
    elif case == "tool":
        (tmp_path / "compiler").write_text("foreign tool")
    else:
        if case == "qualified":
            doc["qualification"] = True
        elif case == "escaping_artifact":
            doc["artifacts"]["../elsewhere"] = {}
        elif case == "false_equality":
            doc["byte_identical"] = False
        elif case == "unknown_field":
            doc["extra"] = "not allowed"
        elif case == "false_clean":
            doc["provenance"]["source_dirty"] = False
        elif case == "missing_artifacts":
            doc["artifacts"] = {}
        elif case == "bool_alias":
            doc["success"] = 1
        elif case == "wrong_recipe":
            doc["recipe"] = "foreign recipe"
        else:
            doc["recipe"] = "forged"
        if case != "report":
            doc["report_sha256"] = verification.digest({k: v for k, v in doc.items() if k != "report_sha256"})
        path.write_text(json.dumps(doc))
    with pytest.raises(verification.VerificationError):
        verification.verify_report(path)


@pytest.mark.parametrize("case", ["inside_repo", "ancestor", "existing", "container_tag", "bad_timeout"])
def test_unsafe_build_destinations_and_options_refuse(source, tmp_path, case):
    out = tmp_path / "output"
    kw = {}
    if case == "inside_repo": out = source.parent / "build"
    elif case == "ancestor": out = tmp_path
    elif case == "existing": out.mkdir()
    elif case == "container_tag": kw["container_digest"] = "image:latest"
    elif case == "bad_timeout": kw["timeout"] = True
    with pytest.raises(verification.VerificationError):
        verification.verify_builds(repo_root=source.parent, source_root=source, output_root=out, **kw)


@pytest.fixture(scope="module")
def native_binary(tmp_path_factory):
    supplied = os.environ.get("VERITX_SOURCE_VERIFICATION_BINARY")
    if supplied:
        binary = Path(supplied)
        assert verification.file_fact(binary)["sha256"] == os.environ["VERITX_SOURCE_VERIFICATION_SHA256"]
        return binary
    out = tmp_path_factory.mktemp("source-verification") / "two-builds"
    report = verification.verify_builds(repo_root=REPO, source_root=REPO / "third_party/booksim2/src",
                                       output_root=out, native_diagnostics=False)
    assert report["success"], report["failure"]
    verification.verify_report(out / "verification.json")
    return out / "build-1/booksim"


def evidence_root(tmp_path, name):
    root = Path(os.environ.get("VERITX_SOURCE_VERIFICATION_EVIDENCE", str(tmp_path))) / name
    root.mkdir(parents=True)
    return root


def save_summary(root, binary, prepared, record, checks):
    # Retain raw output from an explicitly separate repeated native invocation;
    # the generic supervised executor currently retains only parsed evidence.
    from veritx_dse.backend.booksim_execution import parse_booksim_stats, validate_mesh_class_vc_observations
    run = root / "positive"
    proc = subprocess.run([str(binary), "config.cfg"], cwd=run, capture_output=True, text=True, timeout=300)
    (run / "repeat-stdout.txt").write_text(proc.stdout)
    (run / "repeat-stderr.txt").write_text(proc.stderr)
    assert proc.returncode == 0
    stats = parse_booksim_stats(proc.stdout, proc.stderr)
    classes = {int(row.split()[2]) for row in prepared.trace_text.splitlines()}
    observations = validate_mesh_class_vc_observations(prepared.config_text, proc.stdout + "\n" + proc.stderr, expected_classes=classes)
    if observations:
        stats["mesh_class_vc_route_observations"] = observations
    assert stats == record.evidence.stats
    assert verification.file_fact(run / "routing.dump")["sha256"] == record.evidence.route_dump_sha256
    doc = {"state": "DIAGNOSTIC_UNQUALIFIED", "qualification": False,
           "raw_logs": "SEPARATE_REPEAT_SAME_INPUT_SEED_MATCHED_STATS_AND_ROUTE_DUMP",
           "binary_sha256": verification.file_fact(binary)["sha256"],
           "prepared_id": prepared.prepared_id(), "expected_packets": prepared.expected_packets,
           "expected_flits": prepared.expected_flits, "checks": checks, "record": record.to_dict()}
    (root / "summary.json").write_text(json.dumps(doc, sort_keys=True, indent=2) + "\n")


@pytest.mark.parametrize("concentration", [2, 4])
def test_native_diagnostic_cmesh_mapping_routes_conservation_and_refusals(concentration, native_binary, tmp_path):
    from test_booksim_cmesh_projection import _cmesh_parents
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.cmesh_terminal_map import cmesh_terminal_map
    root = evidence_root(tmp_path, f"cmesh-{concentration}")
    parents = _cmesh_parents(tmp_path, concentration)
    prepared = prepare_booksim_input(parents, seed=0)
    record = execute_prepared_booksim(prepared=prepared, binary=native_binary, run_dir=root / "positive",
                                      timeout=300, repo_root=REPO, allow_unqualified_profile=True)
    stats = record.evidence.stats
    assert stats["flits_injected"] == stats["flits_accepted"] == prepared.expected_flits
    assert record.evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"
    k = int(re.search(r"(?m)^k = (\d+);", prepared.config_text)[1])
    bindings = cmesh_terminal_map(parents.attachment, k=k, concentration=concentration).bindings
    ejections = {(int(r), int(n)): (int(next_r), int(port)) for r, n, next_r, port in re.findall(
        r"src_router (\d+) dst_node (\d+) next_router (\d+) port (\d+)", (root / "positive/routing.dump").read_text())}
    for endpoint, node, router, port in bindings:
        assert ejections[(router, node)] == (router, port)
        # Independent no-express XY neighbor law, not the production route rows.
        for src in range(k * k):
            sx, sy, dx, dy = src % k, src // k, router % k, router // k
            expected = src + (1 if dx > sx else -1) if sx != dx else src + k * (1 if dy > sy else -1) if sy != dy else src
            assert ejections[(src, node)][0] == expected
    from dataclasses import replace
    bad = root / "unsupported"
    change = ("routing_function = dor_no_express;", "routing_function = dor;") if concentration == 2 else ("n = 2;", "n = 3;")
    reason = "dor_no_express only" if concentration == 2 else "requires n = 2"
    replace(prepared, config_text=prepared.config_text.replace(*change)).prepare_directory(bad)
    proc = subprocess.run([str(native_binary), "config.cfg"], cwd=bad, capture_output=True, text=True, timeout=30)
    (bad / "stdout.txt").write_text(proc.stdout); (bad / "stderr.txt").write_text(proc.stderr)
    assert proc.returncode != 0 and reason in proc.stdout + proc.stderr
    save_summary(root, native_binary, prepared, record, ["exact terminal ejection bijection", "route dump verified", "packets/flits conserved", "unsupported routing/geometry refused"])


def test_native_diagnostic_class_vc_exact_map_bounds_conservation(native_binary, tmp_path):
    from test_booksim_class_vc_withdrawal import _parents
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    prepared = prepare_booksim_input(_parents(), seed=0)
    root = evidence_root(tmp_path, "class-vc")
    record = execute_prepared_booksim(prepared=prepared, binary=native_binary, run_dir=root / "positive",
                                      timeout=300, repo_root=REPO, allow_unqualified_profile=True)
    stats = record.evidence.stats
    assert stats["flits_injected"] == stats["flits_accepted"] == prepared.expected_flits
    assert record.evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"
    observations = stats["mesh_class_vc_route_observations"]
    assert set(observations) == {"0", "1"} and all(observations.values())
    assert set(observations["0"]) == {"1"} and set(observations["1"]) == {"0"}
    assert observations["0"]["1"] > 0 and observations["1"]["0"] > 0
    # Native parser plus canonical observation verifier enforces configured
    # class0->VC1/class1->VC0; insist the expected table was actually rendered.
    assert "mesh_class_vc_begin = {1,0};" in prepared.config_text
    assert "mesh_class_vc_end = {1,0};" in prepared.config_text
    cases = [("begin-negative", "mesh_class_vc_begin", "{-1,0}", "invalid range"),
             ("end-upper", "mesh_class_vc_end", "{2,0}", "invalid range"),
             ("reversed", "mesh_class_vc_end", "{0,0}", "invalid range"),
             ("short", "mesh_class_vc_begin", "{1}", "complete DOR_XY class table required"),
             ("long", "mesh_class_vc_end", "{1,0,0}", "complete DOR_XY class table required"),
             ("route", "routing_function", "min_adapt", "complete DOR_XY class table required")]
    from dataclasses import replace
    for name, field, value, reason in cases:
        config, count = re.subn(rf"(?m)^{field}\s*=.*?;", f"{field} = {value};", prepared.config_text)
        assert count == 1
        bad = root / name
        replace(prepared, config_text=config).prepare_directory(bad)
        proc = subprocess.run([str(native_binary), "config.cfg"], cwd=bad, capture_output=True, text=True, timeout=30)
        (bad / "stdout.txt").write_text(proc.stdout); (bad / "stderr.txt").write_text(proc.stderr)
        assert proc.returncode != 0 and reason in proc.stdout + proc.stderr
    for cl in (-1, 2):
        bad = root / f"foreign-class-{cl}"
        replace(prepared, trace_text=f"0 0 {cl} 1 8\n").prepare_directory(bad)
        proc = subprocess.run([str(native_binary), "config.cfg"], cwd=bad, capture_output=True, text=True, timeout=30)
        (bad / "stdout.txt").write_text(proc.stdout); (bad / "stderr.txt").write_text(proc.stderr)
        assert proc.returncode != 0 and "Trace traffic class outside configured class range" in proc.stdout + proc.stderr
    save_summary(root, native_binary, prepared, record, ["class0->VC1/class1->VC0", "route observed", "packets/flits conserved", "six table/route refusals", "negative/upper foreign trace classes refused"])
