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

from .booksim import assert_canonical_booksim_projection
from .booksim_profile import BOOKSIM_SERVING_PROFILE, \
    BOOKSIM_STANDALONE_PROFILE
from .bundle import ResolvedFabricBundle
from .contracts import (
    BackendConfigArtifact, BackendTarget, RepresentationStatus,
    SemanticDimension,
)

_EXACT = frozenset({RepresentationStatus.EXACT,
                    RepresentationStatus.DERIVED_EXACT})

# Fields allowed to differ between the two BookSim targets, with the
# reason they are execution/workload-specific rather than realization
# semantics. Closed list: a new target override must be added here
# explicitly after review, or realization comparison will refuse it.
TARGET_SPECIFIC_EXCLUSIONS: dict[str, str] = {
    "traffic": "workload/traffic-pattern source: standalone renders "
               "trace(<logical>); serving renders the uniform placeholder "
               "(embedded traffic is injected by sim_send)",
    "sample_period": "workload-derived sampling window (standalone = "
                     "trace span + margin; serving = fixed profile pin)",
    "seed": "per-run execution input (explicit or pinned); its policy "
            "lives in the BackendInputManifest, not the realization",
    "routing_dump_file": "evidence/diagnostic output path; cannot affect "
                         "routing, buffering or timing",
}

_PROJECTION_ONLY_KEYS = frozenset({"routing_class",
                                   "channel_latency_cycles"})


def _assert_exclusions_are_audited() -> None:
    for name in TARGET_SPECIFIC_EXCLUSIONS:
        for profile in (BOOKSIM_STANDALONE_PROFILE,
                        BOOKSIM_SERVING_PROFILE):
            if name not in profile.active_names():
                raise QualificationError(
                    f"target-specific exclusion {name!r} is not an active "
                    f"field of {profile.profile_id}")


_assert_exclusions_are_audited()


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
class RealizationComparison:
    target_a: str
    target_b: str
    equivalent: bool
    differences: tuple[tuple[str, Any, Any], ...]


@dataclass(frozen=True)
class QualificationReport:
    targets: tuple[str, ...]
    authorities: tuple[SharedAuthorityClaim, ...]
    disagreements: tuple[UnsupportedRow, ...]
    realizations: tuple[RealizationComparison, ...]
    fabric_hash: str
    resolved_fabric_hash: str
    config_hashes: tuple[tuple[str, str], ...]

    @property
    def shared_authority_dimensions(self) -> frozenset[str]:
        return frozenset(c.dimension.value for c in self.authorities)

    def realization_for(self, a: str,
                        b: str) -> RealizationComparison | None:
        for row in self.realizations:
            if {row.target_a, row.target_b} == {a, b}:
                return row
        return None


# ── BookSim shared realization ──────────────────────────────────────────

def booksim_shared_realization(
        artifact: BackendConfigArtifact) -> dict[str, Any]:
    """Every shared result-affecting BookSim configuration parameter.

    Starts from the artifact's full normalized projection (which includes
    the explicit BACKEND_PROFILE pins, not only fabric-derived values) and
    removes only the closed, reviewed target-specific executions:
    traffic source, sample window, seed, and the route-dump evidence path.
    Anything that can change routing, buffering, arbitration, flow
    control, pipeline timing, channel behavior or packet handling stays
    in the comparison.
    """
    if artifact.backend_target not in (BackendTarget.BOOKSIM_STANDALONE,
                                       BackendTarget.SERVING_BOOKSIM2):
        raise QualificationError(
            f"{artifact.backend_target.value} is not a BookSim target")
    realization: dict[str, Any] = {}
    for key, value in artifact.normalized_parameters:
        if key in TARGET_SPECIFIC_EXCLUSIONS:
            continue
        realization[key] = value
    for key in _PROJECTION_ONLY_KEYS:
        value = dict(artifact.normalized_parameters).get(key)
        if value is not None:
            realization[key] = value
    return realization


def compare_booksim_realizations(
        a: BackendConfigArtifact, b: BackendConfigArtifact
) -> RealizationComparison:
    ra, rb = booksim_shared_realization(a), booksim_shared_realization(b)
    differences = tuple(
        (key, ra.get(key), rb.get(key))
        for key in sorted(set(ra) | set(rb))
        if ra.get(key) != rb.get(key))
    return RealizationComparison(
        target_a=a.backend_target.value, target_b=b.backend_target.value,
        equivalent=not differences, differences=differences)


# ── the qualifier ───────────────────────────────────────────────────────

def qualify_cross_backend(
        bundle: ResolvedFabricBundle,
        artifacts: Mapping[str, BackendConfigArtifact],
) -> QualificationReport:
    """Qualify targets against the authoritative bundle context.

    Canonical lowering is checked FIRST for every BookSim target: an
    artifact that recomputed its own hash but is not the canonical
    lowering of ``bundle`` is refused before authority or realization
    comparison, so two equally forged artifacts cannot agree their way
    to validity. Analytical canonical re-lowering is out of scope (no
    graph authority exists); their identity checks are structural only.
    """
    if len(artifacts) < 2:
        raise QualificationError("need at least two target artifacts")
    # Target identity is authoritative from the artifact; caller labels are
    # display aliases and must agree. Duplicate target artifacts under
    # different aliases are refused.
    seen_targets: list[str] = []
    for name, art in artifacts.items():
        actual = art.backend_target.value
        if name != actual:
            raise QualificationError(
                f"mapping label {name!r} does not match artifact "
                f"backend_target {actual!r}")
        seen_targets.append(actual)
    if len(set(seen_targets)) != len(seen_targets):
        raise QualificationError(
            f"duplicate backend targets in qualification input: "
            f"{sorted(seen_targets)}")
    for name, art in artifacts.items():
        if art.backend_target in (BackendTarget.BOOKSIM_STANDALONE,
                                  BackendTarget.SERVING_BOOKSIM2):
            try:
                assert_canonical_booksim_projection(bundle, art)
            except ValueError as exc:
                raise QualificationError(
                    f"{name}: artifact is not the canonical lowering of "
                    f"the supplied bundle: {exc}") from exc
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

    # Shared realization for target pairs sharing the canonical BookSim
    # lowerer: every result-affecting parameter except the closed
    # target-specific exclusion list.
    book_targets = {name: art for name, art in artifacts.items() if
                    art.backend_target in (BackendTarget.BOOKSIM_STANDALONE,
                                           BackendTarget.SERVING_BOOKSIM2)}
    realizations: list[RealizationComparison] = []
    book_names = sorted(book_targets)
    for i, a_name in enumerate(book_names):
        for b_name in book_names[i + 1:]:
            cmp = compare_booksim_realizations(book_targets[a_name],
                                               book_targets[b_name])
            realizations.append(cmp)
            if not cmp.equivalent:
                problems.append(
                    f"{a_name} vs {b_name}: shared BookSim realization "
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
        realizations=tuple(realizations),
        fabric_hash=next(iter(fabric_hashes)),
        resolved_fabric_hash=next(iter(resolved_hashes)),
        config_hashes=config_hashes,
    )


__all__ = [
    "QualificationError",
    "QualificationReport",
    "RealizationComparison",
    "SharedAuthorityClaim",
    "TARGET_SPECIFIC_EXCLUSIONS",
    "UnsupportedRow",
    "booksim_shared_realization",
    "compare_booksim_realizations",
    "qualify_cross_backend",
]
