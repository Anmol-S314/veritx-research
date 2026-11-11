"""veritx_dse.model.ordering_vc — M2 Ordering & VC assignment (STAGE 1 §4.2).

Rationale: docs/design/mesh-stage1-schema-compiler-scope.md §4.2.
Frozen input struct in -> Verdict out. No ``CompileRequestV4``, no
``topology_intent`` in the imports (module-isolation contract, §8.3).

This module is the legality GATE in front of the single authority,
``derive_vc_assignment_v3`` (D4): desired VCs are validated against the
derived assignment BEFORE it is trusted. A ``traffic_class_vcs`` mismatch is
compile INVALID, never a silent override (the failure ``rtl_support``
exists to prevent).
"""
from __future__ import annotations

from dataclasses import dataclass

from veritx_dse.core.constants import PLANE_C_MAX_VC
from veritx_dse.model.agent_intent_v4 import TrafficClassVC
from veritx_dse.model.compile_model import DependencyGraph


@dataclass(frozen=True)
class Verdict:
    ok: bool
    reason: str | None = None
    findings: tuple[str, ...] = ()
    status: str = "INVALID"


@dataclass(frozen=True)
class OrderingVCInput:
    graph: DependencyGraph
    desired: tuple[TrafficClassVC, ...]
    derived_vc_count: int
    derived_per_class_vc: tuple[tuple[str, int], ...]
    vc_max: int = PLANE_C_MAX_VC


def check_ordering_vc(inp: OrderingVCInput) -> Verdict:
    """Validate every desired VC against the derived assignment."""
    if inp.derived_vc_count < 1:
        return Verdict(ok=False,
                       reason=f"derived VC count {inp.derived_vc_count} "
                       f"is not a legal fabric")
    if inp.derived_vc_count > inp.vc_max:
        return Verdict(
            ok=False,
            reason=f"derived VC count {inp.derived_vc_count} exceeds the "
            f"fabric maximum {inp.vc_max} (PLANE_C_MAX_VC)")
    for row in inp.desired:
        if not 0 <= row.vc < inp.vc_max:
            return Verdict(
                ok=False,
                reason=f"traffic class {row.traffic_class!r} desires VC "
                f"{row.vc}, outside [0, {inp.vc_max})")
        if row.vc >= inp.derived_vc_count:
            return Verdict(
                ok=False,
                reason=f"traffic class {row.traffic_class!r} desires VC "
                f"{row.vc}, but the derived assignment has only "
                f"{inp.derived_vc_count} VC(s) (0.."
                f"{inp.derived_vc_count - 1}) — desired VC does not route "
                f"traffic anywhere; derive_vc_assignment_v3 is the "
                f"authority, not a suggestion")
    derived = dict(inp.derived_per_class_vc)
    for row in inp.desired:
        if row.traffic_class not in derived:
            return Verdict(
                ok=False,
                reason=f"traffic class {row.traffic_class!r} is not in the "
                f"derived assignment (declared classes are "
                f"{sorted(derived)}) — a desired VC for an undeclared "
                f"class cannot be honored")
        if derived[row.traffic_class] != row.vc:
            return Verdict(
                ok=False,
                reason=f"traffic class {row.traffic_class!r} desires VC "
                f"{row.vc}, but the derived assignment binds it to VC "
                f"{derived[row.traffic_class]} — mismatch is INVALID; the "
                f"derived assignment is not overridden")
    return Verdict(ok=True, findings=())


__all__ = ["OrderingVCInput", "Verdict", "check_ordering_vc"]
