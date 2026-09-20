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
    load_verified_attempt, load_verified_result, load_verified_study,
    load_verified_studyrun,
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


def _three_candidate_request():
    return {
        "name": "three-way",
        "candidates": [_doc(name="a"),
                       _doc(name="b", fabric_preset="mesh4_wide128"),
                       _doc(name="c", fabric_preset="mesh4_hbm")],
        "comparison": {
            "contract": {"metric_ids": ["sim.latency.avg_cycles"]},
            "pairs": [[0, 1], [0, 2]]}}


class TestStudyComparisonCompleteness:
    """Exactly one verified outcome per requested comparison pair."""

    @pytest.fixture()
    def compared(self, clean_service):
        run = clean_service.run_study(_three_candidate_request())
        assert [r["status"] for r in run["comparisons"]] == \
            ["COMPARED", "COMPARED"]
        return run

    def _rewrite_rows(self, clean_service, run, rows):
        store = clean_service.store
        doc = copy.deepcopy(store.get("studyrun", run["resource_id"]))
        doc["comparisons"] = rows
        _overwrite(store, "studyrun", run["resource_id"], doc)

    def test_correct_rows_verify(self, clean_service, compared):
        load_verified_studyrun(clean_service.store,
                               compared["resource_id"])

    def test_missing_all_rows_refuses(self, clean_service, compared):
        self._rewrite_rows(clean_service, compared, [])
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(clean_service.store,
                                   compared["resource_id"])

    def test_missing_one_row_refuses(self, clean_service, compared):
        self._rewrite_rows(clean_service, compared,
                           [compared["comparisons"][0]])
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(clean_service.store,
                                   compared["resource_id"])

    def test_duplicate_row_refuses(self, clean_service, compared):
        first = compared["comparisons"][0]
        self._rewrite_rows(clean_service, compared, [first, dict(first)])
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(clean_service.store,
                                   compared["resource_id"])

    def test_replaced_pair_refuses(self, clean_service, compared):
        # [0,1] twice: one requested pair missing, another duplicated.
        first = compared["comparisons"][0]
        self._rewrite_rows(clean_service, compared, [first, dict(first)])
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(clean_service.store,
                                   compared["resource_id"])

    def test_extra_unrequested_row_refuses(self, clean_service,
                                           compared):
        rows = list(compared["comparisons"])
        rows.append({"pair": [1, 2], "status": "SKIPPED",
                     "reason": "a side has no successful result"})
        self._rewrite_rows(clean_service, compared, rows)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(clean_service.store,
                                   compared["resource_id"])

    def test_duplicate_requested_pair_refused_at_parse(self):
        with pytest.raises(ControlPlaneError) as excinfo:
            StudyRequest.parse({
                "name": "dup",
                "candidates": [_doc(name="a"), _doc(name="b")],
                "comparison": {"contract": {}, "pairs": [[0, 1], [0, 1]]}})
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_out_of_range_pair_refused_at_parse(self):
        with pytest.raises(ControlPlaneError) as excinfo:
            StudyRequest.parse({
                "name": "oor",
                "candidates": [_doc(name="a")],
                "comparison": {"contract": {}, "pairs": [[0, 1]]}})
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_directional_pairs_are_distinct(self):
        forward = StudyRequest.parse({
            "name": "d", "candidates": [_doc(name="a"),
                                       _doc(name="b")],
            "comparison": {"contract": {}, "pairs": [[0, 1], [1, 0]]}})
        assert forward.comparison["pairs"] == [[0, 1], [1, 0]]


class TestStudyTypedStatuses:
    """Typed evaluation failures survive into StudyRun entries."""

    def _status_of(self, service, request):
        run = service.run_study(request)
        return run, run["experiments"][0]

    def _sleeper_service(self, clean_service, tmp_path):
        sleeper = tmp_path / "sleeper"
        sleeper.write_text("#!/bin/sh\nsleep 30\n")
        sleeper.chmod(0o755)
        return SrotaControlPlane(
            store_root=tmp_path / "timeout_store",
            repo_root=clean_service.repo_root, binary=sleeper)

    def test_backend_failure_is_failed(self, clean_service, tmp_path):
        broken = tmp_path / "broken"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(
            store_root=tmp_path / "fail_store",
            repo_root=clean_service.repo_root, binary=broken)
        run, entry = self._status_of(
            dark, {"name": "f", "candidates": [_doc(name="x")]})
        assert entry["status"] == "FAILED"
        assert entry["error"]["code"] == "EXECUTION_FAILED"
        load_verified_studyrun(dark.store, run["resource_id"])

    def test_backend_timeout_is_timed_out(self, clean_service,
                                          tmp_path):
        dark = self._sleeper_service(clean_service, tmp_path)
        candidate = _doc(name="t")
        candidate["timeout_s"] = 1
        run, entry = self._status_of(
            dark, {"name": "t", "candidates": [candidate]})
        assert entry["status"] == "TIMED_OUT"
        assert entry["error"]["code"] == "EXECUTION_TIMEOUT"
        load_verified_studyrun(dark.store, run["resource_id"])

    def test_analytical_candidate_is_unsupported(self, clean_service):
        run, entry = self._status_of(clean_service, {
            "name": "u",
            "candidates": [_doc(name="a",
                                backend_target="SERVING_ANALYTICAL_AWARE")]})
        assert entry["status"] == "UNSUPPORTED"
        assert entry["error"]["code"] == "UNSUPPORTED_SEMANTICS"
        load_verified_studyrun(clean_service.store, run["resource_id"])

    def test_serving_candidate_is_blocked(self, clean_service):
        run, entry = self._status_of(clean_service, {
            "name": "b",
            "candidates": [_doc(name="a",
                                backend_target="SERVING_BOOKSIM2")]})
        assert entry["status"] == "BLOCKED"
        assert entry["error"]["code"] == "UNSUPPORTED_SEMANTICS"
        load_verified_studyrun(clean_service.store, run["resource_id"])

    def test_lowering_unsupported_maps_unsupported(self):
        from veritx_dse.application.studies import (  # noqa: PLC0415
            study_status_for_code,
        )
        assert study_status_for_code(
            ErrorCode.LOWERING_UNSUPPORTED,
            backend_target="BOOKSIM_STANDALONE") == "UNSUPPORTED"
        assert study_status_for_code(
            ErrorCode.POLICY_REJECTED) == "FAILED"

    def _tamper_entry(self, service, run, **fields):
        store = service.store
        doc = copy.deepcopy(store.get("studyrun", run["resource_id"]))
        doc["experiments"][0].update(fields)
        _overwrite(store, "studyrun", run["resource_id"], doc)
        with pytest.raises(ControlPlaneError):
            load_verified_studyrun(store, run["resource_id"])

    def test_timed_out_with_failure_code_refuses(self, clean_service,
                                                 tmp_path):
        dark = self._sleeper_service(clean_service, tmp_path)
        candidate = _doc(name="t")
        candidate["timeout_s"] = 1
        run, _ = self._status_of(
            dark, {"name": "t2", "candidates": [candidate]})
        self._tamper_entry(dark, run,
                           error={"code": "EXECUTION_FAILED",
                                  "message": "forged",
                                  "operation": "evaluate",
                                  "resource_id": "", "cause_type": "",
                                  "details": {}})

    def test_failed_with_timeout_code_refuses(self, clean_service,
                                              tmp_path):
        broken = tmp_path / "broken9"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(
            store_root=tmp_path / "fail_store9",
            repo_root=clean_service.repo_root, binary=broken)
        run, _ = self._status_of(
            dark, {"name": "f9", "candidates": [_doc(name="x")]})
        self._tamper_entry(dark, run,
                           error={"code": "EXECUTION_TIMEOUT",
                                  "message": "forged",
                                  "operation": "evaluate",
                                  "resource_id": "", "cause_type": "",
                                  "details": {}})

    def test_unsupported_with_execution_error_refuses(self,
                                                      clean_service):
        run, _ = self._status_of(clean_service, {
            "name": "u2",
            "candidates": [_doc(name="a",
                                backend_target="SERVING_ANALYTICAL_AWARE")]})
        self._tamper_entry(clean_service, run,
                           error={"code": "EXECUTION_FAILED",
                                  "message": "forged",
                                  "operation": "evaluate",
                                  "resource_id": "", "cause_type": "",
                                  "details": {}})

    def test_unsupported_relabelled_blocked_refuses(self, clean_service):
        run, _ = self._status_of(clean_service, {
            "name": "u3",
            "candidates": [_doc(name="a",
                                backend_target="SERVING_ANALYTICAL_AWARE")]})
        self._tamper_entry(clean_service, run, status="BLOCKED")

    def test_unknown_error_code_refuses(self, clean_service, tmp_path):
        broken = tmp_path / "broken10"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(
            store_root=tmp_path / "fail_store10",
            repo_root=clean_service.repo_root, binary=broken)
        run, _ = self._status_of(
            dark, {"name": "f10", "candidates": [_doc(name="x")]})
        self._tamper_entry(dark, run,
                           error={"code": "NOT_A_CODE", "message": "x",
                                  "operation": "evaluate",
                                  "resource_id": "", "cause_type": "",
                                  "details": {}})


class TestAttemptStructure:
    """Non-success attempts: coherent, never authenticated success."""

    def _failed_attempt(self, clean_service, tmp_path):
        broken = tmp_path / "brokenA"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        service = SrotaControlPlane(
            store_root=tmp_path / "storeA",
            repo_root=clean_service.repo_root, binary=broken)
        with pytest.raises(ControlPlaneError) as excinfo:
            service.evaluate(_doc(name="f"))
        return service, excinfo.value.resource_id

    def _timed_out_attempt(self, clean_service, tmp_path):
        sleeper = tmp_path / "sleeperA"
        sleeper.write_text("#!/bin/sh\nsleep 30\n")
        sleeper.chmod(0o755)
        service = SrotaControlPlane(
            store_root=tmp_path / "storeB",
            repo_root=clean_service.repo_root, binary=sleeper)
        candidate = _doc(name="t")
        candidate["timeout_s"] = 1
        with pytest.raises(ControlPlaneError) as excinfo:
            service.evaluate(candidate)
        return service, excinfo.value.resource_id

    def test_failed_attempt_is_structurally_valid(self, clean_service,
                                                  tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        described = service.inspect(attempt_id)
        assert described["integrity"]["state"] == "STRUCTURALLY_VALID"
        assert described["integrity"]["evidence"] == "NOT_AVAILABLE"

    def test_timed_out_attempt_is_structurally_valid(self,
                                                     clean_service,
                                                     tmp_path):
        service, attempt_id = self._timed_out_attempt(clean_service,
                                                      tmp_path)
        described = service.inspect(attempt_id)
        assert described["integrity"]["state"] == "STRUCTURALLY_VALID"
        assert described["record"]["error"]["code"] == \
            "EXECUTION_TIMEOUT"

    def test_interrupted_attempt_is_structurally_valid(self,
                                                       clean_service):
        from veritx_dse.application.resources import AttemptRecord
        store = clean_service.store
        attempt = AttemptRecord(
            attempt_id="01a0be00-0000-7000-8000-00000000abcd",
            experiment_id="experiment:" + "0" * 64,
            status="INTERRUPTED", backend_dir="/tmp/x",
            producer={}, error={"code": "INTERRUPTED",
                                "message": "KeyboardInterrupt"},
            runtime={})
        store.put("attempt", attempt.attempt_id, attempt.to_dict())
        # No experiment exists for this synthetic record: linkage refuses.
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, attempt.attempt_id)

    def test_planned_attempt_with_error_refuses(self, clean_service):
        from veritx_dse.application.resources import AttemptRecord
        store = clean_service.store
        attempt = AttemptRecord(
            attempt_id="01a0be00-0000-7000-8000-00000000abce",
            experiment_id="experiment:" + "0" * 64,
            status="PLANNED", backend_dir="/tmp/x", producer={},
            error={"code": "EXECUTION_FAILED", "message": "x"},
            runtime={})
        store.put("attempt", attempt.attempt_id, attempt.to_dict())
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, attempt.attempt_id)

    def _tamper(self, service, attempt_id, mutate):
        store = service.store
        doc = copy.deepcopy(store.get("attempt", attempt_id))
        mutate(doc)
        _overwrite(store, "attempt", attempt_id, doc)
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, attempt_id)

    def test_failed_relabelled_timed_out_refuses(self, clean_service,
                                                 tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d.update({"status": "TIMED_OUT"}))

    def test_timed_out_relabelled_failed_refuses(self, clean_service,
                                                 tmp_path):
        service, attempt_id = self._timed_out_attempt(clean_service,
                                                      tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d.update({"status": "FAILED"}))

    def test_interrupted_without_marker_refuses(self, clean_service,
                                                tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d.update({"status": "INTERRUPTED"}))

    def test_evidence_ref_on_failed_attempt_refuses(self, clean_service,
                                                    tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d.update({
                         "evidence_ref": {"path": "/tmp/x",
                                          "sha256": "0" * 64}}))

    def test_evidence_ref_on_timed_out_attempt_refuses(self,
                                                       clean_service,
                                                       tmp_path):
        service, attempt_id = self._timed_out_attempt(clean_service,
                                                      tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d.update({
                         "evidence_ref": {"path": "/tmp/x",
                                          "sha256": "0" * 64}}))

    def test_missing_error_payload_refuses(self, clean_service,
                                           tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d.pop("error", None))

    def test_unknown_error_code_refuses(self, clean_service, tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        self._tamper(service, attempt_id,
                     lambda d: d["error"].update({"code": "NOPE"}))

    def test_legitimate_failed_attempt_verifies_without_evidence(
            self, clean_service, tmp_path):
        service, attempt_id = self._failed_attempt(clean_service,
                                                   tmp_path)
        record = load_verified_attempt(service.store, attempt_id)
        assert record["status"] == "FAILED"
        assert record["error"]["code"] == "EXECUTION_FAILED"
        assert record.get("evidence_ref") is None
        directory = service.store.root / "result"
        assert not list(directory.glob("*.json"))


class TestAttemptTerminalStateClosure:
    """SUCCEEDED admits no error; every status has an explicit rule."""

    def test_succeeded_with_forged_error_refuses(self, clean_service):
        result = clean_service.evaluate(_doc(name="ok"))
        attempt_id = result["attempt_id"]
        load_verified_attempt(clean_service.store, attempt_id)
        store = clean_service.store
        doc = copy.deepcopy(store.get("attempt", attempt_id))
        doc["error"] = {"code": "EXECUTION_FAILED",
                        "message": "forged failure",
                        "operation": "evaluate", "resource_id": attempt_id,
                        "cause_type": "", "details": {}}
        _overwrite(store, "attempt", attempt_id, doc)
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, attempt_id)
        with pytest.raises(ControlPlaneError):
            load_verified_result(store, result["resource_id"])
        described = clean_service.inspect(attempt_id)
        assert described["integrity"]["state"] == "INVALID"

    def test_succeeded_error_message_only_refuses(self, clean_service):
        result = clean_service.evaluate(_doc(name="ok2"))
        attempt_id = result["attempt_id"]
        store = clean_service.store
        doc = copy.deepcopy(store.get("attempt", attempt_id))
        doc["error"] = {"message": "forged"}
        _overwrite(store, "attempt", attempt_id, doc)
        with pytest.raises(ControlPlaneError):
            load_verified_attempt(store, attempt_id)

    def test_every_attempt_status_has_explicit_rule(self):
        from veritx_dse.application.service import (  # noqa: PLC0415
            ATTEMPT_STATUSES,
        )
        assert set(ATTEMPT_STATUSES) == {
            "PLANNED", "RUNNING", "SUCCEEDED", "FAILED",
            "TIMED_OUT", "INTERRUPTED"}
        # No dead states, and no state may fall through into another
        # state's structural rule: the final guard in
        # _verify_attempt_structure refuses anything unlisted.
        import inspect  # noqa: PLC0415
        from veritx_dse.application import results as res  # noqa: PLC0415
        source = inspect.getsource(res._verify_attempt_structure)
        assert "has no verification rule for status" in source
        source_loader = inspect.getsource(res.load_verified_attempt)
        assert "carries an" in source_loader and \
            "error payload" in source_loader
