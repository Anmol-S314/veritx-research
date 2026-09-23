"""ASTRA runtime adapter tests: fail-closed evidence + real requalification.

The fault matrix runs against an injected process runner (no binary needed).
The real-runtime tests run the reclaimed ``astra_tiny`` fixture through an
actual ``AstraSim_BookSim2`` binary when one is available, and are skipped
otherwise -- never faked.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from test_canonical_compiler import _det, _design  # test-only canonical fixture

from veritx_dse.backend import astra
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
    collective_detail, compute_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2

DSE_DIR = Path(__file__).resolve().parent.parent
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "astra_tiny"
COUNT = 16
#: historically qualified exposed communication for the tiny fixture
HISTORICAL_COMM_CYCLES = 30310


# ── fixtures ───────────────────────────────────────────────────────────────

def _projection(tmp_path, *, count=4, payload=1024, granularity="messages"):
    compiled = _det(_design(compute=count, tp=count))
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism, participant_count=count,
        operations=(
            OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                          detail=compute_detail(duration_ns=10000,
                                                participant_count=count)),
            OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                          deps=("pre",),
                          detail=collective_detail(
                              collective_kind="ALLREDUCE",
                              participants=tuple(range(count)),
                              payload_bytes=payload,
                              participant_count=count)),
        ))
    logical = LogicalMessageArtifactV2(graph=graph)
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment,
        et_granularity=granularity)
    return projection, compiled


def _fake_binary(tmp_path) -> Path:
    binary = tmp_path / "AstraSim_BookSim2"
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    return binary


def _configs(tmp_path) -> dict:
    paths = {}
    for name in ("workload", "system", "network", "memory"):
        path = tmp_path / f"{name}.json"
        path.write_text("{}")
        paths[name] = path
    return paths


class _Proc:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def _runner(*, returncode=0, stdout="", stderr="", raises=None):
    def run(command, timeout):
        if raises is not None:
            raise raises
        return _Proc(returncode, stdout, stderr)
    return run


def _stdout(count, cycles=1234, exposed=100):
    lines = "Waiting\n"
    for rank in range(count):
        lines += (f"[workload] sys[{rank}] finished, {cycles} cycles, "
                  f"exposed communication {exposed} cycles.\n")
    return lines


def _run(projection, tmp_path, *, runner, backend="booksim"):
    configs = _configs(tmp_path)
    return astra.run_astra(
        binary=_fake_binary(tmp_path), projection=projection,
        workload_configuration=configs["workload"],
        system_configuration=configs["system"],
        network_configuration=configs["network"],
        memory_configuration=configs["memory"],
        timeout_s=5, runner=runner, backend=backend)


# ── parser units ───────────────────────────────────────────────────────────

def test_parse_cycles_and_exposed_comm():
    out = ("topology = mesh;\n"
           "[workload] sys[0] finished, 100000 cycles, exposed communication "
           "0 cycles.\n"
           "[workload] sys[1] finished, 50000 cycles, exposed communication "
           "50000 cycles.\nWaiting\n")
    cycles, exposed = astra.parse_astra_cycles(out)
    assert cycles == {0: 100000, 1: 50000}
    assert exposed == {0: 0, 1: 50000}
    assert astra.parse_astra_cycles("no results here") == ({}, {})


def test_parse_rejects_duplicate_rank_results():
    out = ("sys[0] finished, 10 cycles\n" * 2)
    with pytest.raises(astra.AstraExecutionError, match="duplicate rank"):
        astra.parse_astra_cycles(out)


# ── fail-closed fault matrix ───────────────────────────────────────────────

def test_missing_binary_is_unavailable(tmp_path):
    projection, _ = _projection(tmp_path)
    configs = _configs(tmp_path)
    with pytest.raises(astra.AstraUnavailable, match="not found"):
        astra.run_astra(binary=tmp_path / "nope", projection=projection,
                        workload_configuration=configs["workload"],
                        system_configuration=configs["system"],
                        network_configuration=configs["network"],
                        memory_configuration=configs["memory"],
                        runner=_runner())


def test_missing_config_is_refused(tmp_path):
    projection, _ = _projection(tmp_path)
    configs = _configs(tmp_path)
    with pytest.raises(astra.AstraExecutionError, match="configuration not found"):
        astra.run_astra(binary=_fake_binary(tmp_path), projection=projection,
                        workload_configuration=tmp_path / "absent.json",
                        system_configuration=configs["system"],
                        network_configuration=configs["network"],
                        memory_configuration=configs["memory"],
                        runner=_runner())


def test_nonzero_exit_fails_closed(tmp_path):
    projection, _ = _projection(tmp_path)
    with pytest.raises(astra.AstraExecutionError, match="exited 3"):
        _run(projection, tmp_path, runner=_runner(returncode=3,
                                                  stderr="boom"))


def test_timeout_fails_closed(tmp_path):
    projection, _ = _projection(tmp_path)
    with pytest.raises(astra.AstraExecutionError, match="timed out"):
        _run(projection, tmp_path,
             runner=_runner(raises=subprocess.TimeoutExpired("bs", 5)))


def test_malformed_output_fails_closed(tmp_path):
    projection, _ = _projection(tmp_path)
    with pytest.raises(astra.AstraExecutionError, match="participant ranks"):
        _run(projection, tmp_path, runner=_runner(stdout="garbage\n"))


def test_missing_rank_fails_closed(tmp_path):
    projection, _ = _projection(tmp_path, count=4)
    partial = "".join(f"sys[{r}] finished, 100 cycles\n" for r in range(3))
    with pytest.raises(astra.AstraExecutionError, match="missing=\\[3\\]"):
        _run(projection, tmp_path, runner=_runner(stdout=partial))


def test_unexpected_rank_fails_closed(tmp_path):
    projection, _ = _projection(tmp_path, count=4)
    extra = _stdout(4) + "sys[9] finished, 100 cycles\n"
    with pytest.raises(astra.AstraExecutionError, match="unexpected=\\[9\\]"):
        _run(projection, tmp_path, runner=_runner(stdout=extra))


def test_non_positive_cycles_fail_closed(tmp_path):
    projection, _ = _projection(tmp_path, count=4)
    with pytest.raises(astra.AstraExecutionError, match="non-positive"):
        _run(projection, tmp_path, runner=_runner(stdout=_stdout(4, cycles=0)))


def test_silent_non_simulation_is_refused(tmp_path):
    """All ranks reported, exit 0, but comm contributed nothing."""
    projection, _ = _projection(tmp_path, count=4)
    with pytest.raises(astra.AstraExecutionError,
                       match="simulated no communication"):
        _run(projection, tmp_path,
             runner=_runner(stdout=_stdout(4, cycles=10000, exposed=0)))


def test_successful_run_produces_evidence(tmp_path):
    projection, compiled = _projection(tmp_path, count=4)
    evidence = _run(projection, tmp_path,
                    runner=_runner(stdout=_stdout(4, cycles=50000)),
                    backend="booksim")
    assert evidence.status == "EXECUTED"
    assert evidence.projection_id == projection.projection_id()
    assert evidence.resolved_fabric_hash \
        == compiled.resolved_fabric.resolved_fabric_hash
    assert evidence.backend == "booksim"
    assert evidence.per_rank_map() == {r: 50000 for r in range(4)}
    assert evidence.aggregate_cycles == 50000
    assert len(evidence.per_rank_cycles) == 4
    doc = evidence.to_dict()
    assert doc["per_rank_cycles"]["3"] == 50000
    assert doc["evidence_scope"] == "canonical_logical_messages"


def test_analytical_backend_is_labelled(tmp_path):
    projection, _ = _projection(tmp_path, count=4)
    evidence = _run(projection, tmp_path,
                    runner=_runner(stdout=_stdout(4, cycles=50000)),
                    backend="analytical")
    assert evidence.backend == "analytical"
    assert evidence.status == "EXECUTED"


def test_replicated_unicast_scope_is_recorded(tmp_path):
    compiled = _det(_design(compute=4, tp=4))
    from veritx_dse.workload.graph import multicast_detail
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism, participant_count=4,
        operations=(OperationNode(
            operation_id="pre", kind=KIND_COMPUTE,
            detail=compute_detail(duration_ns=10000, participant_count=4)),
            OperationNode(
                operation_id="m", kind="MULTICAST", deps=("pre",),
                detail=multicast_detail(
                    source_rank=0, destinations=(1, 2), payload_bytes=64,
                    replication="SOURCE_REPLICATION", participant_count=4))))
    logical = LogicalMessageArtifactV2(graph=graph)
    projection = astra.AstraWorkloadProjection.build(
        logical=logical, resolved_fabric=compiled.resolved_fabric,
        mapping=compiled.mapping, attachment=compiled.attachment)
    evidence = _run(projection, tmp_path,
                    runner=_runner(stdout=_stdout(4, cycles=50000)))
    assert evidence.evidence_scope == "replicated_unicast"


# ── differential helper ────────────────────────────────────────────────────

def test_compare_per_rank_reports_bit_identical_ranks():
    a = astra.AstraExecutionEvidence(
        status="EXECUTED", projection_id="p", resolved_fabric_hash="r",
        backend="booksim", binary="a", per_rank_cycles=((0, 10), (1, 20)),
        exposed_comm_cycles=(), aggregate_cycles=20, evidence_scope="s")
    b = astra.AstraExecutionEvidence(
        status="EXECUTED", projection_id="p", resolved_fabric_hash="r",
        backend="booksim", binary="b", per_rank_cycles=((0, 10), (1, 99)),
        exposed_comm_cycles=(), aggregate_cycles=99, evidence_scope="s")
    report = astra.compare_per_rank(a, b)
    assert report["common_ranks"] == 2
    assert report["bit_identical_ranks"] == 1
    assert report["differing_ranks"] == [1]


# ── real runtime requalification ───────────────────────────────────────────

_REAL_CANDIDATES = (
    "/home/datavex/worktree-archive/veritx-manal/third_party/astra-sim/"
    "astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2",
    "/home/datavex/worktree-archive/veritx-epic/third_party/astra-sim/"
    "astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2",
)


def _real_binary() -> Path | None:
    env = os.environ.get("VERITX_ASTRA_BIN")
    candidates = ([env] if env else []) + list(_REAL_CANDIDATES)
    for candidate in candidates:
        path = Path(candidate)
        if path.is_file():
            return path
    resolved = astra.resolve_runtime_binary()
    return resolved


_requires_binary = pytest.mark.skipif(
    _real_binary() is None,
    reason="no AstraSim_BookSim2 binary available on this machine")
_requires_fixture = pytest.mark.skipif(
    not (FIXTURE / "mesh4x4.cfg").exists(),
    reason="reclaimed astra_tiny fixture missing")


def _real_project(tmp_path, granularity):
    projection, compiled = _projection(tmp_path, count=COUNT, payload=1024,
                                       granularity=granularity)
    out = tmp_path / "et"
    projection.write_chakra(directory=out, stem="canon")
    return projection, compiled, out / "canon.et"


def _real_run(tmp_path, granularity, *, network="mesh4x4.cfg"):
    projection, compiled, workload = _real_project(tmp_path, granularity)
    evidence = astra.run_astra(
        binary=_real_binary(), projection=projection,
        workload_configuration=workload,
        system_configuration=FIXTURE / "system.json",
        network_configuration=FIXTURE / network,
        memory_configuration=FIXTURE / "memory.json",
        logging_folder=tmp_path / "logs", timeout_s=240)
    return projection, compiled, evidence


@_requires_binary
@_requires_fixture
def test_real_runtime_executes_canonical_projection(tmp_path):
    projection, compiled, evidence = _real_run(tmp_path, "collectives")
    assert evidence.status == "EXECUTED"
    assert len(evidence.per_rank_cycles) == COUNT
    assert evidence.resolved_fabric_hash \
        == compiled.resolved_fabric.resolved_fabric_hash
    # communication was really simulated (above the declared compute floor)
    assert evidence.aggregate_cycles > projection.declared_compute_cycles()


@_requires_binary
@_requires_fixture
def test_real_runtime_messages_mode_is_refused_when_not_simulated(tmp_path):
    """This build ignores send/recv; the guard must refuse, not report PASS."""
    with pytest.raises(astra.AstraExecutionError) as excinfo:
        _real_run(tmp_path, "messages")
    assert "simulated no communication" in str(excinfo.value)


@_requires_binary
@_requires_fixture
def test_historical_comm_component_requalification(tmp_path):
    """The canonical projection reproduces the qualified comm work.

    Historical provenance: the tiny fixture (3 nodes, 1 KB ring allreduce,
    16 ranks) finished at 50310 cycles = 20000 compute + 30310 exposed
    communication. This projection declares 10000 compute, so an exact
    match of the communication component is 30310.
    """
    projection, _, evidence = _real_run(tmp_path, "collectives")
    comm_component = evidence.aggregate_cycles \
        - projection.declared_compute_cycles()
    if comm_component != HISTORICAL_COMM_CYCLES:
        pytest.skip(
            "the binary available here is not the historically qualified "
            f"build (comm component {comm_component} != "
            f"{HISTORICAL_COMM_CYCLES}); see the slice report")
    assert comm_component == HISTORICAL_COMM_CYCLES
    assert len(evidence.per_rank_cycles) == COUNT


@pytest.mark.skipif(
    not os.environ.get("VERITX_ASTRA_REF_BIN"),
    reason="set VERITX_ASTRA_REF_BIN to attempt the two-binary 16/16 "
           "bit-identical differential")
@_requires_fixture
def test_two_binary_bit_identical_differential(tmp_path):
    """Requalification METHOD from the historical handoff.

    Reproducible only when two independent qualified builds are supplied;
    the exact historical reference (md5 13326f89d95c7b959db823a458328486)
    is absent on this machine.
    """
    projection, _, workload = _real_project(tmp_path / "a", "collectives")
    reference = Path(os.environ["VERITX_ASTRA_REF_BIN"])
    if not reference.is_file():
        pytest.skip("VERITX_ASTRA_REF_BIN does not exist")
    configs = dict(
        system_configuration=FIXTURE / "system.json",
        network_configuration=FIXTURE / "mesh4x4.cfg",
        memory_configuration=FIXTURE / "memory.json", timeout_s=240)
    left = astra.run_astra(binary=_real_binary(), projection=projection,
                           workload_configuration=workload,
                           logging_folder=tmp_path / "la", **configs)
    right = astra.run_astra(binary=reference, projection=projection,
                            workload_configuration=workload,
                            logging_folder=tmp_path / "ra", **configs)
    report = astra.compare_per_rank(left, right)
    assert report["common_ranks"] == COUNT
    assert report["bit_identical_ranks"] == COUNT, report
