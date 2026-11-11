from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from veritx_dse.gateway.app import GatewayConfig, create_app
from veritx_dse.product import rtl_prototypes


def client(tmp_path, monkeypatch):
    root = tmp_path / "trusted"
    root.mkdir()
    monkeypatch.setenv("VERITX_RTL_RESEARCH_ROOTS", str(root))
    config = GatewayConfig(store_root=tmp_path / "store", runs_root=tmp_path / "runs",
                           projects_root=tmp_path / "projects", prewarm_capability_probe=False)
    return root, TestClient(create_app(config))


def test_catalog_uses_real_presence_required_denominator_and_optional_separate(tmp_path, monkeypatch):
    root, api = client(tmp_path, monkeypatch)
    try:
        (root / "mesh8x8").mkdir()
        (root / "mesh8x8" / "CandidateNoCTop.v").write_bytes(b"module actual; endmodule\n")
        response = api.get("/api/v1/catalog/rtl-prototypes")
        assert response.status_code == 200
        body = response.json()
        assert body["counts"]["required_total"] == 12
        assert body["counts"]["required_present"] == 1
        assert body["counts"]["optional_total"] == 1
        assert body["counts"]["non_target_total"] == 1
        mesh = next(row for row in body["prototypes"] if row["topology_id"] == "mesh8x8")
        absent = next(row for row in body["prototypes"] if row["topology_id"] == "torus8x8")
        assert mesh["file_presence"] == "PRESENT" and mesh["qualification_status"] == "NOT_QUALIFIED"
        assert mesh["proof_status"] == "UNVERIFIED" and mesh["lineage"] == "UNKNOWN"
        assert absent["file_presence"] == "UNKNOWN" and absent["verilog_status"] == "MISSING"
        assert len(mesh["artifacts"]) == 1 and mesh["artifacts"][0]["size_bytes"] < 100
        for name in ("manifest.tsv", "verification.json"):
            (root / name).write_text("bounded evidence", encoding="utf-8")
        evidence = api.get("/api/v1/catalog/rtl-prototypes").json()["artifacts"]
        assert {item["name"] for item in evidence} == {"manifest.tsv", "verification.json"}
        receipt = next(item for item in evidence if item["name"] == "verification.json")
        assert api.get(f"/api/v1/catalog/rtl-prototypes/catalog/artifacts/verification.json", params={"version": receipt["version"]}).text == "bounded evidence"
    finally:
        api.close()


def test_download_allowlist_traversal_symlink_and_current_bytes(tmp_path, monkeypatch):
    root, api = client(tmp_path, monkeypatch)
    try:
        folder = root / "mesh8x8"
        folder.mkdir()
        source = folder / "CandidateNoCTop.v"
        source.write_bytes(b"real named source\n")
        catalog = api.get("/api/v1/catalog/rtl-prototypes").json()
        entry = catalog["prototypes"][0]["artifacts"][0]
        downloaded = api.get(f"/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/CandidateNoCTop.v", params={"version": entry["version"]})
        assert downloaded.status_code == 200 and downloaded.content == source.read_bytes()
        assert api.get("/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/CandidateNoCTop.v").status_code == 404
        source.write_bytes(b"replacement bytes are not the catalogued artifact")
        stale = api.get("/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/CandidateNoCTop.v", params={"version": entry["version"]})
        assert stale.status_code == 404
        assert api.get("/api/v1/catalog/rtl-prototypes/unknown/artifacts/CandidateNoCTop.v", params={"version": entry["version"]}).status_code == 404
        assert api.get("/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/..%2Fetc%2Fpasswd", params={"version": entry["version"]}).status_code == 404
        assert api.get("/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/arbitrary.v", params={"version": entry["version"]}).status_code == 404
        outside = tmp_path / "outside.v"
        outside.write_bytes(b"secret")
        source.unlink()
        source.symlink_to(outside)
        assert api.get("/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/CandidateNoCTop.v", params={"version": entry["version"]}).status_code == 404
        assert api.get("/api/v1/catalog/rtl-prototypes/mesh8x8/artifacts/CandidateNoCTop.v", params={"version": entry["version"]}).status_code == 404
        assert outside.read_bytes() == b"secret"

        # A symlinked ancestor must also be rejected, not merely a symlinked file.
        source.unlink()
        source.parent.rmdir()
        source.parent.symlink_to(outside.parent, target_is_directory=True)
        with pytest.raises(FileNotFoundError):
            rtl_prototypes.stream_artifact("mesh8x8", "CandidateNoCTop.v", entry["version"])
        assert outside.read_bytes() == b"secret"
    finally:
        api.close()


def test_catalog_read_is_read_only_and_family_lookup_uses_evidence_shape(tmp_path, monkeypatch):
    root, api = client(tmp_path, monkeypatch)
    try:
        before = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        response = api.get("/api/v1/catalog/rtl-prototypes")
        assert response.status_code == 200
        after = sorted(p.relative_to(root).as_posix() for p in root.rglob("*"))
        assert before == after
        selected = rtl_prototypes.prototype_for_family("torus")
        assert selected["topology_id"] == "torus8x8"
        assert selected["qualification_status"] == "NOT_QUALIFIED"
    finally:
        api.close()
