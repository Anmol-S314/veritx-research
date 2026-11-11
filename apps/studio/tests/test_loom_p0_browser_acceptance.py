"""Opt-in Loom browser acceptance and truthful-blocker probes.

Runs the real Studio + gateway, with isolated temporary server state (no
mocked project API). The F01 test establishes graph edit/export/reopen; other
cases explicitly record partial behavior or blockers, not complete flows.
No test claims Tauri desktop behavior.

Opt in with VERITX_LOOM_E2E=1; requires Python uvicorn, Playwright Chromium,
Node/npm, and the repository DSE gateway dependencies.
"""
from __future__ import annotations

import json
import os
import re
import signal
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
BROWSER_TMP_ROOT = Path.home() / ".cache" / "loom-e2e-browser-tmp"

pytestmark = pytest.mark.skipif(
    os.environ.get("VERITX_LOOM_E2E") != "1",
    reason="opt-in browser acceptance; set VERITX_LOOM_E2E=1",
)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_http(url: str, timeout: float = 60) -> None:
    deadline = time.time() + timeout
    last: Exception | None = None
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status < 500:
                    return
        except Exception as exc:  # noqa: BLE001
            last = exc
        time.sleep(0.25)
    raise AssertionError(f"service did not become ready: {url}: {last}")


@pytest.fixture(scope="module")
def studio_stack(tmp_path_factory):
    # Keep Chromium's per-launch profile off constrained /tmp mounts; this is
    # important in shared runner hosts with a per-user /tmp quota.
    BROWSER_TMP_ROOT.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = str(BROWSER_TMP_ROOT)
    tmp_path = tmp_path_factory.mktemp("loom-browser-stack")
    gateway_port, ui_port = _free_port(), _free_port()
    env = os.environ.copy()
    env.update({
        "PYTHONPATH": str(DSE),
        "VERITX_STORE_ROOT": str(tmp_path / "store"),
        "VERITX_RUNS_ROOT": str(tmp_path / "runs"),
        "VERITX_PROJECTS_ROOT": str(tmp_path / "projects"),
    })
    gateway = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "veritx_dse.gateway.app:app",
         "--host", "127.0.0.1", "--port", str(gateway_port),
         "--log-level", "warning"],
        cwd=DSE, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    ui_env = os.environ.copy()
    ui_env["VERITX_GATEWAY_URL"] = f"http://127.0.0.1:{gateway_port}"
    ui = subprocess.Popen(
        ["npm", "run", "dev", "--", "--host", "127.0.0.1",
         "--port", str(ui_port), "--strictPort"],
        cwd=STUDIO, env=ui_env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        _wait_http(f"http://127.0.0.1:{gateway_port}/api/v1/health")
        _wait_http(f"http://127.0.0.1:{ui_port}/")
        yield ui_port
    finally:
        for process in (ui, gateway):
            if process.poll() is None:
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait(timeout=5)


def _chromium_kwargs() -> dict:
    explicit = os.environ.get("PLAYWRIGHT_CHROMIUM_EXECUTABLE")
    candidates = [explicit] if explicit else []
    candidates.extend(("/usr/bin/google-chrome", "/usr/bin/chromium"))
    candidates.extend(str(p) for p in sorted(
        (Path.home() / ".cache" / "ms-playwright").glob(
            "chromium-*/chrome-linux64/chrome"), reverse=True))
    for path in candidates:
        if path and Path(path).is_file():
            return {"executable_path": path}
    return {}


def test_f01_mesh_edit_validate_export_reopen_is_semantically_stable(
        studio_stack, tmp_path):
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page(accept_downloads=True)
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            expect(page.get_by_role("button", name="Create project")).to_be_enabled()
            page.get_by_label("Name").fill("F01 graph persistence acceptance")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            page.get_by_role("navigation", name="Workspaces").get_by_text(
                "Architecture", exact=True).click()
            page.get_by_role("link", name="Fabric canvas", exact=True).click()
            canvas = page.get_by_test_id("graph-canvas")
            expect(canvas).to_be_visible(timeout=20000)
            page.get_by_label("graph preset").select_option("8x8-mesh")
            initial_nodes = page.locator("[data-node-id]").count()
            initial_links = page.locator("[data-testid^='link-']").count()
            assert initial_nodes == 64, f"expected seeded 8x8 mesh, got {initial_nodes}"
            assert initial_links > 0

            page.get_by_role("button", name="node (auto-wired)").click()
            expect(page.locator("[data-node-id]")).to_have_count(65)
            expect(page.get_by_label("graph preset")).to_have_value("custom")
            new_node = page.locator("[data-node-id]").last.get_attribute("data-node-id")
            assert page.locator("[data-testid^='link-']").count() == initial_links + 1

            # Connect by dragging from the new node's east port to a target
            # node's west port through the canvas pointer handlers.
            source_port = page.get_by_test_id(f"port-{new_node}-e").bounding_box()
            target_port = page.get_by_test_id("port-n2-w").bounding_box()
            assert source_port and target_port
            page.mouse.move(source_port["x"] + source_port["width"] / 2,
                            source_port["y"] + source_port["height"] / 2)
            page.mouse.down()
            page.mouse.move(target_port["x"] + target_port["width"] / 2,
                            target_port["y"] + target_port["height"] / 2,
                            steps=8)
            page.mouse.up()
            assert page.locator("[data-testid^='link-']").count() == initial_links + 2

            # SVG edges use transparent hit paths. Dispatch a click to the last
            # actual edge path to exercise the React selection handler in the
            # dense 8x8 canvas without brittle pointer coordinates.
            page.locator("[data-testid^='link-']").last.dispatch_event("click")
            stages = page.get_by_label("inspector stages")
            expect(stages).to_be_visible()
            stages.fill("3")
            stages.press("Tab")
            expect(stages).to_have_value("3")
            expect(page.get_by_text("No issue in the graph.")).to_be_visible()

            with page.expect_download() as download_info:
                page.get_by_role("button", name="save project.json").click()
            download = download_info.value
            first_file = tmp_path / "graph-first.json"
            download.save_as(first_file)
            original = json.loads(first_file.read_text())
            graph = original["graph"]
            assert len(graph["nodes"]) == 65
            assert all(e["src"] in {n["id"] for n in graph["nodes"]}
                       and e["dst"] in {n["id"] for n in graph["nodes"]}
                       for e in graph["edges"]), "dangling edge reference"
            assert any(e.get("pipelineStages") == 3 for e in graph["edges"])

            page.locator("input[type=file][accept='.json']").set_input_files(
                str(first_file))
            expect(page.locator("[data-node-id]")).to_have_count(65)
            expect(page.get_by_text("No issue in the graph.")).to_be_visible()
            with page.expect_download() as second_download_info:
                page.get_by_role("button", name="save project.json").click()
            second_download = second_download_info.value
            second_file = tmp_path / "graph-reopened.json"
            second_download.save_as(second_file)
            reopened = json.loads(second_file.read_text())
            assert reopened == original, "export/reopen changed graph semantics"

            # The edited stage is faithfully stored, but the adapter must not
            # claim a run can consume it when lowering refuses this field.
            writes: list[str] = []
            page.on("request", lambda request: writes.append(request.url)
                   if request.method == "PUT" or "/compile-jobs" in request.url
                   else None)
            refusal = page.get_by_role("alert")
            expect(refusal).to_be_visible(timeout=10000)
            assert "per-edge pipelineStages are not materialized" in refusal.inner_text()
            expect(page.get_by_role("button", name="save + compile")).to_be_disabled()
            assert writes == [], f"refused pipeline edit made server writes: {writes}"
        finally:
            browser.close()


def test_f02_catalog_ui_explicitly_disclaims_stampable_ip_contract(studio_stack):
    """Browser-observe why F02 cannot currently pass; not an F02 pass test.

    The UI's catalog is agent-kind metadata, with no vendor/IP provenance or
    stamping surface. Keep this as guardrail evidence against calling this
    primitive list a qualified IP catalog.
    """
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F02 catalog capability probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/catalog")
            expect(page.get_by_role("heading", name="Loom workspace: catalog")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_role("heading", name="Not in the contract")
                   ).to_be_visible()
            expect(page.get_by_text(
                "Vendor, part number, version, licence", exact=False)
                   ).to_be_visible()
            expect(page.get_by_text(
                "Per-IP parameters (array rows, SRAM, channels)", exact=False)
                   ).to_be_visible()
            assert page.get_by_role("button", name="stamp IP").count() == 0
            expect(page.get_by_role("button", name=re.compile("replace", re.I))
                   ).to_have_count(0)
            expect(page.get_by_role("link", name=re.compile("replace", re.I))
                   ).to_have_count(0)
            compute = page.locator(".loom-card").filter(has_text="compute tile")
            expect(compute).to_be_visible()
            expect(compute.get_by_text("64", exact=True).first).to_be_visible()
            compute.click()
            expect(page.get_by_text(
                "A kind is a member of the engine's closed", exact=False)
                   ).to_be_visible()
            instance_link = page.get_by_role(
                "link", name=re.compile(r"See the 64 instance rows"))
            expect(instance_link).to_be_visible()
            instance_link.click()
            expect(page.get_by_role("heading", name="Loom workspace: agents")
                   ).to_be_visible(timeout=20000)
            agent_rows = page.locator(".loom-table tbody tr")
            expect(agent_rows).to_have_count(72)
            expect(agent_rows.first).to_contain_text("compute_tile")
            agent_rows.first.click()
            expect(page.get_by_role("heading", name="Agent inspector", exact=True)
                   ).to_be_visible()
            expect(page.get_by_label("role n1", exact=True)
                   ).to_have_value("compute_tile")
            expect(page.get_by_label("ports n1", exact=True)).to_have_value("5")
            expect(page.get_by_label("Selection inspector").get_by_text(
                "agent:g0-i0", exact=True)).to_be_visible()
            expect(page.get_by_text("UNATTACHED", exact=True).last
                   ).to_be_visible()
            editor = page.get_by_role("group", name="Edit agent group 0")
            data_width = editor.get_by_label("data width (bits)")
            data_width.fill("512")
            expect(editor.get_by_text("UNSAVED", exact=True)).to_be_visible()
            editor.get_by_role("button", name="Save draft").click()
            expect(editor.get_by_text(
                "Working copy matches the server draft.", exact=True)
                   ).to_be_visible(timeout=15000)
            page.reload()
            expect(page.get_by_role("heading", name="Agent inspector", exact=True)
                   ).to_be_visible(timeout=20000)
            editor = page.get_by_role("group", name="Edit agent group 0")
            expect(editor.get_by_label("data width (bits)")).to_have_value("512")
            expect(page.get_by_label("role n1", exact=True)
                   ).to_have_value("compute_tile")
            expect(page.get_by_label("ports n1", exact=True)).to_have_value("5")
            expect(page.get_by_label("Selection inspector").get_by_text(
                "agent:g0-i0", exact=True)).to_be_visible()
        finally:
            browser.close()


def test_no_run_simulation_offers_evaluation_without_mock_player(studio_stack):
    """Mock playback was removed from the simulation page: a measured-evidence
    page carries no MOCK geometry player. A fresh project gets the empty state
    with a link to evaluation, and nothing labeled MOCK."""

    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("no-run simulation probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/simulation")
            expect(page.get_by_role("heading", name="Loom workspace: simulation")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_text("No run on this project", exact=False)
                   ).to_be_visible()
            expect(page.get_by_role("heading", name="Mock playback (beta)")
                   ).to_have_count(0)
            expect(page.get_by_text("MOCK trace", exact=True)).to_have_count(0)
            expect(page.get_by_role("link", name="Open evaluation")
                   ).to_be_visible()
            expect(page.get_by_role("heading", name="Unavailable readouts")
                   ).to_be_visible()
        finally:
            browser.close()


def test_f14_problem_panel_reports_missing_revision_not_recovery(studio_stack):
    """F14 blocker probe: absence of engine issue artifacts is not a fix."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F14 no issue artifact probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/simulation")
            expect(page.get_by_role("heading", name="Loom workspace: simulation")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_text("No compiled revision", exact=True)
                   ).to_be_visible()
            expect(page.get_by_text(
                "This project has no certified revision", exact=False)
                   ).to_be_visible()
            expect(page.get_by_text("No run on this project", exact=False)
                   ).to_be_visible()
        finally:
            browser.close()


def test_f14_review_reports_unsupported_rcu_then_clears_after_fix(studio_stack):
    """F14 partial: a real blocking design finding clears after intent is fixed."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            base = f"http://127.0.0.1:{studio_stack}"
            page.goto(base + "/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F14 unsupported RCU recovery probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            page.goto(f"{base}/projects/{project_id}/overview")
            page.get_by_role("tab", name="Topology graph").click()
            page.locator("svg.canvas rect.cv-router").first.click()
            inspector = page.get_by_role(
                "region", name="Draft fabric inspector")
            rcu = inspector.get_by_label("RCU (in-network reduction)")
            assert not rcu.is_checked(), "probe expects the default RCU intent off"
            with page.expect_response(lambda response:
                    response.request.method == "PUT"
                    and f"/projects/{project_id}/draft" in response.url) as saved:
                rcu.click()
            assert saved.value.ok

            page.get_by_role("link", name="System design", exact=True).click()
            page.get_by_role("link", name="Review Design").click()
            expect(page.get_by_text("UNSUPPORTED_RCU_EXECUTION", exact=True)
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name="Compile Design")
                   ).to_be_disabled()
            page.get_by_role("button", name="fabric", exact=True).click()
            fabric_section = page.get_by_role(
                "navigation", name="Design sections").get_by_role(
                    "button", name="Fabric", exact=True)
            expect(fabric_section).to_have_attribute("aria-current", "true")

            page.goto(f"{base}/projects/{project_id}/overview")
            page.get_by_role("tab", name="Topology graph").click()
            page.locator("svg.canvas rect.cv-router").first.click()
            inspector = page.get_by_role(
                "region", name="Draft fabric inspector")
            rcu = inspector.get_by_label("RCU (in-network reduction)")
            expect(rcu).to_be_checked()
            with page.expect_response(lambda response:
                    response.request.method == "PUT"
                    and f"/projects/{project_id}/draft" in response.url) as saved:
                rcu.click()
            assert saved.value.ok

            page.get_by_role("link", name="System design", exact=True).click()
            page.get_by_role("link", name="Review Design").click()
            expect(page.get_by_text("UNSUPPORTED_RCU_EXECUTION", exact=True)
                   ).to_have_count(0)
            expect(page.get_by_role("button", name="Compile Design")
                   ).to_be_enabled()
            page.get_by_role("button", name="Compile Design").click()
            expect(page.get_by_role("heading", name="Compile result")
                   ).to_be_visible(timeout=45000)
        finally:
            browser.close()


def test_f13_comparison_stays_empty_without_two_evaluated_runs(studio_stack):
    """F13 blocker probe: no run pair means no fabricated metric comparison."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            compare_requests: list[str] = []
            page.on("request", lambda request: compare_requests.append(request.url)
                   if "/api/v1/compare?" in request.url else None)
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F13 no evaluated runs probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/simulation")
            expect(page.get_by_role("heading", name="Run comparison")
                   ).to_be_visible(timeout=20000)
            for label in ("run a", "run b"):
                picker = page.locator(".loom-field").filter(has_text=label).locator("select")
                expect(picker).to_be_visible()
                expect(picker).to_have_value("")
                expect(picker.locator("option")).to_have_count(1)
                expect(picker.locator("option")).to_have_text("no evaluated run")
            expect(page.get_by_text("comparable", exact=True)).to_have_count(0)
            assert not compare_requests, (
                "comparison API must not be called without two evaluated runs")
        finally:
            browser.close()


def test_f15_replay_is_not_offered_without_a_historical_run(studio_stack):
    """F15 blocker probe: no stored run means no replay claim or request."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            replay_requests: list[str] = []
            page.on("request", lambda request: replay_requests.append(request.url)
                   if "/replay" in request.url.lower() else None)
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F15 no historical run probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/simulation")
            expect(page.get_by_text("No run on this project", exact=False)
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name=re.compile("replay", re.I))
                   ).to_have_count(0)
            expect(page.get_by_role("link", name=re.compile("replay", re.I))
                   ).to_have_count(0)
            assert not replay_requests, (
                "replay must not be requested without a stored historical run")
        finally:
            browser.close()


def test_f17_support_bundle_is_not_claimed_without_a_failed_run(studio_stack):
    """F17 blocker probe: a no-run project cannot export a failure bundle."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            bundle_requests: list[str] = []
            page.on("request", lambda request: bundle_requests.append(request.url)
                   if "bundle" in request.url.lower() else None)
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F17 no failed run probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/simulation")
            expect(page.get_by_text("No run on this project", exact=False)
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name=re.compile("support bundle", re.I))
                   ).to_have_count(0)
            expect(page.get_by_role("link", name=re.compile("support bundle", re.I))
                   ).to_have_count(0)
            assert not bundle_requests, (
                "no failure bundle request is valid without a failed run")
        finally:
            browser.close()


def test_f22_truncated_trace_reports_exact_line_and_keeps_valid_prefix(studio_stack, tmp_path):
    """F22 partial: the real JSONL parser reports corruption without completion."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            trace_import_requests: list[str] = []
            page.on("request", lambda request: trace_import_requests.append(request.url)
                   if "trace" in request.url.lower()
                   and request.method in {"POST", "PUT"} else None)
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F22 no trace artifact probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/simulation")
            expect(page.get_by_text("No run on this project", exact=False)
                   ).to_be_visible(timeout=20000)
            trace_path = tmp_path / "truncated-trace.jsonl"
            trace_path.write_text(
                json.dumps({"cycle": 0, "phase": "prefill",
                            "nodeLoad": {"n1": 1}, "edgeUtil": {},
                            "stalls": {}}) + "\n{" , encoding="utf-8")
            page.get_by_label("Import trace JSONL").set_input_files(str(trace_path))
            expect(page.get_by_role("alert")).to_contain_text(
                "Trace import stopped: trace line 2: invalid JSON", timeout=10000)
            expect(page.get_by_text("USER-PROVIDED TRACE", exact=False)
                   ).to_be_visible()
            expect(page.get_by_text("1 valid frames retained", exact=False)
                   ).to_be_visible()
            expect(page.get_by_text("No run on this project", exact=False)
                   ).to_be_visible()
            expect(page.get_by_role("button", name="Use mock playback instead")
                   ).to_be_visible()
            assert not trace_import_requests, (
                "local trace parsing must not invent a backend run or upload")
        finally:
            browser.close()


def test_f02_hbm3e_gateway_stamp_persists_provenance_and_address_intent(studio_stack):
    """F02 API slice: the hidden product stamp endpoint persists HBM identity."""
    from playwright.sync_api import expect, sync_playwright

    from dataclasses import replace
    sys.path.insert(0, str(DSE))
    from veritx_dse.model.compile_request_v5 import CompileRequestV5

    example_path = DSE / "examples" / "tensor_demand_v5.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    parsed = CompileRequestV5.from_dict(example["design"])
    # Stamping appends a fifth agent group to the example; increase declared
    # concentration to keep the 2x2 topology's eight seats sufficient.
    v5_request = replace(parsed, base_v4=replace(
        parsed.base_v4, topology=replace(
            parsed.base_v4.topology, concentration=2))).to_dict()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            base = f"http://127.0.0.1:{studio_stack}"
            page.goto(base + "/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F02 HBM3E API stamp probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            put = page.request.put(
                f"{base}/gw/api/v1/projects/{project_id}/draft",
                data={"request": v5_request})
            assert put.status == 200, put.text()
            original = put.json()
            body = {
                "expected_draft_design_hash": original["design_hash"],
                "template_id": "hbm3e-memory", "instance_id": "mem0",
                "address_base": 0xA000, "address_size": 16,
                "clock_domain": "network", "power_domain": "DEFAULT",
                "initiator_group_index": 0, "access_permission": "RW",
            }
            stamp = page.request.post(
                f"{base}/gw/api/v1/projects/{project_id}/draft/ip-templates/stamp",
                data=body)
            assert stamp.status == 200, stamp.text()
            stamped = stamp.json()
            assert stamped["design_hash"] != original["design_hash"]
            stale_stamp = page.request.post(
                f"{base}/gw/api/v1/projects/{project_id}/draft/ip-templates/stamp",
                data=body)
            assert stale_stamp.status == 409
            unchanged = page.request.get(
                f"{base}/gw/api/v1/projects/{project_id}/draft").json()
            assert unchanged["design_hash"] == stamped["design_hash"]
            missing_item = page.request.post(
                f"{base}/gw/api/v1/projects/{project_id}/draft/ip-templates/stamp",
                data={**body,
                      "expected_draft_design_hash": stamped["design_hash"],
                      "template_id": "retired-hbm3e-v0"})
            assert missing_item.status == 400, missing_item.text()
            still_stamped = page.request.get(
                f"{base}/gw/api/v1/projects/{project_id}/draft").json()
            assert still_stamped["design_hash"] == stamped["design_hash"]

            page.reload()
            saved_response = page.request.get(
                f"{base}/gw/api/v1/projects/{project_id}/draft")
            assert saved_response.status == 200
            saved = saved_response.json()
            assert saved["design_hash"] == stamped["design_hash"]
            request = saved["request"]
            base_v4 = request["base_v4"]
            hbm = base_v4["agents"][-1]
            assert (hbm["kind"], hbm["ip_template_id"],
                    hbm["ip_template_version"], hbm["ip_instance_id"]) == (
                        "hbm_controller", "hbm3e-memory", "1.0", "mem0")
            assert (hbm["data_width"], hbm["addr_width"], hbm["protocol"]) == (
                256, 64, "AXI")
            assert (hbm["clock_domain"], hbm["power_domain"]) == (
                "network", "DEFAULT")
            address = base_v4["address_map"]["ranges"][-1]
            assert address == {
                "name": "mem0", "base": 0xA000, "size": 16,
                "target_agent_idx": len(base_v4["agents"]) - 1,
            }
            intent = request["agent_intents"][-1]
            assert intent["agent_group_index"] == len(base_v4["agents"]) - 1
            assert intent["transaction_clock_domain"] == "network"
            rule = request["access_policy"]["rules"][-1]
            assert (rule["rule_id"], rule["initiator"], rule["target"],
                    rule["permission"]) == (
                        "ip:mem0", "group:0",
                        f"group:{len(base_v4['agents']) - 1}", "RW")

            page.goto(f"{base}/projects/{project_id}/design")
            expect(page.get_by_role("heading", name="Design workspace")
                   ).to_be_visible(timeout=20000)
            page.get_by_role("link", name="Review Design").click()
            expect(page.get_by_role("heading", name="You are about to compile")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_role("heading", name="V5 declarations")
                   ).to_be_visible()
            page.get_by_text("crossings · declaration JSON", exact=True).click()
            crossing_json = page.get_by_label("crossings")
            expect(crossing_json).to_have_value(re.compile(r'"core-network"'))
            expect(crossing_json).to_have_value(re.compile(r'"ASYNC_FIFO"'))
            expect(crossing_json).to_have_value(re.compile(r'"depth": 4'))
            compile_button = page.get_by_role("button", name="Compile Design")
            expect(compile_button).to_be_enabled()
            with page.expect_response(lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith(
                        f"/projects/{project_id}/compile-jobs"))) as compile_info:
                compile_button.click()
            compile_response = compile_info.value
            assert compile_response.status == 202, compile_response.text()
            job_id = compile_response.json()["job_id"]
            expect(page.get_by_role("heading", name="Compile result")
                   ).to_be_visible(timeout=60000)
            job = page.request.get(
                f"{base}/gw/api/v1/jobs/{job_id}")
            assert job.status == 200
            job_view = job.json()
            assert job_view["state"] == "COMPLETED"
            revision_id = job_view["result"]["revision_id"]
            revision = page.request.get(
                f"{base}/gw/api/v1/revisions/{revision_id}")
            assert revision.status == 200
            assert revision.json()["compilation"]["status"] == "COMPILED"

            page.goto(f"{base}/projects/{project_id}/loom/agents")
            expect(page.get_by_role("heading", name="Loom workspace: agents")
                   ).to_be_visible(timeout=20000)
            page.locator("#loom-agent-search").fill("hbm_controller")
            hbm_row = page.locator(".loom-table tbody tr").filter(
                has_text="hbm_controller").last
            expect(hbm_row).to_be_visible()
            hbm_row.click()
            selected = page.get_by_label("Selection inspector")
            expect(selected.get_by_text(
                "agent:g4-i0", exact=True)).to_be_visible()
            expect(selected).to_contain_text("hbm_controller")
            expect(selected).to_contain_text("ATTACHED")
            expect(selected).to_contain_text("256 bits")
            expect(selected).to_contain_text("64 bits")
        finally:
            browser.close()


def test_f03_product_revision_shows_canonical_hop_preview(studio_stack):
    """F03 slice: a product-certified revision can expose a server route."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Workload").select_option(
                "llama-dense-8b-64tiles")
            page.get_by_label("Name").fill("F03 certified path preview probe")
            page.get_by_role("button", name="Create project").click()
            expect(page.get_by_role("heading", name="Workload")
                   ).to_be_visible(timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            page.get_by_role("link", name="System design", exact=True).click()
            expect(page.get_by_role("heading", name="Design workspace")
                   ).to_be_visible(timeout=20000)
            page.get_by_role("link", name="Review Design").click()
            page.get_by_role("button", name="Compile Design").click()
            expect(page.get_by_role("heading", name="Compile result")
                   ).to_be_visible(timeout=45000)
            base = f"http://127.0.0.1:{studio_stack}"
            project_view = page.request.get(
                f"{base}/gw/api/v1/projects/{project_id}").json()
            revision_id = project_view["active_revision_id"]
            revision = page.request.get(
                f"{base}/gw/api/v1/revisions/{revision_id}").json()
            assert revision["compilation"]["status"] == "COMPILED"
            compile_result = page.request.get(
                f"{base}/gw/api/v1/revisions/{revision_id}/compile-result")
            assert compile_result.status == 200
            resources = compile_result.json()["groups"]["resources"]
            class_vcs = dict(resources["traffic_class_to_vcs"])

            page.goto(f"{base}/projects/"
                      f"{project_id}/loom/access")
            expect(page.get_by_role("heading", name="Loom workspace: access")
                   ).to_be_visible(timeout=20000)
            show_path = page.get_by_role("button", name="Show path")
            expect(show_path).to_be_enabled(timeout=30000)
            with page.expect_response(lambda response: (
                    response.request.method == "GET"
                    and f"/revisions/{revision_id}/route" in response.url
            )) as route_info:
                show_path.click()
            route = route_info.value.json()
            assert route["terminates"] is True
            route_vcs = [vc for vc, routing_class
                         in resources["vc_to_routing_class"]
                         if routing_class == route["routing_class"]]
            assert route_vcs
            assert set(route_vcs) <= set(resources["vc_ids"])
            allocated_vcs = {vc for vcs in class_vcs.values() for vc in vcs}
            assert set(route_vcs) & allocated_vcs
            assert all("vc_id" not in hop and "vc" not in hop
                       for hop in route["hops"])
            right = page.locator(".loom-rail-right")
            terminates = right.locator(".kv").filter(has_text="terminates")
            expect(terminates).to_contain_text("yes", timeout=30000)
            hops = right.locator("table.tbl tbody tr")
            expect(hops.first).to_be_visible(timeout=30000)
            assert hops.count() > 0, "canonical route should expose at least one hop"
            expect(hops.first).to_contain_text("R")
            expect(hops.first).to_contain_text("→")
            expect(right.get_by_text("route", exact=True).first).to_be_visible()
        finally:
            browser.close()


def test_f21_gateway_roundtrip_preserves_canonical_migration_provenance(studio_stack):
    """A model-produced V4→V5 migration record survives the real Studio/API roundtrip.

    The fixture conversion uses the existing canonical helper; this does not
    imply a user-facing open/preview/migrate/diff workflow exists.
    """
    from playwright.sync_api import expect, sync_playwright

    sys.path.insert(0, str(DSE))
    from veritx_dse.model.compile_request_v4 import CompileRequestV4
    from veritx_dse.model.compile_request_v5 import migrate_v4_to_v5

    example_path = DSE / "examples" / "tensor_demand_v5.json"
    source_bytes = example_path.read_bytes()
    source = json.loads(source_bytes)
    old_request = CompileRequestV4.from_dict(source["design"]["base_v4"])
    migrated = migrate_v4_to_v5(old_request)
    migrated_doc = migrated.to_dict()
    source_hash = old_request.design_hash()
    assert migrated_doc["migration_provenance"]["source_design_hash"] == source_hash
    assert migrate_v4_to_v5(old_request).to_dict() == migrated_doc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            base = f"http://127.0.0.1:{studio_stack}"
            page.goto(base + "/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F21 migration provenance roundtrip")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            put = page.request.put(
                f"{base}/gw/api/v1/projects/{project_id}/draft",
                data={"request": migrated_doc})
            assert put.status == 200, put.text()
            assert put.json()["request"]["schema_version"] == 5
            saved = page.request.get(
                f"{base}/gw/api/v1/projects/{project_id}/draft").json()
            assert saved["request"]["migration_provenance"] == \
                migrated_doc["migration_provenance"]

            page.goto(f"{base}/projects/{project_id}/design")
            expect(page.get_by_role("heading", name="Design workspace")
                   ).to_be_visible(timeout=20000)
            page.get_by_role("link", name="Review Design").click()
            expect(page.get_by_role("heading", name="V5 declarations")
                   ).to_be_visible(timeout=20000)
            page.get_by_text("Migration provenance · read-only", exact=True).click()
            provenance = page.locator("details").filter(
                has_text="Migration provenance · read-only").locator("pre")
            expect(provenance).to_contain_text("CompileRequestV4")
            expect(provenance).to_contain_text(source_hash)
            assert example_path.read_bytes() == source_bytes
        finally:
            browser.close()


def test_f03_nondefault_vc_is_rejected_before_claiming_a_routed_preview(studio_stack):
    """F03 partial refusal probe: unsupported VC lowering is visible."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F03 VC refusal probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/graph")
            apply_graph = page.get_by_role("button", name="save + compile")
            expect(apply_graph).to_be_enabled(timeout=20000)
            apply_graph.click()
            expect(page.get_by_text("Draft saved and compiled", exact=False)
                   ).to_be_visible(timeout=45000)
            # A completed compile job can still produce a refused revision;
            # only a materialized topology enables certified readback.
            expect(page.get_by_role("alert")).to_contain_text(
                "this revision did not compile", timeout=15000)
            page.get_by_label("More fabric views").select_option("access")
            expect(page.get_by_role("heading", name="Loom workspace: access")
                   ).to_be_visible(timeout=20000)
            show_path = page.get_by_role("button", name="Show path")
            # This compile does not expose the active revision/routing class
            # required by the path-query control, so no route may be claimed.
            expect(show_path).to_be_disabled()
            page.get_by_role("link", name="Fabric canvas", exact=True).click()
            expect(page.get_by_role("heading", name="Loom workspace: graph")
                   ).to_be_visible(timeout=20000)
            page.get_by_test_id("node-n1").click()
            vc_depth = page.get_by_label("inspector vc depth")
            expect(vc_depth).to_be_visible(timeout=20000)
            vc_depth.fill("8")
            vc_depth.press("Tab")
            expect(page.get_by_role("alert")).to_contain_text(
                "per-node VC configuration is not materialized")
            # Unsupported VC edits must be visibly refused before PUT/compile.
            writes: list[str] = []
            page.on("request", lambda request: writes.append(request.url)
                   if request.method == "PUT" or "/compile-jobs" in request.url
                   else None)
            refusal = page.get_by_role("alert")
            expect(refusal).to_be_visible(timeout=10000)
            assert "not materialized by the compiler adapter" in refusal.inner_text()
            expect(page.get_by_role("button", name="save + compile")).to_be_disabled()
            assert writes == [], f"refused VC graph made server writes: {writes}"
        finally:
            browser.close()


def test_f04_v5_crossing_declaration_is_separate_from_channel_census(studio_stack):
    """F04 partial: compiled V5 CDC intent is not a channel-level mitigation join."""
    from dataclasses import replace
    from playwright.sync_api import expect, sync_playwright

    sys.path.insert(0, str(DSE))
    from veritx_dse.model.compile_request_v5 import CompileRequestV5

    example_path = DSE / "examples" / "tensor_demand_v5.json"
    example = json.loads(example_path.read_text(encoding="utf-8"))
    parsed = CompileRequestV5.from_dict(example["design"])
    crossings = parsed.to_dict()["crossings"]
    assert any(c["id"] == "core-network" and
               c["mechanism"] == "ASYNC_FIFO" for c in crossings)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            base = f"http://127.0.0.1:{studio_stack}"
            page.goto(base + "/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F04 V5 crossing/census separation")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            put = page.request.put(
                f"{base}/gw/api/v1/projects/{project_id}/draft",
                data={"request": parsed.to_dict()})
            assert put.status == 200, put.text()
            page.goto(f"{base}/projects/{project_id}/design")
            expect(page.get_by_role("heading", name="Design workspace")
                   ).to_be_visible(timeout=20000)
            page.get_by_role("link", name="Review Design").click()
            expect(page.get_by_role("button", name="Compile Design")
                   ).to_be_enabled(timeout=20000)
            with page.expect_response(lambda response: (
                    response.request.method == "POST"
                    and response.url.endswith(
                        f"/projects/{project_id}/compile-jobs"))) as compile_info:
                page.get_by_role("button", name="Compile Design").click()
            compile_response = compile_info.value
            assert compile_response.status == 202, compile_response.text()
            job_id = compile_response.json()["job_id"]
            expect(page.get_by_role("heading", name="Compile result")
                   ).to_be_visible(timeout=60000)
            job = page.request.get(f"{base}/gw/api/v1/jobs/{job_id}").json()
            assert job["state"] == "COMPLETED"
            revision = page.request.get(
                f"{base}/gw/api/v1/revisions/{job['result']['revision_id']}")
            assert revision.status == 200
            assert revision.json()["compilation"]["status"] == "COMPILED"

            # Change only the authored group clock label after compilation.
            edited = replace(parsed, base_v4=replace(
                parsed.base_v4, agents=(
                    replace(parsed.base_v4.agents[0], clock_domain="core"),
                    *parsed.base_v4.agents[1:]))).to_dict()
            saved = page.request.put(
                f"{base}/gw/api/v1/projects/{project_id}/draft",
                data={"request": edited})
            assert saved.status == 200, saved.text()
            saved_doc = page.request.get(
                f"{base}/gw/api/v1/projects/{project_id}/draft").json()["request"]
            assert saved_doc["crossings"] == crossings
            assert saved_doc["base_v4"]["agents"][0]["clock_domain"] == "core"

            page.goto(f"{base}/projects/{project_id}/loom/domains")
            expect(page.get_by_text("UNCOMPILED CHANGES", exact=True)
                   ).to_be_visible(timeout=20000)
            page.get_by_role("tab", name=re.compile("Clock crossings")).click()
            crossing_section = page.locator("section.loom-section").filter(
                has=page.get_by_role(
                    "heading", name="Derived clock-domain crossings"))
            expect(crossing_section).to_contain_text(
                re.compile(r"core\s*→\s*network"), timeout=20000)
            page.get_by_role("tab", name="Domain census").click()
            domain_section = page.locator("section.loom-section").filter(
                has=page.get_by_role("heading", name="Clock domains"))
            core_row = domain_section.locator("table.tbl tbody tr").filter(
                has_text="core")
            expect(core_row).to_be_visible()
            core_row.click()
            inspector = page.get_by_label("Selection inspector")
            expect(inspector).to_contain_text(
                "V5 clock sources/domains/crossings are separate explicit "
                "declarations in Design, not this attachment-derived census.")
            expect(inspector).to_contain_text("preflight.backend")
            inspector.get_by_role("link", name="open simulation").first.click()
            expect(page.get_by_role("heading", name="Loom workspace: simulation")
                   ).to_be_visible(timeout=20000)
        finally:
            browser.close()


def test_f04_certified_attachment_derives_clock_domain_crossings(studio_stack):
    """F04 partial: saved clock labels join a compiled certified attachment."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Workload").select_option(
                "llama-dense-8b-64tiles")
            page.get_by_label("Name").fill("F04 certified domain crossing probe")
            page.get_by_role("button", name="Create project").click()
            expect(page.get_by_role("heading", name="Workload")
                   ).to_be_visible(timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]

            page.get_by_role("link", name="System design", exact=True).click()
            page.get_by_role("link", name="Review Design").click()
            page.get_by_role("button", name="Compile Design").click()
            expect(page.get_by_role("heading", name="Compile result")
                   ).to_be_visible(timeout=45000)

            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/agents")
            expect(page.get_by_role("heading", name="Loom workspace: agents")
                   ).to_be_visible(timeout=20000)
            page.locator("#loom-agent-search").fill("compute_tile")
            compute_row = page.locator(".loom-table tbody tr").first
            expect(compute_row).to_contain_text("compute_tile", timeout=10000)
            compute_row.click()
            expect(page.get_by_label("Selection inspector").get_by_text(
                "agent:g0-i0", exact=True)).to_be_visible(timeout=10000)
            first_domain = page.get_by_label(
                "clock domain (empty = undeclared)")
            first_domain.fill("clk_a")
            page.get_by_role("button", name="Save draft").click()
            expect(page.get_by_text(
                "Working copy matches the server draft.", exact=True)
                   ).to_be_visible(timeout=15000)
            first_saved = page.request.get(
                f"http://127.0.0.1:{studio_stack}/gw/api/v1/projects/"
                f"{project_id}/draft").json()["request"]
            assert first_saved["agents"][0]["clock_domain"] == "clk_a"

            page.locator("#loom-agent-search").fill("hbm_controller")
            hbm_row = page.locator(".loom-table tbody tr").first
            expect(hbm_row).to_contain_text("hbm_controller", timeout=10000)
            hbm_row.click()
            expect(page.get_by_label("Selection inspector").get_by_text(
                "agent:g1-i0", exact=True)).to_be_visible(timeout=10000)
            second_domain = page.get_by_label(
                "clock domain (empty = undeclared)")
            second_domain.fill("clk_mem_probe")
            page.get_by_role("button", name="Save draft").click()
            expect(page.get_by_text(
                "Working copy matches the server draft.", exact=True)
                   ).to_be_visible(timeout=15000)
            second_saved = page.request.get(
                f"http://127.0.0.1:{studio_stack}/gw/api/v1/projects/"
                f"{project_id}/draft").json()["request"]
            assert second_saved["agents"][1]["clock_domain"] == \
                "clk_mem_probe"

            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/domains")
            expect(page.get_by_text("UNCOMPILED CHANGES", exact=True)
                   ).to_be_visible()
            page.get_by_role("tab", name=re.compile("Clock crossings")).click()
            section = page.locator("section.loom-section").filter(
                has=page.get_by_role(
                    "heading", name="Derived clock-domain crossings"))
            expect(section).to_be_visible(timeout=20000)
            crossing_rows = section.locator("table.tbl tbody tr")
            expect(crossing_rows.first).to_be_visible(timeout=20000)
            expect(section).to_contain_text("clk_a")
            expect(section).to_contain_text("clk_mem_probe")
            expect(crossing_rows.first).to_contain_text("64b")
            expect(crossing_rows.first).to_contain_text("1 cyc")
        finally:
            browser.close()


def test_f04_domain_assignments_persist_but_crossing_needs_attachment(studio_stack):
    """F04 partial: domain intent persists; no uncertified crossing is invented."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F04 domain crossing probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/agents")
            expect(page.get_by_role("heading", name="Loom workspace: agents")
                   ).to_be_visible(timeout=20000)
            page.locator(".loom-table tbody tr").first.click()
            first_domain = page.get_by_label(
                "clock domain (empty = undeclared)")
            expect(first_domain).to_be_visible()
            first_domain.fill("clk_a")
            page.get_by_role("button", name="Save draft").click()
            expect(page.get_by_text(
                "Working copy matches the server draft.", exact=True)
                   ).to_be_visible(timeout=15000)

            page.locator("#loom-agent-search").fill("hbm_controller")
            page.locator(".loom-table tbody tr").first.click()
            second_domain = page.get_by_label(
                "clock domain (empty = undeclared)")
            second_domain.fill("clk_b")
            page.get_by_role("button", name="Save draft").click()
            expect(page.get_by_text(
                "Working copy matches the server draft.", exact=True)
                   ).to_be_visible(timeout=15000)

            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/domains")
            expect(page.get_by_role("heading", name="Loom workspace: domains")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_text("clk_a", exact=True).first).to_be_visible()
            expect(page.get_by_text("clk_b", exact=True).first).to_be_visible()
            topology_row = page.locator(".kv").filter(has_text="topology")
            expect(topology_row.get_by_text("—", exact=True)).to_be_visible()
            page.get_by_role("tab", name=re.compile("Clock crossings")).click()
            expect(page.get_by_role("heading",
                                    name="Derived clock-domain crossings")
                   ).to_be_visible()
            expect(page.get_by_text("No clock-domain crossings to derive", exact=True)
                   ).to_be_visible()
        finally:
            browser.close()


def test_f05_firewall_editor_states_intent_without_execution_evidence(studio_stack):
    """F05 partial browser probe; firewall intent is not an evaluated rule."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Workload").select_option(
                "llama-dense-8b-64tiles")
            page.get_by_label("Name").fill("F05 firewall truthfulness probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.get_by_role("link", name="System design", exact=True).click()
            page.get_by_role("link", name="Review Design").click()
            page.get_by_role("button", name="Compile Design").click()
            expect(page.get_by_role("heading", name="Compile result")
                   ).to_be_visible(timeout=45000)
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/access")
            expect(page.get_by_role("heading", name="Loom workspace: access")
                   ).to_be_visible(timeout=20000)
            show_path = page.get_by_role("button", name="Show path")
            expect(show_path).to_be_enabled(timeout=30000)
            show_path.click()
            right = page.locator(".loom-rail-right")
            expect(right.locator(".kv").filter(has_text="terminates")
                   ).to_contain_text("yes", timeout=30000)
            expect(right.locator("table.tbl tbody tr").first
                   ).to_be_visible(timeout=30000)
            expect(page.get_by_text(
                "No firewall engine executes it", exact=False)).to_be_visible()
            expect(page.get_by_text(
                "permissions: no artifact", exact=False)).to_be_visible()
            # No measured matrix or route exists for this new project, so the
            # UI must not turn the local rule editor into evaluated authority.
            expect(page.get_by_text("No measured matrix on this project", exact=False)
                   ).to_be_visible()
            page.get_by_role("button", name="Deny by default").click()
            cell = page.get_by_role("button", name="n1 to n2: DENY")
            cell.click()  # none -> RO
            page.get_by_role("button", name="n1 to n2: RO").click()  # RO -> RW
            expect(page.get_by_role("button", name="n1 to n2: RW")).to_be_visible()
            expect(page.get_by_text("1 rules · default deny · keyed on node id")
                   ).to_be_visible()
            page.reload()
            expect(page.get_by_role("heading", name="Loom workspace: access")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_role("button", name="n1 to n2: RW")).to_be_visible()
            expect(page.get_by_text("1 rules · default deny · keyed on node id")
                   ).to_be_visible()
            expect(page.get_by_text("No measured matrix on this project", exact=False)
                   ).to_be_visible()
        finally:
            browser.close()


def test_f09_workload_phase_editor_refuses_rank_capacity_overflow(studio_stack):
    """F09 partial: real phase edits are capacity-checked in the browser."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F09 capacity probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/workload")
            expect(page.get_by_role("heading", name="Loom workspace: workload")
                   ).to_be_visible(timeout=20000)
            page.get_by_role("button", name="Load dense example").click()
            tp = page.get_by_label("tp ph-prefill")
            expect(tp).to_have_value("8")
            tp.fill("16")
            warning = page.get_by_text(
                "parallelism needs 128 nodes but the graph has 64", exact=False)
            expect(warning).to_be_visible()
            page.reload()
            expect(page.get_by_role("heading", name="Loom workspace: workload")
                   ).to_be_visible(timeout=20000)
            tp = page.get_by_label("tp ph-prefill")
            expect(tp).to_have_value("16")
            expect(warning).to_be_visible()
            tp.fill("4")
            expect(page.get_by_text(
                "✓ 2 phases validate against the 64-node graph", exact=True
            )).to_be_visible()
        finally:
            browser.close()


def test_f10_moe_workload_lowering_exposes_collectives_without_full_mapping(studio_stack):
    """F10 partial: real lowering, but rank mapping/traffic labels stay incomplete."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Workload").select_option(
                "qwen3-moe-tp2-ep4-16tiles")
            page.get_by_label("Name").fill("F10 canonical MoE probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            with page.expect_response(lambda response:
                    "/workloads/qwen3-moe-tp2-ep4-16tiles/lowering"
                    in response.url) as lowering_response:
                page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                          f"{project_id}/loom/workload")
            expect(page.get_by_role("heading", name="Loom workspace: workload")
                   ).to_be_visible(timeout=20000)
            lowering = lowering_response.value.json()
            assert lowering["workload_id"] == "qwen3-moe-tp2-ep4-16tiles"
            assert lowering["participant_count"] == 8
            collectives = lowering["collectives"]
            assert len(collectives) == 8
            assert sum(c["kind"] == "ALLREDUCE" for c in collectives) == 4
            assert sum(c["kind"] == "ALLTOALL" for c in collectives) == 4
            assert all(op["kind"] == "COLLECTIVE"
                       for op in lowering["operations"])
            # The raw MoE workload names TP/EP traffic classes, but this
            # lowering reports only DEFAULT, so do not claim class mapping.
            assert lowering["traffic_class"] == "DEFAULT"
            assert all(flow["traffic_class"] == "DEFAULT"
                       for flow in lowering["flows"])
            expect(page.get_by_text(
                "Ranks are the lowering's participants", exact=False)
                   ).to_be_visible()
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/graph")
            apply_graph = page.get_by_role("button", name="save + compile")
            expect(apply_graph).to_be_enabled(timeout=20000)
            apply_graph.click()
            compiled = page.get_by_text("Draft saved and compiled", exact=False)
            try:
                compiled.wait_for(timeout=45000)
            except Exception as exc:  # noqa: BLE001
                refusal = page.get_by_role("alert")
                if refusal.count() == 0:
                    raise AssertionError(
                        "MoE graph compile had neither completion nor refusal") from exc
                print("F10 MoE graph compile refused:", refusal.inner_text())
            else:
                expect(page.get_by_text(
                    "the compiled fabric is the graph you applied", exact=False)
                       ).to_be_visible(timeout=15000)
        finally:
            browser.close()


def test_f08_capability_registry_names_physical_signoff_as_not_implemented(studio_stack):
    """F08 partial blocker evidence: live capability registry denies signoff."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F08 physical signoff capability probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/capability")
            expect(page.get_by_role("heading", name="Loom workspace: capability")
                   ).to_be_visible(timeout=20000)
            physical = page.get_by_role("row").filter(
                has_text="physical.signoff")
            expect(physical).to_have_count(1, timeout=20000)
            expect(physical).to_contain_text("NOT_IMPLEMENTED")
            expect(physical).to_contain_text("No PDK, LEF/DEF, RC model")
            expect(physical).to_contain_text("FloorplanLoom.tsx")
        finally:
            browser.close()


def test_f06_floorplan_does_not_claim_physical_placement_without_revision(studio_stack):
    """F06 probe: default-graph compile does not fabricate physical placement."""
    from playwright.sync_api import expect, sync_playwright

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F06 floorplan evidence probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/graph")
            expect(page.get_by_role("heading", name="Loom workspace: graph")
                   ).to_be_visible(timeout=20000)
            apply_graph = page.get_by_role("button", name="save + compile")
            expect(apply_graph).to_be_enabled(timeout=20000)
            apply_graph.click()
            compiled = page.get_by_text(
                "Draft saved and compiled", exact=False)
            compile_succeeded = False
            try:
                compiled.wait_for(timeout=45000)
                compile_succeeded = True
            except Exception as exc:  # noqa: BLE001
                refusal = page.get_by_role("alert")
                if refusal.count() == 0:
                    raise AssertionError(
                        "default graph compile had neither completion nor refusal") from exc
                print("F06 default graph compile refused:", refusal.inner_text())
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/floorplan")
            expect(page.get_by_role("heading", name="Loom workspace: floorplan")
                   ).to_be_visible(timeout=20000)
            expect(page.get_by_text("No placement to draw", exact=False)
                   ).to_be_visible()
            if compile_succeeded:
                expect(page.get_by_text("no certified placement", exact=False)
                       ).to_be_visible()
            else:
                expect(page.get_by_text("a compiled revision", exact=False)
                       ).to_be_visible()
        finally:
            browser.close()


def test_f18_256_node_512_edge_graph_opens_and_allows_edit(studio_stack, tmp_path):
    """F18 partial target-size graph interaction probe, not a budget pass."""
    from playwright.sync_api import expect, sync_playwright

    side = 16
    nodes = [
        {"id": f"n{r * side + c + 1}", "x": 80 + c * 120,
         "y": 80 + r * 120, "role": "compute_tile", "ports": 5,
         "clock": "clk_core"}
        for r in range(side) for c in range(side)
    ]
    edges = []
    for r in range(side):
        for c in range(side):
            here = f"n{r * side + c + 1}"
            east = f"n{r * side + ((c + 1) % side) + 1}"
            south = f"n{((r + 1) % side) * side + c + 1}"
            edges.extend([
                {"id": f"e{len(edges) + 1}", "src": here, "dst": east,
                 "width": 512, "pipelineStages": 1, "vcClass": 0},
                {"id": f"e{len(edges) + 2}", "src": here, "dst": south,
                 "width": 512, "pipelineStages": 1, "vcClass": 0},
            ])
    project_file = tmp_path / "large-graph.json"
    project_file.write_text(json.dumps({
        "schemaVersion": 1, "compilerSemanticsVersion": 1,
        "presetHint": None, "nodes": nodes, "edges": edges,
    }))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(**_chromium_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F18 large graph probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.get_by_role("link", name="Fabric canvas", exact=True).click()
            expect(page.get_by_role("heading", name="Loom workspace: graph")
                   ).to_be_visible(timeout=20000)
            load_started = time.perf_counter()
            page.locator("input[type=file][accept='.json']").set_input_files(
                str(project_file))
            expect(page.locator("[data-node-id]")).to_have_count(256, timeout=30000)
            loaded_seconds = time.perf_counter() - load_started
            assert page.locator("[data-testid^='link-']").count() == 512
            expect(page.get_by_text("No issue in the graph.")).to_be_visible()
            page.get_by_test_id("node-n1").click()
            role = page.get_by_label("inspector role")
            expect(role).to_be_visible()
            edit_started = time.perf_counter()
            role.select_option("NPU")
            expect(page.get_by_test_id("node-n1")).to_contain_text("NPU")
            edit_seconds = time.perf_counter() - edit_started
            print(f"F18 observed local browser wall time: graph upload/render="
                  f"{loaded_seconds:.3f}s, single node edit/render="
                  f"{edit_seconds:.3f}s (no acceptance budget asserted)")
            page.get_by_label("More fabric views").select_option("access")
            expect(page.get_by_role("heading", name="Loom workspace: access")
                   ).to_be_visible(timeout=20000)
            page.get_by_role("button", name="Expand (256 nodes)").click()
            # The firewall grid caps at 24×24, so even excluding its diagonal
            # only 552 directional cells are offered, not the required 10k.
            assert page.locator("button[aria-label*=' to ']").count() == 24 * 23
            assert page.get_by_role("button", name="n1 to n25: none").count() == 0
        finally:
            browser.close()


def test_f16_browser_restart_restores_local_graph_autosave_only(studio_stack, tmp_path):
    """Partial web durability probe, not a Tauri crash-recovery pass."""
    from playwright.sync_api import expect, sync_playwright

    profile = BROWSER_TMP_ROOT / f"persistent-profile-{os.getpid()}-{time.time_ns()}"
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(profile), **_chromium_kwargs())
        try:
            page = context.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            expect(page.get_by_label("Workload")).to_be_enabled(timeout=60000)
            page.get_by_label("Name").fill("F16 local autosave probe")
            page.get_by_role("button", name="Create project").click()
            expect(page).to_have_url(re.compile(
                r"/projects/[^/]+/workload"), timeout=20000)
            project_id = page.url.split("/projects/", 1)[1].split("/", 1)[0]
            page.goto(f"http://127.0.0.1:{studio_stack}/projects/"
                      f"{project_id}/loom/graph")
            source_file = tmp_path / "F16-source-project.json"
            with page.expect_download() as source_download_info:
                page.get_by_role("button", name="save project.json").click()
            source_download_info.value.save_as(source_file)
            source_bytes = source_file.read_bytes()
            page.locator("input[type=file][accept='.json']").set_input_files(
                str(source_file))
            expect(page.locator("[data-node-id]")).to_have_count(64)
            page.get_by_test_id("node-n1").click()
            role = page.get_by_label("inspector role")
            role.select_option("NPU")
            expect(page.get_by_test_id("node-n1")).to_contain_text("NPU")
            assert source_file.read_bytes() == source_bytes, \
                "browser graph edit overwrote the imported source file"
        finally:
            context.close()

        # Restart Chromium with the same persistent profile. This proves only
        # browser localStorage durability, not abrupt Tauri termination/source
        # file safeguards.
        recovered = playwright.chromium.launch_persistent_context(
            str(profile), **_chromium_kwargs())
        try:
            page = recovered.new_page()
            page.goto(f"http://127.0.0.1:{studio_stack}/")
            active = page.get_by_label("Active project")
            expect(active).to_be_visible(timeout=20000)
            active.select_option(project_id)
            page.get_by_role("link", name="Fabric canvas", exact=True).click()
            expect(page.get_by_role("heading", name="Loom workspace: graph")
                   ).to_be_visible(timeout=20000)
            page.get_by_test_id("node-n1").click()
            expect(page.get_by_label("inspector role")).to_have_value("NPU")
            expect(page.get_by_label("graph preset")).to_have_value("custom")
            assert source_file.read_bytes() == source_bytes, \
                "browser recovery overwrote the imported source file"
        finally:
            recovered.close()
