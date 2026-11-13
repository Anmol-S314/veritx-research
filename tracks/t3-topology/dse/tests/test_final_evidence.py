"""The composed-family evidence index is read-only and never upgrades a row."""
from __future__ import annotations

from veritx_dse.product.final_evidence import composed_family_evidence


def test_composed_family_evidence_reads_recorded_rows() -> None:
    payload = composed_family_evidence()
    assert payload["scope"] == "COMPOSED_FAMILY"
    assert payload["errors"] == []
    families = {row["family"]: row for row in payload["families"]}
    assert {"gec_mecs", "fattree", "mesh"} <= set(families)
    for name in ("gec_mecs", "fattree", "mesh"):
        row = families[name]
        assert row["design_hash"]
        assert row["final_implementation"] is True
        assert row["open_rows"] == []
        assert [item["row"] for item in row["rows"]][:2] == ["A1", "A2"]
        assert all(item["status"] == "CLOSED" for item in row["rows"])
        assert row["measured"]["A2"]["lint"] == "PASS"
        assert row["source"].startswith("docs/product/evidence/final-implementation/")


def test_missing_evidence_never_closes_rows(tmp_path, monkeypatch) -> None:
    import veritx_dse.product.final_evidence as module

    monkeypatch.setattr(module, "EVIDENCE_ROOT", tmp_path / "missing")
    payload = module.composed_family_evidence()
    assert payload["families"] == []
    assert payload["errors"] == []
