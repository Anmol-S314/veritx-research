"""Golden corpus: standalone BookSim slice (control-plane redesign Phase 2).

Migration parity baseline — handoff §30 Phase 2. These tests pin the
observable scientific behavior of the corrected baseline so the Python
control plane (Phases 3+) can be diffed against it:

  Layer 4 (tiny real simulator golden tests): one standalone BookSim
  experiment, validated on scientifically meaningful output (packet
  latency in cycles), not stdout strings.
  Layer 2 pattern (real process, no subprocess mocks): the real binary,
  the real config parsing, the real exit codes.

Determinism: mesh4x4 at ir=0.1 is STOCHASTIC without a seed (measured
spread ~33-35 cycles). Every corpus cfg pins `seed = 42;` first — the
pinned run reproduces 35.0573 exactly (verified 2026-09-16). The seed-pin
mechanism itself is under test, not just the number.

Skipped when the booksim binary is absent (host without build) — mirrors
the needs_binary pattern in test_evaluate_astra.py.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from veritx_dse.core.paths import BOOKSIM_DIR

BOOKSIM = BOOKSIM_DIR / "booksim"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "astra_tiny" / "mesh4x4.cfg"

needs_booksim = pytest.mark.skipif(
    not BOOKSIM.exists(), reason="booksim binary not built"
)

_MEASURED_LATENCY_RE = re.compile(
    r"^Packet latency average = ([0-9.]+) \(1 samples\)", re.M
)

# Pinned golden value: mesh4x4, ir=0.1, seed=42, FINAL measurement period
# (the '(1 samples)' line after warmup — NOT a warmup-period line; BookSim
# prints one latency line per sampling period and only the last has a
# single sample). Recorded 2026-09-16 from the corrected Bash baseline. If
# this changes, classify per handoff §30 Phase 5: expected improvement /
# Bash bug / Python bug / nondeterminism.
GOLDEN_PACKET_LATENCY = 35.0573


def _run_booksim(cfg: Path, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(BOOKSIM), str(cfg)],
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def _pinned_cfg(tmp_path: Path) -> Path:
    """Corpus cfg = fixture + seed pin prepended (seed must win the RNG)."""
    out = tmp_path / "golden_mesh4x4_seed42.cfg"
    body = FIXTURE.read_text()
    assert "seed" not in body, "fixture grew a seed; pin it here explicitly"
    out.write_text("seed = 42;\n" + body)
    return out


@needs_booksim
def test_golden_mesh4x4_pinned_seed_is_deterministic(tmp_path):
    """Same cfg, three runs, identical latency — determinism is the contract."""
    cfg = _pinned_cfg(tmp_path)
    latencies = set()
    for _ in range(3):
        p = _run_booksim(cfg)
        assert p.returncode == 0, p.stderr[-500:]
        m = _MEASURED_LATENCY_RE.search(p.stdout)
        assert m, "no measurement-period latency line '(1 samples)' in output"
        latencies.add(float(m.group(1)))
    assert len(latencies) == 1, f"stochastic despite pinned seed: {latencies}"


@needs_booksim
def test_golden_mesh4x4_matches_recorded_value(tmp_path):
    """The pinned value equals the recorded baseline (parity oracle)."""
    cfg = _pinned_cfg(tmp_path)
    p = _run_booksim(cfg)
    assert p.returncode == 0, p.stderr[-500:]
    m = _MEASURED_LATENCY_RE.search(p.stdout)
    assert m is not None
    assert float(m.group(1)) == pytest.approx(GOLDEN_PACKET_LATENCY, abs=1e-3)


@needs_booksim
def test_unpinned_cfg_is_stochastic_or_equal(tmp_path):
    """Documents the hazard the corpus exists to catch: WITHOUT a seed the
    same cfg may vary. Asserts only the weak property (two runs both
    produce a parseable number) so the test can't flake — but the recorded
    spread is documented here: 32.6-35.3 observed at ir=0.1."""
    p1 = _run_booksim(FIXTURE)
    p2 = _run_booksim(FIXTURE)
    assert p1.returncode == 0 and p2.returncode == 0
    assert _MEASURED_LATENCY_RE.search(p1.stdout)
    assert _MEASURED_LATENCY_RE.search(p2.stdout)


@needs_booksim
def test_failure_case_bad_config_fails_loudly(tmp_path):
    """Layer 2 failure fixture: a malformed cfg must exit non-zero, not
    silently produce garbage metrics. (Handoff §27: 'simulator exits
    non-zero' is an acceptance scenario.)"""
    bad = tmp_path / "bad.cfg"
    bad.write_text("this_is_not_a_booksim_directive = 42;\n")
    p = _run_booksim(bad, timeout=20)
    assert p.returncode != 0, "garbage config accepted — baseline is unsound"


@needs_booksim
def test_failure_case_missing_config_file(tmp_path):
    p = subprocess.run(
        [str(BOOKSIM), str(tmp_path / "nonexistent.cfg")],
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert p.returncode != 0
