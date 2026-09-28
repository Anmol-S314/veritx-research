"""Federation Commit 02 — the orchestration contracts themselves.

Tests the CONTRACT, not any backend: enum closure, capability
strictness, assessment state laws, parent strictness, PreparedExecution
composition over the existing authorities, and Protocol structural
typing. Nothing here consumes a concrete backend.
"""
from __future__ import annotations

import dataclasses
import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.backend.adapter import (  # noqa: E402
    BackendAdapter, BackendAssessment, BackendCapability,
    BackendContractError, BackendReadiness, ModelFidelity,
    PreparedExecution, SupportLevel,
)
from veritx_dse.application.evaluation_question import (  # noqa: E402
    EvaluationQuestion,
)
from veritx_dse.backend.contracts import (  # noqa: E402
    BackendConfigArtifact, BackendInputManifest, BackendTarget,
    RenderedInput,
)
from veritx_dse.backend.producer import ProducerIdentity  # noqa: E402

H64 = "a" * 64
H64B = "b" * 64
H64C = "c" * 64


# ── existing-authority builders (same shapes test_backend_contracts uses)

def _artifact(**kw) -> BackendConfigArtifact:
    from veritx_dse.backend.contracts import (
        CertificationEffect, RepresentationStatus, SemanticBinding,
        SemanticDimension,
    )
    bindings = tuple(
        SemanticBinding(
            dimension=dim, source_identity=H64,
            representation_status=RepresentationStatus.EXACT,
            backend_fields=(), reason="",
            certification_effect=CertificationEffect.NONE,
            supported_domain="test")
        for dim in SemanticDimension)
    defaults = dict(
        backend_target=BackendTarget.BOOKSIM_STANDALONE,
        backend_profile="CERTIFIED_TEST_V1",
        backend_semantics_version="test-1", lowerer_version="B37/1",
        resolved_fabric_hash=H64, fabric_hash=H64B,
        normalized_parameters=(("num_vcs", 4),),
        semantic_bindings=bindings)
    defaults.update(kw)
    return BackendConfigArtifact(**defaults)


def _manifest(**kw) -> BackendInputManifest:
    defaults = dict(
        backend_config_hash=_artifact().backend_config_hash(),
        workload_hash=H64C, execution_mode="REAL_SIMULATION", seed=7,
        seed_policy="explicit",
        rendered_inputs=(RenderedInput(
            role="topology", logical_name="topology.anynet",
            sha256="d" * 64, size=123),),
        invocation_args=(("config", "config.cfg"),))
    defaults.update(kw)
    return BackendInputManifest(**defaults)


def _producer() -> ProducerIdentity:
    return ProducerIdentity(
        binary_path="/test/booksim", binary_sha256=H64, binary_size=10,
        source_revision="deadbeef", dirty=False, dirty_digest=None,
        manifest_verified=True, build_manifest_sha256=H64B,
        build_recipe_version="test/v1")


# ── A. enum closure ───────────────────────────────────────────────────

def test_support_level_is_closed():
    assert {s.value for s in SupportLevel} == {
        "SUPPORTED", "CONDITIONAL", "UNSUPPORTED"}


def test_backend_readiness_is_closed():
    assert {r.value for r in BackendReadiness} == {
        "READY", "BLOCKED", "UNAVAILABLE"}


def test_model_fidelity_is_closed():
    assert {f.value for f in ModelFidelity} == {
        "ANALYTICAL_ESTIMATE", "NETWORK_PACKET_SIMULATION",
        "SYSTEM_SIMULATION", "FULL_SYSTEM_SIMULATION",
        "MEMORY_CYCLE_SIMULATION", "RTL_SIMULATION",
        "OBSERVED"}


# ── B. BackendCapability strictness ──────────────────────────────────

def test_capability_valid_construction():
    cap = BackendCapability(
        question=EvaluationQuestion.NETWORK_COMPLETION,
        support=SupportLevel.SUPPORTED,
        fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
        limitations=("one VC envelope",))
    assert cap.limitations == ("one VC envelope",)


def test_capability_empty_id_refused():
    with pytest.raises(BackendContractError):
        BackendCapability(
            question=None, support=SupportLevel.SUPPORTED,
            fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION)


def test_capability_list_limitations_refused_not_converted():
    with pytest.raises(BackendContractError, match="tuple"):
        BackendCapability(
            question=EvaluationQuestion.NETWORK_COMPLETION, support=SupportLevel.SUPPORTED,
            fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
            limitations=["one VC envelope"])


def test_capability_empty_limitation_refused():
    with pytest.raises(BackendContractError):
        BackendCapability(
            question=EvaluationQuestion.NETWORK_COMPLETION, support=SupportLevel.SUPPORTED,
            fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
            limitations=("",))


def test_capability_duplicate_limitation_refused():
    with pytest.raises(BackendContractError, match="duplicate"):
        BackendCapability(
            question=EvaluationQuestion.NETWORK_COMPLETION, support=SupportLevel.SUPPORTED,
            fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
            limitations=("a", "a"))


def test_capability_wrong_enum_type_refused():
    with pytest.raises(BackendContractError):
        BackendCapability(
            question=EvaluationQuestion.NETWORK_COMPLETION, support="SUPPORTED",
            fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION)
    with pytest.raises(BackendContractError):
        BackendCapability(
            question=EvaluationQuestion.NETWORK_COMPLETION, support=SupportLevel.SUPPORTED,
            fidelity="NETWORK_PACKET_SIMULATION")


# ── C. BackendAssessment state laws ──────────────────────────────────

def _assessment(**kw) -> BackendAssessment:
    defaults = dict(
        backend_id="BOOKSIM_STANDALONE",
        question=EvaluationQuestion.NETWORK_COMPLETION,
        support=SupportLevel.SUPPORTED, readiness=BackendReadiness.READY,
        fidelity=ModelFidelity.NETWORK_PACKET_SIMULATION,
        qualification_profile="CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        reason=None, required_parents=("design",))
    defaults.update(kw)
    return BackendAssessment(**defaults)


def test_assessment_supported_ready_is_valid():
    a = _assessment()
    assert a.readiness is BackendReadiness.READY


def test_assessment_conditional_blocked_with_reason_is_valid():
    a = _assessment(
        support=SupportLevel.CONDITIONAL, readiness=BackendReadiness.BLOCKED,
        reason="concentration knob is unqualified")
    assert a.reason


def test_assessment_supported_unavailable_with_reason_is_valid():
    a = _assessment(
        readiness=BackendReadiness.UNAVAILABLE,
        reason="producer executable is absent")
    assert a.support is SupportLevel.SUPPORTED
    assert a.readiness is BackendReadiness.UNAVAILABLE


def test_assessment_unsupported_blocked_with_reason_is_valid():
    _assessment(support=SupportLevel.UNSUPPORTED,
                readiness=BackendReadiness.BLOCKED,
                reason="no certified multi-class route function")


def test_assessment_unsupported_ready_refused():
    with pytest.raises(BackendContractError):
        _assessment(support=SupportLevel.UNSUPPORTED)


def test_assessment_unsupported_requires_reason():
    with pytest.raises(BackendContractError, match="reason"):
        _assessment(support=SupportLevel.UNSUPPORTED,
                    readiness=BackendReadiness.BLOCKED, reason=None)


def test_assessment_blocked_requires_reason():
    with pytest.raises(BackendContractError, match="reason"):
        _assessment(readiness=BackendReadiness.BLOCKED, reason=None)


def test_assessment_unavailable_requires_reason():
    with pytest.raises(BackendContractError, match="reason"):
        _assessment(readiness=BackendReadiness.UNAVAILABLE, reason=None)


def test_assessment_empty_reason_string_refused():
    with pytest.raises(BackendContractError):
        _assessment(readiness=BackendReadiness.BLOCKED, reason="")


def test_assessment_is_frozen():
    a = _assessment()
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.reason = "tampered"


# ── D. required-parent strictness ────────────────────────────────────

def test_assessment_parent_tuple_accepted():
    assert _assessment(required_parents=("design", "route")).required_parents


def test_assessment_parent_list_refused():
    with pytest.raises(BackendContractError, match="tuple"):
        _assessment(required_parents=["design"])


def test_assessment_parent_duplicates_refused():
    with pytest.raises(BackendContractError, match="duplicate"):
        _assessment(required_parents=("design", "design"))


def test_assessment_empty_parent_refused():
    with pytest.raises(BackendContractError):
        _assessment(required_parents=("",))


# ── E. PreparedExecution composition ─────────────────────────────────

def test_prepared_execution_accepts_existing_authorities():
    config = _artifact()
    manifest = _manifest(backend_config_hash=config.backend_config_hash())
    prepared = PreparedExecution(
        backend_id="BOOKSIM_STANDALONE",
        projection_identity=H64C, qualification_identity="q-1",
        backend_config=config, backend_input=manifest,
        producer=_producer(), native_prepared=object())
    assert prepared.backend_id == "BOOKSIM_STANDALONE"


def test_prepared_execution_wrong_config_type_refused():
    with pytest.raises(BackendContractError, match="BackendConfigArtifact"):
        PreparedExecution(
            backend_id="B", projection_identity=H64,
            qualification_identity=None, backend_config=object(),
            backend_input=None, producer=None, native_prepared=object())


def test_prepared_execution_wrong_input_type_refused():
    with pytest.raises(BackendContractError, match="BackendInputManifest"):
        PreparedExecution(
            backend_id="B", projection_identity=H64,
            qualification_identity=None, backend_config=None,
            backend_input=object(), producer=None, native_prepared=object())


def test_prepared_execution_wrong_producer_type_refused():
    with pytest.raises(BackendContractError, match="ProducerIdentity"):
        PreparedExecution(
            backend_id="B", projection_identity=H64,
            qualification_identity=None, backend_config=None,
            backend_input=None, producer=object(), native_prepared=object())


def test_prepared_execution_native_none_refused():
    with pytest.raises(BackendContractError, match="native_prepared"):
        PreparedExecution(
            backend_id="B", projection_identity=H64,
            qualification_identity=None, backend_config=None,
            backend_input=None, producer=None, native_prepared=None)


def test_prepared_execution_empty_projection_identity_refused():
    with pytest.raises(BackendContractError):
        PreparedExecution(
            backend_id="B", projection_identity="",
            qualification_identity=None, backend_config=None,
            backend_input=None, producer=None, native_prepared=object())


class _FakeAstraMachine:
    """ASTRA-like native prepared structure: not a BookSim artifact."""


def test_prepared_execution_astra_like_without_booksim_contracts_is_legal():
    """The generic contract must not secretly become a BookSim contract:
    a backend with its own native projection identities and no
    BackendConfigArtifact/BackendInputManifest composes fine."""
    prepared = PreparedExecution(
        backend_id="ASTRA2_TEST", projection_identity="wp-123",
        qualification_identity="tier-2", backend_config=None,
        backend_input=None, producer=_producer(),
        native_prepared=_FakeAstraMachine())
    assert isinstance(prepared.native_prepared, _FakeAstraMachine)
    assert prepared.backend_config is None
    assert prepared.backend_input is None


# ── F. Protocol structural typing ────────────────────────────────────

class _FakeAdapter:
    """Minimal structural adapter — no fake scientific behavior."""

    @property
    def backend_id(self) -> str:
        return "FAKE"

    def capabilities(self) -> tuple[BackendCapability, ...]:
        return (BackendCapability(
            question=EvaluationQuestion.NETWORK_COMPLETION, support=SupportLevel.SUPPORTED,
            fidelity=ModelFidelity.ANALYTICAL_ESTIMATE),)

    def assess(self, context: object,
               question: EvaluationQuestion) -> BackendAssessment:
        return _assessment(backend_id="FAKE", question=question)

    def prepare(self, context: object,
                question: EvaluationQuestion) -> PreparedExecution:
        return PreparedExecution(
            backend_id="FAKE", projection_identity=H64,
            qualification_identity=None, backend_config=None,
            backend_input=None, producer=None, native_prepared=object())

    def execute(self, prepared: PreparedExecution,
                options: object) -> object:
        return object()

    def normalize(self, context: object,
                  question: EvaluationQuestion,
                  prepared: PreparedExecution,
                  native_result: object) -> object:
        return object()


def test_fake_adapter_satisfies_protocol_structurally():
    assert isinstance(_FakeAdapter(), BackendAdapter)


def test_non_adapter_does_not_satisfy_protocol():
    assert not isinstance(object(), BackendAdapter)
