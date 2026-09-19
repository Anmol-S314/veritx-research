"""Contract tests for the t3 astrasim spine (scripts/run_astrasim.py).

These pin the shape of the spine that `t3 astrasim` drives:

1. **Single-run mode** — one evaluation per topology. Embedded AstraSim_BookSim2
   injects collective packets via the frontend API, so the standalone-BookSim
   injection-rate dimension is vestigial: sweeping it produced N identical
   cycle counts and N times the wall-clock. The loop must stay single-depth.
2. **Embedded injection override** — every real binary invocation passes
   `--booksim2-extra=injection_rate=0.0` (the template cfgs carry
   standalone-style injection rates; without the override the traffic manager
   self-injects infinite synthetic traffic) and records the same value in the
   row so PA-01/aggregate/energy consumers see a stable schema.
3. **Honest provenance** — rows carry `traffic: "astrasim(<model>_chakra_et)"`,
   the documented proof field that the Chakra trace, not template traffic, was
   the workload; and with no binary available the runner refuses rather than
   fabricating a synthetic result.

Real objects throughout (the real trace generator, the real adapter); only the
ASTRA-sim binary boundary is faked, and only where a real multi-minute
simulation is not needed to pin the contract.
"""
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest

TRACK = Path(__file__).resolve().parent.parent.parent   # .../tracks/t3-topology
SCRIPTS = TRACK / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_astrasim  # noqa: E402  (path set above)


# ---------------------------------------------------------------------------
# Fake binary boundary: the runner spawns via subprocess.Popen + pump threads
# (live progress display), so tests fake THAT boundary — in-memory pipes the
# pump threads drain, plus poll/kill/wait — while recording the spawn kwargs
# so invocation contracts (stdin, --booksim2-extra) stay pinned.
# ---------------------------------------------------------------------------

class _FakePopen:
    def __init__(self, stdout_text, stderr_text="", returncode=0):
        self._stdout_text = stdout_text
        self._stderr_text = stderr_text
        self.returncode = returncode
        self.cmd = None
        self.kwargs = {}
        self.stdout = io.StringIO("")
        self.stderr = io.StringIO("")
        self.killed = False

    def __call__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.stdout = io.StringIO(self._stdout_text)
        self.stderr = io.StringIO(self._stderr_text)
        return self

    def poll(self):
        # Still "running" while the pump threads haven't drained the pipes
        # (a closed stream means its pump finished: fully drained).
        try:
            if self.stdout.tell() < len(self._stdout_text):
                return None
            if self.stderr.tell() < len(self._stderr_text):
                return None
        except ValueError:
            pass
        return self.returncode

    def kill(self):
        self.killed = True

    def wait(self, timeout=None):
        return self.returncode


def _fake_popen(monkeypatch, stdout_text, stderr_text="", returncode=0):
    """Patch run_astrasim's subprocess.Popen; returns the recorder instance."""
    fake = _FakePopen(stdout_text, stderr_text, returncode)
    monkeypatch.setattr(run_astrasim.subprocess, "Popen", fake)
    return fake


# ---------------------------------------------------------------------------
# 1. Single-run mode: main() drives one run per topology, no IR nesting
# ---------------------------------------------------------------------------

def test_topology_loop_is_single_depth():
    """The sweep loop must call the runner once per config, not once per
    (config, injection-rate) pair — the IR dimension is vestigial in
    embedded mode."""
    src = (SCRIPTS / "run_astrasim.py").read_text()

    # The main() sweep region must not contain a nested rate loop.
    main_region = src.split("def main()", 1)[1]
    assert "for inj_rate in" not in main_region, (
        "main() still sweeps injection rates — embedded mode owns the rate "
        "dimension and every swept row was a duplicate"
    )
    assert "injection_rates" not in main_region, (
        "main() still materialises an injection-rate list"
    )
    # ...and the runner consumes exactly one topology config per call.
    assert main_region.count("run_astrasim_topology(") == 1


def test_row_schema_records_embedded_injection_rate(tmp_path, monkeypatch):
    """Rows report injection_rate=0.0 — the value actually passed to the
    traffic manager — keeping the schema stable for PA-01/aggregate."""
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )

    _fake_popen(monkeypatch, "sys[0] finished, 99 cycles")

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    spec = {
        "model_name": "ALL_REDUCE",
        "is_collective_microbenchmark": True,
        "msg_size_mb": 1.0,
        "num_layers": 1,
        "total_allreduce_calls": 1,
        "total_flops": 1e9,
        "tp_degree": 1,
        "pp_degree": 1,
    }

    r = run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")

    assert r["injection_rate"] == 0.0
    # Output dir no longer carries the vestigial inj_* rate tag.
    out_dir = tmp_path / "baseline" / "astrasim"
    written = [p.name for p in out_dir.rglob("*")]
    assert written and all(not n.startswith("inj_") for n in written)


def test_run_invocation_pins_embedded_injection_override(tmp_path, monkeypatch):
    """The real binary path must pass --booksim2-extra=injection_rate=0.0 and
    only that injection knob — proving the trace (not template traffic) drives
    the run."""
    proc = _fake_popen(monkeypatch, "sys[0] finished, 1234 cycles")
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    spec = {
        "model_name": "ALL_REDUCE",
        "is_collective_microbenchmark": True,
        "msg_size_mb": 1.0,
        "num_layers": 1,
        "total_allreduce_calls": 1,
        "total_flops": 1e9,
        "tp_degree": 1,
        "pp_degree": 1,
    }

    r = run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")

    extra = [a for a in proc.cmd if a.startswith("--booksim2-extra=")]
    assert extra == ["--booksim2-extra=injection_rate=0.0"]
    assert r["astrasim_cycles"] == 1234          # real parse, not the fallback
    assert r["status"] == "ok"


def test_flit_bytes_is_explicit_recorded_and_labelled(tmp_path, monkeypatch):
    """Packetization is a comparison key, not cosmetic provenance.

    The runner must (a) pass --booksim2-flit-bytes explicitly, (b) record
    flit_bytes/flit_bits/model/fidelity in the row, and (c) label a coarse
    override distinctly from the 8-byte backend default, so a 512 B run can
    never be ranked as equivalent-fidelity to an 8 B run.
    """
    proc = _fake_popen(monkeypatch, "sys[0] finished, 1234 cycles")
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)
    monkeypatch.setenv("ASTRASIM_FLIT_BYTES", "512")

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text("topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\n")
    spec = {
        "model_name": "ALL_GATHER",
        "is_collective_microbenchmark": True,
        "msg_size_mb": 16.0,
        "num_layers": 1,
        "total_allreduce_calls": 1,
        "total_flops": 1e9,
        "tp_degree": 1,
        "pp_degree": 1,
    }

    r = run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")

    assert "--booksim2-flit-bytes=512" in proc.cmd
    assert r["flit_bytes"] == 512
    assert r["flit_bits"] == 4096                      # derived, one authority
    assert r["embedded_mtu_flits"] == 0
    assert r["packetization_model"] == "single_wormhole_packet_per_send"
    assert r["packetization_fidelity"] == "coarse_packetization_override"
    assert r["message_size_bytes"] == 16777216


def test_packetization_defaults_and_validation():
    rec = run_astrasim._packetization_record(8)        # backend default
    assert rec["packetization_fidelity"] == "backend_default"
    assert rec["flit_bits"] == 64
    assert run_astrasim._resolve_flit_bytes({}) == 128
    assert run_astrasim._resolve_flit_bytes(
        {"ASTRASIM_FLIT_BYTES": "256"}) == 256
    for bad in ("0", "-8", "eight", ""):
        with pytest.raises(ValueError):
            run_astrasim._resolve_flit_bytes({"ASTRASIM_FLIT_BYTES": bad})


# Real-binary ABI canary: guards the Python ET writer ↔ ETFeederNode ↔ Sys
# seam (the field-9 comm_size mismatch silently decoded as 0 and stalled the
# run). Gated on the host-built frontend.
_ASTRA_BS_BIN = (TRACK.parent.parent / "third_party" / "astra-sim" /
                 "astra-sim" / "network_frontend" / "booksim2" / "bin" /
                 "AstraSim_BookSim2")
_needs_binary = pytest.mark.skipif(
    not _ASTRA_BS_BIN.exists(),
    reason="AstraSim_BookSim2 frontend binary not built")


@_needs_binary
def test_real_frontend_decodes_comm_size_and_completes(tmp_path):
    import os
    import shutil
    from generate_chakra_trace import ChakraTraceGenerator, save_chakra_trace

    nodes = ChakraTraceGenerator().build_collective_trace(
        comm_type="ALL_GATHER", msg_size_bytes=1024)
    res = save_chakra_trace(nodes, tmp_path, "abi")
    et = Path(res["et_binary"])
    for rank in range(16):
        shutil.copy(et, Path(str(et) + f".{rank}.et"))

    fix = Path(__file__).parent / "fixtures" / "astra_tiny"
    env = dict(os.environ, VERITX_LEDGER="1")
    proc = subprocess.run(
        [str(_ASTRA_BS_BIN),
         f"--workload-configuration={et}",
         f"--system-configuration={fix / 'system.json'}",
         f"--network-configuration={fix / 'network.json'}",
         f"--remote-memory-configuration={fix / 'memory.json'}",
         f"--logical-topology-configuration={fix / 'logical_topology.json'}",
         "--logging-configuration", "empty",
         "--booksim2-extra=injection_rate=0.0"],
        cwd=str(fix), stdin=subprocess.DEVNULL, capture_output=True,
        text=True, timeout=180, env=env)
    out = proc.stdout + proc.stderr
    assert "comm_size=1024" in out, out[-800:]
    assert "finished" in out, out[-800:]


def test_run_invocation_closes_stdin(tmp_path, monkeypatch):
    """The frontend's post-simulation command loop reads stdin forever: with
    an inherited interactive terminal it blocks after every rank has finished
    (the 1800s TimeoutExpired on `t3 astrasim`). The invocation must pass
    stdin=subprocess.DEVNULL so the loop sees EOF and exits cleanly.

    Reproduced at fd level: an open-but-silent pipe (writer never writes,
    never closes) keeps the process alive indefinitely after all 16
    `sys[*] finished` lines; /dev/null exits normally. Same binary, same
    workload — stdin is the only variable.
    """
    proc = _fake_popen(monkeypatch, "sys[0] finished, 1234 cycles")
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    spec = {
        "model_name": "ALL_REDUCE",
        "is_collective_microbenchmark": True,
        "msg_size_mb": 1.0,
        "num_layers": 1,
        "total_allreduce_calls": 1,
        "total_flops": 1e9,
        "tp_degree": 1,
        "pp_degree": 1,
    }

    run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")

    assert proc.kwargs["stdin"] is subprocess.DEVNULL, (
        "binary spawned with inherited stdin — post-simulation command loop "
        "will block forever on an interactive terminal"
    )


def test_row_wires_exposed_comm_from_finished_lines(tmp_path, monkeypatch):
    """The frontend prints 'sys[i] finished, N cycles, exposed communication M
    cycles.' The spine must surface the real numbers: latency_cycles = max
    wall across ranks, exposed_comm_cycles from that same rank, and the
    derived comm_overhead_pct — no placeholders, no fabrication."""
    _fake_popen(monkeypatch,
                "sys[0] finished, 2000 cycles, exposed communication 1500 cycles.\n"
                "sys[1] finished, 2200 cycles, exposed communication 1400 cycles.\n")
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    spec = {
        "model_name": "ALL_REDUCE",
        "is_collective_microbenchmark": True,
        "msg_size_mb": 1.0,
        "num_layers": 1,
        "total_allreduce_calls": 1,
        "total_flops": 1e9,
        "tp_degree": 1,
        "pp_degree": 1,
    }

    r = run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")

    assert r["astrasim_cycles"] == 2200          # max wall across ranks
    assert r["latency_cycles"] == 2200           # embedded mode: wall IS latency
    assert r["exposed_comm_cycles"] == 1400      # exposed from the slowest rank
    assert r["comm_overhead_pct"] == round(100.0 * 1400 / 2200, 2)


def test_parse_plat_line_extracts_exact_fields():
    """The [plat] frontend line parses into the plat_stats dict; a stdout
    without it yields None (older binary) — absence is honest, never fake."""
    line = ("[plat] packets=480 avg=23.375 min=19 p50=19 p95=44 p99=44 "
            "max=44 hops_avg=2.875 hops_min=2 hops_max=7")
    plat = run_astrasim._parse_plat_line(line)
    assert plat == {
        "packets": "480", "avg": "23.375", "min": "19", "p50": "19",
        "p95": "44", "p99": "44", "max": "44",
        "hops_avg": "2.875", "hops_min": "2", "hops_max": "7",
    }
    assert run_astrasim._parse_plat_line("sys[0] finished, 50310 cycles") is None


def test_row_carries_plat_stats_when_emitted(tmp_path, monkeypatch):
    """When the binary prints [plat], the sweep row surfaces it."""
    _fake_popen(monkeypatch,
                "sys[0] finished, 50310 cycles, exposed communication 30310 cycles.\n"
                "[plat] packets=480 avg=23.375 min=19 p50=19 p95=44 p99=44 "
                "max=44 hops_avg=2.875 hops_min=2 hops_max=7\n")
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    spec = {
        "model_name": "ALL_REDUCE",
        "is_collective_microbenchmark": True,
        "msg_size_mb": 1.0,
        "num_layers": 1,
        "total_allreduce_calls": 1,
        "total_flops": 1e9,
        "tp_degree": 1,
        "pp_degree": 1,
    }

    r = run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")
    assert r["plat_stats"] == {
        "packets": "480", "avg": "23.375", "min": "19", "p50": "19",
        "p95": "44", "p99": "44", "max": "44",
        "hops_avg": "2.875", "hops_min": "2", "hops_max": "7",
    }
    assert r["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. Honest provenance: the traffic proof field + the no-binary refusal
# ---------------------------------------------------------------------------

def test_dangling_astrasim_bin_warns_and_falls_back(monkeypatch, capsys):
    """A set-but-dangling ASTRASIM_BIN (checkout moved/deleted) must not
    masquerade as unset: warn loudly, then fall back to the repo-built
    frontend before ever considering PATH."""
    monkeypatch.setenv("ASTRASIM_BIN", "/gone/checkout/AstraSim_BookSim2")
    found = run_astrasim.find_astrasim_bin()
    assert found is not None and "veritx-research" in found
    assert "does not exist" in capsys.readouterr().out


def test_missing_binary_refusal_names_the_env(monkeypatch, tmp_path):
    """With no binary anywhere the refusal stays the honesty gate — the
    spec-mandated no-synthetic-fallback behaviour."""
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)
    monkeypatch.setattr(run_astrasim, "find_astrasim_bin", lambda: None)
    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    spec = run_astrasim.ChakraTraceGenerator().resolve_spec(
        "llama7b", num_layers=1)
    with pytest.raises(RuntimeError, match="Refusing to substitute"):
        run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")


def test_t3_native_branch_overrides_stale_env():
    """t3's native-execution branch must pass the ldd-verified binary path
    explicitly (ASTRASIM_BIN=... exec python3 ...) so a stale env var from a
    moved checkout cannot sabotage a verified binary."""
    t3_src = (SCRIPTS.parent / "t3").read_text()
    native_region = t3_src.split('"${1:-}" = "astrasim"', 1)[1]
    assert "ASTRASIM_BIN=\"$_asim_bin\"" in native_region, (
        "native branch no longer passes the verified binary path"
    )


def test_traffic_proof_field_names_the_chakra_trace(tmp_path, monkeypatch):
    # Real spec resolution — the same path main() takes for llama7b.
    spec = run_astrasim.ChakraTraceGenerator().resolve_spec("llama7b", num_layers=1)
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path)

    cfg = tmp_path / "mesh4x4.cfg"
    cfg.write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )

    # No binary → runner refuses before any result is produced.
    monkeypatch.setattr(run_astrasim, "find_astrasim_bin", lambda: None)
    with pytest.raises(RuntimeError, match="Refusing to substitute"):
        run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")

    # With the (faked) binary, the row carries the documented proof field.
    # pp override mirrors main()'s --pp 1 acceptance: raw registry pp>1 is
    # refused by the replicated-trace guard (per-rank sharding unimplemented).
    spec["pp_degree"] = 1
    _fake_popen(monkeypatch, "sys[0] finished, 42 cycles")
    monkeypatch.setattr(
        run_astrasim, "find_astrasim_bin", lambda: "/fake/AstraSim_BookSim2"
    )
    r = run_astrasim.run_astrasim_topology(cfg, spec, config_name="baseline")
    assert r["traffic"] == "astrasim(llama-7b_chakra_et)"


def test_sweep_json_and_topology_sweep_written_together(tmp_path, monkeypatch, capsys):
    """main() writes both result artifacts (astrasim_sweep.json and the
    integrated topology_sweep.json) with one row per topology."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(run_astrasim, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(run_astrasim, "CONFIGS_DIR", tmp_path / "configs")
    cfgdir = tmp_path / "configs"
    cfgdir.mkdir()
    (cfgdir / "mesh4x4.cfg").write_text(
        "topology = mesh;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )
    (cfgdir / "torus4x4.cfg").write_text(
        "topology = torus;\nk = 4;\nn = 2;\nnum_vcs = 4;\npacket_size = 5;\n"
    )

    calls = []

    def fake_run_topology(cfg, spec, config_name):
        calls.append(cfg.stem)
        return {
            "topology": cfg.stem,
            "workload": "ALL_REDUCE",
            "total_nodes": 16,
            "astrasim_cycles": 1000 + len(calls),
            "latency_cycles": None,
            "comm_overhead_pct": None,
            "injection_rate": 0.0,
            "hops_avg": None,
            "traffic": "astrasim(all_reduce_chakra_et)",
            "status": "ok",
        }

    monkeypatch.setattr(
        run_astrasim, "run_astrasim_topology", fake_run_topology
    )

    # Microbenchmark spec path skips resolve_spec entirely.
    sys.argv = ["run_astrasim.py", "--model", "all_reduce", "--config", "baseline"]
    run_astrasim.main()

    assert calls == ["mesh4x4", "torus4x4"]          # one run per topology
    res = tmp_path / "results" / "baseline"
    astro = json.loads((res / "astrasim_sweep.json").read_text())
    topo = json.loads((res / "topology_sweep.json").read_text())
    assert astro == topo
    assert [r["topology"] for r in astro] == ["mesh4x4", "torus4x4"]
    assert {r["injection_rate"] for r in astro} == {0.0}
    assert all(r["traffic"].startswith("astrasim(") for r in astro)
