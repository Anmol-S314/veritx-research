# LeRobot trace recorder

Status: runnable tool plus synthetic tests. No LeRobot install, model run, GPU
run, or fabric measurement is part of this repository's evidence yet.

LeRobot is Apache-2.0 (`huggingface/lerobot`). This repository does not modify
LeRobot and does not vendor it. The recorder consumes the records a patched
LeRobot deployment emits and normalizes them for a future fabric trace. The
tool is stdlib-only.

Checked against upstream `main` at commit `9e5ee98` (2026-11-04). Hook names
move; re-check them when LeRobot is upgraded.

Two generations matter:

- **`main` with `lerobot.inference`** — the `PolicyRunner` hook below exposes
  `server_durations` directly.
- **PyPI 0.6.1** — there is **no `lerobot.inference` module**. The verified ACT
  run instruments around `preprocessor(obs)` → `ACTPolicy.predict_action_chunk`
  → `postprocessor(actions)`; see “Verified ACT CPU run” below.

## What it proves, and what it does not

When run against a real LeRobot process, the recorder can prove:

- the three Python-level stage durations LeRobot itself computes:
  `preprocessing`, `policy`, and `postprocessing`, in seconds;
- the observation arrival timestamp (`capture_time`) attached to the request;
- the end-to-end arrival-to-result duration measured by the emitter;
- the decoded observation payload size, image resolution, predicted chunk
  length, and number of replay steps per call, when the emitter supplies them.

It does **not** prove:

- a GR00T N1.x trace. LeRobot can load different policies, but these hooks are
  not NVIDIA's GR00T deployment harness and do not produce GR00T stage splits.
- a Jetson Thor measurement. Nothing here runs on Thor or reports its clocks,
  power, or memory bandwidth.
- NoC, interconnect, PCIe, DRAM, or GPU counters. There are no fabric telemetry
  counters in LeRobot's inference path.
- wire bytes. `payload_bytes` from the provided snippet is decoded RGB bytes.
  Zenoh framing, raw-RGB versus JPEG q90 encoding, retransmits, and protocol
  overhead are not included unless measured separately at the transport.
- closed-loop sensor-to-actuator latency. The hook ends when prediction
  returns, not when an actuator applies the action.
- power, energy, accuracy, safety, or real-time schedulability.
- kernel-level or operator-level timing. The stages are Python boundaries
  around a processor pipeline and a policy call.

## Record shape

One input record is one completed prediction. The required fields are
`capture_time`, `server_durations` with all three stages, and `duration_s`.
The other fields are optional.

```json
{
  "capture_time": 123.5,
  "server_durations": {
    "preprocessing": 0.0125,
    "policy": 0.030,
    "postprocessing": 0.005
  },
  "duration_s": 0.050,
  "payload_bytes": 921600,
  "image_resolution": [480, 640],
  "chunk_size": 50,
  "n_action_steps": 25
}
```

Units and accepted forms:

| Field | Required | Meaning | Unit / form |
|---|---|---|---|
| `capture_time` | yes | observation arrival timestamp on the emitter's monotonic clock | seconds, finite, non-negative |
| `server_durations.preprocessing` | yes | LeRobot preprocessor stage | seconds, finite, non-negative |
| `server_durations.policy` | yes | LeRobot policy inference stage | seconds, finite, non-negative |
| `server_durations.postprocessing` | yes | LeRobot postprocessor stage | seconds, finite, non-negative |
| `duration_s` | yes | end-to-end duration measured by the emitter; not recomputed by the tool | seconds, finite, non-negative |
| `payload_bytes` | no | decoded observation bytes, or a transport measurement if supplied | non-negative integer |
| `image_resolution` | no | camera frame size | `[height, width]` or a non-empty string such as `"480x640"` |
| `chunk_size` | no | predicted action-chunk length | non-negative integer |
| `n_action_steps` | no | actions replayed before the next prediction | non-negative integer |

Extra keys are ignored, so a wrapper can attach request IDs or policy names
without changing this tool. The tool does not check that `duration_s` equals
the stage sum; the difference is useful queueing/transport/overhead signal and
must not be silently erased.

## Output shape

Each input record becomes four rows, always in this order:
`preprocessing`, `policy`, `postprocessing`, `total`.

```json
{"timestamp_s":123.5,"stage":"preprocessing","duration_ms":12.5,"payload_bytes":921600,"image_resolution":[480,640],"chunk_size":50,"n_action_steps":25}
{"timestamp_s":123.5,"stage":"policy","duration_ms":30.0,"payload_bytes":921600,"image_resolution":[480,640],"chunk_size":50,"n_action_steps":25}
{"timestamp_s":123.5,"stage":"postprocessing","duration_ms":5.0,"payload_bytes":921600,"image_resolution":[480,640],"chunk_size":50,"n_action_steps":25}
{"timestamp_s":123.5,"stage":"total","duration_ms":50.0,"payload_bytes":921600,"image_resolution":[480,640],"chunk_size":50,"n_action_steps":25}
```

`timestamp_s` is the observation arrival time, not the row's stage-start time.
A consumer can reconstruct stage starts by accumulating durations in the fixed
order, or join all four rows on `timestamp_s`. The metadata fields are repeated
on every row so the JSONL remains flat and order-independent.

The output is deterministic: fixed stage order, fixed key order, compact JSON,
one object per line. Optional fields are `null` when absent. Invalid input
raises `TraceRecordError`; the CLI validates the whole input before opening the
output, so a bad record does not leave a partial output file.

## Exact LeRobot hook points

### 1. `src/lerobot/inference/policy_runner.py` — `PolicyRunner.predict`

This is the authoritative three-stage split. The method:

- takes `started = time.perf_counter()`;
- runs `self.preprocessor(self._batch(observation))`, then takes
  `preprocessed_at = time.perf_counter()`;
- runs `predict_chunk(...)`, whose result carries `prediction.predicted_at`;
- takes `finished = time.perf_counter()`;
- returns an `ActionChunk` with:

```python
server_durations={
    "preprocessing": preprocessed_at - started,
    "policy": prediction.predicted_at - preprocessed_at,
    "postprocessing": finished - prediction.predicted_at,
}
```

The `ActionChunk` also carries `execution_steps=len(canonical)` and
`provenance`. That is where the recorder's `n_action_steps` and
`capture_time` come from.

`instrumentation_snippet()` in
`tracks/t3-topology/tools/lerobot_trace_dump.py` returns the documented
~30-line patch: add a `_trace_chunk(...)` helper at module scope, replace the
final `return ActionChunk(...)` with a named `chunk`, call the helper, then
return the chunk. The helper is gated by `LEROBOT_TRACE_JSONL`, so an
unpatched path or an unset variable writes nothing.

### 2. `src/lerobot/inference/contracts.py` — provenance and durations

- `ObservationSnapshot.capture_time` is the request's observation arrival time.
  It is validated finite when the snapshot is built.
- `ActionProvenance.capture_time` copies that value, with the oldest
  contributing capture time after blending.
- `ActionChunk.server_durations` is the mapping above.
- `ActionChunk` is the object a server/transport wrapper sees before it is
  serialized to a client.

The provided snippet measures `duration_s` as
`time.perf_counter() - observation.capture_time` at the hook. That is an
arrival-to-result duration **only if** `capture_time` and `perf_counter()` use
the same monotonic clock base. LeRobot's own latency paths use
`time.monotonic()` in places; do not mix clocks. If the host stamps
`capture_time` from a different domain, supply `duration_s` from an explicit
measurement around the call instead.

### 3. `src/lerobot/inference/latency.py` — `LatencyWindow`

`LatencyWindow` is an in-memory diagnostic, not a trace sink:

- `configure(interval_s)` sets the retention window before engine startup;
  zero (the default) disables collection.
- `record(elapsed, completed_at)` appends `(completed_at, elapsed)` after
  pruning, but only when enabled.
- `recent(now)` returns the durations completed in the window.
- `SyncPolicyEngine` calls `self.latency.record(completed - started, completed)`
  around inline inference.
- `ExecutionEngine.accept` calls `self.latency.record(elapsed, now)` when an
  asynchronous chunk completes.

Nothing in LeRobot persists those samples. To use them, either wrap/tap
`record`, or use the `policy_runner` hook above. `completed_at - capture_time`
is a valid end-to-end duration only when both timestamps come from the same
monotonic clock. The recorder's `timestamp_s` is always `capture_time`; it does
not read `LatencyWindow` directly.

### 4. Transport and dataset metadata

The Zenoh transport lives in `src/lerobot/transport/zenoh.py` and has a
`max_payload_bytes` bound. It does not, by itself, emit one record per
prediction with all of these fields. If you need wire sizes for raw RGB or
JPEG q90, capture them at the transport and put the measured value in
`payload_bytes`; the provided snippet reports decoded RGB bytes instead.

Dataset metadata (`timestamp`, `fps`, image resolution, chunk size) describes
recorded episodes, not per-request inference. The recorder copies
`image_resolution`, `chunk_size`, and `n_action_steps` from the emitter; it
does not infer them from a dataset. State that provenance next to any number.

## Verified ACT CPU run (LeRobot 0.6.1)

A real ACT policy was run on CPU, not a mock:

- Checkpoint: `aadarshram/act_pusht`, revision `6d403b1…` (Apache-2.0);
  `lerobot/act_pusht` does not exist. All 234 `model.*` tensors mapped into
  `ACTPolicy` with 0 missing/unexpected/shape mismatches.
- Environment: Python 3.12.13, torch 2.11.0+cpu, lerobot 0.6.1.
- Observation: synthetic `[3,96,96]` image + `[2]` state; output `[1,100,2]`.
- Calls: 1 warmup + 2 timed.

| Stage | Median |
|---|---:|
| preprocessing | 0.1165 ms |
| policy | 30.7484 ms |
| postprocessing | 0.0772 ms |
| total | 30.9422 ms |

Policy is **>99%** of the call. This validates the recorder and gives a real
small-policy trace; it is **not** a VLA and does not resemble GR00T’s
vision/backbone/action split.

- Trace: `tracks/t3-topology/data/lerobot/act_pusht_trace.jsonl` (8 rows).
- Reproduction and exact versions:
  `tracks/t3-topology/data/lerobot/README.md`.

## Verified SmolVLA CPU run (LeRobot 0.6.1)

A real SmolVLA policy was also run on CPU:

- Checkpoint: `lerobot/smolvla_base` @ `5e8d12a…`; 450,046,176 params;
  SmolVLM2-500M-Video-Instruct backbone.
- Inputs: 3 cameras at 256×256, state `[6]`, task string, chunk 50,
  `n_action_steps` 50, 10 flow-matching steps.
- One warmup + 2 timed calls.

| Stage | Median |
|---|---:|
| preprocessing | 0.459 ms |
| policy | 2,628.067 ms |
| postprocessing | 0.037 ms |
| total | 2,628.563 ms |

Policy is **99.98%** of the call. This is a real VLA-ish model (VLM backbone +
action expert), but the recorder still sees only three Python stages; it does
**not** split vision / VLM prefill / action head. It also is not real-time:
~2.6 s per chunk on this CPU.

Caveat: the base checkpoint’s normalizer state file only carries
`so100*`-qualified action stats, so normalization/unnormalization were identity
in this run; documented in the provenance file.

- Trace: `tracks/t3-topology/data/lerobot/smolvla_trace.jsonl` (8 rows).
- Reproduction: `tracks/t3-topology/data/lerobot/SMOLVLA.md`.

## Running LeRobot for a trace

Install LeRobot in its own checkout or environment. Do not install it in this
repository just to run the recorder's synthetic tests.

The `lerobot-rollout` examples below require a robot or simulator; they were
**not** the verified path. The verified ACT run used a direct Python script
around the 0.6.1 policy API (see
`tracks/t3-topology/data/lerobot/README.md`). Treat the rollout flags as
version-dependent until checked against the installed release.

```bash
# In a LeRobot checkout, for example:
pip install -e .
pip install 'lerobot[smolvla]'   # SmolVLA extras
pip install 'lerobot[pi]'        # pi0 / pi0.5 extras
```

`lerobot-rollout` is the deployment entry point. Current LeRobot accepts
`--device=cpu` or `--device=cuda` to override the checkpoint device.

### ACT on CPU

```bash
lerobot-rollout \
  --strategy.type=base \
  --policy.path=lerobot/act_koch_real \
  --device=cpu \
  --robot.type=koch_follower \
  --robot.port=/dev/ttyACM0 \
  --task="pick up cube" \
  --duration=30
```

### SmolVLA on CPU

```bash
lerobot-rollout \
  --strategy.type=base \
  --policy.path=lerobot/smolvla_base \
  --device=cpu \
  --robot.type=so100_follower \
  --robot.port=/dev/ttyACM0 \
  --task="Put the cube in the box" \
  --duration=30
```

CPU runs are for tracing and determinism checks. Do not use their stage times
to claim a real-time control rate, and do not transfer CPU numbers to a GPU or
to Thor. If you use `lerobot-eval` instead of `lerobot-rollout`, the device flag
is `--policy.device`, not `--device`; confirm the flag against the installed
LeRobot version.

### π0 on GPU

π0 is a roughly 3B-parameter VLA. Use a CUDA device with enough memory for the
checkpoint and activations; measure, do not assume, the fit.

```bash
lerobot-rollout \
  --strategy.type=base \
  --policy.path=lerobot/pi0_libero_finetuned \
  --device=cuda \
  --robot.type=so100_follower \
  --robot.port=/dev/ttyACM0 \
  --task="Put the cube in the box" \
  --duration=30
```

LeRobot's hardware guide lists a large-VLA training envelope of roughly
24–40 GB (A100 40 GB recommended, 24 GB tight at batch size 1). Inference is
usually smaller, but the exact fit depends on dtype, image transforms, and the
policy wrapper. Report the GPU model, dtype, batch size, and checkpoint
alongside every trace.

### Emit and normalize

Apply the snippet from `instrumentation_snippet()` to the LeRobot checkout,
then run with a trace path:

```bash
export LEROBOT_TRACE_JSONL=/tmp/lerobot-records.jsonl
# ... run lerobot-rollout as above ...
unset LEROBOT_TRACE_JSONL

python3 tracks/t3-topology/tools/lerobot_trace_dump.py \
  --input /tmp/lerobot-records.jsonl \
  --output /tmp/lerobot-rows.jsonl
```

The stdin/stdout form is:

```bash
python3 tracks/t3-topology/tools/lerobot_trace_dump.py --stdin --stdout \
  < /tmp/lerobot-records.jsonl > /tmp/lerobot-rows.jsonl
```

`--input` and `--stdin` are mutually exclusive; `--output` and `--stdout` are
mutually exclusive. With neither side specified, the tool behaves as a filter
on stdin/stdout.

## Feeding a future fabric trace

The rows are intentionally close to a trace event table. A future importer can
map them as follows:

| Fabric trace concept | Recorder field | Unit / rule |
|---|---|---|
| arrival time | `timestamp_s` | seconds; multiply by `1e9` for ns |
| compute service time | `duration_ms` on a stage row | milliseconds; multiply by `1e6` for ns |
| end-to-end reference | `duration_ms` on `total` | milliseconds; do not add it to stage service times |
| message size | `payload_bytes` | bytes; `null` means unknown, not zero |
| frame geometry | `image_resolution` | `[height, width]` or string; `null` means unknown |
| predicted horizon | `chunk_size` | frames per predicted chunk |
| replay length | `n_action_steps` | actions executed before replanning |

Suggested import rules:

1. Sort by `(timestamp_s, stage_order)` where `stage_order` is the fixed
   sequence; do not depend on JSON object key order in the source.
2. Emit one compute event per stage row. Treat `total` as a span/deadline
   reference, not another compute event.
3. Use `timestamp_s` deltas as inter-arrival periods only within one process
   and one monotonic-clock domain. The rows have no run ID; align separate runs
   explicitly or add a wrapper-level run ID.
4. Compute `residual_ms = total.duration_ms - (preprocessing + policy +
   postprocessing).duration_ms`. Label it queue/transport/overhead unless you
   have a separate measurement that attributes it.
5. If `payload_bytes` is `null`, keep it unknown. Do not substitute decoded
   image dimensions times three; that is a different quantity.
6. Keep `image_resolution` as supplied. A consumer that needs two integers must
   handle both the list form and the string form.

This is enough to seed a workload model with measured stage service times,
arrival spacing, and message sizes. It is not enough to claim a measured
network trace. The fabric traversal, protocol overhead, and any raw-versus-JPEG
difference must be measured or modeled separately, and labeled as such.

## Tests

```bash
cd tracks/t3-topology/dse
PYTHONPATH=. pytest -q tests/test_lerobot_trace_dump.py
```

The tests are synthetic and require no LeRobot installation:

- one valid record produces four rows with the expected millisecond values and
  fixed stage order;
- a missing stage raises `TraceRecordError`;
- a negative stage duration raises `TraceRecordError`;
- absent optional fields become `null` and still produce four valid rows;
- file-to-file CLI round-trip through `tmp_path`;
- invalid CLI input leaves no partial output;
- the `--stdin`/`--stdout` filter produces the same four-row order;
- the instrumentation snippet names all three stages plus `capture_time`.

## Do not claim

Do not present a trace from this tool as any of the following:

- a GR00T N1.7 trace, a GR00T N1.6 trace, or an NVIDIA deployment trace;
- a Jetson Thor measurement, or a measurement of Thor's fabric, memory, or
  power;
- a NoC capture, interconnect counter trace, or fabric bandwidth measurement;
- a Zenoh wire capture, a raw-RGB byte count, or a JPEG q90 byte count unless
  the transport was separately instrumented;
- a closed-loop sensor-to-actuator latency;
- a kernel-level, operator-level, or GPU-utilization profile;
- a real-time control-rate guarantee, especially from a CPU run;
- an accuracy, safety, or functional-safety result;
- a comparison across checkpoints, image encodings, batch sizes, or devices
  without carrying those configuration columns with the number.

The honest claim is narrower: real LeRobot process timings for the three
instrumented stages, real observation arrival timestamps, and whatever payload
metadata the emitter actually measured, normalized into a flat JSONL schema.
