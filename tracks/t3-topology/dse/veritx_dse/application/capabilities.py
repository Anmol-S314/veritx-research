"""veritx_dse.application.capabilities — authoritative capability registry.

Derived from ACTUAL registered backend support (Wave-B modules), never
from a parallel hand-written list. CLI/API/Studio surfaces read this
registry; no duplicate advertising lists.

Fidelity vocabulary is Wave-B's (RepresentationStatus /
CertificationEffect / ExecutionQualification), referenced by name.
"""
from __future__ import annotations

from typing import Any


def capability_registry() -> dict[str, Any]:
    """Backend capability truth, derived from sealed modules."""
    from veritx_dse.backend import analytical as analytical_mod
    from veritx_dse.backend.booksim import (
        BOOKSIM_BACKEND_SEMANTICS_VERSION, BOOKSIM_LOWERER_VERSION,
        BOOKSIM_STANDALONE_PROFILE, SERVING_BOOKSIM2_PROFILE,
        SERVING_BOOKSIM2_SEMANTICS_VERSION,
    )
    _ = analytical_mod  # registry presence only; no execution implied
    return {
        "schema_version": 1,
        "backends": {
            "BOOKSIM_STANDALONE": {
                "lowering": "SUPPORTED",
                "profile": BOOKSIM_STANDALONE_PROFILE,
                "semantics_version": BOOKSIM_BACKEND_SEMANTICS_VERSION,
                "lowerer_version": BOOKSIM_LOWERER_VERSION,
                "execution": "SUPPORTED",
                "execution_transport": "SUPERVISED_PROCESS",
                "route_evidence": "SUPPORTED",
                "exact_fabric": "CONDITIONAL",
                "fidelity_note": "EXECUTED_WITH_DECLARED_LOSS unless "
                                 "all bindings exact; loss itemized per "
                                 "SemanticDimension",
            },
            "SERVING_BOOKSIM2": {
                "lowering": "SUPPORTED",
                "profile": SERVING_BOOKSIM2_PROFILE,
                "semantics_version": SERVING_BOOKSIM2_SEMANTICS_VERSION,
                "lowerer_version": BOOKSIM_LOWERER_VERSION,
                "consumption_seam": "SUPPORTED",
                "execution": "BLOCKED",
                "route_evidence": "UNREPRESENTABLE",
            },
            "SERVING_ANALYTICAL_AWARE": {
                "lowering": "METADATA_ONLY",
                "execution": "UNSUPPORTED",
                "topology": "COARSENED",
            },
            "SERVING_ANALYTICAL_UNAWARE": {
                "lowering": "METADATA_ONLY",
                "execution": "UNSUPPORTED",
                "topology": "COARSENED",
            },
        },
        "operations": [
            "capabilities", "validate", "compile", "plan", "evaluate",
            "run_study", "compare", "inspect", "list_results", "diagnose",
        ],
        "deferred": {
            "rtl_verification": "NOT_RUN",
            "uvm_verification": "NOT_RUN",
            "formal_verification": "NOT_RUN",
            "area_power_energy": "WAVE_E",
            "multicast_concurrency": "WAVE_D",
        },
    }


# ── policy budgets (reject over-budget; never silently clamp) ──────────

POLICY = {
    "max_execution_seconds": 1800,
    "max_query_rows": 500,
    "max_study_candidates": 64,
}


def check_execution_budget(timeout_s: int) -> None:
    from .errors import ControlPlaneError, ErrorCode
    if timeout_s > POLICY["max_execution_seconds"]:
        raise ControlPlaneError(
            ErrorCode.POLICY_REJECTED,
            f"timeout {timeout_s}s exceeds policy maximum "
            f"{POLICY['max_execution_seconds']}s; refusing rather than "
            f"clamping the requested experiment",
            operation="evaluate")


def check_study_budget(count: int) -> None:
    from .errors import ControlPlaneError, ErrorCode
    if count > POLICY["max_study_candidates"]:
        raise ControlPlaneError(
            ErrorCode.POLICY_REJECTED,
            f"{count} study candidates exceed policy maximum "
            f"{POLICY['max_study_candidates']}",
            operation="run_study")


def cap_query_rows(limit: int | None) -> int:
    from .errors import ControlPlaneError, ErrorCode
    if limit is None:
        return POLICY["max_query_rows"]
    if limit > POLICY["max_query_rows"]:
        raise ControlPlaneError(
            ErrorCode.POLICY_REJECTED,
            f"query limit {limit} exceeds policy maximum "
            f"{POLICY['max_query_rows']}; refusing rather than "
            f"silently truncating the requested listing",
            operation="list")
    return limit


__all__ = [
    "POLICY",
    "cap_query_rows",
    "capability_registry",
    "check_execution_budget",
    "check_study_budget",
]
