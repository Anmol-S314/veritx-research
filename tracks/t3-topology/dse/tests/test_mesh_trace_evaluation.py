"""Diagnostic mesh-DOR raw-trace evaluator tests.

Every test injects a fake runner, so no real BookSim binary is required.
The bridge is explicitly diagnostic: these tests pin its refusals and its
``DIAGNOSTIC_MESH_DOR`` / ``exact_fabric_eligible=False`` labels.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from veritx_dse.backend.mesh_trace_evaluation import (
    CONFIG_FILENAME,
    EVIDENCE_FILENAME,
    LIMITATIONS,
    MeshTraceEvaluation,
    MeshTraceEvaluationError,
    QUALIFICATION,
    TRACE_FILENAME,
    evaluate_mesh_dor_trace,
)
from veritx_dse.model.compile_model import (
    Agent,
    AgentKind,
    CollectiveDimension,
    CollectiveIntent,
    CollectiveKind,
    DependencyGraph,
    ModelFamily,
    PhysicalContext,
    QoSClass,
    RequirementV3,
    ServingMode,
    WorkloadV3,
)
from veritx_dse.model.compile_request_v4 import CompileRequestV4
from veritx_dse.model.noc_controls import NocControls
from veritx_dse.model.topology_intent import MeshIntent, TorusIntent

#: 4 endpoints, one class, five whitespace columns per data line.
TRACE = b"""# diagnostic mesh-DOR raw trace
0 0 0 1 1
0 1 0 0 1
1 2 0 3 1
1 3 0 2 1
"""

#: The exact metric shape the fake runner returns.
FAKE_STATS = {
    "completion_time": 100,
    "latency": 12.5,
    "p50": 10.0,
    "p95": 20.0,
    "p99": 30.0,
    "hops": 2.0,
}


def _request(*, topology=None) -> CompileRequestV4:
    """Minimal compiling v4 request: 4 agents on a typed 2x2 mesh."""
    return CompileRequestV4(
        workload=WorkloadV3(
            model_family=ModelFamily.DENSE_TRANSFORMER,
            tp=4,
            serving_mode=ServingMode.MIXED,
            collectives=(
                CollectiveIntent(
                    kind=CollectiveKind.ALLREDUCE,
                    dimension=CollectiveDimension.TP,
                    payload_bytes=8192,
                    traffic_class="tp_collective",
                ),
            ),
        ),
        requirements=(
            RequirementV3(
                qos_class=QoSClass.LATENCY_CRITICAL,
                traffic_class="tp_collective",
                binding=True,
                latency_ceiling_cycles=100000,
            ),
        ),
        agents=(
            Agent(
                kind=AgentKind.COMPUTE_TILE,
                count=4,
                protocol="AXI",
                data_width=256,
                addr_width=64,
            ),
        ),
        dependencies=DependencyGraph(()),
        topology=topology or MeshIntent(side_length=2, concentration=1),
        noc_controls=NocControls(link_width=64),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
    )


def _request_doc(**kwargs) -> dict:
    return _request(**kwargs).to_dict()


def _fake_runner(calls: list[dict] | None = None,
                 result: dict | None = None):
    def runner(ctx, config, *, repo_root, timeout):
        if calls is not None:
            calls.append({
                "ctx": ctx,
                "config": config,
                "repo_root": repo_root,
                "timeout": timeout,
            })
        return dict(FAKE_STATS if result is None else result)

    return runner


def _must_not_run(*args, **kwargs):
    raise AssertionError("runner must not be called")


def _assert_json_native(value) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert isinstance(key, str), f"non-string JSON key: {key!r}"
            _assert_json_native(item)
    elif isinstance(value, list):
        for item in value:
            _assert_json_native(item)
    else:
        assert value is None or isinstance(value, (str, int, float, bool)), (
            f"not JSON-native: {value!r} ({type(value).__name__})")


def test_evaluate_mesh_dor_trace_compiles_runs_and_persists_json(tmp_path):
    run_dir = tmp_path / "run"
    calls: list[dict] = []

    evaluation = evaluate_mesh_dor_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=run_dir,
        seed=7,
        timeout=33,
        runner=_fake_runner(calls),
    )

    assert isinstance(evaluation, MeshTraceEvaluation)
    assert evaluation.request_design_hash == _request().design_hash()
    assert evaluation.topology == "mesh_2x2"
    assert evaluation.k == 2
    assert evaluation.vc_count == 1
    assert evaluation.link_width_bits == 64
    assert evaluation.trace_sha256 == hashlib.sha256(TRACE).hexdigest()
    assert evaluation.trace_summary == {
        "packets": 4,
        "max_timestamp": 1,
        "endpoints": 4,
    }
    assert evaluation.qualification == QUALIFICATION == "DIAGNOSTIC_MESH_DOR"
    assert evaluation.exact_fabric_eligible is False
    assert evaluation.stats == FAKE_STATS
    assert evaluation.seed == 7
    assert evaluation.sample_period == 1001
    assert evaluation.output_dir == str(run_dir)
    assert evaluation.limitations == LIMITATIONS
    assert any("legacy mesh config" in item
               for item in evaluation.limitations)
    assert any("VC assignment" in item for item in evaluation.limitations)
    assert any("route dump" in item for item in evaluation.limitations)
    assert any("ASTRA" in item for item in evaluation.limitations)

    config_bytes = (run_dir / CONFIG_FILENAME).read_bytes()
    config = config_bytes.decode("utf-8")
    assert evaluation.config_sha256 == hashlib.sha256(config_bytes).hexdigest()
    assert "topology = mesh;" in config
    assert "routing_function = dim_order;" in config
    assert "k = 2;" in config
    assert "n = 2;" in config
    assert "sample_period = 1001;" in config
    assert "seed = 7;" in config
    assert (run_dir / TRACE_FILENAME).read_bytes() == TRACE

    assert len(calls) == 1
    assert calls[0]["ctx"].verbosity == 0
    assert calls[0]["config"] == config
    assert calls[0]["repo_root"] == tmp_path
    assert calls[0]["timeout"] == 33

    document = json.loads((run_dir / EVIDENCE_FILENAME).read_text())
    assert document == evaluation.to_dict()
    assert document["qualification"] == "DIAGNOSTIC_MESH_DOR"
    assert document["exact_fabric_eligible"] is False
    assert document["stats"] == FAKE_STATS
    assert document["config_sha256"] == evaluation.config_sha256
    assert document["limitations"] == list(LIMITATIONS)
    _assert_json_native(document)
    _assert_json_native(evaluation.to_dict())


def test_default_runner_uses_legacy_run_booksim(monkeypatch, tmp_path):
    calls: list[dict] = []

    def fake_run_booksim(ctx, config, *, repo_root, timeout):
        calls.append({
            "ctx": ctx,
            "config": config,
            "repo_root": repo_root,
            "timeout": timeout,
        })
        return dict(FAKE_STATS)

    monkeypatch.setattr(
        "veritx_dse.backend.mesh_trace_evaluation.run_booksim",
        fake_run_booksim,
    )

    evaluation = evaluate_mesh_dor_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=tmp_path / "run",
        booksim_bin=Path("/opt/fake/booksim"),
        seed=1,
        timeout=22,
    )

    assert evaluation.stats == FAKE_STATS
    assert len(calls) == 1
    assert calls[0]["ctx"].verbosity == 0
    assert calls[0]["repo_root"] == tmp_path
    assert calls[0]["timeout"] == 22
    assert "topology = mesh;" in calls[0]["config"]


def test_trace_class_one_is_refused_before_runner(tmp_path):
    calls: list[dict] = []

    with pytest.raises(MeshTraceEvaluationError, match="class column 0"):
        evaluate_mesh_dor_trace(
            _request_doc(),
            b"0 0 1 1 1\n",
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_fake_runner(calls),
        )

    assert calls == []


def test_trace_endpoint_out_of_range_is_refused_before_runner(tmp_path):
    calls: list[dict] = []

    with pytest.raises(MeshTraceEvaluationError, match="outside"):
        evaluate_mesh_dor_trace(
            _request_doc(),
            b"0 0 0 4 1\n",
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_fake_runner(calls),
        )

    assert calls == []


def test_non_mesh_request_is_refused(tmp_path):
    calls: list[dict] = []

    with pytest.raises(MeshTraceEvaluationError, match="typed mesh"):
        evaluate_mesh_dor_trace(
            _request_doc(topology=TorusIntent(side_length=2)),
            TRACE,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_fake_runner(calls),
        )

    assert calls == []


@pytest.mark.parametrize("version", [3, 5])
def test_non_v4_request_is_refused_without_migration(version, tmp_path):
    document = _request_doc()
    document["schema_version"] = version
    calls: list[dict] = []

    with pytest.raises(MeshTraceEvaluationError, match="schema v4"):
        evaluate_mesh_dor_trace(
            document,
            TRACE,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_fake_runner(calls),
        )

    assert calls == []


def test_missing_completion_metric_is_refused_with_runner_stderr(tmp_path):
    def runner(ctx, config, *, repo_root, timeout):
        return {"p50": 10.0, "stderr": "booksim exploded"}

    with pytest.raises(
            MeshTraceEvaluationError,
            match="neither completion_time nor latency") as excinfo:
        evaluate_mesh_dor_trace(
            _request_doc(),
            TRACE,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=runner,
        )

    assert "booksim exploded" in str(excinfo.value)
    assert not (tmp_path / "run" / EVIDENCE_FILENAME).exists()


@pytest.mark.parametrize(
    "filename", [TRACE_FILENAME, CONFIG_FILENAME, "config.cfg"])
def test_existing_attempt_artifact_is_refused(filename, tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / filename).write_text("previous attempt\n")
    calls: list[dict] = []

    with pytest.raises(MeshTraceEvaluationError, match="fresh"):
        evaluate_mesh_dor_trace(
            _request_doc(),
            TRACE,
            repo_root=tmp_path,
            run_dir=run_dir,
            runner=_fake_runner(calls),
        )

    assert calls == []
    assert not (run_dir / EVIDENCE_FILENAME).exists()


def test_document_is_json_native_and_deterministic(tmp_path):
    run_dir = tmp_path / "run"
    evaluation = evaluate_mesh_dor_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=run_dir,
        runner=_fake_runner(),
    )

    first = evaluation.to_dict()
    second = evaluation.to_dict()
    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second,
                                                          sort_keys=True)
    _assert_json_native(first)

    document = json.loads((run_dir / EVIDENCE_FILENAME).read_text())
    assert document == first
    assert json.dumps(document, sort_keys=True) == json.dumps(first,
                                                              sort_keys=True)
    assert json.loads(json.dumps(document, sort_keys=True)) == document
