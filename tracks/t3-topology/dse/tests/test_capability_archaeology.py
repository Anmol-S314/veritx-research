"""Evidence-first capability archaeology — structural consistency.

PART 20 of the archaeology work order. These are NOT brittle line-count or
branch-SHA checks: they assert that the ledger is structurally honest, so a
future edit cannot quietly turn a "backend-only" capability into a bare
"SUPPORTED", or assert a measured capability without citing the artifact.

Nothing here depends on a remote branch being present.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).parents[4]
DOC = REPO / "docs/product/EVIDENCE-FIRST-CAPABILITY-ARCHAEOLOGY.md"
LEDGER = REPO / "docs/product/capability-archaeology.yaml"


@pytest.fixture(scope="module")
def ledger():
    return yaml.safe_load(LEDGER.read_text())


# ══ record completeness ═════════════════════════════════════════════════

def test_every_record_answers_every_axis(ledger):
    """No collapsed SUPPORTED flag: all 13 axes, independently."""
    required = ledger["fields"]
    assert len(required) == 13
    for cap in ledger["capabilities"]:
        missing = [f for f in required if f not in cap]
        assert not missing, f"{cap['id']} missing {missing}"
        for f in required:
            assert str(cap[f]).strip(), f"{cap['id']}.{f} is empty"


def test_no_record_uses_unsupported_as_its_only_classification(ledger):
    allowed = set(ledger["classifications"])
    for cap in ledger["capabilities"]:
        cls = cap["classifications"]
        assert cls, f"{cap['id']} has no classification"
        assert set(cls) <= allowed, f"{cap['id']} has unknown classes {set(cls) - allowed}"
        assert "unsupported" not in " ".join(cls).lower()


def test_classification_vocabulary_is_declared_and_used(ledger):
    declared = set(ledger["classifications"])
    used = {c for cap in ledger["capabilities"] for c in cap["classifications"]}
    assert used <= declared
    # The vocabulary must be the full one, even if some cells are unused.
    for must in ("CURRENT_CANONICAL", "CURRENT_BACKEND_ONLY",
                 "HISTORICAL_EXECUTABLE", "HISTORICAL_MEASURED",
                 "DOC_STALE", "TRULY_ABSENT"):
        assert must in declared


# ══ evidence citation ═══════════════════════════════════════════════════

def _cites(cap) -> str:
    return " ".join(str(v) for v in cap.values()) + " " + \
        " ".join(cap.get("evidence") or [])


def test_claimed_implementations_cite_a_source_path(ledger):
    """A YES implementation must name a real path (or an explicit N/A)."""
    path_re = re.compile(r"[A-Za-z0-9_./-]+\.(py|cpp|hpp|h|md|yaml|json|cfg|sh|patch)")
    for cap in ledger["capabilities"]:
        impl = str(cap["IMPLEMENTED_ANYWHERE"])
        if impl.startswith("YES") or impl.startswith("PARTIAL"):
            assert path_re.search(_cites(cap)), (
                f"{cap['id']} claims implementation without citing a path")
        elif impl.startswith("NO"):
            pass
        else:
            assert impl.startswith("N/A"), f"{cap['id']}: odd IMPLEMENTED_ANYWHERE {impl!r}"


def test_claimed_measurements_cite_an_artifact(ledger):
    """HISTORICAL_MEASURED / measured YES must cite an experiment or result."""
    for cap in ledger["capabilities"]:
        measured = str(cap["MEASURED_ANYWHERE"])
        if measured.startswith("YES") and "HISTORICAL_MEASURED" in cap["classifications"]:
            cited = _cites(cap)
            assert ("RESULTS" in cited or "docs/" in cited or "evidence" in cited
                    or "run_full_comparison" in cited or "experiments/" in cited
                    or "study_" in cited or "scripts/" in cited), (
                f"{cap['id']} is HISTORICAL_MEASURED but cites no result artifact")


def test_every_evidence_path_exists_or_is_a_known_history_ref(ledger):
    """Cited repo paths must exist. Historical SHAs/branches are allowed as
    text (the audit process, not runtime tests, owns branch comparison)."""
    for cap in ledger["capabilities"]:
        for p in cap.get("evidence") or []:
            full = REPO / p
            assert full.exists(), f"{cap['id']} cites a non-existent path: {p}"


# ══ the MISSING_BRIDGE field is the point ══════════════════════════════

def test_every_record_names_a_missing_bridge_or_explicitly_none(ledger):
    for cap in ledger["capabilities"]:
        mb = str(cap["MISSING_BRIDGE"]).strip()
        assert mb, f"{cap['id']} has an empty MISSING_BRIDGE"
        assert mb.lower() != "unknown"


def test_backend_only_capabilities_name_a_layer_not_a_verdict(ledger):
    """'GEC unsupported' is forbidden. A backend-only record must name the
    MISSING layer."""
    for cap in ledger["capabilities"]:
        if "CURRENT_BACKEND_ONLY" in cap["classifications"]:
            mb = str(cap["MISSING_BRIDGE"]).lower()
            assert "unsupported" not in mb
            assert len(mb.split()) >= 3, f"{cap['id']} bridge too vague: {mb!r}"


# ══ TRULY_ABSENT discipline ════════════════════════════════════════════

def test_no_truly_absent_record_without_search_scope(ledger):
    for cap in ledger["capabilities"]:
        if "TRULY_ABSENT" in cap["classifications"]:
            cited = _cites(cap).lower()
            assert "search" in cited or "searched" in cited, (
                f"{cap['id']} claims TRULY_ABSENT without recording search scope")


# ══ the document and the ledger agree ══════════════════════════════════

def test_document_states_the_evidence_order(ledger):
    doc = DOC.read_text()
    assert "EVIDENCE ORDER" in doc
    assert "Source beats prose" in doc
    for ref in ("p1b/verified-evaluation", "integration/p1-product",
                "epic/booksim-forward-port"):
        assert ref in doc


def test_document_carries_the_registry_contradiction_section():
    doc = DOC.read_text()
    assert "REGISTRY CLAIMS THAT DO NOT MATCH EXECUTABLE EVIDENCE" in doc
    for target in ("topology-family-registry.yaml", "capability-registry.yaml",
                   "feature-reclamation-registry.yaml",
                   "FEATURE-RECLAMATION-AUDIT.md",
                   "FEATURE-RECLAMATION-AMENDMENT.md",
                   "CAPABILITY-MATRIX.md"):
        assert target in doc, f"{target} not named in the contradiction report"


def test_document_classification_counts_match_the_ledger(ledger):
    """The doc's count table must equal the ledger, so the two cannot drift."""
    doc = DOC.read_text()
    section = doc.split("## 6. CLASSIFICATION COUNTS")[1].split("## 7.")[0]
    counts = {c: sum(1 for cap in ledger["capabilities"]
                     if c in cap["classifications"])
              for c in ledger["classifications"]}
    for cls, n in counts.items():
        row = re.search(rf"\|\s*{cls}\s*\|\s*(\d+)\s*\|", section)
        assert row, f"{cls} missing from the doc count table"
        assert int(row.group(1)) == n, (
            f"{cls}: doc says {row.group(1)}, ledger says {n}")


def test_document_records_the_mecs_power_invalidity(ledger):
    doc = DOC.read_text()
    assert "_md_chan" in doc
    assert "INVALID/INCOMPLETE" in doc
    cap = next(c for c in ledger["capabilities"] if c["id"] == "BOOKSIM-NATIVE-POWER")
    assert "_md_chan" in cap["MISSING_BRIDGE"]


def test_document_does_not_claim_multicast_json_is_capability():
    doc = DOC.read_text()
    assert "no consumer" in doc.lower()
    assert "is not an executable capability" in doc
