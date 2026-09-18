"""Contract tests for the Ramulator execution backend (15b).

Verdicts, drain contract, tamper-evidence, typed metrics — all with a fake
runner (no Ramulator import). One live test runs the real backend when it
is built (skipif, like the booksim/astra needs_binary pattern).
"""
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.core.memory import AddressMappingPolicy
from veritx_dse.simulation.ramulator import (
    FIDELITY, MemoryEvidence, RamulatorBackend, RamulatorError, discover,
    execute, manifest_hash,
)
from veritx_dse.workload.canonical import (
    Parallelism, WorkloadArtifact, build_compute_op)
from veritx_dse.workload.memory_lowering import (
    MemorySystemDesign, hbm3_16gb_8hi_geometry, lower_to_ramulator_trace,
    resolve_memory,
)

DESIGN = MemorySystemDesign(hbm_devices=(0,))
POLICY = AddressMappingPolicy(name="contiguous_aligned_v1", version=1,
                              alignment_bytes=64, parameters={})
GEO = hbm3_16gb_8hi_geometry(num_channels=1)


def _manifest(tmp_path):
    ops = (build_compute_op("op0", 100, input_bytes=4096,
                            weight_bytes=8192, output_bytes=2048),)
    wl = WorkloadArtifact(workload_id="w", source_kind="test",
                          parallelism=Parallelism(), num_participants=1,
                          ops=ops)
    art = resolve_memory(wl, DESIGN, policy=POLICY).artifact
    trace = tmp_path / "t.trace"
    man = lower_to_ramulator_trace(art, GEO, out_path=trace)
    return man, trace


def _backend(tmp_path=None):
    # Fake identity: an (empty) ext file satisfies readiness; the tests
    # prove the verdict seam with a canned runner, not the simulator.
    pkg = Path(tmp_path) / "ram_pkg" if tmp_path else Path("/tmp/ram_pkg")
    pkg.mkdir(parents=True, exist_ok=True)
    ext = pkg / "_ramulator.so"
    ext.touch(exist_ok=True)
    return RamulatorBackend(python_exe=sys.executable, package_dir=pkg,
                            ext_path=ext)


def _stats(**kw):
    d = {"cycles": 1345, "num_read_reqs": 192, "num_write_reqs": 32,
         "num_read_reqs_served": 192, "num_write_reqs_served": 32,
         "num_write_reqs_coalesced": 0,
         "avg_read_latency": 275.0, "row_hits": 160, "row_misses": 1,
         "row_conflicts": 0}
    d.update(kw)
    return d


class _Runner:
    """Fake backend: writes stats.json into the run dir on call (as the
    real driver would), returns canned log output. stdout is log-only —
    the machine channel is the file."""

    def __init__(self, stats="__default__", returncode=0, stderr="",
                 log="RAMULATOR_DONE stats.json\n"):
        self._stats = stats
        self.returncode, self.stderr, self.log = returncode, stderr, log
        self.calls = []

    def __call__(self, cmd, cwd=None, timeout=None, env=None):
        self.calls.append(cmd)
        if self._stats is not None:
            payload = _stats() if self._stats == "__default__" else \
                self._stats
            if isinstance(payload, str):
                (Path(cwd) / "stats.json").write_text(payload)
            else:
                (Path(cwd) / "stats.json").write_text(json.dumps(payload))
        return SimpleNamespace(cmd=cmd, returncode=self.returncode,
                               stdout=self.log, stderr=self.stderr)


# ── verdicts (via monkeypatched runner seam) ────────────────────────────

def _run_with(monkeypatch, tmp_path, runner):
    import veritx_dse.core.process as proc
    monkeypatch.setattr(proc, "supervised_run", runner)
    man, trace = _manifest(tmp_path)
    return execute(man, trace, backend=_backend(tmp_path),
                   run_dir=tmp_path / "run"), man


class TestVerdicts:
    def test_full_drain_passes(self, monkeypatch, tmp_path):
        ev, man = _run_with(monkeypatch, tmp_path,
                            _Runner(_stats()))
        assert ev.status == "PASS"
        assert ev.fidelity == FIDELITY
        assert ev.metrics["completion_cycles"] == {
            "value": 1345, "unit": "cycles"}
        assert ev.metrics["average_read_latency_cycles"] == {
            "value": 275.0, "unit": "cycles"}
        assert ev.metrics["completed_read_bytes"] == {
            "value": 192 * 64, "unit": "bytes"}
        assert ev.metrics["row_hits"] == {"value": 160, "unit": "requests"}
        assert ev.failure_reason == ""
        assert ev.to_dict()["lowering_manifest_hash"] == manifest_hash(man)

    def test_drain_shortfall_is_inconclusive_not_pass(self, monkeypatch,
                                                     tmp_path):
        ev, _ = _run_with(monkeypatch, tmp_path, _Runner(
            _stats(num_read_reqs_served=160)))
        assert ev.status == "INCONCLUSIVE"
        assert "shortfall" in ev.failure_reason

    def test_backend_loss_is_inconclusive(self, monkeypatch, tmp_path):
        ev, _ = _run_with(monkeypatch, tmp_path, _Runner(
            _stats(num_read_reqs=100)))
        assert ev.status == "INCONCLUSIVE"
        assert "accepted" in ev.failure_reason

    def test_coalesced_writes_count_as_completed(self, monkeypatch,
                                                  tmp_path):
        ev, _ = _run_with(monkeypatch, tmp_path, _Runner(_stats(
            num_write_reqs_served=2, num_write_reqs_coalesced=30)))
        assert ev.status == "PASS"
        assert ev.metrics["coalesced_write_requests"] == {
            "value": 30, "unit": "requests"}

    def test_missing_coalesced_counter_refuses(self, monkeypatch, tmp_path):
        s = _stats()
        del s["num_write_reqs_coalesced"]
        ev, _ = _run_with(monkeypatch, tmp_path, _Runner(s))
        assert ev.status == "INCONCLUSIVE"
        assert "coalesced" in ev.failure_reason

    def test_missing_counter_refuses(self, monkeypatch, tmp_path):
        s = _stats()
        del s["num_write_reqs_served"]
        ev, _ = _run_with(monkeypatch, tmp_path,
                          _Runner(s))
        assert ev.status == "INCONCLUSIVE"
        assert "omitted counter" in ev.failure_reason

    def test_crash_is_evaluation_failed(self, monkeypatch, tmp_path):
        ev, _ = _run_with(monkeypatch, tmp_path,
                          _Runner(None, returncode=1,
                                  stderr="boom\ntraceback line"))
        assert ev.status == "EVALUATION_FAILED"
        assert "exited 1" in ev.failure_reason
        assert "boom" in ev.failure_reason

    def test_garbage_stats_file_is_evaluation_failed(self, monkeypatch,
                                                      tmp_path):
        ev, _ = _run_with(monkeypatch, tmp_path,
                          _Runner("not json\n"))
        assert ev.status == "EVALUATION_FAILED"
        assert "unparseable" in ev.failure_reason

    def test_missing_stats_file_is_evaluation_failed(self, monkeypatch,
                                                    tmp_path):
        ev, _ = _run_with(monkeypatch, tmp_path, _Runner(None))
        assert ev.status == "EVALUATION_FAILED"
        assert "no stats.json" in ev.failure_reason

    def test_absent_metric_stays_absent(self, monkeypatch, tmp_path):
        s = _stats()
        del s["avg_read_latency"]
        ev, _ = _run_with(monkeypatch, tmp_path,
                          _Runner(s))
        assert ev.status == "PASS"
        assert "average_read_latency_cycles" not in ev.metrics


# ── misuse raises; unsupported does not run ─────────────────────────────

class TestMisuse:
    def test_backend_not_built_raises(self, tmp_path):
        man, trace = _manifest(tmp_path)
        missing = tmp_path / "nope" / "_ramulator.so"  # never created
        be = RamulatorBackend(python_exe=sys.executable,
                              package_dir=tmp_path, ext_path=missing)
        assert not be.ready
        with pytest.raises(RamulatorError, match="not built"):
            execute(man, trace, backend=be, run_dir=tmp_path / "run")

    def test_tampered_trace_raises(self, monkeypatch, tmp_path):
        import veritx_dse.core.process as proc
        monkeypatch.setattr(proc, "supervised_run", _Runner())
        man, trace = _manifest(tmp_path)
        trace.write_text(trace.read_text() + "R 0,0,0,0,0,0,0\n")
        with pytest.raises(RamulatorError, match="trace_sha256"):
            execute(man, trace, backend=_backend(tmp_path),
                    run_dir=tmp_path / "run")

    def test_unsupported_geometry_returns_evidence(self, monkeypatch,
                                                  tmp_path):
        import veritx_dse.core.process as proc
        runner = _Runner()
        monkeypatch.setattr(proc, "supervised_run", runner)
        ops = (build_compute_op("op0", 100, input_bytes=64),)
        wl = WorkloadArtifact(workload_id="w", source_kind="test",
                              parallelism=Parallelism(), num_participants=1,
                              ops=ops)
        art = resolve_memory(wl, DESIGN, policy=POLICY).artifact
        import dataclasses
        geo = dataclasses.replace(GEO, dram_class="DDR5")
        trace = tmp_path / "t.trace"
        from veritx_dse.workload.memory_lowering import (
            lower_to_ramulator_trace as lower)
        man = lower(art, geo, out_path=trace)
        ev = execute(man, trace, backend=_backend(tmp_path),
                     run_dir=tmp_path / "run")
        assert ev.status == "UNSUPPORTED"
        assert "DDR5" in ev.failure_reason
        assert runner.calls == []  # nothing executed


# ── live backend (skipif, needs_binary pattern) ─────────────────────────

LIVE_PY = Path("/home/datavex/.local/bin/python3.12")
LIVE_VENDOR = DSE.parent.parent.parent / "third_party" / "ramulator2"
LIVE_PKG = LIVE_VENDOR / "python"
LIVE_EXT = list(LIVE_PKG.glob("ramulator/_ramulator*.so"))
needs_backend = pytest.mark.skipif(
    not (LIVE_PY.exists() and LIVE_EXT),
    reason="ramulator backend not built in the vendored tree")


@needs_backend
class TestLiveBackend:
    def test_discover_ready(self):
        be = discover(python_exe=str(LIVE_PY),
                      vendor_dir=LIVE_VENDOR)
        assert be.ready
        assert be.producer()["name"] == "ramulator"
        assert be.binary_hash().startswith("sha256:")

    def test_execute_passes_with_full_drain(self, tmp_path):
        be = discover(python_exe=str(LIVE_PY),
                      vendor_dir=LIVE_VENDOR)
        man, trace = _manifest(tmp_path)
        ev = execute(man, trace, backend=be, run_dir=tmp_path / "run",
                     timeout=300)
        assert ev.status == "PASS", ev.failure_reason
        m = ev.metrics
        assert m["issued_read_transactions"]["value"] == 192
        assert m["completed_read_bytes"]["value"] == 192 * 64
        assert {"row_hits", "row_misses", "row_conflicts"} <= set(m)
        assert (tmp_path / "run" / "driver.py").exists()
        assert (tmp_path / "run" / "stats.json").exists()
