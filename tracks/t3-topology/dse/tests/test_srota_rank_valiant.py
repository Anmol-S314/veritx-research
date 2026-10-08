"""SROTA Valiant under the hop-rank VC policy (P4).

The fork's rank policy is the only one it accepts with Valiant enabled
(``shape`` and ``oneshape`` both ``exit(-1)``). It gives the direct shapes
ranks 0/1 (pre-turn / post-turn) and a Valiant path's second leg ranks 2/3,
so its second turn cannot share a set with its first.

What only these tests can show: the model's rank union is built by the SAME
walk the simulator runs, so the canonical certificate and the fork's own
elaboration-time static check are the same claim.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.model.srota_rank_vc_policy import (  # noqa: E402
    SrotaRankVCPartitionPolicy,
    SrotaRankVCPolicyError,
)
from veritx_dse.model.srota_rank_route import (  # noqa: E402
    RankPolicyRoute,
)


def _compile(preset: str = "srota32_rank"):
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import build_typed_preset_request
    request = build_typed_preset_request(preset)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.error
    return compilation, request


def test_rank_policy_is_one_vc_per_rank():
    direct = SrotaRankVCPartitionPolicy.derive(valiant=False)
    assert direct.nsets == 2
    assert direct.partition_to_vcs == {0: (0,), 1: (1,)}
    valiant = SrotaRankVCPartitionPolicy.derive(valiant=True)
    assert valiant.nsets == 4
    assert valiant.partition_to_vcs == {0: (0,), 1: (1,), 2: (2,), 3: (3,)}
    # Rank never decreases: no (1, 0) transition may exist.
    assert (1, 0) not in valiant.allowed_transitions


def test_rank_policy_refuses_a_foreign_vc_count():
    with pytest.raises(SrotaRankVCPolicyError):
        SrotaRankVCPartitionPolicy(
            num_vcs=3, valiant=True,
            rank_to_vcs=((0, (0,)), (1, (1,)), (2, (2,)), (3, (3,))))


def test_valiant_design_compiles_and_carries_four_rank_sets():
    compilation, _request = _compile()
    route = compilation.bundle.router_route
    assert isinstance(route, RankPolicyRoute)
    assert "valiant" in route.shapes
    assert compilation.bundle.vc_assignment.vc_count == 4
    assert dict(route.partition_to_vcs) == {0: (0,), 1: (1,), 2: (2,), 3: (3,)}


def test_rank_union_is_acyclic_in_the_canonical_proof():
    from veritx_dse.verification.shared_resource_deadlock import (
        verify_shared_resource_deadlock,
    )
    compilation, _request = _compile()
    verdict = verify_shared_resource_deadlock(compilation.bundle.router_route)
    assert verdict.verdict == "PASS", verdict.reason
    assert verdict.edge_count > 0
    assert verdict.node_count > 0


def test_rank_design_renders_the_rank_config():
    from veritx_dse.application.capability_truth import _parents_from_bundle
    from veritx_dse.backend.booksim_projection import prepare_booksim_input
    compilation, request = _compile()
    parents = _parents_from_bundle(compilation.bundle, request)
    prepared = prepare_booksim_input(parents, seed=0)
    values = {line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
              for line in prepared.config_text.splitlines() if " = " in line}
    assert values["topology"] == "srota"
    # ROW|COL|VALIANT = 1 | 2 | 4
    assert values["srota_path_en"] == "7"
    assert values["srota_vc_policy"] == "rank"
    assert values["num_vcs"] == "4"
    assert values["srota_d_num_vcs"] == "4"


def test_rank_valiant_executes_live_and_conserves_flits():
    """The rank route survives projection and the fork's own CDG check."""
    import shutil
    import tempfile

    from veritx_dse.backend.booksim_execution import execute_prepared_booksim
    from veritx_dse.backend.booksim_projection import prepare_booksim_input

    binary = DSE.parents[2] / "third_party" / "booksim2" / "src" / "booksim"
    if not binary.is_file():
        found = shutil.which("booksim")
        if found is None:
            pytest.skip("no built BookSim binary in tree")
        binary = Path(found)

    compilation, request = _compile()
    from veritx_dse.application.capability_truth import _parents_from_bundle
    parents = _parents_from_bundle(compilation.bundle, request)
    prepared = prepare_booksim_input(parents, seed=0)
    values = {line.split(" = ", 1)[0]: line.split(" = ", 1)[1].rstrip(";")
              for line in prepared.config_text.splitlines() if " = " in line}
    assert values["srota_path_en"] == "7"
    assert values["srota_vc_policy"] == "rank"
    assert values["num_vcs"] == "4"
    with tempfile.TemporaryDirectory() as td:
        record = execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=Path(td) / "run",
            timeout=600)
    stats = (record.evidence.to_dict()
             if hasattr(record.evidence, "to_dict") else {}).get("stats", {})
    assert stats.get("completion_cycles", 0) > 0, stats
    assert stats.get("flits_injected") == stats.get("flits_accepted"), stats
    assert stats.get("flits_injected") == prepared.expected_flits
    assert record.evidence.route_observation == "EXECUTED_ROUTE_OBSERVED"
    assert record.evidence.route_dump_sha256


@pytest.mark.parametrize("mutation", ["empty", "edges", "choices", "partition", "tap", "next_router"])
def test_rank_cached_proof_data_cannot_replace_admitted_walks(mutation):
    from dataclasses import replace
    from veritx_dse.verification.certificate import _deadlock_free, _route_legal
    from veritx_dse.verification.shared_resource_deadlock import verify_shared_resource_deadlock
    compilation, _request = _compile()
    route = compilation.bundle.router_route
    if mutation == "empty":
        changed = replace(route, nodes=(), edges=())
    elif mutation == "edges":
        changed = replace(route, edges=())
    elif mutation == "partition":
        changed = replace(route, partition_to_vcs={0: (1,), 1: (0,), 2: (2,), 3: (3,)})
    else:
        choices = dict(route.choices)
        key = next(key for key, options in choices.items()
                   if key[0] != route.terminal_to_router[key[1]] and len(options) > 1)
        first = choices[key][0]
        if mutation == "choices":
            choices[key] = choices[key][1:]
        else:
            replacement = (replace(first, tap=first.tap + 1) if mutation == "tap"
                           else replace(first, next_router=key[0]))
            choices[key] = (replacement,) + choices[key][1:]
        changed = replace(route, choices=choices)
    assert verify_shared_resource_deadlock(changed).verdict == "UNSUPPORTED"
    bundle = replace(compilation.bundle, router_route=changed)
    assert _route_legal(bundle).status == "FAIL"
    assert _deadlock_free(bundle).status == "FAIL"


def test_rank_shape_envelope_must_match_the_authored_parent():
    from dataclasses import replace
    from veritx_dse.model.srota_rank_route import rank_policy_route_for_srota
    from veritx_dse.verification.certificate import _deadlock_free
    compilation, _request = _compile()
    route = rank_policy_route_for_srota(k=4, c=2, shapes=frozenset({"row"}),
        mecs_row=True, mecs_col=True, topology_hash=compilation.bundle.topology.topology_hash())
    # A self-consistent smaller policy is not the authored Valiant policy.
    assert _deadlock_free(replace(compilation.bundle, router_route=route)).status == "FAIL"


def test_shape_policy_cannot_carry_valiant():
    """The model refuses what the fork refuses: `shape` + Valiant."""
    from veritx_dse.application.fabric_compiler import FabricCompiler
    from veritx_dse.application.presets import _typed_workload
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, DependencyGraph,
    )
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.noc_controls import NocControls
    from veritx_dse.model.topology_intent import topology_intent_from_dict
    intent = topology_intent_from_dict({
        "kind": "srota", "side_length": 4, "concentration": 2,
        "mecs_row": True, "mecs_col": True, "drop_latency": 1,
        "planes": ["d", "t"], "island_columns": [],
        "path_shapes": ["row", "valiant"], "vc_policy": "shape",
        "sidebuf_enable": True, "sidebuf_watermark": 6,
        "tel_period": 4, "tel_latency": 8,
    })
    compilation = FabricCompiler().compile(CompileRequestV4(
        workload=_typed_workload(32, payload_bytes=32 * 128),
        dependencies=DependencyGraph(()),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=32, protocol="AXI",
                      data_width=256, addr_width=64),),
        topology=intent, noc_controls=NocControls()))
    assert compilation.status == "UNSUPPORTED"
    assert compilation.stopped_at_stage == "ROUTING"
