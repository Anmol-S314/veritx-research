"""Independent verification suite for the deployment-intent mapping.

Every assertion is derived from
``docs/design/reviews/deployment-intent-mapping.md``. The author's tests live
in ``tests/test_deployment_intent.py`` and are deliberately not imported or
reused here.

The suite is adversarial in three places: collective groups are expanded with
the repository's sealed rank algebra *and* the real workload lowerer (rather
than trusting the mapping's own numbers), refusals must be typed and must not
silently adjust the deployment, and ``status``/``workload`` must agree.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import pytest

DSE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(DSE))

from veritx_dse.application.deployment_intent import (  # noqa: E402
    SCHEMA,
    DeploymentMapping,
    map_deployment,
)
from veritx_dse.application.fabric_compiler import FabricCompiler  # noqa: E402
from veritx_dse.model.parallelism import ParallelismArtifact  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402
from veritx_dse.workload.intent_lowering import (  # noqa: E402
    lower_compile_workload,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "deployment_intent"
MODELS = FIXTURES / "models"
CLUSTERS = FIXTURES / "clusters"
REFUSALS = CLUSTERS / "refusals"
TRACES = FIXTURES / "traces"
INVALID = FIXTURES / "invalid"

QWEN_MODEL = MODELS / "qwen3-30b-a3b.json"
LLAMA_MODEL = MODELS / "llama-3.1-8b.json"
THREE_EXPERT_MODEL = MODELS / "moe_three_experts.json"
PARAMETER_MODEL = MODELS / "moe_with_parameters.json"
INCOMPLETE_MODEL = MODELS / "incomplete.json"
DENSE_MAXPOS_MODEL = MODELS / "dense_max_position_1024.json"
NONDIVISIBLE_HEAD_DIM_MODEL = MODELS / "nondivisible_hidden_no_head_dim.json"
TOPK_EXCEEDS_MODEL = MODELS / "moe_topk_exceeds_experts.json"
FRACTIONAL_PARAMETER_MODEL = MODELS / "moe_fractional_parameters.json"

QWEN = "Qwen/Qwen3-30B-A3B-Instruct-2507"
LLAMA = "meta-llama/Llama-3.1-8B"

TINY_4 = TRACES / "tiny_4.jsonl"
TINY_6 = TRACES / "tiny_6.jsonl"
TEN_ROWS = TRACES / "ten_rows.jsonl"
EMPTY_TRACE = TRACES / "empty.jsonl"

MESH_2 = {"kind": "mesh", "side_length": 2, "concentration": 1}

_TIMESTAMP_KEY_TOKENS = (
    "timestamp", "created_at", "generated_at", "updated_at", "recorded_at")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inst(model_name: str, **overrides: Any) -> dict[str, Any]:
    instance = {
        "model_name": model_name,
        "hardware": "RTXPRO6000",
        "pd_type": None,
    }
    instance.update(overrides)
    return instance


def _write_cluster(tmp_path: Path,
                   instances: list[dict[str, Any]],
                   name: str = "cluster.json") -> Path:
    document = {
        "num_nodes": 1,
        "nodes": [{
            "num_instances": len(instances),
            "instances": instances,
        }],
    }
    path = tmp_path / name
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def _write_trace(tmp_path: Path, rows: list[dict[str, Any]],
                 name: str = "trace.jsonl") -> Path:
    path = tmp_path / name
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def _map(
    cluster: Path,
    *,
    model: Path = QWEN_MODEL,
    trace: Path = TINY_4,
    **kwargs: Any,
) -> DeploymentMapping:
    return map_deployment(
        cluster_config=cluster,
        model_config=model,
        trace=trace,
        **kwargs,
    )


def _request(mapping: DeploymentMapping) -> dict[str, Any]:
    return mapping.to_request(topology=dict(MESH_2))


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _walk_keys(value: Any) -> list[str]:
    if isinstance(value, dict):
        keys: list[str] = []
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(child))
        return keys
    if isinstance(value, (list, tuple)):
        keys = []
        for child in value:
            keys.extend(_walk_keys(child))
        return keys
    return []


def _walk_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in _walk_strings(child)]
    if isinstance(value, (list, tuple)):
        return [text for child in value for text in _walk_strings(child)]
    return []


def _assert_source_hashes(mapping: DeploymentMapping, cluster: Path,
                          model: Path, trace: Path) -> None:
    for name, path in (("cluster", cluster), ("model", model),
                       ("trace", trace)):
        source = mapping.report["sources"][name]
        assert source["path"] == str(path)
        assert source["sha256"] == hashlib.sha256(
            path.read_bytes()).hexdigest()


def _assert_refused(mapping: DeploymentMapping, code: str) -> DeploymentMapping:
    assert mapping.status == "REFUSED"
    assert mapping.workload is None
    assert mapping.report["status"] == "REFUSED"
    assert [issue["code"] for issue in mapping.report["issues"]] == [code]
    assert mapping.report["issues"][0]["message"]
    assert mapping.agents == ()
    assert mapping.requirements == ()
    assert mapping.compute == {"stages": []}
    return mapping


def _assert_collective_groups(mapping: DeploymentMapping,
                              expected_ranks: int) -> None:
    """Expand every collective twice: sealed rank algebra and real lowerer."""
    parsed = parse_request_doc(_request(mapping))
    workload = parsed.workload
    artifact = ParallelismArtifact(
        tp=workload.tp, pp=workload.pp, ep=workload.ep, dp=workload.dp)
    assert artifact.world_size == expected_ranks

    expected_lowered_operations = 0
    for intent in workload.collectives:
        dimension = intent.dimension.value
        if dimension == "GLOBAL":
            groups: tuple[tuple[int, ...], ...] = (
                tuple(range(expected_ranks)),)
        else:
            groups = tuple(
                group.members for group in artifact.groups(dimension))
        assert groups, f"collective dimension {dimension} expanded to no group"
        for members in groups:
            assert len(members) >= 2, (
                f"{dimension} group {members!r} has fewer than two members")
            assert len(set(members)) == len(members)
            assert all(0 <= rank < expected_ranks for rank in members)
        expected_lowered_operations += len(groups)

    lowered = lower_compile_workload(parsed)
    operations = lowered.graph.of_kind("COLLECTIVE")
    assert len(operations) == expected_lowered_operations
    for operation in operations:
        members = operation.detail["participants"]
        assert isinstance(members, tuple)
        assert len(members) >= 2, operation.operation_id
        assert len(set(members)) == len(members)
        assert all(0 <= rank < expected_ranks for rank in members)
        payload = operation.detail["payload_bytes"]
        assert type(payload) is int and payload > 0
    assert lowered.graph.participant_count == expected_ranks


# ---------------------------------------------------------------------------
# 1. Golden compiles
# ---------------------------------------------------------------------------

def test_golden_qwen3_moe_tp2_ep2_compiles() -> None:
    cluster = CLUSTERS / "qwen_tp2_ep2.json"
    mapping = _map(cluster)

    assert mapping.status == "OK"
    assert mapping.report["schema"] == SCHEMA
    assert mapping.report["status"] == "OK"
    assert mapping.report["issues"] == []
    assert mapping.report["deployment"] == {
        "model_name": QWEN,
        "hardware": "RTXPRO6000",
        "pd_type": None,
        "tp": 2,
        "dp": 1,
        "ep": 2,
        "pp": 1,
        "instances": 1,
        "ranks": 2,
    }
    assert mapping.report["model"] == {
        "layers": 48,
        "hidden": 2048,
        "heads": 32,
        "kv_heads": 4,
        "head_dim": 128,
        "attention": "gqa",
        "kv_bytes_per_token_per_layer": 2 * 4 * 128 * 2,
        "experts": 128,
        "top_k": 8,
        "dtype_bytes": 2,
        "weights_bytes": None,
    }
    assert mapping.report["request"] == {
        "num_reqs": 4,
        "isl_mean": 13.0,
        "osl_mean": 72.0,
        "arrival_span_ns": 5000000,
    }
    assert mapping.report["derived"] == {
        "prefill_chunk_tokens": 2048,
        "decode_batch": 4,
        "tp_prefill_bytes": 8388608,
        "tp_decode_bytes": 16384,
        "ep_dispatch_bytes": 4456448,
        "ep_combine_bytes": 8388608,
        "ep_decode_bytes": 8704,
        "kv_bytes_per_token": 98304,
    }
    _assert_source_hashes(mapping, cluster, QWEN_MODEL, TINY_4)

    assert [
        (collective["kind"], collective["dimension"],
         collective["traffic_class"], collective["payload_bytes"])
        for collective in mapping.workload["collectives"]
    ] == [
        ("allreduce", "TP", "tp_collective", 8388608),
        ("allgather", "TP", "ep_dispatch", 4456448),
        ("reducescatter", "TP", "ep_combine", 8388608),
    ]

    parsed = parse_request_doc(_request(mapping))
    assert parsed.workload.model_name == QWEN
    assert parsed.workload.model_family.value == "mixture_of_experts"
    assert (parsed.workload.tp, parsed.workload.dp, parsed.workload.ep,
            parsed.workload.pp) == (2, 1, 1, 1)
    assert [collective.kind.value for collective in
            parsed.workload.collectives] == [
        "allreduce", "allgather", "reducescatter"]
    assert [collective.traffic_class for collective in
            parsed.workload.collectives] == [
        "tp_collective", "ep_dispatch", "ep_combine"]
    assert [collective.payload_bytes for collective in
            parsed.workload.collectives] == [
        8388608, 4456448, 8388608]

    compilation = FabricCompiler().compile(parsed)
    assert compilation.status == "COMPILED", compilation.error
    assert compilation.error is None
    assert compilation.bundle is not None


def test_design_report_example_numbers_for_ten_requests() -> None:
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json", trace=TEN_ROWS)

    assert mapping.status == "OK"
    assert mapping.report["request"] == {
        "num_reqs": 10,
        "isl_mean": 12.0,
        "osl_mean": 69.0,
        "arrival_span_ns": 1234567,
    }
    assert mapping.report["derived"] == {
        "prefill_chunk_tokens": 2048,
        "decode_batch": 10,
        "tp_prefill_bytes": 8388608,
        "tp_decode_bytes": 40960,
        "ep_dispatch_bytes": 4456448,
        "ep_combine_bytes": 8388608,
        "ep_decode_bytes": 21760,
        "kv_bytes_per_token": 98304,
    }


def test_golden_qwen3_moe_tp2_with_omitted_ep_size_compiles() -> None:
    cluster = CLUSTERS / "qwen_tp2_ep_omitted.json"
    mapping = _map(cluster)

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["ep"] == 2
    assert mapping.report["deployment"]["ranks"] == 2
    assert [collective["traffic_class"] for collective in
            mapping.workload["collectives"]] == [
        "tp_collective", "ep_dispatch", "ep_combine"]
    assert [collective["payload_bytes"] for collective in
            mapping.workload["collectives"]] == [
        8388608, 4456448, 8388608]

    parsed = parse_request_doc(_request(mapping))
    compilation = FabricCompiler().compile(parsed)
    assert compilation.status == "COMPILED", compilation.error


def test_golden_llama31_dense_tp4_compiles_with_only_tp_allreduce() -> None:
    cluster = CLUSTERS / "llama_tp4.json"
    mapping = _map(cluster, model=LLAMA_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["deployment"] == {
        "model_name": LLAMA,
        "hardware": "RTXPRO6000",
        "pd_type": None,
        "tp": 4,
        "dp": 1,
        "ep": 1,
        "pp": 1,
        "instances": 1,
        "ranks": 4,
    }
    assert mapping.report["model"] == {
        "layers": 32,
        "hidden": 4096,
        "heads": 32,
        "kv_heads": 8,
        "head_dim": 128,
        "attention": "gqa",
        "kv_bytes_per_token_per_layer": 2 * 8 * 128 * 2,
        "experts": None,
        "top_k": None,
        "dtype_bytes": 2,
        "weights_bytes": None,
    }
    assert mapping.report["derived"] == {
        "prefill_chunk_tokens": 2048,
        "decode_batch": 4,
        "tp_prefill_bytes": 16777216,
        "tp_decode_bytes": 32768,
        "ep_dispatch_bytes": 0,
        "ep_combine_bytes": 0,
        "ep_decode_bytes": 0,
        "kv_bytes_per_token": 131072,
    }
    assert [
        (collective["kind"], collective["dimension"],
         collective["traffic_class"], collective["payload_bytes"])
        for collective in mapping.workload["collectives"]
    ] == [("allreduce", "TP", "tp_collective", 16777216)]

    parsed = parse_request_doc(_request(mapping))
    assert parsed.workload.model_family.value == "dense_transformer"
    assert len(parsed.workload.collectives) == 1
    assert parsed.workload.collectives[0].kind.value == "allreduce"
    assert parsed.workload.collectives[0].dimension.value == "TP"
    assert parsed.workload.collectives[0].traffic_class == "tp_collective"

    compilation = FabricCompiler().compile(parsed)
    assert compilation.status == "COMPILED", compilation.error


def test_golden_dp2_tp2_dense_compiles_with_two_member_tp_groups() -> None:
    cluster = CLUSTERS / "llama_dp2_tp2.json"
    mapping = _map(cluster, model=LLAMA_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["dp"] == 2
    assert mapping.report["deployment"]["tp"] == 2
    assert mapping.report["deployment"]["ranks"] == 4
    assert mapping.report["deployment"]["instances"] == 2
    assert mapping.workload["dp"] == 2
    assert mapping.report["derived"]["decode_batch"] == 4
    assert mapping.report["derived"]["tp_decode_bytes"] == 4 * 4096 * 2
    assert [collective["traffic_class"] for collective in
            mapping.workload["collectives"]] == ["tp_collective"]

    parsed = parse_request_doc(_request(mapping))
    artifact = ParallelismArtifact(tp=2, pp=1, ep=1, dp=2)
    groups = artifact.groups("TP")
    assert len(groups) == 2
    assert all(len(group.members) == 2 for group in groups)

    lowered = lower_compile_workload(parsed)
    operations = lowered.graph.of_kind("COLLECTIVE")
    assert len(operations) == 2
    assert all(len(operation.detail["participants"]) == 2
               for operation in operations)

    compilation = FabricCompiler().compile(parsed)
    assert compilation.status == "COMPILED", compilation.error


# ---------------------------------------------------------------------------
# 2. Rank/group invariants over a matrix of valid deployments
# ---------------------------------------------------------------------------

MATRIX_CASES = [
    pytest.param(
        QWEN_MODEL, [_inst(QWEN, tp_size=2, ep_size=2)],
        2, 1, 2, 2, "mixture_of_experts",
        ("tp_collective", "ep_dispatch", "ep_combine"),
        id="qwen-tp2-ep2-dp1"),
    pytest.param(
        QWEN_MODEL, [_inst(QWEN, tp_size=2)],
        2, 1, 2, 2, "mixture_of_experts",
        ("tp_collective", "ep_dispatch", "ep_combine"),
        id="qwen-tp2-ep-omitted-dp1"),
    pytest.param(
        QWEN_MODEL, [_inst(QWEN, tp_size=4, ep_size=4)],
        4, 1, 4, 4, "mixture_of_experts",
        ("tp_collective", "ep_dispatch", "ep_combine"),
        id="qwen-tp4-ep4-dp1"),
    pytest.param(
        QWEN_MODEL, [_inst(QWEN, tp_size=4, ep_size=1)],
        4, 1, 1, 4, "mixture_of_experts",
        ("tp_collective",),
        id="qwen-tp4-ep1-dp1"),
    pytest.param(
        QWEN_MODEL, [_inst(QWEN, tp_size=4)],
        4, 1, 4, 4, "mixture_of_experts",
        ("tp_collective", "ep_dispatch", "ep_combine"),
        id="qwen-tp4-ep-omitted-dp1"),
    pytest.param(
        QWEN_MODEL, [
            _inst(QWEN, tp_size=2, ep_size=1, dp_group="A"),
            _inst(QWEN, tp_size=2, ep_size=1, dp_group="A"),
        ],
        2, 2, 1, 4, "mixture_of_experts",
        ("tp_collective",),
        id="qwen-tp2-ep1-dp2"),
    pytest.param(
        QWEN_MODEL, [_inst(QWEN, num_npus=2)],
        2, 1, 2, 2, "mixture_of_experts",
        ("tp_collective", "ep_dispatch", "ep_combine"),
        id="qwen-tp-from-num-npus"),
    pytest.param(
        LLAMA_MODEL, [_inst(LLAMA, tp_size=2)],
        2, 1, 1, 2, "dense_transformer",
        ("tp_collective",),
        id="llama-tp2-dp1"),
    pytest.param(
        LLAMA_MODEL, [_inst(LLAMA, tp_size=4)],
        4, 1, 1, 4, "dense_transformer",
        ("tp_collective",),
        id="llama-tp4-dp1"),
    pytest.param(
        LLAMA_MODEL, [_inst(LLAMA, tp_size=8)],
        8, 1, 1, 8, "dense_transformer",
        ("tp_collective",),
        id="llama-tp8-dp1"),
    pytest.param(
        LLAMA_MODEL, [
            _inst(LLAMA, tp_size=2, dp_group="A"),
            _inst(LLAMA, tp_size=2, dp_group="A"),
        ],
        2, 2, 1, 4, "dense_transformer",
        ("tp_collective",),
        id="llama-tp2-dp2"),
    pytest.param(
        LLAMA_MODEL, [
            _inst(LLAMA, tp_size=2, dp_group="A"),
            _inst(LLAMA, tp_size=2, dp_group="A"),
            _inst(LLAMA, tp_size=2, dp_group="A"),
        ],
        2, 3, 1, 6, "dense_transformer",
        ("tp_collective",),
        id="llama-tp2-dp3"),
]


@pytest.mark.parametrize(
    "model,instances,expected_tp,expected_dp,expected_ep,expected_ranks,"
    "expected_family,expected_classes",
    MATRIX_CASES)
def test_rank_and_group_invariants_over_valid_matrix(
        tmp_path: Path,
        model: Path,
        instances: list[dict[str, Any]],
        expected_tp: int,
        expected_dp: int,
        expected_ep: int,
        expected_ranks: int,
        expected_family: str,
        expected_classes: tuple[str, ...],
) -> None:
    cluster = _write_cluster(tmp_path, instances)
    mapping = _map(cluster, model=model)

    assert mapping.status == "OK"
    assert mapping.workload is not None
    assert mapping.report["status"] == "OK"
    assert mapping.report["issues"] == []

    deployment = mapping.report["deployment"]
    assert deployment["tp"] == expected_tp
    assert deployment["dp"] == expected_dp
    assert deployment["ep"] == expected_ep
    assert deployment["pp"] == 1
    assert deployment["instances"] == len(instances)
    assert deployment["ranks"] == expected_tp * expected_dp * deployment["pp"]
    assert deployment["ranks"] == expected_ranks
    assert deployment["model_name"] == instances[0]["model_name"]

    workload = mapping.workload
    assert workload["model_name"] == instances[0]["model_name"]
    assert workload["model_family"] == expected_family
    assert (workload["tp"], workload["dp"], workload["ep"],
            workload["pp"]) == (expected_tp, expected_dp, 1, 1)

    model = mapping.report["model"]
    derived = mapping.report["derived"]
    prefill = derived["prefill_chunk_tokens"]
    decode = derived["decode_batch"]
    assert prefill == 2048
    assert decode == 4
    hidden = model["hidden"]
    dtype = model["dtype_bytes"]
    experts = model["experts"]
    has_ep = (experts is not None
              and expected_ep == expected_tp and expected_tp > 1)

    if has_ep:
        expected_ep_decode = (
            max(1, decode // expected_ep) * (hidden + experts) * dtype)
    else:
        expected_ep_decode = 0
    assert derived["ep_decode_bytes"] == expected_ep_decode

    expected_kind = {
        "tp_collective": "allreduce",
        "ep_dispatch": "allgather",
        "ep_combine": "reducescatter",
    }
    expected_payload = {
        "tp_collective": prefill * hidden * dtype,
    }
    if has_ep:
        expected_payload["ep_dispatch"] = (
            max(1, prefill // expected_ep) * (hidden + experts) * dtype)
        expected_payload["ep_combine"] = prefill * hidden * dtype

    collectives = workload["collectives"]
    assert collectives
    assert tuple(collective["traffic_class"]
                 for collective in collectives) == expected_classes
    for collective in collectives:
        traffic_class = collective["traffic_class"]
        assert collective["kind"] == expected_kind[traffic_class]
        assert collective["dimension"] == "TP"
        assert collective["payload_bytes"] == expected_payload[traffic_class]
        payload = collective["payload_bytes"]
        assert type(payload) is int and payload > 0
        assert isinstance(traffic_class, str) and traffic_class

    assert mapping.agents
    for agent in mapping.agents:
        assert type(agent["count"]) is int and agent["count"] > 0
    assert any(
        agent["kind"] == "compute_tile" and agent["count"] == expected_ranks
        for agent in mapping.agents)

    _assert_collective_groups(mapping, expected_ranks)


def test_agent_counts_are_positive_with_optional_hbm_controllers() -> None:
    default = _map(CLUSTERS / "qwen_tp2_ep2.json")
    assert [agent["kind"] for agent in default.agents] == ["compute_tile"]
    assert default.agents[0]["count"] == 2

    opt_in = _map(
        CLUSTERS / "qwen_tp2_ep2.json", hbm_controllers_per_rank=2)
    assert [agent["kind"] for agent in opt_in.agents] == [
        "compute_tile", "hbm_controller"]
    assert opt_in.agents[0]["count"] == 2
    assert opt_in.agents[1]["count"] == 4
    for agent in opt_in.agents:
        assert type(agent["count"]) is int and agent["count"] > 0


def test_topology_must_seat_ranks_and_hbm_controllers() -> None:
    mapping = _map(
        CLUSTERS / "qwen_tp2_ep2.json", hbm_controllers_per_rank=2)
    assert sum(agent["count"] for agent in mapping.agents) == 6
    assert any(
        "topology must seat ranks + hbm_controllers" in assumption
        for assumption in mapping.report["assumptions"])

    too_small = FabricCompiler().compile(parse_request_doc(
        mapping.to_request(topology=dict(MESH_2))))
    assert too_small.status == "UNSUPPORTED"
    assert "6 agents" in (too_small.error or "")

    roomy = FabricCompiler().compile(parse_request_doc(
        mapping.to_request(
            topology={"kind": "mesh", "side_length": 3,
                      "concentration": 1})))
    assert roomy.status == "COMPILED", roomy.error


def test_status_is_ok_exactly_when_a_workload_exists() -> None:
    ok = _map(CLUSTERS / "qwen_tp2_ep2.json")
    assert (ok.status == "OK") is True
    assert ok.workload is not None

    refused = _map(REFUSALS / "qwen_pd.json")
    assert (refused.status == "OK") is False
    assert refused.workload is None


# ---------------------------------------------------------------------------
# 3. Determinism and identity
# ---------------------------------------------------------------------------

def test_same_inputs_produce_identical_report_and_request() -> None:
    cluster = CLUSTERS / "qwen_tp2_ep2.json"
    first = _map(cluster)
    second = _map(cluster)

    assert first.report == second.report
    assert _canonical(first.report) == _canonical(second.report)

    first_request = _request(first)
    second_request = _request(second)
    assert first_request == second_request
    assert _canonical(first_request) == _canonical(second_request)


def test_request_round_trip_preserves_design_hash() -> None:
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json")
    request = _request(mapping)
    assert request["schema_version"] == 4

    parsed = parse_request_doc(request)
    round_tripped = parse_request_doc(parsed.to_dict())
    assert round_tripped.design_hash() == parsed.design_hash()
    assert round_tripped.to_dict() == parsed.to_dict()


def test_assembled_request_shape_and_caller_supplied_fabric() -> None:
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json")
    topology = {"kind": "mesh", "side_length": 2, "concentration": 1}
    noc_controls = {"link_width": 256}
    physical = {
        "clock_freq_mhz": 1200.0,
        "data_width": 256,
        "process_node_nm": 5,
        "num_power_domains": 2,
    }
    request = mapping.to_request(
        topology=topology, noc_controls=noc_controls, physical=physical)

    assert request["schema_version"] == 4
    assert request["compiler_semantics_version"] == 4
    assert request["topology"] == topology
    assert request["topology"] is not topology
    assert request["noc_controls"] == noc_controls
    assert request["noc_controls"] is not noc_controls
    assert request["physical"] == physical
    assert request["physical"] is not physical
    assert request["dependencies"] == {}
    assert request["address_map"] == {"ranges": []}
    assert request["workload"] == mapping.workload
    assert request["workload"] is not mapping.workload
    assert request["agents"] == list(mapping.agents)
    assert request["agents"] is not mapping.agents

    default_request = mapping.to_request(topology=dict(MESH_2))
    assert default_request["noc_controls"] == {"link_width": 128}
    assert default_request["physical"] == {
        "clock_freq_mhz": 1000.0,
        "data_width": 128,
        "process_node_nm": 7,
        "num_power_domains": 1,
    }


# ---------------------------------------------------------------------------
# 4. Honesty: no invented compute, requirements, weights, timestamps
# ---------------------------------------------------------------------------

def test_compute_and_requirements_are_empty() -> None:
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json")
    assert mapping.compute == {"stages": []}
    assert mapping.requirements == ()

    request = _request(mapping)
    assert request["compute"] == {"stages": []}
    assert request["requirements"] == []
    assert any(
        "compute timing is not modeled" in assumption
        for assumption in mapping.report["assumptions"])


def test_report_assumptions_state_the_collective_contract() -> None:
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json")
    assumptions = " ".join(mapping.report["assumptions"])

    assert "EP dispatch is an all-gather" in assumptions
    assert "reduce-scatter" in assumptions
    assert "ep_decode_bytes is the decode EP dispatch" in assumptions
    assert "parser defaults the legacy serving_mode field to mixed" \
        in assumptions
    assert "topology must seat ranks + hbm_controllers" in assumptions


def test_workload_has_no_legacy_serving_mode_key() -> None:
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json")
    assert "serving_mode" not in mapping.workload
    assert "serving_mode" not in _walk_keys(mapping.workload)
    assert "serving_mode" not in _request(mapping)["workload"]

    parsed = parse_request_doc(_request(mapping))
    assert parsed.workload.serving_mode.value == "mixed"
    assert parsed.to_dict()["workload"]["serving_mode"] == "mixed"
    assert any(
        "parser defaults the legacy serving_mode field to mixed"
        in assumption
        for assumption in mapping.report["assumptions"])


def test_weights_bytes_only_when_num_parameters_declared() -> None:
    qwen = _map(CLUSTERS / "qwen_tp2_ep2.json")
    assert qwen.report["model"]["weights_bytes"] is None

    llama = _map(CLUSTERS / "llama_tp4.json", model=LLAMA_MODEL)
    assert llama.report["model"]["weights_bytes"] is None

    two_byte = _map(
        CLUSTERS / "qwen_weights.json", model=PARAMETER_MODEL,
        dtype_bytes=2)
    assert two_byte.report["model"]["dtype_bytes"] == 2
    assert two_byte.report["model"]["weights_bytes"] == 1000 * 2

    four_byte = _map(
        CLUSTERS / "qwen_weights.json", model=PARAMETER_MODEL,
        dtype_bytes=4)
    assert four_byte.report["model"]["dtype_bytes"] == 4
    assert four_byte.report["model"]["weights_bytes"] == 1000 * 4

    from_torch_dtype = _map(
        CLUSTERS / "qwen_weights.json", model=PARAMETER_MODEL,
        dtype_bytes=None)
    assert from_torch_dtype.report["model"]["dtype_bytes"] == 4
    assert from_torch_dtype.report["model"]["weights_bytes"] == 1000 * 4


def test_fractional_num_parameters_is_not_truncated() -> None:
    mapping = _map(
        CLUSTERS / "qwen_weights.json", model=FRACTIONAL_PARAMETER_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["model"]["weights_bytes"] is None
    assert any(
        "num_parameters=1000.5" in assumption
        and "not a non-negative integer" in assumption
        and "no truncation" in assumption
        for assumption in mapping.report["assumptions"])


def test_model_name_is_not_cross_checked_and_is_declared_as_an_assumption(
        tmp_path: Path) -> None:
    cluster = _write_cluster(tmp_path, [_inst(QWEN, tp_size=2)])
    mapping = _map(cluster, model=LLAMA_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["model_name"] == QWEN
    assert mapping.report["model"]["layers"] == 32
    assert mapping.report["model"]["experts"] is None
    assert mapping.workload["model_name"] == QWEN
    assert any(
        "not cross-checked against the cluster model_name" in assumption
        for assumption in mapping.report["assumptions"])

    override = _map(
        CLUSTERS / "qwen_tp2_ep2.json", model_name="org/override-model")
    assert override.report["deployment"]["model_name"] == QWEN
    assert override.report["deployment"]["model_name_override"] \
        == "org/override-model"
    assert any(
        "not cross-checked against the cluster model_name" in assumption
        for assumption in override.report["assumptions"])


def test_report_has_no_timestamp_like_keys_or_values() -> None:
    for mapping in (
            _map(CLUSTERS / "qwen_tp2_ep2.json"),
            _map(REFUSALS / "qwen_pd.json")):
        keys = _walk_keys(mapping.report)
        for token in _TIMESTAMP_KEY_TOKENS:
            assert not [key for key in keys if token in key.lower()]

        assert not [
            text for text in _walk_strings(mapping.report)
            if re.search(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}", text)]


# ---------------------------------------------------------------------------
# 5. One independent refusal test per code in the design table
# ---------------------------------------------------------------------------

def test_refusal_pd_pools_unsupported() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_pd.json"), "PD_POOLS_UNSUPPORTED")


def test_refusal_pipeline_parallel_unsupported() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_pp2.json"), "PIPELINE_PARALLEL_UNSUPPORTED")


def test_refusal_heterogeneous_cluster_unsupported() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_heterogeneous.json"),
        "HETEROGENEOUS_CLUSTER_UNSUPPORTED")


def test_refusal_dp_group_required() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_dp_no_group.json"), "DP_GROUP_REQUIRED")


def test_refusal_dp_ep_unsupported() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_dp_ep.json"), "DP_EP_UNSUPPORTED")


def test_refusal_ep_subset_unsupported() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_ep_subset.json"), "EP_SUBSET_UNSUPPORTED")


def test_refusal_tp_invalid() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_tp_invalid.json"), "TP_INVALID")


def test_refusal_ep_invalid() -> None:
    _assert_refused(
        _map(REFUSALS / "moe_ep_invalid.json", model=THREE_EXPERT_MODEL),
        "EP_INVALID")


def test_refusal_model_config_incomplete() -> None:
    _assert_refused(
        _map(REFUSALS / "qwen_incomplete_model.json",
             model=INCOMPLETE_MODEL),
        "MODEL_CONFIG_INCOMPLETE")


def test_refusal_no_instances(tmp_path: Path) -> None:
    _assert_refused(
        _map(REFUSALS / "no_instances.json"), "NO_INSTANCES")

    empty_node = _write_cluster(tmp_path, [])
    _assert_refused(_map(empty_node), "NO_INSTANCES")

    missing_nodes = tmp_path / "missing-nodes.json"
    missing_nodes.write_text("{}", encoding="utf-8")
    _assert_refused(_map(missing_nodes), "NO_INSTANCES")


def test_refusal_hardware_required(tmp_path: Path) -> None:
    _assert_refused(
        _map(REFUSALS / "missing_hardware.json"), "HARDWARE_REQUIRED")

    empty_hardware = _write_cluster(tmp_path, [_inst(
        QWEN, tp_size=2, ep_size=2, hardware="")])
    _assert_refused(_map(empty_hardware), "HARDWARE_REQUIRED")


def test_refusal_nondivisible_implicit_head_dim() -> None:
    _assert_refused(
        _map(REFUSALS / "nondivisible_head_dim.json",
             model=NONDIVISIBLE_HEAD_DIM_MODEL),
        "MODEL_CONFIG_INCOMPLETE")


def test_refusal_top_k_exceeds_experts() -> None:
    _assert_refused(
        _map(REFUSALS / "topk_exceeds_experts.json",
             model=TOPK_EXCEEDS_MODEL),
        "MODEL_CONFIG_INCOMPLETE")


@pytest.mark.parametrize("case", [
    "missing_cluster",
    "missing_model",
    "missing_trace",
    "invalid_cluster_json",
    "invalid_model_json",
])
def test_refusal_source_unreadable(tmp_path: Path, case: str) -> None:
    cluster: Path = CLUSTERS / "qwen_tp2_ep2.json"
    model: Path = QWEN_MODEL
    trace: Path = TINY_4
    if case == "missing_cluster":
        cluster = tmp_path / "absent-cluster.json"
    elif case == "missing_model":
        model = tmp_path / "absent-model.json"
    elif case == "missing_trace":
        trace = tmp_path / "absent-trace.jsonl"
    elif case == "invalid_cluster_json":
        cluster = INVALID / "cluster_not_json.json"
    elif case == "invalid_model_json":
        model = INVALID / "model_not_json.json"
    else:  # pragma: no cover - parametrization is exhaustive
        raise AssertionError(case)
    _assert_refused(
        _map(cluster, model=model, trace=trace), "SOURCE_UNREADABLE")


@pytest.mark.parametrize("trace_name", [
    "malformed_json",
    "missing_input_toks",
    "missing_output_toks",
    "non_object_row",
    "non_numeric_input",
])
def test_refusal_trace_invalid(tmp_path: Path, trace_name: str) -> None:
    _assert_refused(
        _map(CLUSTERS / "qwen_tp2_ep2.json",
             trace=TRACES / f"{trace_name}.jsonl"),
        "TRACE_INVALID")


@pytest.mark.parametrize("row", [
    {"input_toks": -1, "output_toks": 1, "arrival_time_ns": 0},
    {"input_toks": 1, "output_toks": -1, "arrival_time_ns": 0},
    {"input_toks": 1, "output_toks": 1, "arrival_time_ns": -1},
    {"input_toks": 1.5, "output_toks": 1, "arrival_time_ns": 0},
    {"input_toks": True, "output_toks": 1, "arrival_time_ns": 0},
    {"input_toks": 1, "output_toks": 1.5, "arrival_time_ns": 0},
])
def test_trace_tokens_must_be_non_negative_integers(
        tmp_path: Path, row: dict[str, Any]) -> None:
    trace = _write_trace(tmp_path, [row])
    _assert_refused(
        _map(CLUSTERS / "qwen_tp2_ep2.json", trace=trace),
        "TRACE_INVALID")


def test_zero_token_counts_are_accepted(tmp_path: Path) -> None:
    trace = _write_trace(tmp_path, [
        {"input_toks": 0, "output_toks": 0, "arrival_time_ns": 0},
        {"input_toks": 0, "output_toks": 0, "arrival_time_ns": 0},
        {"input_toks": 0, "output_toks": 0, "arrival_time_ns": 0},
        {"input_toks": 0, "output_toks": 0, "arrival_time_ns": 0},
    ])
    mapping = _map(CLUSTERS / "qwen_tp2_ep2.json", trace=trace)

    assert mapping.status == "OK"
    assert mapping.report["request"] == {
        "num_reqs": 4,
        "isl_mean": 0.0,
        "osl_mean": 0.0,
        "arrival_span_ns": 0,
    }


@pytest.mark.parametrize("field,value", [
    ("max_num_seqs", "many"),
    ("max_num_seqs", 1.5),
    ("max_num_seqs", True),
    ("max_num_batched_tokens", -1),
    ("max_num_batched_tokens", "2048"),
])
def test_refusal_serving_limit_invalid(
        tmp_path: Path, field: str, value: Any) -> None:
    cluster = _write_cluster(
        tmp_path,
        [_inst(QWEN, tp_size=2, ep_size=2, **{field: value})])
    _assert_refused(_map(cluster), "SERVING_LIMIT_INVALID")


@pytest.mark.parametrize("first_limits,second_limits", [
    ({"max_num_seqs": 8}, {"max_num_seqs": 64}),
    ({"max_num_batched_tokens": 16},
     {"max_num_batched_tokens": 4096}),
    ({}, {"max_num_seqs": 64}),
    ({"max_num_batched_tokens": 16}, {}),
    # Positive declarations are compared as policies before the trace bounds
    # the effective batch, so 8 and the 128 default still disagree.
    ({"max_num_seqs": 8}, {}),
    # 0 resolves against the trace/model, so it disagrees with the defaults.
    ({"max_num_seqs": 0}, {}),
    ({"max_num_batched_tokens": 0}, {}),
])
def test_refusal_heterogeneous_serving_limits(
        tmp_path: Path,
        first_limits: dict[str, Any],
        second_limits: dict[str, Any]) -> None:
    first = _inst(LLAMA, tp_size=2, dp_group="A", **first_limits)
    second = _inst(LLAMA, tp_size=2, dp_group="A", **second_limits)
    cluster = _write_cluster(tmp_path, [first, second])

    _assert_refused(
        _map(cluster, model=LLAMA_MODEL),
        "HETEROGENEOUS_SERVING_LIMITS")


def test_resolved_serving_limits_are_compared_not_raw_declarations(
        tmp_path: Path) -> None:
    # 0 resolves to max_position_embeddings=131072 and to the 4 selected
    # requests, so these two instances agree after resolution even though
    # their raw declarations differ.
    zero = _inst(
        LLAMA, tp_size=2, dp_group="A",
        max_num_batched_tokens=0, max_num_seqs=0)
    explicit = _inst(
        LLAMA, tp_size=2, dp_group="A",
        max_num_batched_tokens=131072, max_num_seqs=4)
    cluster = _write_cluster(tmp_path, [zero, explicit])
    mapping = _map(cluster, model=LLAMA_MODEL, trace=TINY_4)

    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 131072
    assert mapping.report["derived"]["decode_batch"] == 4

    # Absent limits resolve to the 2048 / 128 defaults; an explicit
    # declaration of those defaults must not be treated as disagreement.
    absent = _inst(LLAMA, tp_size=2, dp_group="A")
    declared_default = _inst(
        LLAMA, tp_size=2, dp_group="A",
        max_num_batched_tokens=2048, max_num_seqs=128)
    default_cluster = _write_cluster(
        tmp_path, [absent, declared_default], name="cluster-defaults.json")
    default_mapping = _map(default_cluster, model=LLAMA_MODEL)

    assert default_mapping.status == "OK"
    assert default_mapping.report["derived"]["prefill_chunk_tokens"] == 2048
    assert default_mapping.report["derived"]["decode_batch"] == 4
    assert any(
        "defaults to 128 and is clamped to the 4 selected"
        in assumption
        for assumption in default_mapping.report["assumptions"])

    # Two different over-limit prefill declarations both clamp to the same
    # max_position_embeddings, so they agree after resolution.
    over_a = _inst(
        "synthetic/dense", tp_size=2, dp_group="A",
        max_num_batched_tokens=4096)
    over_b = _inst(
        "synthetic/dense", tp_size=2, dp_group="A",
        max_num_batched_tokens=8192)
    over_cluster = _write_cluster(
        tmp_path, [over_a, over_b], name="cluster-over-limit.json")
    over_mapping = _map(
        over_cluster, model=DENSE_MAXPOS_MODEL, trace=TINY_4)

    assert over_mapping.status == "OK"
    assert over_mapping.report["derived"]["prefill_chunk_tokens"] == 1024
    assert over_mapping.report["derived"]["tp_prefill_bytes"] == 1024 * 8 * 2


@pytest.mark.parametrize("kwargs", [
    {"num_reqs": -1},
    {"num_reqs": "2"},
    {"num_reqs": 1.5},
    {"num_reqs": True},
    {"link_width_bits": 0},
    {"link_width_bits": "wide"},
    {"link_width_bits": True},
    {"hbm_controllers_per_rank": -1},
    {"hbm_controllers_per_rank": 1.5},
    {"hbm_controllers_per_rank": "2"},
    {"dtype_bytes": 0},
    {"dtype_bytes": "two"},
    {"dtype_bytes": 1.5},
])
def test_refusal_argument_invalid(
        tmp_path: Path, kwargs: dict[str, Any]) -> None:
    _assert_refused(
        _map(CLUSTERS / "qwen_tp2_ep2.json", **kwargs),
        "ARGUMENT_INVALID")


def test_argument_boundaries_are_accepted() -> None:
    # num_reqs=0 is a valid argument; it is the later request selection that
    # finds nothing to map.
    _assert_refused(
        _map(CLUSTERS / "qwen_tp2_ep2.json", num_reqs=0),
        "TRACE_EMPTY")

    mapping = _map(
        CLUSTERS / "qwen_tp2_ep2.json",
        num_reqs=4,
        link_width_bits=1,
        hbm_controllers_per_rank=0,
        dtype_bytes=None,
    )
    assert mapping.status == "OK"
    assert mapping.agents[0]["data_width"] == 1
    assert [agent["kind"] for agent in mapping.agents] == ["compute_tile"]
    assert mapping.report["model"]["dtype_bytes"] == 2


def test_refusal_trace_empty(tmp_path: Path) -> None:
    _assert_refused(
        _map(CLUSTERS / "qwen_tp2_ep2.json", trace=EMPTY_TRACE),
        "TRACE_EMPTY")
    _assert_refused(
        _map(CLUSTERS / "qwen_tp2_ep2.json", num_reqs=0), "TRACE_EMPTY")


def test_refusal_no_traffic() -> None:
    mapping = _assert_refused(
        _map(CLUSTERS / "llama_tp1.json", model=LLAMA_MODEL),
        "NO_TRAFFIC")
    assert mapping.report["deployment"]["tp"] == 1


# ---------------------------------------------------------------------------
# 6. Semantic traps
# ---------------------------------------------------------------------------

def test_moe_omitted_ep_defaults_to_tp_not_one() -> None:
    mapping = _map(CLUSTERS / "qwen_tp4_ep_omitted.json")

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["ep"] == 4
    assert mapping.workload["ep"] == 1
    assert [collective["traffic_class"] for collective in
            mapping.workload["collectives"]] == [
        "tp_collective", "ep_dispatch", "ep_combine"]
    # dispatch = max(1, 2048 // ep=4) * (hidden=2048 + experts=128) * bf16=2
    # combine  = 2048 * hidden=2048 * bf16=2
    assert [collective["payload_bytes"] for collective in
            mapping.workload["collectives"]] == [
        8388608, 2228224, 8388608]
    assert mapping.report["derived"]["ep_decode_bytes"] == \
        max(1, 4 // 4) * (2048 + 128) * 2


def test_moe_explicit_ep_one_emits_only_tp_allreduce(tmp_path: Path) -> None:
    cluster = _write_cluster(
        tmp_path, [_inst(QWEN, tp_size=4, ep_size=1)])
    mapping = _map(cluster)

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["ep"] == 1
    assert mapping.workload["ep"] == 1
    assert [collective["traffic_class"] for collective in
            mapping.workload["collectives"]] == ["tp_collective"]
    assert [collective["payload_bytes"] for collective in
            mapping.workload["collectives"]] == [8388608]
    assert mapping.report["derived"]["ep_decode_bytes"] == 0


def test_moe_ep_below_tp_is_refused_not_silently_subset() -> None:
    mapping = _assert_refused(
        _map(REFUSALS / "qwen_ep_subset.json"), "EP_SUBSET_UNSUPPORTED")
    # The refusal must not have adjusted ep_size up to tp_size.
    assert mapping.report["deployment"]["ep"] == 2
    assert mapping.report["deployment"]["tp"] == 4


def test_tp_size_is_inferred_from_num_npus() -> None:
    mapping = _map(CLUSTERS / "qwen_num_npus2.json")

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["tp"] == 2
    assert mapping.report["deployment"]["ep"] == 2
    assert mapping.report["deployment"]["ranks"] == 2
    assert len(mapping.workload["collectives"]) == 3


def test_num_npus_divisible_mismatch_implies_pp() -> None:
    # config_builder would infer pp=2 from num_npus=4 and tp_size=2.
    _assert_refused(
        _map(CLUSTERS / "qwen_num_npus_mismatch.json"),
        "PIPELINE_PARALLEL_UNSUPPORTED")


def test_num_npus_non_divisible_mismatch_is_tp_invalid() -> None:
    _assert_refused(
        _map(CLUSTERS / "qwen_num_npus_nondivisible.json"), "TP_INVALID")


def test_tp_and_num_npus_that_agree_are_accepted(tmp_path: Path) -> None:
    cluster = _write_cluster(
        tmp_path, [_inst(LLAMA, tp_size=2, num_npus=2)])
    mapping = _map(cluster, model=LLAMA_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["deployment"]["tp"] == 2
    assert mapping.report["deployment"]["pp"] == 1
    assert mapping.report["deployment"]["ranks"] == 2


def test_tp_and_num_npus_both_absent_default_to_one() -> None:
    mapping = _assert_refused(
        _map(CLUSTERS / "llama_tp_absent.json", model=LLAMA_MODEL),
        "NO_TRAFFIC")
    deployment = mapping.report["deployment"]
    assert deployment["tp"] == 1
    assert deployment["pp"] == 1
    assert deployment["ranks"] == 1


def test_zero_max_num_batched_tokens_uses_max_position_embeddings() -> None:
    mapping = _map(CLUSTERS / "llama_zero_prefill.json", model=LLAMA_MODEL)

    assert mapping.status == "OK"
    derived = mapping.report["derived"]
    assert derived["prefill_chunk_tokens"] == 131072
    assert derived["tp_prefill_bytes"] == 131072 * 4096 * 2
    assert derived["decode_batch"] == 4
    assert derived["tp_decode_bytes"] == 4 * 4096 * 2
    assert any(
        "max_num_batched_tokens=0" in assumption
        and "max_position_embeddings=131072" in assumption
        for assumption in mapping.report["assumptions"])


def test_absent_prefill_is_clamped_to_max_position_embeddings() -> None:
    mapping = _map(
        CLUSTERS / "dense_tp2.json", model=DENSE_MAXPOS_MODEL)

    assert mapping.status == "OK"
    derived = mapping.report["derived"]
    assert derived["prefill_chunk_tokens"] == 1024
    assert derived["tp_prefill_bytes"] == 1024 * 8 * 2
    assert any(
        "prefill chunk defaults to 2048" in assumption
        and "clamped to max_position_embeddings=1024" in assumption
        for assumption in mapping.report["assumptions"])


def test_declared_prefill_over_limit_is_clamped(tmp_path: Path) -> None:
    cluster = _write_cluster(tmp_path, [_inst(
        "synthetic/dense", tp_size=2, ep_size=1,
        max_num_batched_tokens=4096)])
    mapping = _map(cluster, model=DENSE_MAXPOS_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 1024
    assert mapping.report["derived"]["tp_prefill_bytes"] == 1024 * 8 * 2
    assert any(
        "clamped to max_position_embeddings=1024" in assumption
        for assumption in mapping.report["assumptions"])


def test_declared_prefill_under_limit_is_kept(tmp_path: Path) -> None:
    cluster = _write_cluster(tmp_path, [_inst(
        "synthetic/dense", tp_size=2, ep_size=1,
        max_num_batched_tokens=512)])
    mapping = _map(cluster, model=DENSE_MAXPOS_MODEL)

    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 512
    assert mapping.report["derived"]["tp_prefill_bytes"] == 512 * 8 * 2
    assert not any(
        "clamped to max_position_embeddings" in assumption
        for assumption in mapping.report["assumptions"])


def test_zero_max_num_seqs_uses_the_selected_request_count() -> None:
    mapping = _map(
        CLUSTERS / "llama_zero_decode.json",
        model=LLAMA_MODEL,
        trace=TINY_6,
        num_reqs=4,
    )

    assert mapping.status == "OK"
    assert mapping.report["request"] == {
        "num_reqs": 4,
        "isl_mean": 25.0,
        "osl_mean": 250.0,
        "arrival_span_ns": 3,
    }
    derived = mapping.report["derived"]
    assert derived["decode_batch"] == 4
    assert derived["tp_decode_bytes"] == 4 * 4096 * 2
    assert any(
        "max_num_seqs=0" in assumption
        and "4 selected request" in assumption
        for assumption in mapping.report["assumptions"])


@pytest.mark.parametrize("max_num_seqs,expected_batch", [
    (None, 4),
    (8, 4),
    (2, 2),
    (0, 4),
])
def test_decode_batch_is_bounded_by_selected_request_count(
        tmp_path: Path, max_num_seqs: int | None,
        expected_batch: int) -> None:
    overrides: dict[str, Any] = {"tp_size": 2}
    if max_num_seqs is not None:
        overrides["max_num_seqs"] = max_num_seqs
    cluster = _write_cluster(tmp_path, [_inst(LLAMA, **overrides)])
    mapping = _map(
        cluster, model=LLAMA_MODEL, trace=TINY_6, num_reqs=4)

    assert mapping.status == "OK"
    derived = mapping.report["derived"]
    assert derived["decode_batch"] == expected_batch
    assert derived["tp_decode_bytes"] == expected_batch * 4096 * 2
    if max_num_seqs is None or (max_num_seqs or 0) > 4:
        assert any(
            "clamped to the 4 selected" in assumption
            for assumption in mapping.report["assumptions"])


def test_to_request_raises_value_error_for_refused_mapping() -> None:
    mapping = _map(REFUSALS / "qwen_pd.json")
    assert mapping.status == "REFUSED"
    with pytest.raises(ValueError, match="PD_POOLS_UNSUPPORTED"):
        mapping.to_request(topology=dict(MESH_2))


def test_dense_tp1_is_refused_no_traffic() -> None:
    mapping = _assert_refused(
        _map(CLUSTERS / "llama_tp1.json", model=LLAMA_MODEL),
        "NO_TRAFFIC")
    assert mapping.report["deployment"]["tp"] == 1
    assert mapping.report["deployment"]["ranks"] == 1
