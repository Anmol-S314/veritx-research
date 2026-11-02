"""Real-process smoke tests. Set SROTA_SIDECAR to test the frozen executable."""
from __future__ import annotations

import json
import os
from pathlib import Path
import queue
import threading
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener, ProxyHandler

PROTOTYPE = Path(__file__).resolve().parents[1]
HTTP = build_opener(ProxyHandler({}))


class DesktopGatewayTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="srota-desktop-test-")
        cls.directory = Path(cls.temp.name)
        cls.command = ([str(Path(os.environ["SROTA_SIDECAR"]).resolve())]
                       if os.environ.get("SROTA_SIDECAR")
                       else [os.environ.get("SROTA_PYTHON", str(PROTOTYPE / ".desktop-venv/bin/python")
                                           if (PROTOTYPE / ".desktop-venv/bin/python").is_file() else sys.executable),
                             str(PROTOTYPE / "desktop/gateway.py")])
        cls.start()

    @classmethod
    def start(cls):
        cls.log = open(cls.directory / "backend.log", "a+")
        cls.process = subprocess.Popen(
            [*cls.command, "--data-dir", str(cls.directory / "data")],
            cwd=cls.directory, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=cls.log, start_new_session=os.name != "nt",
        )
        # Windows selectors cannot wait on anonymous subprocess pipes.
        ready = queue.Queue(maxsize=1)
        stdout = cls.process.stdout
        threading.Thread(target=lambda: ready.put(stdout.readline()), daemon=True).start()
        try:
            try:
                line = ready.get(timeout=120).decode()
            except queue.Empty:
                raise AssertionError("Gateway startup timed out") from None
            if not line.startswith("SROTA_READY "):
                raise AssertionError("Gateway exited before announcing readiness")
            cls.base = json.loads(line.removeprefix("SROTA_READY "))["base"]
        except Exception:
            cls.stop()
            raise AssertionError((cls.directory / "backend.log").read_text())

    @classmethod
    def stop(cls):
        cls.process.stdin.close()
        try:
            cls.process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            if os.name == "nt":
                cls.process.kill()
            else:
                os.killpg(cls.process.pid, signal.SIGKILL)
            cls.process.wait()
            raise AssertionError("Backend did not stop after its parent pipe closed")
        finally:
            cls.process.stdout.close()
            cls.log.close()

    @classmethod
    def tearDownClass(cls):
        try:
            cls.stop()
        finally:
            cls.temp.cleanup()

    def request(self, path, body=None, method=None, headers=None):
        data = json.dumps(body).encode() if body is not None else None
        request = Request(self.base + "/api/v1" + path, data=data,
                          method=method, headers={"Content-Type": "application/json", **(headers or {})})
        try:
            with HTTP.open(request, timeout=180) as response:
                return json.load(response)
        except HTTPError as error:
            detail = error.read().decode()
            error.close()
            raise AssertionError(f"{path}: {error.code}: {detail}") from error

    def test_01_security_and_catalogs(self):
        origin = urlsplit(self.base)
        for path in ("/api/v1/health", "/wrong/gw/api/v1/health"):
            with self.assertRaises(HTTPError) as error:
                HTTP.open(f"{origin.scheme}://{origin.netloc}{path}")
            self.assertEqual(error.exception.code, 404)
            error.exception.close()
        with self.assertRaises(HTTPError) as error:
            HTTP.open(Request(self.base + "/api/v1/health", headers={"Host": "attacker.example"}))
        self.assertEqual(error.exception.code, 400)
        error.exception.close()
        with HTTP.open(Request(self.base + "/api/v1/health", headers={"Origin": "tauri://localhost"})) as response:
            self.assertEqual(response.headers["Access-Control-Allow-Origin"], "tauri://localhost")
        with HTTP.open(Request(self.base + "/api/v1/health", headers={"Origin": "https://attacker.example"})) as response:
            self.assertIsNone(response.headers.get("Access-Control-Allow-Origin"))
        health = self.request("/health")
        self.assertEqual(health["status"], "ok")
        self.assertTrue(health["backends"]["BOOKSIM_STANDALONE"]["binary_present"])
        self.assertTrue(health["backends"]["ASTRA2_EMBEDDED_BOOKSIM"]["binary_present"])
        self.assertTrue(health["backends"]["RAMULATOR2_HBM3_V1"]["binary_present"])
        self.assertTrue(self.request("/catalog/fabric-presets")["presets"])
        self.assertTrue(self.request("/capabilities"))
        # Native UI startup probes topology truth, which needs bundled examples.
        self.assertTrue(self.request("/loom/capabilities"))

    def wait_for_job(self, job):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            job = self.request(f"/jobs/{job['job_id']}")
            if job["state"] in {"COMPLETED", "FAILED", "CANCELLED"}:
                break
            time.sleep(0.15)
        if job["state"] != "COMPLETED":
            logs = self.request(f"/jobs/{job['job_id']}/log")
            self.fail(f"{job}\n{logs}")
        return job

    def test_02_project_compile_evaluate_persist(self):
        project = self.request("/projects/from-preset", {"preset_id": "torus25", "name": "Desktop smoke"})
        project_id = project["project"]["project_id"]
        draft = self.request(f"/projects/{project_id}/draft")
        compiled = self.request(f"/projects/{project_id}/compile", {
            "expected_draft_design_hash": draft["design_hash"],
        })
        self.assertEqual(compiled["compilation"]["status"], "COMPILED", compiled)
        revision_id = compiled["revision_id"]
        self.assertTrue(self.request(f"/revisions/{revision_id}/topology")["routers"])
        job = self.request(f"/revisions/{revision_id}/evaluate", {
            "backend": "BOOKSIM_STANDALONE", "questions": ["NETWORK_COMPLETION"],
        })
        job = self.wait_for_job(job)
        run_id = job["result"]["run_id"]
        run = self.request(f"/runs/{run_id}")
        self.assertEqual(run["status"], "EVALUATED", run)
        artifacts = self.request(f"/runs/{run_id}/artifacts")
        files = artifacts["bundle"]["files"]
        self.assertTrue(files)
        from urllib.parse import urlencode
        with HTTP.open(self.base + f"/api/v1/runs/{run_id}/artifact?" + urlencode({"path": next(iter(files))})) as response:
            self.assertTrue(response.read())
        # The URL capability works for EventSource without custom auth headers.
        with HTTP.open(self.base + f"/api/v1/jobs/{job['job_id']}/events", timeout=10) as response:
            self.assertEqual(response.headers.get_content_type(), "text/event-stream")
            self.assertTrue(response.readline())
        self.stop()
        old_base = self.base
        self.start()
        self.assertNotEqual(old_base, self.base)
        self.assertEqual(self.request(f"/projects/{project_id}")["project"]["name"], "Desktop smoke")
        self.assertEqual(self.request(f"/runs/{run_id}")["status"], "EVALUATED")

    def test_03_isolated_compile_worker(self):
        project = self.request("/projects/from-preset", {"preset_id": "torus25"})
        project_id = project["project"]["project_id"]
        draft = self.request(f"/projects/{project_id}/draft")
        job = self.request(f"/projects/{project_id}/compile-jobs", {
            "expected_draft_design_hash": draft["design_hash"],
        })
        job = self.wait_for_job(job)
        self.assertTrue(self.request(f"/revisions/{job['result']['revision_id']}/topology")["routers"])

    def test_04_native_python_bindings(self):
        code = """
import sys
from veritx_dse.core.paths import REPO
sys.path.insert(0, str(REPO / "third_party/ramulator2/python"))
from ramulator._ramulator import Simulation
from chakra.schema.protobuf import et_def_pb2
assert et_def_pb2.Node().SerializeToString() == b""
# The packaged app must be able to read the ASTRA parser surface it validates
# embedded fabric configs against; a missing file is a refusal, not a warning.
from veritx_dse.backend.astra_machine import declared_runtime_config_fields
assert declared_runtime_config_fields(), "ASTRA config surface is empty"
"""
        result = subprocess.run([*self.command, "-c", code], cwd=self.directory,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
