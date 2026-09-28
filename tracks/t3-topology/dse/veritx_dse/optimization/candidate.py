"""veritx_dse.optimization.candidate — Candidate = base + GUIDED patch.

A candidate is NEVER an anonymous hardware dict: it is a base
CompileRequest identity plus a GUIDED patch that re-emits a full
candidate CompileRequest. LOCKED properties have no patch key (see
definition.GUIDED_PARAMS); they recompile via FabricCompiler.

Identity: candidate_id = H(base_design_hash, canonical patch), so
execution order never changes candidate identity. Patch key order and
domain declaration order are non-semantic.

Provenance: the base+patch authority shape REPLAYS synthesis/compiler.py
(candidates arrive from the caller, never synthesized inside the
evaluator) and wave-f space.py candidate_identity
(H(design_space_id, assignment, intent ids)); the patching seam is the
product CompileRequest dataclasses.replace on NocConfig (NOT Wave-F's
fabric_overrides intent patching — SUPERSEDED, see CAPABILITY-LEDGER.md).
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

from veritx_dse.core.artifact import content_id
from veritx_dse.core.spec import canonical_json

from .definition import GUIDED_PARAMS, _normalize_param_name
from veritx_dse.model.generation import is_any_compile_request  # noqa: E402

CANDIDATE_DOMAIN = "veritx/optimization-candidate/v1"


class CandidateError(ValueError):
    """Invalid candidate patch or construction (fail-closed)."""


def normalize_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Normalize user patch keys to short GUIDED names, fail-closed."""
    if not isinstance(patch, dict):
        raise CandidateError(
            f"patch must be a dict, got {type(patch).__name__}")
    out: dict[str, Any] = {}
    for key, value in patch.items():
        short = _normalize_param_name(key)
        if short not in GUIDED_PARAMS:
            raise CandidateError(
                f"patch key {key!r} is not a GUIDED knob "
                f"(supported: {sorted(GUIDED_PARAMS)}); LOCKED properties "
                "cannot be patched — they recompile via FabricCompiler")
        if short in out and out[short] != value:
            raise CandidateError(
                f"patch sets {short!r} twice with different values")
        out[short] = value
    return out


def candidate_id_for(base_design_hash: str, patch: dict[str, Any]) -> str:
    """Full content identity of a candidate: H(base hash, canonical patch).

    The digest is used IN FULL: a truncated hash is not an identity. A
    display layer may shorten ``cand_<64 hex>`` for presentation, but the
    scientific identity is the whole digest.
    """
    norm = normalize_patch(patch)
    return "cand_" + content_id(CANDIDATE_DOMAIN, {
        "base_design_hash": base_design_hash,
        "patch": {k: norm[k] for k in sorted(norm)},
    })


def apply_patch(base: Any, patch: dict[str, Any]) -> Any:
    """Re-emit a candidate CompileRequest from base + GUIDED patch.

    Only NocConfig GUIDED fields are patched (dataclasses.replace, so
    the base request is never mutated). Unknown/LOCKED keys raise.
    NocConfig's own __post_init__ validates value types.
    """
    from veritx_dse.model.compile_model import (
        CompileRequest,
        CompileRequestV3,
    )
    # Integration: v3 bases patch through the identical replace path
    # (same NocConfig class, same frozen-replace mechanics); v2 flow
    # is byte-identical — only the gate widens, nothing else branches.
    if not is_any_compile_request(base):
        raise CandidateError(
            f"base must be a CompileRequest or CompileRequestV3, got "
            f"{type(base).__name__}")
    norm = normalize_patch(patch)
    if not norm:
        raise CandidateError("patch must set at least one GUIDED knob")
    noc_updates: dict[str, Any] = {}
    for key, value in norm.items():
        if key == "topology_family" and isinstance(value, str):
            from veritx_dse.model.compile_model import TopologyFamily
            try:
                value = TopologyFamily(value)
            except ValueError:
                raise CandidateError(
                    f"unknown topology_family {value!r}") from None
        noc_updates[key] = value
    try:
        new_noc = dataclasses.replace(base.noc_config, **noc_updates)
    except TypeError as exc:
        raise CandidateError(f"cannot apply patch {norm!r}: {exc}") from exc
    return dataclasses.replace(base, noc_config=new_noc)


@dataclass(frozen=True)
class Candidate:
    """One search candidate: base identity + GUIDED patch + request.

    candidate_id is fixed at construction from (base hash, patch);
    execution order never changes it (the optimizer re-derives and
    asserts this).
    """
    candidate_id: str
    base_design_hash: str
    guided_patch: dict[str, Any]
    request: Any

    def __post_init__(self):
        norm = normalize_patch(dict(self.guided_patch))
        object.__setattr__(self, "guided_patch",
                           {k: norm[k] for k in sorted(norm)})
        expected = candidate_id_for(self.base_design_hash, norm)
        if self.candidate_id != expected:
            raise CandidateError(
                f"candidate_id {self.candidate_id!r} != content identity "
                f"{expected!r} for this base+patch — refusing transplanted id")


def make_candidate(base: Any, patch: dict[str, Any]) -> Candidate:
    """Build a Candidate from a base request and a GUIDED patch."""
    base_hash = base.design_hash()
    norm = normalize_patch(patch)
    request = apply_patch(base, norm)
    return Candidate(
        candidate_id=candidate_id_for(base_hash, norm),
        base_design_hash=base_hash,
        guided_patch=norm,
        request=request,
    )


# ── study patches: fabric + workload parallelism + placement (additive) ──
#
# GUIDED apply_patch is untouched. Study patches extend the same
# base+patch authority to workload parallelism sizes (patched onto
# base.workload) and placement policy (resolved through canonical
# mapping constructors, never JSON). Dead knobs and LOCKED properties
# refuse with reasons at normalization.

STUDY_CANDIDATE_DOMAIN = "veritx/study-candidate/v1"


def normalize_study_patch(patch: dict[str, Any]) -> dict[str, Any]:
    """Normalize study patch keys to short names, fail-closed."""
    from .definition import (
        DEAD_KNOBS,
        PARALLELISM_DIMS,
        PLACEMENT_DIM,
        SEARCHABLE_FABRIC_PARAMS,
        _LOCKED_TOKENS,
        _normalize_param_name,
    )
    if not isinstance(patch, dict):
        raise CandidateError(
            f"study patch must be a dict, got {type(patch).__name__}")
    out: dict[str, Any] = {}
    for key, value in patch.items():
        short = _normalize_param_name(key)
        squashed = short.lower().replace("_", "")
        for tok in _LOCKED_TOKENS:
            if tok in squashed:
                raise CandidateError(
                    f"study patch key {key!r} names a LOCKED property "
                    f"({tok}): VC count/map, routing, turn restrictions "
                    "and escape VCs recompile via FabricCompiler")
        if short in DEAD_KNOBS:
            raise CandidateError(
                f"study patch key {key!r} refused: {DEAD_KNOBS[short]}")
        if short in PARALLELISM_DIMS or short == PLACEMENT_DIM \
                or short in SEARCHABLE_FABRIC_PARAMS:
            if short in out and out[short] != value:
                raise CandidateError(
                    f"study patch sets {short!r} twice with different values")
            out[short] = value
            continue
        raise CandidateError(
            f"study patch key {key!r} is not a searchable dimension; "
            "searchable fabric: "
            f"{sorted(SEARCHABLE_FABRIC_PARAMS)}, workload: "
            f"{list(PARALLELISM_DIMS)}, placement: [{PLACEMENT_DIM}]")
    return out


def study_candidate_id_for(base_design_hash: str,
                           patch: dict[str, Any]) -> str:
    """Study candidate identity: H(base hash, canonical study patch)."""
    norm = normalize_study_patch(patch)
    return "scand_" + content_id(STUDY_CANDIDATE_DOMAIN, {
        "base_design_hash": base_design_hash,
        "patch": {k: norm[k] for k in sorted(norm)},
    })


def apply_study_patch(base: Any, patch: dict[str, Any]) -> Any:
    """Re-emit a candidate CompileRequest from base + study patch.

    Fabric keys replace NocConfig fields, tp/pp/ep/dp replace workload
    fields (both via dataclasses.replace: the base is never mutated).
    The placement key carries a policy name only — mapping resolves
    through resolve_study_mapping. Empty patches and unknown/LOCKED/dead
    keys raise.
    """
    from .definition import (
        PARALLELISM_DIMS,
        PLACEMENT_DIM,
        SEARCHABLE_FABRIC_PARAMS,
    )
    if not is_any_compile_request(base):
        raise CandidateError(
            f"base must be a CompileRequest or CompileRequestV3, got "
            f"{type(base).__name__}")
    norm = normalize_study_patch(patch)
    if not norm:
        raise CandidateError("study patch must set at least one dimension")
    request = base
    noc_updates: dict[str, Any] = {}
    for key, value in norm.items():
        if key in SEARCHABLE_FABRIC_PARAMS:
            if key == "topology_family" and isinstance(value, str):
                from veritx_dse.model.compile_model import TopologyFamily
                try:
                    value = TopologyFamily(value)
                except ValueError:
                    raise CandidateError(
                        f"unknown topology_family {value!r}") from None
            noc_updates[key] = value
    if noc_updates:
        try:
            new_noc = dataclasses.replace(base.noc_config, **noc_updates)
        except TypeError as exc:
            raise CandidateError(
                f"cannot apply fabric patch: {exc}") from exc
        request = dataclasses.replace(request, noc_config=new_noc)
    wl_updates = {k: v for k, v in norm.items() if k in PARALLELISM_DIMS}
    if wl_updates:
        if not all(hasattr(request.workload, k) for k in wl_updates):
            raise CandidateError(
                "base workload has no parallelism fields; cannot patch "
                f"{sorted(wl_updates)}")
        try:
            new_wl = dataclasses.replace(request.workload, **wl_updates)
        except TypeError as exc:
            raise CandidateError(
                f"cannot apply parallelism patch: {exc}") from exc
        request = dataclasses.replace(request, workload=new_wl)
    return request


def study_placement_policy(patch: dict[str, Any]) -> str | None:
    """Placement policy named by a study patch (None = canonical default)."""
    from .definition import PLACEMENT_DIM
    norm = normalize_study_patch(patch)
    policy = norm.get(PLACEMENT_DIM)
    if policy is None:
        return None
    if not isinstance(policy, str):
        raise CandidateError(
            f"placement policy must be a name, got {policy!r}")
    return policy


def resolve_study_mapping(request: Any, policy: str | None) -> Any:
    """Resolve a MappingArtifact through a canonical constructor.

    None (or "rank_order") resolves via the canonical derive_mapping.
    Any other policy refuses: no canonical constructor exists, and an
    invented mapping would be an arbitrary JSON patch — exactly what
    this dimension exists to prevent.
    """
    from .definition import PLACEMENT_POLICIES
    if policy is None:
        policy = "rank_order"
    if policy not in PLACEMENT_POLICIES:
        raise CandidateError(
            f"placement policy {policy!r} has no canonical constructor; "
            f"qualified: {list(PLACEMENT_POLICIES)}")
    from veritx_dse.model.mapping import derive_mapping
    return derive_mapping(request)


@dataclass(frozen=True)
class StudyCandidate:
    """One study candidate: base identity + namespaced patch + request.

    candidate_id is fixed at construction from (base hash, patch);
    mapping_hash is a derived fact (deterministic of the request), not
    identity. A candidate carries no certificate, measurement, or Pareto
    status.
    """
    candidate_id: str
    base_design_hash: str
    study_patch: dict[str, Any]
    request: Any
    mapping_hash: str | None
    placement_policy: str | None

    def __post_init__(self):
        norm = normalize_study_patch(dict(self.study_patch))
        object.__setattr__(self, "study_patch",
                           {k: norm[k] for k in sorted(norm)})
        expected = study_candidate_id_for(self.base_design_hash, norm)
        if self.candidate_id != expected:
            raise CandidateError(
                f"candidate_id {self.candidate_id!r} != content identity "
                f"{expected!r} — refusing transplanted id")


def make_study_candidate(base: Any, patch: dict[str, Any]) -> StudyCandidate:
    """Build a StudyCandidate; mapping feasibility is canonical.

    The placement policy (explicit or default) resolves through the
    canonical mapping constructor; a MappingError (e.g. parallelism
    growth beyond compute instances) makes the candidate INVALID — a
    build-time refusal by canonical authority, never a guess.
    """
    from veritx_dse.model.mapping import MappingError
    base_hash = base.design_hash()
    norm = normalize_study_patch(patch)
    request = apply_study_patch(base, norm)
    policy = study_placement_policy(norm)
    try:
        mapping = resolve_study_mapping(request, policy)
    except MappingError as exc:
        raise CandidateError(f"mapping infeasible: {exc}") from exc
    return StudyCandidate(
        candidate_id=study_candidate_id_for(base_hash, norm),
        base_design_hash=base_hash,
        study_patch=norm,
        request=request,
        mapping_hash=mapping.mapping_hash(),
        placement_policy=policy or "rank_order",
    )


__all__ = [
    "CANDIDATE_DOMAIN", "Candidate", "CandidateError", "apply_patch",
    "candidate_id_for", "make_candidate", "normalize_patch",
    "STUDY_CANDIDATE_DOMAIN", "StudyCandidate", "normalize_study_patch",
    "study_candidate_id_for", "apply_study_patch",
    "study_placement_policy", "resolve_study_mapping",
    "make_study_candidate",
]
