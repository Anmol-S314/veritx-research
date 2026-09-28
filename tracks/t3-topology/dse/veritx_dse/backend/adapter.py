"""Backend federation orchestration contracts.

An ORCHESTRATION layer over the existing scientific-identity authorities
(``contracts.BackendConfigArtifact``, ``contracts.BackendInputManifest``,
``producer.ProducerIdentity``, backend-native prepared structures) — not
a second identity system. These objects are in-memory declarations:
no schema_version, no hashing, no serialization; identity lives in the
underlying canonical artifacts.

One seam is deliberately temporary (Federation 05 replaces it):
``context`` is opaque (``object``) until adapters consume the canonical
evaluation context; no compatibility machinery is provided.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable

from veritx_dse.application.evaluation_question import EvaluationQuestion
from veritx_dse.backend.contracts import (
    BackendConfigArtifact, BackendInputManifest,
)
from veritx_dse.backend.producer import ProducerIdentity


class BackendContractError(ValueError):
    """A federation orchestration contract was violated."""


class SupportLevel(Enum):
    """Whether a backend can faithfully REPRESENT requested semantics.

    SUPPORTED: representable inside a stated capability envelope.
    CONDITIONAL: representation depends on explicit conditions checked
    during assessment.
    UNSUPPORTED: the backend cannot faithfully represent the semantics.
    Never a boolean: the reason a backend cannot represent is evidence.
    """

    SUPPORTED = "SUPPORTED"
    CONDITIONAL = "CONDITIONAL"
    UNSUPPORTED = "UNSUPPORTED"


class BackendReadiness(Enum):
    """Whether the backend can execute RIGHT NOW.

    READY: semantics passed and the required producer/runtime exists.
    BLOCKED: the backend exists but semantic or qualification
    requirements prevent this execution.
    UNAVAILABLE: the required executable/runtime/producer is absent.

    UNSUPPORTED (semantics) and UNAVAILABLE (runtime) are different
    states: a backend can support a capability while its executable is
    missing.
    """

    READY = "READY"
    BLOCKED = "BLOCKED"
    UNAVAILABLE = "UNAVAILABLE"


class ModelFidelity(Enum):
    """WHAT KIND OF MODEL produced a result.

    Deliberately orthogonal to execution/provenance qualification
    (``ScientificBackendEvidence.execution_fidelity`` QUALIFIED /
    DIAGNOSTIC_UNPINNED_PRODUCER / TEST_INJECTED). Model fidelity says a
    packet-level network simulation produced the number; qualification
    says whether that execution's producer was pinned. Never collapse
    the two dimensions.
    """

    ANALYTICAL_ESTIMATE = "ANALYTICAL_ESTIMATE"
    NETWORK_PACKET_SIMULATION = "NETWORK_PACKET_SIMULATION"
    SYSTEM_SIMULATION = "SYSTEM_SIMULATION"
    FULL_SYSTEM_SIMULATION = "FULL_SYSTEM_SIMULATION"
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

    A declaration, not a persisted scientific artifact — no content
    identity in this commit. ``question`` is from the closed
    ``EvaluationQuestion`` vocabulary: capability truth, not aspiration.
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

    Cross-field laws: UNSUPPORTED can never be READY and always names
    its reason; BLOCKED and UNAVAILABLE always name theirs; READY
    requires the semantics be representable (support != UNSUPPORTED).
    No law requires a qualification_profile — future backends may
    qualify differently.
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

    References the existing authorities; never flattens or supersedes
    them. ``backend_config``/``backend_input`` are optional because
    BookSim fits those contracts naturally while other backends (e.g.
    ASTRA) carry their own native projection identities — requiring the
    BookSim artifacts here would secretly make this a BookSim contract.
    ``native_prepared`` is the backend-specific prepared structure,
    referenced opaquely: no hashing, no serialization, no inspection.
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

    Exactly four operations: declare capabilities, assess one for a
    canonical context, prepare, execute. The adapter ORCHESTRATES
    existing backend authorities (projection, execution, evidence); it
    does not re-implement or force them into one lifecycle — no
    parse()/verify()/qualify() ceremonies, and no normalize() until the
    common evidence envelope exists (Federation 08).
    """

    @property
    def backend_id(self) -> str:
        """Stable execution identity (e.g. ``BOOKSIM_STANDALONE``)."""

    def capabilities(self) -> tuple[BackendCapability, ...]:
        """Declared capabilities; installation does not imply readiness.
        ``capability_id`` names a question from the closed
        ``EvaluationQuestion`` vocabulary (Federation 04)."""

    def assess(
        self,
        context: object,          # Federation 05: CanonicalEvaluationContext
        question: EvaluationQuestion,
    ) -> BackendAssessment:
        """Assess one question against the canonical context, now."""

    def prepare(
        self,
        context: object,          # Federation 05: CanonicalEvaluationContext
        question: EvaluationQuestion,
    ) -> PreparedExecution:
        """Compose the prepared execution identities for one execution."""

    def execute(
        self,
        prepared: PreparedExecution,
        options: object,          # backend-native execution options
    ) -> object:
        """Execute and return the backend-NATIVE result (Federation 08
        adds the common normalized evidence envelope)."""


__all__ = [
    "BackendAdapter", "BackendAssessment", "BackendCapability",
    "BackendContractError", "BackendReadiness", "ModelFidelity",
    "PreparedExecution", "SupportLevel",
]
