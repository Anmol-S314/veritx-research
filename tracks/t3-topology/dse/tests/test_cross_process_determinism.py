"""Cross-process determinism of semantics-v2 graph processing.

The 50x repeatability tests run in ONE Python process, so they cannot see
hash-seed or set-iteration variance. These tests spawn real subprocesses
with explicit PYTHONHASHSEED values and require byte-identical design and
candidate semantics from every process, for every dependency declaration
permutation.

The problematic graph is deliberately one where the OLD deterministic-less
traversal (set-iterated roots + insertion-ordered adjacency) could expose
different DFS back-edge witnesses — and therefore different unique victim
sets and VC counts — under different root orders:

    A -> B BLOCKING
    A -> C BLOCKING
    B -> C BLOCKING
    C -> A BLOCKING

Negative control: legacy semantics v1 identity is still declaration-order
sensitive on purpose (that is the preserved v1 ruling). Legacy candidate
compilation is not required here.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from veritx_dse.compiler.candidate_policy import generate_baseline_candidate
from veritx_dse.model.compile_model import (
    COMPILER_SEMANTICS_VERSION, Agent, AgentKind, CompileRequest, DepKind,
    Dependency, DependencyGraph, ModelFamily, NocConfig, TopologyFamily,
    Workload,
)

DSE_DIR = Path(__file__).resolve().parent.parent

# Explicit hash seeds, including "random" (a fresh randomized seed).
HASH_SEEDS = ["0", "1", "2", "7", "42", "123", "999", "random"]

PROBLEM_GRAPH = (("A", "B"), ("A", "C"), ("B", "C"), ("C", "A"))
# Two declaration permutations of the SAME dependency multiset.
PERMUTATIONS = {
    "declared": PROBLEM_GRAPH,
    "reversed": tuple(reversed(PROBLEM_GRAPH)),
}

# Child program: emits canonical machine-readable results on stdout.
_CHILD = r'''
import json
import sys

from veritx_dse.compiler.candidate_policy import generate_baseline_candidate
from veritx_dse.compiler.canonical import compile_deterministic_candidate
from veritx_dse.model.compile_model import (
    CompileRequest, DepKind, Dependency, DependencyGraph, ModelFamily,
    NocConfig, TopologyFamily, Workload,
)
from veritx_dse.model.compile_model import Agent, AgentKind, AddressMap

rows = json.loads(sys.argv[1])
deps = DependencyGraph(tuple(
    Dependency(source=src, target=tgt, kind=DepKind.BLOCKING)
    for src, tgt in rows))
design = CompileRequest(
    workload=Workload(model_family=ModelFamily.MOE, tp=1, pp=1, ep=1, dp=1),
    requirements=[],
    agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4, protocol="AXI",
                  data_width=256, addr_width=64),),
    dependencies=deps,
    noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    address_map=AddressMap())
plan = generate_baseline_candidate(design=design)
spec = plan.vc_spec
compiled = compile_deterministic_candidate(
    design=design, inventory=plan.inventory, mapping=plan.mapping,
    routing_policy=plan.routing_policy, vc_spec=spec,
    settings=plan.compile_settings)
victims = sorted(name for name, vcs in spec.traffic_class_to_vcs
                 if vcs != (0,))
print(json.dumps({
    "python_hash_seed": __import__("os").environ.get("PYTHONHASHSEED"),
    "compiler_semantics_version": design.compiler_semantics_version,
    "design_hash": design.design_hash(),
    "cycle_witnesses": design.dependencies.find_cycles(),
    "victims": victims,
    "vc_count": spec.vc_count,
    "traffic_class_to_vcs": [[name, list(vcs)]
                             for name, vcs in spec.traffic_class_to_vcs],
    "vc_to_routing_class": [[vc, cls] for vc, cls in spec.vc_to_routing_class],
    "allowed_transitions": [list(p) for p in spec.allowed_transitions],
    "escape_vcs": list(spec.escape_vcs),
    "derivation": spec.derivation,
    "mapping_policy": plan.mapping_policy.value,
    "policy": plan.policy.value,
    "topology_hash": compiled.topology.topology_hash(),
    "mapping_hash": compiled.mapping.mapping_hash(),
    "fabric_hash": compiled.fabric.fabric_hash,
    "resolved_fabric_hash": compiled.resolved_fabric.resolved_fabric_hash,
}, sort_keys=True))
'''


def _run_child(deps: tuple[tuple[str, str], ...], seed: str) -> dict:
    env = {**os.environ,
           "PYTHONHASHSEED": seed,
           "PYTHONPATH": str(DSE_DIR)}
    result = subprocess.run(
        [sys.executable, "-c", _CHILD, json.dumps([list(r) for r in deps])],
        capture_output=True, text=True, timeout=120,
        cwd=str(DSE_DIR), env=env)
    assert result.returncode == 0, (
        f"child failed (seed={seed}):\n{result.stderr[-2000:]}")
    return json.loads(result.stdout)


def _candidate_view(result: dict) -> dict:
    """Everything that must be identical across processes/permutations."""
    return {key: value for key, value in result.items()
            if key != "python_hash_seed"}


@pytest.mark.parametrize("seed", HASH_SEEDS)
@pytest.mark.parametrize("perm", sorted(PERMUTATIONS))
def test_every_hash_seed_process_agrees(perm, seed):
    result = _run_child(PERMUTATIONS[perm], seed)
    assert result["python_hash_seed"] == seed
    assert result["compiler_semantics_version"] \
        == COMPILER_SEMANTICS_VERSION
    assert result["policy"] == "baseline_deterministic_v2"
    assert result["mapping_policy"] == "rank_order_v1"
    # the problematic graph really exercises cycles/victims
    assert result["cycle_witnesses"]
    assert result["victims"]
    assert result["vc_count"] >= 2


def test_all_seeds_and_permutations_are_byte_identical():
    baseline = None
    baseline_perm = None
    for perm in sorted(PERMUTATIONS):
        first_perm = None
        for seed in HASH_SEEDS:
            result = _candidate_view(_run_child(PERMUTATIONS[perm], seed))
            if first_perm is None:
                first_perm = result
            assert result == first_perm, (
                f"seed {seed} diverged for permutation {perm}")
        if baseline is None:
            baseline = first_perm
            baseline_perm = perm
        assert first_perm == baseline, (
            f"declaration permutation {perm} diverged from {baseline_perm}")


def test_permutations_share_one_design_and_candidate_semantics():
    declared = _candidate_view(_run_child(PERMUTATIONS["declared"], "42"))
    reversed_ = _candidate_view(_run_child(PERMUTATIONS["reversed"], "42"))
    assert declared == reversed_


# ── negative control: legacy v1 identity ordering still exists ─────────────

def _v1_design(order) -> CompileRequest:
    return CompileRequest(
        workload=Workload(model_family=ModelFamily.MOE),
        requirements=[],
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
        dependencies=DependencyGraph(tuple(
            Dependency(src, tgt, DepKind.BLOCKING) for src, tgt in order)),
        noc_config=NocConfig(topology_family=TopologyFamily.MESH),
        compiler_semantics_version=1)


def test_legacy_v1_identity_is_declaration_order_sensitive():
    """Negative control: the preserved v1 ruling, not current behavior."""
    deps = (("A", "B"), ("B", "C"), ("C", "A"))
    forward = _v1_design(deps)
    backward = _v1_design(tuple(reversed(deps)))
    assert forward.design_hash() != backward.design_hash()
    # same multiset under CURRENT semantics: identity does not move
    v2_forward = replace(forward, compiler_semantics_version=2)
    v2_backward = replace(backward, compiler_semantics_version=2)
    assert v2_forward.design_hash() == v2_backward.design_hash()
    # v1 hashing itself is process-stable: declaration order is the only
    # variable (a fresh process with another hash seed agrees exactly)
    env = {**os.environ, "PYTHONHASHSEED": "123",
           "PYTHONPATH": str(DSE_DIR)}
    script = r'''
import json
import sys
from veritx_dse.model.compile_model import (
    Agent, AgentKind, CompileRequest, DepKind, Dependency, DependencyGraph,
    ModelFamily, NocConfig, TopologyFamily, Workload,
)
rows = json.loads(sys.argv[1])
design = CompileRequest(
    workload=Workload(model_family=ModelFamily.MOE),
    requirements=[],
    agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=4),),
    dependencies=DependencyGraph(tuple(
        Dependency(src, tgt, DepKind.BLOCKING) for src, tgt in rows)),
    noc_config=NocConfig(topology_family=TopologyFamily.MESH),
    compiler_semantics_version=1)
print(design.design_hash())
'''
    result = subprocess.run(
        [sys.executable, "-c", script, json.dumps(list(deps))],
        capture_output=True, text=True, timeout=120,
        cwd=str(DSE_DIR), env=env)
    assert result.returncode == 0, result.stderr[-1000:]
    assert result.stdout.strip() == forward.design_hash()
