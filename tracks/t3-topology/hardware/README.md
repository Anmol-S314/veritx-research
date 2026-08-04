# T3 — Tenstorrent NoC hardware experiments

**Status: first experiment code-complete, NOT yet run on silicon.** The `.cpp` here is
grounded in the current tt-metal API and checked against the upstream sources (host:
`MeshDevice`/`EnqueueMeshWorkload`; kernel: `noc_async_write_multicast` +
`get_noc_multicast_addr`, both verified against tt-metal `main` docs/headers) but has
**not been compiled on a board**. It is the seed for the on-silicon measurement of the
K/V-multicast assumption that the whole "5.4× decode" result rests on. Spots needing a
live-card check are tagged `// VERIFY:` and listed in the punch-list below.

---

## The experiment: is NoC multicast actually ~flat in fanout?

`serving_multicast.py` / `schedule.py` assume a multicast delivers a buffer to `N` cores
by crossing the bottleneck **once** — so **wall-time per multicast is ~flat in N** and
delivered bandwidth (`N × size / time`) grows ~linearly. That assumption is the entire
basis for "multicast beats re-fetching KV." **It has never been checked on silicon.**
BookSim can't simulate multicast at all. Tenstorrent's NoC does it natively.

`noc_multicast_bw.cpp` measures it directly: one sender core pulls a payload into L1, then
`noc_async_write_multicast`s it to a block of 1 / 3 / 8 destination cores, `REPEAT` times.
Sweep size; read the shape:

- **wall-time-per-multicast flat in N** → the roofline assumption holds; multicast is a
  real bandwidth lever → the 5.4× story survives.
- **wall-time grows ~linearly in N** → multicast degenerates toward a serial unicast loop
  here, and the "multicast is ~free" premise fails on real hardware. Either outcome is a result.

## Run it (Tenstorrent cloud / Koyeb n300)

```bash
# 1. Rent a card (Koyeb TT-N300S instance; TT-LoudBox 4x mesh also works — needs the multi-device edits).
# 2. Install the SDK (once):
git clone https://github.com/tenstorrent/tt-metal.git --recurse-submodules
cd tt-metal && ./build_metal.sh           # sets up TT_METAL_HOME + build/
export TT_METAL_HOME=$PWD
cd -
# 3. Build + run (from the repo root):
make -C tracks/t3-topology hw
# or directly:
cd tracks/t3-topology/hardware && ./build.sh && ./noc_multicast_bw
```

`make hw` is **deliberately not** wired into `setup`/`lint`/`test`, so the hardware-less CI
matrix never touches it.

## How the build works (why it's not a fresh cmake project)

The microbench is dropped into tt-metal's existing example tree and registered as a
subdirectory (the same way `eltwise_binary` is): `build.sh` symlinks this dir into
`$TT_METAL_HOME/tt_metal/programming_examples/noc_multicast_bw`, idempotently appends
`add_subdirectory(.../noc_multicast_bw)` to that CMakeLists, and builds `cmake --build build
--target noc_multicast_bw`. TT-metal's CMake is *not* a glob; skipping the
`add_subdirectory` registration (as an earlier draft assumed) means the example never gets
compiled. The `CMakeLists.txt` here mirrors `eltwise_binary`'s (`TT::Metalium`, PCH reuse).
Binary lands at `build/programming_examples/noc_multicast_bw` (their
`CMAKE_RUNTIME_OUTPUT_DIRECTORY`).

## Coordinates & geometry (this is the subtle part)

`get_noc_multicast_addr(x_s, y_s, x_e, y_e, addr)` takes **physical NoC coordinates**, and
Wormhole's NoC grid has holes: cols {0,5} (ARC / 18 DRAM endpoints) and rows {0,6}
(Ethernet) are not Tensix. A multicast rectangle spanning those holes would try to write
L1 to DRAM/Ethernet nodes. The host therefore:
- places the sender at **logical {0,0}** (physical {1,1}),
- sweeps **S×S blocks anchored at the sender**, `S ∈ {1,2,3}` → fanout `{1,3,8}`,
- keeps the physical rect inside cols 1..4 × rows 1..4 (no holes),
- translates to physical via `MeshDevice::worker_core_from_logical_core()` (the API also
  exists on `Device`), and only physical coords reach the kernel.

Fanout 8 isn't a magic ceiling: the left/right 5..9 halves are each hole-free rects, so a
future revision can fan wider by issuing two multicast writes (SEC: hard-wired in
`kernels/dataflow/mcast_sender.cpp`). Today's sweep is enough to see the shape.

## Truth-on-the-fence / remaining `// VERIFY:` items

1. **`L1_SCRATCH = 128 KiB`** — must sit above the DM kernel's data region on WH and below
   any other use. If it overlaps a kernel buffer the mcast write will scribble into the
   sender's own state. Kernel stack + data sit at the top of L1; 128 KiB is historically
   `L1_UNRESERVED_BASE`-ish on WH, but confirm with `hal` / `dev_addr` before trusting.
2. **DRAM bank 0** — `get_noc_addr_from_bank_id<true>(0, addr)` assumes the replicated
   mesh buffer allocates into bank 0. For ≤64 KiB it does on WH; confirm the buffer's
   `address()` + bank map if patterns shift.
3. **Multicast VC / path reserve** — the shot uses default VC (`NOC_MULTICAST_WRITE_VC`).
   If the sweep shows unexpected saturation at N=3, retry with `linked=true` writes.
4. **Host timing** — `chrono` around `Finish` includes program dispatch. `REPEAT=1000`
   amortises it; the *shape* survives a fixed offset, the absolute GB/s doesn't. Cross-check
   one point with the tt-metal profiler (Tracy) before quoting absolute numbers.
5. **Buffer address args** — `src->address()` passes the *local* DRAM address; a real
   multi-device mesh would need it shard-local. Unit mesh is fine: replicate as-is.

## What to do with the numbers

Record `noc_multicast_bw.out` + the `// VERIFY` resolutions in `docs/progress-tracking/` and
feed verdict: if wall-time is flat (within noise) in dests up to 8, the `schedule.py`/
`serving_multicast.py` multicast premise gets its first silicon check and the 5.4× stays
credible as a *bandwidth ceiling*; if it isn't, that's an even more important negative
result — write it up and demote the 5.4× claim accordingly.