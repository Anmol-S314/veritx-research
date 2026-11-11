"""Local model settings: file fallback, env precedence, and gateway save."""
from __future__ import annotations

import json
import os
from pathlib import Path
import stat
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.gateway.app import GatewayConfig, create_app  # noqa: E402
from veritx_dse.optimization.ai_search import (  # noqa: E402
    ProviderError,
    provider_config,
    save_provider_config,
)


@pytest.fixture
def config_path(tmp_path, monkeypatch):
    path = tmp_path / "model.json"
    monkeypatch.setenv("VERITX_AI_CONFIG", str(path))
    for name in ("VERITX_AI_BASE_URL", "VERITX_AI_MODEL", "VERITX_AI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    return path


@pytest.fixture
def client(tmp_path):
    config = GatewayConfig(
        store_root=tmp_path / "store",
        runs_root=tmp_path / "runs",
        projects_root=tmp_path / "projects",
        prewarm_capability_probe=False,
    )
    with TestClient(create_app(config)) as value:
        yield value


def test_saved_config_is_used_and_private(config_path):
    save_provider_config("http://127.0.0.1:11434/v1", "qwen3:32b")
    endpoint, model, key = provider_config()
    assert endpoint == "http://127.0.0.1:11434/v1/chat/completions"
    assert model == "qwen3:32b"
    assert key == ""
    assert json.loads(config_path.read_text())["base_url"] == "http://127.0.0.1:11434/v1"
    if os.name != "nt":
        assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_environment_overrides_saved_config(config_path, monkeypatch):
    save_provider_config("http://127.0.0.1:11434/v1", "saved-model")
    monkeypatch.setenv("VERITX_AI_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("VERITX_AI_MODEL", "env-model")
    endpoint, model, _ = provider_config()
    assert endpoint == "http://127.0.0.1:8000/v1/chat/completions"
    assert model == "env-model"


def test_an_environment_endpoint_never_reuses_the_saved_key(config_path, monkeypatch):
    """A saved key belongs to its saved endpoint.

    Overriding the base URL must not forward the stored credential to a
    different host (a test mock, a local proxy, or an attacker-controlled
    endpoint). The operator has to supply a key with the new endpoint.
    """
    save_provider_config("https://provider.example/v1", "saved-model", "saved-secret")
    monkeypatch.setenv("VERITX_AI_BASE_URL", "http://127.0.0.1:8000/v1")
    monkeypatch.setenv("VERITX_AI_MODEL", "env-model")
    endpoint, _, key = provider_config()
    assert endpoint == "http://127.0.0.1:8000/v1/chat/completions"
    assert key == ""
    monkeypatch.setenv("VERITX_AI_BASE_URL", "https://other.example/v1")
    with pytest.raises(ProviderError, match="API key"):
        provider_config()


def test_malformed_saved_config_is_ignored(config_path):
    config_path.write_text('{"base_url": 12, "model": null, "api_key": []}')
    with pytest.raises(ProviderError, match="Model settings"):
        provider_config()


def test_remote_endpoint_requires_a_key(config_path):
    with pytest.raises(ProviderError, match="API key"):
        save_provider_config("https://provider.example/v1", "model")
    save_provider_config("https://provider.example/v1", "model", "secret")
    assert provider_config()[2] == "secret"


def test_blank_key_preserves_the_saved_key(config_path):
    save_provider_config("https://provider.example/v1", "model", "secret")
    save_provider_config("https://provider.example/v1", "model-2")
    _, model, key = provider_config()
    assert model == "model-2"
    assert key == "secret"


def test_plain_http_is_loopback_only(config_path):
    with pytest.raises(ProviderError, match="HTTPS"):
        save_provider_config("http://provider.example/v1", "model", "secret")
    with pytest.raises(ProviderError, match="query"):
        save_provider_config("http://127.0.0.1:11434/v1?token=x", "model")


def test_gateway_saves_config_and_reports_it_ready(client, config_path):
    response = client.post("/api/v1/agents/config", json={
        "base_url": "http://127.0.0.1:11434/v1",
        "model": "qwen3:32b",
    })
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["saved"] is True
    assert body["configured"] is True
    assert body["model"] == "qwen3:32b"
    assert body["base_url"] == "http://127.0.0.1:11434/v1"
    assert config_path.exists()
    capabilities = client.get("/api/v1/agents/capabilities").json()
    assert capabilities["configured"] is True
    assert capabilities["model"] == "qwen3:32b"


def test_gateway_rejects_unsafe_config(client, config_path):
    response = client.post("/api/v1/agents/config", json={
        "base_url": "http://provider.example/v1",
        "model": "model",
    })
    assert response.status_code == 400
    assert "HTTPS" in response.text
    assert not config_path.exists()
