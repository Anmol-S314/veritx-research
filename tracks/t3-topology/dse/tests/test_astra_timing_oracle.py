"""R2 — independent ASTRA timing micro-oracles.

F-ASTRA-0001 fixed a 1,000,000-cycle quantization in the embedded BookSim
frontend. That is a bug fix, not a numerical qualification. This module
qualifies ASTRA *timing* against closed-form laws derived from the declared
configuration and the frontend's source, on the real release binary.

Model under test (call it M: quantized-stepping ring accounting)
----------------------------------------------------------------
The embedded frontend advances the shared fabric in fixed ``CHUNK`` steps
(``Booksim2Fabric.hh``: ``constexpr int64_t CHUNK = 1000``) and returns as
soon as a packet retires, so a ring step whose packet needs fewer than 1000
fabric cycles is still billed a full 1000-cycle chunk. Each collective event
also pays the declared ``endpoint-delay`` (10 in the ASTRA scheduler profile)
and one trailing endpoint delay closes the collective. Therefore, for a ring
ALLREDUCE over N ranks and a payload small enough that one step fits in a
chunk:

    steps(N)          = 2 * (N - 1)          # closed-form ring law
    comm_cycles(N)    = (CHUNK + ENDPOINT) * steps(N) + ENDPOINT
                      = 1010 * 2 * (N - 1) + 10

Multi-round is additive: k sequential collectives cost k * comm_cycles(N).

This is an INTERNAL qualification under model M. It does not claim ASTRA
predicts real hardware latency. The companion finding (``F-ASTRA-0002``) is
that comm cycles are payload-insensitive below ~64 KiB — the model has a
1000-cycle granularity floor — so absolute bandwidth/latency for realistic
small payloads is NOT established and must not enter a comparison.
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

#: the frontend's fixed fabric-step quantum (Booksim2Fabric.hh)
CHUNK = 1000
#: the declared per-collective-event endpoint delay (ASTRA scheduler profile)
ENDPOINT_DELAY = 10
#: payloads up to this many bytes never exceed one 1000-cycle step per rank
QUANTIZED_PAYLOAD_CEILING = 65536


def ring_comm_cycles(ranks: int) -> int:
    """Closed-form comm cycles for a ring ALLREDUCE under model M."""
    if ranks < 2:
        raise ValueError("a ring collective needs at least two ranks")
    steps = 2 * (ranks - 1)
    return (CHUNK + ENDPOINT_DELAY) * steps + ENDPOINT_DELAY


# ── the law itself (no binary) ─────────────────────────────────────────────

def test_ring_law_hand_table():
    assert [ring_comm_cycles(n) for n in (2, 4, 8, 16)] == \
        [2030, 6070, 14150, 30310]
    # the historic qualified comm component for the 16-rank tiny fixture
    assert ring_comm_cycles(16) == 30310


# ── real-binary oracles ────────────────────────────────────────────────────

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


def _mesh_config(path: Path, k: int, n: int) -> Path:
    path.write_text(
        "topology = mesh;\n"
        f"k = {k};\nn = {n};\n"
        "routing_function = dor;\nnum_vcs = 4;\nvc_buf_size = 8;\n"
        "traffic = uniform;\ninjection_rate = 0.1;\npacket_size = 5;\n"
        "sim_type = latency;\nsample_period = 1000;\nwarmup_periods = 3;\n"
        "print_activity = 1;\n")
    return path


#: power-of-two rank counts and a mesh shape (k**n == ranks) for each
_MESH = {2: (2, 1), 4: (2, 2), 8: (2, 3), 16: (4, 2)}


def _run(projection, tmp_path, ranks: int, tag: str):
    if ranks == 16:
        network = FIXTURE / "mesh4x4.cfg"
    else:
        k, n = _MESH[ranks]
        network = _mesh_config(tmp_path / f"mesh-{ranks}.cfg", k, n)
    out = tmp_path / tag / "et"
    projection.write_chakra(directory=out, stem="canon")
    return astra.run_astra(
        binary=_BINARY, projection=projection,
        workload_configuration=out / "canon.et",
        system_configuration=FIXTURE / "system.json",
        network_configuration=network,
        memory_configuration=FIXTURE / "memory.json",
        logging_folder=tmp_path / tag / "logs", timeout_s=300)


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
@pytest.mark.parametrize("ranks", [2, 4, 8, 16])
def test_real_ring_collective_matches_the_closed_form(tmp_path, ranks):
    """A2/A3: one ring ALLREDUCE fits model M exactly."""
    projection = _projection(ranks, [
        _compute(ranks, 10000),
        _collective(ranks, 64, ("c0",)),
    ])
    evidence = _run(projection, tmp_path, ranks, f"ring-{ranks}")
    comm = evidence.aggregate_cycles - projection.declared_compute_cycles()
    assert comm == ring_comm_cycles(ranks)
    assert evidence.aggregate_cycles == 10000 + ring_comm_cycles(ranks)


@requires_binary
@requires_fixture
@pytest.mark.parametrize("rounds", [1, 2, 3])
def test_real_multi_round_collectives_are_additive(tmp_path, rounds):
    """A5: k sequential collectives cost k times the single-round law."""
    ops = [_compute(16, 10000)]
    previous = "c0"
    for index in range(rounds):
        ops.append(_collective(16, 64, (previous,), index=index))
        previous = f"ar{index}"
    projection = _projection(16, ops)
    evidence = _run(projection, tmp_path, 16, f"rounds-{rounds}")
    comm = evidence.aggregate_cycles - projection.declared_compute_cycles()
    assert comm == rounds * ring_comm_cycles(16)


@requires_binary
@requires_fixture
def test_real_small_payload_comm_is_quantized_not_bandwidth_limited(tmp_path):
    """Finding F-ASTRA-0002: comm cycles are payload-insensitive below 64 KiB.

    Two payloads 1024x apart cost the same because each ring step is billed a
    full 1000-cycle fabric chunk. This makes ASTRA absolute comm timing
    unusable as a physical bandwidth model for realistic small payloads; it is
    recorded here as a reproducible regression guard, not hidden.
    """
    comms = {}
    for payload in (64, 65536, 262144):
        projection = _projection(16, [
            _compute(16, 10000), _collective(16, payload, ("c0",))])
        evidence = _run(projection, tmp_path, 16, f"payload-{payload}")
        comms[payload] = evidence.aggregate_cycles \
            - projection.declared_compute_cycles()
    assert comms[64] == comms[65536] == ring_comm_cycles(16) == 30310
    # only once a step exceeds the chunk does the payload begin to matter
    assert comms[262144] > comms[65536]
