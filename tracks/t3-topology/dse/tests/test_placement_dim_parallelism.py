"""Study dimensions: TP/PP/EP/DP + placement through canonical artifacts.

Parallelism patches workload sizes (base never mutated; identity binds);
placement resolves through canonical mapping constructors (rank_order
today, everything else refused). VC/route/escape knobs and dead v3
controls are never dimensions.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.compile_model import (  # noqa: E402
    Agent,
    AgentKind,
    CompileRequestV3,
    DependencyGraph,
    ModelFamily,
    NocConfig,
    TopologyFamily,
    WorkloadV3,
)
from veritx_dse.model.mapping import derive_mapping  # noqa: E402
from veritx_dse.optimization.candidate import (  # noqa: E402
    CandidateError,
    apply_study_patch,
    make_study_candidate,
    resolve_study_mapping,
    study_candidate_id_for,
)
from veritx_dse.optimization.definition import (  # noqa: E402
    OptimizationDefinitionError,
    StudyParam,
    assess_effectiveness,
)
from veritx_dse.optimization.space_multiscenario import (  # noqa: E402
    MultiScenarioStudy,
    Scenario,
    build_study_candidates,
    check_hardware_consistent,
)


def _workload(**kw):
    args = {"model_family": ModelFamily.DENSE_TRANSFORMER}
    args.update(kw)
    return WorkloadV3(**args)


def _base():
    return CompileRequestV3(
        workload=_workload(tp=1),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))


# ── parallelism dimensions ──────────────────────────────────────────

def test_tp_patch_changes_workload_not_base():
    base = _base()
    before = base.design_hash()
    cand = make_study_candidate(base, {"tp": 2})
    assert cand.request.workload.tp == 2
    assert base.workload.tp == 1
    assert base.design_hash() == before
    assert cand.request.design_hash() != before


def test_parallelism_values_validated():
    for bad in (0, -1, True, "2", 2.5):
        with pytest.raises(OptimizationDefinitionError):
            StudyParam("tp", (bad,))
    with pytest.raises(OptimizationDefinitionError, match="duplicate"):
        StudyParam("ep", (2, 2))


def test_parallelism_growth_beyond_compute_is_invalid():
    base = _base()
    with pytest.raises(CandidateError, match="mapping infeasible"):
        make_study_candidate(base, {"tp": 8, "ep": 8})


def test_all_four_parallelism_dims_patch():
    base = _base()
    big = CompileRequestV3(
        workload=_workload(tp=1),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=32),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH))
    cand = make_study_candidate(big, {"tp": 2, "pp": 2, "ep": 2, "dp": 2})
    assert (cand.request.workload.tp, cand.request.workload.pp,
            cand.request.workload.ep, cand.request.workload.dp) == (2, 2, 2, 2)
    assert cand.mapping_hash == derive_mapping(cand.request).mapping_hash()


# ── placement dimension ─────────────────────────────────────────────

def test_placement_policy_resolves_canonical_mapping():
    base = _base()
    cand = make_study_candidate(base, {"placement": "rank_order"})
    assert cand.placement_policy == "rank_order"
    mapping = resolve_study_mapping(cand.request, cand.placement_policy)
    assert mapping.mapping_hash() == cand.mapping_hash


def test_default_policy_is_rank_order():
    base = _base()
    cand = make_study_candidate(base, {"link_width": 128})
    assert cand.placement_policy == "rank_order"
    assert resolve_study_mapping(cand.request, None).mapping_hash() == \
        cand.mapping_hash


def test_unqualified_placement_policy_refuses():
    with pytest.raises(OptimizationDefinitionError, match="no canonical"):
        StudyParam("placement", ("spray",))
    with pytest.raises(CandidateError, match="no canonical constructor"):
        resolve_study_mapping(_base(), "spray")


def test_placement_value_must_name_a_policy():
    with pytest.raises(OptimizationDefinitionError):
        StudyParam("placement", (42,))
    with pytest.raises(CandidateError, match="must be a name"):
        make_study_candidate(_base(), {"placement": 42})


# ── never dimensions ────────────────────────────────────────────────

@pytest.mark.parametrize("knob", ["vc_count", "vc_map", "routing_function",
                                  "escape_vc", "turn_restrictions",
                                  "rcu_enabled", "mcast_groups",
                                  "output_formats", "obfuscation_level"])
def test_never_dimensions_refuse(knob):
    with pytest.raises(OptimizationDefinitionError):
        StudyParam(knob, (1,))


def test_apply_study_patch_rejects_locked_and_dead():
    base = _base()
    with pytest.raises(CandidateError, match="LOCKED"):
        apply_study_patch(base, {"vc_count": 4})
    with pytest.raises(CandidateError, match="refused"):
        apply_study_patch(base, {"output_formats": "x"})
    with pytest.raises(CandidateError, match="at least one dimension"):
        apply_study_patch(base, {})


# ── identity, hardware, effectiveness ───────────────────────────────

def test_study_identity_order_independent():
    base = _base()
    h = base.design_hash()
    a = study_candidate_id_for(h, {"tp": 2, "link_width": 64})
    b = study_candidate_id_for(h, {"link_width": 64, "workload.tp": 2})
    assert a == b and a.startswith("scand_")


def test_parallelism_candidates_share_hardware():
    base = _base()
    c1 = make_study_candidate(base, {"tp": 1})
    c2 = make_study_candidate(base, {"tp": 2})
    check_hardware_consistent([c1.request, c2.request])


def test_parallelism_effectiveness():
    for dim in ("tp", "pp", "ep", "dp", "placement"):
        verdict, _ = assess_effectiveness(dim, "completion_cycles")
        assert verdict == "EFFECTIVE", dim


def test_parallelism_study_builds_with_mapping_check():
    from veritx_dse.optimization.definition import ScenarioObjective
    study = MultiScenarioStudy(
        base=_base(),
        scenarios=(Scenario("s", _workload(tp=1)),),
        objectives=(ScenarioObjective("completion_cycles", "MIN"),),
        domain=(StudyParam("tp", (1, 2)), StudyParam("ep", (1, 2))),
        method="grid")
    ledger = build_study_candidates(study)
    assert len(ledger.valid) == 4
    assert ledger.invalid == []
    for cand in ledger.valid:
        assert cand.mapping_hash is not None
