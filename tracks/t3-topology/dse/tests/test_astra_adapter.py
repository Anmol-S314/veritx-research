"""Federation Commit 09 — the Astra2Adapter.

Proves the adapter orchestrates the EXISTING ASTRA authorities (workload
projection, machine qualification over the certified BookSim fabric
projection, canonical namespace binding) and refuses honestly:
multi-class flattening refused, relabeling refused, absent-binary is
UNAVAILABLE not UNSUPPORTED. Execution tests stay in
``test_astra_runtime.py`` (injected-runner fault matrix + real-runtime
when the binary exists); this file owns the federation seam.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from test_canonical_compiler import _det, _design  # noqa: E402

from veritx_dse.application.evaluation_context import (  # noqa: E402
    build_evaluation_context,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAdapter, BackendReadiness, ModelFidelity, SupportLevel,
)
from veritx_dse.backend.astra_adapter import (  # noqa: E402
    ASTRA2_MODEL_FIDELITY, ASTRA2_QUESTIONS, Astra2Adapter,
)
from veritx_dse.workload.graph import (  # noqa: E402
    KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
    collective_detail, compute_detail,
)

COUNT = 4


class _FakeAstraEnv:
    """Makes resolve_runtime_binary find a plausible binary."""

    def __init__(self, tmp_path: Path, monkeypatch):
        binary = tmp_path / "AstraSim_BookSim2"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        monkeypatch.setenv("VERITX_ASTRA_BIN", str(binary))


def _compiled(count=COUNT):
    return _det(_design(compute=count, tp=count))


def _collective_request(count=COUNT, payload=1024):
    from veritx_dse.model.compile_model import (
        Agent, AgentKind, CollectiveDimension, CollectiveIntent,
        CollectiveKind, CompileRequestV3, DependencyGraph, ModelFamily,
        NocConfig, TopologyFamily, WorkloadV3,
    )
    return CompileRequestV3(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER, tp=count, dp=1,
            collectives=(CollectiveIntent(
                kind=CollectiveKind.ALLREDUCE,
                dimension=CollectiveDimension.TP,
                payload_bytes=payload,
                traffic_class="tp_collective"),)),
        requirements=(),
        agents=(Agent(kind=AgentKind.COMPUTE_TILE, count=count),),
        dependencies=DependencyGraph([]),
        noc_config=NocConfig(
            topology_family=TopologyFamily.MESH, concentration=1))


def _context(count=COUNT, payload=1024):
    """A real PASS compilation whose bundle matches the deterministic
    fabric the ASTRA projection needs (compile the v3 request directly)."""
    request = _collective_request(count, payload)
    compilation = FabricCompiler().compile(request)
    assert compilation.status == "COMPILED", compilation.status
    return build_evaluation_context(compilation)


# ── capabilities ─────────────────────────────────────────────────────

def test_capabilities_declare_the_three_system_questions():
    adapter = Astra2Adapter()
    caps = {cap.question: cap for cap in adapter.capabilities()}
    assert set(caps) == set(ASTRA2_QUESTIONS)
    for cap in caps.values():
        assert cap.support is SupportLevel.SUPPORTED
        assert cap.fidelity is ModelFidelity.SYSTEM_SIMULATION
        assert any("never end-to-end workload runtime" in lim
                   for lim in cap.limitations)


def test_backend_id_names_the_embedded_network():
    assert Astra2Adapter().backend_id == "ASTRA2_EMBEDDED_BOOKSIM"


def test_adapter_satisfies_protocol_structurally():
    assert isinstance(Astra2Adapter(), BackendAdapter)


# ── assess: honest gates ─────────────────────────────────────────────

def test_assess_without_binary_is_unavailable_not_unsupported(tmp_path,
                                                              monkeypatch):
    monkeypatch.delenv("VERITX_ASTRA_BIN", raising=False)
    from veritx_dse.backend.astra import resolve_runtime_binary
    if resolve_runtime_binary() is not None:
        pytest.skip("an ASTRA runtime exists in this worktree; the "
                    "absent-runtime condition cannot be pinned here")
    adapter = Astra2Adapter()
    assessment = adapter.assess(
        _context(), EvaluationQuestion.SYSTEM_MAKESPAN)
    # the semantics CAN be represented; the runtime is absent
    assert assessment.support is not SupportLevel.UNSUPPORTED
    assert assessment.readiness is BackendReadiness.UNAVAILABLE
    assert "absent" in assessment.reason


def test_assess_ready_with_binary(tmp_path, monkeypatch):
    _FakeAstraEnv(tmp_path, monkeypatch)
    adapter = Astra2Adapter()
    assessment = adapter.assess(
        _context(), EvaluationQuestion.SYSTEM_MAKESPAN)
    assert assessment.support is SupportLevel.SUPPORTED
    assert assessment.readiness is BackendReadiness.READY
    assert assessment.fidelity is ModelFidelity.SYSTEM_SIMULATION
    assert assessment.qualification_profile == "ASTRA2_EMBEDDED_BOOKSIM"


def test_assess_refuses_network_completion_as_unsupported():
    adapter = Astra2Adapter()
    assessment = adapter.assess(
        _context(), EvaluationQuestion.NETWORK_COMPLETION)
    assert assessment.support is SupportLevel.UNSUPPORTED
    assert assessment.readiness is BackendReadiness.BLOCKED
    assert "system-level" in assessment.reason


def test_assess_refuses_multi_class_flattening():
    """THE semantic trap: MoE's two canonical classes must never be
    flattened into one ASTRA stream."""
    import json
    from veritx_dse.core.paths import REPO
    from veritx_dse.product.service import parse_request_doc
    moe = REPO / "tracks/t3-topology/examples/moe_8x7b_64tiles-v3.json"
    compilation = FabricCompiler().compile(
        parse_request_doc(json.loads(moe.read_text(encoding="utf-8"))))
    assert compilation.status == "COMPILED"
    context = build_evaluation_context(compilation)
    adapter = Astra2Adapter()
    assessment = adapter.assess(context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert assessment.support is SupportLevel.UNSUPPORTED
    assert "single-class" in assessment.reason


# ── prepare: composition over existing authorities ───────────────────

def test_prepare_composes_machine_over_certified_fabric(tmp_path,
                                                        monkeypatch):
    _FakeAstraEnv(tmp_path, monkeypatch)
    context = _context()
    adapter = Astra2Adapter()
    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN)

    # every identity is the EXISTING authority's, not invented
    assert prepared.machine_id == prepared.machine.machine_id()
    assert prepared.workload_projection_id
    assert prepared.embedded_fabric_abi_version == \
        prepared.machine.embedded_fabric_abi_version
    assert prepared.standalone_config_sha256 == \
        prepared.machine.standalone_config_sha256
    # namespace: identity rank→endpoint over the machine's Sys namespace
    assert prepared.rank_to_endpoint == tuple(
        (rank, rank) for rank in range(context.workload.participant_count))


def test_prepare_binds_the_real_namespace_object(tmp_path, monkeypatch):
    _FakeAstraEnv(tmp_path, monkeypatch)
    context = _context()
    adapter = Astra2Adapter()
    prepared = adapter.prepare(
        context, EvaluationQuestion.PER_RANK_COMPLETION)
    assert prepared.namespace is not None
    assert prepared.namespace.machine_id == prepared.machine_id


def test_prepare_refuses_relabeling(tmp_path, monkeypatch):
    _FakeAstraEnv(tmp_path, monkeypatch)
    adapter = Astra2Adapter()
    with pytest.raises(ValueError, match="relabeling is refused"):
        adapter.prepare(
            _context(), EvaluationQuestion.SYSTEM_MAKESPAN,
            traffic_class="made_up")


# ── execute: native evidence only ────────────────────────────────────

def test_execute_requires_astra_native_prepared(tmp_path, monkeypatch):
    _FakeAstraEnv(tmp_path, monkeypatch)
    from veritx_dse.backend.adapter import PreparedExecution
    adapter = Astra2Adapter()
    with pytest.raises(TypeError, match="Astra2Preparation"):
        adapter.execute(
            PreparedExecution(
                backend_id=adapter.backend_id,
                projection_identity="x", qualification_identity=None,
                backend_config=None, backend_input=None, producer=None,
                native_prepared=object()),
            SimpleNamespace(run_dir=tmp_path, timeout_s=60,
                            workload_configuration=tmp_path))
