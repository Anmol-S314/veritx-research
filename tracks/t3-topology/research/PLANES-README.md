# Multiplane separation — retained research (veritx-integrate §19)

Sources retained verbatim from `t3-rtl-noc-backup-20260815`:

- `tracks/t3-topology/configs/plane_{shared,data,control,cmesh,cmesh_ctrl}.cfg`
- `tracks/t3-topology/scripts/research/plane_separation.py`
- `tracks/t3-topology/research/monet-vs-plane-separation.md`

Existing gates (plane_separation.py docstring contract): seeded 8×8 XY,
constant-flit-load burst-length sweep, latency QoS contract, VC-count knob,
cmesh express A/B. Preserve on rerun.

Research evidence only. No new Fabric-plane abstraction was forced to
claim integration; the canonical Fabric schema is unchanged.
