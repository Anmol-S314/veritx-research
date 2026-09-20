"""Wave C.1 integrity tests: the control plane's own artifacts attacked.

Wave B correctly protects Wave-B evidence; these tests attack the NEW
Wave-C summary layer: persisted result fields, reuse links, external
workload identity, and directional comparison/study IDs.
"""
from __future__ import annotations

import copy
import json
import subprocess
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
from veritx_dse.core.paths import REPO  # noqa: E402


def _doc(**over):
    doc = {
        "schema_version": 1, "name": "integrity",
        "fabric_preset": "mesh4", "fabric_overrides": {},
        "workload": {"trace": "tiny2"},
        "backend_target": "BOOKSIM_STANDALONE", "seed": None,
        "metrics": ["sim.latency.avg_cycles", "sim.delivered.packets"],
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


def _read_result(service, result_id):
    return service.store.get("result", result_id)


class TestResultSummaryTamper:
    @pytest.fixture()
    def persisted(self, clean_service):
        res = clean_service.evaluate(_doc())
        return clean_service, res

    def _check_refused(self, service, res, label):
        # Compare refuses.
        wide = service.evaluate(_doc(name="wide",
                                     fabric_preset="mesh4_wide128"))
        with pytest.raises(ControlPlaneError) as excinfo:
            service.compare({
                "candidate_ids": [res["resource_id"],
                                  wide["resource_id"]],
                "contract": {"metric_ids": ["sim.latency.avg_cycles"]}})
        assert excinfo.value.code in (
            ErrorCode.COMPARISON_INCOMPATIBLE, ErrorCode.EVIDENCE_INVALID), \
            label
        # Reuse refuses (falls through to fresh execution).
        fresh = service.evaluate(_doc())
        assert fresh["reused"] is False, label
        assert fresh["attempt_id"] != res["attempt_id"], label
        # Inspect reports invalid chain.
        status = service.inspect(
            res["resource_id"])["evidence_status"]
        assert status["chain_integrity"] is False, label
        assert status["verified"] is False, label

    @pytest.mark.parametrize("field", [
        "qualification", "execution_transport", "semantic_loss",
        "loss_digest", "producer", "seed", "seed_policy",
        "backend_config_hash", "backend_input_hash", "fabric_hash",
        "workload_hash", "metric_schema_version", "evidence_ref",
        "attempt_id", "experiment_id", "plan_id",
    ])
    def test_summary_field_tamper_refused(self, persisted, field):
        service, res = persisted
        path = service.store.root / "result" / f"{res['resource_id']}.json"
        raw = path.read_bytes()
        try:
            forged = json.loads(raw.decode())
            if field == "semantic_loss":
                forged[field] = []
            elif field == "producer":
                forged[field] = dict(forged[field])
                forged[field]["binary_sha256"] = "0" * 64
            elif field == "evidence_ref":
                forged[field] = dict(forged[field])
                forged[field]["sha256"] = "0" * 64
            elif field in ("seed",):
                forged[field] = 424242
            elif field in ("attempt_id", "experiment_id", "plan_id"):
                forged[field] = "0" * 16
            elif field.endswith("_hash") or field == "loss_digest":
                forged[field] = "0" * 64
            elif field == "metric_schema_version":
                forged[field] = "other/v9"
            else:
                forged[field] = "FORGED"
            path.write_bytes(json.dumps(forged).encode())
            self._check_refused(service, res, field)
        finally:
            path.write_bytes(raw)

    def test_metric_value_tamper_refused(self, persisted):
        service, res = persisted
        path = service.store.root / "result" / f"{res['resource_id']}.json"
        raw = path.read_bytes()
        try:
            forged = json.loads(raw.decode())
            assert forged["metrics"][0]["metric_id"] == \
                "sim.latency.avg_cycles"
            forged["metrics"][0]["value"] = 0.000001
            path.write_bytes(json.dumps(forged).encode())
            self._check_refused(service, res, "metric value")
        finally:
            path.write_bytes(raw)

    def test_metric_unit_tamper_refused(self, persisted):
        service, res = persisted
        path = service.store.root / "result" / f"{res['resource_id']}.json"
        raw = path.read_bytes()
        try:
            forged = json.loads(raw.decode())
            forged["metrics"][0]["unit"] = "parsecs"
            path.write_bytes(json.dumps(forged).encode())
            self._check_refused(service, res, "metric unit")
        finally:
            path.write_bytes(raw)


class TestLinkTransplant:
    def test_transplanted_link_reexecutes(self, clean_service):
        svc = clean_service
        doc_a = _doc(name="a")
        doc_b = _doc(name="b", fabric_preset="mesh4_wide128")
        res_a = svc.evaluate(doc_a)
        res_b = svc.evaluate(doc_b)
        exp_a = res_a["experiment_id"]
        link_id = f"experiment-result-{exp_a}"
        link_path = svc.store.root / "links" / f"{link_id}.json"
        raw_link = link_path.read_bytes()
        try:
            transplant = json.loads(raw_link.decode())
            transplant["result_id"] = res_b["resource_id"]
            link_path.write_bytes(json.dumps(transplant).encode())
            # Must NOT return result B for intent A: fresh attempt for A.
            out = svc.evaluate(doc_a)
            assert out["reused"] is False
            assert out["experiment_id"] == exp_a
            assert out["resource_id"] != res_b["resource_id"]
        finally:
            link_path.write_bytes(raw_link)


class TestExternalTraceIdentity:
    def test_same_bytes_different_paths_same_ids(self, clean_service,
                                                 tmp_path):
        a = tmp_path / "a.trace"
        b = tmp_path / "sub" / "b.trace"
        b.parent.mkdir()
        a.write_bytes(b"0 0 0 3 2\n10 3 0 0 2\n")
        b.write_bytes(b"0 0 0 3 2\n10 3 0 0 2\n")
        from veritx_dse.application.surfaces import python_intent
        ia = python_intent(_doc(workload={"trace_file": str(a)}))
        ib = python_intent(_doc(workload={"trace_file": str(b)}))
        assert ia.intent_id() == ib.intent_id()
        ra = clean_service.evaluate(_doc(workload={"trace_file": str(a)}))
        rb = clean_service.evaluate(_doc(workload={"trace_file": str(b)}))
        assert rb["experiment_id"] == ra["experiment_id"]
        assert rb["reused"] is True

    def test_different_bytes_different_ids(self, clean_service, tmp_path):
        a = tmp_path / "a.trace"
        b = tmp_path / "b.trace"
        a.write_bytes(b"0 0 0 3 2\n10 3 0 0 2\n")
        b.write_bytes(b"1 0 0 3 1\n11 3 0 0 1\n")
        from veritx_dse.application.surfaces import python_intent
        assert python_intent(
            _doc(workload={"trace_file": str(a)})).intent_id() != \
            python_intent(
                _doc(workload={"trace_file": str(b)})).intent_id()
        ra = clean_service.evaluate(_doc(workload={"trace_file": str(a)}))
        rb = clean_service.evaluate(_doc(workload={"trace_file": str(b)}))
        assert rb["experiment_id"] != ra["experiment_id"]
        assert rb["reused"] is False

    def test_mutated_file_between_resolution_and_execution(self,
                                                           clean_service,
                                                           tmp_path):
        from veritx_dse.application.requests import resolve_intent
        target = tmp_path / "live.trace"
        target.write_bytes(b"0 0 0 3 2\n10 3 0 0 2\n")
        doc = _doc(workload={"trace_file": str(target)})
        first, _, _ = resolve_intent(doc)
        exp_a = clean_service.evaluate(doc)["experiment_id"]
        # Mutate the file: the same document now resolves differently.
        target.write_bytes(b"1 0 0 3 1\n11 3 0 0 1\n")
        second, _, _ = resolve_intent(doc)
        assert second.intent_id() != first.intent_id()
        exp_b = clean_service.evaluate(doc)["experiment_id"]
        assert exp_b != exp_a
        # And a stale explicit digest refuses outright.
        stale = dict(doc)
        stale["workload"] = {"trace_file": str(target),
                             "trace_sha256": first.workload.trace_sha256}
        with pytest.raises(ControlPlaneError) as excinfo:
            clean_service.evaluate(stale)
        assert excinfo.value.code == ErrorCode.INVALID_INTENT


class TestDirectionalIdentity:
    def test_comparison_order_reverses(self, clean_service):
        a = clean_service.evaluate(_doc(name="a"))
        b = clean_service.evaluate(
            _doc(name="b", fabric_preset="mesh4_wide128"))
        contract = {"comparison_kind": "DESIGN_COMPARISON",
                    "metric_ids": ["sim.latency.avg_cycles"]}
        ab = clean_service.compare(
            {"candidate_ids": [a["resource_id"], b["resource_id"]],
             "contract": contract})
        ba = clean_service.compare(
            {"candidate_ids": [b["resource_id"], a["resource_id"]],
             "contract": contract})
        assert ab["resource_id"] != ba["resource_id"]
        assert ab["metrics"][0]["delta_b_minus_a"] == \
            -ba["metrics"][0]["delta_b_minus_a"]
        assert ab["metrics"][0]["a_value"] == \
            ba["metrics"][0]["b_value"]

    def test_study_order_reverses(self, clean_service):
        one = clean_service.run_study({
            "name": "order",
            "candidates": [_doc(name="a"), _doc(name="b", seed=7)]})
        two = clean_service.run_study({
            "name": "order",
            "candidates": [_doc(name="b", seed=7), _doc(name="a")]})
        assert one["resource_id"] != two["resource_id"]
