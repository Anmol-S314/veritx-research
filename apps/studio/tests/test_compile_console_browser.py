"""Compile console browser acceptance (P9: product-behavior testing).

Drives the Compile page of a real compiled revision in Chromium and proves
usefulness, not existence:

  * each of the seven tabs shows its own heading and hides the others;
  * at most one `Verification` heading is visible on the Compile page
    (the full inspector lives on Verify);
  * no empty `<tbody>` renders without an explicit empty state;
  * the deadlock wording follows the semantic state machine
    ("established" on PASS, never "claim is not established");
  * zero address ranges render empty-state prose with zero table rows;
  * a source/destination/class route query calls the route API, activates
    the Fabric tab and highlights the route;
  * an artifact detail opens with parent/proof identity and inspector
    navigation.

Compiles fixtures through the HTTP API (deterministic), then inspects in
the browser. Enabled only with ``VERITX_E2E=1`` (needs Node + Chromium).
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

def _chromium_launch_kwargs() -> dict:
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    candidates = [explicit] if explicit else []
    cache = Path.home() / ".cache" / "ms-playwright"
    if cache.is_dir():
        candidates.extend(
            str(p) for p in sorted(cache.glob(
                "chromium-*/chrome-linux64/chrome"), reverse=True))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return {"executable_path": candidate}
    for system in ("/usr/bin/google-chrome", "/usr/bin/chromium"):
        if Path(system).is_file():
            return {"executable_path": system}
    return {}

def _api(method: str, gw_port: int, path: str,
         body: dict | None = None) -> dict:
    import json
    data = json.dumps(body or {}).encode() if body is not None else None
    req = urllib.request.Request(
        f"http://127.0.0.1:{gw_port}{path}", data=data, method=method,
        headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())

def _compile_preset(gw_port: int, name: str,
                    mutate=None) -> tuple[str, str]:
    sys.path.insert(0, str(DSE))
    from veritx_dse.application.compile_intent import build_preset_request
    created = _api("POST", gw_port, "/api/v1/projects", {"name": name})
    pid = created["project"]["project_id"]
    request = build_preset_request("mesh4_hbm").to_dict()
    request.pop("design_hash", None)
    request.pop("guardrail_hash", None)
    if mutate:
        mutate(request)
    _api("PUT", gw_port, f"/api/v1/projects/{pid}/draft",
         {"request": request})
    snapshot = _api(
        "GET", gw_port,
        f"/api/v1/projects/{pid}/design?presentation=review")
    compiled = _api("POST", gw_port, f"/api/v1/projects/{pid}/compile",
                    {"expected_draft_design_hash":
                     snapshot["draft_identity"]["draft_design_hash"]})
    return pid, compiled["revision_id"]

TAB_HEADINGS = [
    ("Summary", "Declared → derived"),
    ("Mapping", "Mapping"),
    ("Fabric", "Fabric"),
    ("Routing", "Routing"),
    ("Resources", "Resources"),
    ("Address decode", "Address decode"),
    ("Provenance", "Provenance"),
]

def test_compile_console_seven_tabs(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    pid, _ = _compile_preset(gw_port, "console-seven")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/projects/{pid}/compile",
                      wait_until="networkidle")
            expect(page.get_by_role(
                "heading", name="Compile result")).to_be_visible(timeout=30000)

            expect(page.get_by_text("Compiled design")).to_be_visible()
            expect(page.get_by_text("Can I run this?")).to_be_visible()
            expect(page.get_by_text("Key findings")).to_be_visible()
            expect(page.get_by_text("Next actions")).to_be_visible()

            for tab, heading in TAB_HEADINGS:
                page.get_by_role("button", name=tab, exact=True).click()
                expect(page.locator(".compile-body").get_by_role(
                    "heading", name=heading).first).to_be_visible(
                        timeout=10000)
                others = [h for _, h in TAB_HEADINGS if h != heading]
                for other in others:
                    assert page.locator(
                        ".compile-body").get_by_role(
                            "heading", name=other).count() == 0, \
                        f"{other} visible while {tab} active"

            assert page.locator(
                '.compile-result h4:has-text("Verification")').count() <= 1

            empty = page.evaluate(
                "() => [...document.querySelectorAll("
                "'.compile-result tbody')].filter("
                "tb => tb.rows.length === 0).length")
            assert empty == 0, "blank table body rendered"

            body = page.locator(".compile-result").text_content() or ""
            assert "claim is not established" not in body
        finally:
            browser.close()

def test_compile_console_deadlock_pass_wording(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    pid, _ = _compile_preset(gw_port, "console-deadlock")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/projects/{pid}/compile",
                      wait_until="networkidle")
            expect(page.get_by_role(
                "heading", name="Compile result")).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Resources", exact=True).click()
            expect(page.locator(".compile-body").get_by_text(
                "DEADLOCK_FREE established")).to_be_visible(timeout=10000)
            body = page.locator(".compile-result").text_content() or ""
            assert "claim is not established" not in body
        finally:
            browser.close()

def test_compile_console_address_empty_state(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    def no_ranges(request):
        request["address_map"] = {"ranges": []}

    pid, _ = _compile_preset(gw_port, "console-addr-empty", mutate=no_ranges)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/projects/{pid}/compile",
                      wait_until="networkidle")
            expect(page.get_by_role(
                "heading", name="Compile result")).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Address decode",
                             exact=True).click()
            body = page.locator(".compile-body")
            expect(body.get_by_text(
                "No address ranges were declared for this design."
            )).to_be_visible(timeout=10000)
            assert body.locator("table").count() == 0, \
                "zero ranges rendered table rows"
        finally:
            browser.close()

def test_compile_console_route_query_highlights_fabric(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    pid, _ = _compile_preset(gw_port, "console-route")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/projects/{pid}/compile",
                      wait_until="networkidle")
            expect(page.get_by_role(
                "heading", name="Compile result")).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Routing", exact=True).click()
            with page.expect_response(
                    lambda r: "/route" in r.url and r.ok,
                    timeout=15000) as route_info:
                page.get_by_role(
                    "button", name="Overlay route on fabric").click()
            assert route_info.value.ok
            expect(page.locator(".compile-body").get_by_role(
                "heading", name="Fabric")).to_be_visible(timeout=10000)
            assert page.locator(".cv-link-route, .cv-router-route").count() \
                > 0, "no route highlight on the fabric"
            assert "not observed" in (
                page.locator(".compile-result").text_content() or "").lower()
        finally:
            browser.close()

def test_compile_console_artifact_detail_navigates(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    pid, _ = _compile_preset(gw_port, "console-artifact")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/projects/{pid}/compile",
                      wait_until="networkidle")
            expect(page.get_by_role(
                "heading", name="Compile result")).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Provenance", exact=True).click()
            page.locator(".artifact-jumps select").select_option(index=1)
            detail = page.locator(".artifact-jumps .inspector-detail")
            expect(detail).to_be_visible(timeout=10000)
            text = detail.text_content() or ""
            assert "identity" in text and "proved by" in text
            if detail.get_by_role("button", name="→ Fabric").count():
                detail.get_by_role("button", name="→ Fabric").click()
                expect(page.locator(".compile-body").get_by_role(
                    "heading", name="Fabric")).to_be_visible(timeout=10000)
        finally:
            browser.close()

def test_verify_page_inspects_obligations(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    pid, _ = _compile_preset(gw_port, "console-verify")
    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/projects/{pid}/verify",
                      wait_until="networkidle")
            expect(page.get_by_role(
                "heading",
                name="Verification certificate")).to_be_visible(timeout=30000)
            expect(page.locator(
                '.compile-result h4:has-text("Verification")')).to_be_visible(
                    timeout=10000)
            page.get_by_text("All obligations").click()
            assert page.locator(
                ".compile-result table tbody tr").count() >= 10, \
                "expected every obligation row"
            body = page.locator(".compile-result").text_content() or ""
            assert "DEADLOCK_FREE established" in body
            assert "claim is not established" not in body
        finally:
            browser.close()
