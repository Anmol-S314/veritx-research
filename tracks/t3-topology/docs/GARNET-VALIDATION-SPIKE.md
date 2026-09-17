# Garnet Validation Spike — scoping fabric cross-check in gem5

**Question:** can Garnet validate our BookSim topology rankings, and what does it cost?
**Verdict up front:** yes, via **Garnet standalone** (synthetic, no cores) — *not* full-system
gem5. Our tiles are message-passing (compute_tile + HBM, collectives), so cache
coherence — the main thing full-system buys — is irrelevant to this track. The spike is
1–2 days, not weeks. Torus needs a ~30-line topology file; everything else maps or is
documented below as unmappable.

All claims below verified against gem5 `stable` (v25.1) source on 2026-09-10. File links
are `stable`-pinned.

---

## 1. Which gem5 vehicle (and why not full-system)

- **Garnet standalone** exists as a first-class build: `build_opts/Garnet_standalone`
  (`RUBY=y`, `PROTOCOL="Garnet_standalone"`,
  `RUBY_PROTOCOL_Garnet_standalone=y`) with its own protocol
  (`src/mem/ruby/protocol/Garnet_standalone.{slicc,cache,dir,msg}.sm`) and driver script
  (`configs/example/garnet_synth_traffic.py`, Tushar Krishna). Synthetic traffic generators
  (`GarnetSyntheticTraffic`) replace CPU cores. No ISA, no OS, no checkpoints.
- **Full-system is the wrong tool here.** It buys coherence (Ruby MESI/MOESI), caches, DRAM
  controllers, and OS effects. Our workload model has none of those: tiles exchange explicit
  collectives through HBM controllers. Nothing in our pipeline would exercise a coherence
  protocol, so full-system adds 10–100x slowdown for zero additional signal. Revisit only if
  the tile model ever gains coherent caches.

## 2. Version + build

- **Version: v25.1** (latest stable tag; tags API, 2026-09-10).
- Build: `scons build/Garnet_standalone/gem5.opt -j$(nproc)` (TO-VERIFY: exact target name on
  first run; `build_opts/Garnet_standalone` is the source of truth).
- Cost estimate: 30–60 min wall on 12 cores, ~15 GB disk. We have 88 GB free, 12 cores.
  No gem5 checkout exists on this machine yet; clone is ~1–2 GB.
- Garnet here is **Garnet3.0** (`src/mem/ruby/network/garnet/README.txt`, 2020) — detailed
  5-stage router pipeline (InputUnit, SwitchAllocator, CrossbarSwitch, OutputUnits),
  credit flow control, per-link latencies. Deeper router model than BookSim's, same physics.

## 3. Topology mapping (ours → gem5 stock)

Stock files: `configs/topologies/` = BaseTopology, Cluster, Crossbar, CrossbarGarnet,
CustomMesh, MeshDirCorners_XY, Mesh_westfirst, Mesh_XY, Pt2Pt. **There is no torus, fattree,
dragonfly, flatfly, cmesh, or express-link topology upstream.**

| Ours (13 presets) | gem5 stock | Mapping |
|---|---|---|
| mesh_4x4 / mesh_8x8 | `Mesh_XY` (`--mesh-rows 4/8`) | ✅ direct |
| torus_8x8 | ✗ missing | write it: `Mesh_XY` + wraparound links (~30 lines, link-weight deadlock freedom as in `Mesh_westfirst.py`) |
| fattree_k4n3 / qtree_64 / tree4_64 | ✗ missing | needs new file(s); trees are straightforward (parent/child links) |
| flatfly_64 / cmesh_64 / fbfly_64 | ✗ missing | needs new files; moderate (concentration + link classes) |
| gec_* / dragonfly_72 | ✗ missing | needs new files; express/tap/global links are real work — skip unless GEC becomes the winner |
| anynet winners (grpo_best etc.) | ✗ | no generic importer; hand-translate or skip |

Practical consequence: **phase 1 validates mesh only; torus needs one small file.** That covers
our headline result (mesh vs torus on qwen3) with ~1 hour of topology work.

## 4. Traffic mapping (the real gap)

`garnet_synth_traffic.py` offers exactly: `uniform_random, tornado, bit_complement,
bit_reverse, bit_rotation, neighbor, shuffle, transpose` (+ `--single-sender-id`,
`--single-dest-id`, `--inj-vnet`). Consequences:

- **Our traces do not replay.** No timestamped injection, no scripted patterns, no 4-node
  ring. The injector (`src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.py`)
  draws Bernoulli per cycle at `--injectionrate`.
- **Our 64-flit packets do not fit.** Message size is hardcoded per vnet: vnets 0/1 = 1 flit,
  vnet 2 = 5 flits. Bulk-packet serialization effects (the torus-vs-mesh gap driver) cannot
  be expressed stock.
- Closest honest experiment: `uniform_random` saturation sweep (latency vs injection rate)
  on Mesh_XY 8x8 vs torus-file 8x8. This answers "which fabric saturates later" — a *different
  question* than "which is faster on MoE trace replay." Treat Garnet as an independent
  measurement, not a reproduction: agreement on ordering = confidence, not equality.
- Custom MoE-pattern injector (4-node ring, bursty, 64-flit) = extend `GarnetSyntheticTraffic`
  (C++ + Python params). Estimate: 1–3 days for someone who knows the codebase, most of it
  learning where injection decisions live. Defer until phase-1 ordering disagrees with BookSim.

## 5. Routing mapping

`--routing-algorithm` (`configs/network/Network.py`): `0` weight-table, `1` XY (mesh only,
`RoutingUnit.cc`), `2` Custom. Consequences:

- `dim_order` → XY(1). ✅ (`Mesh_XY.py` + XY is the canonical pairing.)
- `min_adapt` / `ran_min` → **no equivalent.** Adaptive is a Custom(2) implementation task.
  Our mesh_8x8 result *uses* min_adapt — Garnet can only check its dim_order shadow, or
  someone writes adaptive routing.
- torus dim_order → XY+wrap in the new torus file (same link-weight trick as Mesh_westfirst).
- `dest_tag` (fly), `dor_cmesh`, `nca` (trees), `min` (dragonfly): only fly/dragonfly map to
  anything if those topology files get written; express/tap routings have no counterpart.

## 6. Parameter calibration (must-match list)

| Ours (BookSim cfg) | Garnet flag/param | Match? |
|---|---|---|
| `num_vcs = 4` | `--vcs-per-vnet 4` (default) | ✅ |
| `vc_buf_size = 8` | `buffers_per_data_vc` (default **4**) | ⚠️ set explicitly |
| router pipeline | `--router-latency` (default 1) | ⚠️ calibrate to BookSim's alloc delays |
| link latency 1c | `--link-latency` (default 1) | ✅ |
| 64 B packets / 8 flits | `ni_flit_size` (default 16 B) + fixed 1/5-flit vnets | ⚠️ width math won't close; document the assumed flit size |
| ruby clock | `--ruby-clock` (default 2 GHz) | ⚠️ define cycle = 1 ruby tick, state it |
| drain verdict / timeouts | `--garnet-deadlock-threshold` (default 50000) | ⚠️ different semantics (watchdog vs drain proof); a Garnet deadlock-trip ≈ our UNSTABLE flag, treat as fail, not data |
| fault model | `--network-fault-model` | off; parity with BookSim (no faults) |

## 7. What breaks in translation (checklist for the spike runner)

1. Torus file missing → write `Torus_XY.py` first (blocks the headline comparison).
2. uniform_random ≠ MoE trace → saturation ordering only, never latency equality.
3. 64-flit bulk unrepresentable → the torus-vs-mesh gap mechanism can't transfer; expect
   *smaller* gaps in Garnet and do not read that as contradiction.
4. min_adapt unmappable → compare dim_order-vs-dim_order shadows, or write Custom adaptive.
5. Buffer/router/flit-width calibration (table above) must be written down per run or the
   numbers are incomparable across engines.
6. Build cost is one-time (~1 h incl. clone); per-run cost is minutes for 64 nodes
   (Garnet standalone is slower than BookSim per cycle but these are small fabrics).

## 8. Spike plan (phases with exit criteria)

- **Phase 0 — build + smoke (0.5 day).** Clone v25.1, `scons build/Garnet_standalone/gem5.opt`,
  run stock `garnet_synth_traffic.py --n 64 --topology Mesh_XY --mesh-rows 8 --synthetic
  uniform_random` saturation curve. Exit: curve monotonic, matches BookSim mesh_8x8
  saturation point within ~2x (different engines — ordering/scale, not equality).
- **Phase 1 — torus file + headline check (0.5 day).** Write `Torus_XY.py`, XY+wrap routing,
  same sweep. Exit: mesh-vs-torus ordering agrees with our honest ranking (mesh wins
  below saturation). If it disagrees → investigate, do not dismiss (that's the value).
- **Phase 2 — custom injector (only if phase 1 disagrees).** MoE-ring + bursty + bulk in
  `GarnetSyntheticTraffic`. Estimate 1–3 days. Re-run phase 1 with pattern parity.
- **No full-system phase.** Not needed for message-passing tiles; revisit iff the tile model
  gains coherent caches (then: MOESI_AMD_Base or MESI_Two_Level + real LLC/DRAM sizing —
  separate spike).

## Sources (all primary, gem5 `stable` @ v25.1, fetched 2026-09-10)

- Tags: `api.github.com/repos/gem5/gem5/tags` → v25.1 latest.
- `configs/example/garnet_synth_traffic.py` — driver, synthetic choices, injector params.
- `configs/topologies/` listing — available topologies (no torus/fattree/dragonfly).
- `configs/topologies/CustomMesh.py`, `MeshDirCorners_XY.py` — link-weight deadlock freedom pattern.
- `configs/network/Network.py` — `--topology/--mesh-rows/--network/--router-latency/--link-latency/--link-width-bits/--vcs-per-vnet/--routing-algorithm/--garnet-deadlock-threshold` flags + defaults.
- `configs/ruby/Ruby.py` (`create_topology`, `--ruby-clock`) — topology wiring.
- `src/mem/ruby/network/garnet/GarnetNetwork.py` — `vcs_per_vnet=4`, `buffers_per_data_vc=4`, routing enum 0/1/2, deadlock threshold 50000.
- `src/mem/ruby/network/garnet/README.txt` — Garnet3.0 pipeline, NI/link/router wakeup model, NI trace-capture hook.
- `src/cpu/testers/garnet_synthetic_traffic/GarnetSyntheticTraffic.py` — 1-flit/5-flit vnet sizes.
- `src/mem/ruby/protocol/` listing — `Garnet_standalone.{slicc,…}` + full-system alternatives.
- `build_opts/Garnet_standalone`, `build_opts/NULL` — build configuration.
- `src/mem/ruby/network/garnet/RoutingUnit.{cc,hh}` + `routefunc`-side registrations (`dest_tag_fly`, `dor_cmesh`, `nca_*`, `min/ugal_dragonflynew`) — routing support inventory.
