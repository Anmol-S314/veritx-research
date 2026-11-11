# Deployment intent mapping

Status: design locked for v1 implementation.

## Purpose

Turn a **LLMServingSim deployment** — cluster config, model config, request
trace — into the repository's **v4 workload intent** so a serving deployment can
be evaluated on a designed fabric.

The serving simulator owns model/hardware/serving semantics. This mapping does
not re-model them; it translates them into the intent primitives the fabric
compiler already consumes.

## Scope (v1)

Supported:

- aggregated deployments (`pd_type` absent or `null` on every instance)
- `pp_size == 1`
- one homogeneous instance group: same `model_name`, `hardware`, `tp_size`,
  `pp_size`, `ep_size`
- a single instance, or several instances sharing one non-empty `dp_group`
- dense models, and MoE models with `ep_size` in `{1, tp_size}`
- `tp_size` divides `num_attention_heads` and is `<= num_key_value_heads`
- `ep_size` divides the expert count

Refused with a typed issue (never silently adjusted):

- any prefill/decode instance (`pd_type` non-null)
- `pp_size > 1`
- mixed model/hardware/tp/pp/ep across instances
- multiple instances without one shared `dp_group`
- MoE with a DP group and `ep_size > 1` (EP would span DP and TP)
- `1 < ep_size < tp_size` (subset EP groups are not representable)
- `tp_size` not dividing heads, or exceeding KV heads
- `ep_size` not dividing experts
- missing model geometry, empty trace, or a deck with no traffic

## Inputs and resolution

| Input | Default resolution |
|---|---|
| cluster config | explicit path; shape from LLMServingSim `configs/cluster/*.json` |
| model config | explicit path, else `<repo>/third_party/llmservingsim/configs/model/<model_name>.json` |
| trace | explicit path; JSONL rows with `input_toks`, `output_toks`, `arrival_time_ns` |
| hardware profile | optional; `<repo>/third_party/llmservingsim/profiler/perf/<hardware>/hardware.yaml` when present |

The caller supplies the model config that matches the cluster's `model_name`;
an HF config carries no model identifier, so the mapping cannot verify the
match from content. Every OK report records that assumption. A missing hardware
bundle is reported, not refused: the intent does not consume compute timing.

Instance parallelism mirrors `config_builder.py`: `tp_size` and `num_npus` may
be supplied partially, and the missing one is inferred from
`num_npus = tp_size * pp_size`. With both absent, `tp` and `pp` default to 1.
An inconsistent pair that implies `pp > 1` is refused as
`PIPELINE_PARALLEL_UNSUPPORTED`; other inconsistencies are `TP_INVALID`.
`ep_size` defaults to `tp_size` for MoE and 1 for dense. `hardware` is
required on every instance.

## Normalized deployment

```json
{
  "model_name": "Qwen/Qwen3-30B-A3B-Instruct-2507",
  "hardware": "RTXPRO6000",
  "pd_type": null,
  "tp": 2,
  "dp": 1,
  "ep": 2,
  "pp": 1,
  "instances": 1,
  "ranks": 2,
  "model": { "layers": 48, "hidden": 2048, "heads": 32, "kv_heads": 4,
             "head_dim": 128, "experts": 128, "top_k": 8, "dtype_bytes": 2 },
  "request": { "num_reqs": 10, "isl_mean": 12.0, "osl_mean": 69.0,
               "arrival_span_ns": 1234567 },
  "serving": { "max_num_seqs": 10, "max_num_batched_tokens": 2048 }
}
```

`dp` is the number of instances in the shared `dp_group`. `ranks` is
`tp * dp * pp` (v1 has `pp = 1`). EP is a **mode over the TP/DP ranks**, not a
multiplier; the intent therefore carries `ep = 1` and expresses expert traffic
as all-gather/reduce-scatter over `TP`, matching LLMServingSim's
`allgather_reducescatter` backend.

## Mapping

### Workload

| Intent field | Source |
|---|---|
| `model_name` | cluster instance `model_name` |
| `model_family` | `mixture_of_experts` when the config declares experts, else `dense_transformer` |
| `tp` | instance `tp_size` |
| `dp` | number of instances in the shared `dp_group` (1 if single) |
| `ep` | `1` (EP is a mode, not a rank multiplier) |
| `pp` | `1` (v1 refuses PP > 1) |
| `serving_mode` | omitted; legacy identity-only field |

The parser defaults the legacy `serving_mode` field to `mixed`; the mapping
does not set it.

### Collectives

Let:

```
H   = hidden_size
D   = dtype bytes
T   = effective max_num_batched_tokens (prefill chunk, clamped to
      max_position_embeddings)
B   = effective decode batch (max_num_seqs bounded by the selected requests)
E   = num_experts
EP  = instance ep_size
```

| Intent entry | When | `payload_bytes` | `traffic_class` |
|---|---|---|---|
| `allreduce`, `TP` | `tp > 1` | `T * H * D` | `tp_collective` |
| `allgather`, `TP` | MoE and `EP == tp > 1` | `max(1, T // EP) * (H + E) * D` | `ep_dispatch` |
| `reducescatter`, `TP` | MoE and `EP == tp > 1` | `T * H * D` | `ep_combine` |

The dispatch includes router logits, so the payload is `H + E` per token, not
a top-k-weighted activation slice. The intent models the **prefill chunk**.
Decode volumes are reported but not emitted as a second operation, because
the v4 collective has no phase or repetition axis:

```
tp_decode_bytes   = B * H * D
ep_decode_bytes   = max(1, B // EP) * (H + E) * D   # decode dispatch
ep_combine_decode = B * H * D                       # not a separate report key
kv_bytes_per_token = 2 * layers * kv_heads * head_dim * D
```

If the resulting collective list is empty (for example a dense `tp = 1`
deployment), the mapping is refused with `NO_TRAFFIC`: the compiler rejects a
traffic-class-less workload.

### Agents

| Intent agent | Count |
|---|---|
| `compute_tile` | `ranks` |
| `hbm_controller` | `hbm_controllers_per_rank * ranks` (default 0) |

`protocol` is `AXI`, `data_width` is the mapping's `link_width_bits`, and
`addr_width` is 64. HBM controllers are a fabric choice, not a serving fact, so
the default is zero and the caller may add them.

### Compute and requirements

`compute` is empty and `requirements` is empty. The mapping does not invent
per-layer durations or SLOs. Compute timing belongs to a measured profile or a
later explicit intent; requirements belong to the project.

### Request assembly

The mapping returns a fragment (`workload`, `agents`, `requirements`,
`compute`). The caller supplies the fabric:

```python
mapping.to_request(
    topology={"kind": "mesh", "side_length": 2, "concentration": 1},
    noc_controls={"link_width": 128},
    physical={"clock_freq_mhz": 1000, "data_width": 128,
              "process_node_nm": 7, "num_power_domains": 1},
)
```

The assembled document is schema 4 with `dependencies: {}` and
`address_map: {"ranges": []}`.

The supplied topology must seat `ranks + hbm_controllers` agents. A mesh side
length sized only for `ranks` is insufficient when the caller adds HBM
controllers.

## Report

Deterministic JSON, no timestamps:

```json
{
  "schema": "veritx/deployment-mapping/1",
  "status": "OK",
  "sources": {
    "cluster": {"path": "...", "sha256": "..."},
    "model": {"path": "...", "sha256": "..."},
    "trace": {"path": "...", "sha256": "..."}
  },
  "deployment": {"model_name": "...", "hardware": "...", "pd_type": null,
                 "tp": 2, "dp": 1, "ep": 2, "pp": 1,
                 "instances": 1, "ranks": 2},
  "model": {"layers": 48, "hidden": 2048, "heads": 32, "kv_heads": 4,
            "head_dim": 128, "experts": 128, "top_k": 8,
            "dtype_bytes": 2, "weights_bytes": null},
  "request": {"num_reqs": 10, "isl_mean": 12.0, "osl_mean": 69.0,
              "arrival_span_ns": 1234567},
  "derived": {
    "prefill_chunk_tokens": 2048,
    "decode_batch": 10,
    "tp_prefill_bytes": 8388608,
    "tp_decode_bytes": 40960,
    "ep_dispatch_bytes": 4456448,
    "ep_combine_bytes": 8388608,
    "ep_decode_bytes": 21760,
    "kv_bytes_per_token": 98304
  },
  "assumptions": ["..."],
  "issues": []
}
```

`weights_bytes` is reported only when the model config declares a
non-negative integer `num_parameters`; geometry alone is not converted into a
parameter estimate, and a fractional `num_parameters` is never truncated (it
is reported as `null` with an assumption).

## Refusal codes

| Code | Meaning |
|---|---|
| `PD_POOLS_UNSUPPORTED` | any `pd_type` other than null |
| `PIPELINE_PARALLEL_UNSUPPORTED` | `pp_size != 1`, including a `num_npus`/`tp_size` pair that implies `pp > 1` |
| `HETEROGENEOUS_CLUSTER_UNSUPPORTED` | instances disagree on model/hardware/tp/ep |
| `DP_GROUP_REQUIRED` | several instances but no shared non-empty `dp_group` |
| `DP_EP_UNSUPPORTED` | MoE with a DP group and `ep_size > 1` |
| `EP_SUBSET_UNSUPPORTED` | `ep_size` is not in `{1, tp_size}` (including dense `ep_size > 1` and MoE `ep_size > tp_size`) |
| `TP_INVALID` | `tp` cannot be resolved from `tp_size`/`num_npus`, does not divide heads, or exceeds KV heads |
| `EP_INVALID` | `ep_size` does not divide experts |
| `MODEL_CONFIG_INCOMPLETE` | required geometry missing or invalid (including a non-divisible implicit `head_dim` and `top_k > num_experts`) |
| `NO_INSTANCES` | the cluster config declares no instance rows |
| `HARDWARE_REQUIRED` | an instance omits `hardware` |
| `SOURCE_UNREADABLE` | cluster/model file cannot be read or is not valid JSON; a trace file is missing |
| `TRACE_INVALID` | trace cannot be read, or a JSONL row is malformed or lacks non-negative integer `input_toks`/`output_toks` |
| `SERVING_LIMIT_INVALID` | `max_num_seqs` / `max_num_batched_tokens` is not a non-negative integer |
| `HETEROGENEOUS_SERVING_LIMITS` | instances disagree on the resolved `max_num_seqs` / `max_num_batched_tokens` policies |
| `ARGUMENT_INVALID` | `num_reqs`, `link_width_bits`, `hbm_controllers_per_rank`, or `dtype_bytes` is invalid |
| `TRACE_EMPTY` | no request rows |
| `NO_TRAFFIC` | no collective would be emitted |

## API

`veritx_dse/application/deployment_intent.py`:

```python
SCHEMA = "veritx/deployment-mapping/1"

@dataclass(frozen=True)
class MappingIssue:
    code: str
    message: str
    path: str | None = None

@dataclass(frozen=True)
class DeploymentMapping:
    status: str                      # "OK" | "REFUSED"
    report: dict[str, Any]
    workload: dict[str, Any] | None
    agents: tuple[dict[str, Any], ...]
    requirements: tuple[dict[str, Any], ...]
    compute: dict[str, Any]

    def to_request(
        self,
        *,
        topology: dict[str, Any],
        noc_controls: dict[str, Any] | None = None,
        physical: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Assemble a schema-4 request; raises ValueError when REFUSED."""

def map_deployment(
    *,
    cluster_config: str | Path,
    model_config: str | Path | None,
    trace: str | Path,
    num_reqs: int | None = None,
    dtype_bytes: int | None = 2,
    link_width_bits: int = 128,
    hbm_controllers_per_rank: int = 0,
    model_name: str | None = None,
) -> DeploymentMapping:
    """Pure, deterministic mapping. Bad user input returns REFUSED with
    issues; unexpected I/O or programming errors may raise."""
```

`model_name` overrides the cluster's model name only for model-config
resolution; the report records both when they differ.

## Verification contract

1. **Golden compile** — Qwen3-30B-A3B, TP2, EP2, 2 ranks, prefill chunk 2048:
   `to_request(topology=mesh-2)` parses with `parse_request_doc` and
   `FabricCompiler().compile()` returns `COMPILED`.
2. **Determinism** — the same inputs produce byte-identical report and request.
3. **Invariants** — every collective payload is a positive int; every
   expanded group has at least two members; every agent count is positive;
   `tp * dp * pp == ranks`; no issue means `status == "OK"`.
4. **Refusals** — one test per refusal code, asserting `status == "REFUSED"`,
   `workload is None`, and the exact code.
5. **Round-trip** — the assembled request is schema 4, carries the supplied
   topology, and `to_dict` -> `from_dict` preserves the design hash.
6. **No invented timing** — `compute` contains no stages and the report says
   compute timing is not modeled.

## Later (v2)

- PD pools: `deployment.pools[]` with role, ranks, per-role TP/PP/EP, and
  explicit `kv_transfer` traffic profiles.
- Phase-split intents: separate prefill and decode evaluations.
- Subset EP: explicit per-group traffic profiles.
- PP: point-to-point stage traffic and a stage-aware intent.
- Measured compute: per-layer durations from
  `profiler/perf/<hw>/<model>/<variant>/tp<N>/*.csv`, only when the bundle
  exists.
