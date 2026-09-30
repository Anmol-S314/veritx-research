"""R2 — independent ASTRA timing micro-oracles.

`F-ASTRA-0002` recorded a closed form for the frontend's 1000-cycle chunking:
``comm = 1010 * 2*(N-1) + 10`` (30310 at N=16). That law described a DEFECT.
An arrival was stamped with its true retirement cycle but scheduled at that
cycle, while the event loop only advances when ``ev.cycle > _now`` — so any
step overshooting a retirement DISCARDED the latency and substituted the
step size. A 16-node packet's whole latency is ~370 cycles, less than one
chunk, so the system makespan was topology-blind: mesh, a complete graph and
a 15-hop chain all reported 30310.

`F-ASTRA-0003` removed the chunking. These oracles now assert PHYSICAL
properties — topology sensitivity, bandwidth sensitivity, rank scaling,
additivity — not a closed form fitted to an artifact.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from test_astra_runtime import _design, FIXTURE
from test_canonical_compiler import _det

from veritx_dse.backend import astra
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, OperationNode, WorkloadGraph,
    collective_detail, compute_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2

ENDPOINT_DELAY = 10

_BINARY = astra.resolve_runtime_binary()
_HAVE_BINARY = _BINARY is not None and Path(_BINARY).is_file()

requires_binary = pytest.mark.skipif(
    not _HAVE_BINARY, reason="AstraSim_BookSim2 release binary not built")
requires_fixture = pytest.mark.skipif(
    not (FIXTURE / "mesh4x4.cfg").exists(), reason="astra_tiny fixture missing")

def _projection(ranks: int, ops):
    compiled = _det(_design(compute=ranks, tp=ranks))
    graph = WorkloadGraph(
        parallelism=compiled.inventory.parallelism, participant_count=ranks,
        operations=tuple(ops))
    return astra.AstraWorkloadProjection.build(
        logical=LogicalMessageArtifactV2(graph=graph),
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment, et_granularity="collectives")

def _compute(ranks: int, duration_ns: int, index: int = 0):
    return OperationNode(
        operation_id=f"c{index}", kind=KIND_COMPUTE,
        detail=compute_detail(duration_ns=duration_ns,
                              participant_count=ranks))

def _collective(ranks: int, payload: int, deps, index: int = 0):
    return OperationNode(
        operation_id=f"ar{index}", kind=KIND_COLLECTIVE, deps=deps,
        detail=collective_detail(
            collective_kind="ALLREDUCE",
            participants=tuple(range(ranks)), payload_bytes=payload,
            participant_count=ranks))

def _mesh_config(path: Path, k: int, n: int, classes: int) -> Path:
    path.write_text(
        "topology = mesh;\n"
        f"k = {k};\nn = {n};\n"
        "routing_function = dor;\nnum_vcs = 4;\nvc_buf_size = 8;\n"
        "traffic = uniform;\ninjection_rate = 0.1;\npacket_size = 5;\n"
        f"classes = {classes};\n"
        "sim_type = latency;\nsample_period = 1000;\nwarmup_periods = 3;\n"
        "print_activity = 1;\n")
    return path

_MESH = {2: (2, 1), 4: (2, 2), 8: (2, 3), 16: (4, 2)}

_WIDTHS = {"4x4": (4, 2), "16x1": (16, 1)}

def _run(projection, tmp_path, ranks: int, tag: str, shape=None):
    classes = astra.required_embedded_classes(
        projection.collective_operations)
    if shape is not None:
        k, n = shape
        network = _mesh_config(tmp_path / f"net-{k}x{n}.cfg", k, n, classes)
    elif ranks == 16:
        network = FIXTURE / "mesh4x4.cfg"
    else:
        k, n = _MESH[ranks]
        network = _mesh_config(
            tmp_path / f"mesh-{ranks}.cfg", k, n, classes)
    out = tmp_path / tag / "et"
    projection.write_chakra(directory=out, stem="canon")
    return astra.run_astra(
        binary=_BINARY, projection=projection,
        workload_configuration=out / "canon.et",
        system_configuration=FIXTURE / "system.json",
        network_configuration=network,
        memory_configuration=FIXTURE / "memory.json",
        logging_folder=tmp_path / tag / "logs", timeout_s=300)

def _comm(tmp_path, tag: str, ranks: int, ops, shape=None) -> int:
    """Comm cycles = measured aggregate minus the declared compute."""
    projection = _projection(ranks, ops)
    evidence = _run(projection, tmp_path, ranks, tag, shape=shape)
    return evidence.aggregate_cycles - projection.declared_compute_cycles()

@requires_binary
@requires_fixture
@pytest.mark.parametrize("duration_ns", [1000, 7000, 10000, 1234000])
def test_real_compute_only_is_exactly_the_declared_compute(tmp_path, duration_ns):
    """A0: no communication. ns_per_cycle == 1, so cycles == declared ns."""
    projection = _projection(16, [_compute(16, duration_ns)])
    evidence = _run(projection, tmp_path, 16, f"a0-{duration_ns}")
    assert evidence.aggregate_cycles == projection.declared_compute_cycles()
    assert evidence.aggregate_cycles == duration_ns
    assert all(cycles == duration_ns for _rank, cycles in evidence.per_rank_cycles)

@requires_binary
@requires_fixture
def test_real_comm_is_topology_sensitive(tmp_path):
    """THE regression guard for F-ASTRA-0003.

    Hundreds of tests passed while the system makespan was topology-blind,
    because none varied the topology. Same ranks, payload and workload; only
    hop distance differs. Equal values here means the stepper is discarding
    retirements again.
    """
    ops = [_compute(16, 10000), _collective(16, 65536, ("c0",))]
    mesh = _comm(tmp_path, "topo-mesh", 16, ops, shape=_WIDTHS["4x4"])
    line = _comm(tmp_path, "topo-line", 16, ops, shape=_WIDTHS["16x1"])
    assert mesh != line, (
        "comm is topology-blind again: a 4x4 mesh and a 16x1 line both cost "
        f"{mesh} cycles — the fabric stepper is discarding retirements")
    assert line > mesh, (
        f"a 16x1 line (diameter 15) must cost more than a 4x4 mesh "
        f"(diameter 6); got line={line} mesh={mesh}")

@requires_binary
@requires_fixture
def test_real_comm_is_bandwidth_limited_not_quantized(tmp_path):
    """F-ASTRA-0002 inverted: payload sensitivity below 64 KiB.

    The old law billed every ring step one 1000-cycle chunk, so 64 B and
    64 KiB cost the same. A fabric that simulates transmission cannot do
    that: a 1024x payload must cost measurably more.
    """
    comms = {}
    for payload in (64, 65536, 262144):
        comms[payload] = _comm(
            tmp_path, f"payload-{payload}", 16,
            [_compute(16, 10000), _collective(16, payload, ("c0",))])
    assert comms[64] < comms[65536] < comms[262144], comms

@requires_binary
@requires_fixture
@pytest.mark.parametrize("ranks", [2, 4, 8, 16])
def test_real_ring_collective_costs_something(tmp_path, ranks):
    """A collective is never free: the fabric must bill real transmission."""
    comm = _comm(tmp_path, f"ring-{ranks}", ranks,
                 [_compute(ranks, 10000), _collective(ranks, 64, ("c0",))])
    assert comm > ENDPOINT_DELAY, (
        f"a {ranks}-rank ring allreduce cost {comm} cycles, which is at or "
        "below the bare endpoint delay — the fabric did no work")

@requires_binary
@requires_fixture
def test_real_ring_comm_grows_monotonically_with_ranks(tmp_path):
    comms = [
        _comm(tmp_path, f"scale-{ranks}", ranks,
              [_compute(ranks, 10000), _collective(ranks, 64, ("c0",))])
        for ranks in (2, 4, 8, 16)
    ]
    assert comms == sorted(comms) and len(set(comms)) == len(comms), comms

@requires_binary
@requires_fixture
@pytest.mark.parametrize("rounds", [1, 2, 3])
def test_real_multi_round_collectives_are_additive(tmp_path, rounds):
    """A5: k sequential collectives cost k times one round."""
    ops = [_compute(16, 10000)]
    previous = "c0"
    for index in range(rounds):
        ops.append(_collective(16, 64, (previous,), index=index))
        previous = f"ar{index}"
    comm = _comm(tmp_path, f"rounds-{rounds}", 16, ops)
    one = _comm(tmp_path, "rounds-1-ref", 16,
                [_compute(16, 10000), _collective(16, 64, ("c0",))])
    assert comm == pytest.approx(rounds * one, rel=0.02)
