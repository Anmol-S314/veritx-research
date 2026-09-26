"""CertificateProjectionV1 — the two-layer certificate (P2-A … P2-D, P2-Q).

The certificate has two semantic layers that must never be conflated:

    certificate obligation status   PASS | FAIL        (enforced upstream)
    CDG analysis verdict            PASS | FAIL | UNSUPPORTED | NOT_RUN

`_deadlock_free` folds every non-PASS CDG verdict into obligation `FAIL`.
That is correct for the certificate — inability to *prove* deadlock freedom
is not compile success — but the underlying verdict survives in the
obligation evidence and must be surfaced separately. Showing `FAIL` alone
tells a user a deadlock was detected when the analysis in fact never
produced a verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.certificate_projection import (  # noqa: E402
    CDG_ANALYSIS_VERDICTS,
    CLAIM_CONTRIBUTIONS,
    OBLIGATION_STATUS,
    TECHNICAL_ONLY,
    CertificateProjectionError,
    cdg_analysis_verdict,
    project_certificate,
)
from veritx_dse.application.compile_intent import (  # noqa: E402
    build_preset_request,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.verification.certificate import OBLIGATIONS  # noqa: E402

PRESET = "mesh4_hbm"


# ── helpers ────────────────────────────────────────────────────────────


class _Row:
    def __init__(self, row: dict) -> None:
        self._row = row

    def to_dict(self) -> dict:
        return self._row


class _Certificate:
    """A certificate-shaped shim over an explicit obligation list."""

    def __init__(self, rows: list[dict], overall: str | None = None) -> None:
        self.obligations = tuple(_Row(r) for r in rows)
        self.overall = overall or (
            "PASS" if all(r.get("status") == "PASS" for r in rows) else "FAIL")

    def certificate_id(self) -> str:
        return "sha256:" + "0" * 64


def _canonical() -> list[dict]:
    compilation = FabricCompiler().compile(build_preset_request(PRESET))
    return [o.to_dict() for o in compilation.certificate.obligations]


def _with_deadlock(evidence: dict, status: str = "FAIL") -> list[dict]:
    rows = _canonical()
    for row in rows:
        if row["obligation"] == "DEADLOCK_FREE":
            row["status"] = status
            row["evidence"] = {"vc_count": 2, "routing_classes": ["DOR_XY"],
                               "escape_vcs": [], **evidence}
    return rows


# ── P2-A: no obligation is lost ────────────────────────────────────────


def test_p2_a_all_canonical_obligations_are_preserved():
    rows = _canonical()
    projection = project_certificate(_Certificate(rows))
    assert projection["obligation_count"] == len(OBLIGATIONS) == 10
    assert {o["obligation"] for o in projection["obligations"]} \
        == set(OBLIGATIONS)


def test_p2_a_claims_and_technical_obligations_partition_the_set():
    """Every obligation is either a claim or technical-only — never both,
    never neither."""
    projection = project_certificate(_Certificate(_canonical()))
    claimed = {name for c in CLAIM_CONTRIBUTIONS for name in c["obligations"]}
    technical = {row["obligation"] for row in TECHNICAL_ONLY}
    assert claimed & technical == set()
    assert claimed | technical == set(OBLIGATIONS)
    assert {t["obligation"] for t in projection["technical_only"]} == technical


def test_p2_a_an_unclassified_obligation_fails_the_projection():
    """Fail closed: verification science must not disappear."""
    rows = _canonical()
    rows.append({"obligation": "INVENTED_OBLIGATION", "status": "PASS",
                 "method": "x", "evidence": {}})
    with pytest.raises(CertificateProjectionError,
                       match="does not classify"):
        project_certificate(_Certificate(rows))


# ── P2-B: claim derivation is deterministic ────────────────────────────


def test_p2_b_every_claim_names_its_contributing_obligations():
    projection = project_certificate(_Certificate(_canonical()))
    for claim in projection["claims"]:
        assert claim["contributing_obligations"], claim["claim"]
        assert claim["aggregation"] == "ALL_PASS"
        assert set(claim["contributing_statuses"]) \
            == set(claim["contributing_obligations"])


def test_p2_b_claim_status_is_derived_not_looked_up():
    """A claim must aggregate its contributors, not echo a same-named row."""
    rows = _canonical()
    projection = project_certificate(_Certificate(rows))
    for claim in projection["claims"]:
        contributors = [r for r in rows
                        if r["obligation"] in claim["contributing_obligations"]]
        expected = all(r["status"] == "PASS" for r in contributors)
        assert claim["established"] is expected
        assert claim["certificate_status"] == ("PASS" if expected else "FAIL")


def test_p2_b_claim_order_does_not_affect_semantics():
    """Reordering the obligation list cannot change any claim."""
    rows = _canonical()
    forward = project_certificate(_Certificate(rows))
    backward = project_certificate(_Certificate(list(reversed(rows))))
    assert [(c["claim"], c["certificate_status"]) for c in forward["claims"]] \
        == [(c["claim"], c["certificate_status"])
            for c in backward["claims"]]


def test_p2_b_a_failing_contributor_fails_the_claim():
    rows = _canonical()
    for row in rows:
        if row["obligation"] == "ROUTE_LEGAL":
            row["status"] = "FAIL"
    projection = project_certificate(_Certificate(rows))
    by_name = {c["claim"]: c for c in projection["claims"]}
    assert by_name["ROUTE_LEGAL"]["certificate_status"] == "FAIL"
    assert by_name["ROUTE_LEGAL"]["established"] is False
    # and it does not leak into a different claim
    assert by_name["ROUTE_COMPLETE"]["certificate_status"] == "PASS"


def test_p2_b_a_claim_naming_a_missing_obligation_fails_closed():
    rows = [r for r in _canonical() if r["obligation"] != "ROUTE_LEGAL"]
    with pytest.raises(CertificateProjectionError, match="does not carry"):
        project_certificate(_Certificate(rows))


# ── P2-D: no sole generic VERIFIED state ───────────────────────────────


def test_p2_d_the_projection_exposes_no_generic_verified_state():
    projection = project_certificate(_Certificate(_canonical()))
    blob = str(projection)
    assert "VERIFIED" not in blob
    assert "verified" not in blob
    for claim in projection["claims"]:
        assert claim["certificate_status"] in OBLIGATION_STATUS
        assert isinstance(claim["established"], bool)


def test_p2_d_the_vocabulary_is_declared_not_implied():
    projection = project_certificate(_Certificate(_canonical()))
    assert projection["vocabulary"]["obligation_status"] \
        == list(OBLIGATION_STATUS) == ["PASS", "FAIL"]
    assert projection["vocabulary"]["cdg_analysis_verdict"] \
        == list(CDG_ANALYSIS_VERDICTS)


def test_p2_d_the_projection_never_invents_unsupported_as_an_obligation():
    """`UNSUPPORTED` is not in the certificate obligation vocabulary."""
    assert "UNSUPPORTED" not in OBLIGATION_STATUS
    projection = project_certificate(_Certificate(_canonical()))
    for claim in projection["claims"]:
        assert claim["certificate_status"] in ("PASS", "FAIL")
    for obligation in projection["obligations"]:
        assert obligation["status"] in ("PASS", "FAIL")


# ── P2-Q: CDG analysis verdicts, all four, independently ───────────────


@pytest.mark.parametrize("expected,evidence,status", [
    ("PASS", {"acyclic": True, "sccs_gt_1": 0}, "PASS"),
    ("FAIL", {"acyclic": False, "cycle": [[3, 1], [7, 1], [3, 1]]}, "FAIL"),
    ("UNSUPPORTED", {"unsupported_reason": "cdg: uninterpretable"}, "FAIL"),
    ("NOT_RUN", {}, "FAIL"),
])
def test_p2_q_each_cdg_verdict_is_recovered_independently(expected, evidence,
                                                         status):
    rows = _with_deadlock(evidence, status=status)
    row = next(r for r in rows if r["obligation"] == "DEADLOCK_FREE")
    assert cdg_analysis_verdict(row) == expected


def test_p2_q_cdg_unsupported_is_not_presented_as_a_detected_deadlock():
    """The defect this closure exists to fix."""
    rows = _with_deadlock({"unsupported_reason": "cdg: uninterpretable"})
    projection = project_certificate(_Certificate(rows))
    analysis = projection["deadlock_analysis"]
    assert analysis["analysis_verdict"] == "UNSUPPORTED"
    assert analysis["detected_deadlock"] is False
    assert analysis["cycle_witness"] == []
    assert analysis["unsupported_reason"]


def test_p2_q_cdg_fail_produces_a_cycle_witness():
    cycle = [[3, 1], [7, 1], [3, 1]]
    rows = _with_deadlock({"acyclic": False, "cycle": cycle})
    analysis = project_certificate(_Certificate(rows))["deadlock_analysis"]
    assert analysis["analysis_verdict"] == "FAIL"
    assert analysis["detected_deadlock"] is True
    assert [w["channel_id"] for w in analysis["cycle_witness"]] == [3, 7, 3]
    assert [w["vc"] for w in analysis["cycle_witness"]] == [1, 1, 1]


def test_p2_q_cdg_not_run_is_not_a_detected_deadlock():
    rows = _with_deadlock({})
    analysis = project_certificate(_Certificate(rows))["deadlock_analysis"]
    assert analysis["analysis_verdict"] == "NOT_RUN"
    assert analysis["detected_deadlock"] is False
    assert analysis["cycle_witness"] == []


def test_p2_q_the_claim_carries_its_analysis_verdict():
    """A NOT-ESTABLISHED certificate state must not read as a deadlock."""
    rows = _with_deadlock({"unsupported_reason": "cdg: uninterpretable"})
    projection = project_certificate(_Certificate(rows))
    claim = next(c for c in projection["claims"]
                 if c["claim"] == "DEADLOCK_FREE")
    assert claim["certificate_status"] == "FAIL"
    assert claim["established"] is False
    assert claim["analysis_verdict"] == "UNSUPPORTED"
    assert claim["detected_deadlock"] is False


def test_p2_q_the_cdg_verdict_is_never_parsed_from_the_message():
    """Derivation reads evidence keys; prose is not an interface.

    The obligation's `failure_reason` names the verdict in prose. A row
    whose prose disagrees with its evidence must be read from the evidence.
    """
    row = {"obligation": "DEADLOCK_FREE", "status": "FAIL",
           "method": "channel-vc-cdg/v2",
           "evidence": {"acyclic": False, "cycle": [[1, 0]],
                        "failure_reason": "CDG verdict UNSUPPORTED: ..."}}
    assert cdg_analysis_verdict(row) == "FAIL"


# ── the real certificate ───────────────────────────────────────────────


def test_the_real_certificate_projects_all_four_claims_established():
    compilation = FabricCompiler().compile(build_preset_request(PRESET))
    projection = project_certificate(compilation.certificate)
    assert projection["overall"] == "PASS"
    assert projection["claim_count"] == 4
    assert projection["obligation_count"] == 10
    assert all(c["established"] for c in projection["claims"])
    assert projection["deadlock_analysis"]["analysis_verdict"] == "PASS"
    assert projection["deadlock_analysis"]["detected_deadlock"] is False


def test_no_certificate_projects_to_unavailable():
    projection = project_certificate(None)
    assert projection["available"] is False
    assert projection["claims"] == []
    assert projection["obligations"] == []
