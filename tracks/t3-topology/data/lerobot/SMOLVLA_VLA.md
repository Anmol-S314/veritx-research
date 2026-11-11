# SmolVLA policy-stage split (real CPU run)

**This is a real model run, not a synthetic trace.** The existing SmolVLA run
timed one monolithic `policy` stage. This run keeps the same real
`SmolVLAPolicy` checkpoint and same synthetic observation, but splits that stage
into three measured calls inside LeRobot 0.6.1:

| Stage | What is timed | Calls per chunk |
| --- | --- | ---: |
| `vision_encoder` | `vlm_with_expert.embed_image` = SmolVLM vision tower + connector | 3 (one per camera) |
| `vlm_prefill` | the `vlm_with_expert.forward` call that creates and fills the KV cache | 1 |
| `action_denoise_step_0..9` | each `VLAFlowMatching.denoise_step` call | 10 |
| `action_denoise_total` | sum of the ten per-step times | 10 |
| `policy_total` | wall time around `policy.predict_action_chunk(batch)` | 1 |
| `other` | `policy_total - vision - prefill - denoise_total` | residual |

The split is **not** a rewrite of LeRobot and **not** a synthetic annotation.
Wrappers were installed on the loaded policy object with `time.perf_counter()`
around the real bound methods; the original methods, arguments, weights, dtypes,
and outputs were unchanged. No LeRobot source file was edited. The trace file was
produced by `tracks/t3-topology/tools/smolvla_stage_trace.py` from the measured
rows; no row was hand-written.

- Date: 2026-11-05
- Host: Ubuntu 26.04 LTS, Linux 7.0.0-38-generic x86_64, AMD Ryzen 7 7445HS
  (6 cores / 12 threads), 14 GiB RAM, **CPU only** (no CUDA device)
- Output: `smolvla_vla_trace.jsonl` (15 rows = 1 timed call x 15 stages)
- Model run: **real** (`SmolVLAPolicy.predict_action_chunk`, 10 flow-matching
  denoise steps, 450,046,176 parameters)

## Environment

The existing `/tmp/opencode/lerobot-venv` was reused. Nothing was installed,
reinstalled, or modified for this run. The repository's system Python, the
LeRobot package, and the previous ACT/SmolVLA files were not touched.

| Component | Version |
| --- | --- |
| venv | `/tmp/opencode/lerobot-venv` |
| Python | 3.12.13 |
| lerobot | 0.6.1 |
| torch | 2.11.0+cpu |
| torchvision | 0.26.0+cpu |
| transformers | 5.5.4 |
| accelerate | 1.15.0 |
| numpy | 2.2.6 |
| huggingface-hub | 1.33.0 |
| safetensors | 0.8.0 |
| tokenizers | 0.22.2 |
| scipy | 1.18.1 |
| num2words | 0.5.14 |
| tokenizer / VLM | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` |

The run used `HF_HOME=/home/datavex/.cache/huggingface`, `HF_HUB_OFFLINE=1`,
`OMP_NUM_THREADS=6`, `torch.set_num_threads(6)`, and
`torch.set_num_interop_threads(6)`.

## Checkpoint

| Field | Value |
| --- | --- |
| Repo | `lerobot/smolvla_base` |
| Revision | `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6` |
| Local snapshot | `/home/datavex/.cache/smolvla-base` |
| Backbone | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` @ `7b375e1b73b11138ff12fe22c8f2822d8fe03467` |
| Parameters | 450,046,176 |
| Weight dtype | 474 bfloat16 tensors (VLM, expert, vision tower) + 26 float32 auxiliary tensors (action/state projections, time MLP) |
| Weight file | `model.safetensors`, 906,712,520 B, sha256 `7cd549ac2351fb069c0ddb3c34ad2d09cfc92b56a15dccdfc2e41467aaca01eb` |
| Config | `config.json`, 2,299 B, sha256 `650584b56c104720f7a3c91d1ec6bec9e8de8ac11e60c92ba2fa82d93eda147d` |
| Preprocessor | `policy_preprocessor.json`, 1,872 B, sha256 `7683d648280a72f0d51e869fb8dd1596beed90b7f84849330cf1bc26634a4bd6` |
| Preprocessor stats | `policy_preprocessor_step_5_normalizer_processor.safetensors`, 640 B, sha256 `490ab239d96e263687c0b2e386a0afbc235a2eceb9857c36ed32f2f162a3e7c8` |
| Postprocessor | `policy_postprocessor.json`, 660 B, sha256 `2b78bb742065288df2ec63b0ee35f97a1f6950171cf2272f7e34b1fe3873b17b` |
| Postprocessor stats | `policy_postprocessor_step_0_unnormalizer_processor.safetensors`, 640 B, sha256 `490ab239d96e263687c0b2e386a0afbc235a2eceb9857c36ed32f2f162a3e7c8` |

Those hashes are identical to the ones recorded in `SMOLVLA.md`, so this is the
same checkpoint material, not a re-download at a different revision. The local
snapshot's HF tree metadata names the same revision.

Derived configuration actually used:

| Property | Value |
| --- | --- |
| Cameras | 3: `observation.images.camera1`, `camera2`, `camera3` |
| Camera input | `3 x 256 x 256` CHW, float32 in `[0, 1]` |
| Internal image path | pad/resize to `512 x 512`, scale to `[-1, 1]`, then bf16 cast inside `embed_image` |
| State / action | 6 / 6, padded to 32 for the model |
| Chunk size / `n_action_steps` | 50 / 50 |
| Flow steps | 10 (`num_steps`) |
| KV cache | `use_cache=True` |
| Attention mode | `cross_attn` |
| VLM / expert layers | 16 VLM layers; `num_expert_layers=0` means the expert uses the same 16 layers |
| Self-attention interval | every 2 layers (`self_attn_every_n_layers=2`) |
| Prefix padding | `prefix_length=0` (no prefix padding in this checkpoint) |
| Image special tokens | disabled (`add_image_special_tokens=False`) |
| Text padding | `max_length`, 48 tokens |

## Exactly where the policy splits

The installed LeRobot 0.6.1 code path is:

`SmolVLAPolicy.predict_action_chunk`
-> `_get_action_chunk`
-> `prepare_images` / `prepare_state`
-> `VLAFlowMatching.sample_actions`
-> `embed_prefix`
-> for each camera, `SmolVLMWithExpertModel.embed_image`
-> `vlm_with_expert.forward(..., past_key_values=None, inputs_embeds=[prefix, None], use_cache=True)`
-> `euler_integrate(..., num_steps=10)`
-> `VLAFlowMatching.denoise_step` ten times.

The hooks are:

1. **Vision encoder / projector** — `smolvlm_with_expert.py`, `embed_image`:
   `self.get_vlm_model().vision_model(...)` followed by
   `self.get_vlm_model().connector(...)`. `vision_ms` is the sum of the three
   `embed_image` calls, including the bf16 dtype cast inside that method.
   The `resize_with_pad` from 256x256 to 512x512 is **not** in `embed_image`; it
   is in `prepare_images` and therefore falls into `other`.
2. **VLM prefill** — in `modeling_smolvla.py`, `sample_actions` calls
   `vlm_with_expert.forward` with `past_key_values=None`, `use_cache=True`,
   and `inputs_embeds=[prefix_embs, None]`. Inside
   `smolvlm_with_expert.py`, `fill_kv_cache = use_cache and past_key_values is
   None`, so this is the call that creates the `DynamicCache` and fills the
   prefix K/V. `vlm_prefill_ms` times exactly this forward call. It excludes
   `embed_prefix`, which has already produced the image, language, and state
   embeddings.
3. **Action denoising** — `sample_actions` passes a lambda calling
   `denoise_step` to `euler_integrate` with `num_steps=10`. Each
   `denoise_step` embeds the noisy action + timestep suffix, runs
   `vlm_with_expert.forward` against the filled cache, crops the cache back to
   the prefix, and applies `action_out_proj`. `denoise_step_ms` contains the ten
   measured calls; `action_denoise_total` is their sum. The harness asserted the
   count is exactly 10.
4. **Policy total** — `time.perf_counter()` around
   `policy.predict_action_chunk(batch)` under `torch.no_grad()`. This includes
   `self.eval()`, queue bookkeeping, `prepare_images`, `prepare_state`,
   `sample_actions`, and the final action slicing/return.
5. **Other** — the algebraic residual
   `policy_total - vision - prefill - denoise_total`. It is not an independent
   timer; it is decomposed with diagnostic timers in the next section.

The wrappers were attached to the loaded instances only:

```python
orig_embed_image = policy.model.vlm_with_expert.embed_image
policy.model.vlm_with_expert.embed_image = timed(orig_embed_image)  # vision_ms

orig_forward = policy.model.vlm_with_expert.forward
policy.model.vlm_with_expert.forward = timed_forward(orig_forward)  # prefill only

orig_denoise = policy.model.denoise_step
policy.model.denoise_step = timed(orig_denoise)  # ten step times
```

The prefill wrapper classifies a call as prefill only when
`past_key_values is None and use_cache and inputs_embeds == [prefix, None]`.
The other ten forwarded calls have a filled cache and `[None, suffix]`; the
harness asserted that count. This is the actual code boundary, not a heuristic
based on tensor sizes.

## Observation and call plan

The observation is the same in-memory synthetic observation as the earlier
`SMOLVLA.md` run, generated once with `torch.manual_seed(0)`:

| Feature | Input | After preprocessor |
| --- | --- | --- |
| `observation.images.camera1` | `float32 [3, 256, 256]` in `[0, 1]` | `[1, 3, 256, 256]` |
| `observation.images.camera2` | `float32 [3, 256, 256]` in `[0, 1]` | `[1, 3, 256, 256]` |
| `observation.images.camera3` | `float32 [3, 256, 256]` in `[0, 1]` | `[1, 3, 256, 256]` |
| `observation.state` | `float32 [6]` | `[1, 6]` |
| `task` | `"put the cube in the bowl"` | `[1, 48]` ids and mask |
| output `action` | - | `[1, 50, 6]` float32 |

Call plan for the committed trace: **1 warmup (discarded) + 1 timed call**. The
preprocessor runs before each call and is outside the measured policy interval.
Then, in the same process, **3 additional timed calls** were run only to obtain
a stability median; those calls are not written to `smolvla_vla_trace.jsonl`.
No CUDA, autocast, quantization, `torch.compile`, or KV-cache reuse across calls
was used.

## Measured results

All values in milliseconds. The canonical timed call (the one in the trace):

| Stage | ms | % of policy total |
| --- | ---: | ---: |
| `vision_encoder` (3 calls) | 1102.660 | 59.89% |
| `vlm_prefill` (1 call) | 151.936 | 8.25% |
| `action_denoise_total` (10 steps) | 577.780 | 31.38% |
| `other` | 8.635 | 0.47% |
| `policy_total` | **1841.011** | 100.00% |

The sum is exact:
`1102.6602629863191 + 151.93582299980335 + 577.7795829926617 +
8.634947007521987 = 1841.0106159863062 ms`.

The three vision calls were 381.761, 359.626, and 361.273 ms (sum 1102.660 ms),
so the camera cost is nearly uniform in this run.

Per-denoise-step values for that call:

| Step | ms |
| ---: | ---: |
| 0 | 55.583 |
| 1 | 55.316 |
| 2 | 55.747 |
| 3 | 65.182 |
| 4 | 58.804 |
| 5 | 56.222 |
| 6 | 56.594 |
| 7 | 56.481 |
| 8 | 59.583 |
| 9 | 58.268 |
| **sum** | **577.780** |
| **median** | **56.537** |
| min / max | 55.316 / 65.182 |

The per-step values are all the same `denoise_step` code path; step 3 is the
largest single sample, but the run does not show a monotonic warm-up or
cool-down trend across steps. The spread is CPU scheduling/frequency noise at
the ~0.06 s scale of one step.

Stability pass (3 extra timed calls, same process, **not** in the trace):

| Stage | Median ms | Range ms |
| --- | ---: | ---: |
| `vision_encoder` | 1173.113 | 1055.723 - 1194.869 |
| `vlm_prefill` | 151.695 | 149.233 - 162.724 |
| `action_denoise_total` | 610.108 | 596.932 - 620.696 |
| `other` | 11.677 | 10.017 - 13.533 |
| `policy_total` | **1944.446** | 1835.669 - 1970.205 |

The median of all 30 stability denoise-step samples is **58.947 ms**; the ten
per-step medians are
`[58.567, 59.386, 60.676, 58.381, 58.551, 58.604, 57.449, 61.466, 62.100,
67.863]`. The canonical trace call is at the low end of the total range: the stability
median is 5.6% above its `policy_total`. With one timed sample in the trace, the
trace values are descriptive measurements, not a statistical estimate; the
stability medians are the more robust summary.

The earlier coarse `SMOLVLA.md` run measured a monolithic `policy` stage of
2461.770-2794.364 ms. This run measured 1835.669-1970.205 ms for the same stage
on the same host and venv. CPU frequency/load is not controlled or normalized,
so the absolute totals are not directly comparable across runs. The split is
internally consistent: within each call the four stage durations reconstruct
`policy_total` exactly.

## What the residual `other` contains

The canonical call's residual is 8.635 ms (0.47% of policy total). Diagnostic
timers around the real methods decompose it as follows:

| Component | ms | What it is |
| --- | ---: | --- |
| `prepare_images` | 3.247 | three `resize_with_pad` operations 256x256 -> 512x512, the `*2-1` scale, mask construction |
| `prepare_state` | 0.034 | state slice and pad to 32 |
| prefix non-vision | 0.733 | `embed_prefix` minus `embed_image`: image-embedding scaling, language token embedding, `state_proj`, concatenation, masks; no image special tokens in this checkpoint |
| `sample_noise` | 0.026 | initial `torch.normal` action noise |
| Euler / prefix-mask overhead | 0.735 | prefix `make_att_2d_masks` and position ids in `sample_actions`, ten `x_t = x_t + dt*v_t` updates, timestep tensors, lambda/Python overhead |
| `predict_action_chunk` bookkeeping | 3.861 | `self.eval()`, queue population, `_get_action_chunk` entry/exit, action unpadding/slicing, Python call overhead |
| **sum** | **8.635** | equals `other` exactly |

The decomposition is algebraic:

```text
other = (embed_prefix - vision)                  # prefix non-vision
      + (sample_actions - embed_prefix - prefill - denoise_total)
      + (policy_total - sample_actions)
```

The first term is 0.733 ms, the second 0.760 ms, and the third 7.142 ms, which
sum to 8.635 ms. The bookkeeping bucket is the least decomposed: it is the
remainder after subtracting `prepare_images` and `prepare_state` from
`policy_total - sample_actions`, and its 3.861 ms was not split into `self.eval()`
versus queue/action-slicing sub-timers. It is small enough (0.21% of total) that
this does not affect the three-way split.

## What is real, what is approximate

Real:

- The actual `lerobot/smolvla_base` weights at the pinned revision, loaded by
  the real LeRobot 0.6.1 `SmolVLAPolicy.from_pretrained`.
- Real CPU forward passes through the 450 M-parameter model: 3 vision-tower +
  connector calls, 1 KV-cache prefill forward, and 10 `denoise_step` calls.
- Real method-level wall-clock timing with `time.perf_counter()`, with asserted
  call counts (3 / 1 / 10) and asserted output shape `[1, 50, 6]`.
- Wrapper transparency was checked with a fixed noise tensor: the uninstrumented
  and instrumented calls produced bitwise-identical `[1, 50, 6]` outputs
  (`torch.equal == True`, max absolute difference `0.0`).
- The sum checks in the trace are exact to floating-point round-trip; the
  validator allows 0.01 ms absolute tolerance.

Approximate or definition-dependent:

- **Vision boundary.** `vision_ms` is `embed_image` only: vision tower plus
  connector, including the bf16 cast. It excludes the image resize/pad and
  `[0,1] -> [-1,1]` scale, which are in `prepare_images` and therefore in
  `other` (3.247 ms). `embed_prefix` also applies the scalar
  `sqrt(hidden_dim)` scaling to each image embedding after `embed_image`; that
  multiply is in the 0.733 ms prefix bucket, not in `vision_ms`. If "vision
  stage" is defined to include image preprocessing and that scaling, add those
  small amounts.
- **Prefill boundary.** `vlm_prefill_ms` is only the transformer forward that
  fills the KV cache. It excludes `embed_prefix` (image embeddings are counted
  in vision; language/state embeddings and concatenation are in `other`,
  0.733 ms) and excludes attention-mask/position-id construction (in `other`).
  If "prefill" is defined as all prefix processing, it would be larger.
- **Denoise boundary.** `denoise_step_ms` is the full `denoise_step` call:
  suffix embedding, transformer forward against the cache, cache crop, and
  `action_out_proj`. The Euler update between steps and the loop overhead are in
  `other` (0.735 ms together with prefix-mask construction).
- **`other` is a residual, not an independent timer.** Its components were
  measured by diagnostic wrappers, but the total residual is defined by
  subtraction. The decomposition closes exactly in this run.
- **CPU wall-clock only.** There are no CUDA events, hardware performance
  counters, NoC/fabric counters, memory-bandwidth counters, or power
  measurements. CPU execution is synchronous, so there is no async
  synchronization ambiguity, but OS scheduling and CPU frequency are not
  controlled. Wrapper overhead is sub-millisecond and is included in both the
  stage timings and `policy_total`; it does not create a gap in the split.

## Boundary of the claim

- **Real SmolVLA on CPU, not GR00T, not Jetson AGX Thor.** These are
  bfloat16/float32 CPU timings for a 450 M-parameter VLA on a 6-core laptop CPU.
  They say nothing about GR00T, Thor, GPU, or accelerator performance.
- **No NoC or fabric counters.** No interconnect, NoC, memory-bandwidth, or
  power measurement was made. The stages are wall-clock timings only.
- **Synthetic observation, no closed loop.** The images and state are random
  tensors. There is no camera, simulator, robot, action execution, or success
  metric. The output shape check is not a task-performance result.
- **Base checkpoint, not a fine-tune.** `lerobot/smolvla_base` is a generalist
  starting point. Its outputs on a random observation are not meaningful
  actions.
- **Normalization is identity in this run.** The checkpoint's normalizer state
  file contains only `so100*`-qualified action statistics and no plain
  `observation.state` / `action` entries. LeRobot 0.6.1's `_apply_transform`
  returns the input unchanged when the key is missing, so state normalization
  and action unnormalization are identity here. The policy still consumes 6-D
  state and produces 6-D actions, but they are not dataset-scaled. This does not
  affect the stage timings (the identity transform is cheap and the preprocessor
  is outside the measured policy interval), but no real dataset normalization
  was exercised.
- **One trace sample plus a separate 3-call stability pass.** The trace file has
  one timed call; the medians in this document come from the extra calls and are
  not in the JSONL. Run-to-run variance is not characterized beyond the three
  stability samples.
- **No RTC.** `rtc_config` is absent in the checkpoint; real-time chunking was
  not exercised.

## Output file

`smolvla_vla_trace.jsonl` has 15 compact JSONL rows, one group, in this fixed
order:

```text
vision_encoder
vlm_prefill
action_denoise_step_0 ... action_denoise_step_9
action_denoise_total
policy_total
other
```

A row looks like:

```json
{"timestamp_s":189645.439706372,"stage":"vision_encoder","duration_ms":1102.6602629863191,
 "payload_bytes":2359296,"image_resolution":[256,256],"chunk_size":50,
 "n_action_steps":50,"num_denoise_steps":10}
```

Metadata:

- `timestamp_s` is a `time.perf_counter()` reading taken immediately before the
  timed `predict_action_chunk`; all rows in the group share it. It is an
  arbitrary monotonic value, not a wall-clock timestamp.
- `payload_bytes` = 2,359,296 = `3 cameras * 3 channels * 256 * 256 * 4 bytes`.
  It is the decoded camera tensor size, not a JPEG or wire payload.
- `image_resolution` = `[256, 256]`, the model input before the internal
  512x512 pad/resize.
- `chunk_size` = 50, from `actions.shape[1]`; `n_action_steps` = 50 from the
  checkpoint config; `num_denoise_steps` = 10.

File hash: `sha256:eea4d4f59fbe6d63d3a508df2b31059c611ac790e0f88b50227f2b48de444a94`.

## Validation

`tracks/t3-topology/tools/smolvla_stage_trace.py` is a stdlib-only validator and
normalizer for this schema. It:

- requires exactly the 15 stages above, once per `timestamp_s` group;
- rejects non-finite or negative durations/timestamps;
- requires uniform metadata within a group;
- checks `action_denoise_total` against the ten-step sum and `policy_total`
  against `vision + prefill + denoise_total + other`, both within **0.01 ms**
  absolute tolerance;
- normalizes by sorting groups by `timestamp_s` and rows by the fixed stage
  order; extra fields are preserved at the end of each row, sorted by key;
- fails closed: an invalid input produces no partial output file.

Commands:

```bash
# Validate the committed trace.
/tmp/opencode/lerobot-venv/bin/python tracks/t3-topology/tools/smolvla_stage_trace.py \
  validate --input tracks/t3-topology/data/lerobot/smolvla_vla_trace.jsonl

# Normalize a raw trace (validate first, then write canonical JSONL).
/tmp/opencode/lerobot-venv/bin/python tracks/t3-topology/tools/smolvla_stage_trace.py \
  normalize --input /tmp/opencode/smolvla_vla_raw.jsonl \
            --output tracks/t3-topology/data/lerobot/smolvla_vla_trace.jsonl
```

Tests:

```bash
cd tracks/t3-topology/dse
PYTHONPATH=. pytest -q tests/test_smolvla_stage_trace.py
```

Result: **11 passed**. The tests cover a valid trace, a missing stage, a
negative duration, both sum mismatches, the stated tolerance, metadata
consistency, CLI normalize/validate round-trip and idempotence, fail-closed
invalid CLI input, and parsing of the committed trace with exactly ten
`action_denoise_step_*` rows.

## Reproduction sketch

The full harness was a throwaway script under `/tmp/opencode`; the essential
body is below. It is the same load and observation as `SMOLVLA.md`, plus the
instance-level wrappers.

```python
import functools, time, torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

PATH = "/home/datavex/.cache/smolvla-base"
SHA = "5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6"

cfg = PreTrainedConfig.from_pretrained(PATH, revision=SHA, token=False)
cfg.device = "cpu"
policy = SmolVLAPolicy.from_pretrained(PATH, config=cfg, revision=SHA, token=False).eval()
pre, _post = make_pre_post_processors(
    cfg, pretrained_path=PATH, pretrained_revision=SHA,
    preprocessor_overrides={"device_processor": {"device": "cpu"}},
)

torch.manual_seed(0)
obs = {
    "observation.state": torch.rand(6, dtype=torch.float32),
    **{f"observation.images.camera{i}": torch.rand(3, 256, 256, dtype=torch.float32)
       for i in (1, 2, 3)},
    "task": "put the cube in the bowl",
}

events = {"vision": [], "prefill": [], "denoise": []}

def timed(name):
    def wrap(fn):
        @functools.wraps(fn)
        def inner(*args, **kwargs):
            t0 = time.perf_counter()
            try:
                return fn(*args, **kwargs)
            finally:
                events[name].append((time.perf_counter() - t0) * 1e3)
        return inner
    return wrap

vwe = policy.model.vlm_with_expert
vwe.embed_image = timed("vision")(vwe.embed_image)

orig_forward = vwe.forward
@functools.wraps(orig_forward)
def timed_forward(*args, **kwargs):
    inputs = kwargs.get("inputs_embeds")
    is_prefill = (
        kwargs.get("past_key_values") is None
        and kwargs.get("use_cache")
        and isinstance(inputs, (list, tuple)) and len(inputs) == 2
        and inputs[0] is not None and inputs[1] is None
    )
    t0 = time.perf_counter()
    try:
        return orig_forward(*args, **kwargs)
    finally:
        if is_prefill:
            events["prefill"].append((time.perf_counter() - t0) * 1e3)
vwe.forward = timed_forward

policy.model.denoise_step = timed("denoise")(policy.model.denoise_step)

def call():
    batch = pre(obs)
    t0 = time.perf_counter()
    with torch.no_grad():
        actions = policy.predict_action_chunk(batch)
    return (time.perf_counter() - t0) * 1e3, actions

call()  # warmup, discarded
for values in events.values():
    values.clear()
total_ms, actions = call()  # timed; events lists are then reduced to the JSONL rows
```

The actual harness also wrapped `embed_prefix`, `sample_actions`,
`prepare_images`, `prepare_state`, and `sample_noise` to produce the diagnostic
residual decomposition. It asserted `len(events["vision"]) == 3`,
`len(events["prefill"]) == 1`, and `len(events["denoise"]) == 10` before writing
any row.

## Limitations

- Timings are CPU wall-clock for one specific 6-core laptop CPU. They are not
  normalized for frequency or load and are not accelerator numbers.
- The trace has one timed call. The stability medians use three additional
  calls in the same process; they are descriptive, not a statistical confidence
  estimate.
- `other` is a residual; its sub-components are diagnostic measurements with
  wrapper overhead, not hardware counters.
- The vision/prefill/denoise boundaries follow the installed LeRobot 0.6.1
  method structure. A different LeRobot version with a different
  `sample_actions` implementation would need its hook points re-checked.
- The base checkpoint's normalizer is identity for the unqualified state/action
  keys, so the run does not exercise real dataset normalization.
- No closed-loop robot execution, task success, power, NoC, or memory-bandwidth
  measurement was performed.

## Verification summary

- Split: **worked**; 3 vision calls, 1 KV-cache prefill, 10 denoise steps.
- Canonical timed call: policy 1841.011 ms = vision 1102.660 + prefill 151.936 +
  denoise 577.780 + other 8.635 (exact).
- Stability medians: policy 1944.446 ms, vision 1173.113, prefill 151.695,
  denoise 610.108, other 11.677; denoise-step median 58.947 ms.
- Wrapper transparency: fixed-noise uninstrumented vs instrumented outputs were
  bitwise identical (`max_abs_diff = 0.0`).
- Output: `smolvla_vla_trace.jsonl`, 15 rows, sha256
  `eea4d4f59fbe6d63d3a508df2b31059c611ac790e0f88b50227f2b48de444a94`.
- Tests: `PYTHONPATH=. pytest -q tests/test_smolvla_stage_trace.py` ->
  **11 passed**.
