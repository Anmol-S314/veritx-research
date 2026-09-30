"""The evaluation-plan view — server truth for Studio, no derivation.

Rationale: docs/decisions/modules/application.md
"""
from __future__ import annotations

from typing import Any

from veritx_dse.application.evaluation_plan import EvaluationPlan
from veritx_dse.application.qualification_envelopes import (
    qualification_envelope,
)

EVALUATION_PLAN_CONTRACT_VERSION = 1

def evaluation_plan_view(
    plan: EvaluationPlan,
    *,
    revision_id: str | None,
    design_hash: str,
    resolved_fabric_hash: str,
    workload_id: str,
) -> dict[str, Any]:
    """Project one adjudicated plan. Every row carries its backend (or
    None when unrepresentable), fidelity (only when READY), the native
    qualification profile, the exact reason and the backend's declared
    limitations."""
    return {
        "contract_version": EVALUATION_PLAN_CONTRACT_VERSION,
        "revision_id": revision_id,
        "design_hash": _prefixed(design_hash),
        "resolved_fabric_hash": _prefixed(resolved_fabric_hash),
        "workload_id": workload_id,
        "analyses": [
            {
                "question": row.question.value,
                "backend": row.backend_id,
                "support": row.support.value,
                "readiness": row.readiness.value,
                "qualification": qualification_envelope(row.backend_id),
                "model_fidelity": (None if row.fidelity is None
                                   else row.fidelity.value),
                "qualification_profile": row.qualification_profile,
                "reason": row.reason,
                "limitations": list(row.limitations),
            }
            for row in plan.analyses
        ],
    }

def _prefixed(value: str) -> str:
    return value if value.startswith("sha256:") else "sha256:" + value

__all__ = [
    "EVALUATION_PLAN_CONTRACT_VERSION", "evaluation_plan_view",
]
