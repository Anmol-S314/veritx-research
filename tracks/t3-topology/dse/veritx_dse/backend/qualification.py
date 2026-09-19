"""veritx_dse.backend.qualification — cross-backend semantic qualification
(B3.8b, hardened in B3.8e).

Two DIFFERENT claims are computed and never conflated:

    AUTHORITY AGREEMENT
        Two targets claim EXACT/DERIVED_EXACT for a dimension and bind
        the SAME authoritative source identity, the same representation
        status and the same supported domain. This proves they consulted
        one authority; it does NOT by itself prove their encodings agree.

    PROJECTION EQUIVALENCE
        For targets that share one canonical lowerer
        (BOOKSIM_STANDALONE vs SERVING_BOOKSIM2), the fabric-derived
        backend parameters must be byte-equal after projecting out
        target-specific execution fields. This is the stronger claim and
        is checked mechanically.

The module deliberately does NOT compare raw backend config hashes across
targets (they should differ) and does NOT impose latency equality across
heterogeneous backend families.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from .booksim_profile import BOOKSIM_SERVING_PROFILE, \
    BOOKSIM_STANDALONE_PROFILE
from .contracts import (
    BackendConfigArtifact, BackendTarget, RepresentationStatus,
    SemanticDimension,
)

_EXACT = frozenset({RepresentationStatus.EXACT,
                    RepresentationStatus.DERIVED_EXACT})

_PROJECTION_ONLY_KEYS = frozenset({"routing_class",
                                   "channel_latency_cycles"})


class QualificationError(ValueError):
    """A cross-backend semantic claim is inconsistent — fail closed."""


@dataclass(frozen=True)
class SharedAuthorityClaim:
    """One dimension claimed exact by >=2 targets from one authority.

    ``source_identity``, ``status`` and ``supported_domain`` must all
    agree across the claimant targets; the domain is what keeps an EXACT
    cell from over-claiming arbitrary semantics.
    """

    dimension: SemanticDimension
    source_identity: str
    status: str
    supported_domain: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class UnsupportedRow:
    dimension: SemanticDimension
    target: str
    status: str
    effect: str
    reason: str
    supported_domain: str


@dataclass(frozen=True)
class ProjectionComparison:
    target_a: str
    target_b: str
    equivalent: bool
    differences: tuple[tuple[str, Any, Any], ...]


@dataclass(frozen=True)
class QualificationReport:
    targets: tuple[str, ...]
    authorities: tuple[SharedAuthorityClaim, ...]
    disagreements: tuple[UnsupportedRow, ...]
    projections: tuple[ProjectionComparison, ...]
    fabric_hash: str
    resolved_fabric_hash: str
    config_hashes: tuple[tuple[str, str], ...]

    @property
    def shared_authority_dimensions(self) -> frozenset[str]:
        return frozenset(c.dimension.value for c in self.authorities)

    def projection_for(self, a: str,
                       b: str) -> ProjectionComparison | None:
        for row in self.projections:
            if {row.target_a, row.target_b} == {a, b}:
                return row
        return None


# ── canonical BookSim semantic projection ───────────────────────────────

def booksim_semantic_projection(
        artifact: BackendConfigArtifact) -> dict[str, Any]:
    """Fabric-derived parameters shared by standalone and serving BookSim.

    Excludes target-specific execution fields (traffic/workload source,
    sample period, seed policy, route-dump path, serving invocation-only
    values). Raises when the artifact is not a BookSim target.
    """
    if artifact.backend_target not in (BackendTarget.BOOKSIM_STANDALONE,
                                       BackendTarget.SERVING_BOOKSIM2):
        raise QualificationError(
            f"{artifact.backend_target.value} is not a BookSim target")
    profile = (BOOKSIM_SERVING_PROFILE
               if artifact.backend_target is BackendTarget.SERVING_BOOKSIM2
               else BOOKSIM_STANDALONE_PROFILE)
    owners = profile.ownership()
    projection: dict[str, Any] = {}
    for key, value in artifact.normalized_parameters:
        if key in _PROJECTION_ONLY_KEYS:
            projection[key] = value
            continue
        if owners.get(key) is not None and \
                owners[key].value == "FABRIC_DERIVED":
            projection[key] = value
    return projection


def compare_booksim_projections(
        a: BackendConfigArtifact, b: BackendConfigArtifact
) -> ProjectionComparison:
    pa, pb = booksim_semantic_projection(a), booksim_semantic_projection(b)
    differences = tuple(
        (key, pa.get(key), pb.get(key))
        for key in sorted(set(pa) | set(pb))
        if pa.get(key) != pb.get(key))
    return ProjectionComparison(
        target_a=a.backend_target.value, target_b=b.backend_target.value,
        equivalent=not differences, differences=differences)


# ── the qualifier ───────────────────────────────────────────────────────

def qualify_cross_backend(
        artifacts: Mapping[str, BackendConfigArtifact],
) -> QualificationReport:
    if len(artifacts) < 2:
        raise QualificationError("need at least two target artifacts")
    problems: list[str] = []
    fabric_hashes = {a.fabric_hash for a in artifacts.values()}
    resolved_hashes = {a.resolved_fabric_hash for a in artifacts.values()}
    if len(fabric_hashes) != 1:
        problems.append(
            f"targets disagree on fabric_hash: {sorted(fabric_hashes)}")
    if len(resolved_hashes) != 1:
        problems.append(
            f"targets disagree on resolved_fabric_hash: "
            f"{sorted(resolved_hashes)}")

    # Authority agreement: (status, domain, source) must match per target.
    by_dim: dict[SemanticDimension, dict[str, tuple[Any, ...]]] = {}
    unsupported: list[UnsupportedRow] = []
    for name, art in artifacts.items():
        for row in art.semantic_bindings:
            if row.representation_status in _EXACT:
                by_dim.setdefault(row.dimension, {})[name] = (
                    row.representation_status, row.supported_domain,
                    row.source_identity)
            else:
                unsupported.append(UnsupportedRow(
                    dimension=row.dimension, target=name,
                    status=row.representation_status.value,
                    effect=row.certification_effect.value,
                    reason=row.reason,
                    supported_domain=row.supported_domain))

    authorities: list[SharedAuthorityClaim] = []
    for dim, claims in sorted(by_dim.items(),
                              key=lambda kv: list(SemanticDimension)
                              .index(kv[0])):
        if len(claims) < 2:
            continue
        signatures = {sig for sig in claims.values()}
        if len(signatures) != 1:
            problems.append(
                f"{dim.value}: targets claim EXACT with incompatible "
                f"authority/status/domain {claims}")
            continue
        status, domain, source = next(iter(signatures))
        if not domain:
            problems.append(
                f"{dim.value}: shared EXACT authority without a "
                "supported_domain")
            continue
        authorities.append(SharedAuthorityClaim(
            dimension=dim, source_identity=source,
            status=status.value, supported_domain=domain,
            targets=tuple(sorted(claims))))

    # Projection equivalence for target pairs sharing the canonical
    # BookSim lowerer.
    book_targets = {name: art for name, art in artifacts.items() if
                    art.backend_target in (BackendTarget.BOOKSIM_STANDALONE,
                                           BackendTarget.SERVING_BOOKSIM2)}
    projections: list[ProjectionComparison] = []
    book_names = sorted(book_targets)
    for i, a_name in enumerate(book_names):
        for b_name in book_names[i + 1:]:
            cmp = compare_booksim_projections(book_targets[a_name],
                                              book_targets[b_name])
            projections.append(cmp)
            if not cmp.equivalent:
                problems.append(
                    f"{a_name} vs {b_name}: fabric-derived projection "
                    f"differs: {cmp.differences[:5]}")

    if problems:
        raise QualificationError("; ".join(problems))

    config_hashes = tuple(sorted(
        (name, art.backend_config_hash())
        for name, art in artifacts.items()))
    if len({h for _n, h in config_hashes}) != len(config_hashes):
        raise QualificationError(
            "different targets produced the same backend_config_hash; "
            "target identity must be part of the projection")

    return QualificationReport(
        targets=tuple(sorted(artifacts)),
        authorities=tuple(authorities),
        disagreements=tuple(unsupported),
        projections=tuple(projections),
        fabric_hash=next(iter(fabric_hashes)),
        resolved_fabric_hash=next(iter(resolved_hashes)),
        config_hashes=config_hashes,
    )


__all__ = [
    "ProjectionComparison",
    "QualificationError",
    "QualificationReport",
    "SharedAuthorityClaim",
    "UnsupportedRow",
    "booksim_semantic_projection",
    "compare_booksim_projections",
    "qualify_cross_backend",
]
