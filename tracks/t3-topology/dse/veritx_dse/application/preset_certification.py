"""veritx_dse.application.preset_certification — shipped-preset certification.

A preset may only advertise a capability envelope whose own conditions it
satisfies. Gate 6 asserted that for four presets; nothing verified it, and
one assertion was false: the ``mesh4`` family declared
``model_family=mixture_of_experts`` while advertising
``CAP-ENV-BOOKSIM-MESH-DOR-XY-V1``, whose ``COND-DENSE-STATIC-WORKLOAD``
requires ``dense_transformer``.

This module derives the certification state from **evidence** rather than
from the claim:

    registry claim  (exposure-registry.yaml: guided_eligible + envelope)
  + condition verdicts evaluated from the canonical compilation
  = certification state

States (Gate 6 already distinguishes the first two; the last two are the
fail-closed additions):

    GUIDED_SAFE    claimed Guided-eligible and every statically decidable
                   required condition of the advertised envelope holds
    EXPERT_ONLY    not claimed Guided-eligible
    INVALID        claimed Guided-eligible but a required condition FAILS —
                   the claim is false and must not ship
    UNCERTIFIED    no registry entry, or the claim rests on a condition
                   only an execution can decide

Fail-closed: an undecidable condition never yields GUIDED_SAFE, and an
unknown preset never yields any state but UNCERTIFIED.
"""
from __future__ import annotations

import math
from typing import Any

from veritx_dse.application import product_registry as registry

GUIDED_SAFE = "GUIDED_SAFE"
EXPERT_ONLY = "EXPERT_ONLY"
INVALID = "INVALID"
UNCERTIFIED = "UNCERTIFIED"
CERTIFICATION_STATES = (GUIDED_SAFE, EXPERT_ONLY, INVALID, UNCERTIFIED)

#: A condition verdict.
HOLDS = "HOLDS"
FAILS = "FAILS"
PENDING_EXECUTION = "PENDING_EXECUTION"
NOT_APPLICABLE = "NOT_APPLICABLE"


def _dig(doc: Any, *path: str) -> Any:
    node = doc
    for key in path:
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    return node


# ── condition evaluators ───────────────────────────────────────────────
#
# Each evaluator reads the canonical intent and/or the canonical
# compilation. It never guesses: a condition it cannot decide returns
# PENDING_EXECUTION, which blocks a GUIDED_SAFE verdict.

def _cond_topology_mesh(doc, compilation) -> str:
    family = _dig(doc, "noc_config", "topology_family")
    if family != "mesh":
        return FAILS
    radix = _dig(doc, "noc_config", "radix")
    if radix is None:
        return HOLDS  # derived by the compiler; COND-ROUTING proves it did
    if not isinstance(radix, int) or radix < 1:
        return FAILS
    return HOLDS if math.isqrt(radix) ** 2 == radix else FAILS


def _routing_class_ids(compilation) -> tuple[str, ...]:
    if compilation is None or compilation.status != "COMPILED":
        return ()
    try:
        return tuple(c.id for c in compilation.bundle.router_route.routing_classes)
    except Exception:  # noqa: BLE001 - absence is a verdict, not a crash
        return ()


def _cond_routing_dor_xy(doc, compilation) -> str:
    if compilation is None:
        return PENDING_EXECUTION
    if compilation.status != "COMPILED":
        return FAILS
    return HOLDS if _routing_class_ids(compilation) == ("DOR_XY",) else FAILS


def _cond_canonical_route_present(doc, compilation) -> str:
    if compilation is None:
        return PENDING_EXECUTION
    if compilation.status != "COMPILED":
        return FAILS
    try:
        return HOLDS if compilation.bundle.resolved_route is not None else FAILS
    except Exception:  # noqa: BLE001
        return FAILS


def _traffic_classes(doc, compilation) -> set[str]:
    """Unified traffic classes after lowering.

    Prefers the compiled VC assignment (the lowered truth); falls back to
    the declared collectives and requirements when there is no compilation.
    """
    if compilation is not None and compilation.status == "COMPILED":
        try:
            pairs = compilation.bundle.vc_assignment.traffic_class_to_vcs
        except Exception:  # noqa: BLE001
            pairs = ()
        # `traffic_class_to_vcs` is a tuple of (traffic_class, vc_ids) pairs.
        classes = {str(pair[0]) for pair in (pairs or ())
                   if isinstance(pair, (tuple, list)) and pair}
        if classes:
            return classes
    declared: set[str] = set()
    for collective in _dig(doc, "workload", "collectives") or []:
        if isinstance(collective, dict) and collective.get("traffic_class"):
            declared.add(collective["traffic_class"])
    for requirement in doc.get("requirements") or []:
        if isinstance(requirement, dict) and requirement.get("traffic_class"):
            declared.add(requirement["traffic_class"])
    return declared


def _cond_single_comm_class(doc, compilation) -> str:
    classes = _traffic_classes(doc, compilation)
    if len(classes) == 0:
        # No declared class at all: the lowering unifies to one class.
        return HOLDS
    return HOLDS if len(classes) == 1 else FAILS


def _cond_identity_vc_transitions(doc, compilation) -> str:
    if compilation is None or compilation.status != "COMPILED":
        return PENDING_EXECUTION
    try:
        transitions = compilation.bundle.vc_assignment.allowed_transitions
    except Exception:  # noqa: BLE001
        return FAILS
    if not transitions:
        return FAILS
    return HOLDS if all(a == b for a, b in transitions) else FAILS


def _cond_single_clock_fabric(doc, compilation) -> str:
    domains = {a.get("clock_domain") for a in doc.get("agents") or []
               if isinstance(a, dict)}
    return HOLDS if len({d for d in domains if d}) <= 1 else FAILS


def _cond_dense_static_workload(doc, compilation) -> str:
    family = _dig(doc, "workload", "model_family")
    return HOLDS if family == "dense_transformer" else FAILS


def _cond_config_audit_closed(doc, compilation) -> str:
    """Every result-affecting backend config value has a ParameterOwner."""
    try:
        from veritx_dse.backend.meshdor_profile import (  # noqa: PLC0415
            MESH_DOR_OWNERSHIP,
        )
    except Exception:  # noqa: BLE001
        return PENDING_EXECUTION
    if not MESH_DOR_OWNERSHIP:
        return FAILS
    from veritx_dse.backend.contracts import ParameterOwner  # noqa: PLC0415
    return HOLDS if all(owner is not ParameterOwner.INACTIVE_FOR_PROFILE
                        for owner in MESH_DOR_OWNERSHIP.values()) else FAILS


def _cond_ramulator_v1(doc, compilation) -> str:
    """dram_class HBM3, controller HBM34, sequential_bankstriped_v1, 4/1."""
    address_map = doc.get("address_map") or {}
    if not address_map.get("ranges"):
        return NOT_APPLICABLE
    return PENDING_EXECUTION


def _cond_serving_round_qualified(doc, compilation) -> str:
    return PENDING_EXECUTION


def _cond_certified_backend_authority(doc, compilation) -> str:
    return PENDING_EXECUTION


#: condition id -> evaluator. A condition with no evaluator is treated as
#: PENDING_EXECUTION, so a new condition can never silently certify.
_EVALUATORS: dict[str, Any] = {
    "COND-TOPOLOGY-MESH": _cond_topology_mesh,
    "COND-ROUTING-DOR-XY": _cond_routing_dor_xy,
    "COND-CANONICAL-ROUTE-PRESENT": _cond_canonical_route_present,
    "COND-SINGLE-COMM-CLASS": _cond_single_comm_class,
    "COND-IDENTITY-VC-TRANSITIONS": _cond_identity_vc_transitions,
    "COND-SINGLE-CLOCK-FABRIC": _cond_single_clock_fabric,
    "COND-DENSE-STATIC-WORKLOAD": _cond_dense_static_workload,
    "COND-CONFIG-AUDIT-CLOSED": _cond_config_audit_closed,
    "COND-RAMULATOR-V1": _cond_ramulator_v1,
    "COND-SERVING-ROUND-QUALIFIED": _cond_serving_round_qualified,
    "COND-CERTIFIED-BACKEND-AUTHORITY": _cond_certified_backend_authority,
}


def condition_verdicts(doc: dict[str, Any], compilation: Any,
                       condition_ids: tuple[str, ...]) -> dict[str, str]:
    verdicts: dict[str, str] = {}
    for condition_id in condition_ids:
        evaluator = _EVALUATORS.get(condition_id)
        verdicts[condition_id] = (PENDING_EXECUTION if evaluator is None
                                  else evaluator(doc, compilation))
    return verdicts


# ── certification ──────────────────────────────────────────────────────

def certify(preset_id: str, doc: dict[str, Any],
            compilation: Any = None) -> dict[str, Any]:
    """The certification state of one shipped preset.

    Fail-closed at every branch: an unknown preset is UNCERTIFIED, a
    failed required condition on a Guided claim is INVALID, and an
    undecidable condition can never produce GUIDED_SAFE.
    """
    spec = registry.preset_spec(preset_id)
    if spec is None:
        return {
            "preset_id": preset_id,
            "state": UNCERTIFIED,
            "claimed_guided_eligible": None,
            "envelope": None,
            "conditions": {},
            "failed_conditions": [],
            "pending_conditions": [],
            "reason": "not in the exposure registry",
        }

    claimed = bool(spec.get("guided_eligible"))
    envelope = spec.get("envelope")
    conditions: dict[str, str] = {}
    if envelope:
        required = tuple(
            registry.envelopes()[envelope].get("required_conditions") or ())
        conditions = condition_verdicts(doc, compilation, required)

    failed = sorted(c for c, v in conditions.items() if v == FAILS)
    pending = sorted(c for c, v in conditions.items()
                     if v == PENDING_EXECUTION)

    if not claimed:
        state = EXPERT_ONLY
        reason = spec.get("reason") or "not Guided-eligible by registry"
    elif failed:
        # A Guided claim that its own envelope refutes.
        state = INVALID
        reason = ("claimed Guided-eligible but the advertised envelope's "
                  "required conditions fail: " + ", ".join(failed))
    elif pending:
        state = UNCERTIFIED
        reason = ("Guided claim rests on conditions only an execution can "
                  "decide: " + ", ".join(pending))
    elif envelope is None:
        state = UNCERTIFIED
        reason = "claimed Guided-eligible but names no envelope"
    else:
        state = GUIDED_SAFE
        reason = f"reaches {envelope}"

    return {
        "preset_id": preset_id,
        "state": state,
        "claimed_guided_eligible": claimed,
        "envelope": envelope,
        "conditions": conditions,
        "failed_conditions": failed,
        "pending_conditions": pending,
        "reason": reason,
    }


def certify_all() -> list[dict[str, Any]]:
    """Certify every preset the exposure registry knows about."""
    return [certify(name, _load_preset_doc(name))
            for name in sorted(registry.exposure_document().get("presets") or {})]


def _load_preset_doc(preset_id: str) -> dict[str, Any]:
    """The canonical request document for a shipped preset, or ``{}``.

    A preset the product cannot expand is not certifiable; ``{}`` fails
    every condition, which is the fail-closed direction.
    """
    from veritx_dse.application.compile_intent import (  # noqa: PLC0415
        build_preset_request as build_fabric_preset,
    )
    if preset_id in ("mesh4", "mesh4_hbm", "mesh4_wide128"):
        return build_fabric_preset(preset_id).to_dict()
    import json  # noqa: PLC0415
    from veritx_dse.core.paths import REPO  # noqa: PLC0415
    from veritx_dse.product.service import (  # noqa: PLC0415
        _WORKLOAD_TEMPLATES,
    )
    for workload_id, path, _title, _description in _WORKLOAD_TEMPLATES:
        if workload_id == preset_id:
            return json.loads((REPO / path).read_text(encoding="utf-8"))
    return {}


__all__ = [
    "CERTIFICATION_STATES",
    "EXPERT_ONLY",
    "FAILS",
    "GUIDED_SAFE",
    "HOLDS",
    "INVALID",
    "NOT_APPLICABLE",
    "PENDING_EXECUTION",
    "UNCERTIFIED",
    "certify",
    "certify_all",
    "condition_verdicts",
]
