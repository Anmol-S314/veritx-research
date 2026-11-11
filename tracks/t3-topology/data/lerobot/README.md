# ACT PushT LeRobot inference trace (real CPU run)

**This is a real model run, not a model or a synthetic trace.** A LeRobot 0.6.1
`ACTPolicy` was loaded from a Hugging Face checkpoint, run on a synthetic PushT-shaped
observation on CPU, and the three documented pipeline stages were timed. The
`act_pusht_trace.jsonl` rows were produced by
`tracks/t3-topology/tools/lerobot_trace_dump.py` from those measurements; no record was
hand-written into the output file.

- Date: 2026-11-05
- Host: Ubuntu 26.04 LTS, Linux 7.0.0-38-generic x86_64, AMD Ryzen 7 7445HS
  (6 cores / 12 threads), 14 GiB RAM, **CPU only** (no CUDA device)
- Output: `act_pusht_trace.jsonl` (8 rows = 2 timed calls x 4 stages)

## Environment

An isolated venv was created so the repository's system Python 3.14 + torch 2.12
environment was not touched. LeRobot 0.6.1 requires Python >= 3.12 and torch
`<2.12,>=2.7`; the system torch 2.12 does not satisfy it.

| Component | Version |
| --- | --- |
| venv | `/tmp/opencode/lerobot-venv` |
| Python | 3.12.13 (uv-managed CPython) |
| uv | 0.11.16 |
| lerobot | 0.6.1 |
| torch | 2.11.0+cpu |
| torchvision | 0.26.0+cpu |
| numpy | 2.2.6 |
| pillow | 12.3.0 |
| huggingface-hub | 1.33.0 |
| safetensors | 0.8.0 |
| einops | 0.8.2 |
| draccus | 0.11.6 |
| opencv-python-headless | 4.13.0.92 |
| gymnasium | 1.4.0 |
| cmake | 4.1.3 |

Only LeRobot's base dependencies were installed. The `pusht` extra (`gym-pusht`,
`pymunk`) was not installed because no simulator was used; ACT inference needs only the
base policy, torch, and the processor pipeline. `transformers` was not installed and is
not used by ACT.

Exact install commands:

```bash
uv venv --python 3.12 /tmp/opencode/lerobot-venv

uv pip install --python /tmp/opencode/lerobot-venv/bin/python \
  torch==2.11.0 torchvision==0.26.0 \
  --index-url https://download.pytorch.org/whl/cpu

uv pip install --python /tmp/opencode/lerobot-venv/bin/python \
  lerobot==0.6.1 \
  --extra-index-url https://download.pytorch.org/whl/cpu \
  --index-strategy unsafe-best-match
```

The CPU index is required: the default PyPI torch wheel is a CUDA build and does not fit
this CPU-only box. The final environment reports `torch 2.11.0+cpu`.

## Checkpoint

| Field | Value |
| --- | --- |
| Repo | `aadarshram/act_pusht` |
| Revision | `6d403b142934aaef61fc07f5eec1515c4325751f` (`main` on 2026-11-05) |
| Model | ACT, 51,588,994 parameters, float32, chunk size 100, `n_action_steps` 100 |
| Dataset in model card | `lerobot/pusht`, 80,000 training steps |
| License | Apache-2.0 (model card) |
| Weight file | `model.safetensors`, 206,666,936 B, sha256 `dfa923d7f82fc152b5c70e27aa7087ebd0f5fd86a486c22ea255748d0a932208` |
| Config | `config.json`, 1,478 B, sha256 `541ce265150b3f45ee7c8d43d308facfc31a8e07f8d8bcb95bb5fc3df86bb981` |
| Preprocessor | `policy_preprocessor.json` + `policy_preprocessor_step_3_normalizer_processor.safetensors` (4,204 B) |
| Postprocessor | `policy_postprocessor.json` + `policy_postprocessor_step_0_unnormalizer_processor.safetensors` (4,204 B) |

`lerobot/act_pusht` (the originally preferred ID) does **not** exist: on 2026-11-05 its
Hub page returns 404 and its API/resolve endpoints return 401, and the `lerobot` org
listing contains no ACT PushT checkpoint. The nearest official ACT checkpoints are
`lerobot/act_aloha_sim_transfer_cube_human` and `lerobot/act_aloha_sim_insertion_human`,
but both predate LeRobot's processor-pipeline format (no `policy_preprocessor.json`).
`aadarshram/act_pusht` is a PushT ACT checkpoint already stored in the native 0.6.x
format, so its real normalization statistics load from the checkpoint's processor state
files rather than being re-derived or invented.

Weight mapping was checked explicitly against the 0.6.1 `ACTPolicy` state dict: all 234
`model.*` tensors are present, with 0 missing keys, 0 unexpected keys and 0 shape
mismatches. Normalization lives only in the processor state files.

Downloads used `token=False`; the machine's cached HF token is invalid, and these files
are public. The revision was pinned for all downloads and loads.

## LeRobot 0.6.1 inference API and stage instrumentation

LeRobot 0.6.1 exposes the documented methods on `ACTPolicy`:

- `predict_action_chunk(batch)` -> `Tensor` of shape `[batch, chunk_size, action_dim]`
- `select_action(batch)` -> one queued action (it calls `predict_action_chunk` when the
  100-step queue is empty)
- `make_pre_post_processors(...)` in `lerobot.policies.factory`, which loads
  `policy_preprocessor.json` / `policy_postprocessor.json`

The installed 0.6.1 package has **no** `lerobot.inference` module, so the recorder's
`PolicyRunner` / `ActionChunk.server_durations` snippet cannot be applied verbatim. At
this call site LeRobot does not expose per-stage durations, so the three stages were
timed with `time.perf_counter()` around the documented calls, in this order:

1. **preprocessing** = `preprocessor(observation)` (rename, add batch dimension, move to
   CPU device, normalizer)
2. **policy** = `policy.predict_action_chunk(batch)` under `torch.no_grad()`
3. **postprocessing** = `postprocessor(actions)` (unnormalizer, move to CPU)

`capture_time` is the `perf_counter` value immediately before preprocessing;
`duration_s` is the end-to-end span of the same three calls. This is a genuine stage
attribution of this pipeline, but it is measured at the call site, not reported by
LeRobot internals.

The config and preprocessor were built for `cuda`. The config's `device` was set to
`cpu`, and the preprocessor's `device_processor` step was overridden to `cpu` when
loading the pipeline. No other processor settings were changed.

## Observation and calls

The synthetic observation matches the checkpoint's declared features:

| Feature | Input tensor | After preprocessor |
| --- | --- | --- |
| `observation.image` | `float32 [3, 96, 96]` in `[0, 1]` | `[1, 3, 96, 96]` |
| `observation.state` | `float32 [2]` | `[1, 2]` |
| output `action` | - | `[1, 100, 2]` |

The observation was generated once with `torch.manual_seed(0)` and reused for every
call. It is a random tensor, not a real PushT camera frame and not a simulator state.

Call plan: **3 calls total** - 1 warmup (executed, then discarded) and 2 timed calls
(recorded). The model is fast enough for this; the warmup is not omitted for time
reasons.

## Measured results

All values in milliseconds. `total` is the sum of the three sequential stages
(`duration_s = sum(server_durations)`).

| Call | preprocessing | policy | postprocessing | total |
| --- | ---: | ---: | ---: | ---: |
| warmup (discarded) | 0.284 | 36.179 | 0.083 | 36.546 |
| timed 1 | 0.115086 | 30.654837 | 0.082205 | 30.852128 |
| timed 2 | 0.117992 | 30.842030 | 0.072206 | 31.032228 |
| **median of timed (n=2)** | **0.116539** | **30.748434** | **0.077206** | **30.942178** |

With two samples the "median" is the mean of the two; it is descriptive, not a
statistical estimate. The policy stage dominates (>99% of total). A 30.94 ms chunk
inference implies about 32 chunk inferences/s for this single-process CPU pipeline, but
each chunk contains 100 actions, so this is **not** a robot control frequency.

Output actions for both timed calls were `float32 [1, 100, 2]` with value range
`[33.210, 450.312]` in the checkpoint's unnormalized PushT action space. This is a
shape/range sanity check only; task success was not evaluated.

## Output file

`act_pusht_trace.jsonl` contains 8 compact JSONL rows: 2 records x the 4 stages
`preprocessing`, `policy`, `postprocessing`, `total`, in that fixed order. Each record
carries:

```json
{"timestamp_s":186929.680368916,"stage":"preprocessing","duration_ms":0.1150860043708235,
 "payload_bytes":110592,"image_resolution":[96,96],"chunk_size":100,"n_action_steps":100}
```

`payload_bytes` is the byte size of the float32 image tensor actually passed to the
pipeline (`3 * 96 * 96 * 4 = 110,592`), following the recorder's `feature.nbytes`
convention. The equivalent 8-bit RGB frame would be 27,648 B; this field is not a wire
or JPEG payload. `image_resolution` is `[height, width]`. `chunk_size` is
`actions.shape[1]` (100) and `n_action_steps` is the checkpoint config value (100).

The two `timestamp_s` values are arbitrary monotonic `perf_counter` readings, not wall
clock times; rows with the same `timestamp_s` belong to the same call.

## Reproduction

```bash
# 1. Inference harness (this is the body; the run used exactly these calls).
/tmp/opencode/lerobot-venv/bin/python /tmp/opencode/lerobot_act_pusht_run.py \
  --raw-out /tmp/opencode/lerobot_act_pusht_raw.jsonl --warmup 1 --calls 2

# 2. Normalize with the repository recorder (fails closed on malformed records).
cd /home/datavex/bruh/veritx-research
/tmp/opencode/lerobot-venv/bin/python tracks/t3-topology/tools/lerobot_trace_dump.py \
  --input /tmp/opencode/lerobot_act_pusht_raw.jsonl \
  --output tracks/t3-topology/data/lerobot/act_pusht_trace.jsonl

# 3. Recorder tests.
cd tracks/t3-topology/dse
PYTHONPATH=. pytest -q tests/test_lerobot_trace_dump.py
```

The harness is not committed (only this data file and README were added). Its essential
body:

```python
import json, time, torch
from lerobot.configs.policies import PreTrainedConfig
from lerobot.policies.act.modeling_act import ACTPolicy
from lerobot.policies.factory import make_pre_post_processors

REPO  = "aadarshram/act_pusht"
SHA   = "6d403b142934aaef61fc07f5eec1515c4325751f"

cfg = PreTrainedConfig.from_pretrained(REPO, revision=SHA, token=False)
cfg.device = "cpu"
policy = ACTPolicy.from_pretrained(REPO, config=cfg, revision=SHA, token=False).eval()
pre, post = make_pre_post_processors(
    cfg,
    pretrained_path=REPO,
    pretrained_revision=SHA,
    preprocessor_overrides={"device_processor": {"device": "cpu"}},
)

torch.manual_seed(0)
obs = {
    "observation.image": torch.rand(3, 96, 96, dtype=torch.float32),  # CHW, [0,1]
    "observation.state": torch.rand(2, dtype=torch.float32),
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
        "payload_bytes": int(obs["observation.image"].nbytes),
        "image_resolution": [96, 96],
        "chunk_size": int(out.shape[1]),
        "n_action_steps": int(cfg.n_action_steps),
    }

call()  # warmup, discarded
with open("/tmp/opencode/lerobot_act_pusht_raw.jsonl", "w") as f:
    for _ in range(2):
        f.write(json.dumps(call(), separators=(",", ":")) + "\n")
```

## Limitations

- **ACT on CPU, not GR00T, not Jetson AGX Thor.** These are float32 CPU timings for a
  51.6 M-parameter ACT policy on a 6-core laptop CPU. They say nothing about GR00T,
  Thor, GPU, or accelerator performance.
- **No NoC or fabric counters.** No interconnect, NoC, memory-bandwidth, or power
  measurement was made. The three stages are wall-clock timings only.
- **Synthetic observation, no closed loop.** The image and state are random tensors.
  There is no camera, simulator, robot, action execution, or success metric. The action
  range check is not a task-performance result.
- **Two timed samples.** Medians are descriptive and not robust; run-to-run variance
  was not characterized. The warmup was 18% slower in the policy stage
  (36.2 ms vs 30.7 ms), which is why it is excluded.
- **Call-site timing.** LeRobot 0.6.1 does not report the three stage durations itself.
  They were measured around `preprocessor`, `predict_action_chunk`, and `postprocessor`
  on the same process and clock. Synchronization overhead is negligible on CPU, but
  these are not server-internal counters.
- **Checkpoint provenance.** The checkpoint is a community PushT ACT model trained on
  `lerobot/pusht`, not an official `lerobot/act_pusht` release (which no longer exists).
  Only the model's inference path was exercised; no accuracy, success rate, or
  generalization claim is made.
- **Version skew.** The checkpoint was produced by an earlier LeRobot 0.6.x. The 0.6.1
  loader accepted its config and all 234 `model.*` tensors; its normalization statistics
  were loaded from the checkpoint's processor state files. No keys were silently
  dropped from the core model.

## Verification

`PYTHONPATH=. pytest -q tests/test_lerobot_trace_dump.py` -> **8 passed** (0.33 s).

`act_pusht_trace.jsonl`: 8 rows, sha256
`eb3f58a144796079b7d49f9613f816819b5935a3c9b64a81399bdee71bafb7ed`.
