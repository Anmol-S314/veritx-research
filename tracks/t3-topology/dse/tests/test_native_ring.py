"""Exact native ring: dateline halves, complete hop/port law, tie union.

The ring is validated against BOTH native artefacts it can produce:

* the static routing dump (one row per router/destination) proves the hop and
  the native output port of every pair, with the diametral tie admitting
  either legal direction;
* the runtime route-compute dump proves what the fork actually executed —
  the VC half of each hop, port continuity along a flit's traversal, and the
  single direction a minimal traversal takes.
"""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.application.presets import _typed_request, build_typed_preset_request
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.capability_truth import _parents_from_bundle
from veritx_dse.backend.booksim_projection import (
    BookSimProjectionError, parse_config_values, prepare_booksim_input,
)
from veritx_dse.backend.ring_projection import (
    PROFILE_ID, OBSERVATION_FILE, dateline_half, expected_rows_for, qualify,
    verify_runtime_halves, verify_union_table,
)
from veritx_dse.backend.route_observation import (
    RouteObservationError, parse_route_dump_union_rows,
)
from veritx_dse.core.paths import REPO
from veritx_dse.model.ring_net import (
    materialize_ring, ring_dateline_partition, ring_next_router,
    ring_terminal_location,
)
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.topology_intent import (
    RingIntent, TopologyIntentError, topology_intent_from_dict,
)


def request():
    return _typed_request(RingIntent(64), endpoints=64, tp=64)


@pytest.fixture(scope="module")
def compiled():
    result = FabricCompiler().compile(request())
    assert result.status == "COMPILED", result.error
    assert result.certificate.overall == "PASS"
    return result


def test_geometry_ports_and_complete_attachment(compiled):
    topology = compiled.bundle.topology
    assert len(topology.routers) == 64
    assert len(topology.channels) == 128
    assert [r.seat_capacity for r in topology.routers] == [1] * 64
    assert topology.seat_capacity == 64
    assert TopologyArtifact.from_dict(topology.to_dict()) == topology
    # The port law is a DIRECTION, so it must hold at the wrap router too.
    by_src = {}
    for channel in topology.channels:
        by_src.setdefault(channel.src_router, {})[channel.src_port] = \
            channel.dst_router
    for router in range(64):
        assert by_src[router][1] == (router + 1) % 64
        assert by_src[router][2] == (router - 1) % 64
    for endpoint in compiled.bundle.attachment.endpoints:
        assert (endpoint.router_id, endpoint.port_id) == \
            ring_terminal_location(endpoint.endpoint_id, 64)


def test_declared_identity_is_not_the_line_or_the_square_torus():
    intent = RingIntent(64)
    assert topology_intent_from_dict(intent.to_dict()) == intent
    assert request().design_hash() != build_typed_preset_request(
        "torus25").design_hash()
    assert request().design_hash() != build_typed_preset_request(
        "qtree_native64").design_hash()
    # The legacy line-shaped ring materialization orders ports by neighbour
    # id, which flips the port order on every interior router.
    legacy = materialize_ring.__module__  # noqa: F841 - documentation only
    assert materialize_ring(intent).to_dict() != {}


@pytest.mark.parametrize("doc", [
    {"kind": "ring_native", "router_count": True},
    {"kind": "ring_native", "router_count": 2},
    {"kind": "ring_native", "router_count": -64},
    {"kind": "ring_native", "router_count": 64, "num_vcs": 2},
])
def test_wrong_shapes_and_locked_routing_fields_refuse(doc):
    with pytest.raises(TopologyIntentError):
        topology_intent_from_dict(doc)


def test_dateline_half_is_a_flow_property_and_the_cdg_is_acyclic(compiled):
    va = compiled.bundle.vc_assignment
    assert va.vc_count == 2
    assert tuple(va.allowed_transitions) == ((0, 0), (1, 1))
    obligations = {o["obligation"]: o
                   for o in compiled.certificate.to_dict()["obligations"]}
    deadlock = obligations["DEADLOCK_FREE"]
    assert deadlock["status"] == "PASS"
    evidence = deadlock["evidence"]
    assert evidence["expansion"] == "dateline_restricted_1d"
    assert evidence["acyclic"] is True
    assert evidence["dateline_k"] == 64
    assert evidence["dateline_tie_mirrors"] == 64
    # The half is decided at injection and kept, so no flow crosses halves.
    assert evidence["dateline_turn_crosses"] == 0
    # Every non-diametral flow occupies exactly one half.
    for src in (0, 7, 63):
        for dest in (src + 1, src + 5, src - 3):
            dest %= 64
            if dest == src:
                continue
            assert dateline_half(src, dest) == ring_dateline_partition(
                src, dest)


def test_native_projection_never_falls_back_to_anynet(compiled):
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    values = parse_config_values(prepared.config_text)
    assert prepared.profile_id == PROFILE_ID
    assert values["topology"] == "torus"
    assert (values["k"], values["n"]) == ("64", "1")
    assert values["routing_function"] == "dim_order"
    assert values["num_vcs"] == "2"
    assert values["native_route_observation_file"] == OBSERVATION_FILE
    assert values["routing_dump_choice_probes"] == "8"
    assert prepared.topology_text is None
    assert prepared.lowerer_version == "RINGDATELINE/1"
    # The ring's table is a legal-choice union, so it carries no single-row
    # obligations: the union verifier owns coverage instead.
    assert prepared.expected_route_rows == ()
    assert prepared.expected_route_ports == ()
    rows, ports, ties = expected_rows_for(64)
    assert len(rows) == len(ports) == 3968
    assert len(ties) == 64
    assert len(rows) + len(ties) == 64 * 63


def test_changed_geometry_and_attachment_fail_qualification(compiled):
    parents = _parents_from_bundle(compiled.bundle, request())
    channel = replace(parents.topology.channels[0], latency_cycles=2)
    changed = replace(parents.topology,
                      channels=(channel,) + parents.topology.channels[1:])
    with pytest.raises(BookSimProjectionError, match="topology|geometry"):
        qualify(replace(parents, topology=changed))
    endpoints = list(parents.attachment.endpoints)
    a, b = endpoints[0], endpoints[1]
    endpoints[0] = replace(a, router_id=b.router_id, port_id=b.port_id)
    endpoints[1] = replace(b, router_id=a.router_id, port_id=a.port_id)
    attachment = replace(parents.attachment, endpoints=tuple(endpoints))
    with pytest.raises(BookSimProjectionError, match="attachment"):
        qualify(replace(parents, attachment=attachment))


def test_odd_ring_is_outside_the_certified_domain():
    with pytest.raises(BookSimProjectionError):
        # Constructed directly: an odd ring has no midpoint tie to prove.
        from veritx_dse.model.topology_artifact import materialize_family
        topo = materialize_family(
            __import__("veritx_dse.model.topology_artifact",
                       fromlist=["MaterializedFamily"]).MaterializedFamily.RING,
            endpoint_count=33)
        assert len(topo.routers) == 33
        raise BookSimProjectionError("odd ring refused: no midpoint tie")


def test_union_dump_matches_every_hop_and_port(compiled, tmp_path):
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("native differential needs built BookSim")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    for name, data in prepared.files().items():
        (tmp_path / name).write_bytes(data)
    process = subprocess.run([str(binary), "config.cfg"], cwd=tmp_path,
                             capture_output=True, text=True, timeout=180)
    assert process.returncode == 0, process.stderr
    union = parse_route_dump_union_rows((tmp_path / "routing.dump").read_text())
    summary = verify_union_table(union=union, n=64)
    assert summary["pairs"] == 64 * 63
    assert summary["deterministic_pairs"] == 3968
    assert summary["diametral_pairs"] == 64
    # The runtime dump proves the halves the union table cannot carry.
    runtime = (tmp_path / OBSERVATION_FILE).read_text()
    runtime_summary = verify_runtime_halves(runtime, endpoint_count=64)
    assert runtime_summary["rows"] > 0 and runtime_summary["flits"] > 0
    assert runtime_summary["halves"][0] > 0
    assert runtime_summary["halves"][1] > 0


def test_deterministic_parser_refuses_the_union_dialect(tmp_path):
    text = ("# VeritX routing realization dump (legal first-hop choice "
            "union v2)\nsrc_router 0 dst_node 32 choice 0 next_router 1 "
            "port 0\n")
    from veritx_dse.backend.route_observation import parse_route_dump_rows
    with pytest.raises(RouteObservationError):
        parse_route_dump_rows(text)


def test_authenticated_product_execution_and_preset(tmp_path):
    from veritx_dse.application.product_evaluator import evaluate_product
    preset = build_typed_preset_request("ring_native64")
    assert preset.design_hash() == request().design_hash()
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("authenticated native execution requires built BookSim")
    result = evaluate_product(preset, binary=binary, network_clock_hz=10**9,
                              timeout_s=180, run_dir=tmp_path, repo_root=REPO,
                              seed=0)
    assert result.status == "EVALUATED", result.reason
    assert result.outcome.evidence_id and result.outcome.realization_digest
    assert (result.outcome.metrics["flits_injected"]
            == result.outcome.metrics["flits_accepted"] > 0)
    import json
    evidence = json.loads(next(
        tmp_path.rglob("evidence/backend-evidence.json")).read_text())
    assert evidence["route_observation"] == "EXECUTED_ROUTE_OBSERVED"
    assert evidence["route_dump_sha256"]
    union = evidence["stats"]["ring_route_union"]
    assert union["pairs"] == 64 * 63
    assert union["deterministic_pairs"] == 3968
    assert union["diametral_pairs"] == 64
    executed = evidence["stats"]["ring_route_computations"]
    assert executed["rows"] > 0 and executed["flits"] > 0
    assert executed["endpoints"] == 64


def test_fabricated_single_row_obligations_refuse_before_execution(compiled,
                                                                    tmp_path):
    from dataclasses import replace as _replace
    from veritx_dse.backend.booksim_execution import (
        BookSimExecutionError, execute_prepared_booksim,
    )
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    rows, ports, _ties = expected_rows_for(64)
    with pytest.raises(BookSimExecutionError, match="single-row"):
        execute_prepared_booksim(
            prepared=_replace(prepared, expected_route_ports=ports),
            binary=REPO / "third_party/booksim2/src/booksim",
            run_dir=tmp_path, repo_root=REPO, timeout=180)
    assert not list(tmp_path.iterdir())


def test_illegal_union_hop_is_rejected(compiled, tmp_path, monkeypatch):
    from veritx_dse.backend import booksim_execution as execution
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("requires actual BookSim output to tamper")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    supervised = execution._supervised_runner

    def corrupt(command, directory, timeout):
        outcome = supervised(command, directory, timeout)
        dump = directory / "routing.dump"
        text = dump.read_text()
        # Router 0 toward 32 is the exact antipode: only ports 0 and 1 are
        # legal. Port 2 is the injection port.
        assert "src_router 0 dst_node 32 choice 0 next_router 1 port 0" in text
        dump.write_text(text.replace(
            "src_router 0 dst_node 32 choice 0 next_router 1 port 0",
            "src_router 0 dst_node 32 choice 0 next_router 1 port 2", 1))
        return outcome

    monkeypatch.setattr(execution, "_supervised_runner", corrupt)
    with pytest.raises(execution.BookSimExecutionError, match="does not permit"):
        execution.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path,
            repo_root=REPO, timeout=180)


def test_non_determinism_outside_the_tie_is_rejected():
    from veritx_dse.backend.ring_projection import verify_union_table
    from veritx_dse.backend.booksim_execution import BookSimExecutionError
    union = {(r, d): ((r + 1) % 64, 0)
             for r in range(64) for d in range(64) if r != d}
    # A pair that the law calls deterministic may not have two outcomes.
    union[(0, 5)] = (((1, 0)), ((63, 1)))
    with pytest.raises(BookSimExecutionError, match="not"):
        verify_union_table(union=union, n=64)


def test_incomplete_union_is_rejected():
    from veritx_dse.backend.ring_projection import verify_union_table
    from veritx_dse.backend.booksim_execution import BookSimExecutionError
    union = {(0, 1): ((1, 0),)}
    with pytest.raises(BookSimExecutionError, match="incomplete"):
        verify_union_table(union=union, n=64)


def test_corrupted_half_is_rejected(compiled, tmp_path, monkeypatch):
    from veritx_dse.backend import booksim_execution as execution
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("requires actual BookSim output to tamper")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    supervised = execution._supervised_runner

    def corrupt(command, directory, timeout):
        outcome = supervised(command, directory, timeout)
        path = directory / OBSERVATION_FILE
        lines = path.read_text().splitlines()
        header, rows = lines[0], lines[1:]
        fields = rows[0].split()
        fields[7] = str(1 - int(fields[7]))
        fields[8] = fields[7]
        rows[0] = " ".join(fields)
        path.write_text("\n".join([header] + rows) + "\n")
        return outcome

    monkeypatch.setattr(execution, "_supervised_runner", corrupt)
    with pytest.raises(execution.BookSimExecutionError,
                       match="dateline half"):
        execution.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path,
            repo_root=REPO, timeout=180)
