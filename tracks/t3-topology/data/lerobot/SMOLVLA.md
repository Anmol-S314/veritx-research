# SmolVLA LeRobot inference trace (real CPU run)

**This is a real model run, not a synthetic trace.** A LeRobot 0.6.1 `SmolVLAPolicy`
was loaded from `lerobot/smolvla_base` at a pinned revision, initialized with the
`SmolVLM2-500M-Video-Instruct` backbone, run on a synthetic observation with the
checkpoint's declared feature shapes on CPU, and the three documented pipeline stages
were timed. The `smolvla_trace.jsonl` rows were produced by
`tracks/t3-topology/tools/lerobot_trace_dump.py` from those measurements; no record was
hand-written into the output file.

- Date: 2026-11-05
- Host: Ubuntu 26.04 LTS, Linux 7.0.0-38-generic x86_64, AMD Ryzen 7 7445HS
  (6 cores / 12 threads), 14 GiB RAM, **CPU only** (no CUDA device)
- Output: `smolvla_trace.jsonl` (8 rows = 2 timed calls x 4 stages)
- Model run: **real** (`SmolVLAPolicy.predict_action_chunk`, 10 flow-matching denoise
  steps, 450,046,176 parameters)

## Environment

The existing `/tmp/opencode/lerobot-venv` from the ACT run was reused. The repository's
system Python was not touched. Only the four missing SmolVLA packages were installed;
`lerobot==0.6.1` was not reinstalled and `torch` was not replaced.

| Component | Version |
| --- | --- |
| venv | `/tmp/opencode/lerobot-venv` |
| Python | 3.12.13 (uv-managed CPython) |
| uv | 0.11.16 |
| lerobot | 0.6.1 |
| torch | 2.11.0+cpu |
| torchvision | 0.26.0+cpu |
| transformers | 5.5.4 |
| accelerate | 1.15.0 |
| num2words | 0.5.14 |
| scipy | 1.18.1 |
| tokenizers | 0.22.2 |
| numpy | 2.2.6 |
| huggingface-hub | 1.33.0 |
| safetensors | 0.8.0 |
| tokenizer / VLM | `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` |

`lerobot==0.6.1` declares the `smolvla` extra as
`transformers>=5.4.0,<5.6.0`, `accelerate>=1.14.0,<2.0.0`,
`num2words>=0.5.14,<0.6.0`. Those constraints were used directly instead of
`lerobot[smolvla]`, so the resolver could not reinstall LeRobot or pull a CUDA torch.

Exact install command:

```bash
uv pip install --python /tmp/opencode/lerobot-venv/bin/python \
  "transformers>=5.4.0,<5.6.0" "accelerate>=1.14.0,<2.0.0" \
  "num2words>=0.5.14,<0.6.0" "scipy>=1.14.0,<2.0.0" \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match
```

`uv pip list` after installation still reports `torch 2.11.0+cpu` and
`torchvision 0.26.0+cpu`. The install added 15 packages (the four targets plus
`regex`, `rich`, `typer`, `shellingham`, `docopt`, `psutil`, `pygments`,
`markdown-it-py`, `mdurl`, `annotated-doc`). `transformers 5.5.4` is the newest
release satisfying the 0.6.1 upper bound.

## Checkpoint

| Field | Value |
| --- | --- |
| Repo | `lerobot/smolvla_base` |
| Revision | `5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6` (last modified 2026-10-06) |
| Model | SmolVLA + SmolVLM2-500M backbone, 450,046,176 parameters |
| Weight dtypes | 474 bfloat16 tensors + 26 float32 tensors |
| Weight file | `model.safetensors`, 906,712,520 B, sha256 `7cd549ac2351fb069c0ddb3c34ad2d09cfc92b56a15dccdfc2e41467aaca01eb` |
| Config | `config.json`, 2,299 B, sha256 `650584b56c104720f7a3c91d1ec6bec9e8de8ac11e60c92ba2fa82d93eda147d` |
| Preprocessor | `policy_preprocessor.json`, 1,872 B, sha256 `7683d648280a72f0d51e869fb8dd1596beed90b7f84849330cf1bc26634a4bd6` |
| Preprocessor stats | `policy_preprocessor_step_5_normalizer_processor.safetensors`, 640 B, sha256 `490ab239d96e263687c0b2e386a0afbc235a2eceb9857c36ed32f2f162a3e7c8` |
| Postprocessor | `policy_postprocessor.json`, 660 B, sha256 `2b78bb742065288df2ec63b0ee35f97a1f6950171cf2272f7e34b1fe3873b17b` |
| Postprocessor stats | `policy_postprocessor_step_0_unnormalizer_processor.safetensors`, 640 B, sha256 `490ab239d96e263687c0b2e386a0afbc235a2eceb9857c36ed32f2f162a3e7c8` |

The 906 MB checkpoint stores the full 450 M-parameter policy (VLM trunk, action expert,
projections and 26 float32 auxiliary tensors). The state dict was checked explicitly
against the loaded policy: **500/500 tensors, 0 missing, 0 unexpected, 0 shape
mismatches, 0 dtype mismatches.**

The backbone initialization reads `HuggingFaceTB/SmolVLM2-500M-Video-Instruct` at
revision `7b375e1b73b11138ff12fe22c8f2822d8fe03467` (`AutoModelForImageTextToText` +
`AutoProcessor`), then the policy checkpoint overwrites all policy weights:

| Backbone file | Size (B) | sha256 |
| --- | ---: | --- |
| `config.json` | 3,767 | `ea6bc1237e96247f6258de3e202e2e62b93d6f386dc47e7b36b5588bf3a15e17` |
| `model.safetensors` | 2,029,990,624 | `b9bfd456c9472c0acd5719d6e514c4b859891af205ee1a736552fd3497b8b0c3` |
| `tokenizer.json` | 3,548,256 | `5ece781dc8d2b2f3e2f289ca0ae50b17cfc27dd27bfe7971bb8241e0b964331a` |
| `tokenizer_config.json` | 28,626 | `dd9ce2ab89a3dd881bd9378f1a79b943a064b9275a7e1706d5b7b47b68977913` |
| `preprocessor_config.json` | 599 | `149e315d9410368e5491455bb06e0f763426e9e56cca731c13b24404a29b6374` |
| `processor_config.json` | 67 | `f3ad45028447b3562b4752be0d5916d6806c1ef589091a469608dcf0faa1737c` |

Downloads used `token=False`; these files are public and the machine's cached HF token
is invalid. All loads were pinned to the revisions above.

## Derived model configuration (from the checkpoint, not guessed)

| Property | Value | Source |
| --- | --- | --- |
| Cameras / views | 3: `observation.images.camera1`, `camera2`, `camera3` | `config.json` `input_features` |
| Camera input resolution | `3 x 256 x 256` (CHW), float32 in `[0, 1]` | `config.json` |
| Internal image resize | pad to `512 x 512` (`resize_imgs_with_padding`), then scale `[0,1] -> [-1,1]` in `prepare_images` | config + `modeling_smolvla.py` |
| State dimension | 6 (`observation.state`) | `config.json` |
| Action dimension | 6 (`action`) | `config.json` |
| Padded state / action | 32 (`max_state_dim`, `max_action_dim`); actions sliced back to 6 | config + `_get_action_chunk` |
| Chunk size | 50 | `config.json` |
| `n_action_steps` | 50 | `config.json` |
| Denoise steps | 10 (`num_steps`) | `config.json`, flow matching |
| Tokenizer max length | 48, padding `max_length`, right side | `config.json` / `policy_preprocessor.json` |
| Language input | `task` string; newline appended; 7 real tokens plus padding for the prompt used | processor pipeline |
| Expected device | config says `cuda`; overridden to `cpu` (`PreTrainedConfig` also auto-switches and warns) | `config.json` |
| Weight dtype | bfloat16 for model weights, float32 for 26 auxiliary tensors | `model.safetensors` |

The checkpoint has `empty_cameras = 0`, so all three camera tensors must be supplied;
`prepare_images` raises if every image feature is missing. The model's action expert is
trained for `(batch, 50, 6)` chunks and `_get_action_chunk` slices the padded 32-wide
output back to 6.

## LeRobot 0.6.1 inference API and stage instrumentation

The installed 0.6.1 API exposes:

- `SmolVLAPolicy.from_pretrained(path, config=cfg)` — loads weights strictly
- `predict_action_chunk(batch)` -> `Tensor [batch, chunk_size, action_dim]`
- `select_action(batch)` -> one queued action (unchanged wrapper around the chunk call)
- `make_pre_post_processors(cfg, pretrained_path=..., preprocessor_overrides=...)` —
  loads the checkpoint's `policy_preprocessor.json` / `policy_postprocessor.json`

As with the ACT run, LeRobot 0.6.1 has **no** `lerobot.inference` module, so the
recorder's `PolicyRunner` / `ActionChunk.server_durations` snippet cannot be applied
verbatim. Stages were timed with `time.perf_counter()` around the documented calls, in
this order:

1. **preprocessing** = `preprocessor(observation)`: rename, batch dimension, newline
   task fix, tokenizer, device move, normalizer
2. **policy** = `policy.predict_action_chunk(batch)` under `torch.no_grad()`:
   image resize/pad, SigLIP-style normalization, state padding, 10 denoise steps
3. **postprocessing** = `postprocessor(actions)`: unnormalizer, move to CPU

`capture_time` is the `perf_counter` value immediately before preprocessing;
`duration_s` is the end-to-end span of the same three calls. The preprocessor's
`device_processor` step was overridden to `cpu`; the model config's device was set to
`cpu`. No other processor setting was changed.

## Observation and calls

The observation was generated once with `torch.manual_seed(0)` and reused for every
call. It is in memory only, with no simulator, camera, or dataset:

| Feature | Input | After preprocessor |
| --- | --- | --- |
| `observation.images.camera1` | `float32 [3, 256, 256]` in `[0, 1]` | `[1, 3, 256, 256]` |
| `observation.images.camera2` | `float32 [3, 256, 256]` in `[0, 1]` | `[1, 3, 256, 256]` |
| `observation.images.camera3` | `float32 [3, 256, 256]` in `[0, 1]` | `[1, 3, 256, 256]` |
| `observation.state` | `float32 [6]` | `[1, 6]` |
| `task` | `"put the cube in the bowl"` | 7 language tokens (`[1, 48]` ids, `[1, 48]` mask) |
| output `action` | - | `[1, 50, 6]` float32 |

Call plan: **3 calls total** - 1 warmup (executed, then discarded) and 2 timed calls
(recorded). Each timed call is about 2.5-2.8 s on this CPU, so the total run is short;
the warmup is not omitted for time reasons.

## Measured results

All values in milliseconds. `total` is the sum of the three sequential stages
(`duration_s = sum(server_durations)`).

| Call | preprocessing | policy | postprocessing | total |
| --- | ---: | ---: | ---: | ---: |
| warmup (discarded) | 1.485237 | 2838.663188 | 0.048752 | 2840.197177 |
| timed 1 | 0.566096 | 2794.364467 | 0.036909 | 2794.967472 |
| timed 2 | 0.350950 | 2461.770283 | 0.037671 | 2462.158904 |
| **median of timed (n=2)** | **0.458523** | **2628.067375** | **0.037290** | **2628.563188** |

With two samples the "median" is the mean of the two; it is descriptive, not a
statistical estimate. The policy stage is 99.98% of total. The 2.63 s chunk latency
corresponds to roughly 0.38 chunk inferences/s, or 19 actions/s if 50-action chunks
were executed back-to-back; that is **not** a robot control frequency and no execution
was performed.

Postprocessing is essentially free because of the checkpoint's normalizer state file
(see Limitations): it contains only dataset-qualified action statistics
(`so100.buffer.action.mean`, `so100-blue...`, `so100-red...`) and no plain
`observation.state` / `action` entries. LeRobot's `_apply_transform` returns the input
unchanged when the key is missing, so both normalization and unnormalization are
identity for this run. This was verified directly: preprocessor state in == state out,
and postprocessor left the action tensor values unchanged. The actions are therefore
raw model-space outputs, not SO-100 units.

The timed calls produce different actions because flow matching samples fresh noise
each call; that is expected and is not a determinism claim. Both outputs were
`float32 [1, 50, 6]`; value ranges were `[-0.408, 1.974]` and `[-0.243, 1.166]`
(model space).

## Output file

`smolvla_trace.jsonl` contains 8 compact JSONL rows: 2 records x the 4 stages
`preprocessing`, `policy`, `postprocessing`, `total`, in that fixed order. Example:

```json
{"timestamp_s":188409.30961575,"stage":"preprocessing","duration_ms":0.5660959868691862,
 "payload_bytes":2359296,"image_resolution":[256,256],"chunk_size":50,"n_action_steps":50}
```

`payload_bytes` is the byte size of the three float32 camera tensors passed to the
pipeline (`3 * 3 * 256 * 256 * 4 = 2,359,296`), following the recorder's
`feature.nbytes` convention. This is not a wire or JPEG payload. `image_resolution` is
`[height, width]` of the model input before the internal 512x512 pad/resize.
`chunk_size` is `actions.shape[1]` (50) and `n_action_steps` is the checkpoint config
value (50).

The two `timestamp_s` values are arbitrary monotonic `perf_counter` readings, not wall
clock times; rows with the same `timestamp_s` belong to the same call.

## Reproduction

```bash
# 1. Inference harness (this is the body; the run used exactly these calls).
HF_HOME=/home/datavex/.cache/huggingface OMP_NUM_THREADS=6 \
  /tmp/opencode/lerobot-venv/bin/python /tmp/opencode/smolvla_cpu_run.py \
  --raw-out /tmp/opencode/smolvla_raw.jsonl \
  --meta-out /tmp/opencode/smolvla_meta.json \
  --warmup 1 --calls 2

# 2. Normalize with the repository recorder (fails closed on malformed records).
cd /home/datavex/bruh/veritx-research
/tmp/opencode/lerobot-venv/bin/python tracks/t3-topology/tools/lerobot_trace_dump.py \
  --input /tmp/opencode/smolvla_raw.jsonl \
  --output tracks/t3-topology/data/lerobot/smolvla_trace.jsonl

# 3. Recorder tests.
cd tracks/t3-topology/dse
PYTHONPATH=. pytest -q tests/test_lerobot_trace_dump.py
```

The harness is not committed (only this data file and README were added). Its essential
body:

```python
import time, torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.factory import make_pre_post_processors
from lerobot.policies.smolvla.modeling_smolvla import SmolVLAPolicy

PATH = "/home/datavex/.cache/smolvla-base"
SHA  = "5e8d12a6e2975b0e5e5fce7c8caf47c371d257b6"

cfg = PreTrainedConfig.from_pretrained(PATH, revision=SHA, token=False)
cfg.device = "cpu"
policy = SmolVLAPolicy.from_pretrained(PATH, config=cfg, revision=SHA, token=False).eval()
pre, post = make_pre_post_processors(
    cfg,
    pretrained_path=PATH,
    pretrained_revision=SHA,
    preprocessor_overrides={"device_processor": {"device": "cpu"}},
)

torch.manual_seed(0)
obs = {
    "observation.state": torch.rand(6, dtype=torch.float32),
    "observation.images.camera1": torch.rand(3, 256, 256, dtype=torch.float32),
    "observation.images.camera2": torch.rand(3, 256, 256, dtype=torch.float32),
    "observation.images.camera3": torch.rand(3, 256, 256, dtype=torch.float32),
    "task": "put the cube in the bowl",
}

def call():
    t0 = time.perf_counter()
    batch = pre(obs)
    t1 = time.perf_counter()
    with torch.no_grad():
        actions = policy.predict_action_chunk(batch)
    t2 = time.perf_counter()
    out = post(actions)
    t3 = time.perf_counter()
    return {
        "capture_time": t0,
        "server_durations": {
            "preprocessing": t1 - t0,
            "policy": t2 - t1,
            "postprocessing": t3 - t2,
        },
        "duration_s": t3 - t0,
        "payload_bytes": sum(obs[k].nbytes for k in (
            "observation.images.camera1",
            "observation.images.camera2",
            "observation.images.camera3",
        )),
        "image_resolution": [256, 256],
        "chunk_size": int(out.shape[1]),
        "n_action_steps": int(cfg.n_action_steps),
    }

call()  # warmup, discarded
with open("/tmp/opencode/smolvla_raw.jsonl", "w") as f:
    for _ in range(2):
        f.write(json.dumps(call(), separators=(",", ":")) + "\n")
```

## Limitations

- **SmolVLA on CPU, not GR00T, not Jetson AGX Thor.** These are bfloat16/float32 CPU
  timings for a 450 M-parameter VLA on a 6-core laptop CPU. They say nothing about
  GR00T, Thor, GPU, or accelerator performance.
- **No NoC or fabric counters.** No interconnect, NoC, memory-bandwidth, or power
  measurement was made. The three stages are wall-clock timings only.
- **Synthetic observation, no closed loop.** The images and state are random tensors.
  There is no camera, simulator, robot, action execution, or success metric. The action
  range check is not a task-performance result.
- **Base checkpoint, not a fine-tune.** `lerobot/smolvla_base` is a generalist starting
  point. Its outputs on a random observation are not meaningful actions.
- **Normalization is identity in this run.** The checkpoint's normalizer state file
  contains only `so100*`-qualified action statistics, so LeRobot 0.6.1 finds no
  `observation.state` or `action` entry and returns both unchanged. The policy still
  consumes the 6-D state and produces 6-D actions, but they are not dataset-scaled. The
  postprocessing stage measures a pass-through plus CPU move, not real unnormalization.
- **Two timed samples.** Medians are descriptive and not robust; run-to-run variance
  was not characterized. The warmup policy stage was 8% above the timed median
  (2838.7 ms vs 2628.1 ms) but only 1.6% above timed call 1 (2794.4 ms); it is excluded
  as a warmup, not as a systematic outlier.
- **Call-site timing.** LeRobot 0.6.1 does not report the three stage durations itself.
  They were measured around `preprocessor`, `predict_action_chunk`, and `postprocessor`
  on the same process and clock. On CPU synchronization overhead is negligible, but
  these are not server-internal counters.
- **Dtype path.** The checkpoint is bfloat16 and CPU inference uses PyTorch's bf16 CPU
  kernels; no autocast, quantization, `torch.compile`, or KV-cache reuse across calls
  was enabled or measured.
- **RTC not exercised.** `rtc_config` is absent in the checkpoint, so real-time
  chunking behaviour was not tested.

## Verification

`PYTHONPATH=. pytest -q tests/test_lerobot_trace_dump.py` -> **8 passed** (0.49 s).

`smolvla_trace.jsonl`: 8 rows, sha256
`5d91310c6fd84de191bb33ef7ca4cccf1b06d232033dd9733d88804af60052fa`.

The existing ACT files (`act_pusht_trace.jsonl`, `README.md`) were not modified.
