"""LLMServingSim deployment -> v4 workload intent (locked design v1).

Every test here is a contract from
``docs/design/reviews/deployment-intent-mapping.md``: the golden Qwen3 MoE
deployment must compile, payload/geometry formulas must be exact, every
refusal code must be reachable and typed, and the report must be deterministic
and free of invented timing.
"""
from __future__ import annotations

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
from veritx_dse.core.paths import REPO  # noqa: E402
from veritx_dse.product.service import parse_request_doc  # noqa: E402

QWEN_NAME = "Qwen/Qwen3-30B-A3B-Instruct-2507"
QWEN_MODEL = (REPO / "third_party" / "llmservingsim" / "configs" / "model"
              / "Qwen" / "Qwen3-30B-A3B-Instruct-2507.json")
MESH_2 = {"kind": "mesh", "side_length": 2, "concentration": 1}

DEFAULT_ROWS = [
    {"input_toks": 10, "output_toks": 60, "arrival_time_ns": 0},
    {"input_toks": 14, "output_toks": 78, "arrival_time_ns": 1234567},
]

def _instance(**overrides: Any) -> dict[str, Any]:
    instance = {
        "model_name": QWEN_NAME,
        "hardware": "RTXPRO6000",
        "tp_size": 2,
        "ep_size": 2,
        "pd_type": None,
    }
    instance.update(overrides)
    return instance

def _write_json(path: Path, payload: Any) -> Path:
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path

def _write_trace(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.write_text(
        "".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path

def _map(
    tmp_path: Path,
    instances: list[dict[str, Any]],
    *,
    model: Path | dict[str, Any] | None = None,
    rows: list[dict[str, Any]] | None = None,
    **kwargs: Any,
) -> DeploymentMapping:
    cluster = {
        "num_nodes": 1,
        "nodes": [{
            "num_instances": len(instances),
            "instances": instances,
        }],
    }
    cluster_path = _write_json(tmp_path / "cluster.json", cluster)
    if model is None:
        model_path = QWEN_MODEL
    elif isinstance(model, dict):
        model_path = _write_json(tmp_path / "model.json", model)
    else:
        model_path = Path(model)
    trace_path = _write_trace(
        tmp_path / "trace.jsonl",
        DEFAULT_ROWS if rows is None else rows)
    return map_deployment(
        cluster_config=cluster_path,
        model_config=model_path,
        trace=trace_path,
        **kwargs)

def _assert_refused(mapping: DeploymentMapping, code: str) -> None:
    assert mapping.status == "REFUSED"
    assert mapping.workload is None
    assert mapping.report["status"] == "REFUSED"
    assert [issue["code"] for issue in mapping.report["issues"]] == [code]

# ---------------------------------------------------------------------------
# Golden compile and exact formulas
# ---------------------------------------------------------------------------

def test_golden_qwen3_tp2_ep2_compiles(tmp_path: Path) -> None:
    mapping = _map(tmp_path, [_instance()])
    assert mapping.status == "OK"
    assert mapping.report["schema"] == SCHEMA
    assert mapping.report["model"]["weights_bytes"] is None
    assert any(
        "The model config content is not cross-checked against the cluster "
        "model_name; the caller supplies the matching config." == assumption
        for assumption in mapping.report["assumptions"])
    assert mapping.report["deployment"] == {
        "model_name": QWEN_NAME,
        "hardware": "RTXPRO6000",
        "pd_type": None,
        "tp": 2,
        "dp": 1,
        "ep": 2,
        "pp": 1,
        "instances": 1,
        "ranks": 2,
    }
    assert mapping.report["request"] == {
        "num_reqs": 2,
        "isl_mean": 12.0,
        "osl_mean": 69.0,
        "arrival_span_ns": 1234567,
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
    assert mapping.report["derived"] == {
        "prefill_chunk_tokens": 2048,
        "decode_batch": 2,
        "tp_prefill_bytes": 8388608,
        "tp_decode_bytes": 8192,
        "ep_dispatch_bytes": 4456448,
        "ep_combine_bytes": 8388608,
        "ep_decode_bytes": 4352,
        "kv_bytes_per_token": 98304,
    }

    request = mapping.to_request(topology=MESH_2)
    assert request["schema_version"] == 4
    assert request["compiler_semantics_version"] == 4
    assert request["topology"] == MESH_2
    assert request["dependencies"] == {}
    assert request["address_map"] == {"ranges": []}
    assert request["requirements"] == []
    assert request["compute"] == {"stages": []}
    assert request["noc_controls"] == {"link_width": 128}
    assert request["physical"] == {
        "clock_freq_mhz": 1000.0,
        "data_width": 128,
        "process_node_nm": 7,
        "num_power_domains": 1,
    }

    parsed = parse_request_doc(request)
    assert parsed.workload.model_name == QWEN_NAME
    assert parsed.workload.model_family.value == "mixture_of_experts"
    assert (parsed.workload.tp, parsed.workload.dp, parsed.workload.ep,
            parsed.workload.pp) == (2, 1, 1, 1)
    assert [c.kind.value for c in parsed.workload.collectives] == [
        "allreduce", "allgather", "reducescatter"]
    assert [c.dimension.value for c in parsed.workload.collectives] == [
        "TP", "TP", "TP"]
    assert [c.traffic_class for c in parsed.workload.collectives] == [
        "tp_collective", "ep_dispatch", "ep_combine"]
    assert [c.payload_bytes for c in parsed.workload.collectives] == [
        8388608, 4456448, 8388608]

    compilation = FabricCompiler().compile(parsed)
    assert compilation.status == "COMPILED", compilation.error
    assert parse_request_doc(parsed.to_dict()).design_hash() \
        == parsed.design_hash()


def test_payload_and_geometry_formulas(tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_local_experts": 4,
        "moe_k": 2,
        "torch_dtype": "float32",
        "num_parameters": 1000,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/moe", tp_size=2,
                             ep_size=2)],
        model=model, dtype_bytes=2)

    report = mapping.report
    geometry = report["model"]
    assert geometry == {
        "layers": 2,
        "hidden": 8,
        "heads": 4,
        "kv_heads": 4,          # defaults to heads
        "head_dim": 2,          # defaults to hidden // heads
        "attention": "gqa",
        "kv_bytes_per_token_per_layer": 2 * 4 * 2 * 2,
        "experts": 4,           # num_local_experts alias
        "top_k": 2,             # moe_k alias
        "dtype_bytes": 2,       # explicit argument beats torch_dtype
        "weights_bytes": 2000,  # 1000 * dtype_bytes
    }
    assert report["derived"] == {
        "prefill_chunk_tokens": 2048,
        "decode_batch": 2,
        "tp_prefill_bytes": 2048 * 8 * 2,
        "tp_decode_bytes": 2 * 8 * 2,
        "ep_dispatch_bytes": (2048 // 2) * (8 + 4) * 2,
        "ep_combine_bytes": 2048 * 8 * 2,
        "ep_decode_bytes": 1 * (8 + 4) * 2,
        "kv_bytes_per_token": 2 * 2 * 4 * 2 * 2,
    }
    assert [c["kind"] for c in mapping.workload["collectives"]] == [
        "allreduce", "allgather", "reducescatter"]
    assert [c["payload_bytes"] for c in mapping.workload["collectives"]] == [
        32768, 24576, 32768]

    # torch_dtype is used only when the caller explicitly leaves dtype unset.
    from_dtype = _map(
        tmp_path, [_instance(model_name="synthetic/moe", tp_size=2,
                             ep_size=2)],
        model=model, dtype_bytes=None)
    assert from_dtype.report["model"]["dtype_bytes"] == 4
    assert from_dtype.report["model"]["weights_bytes"] == 4000
    assert from_dtype.report["derived"]["tp_prefill_bytes"] \
        == 2048 * 8 * 4

    # Instance serving limits override the 2048 / 128 defaults.
    overridden = _map(
        tmp_path, [_instance(model_name="synthetic/moe", tp_size=2,
                             ep_size=2, max_num_batched_tokens=64,
                             max_num_seqs=8)],
        model=model, dtype_bytes=2)
    assert overridden.report["derived"]["prefill_chunk_tokens"] == 64
    assert overridden.report["derived"]["decode_batch"] == 2
    assert overridden.report["derived"]["tp_prefill_bytes"] == 64 * 8 * 2
    assert overridden.report["derived"]["tp_decode_bytes"] == 2 * 8 * 2
    assert overridden.report["derived"]["ep_dispatch_bytes"] \
        == (64 // 2) * (8 + 4) * 2

def test_gqa_model_reports_attention_and_legacy_kv_formula(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 3,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 2,
        "head_dim": 4,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/dense", tp_size=2,
                             ep_size=1)],
        model=model)
    assert mapping.status == "OK"
    geometry = mapping.report["model"]
    assert geometry["attention"] == "gqa"
    assert geometry["kv_bytes_per_token_per_layer"] == 2 * 2 * 4 * 2
    assert "indexer_bytes_per_token_per_layer" not in geometry
    assert mapping.report["derived"]["kv_bytes_per_token"] \
        == 3 * 2 * 2 * 4 * 2

# ---------------------------------------------------------------------------
# One test per locked refusal code
# ---------------------------------------------------------------------------

def test_pd_pools_unsupported(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(pd_type="prefill")]),
        "PD_POOLS_UNSUPPORTED")

def test_pipeline_parallel_unsupported(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(pp_size=2)]),
        "PIPELINE_PARALLEL_UNSUPPORTED")

def test_heterogeneous_cluster_unsupported(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [
            _instance(dp_group="A"),
            _instance(dp_group="A", hardware="H100"),
        ]),
        "HETEROGENEOUS_CLUSTER_UNSUPPORTED")

def test_dp_group_required(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(), _instance()]),
        "DP_GROUP_REQUIRED")

def test_dp_ep_unsupported(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [
            _instance(dp_group="A"),
            _instance(dp_group="A"),
        ]),
        "DP_EP_UNSUPPORTED")

@pytest.mark.parametrize("model_name,tp_size,ep_size,model", [
    (QWEN_NAME, 4, 2, None),                 # subset EP
    (QWEN_NAME, 2, 4, None),                 # EP larger than TP
    ("synthetic/dense", 2, 2, {              # dense ep_size > 1
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }),
])
def test_ep_subset_covers_any_ep_not_in_one_or_tp(
        tmp_path: Path, model_name: str, tp_size: int, ep_size: int,
        model: dict[str, Any] | None) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(
            model_name=model_name, tp_size=tp_size, ep_size=ep_size)],
            model=model),
        "EP_SUBSET_UNSUPPORTED")

def test_tp_invalid(tmp_path: Path) -> None:
    # Qwen3-30B-A3B has 32 heads and 4 KV heads: tp=8 divides heads but
    # exceeds the KV-head count.
    _assert_refused(
        _map(tmp_path, [_instance(tp_size=8, ep_size=1)]),
        "TP_INVALID")

def test_ep_invalid(tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "num_experts": 3,
        "num_experts_per_tok": 2,
    }
    _assert_refused(
        _map(tmp_path, [_instance(model_name="synthetic/moe", tp_size=2,
                                  ep_size=2)], model=model),
        "EP_INVALID")

def test_model_config_incomplete(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(tp_size=2, ep_size=1)],
             model={"num_hidden_layers": 2}),
        "MODEL_CONFIG_INCOMPLETE")

def test_moe_architecture_without_experts_is_incomplete(
        tmp_path: Path) -> None:
    model = {
        "architectures": ["Qwen3MoeForCausalLM"],
        "model_type": "qwen3_moe",
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    _assert_refused(
        _map(tmp_path, [_instance(tp_size=2, ep_size=2)], model=model),
        "MODEL_CONFIG_INCOMPLETE")

def test_trace_empty(tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [_instance()], rows=[]),
        "TRACE_EMPTY")

def test_no_traffic(tmp_path: Path) -> None:
    dense = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
    }
    _assert_refused(
        _map(tmp_path, [_instance(model_name="synthetic/dense", tp_size=1,
                                  ep_size=1)], model=dense),
        "NO_TRAFFIC")

def test_no_instances_is_typed(tmp_path: Path) -> None:
    _assert_refused(_map(tmp_path, []), "NO_INSTANCES")

@pytest.mark.parametrize("hardware", [None, "", "   "])
def test_hardware_is_required(
        tmp_path: Path, hardware: str | None) -> None:
    instance = _instance()
    if hardware is None:
        instance.pop("hardware")
    else:
        instance["hardware"] = hardware
    _assert_refused(
        _map(tmp_path, [instance]), "HARDWARE_REQUIRED")

# ---------------------------------------------------------------------------
# Geometry validation
# ---------------------------------------------------------------------------

def test_implicit_head_dim_requires_divisible_hidden(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 10,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    _assert_refused(
        _map(tmp_path, [_instance(model_name="synthetic/dense", tp_size=1,
                                  ep_size=1)], model=model),
        "MODEL_CONFIG_INCOMPLETE")

def test_top_k_cannot_exceed_experts(tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "num_experts": 2,
        "num_experts_per_tok": 8,
    }
    _assert_refused(
        _map(tmp_path, [_instance(model_name="synthetic/moe", tp_size=1,
                                  ep_size=1)], model=model),
        "MODEL_CONFIG_INCOMPLETE")

def test_fractional_num_parameters_is_not_truncated(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "num_parameters": 1000.5,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/dense", tp_size=2,
                             ep_size=1)], model=model)
    assert mapping.status == "OK"
    assert mapping.report["model"]["weights_bytes"] is None
    assert any("num_parameters=1000.5" in assumption
               and "no truncation" in assumption
               for assumption in mapping.report["assumptions"])

# ---------------------------------------------------------------------------
# Prefill/decode limit resolution
# ---------------------------------------------------------------------------

def test_absent_prefill_is_clamped_to_max_position_embeddings(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "max_position_embeddings": 1024,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/dense", tp_size=2,
                             ep_size=1)], model=model)
    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 1024
    assert any("clamped to max_position_embeddings=1024" in assumption
               for assumption in mapping.report["assumptions"])

def test_declared_prefill_is_clamped_to_max_position_embeddings(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "max_position_embeddings": 1024,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/dense", tp_size=2,
                             ep_size=1, max_num_batched_tokens=4096)],
        model=model)
    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 1024
    assert any("clamped to max_position_embeddings=1024" in assumption
               for assumption in mapping.report["assumptions"])

def test_absent_decode_is_bounded_by_trace(tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/dense", tp_size=2,
                             ep_size=1)], model=model)
    assert mapping.status == "OK"
    assert mapping.report["derived"]["decode_batch"] == 2
    assert any("defaults to 128 and is clamped to the 2 selected"
               in assumption for assumption in mapping.report["assumptions"])

def test_positive_decode_is_bounded_by_trace(tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    mapping = _map(
        tmp_path, [_instance(model_name="synthetic/dense", tp_size=2,
                             ep_size=1, max_num_seqs=4)], model=model)
    assert mapping.status == "OK"
    assert mapping.report["derived"]["decode_batch"] == 2
    assert any("max_num_seqs=4 is clamped to the 2 selected"
               in assumption for assumption in mapping.report["assumptions"])

# ---------------------------------------------------------------------------
# Determinism, refusal assembly and report hygiene
# ---------------------------------------------------------------------------

def test_same_inputs_produce_identical_report_and_request(
        tmp_path: Path) -> None:
    first = _map(tmp_path, [_instance()])
    second = _map(tmp_path, [_instance()])
    assert first.report == second.report
    assert json.dumps(first.report, sort_keys=True) \
        == json.dumps(second.report, sort_keys=True)
    first_request = first.to_request(topology=MESH_2)
    second_request = second.to_request(topology=MESH_2)
    assert first_request == second_request
    assert json.dumps(first_request, sort_keys=True) \
        == json.dumps(second_request, sort_keys=True)

def test_to_request_raises_when_refused(tmp_path: Path) -> None:
    mapping = _map(tmp_path, [_instance(pd_type="prefill")])
    assert mapping.status == "REFUSED"
    with pytest.raises(ValueError):
        mapping.to_request(topology=MESH_2)

def test_report_has_no_timestamps_and_no_invented_weights(
        tmp_path: Path) -> None:
    mapping = _map(tmp_path, [_instance()])
    report = mapping.report
    assert report["model"]["weights_bytes"] is None

    def _keys(value: Any) -> list[str]:
        if isinstance(value, dict):
            keys: list[str] = []
            for key, child in value.items():
                keys.append(str(key))
                keys.extend(_keys(child))
            return keys
        if isinstance(value, (list, tuple)):
            keys = []
            for child in value:
                keys.extend(_keys(child))
            return keys
        return []

    def _strings(value: Any) -> list[str]:
        if isinstance(value, str):
            return [value]
        if isinstance(value, dict):
            return [s for child in value.values() for s in _strings(child)]
        if isinstance(value, (list, tuple)):
            return [s for child in value for s in _strings(child)]
        return []

    assert not [
        key for key in _keys(report)
        if any(token in key.lower()
               for token in ("timestamp", "created_at", "generated_at",
                             "updated_at"))
    ]
    assert not [
        text for text in _strings(report)
        if re.search(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}", text)
    ]
    assert any(
        "compute timing is not modeled" in assumption
        for assumption in report["assumptions"])

def test_model_name_override_is_recorded_beside_the_cluster_name(
        tmp_path: Path) -> None:
    mapping = _map(
        tmp_path, [_instance()],
        model_name="org/override-model")
    assert mapping.status == "OK"
    # The override resolves the model config only; the deployment keeps the
    # model name the cluster declares.
    assert mapping.workload["model_name"] == QWEN_NAME
    assert mapping.report["deployment"]["model_name"] == QWEN_NAME
    assert mapping.report["deployment"]["model_name_override"] \
        == "org/override-model"

def test_hbm_controllers_are_opt_in_and_count_per_rank(
        tmp_path: Path) -> None:
    mapping = _map(
        tmp_path, [_instance()], hbm_controllers_per_rank=2,
        link_width_bits=256)
    assert mapping.agents[0]["kind"] == "compute_tile"
    assert mapping.agents[0]["count"] == 2
    assert mapping.agents[1]["kind"] == "hbm_controller"
    assert mapping.agents[1]["count"] == 4
    assert mapping.agents[1]["protocol"] == "AXI"
    assert mapping.agents[1]["data_width"] == 256
    assert mapping.agents[1]["addr_width"] == 64

    request = mapping.to_request(topology=MESH_2)
    assert request["noc_controls"] == {"link_width": 256}
    assert request["physical"]["data_width"] == 256

def test_dp_ranks_multiply_across_instances(tmp_path: Path) -> None:
    mapping = _map(tmp_path, [
        _instance(dp_group="A", ep_size=1),
        _instance(dp_group="A", ep_size=1),
    ],
        model={"num_hidden_layers": 2, "hidden_size": 8,
               "num_attention_heads": 4, "num_key_value_heads": 4})
    # tp=2, dp=2, pp=1 -> 4 ranks; dense TP groups are two independent pairs.
    assert mapping.status == "OK"
    assert mapping.report["deployment"]["dp"] == 2
    assert mapping.report["deployment"]["ranks"] == 4
    assert mapping.workload["dp"] == 2
    assert mapping.workload["ep"] == 1
    assert mapping.agents[0]["count"] == 4
    assert mapping.report["derived"]["ep_decode_bytes"] == 0

# ---------------------------------------------------------------------------
# LLMServingSim parallelism inference
# ---------------------------------------------------------------------------

def test_moe_omitted_ep_size_defaults_to_tp(tmp_path: Path) -> None:
    instance = _instance(tp_size=2)
    instance.pop("ep_size")
    mapping = _map(tmp_path, [instance])
    assert mapping.status == "OK"
    assert mapping.report["deployment"]["ep"] == 2
    assert mapping.workload["ep"] == 1
    assert [c["traffic_class"]
            for c in mapping.workload["collectives"]] == [
        "tp_collective", "ep_dispatch", "ep_combine"]
    assert [c["kind"]
            for c in mapping.workload["collectives"]] == [
        "allreduce", "allgather", "reducescatter"]
    assert [c["payload_bytes"]
            for c in mapping.workload["collectives"]] == [
        8388608, 4456448, 8388608]

def test_resolved_ep_size_participates_in_homogeneity(
        tmp_path: Path) -> None:
    omitted = _instance(tp_size=2)
    omitted.pop("ep_size")
    declared = _instance(tp_size=2, ep_size=1)
    _assert_refused(
        _map(tmp_path, [omitted, declared]),
        "HETEROGENEOUS_CLUSTER_UNSUPPORTED")

def test_dp_ep_uses_resolved_ep_size(tmp_path: Path) -> None:
    first = _instance(tp_size=2, dp_group="A")
    first.pop("ep_size")
    second = _instance(tp_size=2, dp_group="A")
    second.pop("ep_size")
    _assert_refused(
        _map(tmp_path, [first, second]),
        "DP_EP_UNSUPPORTED")

def test_tp_size_inferred_from_num_npus(tmp_path: Path) -> None:
    instance = _instance()
    instance.pop("tp_size")
    instance.pop("ep_size")
    instance["num_npus"] = 2
    mapping = _map(tmp_path, [instance])
    assert mapping.status == "OK"
    assert mapping.report["deployment"]["tp"] == 2
    assert mapping.report["deployment"]["ep"] == 2
    assert mapping.report["deployment"]["ranks"] == 2
    assert len(mapping.workload["collectives"]) == 3

def test_tp_size_and_num_npus_that_agree_are_accepted(
        tmp_path: Path) -> None:
    mapping = _map(tmp_path, [_instance(tp_size=2, num_npus=2)])
    assert mapping.status == "OK"
    assert mapping.report["deployment"]["tp"] == 2

def test_num_npus_that_implies_pp_is_refused(tmp_path: Path) -> None:
    # config_builder would infer pp=2 from num_npus=4, tp_size=2; v1 refuses.
    _assert_refused(
        _map(tmp_path, [_instance(tp_size=2, num_npus=4)]),
        "PIPELINE_PARALLEL_UNSUPPORTED")

def test_num_npus_that_does_not_divide_by_tp_is_tp_invalid(
        tmp_path: Path) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(tp_size=2, num_npus=3)]),
        "TP_INVALID")

def test_rtxpro_single_shape_implies_pp_and_is_refused(
        tmp_path: Path) -> None:
    # third_party/llmservingsim/configs/cluster/rtxpro_single.json shape.
    _assert_refused(
        _map(tmp_path, [_instance(tp_size=1, num_npus=2, pp_size=1)]),
        "PIPELINE_PARALLEL_UNSUPPORTED")

def test_tp_size_and_num_npus_both_absent_default_to_one(
        tmp_path: Path) -> None:
    instance = _instance()
    instance.pop("tp_size")
    instance.pop("ep_size")
    _assert_refused(_map(tmp_path, [instance]), "NO_TRAFFIC")

# ---------------------------------------------------------------------------
# Source and serving-limit refusals
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("missing", ["cluster", "model", "trace"])
def test_missing_source_is_unreadable(
        tmp_path: Path, missing: str) -> None:
    cluster_path = tmp_path / "cluster.json"
    model_path = tmp_path / "model.json"
    trace_path = tmp_path / "trace.jsonl"
    if missing != "cluster":
        _write_json(cluster_path, {
            "nodes": [{"instances": [_instance()]}]})
    if missing != "model":
        model_path = QWEN_MODEL
    if missing != "trace":
        _write_trace(trace_path, DEFAULT_ROWS)
    _assert_refused(
        map_deployment(
            cluster_config=cluster_path,
            model_config=model_path,
            trace=trace_path),
        "SOURCE_UNREADABLE")

@pytest.mark.parametrize("broken", ["cluster", "model"])
def test_invalid_json_source_is_unreadable(
        tmp_path: Path, broken: str) -> None:
    cluster_path = tmp_path / "cluster.json"
    model_path = tmp_path / "model.json"
    trace_path = _write_trace(tmp_path / "trace.jsonl", DEFAULT_ROWS)
    if broken == "cluster":
        cluster_path.write_text("{not-json", encoding="utf-8")
        model_path = QWEN_MODEL
    else:
        _write_json(cluster_path, {
            "nodes": [{"instances": [_instance(tp_size=2, ep_size=1)]}]})
        model_path.write_text("{not-json", encoding="utf-8")
    _assert_refused(
        map_deployment(
            cluster_config=cluster_path,
            model_config=model_path,
            trace=trace_path),
        "SOURCE_UNREADABLE")

@pytest.mark.parametrize("row", [
    "{not-json}\n",
    json.dumps({"output_toks": 1, "arrival_time_ns": 0}) + "\n",
    json.dumps({"input_toks": 1, "arrival_time_ns": 0}) + "\n",
    json.dumps({"input_toks": -1, "output_toks": 1,
                "arrival_time_ns": 0}) + "\n",
    json.dumps({"input_toks": 1, "output_toks": 1,
                "arrival_time_ns": -1}) + "\n",
])
def test_malformed_trace_is_trace_invalid(
        tmp_path: Path, row: str) -> None:
    cluster_path = _write_json(tmp_path / "cluster.json", {
        "nodes": [{"instances": [_instance()]}]})
    trace_path = tmp_path / "trace.jsonl"
    trace_path.write_text(row, encoding="utf-8")
    _assert_refused(
        map_deployment(
            cluster_config=cluster_path,
            model_config=QWEN_MODEL,
            trace=trace_path),
        "TRACE_INVALID")

@pytest.mark.parametrize("field,value", [
    ("max_num_seqs", "many"),
    ("max_num_seqs", 1.5),
    ("max_num_batched_tokens", -1),
])
def test_invalid_serving_limit_is_typed(
        tmp_path: Path, field: str, value: Any) -> None:
    _assert_refused(
        _map(tmp_path, [_instance(**{field: value})]),
        "SERVING_LIMIT_INVALID")

@pytest.mark.parametrize(
    "field",
    ["max_num_seqs", "max_num_batched_tokens"])
def test_heterogeneous_serving_limits_are_refused(
        tmp_path: Path, field: str) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    first = _instance(
        model_name="synthetic/dense", tp_size=2, ep_size=1,
        dp_group="A", **{field: 8})
    second = _instance(
        model_name="synthetic/dense", tp_size=2, ep_size=1,
        dp_group="A", **{field: 64})
    _assert_refused(
        _map(tmp_path, [first, second], model=model),
        "HETEROGENEOUS_SERVING_LIMITS")

@pytest.mark.parametrize("kwargs", [
    {"num_reqs": -1},
    {"num_reqs": "2"},
    {"link_width_bits": 0},
    {"link_width_bits": "wide"},
    {"hbm_controllers_per_rank": -1},
    {"dtype_bytes": 0},
    {"dtype_bytes": "two"},
])
def test_invalid_caller_argument_is_typed(
        tmp_path: Path, kwargs: dict[str, Any]) -> None:
    _assert_refused(
        _map(tmp_path, [_instance()], **kwargs),
        "ARGUMENT_INVALID")

# ---------------------------------------------------------------------------
# LLMServingSim zero-valued serving limits
# ---------------------------------------------------------------------------

def test_zero_max_num_batched_tokens_caps_at_max_position_embeddings(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
        "max_position_embeddings": 4096,
    }
    mapping = _map(
        tmp_path,
        [_instance(model_name="synthetic/dense", tp_size=2, ep_size=1,
                   max_num_batched_tokens=0)],
        model=model)
    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 4096
    assert mapping.report["derived"]["tp_prefill_bytes"] == 4096 * 8 * 2
    assert any("max_num_batched_tokens=0" in assumption
               and "max_position_embeddings=4096" in assumption
               for assumption in mapping.report["assumptions"])

def test_zero_max_num_batched_tokens_without_max_position_defaults(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    mapping = _map(
        tmp_path,
        [_instance(model_name="synthetic/dense", tp_size=2, ep_size=1,
                   max_num_batched_tokens=0)],
        model=model)
    assert mapping.status == "OK"
    assert mapping.report["derived"]["prefill_chunk_tokens"] == 2048
    assert any("max_num_batched_tokens=0" in assumption
               and "no usable max_position_embeddings" in assumption
               and "2048" in assumption
               for assumption in mapping.report["assumptions"])

def test_integral_float_num_reqs_is_accepted(tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    mapping = _map(
        tmp_path,
        [_instance(model_name="synthetic/dense", tp_size=2, ep_size=1)],
        model=model, num_reqs=2.0)
    assert mapping.status == "OK"
    assert mapping.report["request"]["num_reqs"] == 2


def test_zero_max_num_seqs_uses_selected_request_count(
        tmp_path: Path) -> None:
    model = {
        "num_hidden_layers": 2,
        "hidden_size": 8,
        "num_attention_heads": 4,
        "num_key_value_heads": 4,
    }
    mapping = _map(
        tmp_path,
        [_instance(model_name="synthetic/dense", tp_size=2, ep_size=1,
                   max_num_seqs=0)],
        model=model, num_reqs=1)
    assert mapping.status == "OK"
    assert mapping.report["request"]["num_reqs"] == 1
    assert mapping.report["derived"]["decode_batch"] == 1
    assert mapping.report["derived"]["tp_decode_bytes"] == 1 * 8 * 2
    assert any("max_num_seqs=0 means unlimited" in assumption
               and "num_reqs" in assumption
               and "1 selected request" in assumption
               for assumption in mapping.report["assumptions"])
