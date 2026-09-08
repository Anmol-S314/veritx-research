"""Tests for `veritx evaluate astra` — the CLI ↔ live-binary contract.

Background: this subcommand shells to the AstraSim_BookSim2 frontend, which
after quiescence prints Waiting and reads the interactive protocol from
stdin. A naive subprocess.run inherits the terminal and hangs forever; the
test suite historically covered only argparse wiring (plus pytest stdin,
which EOFs instantly and hides the hang). These tests close that hole:

- _parse_astra_cycles: pure unit tests, always run.
- Convention gate: missing base / missing rank files fail fast, always run.
- Live test: runs the REAL frontend binary on golden fixtures when present
  (skipped otherwise). ~1s wall. Would hang (then fail by timeout) without
  stdin=DEVNULL, and would spin without the injection_rate override.
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.cli.cli import _parse_astra_cycles, cmd_evaluate_astra
from veritx_dse.core.logging import Ctx
from veritx_dse.core.paths import ASTRA_BS_BIN

FIX = Path(__file__).parent / "fixtures" / "astra_tiny"

SAMPLE_STDOUT = """\
topology = mesh;
[2026-09-08 21:21:49.445] [workload] [info] sys[0] finished, 100000 cycles, exposed communication 0 cycles.
[workload] sys[0] finished, 100000 cycles, exposed communication 100000 cycles.
[workload] sys[1] finished, 50000 cycles, exposed communication 50000 cycles.
Waiting
"""


# ── parser unit tests ────────────────────────────────────────────────────

class TestParseAstraCycles:
    def test_parses_per_rank(self):
        got = _parse_astra_cycles(SAMPLE_STDOUT)
        assert got == {0: 100000, 1: 50000}

    def test_empty_when_no_lines(self):
        assert _parse_astra_cycles("BEGIN Configuration File: x.cfg\n") == {}

    def test_ignores_config_echo(self):
        out = "k = 4;\nn = 2;\n[workload] sys[7] finished, 12 cycles, foo.\n"
        assert _parse_astra_cycles(out) == {7: 12}


# ── convention gate ──────────────────────────────────────────────────────

def _args(ets, tmp_path):
    return SimpleNamespace(
        ets=str(ets),
        system_config=str(FIX / "system.json"),
        network_config=str(FIX / "network.json"),
        memory_config=str(FIX / "memory.json"),
        timeout=60,
    )


class TestConventionGate:
    def test_missing_base_fails(self, tmp_path, capsys):
        from unittest.mock import patch
        with patch("veritx_dse.cli.cli.RUNS_DIR", tmp_path):
            cmd_evaluate_astra(Ctx(verbosity=0), _args(tmp_path / "nope.et", tmp_path))
        assert not list(tmp_path.glob("astra/eval_*.json"))

    def test_missing_rank_files_fails(self, tmp_path, capsys):
        from unittest.mock import patch
        lonely = tmp_path / "lonely.et"
        lonely.write_bytes(b"junk")
        with patch("veritx_dse.cli.cli.RUNS_DIR", tmp_path):
            cmd_evaluate_astra(Ctx(verbosity=0), _args(lonely, tmp_path))
        assert not list(tmp_path.glob("astra/eval_*.json"))


# ── live binary test ─────────────────────────────────────────────────────

needs_binary = pytest.mark.skipif(
    not ASTRA_BS_BIN.exists(),
    reason="AstraSim_BookSim2 frontend binary not built",
)


@needs_binary
class TestLiveAstra:
    def test_single_shot_completes(self, tmp_path):
        """End-to-end: real binary, real fixture, DEVNULL stdin.

        Fails (timeout) if the CLI hangs at the interactive prompt, spins on
        self-injected traffic, or emits nothing parseable.
        """
        from unittest.mock import patch
        args = SimpleNamespace(
            ets=str(FIX / "one-coll.et"),
            system_config=str(FIX / "system.json"),
            network_config=str(FIX / "network.json"),
            memory_config=str(FIX / "memory.json"),
            timeout=120,
        )
        with patch("veritx_dse.cli.cli.RUNS_DIR", tmp_path):
            cmd_evaluate_astra(Ctx(verbosity=0), args)
        results = list(tmp_path.glob("astra/eval_*.json"))
        assert len(results) == 1
        result = json.loads(results[0].read_text())
        assert result["status"] == "ok"
        assert result["num_ranks"] == 16
        assert result["cycles"] > 0
        assert result["per_rank_cycles"]["0"] > 0
