"""Raw-trace evaluation seam: compile, run, and persist one trace.

Every test injects a fake runner, so no real BookSim binary is required.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path

import pytest

from veritx_dse.backend.booksim import PreparedBackend
from veritx_dse.backend.trace_evaluation import (
    EVIDENCE_FIELDS,
    TraceEvaluation,
    TraceEvaluationError,
    evaluate_trace,
)
from veritx_dse.model import topology_ir
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
from veritx_dse.model.topology_intent import ExplicitTopologyIntent

#: 4 endpoints, one class, five whitespace columns per data line.
TRACE = b"""# raw single-class trace
0 0 0 1 1
0 1 0 0 1
1 2 0 3 1
1 3 0 2 1
"""


def _mesh2_graph():
    """The 2x2 nearest-neighbour mesh as an explicit graph.

    A typed ``MeshIntent(side_length=2)`` compiles to DOR_XY, while the
    certified raw standalone BookSim profile realizes only ANYNET_MIN_HOPS.
    The same physical 2x2 mesh declared explicitly therefore gives this seam
    a realizable route class without changing the shape under test.
    """
    return topology_ir.from_dict({
        "name": "mesh2",
        "kind": "custom",
        "nodes": 4,
        "links": [[0, 1], [0, 2], [1, 3], [2, 3]],
        "link_attrs": {"bandwidth_GBs": 50.0, "latency_ns": 500.0},
    })


def _request() -> CompileRequestV4:
    """Minimal compiling v4 request: 4 agents on a 2x2 mesh."""
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
        topology=ExplicitTopologyIntent(graph=_mesh2_graph()),
        noc_controls=NocControls(link_width=64),
        physical=PhysicalContext(default_clock_freq_mhz=1000.0),
    )


def _request_doc() -> dict:
    return _request().to_dict()


def _evidence() -> dict:
    return {
        "backend_config_hash": "a" * 64,
        "backend_input_hash": "b" * 64,
        "resolved_fabric_hash": "c" * 64,
        "fabric_hash": "d" * 64,
        "qualification": "QUALIFIED",
        "exact_fabric_eligible": True,
        "stats": {"completion_time": 42, "latency": 3.5},
        "exit_status": 0,
        "workload_hash": hashlib.sha256(TRACE).hexdigest(),
        "seed": 7,
        "seed_policy": "explicit",
        "route_equivalence": "MATCH",
        "route_pairs_compared": 6,
    }


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


def test_evaluate_trace_compiles_runs_and_persists_json(tmp_path):
    run_dir = tmp_path / "run"
    booksim_bin = Path("/opt/fake/booksim")
    expected_evidence = _evidence()
    calls: list[dict] = []

    def runner(prepared, *, run_dir, repo_root, timeout, binary):
        calls.append({
            "prepared": prepared,
            "run_dir": run_dir,
            "repo_root": repo_root,
            "timeout": timeout,
            "binary": binary,
        })
        return expected_evidence

    evaluation = evaluate_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=run_dir,
        booksim_bin=booksim_bin,
        seed=7,
        timeout=33,
        runner=runner,
    )

    assert isinstance(evaluation, TraceEvaluation)
    assert evaluation.request_design_hash == _request().design_hash()
    assert evaluation.trace_sha256 == hashlib.sha256(TRACE).hexdigest()
    assert evaluation.trace_summary == {
        "dialect": "whitespace",
        "num_packets": 4,
        "max_timestamp": 1,
        "endpoint_count": 4,
    }
    assert evaluation.evidence == expected_evidence
    assert evaluation.output_dir == str(run_dir)

    assert len(calls) == 1
    prepared = calls[0]["prepared"]
    assert isinstance(prepared, PreparedBackend)
    assert prepared.manifest.seed == 7
    assert prepared.rendered.trace_summary.num_packets == 4
    assert evaluation.fabric_hash == prepared.bundle.fabric.fabric_hash
    assert calls[0]["run_dir"] == run_dir
    assert calls[0]["repo_root"] == tmp_path
    assert calls[0]["timeout"] == 33
    assert calls[0]["binary"] == booksim_bin

    document = json.loads((run_dir / "trace-evaluation.json").read_text())
    assert document == evaluation.to_dict()
    assert document["trace_sha256"] == hashlib.sha256(TRACE).hexdigest()
    assert document["trace_summary"] == evaluation.trace_summary
    assert document["evidence"] == expected_evidence
    _assert_json_native(document)
    _assert_json_native(evaluation.to_dict())


def test_dataclass_runner_result_keeps_present_fields_and_nulls_absent_ones(tmp_path):
    @dataclass(frozen=True)
    class PartialEvidence:
        backend_config_hash: str
        stats: dict
        exit_status: int

    def runner(prepared, *, run_dir, repo_root, timeout, binary):
        return PartialEvidence(
            backend_config_hash="e" * 64,
            stats={"completion_time": 9},
            exit_status=0,
        )

    evaluation = evaluate_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=tmp_path / "run",
        runner=runner,
    )

    assert set(evaluation.evidence) == set(EVIDENCE_FIELDS)
    assert evaluation.evidence["backend_config_hash"] == "e" * 64
    assert evaluation.evidence["stats"] == {"completion_time": 9}
    assert evaluation.evidence["exit_status"] == 0
    assert evaluation.evidence["qualification"] is None
    assert evaluation.evidence["route_pairs_compared"] is None


def test_dict_runner_result_missing_optional_fields_does_not_fail(tmp_path):
    def runner(prepared, *, run_dir, repo_root, timeout, binary):
        return {"stats": {"latency": 1.25}, "exit_status": 0}

    evaluation = evaluate_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=tmp_path / "run",
        runner=runner,
    )

    assert evaluation.evidence["stats"] == {"latency": 1.25}
    assert evaluation.evidence["exit_status"] == 0
    assert evaluation.evidence["seed"] is None
    assert evaluation.evidence["qualification"] is None


def test_path_values_in_evidence_are_serialized_as_strings(tmp_path):
    artifact = Path("/tmp/evidence/artifact.json")

    def runner(prepared, *, run_dir, repo_root, timeout, binary):
        return {"stats": {"artifact": artifact}, "exit_status": 0}

    evaluation = evaluate_trace(
        _request_doc(),
        TRACE,
        repo_root=tmp_path,
        run_dir=tmp_path / "run",
        runner=runner,
    )

    assert evaluation.evidence["stats"] == {"artifact": str(artifact)}
    document = json.loads(
        (tmp_path / "run" / "trace-evaluation.json").read_text())
    assert document["evidence"]["stats"]["artifact"] == str(artifact)
    _assert_json_native(evaluation.to_dict())


def test_trace_class_must_be_zero(tmp_path):
    with pytest.raises(TraceEvaluationError, match="single-class"):
        evaluate_trace(
            _request_doc(),
            b"0 0 1 1 1\n",
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_must_not_run,
        )


def test_trace_endpoint_out_of_range_is_refused_before_runner(tmp_path):
    calls: list[bool] = []

    def runner(*args, **kwargs):
        calls.append(True)
        raise AssertionError("runner must not be called")

    with pytest.raises(TraceEvaluationError, match="outside"):
        evaluate_trace(
            _request_doc(),
            b"0 0 0 4 1\n",
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=runner,
        )

    assert calls == []


@pytest.mark.parametrize("version", [3, 5])
def test_non_v4_request_is_refused_without_migration(version, tmp_path):
    document = _request_doc()
    document["schema_version"] = version

    with pytest.raises(TraceEvaluationError, match="schema v4"):
        evaluate_trace(
            document,
            TRACE,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_must_not_run,
        )


def test_non_compiling_request_names_status_and_error(tmp_path):
    request = replace(
        _request(),
        agents=(
            Agent(
                kind=AgentKind.COMPUTE_TILE,
                count=8,
                protocol="AXI",
                data_width=256,
                addr_width=64,
            ),
        ),
    )

    with pytest.raises(TraceEvaluationError) as excinfo:
        evaluate_trace(
            request.to_dict(),
            TRACE,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_must_not_run,
        )

    message = str(excinfo.value)
    assert "UNSUPPORTED" in message
    assert "seats" in message


@pytest.mark.parametrize("trace", [b"0 0 0 1\n", b"0 0 0 1 1 9\n"])
def test_trace_must_have_exactly_five_whitespace_columns(trace, tmp_path):
    with pytest.raises(TraceEvaluationError, match="5 whitespace columns"):
        evaluate_trace(
            _request_doc(),
            trace,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_must_not_run,
        )


@pytest.mark.parametrize("trace", [b"", b"# only comments\n% still comments\n"])
def test_empty_trace_is_refused(trace, tmp_path):
    with pytest.raises(TraceEvaluationError, match="empty"):
        evaluate_trace(
            _request_doc(),
            trace,
            repo_root=tmp_path,
            run_dir=tmp_path / "run",
            runner=_must_not_run,
        )
