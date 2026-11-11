# G1 dataset-to-simulator infrastructure

Source: [NVIDIA PhysicalAI Robotics GR00T X Embodiment Sim](https://huggingface.co/datasets/nvidia/PhysicalAI-Robotics-GR00T-X-Embodiment-Sim), revision `ea7ac0b68f87da62f1e726771bba0fe74300802f`, subset `unitree_g1.LMPnPAppleToPlateDC`, episode 0. **CC BY 4.0, attribution NVIDIA.** Changes: derived frame/payload summaries and authored network projection; no endorsement implied. [License](https://creativecommons.org/licenses/by/4.0/).

This first slice provides pinned sample ingestion, reproducible ledger export, a bounded **sensor/trajectory** BookSim run, and an optional Timeloop GEMM smoke. **It does not yet reconstruct internal GR00T operators, weights or activation traffic.** Those are the next model-extraction stage, not something inferred from this sensor ledger.

## Commands

Run from repository root using your existing source/CLI DSE environment. Export alone additionally needs `ffprobe` on PATH and `python -m pip install -r tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/requirements-source.txt`. No research dependencies are added to desktop packaging.

```bash
TOOL=tracks/t3-topology/tools/gr00t_pipeline.py

# Offline: validates the exact audited 683-frame ledger, including its digest.
python3 "$TOOL" verify

# Explicit download: only one Parquet + one MP4 (~3.1 MB), not the 375 MB subset.
# The output directory must not already exist. Both size and SHA-256 are checked.
python3 "$TOOL" fetch --output-dir /tmp/g1-sample

# Reconstruct from actual source rows, validate/decode video, align presentation
# timestamps (not H.264 decode order), and require byte-identical ledger output.
python3 "$TOOL" export \
  --parquet /tmp/g1-sample/episode_000000.parquet \
  --video /tmp/g1-sample/episode_000000.mp4 \
  --output /tmp/g1-ledger.jsonl

# Trace-only: authored endpoints, default one observation, 32-byte flits,
# max 16 flits/packet. Trace and manifest must be new, distinct files.
python3 "$TOOL" project --trace /tmp/g1.trace --manifest /tmp/g1-projection.json

# Actual diagnostic 2x2 mesh run through the existing BookSim runner/parser.
# Fresh run directory; subprocess timeout; packet AND flit conservation required.
python3 "$TOOL" run-booksim --run-dir /tmp/g1-booksim --timeout 60
```

The BookSim run saves `workload.trace`, `projection.json`, `booksim.cfg`, `stdout.log`, `stderr.log`, `packets.csv`, and `result.json`. The result binds executable/config/trace/manifest SHA-256s. This is a diagnostic legacy mesh run, **not certified fabric equivalence or a model of Thor's internal network**.

## Projection contract

- The audited JSONL has one metadata row and 683 frames. The source `frame_index` is **1-based**; timestamps start at 0 s, at 50 Hz, and span 13.64 s. The MP4 contains 683 frames covering 13.66 s.
- H.264 demux sizes are compressed file bitstream payloads, not decoded camera tensors or physical network packets. The source packet PTS is sorted before matching dataset timestamps; export also counts decoded frames.
- State and action are separate 43×float64 vectors, **344 raw value bytes each**. This excludes transport and container overhead; recorded actions are demonstrations, not predicted GR00T output.
- Explicit hypothetical placement: camera `0→1`, state source `2→1`, recorded action `1→3`. No computation or causal inference between these streams is modeled.
- Payload sizes come from the selected ledger rows. Packetization rounds each transfer up to 32-byte flits and splits into packets of at most 16 flits. Source requests serialize at one flit/cycle; the final flit can contain padding. The manifest records source payload bytes separately from padded bytes.
- The selected first observation is rebased to cycle zero. For multiple frames, native timestamp **differences are preserved** at the declared clock (default 1 GHz); no silent compression. `--frames`, `--clock-hz`, `--max-cycles`, `--flit-bytes`, and `--max-packet-flits` are explicit trace-generation parameters.
- Default `--max-cycles 1000000` refuses multi-frame 50 Hz replay at 1 GHz rather than accidentally simulating billions of idle cycles. Raising that bound is an explicit expensive trace-generation choice; the bounded execution command intentionally stays one observation.
- Raw video/state/action input hashes and the ledger digest are pinned. Edited summaries cannot retain the old claimed source hashes and pass verification.

## Optional Timeloop

Timeloop was already vendored in this repo; it was not added for the desktop. It is optional compute/memory mapping infrastructure, separate from BookSim's network simulation.

The preexisting source needs modern-compiler compatibility fixes. Build in a **new disposable directory**, leaving vendor sources untouched:

```bash
# Existing system prerequisites: SCons, g++, libconfig++, yaml-cpp, ncurses,
# Boost iostreams/serialization development libraries (vendor README lists them).
bash tracks/t3-topology/tools/build_timeloop_sandbox.sh /tmp/g1-timeloop-build

python3 "$TOOL" timeloop-doctor \
  --binary /tmp/g1-timeloop-build/build/timeloop-mapper
python3 "$TOOL" timeloop-smoke \
  --binary /tmp/g1-timeloop-build/build/timeloop-mapper \
  --run-dir /tmp/g1-timeloop-smoke --timeout 60
```

The sandbox builder adds `<cstdint>` and makes two libconfig-to-string conversions explicit to satisfy modern `-Werror`; all changes stay in the copy, with `srota-build-patches.json` recording hashes. Build output goes to `build.log`. The smoke sets the matching library path itself, uses a tiny vendor GEMM (M=N=K=16), saves raw logs/mapping/stats, and requires an actual output stats file. Missing binaries or failed tool runs return nonzero, never replacement numbers. Doctor checks executable presence only; smoke proves execution.

**The GEMM is an infrastructure test, not a GR00T layer or Thor architecture.** The vendor PAT energy model is not calibrated for Thor; do not present its energy/area as hardware measurements. No compute/network totals are added together here.

## Checks

```bash
PYTHONPATH=tracks/t3-topology/dse python3 -m pytest -q \
  tracks/t3-topology/dse/tests/test_gr00t_pipeline.py
```

The full audit and workload variants are documented in `docs/research/nvidia-robotics-vla-workloads.md`. Raw dataset files stay outside Git; the small checked-in ledger is a derived evidence artifact. No catalog or UI workflow has been added by this slice.
