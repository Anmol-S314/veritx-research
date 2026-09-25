"""Release-gate skip enforcement (C7.1 / C10.1).

A release-critical test must never pass by skipping. When
``VERITX_RELEASE_GATE=1`` is set (release CI), any skip whose reason names a
release-critical dependency fails the whole session instead of being
tolerated. In ordinary development runs the skips remain visible and
harmless.

The named dependencies are the ones ``SKIP-INVENTORY.md`` marks
release-critical: the deterministic serving trace fixtures and the built
BookSim/ASTRA backend binaries. The two-binary ASTRA reference differential
is no longer release-critical: R2 replaced it with an independent closed-form
timing oracle (``test_astra_timing_oracle.py``); the differential is a
shared-engine check and may skip when no reference binary is supplied.
"""
from __future__ import annotations

import os

#: substrings of skip reasons that make the skip release-blocking
_RELEASE_CRITICAL_REASONS = (
    "event_handler .et not found",
    "generated batch trace not found",
    # a release build must actually execute the backends it qualifies
    "no AstraSim_BookSim2 binary available on this machine",
    "AstraSim_BookSim2 release binary not built",
    "no BookSim binary available",
)

_RELEASE_GATE = os.environ.get("VERITX_RELEASE_GATE") == "1"
_RELEASE_SKIPS: list[str] = []


def pytest_configure(config) -> None:
    _RELEASE_SKIPS.clear()


def pytest_runtest_logreport(report) -> None:
    if not _RELEASE_GATE or report.when != "setup" or not report.skipped:
        return
    reason = ""
    if isinstance(report.longrepr, tuple):
        reason = str(report.longrepr[-1])
    if any(marker in reason for marker in _RELEASE_CRITICAL_REASONS):
        _RELEASE_SKIPS.append(report.nodeid)


def pytest_sessionfinish(session, exitstatus: int) -> None:
    if not _RELEASE_GATE or not _RELEASE_SKIPS:
        return
    session.exitstatus = 1
    reporter = session.config.pluginmanager.get_plugin("terminalreporter")
    if reporter is not None:
        reporter.write_line(
            "RELEASE GATE FAILED: release-critical tests skipped: "
            + ", ".join(sorted(_RELEASE_SKIPS)))
