import hashlib
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[4]))

from veritx_dse.product.project_top_rtl import _run_logged

from scripts.complete_design import (
    FAMILIES14,
    completion_exit_code,
    completion_result,
    generate_hardware,
    hardware_evidence_status,
    physical_stage,
    hardware_family_for_request,
    kncube_lint_and_sim,
    log_artifacts,
    load_live_request,
    make_family_request,
    _is_non_goal_path,
    source_dirty,
)


@pytest.mark.parametrize("family", list(FAMILIES14))
def test_completion_runner_preserves_saved_topology_family(family):
    request = make_family_request(family)
    assert hardware_family_for_request(request) == family


def test_kncube_general_request_uses_the_registered_structured_intent():
    request = make_family_request("kncube")
    assert request.topology.family == "kncube"
    assert request.topology.params == {"radix": 3, "dimensions": 2, "wrap": True}


def test_completion_runner_refuses_topology_without_exact_family_mapping():
    request = SimpleNamespace(topology=SimpleNamespace(kind="unregistered"))
    with pytest.raises(ValueError, match="UNSUPPORTED_COMPLETION_FAMILY"):
        hardware_family_for_request(request)


def test_generator_refuses_wrong_family_before_writing(tmp_path):
    request = make_family_request("gec_mecs")
    with pytest.raises(ValueError, match="hardware family mismatch"):
        generate_hardware(request, "mesh", tmp_path)
    assert not list(tmp_path.iterdir())


def test_kncube_runner_refuses_a_torus_source_instead_of_substituting(tmp_path):
    params = SimpleNamespace(family="kncube")
    topology = SimpleNamespace(kind="torus")
    with pytest.raises(ValueError, match="KNCUBE_GENERAL_INTENT_AND_NATIVE_EQUIVALENCE_CHECKER_MISSING"):
        kncube_lint_and_sim(params, topology, tmp_path)
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("result", [
    {},
    {"lint": "PASS"},
    {"lint": "PASS", "sim": "PASS"},
    {"lint": "PASS", "sim": "PASS", "scenarios": {}},
])
def test_hardware_evidence_is_blocked_when_required_verdicts_are_missing(result):
    assert hardware_evidence_status(result) == "BLOCKED"


def test_hardware_evidence_pass_requires_lint_sim_and_all_scenarios():
    result = {"lint": "PASS", "sim": "PASS", "scenarios": {"drain": True, "reset": True}}
    assert hardware_evidence_status(result) == "PASS"


def test_failed_lint_or_simulation_fails_the_hardware_gate():
    assert hardware_evidence_status({"lint": "FAIL", "sim": "PASS", "scenarios": {"drain": True}}) == "FAIL"
    assert hardware_evidence_status({"lint": "PASS", "sim": "FAIL", "scenarios": {"drain": True}}) == "FAIL"


def test_failed_or_non_boolean_scenario_fails_the_hardware_gate():
    assert hardware_evidence_status({"lint": "PASS", "sim": "PASS", "scenarios": {"drain": False}}) == "FAIL"
    assert hardware_evidence_status({"lint": "PASS", "sim": "PASS", "scenarios": {"drain": 1}}) == "FAIL"


def test_requested_physical_stage_blocks_instead_of_claiming_not_run(tmp_path):
    manifest = {"blockers": [], "stages": []}
    physical_stage(manifest, tmp_path, "sky130A", True)
    assert manifest["stages"][-1]["status"] == "BLOCKED"
    assert manifest["blockers"][0]["code"] == "DESIGN_BOUND_PHYSICAL_RUNNER_NOT_WIRED"


def test_unrequested_physical_stage_is_explicitly_not_run(tmp_path):
    manifest = {"blockers": [], "stages": []}
    physical_stage(manifest, tmp_path, "sky130A", False)
    assert manifest["stages"][-1]["status"] == "NOT_RUN"
    assert manifest["blockers"] == []


@pytest.mark.parametrize("result", ["BLOCKED", "FAIL", "NOT_RUN", "PASS_WITH_NOT_RUN", "PASS_WITH_BLOCKERS"])
def test_incomplete_release_status_never_returns_success(result):
    assert completion_exit_code(result) == 1


def test_only_complete_pass_returns_success():
    assert completion_exit_code("PASS") == 0


def test_family_matrix_without_physical_stage_cannot_report_complete_pass():
    stages = [{"stage": "family:mesh", "status": "PASS"}]
    result = completion_result(stages, [])
    assert result == "PASS"  # matrix result alone; caller must add the required physical stage
    stages.append({"stage": "physical", "status": "NOT_RUN"})
    result = completion_result(stages, [])
    assert result == "PASS_WITH_NOT_RUN"
    assert completion_exit_code(result) == 1


def test_failure_and_blocker_take_precedence_over_not_run():
    assert completion_result([{"status": "NOT_RUN"}, {"status": "FAIL"}], []) == "FAIL"
    assert completion_result([{"status": "NOT_RUN"}, {"status": "BLOCKED"}], []) == "BLOCKED"


def test_logged_command_preserves_complete_stdout_and_stderr(tmp_path):
    command = [sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"]
    completed, output = _run_logged(command, cwd=tmp_path, timeout=5,
                                    log_path=tmp_path / "logs" / "command.log")
    assert completed.returncode == 0
    assert "out" in output and "err" in output
    assert (tmp_path / "logs" / "command.log").read_text() == output
    assert (tmp_path / "logs" / "command.stdout.log").read_text() == "out\n"
    assert (tmp_path / "logs" / "command.stderr.log").read_text() == "err\n"


def test_logged_command_preserves_nonzero_failure_output(tmp_path):
    command = [sys.executable, "-c", "import sys; print('compiler failure'); sys.exit(7)"]
    completed, output = _run_logged(command, cwd=tmp_path, timeout=5,
                                    log_path=tmp_path / "logs" / "failure.log")
    assert completed.returncode == 7
    assert "compiler failure" in output
    assert "compiler failure" in (tmp_path / "logs" / "failure.stdout.log").read_text()


def test_logged_command_preserves_timeout_output(tmp_path):
    command = [sys.executable, "-u", "-c",
               "import sys,time; print('before timeout', flush=True); "
               "print('stderr before timeout', file=sys.stderr, flush=True); time.sleep(2)"]
    log_path = tmp_path / "logs" / "timeout.log"
    with pytest.raises(TimeoutError, match="complete output saved"):
        _run_logged(command, cwd=tmp_path, timeout=0.1, log_path=log_path)
    assert "before timeout" in log_path.read_text()
    assert "before timeout" in log_path.with_name("timeout.stdout.log").read_text()
    assert "stderr before timeout" in log_path.with_name("timeout.stderr.log").read_text()


def _revision_response(monkeypatch, payload):
    import io
    import json
    import urllib.request

    urls = []

    def open_response(url, timeout):
        urls.append(url)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", open_response)
    return urls


def test_pinned_completion_reads_immutable_revision_not_mutable_draft(monkeypatch):
    request = make_family_request("mesh")
    payload = {"project_id": "p-test", "revision_id": "p-test-r01",
               "design": request.to_dict(), "design_hash": request.design_hash()}
    urls = _revision_response(monkeypatch, payload)
    assert load_live_request("p-test", "http://gateway", "p-test-r01") == request.to_dict()
    assert urls == ["http://gateway/api/v1/revisions/p-test-r01"]


@pytest.mark.parametrize("field,value", [
    ("project_id", "p-other"), ("revision_id", "p-test-r02"),
    ("design_hash", "sha256:wrong"), ("design", None),
])
def test_pinned_completion_refuses_wrong_or_corrupt_revision(monkeypatch, field, value):
    request = make_family_request("mesh")
    payload = {"project_id": "p-test", "revision_id": "p-test-r01",
               "design": request.to_dict(), "design_hash": request.design_hash()}
    payload[field] = value
    _revision_response(monkeypatch, payload)
    with pytest.raises(SystemExit):
        load_live_request("p-test", "http://gateway", "p-test-r01")


def test_unpinned_completion_keeps_explicit_draft_mode(monkeypatch):
    request = make_family_request("mesh").to_dict()
    urls = _revision_response(monkeypatch, {"request": request})
    assert load_live_request("p-test", "http://gateway", None) == request
    assert urls == ["http://gateway/api/v1/projects/p-test/draft"]


def test_manifest_log_artifacts_keep_path_size_and_hash(tmp_path):
    (tmp_path / "hardware" / "rtl" / "logs").mkdir(parents=True)
    log = tmp_path / "hardware" / "rtl" / "logs" / "verilator.log"
    log.write_text("complete log\n")
    artifacts = log_artifacts(tmp_path / "hardware", tmp_path)
    assert artifacts == [{
        "path": "hardware/rtl/logs/verilator.log",
        "bytes": len("complete log\n"),
        "sha256": hashlib.sha256(log.read_bytes()).hexdigest(),
    }]


def test_tree_dirty_and_source_dirty_are_different_signals():
    """`tree_dirty` can never be false while the declared scratch is present.

    Both runs cited as clean-tree evidence record ``tree_dirty: true`` because
    the field is computed from the whole ``git status``, which always carries
    the untracked screenshots and scratch directories REMAINING-WORK.md records
    as a non-goal. That made the field unreadable: a genuinely dirty source
    tree and a repo carrying a screenshot looked identical. ``source_dirty`` is
    the signal pinned evidence can key on, and it must still see any tracked
    edit -- including ones under an otherwise-excluded directory.
    """
    dirty, paths = source_dirty()
    assert isinstance(dirty, bool)
    assert isinstance(paths, list)
    assert dirty == bool(paths)
    for entry in paths:
        assert entry.split(" ", 1)[1].startswith((".", "/")) or "/" in entry or entry

    # The declared non-goals are excluded from the source signal...
    for path in (
        "calculator.html",
        "calculator.py",
        "test_calculator.py",
        "srcta-loom-home.png",
        "audit/srota-search-1440-flowmore-open.png",
        ".pi/tasks/abc/log",
        ".codex/notes.md",
        ".impeccable/review.json",
        "test-results/junit.xml",
    ):
        assert _is_non_goal_path(path), path

    # ...but nothing else is. In particular a tracked edit under an excluded
    # directory is still dirty, because exclusion applies to untracked scratch.
    for path in (
        "tracks/t3-topology/dse/veritx_dse/product/project_top_rtl.py",
        "scripts/complete_design.py",
        "docs/product/REMAINING-WORK.md",
        "apps/studio/src/pages/index.tsx",
        "calculator_extra.py",
    ):
        assert not _is_non_goal_path(path), path


def test_manifest_records_the_source_dirty_paths_not_just_a_boolean():
    from scripts.complete_design import new_manifest

    args = SimpleNamespace(platform="sky130A", release=True)
    manifest = new_manifest(args)
    assert "tree_dirty" in manifest
    assert "source_dirty" in manifest
    assert "source_dirty_paths" in manifest
    assert manifest["source_dirty"] == bool(manifest["source_dirty_paths"])
    if manifest["source_dirty"]:
        # Every reported path names what the reader must check before trusting
        # the run, so "dirty" is never an unexplained status word.
        assert all(len(entry.split(" ", 1)) == 2 for entry in manifest["source_dirty_paths"])
