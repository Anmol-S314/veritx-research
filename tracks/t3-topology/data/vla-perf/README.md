# VLA-Perf modeled roofline data (vendored subset)

**The π0 stage numbers used here are MODELED roofline estimates produced by
VLA-Perf's analytical performance model. They are not hardware measurements,
not traces, and not benchmarks.** Do not describe them as measured. The
validation table also carries a `real_ms` comparison column from prior
real-time-VLA work; it is not used as a compute source for the template.

| Field | Value |
| --- | --- |
| Upstream repository | VLA-Perf — https://github.com/NVlabs/vla-perf |
| Default branch | `main` |
| Pinned commit | `1e2b9a7ef9d4188c7e1e2befbdc758222c60d760` |
| Commit date | 2026-02-26T16:52:55Z |
| Retrieved | 2026-11-05 |
| Upstream directory | `vla-perf/perf_results/` |
| License (vendored subtree) | MIT — `vla-perf/LICENSE`, Copyright (c) 2026 Wenqi Jiang, VLA-Perf |
| License (repository root) | Apache-2.0 — root `LICENSE`, which states that the project overall is Apache-2.0 and that a portion is MIT |

The files below were downloaded byte-for-byte from the pinned commit. They are
kept as-is: no numbers, headers, or rows were edited. Checksums let a reviewer
confirm that.

## Files

| File | Data rows | SHA-256 | What it contains |
| --- | ---: | --- | --- |
| `pi0_family_e2e_perf.csv` | 55 | `68e70df3ca4c7f1b8a5cb62acaa6e4d9f1b85a48c2ab1cd47b823561e2286206` | End-to-end π0 stage breakdown from VLA-Perf's GenZ roofline model. One row per hardware × chip count × batch size. Columns: model/stage/seq-len/hardware/chips/batch, `vision_time_ms`, `vlm_time_ms`, `action_time_ms`, `e2e_time_ms`, per-stage boundness, per-stage operational intensity. Hardware: A100 80GB, B100, H100, RTX 4090, Jetson AGX Thor. |
| `pi0_denoising_steps_action_lengths.csv` | 75 | `6addcecbbd4b88303fdede36ded833b4d0aaa8472c7b12c10ceb4ec2d6cdfb63` | Sweep of π0 diffusion/flow-matching denoising steps (1, 5, 10, 20, 50) against action chunk size (5, 25, 50, 100, 250) on B100, Jetson AGX Thor, and RTX 4090 at bf16. Includes stage times, E2E, implied frequency, and boundness/intensity. The Thor row at 10 steps × chunk 50 repeats the same 26.20 ms action stage as the e2e row used by the modeled template; it is the evidence for splitting that stage into 10 steps with horizon 50. |
| `network_latency_images.csv` | 88 | `96ac194c1627de6541f342ad01d0e4379ecb4d18b2c5c25b0978b3588cafbf74` | Analytical image upload latency for 11 network profiles (4G LTE, 5G NR SA, WiFi 5/6/6E/7, DC 1/10/25/100/400GbE) at 224/384/512/1024 px, raw and 0.1× compressed. A 224×224 uint8 RGB image is 150,528 B; its compressed variant is 15,052 B. |
| `network_latency_bidirectional_kvcache.csv` | 66 | `8c90e5c478235943b980d2b524b7250d1ed66f7c8a577e56b6807be2cca40a8f` | Analytical robot→server image upload plus server→robot KV-cache download round trip for Pi0 (Gemma 2B), Pi0.6 (Gemma 3 4B), and OpenVLA-7B, all at sequence length 256 and fp16. Eleven networks × three models × two image configs (224 and 512 px, both 0.1× compressed). Includes upload/download/round-trip latency and max sync/async control frequency. |
| `perf_validation_vs_realtime_vla.csv` | 6 | `f807142651a81bea49b7fbb06fcf0fd3d6a9549b4fe9252b3dc02c6a6128f2d9` | VLA-Perf's own check of modeled roofline latency against real-time-VLA measurements on RTX 4090 and RTX 5090 (1–3 views, bf16). This table does not contain Jetson AGX Thor rows. |

`LICENSE-vla-perf` is the upstream `vla-perf/LICENSE` (MIT). `LICENSE-upstream-root`
is the upstream repository-root `LICENSE` (Apache-2.0), included because the root
license explains the split between the MIT-licensed `vla-perf/` subtree and the
Apache-2.0 project as a whole.

## Provenance of the Thor π0 row

The row used by `tracks/t3-topology/examples/pi0_thor_modeled-v4.json` is:

- file: `pi0_family_e2e_perf.csv`
- `model.name=pi0`, `model.stage=e2e`, `hardware.name=Jetson_AGX_Thor`,
  `hardware.num_chips=1`, `batch_size=1`, `model.seq_len_inference_prefill=256`
- vision 6.062347 ms, VLM 20.303090 ms, action 26.199927 ms,
  E2E 52.565365 ms (the E2E value is the exact sum of the three stages)
- every stage is reported as memory-bound (`Mem`) in that row

The template's 10 action steps split 26.199927 ms evenly and round each step to
an integer nanosecond. See the template `_comment` for the exact rounding and
for which parts of the template are authored.

## Schema notes for parsers

- `pi0_family_e2e_perf.csv` and `pi0_denoising_steps_action_lengths.csv` use
  different hardware/system column names (`hardware.name` vs `system`) and
  different stage column names (`*_time_ms` vs `*_ms`). They cannot share a
  header contract.
- In `network_latency_images.csv`, `image_resolution` alone is ambiguous: each
  resolution appears twice per network (raw and `(comp 0.1x)`), distinguished
  only by `image_config`.
- In `network_latency_bidirectional_kvcache.csv`, sequence length and dtype are
  not their own columns; both are embedded in `return_data_config`, for example
  `Pi0 (Gemma 2B) (seq=256, fp16)`. The file contains only seq=256 and fp16,
  and both of its `image_config` values are `(comp 0.1x)` variants — unlike
  `network_latency_images.csv`, this table has no raw-image rows.
- `perf_validation_vs_realtime_vla.csv` is a validation table for RTX GPUs and
  is not a source for the Thor row. Its `real_ms` column is a published
  real-time-VLA measurement used as a comparison, not a VLA-Perf roofline
  output and not an input to `summarize()`.
- The modeled row is VLA-Perf's own π0 definition (256 vision tokens, prefill
  256; upstream's model table reports 2.686 B parameters). The template's
  3.3 B / horizon 50 / action dim 32 / 224 px labels are the published π0
  deployment config, not inputs to the modeled row. The template `_comment`
  says this too.
