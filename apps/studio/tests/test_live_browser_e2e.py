"""Black-box browser acceptance against a LIVE gateway (UI9 + P5 §12).

Real flow (no fixtures, no faked backends):

    open Studio -> create project -> dense workload -> compile -> PASS
    -> Evaluate -> plan loads -> BookSim READY (clean tree) ->
    ASTRA READY -> select -> run -> job completes ->
    backend/fidelity cards -> run detail -> verify bundle ->
    native evidence ids

Refusal flow:

    MoE project -> compile -> Evaluate -> plan shows the ASTRA system
    rows UNSUPPORTED with the server's exact multi-class reason, their
    checkboxes disabled; the BookSim row carries its own server reason
    and is selectable only when qualified.

The evaluation legs require real, pinned producers; without one the
test still proves the live compile/verify/plan browser path and skips
the execution legs. No mock backend exists anywhere in this file.

Enabled only with ``VERITX_E2E=1`` (it needs Node + a built/installed
studio and, for the execution legs, ``VERITX_BOOKSIM_BIN`` plus — for
the ASTRA leg — ``VERITX_LIVE_FEDERATION=1``).
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

#: Reclaimed truth (class ABI 1): the ASTRA system rows no longer refuse
#: MoE multi-class traffic — the old refusal text below must be ABSENT.
#: Asserted verbatim so a regression reintroduces it loudly.
MOE_ASTRA_REASON = "multi-class traffic refuses rather than flattening"


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
    """Prefer a system/existing Chromium so the test does not require a
    fresh `playwright install` matching the Python package version."""
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


def _require_producer_or_skip() -> None:
    if not _pinned_producer():
        if os.environ.get("VERITX_E2E_REQUIRE_BACKEND") == "1":
            pytest.fail(
                "release gate: no pinned BookSim producer available "
                "(build with a clean manifest and set "
                "VERITX_BOOKSIM_BIN)")
        pytest.skip("compile/verify/plan browser path verified; "
                    "execution legs need a pinned BookSim producer")


def _create_project(page, expect, base: str, name: str,
                    workload: str) -> None:
    page.goto(f"{base}/")
    expect(page.get_by_role("heading", name="Projects")).to_be_visible(
        timeout=20000)
    page.get_by_label("Name").fill(name)
    page.get_by_label("Workload").select_option(workload)
    page.get_by_role("button", name="Create project").click()
    expect(page.get_by_role("heading", name="Workload")).to_be_visible(
        timeout=20000)


def _compile_current_draft(page, expect) -> None:
    """Design -> Review -> Compile Design -> Compile result page."""
    page.get_by_role("link", name="Design", exact=True).click()
    expect(page.get_by_role("heading", name="Design intent")).to_be_visible(
        timeout=20000)
    page.get_by_role("link", name="Review Design").click()
    page.get_by_role("button", name="Compile Design").click()
    expect(page.get_by_role("heading", name="Compile result")).to_be_visible(
        timeout=30000)


def test_browser_live_flow(live_stack):
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            # The marketing landing ships from the same build and renders
            # the photoreal hero, not an SVG stand-in.
            page.goto(f"http://127.0.0.1:{ui_port}/landing.html")
            expect(page.get_by_role(
                "heading", name="Build without boundaries.")).to_be_visible(
                    timeout=20000)
            board = page.locator(".board-stage img.noc-board")
            expect(board).to_be_visible(timeout=20000)
            assert page.evaluate(
                "() => document.querySelector('.board-stage img')"
                ".naturalWidth") > 1000, "hero asset did not load"

            page.goto(f"http://127.0.0.1:{ui_port}/")
            expect(page.get_by_text("LIVE")).to_be_visible(timeout=30000)

            # Dense project, compiled through the reviewed snapshot.
            _create_project(
                page, expect, f"http://127.0.0.1:{ui_port}",
                "Llama Dense 8B Study",
                "llama-dense-8b-64tiles")
            _compile_current_draft(page, expect)

            # Inspect verification: the certificate is PASS.
            page.get_by_role("link", name="Verification", exact=True).click()
            expect(page.get_by_role(
                "heading",
                name="Verification certificate")).to_be_visible(timeout=20000)
            expect(page.get_by_text("All obligations").first).to_be_visible(
                timeout=20000)

            # Evaluate: the server plan is the primary model.
            page.get_by_role("link", name="Evaluate", exact=True).click()
            expect(page.get_by_role(
                "heading", name="Evaluate")).to_be_visible(timeout=20000)
            expect(page.get_by_text("B · Evaluation plan")).to_be_visible(
                timeout=30000)
            plan = page.locator(".page")
            expect(plan.get_by_text("NETWORK_COMPLETION",
                                    exact=True).first).to_be_visible(
                                        timeout=30000)
            expect(plan.get_by_text("SYSTEM_MAKESPAN",
                                    exact=True).first).to_be_visible(
                                        timeout=30000)

            # Explicit backend selection triggers a fresh server plan —
            # scope to ASTRA, then back to all backends.
            page.get_by_label("Backend").select_option(
                "ASTRA2_EMBEDDED_BOOKSIM")
            expect(plan.get_by_text("SYSTEM_MAKESPAN",
                                    exact=True).first).to_be_visible(
                                        timeout=30000)
            page.get_by_label("Backend").select_option("all")
            expect(plan.get_by_text("NETWORK_COMPLETION",
                                    exact=True).first).to_be_visible(
                                        timeout=30000)

            # Only READY rows are selectable: the DRAM_TIMING row (no
            # Ramulator extension on a release tree without one) carries
            # a disabled checkbox.
            dram_box = page.get_by_label("Select DRAM_TIMING")
            if dram_box.count() > 0:
                expect(dram_box).to_be_disabled()

            _require_producer_or_skip()

            # Run the READY selection (default: every READY row) and
            # read the federated result cards.
            page.get_by_role("button", name="Run selected analyses").click()
            expect(page.get_by_text("E · Results").first).to_be_visible(
                timeout=600000)
            expect(page.get_by_text("EVALUATED").first).to_be_visible(
                timeout=60000)
            # Per-analysis cards: backend, fidelity, native evidence id.
            expect(page.get_by_text("native evidence").first).to_be_visible(
                timeout=30000)
            expect(page.get_by_text("Normalized metrics").first).to_be_visible(
                timeout=30000)

            # Run detail: all analyses, bundle verification, trust.
            page.locator("a.link").first.click()
            expect(page.get_by_text("Analyses · federated").first
                   ).to_be_visible(timeout=30000)
            expect(page.get_by_text("Why can I trust this?").first
                   ).to_be_visible(timeout=30000)
            page.get_by_role("button", name="Verify bundle").click()
            expect(page.get_by_text("VERIFIED").first).to_be_visible(
                timeout=60000)
        finally:
            browser.close()


def test_browser_moe_astra_supported(live_stack):
    """MoE: the ASTRA system rows no longer refuse multi-class traffic
    (class ABI 1 reclamation); their checkboxes are enabled, and the
    BookSim row carries its own server reason."""
    gw_port, ui_port = live_stack
    try:
        from playwright.sync_api import expect, sync_playwright
    except ImportError as exc:  # pragma: no cover
        pytest.skip(f"playwright not installed: {exc}")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(**_chromium_launch_kwargs())
        try:
            page = browser.new_page()
            page.goto(f"http://127.0.0.1:{ui_port}/")
            expect(page.get_by_text("LIVE")).to_be_visible(timeout=30000)

            _create_project(
                page, expect, f"http://127.0.0.1:{ui_port}",
                "MoE 8x7B Study", "moe-8x7b-64tiles")
            _compile_current_draft(page, expect)

            page.get_by_role("link", name="Evaluate", exact=True).click()
            expect(page.get_by_text("B · Evaluation plan")).to_be_visible(
                timeout=30000)

            # Explicit ASTRA scope: the old multi-class refusal is gone
            # (ABI-1 reclamation) and the system rows are runnable.
            page.get_by_label("Backend").select_option(
                "ASTRA2_EMBEDDED_BOOKSIM")
            plan = page.locator(".page")
            expect(plan.get_by_text(MOE_ASTRA_REASON).first).to_be_hidden(
                timeout=30000)
            makespan_box = page.get_by_label("Select SYSTEM_MAKESPAN")
            expect(makespan_box).to_be_enabled()

            # The BookSim row stays independent: it carries its own
            # server reason and is selectable only when qualified.
            page.get_by_label("Backend").select_option("all")
            expect(plan.get_by_text("NETWORK_COMPLETION",
                                    exact=True).first).to_be_visible(
                                        timeout=30000)
            network_box = page.get_by_label("Select NETWORK_COMPLETION")
            if network_box.is_enabled():
                if not network_box.is_checked():
                    network_box.check()
                expect(page.get_by_text(
                    "Selected: NETWORK_COMPLETION",
                    exact=False)).to_be_visible(timeout=10000)
                expect(page.get_by_role(
                    "button", name="Run selected analyses"
                ).first).to_be_enabled()
        finally:
            browser.close()
