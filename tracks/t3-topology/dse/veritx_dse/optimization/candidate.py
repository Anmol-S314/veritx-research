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
    """Content identity of a candidate: H(base hash, canonical patch)."""
    norm = normalize_patch(patch)
    return "cand_" + content_id(CANDIDATE_DOMAIN, {
        "base_design_hash": base_design_hash,
        "patch": {k: norm[k] for k in sorted(norm)},
    })[:16]


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
    if not isinstance(base, (CompileRequest, CompileRequestV3)):
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


__all__ = [
    "CANDIDATE_DOMAIN", "Candidate", "CandidateError", "apply_patch",
    "candidate_id_for", "make_candidate", "normalize_patch",
]
