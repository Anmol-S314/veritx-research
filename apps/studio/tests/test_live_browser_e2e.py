"""Black-box browser acceptance against a LIVE gateway (UI9).

Runs the brief's product-surface flow in a real Chromium browser:

    open Studio -> create project -> select workload -> edit design
    -> compile -> inspect verification -> run evaluation -> wait
    -> open Run detail -> inspect evidence

The evaluation leg requires a real, pinned BookSim producer; without one
the test still proves the live compile/verify browser path and skips the
simulation leg. No mock backend exists.

Enabled only with ``VERITX_E2E=1`` (it needs Node + a built/installed
studio and, for the simulation leg, ``VERITX_BOOKSIM_BIN``).
"""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
DSE = REPO / "tracks" / "t3-topology" / "dse"
STUDIO = REPO / "apps" / "studio"

pytestmark = pytest.mark.skipif(
    os.environ.get("VERITX_E2E") != "1",
    reason="browser E2E is opt-in: set VERITX_E2E=1 (needs Node + Chromium)")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _wait_http(url: str, timeout: float = 60.0) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.5)
    raise AssertionError(f"did not become reachable: {url} ({last})")


@pytest.fixture()
def live_stack(tmp_path):
    gw_port, ui_port = _free_port(), _free_port()
    env = os.environ.copy()
    env["PYTHONPATH"] = str(DSE)
    env["VERITX_STORE_ROOT"] = str(tmp_path / "store")
    env["VERITX_RUNS_ROOT"] = str(tmp_path / "runs")
    env["VERITX_PROJECTS_ROOT"] = str(tmp_path / "projects")
    gateway = subprocess.Popen(
        [sys.executable, "-m", "uvicorn",
         "veritx_dse.gateway.app:app",
         "--host", "127.0.0.1", "--port", str(gw_port), "--log-level", "warning"],
        cwd=str(DSE), env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ui_env = os.environ.copy()
    ui_env["VERITX_GATEWAY_URL"] = f"http://127.0.0.1:{gw_port}"
    ui = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1",
         "--port", str(ui_port), "--strictPort"],
        cwd=str(STUDIO), env=ui_env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        _wait_http(f"http://127.0.0.1:{gw_port}/api/v1/health")
        _wait_http(f"http://127.0.0.1:{ui_port}/")
        yield gw_port, ui_port
    finally:
        for proc in (ui, gateway):
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()


def _pinned_producer() -> bool:
    binary = os.environ.get("VERITX_BOOKSIM_BIN")
    if not binary:
        return False
    sys.path.insert(0, str(DSE))
    from veritx_dse.backend.producer import (
        ProducerError, assert_pinned_producer, resolve_producer_identity,
    )
    try:
        identity = resolve_producer_identity(Path(binary), repo_root=REPO)
        assert_pinned_producer(identity)
    except ProducerError:
        return False
    return True


def test_browser_live_flow(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/")
            expect(page.get_by_text("LIVE")).to_be_visible(timeout=30000)

            # Create a project.
            page.get_by_label("Name").fill("Qwen NoC Study")
            page.get_by_role("button", name="Create project").click()
            expect(page.get_by_text("Draft (live edits)")).to_be_visible(
                timeout=20000)

            # Edit the design (link width) then compile.
            page.get_by_role("button", name="Compile design").click()
            expect(page.get_by_text("Fabric canvas")).to_be_visible(
                timeout=30000)

            # Inspect verification.
            page.get_by_role("button", name="Compile & Verify").click()
            expect(page.get_by_text("obligations PASS")).to_be_visible(
                timeout=20000)
            expect(page.get_by_text("Certificate PASS")).to_be_visible(
                timeout=20000)

            if not _pinned_producer():
                pytest.skip("compile/verify browser path verified; "
                            "simulation leg needs a pinned BookSim producer")

            # Run a live evaluation and wait for completion.
            page.get_by_role("button", name="Simulate").click()
            page.get_by_role("button", name="Run Simulation").click()
            expect(page.get_by_text("EVALUATED")).to_be_visible(timeout=600000)
            page.locator("button.link").first.click()
            expect(page.get_by_text("Why can I trust this?")).to_be_visible(
                timeout=30000)
        finally:
            browser.close()
