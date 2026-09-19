"""veritx_dse.backend.qualification — cross-backend semantic qualification
(B3.8b).

The rule this module enforces:

    whenever two backends claim to represent the same semantic dimension,
    they must bind to the same authoritative source identity; whenever a
    backend cannot represent a dimension, that disagreement must be
    mechanically visible as an explicit status/effect/reason.

It deliberately does NOT compare raw backend config hashes across targets
(they should differ) and does NOT impose latency equality between BookSim
and the analytical engines. It compares semantic bindings only.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from .contracts import (
    BackendConfigArtifact, CertificationEffect, RepresentationStatus,
    SemanticDimension,
)

_EXACT = frozenset({RepresentationStatus.EXACT,
                    RepresentationStatus.DERIVED_EXACT})


class QualificationError(ValueError):
    """A cross-backend semantic claim is inconsistent — fail closed."""


@dataclass(frozen=True)
class SharedExactClaim:
    dimension: SemanticDimension
    source_identity: str
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
class QualificationReport:
    targets: tuple[str, ...]
    shared_exact: tuple[SharedExactClaim, ...]
    disagreements: tuple[UnsupportedRow, ...]
    fabric_hash: str
    resolved_fabric_hash: str
    config_hashes: tuple[tuple[str, str], ...]

    @property
    def shared_exact_dimensions(self) -> frozenset[str]:
        return frozenset(c.dimension.value for c in self.shared_exact)


def qualify_cross_backend(
        artifacts: Mapping[str, BackendConfigArtifact],
        *,
        errors: list[str] | None = None,
) -> QualificationReport:
    """Compute the shared-exact / explicit-disagreement report.

    Raises QualificationError when two targets claim EXACT for the same
    dimension with different authoritative sources, or when artifacts do
    not share fabric identity.
    """
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

    by_dim: dict[SemanticDimension, dict[str, str]] = {}
    unsupported: list[UnsupportedRow] = []
    for name, art in artifacts.items():
        if art.fabric_hash != next(iter(fabric_hashes), None):
            problems.append(f"{name}: fabric_hash differs")
        for row in art.semantic_bindings:
            if row.representation_status in _EXACT:
                by_dim.setdefault(row.dimension, {})[name] = \
                    row.source_identity
            else:
                unsupported.append(UnsupportedRow(
                    dimension=row.dimension, target=name,
                    status=row.representation_status.value,
                    effect=row.certification_effect.value,
                    reason=row.reason,
                    supported_domain=row.supported_domain))

    shared: list[SharedExactClaim] = []
    for dim, sources in sorted(by_dim.items(),
                               key=lambda kv: list(SemanticDimension)
                               .index(kv[0])):
        if len(set(sources.values())) != 1:
            problems.append(
                f"{dim.value}: targets claim EXACT with different sources "
                f"{sources}")
            continue
        if len(sources) < 2:
            continue
        shared.append(SharedExactClaim(
            dimension=dim, source_identity=next(iter(sources.values())),
            targets=tuple(sorted(sources))))

    if problems:
        raise QualificationError("; ".join(problems))

    config_hashes = tuple(sorted(
        (name, art.backend_config_hash()) for name, art in
        artifacts.items()))
    if len({h for _n, h in config_hashes}) != len(config_hashes):
        raise QualificationError(
            "different targets produced the same backend_config_hash; "
            "target identity must be part of the projection")

    return QualificationReport(
        targets=tuple(sorted(artifacts)),
        shared_exact=tuple(shared),
        disagreements=tuple(unsupported),
        fabric_hash=next(iter(fabric_hashes)),
        resolved_fabric_hash=next(iter(resolved_hashes)),
        config_hashes=config_hashes,
    )


__all__ = [
    "QualificationError",
    "QualificationReport",
    "SharedExactClaim",
    "UnsupportedRow",
    "qualify_cross_backend",
]
