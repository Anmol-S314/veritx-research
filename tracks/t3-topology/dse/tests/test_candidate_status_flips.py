"""Candidate status flips: compile/verify/evaluate linkage for synth candidates."""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.errors import ControlPlaneError  # noqa: E402
from veritx_dse.product import vnext  # noqa: E402
from veritx_dse.product.store import ProductStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return ProductStore(tmp_path / "store")


def _synth_candidate(cid="cand-1"):
    return {
        "candidate_id": cid,
        "origin": {"kind": "synthesis", "synthesis_id": "syn-1"},
        "links": [[0, 1]],
        "compiled": False,
        "verified": False,
        "evaluated": False,
    }


def test_compile_flip_sets_revision_and_verified(store):
    store.create_candidate(_synth_candidate())
    rec = vnext.mark_candidate_compiled(store, "cand-1", "p-r01", True)
    assert rec["compiled"] is True and rec["verified"] is True
    assert rec["revision_id"] == "p-r01"
    detail = vnext.get_candidate(SimpleNamespace(store=store), "cand-1")
    assert detail["pipeline"] == {
        "compiled": True, "verified": True, "evaluated": False,
        "adopted": False, "revision_id": "p-r01",
        "evaluated_run_id": None, "adopted_project_id": None,
    }


def test_failed_proof_compiles_without_verified(store):
    store.create_candidate(_synth_candidate())
    rec = vnext.mark_candidate_compiled(store, "cand-1", "p-r02", False)
    assert rec["compiled"] is True and rec["verified"] is False


def test_evaluated_flip_records_run(store):
    store.create_candidate(_synth_candidate())
    vnext.mark_candidate_compiled(store, "cand-1", "p-r01", True)
    rec = vnext.mark_candidate_evaluated(store, "cand-1", "run-7")
    assert rec["evaluated"] is True and rec["evaluated_run_id"] == "run-7"
    assert store.list_candidates()[0]["evaluated"] is True


def test_library_filters_light_up(store):
    store.create_candidate(_synth_candidate("a"))
    store.create_candidate(_synth_candidate("b"))
    vnext.mark_candidate_compiled(store, "a", "p-r01", True)
    got = vnext.list_candidates(
        SimpleNamespace(store=store), {"compiled": True})
    assert [c["candidate_id"] for c in got["candidates"]] == ["a"]


def test_unknown_candidate_is_typed_refusal(store):
    with pytest.raises(ControlPlaneError, match="no such candidate"):
        vnext.mark_candidate_compiled(store, "ghost", "p-r01", True)
    with pytest.raises(ControlPlaneError, match="no such candidate"):
        vnext.mark_candidate_evaluated(store, "ghost", "run-1")


def test_non_synthesis_candidate_refused(store):
    store.create_candidate({
        "candidate_id": "opt-1",
        "origin": {"kind": "optimization", "optimization_id": "o-1"},
    })
    with pytest.raises(ControlPlaneError, match="not a synthesis"):
        vnext.mark_candidate_compiled(store, "opt-1", "p-r01", True)


def test_reuse_info_reports_explicit_hit(store):
    project = store.create_project(
        name="t", draft_doc={"request": {}}, workload_id="w",
        source="test")
    pid = project["project_id"]
    store.create_run(pid, {
        "run_id": "run-1",
        "reused_evidence_id": "ev-abc",
        "reuse_matching": {"question": "NETWORK_COMPLETION"},
    })
    info = vnext.reuse_info(SimpleNamespace(store=store), "run-1")
    assert info == {
        "run_id": "run-1", "reused": True,
        "reused_evidence_id": "ev-abc",
        "reason": "REUSED AUTHENTICATED EVIDENCE — the measurement "
                  "below is the referenced evidence, not a new run",
        "reuse_key_fields": info["reuse_key_fields"],
        "matching": {"question": "NETWORK_COMPLETION"},
    }


def test_reuse_info_reports_direct_execution(store):
    project = store.create_project(
        name="t", draft_doc={"request": {}}, workload_id="w",
        source="test")
    pid = project["project_id"]
    store.create_run(pid, {"run_id": "run-2"})
    info = vnext.reuse_info(SimpleNamespace(store=store), "run-2")
    assert info["reused"] is False and info["reused_evidence_id"] is None
