"""Wave-C study/policy/legacy tests: studies, verdicts, capabilities,
budgets, legacy classification, interruption, binary-identity rule.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
TESTS = Path(__file__).resolve().parent
sys.path.insert(0, str(DSE))
sys.path.insert(0, str(TESTS))

from veritx_dse.application.capabilities import (  # noqa: E402
    POLICY, capability_registry, check_execution_budget,
    check_study_budget,
)
from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError, ErrorCode,
)
from veritx_dse.application.legacy import classify_legacy_run  # noqa: E402
from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.application.studies import (  # noqa: E402
    StudyRequest, summarize_study,
)
from veritx_dse.core.paths import REPO  # noqa: E402


def _doc(**over):
    doc = {
        "schema_version": 1, "name": "study-fixture",
        "fabric_preset": "mesh4", "fabric_overrides": {},
        "workload": {"trace": "tiny2"},
        "backend_target": "BOOKSIM_STANDALONE", "seed": None,
        "metrics": ["sim.latency.avg_cycles"],
    }
    doc.update(over)
    return doc


@pytest.fixture()
def clean_service(tmp_path):
    git = tmp_path / "cleanrepo"
    git.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        proc = subprocess.run(["git", "-C", str(git), *args],
                              capture_output=True, timeout=30)
        if proc.returncode != 0:
            pytest.skip("git unavailable")
    (git / "src.txt").write_text("v1")
    subprocess.run(["git", "-C", str(git), "add", "src.txt"],
                   capture_output=True, timeout=30)
    proc = subprocess.run(["git", "-C", str(git), "commit", "-qm", "v1"],
                          capture_output=True, timeout=30)
    if proc.returncode != 0:
        pytest.skip("git commit unavailable")
    from veritx_dse.simulation.booksim import (  # noqa: PLC0415
        find_booksim_bin,
    )
    try:
        binary = Path(find_booksim_bin(REPO))
    except FileNotFoundError:
        pytest.skip("no runnable BookSim binary")
    return SrotaControlPlane(store_root=tmp_path / "store",
                             repo_root=git, binary=binary)


class TestStudy:
    def test_study_runs_candidates_and_compares(self, clean_service):
        study = clean_service.run_study({
            "name": "two-fabrics",
            "candidates": [_doc(name="a"),
                           _doc(name="b",
                                fabric_preset="mesh4_wide128")],
            "comparison": {
                "contract": {"metric_ids": ["sim.latency.avg_cycles"]},
                "pairs": [[0, 1]]}})
        assert study["resource_type"] == "study"
        assert [e["status"] for e in study["experiments"]] == \
            ["SUCCEEDED", "SUCCEEDED"]
        assert study["comparisons"][0]["status"] == "COMPARED"

    def test_study_collects_failures(self, clean_service, tmp_path):
        broken = tmp_path / "broken"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(
            store_root=tmp_path / "dark",
            repo_root=clean_service.repo_root, binary=broken)
        study = dark.run_study({
            "name": "mixed",
            "candidates": [_doc(name="ok"), {"bogus": 1}]})
        by_index = {e["index"]: e for e in study["experiments"]}
        assert by_index[0]["status"] == "FAILED"
        assert by_index[0]["error"]["code"] == "EXECUTION_FAILED"
        assert by_index[1]["status"] == "INVALID"

    def test_study_budget_rejects(self, clean_service):
        many = [_doc(name=f"c{i}") for i in
                range(POLICY["max_study_candidates"] + 1)]
        with pytest.raises(ControlPlaneError) as excinfo:
            clean_service.run_study({"name": "huge", "candidates": many})
        assert excinfo.value.code == ErrorCode.POLICY_REJECTED

    def test_study_id_deterministic(self):
        first = StudyRequest.parse(
            {"name": "s", "candidates": [_doc(name="a")]})
        second = StudyRequest.parse(
            {"name": "s", "candidates": [_doc(name="b")]})
        assert first.study_id() == second.study_id()

    def test_multi_seed_candidates_are_distinct_experiments(
            self, clean_service):
        study = clean_service.run_study({
            "name": "seeds",
            "candidates": [_doc(name="s42", seed=42),
                           _doc(name="s43", seed=43)]})
        ids = [e["experiment_id"] for e in study["experiments"]]
        assert len(set(ids)) == 2


class TestVerdicts:
    @pytest.mark.parametrize("records,verdict", [
        ([{"status": "SUCCEEDED", "measurable": True,
           "constraints_met": True}], "FEASIBLE"),
        ([{"status": "SUCCEEDED", "measurable": True,
           "constraints_met": False}], "NO_FEASIBLE_DESIGN"),
        ([{"status": "FAILED", "measurable": False,
           "constraints_met": False}], "INCONCLUSIVE"),
        ([{"status": "TIMED_OUT", "measurable": False,
           "constraints_met": False}], "INCONCLUSIVE"),
        ([{"status": "SUCCEEDED", "measurable": False,
           "constraints_met": False}], "CONSTRAINT_UNMEASURABLE"),
        ([{"status": "BLOCKED", "measurable": False,
           "constraints_met": False}], "UNSUPPORTED"),
    ])
    def test_verdict_rules(self, records, verdict):
        assert summarize_study(records)["verdict"] == verdict

    def test_empty_records_invalid(self):
        with pytest.raises(ControlPlaneError) as excinfo:
            summarize_study([])
        assert excinfo.value.code == ErrorCode.INVALID_INTENT
        assert excinfo.value.code != ErrorCode.NO_FEASIBLE_DESIGN


class TestPolicy:
    def test_execution_budget_rejects_not_clamps(self, clean_service):
        with pytest.raises(ControlPlaneError) as excinfo:
            clean_service.evaluate(
                _doc(timeout_s=POLICY["max_execution_seconds"] + 1))
        assert excinfo.value.code == ErrorCode.POLICY_REJECTED

    def test_check_helpers(self):
        check_execution_budget(60)
        check_study_budget(2)
        with pytest.raises(ControlPlaneError) as excinfo:
            check_execution_budget(10 ** 9)
        assert excinfo.value.code == ErrorCode.POLICY_REJECTED

    def test_query_over_budget_rejects(self, clean_service):
        from veritx_dse.application.capabilities import (  # noqa: PLC0415
            POLICY,
        )
        clean_service.evaluate(_doc())
        assert clean_service.list_results()["count"] == 1
        with pytest.raises(ControlPlaneError) as excinfo:
            clean_service.list_results(
                limit=POLICY["max_query_rows"] + 1)
        assert excinfo.value.code == ErrorCode.POLICY_REJECTED

    def test_capability_registry_shape(self):
        registry = capability_registry()
        booksim = registry["backends"]["BOOKSIM_STANDALONE"]
        assert booksim["execution"] == "SUPPORTED"
        assert booksim["route_evidence"] == "SUPPORTED"
        serving = registry["backends"]["SERVING_BOOKSIM2"]
        assert serving["execution"] == "BLOCKED"
        assert "diagnose" in registry["operations"]
        assert registry["deferred"]["rtl_verification"] == "NOT_RUN"


class TestInterruption:
    def test_keyboard_interrupt_persists_interrupted(self, clean_service,
                                                    monkeypatch):
        import veritx_dse.backend.booksim as booksim_mod  # noqa: PLC0415

        def located(*args, **kwargs):
            located.calls += 1
            raise KeyboardInterrupt()
        located.calls = 0
        # service.evaluate imports the runner binding at call time, so
        # patching the backend module attribute applies.
        monkeypatch.setattr(booksim_mod, "run_qualified_booksim",
                            located)
        with pytest.raises(KeyboardInterrupt):
            clean_service.evaluate(_doc())
        assert located.calls == 1
        attempts = list((clean_service.store.root / "attempt").glob(
            "*.json"))
        assert len(attempts) == 1
        import json
        record = json.loads(attempts[0].read_text())
        assert record["status"] == "INTERRUPTED"
        assert record["evidence_ref"] is None


class TestBinaryIdentityRule:
    def test_same_experiment_different_producer(self, clean_service,
                                                tmp_path):
        import shutil
        import stat
        from veritx_dse.simulation.booksim import (  # noqa: PLC0415
            find_booksim_bin,
        )
        src = Path(find_booksim_bin(REPO))
        alt = tmp_path / "alt-booksim"
        shutil.copy(src, alt)
        alt.chmod(alt.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP |
                  stat.S_IXOTH)
        # Same bytes, other path: same producer digest, same experiment.
        twin = SrotaControlPlane(
            store_root=tmp_path / "twin",
            repo_root=clean_service.repo_root, binary=alt)
        first = clean_service.evaluate(_doc())
        # Mutate a trailing byte: still executes, different digest.
        with open(alt, "ab") as handle:
            handle.write(b"\x00")
        second = twin.evaluate(_doc())
        assert second["experiment_id"] == first["experiment_id"]
        assert second["reused"] is False
        assert second["producer"]["binary_sha256"] != \
            first["producer"]["binary_sha256"]


class TestLegacyClassification:
    def test_wave_c_result_recognized(self, clean_service):
        res = clean_service.evaluate(_doc())
        verdict = classify_legacy_run(
            clean_service.store.root / "result" /
            f"{res['resource_id']}.json")
        assert verdict["class"] == "WAVE_C_RESULT"

    def test_legacy_dir_classified(self, tmp_path):
        run_dir = tmp_path / "old-run"
        run_dir.mkdir()
        (run_dir / "manifest.json").write_text("{}")
        verdict = classify_legacy_run(run_dir)
        assert verdict["class"] == "LEGACY_RESULT"

    def test_missing_path_classified(self, tmp_path):
        assert classify_legacy_run(
            tmp_path / "absent")["class"] == "NOT_FOUND"
