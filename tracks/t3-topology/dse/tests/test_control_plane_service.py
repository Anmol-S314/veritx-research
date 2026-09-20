"""Wave-C service tests: compile/plan/evaluate/inspect + failure taxonomy.

Semantic flow uses the real BookSim binary (skip when absent); refusal
paths need no execution. Table-driven error codes prove failure
semantics — especially that crashes/timeouts/unsupported are never
NO_FEASIBLE_DESIGN.
"""
from __future__ import annotations

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
        "schema_version": 1, "name": "svc-fixture",
        "fabric_preset": "mesh4", "fabric_overrides": {},
        "workload": {"trace": "tiny2"},
        "backend_target": "BOOKSIM_STANDALONE", "seed": None,
        "metrics": ["sim.latency.avg_cycles", "sim.delivered.packets"],
    }
    doc.update(over)
    return doc


@pytest.fixture()
def service(tmp_path):
    return SrotaControlPlane(store_root=tmp_path / "store")


@pytest.fixture()
def clean_service(tmp_path):
    """Service rooted at a clean scratch git checkout (pinned reuse)."""
    import subprocess
    git = tmp_path / "cleanrepo"
    git.mkdir()
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        proc = subprocess.run(["git", "-C", str(git), *args],
                              capture_output=True, timeout=30)
        if proc.returncode != 0:
            pytest.skip("git unavailable")
    (git / "src.txt").write_text("v1")
    proc = subprocess.run(["git", "-C", str(git), "add", "src.txt"],
                          capture_output=True, timeout=30)
    proc = subprocess.run(
        ["git", "-C", str(git), "commit", "-qm", "v1"],
        capture_output=True, timeout=30)
    if proc.returncode != 0:
        pytest.skip("git commit unavailable")
    binary = _needs_binary()
    return SrotaControlPlane(store_root=tmp_path / "store",
                             repo_root=git, binary=binary)


def _needs_binary():
    from veritx_dse.simulation.booksim import (  # noqa: PLC0415
        find_booksim_bin,
    )
    try:
        return Path(find_booksim_bin(REPO))
    except FileNotFoundError:
        pytest.skip("no runnable BookSim binary")


class TestCompile:
    def test_compile_returns_typed_design(self, service):
        out = service.compile(_doc())
        design, workload = out["design"], out["workload"]
        assert design["resource_type"] == "design"
        assert workload["resource_type"] == "workload"
        assert design["design_hash"] and design["fabric_hash"]
        assert design["mapping_hash"]
        assert workload["trace_sha256"]
        assert out["bundle_hashes"]["resolved_fabric_hash"]

    def test_compile_is_deterministic(self, service):
        first = service.compile(_doc())["design"]["resource_id"]
        second = service.compile(_doc())["design"]["resource_id"]
        assert first == second

    def test_hbm_preset_compiles(self, service):
        out = service.compile(_doc(fabric_preset="mesh4_hbm"))
        assert out["workload"]["endpoint_count"] == 5

    def test_trace_outside_universe_refuses(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.compile(_doc(workload={"trace": "tiny2x5"}))
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_unknown_trace_file_refuses(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.compile(
                _doc(workload={"trace_file": "/nonexistent/trace.txt"}))
        assert excinfo.value.code == ErrorCode.INVALID_INTENT


class TestPlan:
    def test_plan_pins_backend_identity(self, service):
        plan = service.plan(_doc())["plan"]
        assert plan["backend_target"] == "BOOKSIM_STANDALONE"
        assert plan["backend_profile"] == "CERTIFIED_BOOKSIM_ANYNET_V1"
        assert plan["execution_mode"] == "REAL_SIMULATION"
        assert plan["seed_policy"] == "pinned_default"
        assert plan["metric_schema_version"] == "booksim-parse/v1"

    def test_plan_identity_stable(self, service):
        assert service.plan(_doc())["plan"]["resource_id"] == \
            service.plan(_doc())["plan"]["resource_id"]

    def test_blocked_backend_refuses(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.plan(_doc(backend_target="SERVING_BOOKSIM2"))
        assert excinfo.value.code == ErrorCode.UNSUPPORTED_SEMANTICS

    def test_analytical_backend_refuses(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.plan(
                _doc(backend_target="SERVING_ANALYTICAL_AWARE"))
        assert excinfo.value.code == ErrorCode.UNSUPPORTED_SEMANTICS


class TestEvaluate:
    def test_evaluate_real_run(self, service):
        _needs_binary()
        res = service.evaluate(_doc())
        assert res["status"] == "SUCCEEDED"
        assert res["qualification"] == "EXECUTED_WITH_DECLARED_LOSS"
        assert res["execution_transport"] == "SUPERVISED_PROCESS"
        assert res["reused"] is False
        assert res["evidence_ref"]["sha256"]
        assert res["producer"]["binary_sha256"]
        by_id = {m["metric_id"]: m for m in res["metrics"]}
        assert by_id["sim.latency.avg_cycles"]["unit"] == "cycles"
        assert by_id["sim.delivered.packets"]["value"] == 2.0
        assert res["semantic_loss"]
        assert res["loss_digest"]

    def test_evaluate_reuses(self, clean_service):
        first = clean_service.evaluate(_doc())
        second = clean_service.evaluate(_doc())
        assert second["reused"] is True
        assert second["resource_id"] == first["resource_id"]
        assert second["attempt_id"] == first["attempt_id"]

    def test_seed_moves_experiment(self, service):
        _needs_binary()
        base = service.evaluate(_doc())
        shifted = service.evaluate(_doc(seed=7, name="seeded"))
        assert shifted["experiment_id"] != base["experiment_id"]
        assert shifted["backend_input_hash"] != base["backend_input_hash"]
        assert shifted["seed"] == 7
        assert shifted["seed_policy"] == "explicit"

    def test_failed_attempt_is_typed_not_feasible(self, service, tmp_path):
        _needs_binary()
        from veritx_dse.simulation.booksim import (  # noqa: PLC0415
            find_booksim_bin,
        )
        binary = Path(find_booksim_bin(REPO))
        broken = tmp_path / "broken-booksim"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(store_root=tmp_path / "store2",
                                 binary=broken)
        with pytest.raises(ControlPlaneError) as excinfo:
            dark.evaluate(_doc())
        assert excinfo.value.code == ErrorCode.EXECUTION_FAILED
        assert excinfo.value.code != ErrorCode.NO_FEASIBLE_DESIGN
        attempt = dark.inspect(excinfo.value.resource_id)
        assert attempt["record"]["status"] == "FAILED"
        assert attempt["record"]["evidence_ref"] is None


class TestFailureTaxonomy:
    def test_crash_is_not_no_feasible_design(self, service, tmp_path):
        _needs_binary()
        broken = tmp_path / "broken"
        broken.write_text("#!/bin/sh\nexit 3\n")
        broken.chmod(0o755)
        dark = SrotaControlPlane(store_root=tmp_path / "s", binary=broken)
        with pytest.raises(ControlPlaneError) as excinfo:
            dark.evaluate(_doc())
        assert excinfo.value.code == ErrorCode.EXECUTION_FAILED

    def test_invalid_intent_code(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.compile(_doc(fabric_preset="nope"))
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_not_found_code(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.inspect("0" * 64)
        assert excinfo.value.code == ErrorCode.NOT_FOUND

    def test_forced_timeout_maps_typed(self, tmp_path):
        _needs_binary()
        sleeper = tmp_path / "sleeper"
        sleeper.write_text("#!/bin/sh\nsleep 30\n")
        sleeper.chmod(0o755)
        service = SrotaControlPlane(store_root=tmp_path / "store",
                                    binary=sleeper)
        with pytest.raises(ControlPlaneError) as excinfo:
            service.evaluate(_doc(timeout_s=1))
        assert excinfo.value.code == ErrorCode.EXECUTION_TIMEOUT
        attempt = service.inspect(excinfo.value.resource_id)
        assert attempt["record"]["status"] == "TIMED_OUT"

    def test_timeout_maps_typed(self):
        from veritx_dse.application.errors import (  # noqa: PLC0415
            ErrorCode, map_execution_error,
        )
        from veritx_dse.core.errors import (  # noqa: PLC0415
            BookSimError, TimeoutError,
        )
        timeout = TimeoutError("sim timed out", returncode=1,
                               stdout="", stderr="")
        assert map_execution_error(
            timeout, operation="evaluate").code == \
            ErrorCode.EXECUTION_TIMEOUT
        crash = BookSimError("sim exited 3", returncode=3, stdout="",
                             stderr="")
        assert map_execution_error(
            crash, operation="evaluate").code == \
            ErrorCode.EXECUTION_FAILED

    def test_no_feasible_design_never_emitted(self, service, tmp_path):
        _needs_binary()
        codes = set()
        try:
            service.evaluate(_doc())
        except ControlPlaneError as exc:
            codes.add(exc.code)
        try:
            service.plan(_doc(backend_target="SERVING_BOOKSIM2"))
        except ControlPlaneError as exc:
            codes.add(exc.code)
        assert ErrorCode.NO_FEASIBLE_DESIGN not in codes


class TestInspect:
    def test_inspect_result_navigates(self, clean_service):
        res = clean_service.evaluate(_doc())
        out = clean_service.inspect(res["resource_id"])
        assert out["kind"] == "result"
        assert out["related"]["experiment_id"]["resource_id"] == \
            res["experiment_id"]
        assert out["related"]["attempt_id"]["resource_id"] == \
            res["attempt_id"]
        assert out["evidence_status"]["verified"] is True
        assert out["evidence_status"]["record_integrity"] is True
        assert out["evidence_status"]["evidence_integrity"] is True
        assert out["evidence_status"]["chain_integrity"] is True

    def test_inspect_unknown_refuses(self, service):
        with pytest.raises(ControlPlaneError) as excinfo:
            service.inspect("deadbeef")
        assert excinfo.value.code == ErrorCode.NOT_FOUND

    def test_inspect_tampered_reports_invalid(self, clean_service):
        res = clean_service.evaluate(_doc())
        path = Path(res["evidence_ref"]["path"])
        raw = path.read_bytes()
        try:
            import json
            doc = json.loads(raw.decode())
            doc["stats"]["latency"] = 0.0001
            path.write_bytes(json.dumps(doc).encode())
            out = clean_service.inspect(res["resource_id"])
            assert out["evidence_status"]["verified"] is False
        finally:
            path.write_bytes(raw)
