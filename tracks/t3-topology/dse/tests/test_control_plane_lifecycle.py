"""Wave C-FINAL: study/attempt lifecycle integrity.

Deterministic StudyDefinition vs execution-dependent StudyRun; full
per-entry verification; attempt producer binding; study inspect.
"""
from __future__ import annotations

import copy
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
from veritx_dse.application.results import (  # noqa: E402
    load_verified_study, load_verified_studyrun,
)
from veritx_dse.application.service import (  # noqa: E402
    SrotaControlPlane,
)
from veritx_dse.application.studies import StudyRequest  # noqa: E402
from test_control_plane_studies import (  # noqa: E402
    _doc, clean_service,
)


def _overwrite(store, kind, resource_id, doc):
    from veritx_dse.core.spec import canonical_json  # noqa: PLC0415
    store._path(kind, resource_id).write_text(canonical_json(doc))


def _two_candidate_request():
    return {
        "name": "lifecycle",
        "candidates": [_doc(name="a"),
                           _doc(name="b",
                                fabric_preset="mesh4_wide128")],
        "comparison": {
            "contract": {"metric_ids": ["sim.latency.avg_cycles"]},
            "pairs": [[0, 1]]}}


def _run_ok(service):
    return service.run_study(_two_candidate_request())


class TestStudyRerun:
    def test_rerun_is_a_new_run_not_a_conflict(self, clean_service):
        first = _run_ok(clean_service)
        second = _run_ok(clean_service)
        assert first["study_id"] == second["study_id"]
        assert first["resource_id"] != second["resource_id"]
        assert first["study_id"] == StudyRequest.parse(
            _two_candidate_request()).study_id()
        load_verified_studyrun(clean_service.store,
                               first["resource_id"])
        load_verified_studyrun(clean_service.store,
                               second["resource_id"])

    def test_reused_flag_is_observation_not_identity(self,
                                                     clean_service):
        first = _run_ok(clean_service)
        flags = [e["reused"] for e in first["experiments"]]
        assert flags == [False, False]
        second = _run_ok(clean_service)
        assert [e["reused"] for e in second["experiments"]] == \
            [True, True]
        load_verified_studyrun(clean_service.store,
                               second["resource_id"])

    def test_ordering_is_directional(self):
        wide = _doc(fabric_preset="mesh4_wide128")
        forward = StudyRequest.parse({
            "name": "d", "candidates": [_doc(name="a"), wide]})
        backward = StudyRequest.parse({
            "name": "d", "candidates": [wide, _doc(name="a")]})
        assert forward.study_id() != backward.study_id()


class TestStudySummaryTamper:
    @pytest.fixture()
    def verified_run(self, clean_service):
        run = _run_ok(clean_service)
        load_verified_studyrun(clean_service.store,
                               run["resource_id"])
        return run

    def _tamper_entry(self, clean_service, run, key, value):
        store = clean_service.store
        doc = copy.deepcopy(store.get("studyrun", run["resource_id"]))
        doc["experiments"][0][key] = value
        _overwrite(store, "studyrun", run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, run["resource_id"])

    def test_tamper_index(self, clean_service, verified_run):
        self._tamper_entry(clean_service, verified_run, "index", 7)

    def test_tamper_candidate_identity(self, clean_service,
                                       verified_run):
        self._tamper_entry(clean_service, verified_run,
                           "candidate_identity", "intent:" + "0" * 64)

    def test_tamper_status_to_failed(self, clean_service,
                                     verified_run):
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("studyrun", verified_run["resource_id"]))
        doc["experiments"][0].update({
            "status": "FAILED", "intent_id": "garbage",
            "experiment_id": "garbage", "reused": True})
        _overwrite(store, "studyrun", verified_run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, verified_run["resource_id"])

    def test_tamper_intent_id(self, clean_service, verified_run):
        self._tamper_entry(clean_service, verified_run,
                           "intent_id", "intent:" + "0" * 64)

    def test_tamper_experiment_id(self, clean_service, verified_run):
        self._tamper_entry(clean_service, verified_run,
                           "experiment_id", "experiment:" + "0" * 64)

    def test_tamper_result_id(self, clean_service, verified_run):
        self._tamper_entry(clean_service, verified_run,
                           "result_id", "result:" + "0" * 64)

    def test_reused_mutation_still_verifies(self, clean_service,
                                           verified_run):
        # reused is operational observation, not a scientific claim.
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("studyrun", verified_run["resource_id"]))
        doc["experiments"][0]["reused"] = not \
            doc["experiments"][0]["reused"]
        _overwrite(store, "studyrun", verified_run["resource_id"], doc)
        load_verified_studyrun(store, verified_run["resource_id"])

    def test_tamper_error_classification(self, clean_service,
                                        tmp_path):
        from veritx_dse.application.errors import ControlPlaneError
        broken = tmp_path / "broken2"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(
            store_root=tmp_path / "dark2",
            repo_root=clean_service.repo_root, binary=broken)
        run = dark.run_study({"name": "fail",
                              "candidates": [_doc(name="ok")]})
        doc = copy.deepcopy(
            dark.store.get("studyrun", run["resource_id"]))
        assert doc["experiments"][0]["status"] == "FAILED"
        doc["experiments"][0]["error"]["code"] = "TIMEOUT"
        doc["experiments"][0]["status"] = "TIMED_OUT"
        _overwrite(dark.store, "studyrun", run["resource_id"], doc)
        # Forged status/code pair: TIMEOUT is not a real error code and
        # the recorded failure was EXECUTION_FAILED.
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(dark.store, run["resource_id"])

    def test_tamper_study_id_link(self, clean_service, verified_run):
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("studyrun", verified_run["resource_id"]))
        doc["study_id"] = "0" * 64
        _overwrite(store, "studyrun", verified_run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, verified_run["resource_id"])

    def test_tamper_run_id_filename(self, clean_service, verified_run):
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("studyrun", verified_run["resource_id"]))
        doc["resource_id"] = "f" * 64
        _overwrite(store, "studyrun", verified_run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, verified_run["resource_id"])


class TestStudyComparisonRowTamper:
    @pytest.fixture()
    def compared_run(self, clean_service):
        run = _run_ok(clean_service)
        assert run["comparisons"][0]["status"] == "COMPARED"
        return run

    def _tamper_row(self, clean_service, run, key, value):
        store = clean_service.store
        doc = copy.deepcopy(store.get("studyrun", run["resource_id"]))
        doc["comparisons"][0][key] = value
        _overwrite(store, "studyrun", run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, run["resource_id"])

    def test_tamper_pair(self, clean_service, compared_run):
        self._tamper_row(clean_service, compared_run, "pair", [1, 0])

    def test_tamper_status(self, clean_service, compared_run):
        self._tamper_row(clean_service, compared_run, "status",
                         "SKIPPED")

    def test_tamper_comparison_id(self, clean_service, compared_run):
        self._tamper_row(clean_service, compared_run,
                         "comparison_id", "comparison:" + "0" * 64)

    def test_forged_refusal_row_refuses(self, clean_service):
        """A COMPARED row relabeled REFUSED must not verify."""
        run = _run_ok(clean_service)
        assert run["comparisons"][0]["status"] == "COMPARED"
        store = clean_service.store
        doc = copy.deepcopy(store.get("studyrun", run["resource_id"]))
        row = doc["comparisons"][0]
        row.pop("comparison_id", None)
        row["status"] = "REFUSED"
        row["reason"] = "forged"
        row["error"] = {"code": "COMPARISON_INCOMPATIBLE",
                        "message": "forged", "operation": "compare",
                        "resource_id": "", "cause_type": "",
                        "details": {}}
        _overwrite(store, "studyrun", run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, run["resource_id"])

    def test_swapped_comparison_id_refuses(self, clean_service):
        wide = _doc(name="w", fabric_preset="mesh4_wide128")
        block = {
            "contract": {"metric_ids": ["sim.latency.avg_cycles"]},
            "pairs": [[0, 1]]}
        first = clean_service.run_study({
            "name": "swap-a",
            "candidates": [_doc(name="a"), wide],
            "comparison": block})
        second = clean_service.run_study({
            "name": "swap-b",
            "candidates": [wide, _doc(name="a")],
            "comparison": block})
        assert first["comparisons"][0]["status"] == "COMPARED"
        assert second["comparisons"][0]["status"] == "COMPARED"
        assert first["comparisons"][0]["comparison_id"] != \
            second["comparisons"][0]["comparison_id"]
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("studyrun", second["resource_id"]))
        doc["comparisons"][0]["comparison_id"] = \
            first["comparisons"][0]["comparison_id"]
        _overwrite(store, "studyrun", second["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, second["resource_id"])


class TestAttemptProvenance:
    @pytest.fixture()
    def success(self, clean_service):
        result = clean_service.evaluate(_doc(name="prov"))
        attempt = clean_service.store.get("attempt",
                                          result["attempt_id"])
        assert attempt["status"] == "SUCCEEDED"
        return result, attempt

    @pytest.mark.parametrize("field", [
        "binary_sha256", "source_revision", "source_dirty",
        "source_dirty_digest", "tool_identity"])
    def test_producer_field_tamper_refuses(self, clean_service,
                                           success, field):
        from veritx_dse.application.results import (  # noqa: PLC0415
            load_verified_attempt, load_verified_result,
        )
        result, attempt = success
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("attempt", result["attempt_id"]))
        doc["producer"][field] = "forged"
        _overwrite(store, "attempt", result["attempt_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, result["attempt_id"])
        # The linked result ceases to verify as well.
        with pytest.raises(ControlPlaneError):
            load_verified_result(store, result["resource_id"])
        described = clean_service.inspect(result["attempt_id"])
        assert described["integrity"]["state"] == "INVALID"

    def test_status_flip_refuses(self, clean_service, success):
        from veritx_dse.application.results import (  # noqa: PLC0415
            load_verified_attempt,
        )
        result, _ = success
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("attempt", result["attempt_id"]))
        doc["status"] = "FAILED"
        _overwrite(store, "attempt", result["attempt_id"], doc)
        # FAILED with a success evidence trail is not a valid record:
        # the result chain (which requires SUCCEEDED) must refuse.
        from veritx_dse.application.results import (  # noqa: PLC0415
            load_verified_result,
        )
        with pytest.raises(ControlPlaneError):
            load_verified_result(store, result["resource_id"])

    def test_evidence_ref_tamper_refuses(self, clean_service,
                                        success):
        from veritx_dse.application.results import (  # noqa: PLC0415
            load_verified_attempt,
        )
        result, _ = success
        store = clean_service.store
        doc = copy.deepcopy(
            store.get("attempt", result["attempt_id"]))
        doc["evidence_ref"]["sha256"] = "0" * 64
        _overwrite(store, "attempt", result["attempt_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, result["attempt_id"])

    def test_failed_attempt_is_structural_not_verified(self,
                                                      clean_service,
                                                      tmp_path):
        broken = tmp_path / "broken3"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(
            store_root=tmp_path / "dark3",
            repo_root=clean_service.repo_root, binary=broken)
        with pytest.raises(ControlPlaneError):
            dark.evaluate(_doc(name="fails"))
        attempts = sorted(
            p.stem for p in
            (dark.store.root / "attempt").glob("*.json"))
        assert len(attempts) == 1
        described = dark.inspect(attempts[0])
        assert described["integrity"]["state"] == "STRUCTURALLY_VALID"
        assert described["integrity"]["evidence"] == "NOT_AVAILABLE"


class TestStudyCli:
    """Real CLI transport for study/compare (not intent documents)."""

    def _cli(self, *args, timeout=600):
        import json as _json  # noqa: PLC0415
        import os  # noqa: PLC0415
        import subprocess  # noqa: PLC0415
        env = dict(os.environ, PYTHONPATH=str(DSE))
        proc = subprocess.run(
            [sys.executable, "-m", "veritx_dse.cli", "--json", *args],
            cwd=str(DSE), capture_output=True, text=True,
            timeout=timeout, env=env, stdin=subprocess.DEVNULL)
        payload = None
        if proc.stdout.strip():
            try:
                payload = _json.loads(proc.stdout)
            except ValueError:
                payload = None
        return proc.returncode, payload

    def test_study_cli_rerun_and_inspect(self, tmp_path):
        request = tmp_path / "study.json"
        request.write_text(json.dumps(_two_candidate_request()))
        store = tmp_path / "store"
        rc, first = self._cli("service", "study", "--request",
                              str(request), "--store", str(store))
        assert rc == 0, first
        rc, second = self._cli("service", "study", "--request",
                               str(request), "--store", str(store))
        assert rc == 0, second
        first, second = first["result"], second["result"]
        assert first["study_id"] == second["study_id"]
        assert first["resource_id"] != second["resource_id"]
        assert [e["status"] for e in first["experiments"]] == \
            ["SUCCEEDED", "SUCCEEDED"]
        # Comparison may be REFUSED in a dirty worktree (clean-tree
        # gate); either way the row must verify.
        assert first["comparisons"][0]["status"] in (
            "COMPARED", "REFUSED")
        for target in (first["study_id"], first["resource_id"]):
            rc, described = self._cli("service", "inspect", "--resource-id",
                                      target, "--store", str(store))
            assert rc == 0, described
            assert described["result"]["integrity"]["state"] == \
                "VERIFIED"

    def test_study_cli_mixed_invalid_candidate(self, tmp_path):
        request = tmp_path / "mixed.json"
        request.write_text(json.dumps({
            "name": "mixed-cli",
            "candidates": [_doc(name="ok"), {"bogus": 1}]}))
        store = tmp_path / "store"
        rc, payload = self._cli("service", "study", "--request",
                                str(request), "--store", str(store))
        assert rc == 0, payload
        run = payload["result"]
        by_index = {e["index"]: e for e in run["experiments"]}
        assert by_index[0]["status"] == "SUCCEEDED"
        assert by_index[1]["status"] == "INVALID"
        assert by_index[1]["candidate_identity"].startswith("invalid:")
        assert len(run["candidate_intents"]) == 2
        for target in (run["study_id"], run["resource_id"]):
            rc, described = self._cli("service", "inspect", "--resource-id",
                                      target, "--store", str(store))
            assert rc == 0, described
            assert described["result"]["integrity"]["state"] == \
                "VERIFIED"


class TestStudyInspect:
    def test_inspect_definition_and_run(self, clean_service):
        run = _run_ok(clean_service)
        definition = clean_service.inspect(run["study_id"])
        assert definition["integrity"]["state"] == "VERIFIED"
        assert definition["kind"] == "studydef"
        observed = clean_service.inspect(run["resource_id"])
        assert observed["integrity"]["state"] == "VERIFIED"
        assert observed["record"]["study_id"] == run["study_id"]
        assert observed["related"]["studydef"]["resource_id"] == \
            run["study_id"]
        assert run["resource_id"] in definition["related"]["runs"]

    def test_inspect_unknown_study_is_not_found(self,
                                               clean_service):
        with pytest.raises(ControlPlaneError) as excinfo:
            clean_service.inspect("0" * 64)
        assert excinfo.value.code == ErrorCode.NOT_FOUND
