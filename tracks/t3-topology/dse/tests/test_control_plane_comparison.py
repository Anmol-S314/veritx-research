"""Wave-C comparison tests: contract parsing, compatibility gate, output.

Table-driven gate matrix over real evaluated results (skip without a
runnable binary). Observed language only: deltas and lower-observed
ids, never winner/best/optimal.
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

from veritx_dse.application.comparison import (  # noqa: E402
    parse_contract,
)
from veritx_dse.application.errors import (  # noqa: E402
    ControlPlaneError, ErrorCode,
)
from veritx_dse.application.service import SrotaControlPlane  # noqa: E402
from veritx_dse.core.paths import REPO  # noqa: E402


def _doc(**over):
    doc = {
        "schema_version": 1, "name": "cmp-fixture",
        "fabric_preset": "mesh4", "fabric_overrides": {},
        "workload": {"trace": "tiny2"},
        "backend_target": "BOOKSIM_STANDALONE", "seed": None,
        "metrics": ["sim.latency.avg_cycles", "sim.delivered.packets"],
    }
    doc.update(over)
    return doc


@pytest.fixture()
def clean_service(tmp_path):
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


@pytest.fixture()
def pair(clean_service):
    a = clean_service.evaluate(_doc(name="a", fabric_preset="mesh4"))
    b = clean_service.evaluate(
        _doc(name="b", fabric_preset="mesh4_wide128"))
    return clean_service, a, b


def _compare(service, a, b, **contract):
    base = {"comparison_kind": "DESIGN_COMPARISON",
            "metric_ids": ["sim.latency.avg_cycles"]}
    base.update(contract)
    return service.compare({"candidate_ids": [a["resource_id"],
                                              b["resource_id"]],
                            "contract": base})


def _fork(service, record, new_id, **changes):
    """Persist a modified copy under a NEW id (store is immutable)."""
    forked = dict(record)
    forked.update(changes)
    forked["resource_id"] = new_id
    service.store.put("result", new_id, forked)
    return forked


class TestContractParsing:
    @pytest.mark.parametrize("mutator", [
        lambda d: d.update({"bogus": 1}),
        lambda d: d.update({"comparison_kind": "nope"}),
        lambda d: d.update({"allowed_variations": ["nope"]}),
        lambda d: d.update({"metric_ids": []}),
        lambda d: d.update({"metric_ids": ["nope"]}),
        lambda d: d.update({"acknowledged_differences": "x"}),
    ])
    def test_invalid_contracts_refuse(self, mutator):
        doc = {"metric_ids": ["sim.latency.avg_cycles"]}
        mutator(doc)
        with pytest.raises(ControlPlaneError) as excinfo:
            parse_contract(doc)
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_default_design_contract_varies_fabric(self):
        contract = parse_contract(
            {"metric_ids": ["sim.latency.avg_cycles"]})
        assert contract.comparison_kind == "DESIGN_COMPARISON"
        assert "fabric_hash" in contract.allowed_variations


class TestCompatibilityGate:
    def test_compatible_different_fabric(self, pair):
        service, a, b = pair
        out = _compare(service, a, b)
        assert out["compatibility"]["verdict"] == "COMPATIBLE"
        assert out["resource_id"]
        assert out["metrics"][0]["metric_id"] == "sim.latency.avg_cycles"
        assert "lower_observed" in out["metrics"][0]
        assert "WINNER" not in str(out).upper()
        assert "BEST" not in str(out).upper()

    def test_exact_replay_contract(self, pair):
        service, a, b = pair
        with pytest.raises(ControlPlaneError) as excinfo:
            _compare(service, a, b, comparison_kind="EXACT_REPLAY")
        assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE

    def test_different_workload_refused(self, pair, clean_service):
        service, a, _ = pair
        c = clean_service.evaluate(_doc(name="c", seed=9))
        with pytest.raises(ControlPlaneError) as excinfo:
            _compare(service, a, c)
        assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE

    def test_different_trace_bytes_refused(self, pair, clean_service):
        service, a, _ = pair
        alt = clean_service.store.root.parent / "alt.trace"
        alt.write_bytes(b"1 0 0 3 1\n11 3 0 0 1\n")
        c = clean_service.evaluate(_doc(
            name="alt-workload",
            workload={"trace_file": str(alt)}))
        assert c["workload_hash"] != a["workload_hash"]
        with pytest.raises(ControlPlaneError) as excinfo:
            _compare(service, a, c)
        assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE

    def test_different_metric_schema_refused(self, pair):
        service, a, b = pair
        forked = _fork(service, b, "fork-schema",
                       metric_schema_version="other/v9")
        with pytest.raises(ControlPlaneError) as excinfo:
            _compare(service, a, forked)
        assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE

    def test_failed_result_refused(self, pair):
        service, a, b = pair
        failed = _fork(service, b, "fork-failed", status="FAILED")
        with pytest.raises(ControlPlaneError) as excinfo:
            _compare(service, a, failed)
        assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE

    def test_tampered_evidence_refused(self, pair):
        import json
        service, a, b = pair
        path = Path(b["evidence_ref"]["path"])
        raw = path.read_bytes()
        try:
            doc = json.loads(raw.decode())
            doc["stats"]["latency"] = 0.0001
            path.write_bytes(json.dumps(doc).encode())
            with pytest.raises(ControlPlaneError) as excinfo:
                _compare(service, a, b)
            assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE
        finally:
            path.write_bytes(raw)

    def test_test_transport_refused(self, pair):
        service, a, b = pair
        injected = _fork(service, b, "fork-injected",
                         execution_transport="TEST_INJECTED")
        with pytest.raises(ControlPlaneError) as excinfo:
            _compare(service, a, injected)
        assert excinfo.value.code == ErrorCode.COMPARISON_INCOMPATIBLE

    def test_pairwise_only(self, pair):
        service, a, b = pair
        with pytest.raises(ControlPlaneError) as excinfo:
            service.compare({
                "candidate_ids": [a["resource_id"]],
                "contract": {"metric_ids": ["sim.latency.avg_cycles"]}})
        assert excinfo.value.code == ErrorCode.INVALID_INTENT

    def test_candidate_must_be_result(self, pair):
        service, a, b = pair
        with pytest.raises(ControlPlaneError) as excinfo:
            service.compare({
                "candidate_ids": [a["resource_id"], b["experiment_id"]],
                "contract": {"metric_ids": ["sim.latency.avg_cycles"]}})
        assert excinfo.value.code in (ErrorCode.NOT_FOUND,
                                      ErrorCode.COMPARISON_INCOMPATIBLE)
