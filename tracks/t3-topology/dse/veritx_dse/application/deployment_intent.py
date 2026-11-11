"""LLMServingSim deployment -> v4 workload intent (v1).

Rationale: docs/design/reviews/deployment-intent-mapping.md.

The serving simulator owns model, hardware and serving semantics. This module
does NOT re-model them: it translates a supported deployment into exactly the
intent primitives the fabric compiler already consumes, and refuses everything
it cannot represent instead of silently adjusting it.

Two laws make the translation honest:

* the intent models the PREFILL CHUNK only. Decode volumes are reported but
  are not emitted as a second operation (the v4 collective has no phase or
  repetition axis);
* EP is a MODE over the TP ranks, not a rank multiplier. The intent carries
  ``ep = 1`` and expresses expert traffic as all-gather/reduce-scatter over
  TP, matching LLMServingSim's ``allgather_reducescatter`` backend.

Nothing here invents compute durations or SLOs. ``compute`` stays empty and
``requirements`` stays empty; those belong to a measured profile or the
project.
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from veritx_dse.core.paths import LLMSIM_DIR

SCHEMA = "veritx/deployment-mapping/1"

#: Default prefill chunk when the instance declares no positive override.
DEFAULT_MAX_NUM_BATCHED_TOKENS = 2048
#: Default decode batch when the instance declares no positive override.
DEFAULT_MAX_NUM_SEQS = 128
#: Default element width; an explicit ``dtype_bytes`` always wins.
DEFAULT_DTYPE_BYTES = 2

_EXPERTS_KEYS = ("num_experts", "num_local_experts", "n_routed_experts")
_TOP_K_KEYS = ("num_experts_per_tok", "num_experts_per_token", "moe_k")

_TORCH_DTYPE_BYTES = {
    "bfloat16": 2,
    "bf16": 2,
    "float16": 2,
    "fp16": 2,
    "half": 2,
    "float32": 4,
    "fp32": 4,
    "float": 4,
    "float64": 8,
    "fp64": 8,
    "double": 8,
    "int8": 1,
    "uint8": 1,
    "fp8": 1,
    "float8": 1,
    "e4m3fn": 1,
    "e5m2": 1,
}

@dataclass(frozen=True)
class MappingIssue:
    """One typed reason a deployment cannot be represented.

    ``path`` names the source that carries the offending fact (cluster, model
    or trace config), or ``None`` when the issue is about the combination.
    """

    code: str
    message: str
    path: str | None = None

@dataclass(frozen=True)
class DeploymentMapping:
    """The translated fragment plus the report that justifies it.

    ``workload`` is ``None`` exactly when ``status == "REFUSED"``. ``agents``,
    ``requirements`` and ``compute`` are intent primitives; the caller supplies
    the fabric (``topology``, ``noc_controls`` and ``physical``) at assembly
    time.
    """

    status: str
    report: dict[str, Any]
    workload: dict[str, Any] | None
    agents: tuple[dict[str, Any], ...] = ()
    requirements: tuple[dict[str, Any], ...] = ()
    compute: dict[str, Any] = field(
        default_factory=lambda: {"stages": []})

    def to_request(
        self,
        *,
        topology: dict[str, Any],
        noc_controls: dict[str, Any] | None = None,
        physical: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble a schema-4 request; raises ``ValueError`` when REFUSED.

        ``topology`` is REQUIRED: schema 4 has no implicit "None means mesh".
        ``noc_controls`` and ``physical`` default to the widths this mapping
        already declared, never to a hidden design choice.
        """
        if self.status != "OK" or self.workload is None:
            code = self._refusal_code()
            raise ValueError(
                "cannot assemble a request from a REFUSED deployment "
                f"mapping ({code})")
        link_width = self._link_width_bits()
        return {
            "schema_version": 4,
            "compiler_semantics_version": 4,
            "workload": deepcopy(self.workload),
            "agents": [dict(agent) for agent in self.agents],
            "requirements": [dict(req) for req in self.requirements],
            "dependencies": {},
            "topology": deepcopy(topology),
            "noc_controls": (
                deepcopy(noc_controls) if noc_controls is not None
                else {"link_width": link_width}),
            "address_map": {"ranges": []},
            "physical": (
                deepcopy(physical) if physical is not None else {
                    "clock_freq_mhz": 1000.0,
                    "data_width": link_width,
                    "process_node_nm": 7,
                    "num_power_domains": 1,
                }),
            "compute": deepcopy(self.compute),
        }

    def _refusal_code(self) -> str:
        issues = self.report.get("issues") or ()
        if issues:
            return str(issues[0].get("code", "UNKNOWN"))
        return "UNKNOWN"

    def _link_width_bits(self) -> int:
        for agent in self.agents:
            if agent.get("kind") == "compute_tile":
                width = agent.get("data_width")
                if isinstance(width, int) and not isinstance(width, bool):
                    return width
        return 128

class _IncompleteGeometry(ValueError):
    """The model config does not determine the required intent geometry."""

class _Refusal(ValueError):
    """An internal typed refusal carrying the design's issue code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message

class _TraceInvalid(ValueError):
    """A trace line is not a well-formed LLMServingSim request row."""

@dataclass(frozen=True)
class _ModelGeometry:
    layers: int
    hidden: int
    heads: int
    kv_heads: int
    head_dim: int
    experts: int | None
    top_k: int | None
    dtype_bytes: int
    attention: str
    kv_bytes_per_token_per_layer: int
    indexer_bytes_per_token_per_layer: int | None
    weights_bytes: int | None
    weights_note: str | None = None

    @property
    def is_moe(self) -> bool:
        return self.experts is not None

    def to_report(self) -> dict[str, Any]:
        report: dict[str, Any] = {
            "layers": self.layers,
            "hidden": self.hidden,
            "heads": self.heads,
            "kv_heads": self.kv_heads,
            "head_dim": self.head_dim,
            "attention": self.attention,
            "kv_bytes_per_token_per_layer":
                self.kv_bytes_per_token_per_layer,
            "experts": self.experts,
            "top_k": self.top_k,
            "dtype_bytes": self.dtype_bytes,
            "weights_bytes": self.weights_bytes,
        }
        if self.indexer_bytes_per_token_per_layer is not None:
            report["indexer_bytes_per_token_per_layer"] = (
                self.indexer_bytes_per_token_per_layer)
        return report

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()

def _source(path: Path | None, data: bytes | None) -> dict[str, Any]:
    return {
        "path": str(path) if path is not None else None,
        "sha256": _sha256(data) if data is not None else None,
    }

def _read_source_bytes(path: Path) -> tuple[bytes | None, OSError | None]:
    try:
        return path.read_bytes(), None
    except OSError as exc:
        return None, exc

def _parse_json_source(data: bytes) -> tuple[Any, str | None]:
    try:
        return json.loads(data.decode("utf-8")), None
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, str(exc)

def _require_int(value: Any, where: str, *, minimum: int = 1) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        else:
            raise ValueError(f"{where} must be an integer, got {value!r}")
    if value < minimum:
        raise ValueError(f"{where} must be >= {minimum}, got {value!r}")
    return value

def _argument_int(value: Any, where: str, *, minimum: int = 1) -> int:
    try:
        return _require_int(value, where, minimum=minimum)
    except ValueError as exc:
        raise _Refusal("ARGUMENT_INVALID", str(exc)) from exc

def _first_present(doc: Mapping[str, Any],
                    keys: Iterable[str]) -> Any:
    for key in keys:
        if key in doc and doc[key] is not None:
            return doc[key]
    return None

def _default_model_path(model_name: str) -> Path:
    return LLMSIM_DIR / "configs" / "model" / f"{model_name}.json"

def _model_max_position_embeddings(model_doc: Any) -> int | None:
    """The model's usable max_position_embeddings, or None when absent."""
    if not isinstance(model_doc, Mapping):
        return None
    value = model_doc.get("max_position_embeddings")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if isinstance(value, float) and not value.is_integer():
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None

def _architecture_declares_moe(model_doc: Mapping[str, Any]) -> bool:
    """Whether the config's own architecture names a mixture of experts.

    Used only to REFUSE an incomplete MoE config: the family itself is still
    decided by "declares experts".
    """
    values: list[str] = []
    architectures = model_doc.get("architectures")
    if isinstance(architectures, list):
        values.extend(
            value for value in architectures if isinstance(value, str))
    model_type = model_doc.get("model_type")
    if isinstance(model_type, str):
        values.append(model_type)
    text = " ".join(values).lower()
    return any(marker in text for marker in ("moe", "mixtral", "phimoe"))

def _resolve_geometry(model_doc: Any,
                      dtype_bytes: int | None) -> _ModelGeometry:
    if not isinstance(model_doc, dict):
        raise _IncompleteGeometry("model config must be a JSON object")

    def geometry_int(value: Any, where: str) -> int:
        try:
            return _require_int(value, where)
        except ValueError as exc:
            raise _IncompleteGeometry(str(exc)) from exc

    layers = _first_present(
        model_doc, ("num_hidden_layers", "n_layers", "layers"))
    hidden = _first_present(model_doc, ("hidden_size", "hidden"))
    heads = _first_present(
        model_doc, ("num_attention_heads", "n_heads", "heads"))
    missing = [
        name for name, value in (
            ("num_hidden_layers", layers),
            ("hidden_size", hidden),
            ("num_attention_heads", heads)) if value is None]
    if missing:
        raise _IncompleteGeometry(
            "model config is missing required geometry: "
            + ", ".join(missing))

    layers = geometry_int(layers, "num_hidden_layers")
    hidden = geometry_int(hidden, "hidden_size")
    heads = geometry_int(heads, "num_attention_heads")

    kv_heads = _first_present(
        model_doc, ("num_key_value_heads", "kv_heads", "n_kv_heads"))
    kv_heads = heads if kv_heads is None else geometry_int(
        kv_heads, "num_key_value_heads")

    head_dim = _first_present(
        model_doc, ("head_dim", "attention_head_dim"))
    if head_dim is None:
        if hidden % heads != 0:
            raise _IncompleteGeometry(
                f"hidden_size={hidden} is not divisible by "
                f"num_attention_heads={heads}, and the model config "
                "declares no head_dim")
        head_dim = hidden // heads
    head_dim = geometry_int(head_dim, "head_dim")

    experts = _first_present(model_doc, _EXPERTS_KEYS)
    top_k = _first_present(model_doc, _TOP_K_KEYS)
    if experts is None:
        if top_k is not None:
            raise _IncompleteGeometry(
                "model config declares an expert top-k without a number of "
                "experts")
        if _architecture_declares_moe(model_doc):
            raise _IncompleteGeometry(
                "model config declares a mixture-of-experts architecture "
                "but no expert count")
    else:
        experts = geometry_int(experts, "num_experts")
        if top_k is None:
            raise _IncompleteGeometry(
                "model config declares experts but no expert top-k "
                "(num_experts_per_tok)")
        top_k = geometry_int(top_k, "num_experts_per_tok")
        if top_k > experts:
            raise _IncompleteGeometry(
                f"num_experts_per_tok={top_k} exceeds "
                f"num_experts={experts}")

    if dtype_bytes is not None:
        resolved_dtype = _require_int(dtype_bytes, "dtype_bytes")
    else:
        torch_dtype = model_doc.get("torch_dtype")
        if isinstance(torch_dtype, str) and torch_dtype:
            resolved_dtype = _TORCH_DTYPE_BYTES.get(
                torch_dtype.lower(), DEFAULT_DTYPE_BYTES)
        else:
            resolved_dtype = DEFAULT_DTYPE_BYTES

    # MLA (Multi-head Latent Attention) keeps one compressed KV latent plus a
    # decoupled RoPE key per token and layer. The latent is replicated across
    # TP ranks, so it is NOT multiplied by kv_heads and NOT divided by tp.
    # DeepSeek-V3.2-Exp adds the sparse attention indexer: fp8 keys plus one
    # fp32 scale per 128 index elements, mirroring LLMServingSim's memory
    # model.
    kv_lora_rank = model_doc.get("kv_lora_rank")
    indexer_bytes: int | None = None
    if kv_lora_rank is not None:
        kv_lora_rank = geometry_int(kv_lora_rank, "kv_lora_rank")
        qk_rope_head_dim = model_doc.get("qk_rope_head_dim")
        if qk_rope_head_dim is None:
            raise _IncompleteGeometry(
                "model config declares kv_lora_rank but no qk_rope_head_dim; "
                "MLA KV geometry is not determined")
        qk_rope_head_dim = geometry_int(
            qk_rope_head_dim, "qk_rope_head_dim")
        attention = "mla"
        kv_bytes_per_token_per_layer = (
            kv_lora_rank + qk_rope_head_dim) * resolved_dtype
        index_topk = model_doc.get("index_topk")
        index_head_dim = model_doc.get("index_head_dim")
        indexer_bytes = 0
        if index_topk is not None and index_head_dim is not None:
            geometry_int(index_topk, "index_topk")
            index_head_dim = geometry_int(index_head_dim, "index_head_dim")
            indexer_bytes = (
                index_head_dim * 1 + (index_head_dim // 128) * 4)
            kv_bytes_per_token_per_layer += indexer_bytes
    else:
        attention = "gqa"
        kv_bytes_per_token_per_layer = (
            2 * kv_heads * head_dim * resolved_dtype)

    raw_parameters = model_doc.get("num_parameters")
    weights_bytes: int | None = None
    weights_note: str | None = None
    if raw_parameters is not None:
        if isinstance(raw_parameters, bool) \
                or not isinstance(raw_parameters, (int, float)) \
                or raw_parameters < 0 \
                or (isinstance(raw_parameters, float)
                    and not raw_parameters.is_integer()):
            weights_note = (
                f"num_parameters={raw_parameters!r} is not a non-negative "
                "integer; weights_bytes is not reported (no truncation).")
        else:
            weights_bytes = int(raw_parameters) * resolved_dtype

    return _ModelGeometry(
        layers=layers, hidden=hidden, heads=heads, kv_heads=kv_heads,
        head_dim=head_dim, experts=experts, top_k=top_k,
        dtype_bytes=resolved_dtype, attention=attention,
        kv_bytes_per_token_per_layer=kv_bytes_per_token_per_layer,
        indexer_bytes_per_token_per_layer=indexer_bytes,
        weights_bytes=weights_bytes,
        weights_note=weights_note)

def describe_model(model_doc: Mapping[str, Any], *,
                   dtype_bytes: int | None = None) -> dict[str, Any]:
    """The public geometry/family view of one model config.

    Raises ``ValueError`` when the config does not determine the geometry the
    intent needs. Catalog callers must treat that as an unusable entry rather
    than inventing fields.
    """
    doc: Any = (dict(model_doc) if isinstance(model_doc, Mapping)
                else model_doc)
    geometry = _resolve_geometry(doc, dtype_bytes)
    return {
        "model_family": (
            "mixture_of_experts" if geometry.is_moe
            else "dense_transformer"),
        "geometry": {
            "layers": geometry.layers,
            "hidden": geometry.hidden,
            "heads": geometry.heads,
            "kv_heads": geometry.kv_heads,
            "head_dim": geometry.head_dim,
            "attention": geometry.attention,
            "kv_bytes_per_token_per_layer":
                geometry.kv_bytes_per_token_per_layer,
            **({
                "indexer_bytes_per_token_per_layer":
                    geometry.indexer_bytes_per_token_per_layer,
            } if geometry.indexer_bytes_per_token_per_layer is not None
               else {}),
            "experts": geometry.experts,
            "top_k": geometry.top_k,
            "dtype_bytes": geometry.dtype_bytes,
        },
    }

def _flatten_instances(cluster: Any) -> list[dict[str, Any]]:
    if not isinstance(cluster, dict):
        raise ValueError("cluster config must be a JSON object")
    nodes = cluster.get("nodes") or []
    if not isinstance(nodes, list):
        raise ValueError("cluster config nodes must be a JSON array")
    instances: list[dict[str, Any]] = []
    for node_index, node in enumerate(nodes):
        if not isinstance(node, dict):
            raise ValueError(f"cluster node {node_index} must be an object")
        rows = node.get("instances") or []
        if not isinstance(rows, list):
            raise ValueError(
                f"cluster node {node_index} instances must be an array")
        for row in rows:
            if not isinstance(row, dict):
                raise ValueError(
                    "cluster instance rows must be JSON objects")
            instances.append(row)
    return instances

def _instance_value(instance: Mapping[str, Any], key: str,
                    default: Any) -> Any:
    value = instance.get(key)
    return default if value is None else value

def _dp_group(instance: Mapping[str, Any]) -> str:
    value = instance.get("dp_group")
    if value is None:
        return ""
    return str(value).strip()

def _resolve_pp(instance: Mapping[str, Any]) -> int:
    """Resolve pp_size. v1 refuses anything but a single pipeline stage."""
    raw = instance.get("pp_size")
    if raw is None:
        return 1
    try:
        pp = _require_int(raw, "pp_size")
    except ValueError as exc:
        raise _Refusal(
            "PIPELINE_PARALLEL_UNSUPPORTED", str(exc)) from exc
    if pp != 1:
        raise _Refusal(
            "PIPELINE_PARALLEL_UNSUPPORTED",
            "pipeline parallelism is not representable in v1 "
            f"(instance declares pp_size={pp})")
    return pp

def _resolve_tp(instance: Mapping[str, Any], pp: int) -> int:
    """Resolve tp_size from tp_size / num_npus, mirroring config_builder.

    ``num_npus = tp_size * pp_size``. Missing values are inferred exactly as
    LLMServingSim does; an inconsistent pair is refused rather than silently
    preferred.
    """
    raw_tp = instance.get("tp_size")
    raw_npus = instance.get("num_npus")
    tp: int | None = None
    num_npus: int | None = None
    if raw_tp is not None:
        try:
            tp = _require_int(raw_tp, "tp_size")
        except ValueError as exc:
            raise _Refusal("TP_INVALID", str(exc)) from exc
    if raw_npus is not None:
        try:
            num_npus = _require_int(raw_npus, "num_npus")
        except ValueError as exc:
            raise _Refusal("TP_INVALID", str(exc)) from exc

    if tp is None and num_npus is None:
        # config_builder defaults both parallel degrees to 1.
        return 1
    if tp is None:
        assert num_npus is not None
        if num_npus % pp != 0:
            raise _Refusal(
                "TP_INVALID",
                f"num_npus={num_npus} is not divisible by pp_size={pp}")
        return num_npus // pp
    if num_npus is None or num_npus == tp * pp:
        return tp
    if num_npus % tp == 0:
        inferred_pp = num_npus // tp
        raise _Refusal(
            "PIPELINE_PARALLEL_UNSUPPORTED",
            f"num_npus={num_npus} with tp_size={tp} implies "
            f"pp_size={inferred_pp}; pipeline parallelism is not "
            "representable in v1")
    raise _Refusal(
        "TP_INVALID",
        f"num_npus={num_npus} is inconsistent with "
        f"tp_size={tp} * pp_size={pp} = {tp * pp} and is not divisible "
        f"by tp_size={tp}")

def _resolve_ep(instance: Mapping[str, Any], tp: int, is_moe: bool) -> int:
    """Resolve ep_size after model geometry is known.

    LLMServingSim defaults ep_size to tp_size for MoE and to 1 for dense.
    """
    raw = instance.get("ep_size")
    if raw is None:
        return tp if is_moe else 1
    try:
        return _require_int(raw, "ep_size")
    except ValueError as exc:
        raise _Refusal("EP_INVALID", str(exc)) from exc

def _serving_limit(instance: Mapping[str, Any], key: str) -> int | None:
    """Read one non-negative integer serving limit, or None when absent.

    ``0`` is meaningful for both ``max_num_seqs`` (unlimited) and
    ``max_num_batched_tokens`` (cap at max_position_embeddings), so it must
    survive this parse. Negative, fractional and non-numeric values are
    refused as SERVING_LIMIT_INVALID.
    """
    if key not in instance or instance[key] is None:
        return None
    value = instance[key]
    if isinstance(value, bool) \
            or not isinstance(value, (int, float)) \
            or (isinstance(value, float) and not value.is_integer()):
        raise _Refusal(
            "SERVING_LIMIT_INVALID",
            f"{key} must be a non-negative integer, got {value!r}")
    parsed = int(value)
    if parsed < 0:
        raise _Refusal(
            "SERVING_LIMIT_INVALID",
            f"{key} must be a non-negative integer, got {value!r}")
    return parsed

def _effective_prefill_limit(
        raw: int | None, model_doc: Any) -> tuple[int, str | None]:
    """Resolve max_num_batched_tokens, then clamp to max_position.

    LLMServingSim's scheduler computes
    ``min(max_num_batched_tokens, max_position_embeddings)`` for every
    declaration, including the default and the ``0 = unlimited`` form.
    """
    max_position = _model_max_position_embeddings(model_doc)
    if raw is None:
        value = DEFAULT_MAX_NUM_BATCHED_TOKENS
        note: str | None = (
            "max_num_batched_tokens is absent; the prefill chunk defaults "
            f"to {DEFAULT_MAX_NUM_BATCHED_TOKENS}.")
    elif raw == 0:
        if max_position is None:
            return DEFAULT_MAX_NUM_BATCHED_TOKENS, (
                "max_num_batched_tokens=0 means unlimited in "
                "LLMServingSim, but the model declares no usable "
                "max_position_embeddings; the prefill chunk defaults to "
                f"{DEFAULT_MAX_NUM_BATCHED_TOKENS}.")
        return max_position, (
            "max_num_batched_tokens=0 means unlimited in LLMServingSim; "
            f"the prefill chunk is capped at "
            f"max_position_embeddings={max_position}.")
    else:
        value = raw
        note = None

    if max_position is not None and value > max_position:
        clamp_note = (
            "The prefill chunk is clamped to "
            f"max_position_embeddings={max_position}.")
        note = f"{note} {clamp_note}" if note else clamp_note
        value = max_position
    return value, note

def _decode_limit_policy(raw: int | None, num_seqs: int) -> int:
    """The per-instance max_num_seqs policy used for agreement.

    ``0`` means unlimited and therefore resolves to the selected request
    count; absent defaults to 128; a positive declaration is compared before
    the trace bounds the actual batch. This keeps ``0`` and a positive cap
    equal to ``num_reqs`` equivalent while still refusing declared 8 vs 64.
    """
    if raw is None:
        return DEFAULT_MAX_NUM_SEQS
    if raw == 0:
        return num_seqs
    return raw

def _effective_decode_limit(
        raw: int | None, num_seqs: int) -> tuple[int, str | None]:
    """Resolve max_num_seqs, then bound the batch by the selected requests."""
    if raw is None:
        if DEFAULT_MAX_NUM_SEQS > num_seqs:
            return num_seqs, (
                "max_num_seqs is absent; the decode batch defaults to "
                f"{DEFAULT_MAX_NUM_SEQS} and is clamped to the {num_seqs} "
                "selected request(s).")
        return DEFAULT_MAX_NUM_SEQS, (
            "max_num_seqs is absent; the decode batch defaults to "
            f"{DEFAULT_MAX_NUM_SEQS}.")
    if raw == 0:
        return num_seqs, (
            "max_num_seqs=0 means unlimited in LLMServingSim; the decode "
            f"batch is num_reqs (all {num_seqs} selected request(s)).")
    if raw > num_seqs:
        return num_seqs, (
            f"max_num_seqs={raw} is clamped to the {num_seqs} selected "
            "request(s).")
    return raw, None

def _read_trace_rows(data: bytes, path: Path) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _TraceInvalid(
            f"trace is not UTF-8 JSONL: {path}: {exc}") from exc
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            raise _TraceInvalid(
                f"trace row {line_number} is not valid JSON: {exc}") from exc
        if not isinstance(row, dict):
            raise _TraceInvalid(
                f"trace row {line_number} must be a JSON object")
        rows.append(row)
    return rows

def _trace_int(row: Mapping[str, Any], key: str, line_number: int,
               default: int | None = None) -> int:
    if key not in row:
        if default is not None:
            return default
        raise _TraceInvalid(
            f"trace row {line_number} is missing {key!r}")
    value = row[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise _TraceInvalid(
            f"trace row {line_number} field {key!r} must be an integer >= 0")
    if isinstance(value, float) and not value.is_integer():
        raise _TraceInvalid(
            f"trace row {line_number} field {key!r} must be an integer >= 0")
    parsed = int(value)
    if parsed < 0:
        raise _TraceInvalid(
            f"trace row {line_number} field {key!r} must be an integer >= 0")
    return parsed

def _validate_trace_rows(rows: list[dict[str, Any]]) -> None:
    for line_number, row in enumerate(rows, 1):
        _trace_int(row, "input_toks", line_number)
        _trace_int(row, "output_toks", line_number)
        if "arrival_time_ns" in row:
            _trace_int(row, "arrival_time_ns", line_number)

def _request_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    input_tokens = [
        _trace_int(row, "input_toks", index)
        for index, row in enumerate(rows, 1)]
    output_tokens = [
        _trace_int(row, "output_toks", index)
        for index, row in enumerate(rows, 1)]
    arrivals = [
        _trace_int(row, "arrival_time_ns", index, default=0)
        for index, row in enumerate(rows, 1)]
    count = len(rows)
    return {
        "num_reqs": count,
        "isl_mean": sum(input_tokens) / count,
        "osl_mean": sum(output_tokens) / count,
        "arrival_span_ns": max(arrivals) - min(arrivals),
    }

def _hardware_assumption(hardware: str) -> str:
    path = LLMSIM_DIR / "profiler" / "perf" / hardware / "hardware.yaml"
    if path.is_file():
        return (
            f"Hardware profile bundle present at {path}; not consumed: "
            "compute timing is not modeled.")
    return (
        f"No hardware profile bundle at {path}; not required: compute "
        "timing is not modeled.")

def _static_assumptions() -> list[str]:
    """Facts that are true of every mapping, OK or REFUSED."""
    return [
        "The intent models the prefill chunk; decode volumes are reported "
        "but not emitted as a second operation.",
        "compute timing is not modeled: the mapping declares no compute "
        "stages and invents no per-layer durations.",
        "requirements (SLO/QoS) are not modeled: the mapping emits none.",
        "EP is a mode over the TP ranks, not a rank multiplier; the intent "
        "carries ep=1 and expresses expert traffic as all-gather/reduce-"
        "scatter over TP when ep_size == tp_size.",
    ]

def _assumptions(
    *,
    geometry: _ModelGeometry,
    prefill_chunk: int,
    decode_batch: int,
    hbm_controllers_per_rank: int,
    hardware: str,
    num_reqs_note: str | None,
    dtype_note: str | None,
    weights_note: str | None,
    prefill_note: str | None,
    decode_note: str | None,
) -> list[str]:
    assumptions = [
        f"Effective prefill chunk is {prefill_chunk} tokens and decode "
        f"batch is {decode_batch} requests.",
        "TP allreduce payload is prefill_chunk * hidden * dtype_bytes; EP "
        "dispatch is an all-gather of max(1, prefill_chunk // ep_size) * "
        "(hidden + num_experts) * dtype_bytes, and EP combine is a "
        "reduce-scatter of prefill_chunk * hidden * dtype_bytes.",
        "ep_decode_bytes is the decode EP dispatch (all-gather) volume; the "
        "decode combine volume is decode_batch * hidden * dtype_bytes.",
        "The v4 parser defaults the legacy serving_mode field to mixed; the "
        "mapping does not set it.",
        f"HBM controllers are a fabric choice, not a serving fact: "
        f"hbm_controllers_per_rank={hbm_controllers_per_rank}.",
        "The supplied topology must seat ranks + hbm_controllers agents; a "
        "mesh side length sized only for ranks is insufficient when HBM "
        "controllers are added.",
        _hardware_assumption(hardware),
        "The model config content is not cross-checked against the cluster "
        "model_name; the caller supplies the matching config.",
    ]
    if not geometry.is_moe:
        assumptions.append(
            "The model declares no experts; no expert-parallel traffic is "
            "emitted.")
    if prefill_note is not None:
        assumptions.append(prefill_note)
    if decode_note is not None:
        assumptions.append(decode_note)
    if num_reqs_note is not None:
        assumptions.append(num_reqs_note)
    if dtype_note is not None:
        assumptions.append(dtype_note)
    if weights_note is not None:
        assumptions.append(weights_note)
    return assumptions

def _refused(report: dict[str, Any], issue: MappingIssue) -> DeploymentMapping:
    report["status"] = "REFUSED"
    report["issues"] = [asdict(issue)]
    return DeploymentMapping(
        status="REFUSED", report=report, workload=None,
        agents=(), requirements=(), compute={"stages": []})

def _intent_collective(kind: str, dimension: str, payload_bytes: int,
                       traffic_class: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "dimension": dimension,
        "payload_bytes": payload_bytes,
        "traffic_class": traffic_class,
        "source_rank": None,
    }

def _document_digest(value: Any) -> str | None:
    """A stable sha256 for an in-memory JSON document (no file bytes exist)."""
    try:
        data = json.dumps(
            value, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")
    except (TypeError, ValueError):
        return None
    return _sha256(data)

def _report_skeleton(sources: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": SCHEMA,
        "status": "REFUSED",
        "sources": dict(sources),
        "deployment": None,
        "model": None,
        "request": None,
        "derived": None,
        "assumptions": _static_assumptions(),
        "issues": [],
    }

def _normalize_arguments(
    *,
    num_reqs: int | None,
    dtype_bytes: int | None,
    link_width_bits: int,
    hbm_controllers_per_rank: int,
) -> tuple[int | None, int | None, int, int]:
    """Validate caller arguments in the locked order (arguments first)."""
    link_width_bits = _argument_int(link_width_bits, "link_width_bits")
    hbm_controllers_per_rank = _argument_int(
        hbm_controllers_per_rank, "hbm_controllers_per_rank", minimum=0)
    if dtype_bytes is not None:
        dtype_bytes = _argument_int(dtype_bytes, "dtype_bytes")
    if num_reqs is not None:
        num_reqs = _argument_int(num_reqs, "num_reqs", minimum=0)
    return num_reqs, dtype_bytes, link_width_bits, hbm_controllers_per_rank

def _map_document(
    *,
    cluster: Any,
    model: Any,
    trace_rows: list[dict[str, Any]] | None,
    trace_rows_loader: Callable[[], list[dict[str, Any]]] | None,
    sources: Mapping[str, Any],
    cluster_source: str,
    model_source: str,
    trace_source: str,
    num_reqs: int | None,
    dtype_bytes: int | None,
    link_width_bits: int,
    hbm_controllers_per_rank: int,
    model_name: str | None,
) -> DeploymentMapping:
    """Shared semantic body. Caller arguments are already validated."""
    model_doc = model
    report = _report_skeleton(sources)

    def refuse(code: str, message: str,
               path: str | None = None) -> DeploymentMapping:
        return _refused(report, MappingIssue(
            code=code, message=message, path=path))

    try:
        instances = _flatten_instances(cluster)
    except ValueError as exc:
        return refuse(
            "SOURCE_UNREADABLE",
            f"cluster config is invalid: {exc}",
            cluster_source)

    if not instances:
        return refuse(
            "NO_INSTANCES",
            "cluster config declares no serving instances",
            cluster_source)

    for index, instance in enumerate(instances):
        hardware_value = instance.get("hardware")
        if not isinstance(hardware_value, str) or not hardware_value.strip():
            return refuse(
                "HARDWARE_REQUIRED",
                f"instance {index} omits the required hardware profile",
                cluster_source)

    # ---- refusal order follows the locked design ------------------------
    for index, instance in enumerate(instances):
        if instance.get("pd_type") is not None:
            return refuse(
                "PD_POOLS_UNSUPPORTED",
                "prefill/decode pools are not representable in v1 "
                f"(instance {index} declares pd_type="
                f"{instance.get('pd_type')!r})",
                cluster_source)

    pp_values: list[int] = []
    for instance in instances:
        try:
            pp_values.append(_resolve_pp(instance))
        except _Refusal as exc:
            return refuse(exc.code, exc.message, cluster_source)

    tp_values: list[int] = []
    for index, instance in enumerate(instances):
        try:
            tp_values.append(_resolve_tp(instance, pp_values[index]))
        except _Refusal as exc:
            return refuse(exc.code, exc.message, cluster_source)

    try:
        geometry = _resolve_geometry(model_doc, dtype_bytes)
    except _IncompleteGeometry as exc:
        return refuse("MODEL_CONFIG_INCOMPLETE", str(exc), model_source)

    ep_values: list[int] = []
    for index, instance in enumerate(instances):
        try:
            ep_values.append(_resolve_ep(
                instance, tp_values[index], geometry.is_moe))
        except _Refusal as exc:
            return refuse(exc.code, exc.message, cluster_source)

    signatures = []
    for index, instance in enumerate(instances):
        signatures.append((
            str(_instance_value(instance, "model_name", "")),
            str(_instance_value(instance, "hardware", "")),
            tp_values[index],
            ep_values[index],
            pp_values[index],
        ))
    if any(signature != signatures[0] for signature in signatures[1:]):
        return refuse(
            "HETEROGENEOUS_CLUSTER_UNSUPPORTED",
            "v1 requires one homogeneous instance group over "
            "model_name/hardware/tp_size/ep_size/pp_size; instances disagree: "
            f"{sorted(set(signatures), key=repr)}",
            cluster_source)

    first = instances[0]
    model_name_value = str(_instance_value(first, "model_name", ""))
    hardware = str(_instance_value(first, "hardware", ""))
    tp = tp_values[0]
    ep_size = ep_values[0]
    pp = pp_values[0]

    dp_groups = [_dp_group(instance) for instance in instances]
    if len(instances) > 1:
        shared = set(dp_groups)
        if "" in shared or len(shared) != 1:
            return refuse(
                "DP_GROUP_REQUIRED",
                "several instances must share one non-empty dp_group; "
                f"declared groups are {dp_groups!r}",
                cluster_source)
        dp = len(instances)
    else:
        dp = 1
    ranks = tp * dp * pp

    report["deployment"] = {
        "model_name": model_name_value,
        **({"model_name_override": model_name}
           if model_name and model_name != model_name_value else {}),
        "hardware": hardware,
        "pd_type": None,
        "tp": tp,
        "dp": dp,
        "ep": ep_size,
        "pp": pp,
        "instances": len(instances),
        "ranks": ranks,
    }

    raw_dtype = model_doc.get("torch_dtype") \
        if isinstance(model_doc, dict) else None
    dtype_note = None
    if dtype_bytes is None and isinstance(raw_dtype, str) and raw_dtype:
        if raw_dtype.lower() in _TORCH_DTYPE_BYTES:
            dtype_note = (
                f"dtype_bytes={geometry.dtype_bytes} resolved from the "
                f"model config torch_dtype={raw_dtype!r}.")
        else:
            dtype_note = (
                f"torch_dtype={raw_dtype!r} is not recognized; dtype_bytes "
                f"defaulted to {DEFAULT_DTYPE_BYTES}.")

    report["model"] = geometry.to_report()

    if geometry.is_moe and dp > 1 and ep_size > 1:
        return refuse(
            "DP_EP_UNSUPPORTED",
            "a MoE instance group with a DP group and ep_size > 1 would "
            "span expert parallelism across both DP and TP; v1 cannot "
            "represent that",
            cluster_source)

    if ep_size > 1 and (not geometry.is_moe or ep_size != tp):
        return refuse(
            "EP_SUBSET_UNSUPPORTED",
            "v1 only represents ep_size in {1, tp_size}; got "
            f"ep_size={ep_size}, tp_size={tp}"
            + ("" if geometry.is_moe else " on a dense model"),
            cluster_source)

    if tp > geometry.kv_heads or geometry.heads % tp != 0:
        return refuse(
            "TP_INVALID",
            f"tp_size={tp} must divide num_attention_heads="
            f"{geometry.heads} and must not exceed "
            f"num_key_value_heads={geometry.kv_heads}",
            model_source)

    if geometry.is_moe and geometry.experts is not None \
            and geometry.experts % ep_size != 0:
        return refuse(
            "EP_INVALID",
            f"ep_size={ep_size} does not divide num_experts="
            f"{geometry.experts}",
            model_source)

    try:
        if trace_rows is not None:
            rows = trace_rows
        elif trace_rows_loader is not None:
            rows = trace_rows_loader()
        else:
            rows = []
        _validate_trace_rows(rows)
    except _TraceInvalid as exc:
        return refuse("TRACE_INVALID", str(exc), trace_source)

    total_rows = len(rows)
    num_reqs_note = None
    if num_reqs is not None:
        selected = rows[:num_reqs]
        if num_reqs > total_rows:
            num_reqs_note = (
                f"num_reqs={num_reqs} exceeds the {total_rows} trace rows; "
                f"all {total_rows} rows were used.")
        elif num_reqs != total_rows:
            num_reqs_note = (
                f"Only the first {len(selected)} of {total_rows} trace rows "
                f"were used (num_reqs={num_reqs}).")
    else:
        selected = rows

    if not selected:
        return refuse(
            "TRACE_EMPTY",
            "the request trace contains no request rows"
            + (f" (num_reqs={num_reqs})" if num_reqs is not None else ""),
            trace_source)

    stats = _request_stats(selected)
    report["request"] = stats

    resolved_limits: list[
        tuple[int, int, int, str | None, str | None]] = []
    for instance in instances:
        try:
            raw_prefill = _serving_limit(
                instance, "max_num_batched_tokens")
            raw_decode = _serving_limit(instance, "max_num_seqs")
        except _Refusal as exc:
            return refuse(exc.code, exc.message, cluster_source)
        prefill_value, prefill_note = _effective_prefill_limit(
            raw_prefill, model_doc)
        decode_value, decode_note = _effective_decode_limit(
            raw_decode, stats["num_reqs"])
        resolved_limits.append((
            prefill_value, decode_value,
            _decode_limit_policy(raw_decode, stats["num_reqs"]),
            prefill_note, decode_note))

    first_limit = resolved_limits[0]
    if any((prefill, decode_policy) != (first_limit[0], first_limit[2])
           for prefill, _decode, decode_policy, _pn, _dn
           in resolved_limits[1:]):
        return refuse(
            "HETEROGENEOUS_SERVING_LIMITS",
            "instances disagree on the resolved max_num_seqs / "
            "max_num_batched_tokens policies: "
            f"{[(p, dp) for p, _d, dp, _pn, _dn in resolved_limits]!r}",
            cluster_source)

    prefill_chunk, decode_batch, _decode_policy, prefill_note, decode_note = \
        first_limit

    hidden = geometry.hidden
    dtype = geometry.dtype_bytes
    tp_prefill = prefill_chunk * hidden * dtype
    tp_decode = decode_batch * hidden * dtype
    kv_bytes_per_token = (
        geometry.layers * geometry.kv_bytes_per_token_per_layer)

    ep_dispatch = 0
    ep_combine = 0
    ep_decode = 0
    has_ep = (geometry.is_moe and ep_size == tp and tp > 1)
    if has_ep:
        assert geometry.experts is not None
        dispatch_tokens = max(1, prefill_chunk // ep_size)
        ep_dispatch = (
            dispatch_tokens * (hidden + geometry.experts) * dtype)
        ep_combine = prefill_chunk * hidden * dtype
        decode_dispatch_tokens = max(1, decode_batch // ep_size)
        ep_decode = (
            decode_dispatch_tokens * (hidden + geometry.experts) * dtype)

    collectives: list[dict[str, Any]] = []
    if tp > 1:
        collectives.append(_intent_collective(
            "allreduce", "TP", tp_prefill, "tp_collective"))
    if has_ep:
        collectives.append(_intent_collective(
            "allgather", "TP", ep_dispatch, "ep_dispatch"))
        collectives.append(_intent_collective(
            "reducescatter", "TP", ep_combine, "ep_combine"))

    report["derived"] = {
        "prefill_chunk_tokens": prefill_chunk,
        "decode_batch": decode_batch,
        "tp_prefill_bytes": tp_prefill,
        "tp_decode_bytes": tp_decode,
        "ep_dispatch_bytes": ep_dispatch,
        "ep_combine_bytes": ep_combine,
        "ep_decode_bytes": ep_decode,
        "kv_bytes_per_token": kv_bytes_per_token,
    }
    report["assumptions"] = _assumptions(
        geometry=geometry, prefill_chunk=prefill_chunk,
        decode_batch=decode_batch,
        hbm_controllers_per_rank=hbm_controllers_per_rank,
        hardware=hardware, num_reqs_note=num_reqs_note,
        dtype_note=dtype_note, weights_note=geometry.weights_note,
        prefill_note=prefill_note, decode_note=decode_note)

    if not collectives:
        return refuse(
            "NO_TRAFFIC",
            "the deployment emits no collective (for example a dense "
            "tp=1 deployment), and the compiler rejects a "
            "traffic-class-less workload",
            cluster_source)

    workload = {
        "model_name": model_name_value,
        "model_family": (
            "mixture_of_experts" if geometry.is_moe
            else "dense_transformer"),
        "tp": tp,
        "dp": dp,
        "ep": 1,
        "pp": 1,
        "collectives": collectives,
    }

    agents: list[dict[str, Any]] = [{
        "kind": "compute_tile",
        "count": ranks,
        "protocol": "AXI",
        "data_width": link_width_bits,
        "addr_width": 64,
    }]
    hbm_count = hbm_controllers_per_rank * ranks
    if hbm_count > 0:
        agents.append({
            "kind": "hbm_controller",
            "count": hbm_count,
            "protocol": "AXI",
            "data_width": link_width_bits,
            "addr_width": 64,
        })

    report["status"] = "OK"
    report["issues"] = []
    return DeploymentMapping(
        status="OK",
        report=report,
        workload=workload,
        agents=tuple(agents),
        requirements=(),
        compute={"stages": []},
    )

def map_deployment_document(
    *,
    cluster: Mapping[str, Any],
    model: Mapping[str, Any],
    trace_rows: list[dict[str, Any]] | None,
    cluster_source: str,
    model_source: str,
    trace_source: str,
    num_reqs: int | None = None,
    dtype_bytes: int | None = DEFAULT_DTYPE_BYTES,
    link_width_bits: int = 128,
    hbm_controllers_per_rank: int = 0,
    model_name: str | None = None,
    source_digests: Mapping[str, str | None] | None = None,
    trace_rows_loader: Callable[[], list[dict[str, Any]]] | None = None,
) -> DeploymentMapping:
    """Map already-parsed documents, with no temporary files.

    ``cluster_source``, ``model_source`` and ``trace_source`` are the report
    provenance names. ``source_digests`` overrides the default digest of the
    canonical JSON document (``map_deployment`` passes the exact file bytes).
    ``trace_rows`` may be ``None`` only when ``trace_rows_loader`` supplies
    the rows; the loader keeps ``map_deployment``'s refusal order (trace
    parsing happens only after deployment semantics pass).
    """
    cluster_doc: Any = (
        dict(cluster) if isinstance(cluster, Mapping)
        and not isinstance(cluster, dict) else cluster)
    model_doc: Any = (
        dict(model) if isinstance(model, Mapping)
        and not isinstance(model, dict) else model)
    digests = dict(source_digests or {})
    sources = {
        "cluster": {
            "path": cluster_source,
            "sha256": digests.get("cluster",
                                  _document_digest(cluster_doc)),
        },
        "model": {
            "path": model_source,
            "sha256": digests.get("model", _document_digest(model_doc)),
        },
        "trace": {
            "path": trace_source,
            "sha256": digests.get("trace", _document_digest(trace_rows)),
        },
    }
    report = _report_skeleton(sources)

    def refuse(code: str, message: str,
               path: str | None = None) -> DeploymentMapping:
        return _refused(report, MappingIssue(
            code=code, message=message, path=path))

    try:
        num_reqs, dtype_bytes, link_width_bits, hbm_controllers_per_rank = (
            _normalize_arguments(
                num_reqs=num_reqs, dtype_bytes=dtype_bytes,
                link_width_bits=link_width_bits,
                hbm_controllers_per_rank=hbm_controllers_per_rank))
    except _Refusal as exc:
        return refuse(exc.code, exc.message)

    return _map_document(
        cluster=cluster_doc, model=model_doc, trace_rows=trace_rows,
        trace_rows_loader=trace_rows_loader, sources=sources,
        cluster_source=cluster_source, model_source=model_source,
        trace_source=trace_source, num_reqs=num_reqs,
        dtype_bytes=dtype_bytes, link_width_bits=link_width_bits,
        hbm_controllers_per_rank=hbm_controllers_per_rank,
        model_name=model_name)

def map_deployment(
    *,
    cluster_config: str | Path,
    model_config: str | Path | None,
    trace: str | Path,
    num_reqs: int | None = None,
    dtype_bytes: int | None = DEFAULT_DTYPE_BYTES,
    link_width_bits: int = 128,
    hbm_controllers_per_rank: int = 0,
    model_name: str | None = None,
) -> DeploymentMapping:
    """Pure, deterministic deployment -> intent mapping.

    Bad user input returns ``REFUSED`` with typed issues; unexpected I/O or
    programming errors may raise. The report has no timestamps, so the same
    inputs always produce byte-identical report and request documents.
    """
    cluster_path = Path(cluster_config)
    trace_path = Path(trace)

    cluster_bytes, cluster_error = _read_source_bytes(cluster_path)
    cluster_doc: Any = None
    cluster_parse_error: str | None = None
    if cluster_bytes is not None:
        cluster_doc, cluster_parse_error = _parse_json_source(cluster_bytes)

    instances: list[dict[str, Any]] = []
    cluster_shape_error: str | None = None
    if cluster_doc is not None:
        try:
            instances = _flatten_instances(cluster_doc)
        except ValueError as exc:
            cluster_shape_error = str(exc)

    cluster_model_name = (
        _instance_value(instances[0], "model_name", "")
        if instances else "")
    # `model_name` is a RESOLUTION override only: the deployment still names
    # the model the cluster names, and the report records both when they
    # differ (locked design, "model_name overrides ... only for model-config
    # resolution").
    resolution_name = model_name if model_name else cluster_model_name

    model_path: Path | None
    if model_config is None:
        model_path = (
            _default_model_path(resolution_name)
            if resolution_name else None)
    else:
        model_path = Path(model_config)

    model_bytes: bytes | None = None
    model_error: OSError | None = None
    model_doc: Any = None
    model_parse_error: str | None = None
    if model_path is not None:
        model_bytes, model_error = _read_source_bytes(model_path)
        if model_bytes is not None:
            model_doc, model_parse_error = _parse_json_source(model_bytes)

    trace_bytes, trace_error = _read_source_bytes(trace_path)

    sources = {
        "cluster": _source(cluster_path, cluster_bytes),
        "model": _source(model_path, model_bytes),
        "trace": _source(trace_path, trace_bytes),
    }
    report = _report_skeleton(sources)

    def refuse(code: str, message: str,
               path: str | None = None) -> DeploymentMapping:
        return _refused(report, MappingIssue(
            code=code, message=message, path=path))

    # ---- caller arguments before any semantic decision ------------------
    try:
        num_reqs, dtype_bytes, link_width_bits, hbm_controllers_per_rank = (
            _normalize_arguments(
                num_reqs=num_reqs, dtype_bytes=dtype_bytes,
                link_width_bits=link_width_bits,
                hbm_controllers_per_rank=hbm_controllers_per_rank))
    except _Refusal as exc:
        return refuse(exc.code, exc.message)

    # ---- source validity before any semantic decision -------------------
    if cluster_error is not None:
        return refuse(
            "SOURCE_UNREADABLE",
            f"cluster config cannot be read: {cluster_path}: {cluster_error}",
            str(cluster_path))
    if cluster_parse_error is not None:
        return refuse(
            "SOURCE_UNREADABLE",
            f"cluster config is not valid JSON: {cluster_path}: "
            f"{cluster_parse_error}",
            str(cluster_path))
    if cluster_shape_error is not None:
        return refuse(
            "SOURCE_UNREADABLE",
            f"cluster config is invalid: {cluster_shape_error}",
            str(cluster_path))
    if model_path is None:
        return refuse(
            "SOURCE_UNREADABLE",
            "model config cannot be resolved: the cluster declares no "
            "model name and model_config is absent",
            None)
    if model_error is not None:
        return refuse(
            "SOURCE_UNREADABLE",
            f"model config cannot be read: {model_path}: {model_error}",
            str(model_path))
    if model_parse_error is not None:
        return refuse(
            "SOURCE_UNREADABLE",
            f"model config is not valid JSON: {model_path}: "
            f"{model_parse_error}",
            str(model_path))
    if trace_error is not None:
        code = ("SOURCE_UNREADABLE"
                if isinstance(trace_error, FileNotFoundError)
                else "TRACE_INVALID")
        return refuse(
            code, f"trace cannot be read: {trace_path}: {trace_error}",
            str(trace_path))
    assert cluster_bytes is not None
    assert model_bytes is not None
    assert trace_bytes is not None
    assert model_path is not None

    return map_deployment_document(
        cluster=cluster_doc,
        model=model_doc,
        trace_rows=None,
        cluster_source=str(cluster_path),
        model_source=str(model_path),
        trace_source=str(trace_path),
        num_reqs=num_reqs,
        dtype_bytes=dtype_bytes,
        link_width_bits=link_width_bits,
        hbm_controllers_per_rank=hbm_controllers_per_rank,
        model_name=model_name,
        source_digests={
            "cluster": _sha256(cluster_bytes),
            "model": _sha256(model_bytes),
            "trace": _sha256(trace_bytes),
        },
        trace_rows_loader=lambda: _read_trace_rows(trace_bytes, trace_path),
    )

__all__ = [
    "SCHEMA",
    "MappingIssue",
    "DeploymentMapping",
    "describe_model",
    "map_deployment",
    "map_deployment_document",
]
