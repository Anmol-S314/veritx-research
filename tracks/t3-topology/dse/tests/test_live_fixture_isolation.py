"""LIVE/DEMO isolation (§29).

Proves, from the Python side, that a live gateway error can never surface
fixture content, and pins the client-side mode contract as data:

- Gateway: unknown/missing/broken inputs answer with typed failures
  ({"detail", "code"}), never fixture payloads. The gateway code that
  serves live routes never reads the Studio fixture bundle.
- Client (static): the mode vocabulary is closed ({checking, live,
  offline}); the offline fixture demo replaces the whole app behind one
  mode gate; no data loader collapses a failure to null.

What this file deliberately does NOT claim: the client currently has no
intentional DEMO entry point — `offline` follows ANY health() failure
(network-down and gateway-500 alike). test_mode_derivation_states_the_
fallback_rule pins that behavior as data; making DEMO an explicit
opt-in launch mode (URL flag / build flag) with a hard error state
otherwise is recorded as required follow-up, not implemented here.

No engine runs here. Gateway tests use TestClient against tmp_dirs.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parents[1]
REPO = DSE.parents[2]
STUDIO_SRC = REPO / "apps" / "studio" / "src"

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402

# Markers that identify a Studio fixture bundle payload. A live error body
# containing any of these is serving demo content on a live route.
FIXTURE_MARKERS = (
    "FixtureBundle",
    "compiled-mesh",
    "invalid-design",
    "backend-unavailable",
    "evaluated-design",
    "optimization-study",
    "OFFLINE DEMO",
    "contract-validated fixtures",
)


@pytest.fixture()
def client(tmp_path):
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def _assert_typed_failure(resp, *, allowed: tuple[int, ...]):
    assert resp.status_code in allowed, (
        resp.status_code, resp.text[:300])
    body = resp.json()
    assert isinstance(body, dict), body
    assert isinstance(body.get("code"), str) and body["code"], body
    assert isinstance(body.get("detail"), str), body
    blob = resp.text
    for marker in FIXTURE_MARKERS:
        assert marker not in blob, (
            f"live error response contains fixture marker {marker!r}")


def test_unknown_project_is_typed_404_not_fixture(client):
    resp = client.get("/api/v1/projects/p-deadbeef")
    _assert_typed_failure(resp, allowed=(404,))


def test_unknown_revision_topology_is_typed_error(client):
    resp = client.get("/api/v1/revisions/r-deadbeef/topology")
    _assert_typed_failure(resp, allowed=(400, 404, 409, 422))


def test_unknown_revision_compile_result_is_typed_error(client):
    resp = client.get("/api/v1/revisions/r-deadbeef/compile-result")
    _assert_typed_failure(resp, allowed=(400, 404, 409, 422))


def test_unknown_run_is_typed_error(client):
    resp = client.get("/api/v1/runs/run-deadbeef")
    _assert_typed_failure(resp, allowed=(400, 404, 409, 422))


def test_malformed_compile_request_is_typed_rejection(client):
    resp = client.post("/api/v1/projects/p-deadbeef/compile", json={
        "design": "not-a-design",
    })
    _assert_typed_failure(
        resp, allowed=(400, 404, 409, 422, 500))


def test_loom_capabilities_carry_reasons_not_fixture_values(client):
    resp = client.get(
        "/api/v1/loom/capabilities?include_topology_probe=false")
    assert resp.status_code == 200, resp.text[:300]
    body = resp.json()
    for cap in body.get("capabilities", []):
        assert isinstance(cap.get("status"), str) and cap["status"], cap
        assert isinstance(cap.get("reason"), str) and cap["reason"], cap
    for marker in FIXTURE_MARKERS:
        assert marker not in resp.text, (
            f"capability registry contains fixture marker {marker!r}")


def _studio_sources():
    return [
        p for p in STUDIO_SRC.rglob("*.tsx")
    ] + [p for p in STUDIO_SRC.rglob("*.ts")
         if ".test." not in p.name]


def test_live_gateway_code_never_reads_studio_fixtures():
    """No live-route gateway/application module may import the fixture
    bundle or read apps/studio/fixtures. Fixture GENERATORS (tools that
    write fixtures from engine output) live elsewhere and are unaffected.
    """
    offenders = []
    roots = [
        DSE / "veritx_dse" / "gateway",
        DSE / "veritx_dse" / "product",
    ]
    for root in roots:
        for path in root.rglob("*.py"):
            if "__pycache__" in str(path):
                continue
            text = path.read_text(encoding="utf-8")
            if ("apps/studio/fixtures" in text
                    or "from veritx_dse.tools.generate_studio_fixtures import"
                    in text
                    and "gateway" in str(path)):
                offenders.append(str(path.relative_to(REPO)))
            if re.search(
                    r"from\s+[\w.]*fixtures\s+import|import\s+[\w.]*fixtures",
                    text):
                offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_client_mode_vocabulary_is_closed():
    """Mode is exactly {checking, live, offline} — no silent fourth mode
    and no second derivation site."""
    studio = (STUDIO_SRC / "studio.tsx").read_text(encoding="utf-8")
    assert "export type Mode = 'checking' | 'live' | 'offline'" in studio
    assert studio.count("setMode(") == 2, (
        "mode may only transition on the health() outcome")


def test_mode_derivation_states_the_fallback_rule():
    """Pins current behavior as data: ANY health() failure — unreachable
    gateway AND gateway-500 alike — flips the whole app to the fixture
    demo. There is no intentional DEMO entry point (no URL flag, no build
    flag, no env switch). Making DEMO explicit opt-in with a hard error
    state otherwise is required follow-up (mission §29), not done here."""
    studio = (STUDIO_SRC / "studio.tsx").read_text(encoding="utf-8")
    assert ".then(() => alive && setMode('live'))" in studio
    assert ".catch(() => alive && setMode('offline'))" in studio
    app = (STUDIO_SRC / "App.tsx").read_text(encoding="utf-8")
    assert "if (mode === 'offline') return <OfflineDemo />" in app
    for probe in ("?demo", "VITE_DEMO", "REACT_APP_DEMO", "DEMO_MODE"):
        assert probe not in studio and probe not in app, (
            f"unexpected DEMO entry point {probe!r}")


def test_no_collapsed_reads_in_studio_data_layer():
    """DSE-side enforcement of the vitest contract: no data loader may
    collapse a rejection to null (absence vs failure must stay distinct)."""
    offenders = []
    for path in _studio_sources():
        text = path.read_text(encoding="utf-8")
        if re.search(r"\.catch\(\(\s*\)\s*=>\s*null\s*\)", text):
            offenders.append(str(path.relative_to(REPO)))
    assert offenders == []


def test_offline_demo_gates_the_whole_app():
    """The fixture demo replaces the app behind one mode gate; no live
    view degrades to fixtures per-view."""
    app = (STUDIO_SRC / "App.tsx").read_text(encoding="utf-8")
    assert "if (mode === 'offline') return <OfflineDemo />" in app
