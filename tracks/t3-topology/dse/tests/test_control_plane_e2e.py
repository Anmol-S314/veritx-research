"""Wave-C end-to-end certification: canonical scenario + mutation matrix.

One canonical fixture (mesh4 + tiny2 + pinned seed policy) through the
full production chain, then every required identity mutation with its
expected effect asserted. Real BookSim throughout; no injected runner.
"""
from __future__ import annotations

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
        "schema_version": 1, "name": "canonical",
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


class TestCanonicalScenario:
    def test_full_chain(self, clean_service):
        svc = clean_service
        compiled = svc.compile(_doc())
        planned = svc.plan(_doc())
        result = svc.evaluate(_doc())
        assert result["status"] == "SUCCEEDED"
        assert result["execution_transport"] == "SUPERVISED_PROCESS"
        assert result["qualification"] == "EXECUTED_WITH_DECLARED_LOSS"
        assert result["evidence_ref"]["sha256"]
        inspected = svc.inspect(result["resource_id"])
        assert inspected["evidence_status"]["verified"] is True
        assert inspected["related"]["experiment_id"]["resource_id"] == \
            result["experiment_id"]
        reused = svc.evaluate(_doc())
        assert reused["reused"] is True
        assert reused["resource_id"] == result["resource_id"]
        wide = svc.evaluate(_doc(name="wide", fabric_preset="mesh4_wide128"))
        comparison = svc.compare({
            "candidate_ids": [result["resource_id"],
                              wide["resource_id"]],
            "contract": {"comparison_kind": "DESIGN_COMPARISON",
                         "metric_ids": ["sim.latency.avg_cycles"]}})
        assert comparison["compatibility"]["verdict"] == "COMPATIBLE"
        assert comparison["metrics"][0]["metric_id"] == \
            "sim.latency.avg_cycles"


class TestMutationMatrix:
    def test_intent_label_change_keeps_ids(self, clean_service):
        a = clean_service.compile(_doc(name="one"))
        b = clean_service.compile(_doc(name="two"))
        assert a["design"]["resource_id"] == b["design"]["resource_id"]

    def test_fabric_change_moves_dependents(self, clean_service):
        base = clean_service.compile(_doc())
        other = clean_service.compile(
            _doc(fabric_preset="mesh4_wide128"))
        assert other["design"]["fabric_hash"] != \
            base["design"]["fabric_hash"]
        # Mapping binds ranks to compute instances: link width and HBM
        # agents do not move it (correct insensitivity, pinned here).
        assert other["design"]["mapping_hash"] == \
            base["design"]["mapping_hash"]
        hbm = clean_service.compile(_doc(fabric_preset="mesh4_hbm"))
        assert hbm["design"]["fabric_hash"] != \
            base["design"]["fabric_hash"]
        assert hbm["design"]["mapping_hash"] == \
            base["design"]["mapping_hash"]
        # The plan still varies (fabric/design identity) and always
        # carries the mapping hash, so future mapping variation moves it.
        plan_base = clean_service.plan(_doc())["plan"]
        plan_other = clean_service.plan(
            _doc(fabric_preset="mesh4_wide128"))["plan"]
        assert plan_base["resource_id"] != plan_other["resource_id"]
        assert plan_base["mapping_hash"] == \
            base["design"]["mapping_hash"]

    def test_workload_change_moves_input_and_experiment(
            self, clean_service, tmp_path):
        base = clean_service.evaluate(_doc())
        alt = tmp_path / "alt.trace"
        alt.write_bytes(b"1 0 0 3 1\n11 3 0 0 1\n")
        other = clean_service.evaluate(
            _doc(name="alt", workload={"trace_file": str(alt)}))
        assert other["workload_hash"] != base["workload_hash"]
        assert other["backend_input_hash"] != base["backend_input_hash"]
        assert other["experiment_id"] != base["experiment_id"]

    def test_seed_change_moves_experiment(self, clean_service):
        base = clean_service.evaluate(_doc())
        other = clean_service.evaluate(_doc(name="seeded", seed=9))
        assert other["experiment_id"] != base["experiment_id"]
        assert other["backend_input_hash"] != base["backend_input_hash"]

    def test_backend_change_refuses(self, clean_service):
        with pytest.raises(ControlPlaneError) as excinfo:
            clean_service.evaluate(
                _doc(backend_target="SERVING_BOOKSIM2"))
        assert excinfo.value.code == ErrorCode.UNSUPPORTED_SEMANTICS

    def test_store_location_keeps_identity(self, clean_service, tmp_path):
        first = clean_service.compile(_doc())
        other_store = SrotaControlPlane(
            store_root=tmp_path / "elsewhere")
        second = other_store.compile(_doc())
        assert first["design"]["resource_id"] == \
            second["design"]["resource_id"]
        assert first["design"]["design_hash"] == \
            second["design"]["design_hash"]

    def test_deleted_evidence_reruns_fresh(self, clean_service):
        first = clean_service.evaluate(_doc())
        Path(first["evidence_ref"]["path"]).unlink()
        second = clean_service.evaluate(_doc())
        assert second["reused"] is False
        assert second["attempt_id"] != first["attempt_id"]
        assert second["experiment_id"] == first["experiment_id"]

    def test_preset_derivation_keeps_source(self, clean_service):
        from veritx_dse.application.presets import (  # noqa: PLC0415
            build_preset_request, derive_request,
        )
        before = build_preset_request("mesh4").to_dict()
        derived = derive_request("mesh4", {"noc_config.link_width": 64})
        assert build_preset_request("mesh4").to_dict() == before
        out = clean_service.compile(_doc(
            fabric_overrides={"noc_config.link_width": 64}))
        assert out["design"]["design_hash"] != \
            clean_service.compile(_doc())["design"]["design_hash"]
        assert derived["noc_config"]["link_width"] == 64


class TestGoldenFixtures:
    """Frozen golden corpus intact (real runs live in the golden suite)."""

    @pytest.mark.parametrize("case", [
        "mesh4_multiclass", "mesh4_singleclass", "hbm5_addrmap",
        "wide128", "escape_blocked",
    ])
    def test_frozen_golden_fixtures_intact(self, case):
        import json as _json
        corpus = _json.loads(
            (TESTS / "fixtures" / "backend_golden.json").read_text())
        row = corpus["cases"][case]
        assert row["route_expected_sha256"]
        assert row["qualification"]
        assert row["standalone_config_hash"]
