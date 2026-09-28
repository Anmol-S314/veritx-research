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
    """Makes resolve_runtime_binary find a binary file.

    NOTE: a bare executable is NOT a qualified producer — assessment
    must still refuse READY unless the producer-identity resolver is
    explicitly monkeypatched (an "exit 0" shell never qualifies).
    """

    def __init__(self, tmp_path: Path, monkeypatch):
        binary = tmp_path / "AstraSim_BookSim2"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        monkeypatch.setenv("VERITX_ASTRA_BIN", str(binary))
        self.binary = binary


def _pinned_identity(binary: Path):
    """A manifest-verified, clean producer identity for the fake binary."""
    from veritx_dse.backend.producer import ProducerIdentity
    return ProducerIdentity(
        binary_path=str(binary), binary_sha256="a" * 64, binary_size=128,
        source_revision="cafe" * 10, dirty=False, dirty_digest=None,
        manifest_verified=True, build_manifest_sha256="b" * 64,
        build_recipe_version="astra-sim+booksim2/v1")


def _qualify_fake_producer(tmp_path: Path, monkeypatch):
    """Monkeypatch ONLY the producer-identity resolver to vouch for the
    fake binary — the product path itself never accepts it."""
    import veritx_dse.backend.astra_execution as _ax
    env = _FakeAstraEnv(tmp_path, monkeypatch)
    monkeypatch.setattr(
        _ax, "resolve_astra_identity",
        lambda binary, repo_root=None: _pinned_identity(Path(binary)))
    return env


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


def test_an_exit_zero_shell_is_never_a_qualified_producer(tmp_path,
                                                          monkeypatch):
    """THE qualification pin: a bare executable file must NOT read READY.
    Only an explicitly monkeypatched identity resolver (test-only) can
    vouch for the fake binary."""
    _FakeAstraEnv(tmp_path, monkeypatch)
    adapter = Astra2Adapter()
    assessment = adapter.assess(
        _context(), EvaluationQuestion.SYSTEM_MAKESPAN)
    assert assessment.support is SupportLevel.SUPPORTED
    assert assessment.readiness is BackendReadiness.BLOCKED
    assert "not qualified" in assessment.reason or \
        "not pinned" in assessment.reason


def test_assess_ready_with_binary(tmp_path, monkeypatch):
    _qualify_fake_producer(tmp_path, monkeypatch)
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


def test_assess_supports_multi_class_without_flattening():
    """Multi-class is never flattened: the V3 seam preserves both MoE
    classes structurally, and assessment is SUPPORTED now that the
    embedded runtime proves class-aware injection (class ABI 1).
    Flattening into one stream never happens."""
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
    assert assessment.support is SupportLevel.SUPPORTED
    assert "flatten" not in (assessment.reason or "").lower()


# ── prepare: composition over existing authorities ───────────────────

def test_prepare_returns_the_generic_execution_seam(tmp_path, monkeypatch):
    """prepare() returns PreparedExecution (the federation seam), with
    the REAL projections retained inside — preparation is executable by
    itself and needs no runtime binary."""
    monkeypatch.delenv("VERITX_ASTRA_BIN", raising=False)
    context = _context()
    adapter = Astra2Adapter()
    from veritx_dse.backend.adapter import PreparedExecution
    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert isinstance(prepared, PreparedExecution)
    assert prepared.backend_id == "ASTRA2_EMBEDDED_BOOKSIM"
    native = prepared.native_prepared
    # every identity is the EXISTING authority's, not invented
    assert prepared.projection_identity == native.workload_projection_id
    assert prepared.qualification_identity == native.machine_id
    assert native.machine_id == native.machine.machine_id()
    assert native.workload_projection_id == \
        native.workload_projection.projection_id()
    assert native.embedded_fabric_abi_version == \
        native.machine.embedded_fabric_abi_version
    assert native.standalone_config_sha256 == \
        native.machine.standalone_config_sha256
    # collective-mode is the qualified path: never the message default
    assert native.workload_projection.et_granularity == "collectives"
    assert native.namespace is not None
    assert native.namespace.machine_id == native.machine_id


def test_prepare_consults_the_canonical_binding_authority(tmp_path,
                                                          monkeypatch):
    """The adapter feeds bind_participants() the canonical bundle objects
    — no second rank→endpoint map lives in the adapter."""
    from veritx_dse.backend.adapter import PreparedExecution
    import veritx_dse.workload.traffic as _traffic

    calls: list[dict] = []
    real_bind = _traffic.bind_participants

    def _spy(*, participant_count, mapping, attachment,
             resolved_fabric):
        calls.append({
            "participant_count": participant_count, "mapping": mapping,
            "attachment": attachment,
            "resolved_fabric": resolved_fabric})
        return real_bind(
            participant_count=participant_count, mapping=mapping,
            attachment=attachment, resolved_fabric=resolved_fabric)

    monkeypatch.setattr(_traffic, "bind_participants", _spy)
    context = _context()
    adapter = Astra2Adapter()
    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert isinstance(prepared, PreparedExecution)
    # every binding derivation in this path consults the canonical
    # authority (BookSim traffic + the adapter's own namespace binding)
    assert calls
    for call in calls:
        assert call["mapping"] is context.bundle.mapping
        assert call["attachment"] is context.bundle.attachment
        assert call["resolved_fabric"] is context.bundle.resolved_fabric
    native = prepared.native_prepared
    binding = real_bind(
        participant_count=native.workload_projection.participant_count,
        mapping=context.bundle.mapping,
        attachment=context.bundle.attachment,
        resolved_fabric=context.bundle.resolved_fabric)
    assert native.rank_to_endpoint == binding.rank_to_endpoint
    assert native.namespace.rank_to_endpoint == binding.rank_to_endpoint
    assert native.namespace.participant_mapping_id == binding.binding_id()


def test_prepare_preserves_a_permuted_canonical_placement(tmp_path,
                                                          monkeypatch):
    """Deliberately permuted rank→endpoint placement flows through the
    adapter unchanged: rank == endpoint is never assumed, and the
    namespace uses the same mapping."""
    from veritx_dse.backend.adapter import PreparedExecution
    from veritx_dse.workload.traffic import ParticipantEndpointMapping
    import veritx_dse.workload.traffic as _traffic

    context = _context()
    count = context.workload.participant_count
    # a genuine permutation inside the participant endpoint range
    rows = tuple((rank, (rank * 3 + 1) % count) for rank in range(count))
    assert any(r != e for r, e in rows)
    assert len({e for _, e in rows}) == count
    permuted = ParticipantEndpointMapping(
        participant_count=count, rank_to_endpoint=rows,
        fabric_id=context.bundle.resolved_fabric.resolved_fabric_hash
        if not callable(getattr(context.bundle.resolved_fabric,
                                "resolved_fabric_hash", None))
        else context.bundle.resolved_fabric.resolved_fabric_hash())
    monkeypatch.setattr(_traffic, "bind_participants",
                        lambda **kw: permuted)
    adapter = Astra2Adapter()
    prepared = adapter.prepare(
        context, EvaluationQuestion.SYSTEM_MAKESPAN)
    assert isinstance(prepared, PreparedExecution)
    native = prepared.native_prepared
    assert native.rank_to_endpoint != tuple((r, r) for r in range(count))
    assert native.rank_to_endpoint == permuted.rank_to_endpoint
    assert native.namespace.rank_to_endpoint == permuted.rank_to_endpoint
    assert native.namespace.participant_mapping_id == \
        permuted.binding_id()


def test_prepare_refuses_relabeling(tmp_path, monkeypatch):
    _FakeAstraEnv(tmp_path, monkeypatch)
    adapter = Astra2Adapter()
    with pytest.raises(ValueError, match="relabeling is refused"):
        adapter.prepare(
            _context(), EvaluationQuestion.SYSTEM_MAKESPAN,
            traffic_class="made_up")


def test_prepare_needs_no_runtime_binary(tmp_path, monkeypatch):
    """Preparation is semantic projection: it must succeed with no
    binary anywhere (execution availability is a separate concern)."""
    monkeypatch.delenv("VERITX_ASTRA_BIN", raising=False)
    import veritx_dse.backend.astra as _astra
    monkeypatch.setattr(_astra, "resolve_runtime_binary", lambda: None)
    from veritx_dse.backend.adapter import PreparedExecution
    prepared = Astra2Adapter().prepare(
        _context(), EvaluationQuestion.SYSTEM_MAKESPAN)
    assert isinstance(prepared, PreparedExecution)


def _envelope_workload(operations):
    """A minimal workload double: audit + by_id only."""
    from types import SimpleNamespace
    graph = SimpleNamespace(
        ordered_operations=lambda: operations,
        by_id=lambda op_id: next(
            op for op in operations if op.operation_id == op_id))
    return SimpleNamespace(
        ordered_operations=graph.ordered_operations, by_id=graph.by_id)


def test_collective_envelope_allows_compute_and_qualified_collectives():
    from veritx_dse.workload.graph import (
        KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, collective_detail,
        compute_detail,
    )
    adapter = Astra2Adapter()
    ops = (
        OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=1000,
                                            participant_count=4)),
        OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                      deps=("pre",),
                      detail=collective_detail(
                          collective_kind="ALLREDUCE",
                          participants=(0, 1, 2, 3), payload_bytes=1024,
                          participant_count=4)),
    )
    adapter._require_collective_envelope(_envelope_workload(ops))


def test_collective_envelope_refuses_p2p_and_multicast():
    from veritx_dse.backend.astra_adapter import Astra2SemanticRefusal
    from veritx_dse.workload.graph import (
        KIND_MULTICAST, KIND_P2P, OperationNode, multicast_detail,
        p2p_detail,
    )
    adapter = Astra2Adapter()
    p2p = OperationNode(
        operation_id="p2p0", kind=KIND_P2P,
        detail=p2p_detail(role="TRANSFER", src_rank=0, dst_rank=1,
                          payload_bytes=64, participant_count=4))
    mcast = OperationNode(
        operation_id="mc0", kind=KIND_MULTICAST,
        detail=multicast_detail(
            source_rank=0, destinations=(1, 2, 3), payload_bytes=64,
            replication="SOURCE_REPLICATION", participant_count=4))
    for op in (p2p, mcast):
        with pytest.raises(Astra2SemanticRefusal):
            adapter._require_collective_envelope(
                _envelope_workload((op,)))


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
