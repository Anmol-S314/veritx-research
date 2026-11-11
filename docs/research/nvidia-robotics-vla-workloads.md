# NVIDIA robotics / VLA workloads for the Srota demonstration

## Recommendation

Lead with **GR00T on Jetson Thor**, not datacenter LLM serving. The relevant question is how perception, policy inference, and time-sensitive control coexist, and where a proposed communication design adds delay. NVIDIA-reported compute/software timings can anchor a workload without raw packet traces. They do not calibrate a new fabric.

## 1. GR00T N1.7 stage workload on Thor — immediate model input

[NVIDIA's N1.7 model card](https://huggingface.co/nvidia/GR00T-N1.7-3B) reports one camera, four denoising steps, and the following Thor TensorRT full-pipeline timings:

| Component | NVIDIA-reported time |
|---|---:|
| Data processing | 8.21 ms |
| Backbone | 28.89 ms |
| Action head | 56.64 ms |
| End-to-end | 93.8 ms / 10.7 Hz |

Use these as **source-reported stage durations**, not our measurements. Rounded stage totals need not exactly equal the rounded end-to-end value. The action-head total covers four iterations; assigning 14.16 ms to each is a modeling assumption, not a measured per-iteration distribution.

Existing project input: `tracks/t3-topology/examples/gr00t_vla_robotics-v4.json`. Its compute times match this model-card row. Its eight-rank topology, data transfers, endpoint assignments, control stage, and 1 kHz control deadline are authored. In particular, the schema's `tp=8` is not evidence that NVIDIA's policy used eight GPUs or that eight devices are required for deployment.

**Demo:** source-reported VLA compute stages plus a clearly labeled authored interconnect scenario. Vary camera traffic, shared traffic, mapping, and QoS; report simulated communication effects, not a measured GR00T speedup or a model of Thor's internal fabric.

**Label:** “GR00T N1.7 / Thor workload using NVIDIA-reported compute timings; communication and endpoint mapping are modeled.”

### Keep NVIDIA sources separate

The [hardware recommendation guide](https://github.com/NVIDIA/Isaac-GR00T/blob/main/getting_started/hardware_recommendation.md) currently reports Thor TensorRT at **12.4 Hz**, whereas the model card reports **10.7 Hz**. The sources do not establish why these rows differ. Do not combine them or silently replace the existing template's model-card timings. Pin the exact model, source revision, settings, and harness before comparison. The [deployment guide](https://github.com/NVIDIA/Isaac-GR00T/blob/main/scripts/deployment/README.md) also uses fine-tuned LIBERO checkpoints and other configurations; those are separate workload variants.

## 2. GR00T N1.7 + whole-body control on Thor — strongest system-level reference

[NVIDIA's Isaac OS benchmark](https://docs.nvidia.com/isaac-os/reference/applications/gr00t-n1-7-wbc-g1/benchmark) documents concurrent GR00T and WBC execution on AGX Thor:

- Mock camera images: **30 Hz**.
- GR00T inference/replanning: **5 Hz**.
- Mock joint state and command/control path: **50 Hz**.
- GR00T latency budget: **200 ms**; WBC latency budget: **20 ms**.
- One one-hour trial per condition, Green Context off first and on second; no repeated trials.
- Green Context on reserves **2 of 20 SMs** for WBC.

| NVIDIA-reported metric | Shared GPU / isolation off | Green Context on |
|---|---:|---:|
| WBC p99.9 software latency | 2.5747 ms | 0.3747 ms |
| GR00T image-to-command p50 | 126.9310 ms | 120.2659 ms |
| GR00T image-to-command p99.9 | 126.9618 ms | 140.2846 ms |

This is measured **software callback-to-callback timing with mock I/O**. Physical camera latency, robot communication, actuator response, and real-world task success are excluded. The benchmark's 50 Hz control rate is not the existing Srota template's authored 1 kHz deadline. Its 5 Hz replanning rate is not the model-card maximum inference frequency. Green Context is GPU execution isolation, not a measured change in NoC or switch topology.

**Demo:** a separate co-running perception/policy/control scenario using the published source rates and budgets. Ask whether an authored shared communication design preserves control latency under VLA load. Do not claim NVIDIA's isolation result proves Srota's fabric benefit.

**Label:** “NVIDIA-reported concurrent GR00T/WBC software benchmark with mock I/O; proposed fabric effects modeled separately.”

This reference has profiling and Nsight export instructions. It is a useful target for an approved Thor reproduction; it does not itself provide us a raw captured trace.

## Concrete task and tensor shapes found in the application configuration

A closer inspection identifies a more concrete candidate: **Unitree G1 apple-to-plate manipulation with GR00T N1.7 plus WBC**. This is not just a generic VLA block diagram. NVIDIA publishes model bindings, state/action groups, and the application wiring.

Versioned configuration sources:

- [Isaac OS v0.11.0 application configuration](https://github.com/nvidia-isaac/isaac-os/blob/v0.11.0/applications/gr00t_n1_7_wbc_g1/config/control.yaml)
- [Mock/hardware G1 model bindings](https://github.com/nvidia-isaac/isaac-os/blob/v0.11.0/operators/gr00t_n1_7/config/n1_7_g1.yaml)
- [Separate apple-simulation model bindings](https://github.com/nvidia-isaac/isaac-os/blob/v0.11.0/operators/gr00t_n1_7/config/n1_7_g1_apple_sim_trt.yaml)
- [Application behavior and simulation timing](https://docs.nvidia.com/isaac-os/reference/applications/gr00t-n1-7-wbc-g1)

The mock/hardware binding file declares five models executed in order on **one CUDA stream**: video preprocessing, state preprocessing, backbone, action head, action decoding. The action-head export performs the complete denoising loop internally. These bindings are not an observed multi-chip or tensor-parallel deployment.

The following sizes are **derived dense tensor payloads**, using the configuration's declared shapes and float32 element width. They are not captured allocations, transferred wire bytes, or measured bandwidth. Check runtime bindings before using them as execution evidence.

| Declared tensor | Shape | Derived bytes |
|---|---|---:|
| Ego-view model input | `[1,480,640,3]` float32 | 3,686,400 |
| Backbone features | `[1,77,2048]` float | 630,784 |
| Initial noise / predicted latent actions, each | `[1,40,132]` float | 21,120 |
| Decoded arm/hand/waist position chunk | 16 × (7+7+7+7+3) float values | 1,984 |

The combiner uses **15 leg/waist joints from WBC** and **28 arm/hand joints from GR00T**; the decode output includes a waist group that is not the combiner's GR00T-controlled waist. Effort outputs and metadata are additional data, not included in the position-only size above. The full robot state has 43 joint dimensions.

A derived example: materializing the declared float32 input at 30 Hz would represent 110.592 MB/s of tensor payload; selecting it at 5 Hz corresponds to 18.432 MB/s for selected inputs. Neither value proves those bytes traverse a physical interconnect: source image format, copies, preprocessing, zero-copy sharing, and actual placement determine traffic. Do not equate the float32 binding with physical RGB camera-wire format.

**Important variant boundary:** mock/hardware uses a 16-step output chunk and a 0.2 s inference-selection interval. The separate Isaac Sim apple model uses a 40-step output chunk and a 0.7 s inference interval, with 0.02 s action spacing. The mock benchmark's timing statistics must not be attached to the simulation model. Neither variant is the existing template's generic 256×256 / eight-rank / 1 kHz scenario.

This is the preferred next workload to construct: preserve the source graph/rates and declared payload provenance, explicitly select any proposed endpoint placement, and simulate only the communication effects supported by that model. Runtime memory/weight traffic and per-stage compute in this exact G1 configuration still require profiling; the model-card base-checkpoint timings are not a substitute.

## 3. NVlabs VLA-Perf — robotics split-inference exploration

[NVlabs/vla-perf](https://github.com/NVlabs/vla-perf) studies π0 and OpenVLA, including on-device versus server execution, image/KV-cache transport, denoising steps, and action chunk size. This is **analytical performance modeling**, not a GR00T benchmark or a physical link capture. π0 and OpenVLA are not NVIDIA GR00T models merely because NVlabs models them.

Already present:

- `tracks/t3-topology/data/vla-perf/README.md` — pinned sources and explicit modeled status.
- `tracks/t3-topology/examples/pi0_thor_modeled-v4.json` — modeled π0/Thor stages.

The pinned π0/Thor row estimates vision **6.062 ms**, VLM **20.303 ms**, action **26.200 ms**, E2E **52.565 ms**. These are not Thor hardware measurements. Use this as a secondary robotics exploration, especially for endpoint/network partitioning, not the headline NVIDIA GR00T evidence.

## Open NVIDIA robotics dataset: G1 apple-to-plate

The strongest open dataset match is NVIDIA's [PhysicalAI Robotics GR00T X Embodiment Sim dataset](https://huggingface.co/datasets/nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim), licensed **CC BY 4.0**. The dataset card lists the Unitree G1 `unitree_g1.LMPnPAppleToPlateDC` loco-manipulation subset, closely related to the Isaac OS apple-to-plate example but not the same benchmark run or scene.

At audited Hugging Face revision `ea7ac0b68f87da62f1e726771bba0fe74300802f`, the subset metadata declares H.264 ego-view video at **640×480, 50 fps**, **43-dimensional float64** state and action vectors, a float32 timestamp per frame, and 2 task IDs. The task text includes “pick up the apple, walk left, and place the apple on the plate.” The dataset tree contains 103 Parquet episodes and 103 matching MP4s (375,257,241 bytes combined); this conflicts with the card's 102 trajectories and metadata's `train: 0:100` split. Use the pinned file listing rather than repeating an unqualified episode count.

I downloaded and checked episode 0 (Parquet SHA-256 `dbbcb8ac2831fb62f16425b3c7dfe7b57169a6a24960a8a743bbef903bd6fd32`; MP4 SHA-256 `e3287f43ec3a8ea8b1f75453c2c559c75909cdd9128b0a147bb7fc936fc84e4d`):

- 683 Parquet rows and 683 decoded H.264 frames, 640×480 at 50 fps, duration 13.66 s.
- Timestamp starts at 0 and ends at 13.64 s; all 682 intervals are strictly increasing and within 20.000±0.001 ms.
- State and action arrays are each 683×43, finite, with nonconstant values.
- The row's task ID maps to the apple-pick/walk/place instruction.

The sample is structurally coherent and suitable as an **open simulated trajectory workload source**. It is not a GR00T inference profile, GPU latency trace, robot-hardware log, or network packet trace.

Download just this subset (not the full multi-embodiment collection):

```bash
huggingface-cli download nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim \
  --repo-type dataset \
  --revision ea7ac0b68f87da62f1e726771bba0fe74300802f \
  --include "unitree_g1.LMPnPAppleToPlateDC/**" \
  --local-dir "$HOME/gr00t_g1_apple_to_plate"
```

Its 50 fps trajectory stream differs from the separate Isaac OS mock benchmark's 30 Hz image source, 5 Hz inference, and 50 Hz WBC. Keep those workloads distinct.

Other open choices if broader robots/tasks matter:

- [DROID](https://droid-dataset.github.io/droid/the-droid-dataset): 76K real-world demonstrations, 3 camera views and action/state fields; official docs offer a 100-episode RLDS debugging subset (~2 GB). Full RLDS is ~1.7 TB, so use the sample. Its RLDS schema is step-based; do not infer sensor wall-clock timing from index alone.
- [BridgeData V2](https://rail-berkeley.github.io/bridgedata/): 60,096 WidowX arm trajectories, 5 Hz control, image/state/action and language labels, CC BY 4.0. It is a different robot and task family, not GR00T G1 evidence.

## Supporting local evidence

`tracks/t3-topology/data/lerobot/SMOLVLA_VLA.md` documents real CPU VLA calls with a vision stage, VLM prefill, and ten measured action-denoising steps. It validates our ability to instrument a VLA-shaped policy, not GR00T/Thor performance. Inputs are synthetic observations; there is no robot task-success or link-traffic measurement.

## Stop condition and next execution step

The public workload evidence is sufficient to propose a robotics-focused demo **without waiting for packet captures**. It is not sufficient to claim a fabric improves a real robot.

1. Use the existing model-card-anchored GR00T template as the immediate demo, with modeled traffic prominently labeled.
2. Build a distinct GR00T/WBC scenario from 30/5/50 Hz rates and 200/20 ms budgets; do not relabel the authored 1 kHz template as NVIDIA's measured setup.
3. For target validation, request approved Thor access and reproduce one pinned workload with GPU/software profiling plus the relevant target-fabric counters. No paid compute is authorized by this note.
