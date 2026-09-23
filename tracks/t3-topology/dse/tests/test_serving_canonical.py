"""Slice 35 — canonical serving integration tests."""
from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from test_backend_astra_machine import BOOKSIM_SOURCE, _machine
from test_backend_astra_namespace import _namespace as _astra_namespace
from test_backend_booksim_projection import _parents

from veritx_dse.backend import canonical_serving as cs
from veritx_dse.backend import astra_namespace as ans
from veritx_dse.backend.astra_machine import NETWORK_FILE
from veritx_dse.backend.booksim_projection import prepare_booksim_input
from veritx_dse.simulation import serving_runtime as sr
from veritx_dse.workload.traffic import ParticipantEndpointMapping

REPO = Path(__file__).resolve().parents[4]
BUILT_FROM_SOURCE = (REPO / "third_party" / "astra-sim" / "astra-sim"
                     / "network_frontend" / "booksim2" / "bin"
                     / "AstraSim_BookSim2")


# ── fixtures ──────────────────────────────────────────────────────────────

def _qualified(*, instance_count=4, granularity="collectives"):
    """machine + permuted namespace + a serving instance partition."""
    compiled, projection, machine, binding, ns = _astra_namespace(
        granularity=granularity)
    ranks = [r for r, _ in ns.rank_to_endpoint]
    groups = [[] for _ in range(instance_count)]
    for index, rank in enumerate(ranks):
        groups[index % instance_count].append(rank)
    instances = tuple(cs.ServingInstance(instance_id=i, ranks=tuple(g))
                      for i, g in enumerate(groups))
    serving = cs.ServingNamespaceBinding(
        namespace=ns, instances=instances, serving_config_id="cfg/serving-test")
    return machine, ns, serving


def _backend(machine, serving, *, mode=cs.MODE_LIVE_CANONICAL, binary=None):
    return cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving,
        astra_binary=str(binary or BUILT_FROM_SOURCE),
        astra_binary_sha256="a" * 64, astra_binary_size=123,
        astra_source_revision="deadbeef", execution_mode=mode)


class FakeSession:
    """Scripted protocol session (context-managed) for round-level tests."""

    def __init__(self, argv, *, cwd=None, endpoints=(), comm=None,
                 injected=0, cycles=4242, startup="[workload] sys[0] finished, 1 cycles\nWaiting\n"):
        self.argv = argv
        self.cwd = cwd
        self._endpoints = endpoints
        self._comm = dict(comm or {})
        self._injected = injected
        self._cycles = cycles
        self._startup = startup
        self.entered = False
        self.exited = False
        self.commands: list[str] = []

    # context manager
    def __enter__(self):
        self.entered = True
        return self

    def __exit__(self, *exc):
        self.exited = True
        return False

    def read_startup(self):
        return sr.BackendReply([self._startup], "Waiting")

    def command(self, line, *, expect_reply=True, timeout=None):
        self.commands.append(line)
        if not expect_reply:
            return None
        lines = [f"[workload] sys[{e}] finished, {self._cycles} cycles, "
                 f"exposed communication {self._cycles} cycles."
                 for e in self._endpoints]
        lines.append("Waiting")
        return sr.BackendReply(lines, "Waiting")

    def stderr_text(self):
        rows = [f"[statistics] sys[{e}], Wall time: {self._cycles}\n"
                f"[statistics] sys[{e}], Comm time: {c}\n"
                for e, c in sorted(self._comm.items())]
        if self._injected is not None:
            rows.append(f"[trace] All 0 cycles, injected={self._injected} "
                        "— draining\n")
        return "".join(rows)


def _session_factory(**kwargs):
    def factory(argv, cwd=None):
        return FakeSession(argv, cwd=cwd, **kwargs)
    return factory


def _workload(granularity="collectives"):
    _, projection, _, _, _ = _astra_namespace(granularity=granularity)
    return projection


def _round(tmp_path, *, backend, granularity="collectives", dispatched,
           instance_count=4, **session_kwargs):
    machine, ns, serving = _qualified(instance_count=instance_count,
                                      granularity=granularity)
    backend = backend(machine, serving) if callable(backend) else backend
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(granularity),
        run_dir=tmp_path / "run", dispatched_instances=frozenset(dispatched),
        session_factory=_session_factory(**session_kwargs))
    return backend, outcome


# ── instance / rank / endpoint are distinct namespaces ────────────────────

def test_instance_rank_endpoint_are_not_assumed_equal():
    machine, ns, serving = _qualified(instance_count=4)
    assert len(serving.instances) == 4
    # a rank maps to a permuted endpoint, and instances own several ranks
    assert any(r != e for r, e in serving.rank_to_endpoint())
    assert all(len(i.ranks) == 4 for i in serving.instances)
    for instance in serving.instances:
        endpoints = serving.endpoints_of(instance.instance_id)
        assert set(endpoints) != set(instance.ranks)
        for rank, endpoint in zip(sorted(instance.ranks), endpoints):
            assert serving.instance_of_endpoint(endpoint) == instance.instance_id
            assert serving.instance_of_rank(rank) == instance.instance_id


def test_every_participant_rank_must_be_owned_by_an_instance():
    machine, ns, serving = _qualified(instance_count=4)
    with pytest.raises(cs.ServingBoundaryError, match="not owned by any"):
        cs.ServingNamespaceBinding(
            namespace=ns,
            instances=(cs.ServingInstance(0, tuple(range(10))),),
            serving_config_id="cfg/x")


def test_a_rank_cannot_be_owned_twice():
    machine, ns, serving = _qualified(instance_count=4)
    with pytest.raises(cs.ServingBoundaryError, match="more than one"):
        cs.ServingNamespaceBinding(
            namespace=ns,
            instances=(cs.ServingInstance(0, (0, 1)),
                       cs.ServingInstance(1, (1, 2))),
            serving_config_id="cfg/x")


def test_instance_ids_must_be_dense():
    machine, ns, serving = _qualified(instance_count=4)
    with pytest.raises(cs.ServingBoundaryError, match="0..N-1"):
        cs.ServingNamespaceBinding(
            namespace=ns,
            instances=(cs.ServingInstance(0, tuple(range(16))),
                       cs.ServingInstance(2, (0,))),
            serving_config_id="cfg/x")


# ── completion attribution (never sys-0 bias) ─────────────────────────────

def test_completions_are_attributed_by_endpoint_not_by_sys_zero():
    machine, ns, serving = _qualified(instance_count=4)
    endpoints = ns.participant_endpoints()
    # every participant endpoint reports a completion, including high ids
    per_endpoint = {e: 1 for e in endpoints}
    rows, unowned = cs.attribute_completions(
        per_endpoint=per_endpoint, binding=serving,
        dispatched=frozenset(range(4)))
    assert unowned == ()
    assert cs.instances_with_completions(rows) == (0, 1, 2, 3)
    # attribution follows the mapping, not numeric coincidence
    for row in rows:
        assert row.endpoint == ns.endpoint_for(row.rank)
        assert row.instance == serving.instance_of_rank(row.rank)


def test_pass_echo_cannot_retire_an_unsent_batch():
    machine, ns, serving = _qualified(instance_count=4)
    endpoint_of_instance_3 = serving.endpoints_of(3)[0]
    with pytest.raises(cs.ServingBoundaryError, match="dispatched no batch"):
        cs.attribute_completions(
            per_endpoint={endpoint_of_instance_3: 1}, binding=serving,
            dispatched=frozenset({0, 1, 2}))


def test_non_participant_endpoint_completion_refuses():
    machine, ns, serving = _qualified(instance_count=4)
    idle = ns.idle_endpoints()[0]
    with pytest.raises(cs.ServingBoundaryError, match="non-participant"):
        cs.attribute_completions(
            per_endpoint={idle: 1}, binding=serving,
            dispatched=frozenset(range(4)))


def test_all_completions_in_a_burst_are_processed():
    machine, ns, serving = _qualified(instance_count=4)
    per_endpoint = {e: 2 for e in ns.participant_endpoints()}
    rows, _ = cs.attribute_completions(
        per_endpoint=per_endpoint, binding=serving,
        dispatched=frozenset(range(4)))
    assert len(rows) == len(ns.participant_endpoints()) == 16
    assert cs.instances_with_completions(rows) == (0, 1, 2, 3)


# ── liveness: every expected instance must serve work ────────────────────

@pytest.mark.parametrize("instance_count", [2, 4])
def test_every_instance_serves_work_regression(tmp_path, instance_count):
    """The historical 2-instance DP/EP and 4-instance TP2 hang classes."""
    machine, ns, serving = _qualified(instance_count=instance_count)
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(instance_count)),
        session_factory=_session_factory(
            comm={e: 7 for e in ns.participant_endpoints()},
            endpoints=ns.participant_endpoints()))
    evidence = sr.build_serving_evidence(
        backend=backend, rounds=(outcome,), workload_id="wl/regression")
    assert evidence.instance_count == instance_count
    assert evidence.instances_with_completions == tuple(range(instance_count))
    assert evidence.every_instance_served()
    evidence.assert_all_instances_served()


def test_instance_starvation_is_detected(tmp_path):
    """A total count is not enough: one starved instance must fail the gate."""
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    # only instance 0's endpoints report work (the historical sys-0 bias)
    starved = {e: 5 for e in serving.endpoints_of(0)}
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(4)),
        session_factory=_session_factory(comm=starved,
                                         endpoints=tuple(starved)))
    evidence = sr.build_serving_evidence(
        backend=backend, rounds=(outcome,), workload_id="wl/starved")
    assert evidence.instances_with_completions == (0,)
    assert not evidence.every_instance_served()
    with pytest.raises(cs.ServingBoundaryError, match="not every serving"):
        evidence.assert_all_instances_served()


def test_dp_quorum_pass_is_not_a_completion(tmp_path):
    """A DP member that has not been dispatched must not be retired by a pass."""
    machine, ns, serving = _qualified(instance_count=2)
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    # instance 1 is DP-pending; its endpoints still report Comm time (a pass
    # echo would look like this) but no batch was dispatched for it
    comm = {e: 3 for e in serving.endpoints_of(1)}
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset({0, 1}),
        session_factory=_session_factory(comm=comm, endpoints=tuple(comm)))
    # dispatched includes both, so this is a legitimate completion
    assert cs.instances_with_completions(outcome.attributions) == (1,)
    # ...but if only instance 0 was dispatched the same burst must refuse
    with pytest.raises(cs.ServingBoundaryError, match="dispatched no batch"):
        cs.attribute_completions(per_endpoint=comm, binding=serving,
                                 dispatched=frozenset({0}))


# ── autonomous injection ─────────────────────────────────────────────────

def test_autonomous_fabric_injection_refuses(tmp_path):
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    with pytest.raises(cs.ServingBoundaryError, match="injected"):
        sr.run_live_round(
            backend=backend, workload=_workload(), run_dir=tmp_path / "run",
            dispatched_instances=frozenset(range(4)),
            session_factory=_session_factory(
                comm={e: 1 for e in ns.participant_endpoints()},
                endpoints=ns.participant_endpoints(), injected=42))


# ── boundary refusals ────────────────────────────────────────────────────

def test_canonical_message_mode_is_refused_not_downgraded():
    machine, ns, serving = _qualified(instance_count=4, granularity="messages")
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    assert machine.expansion_authority == "srota_logical_messages"
    with pytest.raises(cs.CanonicalMessageModeUnsupported) as excinfo:
        backend.assert_network_authority()
    assert excinfo.value.status == cs.MESSAGE_MODE_STATUS
    # and the tier is unavailable rather than silently substituted
    with pytest.raises(cs.CanonicalMessageModeUnsupported):
        backend.evidence_tier()


def test_namespace_machine_transplant_refuses():
    machine, ns, serving = _qualified(instance_count=4)
    other_machine = _machine(anynet=True)[4]
    assert other_machine.machine_id() != machine.machine_id()
    with pytest.raises(cs.ServingBoundaryError, match="different machine"):
        cs.CanonicalServingNetworkBackend(
            machine=other_machine, binding=serving,
            astra_binary=str(BUILT_FROM_SOURCE), astra_binary_sha256="a" * 64,
            astra_binary_size=1, astra_source_revision=None,
            execution_mode=cs.MODE_REPLAY_ONLY)


def test_machine_identity_transplant_is_refused_by_the_reuse_gate():
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    assert backend.covers(machine_id=machine.machine_id(),
                          namespace_id=ns.namespace_id(),
                          participant_mapping_id=ns.participant_mapping_id)
    assert not backend.covers(machine_id="f" * 64,
                              namespace_id=ns.namespace_id(),
                              participant_mapping_id=ns.participant_mapping_id)
    assert not backend.covers(machine_id=machine.machine_id(),
                              namespace_id="e" * 64,
                              participant_mapping_id=ns.participant_mapping_id)
    assert not backend.covers(machine_id=machine.machine_id(),
                              namespace_id=ns.namespace_id(),
                              participant_mapping_id="d" * 64)


def test_backend_requires_a_qualified_machine_projection():
    _, ns, serving = _qualified(instance_count=4)
    with pytest.raises(cs.ServingBoundaryError, match="AstraMachineProjection"):
        cs.CanonicalServingNetworkBackend(
            machine={"not": "a projection"}, binding=serving,
            astra_binary="/bin/true", astra_binary_sha256="a" * 64,
            astra_binary_size=1, astra_source_revision=None,
            execution_mode=cs.MODE_REPLAY_ONLY)


def test_live_mode_requires_an_existing_binary():
    machine, ns, serving = _qualified(instance_count=4)
    with pytest.raises(cs.ServingBoundaryError, match="not found"):
        cs.CanonicalServingNetworkBackend(
            machine=machine, binding=serving,
            astra_binary="/nonexistent/AstraSim_BookSim2",
            astra_binary_sha256="a" * 64, astra_binary_size=1,
            astra_source_revision=None)


# ── the adapter never authors machine semantics ──────────────────────────

def test_adapter_command_is_the_canonical_machine_command(tmp_path):
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                       binary=Path("/bin/true"))
    command = backend.qualified_argv(workload_path="/tmp/w.et", cwd=tmp_path)
    joined = " ".join(command)
    assert f"--network-configuration={NETWORK_FILE}" in joined
    assert f"--comm-group-configuration={ans.COMM_GROUP_FILE}" in joined
    assert f"--booksim2-flit-bytes={machine.flit_bytes}" in joined
    # it must not smuggle a topology of its own, and the only injection
    # control is the canonical DISARMING override (never a serving-chosen rate)
    for forbidden in ("topology =", "k =", "routing_function ="):
        assert forbidden not in joined
    assert "injection_rate=0.0" in joined
    assert "injection_rate=0." not in joined.replace("injection_rate=0.0", "")


def test_module_authors_no_topology_or_config():
    """Static guard: no BookSim/topology authoring in the serving adapter."""
    source = (REPO / "tracks" / "t3-topology" / "dse" / "veritx_dse"
              / "backend" / "canonical_serving.py").read_text()
    for forbidden in ("_prepare_booksim_config", "math.sqrt",
                      "topology = mesh", "routing_function =",
                      "astrasim_adapter"):
        assert forbidden not in source, \
            f"serving adapter must not author {forbidden!r}"


def test_historical_serving_config_authoring_is_not_used():
    """The vendored __main__ still has it; the canonical path must not call it."""
    main_py = (REPO / "third_party" / "llmservingsim" / "serving"
               / "__main__.py")
    if main_py.is_file():
        assert "_prepare_booksim_config" in main_py.read_text()
    runtime = (REPO / "tracks" / "t3-topology" / "dse" / "veritx_dse"
               / "simulation" / "serving_runtime.py").read_text()
    assert "_prepare_booksim_config" not in runtime


# ── evidence identity ────────────────────────────────────────────────────

def test_live_and_replay_evidence_are_distinguishable(tmp_path):
    machine, ns, serving = _qualified(instance_count=4)
    live = _backend(machine, serving, mode=cs.MODE_LIVE_CANONICAL)
    replay = _backend(machine, serving, mode=cs.MODE_REPLAY_ONLY,
                      binary=Path("/bin/true"))
    outcome = sr.run_live_round(
        backend=replay, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(4)),
        session_factory=_session_factory(
            comm={e: 1 for e in ns.participant_endpoints()},
            endpoints=ns.participant_endpoints()))
    replay_ev = sr.build_serving_evidence(backend=replay, rounds=(outcome,),
                                          workload_id="wl/x")
    live_ev = sr.build_serving_evidence(backend=live, rounds=(outcome,),
                                        workload_id="wl/x")
    assert replay_ev.execution_mode == cs.MODE_REPLAY_ONLY
    assert not replay_ev.reusable()
    with pytest.raises(cs.ServingBoundaryError, match="replay-only"):
        replay_ev.assert_live()
    assert live_ev.execution_mode == cs.MODE_LIVE_CANONICAL
    assert live_ev.reusable()
    assert live_ev.evidence_id() != replay_ev.evidence_id()


def test_evidence_binds_every_canonical_identity(tmp_path):
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_LIVE_CANONICAL)
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(4)),
        session_factory=_session_factory(
            comm={e: 1 for e in ns.participant_endpoints()},
            endpoints=ns.participant_endpoints()))
    evidence = sr.build_serving_evidence(
        backend=backend, rounds=(outcome,), workload_id="wl/identity",
        request_metrics=(cs.RequestMetric("r0", 10, 100),))
    identity = evidence.identity_dict()
    for field in ("machine_id", "namespace_id", "participant_mapping_id",
                  "serving_binding_id", "backend_id", "astra_binary_sha256",
                  "embedded_fabric_abi_version", "standalone_config_sha256",
                  "network_evidence_tier", "expansion_authority",
                  "instance_count", "served_instances", "request_count",
                  "request_metrics", "backend_evidence_ids"):
        assert field in identity, f"{field} is not bound into evidence"
    assert identity["machine_id"] == machine.machine_id()
    assert identity["namespace_id"] == ns.namespace_id()
    assert identity["network_evidence_tier"] \
        == cs.TIER_ASTRA_OWNED_COLLECTIVE
    assert identity["expansion_authority"] == cs.EXPANSION_AUTHORITY_ASTRA


def test_evidence_identity_excludes_host_facts(tmp_path):
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_LIVE_CANONICAL)
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(4)),
        session_factory=_session_factory(
            comm={e: 1 for e in ns.participant_endpoints()},
            endpoints=ns.participant_endpoints()))
    evidence = sr.build_serving_evidence(backend=backend, rounds=(outcome,),
                                         workload_id="wl/x")
    blob = json.dumps(evidence.identity_dict(), sort_keys=True)
    for token in ("/tmp", "pid", "run_dir", "wall_time", "host", "elapsed"):
        assert token not in blob


def test_evidence_is_deterministic_across_run_locations(tmp_path):
    machine, ns, serving = _qualified(instance_count=4)
    backend = _backend(machine, serving, mode=cs.MODE_LIVE_CANONICAL)
    ids = []
    for slot in ("a", "b"):
        outcome = sr.run_live_round(
            backend=backend, workload=_workload(),
            run_dir=tmp_path / slot, dispatched_instances=frozenset(range(4)),
            session_factory=_session_factory(
                comm={e: 1 for e in ns.participant_endpoints()},
                endpoints=ns.participant_endpoints()))
        ids.append(sr.build_serving_evidence(
            backend=backend, rounds=(outcome,),
            workload_id="wl/x").evidence_id())
    assert ids[0] == ids[1]


# ── real live end-to-end gate ────────────────────────────────────────────

_requires_built = pytest.mark.skipif(
    not BUILT_FROM_SOURCE.is_file(),
    reason="current-source ASTRA frontend not built")


def _live_backend(instance_count=4):
    machine, ns, serving = _qualified(instance_count=instance_count)
    backend = cs.CanonicalServingNetworkBackend(
        machine=machine, binding=serving, astra_binary=str(BUILT_FROM_SOURCE),
        astra_binary_sha256="pending", astra_binary_size=0,
        astra_source_revision=None, execution_mode=cs.MODE_LIVE_CANONICAL)
    return machine, ns, serving, backend


@_requires_built
def test_real_live_canonical_serving_round(tmp_path):
    """Live: LLMServingSim scheduling -> real ASTRA -> canonical BookSim."""
    machine, ns, serving, backend = _live_backend(instance_count=4)
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(4)), timeout_s=900)
    evidence = sr.build_serving_evidence(
        backend=backend, rounds=(outcome,), workload_id="wl/live",
        request_metrics=(cs.RequestMetric("r0", 100, 1000),))
    evidence.assert_live()
    assert evidence.every_instance_served()
    assert evidence.autonomous_injection_packets in ((0,), (None,))
    assert evidence.machine_id == machine.machine_id()
    assert evidence.namespace_id == ns.namespace_id()
    print(f"\n[live] instances={evidence.instance_count} "
          f"served={evidence.instances_with_completions} "
          f"comm={dict(evidence.endpoint_completions)} "
          f"injected={evidence.autonomous_injection_packets} "
          f"tier={evidence.network_evidence_tier} "
          f"evidence={evidence.evidence_id()[:24]}")


@_requires_built
def test_real_live_multi_instance_serving(tmp_path):
    """The multi-instance completion gate: every instance must serve."""
    machine, ns, serving, backend = _live_backend(instance_count=2)
    outcome = sr.run_live_round(
        backend=backend, workload=_workload(), run_dir=tmp_path / "run",
        dispatched_instances=frozenset(range(2)), timeout_s=900)
    evidence = sr.build_serving_evidence(
        backend=backend, rounds=(outcome,), workload_id="wl/live-multi")
    evidence.assert_all_instances_served()
    assert evidence.instances_with_completions == (0, 1)
    print(f"\n[live-multi] instances={evidence.instance_count} "
          f"served={evidence.instances_with_completions} "
          f"rounds={evidence.rounds}")
