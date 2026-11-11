# NVIDIA Robotics use case: the fabric behind a VLA pipeline

Status: demo brief with public source numbers. The Thor template uses measured
compute durations from NVIDIA’s model card; its fabric, traffic, and control
shape is authored. It is not a measured GR00T trace. Read the limitations before
presenting a number as a hardware result.

## The workload

A humanoid robot runs a vision-language-action (VLA) pipeline on an edge SoC:

```
cameras → ISP → vision encoder → VLM backbone → action head → motor control
```

GR00T N1.7-3B is the public reference:

- 3.14 B parameters; Cosmos-Reason2-2B backbone, 16 of 28 text layers kept
- 256×256 images, 64 image tokens per camera
- 32-layer diffusion action head, 4 denoise steps, action horizon 40
- System 2 (VLM) at ~10 Hz; System 1 (action head) at up to 120 Hz on the N1 paper

Jetson AGX Thor T5000 is the public edge envelope:

- 128 GB LPDDR5X, 273 GB/s, 40–130 W
- 14× Neoverse V3AE, 2070 FP4 TFLOPS sparse / 1035 dense
- PCIe Gen5 ×8, 16-lane CSI, 4×25 GbE

## What the public numbers say

| Fact | Value | Source | Confidence |
|---|---:|---|---|
| GR00T N1.7 E2E on Thor, base checkpoint, 1 camera, 4 steps | 93.8 ms / 10.7 Hz | NVIDIA model card | measured by source |
| Stage split on Thor (TRT bf16) | 8.21 ms data / 28.89 ms backbone / 56.64 ms action head | NVIDIA model card | measured by source |
| Optimized mixed NVFP4, 2 cameras | 35.6 ms / 28.1 Hz | Isaac-GR00T deployment README | measured by source |
| LIBERO, 1 camera, optimized | 39.9 ms / 25.1 Hz | Jetson AI Lab tutorial | measured by source |
| Per denoise step, Thor | 14.16 ms baseline / 4.30 ms optimized | derived from 56.64/4 and 17.18/4 | derived |
| Weight footprint, 3.14 B | 6.29 GB BF16 / 3.14 GB FP8 / 1.57 GB NVFP4 | derived | derived |
| Weight-streaming floor at 273 GB/s | 23.0 / 11.5 / 5.8 ms | derived | derived |
| 1080p60 RGB camera | 373 MB/s | derived | derived |
| 4K30 RGB camera | 746 MB/s | derived | derived |
| CSI aggregate / PCIe Gen5 ×8 | 40 Gbps / 31.5 GB/s | Thor datasheet | vendor claim |

**Do not mix the Thor numbers.** They use different checkpoints, camera counts,
and harnesses:

| Source | Config | Eager | TRT bf16 | TRT NVFP4 |
|---|---|---:|---:|---:|
| HF model card | N1.7 base, 1 camera, 4 steps | 144.9 ms | 93.8 ms | — |
| Deployment README | N1.7-LIBERO, 2 cameras, horizon 40 | 106.8 ms | 76.8 ms | 35.6 ms |
| Jetson AI Lab | N1.7-LIBERO, 1 camera | ~126 ms | ~81 ms | ~40 ms |
| ZETIC | N1.7-LIBERO, BF16 | 108.52 ms p50 | — | — |

Use one row per claim and keep the config column attached.

**The correction that matters:** raw camera ingest is small compared with
273 GB/s. Four 1080p60 cameras are ~1.5 GB/s; four 4K30 cameras are ~3 GB/s.
The dominant fabric traffic is **model weight streaming**, and the action head
replays **4× per chunk**. That is why FP8/NVFP4 and weight reuse move the needle
far more than camera bandwidth.

One nuance: on Thor the action head is still **compute-bound** — 56.64 ms
measured versus ~23.2 ms for four 1.57 GB NVFP4 passes at 273 GB/s. Weight
streaming is the largest *traffic* class, not automatically the latency
bottleneck. The fabric question is whether the stream can be sustained while
the DiT computes.

## Real artifacts we found

| Artifact | What it gives us | Access | Confidence |
|---|---|---|---|
| `NVIDIA/Isaac-GR00T` → `n1d6:scripts/deployment/GR00T_inference_timing.ipynb` | Measured **N1.6** H100 stage split: data 4.72 ms, backbone 37.96 ms, action head 94.28 ms, E2E 148.62 ms; eager/compile/TRT; denoising sweep 1/2/4/8/16 steps. The HEAD copy is labelled N1.7 but carries these same N1.6 outputs. | Apache-2.0, saved notebook outputs | **measured N1.6** |
| `NVIDIA/Isaac-GR00T` → `scripts/deployment/README.md` | Measured Thor totals: 76.8 ms TensorRT, 35.6 ms NVFP4; 2 cameras, horizon 40, 60 calls | Apache-2.0 | **measured** |
| `NVlabs/vla-perf` → `vla-perf/perf_results/*.csv` | 25 CSVs: per-stage ms, operational intensity, compute/memory boundness, image/KV bytes, network transfer times, Thor roofline. Vendored subset pinned at `1e2b9a7`; π0 Thor template built. | MIT, pure Python | **modeled**, validated 56.8–82.6% vs real GPUs |
| `huggingface/lerobot` → `inference/policy_runner.py` | Three-stage `preprocessing/policy/postprocessing` durations + observation capture timestamps; no shipped traces. Recorder + a **real ACT CPU run**: 30.94 ms total, policy 99% (`data/lerobot/act_pusht_trace.jsonl`). | Apache-2.0, runnable on CPU for ACT | **real small-policy run** |
| `NVIDIA-ISAAC-ROS/isaac_ros_benchmark` → `results/*.json` | Measured frame rate, jitter, missed frames, CPU/GPU utilization at fixed 30 fps | Apache-2.0 | **measured**, not a VLA |
| ZETIC / Ixian GR00T record | Thor N1.7-LIBERO: p50 108.52 ms, 65.5 W board, 7.11 J/call, 15.57 GB peak | public web, no explicit license | **third-party measured** |
| `qdox-labs/thor-hacks` | 262.8 GB/s measured peak read (96% of 273); device props log | MIT | **third-party measured** |
| `nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim` | 1,000 episodes / 213,493 frames per embodiment, 20 fps, 3 views, per-frame timestamps | CC BY 4.0 | **dataset** |
| `Isaac-GR00T/demo_data/libero_demo/meta/info.json` | 20 fps, 256×256×3, 2 cameras, 1,406 frames, timestamp field | Apache-2.0 | **dataset metadata** |

**No open project ships raw per-request VLA inference traces.** Specifically, no
`.nsys-rep`, `.ncu-rep`, Perfetto trace, or `tegrastats` log for GR00T on Thor
is public, and the Isaac-GR00T repo has no checked-in benchmark CSV/JSON. The
closest artifacts are the measured aggregate notebook and VLA-Perf’s modeled
CSVs. That is the honest boundary.

### Measured template

`tracks/t3-topology/examples/gr00t_n16_h100_measured-v4.json`

- Uses the **measured N1.6 H100** stage durations: 4.72 + 37.96 + 94.28 ms.
- Four action-head stages of 23.57 ms each (the measured 94.28 ms split evenly).
- One 256×256 camera, 64 image tokens.
- The 8-rank fabric and traffic profiles are authored; only the compute
  durations are measured.
- N1.6, H100 — not N1.7 and not Thor. The HEAD notebook’s N1.7 label is a
  relabel of the same stored N1.6 outputs; do not propagate it.

The authored Thor pipeline template remains
`tracks/t3-topology/examples/gr00t_vla_robotics-v4.json`; it models the
control/QoS story and is explicitly not a measured GR00T trace.

### Modeled π0/Thor template

`tracks/t3-topology/examples/pi0_thor_modeled-v4.json`

- VLA-Perf `pi0_family_e2e_perf.csv`, pinned commit
  `1e2b9a7ef9d4188c7e1e2befbdc758222c60d760`, row
  `model.name=pi0`, `hardware.name=Jetson_AGX_Thor`, `num_chips=1`, `batch_size=1`.
- Modeled stages: vision **6.062 ms**, VLM **20.303 ms**, action **26.200 ms**
  (10 flow steps), E2E **52.565 ms**.
- All three stages are **Mem-bound** in VLA-Perf’s roofline.
- **Modeled, not measured.** The fabric/rank/traffic shape is authored.
- Vendored CSVs and provenance: `tracks/t3-topology/data/vla-perf/`.

## Open-source proxies (95% close)

If a measured GR00T trace is unavailable, these are the closest usable
open-source workloads:

| Project | What it gives us | Run cost |
|---|---|---|
| **VLA-Perf** (`NVlabs/vla-perf`) | Per-stage ms, operational intensity, boundness, image/KV bytes, network transfer times; 25 CSVs. Ingested: `pi0_thor_modeled-v4.json`. | CPU, minutes |
| **LeRobot** (`huggingface/lerobot`) | Three-stage `preprocessing/policy/postprocessing` timings + observation capture timestamps; Zenoh transport. Recorder: `tracks/t3-topology/tools/lerobot_trace_dump.py`. Real ACT CPU trace: 30.94 ms, policy 99%. Real SmolVLA CPU run: 2,628 ms/chunk, policy 99.98%, 450 M params, 3 cameras, chunk 50, 10 denoise steps. | CPU for ACT/SmolVLA; GPU for π0 |
| **openpi** (`Physical-Intelligence/openpi`) | `infer_ms` and `prev_total_ms` per request; π0 config (action horizon 50, 10 flow steps) | >8 GB GPU |
| **Octo-Small** (`octo-models/octo`) | 27 M params, 256×256, chunk 4; CPU-runnable JAX | CPU, ~1 GB |
| **OpenVLA-OFT** (`moojink/openvla-oft`) | 7 B, chunk 8/25, per-episode model time | 16–18 GB GPU |

LeRobot is the best runnable chain for real arrival timestamps; VLA-Perf is the
best ready-made dataset for bytes/intensity. Neither is a GR00T trace.

SmolVLA is the closest CPU-runnable VLA we actually ran (450 M, VLM backbone +
action expert, 3 cameras, chunk 50, 10 denoise steps). But it is **2.6 s per
chunk** and still exposes only three Python stages — not vision / VLM prefill /
action head. Use it as evidence that the recorder works on a VLA-shaped policy,
not as a GR00T timing proxy.

## What the software models

For a given topology and workload shape, it produces cycle-level traffic,
queueing, arbitration, channel utilization, latency percentiles, and network
power/area estimates. It does **not** model robot dynamics, functional safety,
GR00T accuracy, or NVIDIA's internal SCF/MCF/MSS fabric.

Two demo templates:

- **Measured N1.6 H100 stage split:** `gr00t_n16_h100_measured-v4.json` (above).
- **Authored Thor control pipeline:** `gr00t_vla_robotics-v4.json` (below).

| Rank | Role | Traffic |
|---|---|---|
| 0 | camera/ISP | 4 × 1080p frames → vision (`camera_ingest`, 16.6 MB/tick) |
| 1 | vision encoder | 64 image tokens → four VLM slices (`vision_tokens`, 262 KB each) |
| 2–5 | VLM/LLM slices | action latents → action head (`action_tokens`, 82 KB each) |
| 6 | action head | 32-dim action → control (`control_out`, 128 B) |
| 7 | control MCU | 1 kHz control loop (`control_out`, deadline 1 ms) |

Declared requirements:

- `control_out`: latency-critical, ≤ 1,000,000 cycles (1 ms at 1 GHz).
- `camera_ingest`: bandwidth ≥ 0.5 GB/s, ≤ 5 ms.

The template uses an 8-rank, 9-agent fabric (`compute_tile × 8` +
`hbm_controller × 1`) on a 3×3 mesh, 256-bit links, 1 GHz, 4 nm. It compiles to
PASS.

## Demo script (5 minutes)

1. **Create the project** — Flow → Workload templates → “GR00T N1.7 VLA ·
   robotics pipeline” → Use this workload.
2. **Compile** — PASS certificate.
3. **Baseline** — evaluate the 3×3 mesh. Show `control_out` p99,
   `camera_ingest` delivered bandwidth, and the hottest channels.
4. **Change the fabric** — ring, crossbar, 4×4 mesh; or keep the mesh and raise
   buffer depth / link width.
5. **Show the trade-off** — control-loop p99 versus perception throughput and
   network power/area. The “best” fabric depends on which deadline the robot
   cannot miss.
6. **Weight-streaming follow-up** — run the HBM→compute weight-stream class
   (next slice) and show sustained bandwidth versus the 273 GB/s ceiling.

What to point at on screen:

- the rank/role map (camera → vision → VLM → action → control),
- per-class requirements,
- channel utilization and queue/arbitration split,
- the selected run’s evidence bundle.

## Why this matters to NVIDIA

- Jetson Thor is a fixed product; the next robotics SoC is not. The same
  questions apply to a custom robotics chip, an automotive SoC, or a robot’s
  compute island.
- The VLA pipeline is a concrete, public, NVIDIA-owned workload with three
  traffic regimes that stress a fabric differently.
- The demo shows a design-space loop: workload → fabric → measured trade-off →
  evidence. That is the pitch, not one latency number.
- The software already has the pieces architecture teams care about: explicit
  topology objects, cycle-level simulation, QoS classes, multicast/shared-wire
  modeling, and run evidence.

## Honest limitations

- The Thor template combines **measured N1.7 TRT stage durations** (8.21 /
  28.89 / 56.64 ms) with an authored fabric, traffic, and 1 kHz control shape.
  Frame sizes, traffic volumes, and deadlines are illustrative; it is not a
  measured GR00T trace.
- The measured template uses NVIDIA’s **N1.6 H100** notebook numbers, not N1.7
  and not Thor.
- No public project ships raw per-request VLA inference traces. GR00T’s
  notebook and deployment README are measured aggregates; VLA-Perf’s CSVs are
  modeled.
- NVIDIA’s on-chip SCF/MCF/MSS topology, link widths, clocks, and per-agent
  bandwidth are not public. We model a hypothetical fabric, not Thor’s
  internals.
- No per-kernel/DRAM/NoC counters, sensor-fabric captures, closed-loop
  sensor-to-actuator latency, or stage power are public.
- The software does not model GPU SIMT execution, ISP pipelines, sensor
  physics, robot dynamics, functional safety (lockstep/ECC), or ISO 26262.
- Power/area are research estimates, not silicon signoff.

## What would make it investor-grade

1. **Measured trace** — run GR00T N1.7 on Jetson Thor with Nsight Systems NVTX
   ranges (`ingest`, `preprocess`, `vit`, `llm_prefill`, `dit_0..3`,
   `action_decode`, `actuate`) and replace the authored payloads. The GR00T
   harness already prints stage medians and writes a preprocessing-reference
   JSON; `nsys`, `trtexec --dumpProfile`, and `tegrastats` supply the missing
   bytes, per-engine time, and power.
2. **Weight-streaming workload** — HBM→compute class with 1.57 GB NVFP4 /
   3.14 GB FP8 payloads; sweep topology, buffers, and multicast/reuse.
3. **QoS experiment** — explicit VC/arbitration policy for control vs
   perception; before/after tail latency.
4. **Multicast experiment** — camera frames and weight broadcast; quantify
   shared-wire savings.
5. **Safety scope** — state functional safety is out of scope, or add a
   separate redundancy/ECC track.

## Sources

- GR00T N1 paper: https://arxiv.org/abs/2503.14734
- GR00T N1.7 model card: https://huggingface.co/nvidia/GR00T-N1.7-3B
- Isaac-GR00T deployment README: https://github.com/NVIDIA/Isaac-GR00T/blob/main/scripts/deployment/README.md
- Jetson AI Lab N1.7 tutorial: https://www.jetson-ai-lab.com/tutorials/groot_n17_on_thor/
- Jetson Thor module datasheet: https://developer.nvidia.com/downloads/assets/embedded/secure/jetson/thor/docs/jetson-thor-series-modules-datasheet_ds-11945-001.pdf
- VLA-Perf (π0 roofline): https://arxiv.org/html/2602.18397v1

## Related

- Deployment builder: `docs/design/reviews/deployment-builder.md`
- Deployment mapping: `docs/design/reviews/deployment-intent-mapping.md`
- Workload registry: `tracks/t3-topology/workloads/registry.json`
