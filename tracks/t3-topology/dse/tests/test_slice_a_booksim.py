"""Slice A acceptance tests: run_experiment (standalone BookSim) end-to-end.

Redesign PR 3 / §6 Slice A. These cross only the public seam — a raw spec
dict in, a finished immutable Run out — on the real binary (Layer-2/4
pattern: no subprocess mocks). The golden corpus pins the *simulator's*
number (35.0573); these tests pin the *control plane's* behavior:

  * spec -> SUCCEEDED run with results recorded in the manifest
  * two executions of one experiment: same experiment_hash, new run_id,
    identical latency (seeded determinism, corpus-verified mechanism)
  * bad intent (unknown field, unknown topology id, missing trace) is
    rejected loudly — with evidence in the run dir, debris nowhere else
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from veritx_dse.core.experiment import run_experiment
from veritx_dse.core.paths import BOOKSIM_DIR
from veritx_dse.core.runs import Run
from veritx_dse.core.spec import SpecError, experiment_hash

needs_booksim = pytest.mark.skipif(
    not (BOOKSIM_DIR / "booksim").exists(), reason="booksim binary not built"
)

TRACE = "tests/fixtures/traces/qwen3_20k.trace"  # 20k pkts, max_node 3


def _spec(**over):
    d = {
        "schema_version": 2,
        "name": "slice_a_qwen20k_mesh4x4",
        "workload": {"id": "qwen3_20k", "trace": TRACE},
        "system": {"nodes": 16},
        "network": {"topology": "mesh_4x4"},
        "simulation": {"mode": "latency", "network_simulator": "booksim",
                        "timeout_s": 120},
        "replication": {"mode": "deterministic", "seeds": [42]},
    }
    d.update(over)
    return d


@pytest.fixture()
def runs_root(tmp_path, monkeypatch):
    monkeypatch.setattr("veritx_dse.core.runs.VERITX_RUNS_DIR",
                        tmp_path / "veritx-runs")
    return tmp_path / "veritx-runs"


@needs_booksim
class TestSliceA:
    def test_e2e_succeeded(self, runs_root):
        import hashlib
        run = run_experiment(_spec())
        assert run.state == "SUCCEEDED"
        manifest = json.loads((run.root / "manifest.json").read_text())
        (res,) = manifest["results"]
        assert isinstance(res["latency"], float)
        # Provenance is automatic (ADR 0006): input content hash recorded
        # beside the result without anyone opting in.
        trace_abs = Path(__file__).resolve().parents[1] / TRACE
        want = hashlib.sha256(trace_abs.read_bytes()).hexdigest()
        assert res["trace_sha256"] == want

    def test_deterministic_replay(self, runs_root):
        r1 = run_experiment(_spec())
        r2 = run_experiment(_spec())
        # One experiment, two executions (ADR 0002): same intent, new id.
        assert r1.run_id != r2.run_id
        m1 = json.loads((r1.root / "manifest.json").read_text())
        m2 = json.loads((r2.root / "manifest.json").read_text())
        assert m1["experiment_hash"] == m2["experiment_hash"]
        assert m1["results"][0]["latency"] == m2["results"][0]["latency"]

    def test_result_frozen_spec_matches_hash(self, runs_root):
        run = run_experiment(_spec())
        frozen = json.loads((run.root / "spec.resolved.json").read_text())
        manifest = json.loads((run.root / "manifest.json").read_text())
        assert manifest["experiment_hash"] == experiment_hash(frozen)
        plan = json.loads((run.root / "plan.json").read_text())
        assert plan["experiment_hash"] == manifest["experiment_hash"]


class TestRejections:
    def test_unknown_field_rejected_no_debris(self, runs_root):
        with pytest.raises(SpecError):
            run_experiment(_spec(cutoff_latency=1))
        assert not runs_root.exists() or not list(runs_root.iterdir())

    def test_unknown_topology_id_rejected(self, runs_root):
        with pytest.raises(SpecError, match="registered"):
            run_experiment(_spec(network={"topology": "nonsense_9x9"}))
        assert not runs_root.exists() or not list(runs_root.iterdir())

    def test_missing_trace_cancelled_with_evidence(self, runs_root):
        run = run_experiment(
            _spec(workload={"id": "x",
                            "trace": "archive/inputs/traces/nope.trace"}))
        assert run.state == "CANCELLED"
        manifest = json.loads((run.root / "manifest.json").read_text())
        assert "no parseable packets" in manifest["results"][0]["error"] \
            or "trace invalid" in manifest["results"][0]["error"]
