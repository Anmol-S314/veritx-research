"""booksim_qualification_registry — the ONE qualification authority.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from veritx_dse.backend.booksim_projection import (
    BookSimProjectionError,
)
from veritx_dse.core.errors import Refusal, SemanticError

class QualificationRegistryError(ValueError, SemanticError):
    """The registry itself is malformed. Never a design refusal."""

def _repo_root() -> Path:
    return Path(__file__).resolve().parents[5]

@dataclass(frozen=True)
class QualificationRecord:
    """One profile's qualification: state, scope and RESOLVABLE evidence.

Rationale: docs/decisions/modules/application.md
    """

    profile_id: str
    state: str
    projection_semantics_version: str
    lowerer_version: str | None
    qualifier: str
    evidence_paths: tuple[str, ...]
    scope: str

    def __post_init__(self):
        if self.state not in ("QUALIFIED", "NOT_QUALIFIED"):
            raise QualificationRegistryError(
                f"state must be QUALIFIED or NOT_QUALIFIED, got "
                f"{self.state!r}")
        if self.state != "QUALIFIED":
            return
        if not self.qualifier or ":" not in self.qualifier:
            raise QualificationRegistryError(
                f"profile {self.profile_id!r} is QUALIFIED but its qualifier "
                f"{self.qualifier!r} is not a 'module:function' authority")
        if not self.evidence_paths:
            raise QualificationRegistryError(
                f"profile {self.profile_id!r} is QUALIFIED but names no "
                "durable evidence")

    @property
    def is_qualified(self) -> bool:
        return self.state == "QUALIFIED"

    def unresolved_evidence(self) -> tuple[str, ...]:
        """Repository-relative evidence paths that do not exist."""
        root = _repo_root()
        return tuple(p for p in self.evidence_paths if not (root / p).exists())

    def qualifier_callable(self) -> Callable[..., Any]:
        """Resolve the executable authority. Raises if it cannot."""
        return resolve_handler(self.qualifier)

QUALIFICATION: dict[str, QualificationRecord] = {
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        state="QUALIFIED",
        projection_semantics_version="booksim2-fork+P1B-meshdor-dump+prepared-v2",
        lowerer_version="DORXY/1",
        qualifier="veritx_dse.backend.booksim_projection:qualify_native_mesh_dor",
        evidence_paths=(
            "docs/product/EVIDENCE-FIRST-CAPABILITY-ARCHAEOLOGY.md",
            "tracks/t3-topology/dse/docs/BAKE-OFF-REPRODUCIBILITY.md",
            "tracks/t3-topology/dse/tests/test_booksim_route_equivalence.py",
        ),
        scope="MaterializedFamily.MESH, seat_capacity 1, square k x k, "
              "routing class DOR_XY",
    ),
    "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1",
        state="QUALIFIED",
        projection_semantics_version=
            "booksim2-fork+P2-cmesh-dor+prepared-v1",
        lowerer_version="DORXY/1",
        qualifier=(
            "veritx_dse.backend.booksim_projection:"
            "qualify_native_cmesh_dor"),
        evidence_paths=(
            "tracks/t3-topology/dse/tests/test_booksim_cmesh_projection.py",
            "docs/product/CAPABILITY-CLOSURE-2026-09.md",
        ),
        scope="MaterializedFamily.CONCENTRATED_MESH, seat_capacity 4, "
              "square k x k, routing class DOR_XY, use_noc_latency 0",
    ),
    "CERTIFIED_BOOKSIM_ANYNET_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_ANYNET_V1",
        state="QUALIFIED",
        projection_semantics_version="booksim2-fork+B3.7b-anynet-dump+prepared-v2",
        lowerer_version=None,
        qualifier="veritx_dse.backend.booksim_projection:qualify_anynet_min_hops",
        evidence_paths=(
            "tracks/t3-topology/dse/docs/BAKE-OFF-REPRODUCIBILITY.md",
            "docs/product/EVIDENCE-FIRST-CAPABILITY-ARCHAEOLOGY.md",
        ),
        scope="explicit graph, routing class ANYNET_MIN_HOPS",
    ),
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1",
        state="QUALIFIED",
        projection_semantics_version="booksim2-fork+P3-meshdor-mc+prepared-v1",
        lowerer_version="DORXY-MC/1",
        qualifier="veritx_dse.backend.booksim_projection:"
                  "qualify_native_mesh_dor_mc",
        evidence_paths=(
            "tracks/t3-topology/dse/tests/"
            "test_multiclass_optimization_hard_gate.py",
            "tracks/t3-topology/dse/tests/test_booksim_conservation.py",
            "tracks/t3-topology/dse/tests/test_booksim_route_equivalence.py",
        ),
        scope="MaterializedFamily.MESH, seat_capacity 1, square k x k, "
              "routing class DOR_XY, two or more canonical traffic "
              "classes, fork-v2 per-class replay with per-class "
              "conservation",
    ),
    "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1",
        state="QUALIFIED",
        projection_semantics_version=
            "booksim2-fork+T1-torusdor-dump+prepared-v1",
        lowerer_version="DORTORUS/1",
        qualifier="veritx_dse.backend.booksim_projection:"
                  "qualify_native_torus_dor",
        evidence_paths=(
            "tracks/t3-topology/dse/tests/test_torus_route.py",
            "tracks/t3-topology/dse/tests/"
            "test_torus_flatfly_profiles.py",
            "tracks/t3-topology/dse/tests/"
            "test_torus_flatfly_execution.py",
        ),
        scope="MaterializedFamily.TORUS, square k x k, routing class "
              "DOR_TORUS_XY, exact 2-VC dateline halves, deterministic "
              "midpoint ties, identity VC transitions, use_noc_latency 0",
    ),
    "CERTIFIED_BOOKSIM_FLATFLY_MIN_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_FLATFLY_MIN_V1",
        state="QUALIFIED",
        projection_semantics_version=
            "booksim2-fork+F1-flatflymin-dump+prepared-v1",
        lowerer_version="FLATFLYMIN/1",
        qualifier="veritx_dse.backend.booksim_projection:"
                  "qualify_native_flatfly_min",
        evidence_paths=(
            "tracks/t3-topology/dse/tests/test_flatfly_min.py",
            "tracks/t3-topology/dse/tests/"
            "test_torus_flatfly_profiles.py",
            "tracks/t3-topology/dse/tests/"
            "test_torus_flatfly_execution.py",
        ),
        scope="MaterializedFamily.FLATFLY, k-ary 2-fly, concentration 1, "
              "routing class FLATFLY_MIN, identity node->router, unit "
              "latency/weight, no parallel channels, single class",
    ),
}

EXECUTION_HANDLERS: dict[str, str] = {
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
    "CERTIFIED_BOOKSIM_CMESH_DOR_XY_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
    "CERTIFIED_BOOKSIM_ANYNET_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_MC_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
    "CERTIFIED_BOOKSIM_TORUS_DOR_XY_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
    "CERTIFIED_BOOKSIM_FLATFLY_MIN_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
}

def qualification_of(profile_id: str) -> QualificationRecord:
    """An UNREGISTERED profile is NOT_QUALIFIED by construction — never
    qualified by omission."""
    record = QUALIFICATION.get(profile_id)
    if record is not None:
        return record
    return QualificationRecord(
        profile_id=profile_id,
        state="NOT_QUALIFIED",
        projection_semantics_version="",
        lowerer_version=None,
        qualifier="",
        evidence_paths=(),
        scope="none",
    )

def resolve_handler(dotted: str) -> Callable[..., Any]:
    """Import a `module:function` authority, so a registry entry cannot be a
    typo that silently means 'available'."""
    import importlib
    module_name, _, attr = dotted.partition(":")
    if not module_name or not attr:
        raise QualificationRegistryError(
            f"handler {dotted!r} is not 'module:attribute'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise QualificationRegistryError(
            f"handler module {module_name!r} does not import: {e}") from e
    handler = getattr(module, attr, None)
    if handler is None:
        raise QualificationRegistryError(
            f"handler {dotted!r} does not exist")
    if not callable(handler):
        raise QualificationRegistryError(
            f"handler {dotted!r} is not callable")
    return handler

def execution_handler_for(profile_id: str) -> str | None:
    """The dotted path of the execution implementation, or None.

    `None` means NO execution implementation is registered — which is a
    different fact from "execution was not attempted".
    """
    return EXECUTION_HANDLERS.get(profile_id)

def resolve_execution_handler(profile_id: str) -> tuple[Callable[..., Any] | None, str | None]:
    """(handler, None) when the registration RESOLVES, else (None, reason).

    THE runtime authority for EXECUTABLE. Callers must not mark EXECUTABLE
    from the mere presence of a registry string: a typo would otherwise read
    as availability until a test happened to catch it.
    """
    dotted = EXECUTION_HANDLERS.get(profile_id)
    if dotted is None:
        return None, "no execution implementation is registered for this profile"
    try:
        return resolve_handler(dotted), None
    except QualificationRegistryError as e:
        return None, f"registered handler does not resolve: {e}"

def _profile_semantics() -> dict[str, tuple[str, str | None]]:
    """Read the EXACT profile semantics from the projection layer itself.

    Reading them rather than hardcoding them is what makes a semantics change
    invalidate the old qualification automatically.
    """
    from veritx_dse.backend import booksim_projection as bp
    return {
        bp.MESH_DOR_PROFILE.profile_id: (
            bp.MESH_DOR_PROFILE.semantics_version,
            getattr(bp, "_MESH_DOR_LOWERER_VERSION", None)),
        bp.CMESH_DOR_PROFILE.profile_id: (
            bp.CMESH_DOR_PROFILE.semantics_version,
            getattr(bp, "_CMESH_DOR_LOWERER_VERSION", None)),
        bp.ANYNET_PROFILE.profile_id: (
            bp.ANYNET_PROFILE.semantics_version,
            getattr(bp, "_ANYNET_LOWERER_VERSION", None)),
        bp.MESH_DOR_MC_PROFILE.profile_id: (
            bp.MESH_DOR_MC_PROFILE.semantics_version,
            getattr(bp, "_ML_DOR_LOWERER_VERSION", None)),
        bp.TORUS_DOR_PROFILE.profile_id: (
            bp.TORUS_DOR_PROFILE.semantics_version,
            getattr(bp, "_TORUS_DOR_LOWERER_VERSION", None)),
        bp.FLATFLY_MIN_PROFILE.profile_id: (
            bp.FLATFLY_MIN_PROFILE.semantics_version,
            getattr(bp, "_FLATFLY_MIN_LOWERER_VERSION", None)),
    }

def validate_registry() -> None:
    """FAIL CLOSED. Called at import and by the gate.

Rationale: docs/decisions/modules/application.md
    """
    problems: list[str] = []
    semantics = _profile_semantics()
    for profile_id, record in QUALIFICATION.items():
        if not record.is_qualified:
            continue
        if profile_id not in semantics:
            problems.append(
                f"{profile_id}: QUALIFIED but no such profile exists in the "
                "projection layer")
            continue
        want_sem, want_lower = semantics[profile_id]
        if record.projection_semantics_version != want_sem:
            problems.append(
                f"{profile_id}: qualification covers semantics "
                f"{record.projection_semantics_version!r} but the profile is "
                f"{want_sem!r} — the qualification is STALE and must be "
                "re-established")
        if record.lowerer_version != want_lower:
            problems.append(
                f"{profile_id}: qualification covers lowerer "
                f"{record.lowerer_version!r} but the profile binds "
                f"{want_lower!r}")
        try:
            resolve_handler(record.qualifier)
        except QualificationRegistryError as e:
            problems.append(f"{profile_id}: qualifier does not resolve: {e}")
        missing = record.unresolved_evidence()
        if missing:
            problems.append(
                f"{profile_id}: durable evidence does not exist: "
                f"{list(missing)}")
    if problems:
        raise QualificationRegistryError(
            "QUALIFICATION REGISTRY INVALID:\n  - " + "\n  - ".join(problems))

validate_registry()

def _projection_module():
    from veritx_dse.backend import booksim_projection as bp
    return bp

def evaluate_qualification(profile: Any, parents: Any
                           ) -> tuple[bool, str]:
    """(qualified, authority) for an ACTUAL selected profile + parents.

    This is the only way capability truth may answer QUALIFIED. Every
    condition must hold; the first failure is reported with its reason.
    """
    profile_id = getattr(profile, "profile_id", None)
    record = qualification_of(profile_id)
    if not record.is_qualified:
        return False, (f"{profile_id} has no qualification record "
                       "(unregistered profiles are NOT_QUALIFIED by "
                       "construction)")
    actual_sem = getattr(profile, "semantics_version", None)
    if actual_sem != record.projection_semantics_version:
        return False, (
            f"{profile_id} selected with projection semantics "
            f"{actual_sem!r} but its qualification covers "
            f"{record.projection_semantics_version!r} — the qualification does "
            "not carry across a semantics change")
    default_lower = _profile_semantics().get(profile_id, (None, None))[1]
    actual_lower = getattr(profile, "lowerer_version", default_lower)
    if actual_lower != record.lowerer_version:
        return False, (
            f"{profile_id} selected with lowerer {actual_lower!r} but its "
            f"qualification covers {record.lowerer_version!r}")
    missing = record.unresolved_evidence()
    if missing:
        return False, (f"{profile_id} durable evidence does not exist: "
                       f"{list(missing)}")
    try:
        qualifier = resolve_handler(record.qualifier)
    except QualificationRegistryError as e:
        return False, f"{profile_id} qualifier does not resolve: {e}"
    try:
        verdict = qualifier(parents)
    except (Refusal, BookSimProjectionError, QualificationRegistryError
            ) as exc:
        return False, (f"{profile_id} qualifier "
                       f"{record.qualifier} refused these parents: "
                       f"{type(exc).__name__}: {str(exc)[:200]}")
    return True, (f"{profile_id} QUALIFIED under projection semantics "
                  f"{record.projection_semantics_version!r} "
                  f"(lowerer {record.lowerer_version!r}); scope "
                  f"{record.scope}; qualifier {record.qualifier} accepted "
                  f"these canonical parents; evidence "
                  f"{', '.join(record.evidence_paths)}; verdict {verdict!r}")

__all__ = [
    "QualificationRecord", "QualificationRegistryError", "QUALIFICATION",
    "EXECUTION_HANDLERS", "qualification_of", "execution_handler_for",
    "resolve_handler", "resolve_execution_handler", "validate_registry",
    "evaluate_qualification",
]
