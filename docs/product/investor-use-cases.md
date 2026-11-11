# Investor use cases: NVIDIA Robotics and Microchip

Two concrete fabric problems, one design-space tool. Both briefs separate
source-backed facts from authored demo shapes.

## One-line pitches

- **NVIDIA Robotics** — “Your camera fabric is fine; the hard problem is feeding
  a 4×-replayed diffusion action head from LPDDR5X while protecting a 1 kHz
  control loop.”
- **Microchip** — “A 160-lane Gen 6 switch with 16 partitions and hardware
  multicast is a fabric problem: buffer, arbitrate, isolate, and hold p99 under
  incast.”

## NVIDIA Robotics

**Workload:** GR00T N1.7-3B VLA pipeline — cameras → ISP → vision encoder →
VLM backbone → action head → motor control.

**Public anchors:**

- 3.14 B parameters; 32-layer diffusion action head; 4 denoise steps; action
  horizon 40; 64 image tokens per camera.
- Jetson AGX Thor T5000: 128 GB LPDDR5X, 273 GB/s, 40–130 W.
- Published Thor E2E: 93.8 ms / 10.7 Hz base; 35.6 ms / 28.1 Hz optimized
  NVFP4; stage split 8.21 / 28.89 / 56.64 ms.
- Weight footprint: 6.29 GB BF16 / 3.14 GB FP8 / 1.57 GB NVFP4; streaming floor
  23.0 / 11.5 / 5.8 ms at 273 GB/s.

**Fabric question:** can the fabric sustain HBM→compute weight streaming for
four denoise replays while a 1 kHz control stream meets a 1 ms deadline?

**What we show:** control-loop p99 under perception load; topology/buffer
trade-offs; weight-streaming bandwidth vs the 273 GB/s ceiling; multicast and
QoS isolation.

**Runnable template:** `tracks/t3-topology/examples/gr00t_vla_robotics-v4.json`
(Flow → Workload templates → “GR00T N1.7 VLA · robotics pipeline”).

**Brief:** `docs/product/nvidia-robotics-use-case.md`

## Microchip

**Product fit:** Switchtec Gen 6, not PolarFire. PolarFire’s FPGA routing is not
a packet NoC; there is no public Microchip UCIe/die-to-die product.

**Public anchors:**

- 160 lanes, 20 ports, 16 virtual switch partitions, 16 NTBs, 64 GT/s,
  hardware multicast, 3 nm.
- ≈1.28 TB/s per direction raw; ≈1.21 TB/s after 256B FLIT / 242B payload
  efficiency.
- August 2026 Micron demo: Gen 6 fan-out switch to multiple Gen 6 SSDs.

**Fabric question:** at 160 lanes and 16 partitions, which topology (single
crossbar vs two-stage Clos), buffer depth, VC count, and multicast replication
point holds p99 under incast without leaking latency across partitions?

**What we show:** latency CDF/p99 vs load; buffer sensitivity; multicast fan-out
cost; partition-isolation experiment; normalised area/power Pareto.

**Positioning:** a “Gen 6-class 160-lane switch fabric,” never “the Switchtec
fabric.” Sell design-space exploration for the generation after Gen 6.

**Brief:** `docs/product/microchip-use-case.md`

## What both need before an investor demo

1. **One measured calibration point** on real silicon.
2. **A stated reference fabric** with assumptions labelled.
3. **A workload justification** (published trace or synthetic mix).
4. **A defensible PPA axis** (relative/normalised, not absolute).
5. **A boundary slide**: “We model the fabric; we do not model the protocol,
   robot dynamics, or functional safety.”

## Existing tooling

- Deployment builder: `/builder` in Studio (model/hardware/policy → intent).
- Deployment mapping: `docs/design/reviews/deployment-intent-mapping.md`.
- GR00T Thor template (measured N1.7 TRT stages, authored fabric/control):
  `tracks/t3-topology/examples/gr00t_vla_robotics-v4.json`.
- GR00T N1.6 H100 measured stage template:
  `tracks/t3-topology/examples/gr00t_n16_h100_measured-v4.json`.
- π0 Thor modeled roofline template:
  `tracks/t3-topology/examples/pi0_thor_modeled-v4.json`.
- VLA-Perf vendored data (pinned): `tracks/t3-topology/data/vla-perf/`.
- LeRobot trace recorder: `tracks/t3-topology/tools/lerobot_trace_dump.py`.
- Real ACT CPU trace: `tracks/t3-topology/data/lerobot/act_pusht_trace.jsonl`
  (30.94 ms, policy stage 99%; a small-policy smoke test, not a VLA).
- Real SmolVLA CPU trace: `tracks/t3-topology/data/lerobot/smolvla_trace.jsonl`
  (2.63 s/chunk, 450 M, 3 cameras, chunk 50, 10 denoise steps; VLA-shaped but
  only three Python stages, not vision/VLM/action).
- Workload registry: `tracks/t3-topology/workloads/registry.json`.
