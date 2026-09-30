"""Backend federation orchestration contracts.

Rationale: docs/decisions/modules/backend.md
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.contracts import (
    BackendConfigArtifact, BackendInputManifest,
)
from veritx_dse.backend.producer import ProducerIdentity

if TYPE_CHECKING:
    from veritx_dse.application.evaluation_context import (
        CanonicalEvaluationContext,
    )
    from veritx_dse.backend.normalized_evidence import (
        NormalizedBackendEvidence,
    )

class BackendContractError(ValueError):
    """A federation orchestration contract was violated."""

class SupportLevel(Enum):
    """Whether a backend can faithfully REPRESENT requested semantics.

Rationale: docs/decisions/modules/backend.md
    """

    SUPPORTED = "SUPPORTED"
    CONDITIONAL = "CONDITIONAL"
    UNSUPPORTED = "UNSUPPORTED"

class BackendReadiness(Enum):
    """Whether the backend can execute RIGHT NOW.

Rationale: docs/decisions/modules/backend.md
    """

    READY = "READY"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"

class ModelFidelity(Enum):
    """WHAT KIND OF MODEL produced a result.

Rationale: docs/decisions/modules/backend.md
    """

    ANALYTICAL_ESTIMATE = "ANALYTICAL_ESTIMATE"
    NETWORK_PACKET_SIMULATION = "NETWORK_PACKET_SIMULATION"
    SYSTEM_SIMULATION = "SYSTEM_SIMULATION"
    FULL_SYSTEM_SIMULATION = "FULL_SYSTEM_SIMULATION"
    MEMORY_CYCLE_SIMULATION = "MEMORY_CYCLE_SIMULATION"
    RTL_SIMULATION = "RTL_SIMULATION"
    OBSERVED = "OBSERVED"

def _non_empty_str(name: str, value: object) -> None:
    if type(value) is not str or not value:
        raise BackendContractError(
            f"{name} must be a non-empty string, got {value!r}")

def _opt_non_empty_str(name: str, value: object) -> None:
    if value is not None:
        _non_empty_str(name, value)

def _limitations(name: str, value: object) -> None:
    if type(value) is not tuple:
        raise BackendContractError(
            f"{name} must be a tuple, got {type(value).__name__}")
    seen: set[str] = set()
    for item in value:
        _non_empty_str(f"{name} entry", item)
        if item in seen:
            raise BackendContractError(
                f"{name} has duplicate entry {item!r}")
        seen.add(item)

@dataclass(frozen=True)
class BackendCapability:
    """A backend's declaration of one thing it can (or cannot) do.

Rationale: docs/decisions/modules/backend.md
    """

    question: EvaluationQuestion
    support: SupportLevel
    fidelity: ModelFidelity
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.question) is not EvaluationQuestion:
            raise BackendContractError(
                f"question must be an EvaluationQuestion, got "
                f"{self.question!r}")
        if type(self.support) is not SupportLevel:
            raise BackendContractError(
                f"support must be a SupportLevel, got {self.support!r}")
        if type(self.fidelity) is not ModelFidelity:
            raise BackendContractError(
                f"fidelity must be a ModelFidelity, got {self.fidelity!r}")
        _limitations("limitations", self.limitations)

@dataclass(frozen=True)
class BackendAssessment:
    """Can this backend answer this capability, for this exact canonical
    context, right now?

Rationale: docs/decisions/modules/backend.md
    """

    backend_id: str
    question: EvaluationQuestion
    support: SupportLevel
    readiness: BackendReadiness
    fidelity: ModelFidelity
    qualification_profile: str | None
    reason: str | None
    required_parents: tuple[str, ...]
    limitations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _non_empty_str("backend_id", self.backend_id)
        if type(self.question) is not EvaluationQuestion:
            raise BackendContractError(
                f"question must be an EvaluationQuestion, got "
                f"{self.question!r}")
        if type(self.support) is not SupportLevel:
            raise BackendContractError(
                f"support must be a SupportLevel, got {self.support!r}")
        if type(self.readiness) is not BackendReadiness:
            raise BackendContractError(
                f"readiness must be a BackendReadiness, got "
                f"{self.readiness!r}")
        if type(self.fidelity) is not ModelFidelity:
            raise BackendContractError(
                f"fidelity must be a ModelFidelity, got {self.fidelity!r}")
        _opt_non_empty_str("qualification_profile",
                           self.qualification_profile)
        _opt_non_empty_str("reason", self.reason)
        if type(self.required_parents) is not tuple:
            raise BackendContractError(
                "required_parents must be a tuple, got "
                f"{type(self.required_parents).__name__}")
        seen: set[str] = set()
        for parent in self.required_parents:
            _non_empty_str("required_parents entry", parent)
            if parent in seen:
                raise BackendContractError(
                    f"required_parents has duplicate {parent!r}")
            seen.add(parent)
        _limitations("limitations", self.limitations)

        if self.support is SupportLevel.UNSUPPORTED:
            if self.readiness is BackendReadiness.READY:
                raise BackendContractError(
                    "an UNSUPPORTED assessment can never be READY")
            if self.reason is None:
                raise BackendContractError(
                    "an UNSUPPORTED assessment must name its reason")
        if self.readiness is BackendReadiness.BLOCKED \
                and self.reason is None:
            raise BackendContractError(
                "a BLOCKED assessment must name its reason")
        if self.readiness is BackendReadiness.UNAVAILABLE \
                and self.reason is None:
            raise BackendContractError(
                "an UNAVAILABLE assessment must name its reason")
        if self.readiness is BackendReadiness.READY \
                and self.support is SupportLevel.UNSUPPORTED:
            raise BackendContractError(
                "a READY assessment cannot carry UNSUPPORTED semantics")

@dataclass(frozen=True)
class PreparedExecution:
    """Composition of one backend's prepared execution identities.

Rationale: docs/decisions/modules/backend.md
    """

    backend_id: str
    projection_identity: str
    qualification_identity: str | None
    backend_config: BackendConfigArtifact | None
    backend_input: BackendInputManifest | None
    producer: ProducerIdentity | None
    native_prepared: object

    def __post_init__(self) -> None:
        _non_empty_str("backend_id", self.backend_id)
        _non_empty_str("projection_identity", self.projection_identity)
        _opt_non_empty_str("qualification_identity",
                           self.qualification_identity)
        if self.backend_config is not None and not isinstance(
                self.backend_config, BackendConfigArtifact):
            raise BackendContractError(
                "backend_config must be a BackendConfigArtifact, got "
                f"{type(self.backend_config).__name__}")
        if self.backend_input is not None and not isinstance(
                self.backend_input, BackendInputManifest):
            raise BackendContractError(
                "backend_input must be a BackendInputManifest, got "
                f"{type(self.backend_input).__name__}")
        if self.producer is not None and not isinstance(
                self.producer, ProducerIdentity):
            raise BackendContractError(
                f"producer must be a ProducerIdentity, got "
                f"{type(self.producer).__name__}")
        if self.native_prepared is None:
            raise BackendContractError(
                "native_prepared must not be None: a prepared execution "
                "without its backend-native structure is not prepared")

@runtime_checkable
class BackendAdapter(Protocol):
    """The minimal federation execution seam.

Rationale: docs/decisions/modules/backend.md
    """

    @property
    def backend_id(self) -> str:
        """Stable execution identity (e.g. ``BOOKSIM_STANDALONE``)."""

    def capabilities(self) -> tuple[BackendCapability, ...]:
        """Declared capabilities; installation does not imply readiness.
        ``question`` names a question from the closed
        ``EvaluationQuestion`` vocabulary: capability truth, never
        aspiration."""

    def assess(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        """Assess one question against the canonical context, now."""

    def prepare(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        **kwargs: object,
    ) -> PreparedExecution:
        """Compose the prepared execution identities for one execution."""

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,
    ) -> object:
        """Execute and return the backend-NATIVE result."""

    def normalize(
        self,
        context: CanonicalEvaluationContext,
        question: EvaluationQuestion,
        prepared: PreparedExecution,
        native_result: object,
    ) -> NormalizedBackendEvidence:
        """Project authenticated native evidence into the common
        normalized envelope. The native evidence stays authoritative;
        this is an index/view over it."""

__all__ = [
    "BackendAdapter", "BackendAssessment", "BackendCapability",
    "BackendContractError", "BackendReadiness", "ModelFidelity",
    "PreparedExecution", "SupportLevel",
]
