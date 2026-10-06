"""veritx_dse.application.value_provenance — every scientific value answers
for itself.

Why this module exists
----------------------
The reference product shows engineering values with no way to ask where they
came from. A link width, a routing algorithm, a latency, a clock frequency and
a technology node all render identically, so a reader cannot tell an authored
intent from a compiler derivation from a measured result from a declaration.

This module is the single vocabulary for that answer. It exists because the
alternative — each view inventing its own labels — is how a UI starts calling
declared values measured.

The distinction the vocabulary enforces
---------------------------------------
``AUTHORED``   a human wrote it into the draft; it is intent.
``DERIVED``    the compiler computed it from intent and certified it.
``DECLARED``   someone asserted it and nothing verified it — a target
               technology, a frequency, a bandwidth floor.
``MEASURED``   a backend executed and produced it, under a qualification.

A ``MEASURED`` value is the only one that may be called a result, and it must
carry the run and evidence that produced it. A ``DECLARED`` value may never be
rendered with a pass/fail colour, because nothing evaluated it.

Freshness is a SEPARATE axis from origin. A ``MEASURED`` value can be
``STALE``: it was real, measured against revision r07, and the draft has since
moved to r08. Staleness never rewrites the origin and never invalidates the
measurement — it says the measurement answers a question the user is no longer
asking. That is why this module keeps ``freshness`` independent.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# The four origins. Deliberately exactly four, and deliberately not a synonym
# set: every additional label is a place for two views to disagree.
ORIGINS: tuple[str, ...] = ("AUTHORED", "DERIVED", "DECLARED", "MEASURED")

# Independent of origin. A value is either answering the current question or
# answering a superseded one.
FRESHNESS: tuple[str, ...] = ("CURRENT", "STALE", "FOREIGN_REVISION")

# What kind of artifact a value came from. This is what makes a value
# navigable: it names the thing to open.
_ARTIFACT_KINDS: tuple[str, ...] = (
    "draft",            # the working design intent
    "topology",         # TopologyArtifact
    "attachment",       # AgentAttachmentArtifact
    "route",            # RouteArtifact
    "vc_assignment",    # the VC assignment carried in the compile result
    "certificate",      # a verification certificate
    "compile_result",   # the frozen compile-result groups
    "run",              # an evaluation run's own view
    "traffic_matrix",   # counted from an executed trace
    "evidence",         # the evidence bundle
    "backend",          # backend-declared facts (profiles, qualification)
    "capability",       # the capability registry
    "lowering",         # the workload-lowering schedule (intent_lowering domain)
)

# An origin is not a licence to render a verdict. This is the rule that keeps a
# declared technology node from being painted green.
_MEASURE_ONLY: frozenset[str] = frozenset({"MEASURED"})

# Which origins can legitimately point at each artifact kind. A client that
# needs to trust a value's chain can check this without reading prose.
_ORIGIN_ARTIFACTS: dict[str, frozenset[str]] = {
    "AUTHORED": frozenset({"draft"}),
    # "capability" joins the derived set because the registry is produced by
    # RUNNING the compiler: capability_truth.derive_all_stages() invokes the
    # topology families, the profile selector and the execution handlers and
    # reports the authority string each stage returned. It was missing here, so
    # a capability could carry no origin at all and the UI had to badge it
    # "ORIGIN ?".
    # "lowering" joins the derived set because the schedule is produced by
    # the compiler's intent-lowering pass from the authored workload: same
    # authority as the compile result, but a distinct artifact with its own
    # read path (/api/v1/workloads/{id}/lowering), so it gets its own name.
    "DERIVED": frozenset({
        "topology", "attachment", "route", "vc_assignment",
        "certificate", "compile_result", "capability", "lowering"}),
    "DECLARED": frozenset({"draft", "backend"}),
    "MEASURED": frozenset({"run", "traffic_matrix", "evidence"}),
}


class ProvenanceError(ValueError):
    """A value's provenance is inconsistent with itself."""


@dataclass(frozen=True)
class ValueProvenance:
    """Where one displayed value came from, and whether it still applies.

    A ``MEASURED`` value without ``run_id`` is rejected at construction. That is
    the whole point of the type: it makes "a measured number with nothing
    behind it" unrepresentable rather than merely discouraged.
    """

    origin: str
    label: str
    unit: str | None = None
    revision_id: str | None = None
    artifact_kind: str | None = None
    artifact_ref: str | None = None
    backend: str | None = None
    run_id: str | None = None
    evidence_ref: str | None = None
    qualification: str | None = None
    freshness: str = "CURRENT"
    note: str | None = None

    def __post_init__(self) -> None:
        if self.origin not in ORIGINS:
            raise ProvenanceError(
                f"origin must be one of {ORIGINS}, got {self.origin!r}")
        if self.freshness not in FRESHNESS:
            raise ProvenanceError(
                f"freshness must be one of {FRESHNESS}, got {self.freshness!r}")
        if self.artifact_kind is not None \
                and self.artifact_kind not in _ARTIFACT_KINDS:
            raise ProvenanceError(
                f"artifact_kind must be one of {_ARTIFACT_KINDS}, "
                f"got {self.artifact_kind!r}")
        if self.origin == "MEASURED" and not self.run_id:
            raise ProvenanceError(
                f"{self.label!r} is MEASURED but carries no run_id. A measured "
                "value must name the run that produced it; without one it is "
                "not a measurement, it is a number someone typed.")
        if self.origin == "MEASURED" and self.run_id and not self.backend:
            raise ProvenanceError(
                f"{self.label!r} is MEASURED and names run {self.run_id!r} but "
                "no backend. The backend is what makes the run evidence.")
        if self.artifact_kind is not None and self.origin in _ORIGIN_ARTIFACTS \
                and self.artifact_kind not in _ORIGIN_ARTIFACTS[self.origin]:
            raise ProvenanceError(
                f"{self.label!r} is {self.origin} and cannot cite a "
                f"{self.artifact_kind!r} artifact; a {self.origin} value may "
                f"cite {sorted(_ORIGIN_ARTIFACTS[self.origin])}")
        if self.freshness != "CURRENT" and self.revision_id is None:
            raise ProvenanceError(
                f"{self.label!r} is {self.freshness} but names no revision. "
                "Staleness is a relation between a value and a revision; "
                "without the revision it is an opinion.")

    @property
    def is_result(self) -> bool:
        """Only a MEASURED value may be presented as a result."""
        return self.origin in _MEASURE_ONLY

    def as_dict(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "label": self.label,
            "unit": self.unit,
            "revision_id": self.revision_id,
            "artifact_kind": self.artifact_kind,
            "artifact_ref": self.artifact_ref,
            "backend": self.backend,
            "run_id": self.run_id,
            "evidence_ref": self.evidence_ref,
            "qualification": self.qualification,
            "freshness": self.freshness,
            "is_result": self.is_result,
            "note": self.note,
        }


def authored(label: str, *, unit: str | None = None,
             artifact_ref: str | None = None, **kw: Any) -> ValueProvenance:
    """Intent: a human wrote this into the draft."""
    return ValueProvenance(
        origin="AUTHORED", label=label, unit=unit,
        artifact_kind="draft", artifact_ref=artifact_ref, **kw)


def derived(label: str, *, artifact_kind: str, artifact_ref: str | None = None,
            revision_id: str | None = None, unit: str | None = None,
            **kw: Any) -> ValueProvenance:
    """The compiler computed and certified this."""
    return ValueProvenance(
        origin="DERIVED", label=label, unit=unit, revision_id=revision_id,
        artifact_kind=artifact_kind, artifact_ref=artifact_ref, **kw)


def declared(label: str, *, unit: str | None = None,
             artifact_ref: str | None = None, **kw: Any) -> ValueProvenance:
    """Asserted and unverified: a target node, a clock, a bandwidth floor."""
    return ValueProvenance(
        origin="DECLARED", label=label, unit=unit,
        artifact_kind="draft", artifact_ref=artifact_ref, **kw)


def measured(label: str, *, run_id: str, backend: str, unit: str | None = None,
             artifact_kind: str = "run", artifact_ref: str | None = None,
             revision_id: str | None = None, evidence_ref: str | None = None,
             qualification: str | None = None,
             freshness: str = "CURRENT", **kw: Any) -> ValueProvenance:
    """A backend executed and produced this."""
    return ValueProvenance(
        origin="MEASURED", label=label, unit=unit, revision_id=revision_id,
        artifact_kind=artifact_kind, artifact_ref=artifact_ref,
        backend=backend, run_id=run_id, evidence_ref=evidence_ref,
        qualification=qualification, freshness=freshness, **kw)


def staleness_for(run_revision_id: str | None,
                  current_revision_id: str | None,
                  *, draft_dirty: bool = False) -> str:
    """Freshness of a result against the design currently on screen.

    Three distinct answers, never collapsed:

    ``FOREIGN_REVISION``  the result belongs to a different compiled revision
                          than the one in view. It is a real result about a
                          different design.
    ``STALE``             same revision, but the draft has uncompiled changes,
                          so the on-screen intent is not what was measured.
    ``CURRENT``           the result answers the design in view.
    """
    if run_revision_id is None:
        return "CURRENT"
    if current_revision_id is not None and run_revision_id != current_revision_id:
        return "FOREIGN_REVISION"
    if draft_dirty:
        return "STALE"
    return "CURRENT"


STALENESS_MEANING: dict[str, str] = {
    "CURRENT": (
        "This result was produced from the design currently on screen."),
    "STALE": (
        "This result is real, but the draft has uncompiled changes. It "
        "describes the last compiled revision, not the edits now in the "
        "draft. The measurement is not wrong; it answers a superseded "
        "question."),
    "FOREIGN_REVISION": (
        "This result belongs to a different compiled revision than the one on "
        "screen. It is a valid measurement of that other design and must not "
        "be read as a measurement of this one."),
}


def provenance_registry() -> dict[str, Any]:
    """The vocabulary, served so a client renders labels from one source."""
    return {
        "schema_version": 1,
        "type": "srota/ValueProvenanceVocabulary",
        "origins": list(ORIGINS),
        "freshness": list(FRESHNESS),
        "artifact_kinds": list(_ARTIFACT_KINDS),
        "origin_meaning": {
            "AUTHORED": "intent written by a human into the draft",
            "DERIVED": "computed by the compiler from intent and certified",
            "DECLARED": "asserted and NOT verified: a target technology, a "
                        "frequency, a bandwidth floor",
            "MEASURED": "produced by an executed backend run under a "
                        "qualification profile",
        },
        "freshness_meaning": dict(STALENESS_MEANING),
        "origin_artifacts": {k: sorted(v) for k, v in _ORIGIN_ARTIFACTS.items()},
        "rule": (
            "Only MEASURED may be presented as a result. Only MEASURED may "
            "carry a pass/fail colour. A MEASURED value must name its run and "
            "backend or it is refused at construction. Freshness is "
            "independent of origin: a measurement can be real and still "
            "answer a superseded question."),
    }


__all__ = [
    "FRESHNESS",
    "ORIGINS",
    "STALENESS_MEANING",
    "ProvenanceError",
    "ValueProvenance",
    "authored",
    "declared",
    "derived",
    "measured",
    "provenance_registry",
    "staleness_for",
]