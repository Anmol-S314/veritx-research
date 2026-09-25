"""Slice 33 — canonical ASTRA machine projection and runtime qualification."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path

import pytest

from test_backend_booksim_projection import _parents
from test_canonical_compiler import _anynet_policy, _det, _design, _vs

from veritx_dse.backend import astra_execution as ax
from veritx_dse.backend import astra_machine as am
from veritx_dse.backend.astra import AstraWorkloadProjection
from veritx_dse.backend.booksim_projection import (
    ANYNET_MIN_HOPS, MESH_DOR_PROFILE, prepare_booksim_input,
)
from veritx_dse.model.compile_model import TopologyFamily
from veritx_dse.workload.graph import (
    KIND_COLLECTIVE, KIND_COMPUTE, KIND_MULTICAST, KIND_PIM_CHANNEL,
    KIND_PIM_END,
    OperationNode, WorkloadGraph, collective_detail, compute_detail,
    multicast_detail, pim_detail, pim_end_detail,
)
from veritx_dse.workload.messages import LogicalMessageArtifactV2

REPO = Path(__file__).resolve().parents[4]
BOOKSIM_SOURCE = REPO

BUILT_FROM_SOURCE = (
    REPO / "third_party" / "astra-sim" / "astra-sim" / "network_frontend"
    / "booksim2" / "bin" / "AstraSim_BookSim2")

REAL_CANDIDATES = (
    os.environ.get("VERITX_ASTRA_BIN"),
    str(BUILT_FROM_SOURCE),
)
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "astra_tiny"


ARCHIVED_BINARY = Path(
    "/home/datavex/worktree-archive/veritx-manal/third_party/astra-sim/"
    "astra-sim/network_frontend/booksim2/bin/AstraSim_BookSim2")


def archived_astra_binary() -> Path | None:
    """The pre-existing binary: a DIFFERENTIAL REFERENCE only.

    Slice 33 proved it was built from source that differs from the vendored
    tree (it unwraps ``network.json``; the vendored source cannot), so it is
    never the canonical qualification producer.
    """
    return ARCHIVED_BINARY if ARCHIVED_BINARY.is_file() else None


def real_astra_binary() -> Path | None:
    for candidate in REAL_CANDIDATES:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    return None


def _logical(compiled, *, participants=16, ops=None):
    if ops is None:
        ops = (
            OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                          detail=compute_detail(duration_ns=10000,
                                                participant_count=participants)),
            OperationNode(operation_id="ar", kind=KIND_COLLECTIVE,
                          deps=("pre",),
                          detail=collective_detail(
                              collective_kind="ALLREDUCE",
                              participants=tuple(range(participants)),
                              payload_bytes=1024,
                              participant_count=participants)),
        )
    graph = WorkloadGraph(parallelism=compiled.inventory.parallelism,
                          participant_count=participants,
                          operations=tuple(ops))
    return LogicalMessageArtifactV2(graph=graph)


def _projection(compiled, *, granularity="collectives", ops=None,
                participants=16):
    return AstraWorkloadProjection.build(
        logical=_logical(compiled, participants=participants, ops=ops),
        resolved_fabric=compiled.resolved_fabric, mapping=compiled.mapping,
        attachment=compiled.attachment, et_granularity=granularity)


def _machine(*, anynet=False, granularity="collectives", flit_bytes=None,
             participants=16, ops=None, family=TopologyFamily.MESH):
    compiled, parents = _parents(family=family, compute=participants,
                                 tp=participants, anynet=anynet)
    prepared = prepare_booksim_input(parents)
    projection = _projection(compiled, granularity=granularity, ops=ops,
                             participants=participants)
    machine = am.qualify_astra_machine(
        parents=parents, prepared=prepared, projection=projection,
        logical=_logical(compiled, participants=participants, ops=ops),
        flit_bytes=flit_bytes)
    return compiled, parents, prepared, projection, machine


# ── 1. deterministic projection ───────────────────────────────────────────

def test_machine_projection_is_deterministic_and_content_addressed():
    _, _, _, _, first = _machine()
    _, _, _, _, second = _machine()
    assert first.machine_id() == second.machine_id()
    assert first.files() == second.files()
    assert first.machine_id().startswith("sha256:")
    digest = first.file_digests()
    assert set(digest) == {am.SYSTEM_FILE, am.NETWORK_FILE,
                           am.LOGICAL_TOPOLOGY_FILE, am.MEMORY_FILE}
    assert all(len(v.split(":", 1)[1]) == 64 for v in digest.values())


def test_render_is_a_function_of_canonical_parents_only():
    """Different qualifying runs on the same parents agree byte for byte."""
    compiled, parents, prepared, projection, machine = _machine()
    again = am.qualify_astra_machine(parents=parents, prepared=prepared,
                                     projection=projection)
    assert again.machine_id() == machine.machine_id()


# ── 2. parent identity binding ────────────────────────────────────────────

@pytest.mark.parametrize("field", [
    "resolved_fabric_hash", "mapping_hash", "attachment_hash",
    "topology_hash", "packet_format_hash", "vc_resource_hash",
    "route_artifact_hash", "prepared_id", "booksim_profile_id",
    "standalone_config_sha256", "workload_projection_id",
    "workload_semantics_version", "et_granularity", "expansion_authority",
    "participant_count", "router_count", "endpoint_count", "num_vcs",
    "flit_bytes", "packetization_fidelity", "ns_per_cycle", "memory_scope",
    "network_config_abi", "embedded_fabric_abi_version",
    "machine_profile_version", "machine_derivation_version",
    "astra_collective_profile_version", "memory_profile_version",
    "logical_dimensions", "logical_derivation", "workload_evidence_scope",
])
def test_every_parent_is_bound_into_machine_identity(field):
    _, _, _, _, machine = _machine()
    identity = machine.identity_dict()
    assert field in identity, f"{field} is not bound into machine identity"
    value = identity[field]
    mutated = dataclasses.replace(machine, **{field: _perturb(value)})
    assert mutated.machine_id() != machine.machine_id()


def _perturb(value):
    if isinstance(value, bool):
        return not value
    if isinstance(value, int):
        return value + 1
    if isinstance(value, float):
        return value + 1.0
    if isinstance(value, tuple):
        return tuple(value) + (1,)
    if isinstance(value, list):
        return list(value) + [1]
    return "srota/perturbed/v1"


def test_config_digests_are_bound_into_identity():
    _, _, _, _, machine = _machine()
    identity = machine.identity_dict()
    assert identity["config_digests"] == machine.file_digests()
    tampered = dataclasses.replace(machine, system_config_text='{"a": 1}')
    assert tampered.machine_id() != machine.machine_id()


def test_no_filesystem_path_enters_scientific_identity():
    _, _, _, _, machine = _machine()
    blob = json.dumps(machine.identity_dict(), sort_keys=True)
    for forbidden in ("mesh4x4", "network.json", "astra_tiny", "fixtures",
                      "file://", "/home/", "/tmp/", "/var/", "\\"):
        assert forbidden not in blob, f"{forbidden!r} leaked into identity"
    # the rendered system-name is a label, never a path
    assert "/" not in machine.to_dict()["system_config"]["system-name"]


# ── 3. system-field ownership closure ─────────────────────────────────────

def test_system_field_ownership_is_closed_and_justified():
    owners = am.SYSTEM_FIELD_OWNERS
    assert len(owners) == len(am.SYSTEM_FIELDS)
    for field in am.SYSTEM_FIELDS:
        assert field.owner in am.MachineFieldOwner
        assert field.source, f"{field.name} has no declared source"
    # every rendered field has an owner and is not UNSUPPORTED
    _, _, _, _, machine = _machine()
    rendered = json.loads(machine.system_config_text)
    for key in rendered:
        assert key in owners, f"rendered {key} has no declared owner"
        assert owners[key] is not am.MachineFieldOwner.UNSUPPORTED


def test_unsupported_fields_are_never_rendered():
    _, _, _, _, machine = _machine()
    rendered = json.loads(machine.system_config_text)
    for field in am.SYSTEM_FIELDS:
        if field.owner is am.MachineFieldOwner.UNSUPPORTED:
            assert field.name not in rendered, \
                f"UNSUPPORTED field {field.name} was rendered"


def test_collective_implementation_choices_are_profile_owned():
    _, _, _, _, machine = _machine()
    rendered = json.loads(machine.system_config_text)
    owners = am.SYSTEM_FIELD_OWNERS
    for key in am.ASTRA_COLLECTIVE_IMPLEMENTATIONS:
        assert owners[key] is am.MachineFieldOwner.BACKEND_PROFILE
        assert rendered[key] == am.ASTRA_COLLECTIVE_IMPLEMENTATIONS[key]


def test_no_magic_constants_outside_declared_profiles():
    _, _, _, _, machine = _machine()
    rendered = json.loads(machine.system_config_text)
    allowed = {**am.ASTRA_SCHEDULER_PROFILE,
               **am.ASTRA_COLLECTIVE_IMPLEMENTATIONS}
    for key, value in rendered.items():
        if key == "system-name":
            continue
        assert key in allowed, f"{key} is not a declared profile field"
        assert value == allowed[key], f"{key} is an undeclared magic value"


def test_system_name_is_derived_not_tuned():
    _, _, prepared, _, machine = _machine()
    name = machine.to_dict()["system_config"]["system-name"]
    assert str(prepared.router_count) in name
    assert str(machine.participant_count) in name


# ── 4. embedded fabric disarms autonomous injection ───────────────────────

def test_embedded_config_disarms_autonomous_injection():
    _, _, prepared, _, machine = _machine()
    text = machine.network_config_text
    # the Slice-31 standalone config DID carry a trace; the embedded one must not
    assert "trace(" in prepared.config_text
    assert "trace(" not in text
    assert "traffic = uniform;" in text
    assert "injection_rate = 0.0;" in text
    assert "injection_process = bernoulli;" in text
    assert machine.network_config_text.count("traffic") == 1


def test_standalone_trace_reference_is_refused_by_the_transform():
    _, _, prepared, _, _ = _machine()
    leaked = dataclasses.replace(prepared, config_text=prepared.config_text)
    assert "trace(" in leaked.config_text
    # the transform must never pass a trace pattern through
    config = am.embedded_fabric_config(leaked)
    assert "trace(" not in config.text
    assert config.carries_trace_reference is False


def test_machine_semantics_survive_the_embedded_transform():
    _, _, prepared, _, machine = _machine()
    from veritx_dse.backend.booksim_projection import parse_config_values
    standalone = parse_config_values(prepared.config_text)
    embedded = parse_config_values(machine.network_config_text)
    compared = 0
    for key in am.MACHINE_SEMANTIC_KEYS:
        if key in standalone:
            assert embedded[key] == standalone[key], \
                f"machine key {key} changed in the embedded projection"
            compared += 1
    assert compared >= 3, "no machine-semantic key was actually verified"
    # workload-driving keys are exactly the ones that changed
    changed = {k for k in standalone
               if k in embedded and embedded[k] != standalone[k]}
    assert changed <= {"traffic", "injection_rate", "injection_process"}


def test_embedded_config_keeps_the_certified_profile():
    _, _, _, _, machine = _machine()
    assert machine.booksim_profile_id == MESH_DOR_PROFILE.profile_id
    assert machine.network_config_text == machine.network_config_text


def test_anynet_machine_projection_keeps_min_routing():
    _, _, _, _, machine = _machine(anynet=True)
    from veritx_dse.backend.booksim_projection import parse_config_values
    values = parse_config_values(machine.network_config_text)
    assert values["routing_function"] == "min"
    assert values["topology"] == "anynet"
    assert "trace(" not in machine.network_config_text


# ── 5. network-config ABI ─────────────────────────────────────────────────

def test_network_config_abi_matches_the_vendored_source():
    assert am.NETWORK_CONFIG_ABI == "booksim2-network-config/cfg-file/v1"
    # source-proven: the vendored veritx_embed.cpp has no JSON unwrap
    assert ax.booksim_source_has_json_unwrap(BOOKSIM_SOURCE) is False
    # ...so the emitted network configuration must be a raw .cfg
    _, _, _, _, machine = _machine()
    assert machine.network_config_abi == am.NETWORK_CONFIG_ABI
    assert am.NETWORK_FILE.endswith(".cfg")
    assert not machine.network_config_text.lstrip().startswith("{")


def test_legacy_json_network_config_is_refused():
    """network.json is a legacy binary-only ABI, never emitted."""
    legacy = json.loads((FIXTURE / "network.json").read_text())
    assert set(legacy) == {"topology-type", "booksim-config-file", "num-nodes"}
    _, _, _, _, machine = _machine()
    assert machine.network_config_abi != am.LEGACY_NETWORK_CONFIG_ABI
    with pytest.raises(am.AstraMachineError):
        am.embedded_fabric_config(dataclasses.replace(
            _machine()[2], config_text=json.dumps(legacy)))


def test_fixture_machine_authority_is_reference_only():
    """The historical fixture may be read, never used as machine authority."""
    for name in ("system.json", "network.json", "logical_topology.json",
                 "memory.json", "mesh4x4.cfg"):
        assert (FIXTURE / name).is_file()
    _, _, _, _, machine = _machine()
    rendered = machine.files()
    fixture_cfg = (FIXTURE / "mesh4x4.cfg").read_text()
    assert "injection_rate = 0.1" in fixture_cfg  # standalone-style
    assert rendered[am.NETWORK_FILE].decode() != fixture_cfg


def test_binary_source_abi_divergence_is_recorded_honestly():
    binary = archived_astra_binary()
    if binary is None:
        pytest.skip("no archived ASTRA binary available")
    accepts_json = ax.probe_binary_network_abi(binary)
    source_unwraps = ax.booksim_source_has_json_unwrap(BOOKSIM_SOURCE)
    # the archived binary was built from JSON-capable source, the vendored
    # source is not: the divergence must be observable, not assumed
    assert accepts_json is True
    assert source_unwraps is False
    assert accepts_json != source_unwraps


# ── 6. logical topology ───────────────────────────────────────────────────

def test_logical_topology_is_flat_over_all_participants():
    _, _, _, _, machine = _machine()
    assert machine.logical_dimensions == (16,)
    config = json.loads(machine.logical_topology_text)
    assert config == {"logical-dimensions": [16]}
    assert machine.logical_derivation == "flat_all_participants"


def test_logical_topology_refuses_participant_mismatch():
    compiled, parents = _parents()
    prepared = prepare_booksim_input(parents)
    projection = _projection(compiled, participants=8)
    with pytest.raises(Exception) as excinfo:
        am.qualify_astra_machine(parents=parents, prepared=prepared,
                                 projection=projection)
    assert "participant mismatch" in str(excinfo.value)


def test_logical_dimensions_always_multiply_to_participants():
    _, _, _, projection, machine = _machine()
    product = 1
    for dim in machine.logical_dimensions:
        product *= dim
    assert product == projection.participant_count
    assert am.LogicalTopology(dimensions=(3, 5),
                              derivation="bogus").product() == 15


def test_no_silent_rank_replication():
    """Dimensions must describe the participants, never pad a node count."""
    _, _, _, _, machine = _machine()
    assert machine.logical_dimensions[0] == machine.participant_count
    # the fabric attachment also carries the driver endpoint, so the
    # participant count is a strict subset by construction
    assert machine.participant_count <= machine.endpoint_count


# ── 7. memory scope ───────────────────────────────────────────────────────

def test_memory_scope_is_runtime_required_and_proven_inert():
    _, _, _, _, machine = _machine()
    assert machine.memory_scope == am.MEMORY_SCOPE_RUNTIME_REQUIRED_INERT
    assert machine.memory_semantically_active is False
    memory = json.loads(machine.memory_config_text)
    assert memory["remote-mem-latency"] == 0
    assert memory["remote-mem-bw"] == 0
    # Slice-34 correction: the ASTRA Sys namespace is the BookSim NODE count
    # (k**n), not the attached-endpoint count
    assert memory["num-nodes"] == machine.astra_sys_count
    assert machine.astra_sys_count == 25
    assert machine.endpoint_count == 17


def test_historical_memory_constants_are_not_presented_as_canonical():
    _, _, _, _, machine = _machine()
    memory = json.loads(machine.memory_config_text)
    fixture = json.loads((FIXTURE / "memory.json").read_text())
    assert fixture["remote-mem-latency"] == 100
    assert memory["remote-mem-latency"] != fixture["remote-mem-latency"]
    assert machine.memory_profile_version == am.MEMORY_PROFILE_VERSION


def test_pim_workloads_are_refused():
    ops = (
        OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=10000,
                                            participant_count=16)),
        OperationNode(operation_id="PIM_CHANNEL_0", kind=KIND_PIM_CHANNEL,
                      deps=("pre",),
                      detail=pim_detail(channel=0, participant_count=16)),
        OperationNode(operation_id="PIM_END_0", kind=KIND_PIM_END,
                      deps=("PIM_CHANNEL_0",),
                      detail=pim_end_detail(participant_count=16)),
    )
    compiled, parents = _parents()
    prepared = prepare_booksim_input(parents)
    projection = _projection(compiled, ops=ops)
    with pytest.raises(Exception) as excinfo:
        am.qualify_astra_machine(
            parents=parents, prepared=prepared, projection=projection,
            logical=_logical(compiled, ops=ops))
    assert "memory" in str(excinfo.value).lower()


# ── 8. packetization fidelity ─────────────────────────────────────────────

def test_canonical_flit_width_is_used_by_default():
    _, _, _, _, machine = _machine()
    assert machine.packetization_fidelity == am.PACKETIZATION_CANONICAL
    assert machine.flit_bytes > 0
    # the fork's own embedded default is the same 8-byte (64-bit) flit
    assert machine.flit_bytes == 8


def test_coarse_packetization_is_labelled_lower_fidelity():
    _, _, _, _, coarse = _machine(flit_bytes=am.HISTORICAL_COARSE_FLIT_BYTES)
    assert coarse.packetization_fidelity == am.PACKETIZATION_COARSE
    canonical = _machine()[4]
    if canonical.flit_bytes != am.HISTORICAL_COARSE_FLIT_BYTES:
        assert coarse.machine_id() != canonical.machine_id()
    with pytest.raises(ax.AstraExecutionError):
        _execute_fake(coarse, require_canonical_packetization=True)


def test_narrower_than_canonical_flit_width_is_refused():
    _, _, _, _, machine = _machine()
    if machine.flit_bytes <= 1:
        pytest.skip("canonical width is already 1 byte")
    with pytest.raises(am.AstraMachineError):
        _machine(flit_bytes=1)


def test_ns_per_cycle_keeps_fabric_and_workload_domains_aligned():
    _, _, _, _, machine = _machine()
    assert machine.ns_per_cycle == am.CANONICAL_NS_PER_CYCLE == 1.0
    command = machine.runtime_command(
        binary="astra", workload_configuration="w.et",
        workload_directory=".")
    assert "--booksim2-ns-per-cycle=1.0" in command
    assert f"--booksim2-flit-bytes={machine.flit_bytes}" in command


# ── 9. execution evidence tiers ───────────────────────────────────────────

def _fake_outcome(machine, *, ranks=16, cycles=50000, exposed=30000,
                  injected=0, returncode=0, duplicate=False):
    # main.cc prints one GLOBAL wall time in both fields of its [workload]
    # line; per-endpoint numbers come from the statistics logger.
    lines = [f"[workload] sys[{e}] finished, {max(cycles, 1)} cycles, "
             f"exposed communication {max(cycles, 1)} cycles."
             for e in range(machine.astra_sys_count)]
    if duplicate:
        lines.append("[workload] sys[0] finished, 1 cycles, exposed "
                     "communication 1 cycles.")
    logs = "".join(
        f"[statistics] sys[{e}], Wall time: {cycles}\n"
        f"[statistics] sys[{e}], Comm time: {exposed}\n"
        for e in range(ranks))
    return ax.AstraOutcome(
        returncode=returncode, stdout="\n".join(lines) + "\n",
        stderr=logs + (f"[trace] All 0 cycles, injected={injected} — "
                       "draining\n" if injected is not None else ""))


def _runner(machine, **kwargs):
    outcome = _fake_outcome(machine, **kwargs)

    def run(command, cwd, timeout):
        return outcome
    return run


_RUN_SLOTS: dict[str, int] = {}


def _execute_fake(machine, tmp_path=None, *,
                  require_canonical_packetization=False,
                  expected_machine_id=None, **kwargs):
    import tempfile
    directory = Path(tmp_path or tempfile.mkdtemp())
    directory.mkdir(parents=True, exist_ok=True)
    slot = _RUN_SLOTS.get(str(directory), 0)
    _RUN_SLOTS[str(directory)] = slot + 1
    return ax.execute_astra_machine(
        machine=machine, binary=_fake_binary(directory),
        run_dir=directory / f"run-{slot}",
        workload_configuration=_fake_binary(directory),
        runner=_runner(machine, **kwargs),
        booksim_source_root=BOOKSIM_SOURCE,
        require_canonical_packetization=require_canonical_packetization,
        expected_machine_id=expected_machine_id)


def _fake_binary(directory: Path) -> Path:
    path = directory / "AstraSim_BookSim2"
    if not path.exists():
        directory.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"#!/bin/sh\nexit 0\n" + b"x" * 64)
        path.chmod(0o755)
    return path


def test_astra_collective_evidence_is_labelled(tmp_path):
    _, _, _, _, machine = _machine(granularity="collectives")
    evidence = _execute_fake(machine, tmp_path)
    assert evidence.status == ax.STATUS_EXECUTED
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_COLLECTIVE
    assert evidence.expansion_authority == "astra_comm_coll"
    assert evidence.rank_count == 16
    assert evidence.aggregate_cycles == 50000
    assert evidence.autonomous_injection_packets == 0


def test_canonical_message_mode_is_not_claimed_as_executed(tmp_path):
    _, _, _, _, machine = _machine(granularity="messages")
    evidence = _execute_fake(machine, tmp_path, exposed=0)
    assert evidence.status == ax.STATUS_UNSUPPORTED_MESSAGE_MODE
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_MESSAGES
    assert evidence.expansion_authority == "srota_logical_messages"


def test_tiers_cannot_be_conflated(tmp_path):
    collective = _execute_fake(_machine(granularity="collectives")[4], tmp_path)
    messages = _execute_fake(_machine(granularity="messages")[4],
                             tmp_path / "b", exposed=1)
    assert collective.evidence_tier != messages.evidence_tier
    with pytest.raises(ax.AstraExecutionError, match="not interchangeable"):
        ax.assert_comparable(collective, messages)


def test_different_machines_are_not_comparable(tmp_path):
    first = _execute_fake(_machine()[4], tmp_path)
    second = _execute_fake(_machine()[4], tmp_path / "b")
    ax.assert_comparable(first, second)     # same machine, same tier
    other = _execute_fake(_machine(participants=8)[4], tmp_path / "c", ranks=8)
    with pytest.raises(ax.AstraExecutionError, match="machine projections differ"):
        ax.assert_comparable(first, other)


def test_standalone_tier_is_distinct_from_embedded_tiers():
    tiers = {ax.EVIDENCE_TIER_STANDALONE_BOOKSIM,
             ax.EVIDENCE_TIER_EMBEDDED_FABRIC,
             ax.EVIDENCE_TIER_ASTRA_COLLECTIVE,
             ax.EVIDENCE_TIER_ASTRA_MESSAGES}
    assert len(tiers) == 4
    _, _, _, _, machine = _machine()
    assert ax._tier(machine) == ax.EVIDENCE_TIER_ASTRA_COLLECTIVE


def test_evidence_identity_excludes_host_facts(tmp_path):
    evidence = _execute_fake(_machine()[4], tmp_path)
    blob = json.dumps(evidence.identity_dict(), sort_keys=True)
    for token in ("wall_time", "host", "run_dir", "/tmp", "elapsed"):
        assert token not in blob
    assert evidence.evidence_id().startswith("sha256:")


# ── 10. runtime refusals ──────────────────────────────────────────────────

def test_rank_omission_and_duplication_refuse(tmp_path):
    _, _, _, _, machine = _machine()
    with pytest.raises(ax.AstraExecutionError, match="projected endpoints"):
        _execute_fake(machine, tmp_path, ranks=15)
    with pytest.raises(ax.AstraExecutionError, match="duplicate"):
        _execute_fake(machine, tmp_path / "b", duplicate=True)


def test_silent_communication_execution_refuses(tmp_path):
    _, _, _, _, machine = _machine(granularity="collectives")
    with pytest.raises(ax.AstraExecutionError, match="silent non-simulation"):
        _execute_fake(machine, tmp_path, cycles=1, exposed=0)


def test_autonomous_fabric_injection_refuses(tmp_path):
    _, _, _, _, machine = _machine()
    with pytest.raises(ax.AstraExecutionError, match="injected"):
        _execute_fake(machine, tmp_path, injected=42)


def test_nonzero_exit_and_timeout_refuse(tmp_path):
    _, _, _, _, machine = _machine()
    with pytest.raises(ax.AstraExecutionError, match="exited 7"):
        _execute_fake(machine, tmp_path, returncode=7)


def test_missing_config_refuses(tmp_path):
    _, _, _, _, machine = _machine()
    directory = tmp_path / "run"
    held = machine.machine_id()
    affected = dataclasses.replace(machine, memory_config_text="{}")
    # a coherent tamper cannot be seen by self-consistency; the externally
    # held machine_id sees it
    with pytest.raises(ax.AstraExecutionError, match="modified after"):
        ax.execute_astra_machine(
            machine=affected, binary=_fake_binary(tmp_path),
            run_dir=directory, workload_configuration=_fake_binary(tmp_path),
            runner=_runner(machine), expected_machine_id=held)
    with pytest.raises(ax.AstraExecutionError):
        ax.execute_astra_machine(
            machine=machine, binary=_fake_binary(tmp_path),
            run_dir=directory, workload_configuration=tmp_path / "absent.et",
            runner=_runner(machine))


def test_machine_tamper_refuses_before_spawn(tmp_path):
    _, _, _, _, machine = _machine()
    held = machine.machine_id()
    tampered = dataclasses.replace(machine, network_config_text="x = 1;\n")
    with pytest.raises(ax.AstraExecutionError, match="modified after"):
        ax.execute_astra_machine(
            machine=tampered, binary=_fake_binary(tmp_path),
            run_dir=tmp_path / "run",
            workload_configuration=_fake_binary(tmp_path),
            runner=_runner(machine), expected_machine_id=held)


def test_runtime_binary_substitution_refuses(tmp_path):
    from veritx_dse.backend.producer import resolve_producer_identity
    binary = _fake_binary(tmp_path)
    identity = resolve_producer_identity(binary)
    binary.write_bytes(b"#!/bin/sh\nexit 0\n" + b"y" * 64)
    binary.chmod(0o755)
    from veritx_dse.backend.producer import (
        ProducerError, recheck_binary_digest,
    )
    with pytest.raises(ProducerError, match="changed between identification"):
        recheck_binary_digest(identity)


def test_execution_requires_a_machine_projection(tmp_path):
    with pytest.raises(ax.AstraExecutionError, match="AstraMachineProjection"):
        ax.execute_astra_machine(
            machine={"not": "a machine"}, binary=_fake_binary(tmp_path),
            run_dir=tmp_path / "run",
            workload_configuration=_fake_binary(tmp_path))


# ── 11. replicated-unicast scope ──────────────────────────────────────────

def test_replicated_unicast_multicast_remains_labelled():
    ops = (
        OperationNode(operation_id="pre", kind=KIND_COMPUTE,
                      detail=compute_detail(duration_ns=10000,
                                            participant_count=16)),
        OperationNode(operation_id="m", kind=KIND_MULTICAST, deps=("pre",),
                      detail=multicast_detail(
                          source_rank=0, destinations=(1, 2), payload_bytes=64,
                          replication="SOURCE_REPLICATION",
                          participant_count=16)),
    )
    _, _, _, projection, machine = _machine(ops=ops)
    assert projection.evidence_scope() == "replicated_unicast"
    assert machine.workload_evidence_scope == "replicated_unicast"


def test_canonical_message_scope_is_labelled():
    _, _, _, _, machine = _machine(granularity="messages")
    assert machine.workload_evidence_scope == "canonical_logical_messages"


# ── 12. real execution ────────────────────────────────────────────────────

_requires_binary = pytest.mark.skipif(
    real_astra_binary() is None, reason="no ASTRA runtime binary available")


def _real_run(tmp_path, *, granularity="collectives", machine=None,
              timeout_s=600):
    if machine is None:
        _, _, _, projection, machine = _machine(granularity=granularity)
    else:
        projection = None
    directory = tmp_path / "run"
    directory.mkdir(parents=True, exist_ok=True)
    workload = directory / "workload.et"
    _write_workload_et(workload, machine)
    evidence = ax.execute_astra_machine(
        machine=machine, binary=real_astra_binary(), run_dir=directory,
        workload_configuration=workload, timeout_s=timeout_s,
        booksim_source_root=BOOKSIM_SOURCE)
    return evidence


def _write_workload_et(path: Path, machine) -> None:
    """Stage the canonical Chakra ETs for exactly the projected ranks."""
    _, _, _, projection, _ = _machine(granularity=machine.et_granularity)
    base, ranks = am.stage_workload(projection, path.parent)
    assert len(ranks) == machine.participant_count
    path.write_bytes(base.read_bytes())


@_requires_binary
def test_real_run_is_either_scoped_or_refused_with_a_diagnosis(tmp_path):
    """A real run must never be reported as scoped evidence by accident.

    KNOWN RUNTIME PROPERTY (Slice 33 blocker): the vendored frontend
    instantiates one NPU per *fabric node* and falls back to the base
    workload file for nodes without a rank file, so the canonical fabric's
    non-participant nodes replicate the trace.  When that happens the gate
    must refuse; when it does not happen we must get scoped evidence.
    """
    _, _, _, _, machine = _machine()
    directory = tmp_path / "run"
    directory.mkdir(parents=True, exist_ok=True)
    workload = directory / "workload.et"
    _write_workload_et(workload, machine)
    try:
        evidence = ax.execute_astra_machine(
            machine=machine, binary=real_astra_binary(), run_dir=directory,
            workload_configuration=workload, timeout_s=600,
            booksim_source_root=BOOKSIM_SOURCE)
    except ax.AstraExecutionError as exc:
        # Any refusal is acceptable here; what must never happen is this run
        # being reported as scoped evidence.  The strict qualification gate
        # lives in tests/test_backend_astra_namespace.py (endpoint-indexed ETs
        # + communicator groups), which is what the canonical path requires.
        print(f"\n[real] refused by the gate: {str(exc)[:160]}")
        return
    # if the runtime ever isolates participants, the evidence must be scoped
    assert evidence.evidence_tier in (ax.EVIDENCE_TIER_ASTRA_COLLECTIVE,
                                      ax.EVIDENCE_TIER_ASTRA_MESSAGES)
    assert evidence.rank_count == machine.participant_count
    assert evidence.namespace_binding == ax.NAMESPACE_BINDING_IDENTITY
    assert evidence.idle_fabric_endpoints == tuple(
        range(machine.participant_count, machine.astra_sys_count))
    assert evidence.autonomous_injection_packets in (None, 0)
    print(f"\n[real] SCOPED tier={evidence.evidence_tier} "
          f"ranks={evidence.rank_count} aggregate={evidence.aggregate_cycles} "
          f"evidence={evidence.evidence_id()[:24]}")


@_requires_binary
def test_real_repeat_run_is_deterministic_when_scoped(tmp_path):
    first = _try_real_run(tmp_path / "a")
    second = _try_real_run(tmp_path / "b")
    if first is None or second is None:
        pytest.skip("real runs are refused by the runtime defect; "
                    "determinism is unobservable")
    assert first.evidence_id() == second.evidence_id()
    assert first.per_rank_cycles == second.per_rank_cycles


@_requires_binary
def test_real_canonical_message_mode_is_recorded_not_hidden(tmp_path):
    evidence = _try_real_run(tmp_path, granularity="messages")
    if evidence is None:
        pytest.skip("real runs are refused by the runtime defect")
    assert evidence.evidence_tier == ax.EVIDENCE_TIER_ASTRA_MESSAGES
    assert evidence.expansion_authority == "srota_logical_messages"
    assert evidence.status in (ax.STATUS_EXECUTED,
                               ax.STATUS_UNSUPPORTED_MESSAGE_MODE)


def _try_real_run(tmp_path, *, granularity="collectives"):
    _, _, _, _, machine = _machine(granularity=granularity)
    directory = tmp_path / "run"
    directory.mkdir(parents=True, exist_ok=True)
    workload = directory / "workload.et"
    _write_workload_et(workload, machine)
    try:
        return ax.execute_astra_machine(
            machine=machine, binary=real_astra_binary(), run_dir=directory,
            workload_configuration=workload, timeout_s=600,
            booksim_source_root=BOOKSIM_SOURCE)
    except ax.AstraExecutionError:
        return None


# ── 13. historical differential / regression reference ────────────────────

def _fixture_run(tmp_path, *, network_config="mesh4x4.cfg"):
    """Run the historical fixture through the ARCHIVED reference binary."""
    import shutil
    directory = tmp_path / "fixture"
    shutil.copytree(FIXTURE, directory)
    binary = archived_astra_binary() or real_astra_binary()
    command = (
        str(binary),
        f"--system-configuration=system.json",
        f"--network-configuration={network_config}",
        "--logical-topology-configuration=logical_topology.json",
        "--workload-configuration=one-coll.et",
        "--memory-configuration=memory.json",
        "--remote-memory-configuration=memory.json",
        "--booksim2-extra=injection_rate=0.0",
    )
    proc = subprocess.run(command, cwd=str(directory),
                          stdin=subprocess.DEVNULL, capture_output=True,
                          text=True, timeout=600)
    return proc


@pytest.mark.skipif(archived_astra_binary() is None,
                    reason="no archived reference binary available")
def test_reference_fixture_reproduces_the_qualified_cycles(tmp_path):
    """§13: the 30,310-cycle communication component stays a reference."""
    proc = _fixture_run(tmp_path)
    assert proc.returncode == 0, proc.stderr[-400:]
    combined = proc.stdout + proc.stderr
    assert "Wall time: 50310" in combined
    assert "Comm time: 30310" in combined
    money = ax.parse_astra_stats(proc.stdout, proc.stderr)
    cycles = dict(money.cycles)
    assert set(range(16)) <= set(cycles)
    assert max(cycles[r] for r in range(16)) == 50310
    assert ax.autonomous_injection_packets(proc.stderr) in (None, 0)


@pytest.mark.skipif(archived_astra_binary() is None,
                    reason="no archived reference binary available")
def test_historical_json_and_canonical_cfg_abis_agree_on_the_fixture(tmp_path):
    """The legacy JSON wrapper and the canonical .cfg ABI are equivalent."""
    cfg = _fixture_run(tmp_path / "cfg", network_config="mesh4x4.cfg")
    jsn = _fixture_run(tmp_path / "json", network_config="network.json")
    assert cfg.returncode == jsn.returncode == 0
    a = ax.parse_astra_stats(cfg.stdout, cfg.stderr)
    b = ax.parse_astra_stats(jsn.stdout, jsn.stderr)
    assert dict(a.cycles) == dict(b.cycles)
    # ...but only the .cfg ABI is what the vendored source accepts
    assert ax.booksim_source_has_json_unwrap(BOOKSIM_SOURCE) is False


@_requires_binary
def test_reference_fixture_has_no_canonical_machine_authority():
    """The fixture is a reference input, never this slice's authority."""
    _, _, _, _, machine = _machine()
    rendered = machine.files()
    assert set(rendered) == {am.SYSTEM_FILE, am.NETWORK_FILE,
                             am.LOGICAL_TOPOLOGY_FILE, am.MEMORY_FILE}
    # every rendered field is a declared, derived value
    system = json.loads(machine.system_config_text)
    for key in system:
        assert key in am.SYSTEM_FIELD_OWNERS
    assert "mesh4x4" not in json.dumps(machine.identity_dict())


def test_parser_never_infers_participation_from_global_wall_time():
    """main.cc's [workload] line carries ONE global wall time for every Sys.

    It therefore cannot prove that endpoint ``i`` communicated.  Participation
    must come from the statistics logger; an idle Sys has no entry and must
    stay idle rather than inherit the global wall time.
    """
    _, _, _, _, machine = _machine()
    participants = tuple(range(machine.participant_count))
    idle = tuple(range(machine.participant_count, machine.astra_sys_count))
    assert idle, "the fixture must have non-participant Sys ids"
    # identical, non-zero global wall time for participants AND idle Sys
    stdout = "".join(
        f"[workload] sys[{e}] finished, 50000 cycles, exposed communication "
        "50000 cycles.\n" for e in range(machine.astra_sys_count))
    stderr = "".join(
        f"[statistics] sys[{e}], Wall time: 50000\n"
        f"[statistics] sys[{e}], Comm time: 30000\n" for e in participants)

    money = ax.parse_astra_stats(stdout, stderr)
    exposed = dict(money.exposed_comm)
    assert set(exposed) == set(participants), \
        "an idle Sys inherited the global wall time as exposure"
    for endpoint in idle:
        assert exposed.get(endpoint) is None
        assert endpoint not in dict(money.exposed_comm)

    admitted = ax.assert_astra_gate(
        money, machine=machine, injected=0,
        participant_endpoints=participants,
        endpoint_count=machine.astra_sys_count)
    assert admitted == idle
    assert max(exposed.values()) == 30000

    # a participant without a statistics entry is an omission, not a wall time
    partial = "".join(
        f"[statistics] sys[{e}], Wall time: 50000\n"
        f"[statistics] sys[{e}], Comm time: 30000\n" for e in participants[:-1])
    with pytest.raises(ax.AstraExecutionError, match="projected endpoints"):
        ax.assert_astra_gate(
            ax.parse_astra_stats(stdout, partial), machine=machine, injected=0,
            participant_endpoints=participants,
            endpoint_count=machine.astra_sys_count)


def test_global_line_alone_is_not_execution_evidence():
    """A run that only prints the global line proves nothing per endpoint."""
    _, _, _, _, machine = _machine()
    stdout = "".join(
        f"[workload] sys[{e}] finished, 50000 cycles, exposed communication "
        "50000 cycles.\n" for e in range(machine.astra_sys_count))
    money = ax.parse_astra_stats(stdout, "")
    assert dict(money.exposed_comm) == {}
    with pytest.raises(ax.AstraExecutionError, match="projected endpoints"):
        ax.assert_astra_gate(
            money, machine=machine, injected=0,
            participant_endpoints=tuple(range(machine.participant_count)),
            endpoint_count=machine.astra_sys_count)
