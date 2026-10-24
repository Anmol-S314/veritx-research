"""AI runtime against a local OpenAI-compatible mock provider.

The server is unconfigured by default (no VERITX_AI_BASE_URL/MODEL), so this
test points the process at a loopback stub that speaks the same
``POST {base}/chat/completions`` contract the runtime requires. It verifies
the real HTTP path — connection, model identity, consent gating, workload
translation, and pinned adoption — without any external model. A real
provider still needs owner-supplied credentials and policy approval.
"""
from __future__ import annotations

import copy
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_prototype_backend_closure import client, project  # noqa: E402
from veritx_dse.product import agent_runtime  # noqa: E402


class _MockState:
    def __init__(self):
        self.requests: list[dict] = []
        self.content: str = ""


def _handler(state: _MockState):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
            state.requests.append({
                "path": self.path,
                "model": body.get("model"),
                "messages": body.get("messages"),
                "response_format": body.get("response_format"),
                "authorization": self.headers.get("Authorization"),
            })
            envelope = json.dumps(
                {"choices": [{"message": {"content": state.content}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(envelope)))
            self.end_headers()
            self.wfile.write(envelope)
    return Handler


@pytest.fixture
def mock_provider(monkeypatch):
    state = _MockState()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _handler(state))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("VERITX_AI_BASE_URL",
                       f"http://127.0.0.1:{server.server_port}")
    monkeypatch.setenv("VERITX_AI_MODEL", "mock-model")
    monkeypatch.delenv("VERITX_AI_API_KEY", raising=False)
    yield state
    server.shutdown()
    thread.join()


def test_mock_provider_connection_identity_and_consent(client, mock_provider,
                                                      monkeypatch):
    pid = project(client)
    assert mock_provider.content == ""
    capabilities = client.get("/api/v1/agents/capabilities").json()
    assert capabilities["configured"] is True
    assert capabilities["model"] == "mock-model"
    assert capabilities["transport"] == "openai"

    mock_provider.content = "Mock analysis: no measurements invented."
    chat = client.post(f"/api/v1/projects/{pid}/agent/chat",
                       json={"message": "summarize this design",
                             "allow_model": True})
    assert chat.status_code == 200, chat.text
    assert chat.json()["text"] == "Mock analysis: no measurements invented."
    assert chat.json()["tool_calls"] == [] and chat.json()["mutations"] is False
    assert len(mock_provider.requests) == 1
    only = mock_provider.requests[0]
    assert only["path"] == "/chat/completions"
    assert only["model"] == "mock-model"
    assert only["authorization"] is None  # loopback mock needs no key
    assert any(m.get("role") == "user" and "summarize" in m.get("content", "")
               for m in only["messages"])

    # No consent, no transmission: the provider sees nothing new.
    refused = client.post(f"/api/v1/projects/{pid}/agent/chat",
                          json={"message": "summarize this design",
                                "allow_model": False})
    assert refused.status_code != 200
    assert len(mock_provider.requests) == 1


def test_mock_provider_translation_and_pinned_adoption(client, mock_provider):
    pid = project(client)
    draft = client.get(f"/api/v1/projects/{pid}/draft").json()
    translated = copy.deepcopy(draft["request"]["workload"])
    translated["model_name"] = "mock-reviewed-model"
    mock_provider.content = json.dumps({
        "workload": translated, "rationale": "Declared interpretation",
        "assumptions": ["Input sizes are declared, not measured."]})
    endpoint = f"/api/v1/projects/{pid}/agent/workload-proposals"
    proposal = client.post(
        endpoint, json={"message": "use a reviewed model name",
                        "allow_model": True,
                        "expected_draft_design_hash": draft["design_hash"]})
    assert proposal.status_code == 200, proposal.text
    assert proposal.json()["model"] == "mock-model"
    # Translation never mutates the draft by itself.
    assert client.get(f"/api/v1/projects/{pid}/draft").json()[
        "design_hash"] == draft["design_hash"]
    adopted = client.post(
        f"{endpoint}/{proposal.json()['proposal_id']}/adopt",
        json={"expected_draft_design_hash": draft["design_hash"]})
    assert adopted.status_code == 200, adopted.text
    after = client.get(f"/api/v1/projects/{pid}/draft").json()
    assert after["request"]["workload"]["model_name"] == "mock-reviewed-model"
    assert after["request"]["requirements"] == draft["request"]["requirements"]


def test_mock_provider_invalid_envelope_is_refused(client, mock_provider):
    pid = project(client)
    mock_provider.content = ""
    # Empty model content is not a usable answer.
    response = client.post(f"/api/v1/projects/{pid}/agent/chat",
                           json={"message": "summarize", "allow_model": True})
    assert response.status_code != 200
