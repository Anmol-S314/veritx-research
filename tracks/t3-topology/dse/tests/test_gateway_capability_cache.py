"""The Loom capability probe is expensive and pure; it is memoized per code."""
from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.gateway import app as gateway  # noqa: E402
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402


def _client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(GatewayConfig(
        store_root=tmp_path / "store", projects_root=tmp_path / "projects",
        runs_root=tmp_path / "runs", prewarm_capability_probe=False)))


def test_the_topology_probe_runs_once_per_code_revision(tmp_path, monkeypatch):
    """Regression: every Design visit re-compiled all 16 families (~4 s).

    The probe is a pure function of the loaded code, so a page navigation
    that re-requests the table bought no truth and cost seconds of
    "Checking topology support…". `refresh=true` still re-probes.
    """
    gateway._LOOM_CAPABILITY_CACHE.clear()
    calls = []

    def counted(*, include_topology_probe: bool = True):
        calls.append(include_topology_probe)
        return {"schema_version": 1, "type": fired,
                "probed": include_topology_probe}

    fired = "srota/LoomCapabilityRegistry"
    monkeypatch.setattr(gateway, "loom_capabilities", counted)
    try:
        with _client(tmp_path) as client:
            first = client.get("/api/v1/loom/capabilities").json()
            second = client.get("/api/v1/loom/capabilities").json()
            static = client.get(
                "/api/v1/loom/capabilities?include_topology_probe=false").json()
            refreshed = client.get(
                "/api/v1/loom/capabilities?refresh=true").json()
    finally:
        gateway._LOOM_CAPABILITY_CACHE.clear()
    assert calls == [True, False, True]
    assert first == second == refreshed
    assert static.get("probed") is False
    assert first["probed"] is True
