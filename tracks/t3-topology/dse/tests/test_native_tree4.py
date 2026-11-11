"""Exact native Tree4: four roots, redundant upward choice, union evidence.

Tree4 cannot be certified from a single-row first-hop table, because the
fork draws the upward parent with a real ``RandomInt``. Both native
artefacts are used instead:

* the static legal-choice UNION dump proves the set of hops every
  (router, terminal) pair may take — a root picks one of the two middles of
  the destination group, a middle picks any of the four roots, a leaf picks
  one of its two parents;
* the runtime route-compute dump proves which hops the run executed, that
  they are inside that union, that every flow enters through its source
  terminal's seat port, uses the full VC range, and climbs toward the roots
  before it descends.
"""
from dataclasses import replace
import json
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.application.presets import _typed_request, build_typed_preset_request
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.capability_truth import _parents_from_bundle
from veritx_dse.backend.booksim_projection import (
    BookSimProjectionError, prepare_booksim_input,
)
from veritx_dse.backend.route_observation import (
    RouteObservationError, parse_route_dump_union_rows,
)
from veritx_dse.backend.tree4_projection import (
    CHOICE_PROBES, OBSERVATION_FILE, PROFILE_ID, expected_rows, legal_hops,
    model_topology, pinned_geometry, qualify, verify_runtime,
    verify_union_table,
)
from veritx_dse.core.paths import REPO
from veritx_dse.core.route_artifact import TREE4_NCA, TREE4_NCA_DEFINITION
from veritx_dse.model.topology_artifact import MaterializedFamily
from veritx_dse.model.topology_intent import (
    Tree4Intent, TopologyIntentError, topology_intent_from_dict,
)
from veritx_dse.model.tree4_net import (
    LEVEL_COUNTS, OFFSETS, TERMINALS, materialize_tree4, router_level_position,
    tree4_legal_ports, tree4_native_router_id, tree4_next_router,
    tree4_terminal_location, tree4_terminal_of_seat, tree4_witness_path,
)


def request():
    return _typed_request(Tree4Intent(4, 3), endpoints=64, tp=64)


@pytest.fixture(scope="module")
def compiled():
    result = FabricCompiler().compile(request())
    assert result.status == "COMPILED", result.error
    assert result.certificate.overall == "PASS"
    return result


def test_geometry_ports_and_complete_attachment(compiled):
    topology = compiled.bundle.topology
    assert topology.family is MaterializedFamily.TREE4_NATIVE
    assert len(topology.routers) == 28
    assert LEVEL_COUNTS == (4, 8, 16) and OFFSETS == (0, 4, 12)
    assert len(topology.channels) == 128
    # Leaves own the four terminal seats; transit routers own none.
    assert [r.seat_capacity for r in topology.routers] == [0] * 12 + [4] * 16
    assert sum(r.seat_capacity for r in topology.routers) == TERMINALS
    endpoints = compiled.bundle.attachment.endpoints
    assert len(endpoints) == 64
    for endpoint in endpoints:
        assert (endpoint.router_id, endpoint.port_id) == tree4_terminal_location(
            endpoint.endpoint_id)
    # The native port law: a root leaves down through ports 0..7, a middle
    # through 0..3 (its four leaves) then 4..7 (the four roots), a leaf
    # through 0..3 (its seats) then 4..5 (its two parents).
    channels = {}
    for channel in topology.channels:
        channels.setdefault(channel.src_router, {})[channel.src_port] = (
            channel.dst_router)
    for router, ports in channels.items():
        level, position = router_level_position(router)
        if level == 0:
            assert sorted(ports) == list(range(8))
        elif level == 1:
            assert sorted(ports) == list(range(8))
            assert ports[4] == OFFSETS[0] + 0
        else:
            assert sorted(ports) == [4, 5]


def test_declared_identity_is_not_the_balanced_tree():
    from veritx_dse.model.topology_artifact import (
        k_ary_tree_graph, materialize_ir,
    )
    balanced = materialize_ir(k_ary_tree_graph(radix=4, tiers=3))
    native = materialize_tree4(Tree4Intent(4, 3))
    # The structured `tree4` preset is the balanced k-ary tree with ONE
    # parent per node; the native tree has four roots and redundant upward
    # links, so the two must not share a materialized identity.
    assert balanced.family is MaterializedFamily.CUSTOM
    assert native.family is MaterializedFamily.TREE4_NATIVE
    assert native.canonical_dict() != balanced.canonical_dict()
    assert (len(native.routers), len(native.channels)) == (28, 128)
    assert TREE4_NCA_DEFINITION.parameters != ()


def test_wrong_shapes_and_locked_routing_fields_refuse():
    for bad in ({"kind": "tree4_native", "radix": 2, "levels": 3},
                {"kind": "tree4_native", "radix": 4, "levels": 2},
                {"kind": "tree4_native", "radix": 4, "levels": 3,
                 "routing_function": "nca"},
                {"kind": "tree4_native", "radix": True, "levels": 3}):
        with pytest.raises(TopologyIntentError):
            topology_intent_from_dict(bad)
    doc = Tree4Intent(4, 3).to_dict()
    assert topology_intent_from_dict(doc) == Tree4Intent(4, 3)


def test_legal_union_is_the_fork_law(compiled):
    topology = compiled.bundle.topology
    # A root has two middles (the destination group); a middle has four
    # roots (`RandomInt(gK-1)` is INCLUSIVE in this fork, so port 7 is a
    # real face); a leaf has two parents and ejects locally.
    root = OFFSETS[0]
    assert sorted(tree4_legal_ports(root, 0)) == [0, 1]
    assert sorted(tree4_legal_ports(root, 63)) == [6, 7]
    middle = OFFSETS[1] + 0
    assert sorted(tree4_legal_ports(middle, 0)) == [0]
    assert sorted(tree4_legal_ports(middle, 63)) == [4, 5, 6, 7]
    leaf = tree4_terminal_location(0)[0]
    assert sorted(tree4_legal_ports(leaf, 0)) == [0]
    assert sorted(tree4_legal_ports(leaf, 63)) == [4, 5]
    for router in range(28):
        for terminal in range(64):
            for following, port in legal_hops(topology, router, terminal):
                if following is None:
                    assert tree4_terminal_of_seat(router, port) == terminal
                else:
                    assert tree4_next_router(router, port) == following


def test_the_canonical_witness_terminates_everywhere(compiled):
    topology = compiled.bundle.topology
    for source in range(28):
        for destination in range(28):
            path = tree4_witness_path(topology, source, destination)
            assert path[0] == source and path[-1] == destination
            edges = {(c.src_router, c.dst_router)
                     for c in topology.channels}
            for hop in zip(path, path[1:]):
                assert hop in edges


def test_deadlock_expansion_is_destination_indexed_and_acyclic(compiled):
    from veritx_dse.verification.channel_vc_cdg import (
        TREE4_DESTINATION_EXPANSION, certify_channel_vc_deadlock,
    )
    bundle = compiled.bundle
    certificate = certify_channel_vc_deadlock(
        topology=bundle.topology, resolved_route=bundle.resolved_route,
        router_route=bundle.router_route, vc_assignment=bundle.vc_assignment)
    assert certificate.verdict == "PASS", certificate.evidence
    assert certificate.evidence["expansion"] == TREE4_DESTINATION_EXPANSION
    assert certificate.evidence["node_count"] == 128
    assert certificate.evidence["edge_count"] > 0


def test_native_projection_never_falls_back_to_anynet(compiled):
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    assert prepared.profile_id == PROFILE_ID
    assert prepared.lowerer_version == "TREE4NCA/1"
    assert "topology = tree4;" in prepared.config_text
    assert "routing_function = nca;" in prepared.config_text
    assert f"routing_dump_choice_probes = {CHOICE_PROBES};" in \
        prepared.config_text
    assert "native_route_observation_file" in prepared.config_text
    # A single-row table cannot describe this fabric.
    assert prepared.expected_route_rows == ()
    assert prepared.expected_route_ports == ()


def test_the_balanced_tree4_preset_never_reaches_this_profile():
    """The structured `tree4` preset keeps AnyNet; the native class is not
    reachable from it, and the native profile is not reachable from it."""
    from veritx_dse.application.presets import build_typed_preset_request
    from veritx_dse.backend.booksim_projection import select_booksim_profile
    structured = FabricCompiler().compile(
        build_typed_preset_request("tree4_7")).bundle
    assert structured.topology.family is not MaterializedFamily.TREE4_NATIVE
    assert select_booksim_profile(_parents_from_bundle(
        structured, build_typed_preset_request("tree4_7"))).profile_id \
        != PROFILE_ID


def test_changed_geometry_and_attachment_fail_qualification(compiled):
    parents = _parents_from_bundle(compiled.bundle, request())
    qualify(parents)
    # The geometry gate compares against the pinned construction, so a
    # different construction must be a different artifact. (A parents with a
    # swapped topology is refused earlier, by its own hash binding.)
    other = materialize_tree4(Tree4Intent(4, 3), width_bits=128)
    assert other.canonical_dict() != materialize_tree4(
        Tree4Intent(4, 3)).canonical_dict()
    endpoints = parents.attachment.endpoints
    # Two terminals on the SAME leaf: swapping their seats keeps the seat set
    # unique, so only the terminal law can catch it.
    first, second = endpoints[0], endpoints[1]
    assert first.router_id == second.router_id
    swapped = replace(
        parents.attachment,
        endpoints=(replace(first, port_id=second.port_id),
                   replace(second, port_id=first.port_id))
        + tuple(endpoints[2:]))
    with pytest.raises(BookSimProjectionError, match="seat law|attachment"):
        qualify(replace(parents, attachment=swapped))


def test_unsupported_geometry_is_refused_before_materialization():
    for radix, levels in ((2, 3), (4, 2), (3, 4)):
        with pytest.raises(TopologyIntentError):
            Tree4Intent(radix, levels)


def test_union_dump_matches_every_hop_and_port(compiled, tmp_path):
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("native differential needs built BookSim")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    for name, data in prepared.files().items():
        (tmp_path / name).write_bytes(data)
    process = subprocess.run([str(binary), "config.cfg"], cwd=tmp_path,
                             capture_output=True, text=True, timeout=300)
    assert process.returncode == 0, process.stderr
    union = parse_route_dump_union_rows((tmp_path / "routing.dump").read_text())
    topology = model_topology()
    summary = verify_union_table(union=union, topology=topology)
    assert summary["pairs"] == 28 * 64
    assert summary["deterministic_pairs"] == 192
    assert summary["choice_pairs"] == 1600
    rows, ports, choices = expected_rows(topology)
    assert len(rows) == 192 and len(choices) == 1600
    runtime = (tmp_path / OBSERVATION_FILE).read_text()
    executed = verify_runtime(runtime, topology=topology, vc_count=1)
    assert executed["rows"] > 0 and executed["flits"] > 0
    assert executed["ejections"] == executed["flits"]
    assert executed["vc_range"] == [0, 0]


def test_deterministic_parser_refuses_the_union_dialect(tmp_path):
    from veritx_dse.backend.route_observation import parse_route_dump_rows
    text = ("# VeritX routing realization dump (legal first-hop choice "
            "union v2)\nsrc_router 0 dst_node 0 choice 0 next_router 4 "
            "port 0\n")
    with pytest.raises(RouteObservationError):
        parse_route_dump_rows(text)


def test_authenticated_product_execution_and_preset(tmp_path):
    from veritx_dse.application.product_evaluator import evaluate_product
    preset = build_typed_preset_request("tree4_native64")
    assert preset.design_hash() == request().design_hash()
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("authenticated native execution requires built BookSim")
    result = evaluate_product(preset, binary=binary, network_clock_hz=10**9,
                              timeout_s=600, run_dir=tmp_path, repo_root=REPO,
                              seed=0)
    assert result.status == "EVALUATED", result.reason
    assert result.outcome.evidence_id and result.outcome.realization_digest
    assert (result.outcome.metrics["flits_injected"]
            == result.outcome.metrics["flits_accepted"] > 0)
    evidence = json.loads(next(
        tmp_path.rglob("evidence/backend-evidence.json")).read_text())
    assert evidence["route_observation"] == "EXECUTED_ROUTE_OBSERVED"
    assert evidence["route_dump_sha256"]
    union = evidence["stats"]["tree4_route_union"]
    assert union["pairs"] == 28 * 64
    assert union["choice_pairs"] == 1600
    assert union["choice_probes"] == CHOICE_PROBES
    executed = evidence["stats"]["tree4_route_computations"]
    assert executed["rows"] > 0 and executed["flits"] > 0
    assert executed["terminals"] == 64


def test_fabricated_single_row_obligations_refuse_before_execution(compiled,
                                                                    tmp_path):
    from veritx_dse.backend.booksim_execution import (
        BookSimExecutionError, execute_prepared_booksim,
    )
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle,
                                                          request()))
    rows, ports, _choices = expected_rows(model_topology())
    with pytest.raises(BookSimExecutionError, match="single-row"):
        execute_prepared_booksim(
            prepared=replace(prepared, expected_route_ports=ports),
            binary=REPO / "third_party/booksim2/src/booksim",
            run_dir=tmp_path, repo_root=REPO, timeout=300)
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
        # A middle router has ports 0..3 (its four leaves) and 4..7 (the four
        # roots); toward a terminal outside its group port 0 is DOWN, while
        # the index is the small value the tamper writes. Rewriting router 4's
        # upward port 4 to the traffic-manager-facing down port 0 must be
        # refused: the law offers only 4..7 there.
        lines = text.splitlines(keepends=True)
        for index, line in enumerate(lines):
            fields = line.split()
            if (len(fields) == 10 and fields[1] == "4"
                    and fields[3] == "63" and fields[4] == "choice"):
                # tokens: src_router R dst_node D choice C next_router N
                # port P. Router 4 is a middle whose group contains terminal
                # 63's group only via port 0; its upward faces are 4..7.
                assert int(fields[9]) in (4, 5, 6, 7)
                fields[9] = "0"
                lines[index] = " ".join(fields) + "\n"
                break
        else:
            raise AssertionError("the tamper target row is missing")
        dump.write_text("".join(lines))
        return outcome

    monkeypatch.setattr(execution, "_supervised_runner", corrupt)
    with pytest.raises(execution.BookSimExecutionError, match="does not permit"):
        execution.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path,
            repo_root=REPO, timeout=300)


def _canonical(topology, native_router):
    """BookSim's internal router id back to the canonical dense index."""
    for router in range(len(topology.routers)):
        if tree4_native_router_id(topology, router) == native_router:
            return router
    raise AssertionError(f"{native_router} is not a native Tree4 router id")


def _native_faces(topology, router, terminal):
    """The law's legal hops in the DUMP's dialect (native next ids)."""
    faces = []
    for following, port in legal_hops(topology, router, terminal):
        faces.append(((router if following is None else
                       tree4_native_router_id(topology, following)), port))
    return frozenset(faces)


def test_non_determinism_outside_the_declared_choice_is_rejected():
    from veritx_dse.backend.booksim_execution import BookSimExecutionError
    topology = model_topology()
    union = {}
    for router in range(28):
        for terminal in range(64):
            union[(router, terminal)] = _native_faces(topology, router,
                                                      terminal)
    # Router 4 toward terminal 0 is a middle inside the destination group, so
    # the law makes it deterministic (down port 0): an empty realization
    # there means the producer never showed the hop the law requires, which
    # is exactly the drift the exactness gate exists for.
    union[(4, 0)] = frozenset()
    with pytest.raises(BookSimExecutionError, match="deterministic"):
        verify_union_table(union=union, topology=topology)


def test_incomplete_union_is_rejected():
    from veritx_dse.backend.booksim_execution import BookSimExecutionError
    topology = model_topology()
    with pytest.raises(BookSimExecutionError, match="incomplete"):
        verify_union_table(
            union={(0, 0): _native_faces(topology, 0, 0)},
            topology=topology)


def test_unreached_legal_face_is_rejected():
    from veritx_dse.backend.booksim_execution import BookSimExecutionError
    topology = model_topology()
    union = {}
    for router in range(28):
        for terminal in range(64):
            union[(router, terminal)] = frozenset(
                [sorted(_native_faces(topology, router, terminal))[0]])
    # Every pair keeps one legal face, so the union is sound; but the model
    # claims faces the producer never showed, which must be refused.
    with pytest.raises(BookSimExecutionError, match="never realised"):
        verify_union_table(union=union, topology=topology)


def test_corrupted_runtime_hop_is_rejected(compiled, tmp_path, monkeypatch):
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
        # Rewrite the FIRST executed hop of a flit to a port the law does not
        # offer at that router toward that destination. The runtime dump is
        # the only place the executed choice is recorded, so a fabricated hop
        # must never be accepted as evidence.
        fields = lines[1].split()
        router = int(fields[3])
        destination = int(fields[2])
        legal = {port for _next, port in legal_hops(
            model_topology(), _canonical(model_topology(), router), destination)}
        fields[6] = str(next(port for port in range(8) if port not in legal))
        lines[1] = " ".join(fields)
        path.write_text("\n".join(lines) + "\n")
        return outcome

    monkeypatch.setattr(execution, "_supervised_runner", corrupt)
    with pytest.raises(execution.BookSimExecutionError):
        execution.execute_prepared_booksim(
            prepared=prepared, binary=binary, run_dir=tmp_path,
            repo_root=REPO, timeout=300)


def test_pinned_geometry_is_enforced():
    from veritx_dse.backend.booksim_execution import BookSimExecutionError
    pinned_geometry({"k": 4, "n": 3})
    with pytest.raises(BookSimExecutionError, match="certified"):
        pinned_geometry({"k": 8, "n": 3})
