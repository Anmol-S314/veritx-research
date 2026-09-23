"""veritx_dse.application.service — canonical application compile orchestration.

The ONE product compile path:

    CompileIntent
          |
          v
    derive_compile_request
          |
          v
    generate candidate          (explicit candidate-policy dispatch)
          |
          v
    canonical candidate compiler
          |
          v
    ResolvedFabric
          |
          v
    ResourceStore.commit_resolution
          |
          v
    validated committed result

The service owns SEQUENCING ONLY. It owns no topology derivation, routing
semantics, VC semantics, packet format, router behavior, address decoding,
verification, backend lowering, requirements evaluation, or persistence
format — those authorities already exist below it.

SCOPE

``SrotaControlPlane`` receives an explicit :class:`ResourceStore` (no
implicit path, no environment variable, no repository-relative store, no
global singleton) and exposes exactly one public operation, ``compile``.
Backend lowering is a later slice; compilation here is structural.

RECOMPILATION

``compile()`` always runs candidate generation and canonical compilation;
it never short-circuits on an existing resolution. That keeps one compile
path, detects accidental policy/compiler drift, and lets the idempotent
``commit_resolution`` surface a genuine conflict instead of hiding it
behind a cache lookup. Caching is a later, explicit product policy.

PERSISTENCE

Only the resolution root is durable (see :mod:`veritx_dse.application.store`).
The live ``CompiledFabric`` is returned in :class:`CompileOutcome` for the
future backend-lowering path but is never persisted and never pickled.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType

from veritx_dse.application.compile_intent import (
    CompileIntent, CompileIntentError, derive_compile_request,
)
from veritx_dse.application.resources import ResourceValidationError
from veritx_dse.application.store import (
    ResourceStore, ResourceStoreError, StoredCompileResolution,
)
from veritx_dse.compiler.candidate_policy import (
    CandidatePlan, CandidatePolicy, CandidatePolicyError,
    generate_baseline_candidate,
)
from veritx_dse.compiler.canonical import (
    CanonicalCompileError, CompiledFabric, compile_deterministic_candidate,
)
from veritx_dse.model.compile_model import CompileRequest


class CompileServiceStage(Enum):
    """Stable application-stage vocabulary for failure attribution."""

    INTENT = "INTENT"
    CANDIDATE = "CANDIDATE"
    COMPILE = "COMPILE"
    PERSISTENCE = "PERSISTENCE"


class CompileServiceError(Exception):
    """An application stage failed; the underlying cause is preserved."""

    def __init__(self, stage: CompileServiceStage, detail: str):
        self.stage = stage
        self.detail = detail
        super().__init__(f"stage={stage.value}: {detail}")


@dataclass(frozen=True)
class CompileOutcome:
    """Durable committed root plus the live exact compiled DAG.

    No hash, no schema, no persistence format, no timestamp, no backend.
    The convenience properties derive from the committed resolution rather
    than duplicating stored identity values.
    """

    compiled: CompiledFabric
    committed: StoredCompileResolution

    def __post_init__(self):
        if not isinstance(self.compiled, CompiledFabric):
            raise TypeError(
                f"compiled must be a CompiledFabric, got "
                f"{type(self.compiled).__name__}")
        if not isinstance(self.committed, StoredCompileResolution):
            raise TypeError(
                f"committed must be a StoredCompileResolution, got "
                f"{type(self.committed).__name__}")

    @property
    def intent_id(self) -> str:
        return self.committed.resolution.intent_id

    @property
    def design_hash(self) -> str:
        return self.committed.resolution.design_hash

    @property
    def resolved_fabric_hash(self) -> str:
        return self.committed.resolution.resolved_fabric_hash


# ── candidate-policy dispatch (explicit, closed, no fallback) ─────────────

@dataclass(frozen=True)
class _PolicyDispatch:
    """One declared candidate policy's generator + canonical compiler pair."""

    generate: Callable[[CompileRequest], CandidatePlan]
    compile: Callable[[CompileRequest, CandidatePlan], CompiledFabric]


def _baseline_generate(design: CompileRequest) -> CandidatePlan:
    return generate_baseline_candidate(design=design)


def _deterministic_compile(design: CompileRequest,
                           plan: CandidatePlan) -> CompiledFabric:
    return compile_deterministic_candidate(
        design=design, inventory=plan.inventory, mapping=plan.mapping,
        routing_policy=plan.routing_policy, vc_spec=plan.vc_spec,
        settings=plan.compile_settings)


_POLICY_DISPATCH: MappingProxyType = MappingProxyType({
    CandidatePolicy.BASELINE_DETERMINISTIC_V2: _PolicyDispatch(
        generate=_baseline_generate, compile=_deterministic_compile),
})


class SrotaControlPlane:
    """Sequencing-only application compile surface."""

    def __init__(self, *, store: ResourceStore):
        if not isinstance(store, ResourceStore):
            raise CompileServiceError(
                CompileServiceStage.PERSISTENCE,
                f"store must be a ResourceStore, got "
                f"{type(store).__name__}; there is no implicit store path")
        self._store = store

    def compile(self, intent: CompileIntent) -> CompileOutcome:
        """Compile one intent and commit its resolution root."""
        if not isinstance(intent, CompileIntent):
            raise CompileServiceError(
                CompileServiceStage.INTENT,
                f"intent must be a CompileIntent, got "
                f"{type(intent).__name__}; callers parse their transport "
                "into a CompileIntent before entering the service")

        # 1-2. exact canonical request declared by the intent
        try:
            design = derive_compile_request(intent)
        except CompileIntentError as exc:
            raise CompileServiceError(
                CompileServiceStage.INTENT,
                f"could not derive a CompileRequest: {exc}") from exc

        # 3. explicit dispatch on the DECLARED candidate policy
        dispatch = _POLICY_DISPATCH.get(intent.candidate_policy)
        if dispatch is None:
            raise CompileServiceError(
                CompileServiceStage.INTENT,
                f"no candidate-policy dispatch is implemented for "
                f"{intent.candidate_policy!r}")

        # 4. generate the explicit candidate plan
        try:
            plan = dispatch.generate(design)
        except CandidatePolicyError as exc:
            raise CompileServiceError(
                CompileServiceStage.CANDIDATE,
                f"candidate generation failed: {exc}") from exc
        if not isinstance(plan, CandidatePlan):
            raise CompileServiceError(
                CompileServiceStage.CANDIDATE,
                f"candidate generator returned {type(plan).__name__}, not a "
                "CandidatePlan")
        if plan.policy != intent.candidate_policy:
            raise CompileServiceError(
                CompileServiceStage.CANDIDATE,
                f"generated candidate policy {plan.policy!r} does not match "
                f"the declared policy {intent.candidate_policy!r}")

        # 5. canonical candidate compiler (exact plan -> exact hardware)
        try:
            compiled = dispatch.compile(design, plan)
        except CanonicalCompileError as exc:
            raise CompileServiceError(
                CompileServiceStage.COMPILE,
                f"canonical compilation failed: {exc}") from exc
        if compiled.design.to_dict() != design.to_dict():
            raise CompileServiceError(
                CompileServiceStage.COMPILE,
                "canonical compiler did not preserve the exact design")
        if compiled.resolved_fabric.design_hash != design.design_hash():
            raise CompileServiceError(
                CompileServiceStage.COMPILE,
                "canonical compiler design_hash does not match the design")

        # 6-7. commit the resolution root, then reload it and validate.
        # Only store-domain failures are classified PERSISTENCE: an
        # unexpected RuntimeError/TypeError from a broken internal call is a
        # programmer bug and must propagate unchanged.
        try:
            self._store.commit_resolution(
                intent=intent, design=design,
                resolved_fabric=compiled.resolved_fabric)
            committed = self._store.load_committed(intent.intent_id())
        except (ResourceStoreError, ResourceValidationError) as exc:
            raise CompileServiceError(
                CompileServiceStage.PERSISTENCE,
                f"could not commit or reload the resolution: {exc}") from exc

        # 8. post-commit consistency against the live compiled result
        if committed.design.to_dict() != compiled.design.to_dict() \
                or committed.resolved_fabric.to_dict() \
                != compiled.resolved_fabric.to_dict() \
                or committed.resolution.intent_id != intent.intent_id() \
                or committed.resolution.design_hash \
                != compiled.design.design_hash() \
                or committed.resolution.resolved_fabric_hash \
                != compiled.resolved_fabric.resolved_fabric_hash:
            raise CompileServiceError(
                CompileServiceStage.PERSISTENCE,
                "committed resources do not match the live compiled result")
        return CompileOutcome(compiled=compiled, committed=committed)
