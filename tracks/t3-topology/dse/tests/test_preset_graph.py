"""Preset graph seeding endpoint (graph-seed slice).

GET /api/v1/catalog/fabric-presets/{id}/graph compiles the shipped
preset in memory and projects its certified shape. Unknown names are
404 NOT_FOUND; a preset that does not compile is 422, never partial.
"""
from __future__ import annotations

import sys
from pathlib import Path

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402


def _client(tmp_path):
    runs = tmp_path / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    cfg = GatewayConfig(store_root=tmp_path / "store", runs_root=runs)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def test_explicit16_graph_shape(tmp_path):
    r = _client(tmp_path).get("/api/v1/catalog/fabric-presets/explicit16/graph")
    assert r.status_code == 200, r.text[:400]
    doc = r.json()
    assert doc["preset_id"] == "explicit16"
    assert doc["generation"] == "v4"
    assert doc["counts"]["routers"] == 16
    assert len(doc["routers"]) == 16
    assert len(doc["channels"]) > 0
    assert len(doc["endpoints"]) == 16
    assert doc["design_hash"].startswith("sha256:")


def test_mesh4_graph_shape(tmp_path):
    r = _client(tmp_path).get("/api/v1/catalog/fabric-presets/mesh4/graph")
    assert r.status_code == 200, r.text[:400]
    assert r.json()["counts"]["routers"] == 4


def test_unknown_preset_is_404(tmp_path):
    r = _client(tmp_path).get("/api/v1/catalog/fabric-presets/nope/graph")
    assert r.status_code == 404
    assert r.json()["code"] == "NOT_FOUND"
