# Srota — side buffer, QoS islands, planes: cross-topology evaluation

Written 2026-09-22 on `feat/srota-sidebuf-qos-planes`, which builds on
`feat/srota-noc`. The model itself is described in
[`SROTA.md`](../../../third_party/booksim2/src/SROTA.md) ("Side buffer, QoS
islands, planes"). This page covers what the model produced against the other
topologies in this directory, and how to reproduce it.

## Arms

All arms are 16 terminals, 5-flit packets, `use_noc_latency=0` on every arm,
and BookSim's default router pipeline unless stated.

| arm | what it is | Plane D storage |
|---|---|---|
| `srota16` | MECS + O1TURN-XY, rank VCs, conventional 4 VC × 8 router (the earlier model) | 3584 flits |
| `srota16_sb` | MECS + O1TURN-XY + Plane-T overlay, side-buffered router (2 VC × 2-flit staging + 8-flit shared side buffer), islands in columns 0 and 3 with the column-first rule | 576 flits |
| `srota16_xy` | spec-literal Plane D: MECS, pure XY, 1 VC, 2-flit staging, 8-flit side buffer | 352 flits |
| mesh4x4, torus4x4, cmesh16, flatfly16, fly4, fattree16, ftree | existing configs, 4 VC × 8 | 1024–3584 flits |

## Results

Full tables are in `results/srota_eval/analysis/pareto/pareto_summary.md`,
with per-run BookSim logs in `results/srota_eval*/logs/`.

**Uniform traffic.** Zero-load latency is in cycles; peak throughput is
accepted pkt/node/cycle.

| topology | zero-load | storage | crosspoints | peak thr |
|---|---|---|---|---|
| fly4 | 16.5 | 1024 | 128 | 0.127 |
| cmesh16 | 17.1 | 1024 | 256 | 0.074 |
| flatfly16 | 19.3 | 3584 | 784 | 0.170 |
| **srota16** | 19.3 | 3584 | **448** | 0.166 |
| torus4x4 | 22.0 | 2560 | 400 | 0.159 |
| mesh4x4 | 24.8 | 2560 | 400 | 0.145 |
| **srota16_sb** | 26.3 | **576** | 448 | 0.064 |
| **srota16_xy** | 27.9 | **352** | 448 | 0.044 |

**Timeloop matrix** (`t3 timeloop`). Every topology saturates at the same
offered load, about 0.04, with peak throughput of about 0.024. The matrix's
memory-controller hotspot binds at ejection, whatever the fabric. So on
this workload the topologies differ only in latency, energy and storage.
Zero-load latency: cmesh16 15.5, fattree16 16.0, flatfly16 / srota16 18.1,
torus4x4 19.3, mesh4x4 23.5, srota16_sb 24.1, srota16_xy 24.3.

### What the numbers support

1. **MECS reach matches a flattened butterfly at 57 % of its crossbar.**
   On both workloads `srota16` equals `flatfly16` on hops, latency and
   energy proxy, within 2.5 % on throughput, with 448 crosspoints against
   784. That is the TOPO-003 §3.2 O(k)-versus-O(k²) wiring claim, visible
   at k=4. (Both have the same storage because both use 4 VC × 8 buffers.)
2. **The side-buffered router trades throughput for storage.** It needs
   less input storage than every other arm: 1.8–2.9× less than cmesh16 and
   fly4 (1024 flits), and 6–10× less than flatfly16 and srota16 (3584
   flits). That is why both
   side-buffer arms are Pareto-optimal. But peak uniform throughput is 0.044
   (XY, 1 VC) and 0.064 (O1TURN, 2 VCs), against 0.13–0.17 for the
   VC-buffered arms. The cause is the 2-flit staging window, not the side
   buffer. See the next section.
3. **Zero-load latency is 6–9 cycles above `srota16`** in the default
   pipeline (6 on the matrix, 7–8.6 on uniform), and 6–6.6 with
   `speculative=1`. A 5-flit packet streams
   through a 2-flit credit window, so it waits on credits even at zero load.

## Feature experiments (`scripts/srota_features.py`)

Plots are in `results/srota_eval/analysis/srota_features/`.

- **VC-R1, side-buffer depth** (`sidebuf_vcr1.png`, k=8 c=4). Depth 8 and
  depth 16 give identical results: peak occupancy is 7. Depth 4 is within
  noise; depth 1 turns away many losers but costs little throughput.
  Widening the staging window from 2 to 4 flits moves saturation from about
  0.03 to about 0.04. 8 flits goes past 0.04, but costs 3.5× the storage.
  **The staging window is the binding parameter, and VC-002 §13.6 fixes it
  at 2.**
- **Pipeline** (`pipeline_sensitivity.png`). The spec-like ST0/ST1/ST2
  (`speculative=1`) lifts `srota16_xy` saturation from about 0.043 to about
  0.048 and cuts zero-load latency by about 3.5 cycles. It does not close
  the gap to the VC-buffered arms (at least 0.10).
- **Planes** (`planes_isolation.png`). With control traffic on Plane C, its
  latency holds at about 20.5 cycles as data load rises from 0.005 to 0.04.
  Sharing Plane D is faster at light load (16.3 cycles, from MECS 2-hop
  reach) but climbs to 37 cycles. The crossover is near 0.02 data load.
- **QoS islands** (`qos_islands.png`). Unregulated, the critical tenant
  stays at 26–29 cycles up to 0.05 bulk load. With the bulk class capped
  (0.08 flits/cycle per island router), the critical tenant gets **worse**:
  65 cycles at 0.01, then unstable. The regulator itself behaves correctly
  (grants equal arrivals; only the capped class is deferred). But deferred
  bulk flits hold shared staging slots, and critical flits queue behind
  them. This is SROTA.md finding 6. As modeled, rate regulation needs
  per-class storage at the island, which VC-002 §6.3 says is unnecessary.

## Reproduce

```sh
# BookSim (inside the tools image so the binary runs on host and container)
podman run --rm -u $(id -u):$(id -g) -v "$PWD":/workspace \
  -w /workspace/third_party/booksim2/src ghcr.io/anmol-s314/veritx-tools-base:latest make -j
make tool-sync TOOL=booksim2
(cd third_party/booksim2/src && python3 srota_validate.py)     # 29 checks

cd tracks/t3-topology && source run/env.sh
B=$REPO_ROOT/third_party/booksim2/src/booksim
CONFIG=srota_eval BOOKSIM_BIN=$B BOOKSIM_EXTRA="use_noc_latency=0" t3 timeloop
CONFIG=srota_eval_uniform RATES="0.01,0.03,0.05,0.08,0.11,0.14,0.18" \
  BOOKSIM_BIN=$B BOOKSIM_EXTRA="use_noc_latency=0" t3 sim
CONFIG=srota_eval_specpipe TRAFFIC_MATRIX=results/traffic_matrix.txt \
  RATES="0.002,0.005,0.01,0.02,0.04,0.05" \
  BOOKSIM_BIN=$B BOOKSIM_EXTRA="use_noc_latency=0 speculative=1" t3 sim
CONFIG=srota_eval t3 all
CONFIG=srota_eval t3 pareto \
  --sweep results/srota_eval/topology_sweep.json \
  --sweep results/srota_eval_uniform/topology_sweep.json \
  --sweep results/srota_eval_specpipe/topology_sweep.json \
  --labels timeloop_matrix,uniform,matrix_spec_pipeline
CONFIG=srota_eval python3 scripts/srota_features.py
```

`BOOKSIM_BIN` matters. The tools image bakes in a BookSim built before Srota
existed, and `t3` now forwards a workspace build into the container.
