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
        with patch("veritx_dse.core.paths.RESULTS_DIR", tmp_path):
            cmd_evaluate_astra(Ctx(verbosity=0), _args(tmp_path / "nope.et", tmp_path))
        assert not list(tmp_path.glob("evaluate-astra/*/eval_*.json"))

    def test_missing_rank_files_fails(self, tmp_path, capsys):
        from unittest.mock import patch
        lonely = tmp_path / "lonely.et"
        lonely.write_bytes(b"junk")
        with patch("veritx_dse.core.paths.RESULTS_DIR", tmp_path):
            cmd_evaluate_astra(Ctx(verbosity=0), _args(lonely, tmp_path))
        assert not list(tmp_path.glob("evaluate-astra/*/eval_*.json"))


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
        with patch("veritx_dse.core.paths.RESULTS_DIR", tmp_path):
            cmd_evaluate_astra(Ctx(verbosity=0), args)
        results = list(tmp_path.glob("evaluate-astra/*/eval_*.json"))
        assert len(results) == 1
        result = json.loads(results[0].read_text())
        assert result["status"] == "ok"
        assert result["num_ranks"] == 16
        assert result["cycles"] > 0
        assert result["per_rank_cycles"]["0"] > 0
        # The fixture's allreduce has nonzero exposed comm — the CLI must
        # surface it, not drop the field the frontend already reports.
        assert result["exposed_comm_cycles"] > 0
        # [plat] line: real per-packet latency/hops from the built binary.
        plat = result["plat_stats"]
        assert plat is not None, "binary emits [plat]; CLI dropped it"
        assert int(plat["packets"]) > 0
        assert float(plat["p50"]) > 0
        assert float(plat["hops_avg"]) > 0


@needs_binary
class TestEmbeddedMtu:
    """Trial: --booksim2-embedded-mtu fragments message-sized unicast sends.

    Background: embedded sim_send injects one wormhole packet per send; a
    233KB ring chunk becomes a ~29k-flit packet vs 8-flit VC buffers, which
    wedges inter-router traffic (intra-router pairs bypass the clog, so
    short snapshots misleadingly implicate parity/routing). Fragmenting
    into MTU-sized packets unblocks it (dragonfly16 case: 0 → 864 rank
    completions in the same wall budget, zero tracker mismatches).
    """

    def _run_direct(self, *extra, timeout=120):
        import subprocess
        return subprocess.run(
            [str(ASTRA_BS_BIN),
             "--workload-configuration", str(FIX / "one-coll.et"),
             "--system-configuration", str(FIX / "system.json"),
             "--network-configuration", str(FIX / "network.json"),
             "--remote-memory-configuration", str(FIX / "memory.json"),
             "--booksim2-extra=injection_rate=0.0",
             "--logging-configuration", "empty",
             "--logging-folder", "/tmp/veritx_mtu_test",
             "--max-scale=0", *extra],
            cwd=str(Path(__file__).parent.parent.parent.parent),
            stdin=subprocess.DEVNULL, capture_output=True, text=True,
            timeout=timeout)

    def test_negative_mtu_fails_fast(self):
        r = self._run_direct("--booksim2-embedded-mtu", "-5")
        assert r.returncode != 0
        assert "embedded-mtu" in r.stderr

    def test_mtu_fragments_and_completes(self):
        """MTU=4 forces real fragmentation on the tiny fixture: the
        baseline emits 480 packets; fragmented it must emit 960 with all
        32 rank-steps finishing and no tracker mismatch (each chunk needs
        ALL its fragments to match)."""
        r = self._run_direct("--booksim2-embedded-mtu", "4")
        assert r.returncode == 0, r.stderr[-500:]
        assert (r.stdout + r.stderr).count("finished") == 32
        assert "no tracker entry" not in r.stdout
        plat = [l for l in r.stdout.splitlines() if "[plat]" in l]
        assert plat and "packets=960" in plat[0]

    def test_mtu_above_message_size_is_identity(self):
        """MTU larger than any send behaves exactly like MTU off."""
        r = self._run_direct("--booksim2-embedded-mtu", "1000000")
        assert r.returncode == 0, r.stderr[-500:]
        plat = [l for l in r.stdout.splitlines() if "[plat]" in l]
        assert plat and "packets=480" in plat[0]


# ── fault injection: every error branch, via the REAL subprocess path ────

class TestAstraFaults:
    """Drive cmd_evaluate_astra's error branches with tiny fake binaries.

    The command's value is how it *reacts*: nonzero exit, garbage stdout,
    hangs, and what it refuses to write to disk. Fake scripts keep each
    branch fast and deterministic while subprocess.run, the timeout, and the
    artifact rules all stay real. A regression that reports fabricated
    success (e.g. dropping the no-parseable-output guard) fails here.
    """

    FAKE_STDOUT = (
        "[workload] sys[0] finished, 100000 cycles, exposed communication 0 cycles.\n"
        "[workload] sys[1] finished, 50000 cycles, exposed communication 50000 cycles.\n"
        "Waiting\n"
    )

    def _run(self, monkeypatch, tmp_path, capsys, mode, timeout=60):
        fake = tmp_path / "fake_astra"
        fake.write_text(
            "#!/usr/bin/env bash\n"
            'echo "$@" > "$VERITX_FAKE_ARGV"\n'
            'case "$VERITX_FAKE_MODE" in\n'
            "  crash)   echo 'booksim: assertion failed in trafficmanager' >&2\n"
            "           echo 'second stderr line' >&2; exit 3;;\n"
            "  garbage) echo 'BEGIN Configuration File: x.cfg'\n"
            "           echo 'Waiting'; exit 0;;\n"
            "  hang)    sleep 300;;\n"
            f"  ok)      printf '%s' '{self.FAKE_STDOUT}'; exit 0;;\n"
            "esac\n"
        )
        fake.chmod(0o755)
        monkeypatch.setenv("VERITX_FAKE_MODE", mode)
        monkeypatch.setenv("VERITX_FAKE_ARGV", str(tmp_path / "argv.txt"))
        monkeypatch.setattr("veritx_dse.cli.cli.ASTRA_BS_BIN", fake)
        monkeypatch.setattr("veritx_dse.core.paths.RESULTS_DIR", tmp_path)

        ets = tmp_path / "w.et"
        ets.write_bytes(b"trace")
        (tmp_path / "w.et.0.et").write_bytes(b"rank0")
        (tmp_path / "w.et.1.et").write_bytes(b"rank1")
        args = SimpleNamespace(
            ets=str(ets),
            system_config=str(FIX / "system.json"),
            network_config=str(FIX / "network.json"),
            memory_config=str(FIX / "memory.json"),
            timeout=timeout,
        )
        cmd_evaluate_astra(Ctx(verbosity=1), args)
        return {
            "err": capsys.readouterr().err,
            "argv": (tmp_path / "argv.txt").read_text() if (tmp_path / "argv.txt").exists() else "",
            "results": list(tmp_path.glob("evaluate-astra/*/eval_*.json")),
        }

    def test_missing_binary_fails_fast(self, monkeypatch, tmp_path, capsys):
        monkeypatch.setattr("veritx_dse.cli.cli.ASTRA_BS_BIN",
                            tmp_path / "no_such_binary")
        monkeypatch.setattr("veritx_dse.core.paths.RESULTS_DIR", tmp_path)
        ets = tmp_path / "w.et"
        ets.write_bytes(b"trace")
        (tmp_path / "w.et.0.et").write_bytes(b"rank0")
        args = SimpleNamespace(
            ets=str(ets), system_config="s", network_config="n",
            memory_config="m", timeout=60,
        )
        cmd_evaluate_astra(Ctx(verbosity=0), args)
        assert "binary not found" in capsys.readouterr().err
        assert not list(tmp_path.glob("evaluate-astra/*/eval_*.json"))

    def test_nonzero_exit_reports_tail_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        got = self._run(monkeypatch, tmp_path, capsys, "crash")
        assert "ASTRA-sim failed (exit 3)" in got["err"]
        assert "assertion failed in trafficmanager" in got["err"]
        assert got["results"] == []

    def test_exit_zero_without_parseable_output_is_refused(self, monkeypatch, tmp_path, capsys):
        got = self._run(monkeypatch, tmp_path, capsys, "garbage")
        assert "no parseable" in got["err"]
        assert "sys[i] finished" in got["err"]
        assert got["results"] == []  # no fabricated success on disk

    def test_hanging_binary_times_out_and_writes_nothing(self, monkeypatch, tmp_path, capsys):
        got = self._run(monkeypatch, tmp_path, capsys, "hang", timeout=2)
        assert "timed out after 2s" in got["err"]
        assert got["results"] == []

    def test_success_writes_result_with_max_over_ranks(self, monkeypatch, tmp_path, capsys):
        got = self._run(monkeypatch, tmp_path, capsys, "ok")
        assert "ASTRA-sim: 100,000c over 2 ranks" in got["err"]
        assert len(got["results"]) == 1
        result = json.loads(got["results"][0].read_text())
        assert result["status"] == "ok"
        assert result["cycles"] == 100000        # max over ranks, not rank 0
        assert result["per_rank_cycles"] == {"0": 100000, "1": 50000}  # JSON: int keys → str

    def test_injection_guard_and_configs_reach_the_binary(self, monkeypatch, tmp_path, capsys):
        got = self._run(monkeypatch, tmp_path, capsys, "ok")
        joined = got["argv"]
        # template cfgs carry standalone-style injection_rate; without this
        # override the embedded sim self-injects forever (the historical spin)
        assert "--booksim2-extra=injection_rate=0.0" in joined
        assert "--logging-configuration empty" in joined
        assert str(tmp_path / "w.et") in joined          # workload base (resolved)
        assert str(FIX / "system.json") in joined
        assert str(FIX / "network.json") in joined
        assert str(FIX / "memory.json") in joined
