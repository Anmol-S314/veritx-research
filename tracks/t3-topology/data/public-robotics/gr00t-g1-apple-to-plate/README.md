# GR00T G1 apple-to-plate infrastructure

The checked-in JSONL is a derived source ledger for pinned NVIDIA PhysicalAI Robotics GR00T X Embodiment Sim revision `ea7ac0b68f87da62f1e726771bba0fe74300802f`, subset `unitree_g1.LMPnPAppleToPlateDC`, episode 0 (CC BY 4.0, attribution NVIDIA). It summarizes 683 timestamps, H.264 demux packet lengths, and state/action vector shapes; it does not redistribute source values or describe internal model execution.

From repository root:

```sh
python tracks/t3-topology/tools/gr00t_pipeline.py verify --ledger tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl
python tracks/t3-topology/tools/gr00t_pipeline.py fetch --cache-dir ~/.cache/huggingface --output-dir /tmp/gr00t-episode
python tracks/t3-topology/tools/gr00t_pipeline.py project --ledger tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/episode_000000.events.jsonl --trace /tmp/gr00t.trace --manifest /tmp/gr00t-manifest.json
```

Fetch transfers only the pinned episode Parquet and MP4 and checks audited SHA-256s. Project maps authored endpoints (camera 0→1; state 1→2; demonstrated action 1→2), uses a declared 256-byte flit assumption and one observation at cycle 0. It intentionally does not replay the native 13.64-second, 50-fps timeline (which would create billions of idle 1-GHz cycles). Action is a recorded demonstration, not predicted inference. Generated trace is a sensor/trajectory projection only, not a real GR00T network capture or BookSim execution result. Timeloop doctor reports prerequisites only and fails when no built mapper exists; a tiny GEMM smoke would be infrastructure validation, not a GR00T operation trace. No model extraction, hardware profiling, or calibration is included.

Optional isolated fetch dependency: `python -m pip install -r tracks/t3-topology/data/public-robotics/gr00t-g1-apple-to-plate/requirements-source.txt`.
