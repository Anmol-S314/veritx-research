"""Exact indirect QTree: native terminal law, NCA differential and identity preservation."""
from dataclasses import replace
from pathlib import Path
import subprocess
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from veritx_dse.application.presets import _typed_request, build_typed_preset_request
from veritx_dse.application.fabric_compiler import FabricCompiler
from veritx_dse.application.capability_truth import _parents_from_bundle
from veritx_dse.backend.booksim_projection import prepare_booksim_input, parse_config_values, BookSimProjectionError
from veritx_dse.backend.qtree_projection import PROFILE_ID, qualify
from veritx_dse.backend.route_observation import compare_route_realization, parse_route_dump_rows
from veritx_dse.core.paths import REPO
from veritx_dse.model.indirect_tree import materialize_qtree, qtree_terminal_location
from veritx_dse.model.topology_artifact import TopologyArtifact
from veritx_dse.model.topology_intent import QTreeIntent, TopologyIntentError, topology_intent_from_dict


def request():
    return _typed_request(QTreeIntent(4, 3), endpoints=64, tp=64)


@pytest.fixture(scope="module")
def compiled():
    result = FabricCompiler().compile(request())
    assert result.status == "COMPILED", result.error
    assert result.certificate.overall == "PASS"
    return result


def test_geometry_and_complete_leaf_attachment(compiled):
    topology = compiled.bundle.topology
    assert len(topology.routers) == 21
    assert len(topology.channels) == 40
    assert [r.seat_capacity for r in topology.routers] == [0]*5 + [4]*16
    assert topology.seat_capacity == 64
    from veritx_dse.core.route_artifact import QTREE_NCA_DEFINITION
    assert compiled.bundle.router_route.routing_classes == (QTREE_NCA_DEFINITION,)
    assert TopologyArtifact.from_dict(topology.to_dict()) == topology
    for endpoint in compiled.bundle.attachment.endpoints:
        assert (endpoint.router_id, endpoint.port_id) == qtree_terminal_location(endpoint.endpoint_id)


def test_declared_identity_is_not_the_legacy_balanced_tree():
    intent = QTreeIntent(4, 3)
    assert topology_intent_from_dict(intent.to_dict()) == intent
    legacy = build_typed_preset_request("qtree7")
    assert legacy.design_hash() == "2c813e13d552ee3a456340f1ae6a4d4e6e740b6a80c9c52da5dd7b98ef8fffe3"
    assert request().design_hash() != legacy.design_hash()


@pytest.mark.parametrize("doc", [
    {"kind": "qtree_native", "radix": True, "levels": 3},
    {"kind": "qtree_native", "radix": 2, "levels": 3},
    {"kind": "qtree_native", "radix": 4, "levels": 4},
    {"kind": "qtree_native", "radix": 4, "levels": 3, "vc_count": 4},
])
def test_wrong_shapes_and_locked_routing_fields_refuse(doc):
    with pytest.raises(TopologyIntentError):
        topology_intent_from_dict(doc)


def test_native_projection_never_falls_back_to_anynet(compiled):
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle, request()))
    values = parse_config_values(prepared.config_text)
    assert prepared.profile_id == PROFILE_ID
    assert values["topology"] == "qtree" and values["routing_function"] == "nca"
    assert (values["k"], values["n"], values["num_vcs"]) == ("4", "3", "1")
    assert prepared.topology_text is None
    assert len(prepared.expected_route_rows) == len(prepared.expected_route_ports) == 21*64


def test_changed_geometry_and_terminal_placement_fail_qualification(compiled):
    parents = _parents_from_bundle(compiled.bundle, request())
    channel = replace(parents.topology.channels[0], latency_cycles=2)
    changed = replace(parents.topology, channels=(channel,) + parents.topology.channels[1:])
    with pytest.raises(BookSimProjectionError, match="topology|geometry"):
        qualify(replace(parents, topology=changed))
    endpoints = list(parents.attachment.endpoints)
    # Swap complete terminal records' seats: legal hardware, wrong native ABI.
    a, b = endpoints[0], endpoints[4]
    endpoints[0] = replace(a, router_id=b.router_id, port_id=b.port_id)
    endpoints[4] = replace(b, router_id=a.router_id, port_id=a.port_id)
    attachment = replace(parents.attachment, endpoints=tuple(endpoints))
    with pytest.raises(BookSimProjectionError, match="attachment"):
        qualify(replace(parents, attachment=attachment))


def test_native_nca_matches_all_router_terminal_hops_and_ports(compiled, tmp_path):
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("native differential needs built BookSim")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle, request()))
    for name, data in prepared.files().items():
        (tmp_path / name).write_bytes(data)
    process = subprocess.run([str(binary), "config.cfg"], cwd=tmp_path,
        capture_output=True, text=True, timeout=60)
    assert process.returncode == 0, process.stderr
    dump = (tmp_path / "routing.dump").read_text()
    observed = parse_route_dump_rows(dump)
    result = compare_route_realization(expected_rows=prepared.expected_route_rows, dump_text=dump)
    assert result.pairs_compared == 1344
    assert all(observed[src, dest].port == port for src, dest, port in prepared.expected_route_ports)


def test_authenticated_product_execution_and_preset(compiled, tmp_path):
    from veritx_dse.application.product_evaluator import evaluate_product
    preset = build_typed_preset_request("qtree_native64")
    assert preset.design_hash() == request().design_hash()
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("authenticated native execution requires built BookSim")
    result = evaluate_product(preset, binary=binary, network_clock_hz=10**9,
        timeout_s=60, run_dir=tmp_path, repo_root=REPO, seed=0)
    assert result.status == "EVALUATED", result.reason
    assert result.outcome.evidence_id and result.outcome.realization_digest
    assert result.outcome.metrics["flits_injected"] == result.outcome.metrics["flits_accepted"] > 0
    from veritx_dse.product.service import ProductService, ProductConfig
    from test_product_federation import _wait_job
    service = ProductService(ProductConfig(projects_root=tmp_path / 'projects',
        booksim_bin=binary, network_clock_hz=10**9, timeout_s=60))
    try:
        project = service.create_project_from_preset('qtree_native64')
        revision = service.compile_draft(project['project']['project_id'])
        assert revision['compilation']['status'] == 'COMPILED'
        submitted = service.submit_evaluation(revision['revision_id'])
        job = _wait_job(service, submitted['job_id'], timeout_s=60)
        assert job['state'] == 'COMPLETED', job
        run = service.get_run(job['result']['run_id'])
        assert run['analyses'][0]['status'] == 'EVALUATED', run['analyses']
    finally:
        service.jobs.shutdown()


def test_stripping_port_obligations_refuses_before_execution(compiled, tmp_path):
    from veritx_dse.backend.booksim_execution import execute_prepared_booksim, BookSimExecutionError
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle, request()))
    with pytest.raises(BookSimExecutionError, match="complete hop AND port"):
        execute_prepared_booksim(prepared=replace(prepared, expected_route_ports=()),
            binary=REPO / "third_party/booksim2/src/booksim", run_dir=tmp_path,
            repo_root=REPO, timeout=60)
    assert not list(tmp_path.iterdir())


def test_wrong_local_ejection_port_is_rejected_even_when_hop_and_delivery_match(compiled, tmp_path, monkeypatch):
    from veritx_dse.backend import booksim_execution as execution
    binary = REPO / "third_party/booksim2/src/booksim"
    if not binary.is_file():
        pytest.skip("requires actual BookSim output to tamper")
    prepared = prepare_booksim_input(_parents_from_bundle(compiled.bundle, request()))
    supervised = execution._supervised_runner

    def corrupt_observation(command, directory, timeout):
        outcome = supervised(command, directory, timeout)
        dump = directory / "routing.dump"
        text = dump.read_text()
        correct = "src_router 5 dst_node 0 next_router 5 port 0"
        assert correct in text
        dump.write_text(text.replace(correct, "src_router 5 dst_node 0 next_router 5 port 1", 1))
        return outcome

    monkeypatch.setattr(execution, "_supervised_runner", corrupt_observation)
    with pytest.raises(execution.BookSimExecutionError, match="executed route port differs"):
        execution.execute_prepared_booksim(prepared=prepared, binary=binary,
            run_dir=tmp_path, repo_root=REPO, timeout=60)
