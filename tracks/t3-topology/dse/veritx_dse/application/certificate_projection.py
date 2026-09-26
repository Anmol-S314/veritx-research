"""veritx_dse.application.certificate_projection — CertificateProjectionV1.

The certificate has **two semantic layers** that must never be conflated
(the audit below is the authority; the code encodes it, it does not invent
it):

    certificate obligation status   PASS | FAIL
    CDG analysis verdict            PASS | FAIL | UNSUPPORTED | NOT_RUN

``VerificationCertificate.__post_init__`` enforces that an obligation
status is ``PASS`` or ``FAIL`` and that the certificate carries exactly the
ten canonical ``OBLIGATIONS``. The channel-VC CDG certifier underneath has
a richer vocabulary. ``_deadlock_free`` folds every non-PASS CDG verdict
into obligation ``FAIL`` — which is correct for the certificate, because
inability to *prove* deadlock freedom is not compile success — but the
underlying verdict survives in the obligation's evidence and MUST be
surfaced separately. Showing ``FAIL`` alone would tell a user a deadlock
was detected when the analysis in fact never produced a verdict.

The four product claims are derived here, deterministically, from the ten
obligations. The contribution table is the audit result:

    ATTACHMENT_COMPLETE <- ATTACHMENT_COMPLETE
    ROUTE_COMPLETE      <- ROUTE_COMPLETE
    ROUTE_LEGAL         <- ROUTE_LEGAL
    DEADLOCK_FREE       <- DEADLOCK_FREE

Each is 1:1 because the obligations validate different inputs:

    _attachment_complete  attachment.validate_against(design, inventory,
                                                      topology)
    _mapping_valid        the mapping<->attachment seam over
                          mapping.placements
    _route_complete       entry coverage over the router route table
    _route_legal          route.validate_against(topology)
    _deadlock_free        the (channel, VC) CDG over the realized route

``MAPPING_VALID`` is therefore NOT part of ``ATTACHMENT_COMPLETE`` despite
sharing an artifact-provenance parent in ``views.py``: it is the mapping
seam, a different artifact with a different failure mode, and it is
exposed as technical-only.

Fail-closed: every canonical obligation must be classified. A certificate
carrying an obligation this projection does not know is a projection
failure, never a silently dropped row.
"""
from __future__ import annotations

from typing import Any

CONTRACT_VERSION = 1

#: The canonical certificate obligation vocabulary (enforced upstream).
OBLIGATION_STATUS = ("PASS", "FAIL")

#: The CDG certifier's analysis vocabulary. `NOT_RUN` is declared by the
#: certifier but never produced by `certify_channel_vc_deadlock`; it is
#: retained because a reserved slot is not the same as an impossible one.
CDG_ANALYSIS_VERDICTS = ("PASS", "FAIL", "UNSUPPORTED", "NOT_RUN")

#: How a claim aggregates its contributing obligations.
#: ALL_PASS  every contributor must be PASS for the claim to be established.
AGGREGATION_ALL_PASS = "ALL_PASS"

#: claim -> (scope sentence, contributing obligations, aggregation rule).
#: The scope sentences are the Gate 7 §9 / Gate 8 §62 product wording.
CLAIM_CONTRIBUTIONS: tuple[dict[str, Any], ...] = (
    {
        "claim": "ATTACHMENT_COMPLETE",
        "scope": "every declared agent is attached",
        "obligations": ("ATTACHMENT_COMPLETE",),
        "aggregation": AGGREGATION_ALL_PASS,
    },
    {
        "claim": "ROUTE_COMPLETE",
        "scope": "every required (class, src, dst) has a route",
        "obligations": ("ROUTE_COMPLETE",),
        "aggregation": AGGREGATION_ALL_PASS,
    },
    {
        "claim": "ROUTE_LEGAL",
        "scope": "every route's channel sequence is legal",
        "obligations": ("ROUTE_LEGAL",),
        "aggregation": AGGREGATION_ALL_PASS,
    },
    {
        "claim": "DEADLOCK_FREE",
        "scope": "the channel-VC CDG is acyclic",
        "obligations": ("DEADLOCK_FREE",),
        "aggregation": AGGREGATION_ALL_PASS,
    },
)

#: Obligations that are real verification science but are not one of the
#: four product claims. They stay inspectable; they are not discarded.
TECHNICAL_ONLY: tuple[dict[str, str], ...] = (
    {"obligation": "TOPOLOGY_CONNECTED",
     "meaning": "the router graph is one connected component"},
    {"obligation": "ADDRESS_DECODE_VALID",
     "meaning": "the decode realizes the declared address map"},
    {"obligation": "VC_ASSIGNMENT_VALID",
     "meaning": "the VC structure binds the resolved route"},
    {"obligation": "MAPPING_VALID",
     "meaning": "every mapped rank lands on an attached agent"},
    {"obligation": "PACKET_FORMAT_VALID",
     "meaning": "the wire format fits topology/attachment/VC bounds"},
    {"obligation": "FABRIC_DAG_VALID",
     "meaning": "the full hardware and design/mapping seam revalidates"},
)

#: The DEADLOCK_FREE obligation is the one whose underlying analysis can
#: carry a richer verdict than the obligation status.
DEADLOCK_OBLIGATION = "DEADLOCK_FREE"


class CertificateProjectionError(RuntimeError):
    """The certificate cannot be projected without losing truth."""


def _obligations(certificate: Any) -> list[dict[str, Any]]:
    if certificate is None:
        return []
    return [o.to_dict() for o in getattr(certificate, "obligations", ())]


def cdg_analysis_verdict(obligation: dict[str, Any]) -> str:
    """Recover the CDG certifier's verdict from obligation evidence.

    Read from evidence keys, never from the failure message: the message is
    prose and prose is not an interface.

        acyclic is True                     -> PASS
        acyclic is False, cycle present     -> FAIL
        unsupported_reason, no acyclic      -> UNSUPPORTED
        no analysis evidence at all         -> NOT_RUN
    """
    evidence = obligation.get("evidence") or {}
    acyclic = evidence.get("acyclic")
    if acyclic is True:
        return "PASS"
    if acyclic is False:
        return "FAIL" if evidence.get("cycle") else "UNSUPPORTED"
    if evidence.get("unsupported_reason"):
        return "UNSUPPORTED"
    return "NOT_RUN"


def _cdg_detail(obligation: dict[str, Any]) -> dict[str, Any]:
    """The deadlock analysis, separate from the certificate obligation."""
    evidence = obligation.get("evidence") or {}
    verdict = cdg_analysis_verdict(obligation)
    cycle = evidence.get("cycle") or []
    return {
        "analysis_verdict": verdict,
        # A cycle witness exists only for a real FAIL. B/C must never be
        # rendered as "deadlock detected".
        "cycle_witness": [
            {"channel_id": node[0] if len(node) > 0 else None,
             "vc": node[1] if len(node) > 1 else None}
            for node in cycle if isinstance(node, (list, tuple))
        ] if verdict == "FAIL" else [],
        "acyclic": evidence.get("acyclic"),
        "unsupported_reason": evidence.get("unsupported_reason"),
        "sccs_gt_1": evidence.get("sccs_gt_1"),
        "node_count": evidence.get("node_count"),
        "edge_count": evidence.get("edge_count"),
        "cdg_route_classes": evidence.get("cdg_route_classes"),
        "escape_vcs": evidence.get("escape_vcs"),
        "vc_count": evidence.get("vc_count"),
        "route_realization_scheme": evidence.get("route_realization"),
        "detected_deadlock": verdict == "FAIL",
    }


def _claim_status(contribution: dict[str, Any],
                  by_name: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Aggregate a claim's contributing obligations deterministically."""
    contributors = [
        by_name.get(name) for name in contribution["obligations"]]
    missing = [name for name, row in zip(contribution["obligations"],
                                         contributors) if row is None]
    if missing:
        raise CertificateProjectionError(
            f"claim {contribution['claim']} names obligations the "
            f"certificate does not carry: {missing}")
    statuses = [row.get("status") for row in contributors]
    rule = contribution["aggregation"]
    if rule == AGGREGATION_ALL_PASS:
        established = all(s == "PASS" for s in statuses)
    else:  # pragma: no cover - a new rule must be implemented deliberately
        raise CertificateProjectionError(f"unknown aggregation rule {rule!r}")
    return {
        "claim": contribution["claim"],
        "scope": contribution["scope"],
        "certificate_status": "PASS" if established else "FAIL",
        "established": established,
        "contributing_obligations": list(contribution["obligations"]),
        "contributing_statuses": dict(zip(contribution["obligations"],
                                          statuses)),
        "aggregation": rule,
        "method": contributors[0].get("method") if len(contributors) == 1
        else None,
    }


def project_certificate(certificate: Any) -> dict[str, Any]:
    """CertificateProjectionV1.

    Primary surface: the four product claims. Technical detail: all ten
    canonical obligations. Nothing is dropped, and a certificate carrying
    an unclassified obligation fails the projection rather than losing it.
    """
    if certificate is None:
        return {
            "contract_version": CONTRACT_VERSION,
            "available": False,
            "reason": "no certificate exists for this revision",
            "claims": [],
            "obligations": [],
            "technical_only": [],
        }
    obligations = _obligations(certificate)
    by_name = {o.get("obligation"): o for o in obligations}

    classified = {name for c in CLAIM_CONTRIBUTIONS
                  for name in c["obligations"]}
    classified |= {row["obligation"] for row in TECHNICAL_ONLY}
    unclassified = sorted(set(by_name) - classified)
    if unclassified:
        # A new obligation must be classified deliberately. Dropping it
        # would make verification science disappear from the product.
        raise CertificateProjectionError(
            f"certificate carries obligations this projection does not "
            f"classify: {unclassified}")

    claims = [_claim_status(c, by_name) for c in CLAIM_CONTRIBUTIONS]

    technical = []
    for row in TECHNICAL_ONLY:
        obligation = by_name.get(row["obligation"])
        if obligation is None:
            continue
        technical.append({
            "obligation": row["obligation"],
            "meaning": row["meaning"],
            "status": obligation.get("status"),
            "method": obligation.get("method"),
            "evidence": obligation.get("evidence") or {},
            "failure_reason": (obligation.get("evidence") or {})
            .get("failure_reason"),
        })

    deadlock = by_name.get(DEADLOCK_OBLIGATION)
    deadlock_projection = _cdg_detail(deadlock) if deadlock else None
    # The deadlock claim carries its analysis verdict so a NOT-ESTABLISHED
    # certificate state is never rendered as "deadlock detected".
    if deadlock_projection is not None:
        for claim in claims:
            if claim["claim"] == DEADLOCK_OBLIGATION:
                claim["analysis_verdict"] = \
                    deadlock_projection["analysis_verdict"]
                claim["detected_deadlock"] = \
                    deadlock_projection["detected_deadlock"]
                claim["analysis_reason"] = (
                    deadlock_projection["unsupported_reason"]
                    or (deadlock or {}).get("evidence", {}).get(
                        "failure_reason"))

    return {
        "contract_version": CONTRACT_VERSION,
        "available": True,
        "overall": getattr(certificate, "overall", None),
        "certificate_id": _h(getattr(certificate, "certificate_id",
                                     lambda: None)()),
        "claims": claims,
        "obligations": [
            {"obligation": o.get("obligation"),
             "status": o.get("status"),
             "method": o.get("method"),
             "evidence": o.get("evidence") or {}}
            for o in obligations
        ],
        "technical_only": technical,
        "deadlock_analysis": deadlock_projection,
        "obligation_count": len(obligations),
        "claim_count": len(claims),
        "vocabulary": {
            "obligation_status": list(OBLIGATION_STATUS),
            "cdg_analysis_verdict": list(CDG_ANALYSIS_VERDICTS),
        },
    }


def _h(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value)
    return text if text.startswith("sha256:") else f"sha256:{text}"


__all__ = [
    "AGGREGATION_ALL_PASS",
    "CDG_ANALYSIS_VERDICTS",
    "CLAIM_CONTRIBUTIONS",
    "CONTRACT_VERSION",
    "CertificateProjectionError",
    "DEADLOCK_OBLIGATION",
    "OBLIGATION_STATUS",
    "TECHNICAL_ONLY",
    "cdg_analysis_verdict",
    "project_certificate",
]
