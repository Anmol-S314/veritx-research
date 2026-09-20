"""Tests for `veritx serve` — the CLI ↔ serving-module contract.

`cmd_serve` shells out to `python -m serving` in third_party/llmservingsim.
That module owns the interactive backend protocol whose shutdown gate recently
deadlocked dense-DP runs (serving polled each NPU for a second "done" burst
the booksim backend never sends). These tests pin the contract at both ends:

- build_parser: every flag the user passes survives argparse AND reaches the
  spawned command line (read via the internal probe — no subprocess).
- missing serving root: fails fast with a message, no half-spawned process.
- live end-to-end: a REAL serving run through the CLI entrypoint on the
  analytical backend (pure Python, ~1s, no binary needed). Exercises the full
  spawn → protocol → shutdown → returncode path; a regression of the shutdown
  livelock class fails this test by timeout instead of passing silently.
"""
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from veritx_dse.cli.cli import _probe_serve, build_parser, cmd_serve
from veritx_dse.core.logging import Ctx
from veritx_dse.core.paths import LLMSIM_DIR, REPO

SERVING_ROOT = REPO / "third_party" / "llmservingsim"
CLUSTER = SERVING_ROOT / "configs" / "cluster" / "single_node_single_instance.json"
DATASET = SERVING_ROOT / "workloads" / "example_trace.jsonl"


# ── arg contract: flags survive argparse and reach the command line ──────

class TestServeArgForwarding:
    def _parsed(self, *extra):
        parser = build_parser()
        args = parser.parse_args(["legacy", "serve", "--cluster-config", str(CLUSTER),
                                  "--dataset", str(DATASET), *extra])
        return args

    def test_every_user_flag_reaches_the_command(self):
        args = self._parsed("--num-reqs", "7",
                            "--network-backend", "analytical",
                            "--no-cleanup",
                            "--no-prefix-caching",
                            "--cycle-accurate",
                            "--output", "/tmp/veritx_serve_out",
                            "--timeout", "123",
                            "--log-level", "INFO",
                            "--max-num-seqs", "64",
                            "--max-num-batched-tokens", "1024",
                            "--dtype", "fp8",
                            "--request-routing-policy", "RR",
                            "--expert-routing-policy", "RAND",
                            "--block-size", "32",
                            "--skip-prefill",
                            "--no-chunked-prefill",
                            "--no-block-copy")
        cmd = _probe_serve(args)
        joined = " ".join(cmd)
        assert "--num-reqs 7" in joined
        assert "--network-backend analytical" in joined
        assert "--log-level INFO" in joined
        assert "--keep-inputs" in joined          # upstream renamed --no-cleanup-inputs
        assert "--no-enable-prefix-caching" in joined
        assert "--no-booksim-replay-only" in joined  # downstream flag is inverted
        assert "--output /tmp/veritx_serve_out" in joined
        assert "--max-num-seqs 64" in joined
        assert "--max-num-batched-tokens 1024" in joined
        assert "--dtype fp8" in joined
        assert "--request-routing-policy RR" in joined
        assert "--expert-routing-policy RAND" in joined
        assert "--block-size 32" in joined
        assert "--skip-prefill" in joined
        assert "--no-enable-chunked-prefill" in joined
        assert "--no-enable-block-copy" in joined

    def test_defaults_match_module_expectations(self):
        args = self._parsed()
        cmd = _probe_serve(args)
        joined = " ".join(cmd)
        # booksim is the veritx default (upstream's default is analytical)
        assert "--network-backend booksim" in joined
        # none of the optional toggles fire on defaults
        assert "--keep-inputs" not in joined
        assert "--no-enable-prefix-caching" not in joined
        assert "--no-booksim-replay-only" not in joined
        assert "--output" not in joined

    def test_module_actually_accepts_every_forwarded_flag(self):
        """The other half of the contract: serving's own parser must not
        reject anything cmd_serve can emit (this bit us via upstream renames).

        Trick: put --help LAST — argparse errors (exit 2) on an unknown flag
        before it ever reaches --help, and exits 0 (printing help, running
        nothing) when every flag is known.
        """
        parser = build_parser()
        args = parser.parse_args(["legacy", "serve", "--cluster-config", str(CLUSTER),
                                  "--dataset", str(DATASET),
                                  "--no-cleanup", "--no-prefix-caching",
                                  "--cycle-accurate", "--output", "/tmp/o",
                                  "--max-num-seqs", "64", "--dtype", "fp8",
                                  "--skip-prefill", "--no-chunked-prefill",
                                  "--enable-prefix-sharing",
                                  "--prefix-storage", "CPU",
                                  "--no-reserve-full-isl", "--save-trace-text",
                                  "--log-interval", "0.5",
                                  "--kv-cache-dtype", "fp8",
                                  "--enable-local-offloading",
                                  "--block-size", "32",
                                  "--npu-memory-utilization", "0.8",
                                  "--long-prefill-token-threshold", "512",
                                  "--request-routing-policy", "RR",
                                  "--expert-routing-policy", "RAND",
                                  "--max-num-batched-tokens", "1024",
                                  "--no-block-copy",
                                  "--enable-attn-offloading",
                                  "--enable-sub-batch-interleaving"])
        cmd = _probe_serve(args)
        module_argv = cmd[3:]  # drop [python, -m, serving]
        probe = subprocess.run(
            [sys.executable, "-m", "serving", *module_argv, "--help"],
            cwd=str(SERVING_ROOT), capture_output=True, text=True,
            stdin=subprocess.DEVNULL, timeout=30)
        assert probe.returncode != 2, (
            f"serving rejected flags cmd_serve forwards: {module_argv}\n{probe.stderr[-500:]}")


# ── failure path: missing serving root ───────────────────────────────────

def test_missing_serving_root_fails_fast(capsys, tmp_path):
    args = SimpleNamespace(
        cluster_config=str(CLUSTER), dataset=str(DATASET), num_reqs=1,
        network_backend="analytical", log_level="WARNING", output=None,
        no_cleanup=False, no_prefix_caching=False, cycle_accurate=False,
        timeout=30,
    )
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr("veritx_dse.cli.cli.LLMSIM_DIR", tmp_path / "nonexistent")
        cmd_serve(Ctx(verbosity=0), args)
    err = capsys.readouterr().err
    assert "LLMServingSim not found" in err


# ── live end-to-end: real serving run through the CLI ────────────────────

@pytest.mark.skipif(not CLUSTER.is_file() or not DATASET.is_file(),
                    reason="serving fixtures not present")
@pytest.mark.skipif(not SERVING_ROOT.is_dir(),
                    reason="third_party/llmservingsim not vendored")
def test_serve_end_to_end_analytical():
    """Full stack through the CLI: spawn → protocol → clean shutdown.

    The analytical backend is pure Python (no BookSim binary needed) but
    rides the exact same shutdown path as the booksim backend. When the
    shutdown gate livelocks (the dense-DP bug class), this fails by timeout.
    """
    env = dict(os.environ)
    env.pop("VERITX_TIMEOUT", None)  # don't let ambient env inflate the budget
    proc = subprocess.run(
        [sys.executable, "-m", "veritx_dse.cli", "legacy", "serve",
         "--cluster-config", str(CLUSTER),
         "--dataset", str(DATASET),
         "--num-reqs", "1",
         "--network-backend", "analytical",
         "--log-level", "WARNING",
         "--timeout", "120"],
        cwd=str(REPO / "tracks" / "t3-topology" / "dse"),
        capture_output=True, text=True,
        stdin=subprocess.DEVNULL, env=env, timeout=180)
    assert proc.returncode == 0, f"serve failed:\n{proc.stderr[-1500:]}"
    assert "Simulation completed" in proc.stderr


# ── live end-to-end: the cycle-accurate NoC (the point of the forward-port) ─

BOOKSIM_BIN = REPO / "third_party" / "astra-sim" / "astra-sim" / \
    "network_frontend" / "booksim2" / "bin" / "AstraSim_BookSim2"


def _cli_serve(*extra: str, timeout_s: int = 120) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env.pop("VERITX_TIMEOUT", None)
    return subprocess.run(
        [sys.executable, "-m", "veritx_dse.cli", "legacy", "serve",
         "--cluster-config", str(CLUSTER),
         "--dataset", str(DATASET),
         "--num-reqs", "1",
         "--network-backend", "booksim",
         "--log-level", "WARNING",
         "--timeout", str(timeout_s), *extra],
        cwd=str(REPO / "tracks" / "t3-topology" / "dse"),
        capture_output=True, text=True,
        stdin=subprocess.DEVNULL, env=env, timeout=timeout_s + 60)


@pytest.mark.skipif(not CLUSTER.is_file() or not DATASET.is_file(),
                    reason="serving fixtures not present")
@pytest.mark.skipif(not BOOKSIM_BIN.exists(),
                    reason="AstraSim_BookSim2 binary not built")
def test_serve_end_to_end_booksim_replay_only():
    """Default booksim backend (replay-only) through the CLI, ~1.5s.

    Guards the CLI→module spawn for the veritx-default backend: the serving
    module itself is covered by test_full_pipeline.py, but the CLI wrapper
    (path resolution, flag forwarding, protocol shutdown) was not.
    """
    proc = _cli_serve()
    assert proc.returncode == 0, f"serve failed:\n{proc.stderr[-1500:]}"
    assert "Simulation completed" in proc.stderr


@pytest.mark.skipif(not CLUSTER.is_file() or not DATASET.is_file(),
                    reason="serving fixtures not present")
@pytest.mark.skipif(not BOOKSIM_BIN.exists(),
                    reason="AstraSim_BookSim2 binary not built")
def test_serve_end_to_end_booksim_cycle_accurate():
    """The advertised `--cycle-accurate` flag, live: real NoC simulation.

    This is the only test in the suite that exercises the full stack in
    non-replay mode (AstraSim+BookSim2 stepping actual flits). It pins two
    things: the inverted-flag forwarding (`--cycle-accurate` → module's
    `--no-booksim-replay-only`) and that cycle-accurate mode itself completes
    and reports latency numbers, not just exit 0. ~2s wall.
    """
    proc = _cli_serve("--cycle-accurate")
    assert proc.returncode == 0, f"serve failed:\n{proc.stderr[-1500:]}"
    err = proc.stderr
    assert "Simulation completed" in err
    # the run must report serving metrics — cycle-accurate mode must produce
    # a real latency breakdown, not merely "not crash"
    assert "ITL" in proc.stdout, (
        f"cycle-accurate run produced no ITL metrics:\n{proc.stdout[-800:]}")
