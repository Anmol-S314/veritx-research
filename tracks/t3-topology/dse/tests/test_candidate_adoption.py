"""PHASE 7 — adopting a studied candidate as a DRAFT.

The loop the product flow exists for:

    OptimizationStudy -> selected candidate -> "Use candidate"
      -> Draft updated -> user reviews -> explicit Compile
      -> NEW immutable DesignRevision

The failure this prevents: mutating r05 into r06 behind the user's back, so a
revision the study measured against stops being the revision that exists.

The load-bearing guarantee is IDENTITY, not bookkeeping: the patch is
re-applied to the BASE REVISION's request through the canonical `apply_patch`,
and the resulting design hash must equal the candidate's. If it does not, the
draft and the study would be different designs, and the adoption is refused.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.optimization.candidate import make_candidate  # noqa: E402
from veritx_dse.product.service import (  # noqa: E402
    ProductConfig, ProductService, parse_request_doc,
)

WORKLOAD = "llama-dense-8b-64tiles"

@pytest.fixture
def svc(tmp_path):
    return ProductService(ProductConfig(projects_root=tmp_path / "projects"))

@pytest.fixture
def project(svc):
    """A project with ONE compiled, immutable revision (r01)."""
    pid = svc.create_project(name="adopt", workload_id=WORKLOAD)[
        "project"]["project_id"]
    svc.compile_draft(pid)
    project = svc.store.load_project(pid)
    return pid, project

def _study_record(pid, revision, patch):
    """A minimal but REAL optimization record: the candidate is built through
    the canonical `make_candidate`, so its id and design hash are the same
    objects a genuine study would have produced."""
    base = parse_request_doc(revision["request"])
    candidate = make_candidate(base, patch)
    return {
        "schema_version": 1,
        "optimization_id": "opt-test-1",
        "project_id": pid,
        "base_revision_id": revision["revision_id"],
        "created_at": "t",
        "definition": {"domain": [{"name": "link_width", "values": [64, 128]}],
                       "objectives": [{"metric": "completion_cycles",
                                       "direction": "MIN"}],
                       "constraints": [], "method": "grid",
                       "budget": {}, "selection": "min_first_objective",
                       "seed": None},
        "study": {
            "contract_version": 2,
            "candidates": [{
                "candidate_id": candidate.candidate_id,
                "guided_patch": dict(candidate.guided_patch),
                "design_hash": candidate.request.design_hash(),
                "compilation_status": "COMPILED",
                "evaluation_status": "EVALUATED",
            }],
            "selected_candidate_id": candidate.candidate_id,
        },
        "candidate_runs": [],
        "selected_candidate_id": candidate.candidate_id,
    }, candidate

def _base_revision(project):
    rid = project["active_revision_id"] or project["revision_ids"][-1]
    return rid

def test_adopting_a_candidate_updates_the_draft(svc, project):
    pid, proj = project
    rid = _base_revision(proj)
    revision = svc.store.load_revision(pid, rid)
    record, candidate = _study_record(pid, revision, {"link_width": 128})
    svc.store.create_optimization(pid, record)

    draft = svc.use_candidate("opt-test-1", candidate.candidate_id)
    assert draft["derived_from_optimization_id"] == "opt-test-1"
    assert draft["derived_from_candidate_id"] == candidate.candidate_id
    assert draft["adopted_from_revision_id"] == rid
    assert draft["source"] == "optimization-candidate"

def test_the_adopted_draft_is_the_SAME_DESIGN_the_study_measured(svc, project):
    """The identity guarantee: re-applying the patch to the base revision must
    reproduce the candidate's design, not merely something similar."""
    pid, proj = project
    rid = _base_revision(proj)
    revision = svc.store.load_revision(pid, rid)
    record, candidate = _study_record(pid, revision, {"link_width": 128})
    svc.store.create_optimization(pid, record)

    draft = svc.use_candidate("opt-test-1", candidate.candidate_id)
    adopted = parse_request_doc(draft["request"])
    assert adopted.design_hash() == candidate.request.design_hash()
    base = parse_request_doc(revision["request"])
    assert adopted.design_hash() != base.design_hash()

def test_the_base_revision_remains_immutable(svc, project):
    pid, proj = project
    rid = _base_revision(proj)
    before = svc.store.load_revision(pid, rid)
    record, candidate = _study_record(pid, before, {"link_width": 128})
    svc.store.create_optimization(pid, record)

    svc.use_candidate("opt-test-1", candidate.candidate_id)

    after = svc.store.load_revision(pid, rid)
    assert after == before
    assert after["design_hash"] == before["design_hash"]
    assert after["request"] == before["request"]
    project_after = svc.store.load_project(pid)
    assert project_after["revision_ids"] == proj["revision_ids"]

def test_adoption_marks_the_draft_dirty(svc, project):
    pid, proj = project
    rid = _base_revision(proj)
    revision = svc.store.load_revision(pid, rid)
    assert svc.draft_view(pid)["dirty"] is False
    record, candidate = _study_record(pid, revision, {"link_width": 128})
    svc.store.create_optimization(pid, record)

    svc.use_candidate("opt-test-1", candidate.candidate_id)
    assert svc.draft_view(pid)["dirty"] is True

def test_the_draft_compiles_into_a_new_revision(svc, project):
    pid, proj = project
    rid = _base_revision(proj)
    revision = svc.store.load_revision(pid, rid)
    record, candidate = _study_record(pid, revision, {"link_width": 128})
    svc.store.create_optimization(pid, record)

    svc.use_candidate("opt-test-1", candidate.candidate_id)
    new_revision = svc.compile_draft(pid)

    assert new_revision["revision_id"] != rid
    assert new_revision["design_hash"].removeprefix("sha256:") == \
        candidate.request.design_hash().removeprefix("sha256:")
    assert new_revision.get("derived_from_optimization_id") == "opt-test-1"
    assert new_revision.get("derived_from_candidate_id") == \
        candidate.candidate_id
    assert svc.store.load_revision(pid, rid) == revision

def test_an_unknown_candidate_is_refused(svc, project):
    pid, proj = project
    revision = svc.store.load_revision(pid, _base_revision(proj))
    record, _ = _study_record(pid, revision, {"link_width": 128})
    svc.store.create_optimization(pid, record)
    with pytest.raises(Exception, match="unknown candidate"):
        svc.use_candidate("opt-test-1", "cand_does_not_exist")

def test_a_candidate_that_did_not_compile_is_refused(svc, project):
    pid, proj = project
    revision = svc.store.load_revision(pid, _base_revision(proj))
    record, candidate = _study_record(pid, revision, {"link_width": 128})
    record["study"]["candidates"][0]["compilation_status"] = "FAILED"
    svc.store.create_optimization(pid, record)
    with pytest.raises(Exception, match="did not compile"):
        svc.use_candidate("opt-test-1", candidate.candidate_id)

def test_a_drifted_study_hash_is_refused(svc, project):
    """If the recorded hash does not match what re-applying the patch
    produces, the draft and the study would be different designs."""
    pid, proj = project
    revision = svc.store.load_revision(pid, _base_revision(proj))
    record, candidate = _study_record(pid, revision, {"link_width": 128})
    record["study"]["candidates"][0]["design_hash"] = "sha256:deadbeef"
    svc.store.create_optimization(pid, record)
    with pytest.raises(Exception, match="would be different designs"):
        svc.use_candidate("opt-test-1", candidate.candidate_id)

def test_an_empty_patch_is_refused_rather_than_silently_adopted(svc, project):
    pid, proj = project
    revision = svc.store.load_revision(pid, _base_revision(proj))
    record, _ = _study_record(pid, revision, {"link_width": 128})
    record["study"]["candidates"][0]["guided_patch"] = {}
    svc.store.create_optimization(pid, record)
    with pytest.raises(Exception, match="no GUIDED patch"):
        svc.use_candidate("opt-test-1",
                          record["study"]["candidates"][0]["candidate_id"])
