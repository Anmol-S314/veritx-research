"""Phase-1 gateway closure: typed legacy-compile failures (P1).

Pins the three gateway repairs: the guided/v3 hash-mismatch path raises a
typed 500 INTERNAL_ERROR (never a NameError), malformed legacy /compile
bodies are typed 400 INVALID_INPUT (never a bare HTTP_ERROR), and the
.../compilation alias keeps serving the revision envelope.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from fastapi.testclient import TestClient  # noqa: E402

from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402


@pytest.fixture()
def client(tmp_path):
    cfg = GatewayConfig(store_root=tmp_path / "store",
                        runs_root=tmp_path / "runs")
    (tmp_path / "runs").mkdir(parents=True, exist_ok=True)
    return TestClient(create_app(cfg), raise_server_exceptions=False)


def test_guided_v3_hash_mismatch_is_typed_internal_error(client, monkeypatch):
    """The guided/v3 identity gate must answer 500/INTERNAL_ERROR, never a
    NameError from the missing ErrorCode import."""
    from veritx_dse.application import fabric_compiler

    real_compile = fabric_compiler.FabricCompiler.compile

    # Forge at the bundle level: wrap the real compile and swap only the
    # resolved fabric hash seen by the gateway comparison, so the guided
    # and v3 paths provably disagree.
    def forged(self, request):
        compilation = real_compile(self, request)
        assert compilation.status == "COMPILED"
        real_hashes = compilation.bundle.root_hashes()

        class _Bundle:
            def root_hashes(self):
                return {**real_hashes,
                        "resolved_fabric_hash": "0" * 64}

        # Compilation is a frozen dataclass: bypass the frozen gate the
        # same way only a test double may, to forge the fabric hash.
        object.__setattr__(compilation, "bundle", _Bundle())
        return compilation

    monkeypatch.setattr(fabric_compiler.FabricCompiler, "compile", forged)
    resp = client.post("/compile", json={
        "preset": "mesh4", "policy": "baseline_deterministic_v2"})
    assert resp.status_code == 500, resp.text
    body = resp.json()
    assert body["code"] == "INTERNAL_ERROR"
    # The typed message proves the ErrorCode path executed: an unpatched
    # NameError would surface here as the generic "internal server error".
    assert "disagree on resolved_fabric_hash" in body["detail"]


def test_legacy_compile_bad_policy_is_typed_invalid_input(client):
    resp = client.post("/compile", json={
        "preset": "mesh4", "policy": "no_such_policy"})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"


def test_legacy_compile_bad_request_doc_is_typed_invalid_input(client):
    resp = client.post("/compile", json={
        "request": {"schema_version": 999}})
    assert resp.status_code == 400, resp.text
    assert resp.json()["code"] == "INVALID_INPUT"
