"""Stage-4 product vertical slice: mesh_dense_64_v3.

Part 1 (live objects): v3 fixture -> compile -> cert PASS -> lower ->
P1B VC admission -> certified DOR BookSim -> route equivalence ->
quiescence -> evidence auth -> PerformanceResult -> RequirementReport,
persisting every intermediate to disk.

Part 2 (TRULY cold — RT-3): the reopen assertions run in a SUBPROCESS
(tests/cold_replay_p1_slice.py) that loads only the persisted directory.
It rebuilds the TemporalWorkload from the AUTHENTICATED window binding
(the PerformanceModel is persisted only by id), proves the rebuilt
parents reproduce temporal_workload_id, and requires
performance/result.py::reverify_result to accept the persisted
PerformanceResult — event-graph reconstruction, deterministic scheduler
re-run, summary re-derivation and resource_id recomputation. The parent
asserts on that subprocess's canonical JSON, cross-checked against the
persisted documents; no warm Python object from the live phase is used
for the cold assertions beyond paths.

Tamper tests pin that a mutated persisted performance field (summary
value, network-binding cycles, Wave-D chain id) with a stale
resource_id is refused by reverify_result (ResultError).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest

from veritx_dse.application.product_evaluator import evaluate_product
from veritx_dse.core.paths import REPO
from veritx_dse.model.compile_model import CompileRequestV3
from veritx_dse.performance.result import ResultError, reverify_result
from veritx_dse.simulation.booksim import find_booksim_bin

from cold_replay_p1_slice import (  # noqa: E402
    load_persisted,
    rebuild_temporal_workload,
)

DSE = Path(__file__).resolve().parents[1]
HELPER = DSE / "tests" / "cold_replay_p1_slice.py"
FIXTURE = (REPO / "tracks" / "t3-topology" / "examples" /
           "llama_dense_64tiles-v3.json")


def _load_request() -> tuple[CompileRequestV3, dict]:
    doc = json.loads(FIXTURE.read_text())
    return CompileRequestV3.from_dict(doc), doc


def _persist(persist: Path, prod, request_doc: dict) -> None:
    """Persist every intermediate as BYTES (the only cold transport)."""
    (persist / "request.json").write_text(json.dumps(
        request_doc, indent=2))
    (persist / "certificate.json").write_text(json.dumps(
        prod.compilation.certificate.to_dict(), indent=2))
    (persist / "workload_graph.json").write_text(json.dumps(
        prod.lowered.graph.to_dict()))
    (persist / "sidecar.json").write_text(json.dumps({
        "traffic_class_by_operation":
            [list(p) for p in prod.lowered.traffic_class_by_operation],
        "design_hash": prod.lowered.design_hash,
    }))
    (persist / "performance_result.json").write_text(json.dumps(
        prod.outcome.performance_result, indent=2))
    (persist / "requirement_report.json").write_text(json.dumps(
        prod.requirement_report, indent=2))
    # Paths only: the evidence file lives outside the persist dir and is
    # named by the manifest; every digest is re-derived from bytes.
    (persist / "manifest.json").write_text(json.dumps({
        "evidence_path": prod.outcome.evidence_path,
    }))


@pytest.fixture(scope="module")
def slice_run(tmp_path_factory):
    """Run the live chain ONCE; persist the transport for the cold half."""
    request, request_doc = _load_request()
    root = tmp_path_factory.mktemp("p1_slice")
    run_dir = root / "run"
    persist = root / "persist"
    persist.mkdir()
    binary = find_booksim_bin(REPO)
    prod = evaluate_product(
        request, binary=str(binary), run_dir=str(run_dir),
        network_clock_hz=10 ** 9, timeout_s=900)
    _persist(persist, prod, request_doc)
    return {"prod": prod, "persist": persist, "run_dir": run_dir}


def test_mesh_dense_64_v3_vertical_slice(slice_run):
    """Part 1: the live chain and its view/report contract."""
    prod = slice_run["prod"]
    request = prod.request
    assert prod.compilation.status == "COMPILED", prod.compilation.error
    obligations = prod.compilation.certificate.obligations
    assert len(obligations) == 10
    assert prod.compilation.certificate.overall == "PASS"
    assert all(o.status == "PASS" for o in obligations)
    assert prod.lowered.graph.participant_count == 8
    assert prod.lowered.unified_traffic_class == "tp_collective"
    assert prod.status == "EVALUATED", prod.reason
    assert prod.outcome.backend_profile == "CERTIFIED_BOOKSIM_MESH_DOR_XY_V1"
    assert prod.outcome.performance_result is not None
    assert prod.requirements_pass is True
    assert all(e["verdict"] == "SATISFIED"
               for e in prod.requirement_report["entries"])
    assert request.design_hash() == prod.lowered.design_hash
    jsonschema.validate(
        prod.outcome.to_view_dict(),
        json.loads((REPO / "contracts" / "srota" / "v1" /
                    "evaluation.view.schema.json").read_text()))
    jsonschema.validate(
        prod.requirement_report,
        json.loads((REPO / "contracts" / "srota" / "v1" /
                    "requirement.report.schema.json").read_text()))


def test_cold_replay_subprocess_uses_reverify_result(slice_run):
    """Part 2: a fresh interpreter replays the persisted bytes only and
    must pass reverify_result before any verdict is reported."""
    persist = slice_run["persist"]
    env = dict(os.environ)
    pypath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(DSE) + (os.pathsep + pypath if pypath else "")
    proc = subprocess.run(
        [sys.executable, str(HELPER), str(persist)],
        cwd=str(DSE), env=env, capture_output=True, text=True, timeout=900)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["ok"] is True
    assert out["reverified"] is True
    assert out["requirements_pass"] is True
    assert out["verdicts"] and all(v == "SATISFIED"
                                   for v in out["verdicts"])

    # Parent cross-check: only the PERSISTED documents (bytes), never a
    # warm object from the live phase.
    docs = load_persisted(persist)
    perf = docs["performance_result"]
    chain = perf["wave_d_chain"]
    binding = perf["network_binding"]
    assert out["performance_result_id"] == perf["resource_id"]
    assert out["workload_id"] == chain["workload_graph_id"]
    assert out["message_artifact_id"] == chain["message_artifact_id"]
    assert out["physical_traffic_id"] == chain["physical_traffic_id"]
    assert out["temporal_workload_id"] == perf["temporal_workload_id"]
    assert out["evidence_digest"] == binding["evidence_sha256"]
    assert out["stats_digest"] == binding["stats_sha256"]
    assert out["design_hash"] == docs["requirement_report"]["design_hash"]
    assert out["certificate_id"] == docs["certificate"]["certificate_id"]


def _tamper_makespan(perf):
    perf["makespan"]["numerator"] += 1


def _tamper_utilization(perf):
    perf["utilization"]["fabric.network_window"]["utilization"] = 0.5


def _tamper_binding_cycles(perf):
    # The cycles-derived wall duration: doubling it fabricates half the
    # completion_time with the same recorded clock.
    perf["network_binding"]["duration"]["numerator"] *= 2


def _tamper_chain_id(perf):
    perf["wave_d_chain"]["workload_graph_id"] = "0" * 64


@pytest.mark.parametrize(
    "mutate,match",
    [(_tamper_makespan, "makespan"),
     (_tamper_utilization, "utilization"),
     (_tamper_binding_cycles, "event_graph_id"),
     (_tamper_chain_id, "event_graph_id")],
    ids=["summary-makespan", "summary-utilization",
         "network-binding-duration", "wave-d-chain-id"])
def test_tampered_persisted_result_refuses(slice_run, mutate, match):
    docs = load_persisted(slice_run["persist"])
    perf = json.loads(json.dumps(docs["performance_result"]))
    temporal = rebuild_temporal_workload(perf)
    assert temporal.temporal_workload_id() == perf["temporal_workload_id"]
    mutate(perf)
    with pytest.raises(ResultError) as ei:
        reverify_result(perf, workload=temporal)
    assert match in str(ei.value)
