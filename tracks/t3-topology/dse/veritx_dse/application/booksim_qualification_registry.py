"""booksim_qualification_registry — the ONE qualification authority.

WHY THIS EXISTS (PHASE B.1 §19)
===============================

`select_booksim_profile()` returning a profile is NOT a qualification result.
Before this module, the capability-truth gate treated a successful selection
as PROJECTABLE = EXECUTABLE = QUALIFIED = YES, which is exactly the
false-positive shape the phase exists to remove: three DIFFERENT questions
answered by one observation.

The three questions, and their separate authorities:

  PROJECTABLE  can the canonical projector/preparer produce the backend
               input?  Authority: the REAL preparation path
               (`prepare_booksim_input`) run on the probe parents. Selecting a
               profile is necessary but not sufficient, and the binary is NOT
               spawned merely to answer this.

  EXECUTABLE   does a selected profile have an actual execution
               implementation registered?  Authority: EXECUTION_HANDLERS
               below. This is IMPLEMENTATION AVAILABILITY, not a claim that a
               probe executed during the capability gate.

  QUALIFIED    has the profile been SCIENTIFICALLY qualified?  Authority:
               QUALIFICATION below — a profile id, the compiler semantics it
               was qualified under, its state, and the durable evidence that
               qualified it.

A profile becoming selectable must NOT become QUALIFIED. Adding a profile
here requires naming its qualification evidence; there is no default.

THE TWO SEALED PROFILES ARE NOT BROADENED. Their entries record the
qualification function that already existed and the sealed semantics version
they were qualified under. Future CMesh stays `NOT_QUALIFIED` until PHASE C's
actual end-to-end qualification completes.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from veritx_dse.core.errors import SemanticError


class QualificationRegistryError(ValueError, SemanticError):
    """The registry itself is malformed. Never a design refusal."""


#: The compiler semantics the sealed profiles were qualified under.
SEALED_SEMANTICS_VERSION = 1


@dataclass(frozen=True)
class QualificationRecord:
    """One profile's qualification state and the evidence for it."""
    profile_id: str
    #: QUALIFIED | NOT_QUALIFIED
    state: str
    #: The compiler semantics version the qualification was performed under.
    #: A qualification does not silently carry across semantics versions.
    semantics_version: int
    #: Durable evidence: the qualification function that proves it, and/or a
    #: committed evidence document. NEVER prose alone.
    evidence: tuple[str, ...]
    #: The family/route-class scope the qualification covers. A qualification
    #: is scoped: it never generalizes to a family it did not test.
    scope: str

    def __post_init__(self):
        if self.state not in ("QUALIFIED", "NOT_QUALIFIED"):
            raise QualificationRegistryError(
                f"state must be QUALIFIED or NOT_QUALIFIED, got "
                f"{self.state!r}")
        if not self.evidence:
            raise QualificationRegistryError(
                f"profile {self.profile_id!r} has no qualification evidence: "
                "a qualification claim without durable evidence is exactly "
                "what this registry exists to prevent")

    @property
    def is_qualified(self) -> bool:
        return self.state == "QUALIFIED"


#: profile id -> qualification record. THE qualification authority.
QUALIFICATION: dict[str, QualificationRecord] = {
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_MESH_DOR_XY_V1",
        state="QUALIFIED",
        semantics_version=SEALED_SEMANTICS_VERSION,
        evidence=(
            "veritx_dse.backend.booksim_projection:qualify_native_mesh_dor",
            "docs/product/EVIDENCE-FIRST-CAPABILITY-ARCHAEOLOGY.md",
        ),
        scope="MaterializedFamily.MESH, seat_capacity 1, square k x k, "
              "routing class DOR_XY",
    ),
    "CERTIFIED_BOOKSIM_ANYNET_V1": QualificationRecord(
        profile_id="CERTIFIED_BOOKSIM_ANYNET_V1",
        state="QUALIFIED",
        semantics_version=SEALED_SEMANTICS_VERSION,
        evidence=(
            "veritx_dse.backend.booksim_projection:qualify_anynet_min_hops",
            "docs/product/BAKE-OFF-REPRODUCIBILITY.md",
        ),
        scope="explicit graph, routing class ANYNET_MIN_HOPS",
    ),
}


def qualification_of(profile_id: str) -> QualificationRecord:
    """Look up a profile's qualification. An UNREGISTERED profile is
    NOT_QUALIFIED by construction — never qualified by omission."""
    record = QUALIFICATION.get(profile_id)
    if record is not None:
        return record
    return QualificationRecord(
        profile_id=profile_id,
        state="NOT_QUALIFIED",
        semantics_version=-1,
        evidence=(
            "unregistered: no qualification record exists for this profile",
        ),
        scope="none",
    )


#: profile id -> the execution implementation that runs a prepared input.
#: THE execution authority. An entry here means a real code path exists; it
#: does NOT mean a probe was executed during the capability gate.
EXECUTION_HANDLERS: dict[str, str] = {
    "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
    "CERTIFIED_BOOKSIM_ANYNET_V1":
        "veritx_dse.backend.booksim_execution:execute_prepared_booksim",
}


def execution_handler_for(profile_id: str) -> str | None:
    """The dotted path of the execution implementation, or None.

    `None` means NO execution implementation is registered — which is a
    different fact from "execution was not attempted".
    """
    return EXECUTION_HANDLERS.get(profile_id)


def resolve_handler(dotted: str) -> Callable[..., Any]:
    """Import the named implementation, so a registry entry cannot be a
    typo that silently means 'executable'."""
    import importlib
    module_name, _, attr = dotted.partition(":")
    if not module_name or not attr:
        raise QualificationRegistryError(
            f"execution handler {dotted!r} is not 'module:attribute'")
    try:
        module = importlib.import_module(module_name)
    except ImportError as e:
        raise QualificationRegistryError(
            f"execution handler module {module_name!r} does not import: {e}"
        ) from e
    handler = getattr(module, attr, None)
    if handler is None:
        raise QualificationRegistryError(
            f"execution handler {dotted!r} does not exist")
    return handler


__all__ = [
    "QualificationRecord", "QualificationRegistryError", "QUALIFICATION",
    "EXECUTION_HANDLERS", "SEALED_SEMANTICS_VERSION", "qualification_of",
    "execution_handler_for", "resolve_handler",
]
