"""Owned process cancellation, immutable snapshots and real evidence-backed AI adoption."""
import json
import os
from pathlib import Path
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from veritx_dse.gateway.app import GatewayConfig, create_app, resolve_booksim_bin
from veritx_dse.product.jobs import JobManager, TERMINAL_STATES
from veritx_dse.product.store import ProductStore
from test_topology_search import _base


def wait_for(fn, predicate, timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = fn()
        if predicate(value):
            return value
        time.sleep(.05)
    pytest.fail(f"deadline waiting for {value}")


def client_for(tmp_path):
    return TestClient(create_app(GatewayConfig(store_root=tmp_path / "store",
        projects_root=tmp_path / "projects", runs_root=tmp_path / "runs",
        booksim_bin=resolve_booksim_bin())), raise_server_exceptions=False)


def project_for(client):
    response = client.post("/api/v1/projects", json={"name": "bounded jobs"})
    assert response.status_code == 200, response.text
    pid = response.json()["project"]["project_id"]
    assert client.put(f"/api/v1/projects/{pid}/draft", json={"request": _base().to_dict()}).status_code == 200
    draft = client.get(f"/api/v1/projects/{pid}/draft").json()
    return pid, draft


def pin(draft):
    return {"expected_draft_design_hash": draft["design_hash"]}


def test_real_compile_job_publishes_without_changing_draft(tmp_path):
    with client_for(tmp_path) as client:
        pid, draft = project_for(client)
        response = client.post(f"/api/v1/projects/{pid}/compile-jobs", json=pin(draft))
        assert response.status_code == 202, response.text
        job = response.json()
        done = wait_for(lambda: client.get(f"/api/v1/jobs/{job['job_id']}").json(), lambda j: j["state"] in TERMINAL_STATES)
        assert done["state"] == "COMPLETED", done
        revision = client.get(f"/api/v1/revisions/{done['result']['revision_id']}").json()
        assert revision["compilation"]["status"] == "COMPILED"
        assert revision["certificate"]["overall"] == "PASS"
        after = client.get(f"/api/v1/projects/{pid}/draft").json()
        assert after["request"] == draft["request"] and after["updated_at"] == draft["updated_at"]
        assert client.post(f"/api/v1/jobs/{job['job_id']}/cancel").json()["state"] == "COMPLETED"


def test_qtree_compile_is_cancellable_and_does_not_block_design(tmp_path):
    with client_for(tmp_path) as client:
        pid, draft = project_for(client)
        request = dict(draft["request"])
        request["topology"] = {"kind": "structured", "family": "qtree", "params": {"radix": 32, "tiers": 2}}
        response = client.put(f"/api/v1/projects/{pid}/draft", json={"request": request})
        assert response.status_code == 200, response.text
        draft = response.json()
        job = client.post(f"/api/v1/projects/{pid}/compile-jobs", json=pin(draft)).json()
        wait_for(lambda: client.get(f"/api/v1/jobs/{job['job_id']}").json(), lambda j: j["state"] == "RUNNING")
        process = client.app.state.product.jobs._processes[job["job_id"]]
        start = time.monotonic()
        assert client.get("/api/v1/health").status_code == 200
        assert client.get(f"/api/v1/projects/{pid}/design").status_code == 200
        assert time.monotonic() - start < 3
        assert client.post(f"/api/v1/projects/{pid}/compile-jobs", json=pin(draft)).status_code == 409
        stopped = client.post(f"/api/v1/jobs/{job['job_id']}/cancel").json()
        assert stopped["state"] == "CANCELLED" and process.poll() is not None
        assert client.get(f"/api/v1/projects/{pid}").json()["revisions"] == []
        assert client.get(f"/api/v1/projects/{pid}/draft").json() == draft


def test_stale_and_extra_fields_never_launch(tmp_path):
    with client_for(tmp_path) as client:
        pid, draft = project_for(client)
        assert client.post(f"/api/v1/projects/{pid}/compile-jobs", json={"expected_draft_design_hash": "old"}).status_code == 409
        assert client.post(f"/api/v1/projects/{pid}/compile-jobs", json={**pin(draft), "timeout_s": 9999}).status_code == 422
        assert client.get(f"/api/v1/projects/{pid}/jobs?kind=COMPILE").json()["jobs"] == []


def test_process_cancel_and_timeout_do_not_publish(tmp_path):
    store = ProductStore(tmp_path / "store")
    pid = store.create_project(name="process jobs", draft_doc={}, workload_id="fixture", source="test")["project_id"]
    manager = JobManager(store)
    published = []

    def prepare(job_id):
        directory = tmp_path / job_id
        directory.mkdir()
        output = directory / "output.json"
        return [sys.executable, "-c", "import time; time.sleep(30)"], output

    try:
        job = manager.submit_process(pid, kind="COMPILE", draft_hash="pinned", prepare=prepare, publish=published.append)
        wait_for(lambda: store.load_job(pid, job["job_id"]), lambda j: j["state"] == "RUNNING")
        process = manager._processes[job["job_id"]]
        assert manager.cancel(pid, job["job_id"])["state"] == "CANCELLED"
        assert process.poll() is not None
        timed = manager.submit_process(pid, kind="COMPILE", draft_hash="pinned", prepare=prepare, publish=published.append, timeout_s=1)
        done = wait_for(lambda: store.load_job(pid, timed["job_id"]), lambda j: j["state"] in TERMINAL_STATES)
        assert done["state"] == "FAILED" and done["error_code"] == "EXECUTION_TIMEOUT"
        assert published == []
    finally:
        manager.shutdown()


@pytest.fixture
def provider(monkeypatch):
    requests = []
    mode = {"error": False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            if mode["error"]:
                self.send_response(401)
                self.end_headers()
                self.wfile.write(b"secret-token-do-not-expose")
                return
            context = json.loads(body["messages"][1]["content"])
            number = len(requests)
            topology = {"kind": "mesh", "side_length": 6, "concentration": 1}
            proposal = {"base_design_hash": context["base_design_hash"], "topology": topology,
                        "rationale": "Local HTTP contract fixture, not a real model."}
            if number == 3:
                proposal["objective_values"] = {"completion_cycles": 1}
            if number == 4:
                proposal["topology"] = {"kind": "torus", "side_length": 6, "concentration": 1}
            raw = json.dumps({"choices": [{"message": {"content": json.dumps(proposal)}}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv("VERITX_AI_BASE_URL", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("VERITX_AI_MODEL", "http-contract-fixture")
    monkeypatch.setenv("VERITX_AI_API_KEY", "secret-token-do-not-expose")
    yield requests, mode
    server.shutdown()
    server.server_close()
    thread.join()


def run_ai(client, pid, draft):
    response = client.post(f"/api/v1/projects/{pid}/ai-topology-search", json=pin(draft))
    assert response.status_code == 202, response.text
    job = response.json()
    return wait_for(lambda: client.get(f"/api/v1/jobs/{job['job_id']}").json(), lambda j: j["state"] in TERMINAL_STATES)


def test_http_loop_real_evidence_and_explicit_adoption(tmp_path, provider):
    with client_for(tmp_path) as client:
        pid, draft = project_for(client)
        done = run_ai(client, pid, draft)
        assert done["state"] == "COMPLETED", done
        assert len(provider[0]) == 4
        assert provider[0][1]["max_tokens"] == 4096
        prior = json.loads(provider[0][1]["messages"][1]["content"])["feedback"][0]
        assert prior["status"] == "EVALUATED" and prior["objective_values"]["completion_cycles"] > 0
        view = client.get(f"/api/v1/projects/{pid}/ai-topology-search/{done['job_id']}").json()
        first = view["attempts"][0]
        assert first["adoptable"] and first["requirements_pass"], view
        assert first["objective_values"]["completion_cycles"] > 0
        assert view["attempts"][1]["status"] == "REFUSED"  # duplicate
        assert view["attempts"][2]["status"] == "REFUSED"  # invented score
        assert all(row["objective_values"] == {} for row in view["attempts"][1:])
        assert client.get(f"/api/v1/projects/{pid}/draft").json() == draft
        assert client.get(f"/api/v1/projects/{pid}").json()["revisions"] == []
        response = client.post(f"/api/v1/projects/{pid}/ai-topology-search/{done['job_id']}/candidates/{first['candidate_id']}/adopt", json=pin(draft))
        assert response.status_code == 200, response.text
        adopted = response.json()["request"]
        previous = dict(draft["request"])
        previous["topology"] = adopted["topology"]
        assert adopted == previous
        assert adopted["topology"]["kind"] == "mesh"
        assert client.get(f"/api/v1/projects/{pid}").json()["revisions"] == []


def test_evidence_corruption_and_stale_adoption_refuse(tmp_path, provider):
    with client_for(tmp_path) as client:
        pid, draft = project_for(client)
        done = run_ai(client, pid, draft)
        directory = tmp_path / "projects" / "projects" / pid / "job-work" / done["job_id"]
        feedback = json.loads((directory / "feedback.json").read_text())
        row = feedback["attempts"][0]
        path = Path(row["evidence_path"])
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        view = client.get(f"/api/v1/projects/{pid}/ai-topology-search/{done['job_id']}").json()
        assert view["attempts"][0]["status"] == "EVIDENCE_INVALID", view
        assert view["attempts"][0]["objective_values"] == {}
        endpoint = f"/api/v1/projects/{pid}/ai-topology-search/{done['job_id']}/candidates/{row['candidate_id']}/adopt"
        assert client.post(endpoint, json=pin(draft)).status_code == 422
        path.write_bytes(original)
        changed = dict(draft["request"])
        changed["noc_controls"] = {**changed["noc_controls"], "link_width": 128}
        assert client.put(f"/api/v1/projects/{pid}/draft", json={"request": changed}).status_code == 200
        assert client.post(endpoint, json=pin(draft)).status_code == 409
        assert client.get(f"/api/v1/projects/{pid}/draft").json()["request"]["noc_controls"]["link_width"] == 128


def test_provider_error_is_redacted_and_not_a_topology_verdict(tmp_path, provider):
    provider[1]["error"] = True
    with client_for(tmp_path) as client:
        pid, draft = project_for(client)
        assert "secret-token" not in client.get("/api/v1/ai-topology-search/capabilities").text
        done = run_ai(client, pid, draft)
        assert done["state"] == "FAILED" and "HTTP 401" in done["error_message"], done
        assert "secret-token" not in json.dumps(done)
        assert len(provider[0]) == 1
        assert client.get(f"/api/v1/projects/{pid}/draft").json() == draft
