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
import json
import sys
from pathlib import Path

import pytest

TRACK = Path(__file__).resolve().parent.parent.parent   # .../tracks/t3-topology
SCRIPTS = TRACK / "scripts"
sys.path.insert(0, str(SCRIPTS))

import run_astrasim  # noqa: E402  (path set above)


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

    class R:
        returncode = 0
        stdout = "sys[0] finished, 99 cycles"
        stderr = ""

    monkeypatch.setattr(run_astrasim.subprocess, "run", lambda *a, **k: R())

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
    captured = {}

    def fake_run(cmd, capture_output, text, timeout):
        captured["cmd"] = cmd
        class R:
            returncode = 0
            stdout = "sys[0] finished, 1234 cycles"
            stderr = ""
        return R()

    monkeypatch.setattr(run_astrasim.subprocess, "run", fake_run)
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

    extra = [a for a in captured["cmd"] if a.startswith("--booksim2-extra=")]
    assert extra == ["--booksim2-extra=injection_rate=0.0"]
    assert r["astrasim_cycles"] == 1234          # real parse, not the fallback
    assert r["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. Honest provenance: the traffic proof field + the no-binary refusal
# ---------------------------------------------------------------------------

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
    class R:
        returncode = 0
        stdout = "sys[0] finished, 42 cycles"
        stderr = ""

    monkeypatch.setattr(run_astrasim.subprocess, "run", lambda *a, **k: R())
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
